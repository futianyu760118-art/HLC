from __future__ import annotations

from datetime import datetime

import bcrypt
import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import event

from models import Employee, EmployeePortalAccount, OperationLog, Tenant, User, db
from services.tenancy import tenant_claims_for
from tests.test_saas_tenancy import _client, saas_app


OLD_PASSWORD = 'Old-management-password!'
OLD_PORTAL_PASSWORD = 'Old-portal-password!'


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


@pytest.fixture()
def tenant_accounts(saas_app):
    app, tokens = saas_app
    with app.app_context():
        alpha = db.session.get(Tenant, tokens['alpha_id'])
        beta = db.session.get(Tenant, tokens['beta_id'])
        assert alpha is not None
        assert beta is not None

        db.session.add_all([
            User(
                id='alpha-management-user',
                tenant_id=alpha.id,
                email='management@alpha.example.com',
                password_hash=_hash(OLD_PASSWORD),
                name='Alpha Management User',
                role='recruiter',
                status='active',
                must_change_password=False,
                updated_at=datetime(2025, 1, 1),
            ),
            User(
                id='alpha-inactive-user',
                tenant_id=alpha.id,
                email='inactive@alpha.example.com',
                password_hash=_hash(OLD_PASSWORD),
                name='Alpha Inactive User',
                role='recruiter',
                status='inactive',
                must_change_password=False,
            ),
            User(
                id='alpha-viewer',
                tenant_id=alpha.id,
                email='viewer@alpha.example.com',
                password_hash=_hash(OLD_PASSWORD),
                name='Alpha Viewer',
                role='viewer',
                status='active',
            ),
            User(
                id='alpha-hr-admin',
                tenant_id=alpha.id,
                email='hr-admin@alpha.example.com',
                password_hash=_hash(OLD_PASSWORD),
                name='Alpha HR Admin',
                role='hr_admin',
                status='active',
            ),
            Employee(
                id='alpha-employee',
                tenant_id=alpha.id,
                employee_no='ALPHA-001',
                name='Alpha Employee',
                status='active',
                updated_at=datetime(2025, 1, 1),
            ),
            Employee(
                id='alpha-inactive-employee',
                tenant_id=alpha.id,
                employee_no='ALPHA-002',
                name='Alpha Inactive Employee',
                status='resigned',
            ),
            Employee(
                id='alpha-no-portal',
                tenant_id=alpha.id,
                employee_no='ALPHA-003',
                name='Alpha Employee Without Portal',
                status='active',
            ),
            Employee(
                id='alpha-probation-employee',
                tenant_id=alpha.id,
                employee_no='ALPHA-004',
                name='Alpha Probation Employee',
                status='probation',
            ),
            Employee(
                id='beta-employee',
                tenant_id=beta.id,
                employee_no='BETA-001',
                name='Beta Employee',
                status='active',
            ),
        ])
        db.session.flush()
        db.session.add_all([
            EmployeePortalAccount(
                id='alpha-portal',
                tenant_id=alpha.id,
                employee_id='alpha-employee',
                password_hash=_hash(OLD_PORTAL_PASSWORD),
                status='active',
                must_change_password=False,
                updated_at=datetime(2025, 1, 1),
            ),
            EmployeePortalAccount(
                id='alpha-inactive-portal',
                tenant_id=alpha.id,
                employee_id='alpha-inactive-employee',
                password_hash=_hash(OLD_PORTAL_PASSWORD),
                status='active',
                must_change_password=False,
            ),
            EmployeePortalAccount(
                id='beta-portal',
                tenant_id=beta.id,
                employee_id='beta-employee',
                password_hash=_hash(OLD_PORTAL_PASSWORD),
                status='active',
                must_change_password=False,
            ),
            EmployeePortalAccount(
                id='alpha-probation-portal',
                tenant_id=alpha.id,
                employee_id='alpha-probation-employee',
                password_hash=_hash(OLD_PORTAL_PASSWORD),
                status='active',
                must_change_password=False,
            ),
        ])
        db.session.commit()

        viewer_token = create_access_token(
            identity='alpha-viewer',
            additional_claims={
                'role': 'viewer',
                'account_type': 'hrm',
                **tenant_claims_for(alpha),
            },
        )
        hr_admin_token = create_access_token(
            identity='alpha-hr-admin',
            additional_claims={
                'role': 'hr_admin',
                'account_type': 'hrm',
                **tenant_claims_for(alpha),
            },
        )

    return app, {**tokens, 'viewer': viewer_token, 'hr_admin': hr_admin_token}


