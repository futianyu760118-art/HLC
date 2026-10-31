"""Concrete Docker runtime for two-phase first-tenant preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Mapping, Sequence

from ops.legacy_snapshot import prove_source_project, sync_tree
from ops.operation_common import (
    OperationSafetyError,
    sha256_file,
    validate_runtime_id,
    write_atomic_json,
)
from ops.server_migration import (
    BUCKET_RE,
    DATABASE_RE,
    PrepareConfig,
    PreparePlan,
    PreparedMigrationState,
    verify_snapshot_package,
    write_prepared_state,
)


OPERATION_CONTAINER_USER = '0:0'


@dataclass(frozen=True)
class ActiveTargets:
    database: str
    readonly_database: str
    bucket: str


@dataclass(frozen=True)
class ServerTargetNames:
    stage_database: str
    candidate_database: str
    restore_proof_database: str
    candidate_bucket: str
    restore_proof_bucket: str

    @classmethod
    def for_snapshot(cls, snapshot_id: str) -> 'ServerTargetNames':
        safe_snapshot_id = validate_runtime_id(snapshot_id)
        lowered = safe_snapshot_id.lower()
        return cls(
            stage_database=f'legacy_stage_{safe_snapshot_id}',
            candidate_database=f'hrm_candidate_{safe_snapshot_id}',
            restore_proof_database=f'hrm_restoreproof_{safe_snapshot_id}',
            candidate_bucket=f'hrm-candidate-{lowered}',
            restore_proof_bucket=f'hrm-restoreproof-{lowered}',
        )


def read_active_targets(environment_path: Path) -> ActiveTargets:
    path = Path(environment_path)
    if path.is_symlink() or not path.is_file():
        raise OperationSafetyError('active environment is missing or unsafe')
    values: dict[str, str] = {}
    expected = ('DB_NAME', 'DB_READONLY_NAME', 'MINIO_BUCKET')
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as exc:
        raise OperationSafetyError('active environment cannot be read') from exc
    for line in lines:
        for key in expected:
            prefix = f'{key}='
            if not line.startswith(prefix):
                continue
            if key in values:
                raise OperationSafetyError(
                    f'active environment contains duplicate {key}'
                )
            values[key] = line[len(prefix):]
    if set(values) != set(expected):
        raise OperationSafetyError('active environment target values are missing')
    if DATABASE_RE.fullmatch(values['DB_NAME']) is None:
        raise OperationSafetyError('active database name is invalid')
    if DATABASE_RE.fullmatch(values['DB_READONLY_NAME']) is None:
        raise OperationSafetyError('active read-only database name is invalid')
    if BUCKET_RE.fullmatch(values['MINIO_BUCKET']) is None:
        raise OperationSafetyError('active bucket name is invalid')
    return ActiveTargets(
        database=values['DB_NAME'],
        readonly_database=values['DB_READONLY_NAME'],
        bucket=values['MINIO_BUCKET'],
    )


class ServerPrepareActions:
    """Execute prepare steps while leaving active targets untouched."""

    def __init__(
        self,
        *,
        runner,
        config: PrepareConfig,
        plan: PreparePlan,
        code_root: Path,
    ) -> None:
        self.runner = runner
        self.config = config
        self.plan = plan
        self.code_root = Path(code_root).resolve(strict=True)
        if self.code_root.is_symlink() or not (
            self.code_root / 'backend-python' / 'scripts' / 'server_migration_internal.py'
        ).is_file():
            raise OperationSafetyError('server migration code root is incomplete')
        self.operation_root = Path(config.operation_root)
        self.names = ServerTargetNames.for_snapshot(config.snapshot_id)
        self.proof = None
        self.targets: ActiveTargets | None = None
        self.verified_package = None
        self.candidate_container: str | None = None

    def _active_runtime_directory(
        self,
        configured_path: Path | None,
        fallback_paths: Sequence[Path],
        *,
        owner: str,
    ) -> Path:
        if configured_path is not None:
            candidate = Path(configured_path)
            if candidate.is_symlink() or not candidate.is_dir():
                raise OperationSafetyError(f'{owner} is missing or unsafe')
            return candidate.resolve(strict=True)

        for candidate in fallback_paths:
            path = Path(candidate)
            if path.is_symlink():
                raise OperationSafetyError(f'{owner} fallback is unsafe')
            if path.is_dir():
                return path.resolve(strict=True)
        return Path(fallback_paths[0])

    def _active_uploads_path(self) -> Path:
        app_root = Path(self.config.app_root)
        return self._active_runtime_directory(
            self.config.uploads_path,
            (
                app_root / 'outputs' / 'saas-docker-preview' / 'uploads',
                app_root / 'backend-python' / 'uploads',
            ),
            owner='active uploads directory',
        )

    def _active_certs_path(self) -> Path:
        return self._active_runtime_directory(
            self.config.certs_path,
            (Path(self.config.app_root) / 'certs',),
            owner='active certificates directory',
        )

    def run_prepare_step(self, step) -> None:
        handler = getattr(self, f'_step_{step.name}', None)
        if handler is None:
            raise OperationSafetyError(f'unknown prepare step: {step.name}')
        handler()

    def _run_required(
        self,
        argv: Sequence[str],
        *,
        timeout: int = 600,
    ):
        result = self.runner.run(
            tuple(argv),
            cwd=Path(self.config.app_root),
            timeout=timeout,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'prepare command failed with code {result.returncode}'
            )
        return result

    def _mysql_exec(self, sql: str) -> None:
        self._run_required(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_SQL={sql}',
                'mysql',
                'sh',
                '-lc',
                'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "$HPT_SQL"',
            )
        )

    def _mysql_query_int(self, sql: str) -> int:
        result = self._run_required(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_SQL={sql}',
                'mysql',
                'sh',
                '-lc',
                'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "$HPT_SQL"',
            )
        )
        try:
            value = int(result.stdout.strip())
        except (TypeError, ValueError) as exc:
            raise OperationSafetyError('MySQL aggregate output is invalid') from exc
        if value < 0:
            raise OperationSafetyError('MySQL aggregate output is negative')
        return value

    def _mysql_dump(self, database: str, destination: Path) -> None:
        if DATABASE_RE.fullmatch(database) is None:
            raise OperationSafetyError('MySQL dump database name is invalid')
        result = self.runner.run_to_file(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_DATABASE={database}',
                'mysql',
                'sh',
                '-lc',
                'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" '
                '--single-transaction --routines --triggers --events '
                '--hex-blob --set-gtid-purged=OFF "$HPT_DATABASE"',
            ),
            destination,
            cwd=Path(self.config.app_root),
            timeout=7200,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'MySQL dump failed with code {result.returncode}'
            )

    def _mysql_import(self, database: str, source: Path) -> None:
        if DATABASE_RE.fullmatch(database) is None:
            raise OperationSafetyError('MySQL import database name is invalid')
        result = self.runner.run_from_file(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_DATABASE={database}',
                'mysql',
                'sh',
                '-lc',
                'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$HPT_DATABASE"',
            ),
            source,
            cwd=Path(self.config.app_root),
            timeout=7200,
        )
        if result.returncode != 0:
            raise OperationSafetyError(
                f'MySQL import failed with code {result.returncode}'
            )

    def _internal_command(
        self,
        *arguments: str,
        snapshot_mount: bool = False,
        timeout: int = 7200,
    ):
        mounts = [
            '-v',
            f'{self.code_root / "backend-python"}:/migration-code:ro',
            '-v',
            f'{self.operation_root}:/operation',
        ]
        if snapshot_mount:
            if self.verified_package is None:
                raise OperationSafetyError('snapshot package is not verified')
            mounts.extend(
                ['-v', f'{self.verified_package.snapshot_root}:/snapshot:ro']
            )
        return self._run_required(
            (
                *self.plan.compose_prefix,
                'run',
                '--rm',
                '--no-deps',
                '-T',
                '--user',
                OPERATION_CONTAINER_USER,
                '-e',
                'PYTHONPATH=/migration-code',
                *mounts,
                'backend',
                'python',
                '/migration-code/scripts/server_migration_internal.py',
                *arguments,
            ),
            timeout=timeout,
        )

    def _migration_command(self, *, execute: bool) -> None:
        if self.targets is None or self.verified_package is None:
            raise OperationSafetyError('prepare context is incomplete')
        report_name = 'migration-execute.json' if execute else 'migration-dry-run.json'
        arguments = [
            '--env',
            '/migration-env/.env',
            '--dump',
            '/snapshot/legacy-full.sql',
            '--host',
            'mysql',
            '--stage-database',
            self.names.stage_database,
            '--candidate-database',
            self.names.candidate_database,
            '--tenant-slug',
            'HPT-00000001',
            '--report',
            f'/operation/{report_name}',
            '--file-manifest',
            f'/operation/{report_name}.files.json',
        ]
        for root in ('/snapshot/uploads-export', '/snapshot/minio-export'):
            arguments.extend(['--file-root', root])
        if execute:
            arguments.extend(
                [
                    '--prepared-files-root',
                    '/operation/prepared-files',
                    '--execute',
                    '--confirm',
                    'MIGRATE_LEGACY_TO_CANDIDATE',
                ]
            )
        mounts = (
            '-v',
            f'{self.code_root / "backend-python"}:/migration-code:ro',
            '-v',
            f'{self.operation_root}:/operation',
            '-v',
            f'{self.verified_package.snapshot_root}:/snapshot:ro',
            '-v',
            f'{self.plan.active_environment_path}:/migration-env/.env:ro',
        )
        self._run_required(
            (
                *self.plan.compose_prefix,
                'run',
                '--rm',
                '--no-deps',
                '-T',
                '--user',
                OPERATION_CONTAINER_USER,
                '-e',
                'PYTHONPATH=/migration-code',
                *mounts,
                'backend',
                'python',
                '/migration-code/scripts/restore_legacy_data.py',
                *arguments,
            ),
            timeout=7200,
        )

    def _step_prove_active(self) -> None:
        self.proof = prove_source_project(
            self.runner,
            project=self.config.project,
            docker_command=self.config.docker_command,
        )
        self.targets = read_active_targets(self.plan.active_environment_path)

    def _step_verify_package(self) -> None:
        self.operation_root.mkdir(parents=True, exist_ok=False)
        os.chmod(self.operation_root, 0o700)
        self.verified_package = verify_snapshot_package(
            self.config.package_path,
            sidecar_path=self.config.sidecar_path,
            extraction_root=self.operation_root / 'extracted',
        )
        if self.verified_package.snapshot_id != self.config.snapshot_id:
            raise OperationSafetyError('snapshot ID differs from prepare config')

    def _step_check_prerequisites(self) -> None:
        if self.targets is None or self.verified_package is None:
            raise OperationSafetyError('prepare proof is incomplete')
        if shutil.which(self.config.docker_command) is None:
            raise OperationSafetyError('Docker command is unavailable')
        free_bytes = shutil.disk_usage(self.operation_root).free
        package_bytes = Path(self.config.package_path).stat().st_size
        required_bytes = max(package_bytes * 4, 2 * 1024 * 1024 * 1024)
        if free_bytes < required_bytes:
            raise OperationSafetyError('insufficient free disk space for prepare')

    def _step_backup_active(self) -> None:
        if self.targets is None:
            raise OperationSafetyError('active targets are not proved')
        backup_root = self.operation_root / 'backups'
        backup_root.mkdir(mode=0o700)
        environment_backup = backup_root / 'active.env'
        environment_backup.write_bytes(self.plan.active_environment_path.read_bytes())
        os.chmod(environment_backup, 0o600)
        for filename in (
            'docker-compose.yml',
            'docker-compose.saas-preview.yml',
        ):
            source = Path(self.config.app_root) / filename
            destination = backup_root / filename
            destination.write_bytes(source.read_bytes())
            os.chmod(destination, 0o600)

        cert_rows = []
        cert_root = self._active_certs_path()
        if cert_root.is_dir() and not cert_root.is_symlink():
            for path in sorted(cert_root.iterdir(), key=lambda item: item.name):
                if path.is_symlink() or not path.is_file():
                    raise OperationSafetyError('certificate path is unsafe')
                metadata = path.stat()
                cert_rows.append(
                    {
                        'name': path.name,
                        'sizeBytes': metadata.st_size,
                        'mode': stat.S_IMODE(metadata.st_mode),
                    }
                )
        write_atomic_json(
            backup_root / 'certificates-metadata.json',
            {'files': cert_rows},
            overwrite=False,
        )

        active_dump = backup_root / 'active.sql'
        self._mysql_dump(self.targets.database, active_dump)
        active_tables = self._mysql_query_int(
            'SELECT COUNT(*) FROM information_schema.tables '
            f"WHERE table_schema='{self.targets.database}' "
            "AND table_type='BASE TABLE'"
        )
        upload_source = self._active_uploads_path()
        upload_report = sync_tree(upload_source, backup_root / 'uploads')
        self._internal_command(
            'minio-export',
            '--bucket',
            self.targets.bucket,
            '--output-root',
            '/operation/backups/minio-export',
        )
        minio_report = json.loads(
            (backup_root / 'minio-export-report.json').read_text(encoding='utf-8')
        )
        write_atomic_json(
            backup_root / 'backup-manifest.json',
            {
                'activeDatabase': self.targets.database,
                'activeReadonlyDatabase': self.targets.readonly_database,
                'activeBucket': self.targets.bucket,
                'databaseDumpSha256': sha256_file(active_dump),
                'databaseTableCount': active_tables,
                'uploads': upload_report.to_dict(),
                'minio': minio_report,
            },
            overwrite=False,
        )

    def _step_restore_prove_backup(self) -> None:
        backup_root = self.operation_root / 'backups'
        manifest = json.loads(
            (backup_root / 'backup-manifest.json').read_text(encoding='utf-8')
        )
        proof_database = self.names.restore_proof_database
        self._mysql_exec(
            f'CREATE DATABASE `{proof_database}` CHARACTER SET utf8mb4 '
            'COLLATE utf8mb4_unicode_ci'
        )
        self._mysql_import(proof_database, backup_root / 'active.sql')
        restored_tables = self._mysql_query_int(
            'SELECT COUNT(*) FROM information_schema.tables '
            f"WHERE table_schema='{proof_database}' "
            "AND table_type='BASE TABLE'"
        )
        if restored_tables != manifest['databaseTableCount']:
            raise OperationSafetyError('database restore proof table count mismatch')
        self._internal_command(
            'minio-import',
            '--bucket',
            self.names.restore_proof_bucket,
            '--source-root',
            '/operation/backups/minio-export',
            '--report',
            '/operation/restore-proof-minio.json',
        )
        self._internal_command(
            'minio-delete-bucket',
            '--bucket',
            self.names.restore_proof_bucket,
        )
        self._mysql_exec(f'DROP DATABASE `{proof_database}`')
        write_atomic_json(
            self.operation_root / 'restore-proof.json',
            {
                'databaseTableCount': restored_tables,
                'databaseStatus': 'passed',
                'minioStatus': 'passed',
                'formalRestoreDrillEvidence': False,
            },
            overwrite=False,
        )

    def _step_create_candidates(self) -> None:
        for database in (
            self.names.stage_database,
            self.names.candidate_database,
        ):
            self._mysql_exec(
                f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 '
                'COLLATE utf8mb4_unicode_ci'
            )
        grant_script = r'''set -eu
case "$MYSQL_USER" in ""|*[!A-Za-z0-9_]*) exit 64;; esac
case "$DB_READONLY_USER" in ""|*[!A-Za-z0-9_]*) exit 64;; esac
mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
GRANT ALL PRIVILEGES ON \`$HPT_STAGE\`.* TO '$MYSQL_USER'@'%';
GRANT ALL PRIVILEGES ON \`$HPT_CANDIDATE\`.* TO '$MYSQL_USER'@'%';
GRANT SELECT ON \`$HPT_CANDIDATE\`.* TO '$DB_READONLY_USER'@'%';
FLUSH PRIVILEGES;
SQL'''
        self._run_required(
            (
                *self.plan.compose_prefix,
                'exec',
                '-T',
                '-e',
                f'HPT_STAGE={self.names.stage_database}',
                '-e',
                f'HPT_CANDIDATE={self.names.candidate_database}',
                'mysql',
                'sh',
                '-lc',
                grant_script,
            )
        )
        self._mysql_import(
            self.names.candidate_database,
            self.operation_root / 'backups' / 'active.sql',
        )
        # The active SaaS clone historically drifted from the ORM/source
        # contract: legacy interviews may have no linked resume, while the
        # cloned column was NOT NULL.  Reconcile this candidate-only column
        # before migration so the source row is preserved without inventing
        # a resume ID or weakening the active database.
        self._mysql_exec(
            f'ALTER TABLE `{self.names.candidate_database}`.`interviews` '
            'MODIFY `resume_id` varchar(36) NULL'
        )

    def _step_bootstrap_candidate(self) -> None:
        if self.targets is None:
            raise OperationSafetyError('active targets are not available')
        self._internal_command(
            'bootstrap-candidate-controls',
            '--candidate-database',
            self.names.candidate_database,
            '--active-database',
            self.targets.database,
            '--snapshot-id',
            self.config.snapshot_id,
            '--tenant-profile',
            '/snapshot/tenant-profile.json',
            '--result-path',
            '/operation/candidate-controls.json',
            snapshot_mount=True,
        )

    def _step_load_stage(self) -> None:
        if self.verified_package is None:
            raise OperationSafetyError('snapshot package is not verified')
        self._mysql_import(
            self.names.stage_database,
            self.verified_package.snapshot_root / 'legacy-full.sql',
        )

    def _step_migration_dry_run(self) -> None:
        self._migration_command(execute=False)
        report = json.loads(
            (self.operation_root / 'migration-dry-run.json').read_text(
                encoding='utf-8'
            )
        )
        if report.get('status') != 'ready' or report.get('dry_run') is not True:
            raise OperationSafetyError('candidate migration dry-run is not ready')

    def _step_migration_execute(self) -> None:
        prepared_root = self.operation_root / 'prepared-files'
        if prepared_root.is_symlink() or prepared_root.exists():
            raise OperationSafetyError(
                'prepared files root already exists before migration execute'
            )
        prepared_root.mkdir(mode=0o700)
        os.chmod(prepared_root, 0o700)
        self._migration_command(execute=True)
        report = json.loads(
            (self.operation_root / 'migration-execute.json').read_text(
                encoding='utf-8'
            )
        )
        if report.get('status') != 'passed' or report.get('dry_run') is not False:
            raise OperationSafetyError('candidate migration execution failed')

    def _step_upload_prepared_objects(self) -> None:
        self._internal_command(
            'minio-import',
            '--bucket',
            self.names.candidate_bucket,
            '--source-root',
            '/operation/prepared-files',
            '--report',
            '/operation/candidate-minio.json',
        )

    def _step_create_temporary_admin(self) -> None:
        if self.targets is None:
            raise OperationSafetyError('active targets are not available')
        self._internal_command(
            'bootstrap-candidate',
            '--candidate-database',
            self.names.candidate_database,
            '--active-database',
            self.targets.database,
            '--snapshot-id',
            self.config.snapshot_id,
            '--tenant-profile',
            '/snapshot/tenant-profile.json',
            '--credential-path',
            '/operation/validation-admin.json',
            '--result-path',
            '/operation/candidate-bootstrap.json',
            snapshot_mount=True,
        )

    def _step_start_candidate_backend(self) -> None:
        container_name = f'hpt-candidate-{self.config.snapshot_id.lower()}'
        result = self._run_required(
            (
                *self.plan.compose_prefix,
                'run',
                '--no-deps',
                '-d',
                '--name',
                container_name,
                '-e',
                'GUNICORN_WORKERS=1',
                '-e',
                'GUNICORN_THREADS=1',
                '-e',
                f'DB_NAME={self.names.candidate_database}',
                '-e',
                f'DB_READONLY_NAME={self.names.candidate_database}',
                '-e',
                f'MINIO_BUCKET={self.names.candidate_bucket}',
                '-e',
                'PYTHONPATH=/migration-code',
                '-v',
                f'{self.code_root / "backend-python"}:/migration-code:ro',
                '-v',
                f'{self.operation_root}:/operation:ro',
                'backend',
            ),
            timeout=600,
        )
        if result.stdout.strip() and container_name not in result.stdout:
            # Compose normally prints the container ID, so absence of the name is fine.
            pass
        active_container = self._run_required(
            (*self.plan.compose_prefix, 'ps', '-q', 'backend')
        ).stdout.strip()
        if not active_container:
            self._run_required((self.config.docker_command, 'rm', '-f', container_name))
            raise OperationSafetyError('active backend container is unavailable')
        active_image = self._run_required(
            (self.config.docker_command, 'inspect', '--format', '{{.Image}}', active_container)
        ).stdout.strip()
        candidate_image = self._run_required(
            (self.config.docker_command, 'inspect', '--format', '{{.Image}}', container_name)
        ).stdout.strip()
        if not active_image or active_image != candidate_image:
            self._run_required((self.config.docker_command, 'rm', '-f', container_name))
            raise OperationSafetyError(
                'candidate backend image does not match active release'
            )
        self.candidate_container = container_name

    def _step_validate_candidate(self) -> None:
        if self.candidate_container is None:
            raise OperationSafetyError('candidate backend is not running')
        self._run_required(
            (
                self.config.docker_command,
                'exec',
                '--user',
                OPERATION_CONTAINER_USER,
                self.candidate_container,
                'python',
                '/migration-code/scripts/server_migration_internal.py',
                'validate-candidate',
                '--credential-path',
                '/operation/validation-admin.json',
                '--candidate-database',
                self.names.candidate_database,
                '--candidate-bucket',
                self.names.candidate_bucket,
                '--report',
                '/tmp/candidate-validation.json',
            ),
            timeout=600,
        )
        copy_result = self._run_required(
            (
                self.config.docker_command,
                'cp',
                f'{self.candidate_container}:/tmp/candidate-validation.json',
                str(self.operation_root / 'candidate-validation.json'),
            )
        )
        if copy_result.returncode != 0:
            raise OperationSafetyError('candidate validation report copy failed')

    def _step_remove_temporary_admin(self) -> None:
        self._internal_command(
            'remove-candidate-admin',
            '--candidate-database',
            self.names.candidate_database,
            '--bootstrap-result',
            '/operation/candidate-bootstrap.json',
            '--report',
            '/operation/admin-removal.json',
        )
        if self.candidate_container is not None:
            self._run_required(
                (
                    self.config.docker_command,
                    'rm',
                    '-f',
                    self.candidate_container,
                )
            )
            self.candidate_container = None
        credential_path = self.operation_root / 'validation-admin.json'
        if credential_path.is_symlink() or not credential_path.is_file():
            raise OperationSafetyError('validation credential file is missing')
        credential_path.unlink()

    def _step_write_prepared_state(self) -> None:
        if self.targets is None or self.verified_package is None:
            raise OperationSafetyError('prepare state context is incomplete')
        validation = json.loads(
            (self.operation_root / 'candidate-validation.json').read_text(
                encoding='utf-8'
            )
        )
        removal = json.loads(
            (self.operation_root / 'admin-removal.json').read_text(
                encoding='utf-8'
            )
        )
        if validation.get('status') != 'passed' or removal.get('status') != 'passed':
            raise OperationSafetyError('candidate is not ready for prepared state')
        prepared_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace('+00:00', 'Z')
        )
        state = PreparedMigrationState(
            snapshot_id=self.config.snapshot_id,
            package_sha256=self.verified_package.package_sha256,
            status='ready',
            candidate_database=self.names.candidate_database,
            candidate_bucket=self.names.candidate_bucket,
            active_database=self.targets.database,
            active_readonly_database=self.targets.readonly_database,
            active_bucket=self.targets.bucket,
            prepared_at=prepared_at,
            validation_results={
                'apiHealth': bool(validation.get('apiHealth')),
                'apiReady': bool(validation.get('apiReady')),
                'platformLogin': bool(validation.get('platformLogin')),
                'tenantLogin': bool(validation.get('tenantLogin')),
                'coreRecords': bool(validation.get('coreRecords')),
                'objectStorage': bool(validation.get('objectStorage')),
                'temporaryAdminRemoved': True,
                'formalRestoreDrillEvidence': False,
            },
        )
        write_prepared_state(self.operation_root / 'prepared.json', state)
