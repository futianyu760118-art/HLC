from __future__ import annotations

import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
import stat
import warnings
import zipfile

import pytest

from ops.operation_common import OperationSafetyError
from ops.server_migration import (
    OperationLock,
    DockerSwitchActions,
    PrepareConfig,
    PreparedMigrationState,
    build_prepare_plan,
    clear_stale_operation_lock,
    execute_prepare,
    load_prepared_state,
    peek_snapshot_id,
    promote_candidate,
    rollback_candidate,
    verify_snapshot_package,
    verify_outer_package_hash,
    write_prepared_state,
)
from ops.server_prepare import ServerPrepareActions


SNAPSHOT_ID = '20260715T102030Z'
PACKAGE_HASH = 'a' * 64


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_snapshot_package(
    tmp_path: Path,
    *,
    extra_members: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None,
    bad_inner_hash: bool = False,
    bad_outer_hash: bool = False,
) -> tuple[Path, Path]:
    archive_path = tmp_path / 'snapshot.zip'
    members = {
        'legacy-full.sql': b'SELECT 1;\n',
        'snapshot-manifest.json': json.dumps(
            {'snapshotId': SNAPSHOT_ID},
            sort_keys=True,
        ).encode('ascii'),
    }
    checksum_rows = []
    for name, payload in sorted(members.items()):
        digest = '0' * 64 if bad_inner_hash and name == 'legacy-full.sql' else _sha256(payload)
        checksum_rows.append(f'{digest}  {name}\n')

    with zipfile.ZipFile(archive_path, 'w', allowZip64=True) as archive:
        for name, payload in sorted(members.items()):
            archive.writestr(f'first-tenant-snapshot/{name}', payload)
        archive.writestr(
            'first-tenant-snapshot/SHA256SUMS',
            ''.join(checksum_rows).encode('ascii'),
        )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                'ignore',
                message='Duplicate name:',
                category=UserWarning,
            )
            for name, payload in extra_members or []:
                archive.writestr(name, payload)

    outer_hash = 'f' * 64 if bad_outer_hash else _sha256(archive_path.read_bytes())
    sidecar_path = archive_path.with_name(archive_path.name + '.sha256')
    sidecar_path.write_text(
        f'{outer_hash}  {archive_path.name}\n',
        encoding='ascii',
    )
    return archive_path, sidecar_path


def test_verify_snapshot_package_extracts_only_hash_verified_members(tmp_path):
    archive_path, sidecar_path = _write_snapshot_package(tmp_path)
    extraction_root = tmp_path / 'extracted'

    assert peek_snapshot_id(archive_path) == SNAPSHOT_ID
    assert verify_outer_package_hash(archive_path, sidecar_path) == _sha256(
        archive_path.read_bytes()
    )
    verified = verify_snapshot_package(
        archive_path,
        sidecar_path=sidecar_path,
        extraction_root=extraction_root,
    )

    assert verified.snapshot_id == SNAPSHOT_ID
    assert verified.package_sha256 == _sha256(archive_path.read_bytes())
    assert verified.file_count == 2
    assert verified.snapshot_root == extraction_root / 'first-tenant-snapshot'
    assert (verified.snapshot_root / 'legacy-full.sql').read_bytes() == b'SELECT 1;\n'
    assert not (verified.snapshot_root / 'SHA256SUMS').is_symlink()


def _symlink_member(name: str) -> zipfile.ZipInfo:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    return member


@pytest.mark.parametrize(
    'package_options, match',
    (
        ({'bad_outer_hash': True}, 'outer SHA-256'),
        ({'bad_inner_hash': True}, 'SHA256SUMS'),
        (
            {
                'extra_members': [
                    ('first-tenant-snapshot/../escape.txt', b'escape')
                ]
            },
            'archive member',
        ),
        (
            {
                'extra_members': [
                    (
                        _symlink_member(
                            'first-tenant-snapshot/uploads-export/link'
                        ),
                        b'../../escape',
                    )
                ]
            },
            'symlink',
        ),
        (
            {
                'extra_members': [
                    ('first-tenant-snapshot/legacy-full.sql', b'duplicate')
                ]
            },
            'duplicate',
        ),
        (
            {
                'extra_members': [
                    ('first-tenant-snapshot/unexpected.bin', b'unexpected')
                ]
            },
            'allowlisted',
        ),
    ),
)
def test_verify_snapshot_package_rejects_unsafe_or_drifted_archives(
    tmp_path,
    package_options,
    match,
):
    archive_path, sidecar_path = _write_snapshot_package(
        tmp_path,
        **package_options,
    )
    extraction_root = tmp_path / 'extracted'

    with pytest.raises(OperationSafetyError, match=match):
        verify_snapshot_package(
            archive_path,
            sidecar_path=sidecar_path,
            extraction_root=extraction_root,
        )

    assert not extraction_root.exists()