def test_management_password_reset_returns_one_time_password_and_safe_account(tenant_accounts):
    app, tokens = tenant_accounts
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/users/alpha-management-user/reset-password',
        json={'password': 'caller-controlled-password'},
    )

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    payload = response.get_json()
    generated = payload['initialPassword']
    assert len(generated) >= 20
    assert generated != 'caller-controlled-password'
    assert payload['requestId']
    assert payload['account']['id'] == 'alpha-management-user'
    assert payload['account']['accountType'] == 'hrm'
    assert payload['account']['mustChangePassword'] is True
    assert 'password' not in {key.lower() for key in payload['account']}

    with app.app_context():
        account = db.session.get(User, 'alpha-management-user')
        assert account is not None
        assert account.must_change_password is True
        assert account.updated_at > datetime(2025, 1, 1)
        assert bcrypt.checkpw(generated.encode('utf-8'), account.password_hash.encode('utf-8'))
        log = OperationLog.query.filter_by(
            module='account_security',
            action='reset_management_password',
            target_id=account.id,
        ).one()
        assert log.tenant_id == tokens['alpha_id']
        assert log.user_id == 'alpha-admin'
        assert log.detail == {
            'credentialType': 'one_time',
            'accountType': 'hrm',
            'mustChangePassword': True,
        }
        assert generated not in str(log.to_dict())


def test_portal_password_reset_returns_one_time_password_and_safe_account(tenant_accounts):
    app, tokens = tenant_accounts
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/employees/alpha-employee/reset-portal-password',
        json={'password': 'caller-controlled-password'},
    )

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    payload = response.get_json()
    generated = payload['initialPassword']
    assert len(generated) >= 20
    assert generated != 'caller-controlled-password'
    assert payload['requestId']
    assert payload['account']['id'] == 'alpha-portal'
    assert payload['account']['accountType'] == 'employee_portal'
    assert payload['account']['employeeId'] == 'alpha-employee'
    assert payload['account']['mustChangePassword'] is True
    assert 'password' not in {key.lower() for key in payload['account']}

    with app.app_context():
        account = db.session.get(EmployeePortalAccount, 'alpha-portal')
        assert account is not None
        assert account.must_change_password is True
        assert account.updated_at > datetime(2025, 1, 1)
        assert bcrypt.checkpw(generated.encode('utf-8'), account.password_hash.encode('utf-8'))
        log = OperationLog.query.filter_by(
            module='account_security',
            action='reset_portal_password',
            target_id=account.id,
        ).one()
        assert log.tenant_id == tokens['alpha_id']
        assert log.user_id == 'alpha-admin'
        assert log.detail == {
            'credentialType': 'one_time',
            'accountType': 'employee_portal',
            'mustChangePassword': True,
        }
        assert generated not in str(log.to_dict())


def test_portal_password_reset_accepts_probation_employee_account(tenant_accounts):
    app, tokens = tenant_accounts

    response = _client(app, tokens['alpha']).post(
        '/api/hrm/employees/alpha-probation-employee/reset-portal-password',
    )

    assert response.status_code == 200
    generated = response.get_json()['initialPassword']
    with app.app_context():
        account = db.session.get(EmployeePortalAccount, 'alpha-probation-portal')
        assert account is not None
        assert account.must_change_password is True
        assert bcrypt.checkpw(generated.encode('utf-8'), account.password_hash.encode('utf-8'))


def test_hr_admin_can_reset_portal_password_but_not_management_password(tenant_accounts):
    app, tokens = tenant_accounts
    client = _client(app, tokens['hr_admin'])

    management = client.post('/api/hrm/users/alpha-management-user/reset-password')
    portal = client.post('/api/hrm/employees/alpha-employee/reset-portal-password')

    assert management.status_code == 403
    assert 'initialPassword' not in management.get_json()
    assert portal.status_code == 200
    assert portal.get_json()['initialPassword']


