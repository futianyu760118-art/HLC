"""HRM 助手核心模块。

提供：Agent Kernel → Skill-first Runtime → ToolExecutor → Guardrails →
Widgets → Memory 的完整编排链路。

对外暴露入口：
- run_query(message, context) → ExecutionResult
- memory.build_context(user_id, session_id) → AssistantContext
"""

from .schemas import (
    AssistantContext, RouterResult, TaskTemplate, WorkflowStep,
    SkillSpec, ExecutionResult, ExecutionStep, RouteDecision,
    GenerationPlan, ToolCallPlan, router_result_to_route_decision,
    route_decision_to_router_result,
)
from .memory import build_context


def run_query(message: str, context: AssistantContext) -> ExecutionResult:
    """Compatibility entry for old imports.

    Ordinary natural-language traffic must use the Skill-first Agent Kernel.
    The legacy orchestrator remains importable as explicit migration/test code,
    but this public helper must not route product traffic back through it.
    """

    from .skill_first import runtime as skill_first_runtime

    result = skill_first_runtime.try_run(message, context)
    if result is None:
        return skill_first_runtime.build_unhandled_result(message, context)
    return result


__all__ = [
    'AssistantContext', 'RouterResult', 'TaskTemplate', 'WorkflowStep',
    'SkillSpec', 'ExecutionResult', 'ExecutionStep', 'RouteDecision',
    'GenerationPlan', 'ToolCallPlan', 'router_result_to_route_decision',
    'route_decision_to_router_result',
    'run_query', 'build_context',
]
