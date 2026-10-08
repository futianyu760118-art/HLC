from __future__ import annotations

import io
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.operation_common import OperationSafetyError
from ops.server_prepare import (
    ServerPrepareActions,
    ServerTargetNames,
    read_active_targets,
)
from ops.server_internal import (
    delete_restore_proof_bucket,
    import_minio_tree,
    load_tenant_profile,
)


def test_create_candidates_restores_nullable_legacy_interview_resume_id():
    actions = object.__new__(ServerPrepareActions)
    actions.names = SimpleNamespace(
        stage_database='legacy_stage_20260715T102030Z',
        candidate_database='hrm_candidate_20260715T102030Z',
    )
    actions.plan = SimpleNamespace(compose_prefix=('docker', 'compose'))
    actions.operation_root = Path('/operation')
    sql = []
    imports = []

    actions._mysql_exec = lambda statement: sql.append(statement)
    actions._run_required = lambda *args, **kwargs: None
    actions._mysql_import = lambda database, dump: imports.append((database, dump))

    actions._step_create_candidates()

    assert imports == [
        ('hrm_candidate_20260715T102030Z', Path('/operation/backups/active.sql'))
    ]
    assert any(
        'ALTER TABLE `hrm_candidate_20260715T102030Z`.`interviews`' in statement
        and 'MODIFY `resume_id`' in statement
        and 'NULL' in statement
        for statement in sql
    )


def test_candidate_validation_exec_runs_as_root_for_owner_only_credentials():
    actions = object.__new__(ServerPrepareActions)
    actions.candidate_container = 'hpt-candidate-20260715t102030z'
    actions.config = SimpleNamespace(docker_command='docker')
    actions.names = SimpleNamespace(
        candidate_database='hrm_candidate_20260715T102030Z',
        candidate_bucket='hrm-candidate-20260715t102030z',
    )
    actions.operation_root = Path('/operation')
    commands = []

    def record(argv, **kwargs):
        commands.append(tuple(argv))
        return SimpleNamespace(returncode=0)

    actions._run_required = record

    actions._step_validate_candidate()

    validation = commands[0]
    assert validation[:4] == ('docker', 'exec', '--user', '0:0')
    assert validation[4] == actions.candidate_container


def test_candidate_backend_starts_single_worker_for_seed_race_free_validation():
    actions = object.__new__(ServerPrepareActions)
    actions.config = SimpleNamespace(
        snapshot_id=SNAPSHOT_ID,
        docker_command='docker',
    )
    actions.plan = SimpleNamespace(compose_prefix=('docker', 'compose'))
    actions.code_root = Path('/code')
    actions.operation_root = Path('/operation')
    actions.names = SimpleNamespace(
        candidate_database='hrm_candidate_20260715T102030Z',
        candidate_bucket='hrm-candidate-20260715t102030z',
    )
    commands = []

    def record(argv, **kwargs):
        commands.append(tuple(argv))
        if tuple(argv)[-3:] == ('ps', '-q', 'backend'):
            return SimpleNamespace(returncode=0, stdout='active-id\n')
        if 'inspect' in argv:
            return SimpleNamespace(returncode=0, stdout='sha256:release\n')
        return SimpleNamespace(returncode=0, stdout='candidate-id\n')

    actions._run_required = record

    actions._step_start_candidate_backend()

    command = commands[0]
    assert 'GUNICORN_WORKERS=1' in command
    assert 'GUNICORN_THREADS=1' in command


SNAPSHOT_ID = '20260715T102030Z'


def test_read_active_targets_returns_only_non_secret_switch_values(tmp_path):
    environment = tmp_path / '.env'
    environment.write_text(
        'DB_NAME=hengpintong_saas\n'
        'DB_READONLY_NAME=hengpintong_saas\n'
        'MINIO_BUCKET=hrm-courses\n'
        'DB_PASSWORD=must-not-be-returned\n',
        encoding='utf-8',
    )

    targets = read_active_targets(environment)

    assert targets.database == 'hengpintong_saas'
    assert targets.readonly_database == 'hengpintong_saas'
    assert targets.bucket == 'hrm-courses'
    assert 'password' not in repr(targets).lower()
    assert 'must-not-be-returned' not in repr(targets)


def test_read_active_targets_rejects_duplicates_and_unsafe_names(tmp_path):
    environment = tmp_path / '.env'
    environment.write_text(
        'DB_NAME=hengpintong_saas\n'
        'DB_NAME=other\n'
        'DB_READONLY_NAME=hengpintong_saas\n'
        'MINIO_BUCKET=hrm-courses\n',
        encoding='utf-8',
    )
    with pytest.raises(OperationSafetyError, match='duplicate'):
        read_active_targets(environment)

    environment.write_text(
        'DB_NAME=hengpintong_saas;DROP\n'
        'DB_READONLY_NAME=hengpintong_saas\n'
        'MINIO_BUCKET=hrm-courses\n',
        encoding='utf-8',
    )
    with pytest.raises(OperationSafetyError, match='invalid'):
        read_active_targets(environment)


