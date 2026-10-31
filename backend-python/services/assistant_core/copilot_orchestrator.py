"""HRM Copilot 2.0 orchestration facade.

The old public ``services.assistant`` module stays as API compatibility glue.
Normal natural-language requests now run through the Skill-first runtime only.
Legacy agentic/regex routes are kept as historical assets and explicit test
targets, but they are no longer an invisible fallback for product traffic.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any, Dict, Iterator, List, Optional

from . import build_context, memory
from .constants import PRIVILEGED_ROLES
from .response_contract import apply_response_contract

logger = logging.getLogger('hengpintong.assistant.copilot')


def query(
    *,
    user_id: str,
    message: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_id = request_id or uuid.uuid4().hex
    ctx = build_context(user_id, session_id, request_id=request_id, client_context=client_context)
    include_full = ctx.role in PRIVILEGED_ROLES

    from .skill_first import runtime as skill_first_runtime

    try:
        result = skill_first_runtime.try_run(message, ctx)
    except Exception:
        logger.exception('skill_first_runtime_failed_returning_skill_first_unhandled')
        result = skill_first_runtime.build_unhandled_result(
            message,
            ctx,
            reason='skill_first_runtime_exception',
            error_code='skill_first_runtime_exception',
        )
    if result is None:
        result = skill_first_runtime.build_unhandled_result(message, ctx)
    apply_response_contract(result, ctx, message=message)
    skill_first_runtime.persist_turn(message, ctx, result)
    return result.to_response(include_meta=True, include_full_trace=include_full)


def invoke_skill(
    *,
    skill_id: str,
    params: Dict[str, Any],
    user_id: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from .skill_cards import SKILL_CARDS
    from .skill_first import runtime as skill_first_runtime

    launcher_card = next((c for c in SKILL_CARDS if c['id'] == skill_id), None)
    agent_skill_id = _agent_skill_id_for_launcher(skill_id)
    if not launcher_card or not agent_skill_id:
        return {
            'summary': f'未知技能：{skill_id}',
            'entities': [],
            'widgets': [],
            'sessionId': session_id,
            'meta': {'taskTemplateId': None, 'errorCode': 'unknown_skill'},
        }

    request_id = request_id or uuid.uuid4().hex
    ctx = build_context(user_id, session_id, request_id=request_id, client_context=client_context)
    if ctx.role not in launcher_card.get('allowed_roles', []):
        return {
            'summary': '权限不足，无法使用此技能。',
            'entities': [],
            'widgets': [],
            'sessionId': ctx.session_id,
            'meta': {'taskTemplateId': None, 'errorCode': 'permission_denied'},
        }

    clean_params = _clean_skill_params(params or {})
    synthetic_message = _synthetic_skill_message(launcher_card, clean_params)
    exec_result = skill_first_runtime.invoke_registered_skill(
        agent_skill_id,
        clean_params,
        ctx,
        display_name=str(launcher_card.get('name') or skill_id),
    )
    apply_response_contract(exec_result, ctx, message=synthetic_message)
    skill_first_runtime.persist_turn(synthetic_message, ctx, exec_result)
    if isinstance(exec_result.copilot, dict):
        exec_result.copilot['skillInvoke'] = skill_id
        exec_result.copilot['agentSkillInvoke'] = agent_skill_id
    include_full = ctx.role in PRIVILEGED_ROLES
    return exec_result.to_response(include_meta=True, include_full_trace=include_full)


def _agent_skill_id_for_launcher(skill_id: str) -> Optional[str]:
    mapping = {
        'system_dashboard': 'report.operations',
        'global_search': 'system.global_search',
        'resume_analysis': 'candidate.recent_resumes',
        'recruitment_overview': 'recruitment.overview',
        'interview_planning': 'interview.suggestion',
        'employee_lookup': 'employee.search',
        'organization_overview': 'organization.overview',
        'attendance_analysis': 'attendance.overview',
        'performance_analysis': 'performance.distribution',
        'payroll_analysis': 'payroll.summary',
        'training_analysis': 'training.completion',
        'approval_summary': 'approval.todo',
        'feedback_triage': 'feedback.summary',
        'draft_generator': 'draft.generation',
    }
    return mapping.get(str(skill_id or '').strip())


def stream_grounded_response(
    *,
    user_id: str,
    message: str,
    result_payload: Dict[str, Any],
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Iterator[str]:
    """Stream a natural-language expression of an already grounded result.

    The business pipeline still owns intent routing, entity parsing, data
    retrieval, actions and confirmation. This model call is deliberately
    constrained to expression only, so streaming improves UX without moving
    facts or side effects into the LLM layer.
    """
    from . import llm_client

    ctx = build_context(
        user_id,
        session_id or result_payload.get('sessionId'),
        request_id=request_id,
        client_context=client_context,
    )
    if _is_confirmed_action_result(result_payload):
        yield from _stream_confirmed_action_receipt(
            message=message,
            result_payload=result_payload,
            ctx=ctx,
        )
        return
    if _is_permission_denied_result(result_payload):
        yield from _stream_permission_denied_receipt(
            message=message,
            result_payload=result_payload,
            ctx=ctx,
        )
        return

    messages = _stream_answer_messages(message, result_payload)
    try:
        yield from llm_client.stream_chat_profile(
            'strong',
            messages,
            temperature=0.2,
            max_tokens=900,
            timeout=30,
            use_case='assistant_stream_answer',
            ctx=ctx,
            retry_once=False,
        )
    except Exception:
        logger.exception('assistant_stream_grounded_response_failed')


def _is_confirmed_action_result(result_payload: Dict[str, Any]) -> bool:
    meta = result_payload.get('meta') if isinstance(result_payload.get('meta'), dict) else {}
    route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    copilot = result_payload.get('copilot') if isinstance(result_payload.get('copilot'), dict) else {}
    return (
        str(meta.get('routeTrack') or route_decision.get('routeTrack') or copilot.get('routeTrack') or '') == 'CONFIRMED_ACTION'
        or str(route_decision.get('intent') or meta.get('taskTemplateId') or copilot.get('intent') or '') == 'execute_pending_action'
    )


def _is_permission_denied_result(result_payload: Dict[str, Any]) -> bool:
    meta = result_payload.get('meta') if isinstance(result_payload.get('meta'), dict) else {}
    route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    copilot = result_payload.get('copilot') if isinstance(result_payload.get('copilot'), dict) else {}
    safety_flags = route_decision.get('safetyFlags') if isinstance(route_decision.get('safetyFlags'), list) else []
    return (
        str(meta.get('taskType') or route_decision.get('taskType') or copilot.get('taskType') or '') == 'forbidden'
        or str(meta.get('errorCode') or copilot.get('errorCode') or '') == 'permission_denied'
        or 'permission_denied' in safety_flags
    )


def _stream_confirmed_action_receipt(
    *,
    message: str,
    result_payload: Dict[str, Any],
    ctx: Any,
) -> Iterator[str]:
    from .audit import record_llm_call
    from services.tenancy import current_tenant_id

    summary = str(
        (result_payload.get('answer') or {}).get('content')
        if isinstance(result_payload.get('answer'), dict) else ''
    ).strip() or str(result_payload.get('summary') or '').strip()
    if not summary:
        summary = '已完成确认动作。'
    content = _clean_stream_text(summary)
    chunks = _split_receipt_chunks(content)
    record_llm_call(
        tenant_id=getattr(ctx, 'tenant_id', None) or current_tenant_id(),
        user_id=getattr(ctx, 'audit_user_id', None) or getattr(ctx, 'user_id', None),
        session_id=getattr(ctx, 'audit_session_id', None) or getattr(ctx, 'session_id', None),
        request_id=getattr(ctx, 'request_id', None),
        provider='siliconflow',
        model='deterministic-confirmed-action-receipt',
        model_profile='system',
        use_case='assistant_stream_answer',
        messages=[{
            'role': 'system',
            'content': 'Confirmed side-effect actions use deterministic receipts; no provider call is needed.',
        }, {
            'role': 'user',
            'content': message,
        }],
        response_content=content,
        response_meta={
            'stream': True,
            'chunkCount': len(chunks),
            'deterministicReceipt': True,
            'skippedProviderCall': True,
            'reason': 'confirmed_action_receipt',
        },
        status='success',
        latency_ms=0,
    )
    for chunk in chunks:
        yield chunk


def _stream_permission_denied_receipt(
    *,
    message: str,
    result_payload: Dict[str, Any],
    ctx: Any,
) -> Iterator[str]:
    from .audit import record_llm_call
    from services.tenancy import current_tenant_id

    summary = str(
        (result_payload.get('answer') or {}).get('content')
        if isinstance(result_payload.get('answer'), dict) else ''
    ).strip() or str(result_payload.get('summary') or '').strip()
    if not summary:
        summary = '当前账号没有权限执行该操作。'
    content = _clean_stream_text(summary)
    chunks = _split_receipt_chunks(content)
    record_llm_call(
        tenant_id=getattr(ctx, 'tenant_id', None) or current_tenant_id(),
        user_id=getattr(ctx, 'audit_user_id', None) or getattr(ctx, 'user_id', None),
        session_id=getattr(ctx, 'audit_session_id', None) or getattr(ctx, 'session_id', None),
        request_id=getattr(ctx, 'request_id', None),
        provider='siliconflow',
        model='deterministic-permission-denied-receipt',
        model_profile='system',
        use_case='assistant_stream_answer',
        messages=[{
            'role': 'system',
            'content': 'Permission-denied assistant responses use deterministic receipts; no provider call is needed.',
        }, {
            'role': 'user',
            'content': message,
        }],
        response_content=content,
        response_meta={
            'stream': True,
            'chunkCount': len(chunks),
            'deterministicReceipt': True,
            'skippedProviderCall': True,
            'reason': 'permission_denied_receipt',
        },
        status='success',
        latency_ms=0,
    )
    for chunk in chunks:
        yield chunk


def _split_receipt_chunks(content: str) -> List[str]:
    text = content or ''
    if not text:
        return ['已完成确认动作。']
    if len(text) <= 36:
        return [text]
    chunks: List[str] = []
    cursor = 0
    while cursor < len(text):
        chunks.append(text[cursor:cursor + 36])
        cursor += 36
    return chunks


def apply_streamed_answer(
    result_payload: Dict[str, Any],
    streamed_text: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a payload whose display answer matches the streamed text."""
    content = _clean_stream_text(streamed_text)
    if not content:
        return result_payload

    payload = deepcopy(result_payload)
    payload['summary'] = content
    answer = payload.get('answer') if isinstance(payload.get('answer'), dict) else {}
    answer = {**answer, 'content': content, 'format': answer.get('format') or 'markdown'}
    payload['answer'] = answer

    blocks = payload.get('renderBlocks') if isinstance(payload.get('renderBlocks'), list) else []
    if blocks:
        updated = False
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get('id') == 'answer' or block.get('source') == 'answer':
                block['kind'] = block.get('kind') or 'markdown'
                block['content'] = content
                block['title'] = block.get('title') or '结论'
                updated = True
                break
        if not updated:
            blocks.insert(0, {
                'id': 'answer',
                'kind': 'markdown',
                'title': '结论',
                'content': content,
                'source': 'answer',
            })
        payload['renderBlocks'] = blocks

    copilot = payload.get('copilot') if isinstance(payload.get('copilot'), dict) else {}
    deterministic_receipt = _is_confirmed_action_result(payload)
    permission_denied_receipt = _is_permission_denied_result(payload)
    copilot['responseGeneration'] = {
        **(copilot.get('responseGeneration') if isinstance(copilot.get('responseGeneration'), dict) else {}),
        'streamed': True,
        'provider': 'siliconflow',
        'modelProfile': 'system' if (deterministic_receipt or permission_denied_receipt) else 'strong',
        'model': (
            'deterministic-confirmed-action-receipt'
            if deterministic_receipt else
            'deterministic-permission-denied-receipt'
            if permission_denied_receipt else None
        ),
        'useCase': 'assistant_stream_answer',
        'deterministicReceipt': deterministic_receipt or permission_denied_receipt,
        'skippedProviderCall': deterministic_receipt or permission_denied_receipt,
        'reason': (
            'confirmed_action_receipt'
            if deterministic_receipt else
            'permission_denied_receipt'
            if permission_denied_receipt else None
        ),
    }
    payload['copilot'] = copilot

    if user_id and payload.get('sessionId'):
        memory.update_latest_assistant_answer(
            user_id=user_id,
            session_id=payload.get('sessionId'),
            summary=content,
            answer=answer,
            render_blocks=payload.get('renderBlocks') or [],
            copilot=copilot,
        )
    return payload


