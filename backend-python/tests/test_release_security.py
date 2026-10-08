from __future__ import annotations

from pathlib import Path

import bcrypt
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app import _register_password_change_gate, _register_uploads
from models import Employee, EmployeePortalAccount, Plan, Tenant, User, db
from routes.auth import auth_bp
from routes.hrm import hrm_bp
from routes.portal import portal_bp


def _auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _seed_default_tenant() -> Tenant:
    from services.tenancy import DEFAULT_TENANT_SLUG, SAAS_MODULE_KEYS, seed_tenant_modules

    if not db.session.get(Plan, 'enterprise'):
        db.session.add(Plan(
            code='enterprise',
            name='企业全功能版',
            enabled_modules_json=list(SAAS_MODULE_KEYS),
            limits_json={},
            is_active=True,
        ))
    tenant = Tenant.query.filter_by(slug=DEFAULT_TENANT_SLUG).first()
    if not tenant:
        tenant = Tenant(
            id='tenant-default',
            slug=DEFAULT_TENANT_SLUG,
            name='默认企业',
            status='active',
            plan_code='enterprise',
        )
        db.session.add(tenant)
        db.session.flush()
    seed_tenant_modules(tenant.id)
    db.session.commit()
    return tenant


def test_public_registration_is_disabled_by_default():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    with app.app_context():
        db.create_all()
        _seed_default_tenant()

    response = app.test_client().post('/api/auth/register', json={
        'email': 'first@example.com',
        'password': 'StrongPass1!',
        'name': 'First User',
    })

    assert response.status_code == 403
    assert '公开注册已关闭' in response.get_json()['error']


def test_first_registered_user_is_not_admin_when_public_registration_is_explicitly_enabled():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ALLOW_PUBLIC_REGISTRATION=True,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    with app.app_context():
        db.create_all()
        _seed_default_tenant()

    response = app.test_client().post('/api/auth/register', json={
        'email': 'first@example.com',
        'password': 'StrongPass1!',
        'name': 'First User',
    })

    assert response.status_code == 201
    assert response.get_json()['role'] == 'employee'


def test_hrm_employee_list_requires_privileged_role():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')

    with app.app_context():
        db.create_all()
        db.session.add_all([
            User(id='u-admin', email='admin@example.com', password_hash='x', name='Admin', role='admin', status='active'),
            User(id='u-emp', email='emp@example.com', password_hash='x', name='Employee', role='employee', status='active'),
            Employee(id='e-1', employee_no='E001', name='Employee', status='active'),
        ])
        db.session.commit()
        admin_token = create_access_token(identity='u-admin', additional_claims={'role': 'admin'})
        employee_token = create_access_token(identity='u-emp', additional_claims={'role': 'employee'})

    client = app.test_client()
    denied = client.get('/api/hrm/employees', headers=_auth_header(employee_token))
    allowed = client.get('/api/hrm/employees', headers=_auth_header(admin_token))

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_uploads_and_api_files_require_jwt(tmp_path: Path):
    upload_dir = tmp_path / 'uploads'
    upload_dir.mkdir()
    (upload_dir / 'hello.txt').write_text('secret', encoding='utf-8')

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        UPLOAD_FOLDER=str(upload_dir),
    )
    JWTManager(app)
    _register_uploads(app)

    with app.app_context():
        token = create_access_token(identity='u-admin', additional_claims={'role': 'admin'})

    client = app.test_client()

    assert client.get('/uploads/hello.txt').status_code == 401
    assert client.get('/api/files/hello.txt').status_code == 401

    protected = client.get('/api/files/hello.txt', headers=_auth_header(token))
    assert protected.status_code == 200
    assert protected.data == b'secret'


def test_hrm_employee_role_cannot_login_management_console():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    with app.app_context():
        db.create_all()
        tenant = _seed_default_tenant()
        db.session.add(User(
            id='u-name',
            tenant_id=tenant.id,
            email='alice@example.com',
            password_hash=_hash('hj@123'),
            name='Alice',
            role='employee',
            status='active',
            must_change_password=True,
        ))
        db.session.commit()

    client = app.test_client()
    login = client.post('/api/auth/login', json={'identifier': 'Alice', 'password': 'hj@123'})
    assert login.status_code == 403
    assert '员工门户' in login.get_json()['error']


def test_employee_portal_no_login_requires_password_change_then_allows_after_update():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    _register_password_change_gate(app)

    with app.app_context():
        db.create_all()
        tenant = _seed_default_tenant()
        employee = Employee(
            id='e-alice',
            tenant_id=tenant.id,
            employee_no='HJ-0001',
            name='Alice',
            status='active',
        )
        account = EmployeePortalAccount(
            id='pa-alice',
            tenant_id=tenant.id,
            employee_id='e-alice',
            password_hash=_hash('hj@123'),
            status='active',
            must_change_password=True,
        )
        db.session.add_all([employee, account])
        db.session.commit()

    client = app.test_client()
    login = client.post('/api/portal/auth/login', json={'employeeNo': 'HJ-0001', 'password': 'hj@123'})
    assert login.status_code == 200
    assert login.get_json()['user']['accountType'] == 'employee_portal'
    assert login.get_json()['user']['mustChangePassword'] is True

    token = login.get_json()['token']
    blocked = client.get('/api/portal/me', headers=_auth_header(token))
    assert blocked.status_code == 403
    assert blocked.get_json()['code'] == 'PASSWORD_CHANGE_REQUIRED'

    changed = client.post('/api/portal/auth/change-password', headers=_auth_header(token), json={
        'currentPassword': 'hj@123',
        'newPassword': 'NewPass123!',
    })
    assert changed.status_code == 200
    assert changed.get_json()['user']['mustChangePassword'] is False

    allowed = client.get('/api/portal/me', headers=_auth_header(changed.get_json()['token']))
    assert allowed.status_code == 200
    assert allowed.get_json()['bound'] is True

    relogin = client.post('/api/portal/auth/login', json={'employeeNo': 'HJ-0001', 'password': 'NewPass123!'})
    assert relogin.status_code == 200


def test_hrm_token_cannot_call_employee_portal_api():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    _register_password_change_gate(app)

    with app.app_context():
        db.create_all()
        tenant = _seed_default_tenant()
        db.session.add(User(
            id='u-hr',
            tenant_id=tenant.id,
            email='hr@example.com',
            password_hash=_hash('StrongPass1!'),
            name='HR',
            role='hr_admin',
            status='active',
        ))
        db.session.commit()

    client = app.test_client()
    login = client.post('/api/auth/login', json={'identifier': 'hr@example.com', 'password': 'StrongPass1!'})
    assert login.status_code == 200
    response = client.get('/api/portal/me', headers=_auth_header(login.get_json()['token']))

    assert response.status_code == 403
    assert response.get_json()['code'] == 'EMPLOYEE_PORTAL_LOGIN_REQUIRED'
