import hashlib
import hmac
import json
import os
import time

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    AssistantSession,
    Employee,
    EmployeePortalAccount,
    OnboardingTask,
    Tenant,
    User,
    db,
)
from app import _register_password_change_gate
from routes.portal import portal_bp
from routes.person_lifecycle import PersonLifecycleChecklist, PersonLifecycleEvent, person_lifecycle_bp
import routes.person_lifecycle as person_lifecycle_route


SECRET = 'hlc-person-lifecycle-test-secret'


def lifecycle_event(event_id='evt-offboard-1', event_type='person.offboarded', revision=1,
                    employment_action='offboard', status='inactive'):
    return {
        'event_id': event_id,
        'event_type': event_type,
        'event_version': 1,
        'tenant_id': 'tenant-hengjian',
        'source_system': 'M01_KERNEL',
        'object_type': 'Person',
        'object_id': 'emp-1',
        'revision': revision,
        'occurred_at': '2026-11-03T02:00:00Z',
        'effective_at': '2026-11-03T02:00:00Z',
        'correlation_id': event_id,
        'trace_id': event_id,
        'idempotency_key': f'tenant-hengjian:M01_KERNEL:Person:emp-1:{revision}:{event_type}',
        'person': {'person_id': 'emp-1', 'emp_code': 'E001'},
        'status': status,
        'employment_action': employment_action,
        'occurred_by': '朱剑军',
    }


def signed_headers(body):
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return {
        'Content-Type': 'application/json',
        'X-AEOS-Key-Id': 'm01-kernel',
        'X-AEOS-Timestamp': timestamp,
        'X-AEOS-Signature': signature,
    }


@pytest.fixture()
def lifecycle_app(tmp_path, monkeypatch):
    monkeypatch.setenv('AEOS_PERSON_LIFECYCLE_SECRET', SECRET)
    monkeypatch.setenv('AEOS_PERSON_LIFECYCLE_KEY_ID', 'm01-kernel')
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(tmp_path / 'uploads'),
    )
    db.init_app(app)
    app.config['JWT_SECRET_KEY'] = 'test-jwt-secret'
    JWTManager(app)
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    app.register_blueprint(person_lifecycle_bp)
    _register_password_change_gate(app)
    with app.app_context():
        db.create_all()
        tenant = Tenant(id='tenant-hengjian', name='恒剑光电', slug='hengjian', status='active')
        employee = Employee(
            id='emp-1', tenant_id=tenant.id, employee_no='E001', name='宓曙',
            email='mishu@example.com', status='active', source_system='M01',
        )
        user = User(
            id='user-1', tenant_id=tenant.id, email='mishu@example.com',
            password_hash='x', name='宓曙', status='active', employee_id=employee.id,
        )
        account = EmployeePortalAccount(
            id='portal-1', employee_id=employee.id, tenant_id=tenant.id,
            password_hash='x', status='active', must_change_password=False,
        )
        task = OnboardingTask(
            id='task-1', tenant_id=tenant.id, employee_id=employee.id,
            owner_id=user.id, name='归还电脑', status='in_progress',
        )
        session = AssistantSession(
            id='session-1', tenant_id=tenant.id, user_id=user.id,
            title='工作助手', messages=[], is_active=True,
        )
        db.session.add_all([tenant, employee, user, account, task, session])
        db.session.commit()
    yield app
    with app.app_context():
        db.drop_all()


def post_event(app, event):
    return app.test_client().post(
        '/internal/aeos/person-lifecycle',
        data=json.dumps(event, ensure_ascii=False, separators=(',', ':')),
        headers=signed_headers(event),
    )


def test_offboard_closes_access_and_creates_full_recovery_checklist(lifecycle_app):
    response = post_event(lifecycle_app, lifecycle_event())

    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'synced'
    assert set(body['closed_items']) == {'personnel_service', 'asset', 'device', 'agent_equipment'}
    with lifecycle_app.app_context():
        employee = db.session.get(Employee, 'emp-1')
        user = db.session.get(User, 'user-1')
        account = db.session.get(EmployeePortalAccount, 'portal-1')
        task = db.session.get(OnboardingTask, 'task-1')
        session = db.session.get(AssistantSession, 'session-1')
        assert employee.status == 'inactive'
        assert user.status == 'inactive'
        assert account.status == 'inactive'
        assert task.status == 'reassignment_required' and task.owner_id is None
        assert session.is_active is False
        assert PersonLifecycleChecklist.query.count() == 4


def test_reinstate_restores_basic_login_but_waits_for_permission_and_agent_confirmation(lifecycle_app):
    assert post_event(lifecycle_app, lifecycle_event()).status_code == 200
    response = post_event(lifecycle_app, lifecycle_event(
        event_id='evt-reinstate-1', event_type='person.reinstated', revision=2,
        employment_action='rehire', status='active',
    ))

    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'pending_confirmation'
    assert body['pending_confirmation'] == {'permissions': True, 'agents': True}
    with lifecycle_app.app_context():
        assert db.session.get(Employee, 'emp-1').status == 'active'
        assert db.session.get(User, 'user-1').status == 'active'
        assert db.session.get(EmployeePortalAccount, 'portal-1').status == 'active'
        assert PersonLifecycleChecklist.query.filter_by(status='pending_confirmation').count() == 2


def test_replayed_event_does_not_duplicate_history_or_checklist(lifecycle_app):
    event = lifecycle_event()
    first = post_event(lifecycle_app, event)
    replay = post_event(lifecycle_app, event)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.get_json()['duplicate'] is True
    with lifecycle_app.app_context():
        assert PersonLifecycleEvent.query.count() == 1
        assert PersonLifecycleChecklist.query.count() == 4


def test_existing_portal_token_is_rejected_after_offboard(lifecycle_app):
    assert post_event(lifecycle_app, lifecycle_event()).status_code == 200
    with lifecycle_app.app_context():
        token = create_access_token(
            'portal-1', additional_claims={'account_type': 'employee_portal', 'role': 'employee'},
        )
    response = lifecycle_app.test_client().get(
        '/api/portal/me', headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 401


def test_m07_submits_person_change_to_m01_with_plain_person_details(lifecycle_app, monkeypatch):
    captured = {}

    def fake_submit(payload):
        captured.update(payload)
        return {'status': 'pending_confirmation', 'request_id': 'PCR-1'}, 200

    monkeypatch.setattr(person_lifecycle_route, '_submit_m01_person_change', fake_submit)
    with lifecycle_app.app_context():
        token = create_access_token('user-1')
    response = lifecycle_app.test_client().post(
        '/api/hrm/person-change-requests',
        json={
            'person_id': 'emp-1',
            'action': 'offboard',
            'department_id': 'dept-rd',
            'position_id': 'pos-engineer',
            'job_title': '电子工程师',
            'effective_at': '2026-11-03T09:00:00+08:00',
            'reason': '员工离职',
            'idempotency_key': 'tenant-hengjian:emp-1:offboard:20261103',
        },
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    assert captured == {
        'type': 'person.change.request',
        'tenant_id': 'tenant-hengjian',
        'requester_id': 'emp-1',
        'person_id': 'emp-1',
        'action': 'offboard',
        'department_id': 'dept-rd',
        'position_id': 'pos-engineer',
        'job_title': '电子工程师',
        'effective_at': '2026-11-03T09:00:00+08:00',
        'reason': '员工离职',
        'idempotency_key': 'tenant-hengjian:emp-1:offboard:20261103',
    }
