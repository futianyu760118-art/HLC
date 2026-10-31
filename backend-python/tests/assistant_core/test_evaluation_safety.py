from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
import yaml
from flask import g
from sqlalchemy import event, func, literal_column, select, text, update
from sqlalchemy.orm import Session

from models import (
    AIUsageLedger,
    ApprovalInstance,
    ApprovalRecord,
    AssistantAuditLog,
    AssistantEvaluationRun,
    AssistantSession,
    EmployeeChange,
    EmployeeRequest,
    Interview,
    Notification,
    Tenant,
    User,
    db,
)
from services.assistant_core import evaluation, evaluation_safety, workset_store
from tests.test_saas_tenancy import _client, saas_app


BUSINESS_WRITE_CASE_IDS = {
    'confirmed_attendance_notification_execution',
    'confirmed_approval_decision_execution',
    'confirmed_approval_rejection_execution',
    'confirmed_interview_schedule_from_workset',
    'confirmed_employee_change_submission_execution',
    'confirmed_salary_adjustment_submission_execution',
}
WRITE_CASE_ID = 'confirmed_attendance_notification_execution'
WRITE_FLOW_EXPECTATIONS = {
    'confirmed_attendance_notification_execution': (
        'createdNotifications',
        'duplicateCreatedNotifications',
        Notification,
    ),
    'confirmed_approval_decision_execution': (
        'createdApprovalRecords',
        'duplicateCreatedApprovalRecords',
        ApprovalRecord,
    ),
    'confirmed_approval_rejection_execution': (
        'createdApprovalRecords',
        'duplicateCreatedApprovalRecords',
        ApprovalRecord,
    ),
    'confirmed_interview_schedule_from_workset': (
        'createdInterviews',
        'duplicateCreatedInterviews',
        Interview,
    ),
    'confirmed_employee_change_submission_execution': (
        'createdEmployeeChanges',
        'duplicateCreatedEmployeeChanges',
        EmployeeChange,
    ),
    'confirmed_salary_adjustment_submission_execution': (
        'createdEmployeeChanges',
        'duplicateCreatedEmployeeChanges',
        EmployeeChange,
    ),
}
EVALUATION_EVIDENCE_AND_GOVERNANCE_TABLES = frozenset({
    AIUsageLedger.__table__.name,
    AssistantAuditLog.__table__.name,
    AssistantEvaluationRun.__table__.name,
    AssistantSession.__table__.name,
})


def _business_table_counts() -> dict[str, int]:
    return {
        table.name: db.session.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        for table in db.metadata.sorted_tables
        if table.name not in EVALUATION_EVIDENCE_AND_GOVERNANCE_TABLES
    }


@pytest.mark.parametrize('case_id', sorted(BUSINESS_WRITE_CASE_IDS))
def test_disposable_tenant_business_write_cases_execute_real_flow_and_stay_scoped(
    saas_app,
    monkeypatch,
    case_id,
) -> None:
    """Run each allowlisted write case against a disposable tenant.

    This deliberately exercises the evaluation runner and its confirmation-flow
    fixtures instead of replacing ``_run_and_record_case``.  The model audit is
    stubbed only at the external provider boundary so the business writes and
    duplicate-confirmation checks remain real.
    """
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )
    monkeypatch.setattr(
        evaluation,
        '_record_evaluation_model_audit',
        lambda case, response, assessment, *, user_id, request_id: {
            'requestId': request_id,
            'useCase': 'copilot_evaluation',
            'provider': 'siliconflow',
            'modelProfile': 'strong',
            'model': 'test-audit-model',
            'ok': True,
            'auditRecorded': True,
            'auditLogId': f'audit-{request_id}',
            'status': 'success',
        },
    )

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        result = evaluation.run_case(
            case_id=case_id,
            user_id='platform-user',
            run_user_id='alpha-admin',
            tenant=tenant,
            allow_writes=True,
        )

    assert result['userId'] == 'alpha-admin'
    with app.app_context():
        run_row = db.session.get(AssistantEvaluationRun, result['id'])
        payload = run_row.to_dict(include_payload=True)['responsePayload']
        assert run_row.tenant_id == tokens['alpha_id']
    assert payload['evaluationRunAs']['requestedByUserId'] == 'platform-user'
    assert payload['evaluationRunAs']['runAsUserId'] == 'alpha-admin'
    flow = payload['confirmationFlow']
    assert flow['wroteBeforeConfirmation'] is False
    assert flow['pendingConsumed'] is True
    created_key, duplicate_key, model_type = WRITE_FLOW_EXPECTATIONS[case_id]
    created_rows = flow[created_key]
    assert created_rows
    assert not flow[duplicate_key]
    with app.app_context():
        for created in created_rows:
            row = db.session.get(model_type, created['id'])
            assert row is not None
            assert row.tenant_id == tokens['alpha_id']
        assert model_type.query.filter_by(tenant_id=tokens['beta_id']).count() == 0

        if case_id.startswith('confirmed_approval_'):
            approval = db.session.get(ApprovalInstance, flow['approvalId'])
            request_row = db.session.get(EmployeeRequest, flow['businessRequestId'])
            assert approval.tenant_id == tokens['alpha_id']
            assert request_row.tenant_id == tokens['alpha_id']
        if case_id in {
            'confirmed_employee_change_submission_execution',
            'confirmed_salary_adjustment_submission_execution',
        }:
            assert flow['createdApprovals']
            assert all(
                db.session.get(ApprovalInstance, row['id']).tenant_id == tokens['alpha_id']
                for row in flow['createdApprovals']
            )


def test_write_case_failure_after_committed_business_change_keeps_run_evidence(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )

    def commit_business_change_then_fail(*_args, **_kwargs):
        user = db.session.get(User, 'alpha-admin')
        user.name = 'Committed Evaluation Write'
        db.session.commit()
        raise RuntimeError('synthetic post-write evaluation failure')

    monkeypatch.setattr(
        evaluation,
        '_run_confirmation_flow_case',
        commit_business_change_then_fail,
    )

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        with pytest.raises(RuntimeError, match='synthetic post-write'):
            evaluation.run_case(
                case_id=WRITE_CASE_ID,
                user_id='platform-user',
                run_user_id='alpha-admin',
                tenant=tenant,
                allow_writes=True,
            )

    with app.app_context():
        assert db.session.get(User, 'alpha-admin').name == 'Committed Evaluation Write'
        run = AssistantEvaluationRun.query.filter_by(case_id=WRITE_CASE_ID).one()
        assert run.tenant_id == tokens['alpha_id']
        assert run.pass_status == 'fail'
        assert run.failure_categories == ['execution_error']
        assert 'synthetic post-write' not in str(run.to_dict(include_payload=True))


def test_retest_reference_is_validated_before_write_case_execution(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )
    executed: list[bool] = []
    monkeypatch.setattr(
        evaluation,
        '_run_confirmation_flow_case',
        lambda *_args, **_kwargs: executed.append(True),
    )

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            evaluation.run_case(
                case_id=WRITE_CASE_ID,
                user_id='platform-user',
                run_user_id='alpha-admin',
                tenant=tenant,
                allow_writes=True,
                retest_of='x' * 65,
            )

    assert exc_info.value.code == 'AI_EVALUATION_RETEST_REFERENCE_INVALID'
    assert executed == []


