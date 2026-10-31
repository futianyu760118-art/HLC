"""Candidate-only tenant controls for the first formal SaaS tenant."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
from typing import Mapping, Protocol, Sequence
import uuid

import bcrypt

from ops.operation_common import (
    OperationSafetyError,
    validate_runtime_id,
    write_atomic_json,
)
from services.legacy_tenant_migration import (
    MigrationSafetyError,
    MYSQL_IDENTIFIER_RE,
    validate_candidate_database_names,
)


FIRST_TENANT_SLUG = 'HPT-00000001'
ENTERPRISE_PLAN = 'enterprise'
MODULE_KEY_RE = re.compile(r'^[a-z][a-z0-9._-]{0,79}$', re.ASCII)


class CandidateControlStore(Protocol):
    def selected_database_name(self) -> str: ...
    def plan_exists(self, plan_code: str) -> bool: ...
    def tenant_by_slug(self, slug: str) -> Mapping[str, object] | None: ...
    def insert_tenant(self, row: Mapping[str, object]) -> None: ...
    def update_tenant_name(self, *, tenant_id: str, name: str) -> int: ...
    def subscriptions_for_tenant(
        self,
        tenant_id: str,
    ) -> Sequence[Mapping[str, object]]: ...
    def insert_subscription(self, row: Mapping[str, object]) -> None: ...
    def modules_for_tenant(
        self,
        tenant_id: str,
    ) -> Sequence[Mapping[str, object]]: ...
    def insert_module(self, row: Mapping[str, object]) -> None: ...
    def insert_user(self, row: Mapping[str, object]) -> None: ...
    def delete_user(self, *, tenant_id: str, user_id: str) -> int: ...
    def user_exists(self, *, tenant_id: str, user_id: str) -> bool: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class CandidateBootstrapConfig:
    snapshot_id: str
    candidate_database: str
    active_database: str
    tenant_name: str
    module_keys: tuple[str, ...]
    tenant_slug: str = FIRST_TENANT_SLUG
    plan_code: str = ENTERPRISE_PLAN
    max_users: int = 200
    max_employees: int = 2000
    max_storage_mb: int = 102400
    ai_monthly_quota: int = 10000

    def __post_init__(self) -> None:
        validate_runtime_id(self.snapshot_id)
        if self.tenant_slug != FIRST_TENANT_SLUG:
            raise OperationSafetyError(
                f'first tenant slug must be {FIRST_TENANT_SLUG}'
            )
        if self.plan_code != ENTERPRISE_PLAN:
            raise OperationSafetyError('first tenant plan must be enterprise')
        if not isinstance(self.tenant_name, str) or not self.tenant_name.strip():
            raise OperationSafetyError('first tenant name must not be empty')
        try:
            validate_candidate_database_names(
                stage_database=f'legacy_stage_{self.snapshot_id}',
                candidate_database=self.candidate_database,
            )
        except MigrationSafetyError as exc:
            raise OperationSafetyError(str(exc)) from exc
        if (
            not isinstance(self.active_database, str)
            or MYSQL_IDENTIFIER_RE.fullmatch(self.active_database) is None
        ):
            raise OperationSafetyError('active database name is invalid')
        if self.active_database.casefold() == self.candidate_database.casefold():
            raise OperationSafetyError(
                'candidate database must differ from active database'
            )
        if not isinstance(self.module_keys, tuple) or not self.module_keys:
            raise OperationSafetyError('candidate module keys must not be empty')
        if len(self.module_keys) != len(set(self.module_keys)):
            raise OperationSafetyError('candidate module keys must be unique')
        for module_key in self.module_keys:
            if (
                not isinstance(module_key, str)
                or MODULE_KEY_RE.fullmatch(module_key) is None
            ):
                raise OperationSafetyError('candidate module key is invalid')
        for owner, value in (
            ('max_users', self.max_users),
            ('max_employees', self.max_employees),
            ('max_storage_mb', self.max_storage_mb),
            ('ai_monthly_quota', self.ai_monthly_quota),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise OperationSafetyError(f'{owner} must be a positive integer')


@dataclass(frozen=True)
class CandidateBootstrapResult:
    tenant_id: str
    tenant_slug: str
    temporary_admin_id: str
    temporary_admin_email: str
    temporary_password: str
    temporary_password_hash: str = ''

    def __repr__(self) -> str:
        return (
            'CandidateBootstrapResult('
            f'tenant_id={self.tenant_id!r}, '
            f'tenant_slug={self.tenant_slug!r}, '
            f'temporary_admin_id={self.temporary_admin_id!r}, '
            f'temporary_admin_email={self.temporary_admin_email!r}, '
            "temporary_password='<redacted>', "
            "temporary_password_hash='<redacted>')"
        )


def _expected_tenant_row(
    config: CandidateBootstrapConfig,
    *,
    tenant_id: str,
) -> dict[str, object]:
    return {
        'id': tenant_id,
        'name': config.tenant_name.strip(),
        'slug': config.tenant_slug,
        'status': 'active',
        'plan_code': config.plan_code,
        'max_users': config.max_users,
        'max_employees': config.max_employees,
        'max_storage_mb': config.max_storage_mb,
        'ai_monthly_quota': config.ai_monthly_quota,
        'settings_json': {},
    }


def _normalize_json_object(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _validate_existing_controls(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
    tenant: Mapping[str, object],
) -> str:
    tenant_id = tenant.get('id')
    if not isinstance(tenant_id, str) or not tenant_id:
        raise OperationSafetyError('existing candidate tenant ID is invalid')
    expected = _expected_tenant_row(config, tenant_id=tenant_id)
    stable_keys = tuple(
        key for key in expected if key not in {'name', 'settings_json'}
    )
    actual = {
        key: _normalize_json_object(tenant.get(key))
        for key in stable_keys
    }
    expected_stable = {key: expected[key] for key in stable_keys}
    settings = _normalize_json_object(tenant.get('settings_json'))
    if actual != expected_stable or not isinstance(settings, Mapping):
        raise OperationSafetyError('existing candidate tenant profile mismatch')

    subscriptions = list(store.subscriptions_for_tenant(tenant_id))
    if len(subscriptions) > 1:
        raise OperationSafetyError(
            'existing candidate tenant subscription profile mismatch'
        )
    if subscriptions:
        subscription = subscriptions[0]
        if (
            subscription.get('plan_code') != config.plan_code
            or subscription.get('status') != 'active'
            or subscription.get('ends_at') is not None
        ):
            raise OperationSafetyError(
                'existing candidate tenant subscription profile mismatch'
            )

    modules = list(store.modules_for_tenant(tenant_id))
    modules_by_key = {row.get('module_key'): row for row in modules}
    if len(modules_by_key) != len(modules):
        raise OperationSafetyError(
            'existing candidate tenant module profile mismatch'
        )
    if not set(modules_by_key).issubset(config.module_keys):
        raise OperationSafetyError(
            'existing candidate tenant module profile mismatch'
        )
    for row in modules_by_key.values():
        if row.get('enabled') not in (True, 1):
            raise OperationSafetyError(
                'existing candidate tenant module profile mismatch'
            )
        if not isinstance(
            _normalize_json_object(row.get('limits_json')),
            Mapping,
        ):
            raise OperationSafetyError(
                'existing candidate tenant module profile mismatch'
            )

    expected_name = config.tenant_name.strip()
    if tenant.get('name') != expected_name:
        updated = store.update_tenant_name(
            tenant_id=tenant_id,
            name=expected_name,
        )
        if updated != 1:
            raise OperationSafetyError(
                'existing candidate tenant name could not be updated exactly once'
            )
    if not subscriptions:
        store.insert_subscription(
            {
                'id': str(uuid.uuid4()),
                'tenant_id': tenant_id,
                'plan_code': config.plan_code,
                'status': 'active',
                'ends_at': None,
                'notes': 'Prepared by first-tenant candidate migration',
            }
        )
    for module_key in config.module_keys:
        if module_key not in modules_by_key:
            store.insert_module(
                {
                    'id': str(uuid.uuid4()),
                    'tenant_id': tenant_id,
                    'module_key': module_key,
                    'enabled': True,
                    'limits_json': {},
                }
            )
    return tenant_id


def _create_controls(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
) -> str:
    tenant_id = str(uuid.uuid4())
    store.insert_tenant(_expected_tenant_row(config, tenant_id=tenant_id))
    store.insert_subscription(
        {
            'id': str(uuid.uuid4()),
            'tenant_id': tenant_id,
            'plan_code': config.plan_code,
            'status': 'active',
            'ends_at': None,
            'notes': 'Prepared by first-tenant candidate migration',
        }
    )
    for module_key in config.module_keys:
        store.insert_module(
            {
                'id': str(uuid.uuid4()),
                'tenant_id': tenant_id,
                'module_key': module_key,
                'enabled': True,
                'limits_json': {},
            }
        )
    return tenant_id


def _validate_candidate_store_target(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
) -> None:
    selected_database = store.selected_database_name()
    if (
        not isinstance(selected_database, str)
        or selected_database.casefold() != config.candidate_database.casefold()
    ):
        raise OperationSafetyError(
            'connection is not selected to the proved candidate database'
        )
    if selected_database.casefold() == config.active_database.casefold():
        raise OperationSafetyError('candidate database resolves to active database')


def _ensure_candidate_tenant_controls_uncommitted(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
) -> str:
    if not store.plan_exists(config.plan_code):
        raise OperationSafetyError('enterprise plan is missing in candidate')
    tenant = store.tenant_by_slug(config.tenant_slug)
    if tenant is None:
        return _create_controls(store, config)
    return _validate_existing_controls(store, config, tenant)


def ensure_candidate_tenant_controls(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
) -> str:
    """Commit candidate tenant controls without creating a validation user."""

    _validate_candidate_store_target(store, config)
    try:
        tenant_id = _ensure_candidate_tenant_controls_uncommitted(store, config)
        store.commit()
    except BaseException:
        store.rollback()
        raise
    return tenant_id


def bootstrap_candidate_tenant(
    store: CandidateControlStore,
    config: CandidateBootstrapConfig,
) -> CandidateBootstrapResult:
    _validate_candidate_store_target(store, config)
    try:
        tenant_id = _ensure_candidate_tenant_controls_uncommitted(store, config)

        temporary_admin_id = str(uuid.uuid4())
        random_marker = secrets.token_hex(12)
        temporary_email = (
            f'migration-validation+{random_marker}@invalid.hengpintong.local'
        )
        temporary_password = secrets.token_urlsafe(32)
        password_hash = bcrypt.hashpw(
            temporary_password.encode('utf-8'),
            bcrypt.gensalt(),
        ).decode('ascii')
        store.insert_user(
            {
                'id': temporary_admin_id,
                'tenant_id': tenant_id,
                'email': temporary_email,
                'password_hash': password_hash,
                'name': '迁移临时验证管理员',
                'role': 'admin',
                'status': 'active',
                'must_change_password': False,
            }
        )
        store.commit()
    except BaseException:
        store.rollback()
        raise

    return CandidateBootstrapResult(
        tenant_id=tenant_id,
        tenant_slug=config.tenant_slug,
        temporary_admin_id=temporary_admin_id,
        temporary_admin_email=temporary_email,
        temporary_password=temporary_password,
        temporary_password_hash=password_hash,
    )


def write_validation_credentials(
    path: Path,
    result: CandidateBootstrapResult,
) -> None:
    write_atomic_json(
        Path(path),
        {
            'email': result.temporary_admin_email,
            'password': result.temporary_password,
            'tenantSlug': result.tenant_slug,
        },
        overwrite=False,
    )
    os.chmod(path, 0o600)


def remove_temporary_validation_admin(
    store: CandidateControlStore,
    result: CandidateBootstrapResult,
) -> None:
    try:
        deleted = store.delete_user(
            tenant_id=result.tenant_id,
            user_id=result.temporary_admin_id,
        )
        if deleted != 1:
            raise OperationSafetyError(
                'temporary validation admin could not be removed exactly once'
            )
        store.commit()
    except BaseException:
        store.rollback()
        raise


def assert_candidate_ready(
    store: CandidateControlStore,
    result: CandidateBootstrapResult,
) -> None:
    if store.user_exists(
        tenant_id=result.tenant_id,
        user_id=result.temporary_admin_id,
    ):
        raise OperationSafetyError(
            'temporary validation admin must be removed before ready state'
        )


class MySQLCandidateControlStore:
    """Small DB-API adapter that writes only the selected candidate schema."""

    def __init__(self, connection) -> None:
        self.connection = connection

    def _fetchone(self, sql: str, params=()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            cursor.close()

    def _fetchall(self, sql: str, params=()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        finally:
            cursor.close()

    def _execute(self, sql: str, params=()) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.rowcount
        finally:
            cursor.close()

    @staticmethod
    def _mapping(row, columns: tuple[str, ...]):
        if row is None or isinstance(row, Mapping):
            return row
        return dict(zip(columns, row))

    def selected_database_name(self) -> str:
        row = self._fetchone('SELECT DATABASE()')
        if isinstance(row, Mapping):
            return next(iter(row.values()))
        return row[0] if row else None

    def plan_exists(self, plan_code: str) -> bool:
        row = self._fetchone(
            'SELECT COUNT(*) FROM plans WHERE code = %s AND is_active = 1',
            (plan_code,),
        )
        value = next(iter(row.values())) if isinstance(row, Mapping) else row[0]
        return value == 1

    def tenant_by_slug(self, slug: str):
        columns = (
            'id', 'name', 'slug', 'status', 'plan_code', 'max_users',
            'max_employees', 'max_storage_mb', 'ai_monthly_quota',
            'settings_json',
        )
        row = self._fetchone(
            f"SELECT {', '.join(columns)} FROM tenants WHERE slug = %s",
            (slug,),
        )
        return self._mapping(row, columns)

    def insert_tenant(self, row: Mapping[str, object]) -> None:
        self._execute(
            'INSERT INTO tenants '
            '(id, name, slug, status, plan_code, max_users, max_employees, '
            'max_storage_mb, ai_monthly_quota, settings_json, created_at, '
            'updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
            'UTC_TIMESTAMP(), UTC_TIMESTAMP())',
            (
                row['id'], row['name'], row['slug'], row['status'],
                row['plan_code'], row['max_users'], row['max_employees'],
                row['max_storage_mb'], row['ai_monthly_quota'],
                json.dumps(row['settings_json'], ensure_ascii=True),
            ),
        )

    def update_tenant_name(self, *, tenant_id: str, name: str) -> int:
        return self._execute(
            'UPDATE tenants SET name = %s WHERE id = %s',
            (name, tenant_id),
        )

    def subscriptions_for_tenant(self, tenant_id: str):
        columns = ('id', 'tenant_id', 'plan_code', 'status', 'ends_at')
        rows = self._fetchall(
            f"SELECT {', '.join(columns)} FROM tenant_subscriptions "
            'WHERE tenant_id = %s',
            (tenant_id,),
        )
        return [self._mapping(row, columns) for row in rows]

    def insert_subscription(self, row: Mapping[str, object]) -> None:
        self._execute(
            'INSERT INTO tenant_subscriptions '
            '(id, tenant_id, plan_code, status, starts_at, ends_at, notes, '
            'created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), %s, %s, '
            'UTC_TIMESTAMP(), UTC_TIMESTAMP())',
            (
                row['id'], row['tenant_id'], row['plan_code'], row['status'],
                row['ends_at'], row['notes'],
            ),
        )

    def modules_for_tenant(self, tenant_id: str):
        columns = ('id', 'tenant_id', 'module_key', 'enabled', 'limits_json')
        rows = self._fetchall(
            f"SELECT {', '.join(columns)} FROM tenant_modules "
            'WHERE tenant_id = %s',
            (tenant_id,),
        )
        return [self._mapping(row, columns) for row in rows]

    def insert_module(self, row: Mapping[str, object]) -> None:
        self._execute(
            'INSERT INTO tenant_modules '
            '(id, tenant_id, module_key, enabled, limits_json, created_at, '
            'updated_at) '
            'VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP(), UTC_TIMESTAMP())',
            (
                row['id'], row['tenant_id'], row['module_key'],
                row['enabled'],
                json.dumps(row['limits_json'], ensure_ascii=True),
            ),
        )

    def insert_user(self, row: Mapping[str, object]) -> None:
        self._execute(
            'INSERT INTO users '
            '(id, tenant_id, email, password_hash, name, role, status, '
            'must_change_password, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '
            'UTC_TIMESTAMP(), UTC_TIMESTAMP())',
            (
                row['id'], row['tenant_id'], row['email'], row['password_hash'],
                row['name'], row['role'], row['status'],
                row['must_change_password'],
            ),
        )

    def delete_user(self, *, tenant_id: str, user_id: str) -> int:
        return self._execute(
            'DELETE FROM users WHERE id = %s AND tenant_id = %s',
            (user_id, tenant_id),
        )

    def user_exists(self, *, tenant_id: str, user_id: str) -> bool:
        row = self._fetchone(
            'SELECT COUNT(*) FROM users WHERE id = %s AND tenant_id = %s',
            (user_id, tenant_id),
        )
        value = next(iter(row.values())) if isinstance(row, Mapping) else row[0]
        return value == 1

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()
