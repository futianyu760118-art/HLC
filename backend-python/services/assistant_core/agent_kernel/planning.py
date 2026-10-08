"""Planner data contracts for the HRM Agent Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..schemas import AssistantContext
from ..skill_first.cards import AgentSkillCard


@dataclass
class SkillPlan:
    normalized_query: str
    selected_skill: Optional[str]
    confidence: float
    slot_values: Dict[str, Any] = field(default_factory=dict)
    missing_slots: List[str] = field(default_factory=list)
    route_reason: str = ''
    rejected_skills: List[Dict[str, Any]] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    planner_source: str = 'deterministic'
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'normalized_query': self.normalized_query,
            'selected_skill': self.selected_skill,
            'confidence': round(self.confidence, 4),
            'slot_values': dict(self.slot_values),
            'missing_slots': list(self.missing_slots),
            'route_reason': self.route_reason,
            'rejected_skills': list(self.rejected_skills),
            'fallback_reason': self.fallback_reason,
            'planner_source': self.planner_source,
            'diagnostics': dict(self.diagnostics),
        }


def deterministic_candidate_plan(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    *,
    normalize_query: Callable[[str], str],
    get_card: Callable[[str], Optional[AgentSkillCard]],
    fill_slots: Callable[[str, AssistantContext, Optional[AgentSkillCard]], Dict[str, Any]],
    missing_required_slots: Callable[[Optional[AgentSkillCard], Dict[str, Any], AssistantContext], List[str]],
    min_confidence: float,
) -> SkillPlan:
    normalized = normalize_query(message)
    if not candidates:
        return SkillPlan(
            normalized_query=normalized,
            selected_skill=None,
            confidence=0.0,
            fallback_reason='no_skill_recalled',
            route_reason='semantic_index_returned_empty',
            diagnostics={
                'stage': 'planner',
                'planner_mode': 'deterministic_candidate_order',
                'fallback_reason': 'no_skill_recalled',
            },
        )

    best = candidates[0]
    selected = best.skill_id
    confidence = candidate_order_confidence(float(best.score or 0.0))

    card = get_card(selected)
    slot_values = fill_slots(message, ctx, card) if card else {}
    missing_slots = missing_required_slots(card, slot_values, ctx) if card else []

    rejected = [
        {
            'skill_id': item.skill_id,
            'reason': 'lower_semantic_score_or_anti_example_penalty',
            'score': round(item.score, 4),
        }
        for item in candidates[1:]
    ]
    fallback_reason = None
    if confidence < min_confidence:
        fallback_reason = 'low_confidence'
    elif missing_slots and card and card.side_effect:
        fallback_reason = 'missing_required_side_effect_slots'
        confidence = min(confidence, 0.62)
    return SkillPlan(
        normalized_query=normalized,
        selected_skill=selected,
        confidence=confidence,
        slot_values=slot_values,
        missing_slots=missing_slots,
        route_reason=f'candidate_order_fallback:{best.match_reason}',
        rejected_skills=rejected,
        fallback_reason=fallback_reason,
        diagnostics={
            'stage': 'planner',
            'planner_mode': 'deterministic_candidate_order',
            'candidate_count': len(candidates),
            'top_candidate': best.skill_id,
            'top_candidate_score': round(float(best.score or 0.0), 4),
            'fallback_reason': fallback_reason,
        },
    )


def candidate_order_confidence(score: float) -> float:
    confidence = min(0.96, score / max(score + 2.8, 1.0))
    if score >= 6:
        return max(confidence, 0.82)
    if score >= 3.5:
        return max(confidence, 0.68)
    if score >= 2:
        return max(confidence, 0.54)
    return min(confidence, 0.46)


__all__ = ['SkillPlan', 'candidate_order_confidence', 'deterministic_candidate_plan']