def _configure_test_tenant(
    app,
    tenant_id: str,
    *,
    disposable_slug: bool,
    disposable_setting: bool,
) -> None:
    with app.app_context():
        tenant = db.session.get(Tenant, tenant_id)
        tenant.slug = f'e2e-platform-{tenant_id}' if disposable_slug else 'ordinary-tenant'
        tenant.settings_json = {'disposableTestTenant': disposable_setting}
        db.session.commit()


def _capture_evaluation_cases(monkeypatch):
    executed: list[tuple[str, str]] = []

    def record_case(case, **kwargs):
        executed.append((case['id'], kwargs.get('run_user_id') or kwargs['user_id']))
        return {'passStatus': 'pass'}

    monkeypatch.setattr(evaluation, '_run_and_record_case', record_case)
    return executed


def test_all_evaluation_cases_have_explicit_side_effect_classification() -> None:
    cases = evaluation.list_cases()

    assert len(cases) == 39
    assert all(case.get('side_effect') in {'read_only', 'business_write'} for case in cases)
    assert {
        case['id']
        for case in cases
        if case['side_effect'] == 'business_write'
    } == BUSINESS_WRITE_CASE_IDS


def test_default_suite_filters_read_only_cases_before_applying_limit(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    cases = [
        {
            'id': 'write-first',
            'side_effect': 'business_write',
            'requires_confirmation': True,
            'confirmation_flow': True,
            'confirmation_flow_type': 'notification',
        },
        {'id': 'read-first', 'side_effect': 'read_only'},
        {'id': 'read-second', 'side_effect': 'read_only'},
    ]
    executed: list[str] = []

    monkeypatch.setattr(evaluation, 'list_cases', lambda: cases)

    def record_case(case, **_kwargs):
        executed.append(case['id'])
        return {'passStatus': 'pass'}

    monkeypatch.setattr(evaluation, '_run_and_record_case', record_case)

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        result = evaluation.run_suite(
            user_id='platform-caller',
            run_user_id='alpha-admin',
            tenant=db.session.get(Tenant, tokens['alpha_id']),
            limit=1,
        )

    assert executed == ['read-first']
    assert result['total'] == 1


def test_default_read_only_suite_real_run_preserves_every_business_table(
    saas_app,
    monkeypatch,
) -> None:
    """Exercise the real runner while replacing only the external provider."""
    app, tokens = saas_app
    from services.assistant_core import llm_client

    provider_calls: list[str] = []

    class ProviderResponse:
        status_code = 200

        def __init__(self, url: str, request_body: dict) -> None:
            self.url = url
            self.request_body = request_body
            self.text = 'provider response'

        def json(self):
            if self.url.rstrip('/').endswith('/embeddings'):
                return {'data': [{'embedding': [0.1] * 16}]}
            content = (
                '{}'
                if self.request_body.get('response_format')
                else '外部模型评测响应'
            )
            return {
                'choices': [{
                    'message': {'role': 'assistant', 'content': content},
                    'finish_reason': 'stop',
                }],
                'usage': {
                    'prompt_tokens': 1,
                    'completion_tokens': 1,
                    'total_tokens': 2,
                },
            }

        def raise_for_status(self) -> None:
            return None

    def provider_post(url, **kwargs):
        provider_calls.append(url)
        return ProviderResponse(url, kwargs.get('json') or {})

    monkeypatch.setenv('SILICONFLOW_API_KEY', 'sk-evaluation-provider-test')
    monkeypatch.setenv('SILICONFLOW_API_URL', 'https://provider.invalid/v1')
    monkeypatch.setattr(llm_client, 'API_KEY', 'sk-evaluation-provider-test')
    monkeypatch.setattr(llm_client.requests, 'post', provider_post)

    with app.app_context():
        before_business = _business_table_counts()
        before_evidence = {
            table_name: db.session.execute(
                select(func.count()).select_from(db.metadata.tables[table_name])
            ).scalar_one()
            for table_name in EVALUATION_EVIDENCE_AND_GOVERNANCE_TABLES
        }

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'mode': 'read_only',
        },
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['total'] == 8
    case_side_effects = {
        case['id']: case['side_effect']
        for case in evaluation.list_cases()
    }
    assert all(
        case_side_effects[result['caseId']] == 'read_only'
        for result in payload['results']
    )
    assert provider_calls

    with app.app_context():
        assert _business_table_counts() == before_business
        after_evidence = {
            table_name: db.session.execute(
                select(func.count()).select_from(db.metadata.tables[table_name])
            ).scalar_one()
            for table_name in EVALUATION_EVIDENCE_AND_GOVERNANCE_TABLES
        }
    assert after_evidence[AssistantEvaluationRun.__table__.name] > before_evidence[
        AssistantEvaluationRun.__table__.name
    ]
    assert after_evidence[AssistantAuditLog.__table__.name] > before_evidence[
        AssistantAuditLog.__table__.name
    ]


