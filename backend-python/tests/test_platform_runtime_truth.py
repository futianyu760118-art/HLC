from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import bcrypt
from sqlalchemy import event

from models import PlatformOperationLog, Tenant, TenantSubscription, User, db
from tests.test_saas_tenancy import _client, saas_app


def platform_client_and_tenant(saas_app):
    app, tokens = saas_app
    return app, _client(app, tokens['platform']), tokens['alpha_id']


def ensure_subscription(app, tenant_id, *, status='active', ends_at=None):
    with app.app_context():
        row = TenantSubscription.query.filter_by(tenant_id=tenant_id).first()
        if not row:
            row = TenantSubscription(
                id='subscription-' + tenant_id,
                tenant_id=tenant_id,
                plan_code='enterprise',
                status=status,
                ends_at=ends_at,
            )
            db.session.add(row)
        else:
            row.status = status
            row.ends_at = ends_at
        db.session.commit()
        return row.id


def add_non_admin_user(app, tenant_id):
    with app.app_context():
        user = User(
            id='non-admin-' + tenant_id,
            tenant_id=tenant_id,
            email='employee@example.com',
            password_hash='unused-in-route-test',
            name='Employee',
            role='employee',
            status='active',
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def test_elapsed_tenant_expiry_is_denied_even_when_status_is_active(saas_app):
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.status = 'active'
        tenant.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 403
    assert response.get_json() == {
        'code': 'TENANT_SUBSCRIPTION_EXPIRED',
        'error': '企业订阅已到期，请联系平台管理员续费',
    }


def test_elapsed_subscription_end_is_denied_at_login_using_latest_row(saas_app):
    app, tokens = saas_app
    with app.app_context():
        db.session.add_all([
            TenantSubscription(
                id='alpha-subscription-older',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='active',
                ends_at=datetime.utcnow() + timedelta(days=30),
                created_at=datetime.utcnow() - timedelta(days=1),
            ),
            TenantSubscription(
                id='alpha-subscription-latest',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='active',
                ends_at=datetime.utcnow() - timedelta(seconds=1),
                created_at=datetime.utcnow(),
            ),
        ])
        db.session.commit()

    response = app.test_client().post('/api/auth/login', json={
        'tenantSlug': 'alpha',
        'identifier': 'admin@example.com',
        'password': 'Passw0rd!',
    })

    assert response.status_code == 403
    assert response.get_json() == {
        'code': 'TENANT_SUBSCRIPTION_EXPIRED',
        'error': '企业订阅已到期，请联系平台管理员续费',
    }


@pytest.mark.parametrize('status', ['suspended', 'cancelled', 'expired'])
def test_inactive_latest_subscription_blocks_authenticated_requests(saas_app, status):
    app, tokens = saas_app
    ensure_subscription(
        app,
        tokens['alpha_id'],
        status=status,
        ends_at=datetime.utcnow() + timedelta(days=30),
    )

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 403
    assert response.get_json() == {
        'code': 'TENANT_SUBSCRIPTION_INACTIVE',
        'error': '企业订阅当前不可用，请联系平台管理员',
    }


def test_latest_subscription_uses_id_as_deterministic_created_at_tiebreaker(saas_app):
    app, tokens = saas_app
    same_created_at = datetime.utcnow()
    with app.app_context():
        db.session.add_all([
            TenantSubscription(
                id='alpha-subscription-a',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='active',
                ends_at=datetime.utcnow() + timedelta(days=30),
                created_at=same_created_at,
            ),
            TenantSubscription(
                id='alpha-subscription-z',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='cancelled',
                ends_at=datetime.utcnow() + timedelta(days=30),
                created_at=same_created_at,
            ),
        ])
        db.session.commit()

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 403
    assert response.get_json()['code'] == 'TENANT_SUBSCRIPTION_INACTIVE'


def test_platform_detail_uses_the_same_deterministic_latest_subscription(saas_app):
    app, tokens = saas_app
    same_created_at = datetime.utcnow()
    with app.app_context():
        db.session.add_all([
            TenantSubscription(
                id='alpha-subscription-a',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='active',
                created_at=same_created_at,
            ),
            TenantSubscription(
                id='alpha-subscription-z',
                tenant_id=tokens['alpha_id'],
                plan_code='enterprise',
                status='cancelled',
                created_at=same_created_at,
            ),
        ])
        db.session.commit()

    response = _client(app, tokens['platform']).get(
        f"/api/platform/tenants/{tokens['alpha_id']}"
    )

    assert response.status_code == 200
    assert response.get_json()['subscription']['id'] == 'alpha-subscription-z'


@pytest.mark.parametrize('status', ['inactive', 'suspended', 'expired'])
def test_persisted_inactive_tenant_status_remains_denied(saas_app, status):
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.status = status
        db.session.commit()

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 403
    assert response.get_json() == {
        'code': 'TENANT_INACTIVE',
        'error': '企业服务已停用或到期，请联系平台管理员',
    }


def test_active_tenant_without_subscription_remains_allowed(saas_app):
    app, tokens = saas_app

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 200


def test_active_tenant_with_future_expiries_remains_allowed(saas_app):
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.expires_at = datetime.utcnow() + timedelta(days=15)
        db.session.commit()
    ensure_subscription(
        app,
        tokens['alpha_id'],
        status='active',
        ends_at=datetime.utcnow() + timedelta(days=30),
    )

    response = _client(app, tokens['alpha']).get('/api/jobs/')

    assert response.status_code == 200


def test_platform_admin_apis_remain_accessible_when_tenant_is_blocked(saas_app):
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.status = 'suspended'
        tenant.expires_at = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
    ensure_subscription(app, tokens['alpha_id'], status='cancelled')

    response = _client(app, tokens['platform']).get('/api/platform/tenants')

    assert response.status_code == 200
    assert {row['slug'] for row in response.get_json()} == {'alpha', 'beta'}


def test_updating_only_expiry_updates_latest_subscription(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    subscription_id = ensure_subscription(app, tenant_id)

    response = platform.put(
        f'/api/platform/tenants/{tenant_id}',
        json={'expiresAt': '2031-01-02T00:00:00Z'},
    )

    assert response.status_code == 200
    with app.app_context():
        tenant = db.session.get(Tenant, tenant_id)
        subscription = db.session.get(TenantSubscription, subscription_id)
        assert tenant.expires_at == datetime(2031, 1, 2)
        assert subscription.ends_at == datetime(2031, 1, 2)


def test_clearing_expiry_clears_latest_subscription_end(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    subscription_id = ensure_subscription(
        app,
        tenant_id,
        ends_at=datetime(2031, 1, 2),
    )

    response = platform.put(
        f'/api/platform/tenants/{tenant_id}',
        json={'expiresAt': None},
    )

    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Tenant, tenant_id).expires_at is None
        assert db.session.get(TenantSubscription, subscription_id).ends_at is None


@pytest.mark.parametrize(
    'payload',
    [
        {'status': 'anything'},
        {'maxUsers': -1},
        {'maxEmployees': 0},
        {'maxStorageMb': 'bad'},
        {'aiMonthlyQuota': -1},
        {'expiresAt': 'not-a-date'},
    ],
)
def test_tenant_update_rejects_invalid_fields(saas_app, payload):
    _app, platform, tenant_id = platform_client_and_tenant(saas_app)

    response = platform.put(f'/api/platform/tenants/{tenant_id}', json=payload)

    assert response.status_code == 400
    assert response.get_json()['code'] == 'PLATFORM_VALIDATION_ERROR'


def test_password_reset_requires_explicit_admin_target(saas_app):
    _app, platform, tenant_id = platform_client_and_tenant(saas_app)

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'ADMIN_TARGET_REQUIRED'


def test_tenant_detail_lists_only_active_administrator_reset_targets(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    with app.app_context():
        db.session.add_all([
            User(
                id='alpha-active-hr-admin',
                tenant_id=tenant_id,
                email='active-hr-admin@example.com',
                password_hash='unused',
                name='Active HR Admin',
                role='hr_admin',
                status='active',
            ),
            User(
                id='alpha-inactive-admin',
                tenant_id=tenant_id,
                email='inactive-admin@example.com',
                password_hash='unused',
                name='Inactive Admin',
                role='admin',
                status='inactive',
            ),
        ])
        db.session.commit()

    response = platform.get(f'/api/platform/tenants/{tenant_id}')

    assert response.status_code == 200
    targets = response.get_json()['admins']
    target_ids = {row['id'] for row in targets}
    assert target_ids == {'alpha-admin', 'alpha-active-hr-admin'}
    assert all(set(row) == {'id', 'email', 'name', 'role', 'status'} for row in targets)


def test_password_reset_rejects_non_admin_user_and_records_sanitized_failure(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    employee_user_id = add_non_admin_user(app, tenant_id)
    request_id = 'reset-non-admin-test'

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        headers={'X-Request-ID': request_id},
        json={
            'userId': employee_user_id,
            'confirmation': 'RESET',
            'password': 'client-controlled-secret',
            'email': 'employee@example.com',
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'TARGET_NOT_TENANT_ADMIN'
    safe_request_id = response.get_json()['requestId']
    assert safe_request_id != request_id
    with app.app_context():
        log = PlatformOperationLog.query.filter_by(request_id=safe_request_id).one()
        assert log.result == 'failure'
        assert log.error_code == 'TARGET_NOT_TENANT_ADMIN'
        assert log.action == 'reset_admin_password'
        assert 'employee@example.com' not in str(log.detail)
        assert 'client-controlled-secret' not in str(log.detail)
        assert 'RESET' not in str(log.detail)
        employee = db.session.get(User, employee_user_id)
        assert employee.must_change_password is False


def test_password_reset_requires_same_tenant_active_admin(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    with app.app_context():
        # The fixture has one administrator per tenant; resolve the other tenant
        # explicitly to prove the command does not cross the tenant boundary.
        beta_admin = User.query.filter(User.tenant_id != tenant_id, User.role == 'admin').first()
        assert beta_admin is not None
        target_id = beta_admin.id

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'userId': target_id, 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'TARGET_NOT_TENANT_ADMIN'


def test_password_reset_generates_one_time_credential_and_atomic_success_audit(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    request_id = 'reset-success-test'

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        headers={'X-Request-ID': request_id},
        json={
            'userId': 'alpha-admin',
            'confirmation': 'RESET alpha',
            'password': 'ignored-client-password',
            'email': 'admin@example.com',
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    generated = payload['initialPassword']
    assert len(generated) >= 20
    assert generated != 'ignored-client-password'
    assert payload['requestId'] != request_id
    with app.app_context():
        user = db.session.get(User, 'alpha-admin')
        assert user.must_change_password is True
        assert bcrypt.checkpw(generated.encode('utf-8'), user.password_hash.encode('utf-8'))
        log = PlatformOperationLog.query.filter_by(request_id=payload['requestId']).one()
        assert log.result == 'success'
        assert log.error_code is None
        assert log.detail == {'credentialType': 'one_time', 'mustChangePassword': True}


def test_password_reset_rejects_inactive_admin_and_does_not_return_credential(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    with app.app_context():
        user = db.session.get(User, 'alpha-admin')
        user.status = 'inactive'
        db.session.commit()

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'userId': 'alpha-admin', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'TARGET_NOT_TENANT_ADMIN'
    assert 'initialPassword' not in response.get_json()


def test_password_reset_failure_audit_hashes_untrusted_target_identifier(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    request_id = 'reset-pii-target-test'
    untrusted_identifier = 'person@example.com'

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        headers={'X-Request-ID': request_id},
        json={'userId': untrusted_identifier, 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 409
    safe_request_id = response.get_json()['requestId']
    assert safe_request_id != request_id
    with app.app_context():
        log = PlatformOperationLog.query.filter_by(request_id=safe_request_id).one()
        assert untrusted_identifier not in str(log.to_dict())
        assert log.target_id != untrusted_identifier


def test_password_reset_email_selector_cannot_replace_explicit_user_id(saas_app):
    _app, platform, tenant_id = platform_client_and_tenant(saas_app)

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'email': 'admin@example.com', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'ADMIN_TARGET_REQUIRED'
    assert 'initialPassword' not in response.get_json()


def test_password_reset_confirmation_mismatch_does_not_change_hash(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    with app.app_context():
        original_hash = db.session.get(User, 'alpha-admin').password_hash

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'userId': 'alpha-admin', 'confirmation': 'RESET wrong-tenant'},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'CONFIRMATION_MISMATCH'
    with app.app_context():
        assert db.session.get(User, 'alpha-admin').password_hash == original_hash


def test_password_reset_rolls_back_credential_and_success_audit_when_commit_fails_once(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    request_id = 'reset-commit-failure-test'
    with app.app_context():
        original_hash = db.session.get(User, 'alpha-admin').password_hash
        session_class = type(db.session())

    state = {'fail_next': True}

    def fail_first_commit(_session):
        if state['fail_next']:
            state['fail_next'] = False
            raise RuntimeError('synthetic commit failure')

    event.listen(session_class, 'before_commit', fail_first_commit)
    try:
        response = platform.post(
            f'/api/platform/tenants/{tenant_id}/reset-admin-password',
            headers={'X-Request-ID': request_id},
            json={'userId': 'alpha-admin', 'confirmation': 'RESET alpha'},
        )
    finally:
        event.remove(session_class, 'before_commit', fail_first_commit)

    assert response.status_code == 500
    assert response.get_json()['code'] == 'ADMIN_PASSWORD_RESET_FAILED'
    assert 'initialPassword' not in response.get_json()
    safe_request_id = response.get_json()['requestId']
    assert safe_request_id != request_id
    with app.app_context():
        user = db.session.get(User, 'alpha-admin')
        assert user.password_hash == original_hash
        assert user.must_change_password is False
        logs = PlatformOperationLog.query.filter_by(request_id=safe_request_id).all()
        assert len(logs) == 1
        assert logs[0].result == 'failure'
        assert logs[0].error_code == 'ADMIN_PASSWORD_RESET_FAILED'


def test_password_reset_accepts_active_hr_admin_in_same_tenant(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    with app.app_context():
        db.session.add(User(
            id='alpha-hr-admin',
            tenant_id=tenant_id,
            email='hr-admin@example.com',
            password_hash='old-unused-hash',
            name='Alpha HR Admin',
            role='hr_admin',
            status='active',
        ))
        db.session.commit()

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'userId': 'alpha-hr-admin', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 200
    generated = response.get_json()['initialPassword']
    with app.app_context():
        user = db.session.get(User, 'alpha-hr-admin')
        assert user.must_change_password is True
        assert bcrypt.checkpw(generated.encode('utf-8'), user.password_hash.encode('utf-8'))


@pytest.mark.parametrize('raw_request_id', ['person@example.com', '13800138000', 'x' * 256])
def test_password_reset_audit_normalizes_untrusted_request_and_forwarded_ip(
    saas_app,
    raw_request_id,
):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    raw_forwarded_for = 'attacker@example.com, secret-token'

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        headers={
            'X-Request-ID': raw_request_id,
            'X-Forwarded-For': raw_forwarded_for,
        },
        json={'userId': 'missing-target', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 409
    assert len(response.get_json()['requestId']) <= 64
    with app.app_context():
        log = PlatformOperationLog.query.filter_by(action='reset_admin_password').one()
        assert log.request_id != raw_request_id
        assert raw_request_id not in str(log.to_dict())
        assert raw_forwarded_for not in str(log.to_dict())
        assert log.ip_address == '127.0.0.1'


def test_password_reset_prepares_response_before_commit_expiration(saas_app, monkeypatch):
    """A post-commit expiration must not prevent one-time credential delivery."""

    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    from sqlalchemy import inspect

    original_to_dict = User.to_dict

    def fail_if_expired(user):
        if inspect(user).expired:
            raise RuntimeError('response serialization touched expired user')
        return original_to_dict(user)

    monkeypatch.setattr(User, 'to_dict', fail_if_expired)
    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        json={'userId': 'alpha-admin', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 200
    assert len(response.get_json()['initialPassword']) >= 20


def test_password_reset_malformed_unicode_target_still_records_failure_audit(saas_app):
    app, platform, tenant_id = platform_client_and_tenant(saas_app)
    request_id = 'reset-malformed-unicode-test'

    response = platform.post(
        f'/api/platform/tenants/{tenant_id}/reset-admin-password',
        headers={'X-Request-ID': request_id},
        json={'userId': '\ud800', 'confirmation': 'RESET alpha'},
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'TARGET_NOT_TENANT_ADMIN'
    safe_request_id = response.get_json()['requestId']
    assert safe_request_id != request_id
    with app.app_context():
        log = PlatformOperationLog.query.filter_by(request_id=safe_request_id).one()
        assert log.result == 'failure'
        assert log.error_code == 'TARGET_NOT_TENANT_ADMIN'
