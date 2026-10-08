from __future__ import annotations

from models import Department, Employee, PlatformOperationLog, db
from tests.test_saas_tenancy import _client, saas_app


def test_tenant_data_inventory_counts_only_requested_tenant(saas_app):
    app, tokens = saas_app
    alpha_id = tokens['alpha_id']
    beta_id = tokens['beta_id']

    with app.app_context():
        db.session.add_all([
            Department(id='dept-alpha-1', tenant_id=alpha_id, name='Alpha 研发部', code='A-RD'),
            Department(id='dept-beta-1', tenant_id=beta_id, name='Beta 研发部', code='B-RD'),
            Employee(id='emp-alpha-1', tenant_id=alpha_id, name='Alpha 员工', employee_no='A001'),
        ])
        db.session.commit()

        from services.tenant_data_lifecycle import tenant_data_inventory

        inventory = tenant_data_inventory(alpha_id)

    tables = {row['table']: row for row in inventory['tables']}
    assert inventory['tenantId'] == alpha_id
    assert inventory['totalRows'] >= 3
    assert tables['users']['rows'] == 1
    assert tables['departments']['rows'] == 1
    assert tables['employees']['rows'] == 1
    assert inventory['generatedAt']


def test_tenant_data_inventory_can_include_empty_tables_for_manifest_review(saas_app):
    app, tokens = saas_app

    with app.app_context():
        from services.tenant_data_lifecycle import tenant_data_inventory

        inventory = tenant_data_inventory(tokens['alpha_id'], include_empty=True)

    tables = {row['table']: row for row in inventory['tables']}
    assert 'employees' in tables
    assert tables['employees']['rows'] == 0
    assert inventory['tableCount'] == len(inventory['tables'])


def test_platform_tenant_data_inventory_endpoint_returns_manifest(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        db.session.add(Department(id='dept-alpha-api', tenant_id=tenant_id, name='Alpha API 部', code='A-API'))
        db.session.commit()

    platform = _client(app, tokens['platform'])
    response = platform.get(f'/api/platform/tenants/{tenant_id}/data-inventory?includeEmpty=1')

    assert response.status_code == 200
    payload = response.get_json()
    tables = {row['table']: row for row in payload['tables']}
    assert payload['tenantId'] == tenant_id
    assert tables['users']['rows'] == 1
    assert tables['departments']['rows'] == 1
    assert 'employees' in tables


def test_platform_tenant_data_inventory_endpoint_writes_operation_log(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    platform = _client(app, tokens['platform'])
    response = platform.get(f'/api/platform/tenants/{tenant_id}/data-inventory?includeEmpty=1')

    assert response.status_code == 200
    payload = response.get_json()
    with app.app_context():
        log = PlatformOperationLog.query.filter_by(
            tenant_id=tenant_id,
            action='tenant_data_inventory',
        ).one()

    assert log.target_type == 'tenant'
    assert log.target_id == tenant_id
    assert log.detail['includeEmpty'] is True
    assert log.detail['tableCount'] == payload['tableCount']
    assert log.detail['totalRows'] == payload['totalRows']


def test_tenant_structured_export_excludes_sensitive_fields_and_other_tenants(saas_app):
    app, tokens = saas_app
    alpha_id = tokens['alpha_id']
    beta_id = tokens['beta_id']

    with app.app_context():
        db.session.add_all([
            Department(id='dept-alpha-export', tenant_id=alpha_id, name='Alpha 导出部', code='A-EXP'),
            Department(id='dept-beta-export', tenant_id=beta_id, name='Beta 导出部', code='B-EXP'),
            Employee(id='emp-alpha-export', tenant_id=alpha_id, name='Alpha 导出员工', employee_no='A-EXP-001'),
        ])
        db.session.commit()

        from services.tenant_data_lifecycle import tenant_structured_export

        package = tenant_structured_export(alpha_id)

    departments = package['data']['departments']
    users = package['data']['users']
    assert package['tenantId'] == alpha_id
    assert package['format'] == 'json-v1'
    assert {row['name'] for row in departments} == {'Alpha 导出部'}
    assert all(row['tenant_id'] == alpha_id for row in departments)
    assert all('password_hash' not in row for row in users)
    assert all('token' not in key.lower() for row in users for key in row)


def test_platform_tenant_structured_export_endpoint_returns_package_and_logs(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        db.session.add(Department(id='dept-alpha-export-api', tenant_id=tenant_id, name='Alpha 导出 API 部', code='A-EXP-API'))
        db.session.commit()

    platform = _client(app, tokens['platform'])
    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/structured-export',
        json={'includeEmpty': False, 'maxRowsPerTable': 50},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['tenantId'] == tenant_id
    assert payload['format'] == 'json-v1'
    assert 'departments' in payload['data']
    assert any(row['name'] == 'Alpha 导出 API 部' for row in payload['data']['departments'])

    with app.app_context():
        log = PlatformOperationLog.query.filter_by(
            tenant_id=tenant_id,
            action='tenant_structured_export',
        ).one()

    assert log.target_type == 'tenant'
    assert log.target_id == tenant_id
    assert log.detail['format'] == 'json-v1'
    assert log.detail['tableCount'] == payload['tableCount']
    assert log.detail['totalRows'] == payload['totalRows']
    assert log.detail['exportedRows'] == payload['exportedRows']


def test_tenant_deletion_plan_is_non_destructive_and_requires_confirmation(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        db.session.add(Department(id='dept-alpha-delete-plan', tenant_id=tenant_id, name='Alpha 删除计划部', code='A-DEL'))
        db.session.commit()

        from services.tenant_data_lifecycle import tenant_deletion_plan

        plan = tenant_deletion_plan(tenant_id, tenant_slug='alpha', mode='delete')
        department_count = Department.query.filter_by(tenant_id=tenant_id).count()

    tables = {row['table']: row for row in plan['tables']}
    assert plan['tenantId'] == tenant_id
    assert plan['mode'] == 'delete'
    assert plan['destructive'] is False
    assert plan['requiresFinalBackup'] is True
    assert plan['requiresOwnerApproval'] is True
    assert plan['confirmationPhrase'] == 'DELETE TENANT alpha'
    assert tables['departments']['rows'] == department_count

    with app.app_context():
        assert Department.query.filter_by(tenant_id=tenant_id).count() == department_count


def test_platform_tenant_deletion_plan_endpoint_returns_plan_and_logs(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    platform = _client(app, tokens['platform'])
    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/deletion-plan',
        json={'mode': 'anonymize'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['mode'] == 'anonymize'
    assert payload['destructive'] is False
    assert payload['confirmationPhrase'] == 'ANONYMIZE TENANT alpha'
    assert 'final_backup' in payload['requiredSteps']
    assert 'owner_approval' in payload['requiredSteps']

    with app.app_context():
        log = PlatformOperationLog.query.filter_by(
            tenant_id=tenant_id,
            action='tenant_deletion_plan',
        ).one()

    assert log.target_type == 'tenant'
    assert log.target_id == tenant_id
    assert log.detail['mode'] == 'anonymize'
    assert log.detail['tableCount'] == payload['tableCount']
    assert log.detail['totalRows'] == payload['totalRows']