def test_default_suite_rejects_catalog_without_read_only_cases(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    monkeypatch.setattr(
        evaluation,
        'list_cases',
        lambda: [{'id': 'write-only', 'side_effect': 'business_write'}],
    )

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            evaluation.run_suite(
                user_id='platform-caller',
                run_user_id='alpha-admin',
                tenant=db.session.get(Tenant, tokens['alpha_id']),
            )

    assert exc_info.value.code == 'AI_EVALUATION_CASE_CONFIGURATION_INVALID'
    assert exc_info.value.status_code == 500


@pytest.mark.parametrize('side_effect', [None, 'unknown'])
def test_evaluation_case_loader_fails_closed_for_invalid_side_effect(
    monkeypatch,
    tmp_path,
    side_effect,
) -> None:
    suite_path = tmp_path / 'evaluation_cases.yaml'
    case = {'id': 'unsafe-case'}
    if side_effect is not None:
        case['side_effect'] = side_effect
    suite_path.write_text(yaml.safe_dump({'cases': [case]}), encoding='utf-8')
    monkeypatch.setattr(evaluation, 'CASES_PATH', suite_path)

    with pytest.raises(ValueError, match='side_effect'):
        evaluation.load_evaluation_suite()


@pytest.mark.parametrize(
    'case',
    [
        {
            'id': 'read-only-confirmation',
            'side_effect': 'read_only',
            'confirmation_flow': True,
            'confirmation_flow_type': 'notification',
        },
        {
            'id': 'write-missing-confirmation-type',
            'side_effect': 'business_write',
            'confirmation_flow': True,
        },
        {
            'id': 'write-unknown-confirmation-type',
            'side_effect': 'business_write',
            'confirmation_flow': True,
            'confirmation_flow_type': 'unknown',
        },
        {
            'id': 'write-missing-requires-confirmation',
            'side_effect': 'business_write',
            'confirmation_flow': True,
            'confirmation_flow_type': 'notification',
        },
        {
            'id': 'truthy-non-boolean-requires-confirmation',
            'side_effect': 'read_only',
            'requires_confirmation': 'yes',
        },
        {
            'id': 'truthy-non-boolean-confirmation',
            'side_effect': 'read_only',
            'confirmation_flow': 'yes',
        },
    ],
)
def test_evaluation_case_loader_rejects_malformed_confirmation_contract(case) -> None:
    with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
        evaluation._validate_evaluation_case_classification([case])

    assert exc_info.value.code == 'AI_EVALUATION_CASE_CONFIGURATION_INVALID'


@pytest.mark.parametrize('yaml_text', ['[]\n', '- item\n', '42\n', 'scalar\n', 'null\n'])
def test_evaluation_case_loader_rejects_non_mapping_root(
    monkeypatch,
    tmp_path,
    yaml_text,
) -> None:
    suite_path = tmp_path / 'evaluation_cases.yaml'
    suite_path.write_text(yaml_text, encoding='utf-8')
    monkeypatch.setattr(evaluation, 'CASES_PATH', suite_path)

    with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
        evaluation.load_evaluation_suite()

    assert exc_info.value.code == 'AI_EVALUATION_CASE_CONFIGURATION_INVALID'
    assert exc_info.value.status_code == 500


@pytest.mark.parametrize(
    'cases',
    [
        [{'side_effect': 'read_only'}],
        [
            {'id': 'duplicate-case', 'side_effect': 'read_only'},
            {'id': 'duplicate-case', 'side_effect': 'business_write'},
        ],
    ],
)
def test_evaluation_case_loader_rejects_missing_or_duplicate_case_ids(
    monkeypatch,
    tmp_path,
    cases,
) -> None:
    suite_path = tmp_path / 'evaluation_cases.yaml'
    suite_path.write_text(yaml.safe_dump({'cases': cases}), encoding='utf-8')
    monkeypatch.setattr(evaluation, 'CASES_PATH', suite_path)

    with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
        evaluation.load_evaluation_suite()

    assert exc_info.value.code == 'AI_EVALUATION_CASE_CONFIGURATION_INVALID'


def test_suite_rejects_unknown_case_ids_before_any_case_executes(monkeypatch) -> None:
    cases = [{'id': 'known', 'side_effect': 'read_only'}]
    executed: list[str] = []
    monkeypatch.setattr(evaluation, 'list_cases', lambda: cases)
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    with pytest.raises(ValueError, match='unknown'):
        evaluation.run_suite(
            user_id='platform-caller',
            run_user_id='tenant-admin',
            tenant=SimpleNamespace(slug='ordinary', settings_json={}),
            case_ids=['known', 'unknown'],
            limit=2,
        )

    assert executed == []


@pytest.mark.parametrize('case_ids', [[], 'known', [1], ['   ']])
def test_suite_rejects_malformed_case_ids_before_any_case_executes(
    monkeypatch,
    case_ids,
) -> None:
    cases = [{'id': 'known', 'side_effect': 'read_only'}]
    executed: list[str] = []
    monkeypatch.setattr(evaluation, 'list_cases', lambda: cases)
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
        evaluation.run_suite(
            user_id='platform-caller',
            run_user_id='tenant-admin',
            tenant=SimpleNamespace(slug='ordinary', settings_json={}),
            case_ids=case_ids,
            limit=2,
        )

    assert exc_info.value.code == 'AI_EVALUATION_CASE_INVALID'
    assert executed == []


@pytest.mark.parametrize('limit', [0, -1, 31, True, '2'])
def test_suite_rejects_invalid_limit_before_any_case_executes(monkeypatch, limit) -> None:
    cases = [{'id': 'known', 'side_effect': 'read_only'}]
    executed: list[str] = []
    monkeypatch.setattr(evaluation, 'list_cases', lambda: cases)
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    with pytest.raises(ValueError, match='limit'):
        evaluation.run_suite(
            user_id='platform-caller',
            run_user_id='tenant-admin',
            tenant=SimpleNamespace(slug='ordinary', settings_json={}),
            limit=limit,
        )

    assert executed == []


def test_route_requires_tenant_before_calling_evaluation_service(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    called: list[dict] = []
    monkeypatch.setattr(
        evaluation,
        'run_suite',
        lambda **kwargs: called.append(kwargs) or {'total': 0, 'results': []},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'limit': 1},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_TENANT_REQUIRED'
    assert called == []


def test_evaluation_cases_route_maps_invalid_catalog_to_stable_error(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app

    def raise_configuration_error():
        raise evaluation_safety.EvaluationSafetyError(
            'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
            '评估用例目录配置无效',
            status_code=500,
        )

    monkeypatch.setattr(evaluation, 'load_evaluation_suite', raise_configuration_error)

    response = _client(app, tokens['platform']).get('/api/platform/ai/evaluation-cases')

    assert response.status_code == 500
    assert response.get_json() == {
        'error': '评估用例目录配置无效',
        'code': 'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
    }


def test_evaluation_run_route_rejects_non_object_payload_before_execution(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    app.config['PROPAGATE_EXCEPTIONS'] = False
    called: list[dict] = []
    monkeypatch.setattr(
        evaluation,
        'run_suite',
        lambda **kwargs: called.append(kwargs) or {'total': 0, 'results': []},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json=['not', 'an', 'object'],
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_PAYLOAD_INVALID'
    assert called == []


def test_route_maps_unknown_batch_case_to_stable_error_before_execution(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    app.config['PROPAGATE_EXCEPTIONS'] = False
    executed: list[str] = []
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['attendance_employee_anomaly', 'missing-case'],
            'limit': 2,
        },
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_CASE_INVALID'
    assert executed == []


def test_route_rejects_duplicate_batch_case_ids_before_execution(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    executed: list[str] = []
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['attendance_employee_anomaly', 'attendance_employee_anomaly'],
            'limit': 2,
        },
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_CASE_INVALID'
    assert executed == []


@pytest.mark.parametrize('malformed_case_ids', ['attendance_employee_anomaly', [], [1]])
def test_route_rejects_malformed_case_ids_before_execution(
    saas_app,
    monkeypatch,
    malformed_case_ids,
) -> None:
    app, tokens = saas_app
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': malformed_case_ids,
        },
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_CASE_INVALID'
    assert executed == []


def test_route_rejects_non_object_evaluation_payload_before_execution(saas_app) -> None:
    app, tokens = saas_app

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json=['not', 'an', 'object'],
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_PAYLOAD_INVALID'


def test_case_catalog_route_maps_configuration_error_to_stable_json(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app

    def fail_closed():
        raise evaluation_safety.EvaluationSafetyError(
            'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
            'invalid evaluation catalog',
            status_code=500,
        )

    monkeypatch.setattr(evaluation, 'load_evaluation_suite', fail_closed)

    response = _client(app, tokens['platform']).get('/api/platform/ai/evaluation-cases')

    assert response.status_code == 500
    assert response.get_json()['code'] == 'AI_EVALUATION_CASE_CONFIGURATION_INVALID'


@pytest.mark.parametrize('allow_writes', [None, False, 1])
def test_write_suite_requires_allow_writes_to_be_strict_true(
    saas_app,
    monkeypatch,
    allow_writes,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )
    executed = _capture_evaluation_cases(monkeypatch)
    payload = {'tenantId': tokens['alpha_id'], 'caseIds': [WRITE_CASE_ID]}
    if allow_writes is not None:
        payload['allowWrites'] = allow_writes

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json=payload,
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_WRITES_NOT_ALLOWED'
    assert executed == []


@pytest.mark.parametrize(
    ('disposable_slug', 'disposable_setting'),
    [(False, False), (True, False), (False, True)],
)
def test_write_suite_requires_both_disposable_tenant_markers(
    saas_app,
    monkeypatch,
    disposable_slug,
    disposable_setting,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=disposable_slug,
        disposable_setting=disposable_setting,
    )
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': [WRITE_CASE_ID],
            'allowWrites': True,
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_REQUIRES_DISPOSABLE_TENANT'
    assert executed == []


def test_write_suite_allows_strict_true_for_double_marked_disposable_tenant(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': [WRITE_CASE_ID],
            'allowWrites': True,
        },
    )

    assert response.status_code == 200
    assert executed == [(WRITE_CASE_ID, 'alpha-admin')]


def test_write_suite_accepts_json_string_disposable_tenant_settings(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    with app.app_context():
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.slug = f'e2e-platform-{tokens["alpha_id"]}'
        tenant.settings_json = json.dumps({'disposableTestTenant': True})
        db.session.commit()
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': [WRITE_CASE_ID],
            'allowWrites': True,
        },
    )

    assert response.status_code == 200
    assert executed == [(WRITE_CASE_ID, 'alpha-admin')]


def test_evaluation_run_user_prefers_active_tenant_admin(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add(User(
            id='alpha-hr-admin',
            tenant_id=tokens['alpha_id'],
            email='hr-admin@example.com',
            password_hash='unused',
            name='Alpha HR Admin',
            role='hr_admin',
            status='active',
        ))
        db.session.commit()
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseIds': ['attendance_employee_anomaly']},
    )

    assert response.status_code == 200
    assert executed == [('attendance_employee_anomaly', 'alpha-admin')]


def test_evaluation_run_user_falls_back_to_active_hr_admin(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.get(User, 'alpha-admin').status = 'inactive'
        db.session.add(User(
            id='alpha-hr-admin',
            tenant_id=tokens['alpha_id'],
            email='hr-admin@example.com',
            password_hash='unused',
            name='Alpha HR Admin',
            role='hr_admin',
            status='active',
        ))
        db.session.commit()
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseIds': ['attendance_employee_anomaly']},
    )

    assert response.status_code == 200
    assert executed == [('attendance_employee_anomaly', 'alpha-hr-admin')]


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('runAsUserId', '   '),
        ('runAsUserId', None),
        ('runAsUserId', 7),
        ('runAsUserEmail', ''),
        ('runAsUserEmail', False),
        ('runAsUserEmail', {}),
    ],
)
def test_explicit_invalid_run_as_value_does_not_fall_back_to_default_admin(
    saas_app,
    monkeypatch,
    field,
    value,
) -> None:
    app, tokens = saas_app
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['attendance_employee_anomaly'],
            field: value,
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_RUN_USER_INVALID'
    assert executed == []


@pytest.mark.parametrize('run_as_kind', ['cross_tenant', 'inactive', 'employee'])
def test_explicit_run_as_must_be_active_admin_in_target_tenant(
    saas_app,
    monkeypatch,
    run_as_kind,
) -> None:
    app, tokens = saas_app
    run_as_user_id = 'beta-admin'
    with app.app_context():
        if run_as_kind == 'inactive':
            db.session.get(User, 'alpha-admin').status = 'inactive'
            run_as_user_id = 'alpha-admin'
        elif run_as_kind == 'employee':
            db.session.add(User(
                id='alpha-employee',
                tenant_id=tokens['alpha_id'],
                email='employee@example.com',
                password_hash='unused',
                name='Alpha Employee',
                role='employee',
                status='active',
            ))
            run_as_user_id = 'alpha-employee'
        db.session.commit()
    app.config['PROPAGATE_EXCEPTIONS'] = False
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['attendance_employee_anomaly'],
            'runAsUserId': run_as_user_id,
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_RUN_USER_INVALID'
    assert executed == []


def test_evaluation_rejects_tenant_without_active_admin(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.get(User, 'alpha-admin').status = 'inactive'
        db.session.commit()
    app.config['PROPAGATE_EXCEPTIONS'] = False
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseIds': ['attendance_employee_anomaly']},
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_RUN_USER_REQUIRED'
    assert executed == []


def test_platform_caller_is_preserved_separately_from_tenant_run_user(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    identities: list[tuple[str, str]] = []

    def record_case(_case, **kwargs):
        identities.append((kwargs['user_id'], kwargs['run_user_id']))
        return {'passStatus': 'pass'}

    monkeypatch.setattr(evaluation, '_run_and_record_case', record_case)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'caseIds': ['attendance_employee_anomaly']},
    )

    assert response.status_code == 200
    assert identities == [('platform-user', 'alpha-admin')]


def test_permission_case_declares_tenant_local_role_instead_of_fixed_user() -> None:
    case = evaluation.get_case('payroll_permission_denied_employee')

    assert 'run_as_user_id' not in case
    assert case['run_as_role'] == 'employee'


def test_read_only_permission_case_uses_active_employee_from_target_tenant(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add_all([
            User(
                id='alpha-evaluator-employee',
                tenant_id=tokens['alpha_id'],
                email='alpha-evaluator@example.com',
                password_hash='unused',
                name='Alpha Evaluator Employee',
                role='employee',
                status='active',
            ),
            User(
                id='beta-evaluator-employee',
                tenant_id=tokens['beta_id'],
                email='beta-evaluator@example.com',
                password_hash='unused',
                name='Beta Evaluator Employee',
                role='employee',
                status='active',
            ),
        ])
        db.session.commit()
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['payroll_permission_denied_employee'],
        },
    )

    assert response.status_code == 200
    assert executed == [('payroll_permission_denied_employee', 'alpha-evaluator-employee')]


