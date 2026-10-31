from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import threading

import pytest
from flask import Flask
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from logging_config import JsonFormatter
from app import _register_password_change_gate, _register_request_lifecycle
from models import EnterpriseServiceApplication, PlatformOperationLog, Tenant, User, db
from routes.enterprise_applications import enterprise_applications_public_bp
from schema_migrations import ensure_schema
from tests.test_saas_tenancy import _client, saas_app


VALID_PAYLOAD = {
    'companyName': '星海智造有限公司',
    'contactName': '林女士',
    'mobile': '138 0013 8000',
    'email': 'lin@example.com',
    'region': '上海市',
    'employeeScale': '100-499',
    'interestedModules': ['organization', 'attendance', 'payroll'],
    'preferredContactTime': 'weekday_afternoon',
    'notes': '希望先了解组织人事、考勤和薪酬的一体化方案。',
    'privacyConsent': True,
    'website': '',
}


def submit(client, *, key='123e4567-e89b-12d3-a456-426614174000', payload=None,
           forwarded_for='203.0.113.10', remote_addr='203.0.113.10',
           user_agent='enterprise-test/1.0', request_id='public-application-test'):
    return client.post(
        '/api/public/enterprise-applications',
        json=VALID_PAYLOAD if payload is None else payload,
        headers={
            'Idempotency-Key': key,
            'X-Forwarded-For': forwarded_for,
            'User-Agent': user_agent,
            'X-Request-ID': request_id,
        },
        environ_overrides={'REMOTE_ADDR': remote_addr},
    )


def _file_backed_public_app(tmp_path):
    app = Flask(f'enterprise-concurrency-{tmp_path.name}')
    database_path = (tmp_path / 'enterprise-concurrency.sqlite').as_posix()
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-secret',
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{database_path}',
        SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'timeout': 15}},
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(enterprise_applications_public_bp, url_prefix='/api/public')
    _register_request_lifecycle(app)
    with app.app_context():
        db.create_all()
    return app


def _concurrent_submissions(app, keys):
    start = threading.Barrier(len(keys))
    responses = [None] * len(keys)

    def worker(index, key):
        start.wait(timeout=10)
        responses[index] = submit(
            app.test_client(),
            key=key,
            remote_addr='203.0.113.77',
            forwarded_for=f'198.51.100.{index + 1}',
        )

    threads = [threading.Thread(target=worker, args=(index, key)) for index, key in enumerate(keys)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    return responses


def test_public_submission_requires_no_login_and_returns_no_pii(saas_app):
    app, _tokens = saas_app

    response = submit(app.test_client())

    assert response.status_code == 201
    assert set(response.get_json()) == {'applicationNo', 'status'}
    assert response.get_json()['status'] == 'new'
    assert response.get_json()['applicationNo'].startswith('ESA-')
    raw = response.get_data(as_text=True)
    assert '13800138000' not in raw
    assert 'lin@example.com' not in raw
    assert '星海智造' not in raw


def test_public_submission_inserts_application_before_linking_submission_guard(saas_app):
    """The guard FK may only be linked after its application row exists."""
    app, _tokens = saas_app
    with app.app_context():
        engine = db.engine

    statements = []

    def capture_submission_writes(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = ' '.join(statement.lower().split())
        if (
            normalized.startswith('insert into enterprise_service_applications')
            or normalized.startswith('update enterprise_application_submission_guards')
        ):
            statements.append(normalized)

    event.listen(engine, 'before_cursor_execute', capture_submission_writes)
    try:
        response = submit(app.test_client())
    finally:
        event.remove(engine, 'before_cursor_execute', capture_submission_writes)

    assert response.status_code == 201
    application_insert = next(
        index for index, statement in enumerate(statements)
        if statement.startswith('insert into enterprise_service_applications')
    )
    guard_link = next(
        index for index, statement in enumerate(statements)
        if statement.startswith('update enterprise_application_submission_guards')
    )
    assert application_insert < guard_link


def test_public_submission_is_available_when_the_browser_has_a_password_change_token(saas_app):
    """A public lead form must not inherit an authenticated user's password gate."""
    app, tokens = saas_app
    with app.app_context():
        user = db.session.get(User, 'alpha-admin')
        user.must_change_password = True
        db.session.commit()

    _register_password_change_gate(app)

    response = submit(_client(app, tokens['alpha']))

    assert response.status_code == 201
    assert response.get_json()['status'] == 'new'


@pytest.mark.parametrize(
    ('payload', 'code'),
    [
        ({**VALID_PAYLOAD, 'unknown': 'value'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'companyName': ' '}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'companyName': 'A'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'contactName': ''}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'mobile': '12345'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'email': 'not-an-email'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'privacyConsent': 1}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'interestedModules': ['unknown-module']}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'employeeScale': 'huge'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'preferredContactTime': 'midnight'}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'notes': 'x' * 1001}, 'APPLICATION_PAYLOAD_INVALID'),
        ({**VALID_PAYLOAD, 'website': 'https://spam.example'}, 'APPLICATION_PAYLOAD_INVALID'),
    ],
)
def test_public_submission_strictly_validates_payload(saas_app, payload, code):
    app, _tokens = saas_app

    response = submit(app.test_client(), payload=payload)

    assert response.status_code == 400
    assert response.get_json()['code'] == code
    assert set(response.get_json()) <= {'error', 'code', 'requestId', 'fields'}


