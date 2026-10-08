"""Planner slot sanitization and schema guards for the HRM Agent Kernel."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .. import skill_registry
from ..schemas import AssistantContext
from ..skill_first.cards import AgentSkillCard


PLANNER_FORBIDDEN_SLOT_KEYS = {
    'sql',
    'candidate_sql',
    'candidateSql',
    'raw_sql',
    'rawSql',
    'query_plan',
    'queryPlan',
}


def guard_slot_values(
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    slot_values: Dict[str, Any],
    planner_source: str,
    *,
    fill_slots: Callable[[str, AssistantContext, Optional[AgentSkillCard]], Dict[str, Any]],
    looks_like_workset_reference: Callable[[str], bool],
    extract_candidate_name: Callable[[str], Optional[str]],
    extract_employee_name_for_query: Callable[[str], Optional[str]],
    extract_employee_name_for_action: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    deterministic_slots = fill_slots(message, ctx, card)
    if planner_source == 'llm':
        llm_slots = filter_card_slots(card, slot_values)
        if card.side_effect:
            guarded = dict(deterministic_slots)
            for key, value in llm_slots.items():
                if key.endswith('_id') or key in {'candidate_id', 'resume_id', 'job_id', 'employee_id', 'approval_id'}:
                    continue
                if key in {'target_candidate', 'scheduled_at', 'notes', 'keyword', 'comment', 'action', 'title', 'content'}:
                    if key == 'keyword' and card.id in {
                        'employee.change_submit_confirm',
                        'employee.salary_adjustment_submit_confirm',
                    }:
                        continue
                    if key == 'target_candidate':
                        if looks_like_workset_reference(message) or looks_like_workset_reference(str(value)):
                            continue
                        if str(value).strip() not in (message or ''):
                            continue
                    guarded[key] = value
            guarded['question'] = message
            return drop_empty_values(ground_explicit_entity_slots(
                message,
                card,
                guarded,
                extract_candidate_name=extract_candidate_name,
                extract_employee_name_for_query=extract_employee_name_for_query,
                extract_employee_name_for_action=extract_employee_name_for_action,
            ))
        if card.id == 'smart.data_query':
            guarded: Dict[str, Any] = {}
            if llm_slots.get('limit'):
                guarded['limit'] = llm_slots['limit']
            guarded.update(deterministic_slots)
            guarded['question'] = message
            return drop_empty_values(ground_explicit_entity_slots(
                message,
                card,
                guarded,
                extract_candidate_name=extract_candidate_name,
                extract_employee_name_for_query=extract_employee_name_for_query,
                extract_employee_name_for_action=extract_employee_name_for_action,
            ))
        merged = dict(deterministic_slots)
        merged.update(llm_slots)
        merged['question'] = message
        return drop_empty_values(ground_explicit_entity_slots(
            message,
            card,
            merged,
            extract_candidate_name=extract_candidate_name,
            extract_employee_name_for_query=extract_employee_name_for_query,
            extract_employee_name_for_action=extract_employee_name_for_action,
        ))
    return drop_empty_values(ground_explicit_entity_slots(
        message,
        card,
        filter_card_slots(card, slot_values),
        extract_candidate_name=extract_candidate_name,
        extract_employee_name_for_query=extract_employee_name_for_query,
        extract_employee_name_for_action=extract_employee_name_for_action,
    ))


def ground_explicit_candidate_slots(
    message: str,
    card: AgentSkillCard,
    slots: Dict[str, Any],
    *,
    extract_candidate_name: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Prefer an explicit candidate name over stale WorkSet/history ids."""
    if card.id not in {'candidate.job_fit', 'candidate.evaluation', 'candidate.resume_analysis'}:
        return slots
    subject = extract_candidate_name(message or '')
    if not subject:
        return slots
    grounded = dict(slots or {})
    current_keyword = str(grounded.get('keyword') or '').strip()
    if not current_keyword or current_keyword not in (message or ''):
        grounded['keyword'] = subject
    grounded.pop('candidate_id', None)
    grounded.pop('candidateId', None)
    grounded.pop('resume_id', None)
    grounded.pop('resumeId', None)
    return grounded