def test_read_only_permission_case_rejects_when_target_role_is_missing(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    executed = _capture_evaluation_cases(monkeypatch)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseIds': ['payroll_permission_denied_employee'],
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_RUN_USER_REQUIRED'
    assert executed == []


def test_evaluation_execution_scope_is_available() -> None:
    assert callable(getattr(evaluation_safety, 'evaluation_execution_scope', None))


def test_evaluation_execution_scope_switches_and_restores_request_identity(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        original_tenant = object()
        g.tenant_id = 'original-tenant-id'
        g.tenant = original_tenant
        g.is_platform_admin = True

        with evaluation_safety.evaluation_execution_scope(
            tenant=tenant,
            run_user=run_user,
            read_only=True,
        ):
            assert g.tenant_id == tokens['alpha_id']
            assert g.tenant is tenant
            assert g.is_platform_admin is False
            assert workset_store._request_user_id() == 'alpha-admin'

        assert g.tenant_id == 'original-tenant-id'
        assert g.tenant is original_tenant
        assert g.is_platform_admin is True
        assert workset_store._request_user_id() is None


def test_route_executes_case_inside_target_tenant_identity_scope(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    observed: list[tuple[str | None, str | None, bool, str | None, str]] = []

    def record_case(case, **kwargs):
        observed.append((
            getattr(g, 'tenant_id', None),
            getattr(getattr(g, 'tenant', None), 'id', None),
            bool(getattr(g, 'is_platform_admin', False)),
            workset_store._request_user_id(),
            kwargs['run_user_id'],
        ))
        return {'passStatus': 'pass'}

    monkeypatch.setattr(evaluation, '_run_and_record_case', record_case)

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'caseId': 'attendance_employee_anomaly',
        },
    )

    assert response.status_code == 200
    assert observed == [(
        tokens['alpha_id'],
        tokens['alpha_id'],
        False,
        'alpha-admin',
        'alpha-admin',
    )]


def test_evaluation_execution_scope_restores_quota_state_after_success(saas_app) -> None:
    app, tokens = saas_app
    reservation_key = (tokens['alpha_id'], 'assistant')
    original_reservations = {
        reservation_key: {'baseline': 3, 'pending': 1, 'settled': 2},
    }

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        g.tenant_id = None
        g.tenant = None
        g.is_platform_admin = True
        g._ai_actual_call_reservations = copy.deepcopy(original_reservations)

        with evaluation_safety.evaluation_execution_scope(
            tenant=tenant,
            run_user=run_user,
            read_only=True,
        ):
            g._ai_actual_call_reservations[reservation_key]['pending'] = 99

        assert g._ai_actual_call_reservations == original_reservations


def test_evaluation_execution_scope_rolls_back_and_restores_on_exception(saas_app) -> None:
    app, tokens = saas_app
    reservation_key = (tokens['alpha_id'], 'assistant')
    original_reservations = {
        reservation_key: {'baseline': 3, 'pending': 1, 'settled': 2},
    }
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        g.tenant_id = None
        g.tenant = None
        g.is_platform_admin = True
        g._ai_actual_call_reservations = copy.deepcopy(original_reservations)

        with pytest.raises(RuntimeError, match='scope failure'):
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                run_user.name = 'Uncommitted Name'
                db.session.add(User(
                    id='pending-scope-user',
                    tenant_id=tokens['alpha_id'],
                    email='pending-scope@example.com',
                    password_hash='unused',
                    name='Pending Scope User',
                    role='employee',
                    status='active',
                ))
                g._ai_actual_call_reservations[reservation_key]['pending'] = 99
                raise RuntimeError('scope failure')

        assert g.tenant_id is None
        assert g.tenant is None
        assert g.is_platform_admin is True
        assert g._ai_actual_call_reservations == original_reservations
        assert workset_store._request_user_id() is None
        assert db.session.get(User, 'pending-scope-user') is None
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


@pytest.mark.parametrize('mutation_kind', ['new', 'dirty', 'deleted'])
def test_read_only_evaluation_scope_rejects_business_orm_mutations(
    saas_app,
    mutation_kind,
) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add(User(
            id='firewall-business-user',
            tenant_id=tokens['alpha_id'],
            email='firewall-business@example.com',
            password_hash='unused',
            name='Firewall Business User',
            role='employee',
            status='active',
        ))
        db.session.commit()

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        target = db.session.get(User, 'firewall-business-user')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                if mutation_kind == 'new':
                    db.session.add(User(
                        id='firewall-new-user',
                        tenant_id=tokens['alpha_id'],
                        email='firewall-new@example.com',
                        password_hash='unused',
                        name='Firewall New User',
                        role='employee',
                        status='active',
                    ))
                elif mutation_kind == 'dirty':
                    target.name = 'Mutated Name'
                else:
                    db.session.delete(target)
                db.session.flush()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert db.session.get(User, 'firewall-new-user') is None
        assert db.session.get(User, 'firewall-business-user').name == 'Firewall Business User'


def test_read_only_evaluation_scope_rejects_bulk_dml(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.execute(
                    update(User)
                    .where(User.id == 'alpha-admin')
                    .values(name='Bulk Mutated Name')
                )

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_evaluation_scope_rejects_unscoped_core_table_select(saas_app) -> None:
    """Core table SELECTs must not bypass the request's ORM tenant criteria."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.execute(select(User.__table__)).mappings().all()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'


def test_read_only_evaluation_scope_rejects_tenant_filter_opt_out(saas_app) -> None:
    """An ORM SELECT cannot disable tenant criteria inside the evaluation scope."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.execute(
                    select(User).execution_options(skip_tenant_criteria=True)
                ).scalars().all()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'


@pytest.mark.parametrize('override_kind', ['platform_admin', 'tenant_id'])
def test_read_only_evaluation_scope_rejects_tenant_context_override(
    saas_app,
    override_kind,
) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                if override_kind == 'platform_admin':
                    g.is_platform_admin = True
                else:
                    g.tenant_id = tokens['beta_id']
                db.session.execute(select(User)).scalars().all()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'


def test_read_only_evaluation_scope_rejects_connection_level_orm_select(saas_app) -> None:
    """Connection.execute cannot claim ORM safety without Session tenant criteria."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.connection().execute(select(User)).all()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'


def test_read_only_evaluation_scope_rejects_connection_level_core_dml(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.connection().execute(
                    User.__table__.update()
                    .where(User.id == 'alpha-admin')
                    .values(name='Connection Mutated Name')
                )

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_evaluation_scope_rejects_commented_textual_dml(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.connection().execute(
                    text(
                        '/* evaluation read-only bypass */ '
                        'UPDATE users SET name = :name WHERE id = :user_id'
                    ),
                    {'name': 'Text Mutated Name', 'user_id': 'alpha-admin'},
                )

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_evaluation_scope_rejects_driver_level_dml(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.connection().exec_driver_sql(
                    'UPDATE users SET name = ? WHERE id = ?',
                    ('Driver Bypass', 'alpha-admin'),
                )

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_flush_marker_does_not_allow_listener_driver_sql_business_bypass(saas_app) -> None:
    app, tokens = saas_app

    def malicious_listener(session, _flush_context, _instances):
        session.connection().exec_driver_sql(
            'UPDATE users SET name = ? WHERE id = ?',
            ('Listener Bypass', 'alpha-admin'),
        )

    event.listen(Session, 'before_flush', malicious_listener)
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    db.session.add(AssistantSession(
                        id='listener-bypass-session',
                        tenant_id=tokens['alpha_id'],
                        user_id='alpha-admin',
                        title='Listener Bypass',
                        messages=[],
                        is_active=True,
                        message_count=0,
                    ))
                    db.session.flush()
            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        event.remove(Session, 'before_flush', malicious_listener)


def test_read_only_flush_marker_does_not_allow_listener_metadata_core_sql_bypass(saas_app) -> None:
    """The flush marker must not turn arbitrary Core metadata SQL into ORM work."""
    app, tokens = saas_app

    def malicious_listener(session, _flush_context, _instances):
        session.connection().execution_options(
            compiled_cache=AssistantSession.__mapper__._compiled_cache,
        ).execute(
            AssistantSession.__table__.update()
            .where(AssistantSession.id == 'listener-metadata-bypass-session')
            .values(title='Metadata Core Bypass')
        )

    with app.app_context():
        db.session.add(AssistantSession(
            id='listener-metadata-bypass-session',
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            title='Original Metadata Title',
            messages=[],
            is_active=True,
            message_count=0,
        ))
        db.session.commit()

    event.listen(Session, 'before_flush', malicious_listener)
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    db.session.add(AssistantSession(
                        id='listener-metadata-trigger-session',
                        tenant_id=tokens['alpha_id'],
                        user_id='alpha-admin',
                        title='Trigger Flush',
                        messages=[],
                        is_active=True,
                        message_count=0,
                    ))
                    db.session.flush()
            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(
                AssistantSession,
                'listener-metadata-bypass-session',
            ).title == 'Original Metadata Title'
    finally:
        event.remove(Session, 'before_flush', malicious_listener)


def test_read_only_scope_rejects_engine_raw_connection_before_cursor_access(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        raw = None
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                raw = db.engine.raw_connection()
                raw.cursor().execute(
                    'UPDATE users SET name = ? WHERE id = ?',
                    ('Raw Connection Bypass', 'alpha-admin'),
                )
        if raw is not None:
            raw.rollback()
            raw.close()
        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_scope_rejects_unscoped_raw_table_select(saas_app) -> None:
    """Direct DB-API reads must not bypass the tenant-aware ORM path."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    raw.cursor().execute('SELECT id, tenant_id FROM users').fetchall()

            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_underlying_driver_connection_cursor(saas_app) -> None:
    """The fairy's deprecated ``connection`` escape hatch must be guarded too."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        raw = None
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                raw = db.engine.raw_connection()
                raw.connection.cursor().execute(
                    'UPDATE users SET name = ? WHERE id = ?',
                    ('Underlying Raw Bypass', 'alpha-admin'),
                )
        if raw is not None:
            raw.rollback()
            raw.close()
        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_scope_rejects_proxy_wrapped_connection_attribute_bypass(saas_app) -> None:
    """The proxy's storage attribute must not expose the writable DB-API object."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    underlying = raw.driver_connection._connection
                    underlying.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Wrapped Connection Bypass', 'alpha-admin'),
                    )
                    underlying.commit()

            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_proxy_wrapped_cursor_attribute_bypass(saas_app) -> None:
    """The cursor proxy must not expose its writable DB-API cursor."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    raw.cursor()._cursor.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Wrapped Cursor Bypass', 'alpha-admin'),
                    )
                    raw.commit()

            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_fairy_private_connection_attribute_bypass(saas_app) -> None:
    """The fairy's direct ``_connection`` slot must not expose DB-API writes."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    underlying = raw._connection
                    underlying.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Fairy Private Connection Bypass', 'alpha-admin'),
                    )
                    underlying.commit()

            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_preacquired_fairy_private_connection_bypass(saas_app) -> None:
    """A native connection reference acquired before scope entry must stay guarded."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            raw = db.engine.raw_connection()
            underlying = raw._connection
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    underlying.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Preacquired Fairy Connection Bypass', 'alpha-admin'),
                    )
                    underlying.commit()

            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_fairy_driver_connection_cursor_bypass(saas_app) -> None:
    """Accessing the fairy's underlying DB-API connection must not evade the guard."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                fairy = db.session.connection().connection
                fairy.connection.cursor().execute(
                    'UPDATE users SET name = ? WHERE id = ?',
                    ('Fairy Driver Bypass', 'alpha-admin'),
                )
        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


