from __future__ import annotations

import uuid
from datetime import date

import bcrypt
import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app import _register_tenant_context
from models import (
    Contract,
    Employee,
    EmployeePortalAccount,
    Notification,
    OperationLog,
    Plan,
    Probation,
    Resignation,
    Tenant,
    TenantModule,
    User,
    db,
)
from routes import hrm_bp
from services.tenancy import SAAS_MODULE_KEYS, register_tenant_orm_filters, tenant_claims_for


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _tenant(slug: str, name: str) -> Tenant:
    return Tenant(
        id=str(uuid.uuid4()),
        slug=slug,
        name=name,
        status='active',
        plan_code='enterprise',
        max_users=20,
        max_employees=200,
        max_storage_mb=1024,
        ai_monthly_quota=100,
    )


def _seed_modules(tenant_id: str) -> None:
    for module_key in SAAS_MODULE_KEYS:
        db.session.add(TenantModule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            module_key=module_key,
            enabled=True,
            limits_json={},
        ))


@pytest.fixture()
def lifecycle_app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(tmp_path / 'uploads'),
    )
    db.init_app(app)
    register_tenant_orm_filters()
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    _register_tenant_context(app)

    with app.app_context():
        db.create_all()
        db.session.add(Plan(
            code='enterprise',
            name='Enterprise',
            enabled_modules_json=list(SAAS_MODULE_KEYS),
            limits_json={},
            is_active=True,
        ))
        alpha = _tenant('alpha', 'Alpha')
        beta = _tenant('beta', 'Beta')
        db.session.add_all([alpha, beta])
        db.session.flush()
        _seed_modules(alpha.id)
        _seed_modules(beta.id)

        users = [
            User(id='alpha-admin', tenant_id=alpha.id, email='admin@alpha.test', password_hash=_hash('Passw0rd!'), name='Alpha Admin', role='admin', status='active'),
            User(id='alpha-viewer', tenant_id=alpha.id, email='viewer@alpha.test', password_hash=_hash('Passw0rd!'), name='Alpha Viewer', role='viewer', status='active'),
            User(id='beta-admin', tenant_id=beta.id, email='admin@beta.test', password_hash=_hash('Passw0rd!'), name='Beta Admin', role='admin', status='active'),
        ]
        employees = [
            Employee(id='emp-alpha', tenant_id=alpha.id, employee_no='A001', name='Alpha Employee', status='probation', hire_date=date(2026, 1, 1)),
            Employee(id='emp-beta', tenant_id=beta.id, employee_no='B001', name='Beta Employee', status='active', hire_date=date(2026, 1, 1)),
        ]
        db.session.add_all(users + employees)
        db.session.flush()
        db.session.add_all([
            EmployeePortalAccount(id='portal-alpha', tenant_id=alpha.id, employee_id='emp-alpha', password_hash='x', status='active'),
            Contract(id='contract-alpha', tenant_id=alpha.id, employee_id='emp-alpha', contract_no='C-A-001', contract_type='劳动合同', start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status='active', created_by='alpha-admin'),
            Contract(id='contract-beta', tenant_id=beta.id, employee_id='emp-beta', contract_no='C-B-001', contract_type='劳动合同', start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status='active', created_by='beta-admin'),
            Probation(id='probation-alpha', tenant_id=alpha.id, employee_id='emp-alpha', apply_date=date(2026, 3, 20), expected_regular_date=date(2026, 4, 1), status='pending', created_by='alpha-admin'),
            Resignation(id='resignation-alpha', tenant_id=alpha.id, employee_id='emp-alpha', apply_date=date(2026, 6, 1), expected_leave_date=date(2026, 6, 30), status='approved', created_by='alpha-admin'),
        ])
        db.session.commit()

        def token_for(user_id: str, tenant: Tenant) -> str:
            user = db.session.get(User, user_id)
            return create_access_token(
                identity=user_id,
                additional_claims={
                    'role': user.role,
                    'account_type': 'hrm',
                    **tenant_claims_for(tenant),
                },
            )

        tokens = {
            'alpha_admin': token_for('alpha-admin', alpha),
            'alpha_viewer': token_for('alpha-viewer', alpha),
            'beta_admin': token_for('beta-admin', beta),
            'alpha_id': alpha.id,
            'beta_id': beta.id,
        }

    yield app, tokens

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _client(app: Flask, token: str):
    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


