"""Planner model-output parsing for the HRM Agent Kernel."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from .planner_slots import sanitize_slot_values
from .planning import SkillPlan


def normalize_llm_plan(
    raw: Any,
    message: str,
    candidates: Sequence[Any],
    *,
    normalize_query: Callable[[str], str],
) -> Optional[SkillPlan]:
    if not isinstance(raw, dict):
        return None
    candidate_ids = {item.skill_id for item in candidates}
    selected = raw.get('selected_skill') or raw.get('selectedSkill')
    if selected is not None:
        selected = str(selected)
    if selected and selected not in candidate_ids:
        return None
    try:
        confidence = max(0.0, min(float(raw.get('confidence')), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    rejected = raw.get('rejected_skills') or raw.get('rejectedSkills')
    if not isinstance(rejected, list):
        rejected = default_rejected_skills(candidates, selected)
    slot_values = raw.get('slot_values') or raw.get('slotValues') or {}
    if not isinstance(slot_values, dict):
        slot_values = {}
    missing_slots = raw.get('missing_slots') or raw.get('missingSlots') or []
    if not isinstance(missing_slots, list):
        missing_slots = []
    return SkillPlan(
        normalized_query=str(raw.get('normalized_query') or raw.get('normalizedQuery') or normalize_query(message)),
        selected_skill=selected,
        confidence=confidence,
        slot_values=sanitize_slot_values(slot_values),
        missing_slots=[str(item) for item in missing_slots],
        route_reason=str(raw.get('route_reason') or raw.get('routeReason') or 'llm_rerank'),
        rejected_skills=[item for item in rejected if isinstance(item, dict)],
        planner_source='llm',
    )


def default_rejected_skills(candidates: Sequence[Any], selected: Optional[str]) -> List[Dict[str, Any]]:
    return [
        {
            'skill_id': item.skill_id,
            'reason': 'not_selected_by_llm_reranker',
            'score': round(float(item.score or 0.0), 4),
        }
        for item in candidates
        if item.skill_id != selected
    ]


def diagnostic_status_from_llm_meta(meta: Dict[str, Any]) -> str:
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


__all__ = [
    'default_rejected_skills',
    'diagnostic_status_from_llm_meta',
    'normalize_llm_plan',
]
