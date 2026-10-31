"""Authoritative tenant storage measurement and quota enforcement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app, jsonify


STORAGE_QUOTA_MESSAGE = '企业存储空间已达上限，请删除文件或联系平台管理员扩容'
STORAGE_USAGE_UNAVAILABLE_MESSAGE = '对象存储用量暂时无法校验，本次上传已安全阻止'


@dataclass(frozen=True)
class StorageQuotaSnapshot:
    limit_bytes: int
    used_bytes: int
    projected_bytes: int


class StorageQuotaExceeded(Exception):
    code = 'STORAGE_QUOTA_EXCEEDED'
    status_code = 413

    def __init__(self, *, limit_bytes: int, used_bytes: int, projected_bytes: int):
        super().__init__(STORAGE_QUOTA_MESSAGE)
        self.limit_bytes = limit_bytes
        self.used_bytes = used_bytes
        self.projected_bytes = projected_bytes

    def to_payload(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'error': STORAGE_QUOTA_MESSAGE,
            'limitBytes': self.limit_bytes,
            'projectedBytes': self.projected_bytes,
            'usedBytes': self.used_bytes,
        }


class StorageUsageUnavailable(Exception):
    code = 'STORAGE_USAGE_UNAVAILABLE'
    status_code = 503

    def __init__(self):
        super().__init__(STORAGE_USAGE_UNAVAILABLE_MESSAGE)

    def to_payload(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'error': STORAGE_USAGE_UNAVAILABLE_MESSAGE,
        }


def register_storage_quota_error_handler(blueprint) -> None:
    """Install the same JSON response on every upload-owning blueprint."""

    def _handle_storage_quota(error: StorageQuotaExceeded):
        return jsonify(error.to_payload()), error.status_code

    blueprint.register_error_handler(StorageQuotaExceeded, _handle_storage_quota)
    blueprint.register_error_handler(StorageUsageUnavailable, _handle_storage_quota)


def _configured_local_root() -> Path | None:
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER')
    except RuntimeError:
        return None
    return Path(upload_folder) if upload_folder else None


def _sum_files(root: Path) -> int:
    if not root.is_dir():
        return 0
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [name for name in dirnames if not (directory_path / name).is_symlink()]
        for filename in filenames:
            path = directory_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
    return total


def sum_tenant_local_files(tenant_id: str, *, local_root: Path | None = None) -> int:
    root = Path(local_root) if local_root is not None else _configured_local_root()
    if root is None:
        return 0
    return sum(
        _sum_files(candidate)
        for candidate in (root / 'tenants' / tenant_id, root / tenant_id)
    )


def tenant_storage_usage_bytes(
    tenant_id: str,
    *,
    local_root: Path | None = None,
) -> int:
    from services import storage

    local_bytes = sum_tenant_local_files(tenant_id, local_root=local_root)
    object_bytes = sum(item.size for item in storage.list_tenant_objects(tenant_id))
    return local_bytes + object_bytes


def enforce_storage_quota(
    tenant,
    *,
    incoming_bytes: int,
    replacing_bytes: int = 0,
) -> StorageQuotaSnapshot:
    incoming = max(int(incoming_bytes or 0), 0)
    replacing = max(int(replacing_bytes or 0), 0)
    used = tenant_storage_usage_bytes(tenant.id)
    projected = max(used - replacing, 0) + incoming
    limit = max(int(tenant.max_storage_mb or 0), 0) * 1024 * 1024
    if limit and projected > limit:
        raise StorageQuotaExceeded(
            limit_bytes=limit,
            used_bytes=used,
            projected_bytes=projected,
        )
    return StorageQuotaSnapshot(
        limit_bytes=limit,
        used_bytes=used,
        projected_bytes=projected,
    )
