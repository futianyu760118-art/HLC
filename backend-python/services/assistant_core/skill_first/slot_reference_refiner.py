"""LLM-assisted slot and reference refinement for the Agent Kernel.

This module is deliberately narrower than the Skill planner. It cannot choose a
Skill, cannot create tools and cannot execute anything. It only refines slots
for the already selected Skill Card, then filters the result through the card
and registered tool schema.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Sequence, Tuple

from .. import llm_client, skill_registry
from ..schemas import AssistantContext
from . import llm_health
from .cards import AgentSkillCard
from . import llm_runtime_config
from .understanding import UnderstandingResult


FORBIDDEN_SLOT_KEYS = {
    'sql',
    'candidate_sql',
    'candidateSql',
    'raw_sql',
    'rawSql',
    'query_plan',
    'queryPlan',
}

WRITE_ID_SLOTS = {
    'approval_id',
    'candidate_id',
    'resume_id',
    'job_id',
    'employee_id',
    'target_department_id',
    'target_position_id',
    'action_id',
}


def refine_slots(
    *,
    message: str,
    ctx: AssistantContext,
    card: Optional[AgentSkillCard],
    current_slots: Dict[str, Any],
    missing_slots: Sequence[str],
    understanding: Optional[UnderstandingResult] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return guarded slot values plus an observable refinement trace."""

    enabled, availability_reason, health_snapshot = _llm_availability()
    trace = {
        'enabled': enabled,
        'status': availability_reason,
        'llm_health': health_snapshot,
        'source': 'deterministic',
        'applied': False,
        'rejected_fields': [],
    }
    if not card or not enabled:
        return dict(current_slots or {}), trace
    trace['timeout_seconds'] = llm_runtime_config.slot_reference_timeout()

    try:
        raw = _call_refiner(
            message=message,
            ctx=ctx,
            card=card,
            current_slots=current_slots,
            missing_slots=missing_slots,
            understanding=understanding,
        )
        llm_meta = llm_client.last_call_meta()
        trace['llm_call'] = llm_meta
        try:
            trace['llm_health'] = llm_health.record_call_result('skill_first_slot_reference', llm_meta)
        except Exception as health_exc:
            trace['llm_health_error'] = {
                'stage': 'health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
    except Exception as exc:
        trace.update({
            'source': 'unavailable',
            'status': 'exception',
            'error_type': type(exc).__name__,
            'error': str(exc)[:180],
        })
        try:
            trace['llm_health'] = llm_health.record_failure(
                'skill_first_slot_reference',
                {
                    'status': 'error',
                    'error_type': type(exc).__name__,
                },
            )
        except Exception as health_exc:
            trace['llm_health_error'] = {
                'stage': 'health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
        return dict(current_slots or {}), trace
    if not isinstance(raw, dict):
        trace['source'] = 'unavailable'
        trace['status'] = _diagnostic_status_from_llm_meta(trace.get('llm_call') or {})
        return dict(current_slots or {}), trace

    proposed = raw.get('slot_values') or raw.get('slotValues') or {}
    if not isinstance(proposed, dict):
        proposed = {}
    guarded, guard_trace = _guard_refined_slots(card, current_slots, proposed)
    trace.update({
        'source': 'llm',
        'status': 'accepted',
        'applied': guarded != dict(current_slots or {}),
        'reason': str(raw.get('reason') or raw.get('route_reason') or raw.get('routeReason') or ''),
        'confidence': _clamp_confidence(raw.get('confidence')),
        'missing_slots': [str(item) for item in (raw.get('missing_slots') or raw.get('missingSlots') or []) if item],
        **guard_trace,
    })
    return guarded, trace


def _llm_availability() -> Tuple[bool, str, Dict[str, Any]]:
    flag = os.getenv('ASSISTANT_SKILL_FIRST_SLOT_LLM')
    if flag is not None and flag.strip().lower() in {'0', 'false', 'off', 'no'}:
        return False, 'disabled_by_env', llm_health.availability('skill_first_slot_reference')[2]
    if not llm_client.is_available():
        return False, 'llm_unavailable', llm_health.availability('skill_first_slot_reference')[2]
    health_allowed, health_reason, health = llm_health.availability('skill_first_slot_reference')
    if not health_allowed:
        return False, health_reason, health
    return True, 'available', health


def _llm_enabled() -> bool:
    enabled, _reason, _health = _llm_availability()
    return enabled


def _call_refiner(
    *,
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    current_slots: Dict[str, Any],
    missing_slots: Sequence[str],
    understanding: Optional[UnderstandingResult],
) -> Optional[Dict[str, Any]]:
    timeout_seconds = llm_runtime_config.slot_reference_timeout()
    return llm_client.json_chat_profile(
        'small',
        _messages(
            message=message,
            ctx=ctx,
            card=card,
            current_slots=current_slots,
            missing_slots=missing_slots,
            understanding=understanding,
        ),
        temperature=0.03,
        max_tokens=450,
        timeout=timeout_seconds,
        use_case='skill_first_slot_reference',
        retry_once=False,
        ctx=ctx,
    )


def _diagnostic_status_from_llm_meta(meta: Dict[str, Any]) -> str:
    status = str((meta or {}).get('status') or '')
    json_status = str((meta or {}).get('json_status') or '')
    if status == 'timeout':
        return 'llm_timeout'
    if status == 'http_error':
        return 'llm_http_error'
    if status == 'error':
        return 'llm_error'
    if json_status == 'empty_content':
        return 'llm_empty_content'
    if json_status == 'parse_failed':
        return 'llm_json_parse_failed'
    if status and status != 'success':
        return f'llm_{status}'
    return 'invalid_response'


def _messages(
    *,
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    current_slots: Dict[str, Any],
    missing_slots: Sequence[str],
    understanding: Optional[UnderstandingResult],
) -> list[dict[str, str]]:
    tool = str((card.executor or {}).get('tool') or '')
    spec = skill_registry.get(tool)
    schema = getattr(spec, 'input_schema', {}) if spec else {}
    payload = {
        'user_text': message,
        'selected_skill': {
            'id': card.id,
            'name': card.name,
            'domain': card.domain,
            'description': card.description,
            'when_to_use': card.when_to_use[:2],
            'anti_examples': card.anti_examples[:2],
            'required_slots': card.required_slots,
            'optional_slots': card.optional_slots,
            'slot_extraction_hints': {
                str(key): str(value)[:90]
                for key, value in list((card.slot_extraction_hints or {}).items())[:6]
            },
            'side_effect': card.side_effect,
            'executor_tool': tool,
            'tool_input_schema': schema,
        },
        'current_slots': current_slots,
        'missing_slots': list(missing_slots or []),
        'understanding_result': _compact_understanding(understanding),
        'current_page_context': getattr(ctx, 'client_context', {}) or {},
        'recent_history': (ctx.history or [])[-3:],
        'strict_contract': {
            'selected_skill_is_fixed': True,
            'output_fields': ['slot_values', 'missing_slots', 'confidence', 'reason'],
            'allowed_slot_keys': sorted(_allowed_slot_keys(card)),
            'forbidden_keys': sorted(FORBIDDEN_SLOT_KEYS),
            'do_not_create_skill': True,
            'do_not_create_tool': True,
            'do_not_write_sql': True,
            'side_effect_id_policy': (
                'For side-effect Skills, do not invent database ids such as approval_id, candidate_id, '
                'resume_id, job_id or employee_id. Leave missing when the id is not explicitly present in '
                'current_slots, user text, or recent history/workset evidence.'
            ),
        },
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Agent Kernel 的槽位和多轮指代细化节点。'
                'Skill 已经由上游 planner 选择，你不能改选 Skill，不能创造工具，不能执行动作。'
                '你只根据 selected_skill 的 schema、用户原话、当前槽位、页面上下文和最近历史，'
                '补充允许的 slot_values、列出 missing_slots，并说明依据。返回严格 JSON。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def _compact_understanding(understanding: Optional[UnderstandingResult]) -> Optional[Dict[str, Any]]:
    if not understanding:
        return None
    return {
        'normalized_query': understanding.normalized_query,
        'intent_summary': str(understanding.intent_summary or '')[:120],
        'domain_hints': list(understanding.domain_hints or [])[:6],
        'entity_mentions': dict(understanding.entity_mentions or {}),
        'slot_hints': dict(understanding.slot_hints or {}),
        'reference_hints': dict(understanding.reference_hints or {}),
        'candidate_skill_hints': list(understanding.candidate_skill_hints or [])[:8],
        'confidence': round(float(understanding.confidence or 0.0), 4),
        'source': understanding.source,
    }


def _guard_refined_slots(
    card: AgentSkillCard,
    current_slots: Dict[str, Any],
    proposed_slots: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    allowed = _allowed_slot_keys(card)
    merged = dict(current_slots or {})
    rejected = []
    for key, value in proposed_slots.items():
        key_text = str(key)
        if key_text in FORBIDDEN_SLOT_KEYS or key_text.startswith('_'):
            rejected.append({'field': key_text, 'reason': 'forbidden'})
            continue
        if key_text not in allowed:
            rejected.append({'field': key_text, 'reason': 'not_in_selected_skill_schema'})
            continue
        if _is_missing(value):
            continue
        if card.side_effect and key_text in WRITE_ID_SLOTS and _is_missing((current_slots or {}).get(key_text)):
            rejected.append({'field': key_text, 'reason': 'side_effect_id_not_trusted_from_llm'})
            continue
        merged[key_text] = _sanitize_slot_value(value)
    return _drop_empty_values(merged), {'rejected_fields': rejected}


def _allowed_slot_keys(card: AgentSkillCard) -> set[str]:
    tool = str((card.executor or {}).get('tool') or '')
    spec = skill_registry.get(tool)
    schema = getattr(spec, 'input_schema', None) if spec else None
    allowed = set(card.required_slots or []) | set(card.optional_slots or []) | {'question'}
    if isinstance(schema, dict):
        allowed.update(schema.keys())
    if card.id == 'smart.data_query':
        allowed.discard('sql')
        allowed.discard('explanation')
    return {str(item) for item in allowed if item}


def _sanitize_slot_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_sanitize_slot_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _sanitize_slot_value(raw)
            for key, raw in list(value.items())[:40]
            if not str(key).startswith('_')
        }
    return str(value)[:1000]


def _drop_empty_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if not _is_missing(value)
    }


def _is_missing(value: Any) -> bool:
    return value is None or value == '' or value == []


def _clamp_confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(float(value), 1.0)), 4)
    except (TypeError, ValueError):
        return 0.0


__all__ = ['refine_slots']
