"""Skill-first compatibility pipeline for the retired IntentRouter v2 name.

This module projects the current Agent Kernel Skill-first planner into the old
``RouterResult`` contract only.  The public name must stay free of retired
embedding/rerank/feature-flag routing behavior.
"""

from __future__ import annotations

import time
from ..agent_kernel.decision import build_route_decision
from ..schemas import AssistantContext, RouterResult, route_decision_to_router_result
from ..skill_first.cards import get_card
from ..skill_first.planner import plan_skill
from ..skill_first.semantic_index import normalize_query
from ..skill_first.skill_retriever import retrieve_skills
from ..skill_first.understanding import understand_query


class _EmbeddingClientFacade:
    """Retained only so old imports fail softly during migration."""

    def embed(self, text: str) -> None:
        return None

    def embed_corpus(self, text: str) -> None:
        return None


def _ensure_index_built() -> None:
    """No-op: Skill-first retrieval builds from formal Skill Cards."""


def _on_task_registry_reload() -> None:
    """No-op: Skill-first Skill Card reload is not task-template driven."""


def route(message: str, ctx: AssistantContext) -> RouterResult:
    """Return a RouterResult projection of the Skill-first Agent Kernel plan."""

    text = (message or '').strip()
    if not text:
        return _clarification_result(reason='empty_message')

    start = time.perf_counter()
    understanding = understand_query(text, ctx)
    normalized = str(getattr(understanding, 'normalized_query', '') or normalize_query(text))
    candidates = retrieve_skills(
        text,
        normalized_query=normalized,
        understanding=understanding,
        top_k=16,
    )
    if not candidates:
        result = _clarification_result(reason='skill_first_pipeline:no_skill_recalled')
    else:
        plan = plan_skill(text, ctx, candidates, understanding=understanding)
        card = get_card(str(getattr(plan, 'selected_skill', '') or ''))
        if not card:
            result = _clarification_result(
                reason=str(
                    getattr(plan, 'fallback_reason', '')
                    or 'skill_first_pipeline:no_selected_skill'
                ),
            )
        else:
            decision = build_route_decision(card, plan)
            result = route_decision_to_router_result(decision)
            result.route_path = 'skill_first_pipeline_shim'
            result.reason = (
                f'{result.reason}; skill_first_pipeline_shim'
                if result.reason
                else 'skill_first_pipeline_shim'
            )
            result.entities = _visible_slots(getattr(plan, 'slot_values', {}) or {})

        result.top_k = [
            (str(item.skill_id), float(getattr(item, 'score', 0.0) or 0.0))
            for item in candidates[:16]
            if getattr(item, 'skill_id', '')
        ]
        result.candidate_skills = [
            str(item.skill_id)
            for item in candidates[:16]
            if getattr(item, 'skill_id', '')
        ]

    result.entity_resolved = {
        'normalized_query': normalized if 'normalized' in locals() else text,
        'source': 'skill_first_pipeline_shim',
    }
    result.low_confidence_warning = bool(float(result.confidence or 0.0) < 0.5)
    result.top_k = list(result.top_k or [])
    result.clarification_options = list(result.clarification_options or [])
    result._latency_ms = (time.perf_counter() - start) * 1000.0  # type: ignore[attr-defined]
    return result


def _maybe_write_fallback_sample(
    message: str,
    ctx: AssistantContext,
    result: RouterResult,
) -> None:
    """No-op compatibility hook.

    Skill-first failure learning is owned by ``skill_first.failure_samples``.
    Historical IntentRouter fallback sampling remains in its explicit retired
    module for migration tests only.
    """


def _clarification_result(*, reason: str) -> RouterResult:
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
        route_path='skill_first_pipeline_shim',
    )


def _visible_slots(slots: dict) -> dict:
    return {
        str(key): value
        for key, value in (slots or {}).items()
        if value not in (None, '', [])
        and not str(key).startswith('_')
        and key not in {'question', 'sql', 'raw_sql', 'query_plan'}
    }


__all__ = [
    'route',
    '_ensure_index_built',
    '_on_task_registry_reload',
    '_EmbeddingClientFacade',
    '_maybe_write_fallback_sample',
]