@pytest.mark.parametrize('key', [None, '', 'short', 'contains whitespace'])
def test_public_submission_requires_valid_idempotency_key(saas_app, key):
    app, _tokens = saas_app
    headers = {
        'X-Forwarded-For': '203.0.113.20',
        'User-Agent': 'enterprise-test/1.0',
    }
    if key is not None:
        headers['Idempotency-Key'] = key

    response = app.test_client().post(
        '/api/public/enterprise-applications',
        json=VALID_PAYLOAD,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'APPLICATION_IDEMPOTENCY_KEY_INVALID'


def test_idempotency_reuses_application_before_cooldown_check(saas_app):
    app, _tokens = saas_app
    client = app.test_client()

    first = submit(client)
    second = submit(client)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    with app.app_context():
        total = db.session.execute(text('SELECT COUNT(*) FROM enterprise_service_applications')).scalar()
        assert total == 1


def test_idempotency_replay_keeps_the_original_public_contract_after_internal_status_changes(saas_app):
    app, tokens = saas_app
    first = submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.get('/api/platform/enterprise-applications?page=1&pageSize=20').get_json()['items'][0]
    contacting = platform.patch(
        f"/api/platform/enterprise-applications/{row['id']}",
        json={'status': 'contacting', 'version': row['version']},
    )
    assert contacting.status_code == 200
    assert platform.patch(
        f"/api/platform/enterprise-applications/{row['id']}",
        json={'status': 'qualified', 'version': contacting.get_json()['version']},
    ).status_code == 200

    replay = submit(app.test_client())

    assert replay.status_code == 200
    assert replay.get_json() == {
        'applicationNo': first.get_json()['applicationNo'],
        'status': 'new',
    }


def test_same_raw_idempotency_key_is_scoped_to_the_server_derived_source_fingerprint(saas_app):
    app, _tokens = saas_app
    raw_key = '123e4567-e89b-12d3-a456-426614174099'

    first = submit(app.test_client(), key=raw_key, remote_addr='203.0.113.21')
    second = submit(app.test_client(), key=raw_key, remote_addr='203.0.113.22')

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()['applicationNo'] != second.get_json()['applicationNo']
    with app.app_context():
        persisted = db.session.execute(text(
            'SELECT idempotency_key FROM enterprise_service_applications ORDER BY created_at'
        )).scalars().all()
        assert len(persisted) == 2
        assert raw_key not in persisted
        assert all(value.startswith('idem_') for value in persisted)


def test_fingerprint_cooldown_rejects_a_different_key_without_disclosing_match(saas_app):
    app, _tokens = saas_app
    client = app.test_client()

    assert submit(client).status_code == 201
    response = submit(
        client,
        key='123e4567-e89b-12d3-a456-426614174001',
    )

    assert response.status_code == 429
    assert response.get_json()['code'] == 'APPLICATION_RATE_LIMITED'
    assert set(response.get_json()) <= {'error', 'code', 'requestId'}


def test_enterprise_fingerprint_ignores_route_level_forwarded_for_spoofing(saas_app):
    app, _tokens = saas_app
    client = app.test_client()

    assert submit(client, forwarded_for='198.51.100.1', remote_addr='203.0.113.30').status_code == 201
    response = submit(
        client,
        key='123e4567-e89b-12d3-a456-426614174002',
        forwarded_for='198.51.100.200',
        remote_addr='203.0.113.30',
    )

    assert response.status_code == 429
    assert response.get_json()['code'] == 'APPLICATION_RATE_LIMITED'


def test_atomic_cooldown_allows_at_most_one_concurrent_different_key_submission(tmp_path):
    app = _file_backed_public_app(tmp_path)
    with app.app_context():
        engine = db.engine
    precheck = threading.Barrier(2)

    def synchronize_legacy_check(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = ' '.join(statement.split())
        if (
            'WHERE enterprise_service_applications.fingerprint_hash =' in normalized
            and 'enterprise_service_applications.created_at >=' in normalized
        ):
            precheck.wait(timeout=10)

    event.listen(engine, 'before_cursor_execute', synchronize_legacy_check)
    try:
        responses = _concurrent_submissions(app, [
            '123e4567-e89b-12d3-a456-426614174010',
            '123e4567-e89b-12d3-a456-426614174011',
        ])
    finally:
        event.remove(engine, 'before_cursor_execute', synchronize_legacy_check)

    assert sorted(response.status_code for response in responses) == [201, 429]
    assert [response.get_json()['code'] for response in responses if response.status_code == 429] == [
        'APPLICATION_RATE_LIMITED'
    ]
    with app.app_context():
        assert EnterpriseServiceApplication.query.count() == 1


def test_atomic_cooldown_keeps_concurrent_same_key_idempotent(tmp_path):
    app = _file_backed_public_app(tmp_path)
    responses = _concurrent_submissions(app, [
        '123e4567-e89b-12d3-a456-426614174012',
        '123e4567-e89b-12d3-a456-426614174012',
    ])

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].get_json()['applicationNo'] == responses[1].get_json()['applicationNo']
    with app.app_context():
        assert EnterpriseServiceApplication.query.count() == 1


def test_public_source_is_server_derived_and_cannot_be_spoofed(saas_app):
    app, _tokens = saas_app

    rejected = submit(app.test_client(), payload={**VALID_PAYLOAD, 'source': 'login_home'})
    accepted = submit(
        app.test_client(),
        key='123e4567-e89b-12d3-a456-426614174003',
        remote_addr='203.0.113.31',
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    with app.app_context():
        row = EnterpriseServiceApplication.query.filter_by(
            application_no=accepted.get_json()['applicationNo'],
        ).one()
        assert row.source == 'enterprise_application'


def test_client_request_metadata_is_pseudonymized_in_response_database_and_access_log(saas_app, caplog):
    app, tokens = saas_app
    raw_request_id = '13800138000-lin@example.com-sensitive-request'
    raw_forwarded = '198.51.100.88'
    caplog.set_level(logging.INFO, logger='hengpintong.app')

    created = submit(
        app.test_client(),
        request_id=raw_request_id,
        forwarded_for=raw_forwarded,
        remote_addr='203.0.113.40',
    )
    response_request_id = created.headers['X-Request-ID']

    assert created.status_code == 201
    assert raw_request_id not in created.get_data(as_text=True)
    assert raw_request_id != response_request_id
    assert 16 <= len(response_request_id) <= 64
    with app.app_context():
        row = EnterpriseServiceApplication.query.filter_by(
            application_no=created.get_json()['applicationNo'],
        ).one()
        assert row.request_id == response_request_id

    platform = _client(app, tokens['platform'])
    listing = platform.get('/api/platform/enterprise-applications?page=1&pageSize=20')
    application_id = listing.get_json()['items'][0]['id']
    updated = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': listing.get_json()['items'][0]['version']},
        headers={'X-Request-ID': raw_request_id},
    )
    assert updated.status_code == 200
    with app.app_context():
        audit = PlatformOperationLog.query.filter_by(
            action='update_enterprise_application',
            target_id=application_id,
        ).one()
        assert audit.request_id == updated.headers['X-Request-ID']
        assert raw_request_id not in json.dumps(audit.to_dict(), ensure_ascii=False)

    formatted = '\n'.join(JsonFormatter().format(record) for record in caplog.records)
    for sensitive in (raw_request_id, raw_forwarded, '13800138000', 'lin@example.com'):
        assert sensitive not in formatted


def test_json_exception_logging_redacts_contact_metadata():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name='test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='failed for lin@example.com at 13800138000 from 198.51.100.88',
        args=(),
        exc_info=None,
    )
    record.payload = {'email': 'lin@example.com', 'mobile': '13800138000'}

    serialized = formatter.format(record)

    assert 'lin@example.com' not in serialized
    assert '13800138000' not in serialized
    assert '198.51.100.88' not in serialized