def test_server_target_names_are_deterministic_and_never_live_marked():
    names = ServerTargetNames.for_snapshot(SNAPSHOT_ID)

    assert names.stage_database == 'legacy_stage_20260715T102030Z'
    assert names.candidate_database == 'hrm_candidate_20260715T102030Z'
    assert names.restore_proof_database == 'hrm_restoreproof_20260715T102030Z'
    assert names.candidate_bucket == 'hrm-candidate-20260715t102030z'
    assert names.restore_proof_bucket == 'hrm-restoreproof-20260715t102030z'


class MemoryMinio:
    def __init__(self):
        self.buckets = {}

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets[bucket] = {}

    def fput_object(self, bucket, key, path):
        self.buckets[bucket][key] = Path(path).read_bytes()

    def stat_object(self, bucket, key):
        payload = self.buckets[bucket][key]
        return type('Stat', (), {'size': len(payload)})()

    def get_object(self, bucket, key, offset=0, length=0):
        payload = self.buckets[bucket][key]
        selected = payload[offset:offset + length] if length else payload[offset:]
        response = io.BytesIO(selected)
        response.release_conn = lambda: None
        return response

    def list_objects(self, bucket, recursive=True):
        assert recursive is True
        return [
            type('Item', (), {'object_name': key})()
            for key in sorted(self.buckets[bucket])
        ]

    def remove_object(self, bucket, key):
        del self.buckets[bucket][key]

    def remove_bucket(self, bucket):
        assert not self.buckets[bucket]
        del self.buckets[bucket]


def test_minio_import_requires_new_bucket_and_hash_verifies_files(tmp_path):
    source = tmp_path / 'objects'
    (source / 'tenants' / 'tenant-a').mkdir(parents=True)
    (source / 'tenants' / 'tenant-a' / 'video.mp4').write_bytes(b'video')
    client = MemoryMinio()

    report = import_minio_tree(
        client,
        bucket='hrm-candidate-20260715t102030z',
        source_root=source,
    )

    assert report == {
        'bucket': 'hrm-candidate-20260715t102030z',
        'objectCount': 1,
        'totalBytes': 5,
        'status': 'passed',
    }
    assert client.buckets['hrm-candidate-20260715t102030z'] == {
        'tenants/tenant-a/video.mp4': b'video'
    }
    with pytest.raises(OperationSafetyError, match='already exists'):
        import_minio_tree(
            client,
            bucket='hrm-candidate-20260715t102030z',
            source_root=source,
        )


def test_only_restore_proof_bucket_can_be_automatically_deleted():
    client = MemoryMinio()
    client.buckets['hrm-restoreproof-20260715t102030z'] = {'a.txt': b'a'}
    delete_restore_proof_bucket(
        client,
        bucket='hrm-restoreproof-20260715t102030z',
    )
    assert client.buckets == {}

    client.buckets['hrm-candidate-20260715t102030z'] = {}
    with pytest.raises(OperationSafetyError, match='restore-proof'):
        delete_restore_proof_bucket(
            client,
            bucket='hrm-candidate-20260715t102030z',
        )


def test_tenant_profile_accepts_only_non_secret_destination_controls(tmp_path):
    profile_path = tmp_path / 'tenant-profile.json'
    profile_path.write_text(
        '{"slug":"HPT-00000001","name":"First Tenant",'
        '"planCode":"enterprise","enabledModuleKeys":["system"]}',
        encoding='utf-8',
    )
    assert load_tenant_profile(profile_path) == {
        'slug': 'HPT-00000001',
        'name': 'First Tenant',
        'planCode': 'enterprise',
        'enabledModuleKeys': ('system',),
    }

    profile_path.write_text(
        '{"slug":"HPT-00000001","name":"First Tenant",'
        '"planCode":"enterprise","enabledModuleKeys":["system"],'
        '"adminPassword":"secret"}',
        encoding='utf-8',
    )
    with pytest.raises(OperationSafetyError, match='fields'):
        load_tenant_profile(profile_path)