def _stream_answer_messages(message: str, result_payload: Dict[str, Any]) -> List[Dict[str, str]]:
    compact = _compact_stream_payload(result_payload)
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Copilot 2.0 的最终表达层。业务编排、权限、检索、证据和动作确认已经由系统完成，'
                '你只能基于用户问题和给定 JSON 结果组织中文回复。不得新增 JSON 中没有的人名、数值、结论、'
                '执行状态或数据来源；不得声称已经执行需要确认的写入动作。若存在表格、图表、卡片、时间线、'
                '确认区等结构化块，正文只做导读和重点解释，不要逐行复述整张表。回答要清晰、专业、可审计，'
                '必要时点明证据来源、风险、下一步和待确认事项。'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'用户问题：{message}\n\n'
                '系统已生成的业务结果 JSON 如下，请在事实受限的前提下输出最终回复正文：\n'
                f'{compact}'
            ),
        },
    ]


def _compact_stream_payload(result_payload: Dict[str, Any]) -> str:
    import json

    meta = result_payload.get('meta') if isinstance(result_payload.get('meta'), dict) else {}
    copilot = result_payload.get('copilot') if isinstance(result_payload.get('copilot'), dict) else {}
    render_blocks = result_payload.get('renderBlocks') if isinstance(result_payload.get('renderBlocks'), list) else []
    evidence = copilot.get('evidence') if isinstance(copilot.get('evidence'), list) else []
    plan = copilot.get('plan') if isinstance(copilot.get('plan'), list) else []

    compact = {
        'summary': result_payload.get('summary'),
        'answer': (result_payload.get('answer') or {}).get('content')
        if isinstance(result_payload.get('answer'), dict) else None,
        'sessionId': result_payload.get('sessionId'),
        'requiresConfirmation': bool(meta.get('requiresConfirmation') or copilot.get('requiresConfirmation')),
        'taskTemplateId': meta.get('taskTemplateId'),
        'usedSkills': meta.get('usedSkills') or [],
        'currentPage': copilot.get('currentContext') or result_payload.get('clientContext') or {},
        'entities': _compact_items(result_payload.get('entities'), 10),
        'metrics': _compact_metrics(result_payload.get('widgets'), result_payload.get('summary')),
        'evidence': _compact_items(evidence, 12),
        'plan': _compact_items(plan, 8),
        'actions': _compact_items(result_payload.get('actions') or copilot.get('actions'), 8),
        'worksets': _compact_items(result_payload.get('worksets'), 6),
        'renderBlocks': [
            {
                'kind': block.get('kind'),
                'title': block.get('title'),
                'widgetType': block.get('widgetType'),
                'source': block.get('source'),
            }
            for block in render_blocks[:12]
            if isinstance(block, dict)
        ],
        'widgets': [
            {
                'type': widget.get('type'),
                'title': widget.get('title'),
                'message': widget.get('message'),
                'rowCount': len(((widget.get('table') or {}).get('rows') or []))
                if isinstance(widget.get('table'), dict) else None,
            }
            for widget in (result_payload.get('widgets') or [])[:10]
            if isinstance(widget, dict)
        ],
        'factBoundary': _fact_boundary(message='', result_payload=result_payload),
    }
    text = json.dumps(compact, ensure_ascii=False, default=str)
    if len(text) <= 9000:
        return text
    compact['entities'] = _compact_items(result_payload.get('entities'), 5)
    compact['evidence'] = _compact_items(evidence, 6)
    compact['plan'] = _compact_items(plan, 5)
    compact['actions'] = _compact_items(result_payload.get('actions') or copilot.get('actions'), 4)
    text = json.dumps(compact, ensure_ascii=False, default=str)
    return text[:9000]