def test_json_logging_redacts_sensitive_values_by_key_even_when_they_do_not_match_pii_patterns():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name='test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='enterprise application failed',
        args=(),
        exc_info=None,
    )
    record.payload = {
        'idempotencyKey': 'opaque-client-retry-token',
        'internalNote': 'commercially sensitive free-form note',
        'nested': {'rawRequestBody': 'arbitrary secret payload'},
    }
    record.authorization = 'Bearer top-level-secret-token'

    serialized = formatter.format(record)

    assert 'opaque-client-retry-token' not in serialized
    assert 'commercially sensitive free-form note' not in serialized
    assert 'arbitrary secret payload' not in serialized
    assert 'Bearer top-level-secret-token' not in serialized


def test_platform_permissions_summary_list_and_detail(saas_app):
    app, tokens = saas_app
    created = submit(app.test_client())
    application_no = created.get_json()['applicationNo']

    unauthenticated = app.test_client().get('/api/platform/enterprise-applications')
    tenant_user = _client(app, tokens['alpha']).get('/api/platform/enterprise-applications')
    platform = _client(app, tokens['platform'])
    summary = platform.get('/api/platform/enterprise-applications/summary')
    listing = platform.post('/api/platform/enterprise-applications/search', json={
        'status': 'new',
        'keyword': '星海',
        'page': 1,
        'pageSize': 20,
    })

    assert unauthenticated.status_code in (401, 403)
    assert tenant_user.status_code == 403
    assert summary.status_code == 200
    assert summary.get_json() == {
        'todayNew': 1,
        'new': 1,
        'contacting': 0,
        'qualified': 0,
        'closed': 0,
        'converted': 0,
    }
    assert listing.status_code == 200
    payload = listing.get_json()
    assert payload['page'] == 1
    assert payload['pageSize'] == 20
    assert payload['total'] == 1
    assert payload['totalPages'] == 1
    assert payload['items'][0]['applicationNo'] == application_no
    assert not ({'contactName', 'mobile', 'email', 'notes', 'internalNote'} & set(payload['items'][0]))

    sensitive_get = platform.get('/api/platform/enterprise-applications?keyword=13800138000')
    assert sensitive_get.status_code == 400
    assert sensitive_get.get_json()['code'] == 'APPLICATION_SEARCH_BODY_REQUIRED'

    detail = platform.get(f"/api/platform/enterprise-applications/{payload['items'][0]['id']}")
    assert detail.status_code == 200
    assert detail.get_json()['mobile'] == '13800138000'
    assert detail.get_json()['email'] == 'lin@example.com'


