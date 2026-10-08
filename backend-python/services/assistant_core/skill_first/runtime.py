"""Skill-first Agent Runtime.

The runtime owns the new primary chain:

user text -> normalized query -> Skill Card Top-K recall -> restricted planner
-> slot fill / WorkSet resolution -> permission/risk check -> ToolExecutor or
pending confirmation -> response assembly -> route trace / failure sample sink.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import memory, workset_store
from ..agent_kernel import AgentKernel, AgentKernelServices
from ..agent_kernel import action_runtime
from ..agent_kernel import answer_synthesis as kernel_answer_synthesis
from ..agent_kernel import context as kernel_context
from ..agent_kernel import direct_invoke as kernel_direct_invoke
from ..agent_kernel import decision as kernel_decision
from ..agent_kernel import execution as kernel_execution
from ..agent_kernel import input_guards as kernel_input_guards
from ..agent_kernel import observability as kernel_observability
from ..agent_kernel import policy as kernel_policy
from ..agent_kernel import result_augmentation as kernel_result_augmentation
from ..agent_kernel import slot_reference as kernel_slot_reference
from ..agent_kernel.skill_provider import record_for_card, records_from_recall
from ..agent_kernel.skill_playbook import build_playbook
from ..agent_kernel.slot_normalizer import normalize_slot_values
from ..executors import ToolExecutor
from ..schemas import AssistantContext, ExecutionResult, RouteDecision
from .cards import AgentSkillCard, get_card
from .planner import plan_skill
from .semantic_index import RecallResult, normalize_query
from .skill_retriever import retrieve_skills
from .understanding import understand_query

# Runtime-level aliases are kept for tests and extension points that monkeypatch
# action behavior, but the implementation now lives under agent_kernel.
_action_message_parts = action_runtime.action_message_parts
_clarification_result = action_runtime.clarification_result
_compose_tool_outputs = action_runtime.compose_tool_outputs
_execute_pending_action = action_runtime.execute_pending_action
_normalize_tool_plan_inputs = action_runtime.normalize_tool_plan_inputs
_prepare_action_confirmation = action_runtime.prepare_action_confirmation


def try_run(message: str, ctx: AssistantContext) -> Optional[ExecutionResult]:
    text = (message or '').strip()
    if not text:
        return None
    return _build_agent_kernel().run(text, ctx)


def invoke_registered_skill(
    skill_id: str,
    params: Dict[str, Any],
    ctx: AssistantContext,
    *,
    display_name: Optional[str] = None,
) -> ExecutionResult:
    """Execute a known Agent Skill Card through the Kernel provider/workbench path.

    This is used by product skill-card clicks. The visible launcher card is a UI
    asset only; execution still goes through formal Agent Skill Cards,
    provider metadata, ToolWorkbench, permission checks, response contract and
    route observability.
    """

    text_id = str(skill_id or '').strip()
    services = _build_agent_kernel().services
    card = get_card(text_id)
    if not card:
        return kernel_direct_invoke.unknown_skill_result(
            text_id,
            ctx,
            display_name=display_name,
            services=services,
        )

    return kernel_direct_invoke.invoke_registered_skill(
        card,
        params,
        ctx,
        display_name=display_name,
        services=services,
    )


def _build_agent_kernel() -> AgentKernel:
    services = AgentKernelServices(
        normalize_query=normalize_query,
        action_message_parts=_action_message_parts,
        execute_pending_action=_execute_pending_action,
        build_base_trace=_base_trace,
        learning_events=_learning_events,
        attach_trace=_attach_trace,
        understand_query=understand_query,
        retrieve_skills=retrieve_skills,
        provide_skill_records=_provide_skill_records,
        provide_skill_record_for_card=_provide_skill_record_for_card,
        plan_skill=plan_skill,
        get_card=get_card,
        trace_from_plan=_trace_from_plan,
        resolve_slots_and_references=_resolve_slots_and_references,
        normalize_slot_values=normalize_slot_values,
        refine_skill_after_reference=_refine_skill_after_reference,
        skill_first_clarification_result=_skill_first_clarification_result,
        unsupported_write_intent=_unsupported_write_intent,
        write_guard_result=_write_guard_result,
        build_route_decision=kernel_decision.build_route_decision,
        normalize_tool_plan_inputs=_normalize_tool_plan_inputs,
        apply_skill_specific_input_guards=_apply_skill_specific_input_guards,
        build_skill_playbook=_build_skill_playbook,
        permission_result=_permission_result,
        permission_denied_result=_permission_denied_result,
        execute_skill=_execute_skill_node,
        synthesize_answer=_synthesize_answer_node,
        verify_output=_verify_output,
    )
    return AgentKernel(services, top_k=16, min_confidence=0.45)


def _kernel_execute_skill_node(
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    decision: RouteDecision,
    trace: Dict[str, Any],
) -> ExecutionResult:
    return kernel_execution.execute_skill_node(
        message,
        ctx,
        card,
        decision,
        trace,
        prepare_action_confirmation=_prepare_action_confirmation,
        compose_tool_outputs=_compose_tool_outputs,
        execute_workset_analysis_fn=_execute_workset_analysis,
    )


def _provide_skill_records(candidates: List[RecallResult], *, limit: Optional[int] = None) -> List[Any]:
    return records_from_recall(candidates, limit=limit, model_schema_mode='planner')


def _provide_skill_record_for_card(card: AgentSkillCard) -> Any:
    return record_for_card(card, model_schema_mode='planner')


def _build_skill_playbook(
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    decision: RouteDecision,
    provider_selected: Dict[str, Any],
) -> Any:
    return build_playbook(
        message=message,
        ctx=ctx,
        card=card,
        decision=decision,
        provider_selected=provider_selected,
    )


def build_unhandled_result(
    message: str,
    ctx: AssistantContext,
    *,
    reason: str = 'skill_first_unhandled',
    error_code: Optional[str] = None,
) -> ExecutionResult:
    return kernel_policy.unhandled_result(
        message,
        ctx,
        reason=reason,
        error_code=error_code,
        normalize_query=normalize_query,
        build_base_trace=_base_trace,
        clarification_result_fn=_skill_first_clarification_result,
    )


def _kernel_policy_clarification_result(
    message: str,
    ctx: AssistantContext,
    question: str,
    trace: Dict[str, Any],
    *,
    kind: str,
    error_code: Optional[str] = None,
    attach_trace: bool = True,
) -> ExecutionResult:
    return kernel_policy.skill_first_clarification_result(
        message,
        ctx,
        question,
        trace,
        kind=kind,
        error_code=error_code,
        attach_trace=attach_trace,
        attach_trace_fn=_attach_trace,
    )


def _kernel_attach_trace(result: ExecutionResult, trace: Dict[str, Any]) -> None:
    kernel_observability.attach_trace(
        result,
        trace,
        first_learning_event_kind=_first_learning_event_kind,
    )


def _kernel_execute_workset_analysis(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    return kernel_execution.execute_workset_analysis(
        message,
        ctx,
        decision,
        compose_tool_outputs=_compose_tool_outputs,
    )


# Keep runtime-level test seams, but make Kernel policy the implementation
# owner for these policy nodes.
_attach_kernel_tool_outputs = kernel_execution.attach_kernel_tool_outputs
_attach_trace = _kernel_attach_trace
_base_trace = kernel_observability.base_trace
_execute_skill_node = _kernel_execute_skill_node
_execute_workset_analysis = _kernel_execute_workset_analysis
_first_learning_event_kind = kernel_context.first_learning_event_kind
_last_focus_from_result = kernel_context.last_focus_from_result
_learning_events = kernel_context.learning_events
_permission_denied_result = kernel_policy.permission_denied_result
_permission_result = kernel_policy.permission_result
_apply_skill_specific_input_guards = kernel_input_guards.apply_skill_specific_input_guards
_looks_like_generic_recent_resume_question = kernel_input_guards.looks_like_generic_recent_resume_question
_record_trace_and_failure = kernel_observability.record_trace_and_failure
_synthesize_answer_node = kernel_answer_synthesis.synthesize_answer_node
_skill_first_clarification_result = _kernel_policy_clarification_result
_append_entity_once = kernel_result_augmentation.append_entity_once
_augment_candidate_job_fit_result = kernel_result_augmentation.augment_candidate_job_fit_result
_augment_page_capability_result = kernel_result_augmentation.augment_page_capability_result
_augment_workflow_help_result = kernel_result_augmentation.augment_workflow_help_result
_capability_label = kernel_result_augmentation.capability_label
_extract_job_label_from_text = kernel_result_augmentation.extract_job_label_from_text
_apply_resolved_item_slots = kernel_slot_reference.apply_resolved_item_slots
_approval_business_terms = kernel_slot_reference.approval_business_terms
_approval_matches_terms = kernel_slot_reference.approval_matches_terms
_approval_target_index = kernel_slot_reference.approval_target_index
_ground_approval_confirmation_slots = kernel_slot_reference.ground_approval_confirmation_slots
_ground_employee_change_slots_from_history = kernel_slot_reference.ground_employee_change_slots_from_history
_has_reference_signal = kernel_slot_reference.has_reference_signal
_looks_like_candidate_evaluation_followup = kernel_slot_reference.looks_like_candidate_evaluation_followup
_looks_like_workset_reference_text = kernel_slot_reference.looks_like_workset_reference_text
_normalize_approval_action = kernel_slot_reference.normalize_approval_action
_recompute_missing_slots = kernel_slot_reference.recompute_missing_slots
_refine_skill_after_reference = kernel_slot_reference.refine_skill_after_reference
_resolve_slots_and_references = kernel_slot_reference.resolve_slots_and_references
_should_run_slot_refiner = kernel_slot_reference.should_run_slot_refiner
_trace_from_plan = kernel_observability.trace_from_plan
_unsupported_write_intent = kernel_policy.unsupported_write_intent
_verify_output = kernel_policy.verify_output
_write_guard_result = kernel_policy.write_guard_result


def persist_turn(message: str, ctx: AssistantContext, result: ExecutionResult) -> None:
    kernel_context.persist_turn(message, ctx, result, route_path='skill_first_runtime')


__all__ = ['build_unhandled_result', 'persist_turn', 'try_run']
