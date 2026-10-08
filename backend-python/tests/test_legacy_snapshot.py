from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from ops.operation_common import CommandResult


def _snapshot():
    return importlib.import_module('ops.legacy_snapshot')


def _container_rows(*, project='hengpintong-next', unhealthy=None):
    rows = []
    for index, service in enumerate(('backend', 'minio', 'mysql', 'nginx'), 1):
        status = 'Up 2 hours (healthy)'
        if service == unhealthy:
            status = 'Up 2 hours (unhealthy)'
        rows.append(
            '|'.join(
                (
                    f'container-{index}',
                    f'{project}-{service}-1',
                    status,
                    service,
                    project,
                )
            )
        )
    return rows


class FakeSourceRunner:
    def __init__(
        self,
        *,
        rows=None,
        table_count='62',
        minio_objects=342,
        minio_bytes=644931942,
    ):
        self.rows = list(rows if rows is not None else _container_rows())
        self.table_count = table_count
        self.minio_objects = minio_objects
        self.minio_bytes = minio_bytes
        self.calls = []

    def run(self, argv, **_kwargs):
        argv = tuple(argv)
        self.calls.append(argv)
        if 'ps' in argv:
            output = '\n'.join(self.rows) + ('\n' if self.rows else '')
        elif 'MYSQL_DATABASE' in ' '.join(argv):
            output = f'{self.table_count}\n'
        elif 'MINIO_ENDPOINT' in ' '.join(argv):
            output = json.dumps(
                {
                    'bucket': 'hrm-courses',
                    'bytes': self.minio_bytes,
                    'objects': self.minio_objects,
                }
            ) + '\n'
        else:
            raise AssertionError(f'unexpected command: {argv!r}')
        return CommandResult(
            argv=argv,
            returncode=0,
            stdout=output,
            stderr='',
        )


def test_source_guard_requires_exact_four_project_labeled_services():
    snapshot = _snapshot()
    runner = FakeSourceRunner()

    proof = snapshot.prove_source_project(
        runner,
        project='hengpintong-next',
    )

    assert proof.project == 'hengpintong-next'
    assert proof.services == ('backend', 'minio', 'mysql', 'nginx')
    assert proof.healthy is True
    assert proof.container_for('mysql') == 'hengpintong-next-mysql-1'
    assert runner.calls[0][:2] == ('docker', 'ps')


@pytest.mark.parametrize(
    'rows, match',
    (
        (_container_rows(project='other-project'), 'project label'),
        (_container_rows()[:-1], 'exact services'),
        (
            [*_container_rows(), _container_rows()[0]],
            'duplicate service',
        ),
        (_container_rows(unhealthy='mysql'), 'healthy'),
    ),
)
def test_source_guard_rejects_incomplete_mislabeled_or_unhealthy_projects(
    rows,
    match,
):
    snapshot = _snapshot()

    with pytest.raises(snapshot.OperationSafetyError, match=match):
        snapshot.prove_source_project(
            FakeSourceRunner(rows=rows),
            project='hengpintong-next',
        )


def test_source_guard_can_prove_exact_unhealthy_project_for_recovery():
    snapshot = _snapshot()

    proof = snapshot.prove_source_project(
        FakeSourceRunner(
            rows=_container_rows(
                project='hengpintong-saas-preview',
                unhealthy='nginx',
            )
        ),
        project='hengpintong-saas-preview',
        require_healthy=False,
    )

    assert proof.services == ('backend', 'minio', 'mysql', 'nginx')
    assert proof.healthy is False


