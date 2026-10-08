"""Immutable server release installation, switching, and rollback."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile

from ops.operation_common import (
    OperationSafetyError,
    sha256_file,
    validate_runtime_id,
    write_atomic_json,
)
from ops.release_bundle import (
    DIGEST_RE,
    IMAGE_RE,
    RELEASE_PREFIX,
    ReleaseManifest,
    WorkspaceFile,
)


@dataclass(frozen=True)
class ServerLayout:
    deployment_root: Path

    def __post_init__(self) -> None:
        root = Path(self.deployment_root)
        if root.is_symlink():
            raise OperationSafetyError('deployment root must not be a symlink')

    @property
    def shared_root(self) -> Path:
        return Path(self.deployment_root) / 'shared'

    @property
    def environment_path(self) -> Path:
        return self.shared_root / '.env'

    @property
    def certs_root(self) -> Path:
        return self.shared_root / 'certs'

    @property
    def uploads_root(self) -> Path:
        return self.shared_root / 'uploads'

    @property
    def locks_root(self) -> Path:
        return self.shared_root / 'locks'

    @property
    def state_root(self) -> Path:
        return self.shared_root / 'state'

    @property
    def releases_root(self) -> Path:
        return Path(self.deployment_root) / 'releases'

    @property
    def incoming_root(self) -> Path:
        return Path(self.deployment_root) / 'incoming'

    @property
    def current_link(self) -> Path:
        return Path(self.deployment_root) / 'current'

    @property
    def release_state_path(self) -> Path:
        return self.state_root / 'release-state.json'

    def ensure_directories(self) -> None:
        root = Path(self.deployment_root)
        root.mkdir(parents=True, exist_ok=True)
        for directory, mode in (
            (self.shared_root, 0o700),
            (self.certs_root, 0o700),
            (self.uploads_root, 0o750),
            (self.locks_root, 0o700),
            (self.state_root, 0o700),
            (self.releases_root, 0o755),
            (self.incoming_root, 0o700),
        ):
            if directory.is_symlink():
                raise OperationSafetyError(
                    f'server layout directory must not be a symlink: {directory.name}'
                )
            directory.mkdir(exist_ok=True)
            os.chmod(directory, mode)

    def release_root(self, release_id: str) -> Path:
        return self.releases_root / validate_runtime_id(release_id)

    def create_release_directory(self, release_id: str) -> Path:
        release = self.release_root(release_id)
        release.mkdir(mode=0o755, parents=False, exist_ok=False)
        os.chmod(release, 0o755)
        return release


@dataclass(frozen=True)
class InstalledRelease:
    release_id: str
    release_root: Path
    app_root: Path
    backend_image: str
    backend_digest: str

    def __post_init__(self) -> None:
        validate_runtime_id(self.release_id)
        if IMAGE_RE.fullmatch(self.backend_image) is None:
            raise OperationSafetyError('installed backend image is invalid')
        if DIGEST_RE.fullmatch(self.backend_digest) is None:
            raise OperationSafetyError('installed backend digest is invalid')
        release_root = Path(self.release_root)
        app_root = Path(self.app_root)
        try:
            app_root.resolve(strict=False).relative_to(
                release_root.resolve(strict=False)
            )
        except ValueError as exc:
            raise OperationSafetyError(
                'installed app root must stay inside release root'
            ) from exc

    @property
    def metadata_path(self) -> Path:
        return Path(self.release_root) / 'installed-release.json'

    def to_dict(self) -> dict[str, str]:
        return {
            'appRoot': str(Path(self.app_root).resolve(strict=False)),
            'backendDigest': self.backend_digest,
            'backendImage': self.backend_image,
            'releaseId': self.release_id,
            'releaseRoot': str(Path(self.release_root).resolve(strict=False)),
        }

    @classmethod
    def from_dict(cls, value: object) -> 'InstalledRelease':
        expected = {
            'appRoot', 'backendDigest', 'backendImage', 'releaseId', 'releaseRoot'
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise OperationSafetyError('installed release metadata is invalid')
        return cls(
            release_id=value['releaseId'],
            release_root=Path(value['releaseRoot']),
            app_root=Path(value['appRoot']),
            backend_image=value['backendImage'],
            backend_digest=value['backendDigest'],
        )


@dataclass(frozen=True)
class ReleaseState:
    current: InstalledRelease
    previous: InstalledRelease

    def to_dict(self) -> dict[str, object]:
        return {
            'current': self.current.to_dict(),
            'previous': self.previous.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> 'ReleaseState':
        if not isinstance(value, dict) or set(value) != {'current', 'previous'}:
            raise OperationSafetyError('release state is invalid')
        return cls(
            current=InstalledRelease.from_dict(value['current']),
            previous=InstalledRelease.from_dict(value['previous']),
        )


def write_installed_release_metadata(release: InstalledRelease) -> None:
    write_atomic_json(release.metadata_path, release.to_dict(), overwrite=False)


def load_installed_release_metadata(path: Path) -> InstalledRelease:
    metadata_path = Path(path)
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise OperationSafetyError('installed release metadata is missing')
    try:
        value = json.loads(metadata_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('installed release metadata is invalid') from exc
    release = InstalledRelease.from_dict(value)
    if release.metadata_path.resolve(strict=False) != metadata_path.resolve(strict=True):
        raise OperationSafetyError('installed release metadata path mismatch')
    return release


def _current_release(layout: ServerLayout) -> InstalledRelease:
    if not layout.current_link.is_symlink():
        raise OperationSafetyError('current release link is missing')
    try:
        app_root = layout.current_link.resolve(strict=True)
    except OSError as exc:
        raise OperationSafetyError('current release link is broken') from exc
    return load_installed_release_metadata(
        app_root.parent / 'installed-release.json'
    )


def _switch_current(layout: ServerLayout, release: InstalledRelease) -> None:
    if not Path(release.app_root).is_dir():
        raise OperationSafetyError('release app directory is missing')
    temporary = layout.current_link.with_name(
        f'.current.{release.release_id}.tmp'
    )
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(temporary)
    os.symlink(
        str(Path(release.app_root).resolve(strict=True)),
        temporary,
        target_is_directory=True,
    )
    try:
        os.replace(temporary, layout.current_link)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _load_release_state(layout: ServerLayout) -> ReleaseState:
    path = layout.release_state_path
    if path.is_symlink() or not path.is_file():
        raise OperationSafetyError('release state is missing')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('release state is invalid') from exc
    return ReleaseState.from_dict(value)


def _write_release_state(layout: ServerLayout, state: ReleaseState) -> None:
    write_atomic_json(layout.release_state_path, state.to_dict(), overwrite=True)


def apply_installed_release(
    layout: ServerLayout,
    incoming: InstalledRelease,
    *,
    actions,
) -> ReleaseState:
    previous = _current_release(layout)
    if incoming.release_id <= previous.release_id:
        raise OperationSafetyError('incoming release ID must be newer than current')
    _switch_current(layout, incoming)
    try:
        actions.recreate_backend_and_nginx(incoming)
        actions.validate_release(incoming)
    except BaseException as apply_error:
        _switch_current(layout, previous)
        try:
            actions.recreate_backend_and_nginx(previous)
            actions.validate_release(previous)
        except BaseException as rollback_error:
            raise OperationSafetyError(
                'release apply and automatic rollback failed; state is unknown'
            ) from rollback_error
        raise OperationSafetyError(
            'release validation failed; restored previous release'
        ) from apply_error
    state = ReleaseState(current=incoming, previous=previous)
    _write_release_state(layout, state)
    return state


def rollback_release(layout: ServerLayout, *, actions) -> ReleaseState:
    state = _load_release_state(layout)
    if _current_release(layout) != state.current:
        raise OperationSafetyError('current link differs from release state')
    _switch_current(layout, state.previous)
    try:
        actions.recreate_backend_and_nginx(state.previous)
        actions.validate_release(state.previous)
    except BaseException as exc:
        _switch_current(layout, state.current)
        raise OperationSafetyError(
            'manual release rollback failed; current link was restored'
        ) from exc
    rolled_back = ReleaseState(
        current=state.previous,
        previous=state.current,
    )
    _write_release_state(layout, rolled_back)
    return rolled_back


def read_release_status(layout: ServerLayout, *, actions) -> dict[str, object]:
    state = _load_release_state(layout)
    current = _current_release(layout)
    if current != state.current:
        raise OperationSafetyError('current link differs from release state')
    return {
        'current': state.current.to_dict(),
        'previous': state.previous.to_dict(),
        'health': actions.read_health(state.current),
    }


def _verify_outer_hash(archive_path: Path, sidecar_path: Path) -> str:
    archive = Path(archive_path)
    sidecar = Path(sidecar_path)
    if archive.is_symlink() or not archive.is_file():
        raise OperationSafetyError('release archive is missing or unsafe')
    if sidecar.is_symlink() or not sidecar.is_file():
        raise OperationSafetyError('release checksum is missing or unsafe')
    try:
        value = sidecar.read_text(encoding='ascii')
    except (OSError, UnicodeError) as exc:
        raise OperationSafetyError('release outer checksum is invalid') from exc
    match = re.fullmatch(r'([0-9a-f]{64})  ([^\r\n]+)\r?\n?', value, re.ASCII)
    if match is None or match.group(2) != archive.name:
        raise OperationSafetyError('release outer checksum is invalid')
    from ops.operation_common import sha256_file

    actual = sha256_file(archive)
    if actual != match.group(1):
        raise OperationSafetyError('release outer checksum mismatch')
    return actual


def _zip_member_hash(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, 'r') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_payload_path(path: str) -> None:
    from ops.operation_common import ensure_relative_member

    ensure_relative_member(path)
    lowered = path.lower()
    if path == 'images/backend-image.tar':
        return
    if not path.startswith('app/'):
        raise OperationSafetyError('release payload path is not allowlisted')
    forbidden = (
        '/.env',
        '/certs/',
        '/uploads/',
        '/node_modules/',
        '/artifacts/',
    )
    if any(marker in f'/{lowered}' for marker in forbidden):
        raise OperationSafetyError('release payload path is prohibited')
    if lowered.endswith(('.key', '.crt', '.pem')):
        raise OperationSafetyError('release payload secret file is prohibited')


def _parse_release_manifest(value: object) -> ReleaseManifest:
    expected = {
        'architecture',
        'backendDigest',
        'backendImage',
        'format',
        'payload',
        'releaseId',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationSafetyError('release manifest fields are invalid')
    if value['format'] != 'hengpintong-offline-release-v1':
        raise OperationSafetyError('release manifest format is invalid')
    if not isinstance(value['payload'], list):
        raise OperationSafetyError('release manifest payload is invalid')
    items = []
    for row in value['payload']:
        if not isinstance(row, dict) or set(row) != {'path', 'sha256', 'sizeBytes'}:
            raise OperationSafetyError('release manifest payload row is invalid')
        _safe_payload_path(row['path'])
        items.append(
            WorkspaceFile(
                path=row['path'],
                size_bytes=row['sizeBytes'],
                sha256=row['sha256'],
            )
        )
    return ReleaseManifest(
        release_id=value['releaseId'],
        architecture=value['architecture'],
        backend_image=value['backendImage'],
        backend_digest=value['backendDigest'],
        payload=tuple(items),
    )


def verify_and_install_release(
    layout: ServerLayout,
    *,
    archive_path: Path,
    sidecar_path: Path,
    runner,
    current_release_id: str | None,
    available_bytes: int | None = None,
) -> InstalledRelease:
    archive_source = Path(archive_path)
    _verify_outer_hash(archive_source, Path(sidecar_path))
    try:
        archive = zipfile.ZipFile(archive_source, 'r')
    except (OSError, zipfile.BadZipFile) as exc:
        raise OperationSafetyError('release ZIP is invalid') from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise OperationSafetyError('release ZIP has duplicate members')
        by_name = {info.filename: info for info in infos}
        manifest_name = RELEASE_PREFIX + 'release-manifest.json'
        checksums_name = RELEASE_PREFIX + 'SHA256SUMS'
        if manifest_name not in by_name or checksums_name not in by_name:
            raise OperationSafetyError('release ZIP metadata is missing')
        for info in infos:
            from ops.operation_common import ensure_relative_member

            ensure_relative_member(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if info.create_system == 3 and stat.S_ISLNK(mode):
                raise OperationSafetyError('release ZIP symlink is prohibited')
            if info.is_dir() or not info.filename.startswith(RELEASE_PREFIX):
                raise OperationSafetyError('release ZIP member is invalid')
        try:
            manifest_value = json.loads(archive.read(by_name[manifest_name]))
        except (UnicodeError, ValueError) as exc:
            raise OperationSafetyError('release manifest JSON is invalid') from exc
        manifest = _parse_release_manifest(manifest_value)
        if current_release_id is not None:
            validate_runtime_id(current_release_id)
            if manifest.release_id <= current_release_id:
                raise OperationSafetyError('release ID is not newer than current')
        payload_names = {RELEASE_PREFIX + item.path for item in manifest.payload}
        if set(names) != payload_names | {manifest_name, checksums_name}:
            raise OperationSafetyError('release ZIP member list mismatch')
        try:
            checksum_text = archive.read(by_name[checksums_name]).decode('ascii')
        except UnicodeError as exc:
            raise OperationSafetyError('release SHA256SUMS is invalid') from exc
        checksum_rows = {}
        for line in checksum_text.splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line, re.ASCII)
            if match is None or match.group(2) in checksum_rows:
                raise OperationSafetyError('release SHA256SUMS is invalid')
            checksum_rows[match.group(2)] = match.group(1)
        expected_checksum_names = {
            *(item.path for item in manifest.payload),
            'release-manifest.json',
        }
        if set(checksum_rows) != expected_checksum_names:
            raise OperationSafetyError('release SHA256SUMS member list mismatch')
        for item in manifest.payload:
            info = by_name[RELEASE_PREFIX + item.path]
            if info.file_size != item.size_bytes:
                raise OperationSafetyError('release payload size mismatch')
            actual_hash = _zip_member_hash(archive, info)
            if actual_hash != item.sha256 or checksum_rows[item.path] != item.sha256:
                raise OperationSafetyError('release payload SHA-256 mismatch')
        manifest_hash = _zip_member_hash(archive, by_name[manifest_name])
        if checksum_rows['release-manifest.json'] != manifest_hash:
            raise OperationSafetyError('release manifest SHA-256 mismatch')
        required = {
            'app/docker-compose.yml',
            'app/docker-compose.saas-preview.yml',
            'app/docker-compose.release.yml',
            'images/backend-image.tar',
        }
        if not required.issubset(item.path for item in manifest.payload):
            raise OperationSafetyError('release required payload is missing')
        required_bytes = sum(info.file_size for info in infos) * 2
        free_bytes = (
            shutil.disk_usage(layout.deployment_root).free
            if available_bytes is None
            else available_bytes
        )
        if free_bytes < required_bytes:
            raise OperationSafetyError('insufficient disk space for release')

        if layout.release_state_path.is_file():
            backup_root = layout.state_root / 'backups'
            backup_root.mkdir(exist_ok=True)
            backup_path = backup_root / f'before-{manifest.release_id}.json'
            if backup_path.exists():
                raise FileExistsError(backup_path)
            backup_path.write_bytes(layout.release_state_path.read_bytes())
            os.chmod(backup_path, 0o600)

        release_root = layout.create_release_directory(manifest.release_id)
        try:
            for info in infos:
                relative_name = info.filename[len(RELEASE_PREFIX):]
                target = release_root.joinpath(*relative_name.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, 'r') as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(target, 0o755 if target.suffix == '.sh' else 0o644)
            for directory in (
                release_root,
                *(path for path in release_root.rglob('*') if path.is_dir()),
            ):
                os.chmod(directory, 0o755)
        except BaseException:
            shutil.rmtree(release_root, ignore_errors=True)
            raise

    image_tar = release_root / 'images' / 'backend-image.tar'
    load_result = runner.run(
        ('docker', 'load', '--input', str(image_tar)),
        timeout=7200,
    )
    if load_result.returncode != 0:
        raise OperationSafetyError('docker image load failed')
    inspect_result = runner.run(
        (
            'docker',
            'image',
            'inspect',
            '--format',
            '{{.Id}}|{{.Os}}|{{.Architecture}}',
            manifest.backend_image,
        ),
        timeout=300,
    )
    if inspect_result.returncode != 0:
        raise OperationSafetyError('loaded image inspection failed')
    fields = inspect_result.stdout.strip().split('|')
    if fields != [manifest.backend_digest, 'linux', 'amd64']:
        raise OperationSafetyError('loaded image digest or architecture mismatch')
    installed = InstalledRelease(
        release_id=manifest.release_id,
        release_root=release_root,
        app_root=release_root / 'app',
        backend_image=manifest.backend_image,
        backend_digest=manifest.backend_digest,
    )
    write_installed_release_metadata(installed)
    return installed


def _copy_tree_regular(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise OperationSafetyError(f'bootstrap directory is unsafe: {source.name}')
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o755)
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise OperationSafetyError('bootstrap copy rejects symlinks')
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(exist_ok=True)
            os.chmod(target, 0o755)
            continue
        if not path.is_file():
            raise OperationSafetyError('bootstrap copy accepts regular files only')
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open('rb') as input_file, target.open('xb') as output:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
        os.chmod(target, 0o644)


def _normalize_compose_image_id(value: object) -> str:
    if not isinstance(value, str):
        raise OperationSafetyError('legacy backend image cannot be proved')
    image_id = value.strip()
    if re.fullmatch(r'[0-9a-f]{64}', image_id):
        return f'sha256:{image_id}'
    if re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        return image_id
    raise OperationSafetyError('legacy backend image cannot be proved')


def _regular_tree_manifest(root: Path) -> tuple[tuple[str, int, str], ...]:
    source = Path(root)
    if not source.exists():
        return ()
    if source.is_symlink() or not source.is_dir():
        raise OperationSafetyError('legacy runtime directory is unsafe')
    rows = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise OperationSafetyError('legacy runtime directory has a symlink')
        if path.is_dir():
            continue
        if not path.is_file():
            raise OperationSafetyError('legacy runtime directory is unsafe')
        rows.append(
            (
                path.relative_to(source).as_posix(),
                path.stat().st_size,
                sha256_file(path),
            )
        )
    return tuple(rows)


def _legacy_uploads_source(source: Path) -> Path:
    uploads = Path(source) / 'outputs' / 'saas-docker-preview' / 'uploads'
    if not uploads.is_dir():
        uploads = Path(source) / 'backend-python' / 'uploads'
    return uploads


def _copy_regular_tree_contents(source: Path, destination: Path) -> None:
    root = Path(source)
    if not root.exists():
        return
    _regular_tree_manifest(root)
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        target = Path(destination) / relative
        if path.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def _copy_or_validate_legacy_runtime(
    layout: ServerLayout,
    source: Path,
) -> str:
    legacy_root = Path(source)
    source_environment = legacy_root / '.env'
    source_certs = legacy_root / 'certs'
    source_uploads = _legacy_uploads_source(legacy_root)
    destination_has_runtime = (
        layout.environment_path.exists()
        or any(layout.certs_root.iterdir())
        or any(layout.uploads_root.iterdir())
    )
    if destination_has_runtime:
        if (
            layout.environment_path.is_symlink()
            or not layout.environment_path.is_file()
            or layout.environment_path.read_bytes() != source_environment.read_bytes()
            or _regular_tree_manifest(layout.certs_root)
            != _regular_tree_manifest(source_certs)
            or _regular_tree_manifest(layout.uploads_root)
            != _regular_tree_manifest(source_uploads)
        ):
            raise OperationSafetyError(
                'existing shared runtime does not match legacy application'
            )
        result = 'reused'
    else:
        layout.environment_path.write_bytes(source_environment.read_bytes())
        os.chmod(layout.environment_path, 0o600)
        _copy_regular_tree_contents(source_certs, layout.certs_root)
        for path in layout.certs_root.rglob('*'):
            if path.is_file():
                os.chmod(path, 0o600)
        _copy_regular_tree_contents(source_uploads, layout.uploads_root)
        result = 'copied'

    os.chmod(layout.uploads_root, 0o750)
    for path in layout.uploads_root.rglob('*'):
        if path.is_dir():
            os.chmod(path, 0o750)
        elif path.is_file():
            os.chmod(path, 0o640)
    if os.name != 'nt' and os.geteuid() == 0:
        for path in (layout.uploads_root, *layout.uploads_root.rglob('*')):
            os.chown(path, 1001, 1001)
    return result


def bootstrap_legacy_layout(
    layout: ServerLayout,
    *,
    legacy_app_root: Path,
    release_override_source: Path,
    runner,
) -> ReleaseState:
    layout.ensure_directories()
    if layout.current_link.exists() or layout.current_link.is_symlink():
        raise OperationSafetyError('release layout is already bootstrapped')
    source = Path(legacy_app_root)
    if source.is_symlink() or not source.is_dir():
        raise OperationSafetyError('legacy application root is missing or unsafe')
    required_files = (
        '.env',
        'docker-compose.yml',
        'docker-compose.saas-preview.yml',
        'nginx-docker.conf',
    )
    for relative in required_files:
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise OperationSafetyError(f'legacy bootstrap file is missing: {relative}')

    compose_prefix = (
        'docker',
        'compose',
        '--env-file',
        str(source / '.env'),
        '-p',
        'hengpintong-saas-preview',
        '-f',
        str(source / 'docker-compose.yml'),
        '-f',
        str(source / 'docker-compose.saas-preview.yml'),
    )
    image_result = runner.run(
        (*compose_prefix, 'images', '-q', 'backend'),
        cwd=source,
        timeout=300,
    )
    if image_result.returncode != 0:
        raise OperationSafetyError('legacy backend image cannot be proved')
    image_id = _normalize_compose_image_id(image_result.stdout)
    inspect = runner.run(
        (
            'docker', 'image', 'inspect', '--format',
            '{{.Id}}|{{.Os}}|{{.Architecture}}', image_id,
        ),
        timeout=300,
    )
    if inspect.returncode != 0 or inspect.stdout.strip() != f'{image_id}|linux|amd64':
        raise OperationSafetyError('legacy backend image architecture is invalid')

    _copy_or_validate_legacy_runtime(layout, source)

    bootstrap_id = '19700101T000000Z'
    release_root = layout.create_release_directory(bootstrap_id)
    app_root = release_root / 'app'
    app_root.mkdir()
    os.chmod(app_root, 0o755)
    for relative in (
        'docker-compose.yml',
        'docker-compose.saas-preview.yml',
        'nginx-docker.conf',
        'init.sql',
        'init-readonly-user.sh',
    ):
        path = source / relative
        if path.is_file() and not path.is_symlink():
            destination = app_root / relative
            destination.write_bytes(path.read_bytes())
            os.chmod(destination, 0o644)
    override = Path(release_override_source)
    if override.is_symlink() or not override.is_file():
        raise OperationSafetyError('release Compose override is missing')
    (app_root / 'docker-compose.release.yml').write_bytes(override.read_bytes())
    os.chmod(app_root / 'docker-compose.release.yml', 0o644)
    frontend_source = source / 'outputs' / 'saas-docker-preview' / 'dist-prod'
    if not frontend_source.is_dir():
        frontend_source = source / 'dist-prod'
    _copy_tree_regular(frontend_source, app_root / 'dist-prod')
    installed = InstalledRelease(
        release_id=bootstrap_id,
        release_root=release_root,
        app_root=app_root,
        backend_image=image_id,
        backend_digest=image_id,
    )
    write_installed_release_metadata(installed)
    _switch_current(layout, installed)
    state = ReleaseState(current=installed, previous=installed)
    _write_release_state(layout, state)
    return state


class DockerReleaseActions:
    def __init__(self, *, layout: ServerLayout, runner) -> None:
        self.layout = layout
        self.runner = runner

    def _compose_prefix(self, release: InstalledRelease) -> tuple[str, ...]:
        app = Path(release.app_root)
        return (
            'docker',
            'compose',
            '--env-file',
            str(self.layout.environment_path),
            '-p',
            'hengpintong-saas-preview',
            '-f',
            str(app / 'docker-compose.yml'),
            '-f',
            str(app / 'docker-compose.saas-preview.yml'),
            '-f',
            str(app / 'docker-compose.release.yml'),
        )

    def _environment(self, release: InstalledRelease) -> dict[str, str]:
        return {
            'HPT_BACKEND_IMAGE': release.backend_image,
            'HPT_SHARED_ROOT': str(self.layout.shared_root.resolve(strict=True)),
        }

    def recreate_backend_and_nginx(self, release: InstalledRelease) -> None:
        from ops.legacy_snapshot import prove_source_project

        prove_source_project(
            self.runner,
            project='hengpintong-saas-preview',
            docker_command='docker',
            require_healthy=False,
        )
        result = self.runner.run(
            (
                *self._compose_prefix(release),
                'up', '-d', '--no-deps', '--no-build', '--force-recreate',
                'backend', 'nginx',
            ),
            cwd=release.app_root,
            env=self._environment(release),
            timeout=900,
        )
        if result.returncode != 0:
            raise OperationSafetyError('release service recreation failed')

    def _health(self, release: InstalledRelease) -> dict[str, bool]:
        if release.release_id == '19700101T000000Z':
            command = (
                *self._compose_prefix(release),
                'exec', '-T', 'backend', 'sh', '-lc',
                'set -eu; '
                'curl -fsS "http://127.0.0.1:${PORT:-18888}/api/health" >/dev/null; '
                'curl -fsS "http://127.0.0.1:${PORT:-18888}/api/ready" >/dev/null',
            )
        else:
            command = (
                *self._compose_prefix(release),
                'exec', '-T', 'backend', 'python',
                '/app/scripts/release_health_check.py',
            )
        result = self.runner.run(
            command,
            cwd=release.app_root,
            env=self._environment(release),
            timeout=300,
        )
        if result.returncode != 0:
            return {'apiHealth': False, 'apiReady': False}
        if release.release_id == '19700101T000000Z':
            return {'apiHealth': True, 'apiReady': True}
        try:
            value = json.loads(result.stdout)
        except ValueError:
            return {'apiHealth': False, 'apiReady': False}
        return value

    def validate_release(self, release: InstalledRelease) -> None:
        health = self._health(release)
        if not all(health.values()):
            raise OperationSafetyError('release health validation failed')

    def read_health(self, release: InstalledRelease) -> dict[str, bool]:
        return self._health(release)
