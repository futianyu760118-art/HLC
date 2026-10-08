"""API tests for Skill-first route trace and failure-sample debugging."""

from __future__ import annotations

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
import pytest

from models import User, db
from routes.hrm import hrm_bp


@pytest.fixture()
def hrm_client(tmp_path, monkeypatch):
    from services.assistant_core.skill_first import failure_samples, observability

    route_file = tmp_path / 'skill-first-routes.jsonl'
    failure_file = tmp_path / 'skill-first-failure-samples.jsonl'
    monkeypatch.setattr(observability, '_ROUTE_TRACE_FILE', route_file)
    monkeypatch.setattr(failure_samples, '_FAILURE_FILE', failure_file)

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
        admin = User(
            id='admin-1',
            email='admin@example.com',
            password_hash='x',
            name='管理员',
            role='admin',
            status='active',
        )
        employee = User(
            id='employee-1',
            email='employee@example.com',
            password_hash='x',
            name='员工',
            role='employee',
            status='active',
        )
        db.session.add_all([admin, employee])
        db.session.commit()
        tokens = {
            'admin': create_access_token(identity=admin.id),
            'employee': create_access_token(identity=employee.id),
        }

    yield app.test_client(), app, tokens, observability, failure_samples

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _trace_payload(**overrides):
    payload = {
        'request_id': 'trace-1',
        'user_text': '工资这块有没有啥异常',
        'normalized_query': '工资这块有没有啥异常 工资 薪资 薪酬 发薪 工资条 钱 异常 风险 问题 不正常',
        'top_k_skills': ['payroll.anomaly', 'payroll.summary'],
        'candidate_scores': [{'skill_id': 'payroll.anomaly', 'score': 12.3}],
        'matched_examples': {'payroll.anomaly': ['工资这块有没有啥异常']},
        'selected_skill': 'payroll.anomaly',
        'rejected_skills': [{'skill_id': 'payroll.summary', 'reason': 'lower_score'}],
        'slot_fill_result': {'slot_values': {'question': '工资这块有没有啥异常'}, 'missing_slots': []},
        'confidence': 0.91,
        'route_reason': 'semantic_card_rerank:test',
        'permission_result': 'allowed',
        'risk_result': {'risk_level': 'high', 'side_effect': False},
        'confirmation_policy': 'not_required_for_read_only',
        'fallback_reason': None,
        'latency_ms': 12.5,
        'final_executor': 'ToolExecutor(payroll_analysis)',
        'output_verification_result': 'ok',
    }
    payload.update(overrides)
    return payload


def test_skill_first_route_traces_api_is_admin_only(hrm_client):
    client, _app, tokens, observability, _failure_samples = hrm_client
    observability.append_route_trace(_trace_payload())

    forbidden = client.get(
        '/api/hrm/assistant/skill-first/route-traces',
        headers=auth_header(tokens['employee']),
    )
    assert forbidden.status_code == 403

    response = client.get(
        '/api/hrm/assistant/skill-first/route-traces?selectedSkill=payroll.anomaly',
        headers=auth_header(tokens['admin']),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 1
    assert body['items'][0]['request_id'] == 'trace-1'
    assert body['items'][0]['candidate_scores'][0]['skill_id'] == 'payroll.anomaly'
    assert body['source'].endswith('skill-first-routes.jsonl')


def test_skill_first_failure_samples_api_lists_learning_loop_inputs(hrm_client):
    client, _app, tokens, _observability, failure_samples = hrm_client
    failure_samples.append_failure_sample('low_confidence', _trace_payload(
        request_id='failure-1',
        user_text='钱这块哪儿怪怪的',
        fallback_reason='low_confidence',
        confidence=0.41,
    ))

    response = client.get(
        '/api/hrm/assistant/skill-first/failure-samples?kind=low_confidence',
        headers=auth_header(tokens['admin']),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 1
    assert body['items'][0]['request_id'] == 'failure-1'
    assert body['items'][0]['kind'] == 'low_confidence'
    assert body['items'][0]['candidate_scores'][0]['skill_id'] == 'payroll.anomaly'
    assert body['items'][0]['matched_examples']['payroll.anomaly'] == ['工资这块有没有啥异常']
    assert body['items'][0]['output_verification_result'] == 'ok'
    assert 'generate-skill-card-eval-patch.mjs' in body['evalPatchCommand']


def test_skill_first_route_trace_replay_is_plan_only(hrm_client, monkeypatch):
    client, _app, tokens, observability, _failure_samples = hrm_client
    observability.append_route_trace(_trace_payload(request_id='replay-1'))

    def fail_execute(*args, **kwargs):
        raise AssertionError('route replay must not execute business tools')

    monkeypatch.setattr(
        'services.assistant_core.executors.tool_executor.ToolExecutor.execute',
        fail_execute,
    )

    response = client.get(
        '/api/hrm/assistant/skill-first/route-traces/replay-1/replay',
        headers=auth_header(tokens['admin']),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['sourceRequestId'] == 'replay-1'
    assert body['mode'] == 'plan_only_no_tool_execution'
    assert body['original']['selectedSkill'] == 'payroll.anomaly'
    assert body['replay']['selectedSkill'] == 'payroll.anomaly'
    assert body['changed'] is False
    assert body['topKSkills'][0]['skill_id'] == 'payroll.anomaly'
