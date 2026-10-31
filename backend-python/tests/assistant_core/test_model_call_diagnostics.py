import json
from types import SimpleNamespace

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import AssistantAuditLog, AssistantEvaluationRun, Tenant, User, db
from routes.hrm import hrm_bp
from routes.platform import platform_bp


@pytest.fixture()
def hrm_client(monkeypatch):
    monkeypatch.setattr('services.assistant_core.llm_client.API_KEY', '')
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
    app.register_blueprint(platform_bp, url_prefix='/api/platform')

    with app.app_context():
        db.create_all()
        tenant = Tenant(
            id='tenant-eval-1',
            name='评估测试企业',
            slug='HPT-EVAL-0001',
            status='active',
            plan_code='enterprise',
            max_users=50,
            max_employees=100,
            max_storage_mb=1024,
            ai_monthly_quota=100,
        )
        admin = User(
            id='admin-1',
            tenant_id=tenant.id,
            email='admin@example.com',
            password_hash='x',
            name='管理员',
            role='admin',
            status='active',
        )
        employee = User(
            id='employee-1',
            tenant_id=tenant.id,
            email='employee@example.com',
            password_hash='x',
            name='员工',
            role='employee',
            status='active',
        )
        platform = User(
            id='platform-1',
            email='platform@example.com',
            password_hash='x',
            name='平台管理员',
            role='platform_admin',
            status='active',
        )
        db.session.add_all([tenant, admin, employee, platform])
        db.session.commit()
        tokens = {
            'admin': create_access_token(identity=admin.id),
            'employee': create_access_token(identity=employee.id),
            'platform': create_access_token(
                identity=platform.id,
                additional_claims={'is_platform_admin': True, 'tenant_id': tenant.id},
            ),
            'alpha_id': tenant.id,
        }

    yield app.test_client(), app, tokens

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_model_call_test_records_missing_key_audit_log(hrm_client):
    client, app, tokens = hrm_client

    response = client.post(
        '/api/platform/ai/diagnostics/model-call-test',
        json={
            'prompt': '【Copilot真实调用测试】请验证真实模型调用链路',
            'modelProfile': 'strong',
            'clientContext': {'path': '/ai-model-settings', 'moduleName': 'AI 模型管理'},
        },
        headers={**auth_header(tokens['platform']), 'X-Request-ID': 'diag-req-1'},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is False
    assert body['requestId'] == 'diag-req-1'
    assert body['useCase'] == 'model_call_test'

    with app.app_context():
        rows = AssistantAuditLog.query.filter_by(request_id='diag-req-1').all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == 'error'
        assert row.model_profile == 'strong'
        assert row.use_case == 'model_call_test'
        assert 'SILICONFLOW_API_KEY' in row.error_message
        assert 'Copilot真实调用测试' in str(row.prompt_messages)


def test_model_call_test_is_admin_only(hrm_client):
    client, _app, tokens = hrm_client

    response = client.post(
        '/api/hrm/assistant/model-call-test',
        json={'prompt': '测试'},
        headers=auth_header(tokens['employee']),
    )

    assert response.status_code == 403


def test_skill_first_llm_health_reset_is_admin_only_and_resets_state(hrm_client):
    client, _app, tokens = hrm_client
    from services.assistant_core.skill_first import llm_health

    llm_health.reset()
    llm_health.record_failure('skill_first_planner', {'status': 'timeout', 'model': 'fake-model'})
    assert llm_health.snapshot()['consecutive_failures'] == 1

    denied = client.post(
        '/api/hrm/assistant/skill-first/llm-health',
        json={},
        headers=auth_header(tokens['employee']),
    )
    assert denied.status_code == 403
    assert llm_health.snapshot()['consecutive_failures'] == 1

    response = client.post(
        '/api/hrm/assistant/skill-first/llm-health',
        json={},
        headers=auth_header(tokens['admin']),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is True
    assert body['reset'] is True
    assert body['health']['consecutive_failures'] == 0
    assert llm_health.snapshot()['consecutive_failures'] == 0


def test_evaluation_run_endpoint_persists_structural_record(hrm_client, monkeypatch):
    client, app, tokens = hrm_client

    def fake_query(**kwargs):
        return {
            'summary': '测试回答',
            'entities': [{'id': 'emp-1', 'type': 'employees', 'title': '张三'}],
            'widgets': [{'type': 'table', 'table': {'rows': []}}],
            'renderBlocks': [{'kind': 'markdown'}, {'kind': 'table'}],
            'copilot': {
                'evidence': [{'module': 'employees', 'recordId': 'emp-1', 'title': '张三'}],
                'evaluationHints': {'failureCategories': []},
            },
            'meta': {
                'usedSkills': ['employee_search'],
                'requiresConfirmation': False,
                'routeDecision': {'entities': {'timeRange': {'label': '最近'}}},
            },
            'sessionId': 'session-eval-1',
        }

    monkeypatch.setattr('services.assistant_core.copilot_orchestrator.query', fake_query)

    def fake_record_model_audit(case, response, assessment, *, user_id, request_id):
        with app.app_context():
            db.session.add(AssistantAuditLog(
                id='audit-eval-record-1',
                request_id=request_id,
                provider='siliconflow',
                model='deepseek-ai/DeepSeek-V4-Pro',
                model_profile='strong',
                use_case='copilot_evaluation',
                prompt_messages=[{'role': 'user', 'content': '评估'}],
                response_content='结构化评估通过',
                response_meta={'caseId': case.get('id')},
                status='success',
                latency_ms=1234,
                prompt_chars=10,
                response_chars=8,
            ))
            db.session.commit()
        return {
            'requestId': request_id,
            'useCase': 'copilot_evaluation',
            'provider': 'siliconflow',
            'modelProfile': 'strong',
            'model': 'deepseek-ai/DeepSeek-V4-Pro',
            'ok': True,
            'auditRecorded': True,
            'auditLogId': 'audit-eval-record-1',
            'status': 'success',
            'latencyMs': 1234,
            'promptChars': 10,
            'responseChars': 8,
            'error': None,
            'message': '结构化评估通过',
        }

    monkeypatch.setattr(
        'services.assistant_core.evaluation._record_evaluation_model_audit',
        fake_record_model_audit,
    )

    response = client.post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseId': 'attendance_employee_anomaly'},
        headers=auth_header(tokens['platform']),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['caseId'] == 'attendance_employee_anomaly'
    assert body['usedTools'] == ['employee_search']
    assert 'employees' in body['actualModules']
    assert body['evaluationAudit']['provider'] == 'siliconflow'
    assert body['evaluationAudit']['auditRecorded'] is True
    assert body['evaluationAudit']['auditLogId'] == 'audit-eval-record-1'
    assert body['evaluationAudit']['latencyMs'] == 1234
    assert body['evaluationAudit']['promptChars'] == 10
    assert body['evaluationAudit']['responseChars'] == 8

    with app.app_context():
        row = AssistantEvaluationRun.query.filter_by(id=body['id']).first()
        assert row is not None
        assert row.question == '吴明华最近考勤异常吗？请给证据'
        assert row.expected_modules
        assert row.actual_render_blocks
        stored = row.to_dict()
        assert stored['evaluationAudit']['provider'] == 'siliconflow'
        assert stored['evaluationAudit']['auditLogId'] == 'audit-eval-record-1'


def test_evaluation_run_endpoint_returns_400_for_unknown_case(hrm_client):
    client, _app, tokens = hrm_client

    response = client.post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseId': 'missing_case_id'},
        headers=auth_header(tokens['platform']),
    )

    assert response.status_code == 400
    assert '未知评估用例' in response.get_json()['error']


def test_evaluation_evidence_sources_are_deduped_with_field_payloads() -> None:
    from services.assistant_core.evaluation import assess_response

    source = {
        'module': 'employees',
        'recordType': 'employees',
        'recordId': 'emp-1',
        'title': '张三 档案',
        'fields': [{'key': 'employee.department', 'label': '部门', 'value': '研发部'}],
    }
    result = assess_response(
        {'id': 'field_source_case', 'expected_modules': ['employees'], 'expected_render_blocks': ['sources']},
        {
            'summary': 'ok',
            'widgets': [{'type': 'source_citations', 'sources': [source]}],
            'renderBlocks': [{'kind': 'sources'}],
            'copilot': {'evidence': [source]},
        },
    )

    assert result['actualModules'] == ['employees']
    assert len(result['evidenceSources']) == 1
    assert result['evidenceSources'][0]['fields'][0]['value'] == '研发部'


def test_chat_profile_can_disable_retry(monkeypatch):
    from services.assistant_core import llm_client

    captured = {}

    def fake_chat(messages, **kwargs):
        captured.update(kwargs)
        return {'content': 'ok'}

    monkeypatch.setattr(llm_client, 'chat', fake_chat)

    result = llm_client.chat_profile(
        'strong',
        [{'role': 'user', 'content': '评估测试'}],
        use_case='copilot_evaluation',
        retry_once=False,
    )

    assert result == {'content': 'ok'}
    assert captured['retry_once'] is False
    assert captured['model']


def test_evaluation_model_audit_uses_retryable_real_model_budget(hrm_client, monkeypatch):
    _client, app, _tokens = hrm_client
    from services.assistant_core import evaluation

    captured = {}

    def fake_chat_profile(profile, messages, **kwargs):
        captured.update({
            'profile': profile,
            'messages': messages,
            **kwargs,
        })
        with app.app_context():
            db.session.add(AssistantAuditLog(
                id='audit-eval-retry-budget-1',
                request_id='eval-retry-budget-1',
                provider='siliconflow',
                model='deepseek-ai/DeepSeek-V4-Pro',
                model_profile=profile,
                use_case=kwargs.get('use_case'),
                prompt_messages=messages,
                response_content='评估审计通过',
                response_meta={'attempt': 1},
                status='success',
                latency_ms=1234,
                prompt_chars=56,
                response_chars=7,
            ))
            db.session.commit()
        return {'content': '评估审计通过'}

    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', fake_chat_profile)
    monkeypatch.delenv('ASSISTANT_EVALUATION_AUDIT_TIMEOUT_SECONDS', raising=False)
    monkeypatch.delenv('ASSISTANT_EVALUATION_AUDIT_MAX_TOKENS', raising=False)
    monkeypatch.delenv('ASSISTANT_EVALUATION_AUDIT_RETRY_ONCE', raising=False)

    with app.app_context():
        result = evaluation._record_evaluation_model_audit(
            {
                'id': 'retry_budget_case',
                'scenario': '真实模型评估预算',
                'question': '测试评估审计调用预算',
                'expected_modules': ['employees'],
                'expected_render_blocks': ['markdown'],
            },
            {'summary': '本地执行结果', 'sessionId': None},
            {
                'actualModules': ['employees'],
                'actualRenderBlocks': ['markdown'],
                'usedTools': [],
                'passStatus': 'pass',
                'missingExpectations': [],
                'failureCategories': [],
                'rootCauseNotes': '',
                'fixPlan': '',
            },
            user_id='admin-1',
            request_id='eval-retry-budget-1',
        )

    assert result['ok'] is True
    assert result['status'] == 'success'
    assert result['provider'] == 'siliconflow'
    assert result['auditLogId'] == 'audit-eval-retry-budget-1'
    assert captured['profile'] == 'strong'
    assert captured['use_case'] == 'copilot_evaluation'
    assert captured['resource_domain'] == 'system_ai'
    assert captured['retry_once'] is True
    assert captured['timeout'] == 60
    assert captured['max_tokens'] == 500


def test_stream_chat_profile_parses_sse_and_records_audit(hrm_client, monkeypatch):
    _client, app, _tokens = hrm_client
    from services.assistant_core import llm_client
    from services.assistant_core.schemas import AssistantContext

    class FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_lines(self, decode_unicode=True):
            yield 'data: {"choices":[{"delta":{"content":"真实"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"流式"}}]}'
            yield 'data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}'
            yield 'data: [DONE]'

    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs.get('json')
        captured['stream'] = kwargs.get('stream')
        return FakeResponse()

    monkeypatch.setattr(llm_client, 'API_KEY', 'fake-key')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    ctx = AssistantContext(
        user_id='admin-1',
        role='admin',
        request_id='stream-unit-1',
        audit_user_id='admin-1',
    )

    with app.app_context():
        chunks = list(llm_client.stream_chat_profile(
            'strong',
            [{'role': 'user', 'content': '请测试真实流式'}],
            use_case='model_stream_test',
            ctx=ctx,
            retry_once=False,
        ))
        row = AssistantAuditLog.query.filter_by(request_id='stream-unit-1').one()

    assert chunks == ['真实', '流式']
    assert captured['stream'] is True
    assert captured['json']['stream'] is True
    assert row.status == 'success'
    assert row.use_case == 'model_stream_test'
    assert row.response_content == '真实流式'
    assert row.response_meta['stream'] is True
    assert row.response_meta['chunkCount'] == 2


def test_model_stream_test_endpoint_emits_delta_and_audit(hrm_client, monkeypatch):
    client, app, tokens = hrm_client

    def fake_stream_model_call_test(prompt, ctx, **kwargs):
        with app.app_context():
            db.session.add(AssistantAuditLog(
                id='audit-stream-route-1',
                request_id=ctx.request_id,
                provider='siliconflow',
                model='deepseek-ai/DeepSeek-V4-Pro',
                model_profile=kwargs.get('profile') or 'strong',
                use_case='model_stream_test',
                prompt_messages=[{'role': 'user', 'content': prompt}],
                response_content='路由流式成功',
                response_meta={'stream': True, 'chunkCount': 2},
                status='success',
                latency_ms=123,
                prompt_chars=len(prompt or ''),
                response_chars=6,
            ))
            db.session.commit()
        yield {'event': 'delta', 'content': '路由'}
        yield {'event': 'delta', 'content': '流式'}
        yield {
            'event': 'final',
            'payload': {
                'ok': True,
                'marker': 'Copilot流式调用测试-route',
                'requestId': ctx.request_id,
                'useCase': 'model_stream_test',
                'response': '路由流式成功',
            },
        }

    monkeypatch.setattr(
        'services.assistant_core.model_diagnostics.stream_model_call_test',
        fake_stream_model_call_test,
    )

    response = client.post(
        '/api/platform/ai/diagnostics/model-stream-test',
        json={
            'prompt': 'stream route test',
            'modelProfile': 'strong',
            'clientContext': {'path': '/ai-model-settings'},
        },
        headers={**auth_header(tokens['platform']), 'X-Request-ID': 'stream-route-1'},
    )

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'event: delta' in text
    assert '路由' in text
    assert 'event: final' in text
    assert 'model_stream_test' in text

    with app.app_context():
        row = AssistantAuditLog.query.filter_by(request_id='stream-route-1').one()
        assert row.response_meta['stream'] is True


def test_main_assistant_query_stream_emits_delta_updates_final_and_audit(hrm_client, monkeypatch):
    client, app, tokens = hrm_client

    def fake_assistant_query(question, user_id=None, session_id=None, request_id=None, client_context=None):
        assert question == '吴明华最近考勤异常吗？请给证据'
        assert request_id == 'assistant-main-stream-1'
        return {
            'summary': '原始结构化摘要',
            'answer': {'content': '原始结构化摘要', 'format': 'markdown'},
            'entities': [{'id': 'emp-wmh', 'type': 'employees', 'title': '吴明华'}],
            'widgets': [{'type': 'source_citations', 'sources': [
                {'module': 'attendance', 'recordId': 'att-1', 'title': '吴明华 2026-05 考勤'}
            ]}],
            'renderBlocks': [
                {'id': 'answer', 'kind': 'markdown', 'title': '结论', 'content': '原始结构化摘要', 'source': 'answer'},
                {'id': 'widget-1', 'kind': 'sources', 'widgetType': 'source_citations', 'source': 'widget'},
            ],
            'copilot': {
                'evidence': [{'module': 'attendance', 'recordId': 'att-1', 'title': '吴明华 2026-05 考勤'}],
                'plan': [{'id': 'load-attendance', 'label': 'attendance_anomaly_scan', 'status': 'ok'}],
            },
            'meta': {'usedSkills': ['attendance_anomaly_scan'], 'requiresConfirmation': False},
            'sessionId': 'session-main-stream-1',
        }

    def fake_stream_grounded_response(question, result_payload, *, user_id, session_id=None,
                                      request_id=None, client_context=None):
        assert question == '吴明华最近考勤异常吗？请给证据'
        assert session_id == 'session-main-stream-1'
        assert request_id == 'assistant-main-stream-1'
        with app.app_context():
            db.session.add(AssistantAuditLog(
                id='audit-assistant-main-stream-1',
                request_id=request_id,
                provider='siliconflow',
                model='deepseek-ai/DeepSeek-V4-Pro',
                model_profile='strong',
                use_case='assistant_stream_answer',
                prompt_messages=[{'role': 'user', 'content': question}],
                response_content='流式最终结论：吴明华存在考勤异常，证据来自考勤记录。',
                response_meta={'stream': True, 'chunkCount': 2},
                status='success',
                latency_ms=321,
                prompt_chars=20,
                response_chars=25,
            ))
            db.session.commit()
        yield '流式最终结论：'
        yield '吴明华存在考勤异常，证据来自考勤记录。'

    monkeypatch.setattr('services.assistant.assistant_query', fake_assistant_query)
    monkeypatch.setattr(
        'services.assistant.assistant_stream_grounded_response',
        fake_stream_grounded_response,
    )
    monkeypatch.setattr(
        'routes.hrm._require_ai_resource',
        lambda *_args, **_kwargs: SimpleNamespace(resource_domain='assistant'),
    )

    response = client.post(
        '/api/hrm/assistant/query',
        json={
            'question': '吴明华最近考勤异常吗？请给证据',
            'stream': True,
            'clientContext': {'path': '/attendance-stats', 'moduleName': '考勤统计'},
        },
        headers={**auth_header(tokens['admin']), 'X-Request-ID': 'assistant-main-stream-1'},
    )

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'event: delta' in text
    assert '流式最终结论' in text
    assert 'event: final' in text

    final_payload = None
    for event in text.split('\n\n'):
        if event.startswith('event: final'):
            data_line = next(line for line in event.splitlines() if line.startswith('data:'))
            final_payload = json.loads(data_line[5:].strip())
            break
    assert final_payload is not None
    assert final_payload['summary'].startswith('流式最终结论')
    assert final_payload['answer']['content'].startswith('流式最终结论')
    assert final_payload['renderBlocks'][0]['content'].startswith('流式最终结论')
    assert final_payload['copilot']['responseGeneration']['useCase'] == 'assistant_stream_answer'
    assert final_payload['entities'][0]['title'] == '吴明华'

    with app.app_context():
        row = AssistantAuditLog.query.filter_by(request_id='assistant-main-stream-1').one()
        assert row.provider == 'siliconflow'
        assert row.use_case == 'assistant_stream_answer'
        assert row.status == 'success'
        assert row.response_meta['stream'] is True


def test_confirmed_action_stream_uses_deterministic_receipt(hrm_client, monkeypatch):
    client, app, tokens = hrm_client
    del client, tokens
    from services.assistant_core import copilot_orchestrator

    def fail_stream_provider(*args, **kwargs):
        raise AssertionError('confirmed action receipts must not call the provider stream')

    monkeypatch.setattr('services.assistant_core.llm_client.stream_chat_profile', fail_stream_provider)

    with app.app_context():
        chunks = list(copilot_orchestrator.stream_grounded_response(
            user_id='admin-1',
            message='确认执行动作：act_salary',
            request_id='confirmed-receipt-1',
            result_payload={
                'summary': '已执行：提交调薪审批，成功 1/1 项。',
                'answer': {'content': '已执行：提交调薪审批，成功 1/1 项。', 'format': 'text'},
                'sessionId': 'confirmed-session-1',
                'meta': {
                    'routeTrack': 'CONFIRMED_ACTION',
                    'routeDecision': {
                        'routeTrack': 'CONFIRMED_ACTION',
                        'intent': 'execute_pending_action',
                    },
                },
                'copilot': {
                    'routeTrack': 'CONFIRMED_ACTION',
                    'intent': 'execute_pending_action',
                },
            },
        ))

        assert ''.join(chunks) == '已执行：提交调薪审批，成功 1/1 项。'
        row = AssistantAuditLog.query.filter_by(request_id='confirmed-receipt-1').one()
        assert row.provider == 'siliconflow'
        assert row.model == 'deterministic-confirmed-action-receipt'
        assert row.model_profile == 'system'
        assert row.use_case == 'assistant_stream_answer'
        assert row.status == 'success'
        assert row.response_meta['stream'] is True
        assert row.response_meta['deterministicReceipt'] is True
        assert row.response_meta['skippedProviderCall'] is True
        assert row.response_meta['chunkCount'] >= 1


def test_evaluation_model_audit_preserves_timeout_status(hrm_client, monkeypatch):
    client, app, tokens = hrm_client
    del client, tokens
    from services.assistant_core import evaluation

    def fake_chat_profile(profile, messages, **kwargs):
        with app.app_context():
            db.session.add(AssistantAuditLog(
                id='audit-timeout-1',
                request_id='eval-timeout-1',
                provider='siliconflow',
                model='deepseek-ai/DeepSeek-V4-Pro',
                model_profile=profile,
                use_case=kwargs.get('use_case'),
                prompt_messages=messages,
                response_content='',
                response_meta={'attempt': 0},
                status='timeout',
                error_message='request timeout',
                latency_ms=45000,
                prompt_chars=12,
                response_chars=0,
            ))
            db.session.commit()
        return None

    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', fake_chat_profile)

    with app.app_context():
        result = evaluation._record_evaluation_model_audit(
            {
                'id': 'timeout_case',
                'scenario': '真实模型超时归因',
                'question': '测试超时是否保留',
                'expected_modules': ['employees'],
                'expected_render_blocks': ['markdown'],
            },
            {'summary': '本地执行结果', 'sessionId': None},
            {
                'actualModules': ['employees'],
                'actualRenderBlocks': ['markdown'],
                'usedTools': [],
                'passStatus': 'pass',
                'missingExpectations': [],
                'failureCategories': [],
                'rootCauseNotes': '',
                'fixPlan': '',
            },
            user_id='admin-1',
            request_id='eval-timeout-1',
        )

    assert result['ok'] is False
    assert result['status'] == 'timeout'
    assert result['provider'] == 'siliconflow'
    assert result['auditRecorded'] is True
    assert result['auditLogId'] == 'audit-timeout-1'
    assert result['latencyMs'] == 45000
    assert result['error'] == 'request timeout'
