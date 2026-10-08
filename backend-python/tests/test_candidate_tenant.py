from __future__ import annotations

import json
import os
from pathlib import Path

import bcrypt
import pytest

from ops import candidate_tenant
from ops.candidate_tenant import (
    CandidateBootstrapConfig,
    MySQLCandidateControlStore,
    assert_candidate_ready,
    bootstrap_candidate_tenant,
    remove_temporary_validation_admin,
    write_validation_credentials,
)
from ops.operation_common import OperationSafetyError


SNAPSHOT_ID = '20260715T102030Z'
MODULE_KEYS = ('organization', 'recruitment', 'system', 'training_exam')


class MemoryCandidateStore:
    def __init__(self, selected_database='hrm_candidate_20260715T102030Z'):
        self.selected_database = selected_database
        self.plans = {'enterprise'}
        self.tenants = {}
        self.subscriptions = []
        self.modules = []
        self.users = {}
        self.commits = 0
        self.rollbacks = 0

    def selected_database_name(self):
        return self.selected_database

    def plan_exists(self, plan_code):
        return plan_code in self.plans

    def tenant_by_slug(self, slug):
        return self.tenants.get(slug)

    def insert_tenant(self, row):
        self.tenants[row['slug']] = dict(row)

    def update_tenant_name(self, *, tenant_id, name):
        for tenant in self.tenants.values():
            if tenant['id'] == tenant_id:
                tenant['name'] = name
                return 1
        return 0

    def subscriptions_for_tenant(self, tenant_id):
        return [
            dict(row)
            for row in self.subscriptions
            if row['tenant_id'] == tenant_id
        ]

    def insert_subscription(self, row):
        self.subscriptions.append(dict(row))

    def modules_for_tenant(self, tenant_id):
        return [
            dict(row)
            for row in self.modules
            if row['tenant_id'] == tenant_id
        ]

    def insert_module(self, row):
        self.modules.append(dict(row))

    def insert_user(self, row):
        self.users[row['id']] = dict(row)

    def delete_user(self, *, tenant_id, user_id):
        row = self.users.get(user_id)
        if row is None or row['tenant_id'] != tenant_id:
            return 0
        del self.users[user_id]
        return 1

    def user_exists(self, *, tenant_id, user_id):
        row = self.users.get(user_id)
        return bool(row and row['tenant_id'] == tenant_id)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class RecordingCursor:
    def __init__(self, statements):
        self.statements = statements
        self.rowcount = 1

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def close(self):
        pass


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def cursor(self):
        return RecordingCursor(self.statements)


def _config(**overrides):
    values = {
        'snapshot_id': SNAPSHOT_ID,
        'candidate_database': 'hrm_candidate_20260715T102030Z',
        'active_database': 'hrm_saas',
        'tenant_name': '恒聘通首个正式企业',
        'module_keys': MODULE_KEYS,
    }
    values.update(overrides)
    return CandidateBootstrapConfig(**values)


def test_bootstrap_refuses_live_database_and_creates_exact_candidate_controls():
    live_store = MemoryCandidateStore(selected_database='hrm_saas')
    with pytest.raises(OperationSafetyError, match='candidate database'):
        bootstrap_candidate_tenant(live_store, _config())
    assert live_store.tenants == {}
    assert live_store.commits == 0

    store = MemoryCandidateStore()
    result = bootstrap_candidate_tenant(store, _config())
    tenant = store.tenants['HPT-00000001']

    assert result.tenant_id == tenant['id']
    assert tenant == {
        'id': result.tenant_id,
        'name': '恒聘通首个正式企业',
        'slug': 'HPT-00000001',
        'status': 'active',
        'plan_code': 'enterprise',
        'max_users': 200,
        'max_employees': 2000,
        'max_storage_mb': 102400,
        'ai_monthly_quota': 10000,
        'settings_json': {},
    }
    assert len(store.subscriptions) == 1
    assert store.subscriptions[0]['plan_code'] == 'enterprise'
    assert store.subscriptions[0]['status'] == 'active'
    assert {
        row['module_key'] for row in store.modules
    } == set(MODULE_KEYS)
    assert all(row['enabled'] is True for row in store.modules)
    assert all(row['limits_json'] == {} for row in store.modules)
    assert store.commits == 1


def test_candidate_controls_can_be_committed_without_creating_validation_user():
    store = MemoryCandidateStore()

    tenant_id = candidate_tenant.ensure_candidate_tenant_controls(
        store,
        _config(),
    )

    assert tenant_id == store.tenants['HPT-00000001']['id']
    assert len(store.subscriptions) == 1
    assert {row['module_key'] for row in store.modules} == set(MODULE_KEYS)
    assert store.users == {}
    assert store.commits == 1