@pytest.mark.parametrize(
    ('path', 'target_id'),
    [
        ('/api/hrm/users/alpha-management-user/reset-password', 'alpha-management-user'),
        ('/api/hrm/employees/alpha-employee/reset-portal-password', 'alpha-portal'),
    ],
)
def test_password_reset_rejects_unauthorized_role_without_mutation(
    tenant_accounts,
    path,
    target_id,
):
    app, tokens = tenant_accounts
    response = _client(app, tokens['viewer']).post(path)

    assert response.status_code == 403
    assert 'initialPassword' not in response.get_json()
    with app.app_context():
        model = User if target_id == 'alpha-management-user' else EmployeePortalAccount
        account = db.session.get(model, target_id)
        assert account is not None
        assert account.must_change_password is False
        assert OperationLog.query.filter_by(module='account_security').count() == 0


@pytest.mark.parametrize(
    'path',
    [
        '/api/hrm/users/beta-admin/reset-password',
        '/api/hrm/employees/beta-employee/reset-portal-password',
    ],
)
def test_password_reset_hides_cross_tenant_targets(tenant_accounts, path):
    app, tokens = tenant_accounts
    response = _client(app, tokens['alpha']).post(path)

    assert response.status_code == 404
    assert response.get_json()['code'] == 'ACCOUNT_NOT_FOUND'
    assert response.get_json()['error'] == '账号不存在或不可用'
    assert 'initialPassword' not in response.get_json()


@pytest.mark.parametrize(
    'path',
    [
        '/api/hrm/users/alpha-inactive-user/reset-password',
        '/api/hrm/employees/alpha-inactive-employee/reset-portal-password',
    ],
)
def test_password_reset_hides_inactive_targets(tenant_accounts, path):
    app, tokens = tenant_accounts
    response = _client(app, tokens['alpha']).post(path)

    assert response.status_code == 404
    assert response.get_json()['code'] == 'ACCOUNT_NOT_FOUND'
    assert response.get_json()['error'] == '账号不存在或不可用'
    assert 'initialPassword' not in response.get_json()


def test_portal_password_reset_hides_missing_portal_account(tenant_accounts):
    app, tokens = tenant_accounts
    response = _client(app, tokens['alpha']).post(
        '/api/hrm/employees/alpha-no-portal/reset-portal-password',
    )

    assert response.status_code == 404
    assert response.get_json()['code'] == 'ACCOUNT_NOT_FOUND'
    assert response.get_json()['error'] == '账号不存在或不可用'
    assert 'initialPassword' not in response.get_json()


def test_management_password_reset_rolls_back_mutation_and_audit_on_commit_failure(
    tenant_accounts,
):
    app, tokens = tenant_accounts
    with app.app_context():
        original_hash = db.session.get(User, 'alpha-management-user').password_hash
        session_class = type(db.session())

    state = {'fail_next': True}

    def fail_first_commit(_session):
        if state['fail_next']:
            state['fail_next'] = False
            raise RuntimeError('synthetic commit failure containing secret-value')

    event.listen(session_class, 'before_commit', fail_first_commit)
    try:
        response = _client(app, tokens['alpha']).post(
            '/api/hrm/users/alpha-management-user/reset-password',
        )
    finally:
        event.remove(session_class, 'before_commit', fail_first_commit)

    assert response.status_code == 500
    assert response.get_json()['code'] == 'ACCOUNT_PASSWORD_RESET_FAILED'
    assert response.get_json()['error'] == '密码重置失败，请稍后重试'
    assert 'initialPassword' not in response.get_json()
    assert 'secret-value' not in response.get_data(as_text=True)
    with app.app_context():
        account = db.session.get(User, 'alpha-management-user')
        assert account is not None
        assert account.password_hash == original_hash
        assert account.must_change_password is False
        assert OperationLog.query.filter_by(module='account_security').count() == 0