def test_enterprise_application_list_clamps_extreme_page_numbers(saas_app):
    app, tokens = saas_app
    assert submit(app.test_client()).status_code == 201
    platform = _client(app, tokens['platform'])

    response = platform.get(
        '/api/platform/enterprise-applications'
        f"?page={'9' * 100}&pageSize=20"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['page'] == 100_000
    assert payload['items'] == []


def test_platform_tenant_listing_can_page_through_every_conversion_target(saas_app):
    app, tokens = saas_app
    with app.app_context():
        db.session.add_all([
            Tenant(
                id=f'conversion-target-{index:04d}',
                name=f'转换目标企业 {index:04d}',
                slug=f'conversion-target-{index:04d}',
                status='active',
            )
            for index in range(501)
        ])
        db.session.commit()
        expected_ids = {tenant_id for tenant_id, in db.session.query(Tenant.id).all()}

    platform = _client(app, tokens['platform'])
    first = platform.get('/api/platform/tenants?page=1&pageSize=500')
    second = platform.get('/api/platform/tenants?page=2&pageSize=500')

    assert first.status_code == 200
    assert second.status_code == 200
    first_ids = {row['id'] for row in first.get_json()}
    second_ids = {row['id'] for row in second.get_json()}
    assert len(first_ids) == 500
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == expected_ids


@pytest.mark.parametrize(
    'mutation',
    [
        {'status': 'inactive'},
        {'role': 'admin'},
        {'tenant': 'alpha'},
    ],
)
def test_stale_platform_token_is_denied_after_live_account_privilege_changes(saas_app, mutation):
    app, tokens = saas_app
    with app.app_context():
        user = db.session.get(User, 'platform-user')
        if 'status' in mutation:
            user.status = mutation['status']
        if 'role' in mutation:
            user.role = mutation['role']
        if mutation.get('tenant') == 'alpha':
            user.tenant_id = tokens['alpha_id']
        db.session.commit()

    response = _client(app, tokens['platform']).get('/api/platform/enterprise-applications/summary')

    assert response.status_code == 403


def test_old_non_platform_claim_cannot_gain_platform_access_from_database_role_change(saas_app):
    app, tokens = saas_app
    with app.app_context():
        user = db.session.get(User, 'alpha-admin')
        user.role = 'platform_admin'
        user.tenant_id = None
        db.session.commit()

    response = _client(app, tokens['alpha']).get('/api/platform/enterprise-applications/summary')

    assert response.status_code == 403


def test_platform_patch_enforces_fields_owner_and_state_machine(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post('/api/platform/enterprise-applications/search', json={'page': 1, 'pageSize': 20}).get_json()['items'][0]
    application_id = row['id']

    unknown = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'mobile': '13900000000', 'version': row['version']},
    )
    invalid_jump = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'converted', 'version': row['version']},
    )
    invalid_owner = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'ownerUserId': 'alpha-admin', 'version': row['version']},
    )
    contacting = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={
            'status': 'contacting',
            'ownerUserId': 'platform-user',
            'followUpAt': '2026-07-23T09:30:00Z',
            'internalNote': '已电话沟通，等待业务负责人确认。',
            'version': row['version'],
        },
        headers={'X-Request-ID': 'application-patch-test'},
    )
    qualified = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': contacting.get_json()['version']},
    )

    assert unknown.status_code == 400
    assert unknown.get_json()['code'] == 'APPLICATION_PAYLOAD_INVALID'
    assert invalid_jump.status_code == 409
    assert invalid_jump.get_json()['code'] == 'APPLICATION_STATUS_INVALID'
    assert invalid_owner.status_code == 400
    assert invalid_owner.get_json()['code'] == 'APPLICATION_OWNER_INVALID'
    assert contacting.status_code == 200
    assert contacting.get_json()['status'] == 'contacting'
    assert contacting.get_json()['ownerUserId'] == 'platform-user'
    assert qualified.status_code == 200
    assert qualified.get_json()['status'] == 'qualified'

    with app.app_context():
        logs = PlatformOperationLog.query.filter_by(
            action='update_enterprise_application',
            target_id=application_id,
        ).all()
        assert logs
        serialized = ' '.join(str(log.to_dict()) for log in logs)
        assert '13800138000' not in serialized
        assert 'lin@example.com' not in serialized
        assert '已电话沟通' not in serialized
        assert 'application-patch-test' not in serialized