def test_source_inventory_combines_database_upload_and_minio_aggregates(tmp_path):
    snapshot = _snapshot()
    upload_root = tmp_path / 'backend-python' / 'uploads'
    (upload_root / 'resumes').mkdir(parents=True)
    (upload_root / 'resumes' / 'a.pdf').write_bytes(b'abc')
    (upload_root / 'b.txt').write_bytes(b'hello')
    runner = FakeSourceRunner(
        table_count='62',
        minio_objects=7,
        minio_bytes=4096,
    )

    inventory = snapshot.inspect_source_inventory(
        runner,
        source_root=tmp_path,
        project='hengpintong-next',
    )

    assert inventory.to_dict() == {
        'table_count': 62,
        'upload_files': 2,
        'upload_bytes': 8,
        'object_count': 7,
        'object_bytes': 4096,
        'bucket': 'hrm-courses',
    }
    mysql_command = next(call for call in runner.calls if 'MYSQL_DATABASE' in ' '.join(call))
    assert mysql_command[-1].endswith(
        "table_type = 'BASE TABLE';\" \"$MYSQL_DATABASE\""
    )


@pytest.mark.parametrize(
    'field, value',
    (
        ('table_count', 'not-an-int'),
        ('minio_objects', -1),
        ('minio_bytes', True),
    ),
)
def test_source_inventory_rejects_invalid_aggregate_data(tmp_path, field, value):
    snapshot = _snapshot()
    (tmp_path / 'backend-python' / 'uploads').mkdir(parents=True)
    kwargs = {field: value}
    if field == 'table_count':
        runner = FakeSourceRunner(table_count=value)
    else:
        runner = FakeSourceRunner(**kwargs)

    with pytest.raises(snapshot.OperationSafetyError, match='inventory'):
        snapshot.inspect_source_inventory(
            runner,
            source_root=tmp_path,
            project='hengpintong-next',
        )


def test_source_inventory_rejects_symlinks(tmp_path):
    snapshot = _snapshot()
    upload_root = tmp_path / 'backend-python' / 'uploads'
    upload_root.mkdir(parents=True)
    target = tmp_path / 'outside.txt'
    target.write_text('outside', encoding='utf-8')
    link = upload_root / 'link.txt'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('current Windows account cannot create symlinks')

    with pytest.raises(snapshot.OperationSafetyError, match='symlink'):
        snapshot.inspect_source_inventory(
            FakeSourceRunner(),
            source_root=tmp_path,
            project='hengpintong-next',
        )


def test_sync_tree_precopies_then_replaces_and_prunes_final_delta(tmp_path):
    snapshot = _snapshot()
    source = tmp_path / 'source'
    destination = tmp_path / 'snapshot'
    (source / 'resumes').mkdir(parents=True)
    (source / 'resumes' / 'a.pdf').write_bytes(b'v1')
    (source / 'stale.txt').write_bytes(b'stale')

    first = snapshot.sync_tree(source, destination)
    (source / 'resumes' / 'a.pdf').write_bytes(b'v2')
    (source / 'new.txt').write_bytes(b'new')
    (source / 'stale.txt').unlink()
    final = snapshot.sync_tree(
        source,
        destination,
        replace_changed=True,
        prune=True,
    )

    assert first.to_dict() == {
        'created_count': 2,
        'replaced_count': 0,
        'skipped_count': 0,
        'pruned_count': 0,
        'file_count': 2,
        'total_bytes': 7,
    }
    assert final.to_dict() == {
        'created_count': 1,
        'replaced_count': 1,
        'skipped_count': 0,
        'pruned_count': 1,
        'file_count': 2,
        'total_bytes': 5,
    }
    assert (destination / 'resumes' / 'a.pdf').read_bytes() == b'v2'
    assert (destination / 'new.txt').read_bytes() == b'new'
    assert not (destination / 'stale.txt').exists()


def test_sync_tree_refuses_changed_destination_without_final_replace(tmp_path):
    snapshot = _snapshot()
    source = tmp_path / 'source'
    destination = tmp_path / 'snapshot'
    source.mkdir()
    destination.mkdir()
    (source / 'a.txt').write_bytes(b'source')
    (destination / 'a.txt').write_bytes(b'different')

    with pytest.raises(snapshot.OperationSafetyError, match='different hash'):
        snapshot.sync_tree(source, destination)

    assert (destination / 'a.txt').read_bytes() == b'different'


