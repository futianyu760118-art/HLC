from __future__ import annotations

from pathlib import Path

import pytest

from ops.legacy_snapshot_runtime import (
    LocalSnapshotPaths,
    build_source_row_count_command,
    copy_snapshot_tooling,
)
from ops.operation_common import OperationSafetyError


SNAPSHOT_ID = '20260715T102030Z'


def test_local_snapshot_paths_are_deterministic_and_non_overwriting(tmp_path):
    paths = LocalSnapshotPaths.build(tmp_path, SNAPSHOT_ID)

    assert paths.staging_root == tmp_path / '.20260715T102030Z.staging'
    assert paths.snapshot_root == paths.staging_root / 'snapshot-data'
    assert paths.final_snapshot_root == (
        tmp_path / 'first-tenant-snapshot-20260715T102030Z'
    )
    assert paths.archive_path == (
        tmp_path / 'first-tenant-snapshot-20260715T102030Z.zip'
    )
    assert paths.archive_sha256_path == tmp_path / (
        'first-tenant-snapshot-20260715T102030Z.zip.sha256'
    )

    paths.archive_path.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        LocalSnapshotPaths.build(tmp_path, SNAPSHOT_ID)


def test_snapshot_tooling_copy_is_allowlisted_and_excludes_secrets(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    snapshot_root = tmp_path / 'snapshot'
    snapshot_root.mkdir()

    copied = copy_snapshot_tooling(repo_root, snapshot_root)

    assert 'server-migration/migrate-first-tenant.sh' in copied
    assert 'server-migration/hpt-release.sh' in copied
    assert 'server-migration/backend-python/scripts/hpt_release.py' in copied
    assert (
        'migration-toolkit/backend-python/scripts/restore_legacy_data.py'
        in copied
    )
    assert (
        'server-migration/backend-python/ops/server_migration.py'
        in copied
    )
    assert not any(
        path.endswith(('.env', '.key', '.crt', '.pem', '.zip'))
        or 'password' in path.lower()
        for path in copied
    )
    assert all(
        snapshot_root.joinpath(*path.split('/')).is_file()
        for path in copied
    )


def test_snapshot_tooling_rejects_symlinked_source(tmp_path):
    repo_root = tmp_path / 'repo'
    source = repo_root / 'migrate-first-tenant.sh'
    source.parent.mkdir(parents=True)
    target = tmp_path / 'outside.sh'
    target.write_text('outside', encoding='ascii')
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip('current Windows account cannot create symlinks')

    with pytest.raises(OperationSafetyError, match='tooling source'):
        copy_snapshot_tooling(repo_root, tmp_path / 'snapshot')


def test_source_row_count_command_uses_validated_identifier_without_shell_substitution():
    command = build_source_row_count_command(
        docker_command='docker',
        mysql_container='hengpintong-next-mysql-1',
        table_name='approval_instances',
    )

    assert command[-1].endswith(
        'SELECT COUNT(*) FROM approval_instances\" \"$MYSQL_DATABASE\"'
    )
    assert '`' not in command[-1]
    with pytest.raises(OperationSafetyError, match='table name'):
        build_source_row_count_command(
            docker_command='docker',
            mysql_container='hengpintong-next-mysql-1',
            table_name='approval_instances;DROP',
        )
