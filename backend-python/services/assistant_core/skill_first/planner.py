"""Restricted planner/reranker for Skill-first routing."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import llm_client, workset_store
from ..agent_kernel import decision as kernel_decision
from ..agent_kernel import planning as kernel_planning
from ..agent_kernel.planning import SkillPlan
from ..agent_kernel import planner_catalog as kernel_planner_catalog
from ..agent_kernel import planner_followup as kernel_planner_followup
from ..agent_kernel import planner_guard as kernel_planner_guard
from ..agent_kernel import planner_output as kernel_planner_output
from ..agent_kernel import planner_prompt as kernel_planner_prompt
from ..agent_kernel import planner_recovery as kernel_planner_recovery
from ..agent_kernel import planner_slot_extraction as kernel_planner_slot_extraction
from ..agent_kernel import planner_slots as kernel_planner_slots
from ..guardrails import detect_write_intent
from ..schemas import AssistantContext, RouteDecision
from . import llm_health
from .cards import AgentSkillCard, get_card
from . import llm_runtime_config
from .semantic_index import (
    RecallResult,
    normalize_query,
)
from .understanding import UnderstandingResult


MIN_CONFIDENCE = 0.48
HIGH_CONFIDENCE = 0.72
LOW_CONFIDENCE_RECOVERY_FLOOR = 0.25
PLANNER_FORBIDDEN_SLOT_KEYS = kernel_planner_slots.PLANNER_FORBIDDEN_SLOT_KEYS
LLM_PLANNER_CANDIDATE_LIMIT = kernel_planner_prompt.PLANNER_CANDIDATE_LIMIT
LLM_PLANNER_PROMPT_MODE = kernel_planner_prompt.PLANNER_PROMPT_MODE
LLM_PLANNER_RETRY_CANDIDATE_LIMIT = kernel_planner_prompt.PLANNER_RETRY_CANDIDATE_LIMIT
LLM_PLANNER_RETRY_PROMPT_MODE = kernel_planner_prompt.PLANNER_RETRY_PROMPT_MODE


def _candidate_cards(candidates: Sequence[RecallResult]) -> List[AgentSkillCard]:
    cards: List[AgentSkillCard] = []
    for item in candidates:
        card = get_card(item.skill_id)
        if card:
            cards.append(card)
    return cards


def _llm_availability() -> Tuple[bool, str]:
    flag = os.getenv('ASSISTANT_SKILL_FIRST_LLM')
    if flag is not None and flag.strip().lower() in {'0', 'false', 'off', 'no'}:
        return False, 'disabled_by_env'
    if not llm_client.is_available():
        return False, 'llm_unavailable'
    health_allowed, health_reason, _health = llm_health.availability('skill_first_planner')
    if not health_allowed:
        return False, health_reason
    return True, 'available'


def _llm_enabled() -> bool:
    enabled, _reason = _llm_availability()
    return enabled


def _planner_messages(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[RecallResult],
    understanding: Optional[UnderstandingResult] = None,
) -> List[Dict[str, str]]:
    return kernel_planner_prompt.planner_messages(
        message,
        ctx,
        candidates,
        understanding=understanding,
        normalize_query=normalize_query,
    )


def _planner_retry_messages(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[RecallResult],
    understanding: Optional[UnderstandingResult] = None,
    first_pass_status: str = '',
) -> List[Dict[str, str]]:
    return kernel_planner_prompt.planner_retry_messages(
        message,
        ctx,
        candidates,
        understanding=understanding,
        first_pass_status=first_pass_status,
        normalize_query=normalize_query,
        get_card=get_card,
    )


def plan_skill(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[RecallResult],
    understanding: Optional[UnderstandingResult] = None,
) -> SkillPlan:
    enabled, availability_reason = _llm_availability()
    diagnostics: Dict[str, Any] = {
        'stage': 'planner',
        'use_case': 'skill_first_planner',
        'prompt_mode': LLM_PLANNER_PROMPT_MODE,
        'planner_candidate_limit': LLM_PLANNER_CANDIDATE_LIMIT,
        'llm_enabled': enabled,
        'availability': availability_reason,
        'status': availability_reason,
        'attempted': False,
        'accepted': False,
        'candidate_count': len(candidates),
        'candidate_ids': [item.skill_id for item in candidates],
        'llm_health': llm_health.availability('skill_first_planner')[2],
    }
    if enabled and candidates:
        try:
            diagnostics['attempted'] = True
            timeout_seconds = llm_runtime_config.planner_timeout()
            diagnostics['timeout_seconds'] = timeout_seconds
            raw = llm_client.json_chat_profile(
                'small',
                _planner_messages(message, ctx, candidates, understanding=understanding),
                temperature=0.05,
                max_tokens=320,
                timeout=timeout_seconds,
                use_case='skill_first_planner',
                retry_once=False,
                ctx=ctx,
            )
            llm_meta = llm_client.last_call_meta()
            try:
                diagnostics['llm_health'] = llm_health.record_call_result('skill_first_planner', llm_meta)
            except Exception as health_exc:
                diagnostics['llm_health_error'] = {
                    'stage': 'health_recording',
                    'error_type': type(health_exc).__name__,
                    'error': str(health_exc)[:180],
                }
            diagnostics['llm_call'] = llm_meta
            diagnostics['raw_type'] = type(raw).__name__
            candidate_ids = {item.skill_id for item in candidates}
            raw_selected = None
            if isinstance(raw, dict):
                raw_selected = raw.get('selected_skill') or raw.get('selectedSkill')
                if raw_selected is not None:
                    raw_selected = str(raw_selected)
                diagnostics['raw_selected_skill'] = raw_selected
                try:
                    diagnostics['raw_confidence'] = round(float(raw.get('confidence') or 0.0), 4)
                except (TypeError, ValueError):
                    diagnostics['raw_confidence'] = None
            if raw_selected and raw_selected not in candidate_ids:
                return SkillPlan(
                    normalized_query=normalize_query(message),
                    selected_skill=None,
                    confidence=0.0,
                    fallback_reason='llm_selected_skill_outside_top_k',
                    route_reason='llm_candidate_boundary_rejected',
                    planner_source='llm',
                    diagnostics={
                        **diagnostics,
                        'status': 'rejected',
                        'accepted': False,
                        'reject_reason': 'selected_skill_outside_top_k',
                    },
                )
            plan = kernel_planner_output.normalize_llm_plan(
                raw,
                message,
                candidates,
                normalize_query=normalize_query,
            )
            if plan and (plan.selected_skill is None or any(c.skill_id == plan.selected_skill for c in candidates)):
                if plan.selected_skill is None:
                    diagnostics.update({
                        'status': 'llm_returned_null_skill',
                        'accepted': False,
                        'confidence': round(float(plan.confidence or 0.0), 4),
                        'fallback_reason': plan.fallback_reason or 'llm_null_skill',
                    })
                    retry_plan = _retry_planner_decision(
                        message,
                        ctx,
                        candidates,
                        understanding,
                        diagnostics,
                        first_pass_status='llm_returned_null_skill',
                    )
                    if retry_plan:
                        return _guard_plan(message, ctx, candidates, retry_plan)
                    return kernel_planner_recovery.llm_unusable_recovery_plan(
                        message,
                        ctx,
                        candidates,
                        diagnostics,
                        normalize_query=normalize_query,
                        get_card=get_card,
                        fill_slots=fill_slots,
                        missing_required_slots=_missing_required_slots,
                        detect_write_intent=detect_write_intent,
                        min_confidence=MIN_CONFIDENCE,
                        guard_plan=_guard_plan,
                    )
                if plan.confidence >= MIN_CONFIDENCE:
                    plan.diagnostics = {
                        **diagnostics,
                        'status': 'accepted',
                        'accepted': True,
                        'selected_skill': plan.selected_skill,
                        'confidence': round(float(plan.confidence or 0.0), 4),
                    }
                    return _guard_plan(message, ctx, candidates, plan)
                if (
                    plan.selected_skill
                    and candidates
                    and plan.selected_skill == candidates[0].skill_id
                    and plan.confidence >= LOW_CONFIDENCE_RECOVERY_FLOOR
                ):
                    diagnostics.update({
                        'status': 'low_confidence',
                        'accepted': False,
                        'confidence': round(float(plan.confidence or 0.0), 4),
                        'fallback_reason': plan.fallback_reason or 'llm_low_confidence',
                        'raw_selected_skill': plan.selected_skill,
                        'low_confidence_recovery_attempted': True,
                    })
                    retry_plan = _retry_planner_decision(
                        message,
                        ctx,
                        candidates,
                        understanding,
                        diagnostics,
                        first_pass_status='llm_low_confidence',
                    )
                    if retry_plan:
                        return _guard_plan(message, ctx, candidates, retry_plan)
                    return kernel_planner_recovery.llm_unusable_recovery_plan(
                        message,
                        ctx,
                        candidates,
                        diagnostics,
                        normalize_query=normalize_query,
                        get_card=get_card,
                        fill_slots=fill_slots,
                        missing_required_slots=_missing_required_slots,
                        detect_write_intent=detect_write_intent,
                        min_confidence=MIN_CONFIDENCE,
                        guard_plan=_guard_plan,
                    )
                plan.selected_skill = None
                plan.fallback_reason = plan.fallback_reason or 'llm_low_confidence'
                plan.diagnostics = {
                    **diagnostics,
                    'status': 'low_confidence',
                    'accepted': False,
                    'confidence': round(float(plan.confidence or 0.0), 4),
                    'fallback_reason': plan.fallback_reason,
                }
                diagnostics.update({
                    'status': 'llm_low_confidence',
                    'accepted': False,
                    'confidence': round(float(plan.confidence or 0.0), 4),
                    'fallback_reason': plan.fallback_reason,
                    'raw_selected_skill': plan.selected_skill,
                    'low_confidence_schema_recovery_attempted': True,
                })
                recovered = kernel_planner_recovery.llm_unusable_recovery_plan(
                    message,
                    ctx,
                    candidates,
                    diagnostics,
                    require_schema_grounding=True,
                    normalize_query=normalize_query,
                    get_card=get_card,
                    fill_slots=fill_slots,
                    missing_required_slots=_missing_required_slots,
                    detect_write_intent=detect_write_intent,
                    min_confidence=MIN_CONFIDENCE,
                    guard_plan=_guard_plan,
                )
                if recovered.selected_skill:
                    return recovered
                plan.diagnostics = {
                    **dict(plan.diagnostics or {}),
                    'low_confidence_schema_recovery': recovered.diagnostics,
                }
                return _guard_plan(message, ctx, candidates, plan)
            diagnostics.update({
                'status': kernel_planner_output.diagnostic_status_from_llm_meta(diagnostics.get('llm_call') or {}),
                'accepted': False,
            })
        except Exception as exc:
            try:
                diagnostics['llm_health'] = llm_health.record_failure(
                    'skill_first_planner',
                    {
                        'status': 'error',
                        'error_type': type(exc).__name__,
                    },
                )
            except Exception as health_exc:
                diagnostics['llm_health_error'] = {
                    'stage': 'health_recording',
                    'error_type': type(health_exc).__name__,
                    'error': str(health_exc)[:180],
                }
            diagnostics.update({
                'status': 'exception',
                'accepted': False,
                'error_type': type(exc).__name__,
                'error': str(exc)[:180],
            })
    if enabled and diagnostics.get('attempted'):
        return kernel_planner_recovery.llm_unusable_recovery_plan(
            message,
            ctx,
            candidates,
            diagnostics,
            normalize_query=normalize_query,
            get_card=get_card,
            fill_slots=fill_slots,
            missing_required_slots=_missing_required_slots,
            detect_write_intent=detect_write_intent,
            min_confidence=MIN_CONFIDENCE,
            guard_plan=_guard_plan,
        )
    if availability_reason == 'llm_health_circuit_open':
        diagnostics.update({
            'status': 'llm_health_circuit_open',
            'accepted': False,
            'fallback_reason': 'llm_health_circuit_open',
        })
        return kernel_planner_recovery.llm_unusable_recovery_plan(
            message,
            ctx,
            candidates,
            diagnostics,
            normalize_query=normalize_query,
            get_card=get_card,
            fill_slots=fill_slots,
            missing_required_slots=_missing_required_slots,
            detect_write_intent=detect_write_intent,
            min_confidence=MIN_CONFIDENCE,
            guard_plan=_guard_plan,
        )
    deterministic = kernel_planning.deterministic_candidate_plan(
        message,
        ctx,
        candidates,
        normalize_query=normalize_query,
        get_card=get_card,
        fill_slots=fill_slots,
        missing_required_slots=_missing_required_slots,
        min_confidence=MIN_CONFIDENCE,
    )
    deterministic.diagnostics = {
        **diagnostics,
        **dict(deterministic.diagnostics or {}),
        'status': diagnostics.get('status') or availability_reason,
        'accepted': False,
        'deterministic_fallback_used': True,
        'deterministic_fallback_reason': diagnostics.get('status') or availability_reason,
    }
    return _guard_plan(message, ctx, candidates, deterministic)


def _retry_planner_decision(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[RecallResult],
    understanding: Optional[UnderstandingResult],
    diagnostics: Dict[str, Any],
    *,
    first_pass_status: str,
) -> Optional[SkillPlan]:
    return kernel_planner_recovery.retry_planner_decision(
        message,
        ctx,
        candidates,
        understanding,
        diagnostics,
        first_pass_status=first_pass_status,
        retry_candidate_limit=LLM_PLANNER_RETRY_CANDIDATE_LIMIT,
        retry_prompt_mode=LLM_PLANNER_RETRY_PROMPT_MODE,
        min_confidence=MIN_CONFIDENCE,
        planner_timeout=llm_runtime_config.planner_timeout,
        planner_retry_messages=lambda msg, c, top, understanding_value, status: _planner_retry_messages(
            msg,
            c,
            top,
            understanding=understanding_value,
            first_pass_status=status,
        ),
        normalize_llm_plan=lambda raw, msg, top: kernel_planner_output.normalize_llm_plan(
            raw,
            msg,
            top,
            normalize_query=normalize_query,
        ),
        diagnostic_status_from_llm_meta=kernel_planner_output.diagnostic_status_from_llm_meta,
        llm_json_chat_profile=llm_client.json_chat_profile,
        llm_last_call_meta=llm_client.last_call_meta,
        record_call_result=llm_health.record_call_result,
        record_failure=llm_health.record_failure,
    )


def _guard_plan(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[RecallResult],
    plan: SkillPlan,
) -> SkillPlan:
    return kernel_planner_guard.guard_plan(
        message,
        ctx,
        candidates,
        plan,
        high_confidence=HIGH_CONFIDENCE,
        fill_slots=fill_slots,
        guard_slot_values=_guard_slot_values,
        slot_guard_changes=_slot_guard_changes,
    )


def _unsupported_write_boundary_card(
    message: str,
    candidates: Sequence[RecallResult],
    selected_card: AgentSkillCard,
    write_reason: Optional[str],
) -> Optional[AgentSkillCard]:
    return kernel_planner_guard.unsupported_write_boundary_card(message, candidates, selected_card, write_reason)


def _looks_like_workflow_help_request(message: str) -> bool:
    return kernel_planner_guard.looks_like_workflow_help_request(message)


def _apply_skill_card_contract_corrections(
    message: str,
    candidates: Sequence[RecallResult],
    plan: SkillPlan,
    selected_card: AgentSkillCard,
) -> Tuple[SkillPlan, AgentSkillCard]:
    return kernel_planner_guard.apply_skill_card_contract_corrections(
        message,
        candidates,
        plan,
        selected_card,
        high_confidence=HIGH_CONFIDENCE,
    )


def _correct_to_more_specific_candidate(
    candidates: Sequence[RecallResult],
    plan: SkillPlan,
    selected_card: AgentSkillCard,
    *,
    target_skill: str,
    reason: str,
    min_target_score: float,
    min_gap: float,
) -> Optional[Tuple[SkillPlan, AgentSkillCard]]:
    return kernel_planner_guard.correct_to_more_specific_candidate(
        candidates,
        plan,
        target_skill=target_skill,
        reason=reason,
        min_target_score=min_target_score,
        min_gap=min_gap,
        high_confidence=HIGH_CONFIDENCE,
    )


def _looks_like_performance_employee_profile_link_request(message: str) -> bool:
    return kernel_planner_guard.looks_like_performance_employee_profile_link_request(message)


def _looks_like_single_resume_evidence_request(message: str) -> bool:
    return kernel_planner_guard.looks_like_single_resume_evidence_request(message)


def _guard_slot_values(
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    slot_values: Dict[str, Any],
    planner_source: str,
) -> Dict[str, Any]:
    return kernel_planner_slots.guard_slot_values(
        message,
        ctx,
        card,
        slot_values,
        planner_source,
        fill_slots=fill_slots,
        looks_like_workset_reference=_looks_like_workset_reference,
        extract_candidate_name=kernel_planner_slot_extraction.extract_candidate_name,
        extract_employee_name_for_query=kernel_planner_slot_extraction.extract_employee_name_for_query,
        extract_employee_name_for_action=kernel_planner_slot_extraction.extract_employee_name_for_action,
    )


def _slot_guard_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    return kernel_planner_slots.slot_guard_changes(before, after)


def _filter_card_slots(card: AgentSkillCard, slot_values: Dict[str, Any]) -> Dict[str, Any]:
    return kernel_planner_slots.filter_card_slots(card, slot_values)


def _sanitize_slot_values(slot_values: Dict[str, Any]) -> Dict[str, Any]:
    return kernel_planner_slots.sanitize_slot_values(slot_values)


def _sanitize_slot_value(value: Any) -> Any:
    return kernel_planner_slots.sanitize_slot_value(value)


def _drop_empty_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return kernel_planner_slots.drop_empty_values(values)


def fill_slots(message: str, ctx: AssistantContext, card: Optional[AgentSkillCard]) -> Dict[str, Any]:
    text = message or ''
    slots: Dict[str, Any] = {'question': text}
    if not card:
        return slots
    defaults = (card.executor or {}).get('defaults')
    if isinstance(defaults, dict):
        slots.update(defaults)

    keyword = _extract_keyword(text, card)
    if keyword:
        slots.setdefault('keyword', keyword)
    if card.id in {'system.page_capability', 'system.workflow_help'}:
        slots.update(kernel_planner_catalog.page_capability_slots(ctx))
    if card.id == 'system.workflow_help':
        slots.update(kernel_planner_catalog.workflow_help_slots(text, ctx))
    if card.id == 'candidate.job_fit':
        subject = kernel_planner_slot_extraction.extract_candidate_name(text)
        if subject:
            slots['keyword'] = subject
        else:
            resolved_subject = _candidate_reference_slots(text, ctx)
            slots.update({key: value for key, value in resolved_subject.items() if value})
        job_keyword = kernel_planner_slot_extraction.extract_job_keyword(text)
        if job_keyword:
            slots['job_keyword'] = job_keyword
    if card.id == 'candidate.resume_analysis':
        resume_subject = kernel_planner_slot_extraction.extract_resume_subject(text)
        if resume_subject:
            slots['keyword'] = resume_subject
    if card.id in {'employee.search', 'employee.profile', 'employee.lifecycle_chain'}:
        slots.update(_employee_reference_slots(text, ctx))
        employee_name = (
            kernel_planner_slot_extraction.extract_employee_name_for_query(text)
            or kernel_planner_slot_extraction.extract_employee_name_for_action(text)
        )
        if employee_name:
            slots['keyword'] = employee_name
    if card.id == 'employee.change_impact':
        slots.update(_employee_change_slots(text, ctx))
    if card.id == 'candidate.evaluation':
        explicit_subject = kernel_planner_slot_extraction.extract_candidate_name(text)
        if explicit_subject:
            slots['keyword'] = explicit_subject
            slots.pop('candidate_id', None)
            slots.pop('resume_id', None)
        else:
            resolved_subject = _candidate_reference_slots(text, ctx)
            slots.update({key: value for key, value in resolved_subject.items() if value})
    if card.id in {'candidate.match_matrix', 'recruitment.job_candidate_match'}:
        job_keyword = kernel_planner_slot_extraction.extract_job_context_keyword(text)
        if job_keyword:
            slots['keyword'] = job_keyword
    if card.id == 'attendance.employee_evidence':
        slots.update(_employee_reference_slots(text, ctx))
        employee_name = kernel_planner_slot_extraction.extract_employee_name_for_query(text)
        if employee_name:
            slots['keyword'] = employee_name
    if card.id == 'performance.employee_link':
        slots.update(_employee_reference_slots(text, ctx))
        if not re.search(r'(低绩效|绩效低|评分低|低评分).{0,8}(员工|人员|人群|这批)', text):
            employee_name = kernel_planner_slot_extraction.extract_employee_name_for_query(text)
            if employee_name:
                slots['keyword'] = employee_name
        if re.search(r'(低绩效|绩效低|评分低|低评分)', text):
            slots['profile_segment'] = 'low_performance'
        if _looks_like_performance_employee_profile_link_request(text):
            slots.setdefault('link_focus', 'performance_profile')
        if slots.get('profile_segment') == 'low_performance' and not re.search(
            r'[\u4e00-\u9fa5·]{2,8}(?:的)?(?:绩效为什么|绩效低|评分低|表现)',
            text,
        ):
            slots.pop('keyword', None)
    if card.id == 'attendance.reminder_confirm':
        slots.update(kernel_planner_slot_extraction.attendance_reminder_confirm_slots(text))
    month = kernel_planner_slot_extraction.extract_month(text)
    if month:
        slots.setdefault('month', month)
    recent_days = kernel_planner_slot_extraction.extract_recent_days(text)
    if recent_days:
        slots['recent_days'] = recent_days
    limit = kernel_planner_slot_extraction.extract_limit(text)
    if limit:
        slots.setdefault('limit', limit)
        slots.setdefault('top_n', limit)
    if card.id == 'approval.confirm_action':
        action = kernel_planner_slot_extraction.extract_approval_action(text)
        if action:
            slots['action'] = action
        slots.update(_approval_reference_slots(text, ctx))
        comment = kernel_planner_slot_extraction.extract_approval_comment(text)
        if comment:
            slots['comment'] = comment
    if card.id == 'notification.create_confirm':
        slots.update(kernel_planner_slot_extraction.notification_slots(text))
    if card.id == 'task.followup_create_confirm':
        slots.update(kernel_planner_followup.followup_task_slots(text, ctx))
    if card.id == 'employee.change_submit_confirm':
        slots.update(_employee_change_slots(text, ctx))
    if card.id == 'employee.salary_adjustment_submit_confirm':
        slots.update(_salary_adjustment_slots(text, ctx))
    if card.id == 'interview.schedule_confirm_create':
        explicit_candidate = kernel_planner_slot_extraction.extract_candidate_name(text)
        if explicit_candidate:
            slots['target_candidate'] = explicit_candidate
            slots['keyword'] = explicit_candidate
        else:
            slots['target_candidate'] = keyword or _workset_reference_value(text, ctx)
        scheduled_at = kernel_planner_slot_extraction.extract_schedule_hint(text)
        if scheduled_at:
            slots['scheduled_at'] = scheduled_at
    if card.id == 'workset.analysis':
        resolved = workset_store.resolve_mention(text, ctx.session_id)
        if resolved:
            slots['latest_workset_or_item'] = {
                'kind': resolved.get('kind'),
                'workset_id': (resolved.get('workset') or {}).get('id'),
                'entity_id': (resolved.get('item') or {}).get('entity_id'),
            }
    if card.id == 'payroll.employee_self_service':
        slots['employee_scope'] = 'self' if getattr(ctx, 'user_employee_id', None) else None
        if getattr(ctx, 'user_employee_id', None):
            slots.setdefault('employee_id', ctx.user_employee_id)
    return {key: value for key, value in slots.items() if value not in (None, '', [])}


def _missing_required_slots(card: Optional[AgentSkillCard], slot_values: Dict[str, Any], ctx: AssistantContext) -> List[str]:
    return kernel_planner_guard.missing_required_slots(card, slot_values, ctx)


def _extract_keyword(text: str, card: AgentSkillCard) -> Optional[str]:
    if card.id in {'employee.change_submit_confirm', 'employee.salary_adjustment_submit_confirm'}:
        return None
    if card.id in {'system.page_capability', 'system.workflow_help'}:
        return None
    if card.id == 'candidate.recent_resumes' and _is_generic_recent_resume_query(text):
        return None
    if card.id in {'candidate.search', 'candidate.job_fit', 'interview.schedule_confirm_create'}:
        return kernel_planner_slot_extraction.extract_candidate_name(text)
    if card.id in {'candidate.match_matrix', 'recruitment.job_candidate_match'}:
        return kernel_planner_slot_extraction.extract_job_context_keyword(text)
    if card.id in {'recruitment.overview', 'recruitment.open_jobs'}:
        if not re.search(r'[\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位)', text or ''):
            return None
    if card.id == 'recruitment.open_jobs' and re.search(r'(哪些|有哪些|多少|几个|在招|招聘中|开放).{0,8}(岗位|职位)', text or ''):
        return None
    if card.domain in {'attendance', 'payroll', 'performance', 'approval', 'dashboard', 'feedback', 'workset'}:
        return None
    cleaned = re.sub(r'(帮我|请|查一下|看一下|分析一下|给我|最近|这个月|本月|怎么样|咋样|有没有|有哪些|多少|几个)', ' ', text)
    match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·]{2,18})(?:岗位|职位|候选人|简历|员工|这个人|这位|招得|招聘|怎么样|靠不靠谱)', cleaned)
    if match:
        value = match.group(1).strip(' ，,。?？')
        if value and value not in {'最近招聘', '工资这块', '钱这块', '这个月谁', '员工这块'}:
            return value
    name_match = re.search(r'([\u4e00-\u9fa5·]{2,4})(?:的|这个人|这位|靠不靠谱|怎么样|迟到|考勤|绩效|画像)', text)
    if name_match and card.domain in {'candidate', 'employee', 'attendance', 'performance'}:
        return name_match.group(1)
    return None


def _is_generic_recent_resume_query(text: str) -> bool:
    text = text or ''
    if not re.search(r'(简历|投递)', text):
        return False
    if not re.search(r'(最近|近\s*\d+\s*天|本周|本月|收到|收到了|新来|新来的|哪些|有哪些|质量)', text):
        return False
    return not bool(re.search(r'[\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位)', text))


def _unsupported_bulk_or_unsafe_side_effect_intent(message: str, card: AgentSkillCard) -> Optional[str]:
    return kernel_planner_guard.unsupported_bulk_or_unsafe_side_effect_intent(message, card)


def _employee_change_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    slots: Dict[str, Any] = _employee_change_slots_from_history(text, ctx)
    employee_ref = _employee_reference_slots(text, ctx)
    slots.update(employee_ref)
    target_department = kernel_planner_slot_extraction.extract_target_department(text)
    target_position = kernel_planner_slot_extraction.extract_target_position(text)
    if target_department:
        slots['target_department'] = target_department
    if target_position:
        slots['target_position'] = target_position
    effective_date = kernel_planner_slot_extraction.extract_effective_date_hint(text)
    if effective_date:
        slots['effective_date'] = effective_date
    reason = kernel_planner_slot_extraction.extract_action_reason(text)
    if reason:
        slots['reason'] = reason
    return slots


def _employee_change_slots_from_history(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    if not re.search(r'(这个|这条|这次|调岗|转岗|异动|审批|提交|确认|准备|那就|继续)', text or ''):
        return {}
    allowed = {
        'employee_id', 'keyword', 'target_department_id', 'target_department',
        'target_position_id', 'target_position', 'effective_date', 'reason',
    }
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        route_trace = None
        copilot = entry.get('copilot') if isinstance(entry.get('copilot'), dict) else {}
        if isinstance(copilot.get('routeTrace'), dict):
            route_trace = copilot.get('routeTrace')
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        if route_trace is None and isinstance(meta.get('routeTrace'), dict):
            route_trace = meta.get('routeTrace')
        route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
        selected = str((route_trace or {}).get('selected_skill') or (route_trace or {}).get('selectedSkill') or '')
        intent = str(route_decision.get('intent') or '')
        if selected not in {'employee.change_impact', 'employee.change_submit_confirm'} and intent not in {'employee.change_impact', 'employee_change_submit'}:
            continue

        merged: Dict[str, Any] = {}
        slot_fill = (route_trace or {}).get('slot_fill_result') if isinstance((route_trace or {}).get('slot_fill_result'), dict) else {}
        slot_values = slot_fill.get('slot_values') if isinstance(slot_fill.get('slot_values'), dict) else {}
        for key, value in slot_values.items():
            if key in allowed and value not in (None, '', []):
                merged[key] = value
        for step in route_decision.get('toolPlan') or []:
            if not isinstance(step, dict):
                continue
            params = step.get('input') if isinstance(step.get('input'), dict) else {}
            for key, value in params.items():
                if key in allowed and value not in (None, '', []):
                    merged[key] = value
        pending = meta.get('pendingAction') if isinstance(meta.get('pendingAction'), dict) else {}
        for tool in pending.get('tools') or []:
            if not isinstance(tool, dict):
                continue
            params = tool.get('input') if isinstance(tool.get('input'), dict) else {}
            for key, value in params.items():
                if key in allowed and value not in (None, '', []):
                    merged[key] = value
        if merged.get('keyword') or merged.get('employee_id'):
            return merged
    return {}


def _salary_adjustment_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    slots.update(_employee_reference_slots(text, ctx))
    amount = kernel_planner_slot_extraction.extract_salary_adjustment_amount(text)
    if amount:
        slots['salary_adjustment'] = kernel_planner_slot_extraction.format_number(amount)
    effective_date = kernel_planner_slot_extraction.extract_effective_date_hint(text)
    if effective_date:
        slots['effective_date'] = effective_date
    reason = kernel_planner_slot_extraction.extract_action_reason(text)
    if reason:
        slots['reason'] = reason
    return slots


def _employee_reference_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    resolved = workset_store.resolve_mention(text, ctx.session_id)
    if resolved:
        item = resolved.get('item') or {}
        if item.get('entity_type') == 'employee' and item.get('entity_id'):
            return {'employee_id': item.get('entity_id'), 'keyword': item.get('title') or item.get('entity_id')}
        if item.get('title') and re.search(r'(这个|这位|他|她|该员工|上面|刚才|第二个|第\s*\d+\s*个)', text or ''):
            return {'keyword': item.get('title')}

    explicit = kernel_planner_slot_extraction.extract_employee_name_for_action(text)
    if explicit:
        return {'keyword': explicit}

    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        focus = meta.get('lastFocus') if isinstance(meta.get('lastFocus'), dict) else {}
        if focus.get('entity_type') == 'employee':
            if focus.get('entity_id'):
                return {'employee_id': focus.get('entity_id'), 'keyword': focus.get('name') or focus.get('entity_id')}
            if focus.get('name'):
                return {'keyword': focus.get('name')}
        for workset in entry.get('worksets') or []:
            if not isinstance(workset, dict):
                continue
            for item in workset.get('items') or []:
                if isinstance(item, dict) and item.get('entity_type') == 'employee' and item.get('entity_id'):
                    return {'employee_id': item.get('entity_id'), 'keyword': item.get('title') or item.get('entity_id')}
        for entity in entry.get('entities') or []:
            if isinstance(entity, dict) and entity.get('type') == 'employee':
                if entity.get('id'):
                    return {'employee_id': entity.get('id'), 'keyword': entity.get('title') or entity.get('name') or entity.get('id')}
                if entity.get('title') or entity.get('name'):
                    return {'keyword': entity.get('title') or entity.get('name')}
    return {}


def _approval_reference_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    approval_id = kernel_planner_slot_extraction.extract_approval_id(text)
    if approval_id:
        return {'approval_id': approval_id}

    target_index = kernel_planner_slot_extraction.extract_approval_rank(text)
    if target_index:
        slots: Dict[str, Any] = {'target_index': target_index}
    else:
        slots = {}

    resolved = workset_store.resolve_mention(text, ctx.session_id)
    if resolved:
        item = resolved.get('item') if isinstance(resolved.get('item'), dict) else {}
        workset = resolved.get('workset') if isinstance(resolved.get('workset'), dict) else {}
        items = workset.get('items') if isinstance(workset.get('items'), list) else []
        if item and item.get('entity_type') == 'approval' and item.get('entity_id'):
            slots['approval_id'] = item.get('entity_id')
            return slots
        if (
            workset.get('entity_type') == 'approval'
            and items
            and re.search(r'(这条|这一条|这个|当前|刚才|上面|第一条|第一个|第1条|第1个|首条)', text or '')
        ):
            first = items[0] if isinstance(items[0], dict) else {}
            if first.get('entity_id'):
                slots.setdefault('target_index', 1)
                slots['approval_id'] = first.get('entity_id')
                return slots

    history_id = _approval_id_from_history(text, ctx, target_index or (1 if re.search(r'(这条|这一条|这个|当前|刚才|上面)', text or '') else None))
    if history_id:
        slots.setdefault('target_index', target_index or 1)
        slots['approval_id'] = history_id
    return slots


def _approval_id_from_history(text: str, ctx: AssistantContext, target_index: Optional[int]) -> Optional[str]:
    if not target_index:
        return None
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        candidates: List[str] = []
        for workset in entry.get('worksets') or []:
            if not isinstance(workset, dict) or workset.get('entity_type') != 'approval':
                continue
            for item in workset.get('items') or []:
                if isinstance(item, dict) and item.get('entity_id'):
                    candidates.append(str(item.get('entity_id')))
        for entity in entry.get('entities') or []:
            if isinstance(entity, dict) and (entity.get('type') == 'approval' or entity.get('typeLabel') == '审批') and entity.get('id'):
                candidates.append(str(entity.get('id')))
        for widget in entry.get('widgets') or []:
            candidates.extend(_approval_ids_from_widget(widget))
        unique_ids = list(dict.fromkeys(candidates))
        if len(unique_ids) >= target_index:
            return unique_ids[target_index - 1]
    return None


def _approval_ids_from_widget(widget: Any) -> List[str]:
    if not isinstance(widget, dict):
        return []
    ids: List[str] = []
    table = widget.get('table') if isinstance(widget.get('table'), dict) else {}
    rows = table.get('rows') if isinstance(table.get('rows'), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get('id'):
            ids.append(str(row.get('id')))
    for entity in widget.get('entities') or []:
        if isinstance(entity, dict) and (entity.get('type') == 'approval' or entity.get('typeLabel') == '审批') and entity.get('id'):
            ids.append(str(entity.get('id')))
    return ids


def _workset_reference_value(text: str, ctx: AssistantContext) -> Optional[str]:
    resolved = workset_store.resolve_mention(text, ctx.session_id)
    if not resolved:
        return None
    item = resolved.get('item') or {}
    if item:
        return item.get('title') or item.get('entity_id')
    ws = resolved.get('workset') or {}
    return ws.get('id')


def _candidate_reference_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    resolved = workset_store.resolve_mention(text, ctx.session_id)
    if resolved:
        item = resolved.get('item') or {}
        entity_type = item.get('entity_type')
        entity_id = item.get('entity_id')
        if entity_type == 'candidate' and entity_id:
            return {'candidate_id': entity_id}
        if entity_type == 'resume' and entity_id:
            return {'resume_id': entity_id}
        title = item.get('title')
        if title:
            return {'keyword': title}
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        focus = meta.get('lastFocus') if isinstance(meta.get('lastFocus'), dict) else {}
        if focus.get('entity_type') == 'candidate':
            if focus.get('entity_id'):
                return {'candidate_id': focus.get('entity_id')}
            if focus.get('name'):
                return {'keyword': focus.get('name')}
        if focus.get('entity_type') == 'resume':
            if focus.get('entity_id'):
                return {'resume_id': focus.get('entity_id')}
            if focus.get('name'):
                return {'keyword': focus.get('name')}
        for workset in entry.get('worksets') or []:
            if not isinstance(workset, dict):
                continue
            for item in workset.get('items') or []:
                if not isinstance(item, dict):
                    continue
                entity_type = item.get('entity_type')
                entity_id = item.get('entity_id')
                if entity_type == 'candidate' and entity_id:
                    return {'candidate_id': entity_id}
                if entity_type == 'resume' and entity_id:
                    return {'resume_id': entity_id}
        for entity in entry.get('entities') or []:
            if not isinstance(entity, dict):
                continue
            if entity.get('type') == 'candidate' and entity.get('id'):
                return {'candidate_id': entity.get('id')}
            if entity.get('type') == 'resume' and entity.get('id'):
                return {'resume_id': entity.get('id')}
    return {}


def build_route_decision(card: AgentSkillCard, plan: SkillPlan) -> RouteDecision:
    return kernel_decision.build_route_decision(card, plan)


def _filter_tool_params(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return kernel_decision.filter_tool_params(tool, params)


def _looks_like_workset_reference(value: str) -> bool:
    return kernel_decision.looks_like_workset_reference(value)


__all__ = ['SkillPlan', 'build_route_decision', 'fill_slots', 'plan_skill']