def test_sync_tree_rejects_overlapping_roots(tmp_path):
    snapshot = _snapshot()
    source = tmp_path / 'source'
    source.mkdir()

    with pytest.raises(snapshot.OperationSafetyError, match='must not overlap'):
        snapshot.sync_tree(source, source / 'snapshot')


class FakeMinioClient:
    def __init__(self, objects, *, mutate_after_download=None):
        self.objects = dict(objects)
        self.mutate_after_download = mutate_after_download
        self.downloads = []
        self.stat_counts = {}

    def list_objects(self, bucket, recursive):
        assert bucket == 'hrm-courses'
        assert recursive is True
        return [
            SimpleNamespace(
                object_name=name,
                size=len(payload),
                etag=f'etag-{name}',
                version_id=None,
            )
            for name, payload in sorted(self.objects.items())
        ]

    def stat_object(self, bucket, object_name):
        assert bucket == 'hrm-courses'
        count = self.stat_counts.get(object_name, 0) + 1
        self.stat_counts[object_name] = count
        etag = f'etag-{object_name}'
        if object_name == self.mutate_after_download and count > 1:
            etag += '-changed'
        return SimpleNamespace(
            size=len(self.objects[object_name]),
            etag=etag,
            version_id=None,
        )

    def fget_object(self, bucket, object_name, file_path):
        assert bucket == 'hrm-courses'
        self.downloads.append(object_name)
        Path(file_path).write_bytes(self.objects[object_name])


def test_minio_export_hashes_and_replaces_changed_objects(tmp_path):
    snapshot = _snapshot()
    destination = tmp_path / 'minio-export'
    first_client = FakeMinioClient(
        {
            'courses/course-1/video.mp4': b'video-v1',
            'covers/course-1.jpg': b'image',
        }
    )

    first = snapshot.export_minio_objects(
        first_client,
        bucket='hrm-courses',
        destination_root=destination,
    )
    second_client = FakeMinioClient(
        {
            'courses/course-1/video.mp4': b'video-v2',
            'docs/new.pdf': b'pdf',
        }
    )
    second = snapshot.export_minio_objects(
        second_client,
        bucket='hrm-courses',
        destination_root=destination,
        replace_changed=True,
        prune=True,
    )

    assert first.file_count == 2
    assert second.created_count == 1
    assert second.replaced_count == 1
    assert second.pruned_count == 1
    assert (destination / 'courses/course-1/video.mp4').read_bytes() == b'video-v2'
    assert (destination / 'docs/new.pdf').read_bytes() == b'pdf'
    assert not (destination / 'covers/course-1.jpg').exists()


def test_minio_export_rejects_unsafe_keys_before_download(tmp_path):
    snapshot = _snapshot()
    client = FakeMinioClient({'../escape.txt': b'escape'})

    with pytest.raises(snapshot.OperationSafetyError, match='archive member'):
        snapshot.export_minio_objects(
            client,
            bucket='hrm-courses',
            destination_root=tmp_path / 'export',
        )

    assert client.downloads == []


def test_minio_export_rejects_object_changed_during_download(tmp_path):
    snapshot = _snapshot()
    client = FakeMinioClient(
        {'courses/video.mp4': b'video'},
        mutate_after_download='courses/video.mp4',
    )
    destination = tmp_path / 'export'

    with pytest.raises(snapshot.OperationSafetyError, match='changed during'):
        snapshot.export_minio_objects(
            client,
            bucket='hrm-courses',
            destination_root=destination,
        )

    assert not (destination / 'courses/video.mp4').exists()


class FakeLifecycleActions:
    def __init__(self, fail_event=None):
        self.fail_event = fail_event
        self.events = []

    def _event(self, name):
        self.events.append(name)
        if self.fail_event == name:
            raise RuntimeError(f'simulated {name} failure')

    def prove(self):
        self._event('prove')

    def precopy(self):
        self._event('precopy')

    def stop(self):
        self._event('stop')

    def verify_stopped(self):
        self._event('verify_stopped')

    def final_sync(self):
        self._event('final_sync')

    def dump(self):
        self._event('dump')

    def verify(self):
        self._event('verify')

    def start(self):
        self._event('start')

    def health(self):
        self._event('health')

    def promote(self):
        self._event('promote')


