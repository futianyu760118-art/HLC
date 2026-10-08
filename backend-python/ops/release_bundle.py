"""Data-free offline release bundle contracts and drift guards."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile
from typing import Sequence

from ops.operation_common import (
    OperationSafetyError,
    ensure_relative_member,
    sha256_file,
    validate_runtime_id,
)


RELEASE_PREFIX = 'hpt-release/'
DIGEST_RE = re.compile(r'^sha256:[0-9a-f]{64}$', re.ASCII)
IMAGE_RE = re.compile(r'^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*$')
DEFAULT_RELEASE_SOURCE_ALLOWLIST = (
    'docker-compose.yml',
    'docker-compose.saas-preview.yml',
    'docker-compose.release.yml',
    'nginx-docker.conf',
    'init.sql',
    'init-readonly-user.sh',
    'hpt-release.sh',
    'migrate-first-tenant.sh',
    'backend-python/requirements.txt',
    'backend-python/ops/__init__.py',
    'backend-python/ops/candidate_tenant.py',
    'backend-python/ops/legacy_snapshot.py',
    'backend-python/ops/legacy_snapshot_runtime.py',
    'backend-python/ops/operation_common.py',
    'backend-python/ops/release_bundle.py',
    'backend-python/ops/release_manager.py',
    'backend-python/ops/release_transport.py',
    'backend-python/ops/server_migration.py',
    'backend-python/ops/server_prepare.py',
    'backend-python/ops/server_internal.py',
    'backend-python/scripts/hpt_release.py',
    'backend-python/scripts/server_first_tenant_migration.py',
    'backend-python/scripts/server_migration_internal.py',
    'backend-python/scripts/restore_legacy_data.py',
    'backend-python/services/course_progress.py',
    'backend-python/services/legacy_tenant_files.py',
    'backend-python/services/legacy_tenant_migration.py',
)


def validate_release_id(value: object) -> str:
    try:
        return validate_runtime_id(value)
    except OperationSafetyError as exc:
        raise OperationSafetyError(
            'release ID must use strict UTC form YYYYMMDDTHHMMSSZ'
        ) from exc


@dataclass(frozen=True)
class WorkspaceFile:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        ensure_relative_member(self.path)
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise OperationSafetyError('workspace file size is invalid')
        if re.fullmatch(r'[0-9a-f]{64}', self.sha256, re.ASCII) is None:
            raise OperationSafetyError('workspace file SHA-256 is invalid')

    def to_dict(self) -> dict[str, object]:
        return {
            'path': self.path,
            'sha256': self.sha256,
            'sizeBytes': self.size_bytes,
        }


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    architecture: str
    backend_image: str
    backend_digest: str
    payload: tuple[WorkspaceFile, ...]

    def __post_init__(self) -> None:
        validate_release_id(self.release_id)
        if self.architecture != 'linux/amd64':
            raise OperationSafetyError('release architecture must be linux/amd64')
        if (
            not isinstance(self.backend_image, str)
            or IMAGE_RE.fullmatch(self.backend_image) is None
            or self.backend_image.endswith(':latest')
        ):
            raise OperationSafetyError('release backend image reference is invalid')
        if (
            not isinstance(self.backend_digest, str)
            or DIGEST_RE.fullmatch(self.backend_digest) is None
        ):
            raise OperationSafetyError('release backend digest is invalid')
        paths = [item.path for item in self.payload]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise OperationSafetyError(
                'release payload must have unique deterministic paths'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'architecture': self.architecture,
            'backendDigest': self.backend_digest,
            'backendImage': self.backend_image,
            'format': 'hengpintong-offline-release-v1',
            'payload': [item.to_dict() for item in self.payload],
            'releaseId': self.release_id,
        }


@dataclass(frozen=True)
class ReleaseArchiveResult:
    archive_path: Path
    sha256_path: Path
    sha256: str
    file_count: int


@dataclass(frozen=True)
class ReleaseBuildStep:
    name: str
    inputs: tuple[str, ...] = ()
    platform: str | None = None
    publishes_archive: bool = False


@dataclass(frozen=True)
class ReleaseBuildPlan:
    release_id: str
    backend_image: str
    steps: tuple[ReleaseBuildStep, ...]


@dataclass(frozen=True)
class ReleaseBuildResult:
    status: str
    completed_steps: tuple[str, ...]


def build_release_plan(release_id: str) -> ReleaseBuildPlan:
    safe_release_id = validate_release_id(release_id)
    return ReleaseBuildPlan(
        release_id=safe_release_id,
        backend_image=f'hengpintong-saas-backend:{safe_release_id}',
        steps=(
            ReleaseBuildStep('target_guard', ('scripts/verify-saas-target-guard.mjs',)),
            ReleaseBuildStep('operation_tests', ('backend-python/tests/test_release_*.py',)),
            ReleaseBuildStep('typescript', ('src', 'tsconfig.json')),
            ReleaseBuildStep('lint', ('src', 'eslint.config.js')),
            ReleaseBuildStep('frontend_build', ('src', 'public', 'vite.config.ts')),
            ReleaseBuildStep(
                'linux_image_build',
                ('Dockerfile.python', 'backend-python'),
                platform='linux/amd64',
            ),
            ReleaseBuildStep('image_inspect'),
            ReleaseBuildStep('image_save'),
            ReleaseBuildStep('workspace_drift_check'),
            ReleaseBuildStep('archive_publish', publishes_archive=True),
        ),
    )


def execute_release_build(actions, plan: ReleaseBuildPlan) -> ReleaseBuildResult:
    completed = []
    for step in plan.steps:
        actions.run_release_build_step(step)
        completed.append(step.name)
    return ReleaseBuildResult(
        status='published',
        completed_steps=tuple(completed),
    )


def _validate_workspace_source(root: Path, relative_path: str) -> Path:
    ensure_relative_member(relative_path)
    source = root.joinpath(*relative_path.split('/'))
    if source.is_symlink() or not source.is_file():
        raise OperationSafetyError(
            f'allowlisted workspace file is missing or unsafe: {relative_path}'
        )
    try:
        source.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise OperationSafetyError(
            f'allowlisted workspace file escapes root: {relative_path}'
        ) from exc
    return source


def capture_workspace_files(
    root: Path,
    allowlist: Sequence[str],
) -> tuple[WorkspaceFile, ...]:
    workspace = Path(root)
    if workspace.is_symlink() or not workspace.is_dir():
        raise OperationSafetyError('workspace root is missing or unsafe')
    workspace = workspace.resolve(strict=True)
    paths = tuple(sorted(allowlist))
    if len(paths) != len(set(paths)):
        raise OperationSafetyError('workspace allowlist contains duplicates')
    captured = []
    for relative_path in paths:
        source = _validate_workspace_source(workspace, relative_path)
        captured.append(
            WorkspaceFile(
                path=relative_path,
                size_bytes=source.stat().st_size,
                sha256=sha256_file(source),
            )
        )
    return tuple(captured)


def assert_workspace_unchanged(
    root: Path,
    captured: Sequence[WorkspaceFile],
) -> None:
    current = capture_workspace_files(
        root,
        tuple(item.path for item in captured),
    )
    if tuple(captured) != current:
        raise OperationSafetyError('workspace changed after release capture')


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n'
    ).encode('utf-8')


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _publish_new_file(temporary: Path, destination: Path) -> None:
    os.link(temporary, destination)
    temporary.unlink()


def build_release_archive(
    *,
    staging_root: Path,
    archive_path: Path,
    manifest: ReleaseManifest,
) -> ReleaseArchiveResult:
    staging = Path(staging_root)
    destination = Path(archive_path)
    sidecar = destination.with_name(destination.name + '.sha256')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if sidecar.exists() or sidecar.is_symlink():
        raise FileExistsError(sidecar)
    expected_paths = tuple(item.path for item in manifest.payload)
    actual_paths = tuple(
        sorted(
            path.relative_to(staging).as_posix()
            for path in staging.rglob('*')
            if path.is_file() and not path.is_symlink()
        )
    )
    if actual_paths != expected_paths:
        raise OperationSafetyError(
            'release staging files do not match manifest payload'
        )
    current = capture_workspace_files(staging, expected_paths)
    if current != manifest.payload:
        raise OperationSafetyError('release staging payload hash drifted')
    manifest_payload = _json_bytes(manifest.to_dict())
    checksum_rows = [
        f'{item.sha256}  {item.path}\n' for item in manifest.payload
    ]
    checksum_rows.append(
        f'{hashlib.sha256(manifest_payload).hexdigest()}  release-manifest.json\n'
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{destination.name}.',
        suffix='.tmp',
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, 'w', allowZip64=True) as archive:
            for item in manifest.payload:
                source = staging.joinpath(*item.path.split('/'))
                archive.write(
                    source,
                    arcname=RELEASE_PREFIX + item.path,
                    compress_type=(
                        zipfile.ZIP_STORED
                        if item.path.endswith('.tar')
                        else zipfile.ZIP_DEFLATED
                    ),
                )
            archive.writestr(
                _zip_info(RELEASE_PREFIX + 'release-manifest.json'),
                manifest_payload,
            )
            archive.writestr(
                _zip_info(RELEASE_PREFIX + 'SHA256SUMS'),
                ''.join(checksum_rows).encode('ascii'),
            )
        with temporary.open('r+b') as output:
            os.fsync(output.fileno())
        archive_sha256 = sha256_file(temporary)
        _publish_new_file(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    try:
        sidecar.write_text(
            f'{archive_sha256}  {destination.name}\n',
            encoding='ascii',
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise
    return ReleaseArchiveResult(
        archive_path=destination,
        sha256_path=sidecar,
        sha256=archive_sha256,
        file_count=len(manifest.payload),
    )