def test_operation_lock_is_exclusive_and_records_owner(tmp_path):
    lock_path = tmp_path / 'locks' / 'first-tenant.lock'
    first = OperationLock(
        lock_path,
        operation='prepare',
        runtime_id=SNAPSHOT_ID,
    )
    first.acquire()
    owner = json.loads(lock_path.read_text(encoding='utf-8'))

    assert owner['operation'] == 'prepare'
    assert owner['runtimeId'] == SNAPSHOT_ID
    assert isinstance(owner['pid'], int) and owner['pid'] > 0
    assert owner['startedAt'].endswith('Z')
    assert 'token' not in owner
    with pytest.raises(OperationSafetyError, match='already held'):
        OperationLock(
            lock_path,
            operation='cutover',
            runtime_id=SNAPSHOT_ID,
        ).acquire()

    first.release()
    assert not lock_path.exists()


def test_stale_lock_requires_exact_clear_confirmation(tmp_path):
    lock_path = tmp_path / 'migration.lock'
    lock_path.write_text(
        json.dumps(
            {
                'operation': 'prepare',
                'pid': 2147483647,
                'runtimeId': SNAPSHOT_ID,
                'startedAt': '2026-07-15T10:20:30Z',
            }
        ),
        encoding='utf-8',
    )

    with pytest.raises(OperationSafetyError, match='CLEAR_STALE_MIGRATION_LOCK'):
        clear_stale_operation_lock(lock_path, confirm=None)

    clear_stale_operation_lock(
        lock_path,
        confirm='CLEAR_STALE_MIGRATION_LOCK',
    )
    assert not lock_path.exists()


def _prepared_state(**overrides) -> PreparedMigrationState:
    values = {
        'snapshot_id': SNAPSHOT_ID,
        'package_sha256': PACKAGE_HASH,
        'status': 'ready',
        'candidate_database': 'hrm_candidate_20260715T102030Z',
        'candidate_bucket': 'hrm-candidate-20260715t102030z',
        'active_database': 'hrm_saas',
        'active_readonly_database': 'hrm_saas',
        'active_bucket': 'hrm-courses',
        'prepared_at': '2026-07-15T10:30:00Z',
        'validation_results': {'apiHealth': True, 'temporaryAdminRemoved': True},
    }
    values.update(overrides)
    return PreparedMigrationState(**values)


def test_prepared_state_is_redacted_and_bound_to_package_hash(tmp_path):
    state_path = tmp_path / 'prepared.json'
    state = _prepared_state()

    write_prepared_state(state_path, state)
    raw_state = state_path.read_text(encoding='utf-8')
    loaded = load_prepared_state(
        state_path,
        expected_package_sha256=PACKAGE_HASH,
    )

    assert loaded == state
    assert 'password' not in raw_state.lower()
    assert 'secret' not in raw_state.lower()
    with pytest.raises(OperationSafetyError, match='package SHA-256'):
        load_prepared_state(
            state_path,
            expected_package_sha256='b' * 64,
        )


def test_prepared_state_rejects_secret_bearing_validation_keys():
    with pytest.raises(OperationSafetyError, match='redacted'):
        _prepared_state(validation_results={'adminPassword': 'do-not-store'})


def _prepare_config(tmp_path):
    app_root = tmp_path / 'app'
    app_root.mkdir()
    (app_root / '.env').write_text('DB_NAME=hrm_saas\n', encoding='utf-8')
    (app_root / 'docker-compose.yml').write_text('services: {}\n')
    (app_root / 'docker-compose.saas-preview.yml').write_text('services: {}\n')
    (app_root / 'docker-compose.release.yml').write_text('services: {}\n')
    return PrepareConfig(
        snapshot_id=SNAPSHOT_ID,
        project='hengpintong-saas-preview',
        app_root=app_root,
        operation_root=tmp_path / 'operations' / SNAPSHOT_ID,
        package_path=tmp_path / 'snapshot.zip',
        sidecar_path=tmp_path / 'snapshot.zip.sha256',
    )