def test_snapshot_lifecycle_precopies_before_stop_and_promotes_after_health():
    snapshot = _snapshot()
    actions = FakeLifecycleActions()

    result = snapshot.execute_snapshot_lifecycle(actions)

    assert result.status == 'promoted'
    assert actions.events == [
        'prove',
        'precopy',
        'stop',
        'verify_stopped',
        'final_sync',
        'dump',
        'verify',
        'start',
        'health',
        'promote',
    ]


def test_snapshot_dump_failure_restarts_source_and_never_promotes():
    snapshot = _snapshot()
    actions = FakeLifecycleActions(fail_event='dump')

    with pytest.raises(RuntimeError, match='simulated dump failure'):
        snapshot.execute_snapshot_lifecycle(actions)

    assert actions.events == [
        'prove',
        'precopy',
        'stop',
        'verify_stopped',
        'final_sync',
        'dump',
        'start',
        'health',
    ]
    assert 'promote' not in actions.events


def test_snapshot_stop_failure_still_attempts_source_recovery():
    snapshot = _snapshot()
    actions = FakeLifecycleActions(fail_event='stop')

    with pytest.raises(RuntimeError, match='simulated stop failure'):
        snapshot.execute_snapshot_lifecycle(actions)

    assert actions.events == ['prove', 'precopy', 'stop', 'start', 'health']


class RestartFailureActions(FakeLifecycleActions):
    def __init__(self):
        super().__init__(fail_event='dump')

    def start(self):
        self.events.append('start')
        raise RuntimeError('simulated restart failure')


def test_source_recovery_failure_supersedes_snapshot_failure():
    snapshot = _snapshot()
    actions = RestartFailureActions()

    with pytest.raises(
        snapshot.OperationSafetyError,
        match='source recovery failed',
    ) as failure:
        snapshot.execute_snapshot_lifecycle(actions)

    assert str(failure.value.__cause__) == 'simulated restart failure'
    assert 'promote' not in actions.events


def test_source_compose_commands_target_only_expected_project_and_services():
    snapshot = _snapshot()
    source_root = Path('D:/project/HRM')
    resolved_root = source_root.resolve(strict=False)

    assert snapshot.build_source_service_command(
        action='stop',
        project='hengpintong-next',
        source_root=source_root,
    ) == (
        'docker',
        'compose',
        '--env-file',
        str(resolved_root / '.env'),
        '-p',
        'hengpintong-next',
        '-f',
        str(resolved_root / 'docker-compose.yml'),
        'stop',
        'nginx',
        'backend',
    )
    assert snapshot.build_source_service_command(
        action='start',
        project='hengpintong-next',
        source_root=Path('D:/project/HRM'),
    )[-3:] == ('start', 'backend', 'nginx')


@pytest.mark.parametrize('action', ('up', 'down', 'rm', 'restart'))
def test_source_compose_command_rejects_unapproved_actions(action):
    snapshot = _snapshot()

    with pytest.raises(snapshot.OperationSafetyError, match='action'):
        snapshot.build_source_service_command(
            action=action,
            project='hengpintong-next',
            source_root=Path('D:/project/HRM'),
        )


