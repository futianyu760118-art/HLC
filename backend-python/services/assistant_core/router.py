"""Compatibility shim for the retired legacy router name.

The old keyword/LLM router implementation now lives in ``legacy_router.py``.
Keeping it under the public ``router.py`` name made it too easy to reintroduce
regex/direct-route behavior into ordinary assistant traffic.  This module only
projects the current Skill-first planner result into the historical
``RouterResult`` contract for migration callers.
"""

from __future__ import annotations

from .agent_kernel.decision import build_route_decision
from .schemas import AssistantContext, RouterResult, route_decision_to_router_result
from .skill_first.cards import get_card
from .skill_first.planner import plan_skill
from .skill_first.skill_retriever import retrieve_skills
from .skill_first.semantic_index import normalize_query
from .skill_first.understanding import understand_query


def route(message: str, ctx: AssistantContext) -> RouterResult:
    """Return a RouterResult view of the Skill-first Agent Kernel planner."""

    text = (message or '').strip()
    if not text:
        return _clarification_result(text, reason='empty_message')

    understanding = understand_query(text, ctx)
    normalized = str(getattr(understanding, 'normalized_query', '') or normalize_query(text))
    candidates = retrieve_skills(
        text,
        normalized_query=normalized,
        understanding=understanding,
        top_k=16,
    )
    if not candidates:
        return _clarification_result(text, reason='skill_first_router:no_skill_recalled')

    plan = plan_skill(text, ctx, candidates, understanding=understanding)
    card = get_card(str(getattr(plan, 'selected_skill', '') or ''))
    if not card:
        return _clarification_result(
            text,
            reason=str(getattr(plan, 'fallback_reason', '') or 'skill_first_router:no_selected_skill'),
        )

    decision = build_route_decision(card, plan)
    result = route_decision_to_router_result(decision)
    result.route_path = 'skill_first_router_shim'
    result.top_k = [
        (str(item.skill_id), float(getattr(item, 'score', 0.0) or 0.0))
        for item in candidates[:16]
        if getattr(item, 'skill_id', '')
    ]
    result.candidate_skills = [
        str((card.executor or {}).get('tool') or skill)
        for skill in [card.id, *list(getattr(card, 'aliases', []) or [])]
        if skill
    ]
    result.entities = _visible_slots(getattr(plan, 'slot_values', {}) or {})
    result.rule_matched = False
    return result


def _clarification_result(message: str, *, reason: str) -> RouterResult:
    return RouterResult(
        intent='skill_first.clarification',
        task_template_id=None,
        confidence=0.0,
        entities={},
        missing_fields=[],
        risk_level='low',
        candidate_skills=[],
        requires_confirmation=False,
        clarification_question='请补充你要查询或处理的 HRM 模块、对象或时间范围。',
        reason=reason,
        rule_matched=False,
        route_path='skill_first_router_shim',
    )


def _visible_slots(slots: dict) -> dict:
    return {
        str(key): value
        for key, value in (slots or {}).items()
        if value not in (None, '', [])
        and not str(key).startswith('_')
        and key not in {'question', 'sql', 'raw_sql', 'query_plan'}
    }


__all__ = ['route']