def test_prepare_plan_proves_saas_before_backup_and_never_edits_active_env(
    tmp_path,
):
    config = _prepare_config(tmp_path)

    plan = build_prepare_plan(config)
    names = [step.name for step in plan.steps]

    assert names.index('prove_active') < names.index('backup_active')
    assert names.index('verify_package') < names.index('backup_active')
    assert all(step.writes_active_environment is False for step in plan.steps)
    assert plan.active_environment_path == config.app_root / '.env'
    assert plan.project == 'hengpintong-saas-preview'
    assert plan.compose_prefix == (
        'docker',
        'compose',
        '--env-file',
        str(config.app_root / '.env'),
        '-p',
        'hengpintong-saas-preview',
        '-f',
        str(config.app_root / 'docker-compose.yml'),
        '-f',
        str(config.app_root / 'docker-compose.saas-preview.yml'),
        '-f',
        str(config.app_root / 'docker-compose.release.yml'),
    )


def test_prepare_plan_restore_proves_backup_before_candidate_creation(tmp_path):
    plan = build_prepare_plan(_prepare_config(tmp_path))
    names = [step.name for step in plan.steps]

    assert names.index('backup_active') < names.index('restore_prove_backup')
    assert names.index('restore_prove_backup') < names.index('create_candidates')
    assert names.index('migration_dry_run') < names.index('migration_execute')
    assert names.index('bootstrap_candidate') < names.index('migration_execute')
    assert names.index('migration_execute') < names.index(
        'create_temporary_admin'
    )
    assert names.index('create_temporary_admin') < names.index(
        'start_candidate_backend'
    )
    assert names[-2:] == ['remove_temporary_admin', 'write_prepared_state']


def test_prepare_plan_uses_explicit_shared_environment_path(tmp_path):
    config = _prepare_config(tmp_path)
    shared_environment = tmp_path / 'deployment' / 'shared' / '.env'
    shared_environment.parent.mkdir(parents=True)
    shared_environment.write_text('DB_NAME=hrm_saas\n', encoding='utf-8')
    shared_uploads = shared_environment.parent / 'uploads'
    shared_certs = shared_environment.parent / 'certs'
    shared_uploads.mkdir()
    shared_certs.mkdir()
    (config.app_root / '.env').unlink()
    shared_config = PrepareConfig(
        snapshot_id=config.snapshot_id,
        project=config.project,
        app_root=config.app_root,
        operation_root=config.operation_root,
        package_path=config.package_path,
        sidecar_path=config.sidecar_path,
        environment_path=shared_environment,
        uploads_path=shared_uploads,
        certs_path=shared_certs,
    )

    plan = build_prepare_plan(shared_config)

    assert plan.active_environment_path == shared_environment.resolve()
    assert plan.compose_prefix[3] == str(shared_environment.resolve())
    assert shared_config.uploads_path == shared_uploads
    assert shared_config.certs_path == shared_certs

    actions = object.__new__(ServerPrepareActions)
    actions.config = shared_config
    assert actions._active_uploads_path() == shared_uploads.resolve()
    assert actions._active_certs_path() == shared_certs.resolve()


class FakePrepareActions:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.events = []
        self.active_environment = b'DB_NAME=hrm_saas\nMINIO_BUCKET=hrm-courses\n'
        self.candidate_retained = False

    def run_prepare_step(self, step):
        self.events.append(step.name)
        if step.name == 'create_candidates':
            self.candidate_retained = True
        if step.name == self.fail_at:
            raise RuntimeError(f'simulated {step.name} failure')


def test_prepare_failure_retains_candidate_and_active_targets_unchanged(tmp_path):
    plan = build_prepare_plan(_prepare_config(tmp_path))
    actions = FakePrepareActions(fail_at='migration_execute')
    original_environment = actions.active_environment

    with pytest.raises(RuntimeError, match='migration_execute'):
        execute_prepare(actions, plan)

    assert actions.active_environment == original_environment
    assert actions.candidate_retained is True
    assert 'write_prepared_state' not in actions.events
    assert not any(name.startswith('cleanup_candidate') for name in actions.events)


class FakeSwitchActions:
    def __init__(self, *, fail_candidate_validation=False):
        self.fail_candidate_validation = fail_candidate_validation
        self.events = []

    def restart_backend_and_nginx(self, *, project):
        self.events.append(('restart', project))

    def validate_active_targets(self, *, database, bucket):
        self.events.append(('validate', database, bucket))
        if self.fail_candidate_validation and database.startswith('hrm_candidate_'):
            raise RuntimeError('candidate health failed')


