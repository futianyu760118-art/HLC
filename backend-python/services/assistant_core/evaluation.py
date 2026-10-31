"""Systematic HRM Copilot evaluation runner.

This module turns the evaluation YAML into auditable runtime records. It is not
meant to "grade by prompt"; it captures expectation gaps and root-cause
categories so fixes can be structural and retestable.
"""

from __future__ import annotations

import os
import uuid
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import yaml
from sqlalchemy.orm import Session as SQLAlchemySession

from models import AssistantAuditLog, AssistantEvaluationRun, AssistantSession, Tenant, User, db
from .evaluation_safety import (
    EvaluationSafetyError,
    assert_evaluation_safe,
    evaluation_execution_scope,
    resolve_evaluation_case_run_user,
)
from .model_settings import model_for_profile


CASES_PATH = Path(__file__).resolve().parent / 'evaluation_cases.yaml'
DEFAULT_MODEL_AUDIT_TIMEOUT_SECONDS = 60
DEFAULT_MODEL_AUDIT_MAX_TOKENS = 500
TAXONOMY_FALLBACK = [
    'intent_recognition',
    'entity_resolution',
    'time_range',
    'page_context',
    'data_retrieval',
    'module_relationship',
    'permission_policy',
    'tool_calling',
    'response_composition',
    'frontend_rendering',
    'test_data_consistency',
    'audit_confirmation',
]
VALID_EVALUATION_SIDE_EFFECTS = frozenset({'read_only', 'business_write'})
VALID_CONFIRMATION_FLOW_TYPES = frozenset({
    'notification', 'approval', 'interview', 'employee_change', 'salary_adjustment',
})
RETEST_REFERENCE_RE = re.compile(r'^[A-Za-z0-9._:-]{1,64}$')


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, '').strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'y', 'on', '是'}


def load_evaluation_suite() -> Dict[str, Any]:
    data = yaml.safe_load(CASES_PATH.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise EvaluationSafetyError(
            'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
            'evaluation suite root must be a mapping',
            status_code=500,
        )
    data.setdefault('version', 'assistant.evaluation.v1')
    data.setdefault('failure_taxonomy', TAXONOMY_FALLBACK)
    data.setdefault('cases', [])
    _validate_evaluation_case_classification(data['cases'])
    return data


def list_cases() -> List[Dict[str, Any]]:
    return load_evaluation_suite().get('cases') or []


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    return next((case for case in list_cases() if case.get('id') == case_id), None)


def run_case(
    *,
    case_id: str,
    user_id: str,
    run_user_id: str,
    tenant: Tenant,
    allow_writes: Any = False,
    client_context: Optional[Dict[str, Any]] = None,
    retest_of: Optional[str] = None,
) -> Dict[str, Any]:
    retest_of = _normalize_retest_reference(retest_of)
    case = get_case(case_id)
    if not case:
        raise EvaluationSafetyError(
            'AI_EVALUATION_CASE_INVALID',
            f'未知评估用例：{case_id}',
            case_ids=[case_id],
        )
    assert_evaluation_safe([case], tenant=tenant, allow_writes=allow_writes)
    default_run_user = db.session.get(User, run_user_id)
    effective_run_user = resolve_evaluation_case_run_user(
        case=case,
        tenant=tenant,
        default_user=default_run_user,
    )
    with evaluation_execution_scope(
        tenant=tenant,
        run_user=effective_run_user,
        read_only=case.get('side_effect') == 'read_only',
    ):
        return _run_and_record_case(
            case,
            user_id=user_id,
            run_user_id=effective_run_user.id,
            tenant_id=tenant.id,
            client_context=client_context,
            retest_of=retest_of,
        )


def run_suite(
    *,
    user_id: str,
    run_user_id: str,
    tenant: Tenant,
    allow_writes: Any = False,
    case_ids: Optional[List[str]] = None,
    limit: int = 8,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    selected = _select_evaluation_cases(case_ids=case_ids, limit=limit)
    assert_evaluation_safe(selected, tenant=tenant, allow_writes=allow_writes)
    default_run_user = db.session.get(User, run_user_id)
    run_users = [
        resolve_evaluation_case_run_user(
            case=case,
            tenant=tenant,
            default_user=default_run_user,
        )
        for case in selected
    ]
    results = []
    for case, case_run_user in zip(selected, run_users):
        with evaluation_execution_scope(
            tenant=tenant,
            run_user=case_run_user,
            read_only=case.get('side_effect') == 'read_only',
        ):
            results.append(_run_and_record_case(
                case,
                user_id=user_id,
                run_user_id=case_run_user.id,
                tenant_id=tenant.id,
                client_context=client_context,
            ))
    return {
        'total': len(results),
        'passed': sum(1 for item in results if item.get('passStatus') == 'pass'),
        'needsReview': sum(1 for item in results if item.get('passStatus') == 'needs_review'),
        'failed': sum(1 for item in results if item.get('passStatus') == 'fail'),
        'results': results,
    }


def _validate_evaluation_case_classification(cases: Any) -> None:
    if not isinstance(cases, list):
        raise EvaluationSafetyError(
            'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
            'evaluation cases must be a list with explicit side_effect values',
            status_code=500,
        )
    seen_case_ids: Set[str] = set()
    for case in cases:
        case_id = case.get('id') if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                'evaluation case id must be a non-empty string',
                status_code=500,
                case_ids=[case_id] if case_id is not None else None,
            )
        if case_id in seen_case_ids:
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'duplicate evaluation case id: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )
        seen_case_ids.add(case_id)
        if not isinstance(case, dict) or case.get('side_effect') not in VALID_EVALUATION_SIDE_EFFECTS:
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'evaluation case side_effect is invalid: {case_id or "<unknown>"}',
                status_code=500,
                case_ids=[case_id] if case_id else None,
            )
        side_effect = case['side_effect']
        requires_confirmation = case.get('requires_confirmation', False)
        if not isinstance(requires_confirmation, bool):
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'requires_confirmation must be boolean: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )
        confirmation_flow = case.get('confirmation_flow', False)
        if not isinstance(confirmation_flow, bool):
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'confirmation_flow must be boolean: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )
        flow_type = case.get('confirmation_flow_type')
        if flow_type is not None and (
            not isinstance(flow_type, str)
            or flow_type not in VALID_CONFIRMATION_FLOW_TYPES
        ):
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'confirmation_flow_type is invalid: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )
        if side_effect == 'read_only' and (confirmation_flow or flow_type is not None):
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'read-only evaluation cannot declare confirmation_flow: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )
        if side_effect == 'business_write' and (
            requires_confirmation is not True
            or confirmation_flow is not True
            or flow_type is None
        ):
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                f'business-write evaluation requires a typed confirmation_flow: {case_id}',
                status_code=500,
                case_ids=[case_id],
            )


def _normalize_retest_reference(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvaluationSafetyError(
            'AI_EVALUATION_RETEST_REFERENCE_INVALID',
            'retestOf 必须是长度不超过 64 的不透明标识',
        )
    normalized = value.strip()
    if not normalized:
        return None
    if not RETEST_REFERENCE_RE.fullmatch(normalized):
        raise EvaluationSafetyError(
            'AI_EVALUATION_RETEST_REFERENCE_INVALID',
            'retestOf 必须是长度不超过 64 的不透明标识',
        )
    return normalized


def _select_evaluation_cases(
    *,
    case_ids: Optional[List[str]],
    limit: int,
) -> List[Dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise EvaluationSafetyError(
            'AI_EVALUATION_LIMIT_INVALID',
            'evaluation limit must be an integer between 1 and 30',
        )

    if (
        case_ids is not None
        and (
            not isinstance(case_ids, list)
            or not case_ids
            or any(not isinstance(case_id, str) or not case_id.strip() for case_id in case_ids)
        )
    ):
        raise EvaluationSafetyError(
            'AI_EVALUATION_CASE_INVALID',
            'evaluation case ids must be a non-empty list of non-empty strings',
        )

    cases = list_cases()
    _validate_evaluation_case_classification(cases)
    if case_ids is None:
        selected = [case for case in cases if case.get('side_effect') == 'read_only']
        if not selected:
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_CONFIGURATION_INVALID',
                'evaluation suite has no read-only cases',
                status_code=500,
            )
    else:
        seen_ids: Set[str] = set()
        duplicate_ids: List[str] = []
        for case_id in case_ids:
            if case_id in seen_ids and case_id not in duplicate_ids:
                duplicate_ids.append(case_id)
            seen_ids.add(case_id)
        if duplicate_ids:
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_INVALID',
                f'duplicate evaluation case ids: {", ".join(map(str, duplicate_ids))}',
                case_ids=duplicate_ids,
            )
        by_id = {case.get('id'): case for case in cases}
        unknown_ids = [case_id for case_id in case_ids if case_id not in by_id]
        if unknown_ids:
            raise EvaluationSafetyError(
                'AI_EVALUATION_CASE_INVALID',
                f'unknown evaluation case ids: {", ".join(map(str, unknown_ids))}',
                case_ids=unknown_ids,
            )
        selected = [by_id[case_id] for case_id in case_ids]
    return selected[:limit]


