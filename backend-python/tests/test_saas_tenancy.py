from __future__ import annotations

import uuid

import bcrypt
import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app import _register_request_lifecycle, _register_tenant_context
from models import AssistantSession, Department, Job, Plan, Resume, Tenant, TenantModule, User, db
from routes import (
    auth_bp,
    enterprise_applications_platform_bp,
    enterprise_applications_public_bp,
    extensions_bp,
    hrm_bp,
    interviews_bp,
    jobs_bp,
    misc_bp,
    platform_bp,
    portal_bp,
    resumes_bp,
)
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
        max_users=10,
        max_employees=100,
        max_storage_mb=1024,
        ai_monthly_quota=100,
    )


def _seed_modules(tenant_id: str, *, disabled: set[str] | None = None) -> None:
    disabled = disabled or set()
    for module_key in SAAS_MODULE_KEYS:
        db.session.add(TenantModule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            module_key=module_key,
            enabled=module_key not in disabled,
            limits_json={},
        ))


@pytest.fixture()
def saas_app(tmp_path):
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
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(jobs_bp, url_prefix='/api/jobs')
    app.register_blueprint(resumes_bp, url_prefix='/api/resumes')
    app.register_blueprint(interviews_bp, url_prefix='/api/interviews')
    app.register_blueprint(misc_bp, url_prefix='/api')
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    app.register_blueprint(extensions_bp, url_prefix='/api/extensions')
    app.register_blueprint(platform_bp, url_prefix='/api/platform')
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    app.register_blueprint(enterprise_applications_public_bp, url_prefix='/api/public')
    app.register_blueprint(enterprise_applications_platform_bp, url_prefix='/api/platform')
    _register_request_lifecycle(app)
    _register_tenant_context(app)

    with app.app_context():
        db.create_all()
        db.session.add(Plan(
            code='enterprise',
            name='企业全功能版',
            enabled_modules_json=list(SAAS_MODULE_KEYS),
            limits_json={},
            is_active=True,
        ))
        alpha = _tenant('alpha', 'Alpha 公司')
        beta = _tenant('beta', 'Beta 公司')
        db.session.add_all([alpha, beta])
        db.session.flush()
        _seed_modules(alpha.id)
        _seed_modules(beta.id)
        users = [
            User(id='platform-user', tenant_id=None, email='platform@example.com', password_hash=_hash('Passw0rd!'), name='Platform', role='platform_admin', status='active'),
            User(id='alpha-admin', tenant_id=alpha.id, email='admin@example.com', password_hash=_hash('Passw0rd!'), name='Alpha Admin', role='admin', status='active'),
            User(id='beta-admin', tenant_id=beta.id, email='admin@example.com', password_hash=_hash('Passw0rd!'), name='Beta Admin', role='admin', status='active'),
        ]
        db.session.add_all(users)
        db.session.commit()

        def token_for(user_id: str, tenant: Tenant | None = None, *, platform: bool = False) -> str:
            user = db.session.get(User, user_id)
            return create_access_token(
                identity=user_id,
                additional_claims={
                    'role': user.role,
                    'account_type': 'hrm',
                    **tenant_claims_for(tenant, is_platform_admin=platform),
                },
            )

        tokens = {
            'platform': token_for('platform-user', None, platform=True),
            'alpha': token_for('alpha-admin', alpha),
            'beta': token_for('beta-admin', beta),
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


def test_login_uses_tenant_slug(saas_app):
    app, _tokens = saas_app
    client = app.test_client()

    ok = client.post('/api/auth/login', json={
        'tenantSlug': 'alpha',
        'identifier': 'admin@example.com',
        'password': 'Passw0rd!',
    })
    assert ok.status_code == 200
    assert ok.get_json()['user']['tenantSlug'] == 'alpha'

    wrong_tenant = client.post('/api/auth/login', json={
        'tenantSlug': 'missing',
        'identifier': 'admin@example.com',
        'password': 'Passw0rd!',
    })
    assert wrong_tenant.status_code == 404

    platform = client.post('/api/platform/auth/login', json={
        'identifier': 'platform@example.com',
        'password': 'Passw0rd!',
    })
    assert platform.status_code == 200
    assert platform.get_json()['user']['isPlatformAdmin'] is True


def test_hrm_crud_is_tenant_scoped(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    assert alpha.post('/api/hrm/departments', json={'name': '研发部', 'code': 'RD'}).status_code == 201
    assert beta.post('/api/hrm/departments', json={'name': '研发部', 'code': 'RD'}).status_code == 201

    alpha_rows = alpha.get('/api/hrm/departments').get_json()
    beta_rows = beta.get('/api/hrm/departments').get_json()
    assert len(alpha_rows) == 1
    assert len(beta_rows) == 1
    assert alpha_rows[0]['id'] != beta_rows[0]['id']


def test_hrm_list_pagination_is_bounded_and_tenant_scoped(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    for index in range(3):
        assert alpha.post('/api/hrm/departments', json={
            'name': f'Alpha 研发部 {index}',
            'code': f'ALPHA-RD-{index}',
            'status': 'active',
        }).status_code == 201
    assert beta.post('/api/hrm/departments', json={
        'name': 'Beta 研发部',
        'code': 'BETA-RD',
        'status': 'active',
    }).status_code == 201

    first_page = alpha.get('/api/hrm/departments?page=1&size=2&keyword=Alpha')
    assert first_page.status_code == 200
    payload = first_page.get_json()
    assert payload['page'] == 1
    assert payload['size'] == 2
    assert payload['total'] == 3
    assert payload['pages'] == 2
    assert len(payload['items']) == 2
    assert all(item['name'].startswith('Alpha') for item in payload['items'])

    zero_size = alpha.get('/api/hrm/departments?page=1&size=0')
    assert zero_size.status_code == 200
    assert zero_size.get_json()['size'] == 1

    oversized = alpha.get('/api/hrm/departments?page=1&size=999')
    assert oversized.status_code == 200
    assert oversized.get_json()['size'] == 200

    beta_page = beta.get('/api/hrm/departments?page=1&size=20')
    assert beta_page.status_code == 200
    beta_payload = beta_page.get_json()
    assert beta_payload['total'] == 1
    assert [item['name'] for item in beta_payload['items']] == ['Beta 研发部']

    with app.app_context():
        assert Department.query.count() == 4


def test_job_create_assigns_current_tenant_and_stays_isolated(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    created = alpha.post('/api/jobs/', json={
        'title': 'Alpha SaaS 架构师',
        'description': '负责 SaaS 商业化验证。',
    })
    assert created.status_code == 201
    job_id = created.get_json()['id']

    alpha_rows = alpha.get('/api/jobs/').get_json()
    beta_rows = beta.get('/api/jobs/').get_json()
    assert any(row['id'] == job_id for row in alpha_rows)
    assert all(row['id'] != job_id for row in beta_rows)

    with app.app_context():
        assert db.session.get(Job, job_id).tenant_id == tokens['alpha_id']


def test_jobs_route_pagination_and_object_writes_are_tenant_scoped(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    first = alpha.post('/api/jobs/', json={
        'title': 'Alpha 产品经理',
        'description': '负责商业化需求。',
    })
    second = alpha.post('/api/jobs/', json={
        'title': 'Alpha 招聘专员',
        'description': '负责招聘流程。',
    })
    assert first.status_code == 201
    assert second.status_code == 201
    job_id = first.get_json()['id']

    page = alpha.get('/api/jobs/?page=1&size=1')
    assert page.status_code == 200
    payload = page.get_json()
    assert payload['page'] == 1
    assert payload['size'] == 1
    assert payload['total'] == 2
    assert payload['pages'] == 2
    assert len(payload['items']) == 1

    legacy = alpha.get('/api/jobs/').get_json()
    assert isinstance(legacy, list)
    assert len(legacy) == 2

    assert beta.put(f'/api/jobs/{job_id}', json={'title': 'Beta 越权修改'}).status_code == 404
    assert beta.delete(f'/api/jobs/{job_id}').status_code == 404

    with app.app_context():
        assert db.session.get(Job, job_id).title == 'Alpha 产品经理'


def test_resumes_route_pagination_and_object_writes_are_tenant_scoped(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    with app.app_context():
        job = Job(
            id='alpha-resume-job',
            tenant_id=tokens['alpha_id'],
            title='Alpha 简历岗位',
            description='用于简历测试。',
            created_by='alpha-admin',
            updated_by='alpha-admin',
        )
        resume = Resume(
            id='alpha-resume-1',
            tenant_id=tokens['alpha_id'],
            job_id=job.id,
            candidate_name='Alpha 候选人',
            email='candidate@example.com',
            phone='13800000000',
            file_url='/uploads/resumes/alpha-resume-1.pdf',
            ai_analysis={'summary': 'ok'},
            tags=[],
            created_by='alpha-admin',
            updated_by='alpha-admin',
        )
        resume_two = Resume(
            id='alpha-resume-2',
            tenant_id=tokens['alpha_id'],
            job_id=job.id,
            candidate_name='Alpha 候选人 2',
            file_url='/uploads/resumes/alpha-resume-2.pdf',
            ai_analysis={'summary': 'ok'},
            tags=[],
            created_by='alpha-admin',
            updated_by='alpha-admin',
        )
        db.session.add_all([job, resume, resume_two])
        db.session.commit()

    page = alpha.get('/api/resumes/?page=1&size=1')
    assert page.status_code == 200
    payload = page.get_json()
    assert payload['page'] == 1
    assert payload['size'] == 1
    assert payload['total'] == 2
    assert payload['pages'] == 2
    assert len(payload['items']) == 1

    legacy = alpha.get('/api/resumes/').get_json()
    assert isinstance(legacy, list)
    assert len(legacy) == 2

    assert beta.put('/api/resumes/alpha-resume-1', json={'candidateName': 'Beta 越权修改'}).status_code == 404
    assert beta.delete('/api/resumes/alpha-resume-1').status_code == 404
    assert beta.post('/api/resumes/alpha-resume-1/reanalyze').status_code == 404

    with app.app_context():
        assert db.session.get(Resume, 'alpha-resume-1').candidate_name == 'Alpha 候选人'


def test_module_switch_blocks_backend_routes(saas_app):
    app, tokens = saas_app
    with app.app_context():
        TenantModule.query.filter_by(tenant_id=tokens['alpha_id'], module_key='organization').update({'enabled': False})
        db.session.commit()

    alpha = _client(app, tokens['alpha'])
    response = alpha.get('/api/hrm/departments')
    assert response.status_code == 403
    assert response.get_json()['code'] == 'MODULE_DISABLED'


def test_platform_routes_require_platform_admin(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    platform = _client(app, tokens['platform'])

    assert alpha.get('/api/platform/tenants').status_code == 403
    response = platform.get('/api/platform/tenants')
    assert response.status_code == 200
    assert {row['slug'] for row in response.get_json()} == {'alpha', 'beta'}


def test_platform_create_tenant_generates_random_initial_password(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])

    first = platform.post('/api/platform/tenants', json={
        'name': 'Gamma 公司',
        'adminEmail': 'gamma-admin@example.com',
        'adminName': 'Gamma Admin',
        'planCode': 'enterprise',
    })
    second = platform.post('/api/platform/tenants', json={
        'name': 'Delta 公司',
        'adminEmail': 'delta-admin@example.com',
        'adminName': 'Delta Admin',
        'planCode': 'enterprise',
    })

    assert first.status_code == 201
    assert second.status_code == 201
    p1 = first.get_json()['initialPassword']
    p2 = second.get_json()['initialPassword']
    assert p1 != p2
    assert p1 != 'hj@123'
    assert len(p1) >= 16


def test_platform_create_tenant_persists_selected_enabled_modules(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])

    response = platform.post('/api/platform/tenants', json={
        'name': 'Module Scoped 公司',
        'adminEmail': 'module-scoped-admin@example.com',
        'adminName': 'Module Scoped Admin',
        'planCode': 'enterprise',
        'enabledModules': ['recruitment', 'system'],
    })

    assert response.status_code == 201
    payload = response.get_json()
    modules = {row['moduleKey']: row['enabled'] for row in payload['modules']}
    assert modules['recruitment'] is True
    assert modules['system'] is True
    assert modules['organization'] is False

    with app.app_context():
        tenant_token = create_access_token(
            identity=payload['admin']['id'],
            additional_claims={
                'role': 'admin',
                'account_type': 'hrm',
                **tenant_claims_for(db.session.get(Tenant, payload['id'])),
            },
        )

    tenant_client = _client(app, tenant_token)
    blocked = tenant_client.get('/api/hrm/departments')
    assert blocked.status_code == 403
    assert blocked.get_json()['code'] == 'MODULE_DISABLED'


def test_assistant_sessions_and_history_do_not_cross_tenants(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    with app.app_context():
        db.session.add(AssistantSession(
            id='beta-ai-memory-session',
            tenant_id=tokens['beta_id'],
            user_id='beta-admin',
            title='Beta AI memory',
            messages=[
                {'role': 'user', 'content': 'Beta confidential prompt'},
                {'role': 'assistant', 'content': 'Beta confidential answer'},
            ],
            is_active=True,
            message_count=2,
        ))
        db.session.commit()

    assert alpha.get('/api/hrm/assistant/sessions/beta-ai-memory-session').status_code == 404
    beta_detail = beta.get('/api/hrm/assistant/sessions/beta-ai-memory-session')
    assert beta_detail.status_code == 200
    assert 'Beta confidential answer' in str(beta_detail.get_json())

    with app.test_request_context(
        '/api/hrm/assistant/query',
        method='POST',
        headers={'Authorization': f"Bearer {tokens['alpha']}"},
    ):
        assert app.preprocess_request() is None
        from services.assistant_core.memory import build_context

        ctx = build_context('alpha-admin', 'beta-ai-memory-session')

    assert ctx.session_id != 'beta-ai-memory-session'
    assert 'Beta confidential' not in str(ctx.history)


def test_assistant_workset_memory_is_request_owner_isolated(saas_app):
    app, tokens = saas_app

    from services.assistant_core import workset_store

    workset_store.default_store.clear()
    beta_workset = workset_store.create_workset_from_entities(
        'beta-workset-session',
        'beta-admin',
        'Beta 候选人结果集',
        [{
            'type': 'candidate',
            'id': 'beta-candidate-secret',
            'title': 'Beta confidential candidate',
        }],
    )
    assert beta_workset is not None

    with app.test_request_context(
        '/api/hrm/assistant/query',
        method='POST',
        headers={'Authorization': f"Bearer {tokens['alpha']}"},
    ):
        assert app.preprocess_request() is None
        leaked = workset_store.resolve_mention('这些候选人怎么样', 'beta-workset-session')

    assert leaked is None

    with app.test_request_context(
        '/api/hrm/assistant/query',
        method='POST',
        headers={'Authorization': f"Bearer {tokens['beta']}"},
    ):
        assert app.preprocess_request() is None
        beta_visible = workset_store.resolve_mention('这些候选人怎么样', 'beta-workset-session')

    assert beta_visible is not None
    assert beta_visible['workset']['owner_user_id'] == 'beta-admin'
