"""Tenant-safe rewriting for legacy file references."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
import stat
import tempfile
from typing import Iterable, Literal
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

from services.legacy_tenant_migration import MigrationSafetyError


TENANT_SEGMENT_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$', re.ASCII)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r'^[A-Za-z]:')
MAX_PERCENT_DECODE_ROUNDS = 8
FILE_CHUNK_SIZE = 1024 * 1024
SHA256_RE = re.compile(r'^[0-9a-f]{64}$', re.ASCII)
FILE_REFERENCE_IDENTIFIER_RE = re.compile(
    r'^[A-Za-z_][A-Za-z0-9_]{0,63}$',
    re.ASCII,
)

ATTACHMENT_URL_KEYS = frozenset(
    {
        'url',
        'fileUrl',
        'file_url',
        'attachmentUrl',
        'attachment_url',
        'imageUrl',
        'image_url',
        'coverUrl',
        'cover_url',
        'recordingUrl',
        'recording_url',
        'feedbackFileUrl',
        'feedback_file_url',
    }
)
OBJECT_KEY_KEYS = frozenset({'videoKey', 'video_key'})
PAGE_LINK_KEYS = frozenset({'page_url', 'link_url'})
UNCHANGED_SCHEMES = frozenset({'http', 'https', 'data', 'blob'})


def _validate_relative_file_path(value: object, *, owner: str) -> str:
    if not isinstance(value, str) or not value:
        raise MigrationSafetyError(f'{owner} must be a non-empty string')
    _reject_unsafe_path(value)
    if value.endswith('/') or any(not segment for segment in value.split('/')):
        raise MigrationSafetyError(f'{owner} must identify one relative file')
    return value


def _destination_key_parts(value: object) -> tuple[str, str]:
    destination_key = _validate_relative_file_path(
        value,
        owner='destination_key',
    )
    segments = destination_key.split('/')
    if len(segments) < 3 or segments[0] != 'tenants':
        raise MigrationSafetyError(
            'destination_key must be tenant-prefixed'
        )
    tenant_id = validate_tenant_segment(segments[1])
    relative_path = '/'.join(segments[2:])
    _validate_relative_file_path(
        relative_path,
        owner='destination_key relative path',
    )
    return tenant_id, relative_path


@dataclass(frozen=True)
class FileManifestEntry:
    source_relative_path: str
    destination_key: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        source_relative_path = _validate_relative_file_path(
            self.source_relative_path,
            owner='source_relative_path',
        )
        _, destination_relative_path = _destination_key_parts(
            self.destination_key
        )
        if destination_relative_path != source_relative_path:
            raise MigrationSafetyError(
                'destination_key must preserve source_relative_path'
            )
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise MigrationSafetyError(
                'size_bytes must be a non-bool non-negative int'
            )
        if (
            not isinstance(self.sha256, str)
            or SHA256_RE.fullmatch(self.sha256) is None
        ):
            raise MigrationSafetyError(
                'sha256 must be 64 lowercase hexadecimal characters'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'source_relative_path': self.source_relative_path,
            'destination_key': self.destination_key,
            'size_bytes': self.size_bytes,
            'sha256': self.sha256,
        }


def _validate_report_keys(
    value: object,
    *,
    owner: str,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise MigrationSafetyError(f'{owner} must be a tuple')
    for key in value:
        _destination_key_parts(key)
    if value != tuple(sorted(value)):
        raise MigrationSafetyError(f'{owner} must be sorted')
    if len(value) != len(set(value)):
        raise MigrationSafetyError(f'{owner} must not contain duplicates')
    return value


@dataclass(frozen=True)
class FileCopyReport:
    created_keys: tuple[str, ...]
    skipped_keys: tuple[str, ...]
    total_bytes: int

    def __post_init__(self) -> None:
        created_keys = _validate_report_keys(
            self.created_keys,
            owner='created_keys',
        )
        skipped_keys = _validate_report_keys(
            self.skipped_keys,
            owner='skipped_keys',
        )
        if set(created_keys).intersection(skipped_keys):
            raise MigrationSafetyError(
                'created_keys and skipped_keys must be disjoint'
            )
        if (
            isinstance(self.total_bytes, bool)
            or not isinstance(self.total_bytes, int)
            or self.total_bytes < 0
        ):
            raise MigrationSafetyError(
                'total_bytes must be a non-bool non-negative int'
            )

    def to_dict(self) -> dict[str, object]:
        return {
            'created_keys': list(self.created_keys),
            'skipped_keys': list(self.skipped_keys),
            'total_bytes': self.total_bytes,
        }


@dataclass(frozen=True)
class FileReference:
    source_table: str
    source_column: str
    destination_key: str

    def __post_init__(self) -> None:
        for owner, value in (
            ('source_table', self.source_table),
            ('source_column', self.source_column),
        ):
            if (
                not isinstance(value, str)
                or FILE_REFERENCE_IDENTIFIER_RE.fullmatch(value) is None
            ):
                raise MigrationSafetyError(
                    f'{owner} must be a safe database identifier'
                )
        _destination_key_parts(self.destination_key)

    def to_dict(self) -> dict[str, str]:
        return {
            'source_table': self.source_table,
            'source_column': self.source_column,
            'destination_key': self.destination_key,
        }


@dataclass(frozen=True)
class FileReferenceValidationReport:
    reference_count: int
    referenced_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.reference_count, bool)
            or not isinstance(self.reference_count, int)
            or self.reference_count < 0
        ):
            raise MigrationSafetyError(
                'reference_count must be a non-bool non-negative int'
            )
        referenced_keys = _validate_report_keys(
            self.referenced_keys,
            owner='referenced_keys',
        )
        missing_keys = _validate_report_keys(
            self.missing_keys,
            owner='missing_keys',
        )
        if self.reference_count < len(referenced_keys):
            raise MigrationSafetyError(
                'reference_count cannot be smaller than unique references'
            )
        if not set(missing_keys).issubset(referenced_keys):
            raise MigrationSafetyError(
                'missing_keys must be a subset of referenced_keys'
            )

    @property
    def status(self) -> Literal['passed', 'failed']:
        return 'failed' if self.missing_keys else 'passed'

    def to_dict(self) -> dict[str, object]:
        return {
            'status': self.status,
            'reference_count': self.reference_count,
            'referenced_keys': list(self.referenced_keys),
            'missing_keys': list(self.missing_keys),
        }


def merge_file_manifests(
    *manifests: Iterable[FileManifestEntry],
) -> tuple[FileManifestEntry, ...]:
    """Merge manifests, allowing only byte-identical duplicate keys."""

    entries_by_key: dict[str, FileManifestEntry] = {}
    tenant_ids: set[str] = set()
    for manifest in manifests:
        for entry in manifest:
            if not isinstance(entry, FileManifestEntry):
                raise MigrationSafetyError(
                    'file manifest contains an invalid entry type'
                )
            tenant_id, _ = _destination_key_parts(entry.destination_key)
            tenant_ids.add(tenant_id)
            existing = entries_by_key.get(entry.destination_key)
            if existing is not None and existing != entry:
                raise MigrationSafetyError(
                    'file manifest destination conflict'
                )
            entries_by_key[entry.destination_key] = entry

    if len(tenant_ids) > 1:
        raise MigrationSafetyError(
            'file manifests target more than one tenant'
        )
    return tuple(entries_by_key[key] for key in sorted(entries_by_key))


def validate_manifest_references(
    manifest: Iterable[FileManifestEntry],
    references: Iterable[FileReference],
) -> FileReferenceValidationReport:
    """Compare database file references with a manifest without row values."""

    merged_manifest = merge_file_manifests(tuple(manifest))
    reference_items = tuple(references)
    if any(not isinstance(item, FileReference) for item in reference_items):
        raise MigrationSafetyError('file references contain an invalid type')

    manifest_keys = {entry.destination_key for entry in merged_manifest}
    referenced_keys = tuple(
        sorted({item.destination_key for item in reference_items})
    )
    tenant_ids = {
        _destination_key_parts(key)[0]
        for key in (*manifest_keys, *referenced_keys)
    }
    if len(tenant_ids) > 1:
        raise MigrationSafetyError(
            'file manifest and references target more than one tenant'
        )
    missing_keys = tuple(
        key for key in referenced_keys if key not in manifest_keys
    )
    return FileReferenceValidationReport(
        reference_count=len(reference_items),
        referenced_keys=referenced_keys,
        missing_keys=missing_keys,
    )


def _hash_regular_file(path: Path) -> tuple[int, str]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise MigrationSafetyError('manifest source must be a regular file')

    digest = hashlib.sha256()
    size_bytes = 0
    with path.open('rb') as source:
        while chunk := source.read(FILE_CHUNK_SIZE):
            digest.update(chunk)
            size_bytes += len(chunk)

    after = path.lstat()
    stable_fields = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    if stable_fields != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or size_bytes != after.st_size:
        raise MigrationSafetyError('manifest source changed while hashing')
    return size_bytes, digest.hexdigest()


def build_file_manifest(
    source_root: str | os.PathLike[str],
    tenant_id: object,
) -> tuple[FileManifestEntry, ...]:
    """Build a stable tenant-prefixed SHA-256 manifest for one directory."""

    safe_tenant_id = validate_tenant_segment(tenant_id)
    root = Path(source_root)
    if root.is_symlink():
        raise MigrationSafetyError('manifest source directory is a symlink')
    if not root.is_dir():
        raise MigrationSafetyError(
            'manifest source root must be an existing directory'
        )
    resolved_root = root.resolve(strict=True)

    entries: list[FileManifestEntry] = []
    for current_root, directory_names, file_names in os.walk(
        root,
        followlinks=False,
    ):
        current = Path(current_root)
        for name in (*directory_names, *file_names):
            candidate = current / name
            if candidate.is_symlink():
                raise MigrationSafetyError(
                    'manifest source must not contain symlinks'
                )

        for name in file_names:
            candidate = current / name
            try:
                candidate.resolve(strict=True).relative_to(resolved_root)
            except (OSError, ValueError) as exc:
                raise MigrationSafetyError(
                    'manifest source file escapes its root'
                ) from exc

            relative_path = candidate.relative_to(root).as_posix()
            size_bytes, sha256 = _hash_regular_file(candidate)
            entries.append(
                FileManifestEntry(
                    source_relative_path=relative_path,
                    destination_key=(
                        f'tenants/{safe_tenant_id}/{relative_path}'
                    ),
                    size_bytes=size_bytes,
                    sha256=sha256,
                )
            )

    return tuple(sorted(entries, key=lambda entry: entry.source_relative_path))


def _validate_directory_root(
    value: str | os.PathLike[str],
    *,
    owner: str,
) -> Path:
    root = Path(value)
    if root.is_symlink():
        raise MigrationSafetyError(f'{owner} directory is a symlink')
    if not root.is_dir():
        raise MigrationSafetyError(
            f'{owner} root must be an existing directory'
        )
    return root.resolve(strict=True)


def _join_checked_path(
    root: Path,
    relative_path: str,
    *,
    owner: str,
) -> Path:
    parts = relative_path.split('/')
    candidate = root.joinpath(*parts)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise MigrationSafetyError(f'{owner} path contains a symlink')
        if current.exists() and index < len(parts) - 1 and not current.is_dir():
            raise MigrationSafetyError(
                f'{owner} path has a non-directory parent'
            )

    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise MigrationSafetyError(f'{owner} path escapes its root') from exc
    return candidate


def _verify_file_matches_entry(
    path: Path,
    entry: FileManifestEntry,
    *,
    owner: str,
) -> None:
    try:
        size_bytes, sha256 = _hash_regular_file(path)
    except (OSError, MigrationSafetyError) as exc:
        raise MigrationSafetyError(
            f'{owner} file is missing or unsafe: {entry.destination_key}'
        ) from exc
    if size_bytes != entry.size_bytes or sha256 != entry.sha256:
        raise MigrationSafetyError(
            f'{owner} file changed or does not match its manifest: '
            f'{entry.destination_key}'
        )


def _copy_entry_without_overwrite(
    *,
    source_path: Path,
    destination_path: Path,
    entry: FileManifestEntry,
) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix='.legacy-migration-',
        suffix='.tmp',
        dir=destination_path.parent,
    )
    temporary_path = Path(temporary_name)
    linked = False
    try:
        digest = hashlib.sha256()
        copied_bytes = 0
        with source_path.open('rb') as source, os.fdopen(
            temporary_fd,
            'wb',
        ) as destination:
            temporary_fd = -1
            while chunk := source.read(FILE_CHUNK_SIZE):
                destination.write(chunk)
                digest.update(chunk)
                copied_bytes += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())

        if (
            copied_bytes != entry.size_bytes
            or digest.hexdigest() != entry.sha256
        ):
            raise MigrationSafetyError(
                'source file changed during copy: '
                f'{entry.destination_key}'
            )
        os.link(temporary_path, destination_path)
        linked = True
        temporary_path.unlink()
    except BaseException:
        cleanup_failed = False
        if temporary_fd >= 0:
            try:
                os.close(temporary_fd)
            except OSError:
                cleanup_failed = True
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                cleanup_failed = True
        if linked and destination_path.exists():
            try:
                destination_path.unlink()
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            raise MigrationSafetyError(
                'atomic file copy cleanup failed; destination state is unknown'
            )
        raise


def _remove_created_keys_after_failure(
    destination_root: Path,
    created_keys: Iterable[str],
) -> None:
    cleanup_errors: list[str] = []
    for key in reversed(tuple(created_keys)):
        destination_path = destination_root.joinpath(*key.split('/'))
        try:
            destination_path.unlink()
        except OSError:
            cleanup_errors.append(key)
    if cleanup_errors:
        raise MigrationSafetyError(
            'file copy rollback failed; destination state is unknown'
        )


def copy_file_manifest(
    manifest: Iterable[FileManifestEntry],
    *,
    source_root: str | os.PathLike[str],
    destination_root: str | os.PathLike[str],
) -> FileCopyReport:
    """Copy a verified local export without overwriting destination files."""

    entries = merge_file_manifests(tuple(manifest))
    safe_source_root = _validate_directory_root(
        source_root,
        owner='source',
    )
    safe_destination_root = _validate_directory_root(
        destination_root,
        owner='destination',
    )
    if (
        safe_source_root == safe_destination_root
        or safe_source_root in safe_destination_root.parents
        or safe_destination_root in safe_source_root.parents
    ):
        raise MigrationSafetyError(
            'source and destination roots must not overlap'
        )

    pending: list[tuple[FileManifestEntry, Path, Path]] = []
    skipped_keys: list[str] = []
    for entry in entries:
        source_path = _join_checked_path(
            safe_source_root,
            entry.source_relative_path,
            owner='source',
        )
        _verify_file_matches_entry(
            source_path,
            entry,
            owner='source',
        )

        destination_path = _join_checked_path(
            safe_destination_root,
            entry.destination_key,
            owner='destination',
        )
        if destination_path.exists():
            if not destination_path.is_file():
                raise MigrationSafetyError(
                    'destination conflict is not a regular file: '
                    f'{entry.destination_key}'
                )
            try:
                destination_size, destination_sha256 = _hash_regular_file(
                    destination_path
                )
            except (OSError, MigrationSafetyError) as exc:
                raise MigrationSafetyError(
                    'destination conflict cannot be verified: '
                    f'{entry.destination_key}'
                ) from exc
            if (
                destination_size != entry.size_bytes
                or destination_sha256 != entry.sha256
            ):
                raise MigrationSafetyError(
                    'destination conflict has a different hash: '
                    f'{entry.destination_key}'
                )
            skipped_keys.append(entry.destination_key)
            continue
        pending.append((entry, source_path, destination_path))

    created_keys: list[str] = []
    total_bytes = 0
    try:
        for entry, source_path, destination_path in pending:
            _join_checked_path(
                safe_destination_root,
                entry.destination_key,
                owner='destination',
            )
            _copy_entry_without_overwrite(
                source_path=source_path,
                destination_path=destination_path,
                entry=entry,
            )
            created_keys.append(entry.destination_key)
            total_bytes += entry.size_bytes
    except BaseException as copy_error:
        try:
            _remove_created_keys_after_failure(
                safe_destination_root,
                created_keys,
            )
        except MigrationSafetyError as rollback_error:
            raise rollback_error from copy_error
        raise MigrationSafetyError(
            'file copy failed; files created by this run were rolled back'
        ) from copy_error

    return FileCopyReport(
        created_keys=tuple(created_keys),
        skipped_keys=tuple(skipped_keys),
        total_bytes=total_bytes,
    )


def rollback_created_files(
    manifest: Iterable[FileManifestEntry],
    copy_report: FileCopyReport,
    *,
    destination_root: str | os.PathLike[str],
) -> tuple[str, ...]:
    """Remove only this run's still-hash-matching newly created files."""

    entries = merge_file_manifests(tuple(manifest))
    if not isinstance(copy_report, FileCopyReport):
        raise MigrationSafetyError('copy_report has an invalid type')
    entries_by_key = {entry.destination_key: entry for entry in entries}
    reported_keys = set(copy_report.created_keys).union(
        copy_report.skipped_keys
    )
    unknown_keys = reported_keys - set(entries_by_key)
    if unknown_keys:
        raise MigrationSafetyError(
            'copy_report contains keys outside the file manifest'
        )

    safe_destination_root = _validate_directory_root(
        destination_root,
        owner='destination',
    )
    paths_to_remove: list[Path] = []
    for key in copy_report.created_keys:
        entry = entries_by_key[key]
        destination_path = _join_checked_path(
            safe_destination_root,
            key,
            owner='destination',
        )
        try:
            _verify_file_matches_entry(
                destination_path,
                entry,
                owner='created destination',
            )
        except MigrationSafetyError as exc:
            raise MigrationSafetyError(
                'created destination changed; rollback refused: '
                f'{key}'
            ) from exc
        paths_to_remove.append(destination_path)

    removed_keys: list[str] = []
    for key, path in zip(copy_report.created_keys, paths_to_remove):
        try:
            path.unlink()
        except OSError as exc:
            raise MigrationSafetyError(
                'rollback deletion failed; destination state is unknown'
            ) from exc
        removed_keys.append(key)
    return tuple(removed_keys)


