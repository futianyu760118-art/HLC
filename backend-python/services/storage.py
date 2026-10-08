"""对象存储封装（视频/大文件）。

设计：
- 首选 MinIO（S3 兼容），通过环境变量配置；未配置或连接失败时**自动回退到本地磁盘**，
  保证开发环境无需部署 MinIO 也能跑通流程。
- 上层只关心 `upload_video` / `presigned_url` / `delete_object` 三个语义；
  key 形如 ``courses/{course_id}/{hour_id}.mp4``。
- 回退模式下：文件写到 UPLOAD_FOLDER 下同名子路径，presigned_url 返回
  ``/uploads/{key}``，由 app.py 的鉴权文件代理兼容处理。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger('hengpintong.storage')

# --- 配置（env） ----------------------------------------------------------
_MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', '').strip()  # e.g. minio:9000
_MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', '').strip()
_MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', '').strip()
_MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'hrm-courses').strip() or 'hrm-courses'
_MINIO_SECURE = os.getenv('MINIO_SECURE', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
_PRESIGN_HOURS = int(os.getenv('MINIO_PRESIGN_HOURS', '2'))
_MEDIA_STREAM_CHUNK_BYTES = 1024 * 1024

# 运行期单例
_client = None
_client_inited = False
_use_minio = False
_last_client_attempt = 0.0
_client_retry_seconds = max(float(os.getenv('MINIO_RETRY_SECONDS', '15')), 1.0)

_TENANT_WRITE_LEASES_KEY = 'tenant_storage_write_leases'
_tenant_write_locks: dict[str, threading.Lock] = {}
_tenant_write_locks_guard = threading.Lock()
_tenant_write_listener_guard = threading.Lock()
_tenant_write_listener_registered = False


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int


class StorageTenantBindingError(ValueError):
    """A stable, non-sensitive error for unsafe persistent storage binding."""

    _MESSAGES = {
        'STORAGE_TENANT_BINDING_REQUIRED': '持久化存储写入必须显式绑定企业',
        'STORAGE_CROSS_TENANT_KEY': '存储对象不属于当前企业',
        'STORAGE_TENANT_NOT_FOUND': '存储写入绑定的企业不存在',
    }

    def __init__(self, code: str):
        self.code = code
        super().__init__(self._MESSAGES.get(code, '存储企业绑定无效'))

    def to_payload(self) -> dict[str, str]:
        return {'code': self.code, 'error': str(self)}


def _upload_folder() -> Path:
    """本地回退模式的根目录（即 Flask UPLOAD_FOLDER）。"""
    from flask import current_app
    return Path(current_app.config['UPLOAD_FOLDER'])


def _get_client():
    """惰性初始化 MinIO 客户端。返回 client 或 None（不可用）。"""
    global _client, _client_inited, _use_minio, _last_client_attempt
    if _use_minio and _client is not None:
        return _client
    if not (_MINIO_ENDPOINT and _MINIO_ACCESS_KEY and _MINIO_SECRET_KEY):
        _client_inited = True
        return None
    now = time.monotonic()
    if _client_inited and now - _last_client_attempt < _client_retry_seconds:
        return None
    _client_inited = True
    _last_client_attempt = now
    try:
        from minio import Minio  # type: ignore
        _client = Minio(
            _MINIO_ENDPOINT,
            access_key=_MINIO_ACCESS_KEY,
            secret_key=_MINIO_SECRET_KEY,
            secure=_MINIO_SECURE,
        )
        # 确保 bucket 存在
        if not _client.bucket_exists(_MINIO_BUCKET):
            _client.make_bucket(_MINIO_BUCKET)
            logger.info('storage_minio_bucket_created', extra={'bucket': _MINIO_BUCKET})
        _use_minio = True
        logger.info('storage_minio_ready', extra={'endpoint': _MINIO_ENDPOINT, 'bucket': _MINIO_BUCKET})
        return _client
    except Exception as exc:  # 导入失败/连接失败 → 回退本地
        logger.warning('storage_minio_init_failed_fallback_local', extra={'error': str(exc)})
        _use_minio = False
        _client = None
        return None


def init_bucket() -> None:
    """启动时调用，预建 bucket（失败不致命，已回退本地）。"""
    _get_client()


def storage_readiness() -> dict[str, object]:
    """Return a live storage status and retry a previously unavailable MinIO."""
    global _client, _use_minio
    if not (_MINIO_ENDPOINT and _MINIO_ACCESS_KEY and _MINIO_SECRET_KEY):
        return {'ok': True, 'mode': 'local', 'configured': False}

    client = _get_client()
    if client is None:
        return {'ok': False, 'mode': 'minio', 'configured': True, 'error': 'object storage unavailable'}
    try:
        if not client.bucket_exists(_MINIO_BUCKET):
            client.make_bucket(_MINIO_BUCKET)
        return {'ok': True, 'mode': 'minio', 'configured': True, 'bucket': _MINIO_BUCKET}
    except Exception as exc:
        _client = None
        _use_minio = False
        logger.warning('storage_readiness_failed', extra={'error': str(exc)})
        return {'ok': False, 'mode': 'minio', 'configured': True, 'error': 'object storage unavailable'}


def is_minio_enabled() -> bool:
    return _get_client() is not None


def _safe_key(object_key: str) -> str:
    """规范 key：去掉前导斜杠，禁止 .. 穿越。"""
    if '\\' in object_key:
        raise ValueError(f'非法 object key: {object_key}')
    key = object_key.lstrip('/')
    if '..' in key.split('/'):
        raise ValueError(f'非法 object key: {object_key}')
    return key


def _resolve_write_tenant_id(
    tenant_id: str | None,
    *,
    allow_unscoped: bool,
) -> str | None:
    explicit_tenant_id = str(tenant_id or '').strip() or None
    if explicit_tenant_id:
        _tenant_prefix(explicit_tenant_id)
    try:
        from services.tenancy import current_tenant_id
        request_tenant_id = current_tenant_id()
    except Exception:
        request_tenant_id = None
    request_tenant_id = str(request_tenant_id or '').strip() or None
    if request_tenant_id and explicit_tenant_id and request_tenant_id != explicit_tenant_id:
        raise StorageTenantBindingError('STORAGE_CROSS_TENANT_KEY')
    resolved = explicit_tenant_id or request_tenant_id
    if resolved:
        return resolved
    if allow_unscoped:
        return None
    raise StorageTenantBindingError('STORAGE_TENANT_BINDING_REQUIRED')


def tenant_object_key(
    object_key: str,
    *,
    tenant_id: str | None = None,
    allow_unscoped: bool = False,
) -> str:
    """Bind a persistent object key to exactly one tenant unless explicitly bypassed."""
    key = _safe_key(object_key)
    resolved_tenant_id = _resolve_write_tenant_id(
        tenant_id,
        allow_unscoped=allow_unscoped,
    )
    if key.startswith('tenants/'):
        parts = key.split('/')
        if (
            resolved_tenant_id is None
            or len(parts) < 3
            or not parts[1]
            or parts[1] != resolved_tenant_id
        ):
            raise StorageTenantBindingError('STORAGE_CROSS_TENANT_KEY')
        return key
    if resolved_tenant_id:
        return f'tenants/{resolved_tenant_id}/{key}'
    return key


def _tenant_prefix(tenant_id: str) -> str:
    segment = str(tenant_id or '').strip()
    if not segment or '/' in segment or '\\' in segment or segment in {'.', '..'}:
        raise ValueError('非法 tenant id')
    return f'tenants/{segment}/'


def _tenant_write_lock_statement(tenant_id: str):
    """Return the cross-worker MySQL row-lock statement for one tenant."""
    from sqlalchemy import select
    from models import Tenant

    return select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()


def _release_session_tenant_write_leases(session) -> None:
    leases = session.info.pop(_TENANT_WRITE_LEASES_KEY, {})
    for local_lock in leases.values():
        if local_lock is not None:
            local_lock.release()


def _storage_session_transaction_ended(session, transaction) -> None:
    if transaction.parent is None:
        _release_session_tenant_write_leases(session)


def _register_tenant_write_listener() -> None:
    global _tenant_write_listener_registered
    if _tenant_write_listener_registered:
        return
    with _tenant_write_listener_guard:
        if _tenant_write_listener_registered:
            return
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        event.listen(Session, 'after_transaction_end', _storage_session_transaction_ended)
        _tenant_write_listener_registered = True


def _local_tenant_write_lock(tenant_id: str) -> threading.Lock:
    with _tenant_write_locks_guard:
        return _tenant_write_locks.setdefault(tenant_id, threading.Lock())


def _acquire_tenant_write_lease(tenant_id: str) -> None:
    """Serialize one tenant's quota measurement and physical write.

    MySQL uses a tenant-row ``FOR UPDATE`` lock, which works across Gunicorn
    workers. SQLite ignores row locks, so tests and local preview additionally
    use a process-local tenant mutex. The lease follows the caller SQLAlchemy
    transaction and is also released when Flask-SQLAlchemy removes the session
    at request teardown.
    """
    from models import db

    _register_tenant_write_listener()
    session = db.session()
    leases = session.info.setdefault(_TENANT_WRITE_LEASES_KEY, {})
    if tenant_id in leases:
        return

    dialect_name = session.get_bind().dialect.name
    local_lock = _local_tenant_write_lock(tenant_id) if dialect_name == 'sqlite' else None
    if local_lock is not None:
        local_lock.acquire()
    try:
        if not session.in_transaction():
            session.begin()
        if dialect_name != 'sqlite':
            with session.no_autoflush:
                locked_tenant_id = session.execute(
                    _tenant_write_lock_statement(tenant_id).execution_options(
                        autoflush=False,
                        skip_tenant_criteria=True,
                    )
                ).scalar_one_or_none()
            if locked_tenant_id is None:
                raise StorageTenantBindingError('STORAGE_TENANT_NOT_FOUND')
        leases[tenant_id] = local_lock
    except Exception:
        if local_lock is not None:
            local_lock.release()
        if not leases:
            session.info.pop(_TENANT_WRITE_LEASES_KEY, None)
        raise


def _object_storage_configured() -> bool:
    return bool(_MINIO_ENDPOINT and _MINIO_ACCESS_KEY and _MINIO_SECRET_KEY)


def list_tenant_objects(tenant_id: str) -> list[StoredObject]:
    """List only objects below one tenant's exact MinIO prefix."""
    prefix = _tenant_prefix(tenant_id)
    client = _get_client()
    if client is None:
        if _object_storage_configured():
            from services.tenant_storage_quota import StorageUsageUnavailable
            raise StorageUsageUnavailable()
        return []
    try:
        rows = client.list_objects(_MINIO_BUCKET, prefix=prefix, recursive=True)
        return [
            StoredObject(key=str(row.object_name), size=max(int(row.size or 0), 0))
            for row in rows
            if str(getattr(row, 'object_name', '')).startswith(prefix)
        ]
    except Exception as exc:
        logger.warning('storage_tenant_list_failed', extra={'tenant_id': tenant_id, 'error': str(exc)})
        from services.tenant_storage_quota import StorageUsageUnavailable
        raise StorageUsageUnavailable() from exc


