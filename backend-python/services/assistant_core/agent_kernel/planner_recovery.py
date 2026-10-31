"""Schema-grounded planner degraded-recovery policy for Agent Kernel."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from ..schemas import AssistantContext
from ..skill_first.cards import AgentSkillCard
from .planning import SkillPlan, deterministic_candidate_plan


SCHEMA_GROUNDED_RECOVERY_REASONS = {
    'explicit_object_read_schema_slots',
    'schema_slots_support_top_candidate_despite_soft_anti_overlap',
    'structural_candidate_signal',
    'formal_unsupported_write_boundary_candidate',
    'side_effect_candidate_recovered_for_pending_confirmation',
}


def should_retry_planner_decision(candidates: Sequence[Any]) -> bool:
    if not candidates:
        return False
    best = candidates[0]
    second_score = float(getattr(candidates[1], 'score', 0.0) or 0.0) if len(candidates) > 1 else 0.0
    score = float(getattr(best, 'score', 0.0) or 0.0)
    anti_score = float(getattr(best, 'anti_score', 0.0) or 0.0)
    reason = str(getattr(best, 'match_reason', '') or '')
    if 'candidate_signal:structural_intent' in reason:
        return True
    if score >= 9.0 and anti_score <= 0.35:
        return True
    if score >= 6.0 and (score - second_score) >= 0.75 and anti_score <= 0.25:
        return True
    return False


def retry_planner_decision(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    understanding: Any,
    diagnostics: Dict[str, Any],
    *,
    first_pass_status: str,
    retry_candidate_limit: int,
    retry_prompt_mode: str,
    min_confidence: float,
    planner_timeout: Callable[[], float],
    planner_retry_messages: Callable[[str, AssistantContext, Sequence[Any], Any, str], List[Dict[str, str]]],
    normalize_llm_plan: Callable[[Any, str, Sequence[Any]], Optional[SkillPlan]],
    diagnostic_status_from_llm_meta: Callable[[Dict[str, Any]], str],
    llm_json_chat_profile: Callable[..., Any],
    llm_last_call_meta: Callable[[], Dict[str, Any]],
    record_call_result: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    record_failure: Callable[[str, Dict[str, Any]], Dict[str, Any]],
) -> Optional[SkillPlan]:
    """Run a bounded second LLM decision when the first pass was too conservative."""

    if not candidates:
        return None
    top_candidates = list(candidates)[:retry_candidate_limit]
    if not top_candidates:
        return None
    if not should_retry_planner_decision(top_candidates):
        diagnostics['retry_decision'] = {
            'attempted': False,
            'prompt_mode': retry_prompt_mode,
            'first_pass_status': first_pass_status,
            'status': 'skipped_weak_recall',
            'accepted': False,
        }
        return None
    try:
        retry_timeout = min(planner_timeout(), 10)
        raw = llm_json_chat_profile(
            'small',
            planner_retry_messages(
                message,
                ctx,
                top_candidates,
                understanding,
                first_pass_status,
            ),
            temperature=0.02,
            max_tokens=260,
            timeout=retry_timeout,
            use_case='skill_first_planner',
            retry_once=False,
            ctx=ctx,
        )
        retry_meta = llm_last_call_meta()
        try:
            diagnostics['llm_health'] = record_call_result('skill_first_planner', retry_meta)
        except Exception as health_exc:
            diagnostics['llm_retry_health_error'] = {
                'stage': 'retry_health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
        retry_diagnostics: Dict[str, Any] = {
            'attempted': True,
            'prompt_mode': retry_prompt_mode,
            'first_pass_status': first_pass_status,
            'timeout_seconds': retry_timeout,
            'llm_call': retry_meta,
            'raw_type': type(raw).__name__,
        }
        retry_plan = normalize_llm_plan(raw, message, top_candidates)
        if retry_plan and retry_plan.selected_skill and retry_plan.confidence >= min_confidence:
            retry_plan.planner_source = 'llm'
            retry_plan.route_reason = retry_plan.route_reason or 'llm_retry_selected_skill'
            retry_plan.diagnostics = {
                **diagnostics,
                'status': 'accepted',
                'accepted': True,
                'selected_skill': retry_plan.selected_skill,
                'confidence': round(float(retry_plan.confidence or 0.0), 4),
                'retry_decision': {
                    **retry_diagnostics,
                    'status': 'accepted',
                    'accepted': True,
                    'selected_skill': retry_plan.selected_skill,
                    'confidence': round(float(retry_plan.confidence or 0.0), 4),
                },
            }
            return retry_plan
        diagnostics['retry_decision'] = {
            **retry_diagnostics,
            'status': diagnostic_status_from_llm_meta(retry_meta),
            'accepted': False,
            'raw_selected_skill': (
                str((raw or {}).get('selected_skill') or (raw or {}).get('selectedSkill'))
                if isinstance(raw, dict) and ((raw or {}).get('selected_skill') or (raw or {}).get('selectedSkill'))
                else None
            ),
        }
        return None
    except Exception as exc:
        try:
            diagnostics['llm_health'] = record_failure(
                'skill_first_planner',
                {
                    'status': 'error',
                    'error_type': type(exc).__name__,
                    'stage': 'retry_decision',
                },
            )
        except Exception as health_exc:
            diagnostics['llm_retry_health_error'] = {
                'stage': 'retry_health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
        diagnostics['retry_decision'] = {
            'attempted': True,
            'prompt_mode': retry_prompt_mode,
            'first_pass_status': first_pass_status,
            'status': 'exception',
            'accepted': False,
            'error_type': type(exc).__name__,
            'error': str(exc)[:180],
        }
        return None


def llm_unusable_recovery_plan(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    diagnostics: Dict[str, Any],
    *,
    require_schema_grounding: bool = False,
    normalize_query: Callable[[str], str],
    get_card: Callable[[str], Optional[AgentSkillCard]],
    fill_slots: Callable[[str, AssistantContext, Optional[AgentSkillCard]], Dict[str, Any]],
    missing_required_slots: Callable[[Optional[AgentSkillCard], Dict[str, Any], AssistantContext], List[str]],
    detect_write_intent: Callable[[str], Optional[str]],
    min_confidence: float,
    guard_plan: Callable[[str, AssistantContext, Sequence[Any], SkillPlan], SkillPlan],
) -> SkillPlan:
    """Recover from an attempted-but-unusable LLM planner when recall is clear.

    This remains a bounded Agent Kernel recovery path, not a regex/direct-route
    fallback. The selected Skill must already be the top recalled Skill Card,
    recall must be strong or schema grounded, and the recovered plan still runs
    through the planner guard callback before execution.
    """

    status = str(diagnostics.get('status') or 'llm_planner_unusable')
    base_rejected = [
        {
            'skill_id': item.skill_id,
            'reason': 'candidate_signal_only_llm_planner_unusable',
            'score': round(item.score, 4),
        }
        for item in candidates
    ]
    if not candidates:
        return SkillPlan(
            normalized_query=normalize_query(message),
            selected_skill=None,
            confidence=0.0,
            slot_values={'question': message},
            missing_slots=[],
            route_reason='llm_planner_failed_without_bounded_decision',
            rejected_skills=base_rejected,
            fallback_reason='llm_planner_unusable',
            planner_source='llm',
            diagnostics={
                **diagnostics,
                'status': status,
                'accepted': False,
                'deterministic_fallback_used': False,
                'deterministic_fallback_blocked': True,
                'deterministic_fallback_block_reason': 'no_candidates_after_enabled_llm_failure',
                'degraded_recovery_used': False,
            },
        )

    best = candidates[0]
    second_score = float(candidates[1].score or 0.0) if len(candidates) > 1 else 0.0
    card = get_card(best.skill_id)
    strong_score = float(best.score or 0.0) >= 9.0
    separated = (float(best.score or 0.0) - second_score) >= 0.65 or (
        'candidate_signal:structural_intent' in str(best.match_reason or '')
    )
    assessment = assess_llm_recovery(
        message,
        ctx,
        candidates,
        get_card=get_card,
        fill_slots=fill_slots,
        detect_write_intent=detect_write_intent,
    )
    assessment_reason = str(assessment.get('reason') or '')
    schema_grounded_recovery = assessment_reason in SCHEMA_GROUNDED_RECOVERY_REASONS
    recall_clear_enough = (strong_score and separated) or schema_grounded_recovery
    if require_schema_grounding and not schema_grounded_recovery:
        assessment = {
            **assessment,
            'allowed': False,
            'blocked_by': 'low_confidence_requires_schema_grounded_recovery',
        }
    if not card or not recall_clear_enough or not assessment['allowed']:
        return SkillPlan(
            normalized_query=normalize_query(message),
            selected_skill=None,
            confidence=0.0,
            slot_values={'question': message},
            missing_slots=[],
            route_reason='llm_planner_failed_without_bounded_decision',
            rejected_skills=base_rejected,
            fallback_reason='llm_planner_unusable',
            planner_source='llm',
            diagnostics={
                **diagnostics,
                'status': status,
                'accepted': False,
                'deterministic_fallback_used': False,
                'deterministic_fallback_blocked': True,
                'deterministic_fallback_block_reason': 'enabled_llm_planner_failed_and_recall_not_clear_enough',
                'degraded_recovery_used': False,
                'top_candidate_score': round(float(best.score or 0.0), 4),
                'second_candidate_score': round(second_score, 4),
                'top_candidate_anti_score': round(float(getattr(best, 'anti_score', 0.0) or 0.0), 4),
                'degraded_recovery_assessment': assessment,
            },
        )

    recovered = deterministic_candidate_plan(
        message,
        ctx,
        candidates,
        normalize_query=normalize_query,
        get_card=get_card,
        fill_slots=fill_slots,
        missing_required_slots=missing_required_slots,
        min_confidence=min_confidence,
    )
    recovered.planner_source = 'llm_degraded_recovery'
    recovered.route_reason = f'llm_unusable_schema_guarded_recovery:{best.match_reason}'
    recovered.diagnostics = {
        **diagnostics,
        **dict(recovered.diagnostics or {}),
        'status': status,
        'accepted': False,
        'deterministic_fallback_used': False,
        'deterministic_fallback_blocked': True,
        'deterministic_fallback_block_reason': 'enabled_llm_planner_failed_or_returned_invalid_plan',
        'degraded_recovery_used': True,
        'degraded_recovery_policy': 'top_k_only_strong_recall_schema_guarded',
        'degraded_recovery_requires_schema_grounding': require_schema_grounding,
        'degraded_recovery_skill': best.skill_id,
        'degraded_recovery_assessment': assessment,
        'top_candidate_score': round(float(best.score or 0.0), 4),
        'second_candidate_score': round(second_score, 4),
    }
    if recovered.fallback_reason == 'low_confidence':
        recovered.fallback_reason = None
    return guard_plan(message, ctx, candidates, recovered)


def assess_llm_recovery(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    *,
    get_card: Callable[[str], Any],
    fill_slots: Callable[[str, AssistantContext, Any], Dict[str, Any]],
    detect_write_intent: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    if not candidates:
        return {'allowed': False, 'reason': 'no_candidates'}
    best = candidates[0]
    card = get_card(str(getattr(best, 'skill_id', '') or ''))
    if not card:
        return {'allowed': False, 'reason': 'top_skill_card_not_found'}
    if card.id == 'system.unsupported_write_intent':
        return {
            'allowed': True,
            'reason': 'formal_unsupported_write_boundary_candidate',
            'slot_keys': [],
        }
    if getattr(card, 'side_effect', False):
        slots = fill_slots(message, ctx, card)
        score = float(getattr(best, 'score', 0.0) or 0.0)
        second_score = float(getattr(candidates[1], 'score', 0.0) or 0.0) if len(candidates) > 1 else 0.0
        anti_score = float(getattr(best, 'anti_score', 0.0) or 0.0)
        reason = str(getattr(best, 'match_reason', '') or '')
        explicit_required = [
            slot
            for slot in getattr(card, 'required_slots', []) or []
            if (slots or {}).get(slot)
        ]
        strong_side_effect_recall = (
            'candidate_signal:structural_intent' in reason
            or (score >= 7.0 and anti_score <= 0.55)
            or (score >= 5.5 and (score - second_score) >= 0.6 and anti_score <= 0.45)
        )
        if strong_side_effect_recall and (explicit_required or score >= 8.5):
            return {
                'allowed': True,
                'reason': 'side_effect_candidate_recovered_for_pending_confirmation',
                'skill_id': card.id,
                'slot_keys': sorted(key for key, value in (slots or {}).items() if value),
                'anti_score': round(anti_score, 4),
                'score_gap': round(score - second_score, 4),
            }
        return {
            'allowed': False,
            'reason': 'side_effect_candidate_not_grounded_enough_for_recovery',
            'skill_id': card.id,
            'slot_keys': sorted(key for key, value in (slots or {}).items() if value),
            'anti_score': round(anti_score, 4),
        }
    if detect_write_intent(message):
        return {
            'allowed': False,
            'reason': 'write_intent_requires_guardrail_boundary',
            'skill_id': card.id,
        }
    slots = fill_slots(message, ctx, card)
    business_slots = {
        key: value
        for key, value in (slots or {}).items()
        if key not in {'question', 'module', 'limit', 'top_n', 'include_stats'}
    }
    score = float(getattr(best, 'score', 0.0) or 0.0)
    second_score = float(getattr(candidates[1], 'score', 0.0) or 0.0) if len(candidates) > 1 else 0.0
    anti_score = float(getattr(best, 'anti_score', 0.0) or 0.0)
    reason = str(getattr(best, 'match_reason', '') or '')
    if 'candidate_signal:structural_intent' in reason:
        return {
            'allowed': True,
            'reason': 'structural_candidate_signal',
            'slot_keys': sorted(business_slots),
            'anti_score': round(anti_score, 4),
        }
    if anti_score <= 0.25:
        return {
            'allowed': True,
            'reason': 'anti_examples_clear',
            'slot_keys': sorted(business_slots),
            'anti_score': round(anti_score, 4),
        }
    if business_slots and score >= 8.0 and (score - second_score) >= 1.5 and anti_score <= 0.55:
        return {
            'allowed': True,
            'reason': 'schema_slots_support_top_candidate_despite_soft_anti_overlap',
            'slot_keys': sorted(business_slots),
            'anti_score': round(anti_score, 4),
            'score_gap': round(score - second_score, 4),
        }
    if (
        has_explicit_object_read_slots(card, business_slots)
        and score >= 7.0
        and anti_score <= 0.55
    ):
        return {
            'allowed': True,
            'reason': 'explicit_object_read_schema_slots',
            'slot_keys': sorted(business_slots),
            'anti_score': round(anti_score, 4),
            'score_gap': round(score - second_score, 4),
        }
    return {
        'allowed': False,
        'reason': 'anti_examples_or_schema_slots_not_clear_enough',
        'slot_keys': sorted(business_slots),
        'anti_score': round(anti_score, 4),
        'score_gap': round(score - second_score, 4),
    }


def has_explicit_object_read_slots(card: Any, business_slots: Dict[str, Any]) -> bool:
    if getattr(card, 'side_effect', False):
        return False
    explicit_slot_keys = {
        'keyword',
        'candidate_id',
        'candidateId',
        'resume_id',
        'resumeId',
        'employee_id',
        'employeeId',
        'job_keyword',
        'job_id',
        'jobId',
        'approval_id',
        'approvalId',
        'history_id',
        'historyId',
    }
    return any(key in business_slots and business_slots.get(key) for key in explicit_slot_keys)


__all__ = [
    'SCHEMA_GROUNDED_RECOVERY_REASONS',
    'assess_llm_recovery',
    'has_explicit_object_read_slots',
    'llm_unusable_recovery_plan',
    'retry_planner_decision',
    'should_retry_planner_decision',
]
