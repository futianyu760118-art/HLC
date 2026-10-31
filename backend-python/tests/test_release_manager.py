from __future__ import annotations

from pathlib import Path
import hashlib
import importlib
import json
import os
import stat

import pytest

from ops.operation_common import OperationSafetyError
from ops.operation_common import CommandResult
from ops.release_bundle import (
    ReleaseManifest,
    build_release_archive,
    capture_workspace_files,
)
from ops.release_manager import (
    DockerReleaseActions,
    InstalledRelease,
    ServerLayout,
    apply_installed_release,
    bootstrap_legacy_layout,
    read_release_status,
    rollback_release,
    write_installed_release_metadata,
    verify_and_install_release,
)


RELEASE_ID = '20260715T120000Z'


def test_compose_image_id_accepts_full_hex_without_sha256_prefix():
    from ops import release_manager

    digest = 'a' * 64

    assert release_manager._normalize_compose_image_id(digest) == f'sha256:{digest}'
    assert (
        release_manager._normalize_compose_image_id(f'sha256:{digest}')
        == f'sha256:{digest}'
    )


class BootstrapImageProofRunner:
    def run(self, argv, **_kwargs):
        call = tuple(argv)
        if 'images' in call:
            return CommandResult(call, 0, 'not-an-image-id\n', '')
        raise AssertionError(call)


def test_failed_bootstrap_image_proof_does_not_copy_shared_runtime(tmp_path):
    source = tmp_path / 'legacy-app'
    source.mkdir()
    for filename, payload in (
        ('.env', 'DB_NAME=hrm_saas\n'),
        ('docker-compose.yml', 'services: {}\n'),
        ('docker-compose.saas-preview.yml', 'services: {}\n'),
        ('nginx-docker.conf', 'events {}\n'),
    ):
        (source / filename).write_text(payload, encoding='utf-8')
    (source / 'certs').mkdir()
    (source / 'certs' / 'server.crt').write_text('certificate', encoding='ascii')
    uploads = source / 'backend-python' / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'fixture.txt').write_text('upload', encoding='ascii')
    override = tmp_path / 'docker-compose.release.yml'
    override.write_text('services: {}\n', encoding='utf-8')
    layout = ServerLayout(tmp_path / 'deployment')

    with pytest.raises(OperationSafetyError, match='cannot be proved'):
        bootstrap_legacy_layout(
            layout,
            legacy_app_root=source,
            release_override_source=override,
            runner=BootstrapImageProofRunner(),
        )

    assert not layout.environment_path.exists()
    assert list(layout.certs_root.iterdir()) == []
    assert list(layout.uploads_root.iterdir()) == []


def test_bootstrap_reuses_only_an_exact_failed_runtime_copy(tmp_path):
    from ops import release_manager

    source = tmp_path / 'legacy-app'
    source.mkdir()
    (source / '.env').write_bytes(b'DB_NAME=hrm_saas\n')
    (source / 'certs').mkdir()
    (source / 'certs' / 'server.crt').write_bytes(b'certificate')
    uploads = source / 'backend-python' / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'fixture.txt').write_bytes(b'upload')
    layout = ServerLayout(tmp_path / 'deployment')
    layout.ensure_directories()
    layout.environment_path.write_bytes((source / '.env').read_bytes())
    (layout.certs_root / 'server.crt').write_bytes(b'certificate')
    (layout.uploads_root / 'fixture.txt').write_bytes(b'upload')

    assert release_manager._copy_or_validate_legacy_runtime(layout, source) == 'reused'

    (layout.uploads_root / 'fixture.txt').write_bytes(b'changed')
    with pytest.raises(OperationSafetyError, match='does not match'):
        release_manager._copy_or_validate_legacy_runtime(layout, source)