def test_read_only_scope_rejects_fairy_dbapi_connection_cursor_bypass(saas_app) -> None:
    """The fairy's raw ``dbapi_connection`` slot must not be writable either."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                fairy = db.session.connection().connection
                fairy.dbapi_connection.cursor().execute(
                    'UPDATE users SET name = ? WHERE id = ?',
                    ('Fairy DBAPI Bypass', 'alpha-admin'),
                )
        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


@pytest.mark.parametrize('connection_alias', ['execute', 'connection', 'driver_connection'])
def test_read_only_scope_rejects_connection_execute_aliases(saas_app, connection_alias) -> None:
    """Every public fairy connection alias must enforce the read-only scope."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    connection = (
                        raw
                        if connection_alias == 'execute'
                        else getattr(raw, connection_alias)
                    )
                    connection.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Connection Execute Alias Bypass', 'alpha-admin'),
                    )
            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_cursor_acquired_before_scope(saas_app) -> None:
    """A cursor obtained before entering evaluation must remain guarded."""
    app, tokens = saas_app
    raw = None
    cursor = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            raw = db.engine.raw_connection()
            cursor = raw.cursor()
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    cursor.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Preacquired Cursor Bypass', 'alpha-admin'),
                    )
            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if raw is not None:
            raw.rollback()
            raw.close()


