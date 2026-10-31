"""Skill-first compatibility planner for the retired intent-router planner.

The old route-file planner now lives in ``legacy_planner.py``.  This public
module keeps the historical ``build_route_decision(message, ctx)`` API, but the
decision comes from formal Agent Skill Cards and the restricted Skill-first
planner instead of regex/direct-route task templates.
"""

from __future__ import annotations

from services.business_time import business_now

from ..agent_kernel.decision import build_route_decision as _build_skill_route_decision
from ..schemas import AssistantContext, RouteDecision
from ..skill_first.cards import get_card
from ..skill_first.planner import plan_skill
from ..skill_first.semantic_index import normalize_query
from ..skill_first.skill_retriever import retrieve_skills
from ..skill_first.understanding import understand_query


def build_route_decision(message: str, ctx: AssistantContext) -> RouteDecision:
    """Project the Skill-first planner result into a RouteDecision.

    This shim intentionally does not import legacy planner, legacy router,
    ``routing.route`` or regex/direct-route helpers. Legacy planner regression
    tests should import ``intent_router.legacy_planner`` explicitly.
    """

    text = (message or '').strip()
    if not text:
        return _clarification_decision('empty_message')

    understanding = understand_query(text, ctx)
    normalized = str(getattr(understanding, 'normalized_query', '') or normalize_query(text))
    candidates = retrieve_skills(
        text,
        normalized_query=normalized,
        understanding=understanding,
        top_k=16,
    )
    if not candidates:
        return _clarification_decision('skill_first_planner:no_skill_recalled')

    plan = plan_skill(text, ctx, candidates, understanding=understanding)
    card = get_card(str(getattr(plan, 'selected_skill', '') or ''))
    if not card:
        return _clarification_decision(
            str(getattr(plan, 'fallback_reason', '') or 'skill_first_planner:no_selected_skill'),
        )

    decision = _build_skill_route_decision(card, plan)
    decision.reason = (
        f'{decision.reason}; intent_router_planner_shim'
        if decision.reason
        else 'intent_router_planner_shim'
    )
    return decision


def _clarification_decision(reason: str) -> RouteDecision:
    return RouteDecision(
        task_type='clarification',
        route_track='C_DIALOGUE_KNOWLEDGE',
        intent='skill_first.clarification',
        confidence=0.0,
        risk_level='low',
        clarification_question='请补充你要查询或处理的 HRM 模块、对象或时间范围。',
        fallback_policy='skill_first_clarify',
        reason=reason,
    )


__all__ = ['build_route_decision', 'business_now']