def test_existing_candidate_tenant_is_idempotent_and_rejects_entitlement_drift():
    store = MemoryCandidateStore()
    first = bootstrap_candidate_tenant(store, _config())
    remove_temporary_validation_admin(store, first)
    original_counts = (
        len(store.tenants),
        len(store.subscriptions),
        len(store.modules),
    )

    second = bootstrap_candidate_tenant(store, _config())
    assert second.tenant_id == first.tenant_id
    assert (
        len(store.tenants),
        len(store.subscriptions),
        len(store.modules),
    ) == original_counts

    remove_temporary_validation_admin(store, second)
    store.tenants['HPT-00000001']['max_users'] = 201
    with pytest.raises(OperationSafetyError, match='profile mismatch'):
        bootstrap_candidate_tenant(store, _config())


def test_existing_seeded_tenant_is_claimed_without_dropping_runtime_settings():
    store = MemoryCandidateStore()
    tenant_id = 'seeded-tenant-id'
    store.tenants['HPT-00000001'] = {
        'id': tenant_id,
        'name': '占位企业',
        'slug': 'HPT-00000001',
        'status': 'active',
        'plan_code': 'enterprise',
        'max_users': 200,
        'max_employees': 2000,
        'max_storage_mb': 102400,
        'ai_monthly_quota': 10000,
        'settings_json': {'assistantEnabled': True},
    }
    store.modules.extend(
        [
            {
                'id': 'organization-module',
                'tenant_id': tenant_id,
                'module_key': 'organization',
                'enabled': True,
                'limits_json': {'maxDepartments': 500},
            },
            {
                'id': 'system-module',
                'tenant_id': tenant_id,
                'module_key': 'system',
                'enabled': True,
                'limits_json': {},
            },
        ]
    )

    result = bootstrap_candidate_tenant(store, _config())

    tenant = store.tenants['HPT-00000001']
    assert result.tenant_id == tenant_id
    assert tenant['name'] == '恒聘通首个正式企业'
    assert tenant['settings_json'] == {'assistantEnabled': True}
    assert len(store.subscriptions) == 1
    assert store.subscriptions[0]['tenant_id'] == tenant_id
    assert {row['module_key'] for row in store.modules} == set(MODULE_KEYS)
    organization = next(
        row for row in store.modules if row['module_key'] == 'organization'
    )
    assert organization['limits_json'] == {'maxDepartments': 500}
    assert all(row['enabled'] is True for row in store.modules)


def test_mysql_candidate_inserts_supply_required_orm_timestamps():
    connection = RecordingConnection()
    store = MySQLCandidateControlStore(connection)
    tenant_id = 'tenant-id'

    store.insert_tenant(
        {
            'id': tenant_id,
            'name': '恒聘通首个正式企业',
            'slug': 'HPT-00000001',
            'status': 'active',
            'plan_code': 'enterprise',
            'max_users': 200,
            'max_employees': 2000,
            'max_storage_mb': 102400,
            'ai_monthly_quota': 10000,
            'settings_json': {},
        }
    )
    store.insert_subscription(
        {
            'id': 'subscription-id',
            'tenant_id': tenant_id,
            'plan_code': 'enterprise',
            'status': 'active',
            'ends_at': None,
            'notes': 'migration',
        }
    )
    store.insert_module(
        {
            'id': 'module-id',
            'tenant_id': tenant_id,
            'module_key': 'organization',
            'enabled': True,
            'limits_json': {},
        }
    )
    store.insert_user(
        {
            'id': 'user-id',
            'tenant_id': tenant_id,
            'email': 'migration@example.invalid',
            'password_hash': 'hash',
            'name': '迁移临时验证管理员',
            'role': 'admin',
            'status': 'active',
            'must_change_password': False,
        }
    )

    assert len(connection.statements) == 4
    for sql, _params in connection.statements:
        assert 'created_at' in sql
        assert 'updated_at' in sql
        assert sql.count('UTC_TIMESTAMP()') >= 2


def test_temporary_validation_admin_is_random_and_removed_before_ready(tmp_path):
    first_store = MemoryCandidateStore()
    second_store = MemoryCandidateStore()
    first = bootstrap_candidate_tenant(first_store, _config())
    second = bootstrap_candidate_tenant(second_store, _config())

    assert first.temporary_password != second.temporary_password
    assert first.temporary_admin_email != second.temporary_admin_email
    first_user = first_store.users[first.temporary_admin_id]
    assert first_user['must_change_password'] is False
    assert bcrypt.checkpw(
        first.temporary_password.encode('utf-8'),
        first_user['password_hash'].encode('utf-8'),
    )
    with pytest.raises(OperationSafetyError, match='temporary validation admin'):
        assert_candidate_ready(first_store, first)

    credential_path = tmp_path / 'owner' / 'validation-admin.json'
    write_validation_credentials(credential_path, first)
    credentials = json.loads(credential_path.read_text(encoding='utf-8'))
    assert credentials == {
        'email': first.temporary_admin_email,
        'password': first.temporary_password,
        'tenantSlug': 'HPT-00000001',
    }
    if os.name != 'nt':
        assert credential_path.stat().st_mode & 0o777 == 0o600

    remove_temporary_validation_admin(first_store, first)
    assert_candidate_ready(first_store, first)
    assert first_store.commits == 2