def latest_runs(limit: int = 50, case_id: Optional[str] = None) -> List[Dict[str, Any]]:
    query = AssistantEvaluationRun.query
    if case_id:
        query = query.filter_by(case_id=case_id)
    rows = query.order_by(AssistantEvaluationRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [row.to_dict() for row in rows]


def run_detail(run_id: str) -> Optional[Dict[str, Any]]:
    row = AssistantEvaluationRun.query.get(run_id)
    return row.to_dict(include_payload=True) if row else None


def _run_and_record_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    run_user_id: str,
    tenant_id: str,
    client_context: Optional[Dict[str, Any]],
    retest_of: Optional[str] = None,
) -> Dict[str, Any]:
    from . import copilot_orchestrator

    request_id = _new_evaluation_request_id()
    effective_run_user_id = _resolve_case_user_id(case, run_user_id)
    evaluation_session_id = _create_evaluation_session(effective_run_user_id, case, request_id)
    row = AssistantEvaluationRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        case_id=case.get('id') or request_id,
        question=_case_question(case),
        scenario=case.get('scenario'),
        user_id=effective_run_user_id,
        session_id=evaluation_session_id,
        request_id=request_id,
        expected_modules=case.get('expected_modules') or [],
        expected_render_blocks=case.get('expected_render_blocks') or [],
        expected_behavior=case.get('expected_behavior') or [],
        actual_modules=[],
        actual_render_blocks=[],
        used_tools=[],
        evidence_sources=[],
        entity_summary=[],
        time_range={},
        response_summary='',
        pass_status='running',
        failure_categories=[],
        missing_expectations=[],
        root_cause_notes='',
        fix_plan='',
        retest_of=retest_of,
        response_payload={
            'evaluationExecution': {'status': 'running'},
            'evaluationRunAs': {
                'requestedByUserId': user_id,
                'runAsUserId': effective_run_user_id,
                'caseUserId': case.get('run_as_user_id') or case.get('user_id'),
                'caseUserEmail': case.get('run_as_user_email') or case.get('user_email'),
            },
        },
    )
    # Persist the run identity before a write-capable confirmation flow can
    # commit business data. A later provider/audit failure can then never leave
    # a durable write without a corresponding evaluation record.
    db.session.add(row)
    db.session.commit()
    context = _evaluation_client_context(case, client_context)
    try:
        if case.get('confirmation_flow'):
            response = _run_confirmation_flow_case(
                case,
                user_id=effective_run_user_id,
                tenant_id=tenant_id,
                session_id=evaluation_session_id,
                request_id=request_id,
                client_context=context,
            )
        elif case.get('turns'):
            response = _run_turns_case(
                case,
                user_id=effective_run_user_id,
                session_id=evaluation_session_id,
                request_id=request_id,
                client_context=context,
            )
        else:
            response = copilot_orchestrator.query(
                user_id=effective_run_user_id,
                session_id=evaluation_session_id,
                message=_case_question(case),
                request_id=request_id,
                client_context=context,
            )
        assessment = assess_response(case, response)
        model_audit = _record_evaluation_model_audit(
            case,
            response,
            assessment,
            user_id=effective_run_user_id,
            request_id=request_id,
        )
        assessment = _apply_model_audit_gate(assessment, model_audit)
        row = db.session.get(AssistantEvaluationRun, row.id)
        row.session_id = response.get('sessionId') or evaluation_session_id
        row.actual_modules = assessment['actualModules']
        row.actual_render_blocks = assessment['actualRenderBlocks']
        row.used_tools = assessment['usedTools']
        row.evidence_sources = assessment['evidenceSources']
        row.entity_summary = assessment['entitySummary']
        row.time_range = assessment['timeRange']
        row.response_summary = str(response.get('summary') or '')[:4000]
        row.pass_status = assessment['passStatus']
        row.failure_categories = assessment['failureCategories']
        row.missing_expectations = assessment['missingExpectations']
        row.root_cause_notes = assessment['rootCauseNotes']
        row.fix_plan = assessment['fixPlan']
        row.response_payload = _clip_payload({
            **response,
            'evaluationAudit': model_audit,
            'evaluationExecution': {'status': 'completed'},
            'evaluationRunAs': {
                'requestedByUserId': user_id,
                'runAsUserId': effective_run_user_id,
                'caseUserId': case.get('run_as_user_id') or case.get('user_id'),
                'caseUserEmail': case.get('run_as_user_email') or case.get('user_email'),
            },
        })
        result = row.to_dict()
        db.session.commit()
        return result
    except BaseException:
        db.session.rollback()
        _record_failed_evaluation_run(row.id)
        raise
    finally:
        _deactivate_evaluation_session(evaluation_session_id)


def _record_failed_evaluation_run(run_id: str) -> None:
    """Best-effort sanitized terminal evidence for an interrupted run."""

    try:
        row = db.session.get(AssistantEvaluationRun, run_id)
        if row is None:
            return
        row.pass_status = 'fail'
        row.failure_categories = ['execution_error']
        row.missing_expectations = []
        row.root_cause_notes = '评估执行在完成证据收集前失败；请按 requestId 核对脱敏运行日志。'
        row.fix_plan = '核对一次性测试企业中的已提交写入，完成清理后再重试该评估。'
        payload = dict(row.response_payload or {})
        payload['evaluationExecution'] = {
            'status': 'failed',
            'errorCode': 'AI_EVALUATION_EXECUTION_FAILED',
        }
        row.response_payload = payload
        db.session.commit()
    except Exception:
        # The already committed ``running`` row remains durable evidence even
        # if the failure-status update itself cannot be persisted.
        db.session.rollback()


def _new_evaluation_request_id() -> str:
    """Return a compact request id that stays within DB/index limits.

    Evaluation cases can have long descriptive ids, and confirmation/multi-turn
    flows append suffixes such as ``-prepare1`` or ``-duplicate``. Keep the base
    id short so every derived request id fits the 64-char audit/eval columns.
    """

    return f'eval-{uuid.uuid4().hex[:20]}'


def _run_preparation_turns(
    case: Dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
    default_question: str,
    render_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    from . import copilot_orchestrator

    raw_turns = case.get('preparation_turns') if isinstance(case.get('preparation_turns'), list) else []
    turns = raw_turns or [{'question': default_question}]
    response: Dict[str, Any] = {}
    responses: List[Dict[str, Any]] = []
    render_vars = render_vars or {}
    for index, raw_turn in enumerate(turns, start=1):
        if isinstance(raw_turn, dict):
            message = str(raw_turn.get('question') or raw_turn.get('message') or '').strip()
            turn_context = _evaluation_client_context(case, {
                **client_context,
                **(raw_turn.get('client_context') if isinstance(raw_turn.get('client_context'), dict) else {}),
            })
        else:
            message = str(raw_turn or '').strip()
            turn_context = client_context
        for key, value in render_vars.items():
            message = message.replace(f'{{{key}}}', value)
        if not message:
            continue
        response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=session_id,
            message=message,
            request_id=f'{request_id}-prepare{index}' if raw_turns else f'{request_id}-prepare',
            client_context=turn_context,
        )
        responses.append(response)
    if responses:
        response = dict(response)
        response['_preparationResponses'] = responses
    return response


def _evaluation_interview_schedule_at(request_id: str) -> str:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex
    minute = (int(digest[:2], 16) % 50) + 5
    return f'2026-06-03 15:{minute:02d}'