def test_internal_cli_exposes_only_fixed_operational_commands():
    cli = importlib.import_module('scripts.server_migration_internal')

    export = cli.parse_args(
        [
            'minio-export',
            '--bucket',
            'hrm-courses',
            '--output-root',
            '/operation/export',
        ]
    )
    assert export.command == 'minio-export'

    bootstrap = cli.parse_args(
        [
            'bootstrap-candidate',
            '--candidate-database',
            'hrm_candidate_20260715T102030Z',
            '--active-database',
            'hengpintong_saas',
            '--snapshot-id',
            SNAPSHOT_ID,
            '--tenant-profile',
            '/snapshot/tenant-profile.json',
            '--credential-path',
            '/operation/admin.json',
            '--result-path',
            '/operation/result.json',
        ]
    )
    assert bootstrap.command == 'bootstrap-candidate'

    controls = cli.parse_args(
        [
            'bootstrap-candidate-controls',
            '--candidate-database',
            'hrm_candidate_20260715T102030Z',
            '--active-database',
            'hengpintong_saas',
            '--snapshot-id',
            SNAPSHOT_ID,
            '--tenant-profile',
            '/snapshot/tenant-profile.json',
            '--result-path',
            '/operation/controls.json',
        ]
    )
    assert controls.command == 'bootstrap-candidate-controls'


def test_server_bootstraps_controls_before_creating_temporary_admin():
    actions = object.__new__(ServerPrepareActions)
    actions.targets = SimpleNamespace(database='hengpintong_saas')
    actions.names = SimpleNamespace(
        candidate_database='hrm_candidate_20260715T102030Z',
    )
    actions.config = SimpleNamespace(snapshot_id=SNAPSHOT_ID)
    commands = []

    def record(*arguments, **kwargs):
        commands.append((arguments, kwargs))

    actions._internal_command = record

    actions._step_bootstrap_candidate()
    actions._step_create_temporary_admin()

    controls, admin = commands
    assert controls[0][0] == 'bootstrap-candidate-controls'
    assert '--credential-path' not in controls[0]
    assert controls[1] == {'snapshot_mount': True}
    assert admin[0][0] == 'bootstrap-candidate'
    assert '--credential-path' in admin[0]
    assert admin[1] == {'snapshot_mount': True}


def test_candidate_backend_must_use_the_active_release_image():
    actions = object.__new__(ServerPrepareActions)
    actions.config = SimpleNamespace(snapshot_id=SNAPSHOT_ID, docker_command='docker')
    actions.plan = SimpleNamespace(compose_prefix=('docker', 'compose'))
    actions.names = SimpleNamespace(
        candidate_database='hrm_candidate_20260715T102030Z',
        candidate_bucket='hrm-candidate-20260715t102030z',
    )
    actions.code_root = Path('/code')
    actions.operation_root = Path('/operation')
    actions.candidate_container = None
    results = iter([
        SimpleNamespace(returncode=0, stdout='candidate-id\n', stderr=''),
        SimpleNamespace(returncode=0, stdout='active-id\n', stderr=''),
        SimpleNamespace(returncode=0, stdout='sha256:release\n', stderr=''),
        SimpleNamespace(returncode=0, stdout='sha256:preview\n', stderr=''),
        SimpleNamespace(returncode=0, stdout='', stderr=''),
    ])
    actions._run_required = lambda *_args, **_kwargs: next(results)

    with pytest.raises(
        OperationSafetyError,
        match='candidate backend image does not match active release',
    ):
        actions._step_start_candidate_backend()

    assert actions.candidate_container is None


def test_migration_helper_containers_run_as_root_for_owner_only_mounts():
    actions = object.__new__(ServerPrepareActions)
    actions.code_root = Path('/code')
    actions.operation_root = Path('/operation-host')
    actions.plan = SimpleNamespace(
        compose_prefix=('docker', 'compose'),
        active_environment_path=Path('/shared/.env'),
    )
    actions.config = SimpleNamespace(app_root=Path('/app'))
    actions.targets = SimpleNamespace(database='hrm_saas')
    actions.names = SimpleNamespace(
        stage_database='legacy_stage_20260715T102030Z',
        candidate_database='hrm_candidate_20260715T102030Z',
    )
    actions.verified_package = SimpleNamespace(snapshot_root=Path('/snapshot-host'))
    commands = []

    def record(argv, **_kwargs):
        commands.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    actions._run_required = record
    actions._internal_command('minio-export')
    actions._migration_command(execute=False)

    for command in commands:
        run_index = command.index('run')
        assert command[run_index:run_index + 6] == (
            'run',
            '--rm',
            '--no-deps',
            '-T',
            '--user',
            '0:0',
        )


def test_migration_execute_creates_owner_only_prepared_root_before_helper(
    tmp_path,
):
    actions = object.__new__(ServerPrepareActions)
    actions.operation_root = tmp_path / 'operation'
    actions.operation_root.mkdir()
    prepared_root = actions.operation_root / 'prepared-files'

    def execute_helper(*, execute):
        assert execute is True
        assert prepared_root.is_dir()
        if os.name != 'nt':
            assert prepared_root.stat().st_mode & 0o777 == 0o700
        (actions.operation_root / 'migration-execute.json').write_text(
            json.dumps({'status': 'passed', 'dry_run': False}),
            encoding='utf-8',
        )

    actions._migration_command = execute_helper

    actions._step_migration_execute()

    assert prepared_root.is_dir()