def test_convert_only_links_an_existing_tenant_and_is_terminal(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post('/api/platform/enterprise-applications/search', json={'page': 1, 'pageSize': 20}).get_json()['items'][0]
    application_id = row['id']

    contacting = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': row['version']},
    )
    assert contacting.status_code == 200
    qualified = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': contacting.get_json()['version']},
    )
    assert qualified.status_code == 200

    with app.app_context():
        tenant_count_before = Tenant.query.count()

    missing_version = platform.post(
        f'/api/platform/enterprise-applications/{application_id}/convert',
        json={'tenantId': tokens['alpha_id']},
    )
    stale = platform.post(
        f'/api/platform/enterprise-applications/{application_id}/convert',
        json={'tenantId': tokens['alpha_id'], 'version': contacting.get_json()['version']},
    )
    missing_tenant = platform.post(
        f'/api/platform/enterprise-applications/{application_id}/convert',
        json={'tenantId': 'does-not-exist', 'version': qualified.get_json()['version']},
    )
    converted = platform.post(
        f'/api/platform/enterprise-applications/{application_id}/convert',
        json={'tenantId': tokens['alpha_id'], 'version': qualified.get_json()['version']},
    )
    terminal = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'closed', 'version': converted.get_json()['version']},
    )

    assert missing_version.status_code == 400
    assert missing_version.get_json()['code'] == 'APPLICATION_PAYLOAD_INVALID'
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'APPLICATION_CONFLICT'
    assert missing_tenant.status_code == 404
    assert missing_tenant.get_json()['code'] == 'APPLICATION_TENANT_NOT_FOUND'
    assert converted.status_code == 200
    assert converted.get_json()['status'] == 'converted'
    assert converted.get_json()['convertedTenantId'] == tokens['alpha_id']
    assert terminal.status_code == 409
    assert terminal.get_json()['code'] == 'APPLICATION_STATUS_INVALID'
    with app.app_context():
        assert Tenant.query.count() == tenant_count_before


def test_detail_timeline_comes_from_persisted_status_audit_without_fake_note_events(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post('/api/platform/enterprise-applications/search', json={'page': 1, 'pageSize': 20}).get_json()['items'][0]
    application_id = row['id']

    contacting = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': row['version']},
    )
    assert contacting.status_code == 200
    note_updated = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={
            'internalNote': '只改备注，不应伪造状态时间',
            'version': contacting.get_json()['version'],
        },
    )
    assert note_updated.status_code == 200
    assert platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': note_updated.get_json()['version']},
    ).status_code == 200

    detail = platform.get(f'/api/platform/enterprise-applications/{application_id}').get_json()
    timeline = detail['timeline']

    assert [item['status'] for item in timeline] == ['new', 'contacting', 'qualified']
    assert all(item['at'].endswith('Z') for item in timeline)
    assert [item['at'] for item in timeline] == sorted(item['at'] for item in timeline)
    assert '只改备注' not in json.dumps(timeline, ensure_ascii=False)


