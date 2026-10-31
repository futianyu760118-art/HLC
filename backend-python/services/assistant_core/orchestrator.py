"""Agent Kernel compatibility orchestrator.

The old route-file orchestrator has moved to ``legacy_orchestrator.py`` and is
kept only for explicit migration/tests. Importing this module no longer loads
``intent_router`` or the old direct executor path, and ``run()`` always enters
the Skill-first Agent Kernel.
"""

from __future__ import annotations

from typing import Any

from .schemas import AssistantContext, ExecutionResult


def run(message: str, ctx: AssistantContext) -> ExecutionResult:
    """Compatibility entry that executes ordinary traffic through Agent Kernel."""

    from .skill_first import runtime as skill_first_runtime

    result = skill_first_runtime.try_run(message, ctx)
    if result is None:
        return skill_first_runtime.build_unhandled_result(message, ctx)
    return result


def run_legacy(message: str, ctx: AssistantContext) -> ExecutionResult:
    """Explicit legacy entry for migration tests only."""

    from . import legacy_orchestrator

    return legacy_orchestrator.run(message, ctx)


def __getattr__(name: str) -> Any:
    """Lazy access to legacy helpers without loading legacy routes on import."""

    if name.startswith('_'):
        from . import legacy_orchestrator

        return getattr(legacy_orchestrator, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = ['run', 'run_legacy']
