from __future__ import annotations

import bcrypt
from flask_jwt_extended import create_access_token

from models import Department, OperationLog, Tenant, User, db
from services.tenancy import tenant_claims_for
from tests.test_saas_tenancy import _client, saas_app


def test_admin_creates_tenant_user_with_one_time_password(saas_app):
    app, tokens = saas_app
    response = _client(app, tokens['alpha']).post('/api/hrm/users/create', json={
        'name': ' New Recruiter ',
        'email': ' New.Recruiter@Example.com ',
        'role': 'recruiter',
        'phone': '13800000000',
        'status': 'active',
    })

    assert response.status_code == 201
    assert response.headers['Cache-Control'] == 'no-store'
    payload = response.get_json()
    generated = payload['initialPassword']
    assert len(generated) >= 20
    assert payload['account']['email'] == 'new.recruiter@example.com'
    assert payload['account']['mustChangePassword'] is True
    assert 'passwordHash' not in payload['account']

    with app.app_context():
        account = User.query.filter_by(
            tenant_id=tokens['alpha_id'],
            email='new.recruiter@example.com',
        ).one()
        assert account.name == 'New Recruiter'
        assert account.must_change_password is True
        assert bcrypt.checkpw(generated.encode('utf-8'), account.password_hash.encode('utf-8'))
        log = OperationLog.query.filter_by(
            module='account_security',
            action='create_management_account',
            target_id=account.id,
        ).one()
        assert log.user_id == 'alpha-admin'
        assert generated not in str(log.to_dict())


def test_hr_admin_cannot_create_management_user(saas_app):
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        user = User(
            id='alpha-create-hr-admin', tenant_id=tenant.id,
            email='create-hr-admin@example.com', password_hash='unused',
            name='HR Admin', role='hr_admin', status='active',
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(
            identity=user.id,
            additional_claims={'role': user.role, 'account_type': 'hrm', **tenant_claims_for(tenant)},
        )

    response = _client(app, token).post('/api/hrm/users/create', json={
        'name': 'Denied User', 'email': 'denied@example.com', 'role': 'viewer',
    })
    assert response.status_code == 403
    assert 'initialPassword' not in response.get_json()


def test_create_management_user_rejects_invalid_role_and_duplicate_email(saas_app):
    app, tokens = saas_app
    client = _client(app, tokens['alpha'])

    invalid = client.post('/api/hrm/users/create', json={
        'name': 'Platform User', 'email': 'platform@example.com', 'role': 'platform_admin',
    })
    assert invalid.status_code == 400
    assert invalid.get_json()['code'] == 'USER_ROLE_INVALID'

    duplicate = client.post('/api/hrm/users/create', json={
        'name': 'Duplicate Admin', 'email': 'admin@example.com', 'role': 'admin',
    })
    assert duplicate.status_code == 409
    assert duplicate.get_json()['code'] == 'USER_EMAIL_EXISTS'
    assert 'initialPassword' not in duplicate.get_json()


def test_create_management_user_rejects_cross_tenant_links(saas_app):
    app, tokens = saas_app
    with app.app_context():
        db.session.add(Department(
            id='beta-dept', tenant_id=tokens['beta_id'], name='Beta Department', code='BETA', status='active',
        ))
        db.session.commit()
    response = _client(app, tokens['alpha']).post('/api/hrm/users/create', json={
        'name': 'Cross Tenant',
        'email': 'cross-tenant@example.com',
        'role': 'viewer',
        'departmentId': 'beta-dept',
    })
    assert response.status_code == 400
    assert response.get_json()['code'] == 'USER_DEPARTMENT_INVALID'