def _run_confirmation_flow_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    tenant_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a real prepare-confirm-write flow for side-effect actions."""
    flow_type = str(case.get('confirmation_flow_type') or '').strip() or (
        'approval' if case.get('id') == 'confirmed_approval_decision_execution' else 'notification'
    )
    if flow_type == 'approval':
        return _run_approval_confirmation_flow_case(
            case,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            request_id=request_id,
            client_context=client_context,
        )
    if flow_type == 'interview':
        return _run_interview_confirmation_flow_case(
            case,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            request_id=request_id,
            client_context=client_context,
        )
    if flow_type in {'employee_change', 'salary_adjustment'}:
        return _run_employee_change_confirmation_flow_case(
            case,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            request_id=request_id,
            client_context=client_context,
        )

    from models import Notification
    from . import copilot_orchestrator, memory
    from .approval_test_data import ensure_attendance_notification_confirmation_case

    ensure_attendance_notification_confirmation_case(
        user_id=user_id,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    before_ids = {row.id for row in Notification.query.all()}
    prepare_response = _run_preparation_turns(
        case,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        client_context=client_context,
        default_question=case.get('preparation_question') or case.get('question') or '',
    )
    action_payload = _first_confirmation_payload(prepare_response)
    action_id = _extract_action_id(action_payload)
    immediate_ids = {row.id for row in Notification.query.all()}
    wrote_before_confirmation = bool(immediate_ids - before_ids)

    confirm_response: Dict[str, Any] = {}
    duplicate_response: Dict[str, Any] = {}
    created_notifications: List[Dict[str, Any]] = []
    duplicate_created_notifications: List[Dict[str, Any]] = []
    pending_after_confirm = None
    if action_payload and action_id:
        confirm_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-confirm',
            client_context=client_context,
        )
        after_ids = {row.id for row in Notification.query.all()}
        new_ids = sorted(after_ids - immediate_ids)
        if new_ids:
            created_notifications = [
                row.to_dict()
                for row in Notification.query.filter(Notification.id.in_(new_ids)).all()
            ]
        pending_after_confirm = memory.get_pending_action(
            user_id,
            confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            action_id,
        )
        before_duplicate_ids = {row.id for row in Notification.query.all()}
        duplicate_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-duplicate',
            client_context=client_context,
        )
        after_duplicate_ids = {row.id for row in Notification.query.all()}
        duplicate_ids = sorted(after_duplicate_ids - before_duplicate_ids)
        if duplicate_ids:
            duplicate_created_notifications = [
                row.to_dict()
                for row in Notification.query.filter(Notification.id.in_(duplicate_ids)).all()
            ]

    combined = _merge_flow_response(
        prepare_response,
        confirm_response,
        duplicate_response,
        action_payload=action_payload,
        action_id=action_id,
        wrote_before_confirmation=wrote_before_confirmation,
        created_notifications=created_notifications,
        pending_consumed=pending_after_confirm is None if action_id else False,
        duplicate_created_notifications=duplicate_created_notifications,
    )
    return combined


def _run_interview_confirmation_flow_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    tenant_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
) -> Dict[str, Any]:
    from models import Interview
    from . import copilot_orchestrator, memory
    from .approval_test_data import ensure_interview_confirmation_case

    ensure_interview_confirmation_case(
        user_id=user_id,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    before_ids = {row.id for row in Interview.query.all()}
    prepare_question = str(
        case.get('preparation_question')
        or case.get('question')
        or '给电子工程师岗位第二位候选人安排{schedule_at}面试'
    )
    schedule_at = _evaluation_interview_schedule_at(request_id)
    prepare_response = _run_preparation_turns(
        case,
        user_id=user_id,
        session_id=session_id,
        client_context=client_context,
        request_id=request_id,
        default_question=prepare_question,
        render_vars={'schedule_at': schedule_at},
    )
    db.session.expire_all()
    immediate_ids = {row.id for row in Interview.query.all()}
    wrote_before_confirmation = bool(immediate_ids - before_ids)

    action_payload = _first_confirmation_payload(prepare_response)
    action_id = _extract_action_id(action_payload)
    confirm_response: Dict[str, Any] = {}
    duplicate_response: Dict[str, Any] = {}
    created_interviews: List[Dict[str, Any]] = []
    duplicate_created_interviews: List[Dict[str, Any]] = []
    pending_after_confirm = None
    if action_payload and action_id:
        confirm_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=prepare_response.get('sessionId'),
            message=action_payload.replace('明天下午三点', schedule_at),
            request_id=f'{request_id}-confirm',
            client_context=client_context,
        )
        pending_after_confirm = memory.get_pending_action(
            user_id,
            confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            action_id,
        )
        db.session.expire_all()
        after_confirm_ids = {row.id for row in Interview.query.all()}
        new_ids = sorted(after_confirm_ids - immediate_ids)
        if new_ids:
            created_interviews = [
                row.to_dict()
                for row in Interview.query.filter(Interview.id.in_(new_ids)).all()
            ]
        before_duplicate_ids = {row.id for row in Interview.query.all()}
        duplicate_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            message=action_payload.replace('明天下午三点', schedule_at),
            request_id=f'{request_id}-duplicate',
            client_context=client_context,
        )
        db.session.expire_all()
        after_duplicate_ids = {row.id for row in Interview.query.all()}
        duplicate_ids = sorted(after_duplicate_ids - before_duplicate_ids)
        if duplicate_ids:
            duplicate_created_interviews = [
                row.to_dict()
                for row in Interview.query.filter(Interview.id.in_(duplicate_ids)).all()
            ]

    evidence = []
    if created_interviews:
        first = created_interviews[0]
        evidence.append({
            'module': 'interviews',
            'recordType': 'interviews',
            'recordId': first.get('id'),
            'title': f'确认后创建面试 {len(created_interviews)} 场',
            'url': '/interview-manage',
        })
        if first.get('resumeId'):
            evidence.append({
                'module': 'resumes',
                'recordType': 'resumes',
                'recordId': first.get('resumeId'),
                'title': '面试关联简历',
                'url': f'/resume-detail?resumeId={first.get("resumeId")}',
            })
        if first.get('jobId'):
            evidence.append({
                'module': 'jobs',
                'recordType': 'jobs',
                'recordId': first.get('jobId'),
                'title': '面试关联岗位',
                'url': f'/job-detail?jobId={first.get("jobId")}',
            })

    combined = _merge_flow_response(
        prepare_response,
        confirm_response,
        duplicate_response,
        action_payload=action_payload,
        action_id=action_id,
        wrote_before_confirmation=wrote_before_confirmation,
        created_notifications=[],
        pending_consumed=pending_after_confirm is None if action_id else False,
        duplicate_created_notifications=[],
        confirmed_write_label='确认后已创建面试',
        confirmed_write_ok=bool(created_interviews),
    )
    status_widget = {
        'type': 'status_badges',
        'title': '面试确认执行验证',
        'items': [
            {'label': '确认前未写入', 'status': 'ok' if not wrote_before_confirmation else 'error'},
            {'label': '面试记录已创建', 'value': len(created_interviews), 'status': 'ok' if created_interviews else 'error'},
            {'label': '重复确认未重复创建', 'status': 'ok' if not duplicate_created_interviews else 'error'},
            {'label': '待确认动作已消费', 'status': 'ok' if pending_after_confirm is None and action_id else 'error'},
        ],
    }
    source_widget = {
        'type': 'source_citations',
        'title': '面试确认执行证据',
        'sources': evidence,
    }
    combined.setdefault('widgets', []).extend([status_widget, source_widget])
    combined.setdefault('renderBlocks', []).extend([
        {'kind': 'status', 'source': 'widget', 'payload': status_widget},
        {'kind': 'sources', 'source': 'widget', 'payload': source_widget},
    ])
    copilot = dict(combined.get('copilot') or {})
    copilot['evidence'] = _unique_evidence((copilot.get('evidence') or []) + evidence)
    combined['copilot'] = copilot
    combined['confirmationFlow'] = {
        **(combined.get('confirmationFlow') or {}),
        'flowType': 'interview',
        'createdInterviews': created_interviews,
        'createdInterviewCount': len(created_interviews),
        'duplicateCreatedInterviews': len(duplicate_created_interviews),
        'pendingConsumed': pending_after_confirm is None if action_id else False,
        'wroteBeforeConfirmation': wrote_before_confirmation,
    }
    meta = dict(combined.get('meta') or {})
    meta['confirmationFlow'] = combined['confirmationFlow']
    combined['meta'] = meta
    return combined


def _run_approval_confirmation_flow_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    tenant_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
) -> Dict[str, Any]:
    from models import ApprovalInstance, ApprovalRecord, EmployeeRequest, OperationLog
    from . import copilot_orchestrator, memory
    from .approval_test_data import ensure_approval_confirmation_case

    seeded = ensure_approval_confirmation_case(user_id=user_id, tenant_id=tenant_id, request_id=request_id)
    approval_id = seeded['approval_id']
    request_id_value = seeded['request_id']
    expected_action = str(case.get('expected_approval_action') or 'approve').strip().lower()
    if expected_action in {'approved', 'pass', 'agree', '同意', '通过', '批准'}:
        expected_action = 'approve'
    elif expected_action in {'rejected', 'deny', '驳回', '拒绝'}:
        expected_action = 'reject'
    if expected_action not in {'approve', 'reject'}:
        expected_action = 'approve'
    expected_approval_status = str(
        case.get('expected_approval_status')
        or ('approved' if expected_action == 'approve' else 'rejected')
    )
    expected_business_status = str(case.get('expected_business_status') or expected_approval_status)
    action_label = '通过' if expected_action == 'approve' else '驳回'
    prepare_question = str(
        case.get('preparation_question') or case.get('question') or f'请{action_label}审批 {{approval_id}}'
    ).replace('{approval_id}', approval_id)
    approval_before = ApprovalInstance.query.get(approval_id)
    before_status = approval_before.status if approval_before else None
    records_before = ApprovalRecord.query.filter_by(approval_id=approval_id).count()
    logs_before = OperationLog.query.filter_by(module='approval', target_id=approval_id).count()

    prepare_response = copilot_orchestrator.query(
        user_id=user_id,
        session_id=session_id,
        message=prepare_question,
        request_id=f'{request_id}-prepare',
        client_context=client_context,
    )
    db.session.expire_all()
    approval_after_prepare = ApprovalInstance.query.get(approval_id)
    request_after_prepare = EmployeeRequest.query.get(request_id_value)
    wrote_before_confirmation = bool(
        (approval_after_prepare and approval_after_prepare.status != before_status)
        or (request_after_prepare and request_after_prepare.status != 'pending')
        or ApprovalRecord.query.filter_by(approval_id=approval_id).count() > records_before
    )

    action_payload = _first_confirmation_payload(prepare_response)
    action_id = _extract_action_id(action_payload)
    confirm_response: Dict[str, Any] = {}
    duplicate_response: Dict[str, Any] = {}
    pending_after_confirm = None
    records_after_confirm = records_before
    if action_payload and action_id:
        confirm_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-confirm',
            client_context=client_context,
        )
        pending_after_confirm = memory.get_pending_action(
            user_id,
            confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            action_id,
        )
        db.session.expire_all()
        records_after_confirm = ApprovalRecord.query.filter_by(approval_id=approval_id).count()
        duplicate_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-duplicate',
            client_context=client_context,
        )

    db.session.expire_all()
    approval_after = ApprovalInstance.query.get(approval_id)
    request_after = EmployeeRequest.query.get(request_id_value)
    records_after = ApprovalRecord.query.filter_by(approval_id=approval_id).count()
    logs_after = OperationLog.query.filter_by(module='approval', target_id=approval_id).count()
    record_rows = [
        row.to_dict()
        for row in ApprovalRecord.query.filter_by(approval_id=approval_id).order_by(ApprovalRecord.created_at.asc()).all()
    ]
    duplicate_record_count = ApprovalRecord.query.filter_by(approval_id=approval_id).count()

    evidence = []
    if approval_after:
        evidence.append({
            'module': 'approvals',
            'recordType': 'approval_instances',
            'recordId': approval_after.id,
            'title': approval_after.title,
            'url': '/approval-center',
        })
    if request_after:
        evidence.append({
            'module': 'leave_requests',
            'recordType': 'employee_requests',
            'recordId': request_after.id,
            'title': request_after.title,
            'url': '/employee-requests',
        })
    if logs_after > logs_before:
        evidence.append({
            'module': 'operation_logs',
            'recordType': 'operation_logs',
            'recordId': approval_id,
            'title': 'AI 确认审批操作审计',
            'url': '/operation-logs',
        })

    combined = _merge_flow_response(
        prepare_response,
        confirm_response,
        duplicate_response,
        action_payload=action_payload,
        action_id=action_id,
        wrote_before_confirmation=wrote_before_confirmation,
        created_notifications=[],
        pending_consumed=pending_after_confirm is None if action_id else False,
        duplicate_created_notifications=[],
        confirmed_write_label=f'确认后已{action_label}审批',
        confirmed_write_ok=bool(
            approval_after
            and request_after
            and approval_after.status == expected_approval_status
            and request_after.status == expected_business_status
            and records_after > records_before
            and logs_after > logs_before
        ),
    )
    status_widget = {
        'type': 'status_badges',
        'title': '审批确认执行验证',
        'items': [
            {'label': '确认前未写入', 'status': 'ok' if not wrote_before_confirmation else 'error'},
            {'label': f'审批已{action_label}', 'value': approval_after.status if approval_after else '—', 'status': 'ok' if approval_after and approval_after.status == expected_approval_status else 'error'},
            {'label': '业务申请已同步', 'value': request_after.status if request_after else '—', 'status': 'ok' if request_after and request_after.status == expected_business_status else 'error'},
            {'label': '审批记录写入', 'value': records_after - records_before, 'status': 'ok' if records_after > records_before else 'error'},
            {'label': '操作审计写入', 'value': logs_after - logs_before, 'status': 'ok' if logs_after > logs_before else 'error'},
        ],
    }
    source_widget = {
        'type': 'source_citations',
        'title': '审批确认执行证据',
        'sources': evidence,
    }
    combined.setdefault('widgets', []).extend([status_widget, source_widget])
    combined.setdefault('renderBlocks', []).extend([
        {'kind': 'status', 'source': 'widget', 'payload': status_widget},
        {'kind': 'sources', 'source': 'widget', 'payload': source_widget},
    ])
    copilot = dict(combined.get('copilot') or {})
    copilot['evidence'] = _unique_evidence((copilot.get('evidence') or []) + evidence)
    combined['copilot'] = copilot
    combined['confirmationFlow'] = {
        **(combined.get('confirmationFlow') or {}),
        'flowType': 'approval',
        'approvalId': approval_id,
        'businessRequestId': request_id_value,
        'expectedAction': expected_action,
        'expectedApprovalStatus': expected_approval_status,
        'expectedBusinessStatus': expected_business_status,
        'confirmed': bool(confirm_response),
        'wroteBeforeConfirmation': wrote_before_confirmation,
        'approvalStatus': approval_after.status if approval_after else None,
        'businessStatus': request_after.status if request_after else None,
        'createdApprovalRecords': record_rows,
        'createdOperationLogs': max(0, logs_after - logs_before),
        'pendingConsumed': pending_after_confirm is None if action_id else False,
        'duplicateCreatedApprovalRecords': max(0, duplicate_record_count - records_after_confirm),
        'duplicateResponse': {
            'summary': duplicate_response.get('summary'),
            'sessionId': duplicate_response.get('sessionId'),
        },
    }
    meta = dict(combined.get('meta') or {})
    meta['confirmationFlow'] = combined['confirmationFlow']
    combined['meta'] = meta
    return combined


def _run_employee_change_confirmation_flow_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    tenant_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
) -> Dict[str, Any]:
    from models import ApprovalInstance, Employee, EmployeeChange, OperationLog, SalaryProfile
    from . import copilot_orchestrator, memory
    from .approval_test_data import (
        ensure_employee_change_confirmation_case,
        ensure_salary_adjustment_confirmation_case,
    )

    flow_type = str(case.get('confirmation_flow_type') or 'employee_change')
    if flow_type == 'salary_adjustment':
        seeded = ensure_salary_adjustment_confirmation_case(user_id=user_id, tenant_id=tenant_id, request_id=request_id)
    else:
        seeded = ensure_employee_change_confirmation_case(user_id=user_id, tenant_id=tenant_id, request_id=request_id)
    employee_id = seeded['employee_id']
    employee_name = seeded['employee_name']
    target_department_name = seeded.get('target_department_name') or seeded.get('department_name') or ''
    salary_adjustment = str(seeded.get('salary_adjustment') or case.get('salary_adjustment') or '1800')
    employee_before = Employee.query.get(employee_id)
    before_department_id = employee_before.department_id if employee_before else None
    salary_before = SalaryProfile.query.filter_by(employee_id=employee_id).first()
    salary_before_payload = salary_before.to_dict() if salary_before else None
    before_change_ids = {row.id for row in EmployeeChange.query.filter_by(employee_id=employee_id).all()}
    before_approval_ids = {
        row.id
        for row in ApprovalInstance.query.filter_by(business_type='employee_change').all()
    }
    logs_before = OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count()

    prepare_question = str(
        case.get('preparation_question')
        or f'如果把{employee_name}调到{target_department_name}，会影响哪些岗位、薪资、通知和审批？'
    ).replace('{employee_name}', employee_name).replace('{target_department}', target_department_name).replace('{salary_adjustment}', salary_adjustment)
    prepare_response = copilot_orchestrator.query(
        user_id=user_id,
        session_id=session_id,
        message=prepare_question,
        request_id=f'{request_id}-prepare',
        client_context=client_context,
    )
    db.session.expire_all()
    after_prepare_change_ids = {row.id for row in EmployeeChange.query.filter_by(employee_id=employee_id).all()}
    after_prepare_employee = Employee.query.get(employee_id)
    salary_after_prepare = SalaryProfile.query.filter_by(employee_id=employee_id).first()
    salary_after_prepare_payload = salary_after_prepare.to_dict() if salary_after_prepare else None
    wrote_before_confirmation = bool(
        after_prepare_change_ids - before_change_ids
        or (after_prepare_employee and after_prepare_employee.department_id != before_department_id)
        or (salary_after_prepare_payload != salary_before_payload)
    )

    action_payload = _first_confirmation_payload(prepare_response)
    action_id = _extract_action_id(action_payload)
    confirm_response: Dict[str, Any] = {}
    duplicate_response: Dict[str, Any] = {}
    pending_after_confirm = None
    created_change_rows: List[Dict[str, Any]] = []
    created_approval_rows: List[Dict[str, Any]] = []
    if action_payload and action_id:
        confirm_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-confirm',
            client_context=client_context,
        )
        pending_after_confirm = memory.get_pending_action(
            user_id,
            confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            action_id,
        )
        db.session.expire_all()
        after_confirm_change_ids = {row.id for row in EmployeeChange.query.filter_by(employee_id=employee_id).all()}
        new_change_ids = sorted(after_confirm_change_ids - after_prepare_change_ids)
        if new_change_ids:
            created_change_rows = [
                row.to_dict()
                for row in EmployeeChange.query.filter(EmployeeChange.id.in_(new_change_ids)).all()
            ]
            created_approval_rows = [
                row.to_dict()
                for row in ApprovalInstance.query.filter(
                    ApprovalInstance.business_type == 'employee_change',
                    ApprovalInstance.business_id.in_(new_change_ids),
                ).all()
            ]
        duplicate_response = copilot_orchestrator.query(
            user_id=user_id,
            session_id=confirm_response.get('sessionId') or prepare_response.get('sessionId'),
            message=action_payload,
            request_id=f'{request_id}-duplicate',
            client_context=client_context,
        )

    db.session.expire_all()
    employee_after = Employee.query.get(employee_id)
    salary_after = SalaryProfile.query.filter_by(employee_id=employee_id).first()
    salary_after_payload = salary_after.to_dict() if salary_after else None
    all_change_ids = {row.id for row in EmployeeChange.query.filter_by(employee_id=employee_id).all()}
    all_approval_ids = {
        row.id
        for row in ApprovalInstance.query.filter_by(business_type='employee_change').all()
    }
    logs_after = OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count()
    duplicate_change_count = max(0, len(all_change_ids - after_prepare_change_ids) - len(created_change_rows))
    duplicate_approval_count = max(0, len(all_approval_ids - before_approval_ids) - len(created_approval_rows))
    direct_employee_update = bool(employee_after and employee_after.department_id != before_department_id)
    direct_salary_update = bool(salary_after_payload != salary_before_payload)
    expected_salary_delta = _decimal_or_none(salary_adjustment) if flow_type == 'salary_adjustment' else None
    created_salary_adjustment_amounts = [
        _decimal_or_none(row.get('salaryAdjustment') or row.get('salary_adjustment'))
        for row in created_change_rows
        if str(row.get('changeType') or row.get('change_type') or '') == 'salary_adjustment'
    ]
    created_salary_adjustment = any(
        amount is not None and amount != Decimal('0')
        for amount in created_salary_adjustment_amounts
    )
    salary_adjustment_amount_matches = bool(
        flow_type != 'salary_adjustment'
        or (
            expected_salary_delta is not None
            and any(amount == expected_salary_delta for amount in created_salary_adjustment_amounts)
        )
    )

    evidence = []
    if employee_after:
        evidence.append({
            'module': 'employees',
            'recordType': 'employees',
            'recordId': employee_after.id,
            'title': f'员工档案：{employee_after.name}',
            'url': '/hrm/employees',
        })
    if created_change_rows:
        evidence.append({
            'module': 'employee_changes',
            'recordType': 'employee_changes',
            'recordId': created_change_rows[0].get('id'),
            'title': 'AI 确认后提交调薪异动申请' if flow_type == 'salary_adjustment' else 'AI 确认后提交员工异动申请',
            'url': '/hrm/employee-changes',
        })
    if flow_type == 'salary_adjustment' and salary_after:
        evidence.append({
            'module': 'salary_profiles',
            'recordType': 'salary_profiles',
            'recordId': salary_after.id,
            'title': '薪资档案（确认后未直接修改）',
            'url': '/salary-profiles',
        })
    if created_approval_rows:
        evidence.append({
            'module': 'approvals',
            'recordType': 'approval_instances',
            'recordId': created_approval_rows[0].get('id'),
            'title': 'AI 确认后创建员工异动审批',
            'url': '/approval-center',
        })
    if logs_after > logs_before:
        evidence.append({
            'module': 'operation_logs',
            'recordType': 'operation_logs',
            'recordId': created_change_rows[0].get('id') if created_change_rows else employee_id,
            'title': 'AI 确认提交员工异动操作审计',
            'url': '/operation-logs',
        })

    combined = _merge_flow_response(
        prepare_response,
        confirm_response,
        duplicate_response,
        action_payload=action_payload,
        action_id=action_id,
        wrote_before_confirmation=wrote_before_confirmation,
        created_notifications=[],
        pending_consumed=pending_after_confirm is None if action_id else False,
        duplicate_created_notifications=[],
        confirmed_write_label='确认后已提交调薪审批' if flow_type == 'salary_adjustment' else '确认后已提交异动',
        confirmed_write_ok=bool(
            created_change_rows
            and created_approval_rows
            and (created_salary_adjustment if flow_type == 'salary_adjustment' else True)
            and (salary_adjustment_amount_matches if flow_type == 'salary_adjustment' else True)
            and not direct_salary_update
        ),
    )
    status_widget = {
        'type': 'status_badges',
        'title': '调薪确认执行验证' if flow_type == 'salary_adjustment' else '员工异动确认执行验证',
        'items': [
            {'label': '确认前未写入', 'status': 'ok' if not wrote_before_confirmation else 'error'},
            {'label': '调薪异动已创建' if flow_type == 'salary_adjustment' else '异动申请已创建', 'value': len(created_change_rows), 'status': 'ok' if created_change_rows else 'error'},
            {'label': '调薪金额匹配', 'value': salary_adjustment if flow_type == 'salary_adjustment' else None, 'status': 'ok' if salary_adjustment_amount_matches else 'error'} if flow_type == 'salary_adjustment' else None,
            {'label': '审批实例已创建', 'value': len(created_approval_rows), 'status': 'ok' if created_approval_rows else 'error'},
            {'label': '员工档案未直接变更', 'status': 'ok' if not direct_employee_update else 'error'},
            {'label': '薪资档案未直接变更', 'status': 'ok' if not direct_salary_update else 'error'} if flow_type == 'salary_adjustment' else None,
            {'label': '操作审计写入', 'value': logs_after - logs_before, 'status': 'ok' if logs_after > logs_before else 'error'},
        ],
    }
    status_widget['items'] = [item for item in status_widget['items'] if item]
    source_widget = {
        'type': 'source_citations',
        'title': '调薪确认执行证据' if flow_type == 'salary_adjustment' else '员工异动确认执行证据',
        'sources': evidence,
    }
    combined.setdefault('widgets', []).extend([status_widget, source_widget])
    combined.setdefault('renderBlocks', []).extend([
        {'kind': 'status', 'source': 'widget', 'payload': status_widget},
        {'kind': 'sources', 'source': 'widget', 'payload': source_widget},
    ])
    copilot = dict(combined.get('copilot') or {})
    copilot['evidence'] = _unique_evidence((copilot.get('evidence') or []) + evidence)
    combined['copilot'] = copilot
    combined['confirmationFlow'] = {
        **(combined.get('confirmationFlow') or {}),
        'flowType': flow_type,
        'employeeId': employee_id,
        'createdEmployeeChanges': created_change_rows,
        'createdApprovals': created_approval_rows,
        'createdOperationLogs': max(0, logs_after - logs_before),
        'createdSalaryAdjustment': created_salary_adjustment,
        'expectedSalaryAdjustment': str(expected_salary_delta) if expected_salary_delta is not None else None,
        'createdSalaryAdjustmentAmounts': [
            str(amount) for amount in created_salary_adjustment_amounts if amount is not None
        ],
        'salaryAdjustmentAmountMatches': salary_adjustment_amount_matches,
        'salaryProfileBefore': salary_before_payload,
        'salaryProfileAfter': salary_after_payload,
        'directSalaryUpdate': direct_salary_update,
        'employeeDepartmentBefore': before_department_id,
        'employeeDepartmentAfter': employee_after.department_id if employee_after else None,
        'directEmployeeUpdate': direct_employee_update,
        'duplicateCreatedEmployeeChanges': duplicate_change_count,
        'duplicateCreatedApprovals': duplicate_approval_count,
    }
    meta = dict(combined.get('meta') or {})
    meta['confirmationFlow'] = combined['confirmationFlow']
    combined['meta'] = meta
    return combined


def _run_turns_case(
    case: Dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    request_id: str,
    client_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a real multi-turn conversation in one isolated evaluation session."""
    from . import copilot_orchestrator

    responses: List[Dict[str, Any]] = []
    turns = case.get('turns') if isinstance(case.get('turns'), list) else []
    for index, raw_turn in enumerate(turns, start=1):
        if isinstance(raw_turn, dict):
            message = str(raw_turn.get('question') or raw_turn.get('message') or '').strip()
            turn_context = _evaluation_client_context(case, {
                **client_context,
                **(raw_turn.get('client_context') if isinstance(raw_turn.get('client_context'), dict) else {}),
            })
        else:
            message = str(raw_turn or '').strip()
            turn_context = client_context
        if not message:
            continue
        responses.append(copilot_orchestrator.query(
            user_id=user_id,
            session_id=session_id,
            message=message,
            request_id=f'{request_id}-turn{index}',
            client_context=turn_context,
        ))
    if not responses:
        return copilot_orchestrator.query(
            user_id=user_id,
            session_id=session_id,
            message=_case_question(case),
            request_id=request_id,
            client_context=client_context,
        )
    return _merge_turn_responses(responses)