def validate_tenant_segment(tenant_id: object) -> str:
    """Return a tenant identifier that is safe to use as one path segment."""

    if not isinstance(tenant_id, str) or TENANT_SEGMENT_RE.fullmatch(
        tenant_id
    ) is None:
        raise ValueError(
            'tenant_id must contain 1-64 ASCII letters, digits, underscores, '
            'or hyphens'
        )
    return tenant_id


def _decode_percent_encoding(value: str) -> str:
    current = value
    for _ in range(MAX_PERCENT_DECODE_ROUNDS):
        decoded = unquote(current)
        if decoded == current:
            return current
        current = decoded
    if unquote(current) != current:
        raise ValueError('file reference path encoding is too deeply nested')
    return current


def _reject_unsafe_path(path: str, *, allow_upload_root: bool = False) -> None:
    if '\\' in path:
        raise ValueError('file reference path must not contain backslashes')

    segments = path.split('/')
    decoded_segments = tuple(
        _decode_percent_encoding(segment) for segment in segments
    )
    if any(segment in ('.', '..') for segment in decoded_segments):
        raise ValueError('file reference path must not contain traversal')
    if any('/' in segment or '\\' in segment for segment in decoded_segments):
        raise ValueError('file reference path must not contain encoded separators')

    decoded_path = '/'.join(decoded_segments)
    if WINDOWS_ABSOLUTE_PATH_RE.match(decoded_path):
        raise ValueError('file reference must not be a Windows absolute path')
    if decoded_path.startswith('/') and not allow_upload_root:
        raise ValueError('file reference must not be a Unix absolute path')


