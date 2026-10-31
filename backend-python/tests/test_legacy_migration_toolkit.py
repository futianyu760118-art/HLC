from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


def _load_builder():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / 'scripts' / 'build-legacy-migration-toolkit.py'
    spec = importlib.util.spec_from_file_location(
        'legacy_migration_toolkit_builder',
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_toolkit_archive_contains_only_allowlisted_payload_and_verified_hashes(
    tmp_path,
):
    builder = _load_builder()
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = tmp_path / 'legacy-migration-toolkit'

    archive_path = builder.build_toolkit(
        repo_root=repo_root,
        output_dir=output_dir,
        label='20260715-test',
    )

    assert archive_path == output_dir / 'legacy-migration-toolkit-20260715-test.zip'
    checksum_path = archive_path.with_name(archive_path.name + '.sha256')
    assert checksum_path.is_file()
    assert checksum_path.read_text(encoding='ascii') == (
        f'{hashlib.sha256(archive_path.read_bytes()).hexdigest()}  '
        f'{archive_path.name}\n'
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        prefix = 'legacy-migration-toolkit/'
        assert 'legacy-migration-toolkit/SHA256SUMS' in names
        assert 'legacy-migration-toolkit/release-manifest.json' in names
        assert 'legacy-migration-toolkit/README.md' in names
        assert all(name.startswith(prefix) for name in names)
        assert not any(
            name.endswith(('.env', '.key', '.crt', '.sql', '.zip'))
            or '/artifacts/' in name
            or '/uploads/' in name
            for name in names
        )

        checksums = archive.read('legacy-migration-toolkit/SHA256SUMS')
        checksum_rows = {}
        for line in checksums.decode('ascii').splitlines():
            digest, relative_name = line.split('  ', 1)
            checksum_rows[relative_name] = digest

        assert 'README.md' in checksum_rows
        assert 'release-manifest.json' in checksum_rows
        for relative_name, digest in checksum_rows.items():
            payload = archive.read(prefix + relative_name)
            assert hashlib.sha256(payload).hexdigest() == digest

        manifest = json.loads(
            archive.read('legacy-migration-toolkit/release-manifest.json')
        )
        assert manifest['format'] == 'hengpintong-legacy-migration-toolkit-v1'
        assert manifest['label'] == '20260715-test'
        manifest_paths = {item['path'] for item in manifest['payload']}
        assert 'backend-python/scripts/restore_legacy_data.py' in manifest_paths
        assert 'backend-python/services/legacy_tenant_migration.py' in manifest_paths
        assert 'backend-python/services/legacy_tenant_files.py' in manifest_paths
        assert 'backend-python/ops/operation_common.py' in manifest_paths
        assert 'backend-python/ops/server_migration.py' in manifest_paths
        assert 'backend-python/ops/server_prepare.py' in manifest_paths
        assert 'backend-python/ops/server_internal.py' in manifest_paths
        assert 'backend-python/ops/candidate_tenant.py' in manifest_paths
        assert (
            'backend-python/scripts/server_first_tenant_migration.py'
            in manifest_paths
        )
        assert (
            'backend-python/scripts/server_migration_internal.py'
            in manifest_paths
        )
        assert 'migrate-first-tenant.sh' in manifest_paths
        assert 'hpt-release.sh' in manifest_paths
        assert 'backend-python/scripts/hpt_release.py' in manifest_paths
        assert 'prepare-first-tenant-snapshot.ps1' in manifest_paths
        assert all(path in checksum_rows for path in manifest_paths)


@pytest.mark.parametrize('label', ('', '../escape', 'with space'))
def test_toolkit_builder_rejects_unsafe_labels(tmp_path, label):
    builder = _load_builder()
    repo_root = Path(__file__).resolve().parents[2]

    with pytest.raises(ValueError, match='label'):
        builder.build_toolkit(
            repo_root=repo_root,
            output_dir=tmp_path / 'bundle',
            label=label,
        )


def test_toolkit_builder_refuses_to_overwrite_an_existing_output_directory(
    tmp_path,
):
    builder = _load_builder()
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = tmp_path / 'bundle'
    output_dir.mkdir()

    with pytest.raises(FileExistsError, match='output directory'):
        builder.build_toolkit(
            repo_root=repo_root,
            output_dir=output_dir,
            label='20260715-test',
        )