def test_enterprise_application_times_are_explicit_utc_and_shanghai_day_starts_at_16_utc(saas_app, monkeypatch):
    from routes import enterprise_applications as module

    fixed_now = datetime(2026, 7, 22, 1, 0, tzinfo=timezone.utc)
    assert module._shanghai_business_day_start_utc(fixed_now) == datetime(2026, 7, 21, 16, 0)

    app, tokens = saas_app
    submit(app.test_client())
    with app.app_context():
        row = EnterpriseServiceApplication.query.one()
        row.created_at = datetime(2026, 7, 21, 16, 0)
        row.consent_at = datetime(2026, 7, 21, 16, 0)
        db.session.commit()
    monkeypatch.setattr(module, '_utc_now', lambda: fixed_now)
    platform = _client(app, tokens['platform'])

    summary = platform.get('/api/platform/enterprise-applications/summary')
    listing = platform.post('/api/platform/enterprise-applications/search', json={'page': 1, 'pageSize': 20})
    detail = platform.get(f"/api/platform/enterprise-applications/{listing.get_json()['items'][0]['id']}")

    assert summary.get_json()['todayNew'] == 1
    for field in ('createdAt', 'updatedAt', 'consentAt'):
        value = detail.get_json().get(field)
        if value:
            assert value.endswith('Z')


def test_follow_up_time_requires_an_explicit_utc_offset(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.get(
        '/api/platform/enterprise-applications?page=1&pageSize=20'
    ).get_json()['items'][0]
    application_id = row['id']

    response = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'followUpAt': '2026-07-23T09:30:00', 'version': row['version']},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'APPLICATION_PAYLOAD_INVALID'


def test_route_requires_seen_version_and_rejects_sequential_stale_update(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post(
        '/api/platform/enterprise-applications/search',
        json={'page': 1, 'pageSize': 20},
    ).get_json()['items'][0]
    application_id = row['id']
    seen_version = row['version']

    missing = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting'},
    )
    first = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': seen_version},
    )
    stale = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': seen_version},
    )

    assert missing.status_code == 400
    assert missing.get_json()['code'] == 'APPLICATION_PAYLOAD_INVALID'
    assert first.status_code == 200
    assert first.get_json()['version'] == seen_version + 1
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'APPLICATION_CONFLICT'
    detail = platform.get(
        f'/api/platform/enterprise-applications/{application_id}'
    ).get_json()
    assert detail['status'] == 'contacting'


def test_optimistic_version_rejects_real_two_session_lost_update_and_rolls_back_losing_audit(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post(
        '/api/platform/enterprise-applications/search',
        json={'page': 1, 'pageSize': 20},
    ).get_json()['items'][0]
    application_id = row['id']
    contacting = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': row['version']},
    )
    assert contacting.status_code == 200
    assert platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': contacting.get_json()['version']},
    ).status_code == 200

    with app.app_context():
        SessionFactory = sessionmaker(bind=db.engine, expire_on_commit=False)
        first = SessionFactory()
        second = SessionFactory()
        try:
            closed = first.get(EnterpriseServiceApplication, application_id)
            converted = second.get(EnterpriseServiceApplication, application_id)
            closed.status = 'closed'
            first.add(PlatformOperationLog(
                id='winner-audit', user_id='platform-user', action='update_enterprise_application',
                target_type='enterprise_service_application', target_id=application_id,
                result='success', detail={'fromStatus': 'qualified', 'toStatus': 'closed'},
            ))
            first.commit()

            converted.status = 'converted'
            converted.converted_tenant_id = tokens['alpha_id']
            second.add(PlatformOperationLog(
                id='loser-audit', user_id='platform-user', action='convert_enterprise_application',
                target_type='enterprise_service_application', target_id=application_id,
                result='success', detail={'fromStatus': 'qualified', 'toStatus': 'converted'},
            ))
            with pytest.raises(StaleDataError):
                second.commit()
            second.rollback()
        finally:
            first.close()
            second.close()

        persisted = db.session.get(EnterpriseServiceApplication, application_id)
        assert persisted.status == 'closed'
        assert persisted.converted_tenant_id is None
        assert db.session.get(PlatformOperationLog, 'winner-audit') is not None
        assert db.session.get(PlatformOperationLog, 'loser-audit') is None