def _target_object_size(key: str, client) -> int:
    if client is not None:
        try:
            stat = client.stat_object(_MINIO_BUCKET, key)
            return max(int(getattr(stat, 'size', 0) or 0), 0)
        except Exception:
            return 0
    target = _upload_folder() / key
    return target.stat().st_size if target.is_file() else 0


def _stream_and_remaining_size(file_obj):
    stream = getattr(file_obj, 'stream', file_obj)
    try:
        position = stream.tell()
        stream.seek(0, 2)
        end = stream.tell()
        stream.seek(position)
    except (AttributeError, OSError) as exc:
        raise ValueError('上传文件必须是可计量的二进制流') from exc
    return stream, max(end - position, 0)


def _bound_tenant(tenant_id: str | None):
    if not tenant_id:
        return None
    try:
        from services.tenancy import current_tenant
        tenant = current_tenant()
    except Exception:
        tenant = None
    if tenant is not None and tenant.id == tenant_id:
        return tenant
    from models import Tenant, db
    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None:
        raise StorageTenantBindingError('STORAGE_TENANT_NOT_FOUND')
    return tenant


def _enforce_tenant_quota(
    file_obj,
    key: str,
    client,
    tenant_id: str | None,
    *,
    replacing_key: str | None = None,
):
    stream, incoming_bytes = _stream_and_remaining_size(file_obj)
    if tenant_id:
        _acquire_tenant_write_lease(tenant_id)
    tenant = _bound_tenant(tenant_id)
    if tenant is not None:
        from services.tenant_storage_quota import enforce_storage_quota
        if replacing_key is None or replacing_key == key:
            replacing_bytes = _target_object_size(key, client)
        elif (
            tenant_id
            and replacing_key.startswith(_tenant_prefix(tenant_id))
            and _persistent_storage_reference_count(replacing_key, tenant_id) <= 1
        ):
            replacing_bytes = _target_object_size(replacing_key, client)
        else:
            replacing_bytes = 0
        enforce_storage_quota(
            tenant,
            incoming_bytes=incoming_bytes,
            replacing_bytes=replacing_bytes,
        )
    return stream, incoming_bytes