def ground_explicit_employee_slots(
    message: str,
    card: AgentSkillCard,
    slots: Dict[str, Any],
    *,
    extract_employee_name_for_query: Callable[[str], Optional[str]],
    extract_employee_name_for_action: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Prefer an explicit employee name over stale or LLM-expanded wrappers."""
    if card.id not in {
        'employee.search',
        'employee.profile',
        'employee.lifecycle_chain',
        'employee.change_impact',
        'employee.change_submit_confirm',
        'employee.salary_adjustment_submit_confirm',
        'attendance.employee_evidence',
        'performance.employee_link',
    }:
        return slots
    subject = extract_employee_name_for_query(message or '') or extract_employee_name_for_action(message or '')
    if not subject:
        return slots
    grounded = dict(slots or {})
    current_keyword = str(grounded.get('keyword') or '').strip()
    if current_keyword != subject:
        grounded['keyword'] = subject
    grounded.pop('employee_id', None)
    grounded.pop('employeeId', None)
    return grounded


def ground_explicit_entity_slots(
    message: str,
    card: AgentSkillCard,
    slots: Dict[str, Any],
    *,
    extract_candidate_name: Callable[[str], Optional[str]],
    extract_employee_name_for_query: Callable[[str], Optional[str]],
    extract_employee_name_for_action: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    grounded = ground_explicit_candidate_slots(
        message,
        card,
        slots,
        extract_candidate_name=extract_candidate_name,
    )
    grounded = ground_explicit_employee_slots(
        message,
        card,
        grounded,
        extract_employee_name_for_query=extract_employee_name_for_query,
        extract_employee_name_for_action=extract_employee_name_for_action,
    )
    return grounded


def slot_guard_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return changes
    for key, raw_before in before.items():
        if str(key).startswith('_') or key not in after:
            continue
        raw_after = after.get(key)
        if raw_before == raw_after:
            continue
        changes.append({
            'field': str(key),
            'before': raw_before,
            'after': raw_after,
            'reason': 'trimmed_colloquial_entity_wrapper',
        })
    return changes


def filter_card_slots(card: AgentSkillCard, slot_values: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(slot_values, dict):
        return {}
    tool = str((card.executor or {}).get('tool') or '')
    spec = skill_registry.get(tool)
    schema = getattr(spec, 'input_schema', None) if spec else None
    allowed = set(card.required_slots or []) | set(card.optional_slots or []) | {'question'}
    if isinstance(schema, dict):
        allowed.update(schema.keys())
    if card.id == 'smart.data_query':
        allowed.discard('sql')
        allowed.discard('explanation')
    filtered: Dict[str, Any] = {}
    for key, raw_value in slot_values.items():
        key_text = str(key)
        if key_text.startswith('_') or key_text in PLANNER_FORBIDDEN_SLOT_KEYS:
            continue
        if key_text not in allowed:
            continue
        filtered[key_text] = raw_value
    return drop_empty_values(filtered)


def sanitize_slot_values(slot_values: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(slot_values, dict):
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in slot_values.items():
        key_text = str(key)
        if key_text.startswith('_') or key_text in PLANNER_FORBIDDEN_SLOT_KEYS:
            continue
        sanitized[key_text] = sanitize_slot_value(value)
    return drop_empty_values(sanitized)


def sanitize_slot_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [sanitize_slot_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key)[:80]: sanitize_slot_value(raw)
            for key, raw in list(value.items())[:40]
            if not str(key).startswith('_')
        }
    return str(value)[:1000]


def drop_empty_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value not in (None, '', [])
    }


__all__ = [
    'PLANNER_FORBIDDEN_SLOT_KEYS',
    'drop_empty_values',
    'filter_card_slots',
    'ground_explicit_candidate_slots',
    'ground_explicit_employee_slots',
    'ground_explicit_entity_slots',
    'guard_slot_values',
    'sanitize_slot_value',
    'sanitize_slot_values',
    'slot_guard_changes',
]
