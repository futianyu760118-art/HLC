"""Build a data-free, hash-verifiable legacy migration toolkit archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile


LABEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$', re.ASCII)
ARCHIVE_PREFIX = 'legacy-migration-toolkit/'
FORMAT = 'hengpintong-legacy-migration-toolkit-v1'
PAYLOAD_PATHS = (
    'migrate-first-tenant.sh',
    'hpt-release.sh',
    'docker-compose.release.yml',
    'prepare-first-tenant-snapshot.ps1',
    'backend-python/requirements.txt',
    'backend-python/ops/__init__.py',
    'backend-python/ops/operation_common.py',
    'backend-python/ops/legacy_snapshot.py',
    'backend-python/ops/legacy_snapshot_runtime.py',
    'backend-python/ops/server_migration.py',
    'backend-python/ops/server_prepare.py',
    'backend-python/ops/server_internal.py',
    'backend-python/ops/candidate_tenant.py',
    'backend-python/ops/release_bundle.py',
    'backend-python/ops/release_manager.py',
    'backend-python/ops/release_transport.py',
    'backend-python/scripts/hpt_release.py',
    'backend-python/scripts/prepare_first_tenant_snapshot.py',
    'backend-python/scripts/restore_legacy_data.py',
    'backend-python/scripts/server_first_tenant_migration.py',
    'backend-python/scripts/server_migration_internal.py',
    'backend-python/services/legacy_tenant_files.py',
    'backend-python/services/legacy_tenant_migration.py',
    'backend-python/tests/conftest.py',
    'backend-python/tests/test_candidate_tenant.py',
    'backend-python/tests/test_legacy_tenant_files.py',
    'backend-python/tests/test_legacy_tenant_migration.py',
    'backend-python/tests/test_legacy_snapshot.py',
    'backend-python/tests/test_legacy_snapshot_runtime.py',
    'backend-python/tests/test_operation_common.py',
    'backend-python/tests/test_release_bundle.py',
    'backend-python/tests/test_release_manager.py',
    'backend-python/tests/test_release_transport.py',
    'backend-python/tests/test_server_first_tenant_migration.py',
    'backend-python/tests/test_server_prepare.py',
    'docs/data-restore-runbook.md',
    'pytest.ini',
)


def _validate_label(label: str) -> str:
    if not isinstance(label, str) or LABEL_RE.fullmatch(label) is None:
        raise ValueError(
            'label must contain only ASCII letters, digits, dots, underscores, '
            'or hyphens and start with a letter or digit'
        )
    return label


def _validate_repo_root(repo_root: Path) -> Path:
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise ValueError('repo_root must be an existing non-symlink directory')
    return repo_root.resolve(strict=True)


def _read_allowlisted_file(repo_root: Path, relative_path: str) -> bytes:
    source_path = repo_root.joinpath(*relative_path.split('/'))
    if source_path.is_symlink() or not source_path.is_file():
        raise FileNotFoundError(
            f'allowlisted toolkit source is missing or unsafe: {relative_path}'
        )
    try:
        source_path.resolve(strict=True).relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f'allowlisted toolkit source escapes repo root: {relative_path}'
        ) from exc
    return source_path.read_bytes()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _metadata(path: str, payload: bytes) -> dict[str, object]:
    return {
        'path': path,
        'size_bytes': len(payload),
        'sha256': _sha256(payload),
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + '\n'
    ).encode('utf-8')


def _readme(label: str) -> bytes:
    return (
        f'''# 恒聘通 SaaS 首租户迁移工具包

格式：`{FORMAT}`
发布标签：`{label}`

本包只包含迁移工具、专项测试、依赖声明和 runbook，不包含数据库 dump、
uploads、MinIO/S3 对象、`.env`、证书、私钥或任何业务数据。

## 校验

先核对包外的 `.zip.sha256`，再在解压目录执行：

```bash
sha256sum -c legacy-migration-toolkit/SHA256SUMS
```

## 使用边界

只允许预创建的 `_stage_` / `_candidate_` 数据库。工具默认 dry-run；正式执行
必须显式提供 `--execute --confirm MIGRATE_LEGACY_TO_CANDIDATE`。请按
`docs/data-restore-runbook.md` 取得新鲜 dump、完整对象导出、服务器备份和
回滚证据后再操作。
'''
    ).encode('utf-8')


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_toolkit(
    *,
    repo_root: Path,
    output_dir: Path,
    label: str,
) -> Path:
    """Create a new toolkit directory and return its archive path."""

    safe_label = _validate_label(label)
    safe_repo_root = _validate_repo_root(Path(repo_root))
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError('output directory already exists')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir()

    source_payloads = [
        (relative_path, _read_allowlisted_file(safe_repo_root, relative_path))
        for relative_path in PAYLOAD_PATHS
    ]
    readme_payload = _readme(safe_label)
    payloads = [*source_payloads, ('README.md', readme_payload)]
    manifest = {
        'format': FORMAT,
        'label': safe_label,
        'payload': [
            _metadata(relative_path, payload)
            for relative_path, payload in payloads
        ],
    }
    manifest_payload = _json_bytes(manifest)
    checksum_payloads = [
        *payloads,
        ('release-manifest.json', manifest_payload),
    ]
    checksum_payload = ''.join(
        f'{_sha256(payload)}  {relative_path}\n'
        for relative_path, payload in checksum_payloads
    ).encode('ascii')

    archive_path = output_dir / f'legacy-migration-toolkit-{safe_label}.zip'
    with zipfile.ZipFile(
        archive_path,
        mode='x',
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative_path, payload in (
            *payloads,
            ('release-manifest.json', manifest_payload),
            ('SHA256SUMS', checksum_payload),
        ):
            archive.writestr(
                _zip_info(ARCHIVE_PREFIX + relative_path),
                payload,
            )

    checksum_path = output_dir / f'{archive_path.name}.sha256'
    checksum_path.write_text(
        f'{_sha256(archive_path.read_bytes())}  {archive_path.name}\n',
        encoding='ascii',
    )
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--repo-root',
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        '--output-root',
        type=Path,
        help='directory under which a new toolkit output directory is created',
    )
    parser.add_argument(
        '--label',
        default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
    )
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    output_root = (
        Path(args.output_root)
        if args.output_root is not None
        else repo_root / 'artifacts' / 'db-restore'
    )
    output_dir = output_root / f'legacy-migration-toolkit-{args.label}'
    archive_path = build_toolkit(
        repo_root=repo_root,
        output_dir=output_dir,
        label=args.label,
    )
    print(f'toolkit={archive_path}')
    print(f'checksum={archive_path}.sha256')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
