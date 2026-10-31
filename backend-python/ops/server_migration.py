"""Safety primitives for first-tenant server migration operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Mapping
import zipfile

from ops.operation_common import (
    OperationSafetyError,
    ensure_relative_member,
    sha256_file,
    validate_runtime_id,
    write_atomic_json,
)


ARCHIVE_PREFIX = 'first-tenant-snapshot/'
LOCK_CLEAR_CONFIRMATION = 'CLEAR_STALE_MIGRATION_LOCK'
SHA256_RE = re.compile(r'^[0-9a-f]{64}$', re.ASCII)
OPERATION_RE = re.compile(r'^[a-z][a-z0-9-]{0,63}$', re.ASCII)
DATABASE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$', re.ASCII)
BUCKET_RE = re.compile(r'^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$', re.ASCII)
UTC_TIMESTAMP_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$',
    re.ASCII,
)
TOP_LEVEL_FILES = frozenset(
    {
        'legacy-full.sql',
        'tenant-profile.json',
        'source-row-counts.json',
        'file-manifest.json',
        'snapshot-manifest.json',
    }
)
TOP_LEVEL_DIRECTORIES = frozenset(
    {
        'uploads-export',
        'minio-export',
        'migration-toolkit',
        'server-migration',
    }
)
SECRET_KEY_PARTS = ('credential', 'password', 'secret', 'token')


@dataclass(frozen=True)
class VerifiedSnapshotPackage:
    archive_path: Path
    package_sha256: str
    snapshot_id: str
    snapshot_root: Path
    file_count: int


@dataclass(frozen=True)
class PrepareConfig:
    snapshot_id: str
    project: str
    app_root: Path
    operation_root: Path
    package_path: Path
    sidecar_path: Path
    environment_path: Path | None = None
    uploads_path: Path | None = None
    certs_path: Path | None = None
    docker_command: str = 'docker'

    def __post_init__(self) -> None:
        validate_runtime_id(self.snapshot_id)
        if self.project != 'hengpintong-saas-preview':
            raise OperationSafetyError(
                'server migration project must be hengpintong-saas-preview'
            )
        app_root = Path(self.app_root)
        if app_root.is_symlink() or not app_root.is_dir():
            raise OperationSafetyError(
                'server migration app root must be a non-symlink directory'
            )
        if not isinstance(self.docker_command, str) or not self.docker_command:
            raise OperationSafetyError('Docker command must not be empty')


@dataclass(frozen=True)
class PrepareStep:
    name: str
    writes_active_environment: bool = False


@dataclass(frozen=True)
class PreparePlan:
    project: str
    active_environment_path: Path
    compose_prefix: tuple[str, ...]
    steps: tuple[PrepareStep, ...]


@dataclass(frozen=True)
class PrepareExecutionResult:
    status: str
    completed_steps: tuple[str, ...]


@dataclass(frozen=True)
class CandidatePromotionResult:
    status: str
    active_database: str
    active_bucket: str


@dataclass(frozen=True)
class CandidateRollbackResult:
    status: str
    active_database: str
    active_bucket: str
    retained_candidate_database: str
    retained_candidate_bucket: str


@dataclass(frozen=True)
class PreparedMigrationState:
    snapshot_id: str
    package_sha256: str
    status: str
    candidate_database: str
    candidate_bucket: str
    active_database: str
    active_readonly_database: str
    active_bucket: str
    prepared_at: str
    validation_results: Mapping[str, object]

    def __post_init__(self) -> None:
        validate_runtime_id(self.snapshot_id)
        _validate_sha256(self.package_sha256, owner='package SHA-256')
        if self.status != 'ready':
            raise OperationSafetyError('prepared state status must be ready')
        for owner, value in (
            ('candidate database', self.candidate_database),
            ('active database', self.active_database),
            ('active read-only database', self.active_readonly_database),
        ):
            if not isinstance(value, str) or DATABASE_RE.fullmatch(value) is None:
                raise OperationSafetyError(f'{owner} name is invalid')
        for owner, value in (
            ('candidate bucket', self.candidate_bucket),
            ('active bucket', self.active_bucket),
        ):
            if not isinstance(value, str) or BUCKET_RE.fullmatch(value) is None:
                raise OperationSafetyError(f'{owner} name is invalid')
        _validate_utc_timestamp(self.prepared_at, owner='preparedAt')
        _validate_redacted_value(
            self.validation_results,
            owner='validationResults',
        )

    def to_dict(self) -> dict[str, object]:
        return {
            'activeBucket': self.active_bucket,
            'activeDatabase': self.active_database,
            'activeReadonlyDatabase': self.active_readonly_database,
            'candidateBucket': self.candidate_bucket,
            'candidateDatabase': self.candidate_database,
            'packageSha256': self.package_sha256,
            'preparedAt': self.prepared_at,
            'snapshotId': self.snapshot_id,
            'status': self.status,
            'validationResults': dict(self.validation_results),
        }

    @classmethod
    def from_dict(cls, value: object) -> 'PreparedMigrationState':
        if not isinstance(value, dict):
            raise OperationSafetyError('prepared state must be a JSON object')
        expected = {
            'activeBucket',
            'activeDatabase',
            'activeReadonlyDatabase',
            'candidateBucket',
            'candidateDatabase',
            'packageSha256',
            'preparedAt',
            'snapshotId',
            'status',
            'validationResults',
        }
        if set(value) != expected:
            raise OperationSafetyError('prepared state fields are invalid')
        return cls(
            snapshot_id=value['snapshotId'],
            package_sha256=value['packageSha256'],
            status=value['status'],
            candidate_database=value['candidateDatabase'],
            candidate_bucket=value['candidateBucket'],
            active_database=value['activeDatabase'],
            active_readonly_database=value['activeReadonlyDatabase'],
            active_bucket=value['activeBucket'],
            prepared_at=value['preparedAt'],
            validation_results=value['validationResults'],
        )


class OperationLock:
    def __init__(
        self,
        path: Path,
        *,
        operation: str,
        runtime_id: str,
    ) -> None:
        if not isinstance(operation, str) or OPERATION_RE.fullmatch(operation) is None:
            raise OperationSafetyError('lock operation name is invalid')
        self.path = Path(path)
        self.operation = operation
        self.runtime_id = validate_runtime_id(runtime_id)
        self._owner: dict[str, object] | None = None

    def acquire(self) -> None:
        if self._owner is not None:
            raise OperationSafetyError('operation lock is already held')
        if self.path.is_symlink():
            raise OperationSafetyError('operation lock path must not be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        owner = {
            'operation': self.operation,
            'pid': os.getpid(),
            'runtimeId': self.runtime_id,
            'startedAt': _utc_now_text(),
        }
        payload = (
            json.dumps(owner, ensure_ascii=True, indent=2, sort_keys=True) + '\n'
        ).encode('utf-8')
        try:
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise OperationSafetyError('operation lock is already held') from exc
        try:
            with os.fdopen(descriptor, 'wb') as output:
                descriptor = -1
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(self.path, 0o600)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            self.path.unlink(missing_ok=True)
            raise
        self._owner = owner

    def release(self) -> None:
        if self._owner is None:
            raise OperationSafetyError('operation lock is not held by this owner')
        try:
            current = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise OperationSafetyError('operation lock owner cannot be verified') from exc
        if current != self._owner:
            raise OperationSafetyError('operation lock owner changed')
        self.path.unlink()
        self._owner = None

    def __enter__(self) -> 'OperationLock':
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class DockerSwitchActions:
    """Restart and validate only the proved SaaS backend/Nginx services."""

    def __init__(self, *, runner, plan: PreparePlan) -> None:
        if plan.project != 'hengpintong-saas-preview':
            raise OperationSafetyError('Docker switch plan targets the wrong project')
        self.runner = runner
        self.plan = plan

    def _run_required(self, argv: tuple[str, ...], *, timeout: int = 300) -> None:
        result = self.runner.run(
            argv,
            cwd=self.plan.active_environment_path.parent,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'Docker switch command failed with code {result.returncode}'
            )

    def restart_backend_and_nginx(self, *, project: str) -> None:
        if project != self.plan.project:
            raise OperationSafetyError('Docker restart project proof mismatch')
        from ops.legacy_snapshot import prove_source_project

        prove_source_project(
            self.runner,
            project=self.plan.project,
            docker_command=self.plan.compose_prefix[0],
            require_healthy=False,
        )
        self._run_required(
            (
                *self.plan.compose_prefix,
                'up',
                '-d',
                '--no-deps',
                'backend',
                'nginx',
            ),
            timeout=600,
        )

    def validate_active_targets(self, *, database: str, bucket: str) -> None:
        if DATABASE_RE.fullmatch(database) is None:
            raise OperationSafetyError('validation database name is invalid')
        if BUCKET_RE.fullmatch(bucket) is None:
            raise OperationSafetyError('validation bucket name is invalid')
        validation_script = (
            'set -eu; '
            'test "$DB_NAME" = "$HPT_EXPECTED_DATABASE"; '
            'test "$DB_READONLY_NAME" = "$HPT_EXPECTED_DATABASE"; '
            'test "$MINIO_BUCKET" = "$HPT_EXPECTED_BUCKET"; '
            'curl -fsS "http://127.0.0.1:${PORT:-18888}/api/health" '
            '>/dev/null; '
            'curl -fsS "http://127.0.0.1:${PORT:-18888}/api/ready" '
            '>/dev/null'
        )
        self._run_required(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_EXPECTED_DATABASE={database}',
                '-e',
                f'HPT_EXPECTED_BUCKET={bucket}',
                'backend',
                'sh',
                '-lc',
                validation_script,
            )
        )


def _utc_now_text() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace('+00:00', 'Z')
    )


def _validate_utc_timestamp(value: object, *, owner: str) -> str:
    if not isinstance(value, str) or UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise OperationSafetyError(f'{owner} must be a strict UTC timestamp')
    try:
        datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as exc:
        raise OperationSafetyError(f'{owner} contains an invalid time') from exc
    return value


def _validate_sha256(value: object, *, owner: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise OperationSafetyError(f'{owner} must be lowercase hexadecimal')
    return value


def _validate_redacted_value(value: object, *, owner: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise OperationSafetyError(f'{owner} must use string keys')
            normalized_key = re.sub(r'[^a-z0-9]', '', key.lower())
            if any(part in normalized_key for part in SECRET_KEY_PARTS):
                raise OperationSafetyError(
                    f'{owner} must remain redacted and contain no secret keys'
                )
            _validate_redacted_value(child, owner=owner)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_redacted_value(child, owner=owner)
        return
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    raise OperationSafetyError(f'{owner} contains an unsupported value')


def _archive_member_is_allowlisted(relative_name: str) -> bool:
    parts = relative_name.split('/')
    if len(parts) == 1:
        return parts[0] in TOP_LEVEL_FILES or parts[0] == 'SHA256SUMS'
    return parts[0] in TOP_LEVEL_DIRECTORIES


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return info.create_system == 3 and stat.S_ISLNK(mode)


def _read_checksum_manifest(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> dict[str, str]:
    try:
        payload = archive.read(info).decode('ascii')
    except (UnicodeDecodeError, RuntimeError) as exc:
        raise OperationSafetyError('snapshot SHA256SUMS is invalid') from exc
    rows: dict[str, str] = {}
    for line in payload.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line, re.ASCII)
        if match is None:
            raise OperationSafetyError('snapshot SHA256SUMS is invalid')
        digest, relative_name = match.groups()
        ensure_relative_member(relative_name)
        if relative_name in rows:
            raise OperationSafetyError('snapshot SHA256SUMS has duplicate names')
        rows[relative_name] = digest
    return rows


def _hash_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> str:
    digest = hashlib.sha256()
    with archive.open(info, 'r') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sidecar(
    archive_path: Path,
    sidecar_path: Path,
) -> str:
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise OperationSafetyError('snapshot outer SHA-256 sidecar is invalid')
    try:
        payload = sidecar_path.read_text(encoding='ascii')
    except (OSError, UnicodeError) as exc:
        raise OperationSafetyError('snapshot outer SHA-256 sidecar is invalid') from exc
    match = re.fullmatch(r'([0-9a-f]{64})  ([^\r\n]+)\r?\n?', payload, re.ASCII)
    if match is None or match.group(2) != archive_path.name:
        raise OperationSafetyError('snapshot outer SHA-256 sidecar is invalid')
    expected = match.group(1)
    if sha256_file(archive_path) != expected:
        raise OperationSafetyError('snapshot outer SHA-256 mismatch')
    return expected


def verify_outer_package_hash(
    archive_path: Path,
    sidecar_path: Path,
) -> str:
    archive = Path(archive_path)
    if archive.is_symlink() or not archive.is_file():
        raise OperationSafetyError('snapshot package must be a regular file')
    return _validate_sidecar(archive, Path(sidecar_path))


def peek_snapshot_id(archive_path: Path) -> str:
    """Read only the strict manifest ID; full verification still follows."""

    source = Path(archive_path)
    if source.is_symlink() or not source.is_file():
        raise OperationSafetyError('snapshot package must be a regular file')
    try:
        with zipfile.ZipFile(source, 'r') as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise OperationSafetyError(
                    'snapshot archive has duplicate members'
                )
            for name in names:
                ensure_relative_member(name)
            manifest_name = ARCHIVE_PREFIX + 'snapshot-manifest.json'
            if names.count(manifest_name) != 1:
                raise OperationSafetyError('snapshot manifest is missing')
            info = archive.getinfo(manifest_name)
            if info.file_size > 1024 * 1024:
                raise OperationSafetyError('snapshot manifest is too large')
            value = json.loads(archive.read(info))
    except OperationSafetyError:
        raise
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        raise OperationSafetyError('snapshot manifest is invalid') from exc
    if not isinstance(value, dict):
        raise OperationSafetyError('snapshot manifest is invalid')
    return validate_runtime_id(value.get('snapshotId'))


def verify_snapshot_package(
    archive_path: Path,
    *,
    sidecar_path: Path,
    extraction_root: Path,
) -> VerifiedSnapshotPackage:
    archive_source = Path(archive_path)
    if archive_source.is_symlink() or not archive_source.is_file():
        raise OperationSafetyError('snapshot package must be a regular file')
    package_sha256 = _validate_sidecar(archive_source, Path(sidecar_path))
    destination = Path(extraction_root)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        archive = zipfile.ZipFile(archive_source, 'r')
    except (OSError, zipfile.BadZipFile) as exc:
        raise OperationSafetyError('snapshot package is not a valid ZIP archive') from exc

    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise OperationSafetyError('snapshot archive has duplicate members')
        by_relative_name: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            ensure_relative_member(info.filename)
            if not info.filename.startswith(ARCHIVE_PREFIX):
                raise OperationSafetyError('snapshot archive member prefix is invalid')
            relative_name = info.filename[len(ARCHIVE_PREFIX):]
            ensure_relative_member(relative_name)
            if info.is_dir():
                raise OperationSafetyError('snapshot archive directories are not allowed')
            if _is_symlink(info):
                raise OperationSafetyError('snapshot archive symlink is prohibited')
            if info.flag_bits & 0x1:
                raise OperationSafetyError('encrypted snapshot members are prohibited')
            if not _archive_member_is_allowlisted(relative_name):
                raise OperationSafetyError(
                    f'snapshot archive member is not allowlisted: {relative_name}'
                )
            by_relative_name[relative_name] = info

        checksum_info = by_relative_name.get('SHA256SUMS')
        if checksum_info is None:
            raise OperationSafetyError('snapshot SHA256SUMS is missing')
        checksums = _read_checksum_manifest(archive, checksum_info)
        data_members = {
            name: info
            for name, info in by_relative_name.items()
            if name != 'SHA256SUMS'
        }
        if set(checksums) != set(data_members):
            raise OperationSafetyError(
                'snapshot SHA256SUMS member list does not match the archive'
            )
        for relative_name, info in data_members.items():
            if _hash_archive_member(archive, info) != checksums[relative_name]:
                raise OperationSafetyError(
                    f'snapshot SHA256SUMS mismatch: {relative_name}'
                )

        manifest_info = data_members.get('snapshot-manifest.json')
        if manifest_info is None or 'legacy-full.sql' not in data_members:
            raise OperationSafetyError('snapshot package required members are missing')
        try:
            manifest = json.loads(archive.read(manifest_info))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OperationSafetyError('snapshot manifest is invalid') from exc
        if not isinstance(manifest, dict):
            raise OperationSafetyError('snapshot manifest is invalid')
        snapshot_id = validate_runtime_id(manifest.get('snapshotId'))

        temporary = Path(
            tempfile.mkdtemp(
                prefix=f'.{destination.name}.',
                suffix='.tmp',
                dir=destination.parent,
            )
        )
        try:
            snapshot_root = temporary / 'first-tenant-snapshot'
            for relative_name, info in sorted(by_relative_name.items()):
                target = snapshot_root.joinpath(*relative_name.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, 'r') as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(target, 0o600)
            os.rename(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    return VerifiedSnapshotPackage(
        archive_path=archive_source,
        package_sha256=package_sha256,
        snapshot_id=snapshot_id,
        snapshot_root=destination / 'first-tenant-snapshot',
        file_count=len(data_members),
    )


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, OverflowError, ValueError):
        return False
    return True


def clear_stale_operation_lock(path: Path, *, confirm: str | None) -> None:
    if confirm != LOCK_CLEAR_CONFIRMATION:
        raise OperationSafetyError(
            f'stale lock removal requires {LOCK_CLEAR_CONFIRMATION}'
        )
    lock_path = Path(path)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise OperationSafetyError('stale operation lock is invalid')
    try:
        owner = json.loads(lock_path.read_text(encoding='utf-8'))
        pid = owner['pid']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise OperationSafetyError('stale operation lock owner is invalid') from exc
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise OperationSafetyError('stale operation lock PID is invalid')
    if _pid_is_alive(pid):
        raise OperationSafetyError('operation lock owner process is still active')
    lock_path.unlink()


def write_prepared_state(path: Path, state: PreparedMigrationState) -> None:
    if not isinstance(state, PreparedMigrationState):
        raise TypeError('state must be PreparedMigrationState')
    write_atomic_json(Path(path), state.to_dict(), overwrite=False)
    os.chmod(path, 0o600)


def load_prepared_state(
    path: Path,
    *,
    expected_package_sha256: str,
) -> PreparedMigrationState:
    expected_hash = _validate_sha256(
        expected_package_sha256,
        owner='expected package SHA-256',
    )
    state_path = Path(path)
    if state_path.is_symlink() or not state_path.is_file():
        raise OperationSafetyError('prepared state file is invalid')
    try:
        payload = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('prepared state JSON is invalid') from exc
    state = PreparedMigrationState.from_dict(payload)
    if state.package_sha256 != expected_hash:
        raise OperationSafetyError('prepared state package SHA-256 does not match')
    return state


_PREPARE_STEP_NAMES = (
    'prove_active',
    'verify_package',
    'check_prerequisites',
    'backup_active',
    'restore_prove_backup',
    'create_candidates',
    'bootstrap_candidate',
    'load_stage',
    'migration_dry_run',
    'migration_execute',
    'upload_prepared_objects',
    'create_temporary_admin',
    'start_candidate_backend',
    'validate_candidate',
    'remove_temporary_admin',
    'write_prepared_state',
)


def build_prepare_plan(config: PrepareConfig) -> PreparePlan:
    root = Path(config.app_root).resolve(strict=True)
    environment_path = (
        Path(config.environment_path).resolve(strict=True)
        if config.environment_path is not None
        else root / '.env'
    )
    compose_path = root / 'docker-compose.yml'
    preview_path = root / 'docker-compose.saas-preview.yml'
    release_path = root / 'docker-compose.release.yml'
    for owner, path in (
        ('active environment', environment_path),
        ('base Compose file', compose_path),
        ('preview Compose file', preview_path),
        ('release Compose file', release_path),
    ):
        if path.is_symlink() or not path.is_file():
            raise OperationSafetyError(f'{owner} is missing or unsafe')
    compose_prefix = (
        config.docker_command,
        'compose',
        '--env-file',
        str(environment_path),
        '-p',
        config.project,
        '-f',
        str(compose_path),
        '-f',
        str(preview_path),
        '-f',
        str(release_path),
    )
    return PreparePlan(
        project=config.project,
        active_environment_path=environment_path,
        compose_prefix=compose_prefix,
        steps=tuple(PrepareStep(name=name) for name in _PREPARE_STEP_NAMES),
    )


def execute_prepare(actions, plan: PreparePlan) -> PrepareExecutionResult:
    completed: list[str] = []
    for step in plan.steps:
        if step.writes_active_environment:
            raise OperationSafetyError(
                'prepare plan must never write the active environment'
            )
        actions.run_prepare_step(step)
        completed.append(step.name)
    return PrepareExecutionResult(
        status='ready',
        completed_steps=tuple(completed),
    )


_TARGET_ENVIRONMENT_KEYS = (
    'DB_NAME',
    'DB_READONLY_NAME',
    'MINIO_BUCKET',
)
_PROMOTION_CONFIRMATION = 'PROMOTE_FIRST_TENANT'
_MAX_PREPARED_AGE_SECONDS = 24 * 60 * 60


def _environment_target_values(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in payload.splitlines():
        for key in _TARGET_ENVIRONMENT_KEYS:
            prefix = f'{key}='.encode('ascii')
            if not raw_line.startswith(prefix):
                continue
            if key in values:
                raise OperationSafetyError(
                    f'active environment contains duplicate {key}'
                )
            try:
                values[key] = raw_line[len(prefix):].decode('ascii')
            except UnicodeDecodeError as exc:
                raise OperationSafetyError(
                    f'active environment {key} is not ASCII'
                ) from exc
    if set(values) != set(_TARGET_ENVIRONMENT_KEYS):
        missing = ', '.join(sorted(set(_TARGET_ENVIRONMENT_KEYS) - set(values)))
        raise OperationSafetyError(
            f'active environment is missing target values: {missing}'
        )
    for key in ('DB_NAME', 'DB_READONLY_NAME'):
        if DATABASE_RE.fullmatch(values[key]) is None:
            raise OperationSafetyError(f'active environment {key} is invalid')
    if BUCKET_RE.fullmatch(values['MINIO_BUCKET']) is None:
        raise OperationSafetyError('active environment MINIO_BUCKET is invalid')
    return values


def _replace_environment_targets(
    payload: bytes,
    replacements: Mapping[str, str],
) -> bytes:
    if set(replacements) != set(_TARGET_ENVIRONMENT_KEYS):
        raise OperationSafetyError(
            'environment switch must replace exactly three target values'
        )
    _environment_target_values(payload)
    output: list[bytes] = []
    replaced: set[str] = set()
    for line in payload.splitlines(keepends=True):
        replacement_line = line
        for key in _TARGET_ENVIRONMENT_KEYS:
            prefix = f'{key}='.encode('ascii')
            if not line.startswith(prefix):
                continue
            ending = b''
            if line.endswith(b'\r\n'):
                ending = b'\r\n'
            elif line.endswith(b'\n'):
                ending = b'\n'
            replacement_line = (
                prefix + replacements[key].encode('ascii') + ending
            )
            replaced.add(key)
            break
        output.append(replacement_line)
    if replaced != set(_TARGET_ENVIRONMENT_KEYS):
        raise OperationSafetyError('environment switch target replacement failed')
    return b''.join(output)


def _write_new_owner_file(path: Path, payload: bytes) -> None:
    target = Path(path)
    if target.is_symlink():
        raise OperationSafetyError('owner file target must not be a symlink')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        raise
    try:
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(target, 0o600)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        target.unlink(missing_ok=True)
        raise


def _replace_owner_file(path: Path, payload: bytes) -> None:
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise OperationSafetyError('active environment file is missing or unsafe')
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{target.name}.',
        suffix='.tmp',
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _validate_prepared_age(
    state: PreparedMigrationState,
    now: datetime,
) -> None:
    if now.tzinfo is None:
        raise OperationSafetyError('cutover current time must be timezone-aware')
    prepared_at = datetime.strptime(
        state.prepared_at,
        '%Y-%m-%dT%H:%M:%SZ',
    ).replace(tzinfo=timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - prepared_at).total_seconds()
    if age_seconds < -300 or age_seconds > _MAX_PREPARED_AGE_SECONDS:
        raise OperationSafetyError('prepared state is outside the cutover age limit')


def _require_state_package_hash(
    state: PreparedMigrationState,
    expected_package_sha256: str,
) -> None:
    expected = _validate_sha256(
        expected_package_sha256,
        owner='expected package SHA-256',
    )
    if state.package_sha256 != expected:
        raise OperationSafetyError('prepared state package SHA-256 does not match')


def promote_candidate(
    state: PreparedMigrationState,
    *,
    environment_path: Path,
    backup_path: Path,
    actions,
    expected_package_sha256: str,
    confirm: str | None,
    now: datetime,
) -> CandidatePromotionResult:
    if confirm != _PROMOTION_CONFIRMATION:
        raise OperationSafetyError(
            f'cutover requires --confirm {_PROMOTION_CONFIRMATION}'
        )
    _require_state_package_hash(state, expected_package_sha256)
    _validate_prepared_age(state, now)
    active_path = Path(environment_path)
    if active_path.is_symlink() or not active_path.is_file():
        raise OperationSafetyError('active environment file is missing or unsafe')
    original_payload = active_path.read_bytes()
    current = _environment_target_values(original_payload)
    expected_current = {
        'DB_NAME': state.active_database,
        'DB_READONLY_NAME': state.active_readonly_database,
        'MINIO_BUCKET': state.active_bucket,
    }
    if current != expected_current:
        raise OperationSafetyError(
            'current active targets differ from prepared state'
        )
    candidate_targets = {
        'DB_NAME': state.candidate_database,
        'DB_READONLY_NAME': state.candidate_database,
        'MINIO_BUCKET': state.candidate_bucket,
    }
    candidate_payload = _replace_environment_targets(
        original_payload,
        candidate_targets,
    )
    _write_new_owner_file(Path(backup_path), original_payload)
    _replace_owner_file(active_path, candidate_payload)

    try:
        actions.restart_backend_and_nginx(
            project='hengpintong-saas-preview'
        )
        actions.validate_active_targets(
            database=state.candidate_database,
            bucket=state.candidate_bucket,
        )
    except BaseException as candidate_error:
        _replace_owner_file(active_path, original_payload)
        try:
            actions.restart_backend_and_nginx(
                project='hengpintong-saas-preview'
            )
            actions.validate_active_targets(
                database=state.active_database,
                bucket=state.active_bucket,
            )
        except BaseException as rollback_error:
            raise OperationSafetyError(
                'candidate cutover and automatic rollback validation failed; '
                'active state is unknown'
            ) from rollback_error
        raise OperationSafetyError(
            'candidate validation failed; restored prior targets'
        ) from candidate_error

    return CandidatePromotionResult(
        status='promoted',
        active_database=state.candidate_database,
        active_bucket=state.candidate_bucket,
    )


def rollback_candidate(
    state: PreparedMigrationState,
    *,
    environment_path: Path,
    backup_path: Path,
    actions,
) -> CandidateRollbackResult:
    active_path = Path(environment_path)
    backup = Path(backup_path)
    if active_path.is_symlink() or not active_path.is_file():
        raise OperationSafetyError('active environment file is missing or unsafe')
    if backup.is_symlink() or not backup.is_file():
        raise OperationSafetyError('pre-cutover environment backup is missing')
    current = _environment_target_values(active_path.read_bytes())
    expected_candidate = {
        'DB_NAME': state.candidate_database,
        'DB_READONLY_NAME': state.candidate_database,
        'MINIO_BUCKET': state.candidate_bucket,
    }
    if current != expected_candidate:
        raise OperationSafetyError('current targets are not the prepared candidate')
    original_payload = backup.read_bytes()
    original_targets = _environment_target_values(original_payload)
    expected_original = {
        'DB_NAME': state.active_database,
        'DB_READONLY_NAME': state.active_readonly_database,
        'MINIO_BUCKET': state.active_bucket,
    }
    if original_targets != expected_original:
        raise OperationSafetyError(
            'pre-cutover environment backup does not match prepared state'
        )
    _replace_owner_file(active_path, original_payload)
    try:
        actions.restart_backend_and_nginx(
            project='hengpintong-saas-preview'
        )
        actions.validate_active_targets(
            database=state.active_database,
            bucket=state.active_bucket,
        )
    except BaseException as exc:
        raise OperationSafetyError(
            'manual rollback validation failed; active state is unknown'
        ) from exc
    return CandidateRollbackResult(
        status='rolled_back',
        active_database=state.active_database,
        active_bucket=state.active_bucket,
        retained_candidate_database=state.candidate_database,
        retained_candidate_bucket=state.candidate_bucket,
    )