def _with_path(parts: SplitResult, path: str) -> str:
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _rewrite_upload_url(value: str, tenant_id: str) -> str:
    parts = urlsplit(value)
    path = parts.path
    _reject_unsafe_path(path, allow_upload_root=True)

    relative_path = path[len('/uploads/'):]
    if not relative_path or relative_path.endswith('/'):
        raise ValueError('upload reference path must identify a file')
    _reject_unsafe_path(relative_path)
    if any(not segment for segment in relative_path.split('/')):
        raise ValueError('upload reference path must not contain empty segments')

    segments = relative_path.split('/')
    if segments[0] == 'tenants':
        if len(segments) < 3 or not segments[2]:
            raise ValueError('tenant upload reference path must identify a file')
        owner = validate_tenant_segment(segments[1])
        if owner != tenant_id:
            raise ValueError('file reference belongs to another tenant')
        return value

    return _with_path(parts, f'/uploads/tenants/{tenant_id}/{relative_path}')


def _rewrite_object_key(value: str, tenant_id: str) -> str:
    _reject_unsafe_path(value)
    if value.endswith('/'):
        raise ValueError('object key path must identify a file')

    segments = value.split('/')
    if segments[0] == 'tenants':
        if len(segments) < 3 or not segments[2]:
            raise ValueError('tenant object key path must identify a file')
        owner = validate_tenant_segment(segments[1])
        if owner != tenant_id:
            raise ValueError('file reference belongs to another tenant')
        return value

    return f'tenants/{tenant_id}/{value}'


