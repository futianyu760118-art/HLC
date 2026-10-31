from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from ops.operation_common import OperationSafetyError
from ops.release_bundle import (
    DEFAULT_RELEASE_SOURCE_ALLOWLIST,
    ReleaseManifest,
    WorkspaceFile,
    assert_workspace_unchanged,
    build_release_archive,
    build_release_plan,
    capture_workspace_files,
    validate_release_id,
    execute_release_build,
)


RELEASE_ID = '20260715T120000Z'


def test_release_id_is_utc_and_archive_safe():
    assert validate_release_id(RELEASE_ID) == RELEASE_ID
    for value in ('', '../release', '20260715', '20260715t120000z'):
        with pytest.raises(OperationSafetyError, match='release ID'):
            validate_release_id(value)


def test_release_allowlist_excludes_secrets_data_and_build_caches():
    forbidden = (
        '.env',
        'certs/localhost.key',
        'backend-python/uploads/a.pdf',
        'outputs/saas-docker-preview/uploads/a.pdf',
        'node_modules/pkg/index.js',
        'artifacts/browser-verification/report.json',
    )
    assert not any(path in DEFAULT_RELEASE_SOURCE_ALLOWLIST for path in forbidden)
    assert 'docker-compose.yml' in DEFAULT_RELEASE_SOURCE_ALLOWLIST
    assert 'docker-compose.saas-preview.yml' in DEFAULT_RELEASE_SOURCE_ALLOWLIST
    assert 'docker-compose.release.yml' in DEFAULT_RELEASE_SOURCE_ALLOWLIST


def test_workspace_snapshot_detects_shared_file_change_before_archive(tmp_path):
    (tmp_path / 'docker-compose.yml').write_bytes(b'services: {}\n')
    captured = capture_workspace_files(tmp_path, ('docker-compose.yml',))
    assert captured == (
        WorkspaceFile(
            path='docker-compose.yml',
            size_bytes=13,
            sha256=hashlib.sha256(b'services: {}\n').hexdigest(),
        ),
    )

    (tmp_path / 'docker-compose.yml').write_text('services: {changed: true}\n')
    with pytest.raises(OperationSafetyError, match='workspace changed'):
        assert_workspace_unchanged(tmp_path, captured)


def test_release_manifest_binds_every_payload_size_and_sha256(tmp_path):
    staging = tmp_path / 'staging'
    (staging / 'app' / 'dist-prod').mkdir(parents=True)
    (staging / 'app' / 'dist-prod' / 'index.html').write_text('hello')
    (staging / 'images').mkdir()
    (staging / 'images' / 'backend-image.tar').write_bytes(b'image')
    payload = capture_workspace_files(
        staging,
        ('app/dist-prod/index.html', 'images/backend-image.tar'),
    )
    manifest = ReleaseManifest(
        release_id=RELEASE_ID,
        architecture='linux/amd64',
        backend_image='hengpintong-saas-backend:20260715T120000Z',
        backend_digest='sha256:' + 'a' * 64,
        payload=payload,
    )
    archive_path = tmp_path / 'release.zip'

    built = build_release_archive(
        staging_root=staging,
        archive_path=archive_path,
        manifest=manifest,
    )

    assert built.archive_path == archive_path
    assert built.sha256_path.read_text(encoding='ascii') == (
        f'{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  release.zip\n'
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert names == [
            'hpt-release/app/dist-prod/index.html',
            'hpt-release/images/backend-image.tar',
            'hpt-release/release-manifest.json',
            'hpt-release/SHA256SUMS',
        ]
        manifest_value = json.loads(
            archive.read('hpt-release/release-manifest.json')
        )
        assert manifest_value['releaseId'] == RELEASE_ID
        assert manifest_value['architecture'] == 'linux/amd64'
        assert manifest_value['backendDigest'] == 'sha256:' + 'a' * 64
        checksum_rows = archive.read('hpt-release/SHA256SUMS').decode('ascii')
        for item in payload:
            assert f'{item.sha256}  {item.path}\n' in checksum_rows
        assert archive.getinfo(
            'hpt-release/images/backend-image.tar'
        ).compress_type == zipfile.ZIP_STORED


def test_build_plan_runs_guards_frontend_then_linux_image():
    plan = build_release_plan(RELEASE_ID)
    names = [step.name for step in plan.steps]

    assert names == [
        'target_guard',
        'operation_tests',
        'typescript',
        'lint',
        'frontend_build',
        'linux_image_build',
        'image_inspect',
        'image_save',
        'workspace_drift_check',
        'archive_publish',
    ]
    image_step = next(step for step in plan.steps if step.name == 'linux_image_build')
    assert image_step.platform == 'linux/amd64'
    assert image_step.publishes_archive is False
    assert plan.steps[-1].publishes_archive is True


def test_build_plan_never_reads_env_or_data_paths():
    plan = build_release_plan(RELEASE_ID)
    serialized = json.dumps(
        [step.inputs for step in plan.steps],
        ensure_ascii=True,
    ).lower()

    assert '.env' not in serialized
    assert '/uploads' not in serialized
    assert 'node_modules' not in serialized
    assert 'artifacts/browser-verification' not in serialized
    assert 'certs/' not in serialized


class FailingBuildActions:
    def __init__(self, output, fail_at):
        self.output = output
        self.fail_at = fail_at
        self.events = []

    def run_release_build_step(self, step):
        self.events.append(step.name)
        if step.name == self.fail_at:
            raise RuntimeError(f'simulated {step.name} failure')
        if step.publishes_archive:
            self.output.write_bytes(b'release')


def test_build_failure_does_not_publish_release_archive(tmp_path):
    archive = tmp_path / 'release.zip'
    actions = FailingBuildActions(archive, fail_at='linux_image_build')

    with pytest.raises(RuntimeError, match='linux_image_build'):
        execute_release_build(actions, build_release_plan(RELEASE_ID))

    assert not archive.exists()
    assert 'archive_publish' not in actions.events
