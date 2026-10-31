"""Helpers executed inside an isolated backend image during migration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Mapping
from urllib import error as urlerror
from urllib import request as urlrequest

from ops.candidate_tenant import (
    CandidateBootstrapConfig,
    CandidateBootstrapResult,
    FIRST_TENANT_SLUG,
    MySQLCandidateControlStore,
    assert_candidate_ready,
    bootstrap_candidate_tenant,
    ensure_candidate_tenant_controls,
    remove_temporary_validation_admin,
    write_validation_credentials,
)
from ops.operation_common import (
    OperationSafetyError,
    ensure_relative_member,
    sha256_file,
    write_atomic_json,
)
from ops.server_migration import BUCKET_RE, DATABASE_RE


RESTORE_PROOF_BUCKET_RE = re.compile(
    r'^hrm-restoreproof-\d{8}t\d{6}z$',
    re.ASCII,
)


def load_tenant_profile(path: Path) -> dict[str, object]:
    profile_path = Path(path)
    if profile_path.is_symlink() or not profile_path.is_file():
        raise OperationSafetyError('tenant profile is missing or unsafe')
    try:
        value = json.loads(profile_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('tenant profile JSON is invalid') from exc
    expected = {'slug', 'name', 'planCode', 'enabledModuleKeys'}
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationSafetyError('tenant profile fields are invalid')
    if value['slug'] != FIRST_TENANT_SLUG:
        raise OperationSafetyError('tenant profile slug is invalid')
    if value['planCode'] != 'enterprise':
        raise OperationSafetyError('tenant profile plan is invalid')
    if not isinstance(value['name'], str) or not value['name'].strip():
        raise OperationSafetyError('tenant profile name is invalid')
    module_keys = value['enabledModuleKeys']
    if (
        not isinstance(module_keys, list)
        or not module_keys
        or not all(isinstance(item, str) for item in module_keys)
        or len(module_keys) != len(set(module_keys))
    ):
        raise OperationSafetyError('tenant profile module keys are invalid')
    return {
        'slug': value['slug'],
        'name': value['name'].strip(),
        'planCode': value['planCode'],
        'enabledModuleKeys': tuple(module_keys),
    }


def _tree_files(root: Path) -> list[tuple[str, Path]]:
    source = Path(root)
    if source.is_symlink() or not source.is_dir():
        raise OperationSafetyError('MinIO import root is missing or unsafe')
    files = []
    for path in source.rglob('*'):
        if path.is_symlink():
            raise OperationSafetyError('MinIO import rejects symlinks')
        if path.is_dir():
            continue
        if not path.is_file():
            raise OperationSafetyError('MinIO import accepts regular files only')
        relative_name = path.relative_to(source).as_posix()
        ensure_relative_member(relative_name)
        files.append((relative_name, path))
    return sorted(files)


def _hash_minio_object(client, *, bucket: str, key: str, size: int) -> str:
    response = client.get_object(bucket, key, offset=0, length=size)
    digest = hashlib.sha256()
    try:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
    finally:
        response.close()
        response.release_conn()
    return digest.hexdigest()


def import_minio_tree(
    client,
    *,
    bucket: str,
    source_root: Path,
) -> dict[str, object]:
    if not isinstance(bucket, str) or BUCKET_RE.fullmatch(bucket) is None:
        raise OperationSafetyError('MinIO import bucket name is invalid')
    files = _tree_files(Path(source_root))
    if client.bucket_exists(bucket):
        raise OperationSafetyError('MinIO import bucket already exists')
    client.make_bucket(bucket)
    total_bytes = 0
    for key, path in files:
        source_hash = sha256_file(path)
        size = path.stat().st_size
        client.fput_object(bucket, key, str(path))
        stored = client.stat_object(bucket, key)
        if stored.size != size:
            raise OperationSafetyError(f'MinIO object size mismatch: {key}')
        if _hash_minio_object(
            client,
            bucket=bucket,
            key=key,
            size=size,
        ) != source_hash:
            raise OperationSafetyError(f'MinIO object hash mismatch: {key}')
        total_bytes += size
    return {
        'bucket': bucket,
        'objectCount': len(files),
        'totalBytes': total_bytes,
        'status': 'passed',
    }


def delete_restore_proof_bucket(client, *, bucket: str) -> None:
    if (
        not isinstance(bucket, str)
        or RESTORE_PROOF_BUCKET_RE.fullmatch(bucket) is None
    ):
        raise OperationSafetyError(
            'only an explicit restore-proof bucket may be deleted'
        )
    if not client.bucket_exists(bucket):
        raise OperationSafetyError('restore-proof bucket does not exist')
    for item in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, item.object_name)
    client.remove_bucket(bucket)


def minio_client_from_environment():
    from minio import Minio

    endpoint = os.getenv('MINIO_ENDPOINT', 'minio:9000')
    access_key = os.getenv('MINIO_ACCESS_KEY')
    secret_key = os.getenv('MINIO_SECRET_KEY')
    if not access_key or not secret_key:
        raise OperationSafetyError('MinIO credentials are unavailable')
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=os.getenv('MINIO_SECURE', 'false').lower() == 'true',
    )


def mysql_candidate_store(candidate_database: str):
    if DATABASE_RE.fullmatch(candidate_database) is None:
        raise OperationSafetyError('candidate database name is invalid')
    import pymysql

    host = os.getenv('DB_HOST', 'mysql')
    user = os.getenv('DB_USER') or os.getenv('MYSQL_USER')
    password = os.getenv('DB_PASSWORD') or os.getenv('MYSQL_PASSWORD')
    if not user or not password:
        raise OperationSafetyError('candidate database credentials are missing')
    connection = pymysql.connect(
        host=host,
        port=int(os.getenv('DB_PORT', '3306')),
        user=user,
        password=password,
        database=candidate_database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    return connection, MySQLCandidateControlStore(connection)


def bootstrap_candidate_from_profile(
    *,
    candidate_database: str,
    active_database: str,
    snapshot_id: str,
    tenant_profile_path: Path,
    credential_path: Path,
    result_path: Path,
) -> None:
    profile = load_tenant_profile(tenant_profile_path)
    config = CandidateBootstrapConfig(
        snapshot_id=snapshot_id,
        candidate_database=candidate_database,
        active_database=active_database,
        tenant_name=profile['name'],
        module_keys=profile['enabledModuleKeys'],
        tenant_slug=profile['slug'],
        plan_code=profile['planCode'],
    )
    connection, store = mysql_candidate_store(candidate_database)
    try:
        result = bootstrap_candidate_tenant(store, config)
        write_validation_credentials(credential_path, result)
        write_atomic_json(
            result_path,
            {
                'status': 'created',
                'tenantId': result.tenant_id,
                'tenantSlug': result.tenant_slug,
                'temporaryAdminId': result.temporary_admin_id,
                'temporaryAdminEmail': result.temporary_admin_email,
            },
            overwrite=False,
        )
    finally:
        connection.close()


def bootstrap_candidate_controls_from_profile(
    *,
    candidate_database: str,
    active_database: str,
    snapshot_id: str,
    tenant_profile_path: Path,
    result_path: Path,
) -> None:
    profile = load_tenant_profile(tenant_profile_path)
    config = CandidateBootstrapConfig(
        snapshot_id=snapshot_id,
        candidate_database=candidate_database,
        active_database=active_database,
        tenant_name=profile['name'],
        module_keys=profile['enabledModuleKeys'],
        tenant_slug=profile['slug'],
        plan_code=profile['planCode'],
    )
    connection, store = mysql_candidate_store(candidate_database)
    try:
        tenant_id = ensure_candidate_tenant_controls(store, config)
        write_atomic_json(
            result_path,
            {
                'status': 'ready',
                'tenantId': tenant_id,
                'tenantSlug': config.tenant_slug,
            },
            overwrite=False,
        )
    finally:
        connection.close()


def remove_candidate_admin(
    *,
    candidate_database: str,
    bootstrap_result_path: Path,
    report_path: Path,
) -> None:
    try:
        value = json.loads(
            Path(bootstrap_result_path).read_text(encoding='utf-8')
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('candidate bootstrap result is invalid') from exc
    expected = {
        'status',
        'tenantId',
        'tenantSlug',
        'temporaryAdminId',
        'temporaryAdminEmail',
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationSafetyError('candidate bootstrap result fields are invalid')
    result = CandidateBootstrapResult(
        tenant_id=value['tenantId'],
        tenant_slug=value['tenantSlug'],
        temporary_admin_id=value['temporaryAdminId'],
        temporary_admin_email=value['temporaryAdminEmail'],
        temporary_password='',
    )
    connection, store = mysql_candidate_store(candidate_database)
    try:
        remove_temporary_validation_admin(store, result)
        assert_candidate_ready(store, result)
        write_atomic_json(
            report_path,
            {'status': 'passed', 'temporaryAdminRemoved': True},
            overwrite=False,
        )
    finally:
        connection.close()


def _http_json(
    url: str,
    *,
    method: str = 'GET',
    payload: Mapping[str, object] | None = None,
    token: str | None = None,
) -> object:
    headers = {'Accept': 'application/json'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = urlrequest.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with urlrequest.urlopen(request, timeout=15) as response:
        if response.status < 200 or response.status >= 300:
            raise OperationSafetyError(f'candidate HTTP status {response.status}')
        return json.loads(response.read().decode('utf-8'))


def validate_candidate_runtime(
    *,
    credential_path: Path,
    candidate_database: str,
    candidate_bucket: str,
) -> dict[str, object]:
    if os.getenv('DB_NAME') != candidate_database:
        raise OperationSafetyError('candidate runtime database does not match')
    if os.getenv('MINIO_BUCKET') != candidate_bucket:
        raise OperationSafetyError('candidate runtime bucket does not match')
    try:
        credentials = json.loads(Path(credential_path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationSafetyError('validation credentials are invalid') from exc
    base_url = f"http://127.0.0.1:{os.getenv('PORT', '18888')}"
    last_error = None
    for _attempt in range(60):
        try:
            health = _http_json(base_url + '/api/health')
            ready = _http_json(base_url + '/api/ready')
            if health.get('ok') is True and ready.get('ok') is True:
                break
        except (OSError, ValueError, urlerror.URLError) as exc:
            last_error = exc
        time.sleep(2)
    else:
        raise OperationSafetyError('candidate API did not become ready') from last_error

    login = _http_json(
        base_url + '/api/auth/login',
        method='POST',
        payload={
            'identifier': credentials['email'],
            'password': credentials['password'],
            'tenantSlug': credentials['tenantSlug'],
        },
    )
    token = login.get('token') if isinstance(login, dict) else None
    if not isinstance(token, str) or not token:
        raise OperationSafetyError('candidate tenant login returned no token')
    employees = _http_json(
        base_url + '/api/hrm/employees?page=1&pageSize=1',
        token=token,
    )
    if not isinstance(employees, (dict, list)):
        raise OperationSafetyError('candidate core record response is invalid')

    platform_login_ok = False
    platform_email = os.getenv('PLATFORM_ADMIN_EMAIL')
    platform_password = os.getenv('PLATFORM_ADMIN_PASSWORD')
    if platform_email and platform_password:
        platform_login = _http_json(
            base_url + '/api/platform/auth/login',
            method='POST',
            payload={
                'identifier': platform_email,
                'password': platform_password,
            },
        )
        platform_login_ok = bool(
            isinstance(platform_login, dict) and platform_login.get('token')
        )
    if not platform_login_ok:
        raise OperationSafetyError('candidate platform login failed')

    client = minio_client_from_environment()
    if not client.bucket_exists(candidate_bucket):
        raise OperationSafetyError('candidate object bucket is missing')
    objects = list(client.list_objects(candidate_bucket, recursive=True))
    if not objects:
        raise OperationSafetyError('candidate object bucket is empty')
    first = objects[0]
    if first.size:
        response = client.get_object(
            candidate_bucket,
            first.object_name,
            offset=0,
            length=min(first.size, 64),
        )
        try:
            if not response.read():
                raise OperationSafetyError('candidate object range read is empty')
        finally:
            response.close()
            response.release_conn()
    return {
        'status': 'passed',
        'apiHealth': True,
        'apiReady': True,
        'platformLogin': True,
        'tenantLogin': True,
        'coreRecords': True,
        'objectStorage': True,
        'objectCount': len(objects),
    }