def test_read_only_scope_rejects_cursor_connection_bypass(saas_app) -> None:
    """A proxied cursor must not expose its unguarded driver connection."""
    app, tokens = saas_app
    raw = None
    try:
        with app.test_request_context('/api/platform/ai/evaluation-runs'):
            tenant = db.session.get(Tenant, tokens['alpha_id'])
            run_user = db.session.get(User, 'alpha-admin')
            with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
                with evaluation_safety.evaluation_execution_scope(
                    tenant=tenant,
                    run_user=run_user,
                    read_only=True,
                ):
                    raw = db.engine.raw_connection()
                    raw.cursor().connection.execute(
                        'UPDATE users SET name = ? WHERE id = ?',
                        ('Cursor Connection Bypass', 'alpha-admin'),
                    )
            assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
            db.session.expire_all()
            assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
    finally:
        if raw is not None:
            raw.rollback()
            raw.close()


@pytest.mark.parametrize('command_path', ['cursor_query', 'cursor_get_db_query'])
def test_read_only_scope_rejects_pymysql_cursor_command_paths(
    saas_app,
    command_path,
) -> None:
    """PyMySQL cursor helpers must not recover the unguarded connection."""
    app, tokens = saas_app
    calls: list[object] = []

    class FakePyMySQLConnection:
        def query(self, statement):
            calls.append(statement)
            return 1

    class FakePyMySQLCursor:
        def __init__(self):
            self.connection = FakePyMySQLConnection()

        def _get_db(self):
            return self.connection

        def _query(self, statement):
            return self._get_db().query(statement)

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        proxy = evaluation_safety._ReadOnlyCursorProxy(FakePyMySQLCursor(), {})
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                if command_path == 'cursor_query':
                    proxy._query('UPDATE users SET name = "Cursor Query Bypass"')
                else:
                    proxy._get_db().query(
                        'UPDATE users SET name = "Cursor DB Bypass"'
                    )

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert calls == []