def save_local_upload(
    file_obj,
    object_key: str,
    *,
    tenant_id: str | None = None,
    allow_unscoped: bool = False,
) -> str:
    """Save a Werkzeug upload locally using the tenant-prefixed object key."""
    resolved_tenant_id = _resolve_write_tenant_id(tenant_id, allow_unscoped=allow_unscoped)
    key = tenant_object_key(
        object_key,
        tenant_id=resolved_tenant_id,
        allow_unscoped=allow_unscoped,
    )
    _enforce_tenant_quota(file_obj, key, None, resolved_tenant_id)
    dest_dir = _upload_folder() / Path(key).parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(key).name
    file_obj.save(dest)
    return key


def upload_video(
    file_obj,
    object_key: str,
    content_type: str = 'video/mp4',
    *,
    tenant_id: str | None = None,
    allow_unscoped: bool = False,
    replacing_object_key: str | None = None,
) -> str:
    """上传文件，返回 object_key（不返回 URL，URL 用 presigned_url 取）。

    file_obj: 已打开的二进制文件对象（有 read() 且可 seek）。
    """
    resolved_tenant_id = _resolve_write_tenant_id(tenant_id, allow_unscoped=allow_unscoped)
    key = tenant_object_key(
        object_key,
        tenant_id=resolved_tenant_id,
        allow_unscoped=allow_unscoped,
    )
    client = _get_client()
    replacing_key = None
    if replacing_object_key:
        replacing_key = object_key_from_reference(replacing_object_key)
        if not replacing_key:
            raise ValueError('替换对象键无效')
        assert_storage_references_belong_to_tenant(
            {replacing_key},
            tenant_id=resolved_tenant_id,
        )
    stream, _incoming_bytes = _enforce_tenant_quota(
        file_obj,
        key,
        client,
        resolved_tenant_id,
        replacing_key=replacing_key,
    )
    if client is not None:
        data = stream.read()
        client.put_object(
            _MINIO_BUCKET, key, BytesIO(data), length=len(data),
            content_type=content_type,
        )
        return key
    # 本地回退
    dest_dir = _upload_folder() / Path(key).parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(key).name
    with open(dest, 'wb') as fh:
        fh.write(stream.read())
    return key