def test_snapshot_archive_contains_only_safe_data_members_and_hashes(tmp_path):
    snapshot = _snapshot()
    snapshot_root = tmp_path / 'snapshot'
    (snapshot_root / 'uploads-export').mkdir(parents=True)
    (snapshot_root / 'minio-export' / 'courses').mkdir(parents=True)
    (snapshot_root / 'legacy-full.sql').write_text(
        'CREATE TABLE `employees` (`id` int);\n',
        encoding='utf-8',
    )
    (snapshot_root / 'uploads-export' / 'resume.pdf').write_bytes(b'pdf')
    (snapshot_root / 'minio-export' / 'courses' / 'video.mp4').write_bytes(
        b'video'
    )
    (snapshot_root / 'snapshot-manifest.json').write_text(
        '{"snapshotId":"20260715T102030Z"}\n',
        encoding='utf-8',
    )
    archive_path = tmp_path / 'first-tenant-snapshot.zip'

    built = snapshot.build_snapshot_archive(snapshot_root, archive_path)

    assert built.archive_path == archive_path
    assert built.sha256_path == archive_path.with_name(archive_path.name + '.sha256')
    assert built.file_count == 4
    assert built.sha256_path.read_text(encoding='ascii') == (
        f'{built.sha256}  {archive_path.name}\n'
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert names == [
            'first-tenant-snapshot/legacy-full.sql',
            'first-tenant-snapshot/minio-export/courses/video.mp4',
            'first-tenant-snapshot/snapshot-manifest.json',
            'first-tenant-snapshot/uploads-export/resume.pdf',
            'first-tenant-snapshot/SHA256SUMS',
        ]
        checksum_rows = archive.read(
            'first-tenant-snapshot/SHA256SUMS'
        ).decode('ascii')
        assert 'uploads-export/resume.pdf' in checksum_rows
        assert 'minio-export/courses/video.mp4' in checksum_rows
        assert archive.getinfo(
            'first-tenant-snapshot/minio-export/courses/video.mp4'
        ).compress_type == zipfile.ZIP_STORED
        assert archive.getinfo(
            'first-tenant-snapshot/legacy-full.sql'
        ).compress_type == zipfile.ZIP_DEFLATED


@pytest.mark.parametrize(
    'relative_path',
    (
        '.env',
        'deployment.key',
        'certificate.crt',
        'secret.pem',
        'nested/password.txt',
    ),
)
def test_snapshot_archive_rejects_secret_or_configuration_members(
    tmp_path,
    relative_path,
):
    snapshot = _snapshot()
    snapshot_root = tmp_path / 'snapshot'
    prohibited = snapshot_root.joinpath(*relative_path.split('/'))
    prohibited.parent.mkdir(parents=True, exist_ok=True)
    prohibited.write_text('not-allowed', encoding='utf-8')

    with pytest.raises(snapshot.OperationSafetyError, match='prohibited'):
        snapshot.build_snapshot_archive(
            snapshot_root,
            tmp_path / 'snapshot.zip',
        )


def test_snapshot_archive_refuses_existing_output(tmp_path):
    snapshot = _snapshot()
    snapshot_root = tmp_path / 'snapshot'
    snapshot_root.mkdir()
    (snapshot_root / 'legacy-full.sql').write_text('SELECT 1;\n')
    archive_path = tmp_path / 'snapshot.zip'
    archive_path.write_bytes(b'existing')

    with pytest.raises(FileExistsError):
        snapshot.build_snapshot_archive(snapshot_root, archive_path)


def test_snapshot_cli_defaults_to_plan_and_execute_requires_phrase(tmp_path):
    cli = importlib.import_module('scripts.prepare_first_tenant_snapshot')
    source_root = tmp_path / 'source'
    output_root = tmp_path / 'output'
    source_root.mkdir()
    output_root.mkdir()
    plan_args = cli.parse_args(
        [
            '--source-root',
            str(source_root),
            '--output-root',
            str(output_root),
            '--snapshot-id',
            '20260715T102030Z',
        ]
    )
    assert plan_args.execute is False
    cli.validate_execution_policy(plan_args)

    missing_phrase = cli.parse_args(
        [
            '--source-root',
            str(source_root),
            '--output-root',
            str(output_root),
            '--snapshot-id',
            '20260715T102030Z',
            '--execute',
        ]
    )
    with pytest.raises(cli.OperationSafetyError, match='CAPTURE_HENGPINTONG_NEXT'):
        cli.validate_execution_policy(missing_phrase)

    confirmed = cli.parse_args(
        [
            '--source-root',
            str(source_root),
            '--output-root',
            str(output_root),
            '--snapshot-id',
            '20260715T102030Z',
            '--execute',
            '--confirm',
            'CAPTURE_HENGPINTONG_NEXT',
        ]
    )
    cli.validate_execution_policy(confirmed)