def _resolve_case_user_id(case: Dict[str, Any], fallback_user_id: str) -> str:
    return fallback_user_id


def _create_evaluation_session(user_id: str, case: Dict[str, Any], request_id: str) -> str:
    session_id = str(uuid.uuid4())
    row = AssistantSession(
        id=session_id,
        user_id=user_id,
        title=f'Copilot评估：{case.get("id") or request_id}',
        messages=[],
        is_active=True,
        message_count=0,
    )
    db.session.add(row)
    db.session.commit()
    return session_id


def _deactivate_evaluation_session(session_id: Optional[str]) -> None:
    if not session_id:
        return
    try:
        with SQLAlchemySession(bind=db.engine) as isolated_session:
            with isolated_session.begin():
                row = isolated_session.get(AssistantSession, session_id)
                if row:
                    row.is_active = False
    except Exception:
        pass


def _case_question(case: Dict[str, Any]) -> str:
    if case.get('question'):
        return str(case.get('question') or '')
    turns = case.get('turns') if isinstance(case.get('turns'), list) else []
    parts: List[str] = []
    for item in turns:
        if isinstance(item, dict):
            text = str(item.get('question') or item.get('message') or '').strip()
        else:
            text = str(item or '').strip()
        if text:
            parts.append(text)
    return ' / '.join(parts)