def _active_environment_bytes():
    return (
        b'# preserved comment\n'
        b'DB_NAME=hrm_saas\n'
        b'DB_READONLY_NAME=hrm_saas\n'
        b'MINIO_BUCKET=hrm-courses\n'
        b'JWT_SECRET=exact-secret-bytes\n'
    )


def test_cutover_requires_phrase_and_changes_only_three_target_variables(tmp_path):
    environment_path = tmp_path / '.env'
    environment_path.write_bytes(_active_environment_bytes())
    backup_path = tmp_path / 'operations' / 'before-cutover.env'
    actions = FakeSwitchActions()
    state = _prepared_state()

    with pytest.raises(OperationSafetyError, match='PROMOTE_FIRST_TENANT'):
        promote_candidate(
            state,
            environment_path=environment_path,
            backup_path=backup_path,
            actions=actions,
            expected_package_sha256=PACKAGE_HASH,
            confirm=None,
            now=datetime(2026, 7, 15, 10, 35, tzinfo=timezone.utc),
        )

    result = promote_candidate(
        state,
        environment_path=environment_path,
        backup_path=backup_path,
        actions=actions,
        expected_package_sha256=PACKAGE_HASH,
        confirm='PROMOTE_FIRST_TENANT',
        now=datetime(2026, 7, 15, 10, 35, tzinfo=timezone.utc),
    )

    assert result.status == 'promoted'
    assert environment_path.read_bytes() == (
        b'# preserved comment\n'
        b'DB_NAME=hrm_candidate_20260715T102030Z\n'
        b'DB_READONLY_NAME=hrm_candidate_20260715T102030Z\n'
        b'MINIO_BUCKET=hrm-candidate-20260715t102030z\n'
        b'JWT_SECRET=exact-secret-bytes\n'
    )
    assert backup_path.read_bytes() == _active_environment_bytes()
    assert actions.events == [
        ('restart', 'hengpintong-saas-preview'),
        (
            'validate',
            'hrm_candidate_20260715T102030Z',
            'hrm-candidate-20260715t102030z',
        ),
    ]


def test_failed_post_switch_health_restores_exact_previous_env_and_services(
    tmp_path,
):
    environment_path = tmp_path / '.env'
    original = _active_environment_bytes()
    environment_path.write_bytes(original)
    actions = FakeSwitchActions(fail_candidate_validation=True)

    with pytest.raises(OperationSafetyError, match='restored prior targets'):
        promote_candidate(
            _prepared_state(),
            environment_path=environment_path,
            backup_path=tmp_path / 'before.env',
            actions=actions,
            expected_package_sha256=PACKAGE_HASH,
            confirm='PROMOTE_FIRST_TENANT',
            now=datetime(2026, 7, 15, 10, 35, tzinfo=timezone.utc),
        )

    assert environment_path.read_bytes() == original
    assert actions.events == [
        ('restart', 'hengpintong-saas-preview'),
        (
            'validate',
            'hrm_candidate_20260715T102030Z',
            'hrm-candidate-20260715t102030z',
        ),
        ('restart', 'hengpintong-saas-preview'),
        ('validate', 'hrm_saas', 'hrm-courses'),
    ]


def test_manual_rollback_keeps_failed_candidate_and_restores_prior_targets(
    tmp_path,
):
    environment_path = tmp_path / '.env'
    promoted = _active_environment_bytes().replace(
        b'DB_NAME=hrm_saas\n',
        b'DB_NAME=hrm_candidate_20260715T102030Z\n',
    ).replace(
        b'DB_READONLY_NAME=hrm_saas\n',
        b'DB_READONLY_NAME=hrm_candidate_20260715T102030Z\n',
    ).replace(
        b'MINIO_BUCKET=hrm-courses\n',
        b'MINIO_BUCKET=hrm-candidate-20260715t102030z\n',
    )
    environment_path.write_bytes(promoted)
    backup_path = tmp_path / 'before.env'
    backup_path.write_bytes(_active_environment_bytes())
    actions = FakeSwitchActions()

    result = rollback_candidate(
        _prepared_state(),
        environment_path=environment_path,
        backup_path=backup_path,
        actions=actions,
    )

    assert result.status == 'rolled_back'
    assert environment_path.read_bytes() == _active_environment_bytes()
    assert result.retained_candidate_database == 'hrm_candidate_20260715T102030Z'
    assert result.retained_candidate_bucket == 'hrm-candidate-20260715t102030z'
    assert actions.events == [
        ('restart', 'hengpintong-saas-preview'),
        ('validate', 'hrm_saas', 'hrm-courses'),
    ]


