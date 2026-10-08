"""Concrete Windows/Docker runtime for a consistent legacy snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import time

from ops.legacy_snapshot import (
    SourceInventory,
    build_snapshot_archive,
    build_source_service_command,
    execute_snapshot_lifecycle,
    inspect_source_inventory,
    prove_source_project,
    sync_tree,
)
from ops.operation_common import (
    OperationSafetyError,
    ensure_relative_member,
    sha256_file,
    validate_runtime_id,
    write_atomic_json,
)
from services.legacy_tenant_migration import MYSQL_IDENTIFIER_RE


TOOLING_PATHS = (
    'migrate-first-tenant.sh',
    'hpt-release.sh',
    'docker-compose.release.yml',
    'backend-python/requirements.txt',
    'backend-python/ops/__init__.py',
    'backend-python/ops/operation_common.py',
    'backend-python/ops/legacy_snapshot.py',
    'backend-python/ops/server_migration.py',
    'backend-python/ops/server_prepare.py',
    'backend-python/ops/server_internal.py',
    'backend-python/ops/candidate_tenant.py',
    'backend-python/ops/release_bundle.py',
    'backend-python/ops/release_manager.py',
    'backend-python/ops/release_transport.py',
    'backend-python/scripts/hpt_release.py',
    'backend-python/scripts/server_first_tenant_migration.py',
    'backend-python/scripts/server_migration_internal.py',
    'backend-python/scripts/restore_legacy_data.py',
    'backend-python/services/legacy_tenant_files.py',
    'backend-python/services/legacy_tenant_migration.py',
    'docs/data-restore-runbook.md',
)
MIGRATION_TOOLKIT_PATHS = (
    'migrate-first-tenant.sh',
    'hpt-release.sh',
    'docker-compose.release.yml',
    'backend-python/requirements.txt',
    'backend-python/ops/__init__.py',
    'backend-python/ops/operation_common.py',
    'backend-python/ops/server_migration.py',
    'backend-python/ops/server_prepare.py',
    'backend-python/ops/server_internal.py',
    'backend-python/ops/candidate_tenant.py',
    'backend-python/ops/release_bundle.py',
    'backend-python/ops/release_manager.py',
    'backend-python/ops/release_transport.py',
    'backend-python/scripts/hpt_release.py',
    'backend-python/scripts/server_first_tenant_migration.py',
    'backend-python/scripts/server_migration_internal.py',
    'backend-python/scripts/restore_legacy_data.py',
    'backend-python/services/legacy_tenant_files.py',
    'backend-python/services/legacy_tenant_migration.py',
    'docs/data-restore-runbook.md',
)


@dataclass(frozen=True)
class LocalSnapshotPaths:
    output_root: Path
    staging_root: Path
    snapshot_root: Path
    final_snapshot_root: Path
    archive_path: Path
    archive_sha256_path: Path

    @classmethod
    def build(cls, output_root: Path, snapshot_id: str) -> 'LocalSnapshotPaths':
        safe_snapshot_id = validate_runtime_id(snapshot_id)
        root = Path(output_root).resolve(strict=False)
        staging = root / f'.{safe_snapshot_id}.staging'
        final_root = root / f'first-tenant-snapshot-{safe_snapshot_id}'
        archive = root / f'first-tenant-snapshot-{safe_snapshot_id}.zip'
        sidecar = archive.with_name(archive.name + '.sha256')
        for path in (staging, final_root, archive, sidecar):
            if path.exists() or path.is_symlink():
                raise FileExistsError(path)
        return cls(
            output_root=root,
            staging_root=staging,
            snapshot_root=staging / 'snapshot-data',
            final_snapshot_root=final_root,
            archive_path=archive,
            archive_sha256_path=sidecar,
        )


def _copy_allowlisted_file(
    repo_root: Path,
    relative_path: str,
    destination: Path,
) -> None:
    source = repo_root.joinpath(*relative_path.split('/'))
    if source.is_symlink() or not source.is_file():
        raise OperationSafetyError(
            f'snapshot tooling source is missing or unsafe: {relative_path}'
        )
    try:
        source.resolve(strict=True).relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise OperationSafetyError(
            f'snapshot tooling source escapes repository: {relative_path}'
        ) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as input_file, destination.open('xb') as output:
        shutil.copyfileobj(input_file, output, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())


def copy_snapshot_tooling(
    repo_root: Path,
    snapshot_root: Path,
) -> tuple[str, ...]:
    repository = Path(repo_root).resolve(strict=False)
    destination_root = Path(snapshot_root)
    copied: list[str] = []
    for relative_path in TOOLING_PATHS:
        destination_relative = f'server-migration/{relative_path}'
        _copy_allowlisted_file(
            repository,
            relative_path,
            destination_root.joinpath(*destination_relative.split('/')),
        )
        copied.append(destination_relative)
    for relative_path in MIGRATION_TOOLKIT_PATHS:
        destination_relative = f'migration-toolkit/{relative_path}'
        _copy_allowlisted_file(
            repository,
            relative_path,
            destination_root.joinpath(*destination_relative.split('/')),
        )
        copied.append(destination_relative)
    return tuple(sorted(copied))


def build_source_row_count_command(
    *,
    docker_command: str,
    mysql_container: str,
    table_name: str,
) -> tuple[str, ...]:
    if (
        not isinstance(table_name, str)
        or MYSQL_IDENTIFIER_RE.fullmatch(table_name) is None
    ):
        raise OperationSafetyError('legacy row-count table name is invalid')
    return (
        docker_command,
        'exec',
        mysql_container,
        'sh',
        '-lc',
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N '
        f'-e "SELECT COUNT(*) FROM {table_name}" "$MYSQL_DATABASE"',
    )


class LegacySnapshotActions:
    def __init__(
        self,
        *,
        runner,
        source_root: Path,
        repo_root: Path,
        paths: LocalSnapshotPaths,
        snapshot_id: str,
        docker_command: str,
        project: str = 'hengpintong-next',
    ) -> None:
        if project != 'hengpintong-next':
            raise OperationSafetyError('legacy snapshot project must be hengpintong-next')
        self.runner = runner
        self.source_root = Path(source_root).resolve(strict=True)
        self.repo_root = Path(repo_root).resolve(strict=True)
        self.paths = paths
        self.snapshot_id = validate_runtime_id(snapshot_id)
        self.docker_command = docker_command
        self.project = project
        self.proof_result = None
        self.initial_inventory = None
        self.final_inventory = None

    @property
    def _compose_prefix(self) -> tuple[str, ...]:
        return (
            self.docker_command,
            'compose',
            '--env-file',
            str(self.source_root / '.env'),
            '-p',
            self.project,
            '-f',
            str(self.source_root / 'docker-compose.yml'),
        )

    def _run_required(self, argv, *, timeout=600):
        result = self.runner.run(
            tuple(argv),
            cwd=self.source_root,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'legacy snapshot command failed with code {result.returncode}'
            )
        return result

    def _export_minio(self, *, replace_changed: bool) -> None:
        report_path = self.paths.snapshot_root / 'minio-export-report.json'
        report_path.unlink(missing_ok=True)
        arguments = [
            'minio-export',
            '--bucket',
            self.initial_inventory.bucket,
            '--output-root',
            '/snapshot/minio-export',
        ]
        if replace_changed:
            arguments.extend(['--replace-changed', '--prune'])
        self._run_required(
            (
                *self._compose_prefix,
                'run',
                '--rm',
                '--no-deps',
                '-T',
                '-e',
                'PYTHONPATH=/migration-code',
                '-v',
                f'{self.repo_root / "backend-python"}:/migration-code:ro',
                '-v',
                f'{self.paths.snapshot_root}:/snapshot',
                'backend',
                'python',
                '/migration-code/scripts/server_migration_internal.py',
                *arguments,
            ),
            timeout=7200,
        )

    def prove(self) -> None:
        self.proof_result = prove_source_project(
            self.runner,
            project=self.project,
            docker_command=self.docker_command,
        )
        self.initial_inventory = inspect_source_inventory(
            self.runner,
            source_root=self.source_root,
            project=self.project,
            docker_command=self.docker_command,
        )
        self.paths.output_root.mkdir(parents=True, exist_ok=True)
        self.paths.staging_root.mkdir()
        self.paths.snapshot_root.mkdir()

    def precopy(self) -> None:
        sync_tree(
            self.source_root / 'backend-python' / 'uploads',
            self.paths.snapshot_root / 'uploads-export',
        )
        self._export_minio(replace_changed=False)

    def stop(self) -> None:
        self._run_required(
            build_source_service_command(
                action='stop',
                project=self.project,
                source_root=self.source_root,
                docker_command=self.docker_command,
            ),
            timeout=600,
        )

    def verify_stopped(self) -> None:
        result = self._run_required(
            (
                self.docker_command,
                'ps',
                '-a',
                '--filter',
                f'label=com.docker.compose.project={self.project}',
                '--format',
                '{{.Status}}|{{.Label "com.docker.compose.service"}}',
            )
        )
        rows = {}
        for line in result.stdout.splitlines():
            status_value, separator, service = line.partition('|')
            if not separator or service in rows:
                raise OperationSafetyError('legacy stopped-state proof is invalid')
            rows[service] = status_value
        if set(rows) != {'backend', 'minio', 'mysql', 'nginx'}:
            raise OperationSafetyError('legacy stopped-state services are invalid')
        if rows['backend'].startswith('Up') or rows['nginx'].startswith('Up'):
            raise OperationSafetyError('legacy write services did not stop')
        for service in ('mysql', 'minio'):
            if '(healthy)' not in rows[service]:
                raise OperationSafetyError(
                    'legacy data service is not healthy during snapshot'
                )

    def final_sync(self) -> None:
        sync_tree(
            self.source_root / 'backend-python' / 'uploads',
            self.paths.snapshot_root / 'uploads-export',
            replace_changed=True,
            prune=True,
        )
        self._export_minio(replace_changed=True)

    def dump(self) -> None:
        if self.proof_result is None:
            raise OperationSafetyError('legacy source proof is unavailable')
        result = self.runner.run_to_file(
            (
                self.docker_command,
                'exec',
                self.proof_result.container_for('mysql'),
                'sh',
                '-lc',
                'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" '
                '--single-transaction --routines --triggers --events '
                '--hex-blob --set-gtid-purged=OFF "$MYSQL_DATABASE"',
            ),
            self.paths.snapshot_root / 'legacy-full.sql',
            cwd=self.source_root,
            timeout=7200,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'legacy MySQL dump failed with code {result.returncode}'
            )

    def _source_row_counts(self, table_names: tuple[str, ...]) -> dict[str, int]:
        counts = {}
        for table_name in table_names:
            if MYSQL_IDENTIFIER_RE.fullmatch(table_name) is None:
                raise OperationSafetyError('legacy dump table name is invalid')
            result = self._run_required(
                build_source_row_count_command(
                    docker_command=self.docker_command,
                    mysql_container=self.proof_result.container_for('mysql'),
                    table_name=table_name,
                )
            )
            try:
                count = int(result.stdout.strip())
            except (TypeError, ValueError) as exc:
                raise OperationSafetyError('legacy row count is invalid') from exc
            if count < 0:
                raise OperationSafetyError('legacy row count is negative')
            counts[table_name] = count
        return counts

    @staticmethod
    def _file_manifest(root: Path, label: str) -> list[dict[str, object]]:
        rows = []
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise OperationSafetyError('snapshot file manifest rejects symlinks')
            if path.is_dir():
                continue
            relative_name = path.relative_to(root).as_posix()
            ensure_relative_member(relative_name)
            rows.append(
                {
                    'root': label,
                    'path': relative_name,
                    'sizeBytes': path.stat().st_size,
                    'sha256': sha256_file(path),
                }
            )
        return rows

    def verify(self) -> None:
        from scripts.restore_legacy_data import inspect_dump
        from services.tenancy import MANAGED_MODULE_KEYS

        dump_tables = inspect_dump(self.paths.snapshot_root / 'legacy-full.sql')
        if len(dump_tables) != self.initial_inventory.table_count:
            raise OperationSafetyError('legacy dump table count mismatch')
        row_counts = self._source_row_counts(tuple(sorted(dump_tables)))
        write_atomic_json(
            self.paths.snapshot_root / 'source-row-counts.json',
            {'tables': row_counts},
            overwrite=False,
        )
        file_rows = [
            *self._file_manifest(
                self.paths.snapshot_root / 'uploads-export',
                'uploads-export',
            ),
            *self._file_manifest(
                self.paths.snapshot_root / 'minio-export',
                'minio-export',
            ),
        ]
        upload_rows = [row for row in file_rows if row['root'] == 'uploads-export']
        minio_rows = [row for row in file_rows if row['root'] == 'minio-export']
        minio_export_report = json.loads(
            (self.paths.snapshot_root / 'minio-export-report.json').read_text(
                encoding='utf-8'
            )
        )
        self.final_inventory = SourceInventory(
            table_count=len(dump_tables),
            upload_files=len(upload_rows),
            upload_bytes=sum(row['sizeBytes'] for row in upload_rows),
            object_count=minio_export_report.get('file_count'),
            object_bytes=minio_export_report.get('total_bytes'),
            bucket=minio_export_report.get('bucket'),
        )
        if self.final_inventory.table_count != self.initial_inventory.table_count:
            raise OperationSafetyError('legacy table count changed during snapshot')
        if self.final_inventory.upload_files < self.initial_inventory.upload_files:
            raise OperationSafetyError('legacy upload file count decreased')
        if self.final_inventory.object_count < self.initial_inventory.object_count:
            raise OperationSafetyError('legacy object count decreased')
        write_atomic_json(
            self.paths.snapshot_root / 'file-manifest.json',
            {'files': file_rows},
            overwrite=False,
        )
        company_name = '恒聘通首个正式企业'
        company_result = self.runner.run(
            (
                self.docker_command,
                'exec',
                self.proof_result.container_for('mysql'),
                'sh',
                '-lc',
                'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N '
                '-e "SELECT value FROM settings WHERE settings.key='
                "'company_name' LIMIT 1\" \"$MYSQL_DATABASE\"",
            ),
            cwd=self.source_root,
            timeout=300,
        )
        if company_result.returncode == 0 and company_result.stdout.strip():
            company_name = company_result.stdout.strip()[:160]
        write_atomic_json(
            self.paths.snapshot_root / 'tenant-profile.json',
            {
                'enabledModuleKeys': list(MANAGED_MODULE_KEYS),
                'name': company_name,
                'planCode': 'enterprise',
                'slug': 'HPT-00000001',
            },
            overwrite=False,
        )
        self.paths.snapshot_root.joinpath('minio-export-report.json').unlink(
            missing_ok=True
        )
        copy_snapshot_tooling(self.repo_root, self.paths.snapshot_root)
        write_atomic_json(
            self.paths.snapshot_root / 'snapshot-manifest.json',
            {
                'externalGoLiveEvidenceAccepted': False,
                'format': 'hengpintong-first-tenant-snapshot-v1',
                'snapshotId': self.snapshot_id,
                'sourceProject': self.project,
                'sourceTableCount': len(dump_tables),
                'status': 'verified',
            },
            overwrite=False,
        )

    def start(self) -> None:
        self._run_required(
            build_source_service_command(
                action='start',
                project=self.project,
                source_root=self.source_root,
                docker_command=self.docker_command,
            ),
            timeout=600,
        )

    def health(self) -> None:
        last_error = None
        for _attempt in range(60):
            health = self.runner.run(
                ('curl', '-fsS', 'http://localhost:18080/api/health'),
                timeout=20,
            )
            ready = self.runner.run(
                ('curl', '-fsS', 'http://localhost:18080/api/ready'),
                timeout=20,
            )
            if health.returncode == 0 and ready.returncode == 0:
                try:
                    health_value = json.loads(health.stdout)
                    ready_value = json.loads(ready.stdout)
                except ValueError as exc:
                    last_error = exc
                else:
                    if health_value.get('ok') is True and ready_value.get('ok') is True:
                        return
            time.sleep(2)
        raise OperationSafetyError('legacy source did not recover healthy') from last_error

    def promote(self) -> None:
        package_root = self.paths.staging_root / 'package'
        package_root.mkdir()
        staged_archive = package_root / self.paths.archive_path.name
        built = build_snapshot_archive(self.paths.snapshot_root, staged_archive)
        os.rename(self.paths.snapshot_root, self.paths.final_snapshot_root)
        os.rename(built.archive_path, self.paths.archive_path)
        os.rename(built.sha256_path, self.paths.archive_sha256_path)
        package_root.rmdir()
        self.paths.staging_root.rmdir()


def run_consistent_snapshot(actions: LegacySnapshotActions):
    return execute_snapshot_lifecycle(actions)