def presigned_url(object_key: str, expires_hours: Optional[int] = None) -> str:
    """获取可访问 URL（MinIO 预签名 / 本地相对 URL）。"""
    if not object_key:
        return ''
    key = _safe_key(object_key)
    client = _get_client()
    if client is not None:
        from datetime import timedelta
        hours = expires_hours if expires_hours is not None else _PRESIGN_HOURS
        return client.presigned_get_object(_MINIO_BUCKET, key, expires=timedelta(hours=hours))
    return f'/uploads/{key}'


def upload_file(
    file_obj,
    object_key: str,
    content_type: str = 'application/octet-stream',
    *,
    tenant_id: str | None = None,
    allow_unscoped: bool = False,
    replacing_object_key: str | None = None,
) -> str:
    """通用文件上传（简历/证书/封面等），返回 object_key。

    与 upload_video 语义一致，但默认 content_type 为通用二进制。
    file_obj: 已打开的文件对象（有 read() 且可 seek）。
    """
    return upload_video(
        file_obj,
        object_key,
        content_type,
        tenant_id=tenant_id,
        allow_unscoped=allow_unscoped,
        replacing_object_key=replacing_object_key,
    )


def file_exists(object_key: str) -> bool:
    """检查对象是否存在（MinIO / 本地）。"""
    if not object_key:
        return False
    key = _safe_key(object_key)
    client = _get_client()
    if client is not None:
        try:
            client.stat_object(_MINIO_BUCKET, key)
            return True
        except Exception:
            return False
    target = _upload_folder() / key
    return target.is_file()


def download_to_file(object_key: str, dest_path) -> Path:
    """下载对象到本地文件（MinIO / 本地直接复制）。返回目标路径。

    用于需要本地文件路径的场景（如 PDF 文本提取）。
    """
    key = _safe_key(object_key)
    client = _get_client()
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if client is not None:
        client.fget_object(_MINIO_BUCKET, key, str(dest))
    else:
        import shutil
        shutil.copy2(_upload_folder() / key, dest)
    return dest