def test_server_cli_resolves_unique_incoming_package_and_commands(tmp_path):
    cli = importlib.import_module('scripts.server_first_tenant_migration')
    deployment_root = tmp_path / 'deployment'
    incoming = deployment_root / 'shared' / 'incoming'
    incoming.mkdir(parents=True)
    package = incoming / 'first-tenant-snapshot.zip'
    sidecar = incoming / 'first-tenant-snapshot.zip.sha256'
    package.write_bytes(b'zip')
    sidecar.write_text('0' * 64 + '  first-tenant-snapshot.zip\n')

    prepare = cli.parse_args(
        ['--deployment-root', str(deployment_root), 'prepare']
    )
    resolved_package, resolved_sidecar = cli.resolve_snapshot_package(prepare)
    assert resolved_package == package
    assert resolved_sidecar == sidecar
    assert prepare.command == 'prepare'
    assert prepare.plan is False

    cutover = cli.parse_args(
        [
            '--deployment-root',
            str(deployment_root),
            'cutover',
            '--confirm',
            'PROMOTE_FIRST_TENANT',
        ]
    )
    assert cutover.command == 'cutover'
    assert cutover.confirm == 'PROMOTE_FIRST_TENANT'


def test_server_launcher_requires_root_and_uses_no_eval():
    launcher = Path(__file__).resolve().parents[2] / 'migrate-first-tenant.sh'
    payload = launcher.read_text(encoding='ascii')

    assert 'id -u' in payload
    assert 'umask 077' in payload
    assert 'server_first_tenant_migration.py' in payload
    assert 'current/backend-python/scripts/server_first_tenant_migration.py' in payload
    assert '[ -L "$SCRIPT_DIR/current" ]' in payload
    assert 'eval ' not in payload
    assert 'sudo ' not in payload


def test_docker_switch_recovery_allows_unhealthy_exact_project(
    tmp_path,
    monkeypatch,
):
    from ops import legacy_snapshot

    plan = build_prepare_plan(_prepare_config(tmp_path))
    runner = RecordingRunner()
    observed = []

    def prove(_runner, *, project, docker_command, require_healthy):
        observed.append((project, docker_command, require_healthy))

    monkeypatch.setattr(legacy_snapshot, 'prove_source_project', prove)
    DockerSwitchActions(runner=runner, plan=plan).restart_backend_and_nginx(
        project='hengpintong-saas-preview'
    )

    assert observed == [('hengpintong-saas-preview', 'docker', False)]


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        from ops.operation_common import CommandResult

        call = tuple(argv)
        self.calls.append((call, kwargs))
        output = ''
        if call[:2] == ('docker', 'ps'):
            output = '\n'.join(
                '|'.join(
                    (
                        f'container-{index}',
                        f'hengpintong-saas-preview-{service}-1',
                        'Up 2 hours (healthy)',
                        service,
                        'hengpintong-saas-preview',
                    )
                )
                for index, service in enumerate(
                    ('backend', 'minio', 'mysql', 'nginx'),
                    1,
                )
            ) + '\n'
        return CommandResult(call, 0, output, '')


def test_docker_switch_actions_target_only_proved_saas_compose(tmp_path):
    plan = build_prepare_plan(_prepare_config(tmp_path))
    runner = RecordingRunner()
    actions = DockerSwitchActions(runner=runner, plan=plan)

    actions.restart_backend_and_nginx(project='hengpintong-saas-preview')
    actions.validate_active_targets(
        database='hrm_candidate_20260715T102030Z',
        bucket='hrm-candidate-20260715t102030z',
    )

    commands = [call for call, _kwargs in runner.calls]
    assert commands[0][:2] == ('docker', 'ps')
    assert commands[1] == (
        *plan.compose_prefix,
        'up',
        '-d',
        '--no-deps',
        'backend',
        'nginx',
    )
    assert commands[2][: len(plan.compose_prefix)] == plan.compose_prefix
    assert commands[2][len(plan.compose_prefix):4 + len(plan.compose_prefix)] == (
        'exec', '-T', '-e',
        'HPT_EXPECTED_DATABASE=hrm_candidate_20260715T102030Z',
    )
    assert all('hengpintong-next' not in command for command in commands)