@pytest.mark.parametrize(
    ('method_name', 'statement'),
    [
        ('query', 'UPDATE users SET name = "Driver Query Bypass"'),
        ('query', b'DELETE FROM users WHERE id = "alpha-admin"'),
        ('write_packet', b'\x03UPDATE users SET name = "Packet Bypass"'),
        ('_execute_command', (3, 'UPDATE users SET name = "Command Bypass"')),
        ('_write_bytes', b'raw mysql protocol packet'),
    ],
)
def test_read_only_scope_rejects_pymysql_direct_command_paths(
    saas_app,
    method_name,
    statement,
) -> None:
    """Production PyMySQL command APIs must not bypass the cursor guard."""
    app, tokens = saas_app
    calls: list[tuple[str, object]] = []

    class FakePyMySQLConnection:
        def query(self, sql, unbuffered=False):
            calls.append(('query', sql))
            return 1

        def write_packet(self, payload):
            calls.append(('write_packet', payload))

        def _execute_command(self, command, sql):
            calls.append(('_execute_command', (command, sql)))

        def _write_bytes(self, payload):
            calls.append(('_write_bytes', payload))

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        proxy = evaluation_safety._ReadOnlyConnectionProxy(
            FakePyMySQLConnection(),
            {},
        )
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                method = getattr(proxy, method_name)
                if method_name == '_execute_command':
                    method(*statement)
                else:
                    method(statement)

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert calls == []


def test_read_only_scope_allows_pymysql_direct_read_query(saas_app) -> None:
    app, tokens = saas_app
    calls: list[object] = []

    class FakePyMySQLConnection:
        def query(self, sql, unbuffered=False):
            calls.append((sql, unbuffered))
            return 7

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        proxy = evaluation_safety._ReadOnlyConnectionProxy(
            FakePyMySQLConnection(),
            {},
        )
        with evaluation_safety.evaluation_execution_scope(
            tenant=tenant,
            run_user=run_user,
            read_only=True,
        ):
            assert proxy.query('SELECT 1', unbuffered=True) == 7

        assert calls == [('SELECT 1', True)]


@pytest.mark.parametrize('method_name', ['execute', 'executemany'])
def test_cursor_proxy_preserves_pymysql_integer_rowcount(method_name) -> None:
    """PyMySQL cursor methods return an integer rowcount, not the cursor."""

    class FakePyMySQLCursor:
        def execute(self, statement, parameters=None):
            return 3

        def executemany(self, statement, parameters):
            return 4

    proxy = evaluation_safety._ReadOnlyCursorProxy(FakePyMySQLCursor(), {})
    if method_name == 'execute':
        assert proxy.execute('SELECT 1') == 3
    else:
        assert proxy.executemany('SELECT ?', [(1,)]) == 4


@pytest.mark.parametrize(
    'statement',
    [
        'CALL mutate_users()',
        "LOAD DATA LOCAL INFILE 'users.csv' INTO TABLE users",
        'RENAME TABLE users TO users_old',
        "SELECT * FROM users FOR UPDATE",
        "SELECT * FROM users FOR SHARE",
        "SELECT * FROM users LOCK IN SHARE MODE",
        "SELECT * FROM users INTO OUTFILE '/tmp/users.csv'",
        "SELECT LOAD_FILE('/etc/passwd')",
        'SELECT SLEEP(30)',
        "SELECT GET_LOCK('evaluation-lock', 30)",
        'SELECT BENCHMARK(1000000, SHA2(\'x\', 256))',
        'SELECT mutate_business_rows()',
        'SET GLOBAL read_only = 0',
        'PRAGMA writable_schema = ON',
    ],
)
def test_read_only_scope_rejects_non_readonly_cursor_sql(saas_app, statement) -> None:
    """Textual DB-API SQL is fail-closed, including MySQL non-DML writes."""
    app, tokens = saas_app
    calls: list[str] = []

    class FakeCursor:
        def execute(self, sql, parameters=None):
            calls.append(sql)
            return 1

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        proxy = evaluation_safety._ReadOnlyCursorProxy(FakeCursor(), {})
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                proxy.execute(statement)

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
    assert calls == []


@pytest.mark.parametrize(
    'statement',
    [
        select(User).with_for_update(),
        select(func.mutate_business_rows()),
        select(literal_column('mutate_business_rows()')),
        select(User.id).with_statement_hint('FOR SHARE', dialect_name='*'),
        select(User.id).with_statement_hint("INTO OUTFILE '/tmp/evaluation-users.csv'", dialect_name='*'),
    ],
    ids=[
        'row_lock',
        'unknown_sql_function',
        'literal_sql_expression',
        'statement_hint_row_lock',
        'statement_hint_outfile',
    ],
)
def test_read_only_scope_rejects_unsafe_compiled_selects(saas_app, statement) -> None:
    """A SQLAlchemy SELECT is not automatically read-only."""
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.execute(statement).all()

    assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'