def test_server_layout_keeps_runtime_state_under_shared(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()

    assert layout.shared_root == tmp_path / 'shared'
    assert layout.environment_path == tmp_path / 'shared' / '.env'
    assert layout.certs_root == tmp_path / 'shared' / 'certs'
    assert layout.uploads_root == tmp_path / 'shared' / 'uploads'
    assert layout.locks_root == tmp_path / 'shared' / 'locks'
    assert layout.state_root == tmp_path / 'shared' / 'state'
    assert layout.releases_root == tmp_path / 'releases'
    assert layout.current_link == tmp_path / 'current'
    assert layout.incoming_root == tmp_path / 'incoming'
    for directory in (
        layout.shared_root,
        layout.certs_root,
        layout.uploads_root,
        layout.locks_root,
        layout.state_root,
        layout.releases_root,
        layout.incoming_root,
    ):
        assert directory.is_dir()
    assert not layout.environment_path.exists()


def test_release_compose_uses_image_tag_and_never_contains_build():
    root = Path(__file__).resolve().parents[2]
    payload = (root / 'docker-compose.release.yml').read_text(encoding='utf-8')

    assert 'HPT_BACKEND_IMAGE' in payload
    assert 'HPT_SHARED_ROOT' in payload
    assert 'build:' not in payload
    assert '/app/uploads' in payload
    assert '/etc/nginx/certs' in payload


def test_release_directory_is_new_and_never_overwritten(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()

    release = layout.create_release_directory(RELEASE_ID)
    assert release == tmp_path / 'releases' / RELEASE_ID
    assert release.is_dir()
    with pytest.raises(FileExistsError):
        layout.create_release_directory(RELEASE_ID)


class FakeReleaseActions:
    def __init__(self, *, fail_release=None):
        self.fail_release = fail_release
        self.events = []

    def recreate_backend_and_nginx(self, release):
        self.events.append(('recreate', release.release_id, ('backend', 'nginx')))

    def validate_release(self, release):
        self.events.append(('validate', release.release_id))
        if release.release_id == self.fail_release:
            raise RuntimeError('simulated release health failure')

    def read_health(self, release):
        self.events.append(('health', release.release_id))
        return {'apiHealth': True, 'apiReady': True}


def _installed(layout, release_id):
    release_root = layout.create_release_directory(release_id)
    app_root = release_root / 'app'
    app_root.mkdir()
    installed = InstalledRelease(
        release_id=release_id,
        release_root=release_root,
        app_root=app_root,
        backend_image=f'hengpintong-saas-backend:{release_id}',
        backend_digest='sha256:' + 'a' * 64,
    )
    write_installed_release_metadata(installed)
    return installed


def _point_current(layout, installed):
    try:
        layout.current_link.symlink_to(installed.app_root, target_is_directory=True)
    except OSError:
        pytest.skip('current Windows account cannot create directory symlinks')


def test_apply_switches_current_then_recreates_only_backend_and_nginx(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()
    previous = _installed(layout, '20260715T110000Z')
    incoming = _installed(layout, RELEASE_ID)
    _point_current(layout, previous)
    actions = FakeReleaseActions()

    state = apply_installed_release(layout, incoming, actions=actions)

    assert layout.current_link.resolve() == incoming.app_root.resolve()
    assert state.current.release_id == RELEASE_ID
    assert state.previous.release_id == '20260715T110000Z'
    assert actions.events == [
        ('recreate', RELEASE_ID, ('backend', 'nginx')),
        ('validate', RELEASE_ID),
    ]


def test_failed_health_restores_previous_symlink_and_containers(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()
    previous = _installed(layout, '20260715T110000Z')
    incoming = _installed(layout, RELEASE_ID)
    _point_current(layout, previous)
    actions = FakeReleaseActions(fail_release=RELEASE_ID)

    with pytest.raises(OperationSafetyError, match='restored previous release'):
        apply_installed_release(layout, incoming, actions=actions)

    assert layout.current_link.resolve() == previous.app_root.resolve()
    assert incoming.release_root.is_dir()
    assert actions.events == [
        ('recreate', RELEASE_ID, ('backend', 'nginx')),
        ('validate', RELEASE_ID),
        ('recreate', '20260715T110000Z', ('backend', 'nginx')),
        ('validate', '20260715T110000Z'),
    ]


def test_manual_rollback_keeps_failed_release_and_swaps_state(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()
    previous = _installed(layout, '20260715T110000Z')
    current = _installed(layout, RELEASE_ID)
    _point_current(layout, previous)
    apply_installed_release(layout, current, actions=FakeReleaseActions())
    actions = FakeReleaseActions()

    state = rollback_release(layout, actions=actions)

    assert layout.current_link.resolve() == previous.app_root.resolve()
    assert current.release_root.is_dir()
    assert state.current.release_id == previous.release_id
    assert state.previous.release_id == current.release_id
    assert actions.events == [
        ('recreate', previous.release_id, ('backend', 'nginx')),
        ('validate', previous.release_id),
    ]


def test_status_is_read_only_and_reports_release_image_and_health(tmp_path):
    layout = ServerLayout(tmp_path)
    layout.ensure_directories()
    previous = _installed(layout, '20260715T110000Z')
    current = _installed(layout, RELEASE_ID)
    _point_current(layout, previous)
    apply_installed_release(layout, current, actions=FakeReleaseActions())
    actions = FakeReleaseActions()
    before_target = layout.current_link.resolve()

    status = read_release_status(layout, actions=actions)

    assert status['current']['releaseId'] == RELEASE_ID
    assert status['current']['backendImage'].endswith(RELEASE_ID)
    assert status['health'] == {'apiHealth': True, 'apiReady': True}
    assert layout.current_link.resolve() == before_target
    assert actions.events == [('health', RELEASE_ID)]


def _release_package(tmp_path, *, release_id=RELEASE_ID):
    staging = tmp_path / f'staging-{release_id}'
    (staging / 'app').mkdir(parents=True)
    (staging / 'images').mkdir()
    (staging / 'app' / 'dist-prod' / 'assets').mkdir(parents=True)
    (staging / 'app' / 'dist-prod' / 'index.html').write_text('<main>ok</main>')
    (staging / 'app' / 'dist-prod' / 'assets' / 'app.js').write_text('ok();')
    (staging / 'app' / 'docker-compose.yml').write_text('services: {}\n')
    (staging / 'app' / 'docker-compose.saas-preview.yml').write_text(
        'services: {}\n'
    )
    (staging / 'app' / 'docker-compose.release.yml').write_text(
        'services: {}\n'
    )
    (staging / 'images' / 'backend-image.tar').write_bytes(b'image-tar')
    payload = capture_workspace_files(
        staging,
        (
            'app/docker-compose.release.yml',
            'app/docker-compose.saas-preview.yml',
            'app/docker-compose.yml',
            'app/dist-prod/index.html',
            'app/dist-prod/assets/app.js',
            'images/backend-image.tar',
        ),
    )
    manifest = ReleaseManifest(
        release_id=release_id,
        architecture='linux/amd64',
        backend_image=f'hengpintong-saas-backend:{release_id}',
        backend_digest='sha256:' + 'b' * 64,
        payload=payload,
    )
    archive = tmp_path / f'release-{release_id}.zip'
    built = build_release_archive(
        staging_root=staging,
        archive_path=archive,
        manifest=manifest,
    )
    return built, manifest


class ImageRunner:
    def __init__(self, digest='sha256:' + 'b' * 64):
        self.digest = digest
        self.calls = []

    def run(self, argv, **kwargs):
        call = tuple(argv)
        self.calls.append((call, kwargs))
        stdout = ''
        if call[:3] == ('docker', 'image', 'inspect'):
            stdout = f'{self.digest}|linux|amd64\n'
        return CommandResult(call, 0, stdout, '')


def test_install_loads_image_before_switch_and_backs_up_active_state(tmp_path):
    layout = ServerLayout(tmp_path / 'deployment')
    layout.ensure_directories()
    layout.release_state_path.write_text('{"old":true}\n')
    built, manifest = _release_package(tmp_path)
    runner = ImageRunner()

    installed = verify_and_install_release(
        layout,
        archive_path=built.archive_path,
        sidecar_path=built.sha256_path,
        runner=runner,
        current_release_id='20260715T110000Z',
        available_bytes=10 * 1024 * 1024,
    )

    assert installed.release_id == RELEASE_ID
    assert installed.backend_digest == manifest.backend_digest
    assert installed.app_root.is_dir()
    assert installed.metadata_path.is_file()
    assert layout.current_link.exists() is False
    commands = [call for call, _kwargs in runner.calls]
    assert commands[0][:2] == ('docker', 'load')
    assert commands[1][:3] == ('docker', 'image', 'inspect')
    backup = layout.state_root / 'backups' / f'before-{RELEASE_ID}.json'
    assert backup.read_text() == '{"old":true}\n'


def test_install_makes_release_directories_traversable_for_nginx(tmp_path):
    layout = ServerLayout(tmp_path / 'deployment')
    layout.ensure_directories()
    built, _manifest = _release_package(tmp_path)

    installed = verify_and_install_release(
        layout,
        archive_path=built.archive_path,
        sidecar_path=built.sha256_path,
        runner=ImageRunner(),
        current_release_id=None,
        available_bytes=10 * 1024 * 1024,
    )

    for directory in (
        layout.releases_root,
        installed.release_root,
        installed.app_root,
        installed.app_root / 'dist-prod',
        installed.app_root / 'dist-prod' / 'assets',
    ):
        assert stat.S_IMODE(directory.stat().st_mode) & 0o555 == 0o555
    if os.name != 'nt':
        assert stat.S_IMODE(
            (installed.app_root / 'dist-prod' / 'index.html').stat().st_mode
        ) == 0o644


class SuccessfulCommandRunner:
    def run(self, argv, **_kwargs):
        return CommandResult(tuple(argv), 0, '', '')


def test_release_recreation_allows_unhealthy_exact_project_for_recovery(
    tmp_path,
    monkeypatch,
):
    from ops import legacy_snapshot

    layout = ServerLayout(tmp_path)
    layout.ensure_directories()
    release = _installed(layout, RELEASE_ID)
    observed = []

    def prove(_runner, *, project, docker_command, require_healthy):
        observed.append((project, docker_command, require_healthy))

    monkeypatch.setattr(legacy_snapshot, 'prove_source_project', prove)
    DockerReleaseActions(
        layout=layout,
        runner=SuccessfulCommandRunner(),
    ).recreate_backend_and_nginx(release)

    assert observed == [('hengpintong-saas-preview', 'docker', False)]


@pytest.mark.parametrize('failure', ('hash', 'order', 'disk', 'digest'))
def test_apply_rejects_hash_release_order_disk_and_digest_failures(
    tmp_path,
    failure,
):
    layout = ServerLayout(tmp_path / 'deployment')
    layout.ensure_directories()
    built, _manifest = _release_package(tmp_path)
    current_release = '20260715T130000Z' if failure == 'order' else None
    available = 0 if failure == 'disk' else 10 * 1024 * 1024
    runner = ImageRunner(
        digest=('sha256:' + 'c' * 64) if failure == 'digest' else ('sha256:' + 'b' * 64)
    )
    if failure == 'hash':
        built.sha256_path.write_text(
            f"{'0' * 64}  {built.archive_path.name}\n",
            encoding='ascii',
        )

    with pytest.raises(OperationSafetyError):
        verify_and_install_release(
            layout,
            archive_path=built.archive_path,
            sidecar_path=built.sha256_path,
            runner=runner,
            current_release_id=current_release,
            available_bytes=available,
        )

    if failure in {'hash', 'order', 'disk'}:
        assert runner.calls == []
    assert not layout.release_root(RELEASE_ID).exists() or failure == 'digest'


def test_apply_never_invokes_server_build_or_package_managers(tmp_path):
    layout = ServerLayout(tmp_path / 'deployment')
    layout.ensure_directories()
    built, _manifest = _release_package(tmp_path)
    runner = ImageRunner()

    verify_and_install_release(
        layout,
        archive_path=built.archive_path,
        sidecar_path=built.sha256_path,
        runner=runner,
        current_release_id=None,
        available_bytes=10 * 1024 * 1024,
    )

    serialized = ' '.join(' '.join(call) for call, _kwargs in runner.calls)
    for forbidden in ('apt ', 'pip ', 'npm ', 'vite ', 'docker build'):
        assert forbidden not in serialized


def test_release_cli_and_launcher_expose_bootstrap_apply_status_rollback():
    cli = importlib.import_module('scripts.hpt_release')
    apply_args = cli.parse_args(['apply', '/tmp/release.zip'])
    assert apply_args.command == 'apply'
    assert apply_args.archive == Path('/tmp/release.zip')
    bootstrap = cli.parse_args(['bootstrap', '/opt/legacy-app'])
    assert bootstrap.command == 'bootstrap'

    launcher = Path(__file__).resolve().parents[2] / 'hpt-release.sh'
    payload = launcher.read_text(encoding='ascii')
    assert 'id -u' in payload
    assert 'umask 077' in payload
    assert 'hpt_release.py' in payload
    assert 'eval ' not in payload