def _validate_application_url(value: str) -> str:
    parts = urlsplit(value)
    relative_path = parts.path[len('/api/'):]
    if not relative_path:
        raise ValueError('application URL must contain a non-empty path')
    _reject_unsafe_path(relative_path)
    return value


def rewrite_upload_reference(
    value: object,
    tenant_id: object,
    object_key: bool = False,
) -> str:
    """Rewrite one local upload URL or object key under a tenant prefix."""

    safe_tenant_id = validate_tenant_segment(tenant_id)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('file reference must be a non-empty string path')

    parts = urlsplit(value)
    if parts.scheme.lower() in UNCHANGED_SCHEMES:
        return value
    if parts.scheme:
        raise ValueError('file reference uses an unsupported URL scheme')
    if value.startswith('/api/'):
        return _validate_application_url(value)
    if value.startswith('/uploads/'):
        return _rewrite_upload_url(value, safe_tenant_id)

    if not parts.path:
        raise ValueError('file reference must contain a non-empty path')
    if object_key:
        return _rewrite_object_key(value, safe_tenant_id)

    _reject_unsafe_path(parts.path)
    return value


def rewrite_nested_file_references(
    value: object,
    tenant_id: object,
    *,
    max_depth: int = 64,
    max_nodes: int = 100000,
) -> object:
    """Return a copy with nested attachment references scoped to one tenant."""

    safe_tenant_id = validate_tenant_segment(tenant_id)
    if (
        isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or max_depth < 0
    ):
        raise ValueError('max_depth must be a non-negative integer')
    if (
        isinstance(max_nodes, bool)
        or not isinstance(max_nodes, int)
        or max_nodes < 1
    ):
        raise ValueError('max_nodes must be a positive integer')

    active_containers: set[int] = set()
    visited_nodes = 0

    def rewrite(
        current: object,
        *,
        key: str | None = None,
        depth: int = 0,
        rewrite_files: bool = True,
    ) -> object:
        nonlocal visited_nodes
        visited_nodes += 1
        if visited_nodes > max_nodes:
            raise ValueError('nested file references exceed the node limit')
        if depth > max_depth:
            raise ValueError('nested file references exceed the depth limit')

        if isinstance(current, (dict, list)):
            container_id = id(current)
            if container_id in active_containers:
                raise ValueError('nested file references contain a cycle')
            active_containers.add(container_id)
            try:
                if isinstance(current, dict):
                    return {
                        child_key: rewrite(
                            child_value,
                            key=child_key,
                            depth=depth + 1,
                            rewrite_files=(
                                rewrite_files
                                and child_key not in PAGE_LINK_KEYS
                            ),
                        )
                        for child_key, child_value in current.items()
                    }
                return [
                    rewrite(
                        item,
                        depth=depth + 1,
                        rewrite_files=rewrite_files,
                    )
                    for item in current
                ]
            finally:
                active_containers.remove(container_id)
        if not isinstance(current, str):
            return current
        if not rewrite_files:
            return current
        if key in OBJECT_KEY_KEYS:
            return rewrite_upload_reference(
                current,
                safe_tenant_id,
                object_key=True,
            )
        if key in ATTACHMENT_URL_KEYS or current.startswith('/uploads/'):
            return rewrite_upload_reference(current, safe_tenant_id)
        return current

    return rewrite(value)
