"""Compatibility shim for the retired agentic runtime name.

The production assistant mainline is now:

Agent Kernel -> Skill-first Runtime -> ToolExecutor/Action Runtime.

The historical implementation was moved to ``legacy_agentic_runtime`` so it can
remain a migration/test asset without occupying the public runtime name.  Code
that still imports ``assistant_core.agentic_runtime`` is intentionally routed
through the Skill-first Agent Kernel, not the legacy regex/direct-route stack.
"""

from __future__ import annotations

from typing import Optional

from .schemas import AssistantContext, ExecutionResult
from .skill_first import runtime as _skill_first_runtime


def try_run(message: str, ctx: AssistantContext) -> Optional[ExecutionResult]:
    """Run ordinary assistant traffic through the Skill-first Agent Kernel."""

    return _skill_first_runtime.try_run(message, ctx)


def persist_turn(message: str, ctx: AssistantContext, result: ExecutionResult) -> None:
    """Persist a turn using the Skill-first runtime's memory/workset policy."""

    _skill_first_runtime.persist_turn(message, ctx, result)


def build_unhandled_result(
    message: str,
    ctx: AssistantContext,
    *,
    reason: str = 'skill_first_unhandled',
    error_code: Optional[str] = None,
) -> ExecutionResult:
    return _skill_first_runtime.build_unhandled_result(
        message,
        ctx,
        reason=reason,
        error_code=error_code,
    )


def __getattr__(name: str):
    """Expose selected runtime-level test seams from the Skill-first runtime.

    This keeps existing monkeypatch-style tests honest: patching
    ``agentic_runtime.ToolExecutor`` or ``agentic_runtime.memory`` now affects
    the active Agent Kernel path instead of silently exercising old code.
    """

    if name in {'ToolExecutor', 'memory'}:
        return getattr(_skill_first_runtime, name)
    raise AttributeError(f"module 'services.assistant_core.agentic_runtime' has no attribute {name!r}")


__all__ = ['try_run', 'persist_turn', 'build_unhandled_result']