def _compact_metrics(widgets: Any, summary: Any) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    if isinstance(summary, str) and summary:
        metrics['summaryPreview'] = summary[:800]
    if not isinstance(widgets, list):
        return metrics
    metric_cards: List[Dict[str, Any]] = []
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        if widget.get('type') not in {'metrics', 'metric_cards'}:
            continue
        for item in widget.get('metrics') or widget.get('cards') or []:
            if not isinstance(item, dict):
                continue
            metric_cards.append({
                'label': item.get('label'),
                'value': item.get('value'),
                'unit': item.get('unit'),
            })
    if metric_cards:
        metrics['cards'] = metric_cards[:12]
    return metrics


def _fact_boundary(message: str, result_payload: Dict[str, Any]) -> Dict[str, Any]:
    entities = result_payload.get('entities') if isinstance(result_payload.get('entities'), list) else []
    meta = result_payload.get('meta') if isinstance(result_payload.get('meta'), dict) else {}
    route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
    inputs = []
    for plan in route_decision.get('toolPlan') or []:
        if isinstance(plan, dict):
            inputs.append(plan.get('input') or {})
    employee_entities = [
        entity for entity in entities
        if isinstance(entity, dict) and str(entity.get('type') or entity.get('module') or '').startswith('employee')
    ]
    return {
        'scope': 'employee' if employee_entities else 'aggregate_or_unknown',
        'employeeEvidenceTitles': [entity.get('title') for entity in employee_entities[:6]],
        'toolInputs': inputs[:4],
        'instruction': (
            '若 scope 不是 employee，不能把用户问题中的人名当作已证实员工结论；'
            '只能说明系统结果是汇总/当前筛选结果，或提示需要员工级证据。'
        ),
    }