def test_read_only_scope_allows_safe_compiled_count(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        with evaluation_safety.evaluation_execution_scope(
            tenant=tenant,
            run_user=run_user,
            read_only=True,
        ):
            count = db.session.execute(select(func.count()).select_from(User)).scalar_one()

    assert count >= 1


def test_read_only_evaluation_scope_rejects_cte_wrapped_dml(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                db.session.connection().execute(text(
                    "WITH payload(id, name) AS (SELECT 'alpha-admin', 'CTE Bypass') "
                    "UPDATE users SET name = (SELECT name FROM payload) "
                    "WHERE id = (SELECT id FROM payload)"
                ))

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'


@pytest.mark.parametrize(
    ('listener', 'args'),
    [
        (evaluation_safety._clear_read_only_metadata_flush_marker, (None,)),
        (evaluation_safety._clear_read_only_metadata_flush_marker_after_rollback, ()),
    ],
)
def test_metadata_marker_cleanup_does_not_mask_closed_connection(listener, args) -> None:
    class ClosedConnection:
        @property
        def info(self):
            raise RuntimeError('connection is closed')

    session = SimpleNamespace(info={
        '_evaluation_metadata_flush_connection': ClosedConnection(),
    })

    listener(session, *args)

    assert session.info == {}


def test_run_case_rejects_default_execution_user_outside_target_tenant(saas_app, monkeypatch) -> None:
    app, tokens = saas_app
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda *_args, **_kwargs: {'passStatus': 'pass'},
    )
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            evaluation.run_case(
                case_id='attendance_employee_anomaly',
                user_id='platform-user',
                run_user_id='beta-admin',
                tenant=tenant,
            )

    assert exc_info.value.code == 'AI_EVALUATION_RUN_USER_INVALID'


def test_large_evaluation_payload_preserves_run_identity_and_audit_metadata() -> None:
    payload = {
        'summary': 'large response',
        'verbose': 'x' * 70000,
        'evaluationAudit': {
            'requestId': 'eval-large',
            'provider': 'siliconflow',
            'status': 'success',
            'auditRecorded': True,
            'auditLogId': 'audit-large',
        },
        'evaluationRunAs': {
            'requestedByUserId': 'platform-user',
            'runAsUserId': 'tenant-admin',
        },
        'confirmationFlow': {
            'pendingConsumed': True,
            'wroteBeforeConfirmation': False,
        },
    }

    clipped = evaluation._clip_payload(payload)

    assert clipped['truncated'] is True
    assert clipped['evaluationAudit']['auditLogId'] == 'audit-large'
    assert clipped['evaluationRunAs'] == payload['evaluationRunAs']
    assert clipped['confirmationFlow']['pendingConsumed'] is True


def test_read_only_evaluation_scope_allows_assistant_metadata_rows(saas_app) -> None:
    app, tokens = saas_app
    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        session = AssistantSession(
            id='firewall-session',
            tenant_id=tokens['alpha_id'],
            user_id=run_user.id,
            title='Firewall Evaluation Session',
            messages=[],
            is_active=True,
            message_count=0,
        )
        audit = AssistantAuditLog(
            id='firewall-audit',
            tenant_id=tokens['alpha_id'],
            user_id=run_user.id,
            session_id=session.id,
            request_id='firewall-request',
            status='success',
        )
        ledger = AIUsageLedger(
            id='firewall-ledger',
            tenant_id=tokens['alpha_id'],
            user_id=run_user.id,
            resource_domain='assistant',
            use_case='evaluation',
            status='success',
            units=1,
            request_id='firewall-request',
            assistant_audit_log_id=audit.id,
        )
        evaluation_run = AssistantEvaluationRun(
            id='firewall-evaluation-run',
            tenant_id=tokens['alpha_id'],
            case_id='firewall-case',
            question='firewall question',
            user_id=run_user.id,
            session_id=session.id,
            request_id='firewall-request',
        )

        with evaluation_safety.evaluation_execution_scope(
            tenant=tenant,
            run_user=run_user,
            read_only=True,
        ):
            db.session.add_all([session, audit, ledger, evaluation_run])
            db.session.flush()
            session.title = 'Updated Evaluation Session'
            session.message_count = 1
            session.is_active = False
            db.session.flush()

        assert session.id == 'firewall-session'
        db.session.rollback()


def test_deactivate_evaluation_session_preserves_callers_unit_of_work(saas_app) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add_all([
            AssistantSession(
                id='deactivation-isolation-session',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                title='Evaluation Session',
                messages=[],
                is_active=True,
                message_count=0,
            ),
            User(
                id='deactivation-delete-user',
                tenant_id=tokens['alpha_id'],
                email='deactivation-delete@example.com',
                password_hash='unused',
                name='Delete User',
                role='employee',
                status='active',
            ),
        ])
        db.session.commit()

        dirty_user = db.session.get(User, 'alpha-admin')
        deleted_user = db.session.get(User, 'deactivation-delete-user')
        pending_user = User(
            id='deactivation-pending-user',
            tenant_id=tokens['alpha_id'],
            email='deactivation-pending@example.com',
            password_hash='unused',
            name='Pending User',
            role='employee',
            status='active',
        )
        dirty_user.name = 'Uncommitted Evaluation Caller Change'
        db.session.add(pending_user)
        db.session.delete(deleted_user)

        evaluation._deactivate_evaluation_session('deactivation-isolation-session')

        assert dirty_user in db.session.dirty
        assert pending_user in db.session.new
        assert deleted_user in db.session.deleted

        db.session.rollback()
        db.session.expire_all()
        assert db.session.get(User, 'alpha-admin').name == 'Alpha Admin'
        assert db.session.get(User, 'deactivation-pending-user') is None
        assert db.session.get(User, 'deactivation-delete-user') is not None
        assert db.session.get(AssistantSession, 'deactivation-isolation-session').is_active is False


def test_read_only_evaluation_scope_rejects_assistant_ownership_change(saas_app) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add(AssistantSession(
            id='firewall-existing-session',
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            title='Existing Evaluation Session',
            messages=[],
            is_active=True,
            message_count=0,
        ))
        db.session.commit()

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        session = db.session.get(AssistantSession, 'firewall-existing-session')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                session.user_id = 'platform-user'
                db.session.flush()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert db.session.get(AssistantSession, 'firewall-existing-session').user_id == 'alpha-admin'


def test_read_only_evaluation_scope_rejects_historical_metadata_rewrite(saas_app) -> None:
    app, tokens = saas_app
    with app.app_context():
        db.session.add(AssistantSession(
            id='firewall-historical-session',
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            title='Historical Session',
            messages=[],
            is_active=True,
            message_count=0,
        ))
        db.session.commit()

    with app.test_request_context('/api/platform/ai/evaluation-runs'):
        tenant = db.session.get(Tenant, tokens['alpha_id'])
        run_user = db.session.get(User, 'alpha-admin')
        session = db.session.get(AssistantSession, 'firewall-historical-session')

        with pytest.raises(evaluation_safety.EvaluationSafetyError) as exc_info:
            with evaluation_safety.evaluation_execution_scope(
                tenant=tenant,
                run_user=run_user,
                read_only=True,
            ):
                session.title = 'Rewritten Historical Session'
                db.session.flush()

        assert exc_info.value.code == 'AI_EVALUATION_READ_ONLY_VIOLATION'
        assert db.session.get(
            AssistantSession,
            'firewall-historical-session',
        ).title == 'Historical Session'


def test_confirmation_fixture_ids_are_tenant_scoped(saas_app) -> None:
    app, tokens = saas_app
    from services.assistant_core.approval_test_data import ensure_approval_confirmation_case

    with app.app_context():
        alpha = ensure_approval_confirmation_case(
            user_id='alpha-admin',
            tenant_id=tokens['alpha_id'],
            request_id='same-fixture-request',
        )
        beta = ensure_approval_confirmation_case(
            user_id='beta-admin',
            tenant_id=tokens['beta_id'],
            request_id='same-fixture-request',
        )

    assert alpha['employee_id'] != beta['employee_id']
    assert alpha['department_id'] != beta['department_id']


@pytest.mark.parametrize('limit', [0, True])
def test_route_maps_invalid_limit_to_stable_error_before_execution(
    saas_app,
    monkeypatch,
    limit,
) -> None:
    app, tokens = saas_app
    executed: list[str] = []
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={'tenantId': tokens['alpha_id'], 'limit': limit},
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_LIMIT_INVALID'
    assert executed == []


@pytest.mark.parametrize('mode', [None, '', '   ', 'write', 1, False, [], {}])
def test_route_rejects_invalid_evaluation_mode_before_execution(
    saas_app,
    monkeypatch,
    mode,
) -> None:
    app, tokens = saas_app
    executed: list[str] = []
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'mode': mode,
            'limit': 1,
        },
    )

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_EVALUATION_PAYLOAD_INVALID'
    assert executed == []


def test_read_only_mode_cannot_be_overridden_to_run_a_business_write_case(
    saas_app,
    monkeypatch,
) -> None:
    app, tokens = saas_app
    _configure_test_tenant(
        app,
        tokens['alpha_id'],
        disposable_slug=True,
        disposable_setting=True,
    )
    executed: list[str] = []
    monkeypatch.setattr(
        evaluation,
        '_run_and_record_case',
        lambda case, **_kwargs: executed.append(case['id']) or {'passStatus': 'pass'},
    )

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/evaluation-runs',
        json={
            'tenantId': tokens['alpha_id'],
            'mode': 'read_only',
            'caseId': WRITE_CASE_ID,
            'allowWrites': True,
        },
    )

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_EVALUATION_WRITES_NOT_ALLOWED'
    assert executed == []