def _merge_turn_responses(responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    final = dict(responses[-1])
    widgets: List[Dict[str, Any]] = []
    render_blocks: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []
    worksets: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    used: List[str] = []
    summaries: List[str] = []
    for idx, response in enumerate(responses, start=1):
        summaries.append(f'第 {idx} 轮：{str(response.get("summary") or "").strip()}')
        widgets.extend(widget for widget in response.get('widgets') or [] if isinstance(widget, dict))
        render_blocks.extend(block for block in response.get('renderBlocks') or [] if isinstance(block, dict))
        entities.extend(ent for ent in response.get('entities') or [] if isinstance(ent, dict))
        worksets.extend(ws for ws in response.get('worksets') or [] if isinstance(ws, dict))
        evidence.extend(_evidence_sources(response))
        used.extend(str(item) for item in ((response.get('meta') or {}).get('usedSkills') or []) if item)
    final['summary'] = '\n'.join(summaries)
    final['widgets'] = widgets
    final['renderBlocks'] = render_blocks
    final['entities'] = _unique_entities(entities)
    if worksets:
        final['worksets'] = worksets
    copilot = dict(final.get('copilot') or {})
    copilot['evidence'] = _unique_evidence((copilot.get('evidence') or []) + evidence)
    final['copilot'] = copilot
    meta = dict(final.get('meta') or {})
    meta['usedSkills'] = _unique([*used, *(str(item) for item in (meta.get('usedSkills') or []) if item)])
    meta['conversationTurns'] = len(responses)
    final['meta'] = meta
    final['conversationFlow'] = {
        'turnCount': len(responses),
        'turns': [
            {
                'index': idx,
                'summary': response.get('summary'),
                'sessionId': response.get('sessionId'),
                'renderBlocks': _actual_render_blocks(response),
                'usedTools': _used_tools(response),
                'selectedSkill': _selected_skill(response),
                'routePath': (response.get('copilot') or {}).get('routePath')
                if isinstance(response.get('copilot'), dict) else None,
            }
            for idx, response in enumerate(responses, start=1)
        ],
    }
    return final


def _record_evaluation_model_audit(
    case: Dict[str, Any],
    response: Dict[str, Any],
    assessment: Dict[str, Any],
    *,
    user_id: str,
    request_id: str,
) -> Dict[str, Any]:
    """Ask the configured model to review this real evaluation run.

    The call intentionally goes through the normal LLM client, so it creates
    the same assistant_audit_logs row as production questions. If the provider
    key is missing, the LLM client records an error audit row instead of
    pretending the review succeeded.
    """
    from . import llm_client
    from .schemas import AssistantContext

    ctx = AssistantContext(
        user_id=user_id,
        role='admin',
        session_id=response.get('sessionId'),
        request_id=request_id,
        audit_user_id=user_id,
        audit_session_id=response.get('sessionId'),
        client_context={
            'path': '/ai-model-settings',
            'moduleId': 'ai-model-settings',
            'moduleName': 'AI 模型管理',
            'evaluationCaseId': case.get('id'),
        },
    )
    prompt_payload = {
        'testMarker': f'Copilot评估测试-{case.get("id")}-{request_id}',
        'caseId': case.get('id'),
        'scenario': case.get('scenario'),
        'question': case.get('question'),
        'expectedModules': case.get('expected_modules') or [],
        'expectedRenderBlocks': case.get('expected_render_blocks') or [],
        'actualModules': assessment.get('actualModules') or [],
        'actualRenderBlocks': assessment.get('actualRenderBlocks') or [],
        'usedTools': assessment.get('usedTools') or [],
        'passStatus': assessment.get('passStatus'),
        'missingExpectations': assessment.get('missingExpectations') or [],
        'failureCategories': assessment.get('failureCategories') or [],
        'rootCauseNotes': assessment.get('rootCauseNotes'),
        'fixPlan': assessment.get('fixPlan'),
        'summary': str(response.get('summary') or '')[:1600],
    }
    messages = [
        {
            'role': 'system',
            'content': (
                '你是 HRM Copilot 2.0 的系统化评估审计员。'
                '请基于给定的真实运行结果做结构性复盘，不能编造额外系统数据。'
                '回答需包含：测试结论、主要缺口、根因分类、下一步结构性修复建议。'
            ),
        },
        {
            'role': 'user',
            'content': yaml.safe_dump(prompt_payload, allow_unicode=True, sort_keys=False),
        },
    ]
    selected_profile = 'strong'
    selected_model = model_for_profile(selected_profile, 'copilot_evaluation')
    timeout_seconds = _env_int(
        'ASSISTANT_EVALUATION_AUDIT_TIMEOUT_SECONDS',
        DEFAULT_MODEL_AUDIT_TIMEOUT_SECONDS,
        minimum=20,
        maximum=180,
    )
    max_tokens = _env_int(
        'ASSISTANT_EVALUATION_AUDIT_MAX_TOKENS',
        DEFAULT_MODEL_AUDIT_MAX_TOKENS,
        minimum=120,
        maximum=1200,
    )
    retry_once = _env_bool('ASSISTANT_EVALUATION_AUDIT_RETRY_ONCE', True)
    msg = llm_client.chat_profile(
        selected_profile,
        messages,
        temperature=0.1,
        max_tokens=max_tokens,
        timeout=timeout_seconds,
        use_case='copilot_evaluation',
        resource_domain='system_ai',
        ctx=ctx,
        retry_once=retry_once,
    )
    audit_row = AssistantAuditLog.query.filter_by(
        request_id=request_id,
        use_case='copilot_evaluation',
    ).order_by(AssistantAuditLog.created_at.desc()).first()
    status = audit_row.status if audit_row else ('success' if msg else 'error')
    error_message = audit_row.error_message if audit_row else None
    return {
        'requestId': request_id,
        'useCase': 'copilot_evaluation',
        'provider': audit_row.provider if audit_row else None,
        'modelProfile': selected_profile,
        'model': audit_row.model if audit_row else selected_model,
        'ok': bool(msg),
        'auditRecorded': bool(audit_row),
        'auditLogId': audit_row.id if audit_row else None,
        'status': status,
        'latencyMs': audit_row.latency_ms if audit_row else None,
        'promptChars': audit_row.prompt_chars if audit_row else None,
        'responseChars': audit_row.response_chars if audit_row else None,
        'error': error_message,
        'message': llm_client.clean_text((msg or {}).get('content') or ''),
    }


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None


def _apply_model_audit_gate(assessment: Dict[str, Any], model_audit: Dict[str, Any]) -> Dict[str, Any]:
    """Make the real model audit call a hard evaluation gate.

    The business response contract can pass while the evaluation LLM call times
    out or fails to write an audit row. In that situation the result is not a
    valid "real Copilot test" for AI 模型管理, so it must not remain green.
    """
    if (
        model_audit.get('ok') is True
        and model_audit.get('status') == 'success'
        and model_audit.get('auditRecorded') is True
        and model_audit.get('auditLogId')
        and model_audit.get('provider') == 'siliconflow'
        and model_audit.get('useCase') == 'copilot_evaluation'
    ):
        return assessment

    missing_items = ['copilot_evaluation_success_audit']
    if model_audit.get('provider') != 'siliconflow':
        missing_items.append('siliconflow_provider_audit')
    if model_audit.get('useCase') != 'copilot_evaluation':
        missing_items.append('copilot_evaluation_use_case')
    if not model_audit.get('auditLogId'):
        missing_items.append('assistant_audit_log_id')

    next_assessment = dict(assessment or {})
    missing = list(next_assessment.get('missingExpectations') or [])
    missing.append({
        'type': 'model_audit',
        'missing': missing_items,
        'requestId': model_audit.get('requestId'),
        'provider': model_audit.get('provider'),
        'useCase': model_audit.get('useCase'),
        'auditLogId': model_audit.get('auditLogId'),
        'status': model_audit.get('status') or 'missing',
        'error': model_audit.get('error'),
        'auditRecorded': bool(model_audit.get('auditRecorded')),
    })
    categories = set(next_assessment.get('failureCategories') or [])
    categories.update({'audit_confirmation', 'tool_calling'})
    ordered_categories = sorted(categories)
    next_assessment.update({
        'passStatus': 'fail',
        'failureCategories': ordered_categories,
        'missingExpectations': missing,
        'rootCauseNotes': _root_cause_notes(ordered_categories, missing),
        'fixPlan': _fix_plan(ordered_categories),
    })
    return next_assessment


def assess_response(case: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    actual_modules = _actual_modules(response)
    actual_render_blocks = _actual_render_blocks(response)
    used_tools = _used_tools(response)
    evidence_sources = _evidence_sources(response)
    entity_summary = _entity_summary(response)
    time_range = _time_range(response)
    actual_error_code = _response_error_code(response)
    expected_error_code = str(case.get('expected_error_code') or '').strip()
    expected_skill = str(case.get('expected_skill') or '').strip()
    expected_turn_skills = [
        str(item).strip()
        for item in (case.get('expected_turn_skills') or [])
        if str(item).strip()
    ]
    actual_selected_skill = _selected_skill(response)
    expected_modules = set(case.get('expected_modules') or [])
    expected_blocks = set(case.get('expected_render_blocks') or [])
    clarification_case = 'clarification' in expected_blocks
    expected_error_case = bool(expected_error_code)
    missing_modules = sorted(expected_modules - set(actual_modules))
    missing_blocks = sorted(expected_blocks - set(actual_render_blocks))
    missing_expectations: List[Dict[str, Any]] = []
    if expected_error_code and actual_error_code != expected_error_code:
        missing_expectations.append({
            'type': 'permission',
            'missing': [f'expected_error_code:{expected_error_code}'],
            'actual': actual_error_code,
        })
    if expected_skill and actual_selected_skill != expected_skill:
        missing_expectations.append({
            'type': 'skill',
            'missing': [f'expected_skill:{expected_skill}'],
            'actual': actual_selected_skill,
        })
    if expected_turn_skills:
        actual_turn_skills = _conversation_turn_skills(response)
        for index, expected in enumerate(expected_turn_skills):
            actual = actual_turn_skills[index] if index < len(actual_turn_skills) else ''
            if actual != expected:
                missing_expectations.append({
                    'type': 'skill',
                    'missing': [f'expected_turn_{index + 1}_skill:{expected}'],
                    'actual': actual,
                    'actualTurnSkills': actual_turn_skills,
                })
                break
    if missing_modules and not clarification_case and not expected_error_case:
        missing_expectations.append({'type': 'modules', 'missing': missing_modules})
    if missing_blocks:
        missing_expectations.append({'type': 'renderBlocks', 'missing': missing_blocks})
    if case.get('requires_confirmation') and not _has_confirmation(response):
        missing_expectations.append({'type': 'confirmation', 'missing': ['requires_confirmation']})
    if (not case.get('requires_confirmation')) and 'clarification' in expected_blocks and _has_confirmation(response):
        missing_expectations.append({'type': 'confirmation', 'missing': ['clarification_without_write_confirmation']})
    if expected_modules and not evidence_sources and not clarification_case and not expected_error_case:
        missing_expectations.append({'type': 'evidence', 'missing': ['source_links']})
    field_evidence_count = _field_evidence_count(response)
    min_field_evidence = int(case.get('min_field_evidence_count') or 0)
    if min_field_evidence and field_evidence_count < min_field_evidence:
        missing_expectations.append({
            'type': 'field_evidence',
            'missing': [f'field_evidence_count:{min_field_evidence}'],
            'actual': field_evidence_count,
        })
    expected_field_modules = {
        _normalize_module(item)
        for item in (case.get('expected_field_evidence_modules') or [])
        if item
    }
    if expected_field_modules:
        actual_field_modules = _field_evidence_modules(response)
        missing_field_modules = sorted(expected_field_modules - actual_field_modules)
        if missing_field_modules:
            missing_expectations.append({
                'type': 'field_evidence',
                'missing': missing_field_modules,
                'actual': sorted(actual_field_modules),
            })
    forbidden_hits = _forbidden_pattern_hits(case, response)
    if forbidden_hits:
        missing_expectations.append({'type': 'permission', 'missing': ['sensitive_text_leak'], 'matches': forbidden_hits})
    required_text_missing = _required_text_missing(case, response)
    if required_text_missing:
        missing_expectations.append({'type': 'response', 'missing': required_text_missing})
    if case.get('expect_conversation_turns'):
        flow = response.get('conversationFlow') if isinstance(response.get('conversationFlow'), dict) else {}
        expected_turns = int(case.get('expect_conversation_turns') or 0)
        if int(flow.get('turnCount') or 0) < expected_turns:
            missing_expectations.append({'type': 'context', 'missing': [f'conversation_turns:{expected_turns}']})
    if case.get('confirmation_flow'):
        flow = response.get('confirmationFlow') if isinstance(response.get('confirmationFlow'), dict) else {}
        flow_type = str(case.get('confirmation_flow_type') or flow.get('flowType') or 'notification')
        if not flow.get('actionId') or not flow.get('confirmed'):
            missing_expectations.append({'type': 'confirmation', 'missing': ['confirmed_action_execution']})
        if flow.get('wroteBeforeConfirmation'):
            missing_expectations.append({'type': 'confirmation', 'missing': ['no_write_before_confirmation']})
        if flow_type == 'approval':
            expected_approval_status = str(
                case.get('expected_approval_status')
                or flow.get('expectedApprovalStatus')
                or 'approved'
            )
            expected_business_status = str(
                case.get('expected_business_status')
                or flow.get('expectedBusinessStatus')
                or expected_approval_status
            )
            if flow.get('approvalStatus') != expected_approval_status or flow.get('businessStatus') != expected_business_status:
                missing_expectations.append({'type': 'modules', 'missing': ['approval_business_write']})
            if not flow.get('createdApprovalRecords'):
                missing_expectations.append({'type': 'modules', 'missing': ['approval_record_write']})
            if not flow.get('createdOperationLogs'):
                missing_expectations.append({'type': 'audit', 'missing': ['operation_log_write']})
        elif flow_type in {'employee_change', 'salary_adjustment'}:
            if not flow.get('createdEmployeeChanges'):
                missing_expectations.append({'type': 'modules', 'missing': ['employee_change_write']})
            if not flow.get('createdApprovals'):
                missing_expectations.append({'type': 'modules', 'missing': ['employee_change_approval_write']})
            if not flow.get('createdOperationLogs'):
                missing_expectations.append({'type': 'audit', 'missing': ['operation_log_write']})
            if flow.get('directEmployeeUpdate'):
                missing_expectations.append({'type': 'confirmation', 'missing': ['no_direct_employee_update_before_approval']})
            if flow_type == 'salary_adjustment':
                if not flow.get('createdSalaryAdjustment'):
                    missing_expectations.append({'type': 'modules', 'missing': ['salary_adjustment_change_write']})
                if flow.get('salaryAdjustmentAmountMatches') is not True:
                    missing_expectations.append({
                        'type': 'data_retrieval',
                        'missing': ['salary_adjustment_amount_match'],
                        'expected': flow.get('expectedSalaryAdjustment') or case.get('salary_adjustment'),
                        'actual': flow.get('createdSalaryAdjustmentAmounts'),
                    })
                if flow.get('directSalaryUpdate'):
                    missing_expectations.append({'type': 'confirmation', 'missing': ['no_direct_salary_update_before_approval']})
        elif flow_type == 'interview':
            if not flow.get('createdInterviews'):
                missing_expectations.append({'type': 'modules', 'missing': ['interviews_write']})
        elif not flow.get('createdNotifications'):
            missing_expectations.append({'type': 'modules', 'missing': ['notifications_write']})
        if not flow.get('pendingConsumed'):
            missing_expectations.append({'type': 'confirmation', 'missing': ['pending_action_consumed']})
        duplicate_text = str((flow.get('duplicateResponse') or {}).get('summary') or '')
        if flow_type == 'approval':
            duplicate_created = flow.get('duplicateCreatedApprovalRecords')
        elif flow_type in {'employee_change', 'salary_adjustment'}:
            duplicate_created = (flow.get('duplicateCreatedEmployeeChanges') or 0) + (flow.get('duplicateCreatedApprovals') or 0)
        elif flow_type == 'interview':
            duplicate_created = flow.get('duplicateCreatedInterviews')
        else:
            duplicate_created = flow.get('duplicateCreatedNotifications')
        if duplicate_created or '没有找到可执行的待确认动作' not in duplicate_text:
            missing_expectations.append({'type': 'audit', 'missing': ['duplicate_confirmation_blocked']})
    failure_categories = _failure_categories(case, missing_expectations, response)
    pass_status = 'pass' if not missing_expectations and not failure_categories else 'needs_review'
    if (actual_error_code or response.get('error')) and actual_error_code != expected_error_code:
        pass_status = 'fail'
    if forbidden_hits:
        pass_status = 'fail'
    return {
        'actualModules': actual_modules,
        'actualRenderBlocks': actual_render_blocks,
        'usedTools': used_tools,
        'actualSelectedSkill': actual_selected_skill,
        'actualTurnSkills': _conversation_turn_skills(response),
        'evidenceSources': evidence_sources,
        'entitySummary': entity_summary,
        'timeRange': time_range,
        'passStatus': pass_status,
        'failureCategories': failure_categories,
        'missingExpectations': missing_expectations,
        'rootCauseNotes': _root_cause_notes(failure_categories, missing_expectations),
        'fixPlan': _fix_plan(failure_categories),
    }


def _evaluation_client_context(case: Dict[str, Any], base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = dict(base or {})
    context.setdefault('path', '/ai-model-settings')
    context.setdefault('route', '/ai-model-settings?tab=evaluation')
    context.setdefault('moduleId', 'ai-model-settings')
    context.setdefault('moduleName', 'AI 模型管理')
    context.setdefault('pageTitle', 'AI 模型管理 - Copilot 评估')
    context['evaluationCaseId'] = case.get('id')
    context['evaluationScenario'] = case.get('scenario')
    if case.get('id') == 'page_context_attendance_followup':
        context.update({
            'path': '/attendance-stats',
            'route': '/attendance-stats?month=2026-06',
            'moduleId': 'attendance-stats',
            'moduleName': '考勤统计',
            'pageTitle': '考勤统计',
            'visibleFilters': {'month': '2026-06'},
        })
    elif case.get('id') == 'page_context_job_filter_gap':
        context.update({
            'path': '/job-manage',
            'route': '/job-manage',
            'moduleId': 'job-manage',
            'moduleName': '岗位管理',
            'pageTitle': '岗位管理',
            'visibleFilters': {
                'departmentId': 'demo-dept-rd',
                'departmentIdLabel': '研发部',
                'status': 'open',
            },
        })
    elif case.get('id') == 'page_context_salary_performance_risk':
        context.update({
            'path': '/salary-profiles',
            'route': '/salary-profiles',
            'moduleId': 'salary-profiles',
            'moduleName': '薪资档案',
            'pageTitle': '薪资档案',
            'visibleFilters': {
                'employeeId': 'demo-emp-sales-wangwu',
                'employeeIdLabel': '王五',
                'cycleId': 'demo-cycle-2026-q2',
                'cycleIdLabel': '2026 Q2',
            },
        })
    return context


def _first_confirmation_payload(response: Dict[str, Any]) -> str:
    for action in response.get('actions') or []:
        payload = str((action or {}).get('payload') or '')
        if payload.startswith('确认执行动作'):
            return payload
    for widget in response.get('widgets') or []:
        if not isinstance(widget, dict) or widget.get('type') != 'confirmation_card':
            continue
        for action in widget.get('actions') or []:
            payload = str((action or {}).get('payload') or '')
            if payload.startswith('确认执行动作'):
                return payload
    return ''


def _extract_action_id(payload: str) -> str:
    match = re.match(r'\s*确认执行动作\s*[：:]\s*([A-Za-z0-9_-]+)\s*$', payload or '')
    return match.group(1) if match else ''


def _merge_flow_response(
    prepare_response: Dict[str, Any],
    confirm_response: Dict[str, Any],
    duplicate_response: Dict[str, Any],
    *,
    action_payload: str,
    action_id: str,
    wrote_before_confirmation: bool,
    created_notifications: List[Dict[str, Any]],
    pending_consumed: bool,
    duplicate_created_notifications: List[Dict[str, Any]],
    confirmed_write_label: str = '确认后已写入',
    confirmed_write_ok: Optional[bool] = None,
) -> Dict[str, Any]:
    preparation_responses = [
        item for item in (prepare_response.get('_preparationResponses') or [])
        if isinstance(item, dict)
    ] or [prepare_response]
    response = _merge_turn_responses(preparation_responses)
    widgets = list(response.get('widgets') or [])
    render_blocks = list(response.get('renderBlocks') or [])
    entities = list(response.get('entities') or [])
    entities.extend(confirm_response.get('entities') or [])
    evidence = list(((response.get('copilot') or {}).get('evidence') or []))
    if created_notifications:
        evidence.append({
            'module': 'notifications',
            'recordType': 'notifications',
            'recordId': created_notifications[0].get('id'),
            'title': f'确认后写入通知 {len(created_notifications)} 条',
            'url': '/notifications',
        })
    widgets.append({
        'type': 'status_badges',
        'title': '确认执行验证',
        'items': [
            {'label': '确认前未写入', 'status': 'ok' if not wrote_before_confirmation else 'error'},
            {
                'label': confirmed_write_label,
                'status': 'ok' if (bool(created_notifications) if confirmed_write_ok is None else confirmed_write_ok) else 'error',
            },
            {'label': '待确认动作已消费', 'status': 'ok' if pending_consumed else 'error'},
        ],
    })
    widgets.append({
        'type': 'source_citations',
        'title': '确认执行证据',
        'sources': evidence,
    })
    render_blocks.append({'kind': 'status', 'source': 'widget', 'payload': widgets[-2]})
    render_blocks.append({'kind': 'sources', 'source': 'widget', 'payload': widgets[-1]})
    response['summary'] = '\n'.join([
        str(response.get('summary') or prepare_response.get('summary') or ''),
        str(confirm_response.get('summary') or ''),
        str(duplicate_response.get('summary') or ''),
    ]).strip()
    response['entities'] = entities
    response['widgets'] = widgets
    response['renderBlocks'] = render_blocks
    response['sessionId'] = confirm_response.get('sessionId') or prepare_response.get('sessionId')
    copilot = dict(response.get('copilot') or {})
    copilot['evidence'] = evidence
    response['copilot'] = copilot
    response['confirmationFlow'] = {
        'actionPayload': action_payload,
        'actionId': action_id,
        'confirmed': bool(confirm_response),
        'wroteBeforeConfirmation': wrote_before_confirmation,
        'createdNotifications': created_notifications,
        'pendingConsumed': pending_consumed,
        'duplicateResponse': {
            'summary': duplicate_response.get('summary'),
            'sessionId': duplicate_response.get('sessionId'),
        },
        'duplicateCreatedNotifications': duplicate_created_notifications,
    }
    meta = dict(response.get('meta') or {})
    used = list(meta.get('usedSkills') or [])
    for item in (confirm_response.get('meta') or {}).get('usedSkills') or []:
        used.append(item)
    meta['usedSkills'] = _unique([str(item) for item in used if item])
    meta['confirmationFlow'] = response['confirmationFlow']
    response['meta'] = meta
    return response


def _actual_render_blocks(response: Dict[str, Any]) -> List[str]:
    kinds = [str(block.get('kind')) for block in response.get('renderBlocks') or [] if isinstance(block, dict)]
    widgets = response.get('widgets') or []
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        widget_type = widget.get('type')
        if widget_type in {'metrics', 'metric_cards'}:
            kinds.append('kpi')
        elif widget_type in {'bar', 'bar_chart', 'donut', 'doughnut_chart', 'echarts'}:
            kinds.append('chart')
        elif widget_type in {'table', 'data_table'}:
            kinds.append('table')
        elif widget_type == 'confirmation_card':
            kinds.append('confirmation')
        elif widget_type == 'source_citations':
            kinds.append('sources')
        elif widget_type == 'comparison_matrix':
            kinds.append('matrix')
        elif widget_type == 'workset_summary':
            kinds.append('workset')
        elif widget_type == 'follow_up_actions':
            kinds.append('actions')
        elif widget_type == 'status_badges':
            kinds.append('status')
        elif widget_type == 'media_preview':
            kinds.append('media')
        elif widget_type == 'warning':
            kinds.append('notice')
        elif widget_type == 'mermaid_diagram':
            kinds.append('diagram')
        else:
            kinds.append(str(widget_type))
    if response.get('summary'):
        kinds.append('markdown')
    return _unique(kinds)


def _field_evidence_count(response: Dict[str, Any]) -> int:
    total = 0
    for source in _evidence_sources(response):
        fields = source.get('fields')
        if isinstance(fields, list):
            total += len([field for field in fields if isinstance(field, dict)])
    return total


def _field_evidence_modules(response: Dict[str, Any]) -> Set[str]:
    modules: Set[str] = set()
    for source in _evidence_sources(response):
        fields = source.get('fields')
        if isinstance(fields, list) and fields:
            modules.add(_normalize_module(source.get('module') or source.get('recordType') or source.get('type')))
    return modules


def _actual_modules(response: Dict[str, Any]) -> List[str]:
    modules: List[str] = []
    for item in _evidence_sources(response):
        modules.append(_normalize_module(item.get('module') or item.get('recordType') or item.get('type')))
    for ent in response.get('entities') or []:
        if isinstance(ent, dict):
            modules.append(_normalize_module(ent.get('type') or ent.get('module') or ent.get('recordType')))
    meta = response.get('meta') or {}
    decision = meta.get('routeDecision') or {}
    for tool in decision.get('toolPlan') or []:
        if isinstance(tool, dict):
            modules.extend(_modules_for_tool(tool.get('skill') or tool.get('tool')))
    for tool in meta.get('usedSkills') or []:
        modules.extend(_modules_for_tool(tool))
    if 'clarification' in _actual_render_blocks(response):
        text = str(response.get('summary') or (response.get('answer') or {}).get('content') or '')
        if re.search(r'(员工|员工档案|同事|人员)', text):
            modules.append('employees')
        if re.search(r'(候选人|简历|应聘者)', text):
            modules.append('candidates')
    return _unique([m for m in modules if m])


def _used_tools(response: Dict[str, Any]) -> List[str]:
    meta = response.get('meta') or {}
    tools = list(meta.get('usedSkills') or [])
    decision = meta.get('routeDecision') or {}
    for tool in decision.get('toolPlan') or []:
        if isinstance(tool, dict):
            tools.append(tool.get('skill') or tool.get('tool'))
    return _unique([str(t) for t in tools if t])


def _selected_skill(response: Dict[str, Any]) -> str:
    copilot = response.get('copilot') if isinstance(response.get('copilot'), dict) else {}
    trace = copilot.get('routeTrace') if isinstance(copilot.get('routeTrace'), dict) else {}
    selected = trace.get('selected_skill')
    if selected:
        return str(selected)
    meta = response.get('meta') if isinstance(response.get('meta'), dict) else {}
    decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    return str(decision.get('intent') or meta.get('taskTemplateId') or '')


def _conversation_turn_skills(response: Dict[str, Any]) -> List[str]:
    flow = response.get('conversationFlow') if isinstance(response.get('conversationFlow'), dict) else {}
    skills: List[str] = []
    for turn in flow.get('turns') or []:
        if isinstance(turn, dict):
            skills.append(str(turn.get('selectedSkill') or ''))
    return skills


def _evidence_sources(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    copilot = response.get('copilot') or {}
    sources = [item for item in copilot.get('evidence') or [] if isinstance(item, dict)]
    for widget in response.get('widgets') or []:
        if not isinstance(widget, dict) or widget.get('type') != 'source_citations':
            continue
        raw = widget.get('sources') or widget.get('data') or []
        if isinstance(raw, list):
            sources.extend(item for item in raw if isinstance(item, dict))
    return _unique_evidence(sources)[:30]


def _entity_summary(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    entities = []
    for ent in response.get('entities') or []:
        if not isinstance(ent, dict):
            continue
        entities.append({
            'id': ent.get('id'),
            'type': ent.get('type') or ent.get('module'),
            'title': ent.get('title') or ent.get('name'),
            'url': ent.get('url'),
        })
    return entities[:30]


def _time_range(response: Dict[str, Any]) -> Dict[str, Any]:
    decision = ((response.get('meta') or {}).get('routeDecision') or {})
    entities = decision.get('entities') if isinstance(decision, dict) else {}
    if isinstance(entities, dict):
        for key in ('timeRange', 'time_range', 'dateRange', 'month', 'quarter'):
            if entities.get(key):
                return {key: entities.get(key)}
    return {}


def _has_confirmation(response: Dict[str, Any]) -> bool:
    copilot = response.get('copilot') or {}
    if copilot.get('requiresConfirmation'):
        return True
    if (response.get('meta') or {}).get('requiresConfirmation'):
        return True
    return 'confirmation' in _actual_render_blocks(response)


def _failure_categories(
    case: Dict[str, Any],
    missing: List[Dict[str, Any]],
    response: Dict[str, Any],
) -> List[str]:
    categories = set()
    hints = ((response.get('copilot') or {}).get('evaluationHints') or {})
    for item in hints.get('failureCategories') or []:
        categories.add(_map_hint_category(str(item)))
    for item in missing:
        if item['type'] == 'modules':
            categories.add('module_relationship')
            categories.add('data_retrieval')
        elif item['type'] == 'renderBlocks':
            categories.add('frontend_rendering')
            categories.add('response_composition')
        elif item['type'] == 'confirmation':
            categories.add('audit_confirmation')
        elif item['type'] == 'audit':
            categories.add('audit_confirmation')
            categories.add('tool_calling')
        elif item['type'] == 'evidence':
            categories.add('data_retrieval')
        elif item['type'] == 'field_evidence':
            categories.add('data_retrieval')
            categories.add('response_composition')
        elif item['type'] == 'skill':
            categories.add('intent_recognition')
            categories.add('tool_calling')
        elif item['type'] == 'permission':
            categories.add('permission_policy')
        elif item['type'] == 'context':
            categories.add('page_context')
            categories.add('response_composition')
        elif item['type'] == 'response':
            categories.add('response_composition')
    taxonomy = set(load_evaluation_suite().get('failure_taxonomy') or TAXONOMY_FALLBACK)
    allowed = taxonomy | set(case.get('root_cause_dimensions') or [])
    return sorted(item for item in categories if item in allowed)


def _map_hint_category(category: str) -> str:
    if category in {'intent_confidence', 'intent_or_retrieval_fallback'}:
        return 'intent_recognition'
    if category == 'confirmation_contract':
        return 'audit_confirmation'
    if category == 'evidence_linking':
        return 'data_retrieval'
    return category if category in TAXONOMY_FALLBACK else 'response_composition'


def _root_cause_notes(categories: List[str], missing: List[Dict[str, Any]]) -> str:
    if not categories and not missing:
        return '通过基础契约校验；仍需人工抽样判断业务结论质量。'
    return '；'.join([
        f'归因维度：{", ".join(categories) or "待人工确认"}',
        f'缺失项：{missing or "无"}',
    ])


def _fix_plan(categories: List[str]) -> str:
    if not categories:
        return '无需结构性修复；建议保留为回归样本。'
    mapping = {
        'intent_recognition': '检查路由分类器、低置信度澄清和用例覆盖，而不是追加单个关键词。',
        'entity_resolution': '检查实体解析、重名澄清和会话记忆。',
        'time_range': '补齐统一时间范围解析，并在工具参数中传递。',
        'page_context': '检查前端 clientContext 采集和后端上下文使用。',
        'data_retrieval': '检查工具注册、查询参数、测试数据一致性和证据返回。',
        'module_relationship': '补齐跨模块关系聚合，而不是在回答层硬拼文本。',
        'permission_policy': '检查角色权限、脱敏和可见字段。',
        'tool_calling': '检查工具计划、执行器和错误传播。',
        'response_composition': '检查响应协议、证据组织和多形态块选择。',
        'frontend_rendering': '检查 renderBlocks 到前端组件的映射。',
        'test_data_consistency': '修复跨模块测试数据源头一致性。',
        'audit_confirmation': '检查写入动作确认卡、影响范围和确认后执行链路。',
    }
    return ' '.join(mapping.get(item, item) for item in categories)


def _normalize_module(value: Any) -> str:
    text = str(value or '').strip()
    aliases = {
        'employee': 'employees',
        'employee_search': 'employees',
        'employee_evidence_bundle': 'employees',
        'candidate': 'candidates',
        'candidate_evidence_bundle': 'candidates',
        'resume': 'resumes',
        'onboarding_task': 'onboarding_tasks',
        'contract': 'contracts',
        'probation': 'probations',
        'resignation': 'resignations',
        'training': 'training_records',
        'job': 'jobs',
        'offer': 'offers',
        'interview': 'interviews',
        'recruitment_search': 'jobs',
        'attendance': 'attendance_records',
        'attendance_analysis': 'attendance_records',
        'leave': 'leave_requests',
        'employee_request': 'leave_requests',
        'approval': 'approvals',
        'approval_search': 'approvals',
        'salary': 'salary_profiles',
        'payroll': 'payroll_records',
        'performance': 'performance_reviews',
        'change': 'employee_changes',
        'notification': 'notifications',
        'model_setting': 'system_settings',
    }
    return aliases.get(text, text)


def _modules_for_tool(value: Any) -> List[str]:
    text = str(value or '').strip()
    if text == 'attendance_analysis':
        return ['attendance_records', 'attendance_stats', 'leave_requests']
    if text == 'recruitment_search':
        return ['jobs', 'candidates', 'resumes', 'interviews', 'offers']
    if text == 'resume_analysis':
        return ['resumes', 'candidates', 'jobs']
    if text == 'employee_evidence_bundle':
        return [
            'employees', 'candidates', 'resumes', 'jobs', 'interviews', 'offers',
            'onboarding_tasks', 'contracts', 'attendance_records', 'leave_requests',
            'approvals', 'performance_reviews', 'training_records', 'salary_profiles',
            'payroll_records', 'probations', 'employee_changes', 'resignations',
            'operation_logs', 'notifications',
        ]
    if text == 'candidate_evidence_bundle':
        return ['candidates', 'resumes', 'jobs', 'interviews']
    if text == 'recruitment_match_matrix':
        return ['jobs', 'candidates', 'resumes', 'interviews']
    if text == 'employee_change_impact':
        return ['employees', 'departments', 'jobs', 'salary_profiles', 'employee_changes', 'approvals', 'notifications']
    if text == 'employee_salary_adjustment_impact':
        return ['employees', 'salary_profiles', 'performance_reviews', 'employee_changes', 'approvals', 'notifications']
    if text == 'employee_change_submit':
        return ['employees', 'departments', 'employee_changes', 'approvals', 'operation_logs', 'notifications']
    if text == 'employee_search':
        return ['employees', 'departments']
    if text == 'organization_overview':
        return ['employees', 'departments', 'jobs']
    if text == 'performance_analysis':
        return ['performance_reviews', 'employees']
    if text == 'payroll_analysis':
        return ['payroll_records', 'employees']
    if text == 'approval_decision':
        return ['approvals', 'operation_logs']
    if text == 'notification_create':
        return ['notifications']
    if text == 'followup_task_create':
        return ['notifications']
    if text == 'interview_create':
        return ['interviews', 'candidates', 'resumes', 'jobs']
    if text == 'feedback_triage':
        return ['feedback']
    if text == 'dashboard_report':
        return ['dashboard']
    if text == 'system_search':
        return ['system_search']
    if text == 'smart_data_query':
        return ['analytics']
    if text == 'workset_analyze':
        return ['workset']
    return [_normalize_module(text)]


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_entities(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = (
            item.get('type') or item.get('module') or item.get('recordType'),
            item.get('id') or item.get('recordId') or item.get('title') or item.get('name'),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:40]


def _unique_evidence(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = (
            item.get('module') or item.get('recordType') or item.get('type'),
            item.get('recordId') or item.get('id') or item.get('title'),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result[:30]


def _response_error_code(response: Dict[str, Any]) -> str:
    meta = response.get('meta') if isinstance(response.get('meta'), dict) else {}
    direct = meta.get('errorCode') or response.get('errorCode')
    if direct:
        return str(direct)
    decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    task_id = str(meta.get('taskTemplateId') or decision.get('taskTemplateId') or '')
    intent = str(meta.get('intent') or decision.get('intent') or '')
    if task_id == 'permission_denied_response' or intent == 'permission_denied':
        return 'permission_denied'
    safety_flags = decision.get('safetyFlags') if isinstance(decision, dict) else []
    if isinstance(safety_flags, list) and 'permission_denied' in safety_flags:
        return 'permission_denied'
    if decision.get('taskType') == 'forbidden':
        return 'permission_denied'
    if response.get('error'):
        return str(response.get('error'))
    return ''


def _response_blob(response: Dict[str, Any]) -> str:
    payload = {
        'summary': response.get('summary'),
        'answer': response.get('answer'),
        'widgets': response.get('widgets'),
        'renderBlocks': response.get('renderBlocks'),
        'entities': response.get('entities'),
        'copilot': response.get('copilot'),
        'conversationFlow': response.get('conversationFlow'),
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _forbidden_pattern_hits(case: Dict[str, Any], response: Dict[str, Any]) -> List[str]:
    patterns = case.get('forbidden_patterns') or case.get('forbidden_text_patterns') or []
    if not isinstance(patterns, list):
        return []
    blob = _response_blob(response)
    hits = []
    for pattern in patterns:
        try:
            if re.search(str(pattern), blob, re.I | re.S):
                hits.append(str(pattern))
        except re.error:
            continue
    return hits[:10]


def _required_text_missing(case: Dict[str, Any], response: Dict[str, Any]) -> List[str]:
    patterns = case.get('required_patterns') or case.get('required_text_patterns') or []
    if not isinstance(patterns, list):
        return []
    blob = _response_blob(response)
    missing = []
    for pattern in patterns:
        try:
            if not re.search(str(pattern), blob, re.I | re.S):
                missing.append(str(pattern))
        except re.error:
            missing.append(str(pattern))
    return missing[:10]


def _clip_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload)
    if len(text) <= 60000:
        return payload
    meta = payload.get('meta') if isinstance(payload.get('meta'), dict) else {}
    confirmation_flow = payload.get('confirmationFlow')
    if not isinstance(confirmation_flow, dict):
        confirmation_flow = meta.get('confirmationFlow')
    return {
        'summary': payload.get('summary'),
        'sessionId': payload.get('sessionId'),
        'meta': payload.get('meta'),
        'copilot': payload.get('copilot'),
        # These fields are governance evidence, not optional response detail.
        # Keep them after clipping so large multi-turn responses cannot erase
        # who initiated the run or whether the real audit/confirmation gates
        # passed.
        'evaluationAudit': payload.get('evaluationAudit') or {},
        'evaluationRunAs': payload.get('evaluationRunAs') or {},
        'confirmationFlow': confirmation_flow or {},
        'truncated': True,
    }