def delete_object(object_key: str) -> None:
    """删除对象（失败仅日志，不抛）。"""
    if not object_key:
        return
    key = _safe_key(object_key)
    client = _get_client()
    try:
        if client is not None:
            client.remove_object(_MINIO_BUCKET, key)
        else:
            target = _upload_folder() / key
            if target.is_file():
                target.unlink()
    except Exception as exc:
        logger.warning('storage_delete_failed', extra={'key': key, 'error': str(exc)})


def object_key_from_reference(reference: object) -> str | None:
    """Return a safe local/object key from a persisted storage reference."""
    if not isinstance(reference, str):
        return None
    value = reference.strip()
    if not value:
        return None
    if value.startswith('/uploads/'):
        value = value[len('/uploads/'):]
    elif value.startswith('uploads/'):
        value = value[len('uploads/'):]
    elif value.startswith('/') or '://' in value:
        return None
    try:
        return _safe_key(value)
    except ValueError:
        return None


def storage_reference_keys(value: object) -> set[str]:
    """Collect storage keys conservatively from scalar or JSON reference data."""
    if isinstance(value, dict):
        keys: set[str] = set()
        reference_fields = {
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
            'videoKey',
            'video_key',
        }
        for field, nested in value.items():
            if field in reference_fields or isinstance(nested, (dict, list, tuple, set)):
                keys.update(storage_reference_keys(nested))
        return keys
    if isinstance(value, (list, tuple, set)):
        keys = set()
        for nested in value:
            keys.update(storage_reference_keys(nested))
        return keys
    key = object_key_from_reference(value)
    return {key} if key else set()


def assert_storage_references_belong_to_tenant(
    references: object,
    *,
    tenant_id: str | None,
) -> None:
    """Reject only explicit tenant-prefixed keys owned by another tenant."""
    keys = storage_reference_keys(references)
    if not keys:
        return
    resolved_tenant_id = str(tenant_id or '').strip()
    if not resolved_tenant_id:
        raise StorageTenantBindingError('STORAGE_TENANT_BINDING_REQUIRED')
    expected_prefix = _tenant_prefix(resolved_tenant_id)
    for key in keys:
        if key.startswith('tenants/') and not key.startswith(expected_prefix):
            raise StorageTenantBindingError('STORAGE_CROSS_TENANT_KEY')


def _persistent_storage_reference_values(tenant_id: str | None) -> list[str]:
    from models import (
        Certificate,
        Contract,
        Course,
        CourseAttachment,
        CourseChapter,
        CourseHour,
        Employee,
        Feedback,
        Interview,
        LearningPath,
        Resume,
        db,
    )

    references: list[str] = []
    scalar_fields = (
        (Course, (Course.cover_url,)),
        (CourseAttachment, (CourseAttachment.file_url,)),
        (CourseHour, (CourseHour.video_key,)),
        (Interview, (Interview.feedback_file_url, Interview.recording_url)),
        (Resume, (Resume.file_url,)),
        (Contract, (Contract.attachment_url,)),
        (LearningPath, (LearningPath.cover_url,)),
        (Certificate, (Certificate.image_url,)),
    )
    for model, fields in scalar_fields:
        query = db.session.query(*fields)
        if tenant_id is None:
            query = query.execution_options(skip_tenant_criteria=True)
        else:
            query = query.filter(model.tenant_id == tenant_id)
        rows = query.all()
        for row in rows:
            for value in row:
                references.extend(storage_reference_keys(value))
    json_fields = (
        (CourseChapter, CourseChapter.materials),
        (Employee, Employee.attachments),
        (Feedback, Feedback.attachments),
    )
    for model, field in json_fields:
        query = db.session.query(field)
        if tenant_id is None:
            query = query.execution_options(skip_tenant_criteria=True)
        else:
            query = query.filter(model.tenant_id == tenant_id)
        for row in query.all():
            references.extend(storage_reference_keys(row[0]))
    return references


def _persistent_storage_references(tenant_id: str | None) -> set[str]:
    return set(_persistent_storage_reference_values(tenant_id))


def _persistent_storage_reference_count(key: str, tenant_id: str | None) -> int:
    return sum(
        1
        for reference in _persistent_storage_reference_values(tenant_id)
        if reference == key
    )