def test_route_returns_stable_conflict_when_optimistic_commit_loses(saas_app):
    app, tokens = saas_app
    submit(app.test_client())
    platform = _client(app, tokens['platform'])
    row = platform.post(
        '/api/platform/enterprise-applications/search',
        json={'page': 1, 'pageSize': 20},
    ).get_json()['items'][0]
    application_id = row['id']

    def raise_stale(_session, _flush_context, _instances):
        if any(isinstance(item, EnterpriseServiceApplication) for item in _session.dirty):
            raise StaleDataError('forced concurrent application update')

    event.listen(Session, 'before_flush', raise_stale)
    try:
        response = platform.patch(
            f'/api/platform/enterprise-applications/{application_id}',
            json={'status': 'contacting', 'version': row['version']},
        )
    finally:
        event.remove(Session, 'before_flush', raise_stale)

    assert response.status_code == 409
    assert response.get_json()['code'] == 'APPLICATION_CONFLICT'
    with app.app_context():
        assert PlatformOperationLog.query.filter_by(
            action='update_enterprise_application',
            target_id=application_id,
        ).count() == 0


def test_success_responses_execute_no_sql_after_the_mutation_commit(saas_app):
    app, tokens = saas_app
    with app.app_context():
        engine = db.engine

    def request_without_post_commit_sql(call):
        committed = False

        def mark_committed(_session):
            nonlocal committed
            committed = True

        def reject_post_commit_sql(*_args, **_kwargs):
            if committed:
                raise RuntimeError('post-commit SQL is forbidden for mutation responses')

        event.listen(Session, 'after_commit', mark_committed)
        event.listen(engine, 'before_cursor_execute', reject_post_commit_sql)
        try:
            return call()
        finally:
            event.remove(engine, 'before_cursor_execute', reject_post_commit_sql)
            event.remove(Session, 'after_commit', mark_committed)

    created = request_without_post_commit_sql(lambda: submit(app.test_client()))
    assert created.status_code == 201

    platform = _client(app, tokens['platform'])
    row = platform.post(
        '/api/platform/enterprise-applications/search',
        json={'page': 1, 'pageSize': 20},
    ).get_json()['items'][0]
    application_id = row['id']
    updated = request_without_post_commit_sql(lambda: platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'contacting', 'version': row['version']},
    ))
    assert updated.status_code == 200

    qualified = platform.patch(
        f'/api/platform/enterprise-applications/{application_id}',
        json={'status': 'qualified', 'version': updated.get_json()['version']},
    )
    assert qualified.status_code == 200
    converted = request_without_post_commit_sql(lambda: platform.post(
        f'/api/platform/enterprise-applications/{application_id}/convert',
        json={'tenantId': tokens['alpha_id'], 'version': qualified.get_json()['version']},
    ))
    assert converted.status_code == 200