def _compact_items(value: Any, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compacted: List[Dict[str, Any]] = []
    keep_keys = {
        'id', 'type', 'module', 'recordType', 'recordId', 'title', 'name', 'label',
        'status', 'url', 'path', 'value', 'summary', 'description', 'riskLevel',
        'requiresConfirmation', 'action', 'actionId', 'skill', 'rowsCount',
        'durationMs', 'fields',
    }
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        cleaned: Dict[str, Any] = {}
        for key, raw in item.items():
            if key not in keep_keys:
                continue
            if isinstance(raw, str):
                cleaned[key] = raw[:300]
            elif isinstance(raw, (int, float, bool)) or raw is None:
                cleaned[key] = raw
            elif isinstance(raw, list):
                cleaned[key] = raw[:6]
            elif isinstance(raw, dict):
                cleaned[key] = {
                    str(k)[:80]: v
                    for k, v in list(raw.items())[:8]
                    if isinstance(v, (str, int, float, bool)) or v is None
                }
        if cleaned:
            compacted.append(cleaned)
    return compacted


def _clean_stream_text(text: str) -> str:
    from .llm_client import clean_text

    return clean_text(text or '')


def _clean_skill_params(params: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value == '':
            continue
        if value == 'true':
            clean[key] = True
        elif value == 'false':
            clean[key] = False
        else:
            try:
                clean[key] = int(value)
            except (TypeError, ValueError):
                clean[key] = value
    return clean


def _synthetic_skill_message(card: Dict[str, Any], params: Dict[str, Any]) -> str:
    field_desc = ', '.join(f'{key}={value}' for key, value in params.items()) if params else ''
    message = f'[技能调用] {card["name"]}'
    if field_desc:
        message += f'（{field_desc}）'
    return message