def test_contract_workflow_renews_with_timeline_audit_and_notification(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    workflow = client.get('/api/hrm/contracts/contract-alpha/workflow')

    assert workflow.status_code == 200
    payload = workflow.get_json()
    assert payload['resource'] == 'contracts'
    assert payload['recordId'] == 'contract-alpha'
    assert payload['status'] == 'active'
    assert {item['key'] for item in payload['transitions']} >= {'renew', 'terminate'}
    assert payload['timeline'][0]['eventType'] == 'created'

    renewed = client.post('/api/hrm/contracts/contract-alpha/workflow/renew', json={
        'startDate': '2027-01-01',
        'endDate': '2027-12-31',
        'remark': 'Renewed for 2027',
    })

    assert renewed.status_code == 200
    body = renewed.get_json()
    assert body['record']['status'] == 'active'
    assert body['record']['startDate'] == '2027-01-01'
    assert body['record']['endDate'] == '2027-12-31'
    assert body['workflow']['timeline'][0]['action'] == 'workflow_renew'

    with app.app_context():
        contract = Contract.query.get('contract-alpha')
        assert contract.remark == 'Renewed for 2027'
        assert OperationLog.query.filter_by(module='contracts', action='workflow_renew', target_id='contract-alpha', tenant_id=tokens['alpha_id']).count() == 1
        notice = Notification.query.filter_by(user_id='alpha-admin', notice_type='workflow', tenant_id=tokens['alpha_id']).one()
        assert '合同' in notice.title
        assert notice.link_url == '/hrm/contracts?id=contract-alpha'


def test_invalid_contract_transition_is_rejected(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    terminated = client.post('/api/hrm/contracts/contract-alpha/workflow/terminate', json={'remark': 'Early end'})
    assert terminated.status_code == 200

    renewed = client.post('/api/hrm/contracts/contract-alpha/workflow/renew', json={
        'startDate': '2027-01-01',
        'endDate': '2027-12-31',
    })

    assert renewed.status_code == 400
    assert '不允许' in renewed.get_json()['error']


def test_malformed_workflow_date_returns_validation_error(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    response = client.post('/api/hrm/contracts/contract-alpha/workflow/renew', json={
        'startDate': 'not-a-date',
        'endDate': '2027-12-31',
    })

    assert response.status_code == 400
    assert '日期格式' in response.get_json()['error']


def test_workflow_audit_log_preserves_transition_evidence(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    response = client.post('/api/hrm/resignations/resignation-alpha/workflow/complete', json={
        'actualLeaveDate': '2026-06-30',
        'handoverItems': ['Laptop returned'],
    })

    assert response.status_code == 200

    with app.app_context():
        log = OperationLog.query.filter_by(
            module='resignations',
            action='workflow_complete',
            target_id='resignation-alpha',
            tenant_id=tokens['alpha_id'],
        ).one()
        assert log.detail['submitted']['actualLeaveDate'] == '2026-06-30'
        assert log.detail['submitted']['handoverItems'] == ['Laptop returned']


def test_probation_approval_updates_employee_and_writes_evidence(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    approved = client.post('/api/hrm/probations/probation-alpha/workflow/approve', json={
        'regularDate': '2026-04-01',
        'managerReview': 'Meets expectations',
    })

    assert approved.status_code == 200
    body = approved.get_json()
    assert body['record']['status'] == 'approved'
    assert body['record']['result'] == '通过'
    assert body['record']['regularDate'] == '2026-04-01'

    with app.app_context():
        assert Employee.query.get('emp-alpha').status == 'active'
        assert Probation.query.get('probation-alpha').manager_review == 'Meets expectations'
        assert OperationLog.query.filter_by(module='probations', action='workflow_approve', target_id='probation-alpha', tenant_id=tokens['alpha_id']).count() == 1
        assert Notification.query.filter_by(user_id='alpha-admin', notice_type='workflow', tenant_id=tokens['alpha_id']).count() == 1


def test_resignation_completion_closes_employee_and_portal_account(lifecycle_app):
    app, tokens = lifecycle_app
    client = _client(app, tokens['alpha_admin'])

    completed = client.post('/api/hrm/resignations/resignation-alpha/workflow/complete', json={
        'actualLeaveDate': '2026-06-30',
        'handoverItems': ['Laptop returned', 'Knowledge handover completed'],
    })

    assert completed.status_code == 200
    body = completed.get_json()
    assert body['record']['status'] == 'completed'
    assert body['record']['actualLeaveDate'] == '2026-06-30'

    with app.app_context():
        assert Employee.query.get('emp-alpha').status == 'resigned'
        assert EmployeePortalAccount.query.filter_by(employee_id='emp-alpha').one().status == 'inactive'
        assert Resignation.query.get('resignation-alpha').handover_items == ['Laptop returned', 'Knowledge handover completed']
        assert OperationLog.query.filter_by(module='resignations', action='workflow_complete', target_id='resignation-alpha', tenant_id=tokens['alpha_id']).count() == 1


def test_workflow_respects_tenant_and_write_permissions(lifecycle_app):
    app, tokens = lifecycle_app
    beta = _client(app, tokens['beta_admin'])
    viewer = _client(app, tokens['alpha_viewer'])

    cross_tenant = beta.get('/api/hrm/contracts/contract-alpha/workflow')
    assert cross_tenant.status_code == 404

    denied = viewer.post('/api/hrm/contracts/contract-alpha/workflow/terminate', json={})
    assert denied.status_code == 403
