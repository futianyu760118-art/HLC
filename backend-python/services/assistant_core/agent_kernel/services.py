"""Service boundary injected into the HRM Agent Kernel.

The kernel owns the run-loop shape. Existing HRM modules still own business
handlers, route-decision construction, permissions, WorkSet resolution,
confirmation preparation and response assembly while they are being migrated
into smaller kernel nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..schemas import AssistantContext, ExecutionResult, RouteDecision


@dataclass(frozen=True)
class AgentKernelServices:
    normalize_query: Callable[[str], str]
    action_message_parts: Callable[[str], Tuple[Optional[str], Optional[str]]]
    execute_pending_action: Callable[[str, AssistantContext, RouteDecision], ExecutionResult]
    build_base_trace: Callable[..., Dict[str, Any]]
    learning_events: Callable[..., List[Dict[str, Any]]]
    attach_trace: Callable[[ExecutionResult, Dict[str, Any]], None]
    understand_query: Callable[[str, AssistantContext], Any]
    retrieve_skills: Callable[..., List[Any]]
    provide_skill_records: Callable[..., List[Any]]
    provide_skill_record_for_card: Callable[[Any], Any]
    plan_skill: Callable[..., Any]
    get_card: Callable[[str], Any]
    trace_from_plan: Callable[..., Dict[str, Any]]
    resolve_slots_and_references: Callable[[str, AssistantContext, Any, Any, Any], Any]
    normalize_slot_values: Callable[..., Any]
    refine_skill_after_reference: Callable[[str, AssistantContext, Any, Any, Any], Any]
    skill_first_clarification_result: Callable[..., ExecutionResult]
    unsupported_write_intent: Callable[[str, Any], Optional[str]]
    write_guard_result: Callable[[str, AssistantContext, Any, Any], ExecutionResult]
    build_route_decision: Callable[[Any, Any], RouteDecision]
    normalize_tool_plan_inputs: Callable[[str, RouteDecision], RouteDecision]
    apply_skill_specific_input_guards: Callable[[Any, RouteDecision, str], None]
    build_skill_playbook: Callable[[str, AssistantContext, Any, RouteDecision, Dict[str, Any]], Any]
    permission_result: Callable[[Any, AssistantContext], str]
    permission_denied_result: Callable[[str, AssistantContext, RouteDecision, str], ExecutionResult]
    execute_skill: Callable[[str, AssistantContext, Any, RouteDecision, Dict[str, Any]], ExecutionResult]
    synthesize_answer: Callable[[str, AssistantContext, Any, ExecutionResult, List[Dict[str, Any]], RouteDecision, Dict[str, Any], Any], Dict[str, Any]]
    verify_output: Callable[[ExecutionResult, Any], str]


def candidate_ids(candidates: Sequence[Any]) -> List[str]:
    return [str(getattr(item, 'skill_id', '')) for item in candidates if getattr(item, 'skill_id', '')]
