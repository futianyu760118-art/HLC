"""Consistent, source-safe snapshot orchestration for the legacy HRM stack."""

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

from ops.operation_common import (
    CommandRunner,
    OperationSafetyError,
    ensure_relative_member,
    sha256_file,
)


EXPECTED_SOURCE_SERVICES = frozenset({'backend', 'minio', 'mysql', 'nginx'})
PROJECT_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$', re.ASCII)


@dataclass(frozen=True)
class SourceContainer:
    container_id: str
    name: str
    status: str
    service: str
    project: str


@dataclass(frozen=True)
class SourceProof:
    project: str
    containers: tuple[SourceContainer, ...]

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(sorted(container.service for container in self.containers))

    @property
    def healthy(self) -> bool:
        return all(
            re.search(r'\(healthy\)', container.status) is not None
            for container in self.containers
        )

    def container_for(self, service: str) -> str:
        matches = [
            container.name
            for container in self.containers
            if container.service == service
        ]
        if len(matches) != 1:
            raise OperationSafetyError(
                f'source project proof has no unique {service} container'
            )
        return matches[0]


@dataclass(frozen=True)
class SourceInventory:
    table_count: int
    upload_files: int
    upload_bytes: int
    object_count: int
    object_bytes: int
    bucket: str

    def __post_init__(self) -> None:
        for owner, value in (
            ('table_count', self.table_count),
            ('upload_files', self.upload_files),
            ('upload_bytes', self.upload_bytes),
            ('object_count', self.object_count),
            ('object_bytes', self.object_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise OperationSafetyError(
                    f'source inventory {owner} must be a non-negative integer'
                )
        if not isinstance(self.bucket, str) or not self.bucket.strip():
            raise OperationSafetyError(
                'source inventory bucket must be a non-empty string'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'table_count': self.table_count,
            'upload_files': self.upload_files,
            'upload_bytes': self.upload_bytes,
            'object_count': self.object_count,
            'object_bytes': self.object_bytes,
            'bucket': self.bucket,
        }


@dataclass(frozen=True)
class SyncReport:
    created_count: int
    replaced_count: int
    skipped_count: int
    pruned_count: int
    file_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        for owner, value in self.to_dict().items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise OperationSafetyError(
                    f'synchronization {owner} must be a non-negative integer'
                )

    def to_dict(self) -> dict[str, int]:
        return {
            'created_count': self.created_count,
            'replaced_count': self.replaced_count,
            'skipped_count': self.skipped_count,
            'pruned_count': self.pruned_count,
            'file_count': self.file_count,
            'total_bytes': self.total_bytes,
        }


@dataclass(frozen=True)
class SnapshotLifecycleResult:
    status: str


@dataclass(frozen=True)
class SnapshotArchiveResult:
    archive_path: Path
    sha256_path: Path
    sha256: str
    file_count: int


@dataclass(frozen=True)
class _TreeEntry:
    relative_path: str
    size_bytes: int
    sha256: str


def _validate_project(project: object) -> str:
    if not isinstance(project, str) or PROJECT_RE.fullmatch(project) is None:
        raise OperationSafetyError('source project name is unsafe')
    return project


def prove_source_project(
    runner: CommandRunner,
    *,
    project: str,
    docker_command: str = 'docker',
    require_healthy: bool = True,
) -> SourceProof:
    safe_project = _validate_project(project)
    result = runner.run(
        (
            docker_command,
            'ps',
            '-a',
            '--filter',
            f'label=com.docker.compose.project={safe_project}',
            '--format',
            (
                '{{.ID}}|{{.Names}}|{{.Status}}|'
                '{{.Label "com.docker.compose.service"}}|'
                '{{.Label "com.docker.compose.project"}}'
            ),
        )
    )
    if result.returncode != 0:
        raise OperationSafetyError('source project proof command failed')

    containers: list[SourceContainer] = []
    seen_services: set[str] = set()
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split('|')
        if len(parts) != 5 or any(not part for part in parts):
            raise OperationSafetyError('source project proof returned invalid data')
        container_id, name, status, service, labeled_project = parts
        if labeled_project != safe_project:
            raise OperationSafetyError('source project label does not match')
        if service in seen_services:
            raise OperationSafetyError(
                f'source project proof contains duplicate service: {service}'
            )
        seen_services.add(service)
        containers.append(
            SourceContainer(
                container_id=container_id,
                name=name,
                status=status,
                service=service,
                project=labeled_project,
            )
        )

    if seen_services != EXPECTED_SOURCE_SERVICES:
        raise OperationSafetyError(
            'source project proof requires exact services: '
            + ', '.join(sorted(EXPECTED_SOURCE_SERVICES))
        )
    proof = SourceProof(
        project=safe_project,
        containers=tuple(sorted(containers, key=lambda item: item.service)),
    )
    if not isinstance(require_healthy, bool):
        raise OperationSafetyError('source project health requirement is invalid')
    if require_healthy and not proof.healthy:
        raise OperationSafetyError('source project containers must all be healthy')
    return proof


def _parse_non_negative_int(value: str, *, owner: str) -> int:
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError) as exc:
        raise OperationSafetyError(
            f'source inventory {owner} is invalid'
        ) from exc
    if parsed < 0:
        raise OperationSafetyError(f'source inventory {owner} is invalid')
    return parsed


def _inventory_uploads(upload_root: Path) -> tuple[int, int]:
    if upload_root.is_symlink() or not upload_root.is_dir():
        raise OperationSafetyError(
            'source inventory uploads root must be a non-symlink directory'
        )
    files = 0
    total_bytes = 0
    for current_root, directory_names, file_names in os.walk(
        upload_root,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            if (current / name).is_symlink():
                raise OperationSafetyError(
                    'source inventory uploads must not contain symlinks'
                )
        for name in file_names:
            candidate = current / name
            if not candidate.is_file():
                raise OperationSafetyError(
                    'source inventory upload must be a regular file'
                )
            files += 1
            total_bytes += candidate.stat().st_size
    return files, total_bytes


def _validate_tree_source(source_root: Path) -> Path:
    if source_root.is_symlink() or not source_root.is_dir():
        raise OperationSafetyError('synchronization source must be a directory')
    return source_root.resolve(strict=True)


def _validate_tree_destination(destination_root: Path) -> Path:
    if destination_root.is_symlink():
        raise OperationSafetyError(
            'synchronization destination must not be a symlink'
        )
    destination_root.mkdir(parents=True, exist_ok=True)
    if not destination_root.is_dir():
        raise OperationSafetyError(
            'synchronization destination must be a directory'
        )
    return destination_root.resolve(strict=True)


def _ensure_disjoint_roots(source_root: Path, destination_root: Path) -> None:
    source = source_root.resolve(strict=True)
    destination = destination_root.resolve(strict=False)
    if (
        source == destination
        or source in destination.parents
        or destination in source.parents
    ):
        raise OperationSafetyError(
            'synchronization source and destination must not overlap'
        )


def _tree_manifest(root: Path) -> tuple[_TreeEntry, ...]:
    entries: list[_TreeEntry] = []
    for current_root, directory_names, file_names in os.walk(
        root,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            if (current / name).is_symlink():
                raise OperationSafetyError(
                    'synchronization tree must not contain symlinks'
                )
        for name in file_names:
            candidate = current / name
            metadata = candidate.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise OperationSafetyError(
                    'synchronization tree must contain only regular files'
                )
            relative_path = candidate.relative_to(root).as_posix()
            ensure_relative_member(relative_path)
            entries.append(
                _TreeEntry(
                    relative_path=relative_path,
                    size_bytes=metadata.st_size,
                    sha256=sha256_file(candidate),
                )
            )
    return tuple(sorted(entries, key=lambda item: item.relative_path))


def _destination_path(root: Path, relative_path: str) -> Path:
    safe_relative_path = ensure_relative_member(relative_path)
    candidate = root.joinpath(*safe_relative_path.split('/'))
    current = root
    for part in safe_relative_path.split('/')[:-1]:
        current = current / part
        if current.is_symlink():
            raise OperationSafetyError(
                'synchronization destination path contains a symlink'
            )
        if current.exists() and not current.is_dir():
            raise OperationSafetyError(
                'synchronization destination parent is not a directory'
            )
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise OperationSafetyError(
            'synchronization destination escapes its root'
        ) from exc
    return candidate


def _copy_verified_file(
    source: Path,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    replace: bool,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix='.snapshot-',
        suffix='.tmp',
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        digest = hashlib.sha256()
        size_bytes = 0
        with source.open('rb') as input_file, os.fdopen(
            descriptor,
            'wb',
        ) as output_file:
            descriptor = -1
            while chunk := input_file.read(1024 * 1024):
                output_file.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
        if size_bytes != expected_size or digest.hexdigest() != expected_sha256:
            raise OperationSafetyError(
                'synchronization source changed during copy'
            )
        if replace:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
            linked = True
            temporary.unlink()
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
        if linked and destination.exists():
            destination.unlink()
        raise


def _destination_files(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    files: dict[str, Path] = {}
    for current_root, directory_names, file_names in os.walk(
        root,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            if (current / name).is_symlink():
                raise OperationSafetyError(
                    'synchronization destination must not contain symlinks'
                )
        for name in file_names:
            path = current / name
            relative_path = path.relative_to(root).as_posix()
            ensure_relative_member(relative_path)
            files[relative_path] = path
    return files


def _prune_empty_directories(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob('*') if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass


def sync_tree(
    source_root: Path,
    destination_root: Path,
    *,
    replace_changed: bool = False,
    prune: bool = False,
) -> SyncReport:
    source_path = Path(source_root)
    destination_path = Path(destination_root)
    _ensure_disjoint_roots(source_path, destination_path)
    source = _validate_tree_source(source_path)
    destination = _validate_tree_destination(destination_path)
    source_entries = _tree_manifest(source)
    source_by_path = {entry.relative_path: entry for entry in source_entries}
    destination_files = _destination_files(destination)

    decisions: list[tuple[str, _TreeEntry, Path, bool]] = []
    skipped_count = 0
    for entry in source_entries:
        target = _destination_path(destination, entry.relative_path)
        existing = destination_files.get(entry.relative_path)
        if existing is None:
            decisions.append(('create', entry, target, False))
            continue
        if not existing.is_file():
            raise OperationSafetyError(
                'synchronization destination conflict is not a file'
            )
        if (
            existing.stat().st_size == entry.size_bytes
            and sha256_file(existing) == entry.sha256
        ):
            skipped_count += 1
            continue
        if not replace_changed:
            raise OperationSafetyError(
                'synchronization destination has a different hash'
            )
        decisions.append(('replace', entry, target, True))

    stale_paths = sorted(set(destination_files) - set(source_by_path))
    if stale_paths and not prune:
        stale_paths = []

    created_count = 0
    replaced_count = 0
    for action, entry, target, replace in decisions:
        source_file = source.joinpath(*entry.relative_path.split('/'))
        _copy_verified_file(
            source_file,
            target,
            expected_size=entry.size_bytes,
            expected_sha256=entry.sha256,
            replace=replace,
        )
        if action == 'create':
            created_count += 1
        else:
            replaced_count += 1

    for relative_path in stale_paths:
        destination_files[relative_path].unlink()
    if stale_paths:
        _prune_empty_directories(destination)

    return SyncReport(
        created_count=created_count,
        replaced_count=replaced_count,
        skipped_count=skipped_count,
        pruned_count=len(stale_paths),
        file_count=len(source_entries),
        total_bytes=sum(entry.size_bytes for entry in source_entries),
    )


def _object_identity(metadata) -> tuple[object, object, object]:
    return (
        getattr(metadata, 'size', None),
        getattr(metadata, 'etag', None),
        getattr(metadata, 'version_id', None),
    )


def export_minio_objects(
    client,
    *,
    bucket: str,
    destination_root: Path,
    replace_changed: bool = False,
    prune: bool = False,
) -> SyncReport:
    if not isinstance(bucket, str) or not bucket.strip():
        raise OperationSafetyError('MinIO bucket must be a non-empty string')
    destination_path = Path(destination_root)
    destination = _validate_tree_destination(destination_path)
    listed = tuple(client.list_objects(bucket, recursive=True))
    object_names: list[str] = []
    listed_sizes: dict[str, int] = {}
    for item in listed:
        name = ensure_relative_member(getattr(item, 'object_name', None))
        if name in listed_sizes:
            raise OperationSafetyError('MinIO export contains a duplicate key')
        size = getattr(item, 'size', None)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise OperationSafetyError('MinIO export object size is invalid')
        object_names.append(name)
        listed_sizes[name] = size

    destination_files = _destination_files(destination)
    created_count = 0
    replaced_count = 0
    skipped_count = 0
    for object_name in sorted(object_names):
        target = _destination_path(destination, object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix='.minio-',
            suffix='.tmp',
            dir=target.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            before = client.stat_object(bucket, object_name)
            client.fget_object(bucket, object_name, str(temporary))
            after = client.stat_object(bucket, object_name)
            if _object_identity(before) != _object_identity(after):
                raise OperationSafetyError(
                    f'MinIO object changed during download: {object_name}'
                )
            downloaded_size = temporary.stat().st_size
            if downloaded_size != listed_sizes[object_name]:
                raise OperationSafetyError(
                    f'MinIO object size changed during download: {object_name}'
                )
            downloaded_sha256 = sha256_file(temporary)
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    raise OperationSafetyError(
                        'MinIO destination conflict is not a regular file'
                    )
                if (
                    target.stat().st_size == downloaded_size
                    and sha256_file(target) == downloaded_sha256
                ):
                    skipped_count += 1
                    temporary.unlink()
                    continue
                if not replace_changed:
                    raise OperationSafetyError(
                        'MinIO destination has a different hash'
                    )
                os.replace(temporary, target)
                replaced_count += 1
            else:
                os.link(temporary, target)
                temporary.unlink()
                created_count += 1
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            raise

    stale_paths = sorted(set(destination_files) - set(object_names)) if prune else []
    for relative_path in stale_paths:
        destination_files[relative_path].unlink()
    if stale_paths:
        _prune_empty_directories(destination)

    return SyncReport(
        created_count=created_count,
        replaced_count=replaced_count,
        skipped_count=skipped_count,
        pruned_count=len(stale_paths),
        file_count=len(object_names),
        total_bytes=sum(listed_sizes.values()),
    )


def execute_snapshot_lifecycle(actions) -> SnapshotLifecycleResult:
    """Run the no-write state machine and always recover after stop attempt."""

    stop_attempted = False
    pending_error = None
    pending_traceback = None
    try:
        actions.prove()
        actions.precopy()
        stop_attempted = True
        actions.stop()
        actions.verify_stopped()
        actions.final_sync()
        actions.dump()
        actions.verify()
    except BaseException as exc:
        pending_error = exc
        pending_traceback = exc.__traceback__
    finally:
        if stop_attempted:
            try:
                actions.start()
                actions.health()
            except BaseException as recovery_error:
                raise OperationSafetyError(
                    'source recovery failed after snapshot stop attempt'
                ) from recovery_error

    if pending_error is not None:
        raise pending_error.with_traceback(pending_traceback)
    actions.promote()
    return SnapshotLifecycleResult(status='promoted')


def build_source_service_command(
    *,
    action: str,
    project: str,
    source_root: Path,
    docker_command: str = 'docker',
) -> tuple[str, ...]:
    safe_project = _validate_project(project)
    if action not in {'start', 'stop'}:
        raise OperationSafetyError(
            'source service action must be exactly start or stop'
        )
    root = Path(source_root).resolve(strict=False)
    services = ('nginx', 'backend') if action == 'stop' else ('backend', 'nginx')
    return (
        docker_command,
        'compose',
        '--env-file',
        str(root / '.env'),
        '-p',
        safe_project,
        '-f',
        str(root / 'docker-compose.yml'),
        action,
        *services,
    )


def inspect_source_inventory(
    runner: CommandRunner,
    *,
    source_root: Path,
    project: str,
    docker_command: str = 'docker',
) -> SourceInventory:
    proof = prove_source_project(
        runner,
        project=project,
        docker_command=docker_command,
    )
    source_path = Path(source_root)
    if source_path.is_symlink() or not source_path.is_dir():
        raise OperationSafetyError(
            'source inventory root must be a non-symlink directory'
        )
    upload_files, upload_bytes = _inventory_uploads(
        source_path / 'backend-python' / 'uploads'
    )

    mysql_result = runner.run(
        (
            docker_command,
            'exec',
            proof.container_for('mysql'),
            'sh',
            '-lc',
            (
                'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -N '
                '-e "SELECT COUNT(*) FROM information_schema.tables '
                'WHERE table_schema = DATABASE() AND table_type = '
                "'BASE TABLE';\" \"$MYSQL_DATABASE\""
            ),
        )
    )
    if mysql_result.returncode != 0:
        raise OperationSafetyError('source inventory database query failed')
    table_count = _parse_non_negative_int(
        mysql_result.stdout,
        owner='table_count',
    )

    minio_program = (
        "import json,os; from minio import Minio; "
        "endpoint=os.getenv('MINIO_ENDPOINT','minio:9000'); "
        "client=Minio(endpoint, access_key=os.environ['MINIO_ACCESS_KEY'], "
        "secret_key=os.environ['MINIO_SECRET_KEY'], "
        "secure=os.getenv('MINIO_SECURE','false').lower()=='true'); "
        "bucket=os.getenv('MINIO_BUCKET','hrm-courses'); "
        "items=list(client.list_objects(bucket, recursive=True)); "
        "print(json.dumps({'bucket':bucket,'objects':len(items),"
        "'bytes':sum(item.size or 0 for item in items)}, sort_keys=True))"
    )
    minio_result = runner.run(
        (
            docker_command,
            'exec',
            proof.container_for('backend'),
            'python',
            '-c',
            minio_program,
        )
    )
    if minio_result.returncode != 0:
        raise OperationSafetyError('source inventory MinIO query failed')
    try:
        minio = json.loads(minio_result.stdout)
    except (TypeError, ValueError) as exc:
        raise OperationSafetyError(
            'source inventory MinIO data is invalid'
        ) from exc
    if not isinstance(minio, dict):
        raise OperationSafetyError('source inventory MinIO data is invalid')

    return SourceInventory(
        table_count=table_count,
        upload_files=upload_files,
        upload_bytes=upload_bytes,
        object_count=minio.get('objects'),
        object_bytes=minio.get('bytes'),
        bucket=minio.get('bucket'),
    )


_SNAPSHOT_TOP_LEVEL_FILES = frozenset(
    {
        'legacy-full.sql',
        'tenant-profile.json',
        'source-row-counts.json',
        'file-manifest.json',
        'snapshot-manifest.json',
    }
)
_SNAPSHOT_TOP_LEVEL_DIRECTORIES = frozenset(
    {
        'uploads-export',
        'minio-export',
        'migration-toolkit',
        'server-migration',
    }
)
_PROHIBITED_ARCHIVE_SUFFIXES = frozenset({'.crt', '.env', '.key', '.pem'})
_DEFLATED_ARCHIVE_SUFFIXES = frozenset(
    {
        '.css',
        '.html',
        '.js',
        '.json',
        '.md',
        '.mjs',
        '.ps1',
        '.py',
        '.sh',
        '.sql',
        '.ts',
        '.txt',
        '.yaml',
        '.yml',
    }
)


def _snapshot_archive_entries(snapshot_root: Path) -> list[tuple[str, Path]]:
    root = Path(snapshot_root)
    if root.is_symlink() or not root.is_dir():
        raise OperationSafetyError(
            'snapshot root must be a non-symlink directory'
        )
    entries: list[tuple[str, Path]] = []
    for path in root.rglob('*'):
        if path.is_symlink():
            raise OperationSafetyError('snapshot archive rejects symlinks')
        if path.is_dir():
            continue
        if not path.is_file():
            raise OperationSafetyError(
                'snapshot archive accepts regular files only'
            )
        relative_path = path.relative_to(root).as_posix()
        ensure_relative_member(relative_path)
        parts = relative_path.split('/')
        top_level = parts[0]
        lowercase_parts = tuple(part.lower() for part in parts)
        suffix = path.suffix.lower()
        if (
            suffix in _PROHIBITED_ARCHIVE_SUFFIXES
            or '.env' in lowercase_parts
            or any('password' in part for part in lowercase_parts)
        ):
            raise OperationSafetyError(
                f'snapshot archive member is prohibited: {relative_path}'
            )
        if len(parts) == 1:
            allowed = top_level in _SNAPSHOT_TOP_LEVEL_FILES
        else:
            allowed = top_level in _SNAPSHOT_TOP_LEVEL_DIRECTORIES
        if not allowed:
            raise OperationSafetyError(
                f'snapshot archive member is not allowlisted: {relative_path}'
            )
        entries.append((relative_path, path))
    return sorted(entries, key=lambda item: item[0])


def _publish_new_file(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise
    except OSError:
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(temporary, destination)
        return
    temporary.unlink()


def build_snapshot_archive(
    snapshot_root: Path,
    archive_path: Path,
) -> SnapshotArchiveResult:
    """Build a non-overwriting Zip64 snapshot with inner and outer hashes."""

    destination = Path(archive_path)
    checksum_path = destination.with_name(destination.name + '.sha256')
    if destination.exists():
        raise FileExistsError(destination)
    if checksum_path.exists():
        raise FileExistsError(checksum_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = _snapshot_archive_entries(Path(snapshot_root))
    checksums = [
        f'{sha256_file(path)}  {relative_path}\n'
        for relative_path, path in entries
    ]
    archive_descriptor, archive_temporary_name = tempfile.mkstemp(
        prefix=f'.{destination.name}.',
        suffix='.tmp',
        dir=destination.parent,
    )
    os.close(archive_descriptor)
    archive_temporary = Path(archive_temporary_name)
    try:
        with zipfile.ZipFile(
            archive_temporary,
            mode='w',
            allowZip64=True,
        ) as archive:
            for relative_path, source_path in entries:
                compress_type = (
                    zipfile.ZIP_DEFLATED
                    if source_path.suffix.lower() in _DEFLATED_ARCHIVE_SUFFIXES
                    else zipfile.ZIP_STORED
                )
                archive.write(
                    source_path,
                    arcname=f'first-tenant-snapshot/{relative_path}',
                    compress_type=compress_type,
                )
            archive.writestr(
                'first-tenant-snapshot/SHA256SUMS',
                ''.join(checksums).encode('ascii'),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        with archive_temporary.open('r+b') as archive_file:
            os.fsync(archive_file.fileno())
        archive_sha256 = sha256_file(archive_temporary)
        _publish_new_file(archive_temporary, destination)
    except BaseException:
        archive_temporary.unlink(missing_ok=True)
        raise

    checksum_descriptor, checksum_temporary_name = tempfile.mkstemp(
        prefix=f'.{checksum_path.name}.',
        suffix='.tmp',
        dir=checksum_path.parent,
    )
    os.close(checksum_descriptor)
    checksum_temporary = Path(checksum_temporary_name)
    try:
        with checksum_temporary.open(
            'w',
            encoding='ascii',
            newline='\n',
        ) as checksum_output:
            checksum_output.write(
                f'{archive_sha256}  {destination.name}\n'
            )
        with checksum_temporary.open('r+b') as checksum_file:
            os.fsync(checksum_file.fileno())
        _publish_new_file(checksum_temporary, checksum_path)
    except BaseException:
        checksum_temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    return SnapshotArchiveResult(
        archive_path=destination,
        sha256_path=checksum_path,
        sha256=archive_sha256,
        file_count=len(entries),
    )