def test_application_schema_migration_is_repeatable_without_create_all_help(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        db.session.execute(text('DROP TABLE IF EXISTS enterprise_service_applications'))
        db.session.commit()

        ensure_schema()
        ensure_schema()

        inspector = inspect(db.engine)
        assert 'enterprise_service_applications' in inspector.get_table_names()
        columns = {column['name'] for column in inspector.get_columns('enterprise_service_applications')}
        assert {
            'id', 'application_no', 'company_name', 'contact_name', 'mobile', 'email',
            'status', 'owner_user_id', 'converted_tenant_id', 'idempotency_key',
            'fingerprint_hash', 'consent_at', 'created_at', 'updated_at',
        } <= columns
        unique_indexes = {
            tuple(index['column_names'])
            for index in inspector.get_indexes('enterprise_service_applications')
            if index.get('unique')
        }
        assert ('idempotency_key',) in unique_indexes


def test_sqlite_additive_migration_rebuilds_old_application_table_with_foreign_keys_and_preserves_rows(saas_app):
    app, tokens = saas_app
    with app.app_context():
        db.session.execute(text('DROP TABLE IF EXISTS enterprise_application_submission_guards'))
        db.session.execute(text('DROP TABLE IF EXISTS enterprise_service_applications'))
        db.session.execute(text('''
            CREATE TABLE enterprise_service_applications (
                id TEXT NOT NULL PRIMARY KEY,
                application_no TEXT NOT NULL,
                company_name TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                email TEXT,
                region TEXT,
                employee_scale TEXT,
                interested_modules JSON,
                preferred_contact_time TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                owner_user_id TEXT,
                follow_up_at DATETIME,
                internal_note TEXT,
                converted_tenant_id TEXT,
                source TEXT NOT NULL DEFAULT 'enterprise_application',
                request_id TEXT,
                idempotency_key TEXT NOT NULL,
                fingerprint_hash TEXT NOT NULL,
                consent_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME
            )
        '''))
        db.session.execute(text('''
            CREATE INDEX idx_enterprise_application_status_created
            ON enterprise_service_applications (status)
        '''))
        db.session.execute(text('''
            INSERT INTO enterprise_service_applications (
                id, application_no, company_name, contact_name, mobile, status,
                owner_user_id, converted_tenant_id, source, request_id,
                idempotency_key, fingerprint_hash, consent_at, created_at
            ) VALUES (
                'legacy-application', 'ESA-LEGACY', '保留企业', '保留联系人',
                '13800138000', 'converted', 'platform-user', :tenant_id,
                'enterprise_application', 'legacy-request', 'legacy-key',
                'legacy-fingerprint', '2026-07-20 00:00:00', '2026-07-20 00:00:00'
            )
        '''), {'tenant_id': tokens['alpha_id']})
        db.session.commit()

        ensure_schema()
        ensure_schema()

        inspector = inspect(db.engine)
        columns = {column['name'] for column in inspector.get_columns('enterprise_service_applications')}
        assert 'version' in columns
        foreign_keys = {
            (tuple(item['constrained_columns']), item['referred_table'], item['options'].get('ondelete'))
            for item in inspector.get_foreign_keys('enterprise_service_applications')
        }
        assert (('owner_user_id',), 'users', 'SET NULL') in foreign_keys
        assert (('converted_tenant_id',), 'tenants', 'SET NULL') in foreign_keys
        indexes = {item['name']: item for item in inspector.get_indexes('enterprise_service_applications')}
        assert indexes['idx_enterprise_application_status_created']['column_names'] == ['status', 'created_at']
        assert 'enterprise_application_submission_guards' in inspector.get_table_names()
        guard_columns = {
            column['name']
            for column in inspector.get_columns('enterprise_application_submission_guards')
        }
        assert {
            'fingerprint_hash', 'active_idempotency_hash', 'application_id',
            'claim_token', 'cooldown_until', 'updated_at',
        } <= guard_columns
        guard_foreign_keys = inspector.get_foreign_keys('enterprise_application_submission_guards')
        assert any(
            item['constrained_columns'] == ['application_id']
            and item['referred_table'] == 'enterprise_service_applications'
            and item['options'].get('ondelete') == 'SET NULL'
            for item in guard_foreign_keys
        )

        preserved = db.session.execute(text('''
            SELECT company_name, owner_user_id, converted_tenant_id, version,
                idempotency_key, request_id
            FROM enterprise_service_applications WHERE id = 'legacy-application'
        ''')).one()
        assert preserved[:4] == ('保留企业', 'platform-user', tokens['alpha_id'], 1)
        assert preserved[4].startswith('idem_')
        assert preserved[5].startswith('rid_')
        assert 'legacy-key' not in preserved[4]
        assert 'legacy-request' not in preserved[5]


def test_sqlite_application_rebuild_backfills_missing_status_and_source_columns(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        db.session.execute(text('DROP TABLE IF EXISTS enterprise_application_submission_guards'))
        db.session.execute(text('DROP TABLE IF EXISTS enterprise_service_applications'))
        db.session.execute(text('''
            CREATE TABLE enterprise_service_applications (
                id TEXT NOT NULL PRIMARY KEY,
                application_no TEXT NOT NULL,
                company_name TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                fingerprint_hash TEXT NOT NULL,
                consent_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL
            )
        '''))
        db.session.execute(text('''
            INSERT INTO enterprise_service_applications (
                id, application_no, company_name, contact_name, mobile,
                idempotency_key, fingerprint_hash, consent_at, created_at
            ) VALUES (
                'minimal-legacy-application', 'ESA-MINIMAL', '旧版企业', '旧联系人',
                '13800138000', 'legacy-minimal-key', 'legacy-minimal-fingerprint',
                '2026-07-20 00:00:00', '2026-07-20 00:00:00'
            )
        '''))
        db.session.commit()

        ensure_schema()

        row = db.session.execute(text('''
            SELECT status, source
            FROM enterprise_service_applications
            WHERE id = 'minimal-legacy-application'
        ''')).one()
        assert row == ('new', 'enterprise_application')