def delete_object_if_unreferenced(
    reference: object,
    *,
    tenant_id: str | None = None,
) -> bool:
    """Delete only after commit and after the required reference scope is empty."""
    key = object_key_from_reference(reference)
    if not key:
        return False
    resolved_tenant_id = _resolve_write_tenant_id(tenant_id, allow_unscoped=False)
    if key.startswith('tenants/'):
        parts = key.split('/')
        if len(parts) < 3 or parts[1] != resolved_tenant_id:
            logger.warning('storage_delete_cross_tenant_blocked')
            return False
        reference_tenant_id = resolved_tenant_id
    else:
        # Legacy unprefixed objects may be shared by old rows across tenants.
        reference_tenant_id = None
    if key in _persistent_storage_references(reference_tenant_id):
        return False
    delete_object(key)
    return True


class _MinioMediaBody:
    """A closeable MinIO iterator that releases the connection on every path."""

    def __init__(self, response, object_key: str):
        self._response = response
        self._object_key = object_key
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        try:
            chunk = self._response.read(_MEDIA_STREAM_CHUNK_BYTES)
        except Exception as exc:
            logger.warning('media_range_stream_failed', extra={'key': self._object_key, 'error': str(exc)})
            self.close()
            raise
        if not chunk:
            self.close()
            raise StopIteration
        return chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        finally:
            self._response.release_conn()


def stream_media_range(object_key: str, range_header: str = ''):
    """返回 (status, headers, body) 用于流式分发媒体文件，支持 Range 请求。

    优先策略：
    - 本地有文件：返回本地路径信息，交由调用方 send_from_directory（原生支持 Range）。
    - 本地无文件但 MinIO 有：用 get_object(offset, length) 读取请求范围，
      返回 206 + Content-Range；无 Range 时返回 200 全量。

    返回结构：
        {'mode': 'local', 'path': str, 'filename': str}  → 调用方用 send_from_directory
        {'mode': 'stream', 'status': int, 'headers': dict, 'body': bytes iterable}
        {'mode': 'not_found'}
    """
    key = _safe_key(object_key)
    local_path = _upload_folder() / key
    if local_path.is_file():
        return {'mode': 'local', 'path': str(_upload_folder()), 'filename': key}

    client = _get_client()
    if client is None:
        return {'mode': 'not_found'}
    try:
        stat = client.stat_object(_MINIO_BUCKET, key)
    except Exception as exc:
        logger.warning('media_stat_failed', extra={'key': key, 'error': str(exc)})
        return {'mode': 'not_found'}

    total = int(getattr(stat, 'size', 0) or 0)
    if total <= 0:
        return {'mode': 'not_found'}

    import mimetypes
    ctype = mimetypes.guess_type(key)[0] or 'application/octet-stream'
    safe_name = key.split('/')[-1] or 'media'

    # 解析 Range: bytes=start-end
    start, end = 0, total - 1
    is_range = False
    if range_header and range_header.startswith('bytes='):
        spec = range_header[6:].split(',')[0].strip()
        if '-' in spec:
            s_str, e_str = spec.split('-', 1)
            if s_str:
                start = int(s_str)
                if e_str:
                    end = int(e_str)
                # start 已确定，end 保持 total-1（或指定值）
            else:
                # suffix range: bytes=-N (最后 N 字节)
                n = int(e_str) if e_str else total
                start = max(0, total - n)
            end = min(end, total - 1)
            is_range = True
    if start > end or start >= total:
        return {'mode': 'stream', 'status': 416,
                'headers': {'Content-Range': f'bytes */{total}'},
                'body': b''}

    length = end - start + 1
    try:
        resp = client.get_object(_MINIO_BUCKET, key, offset=start, length=length)
    except Exception as exc:
        logger.warning('media_range_read_failed', extra={'key': key, 'error': str(exc)})
        return {'mode': 'not_found'}
    body = _MinioMediaBody(resp, key)

    headers = {
        'Content-Type': ctype,
        'Content-Length': str(length),
        'Cache-Control': 'private, max-age=3600',
        'Accept-Ranges': 'bytes',
    }
    if is_range:
        headers['Content-Range'] = f'bytes {start}-{end}/{total}'
        return {'mode': 'stream', 'status': 206, 'headers': headers, 'body': body}
    headers['Content-Disposition'] = f'inline; filename="{safe_name}"'
    return {'mode': 'stream', 'status': 200, 'headers': headers, 'body': body}
