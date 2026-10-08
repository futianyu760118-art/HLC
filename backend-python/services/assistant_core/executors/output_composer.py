"""Convert hybrid executor outputs to ExecutionResult."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AssistantContext, ExecutionResult, RouteDecision


class OutputComposer:
    @staticmethod
    def dialogue(
        text: str,
        ctx: AssistantContext,
        decision: Optional[RouteDecision] = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            summary=text or '',
            entities=[],
            widgets=[],
            session_id=ctx.session_id,
            route_decision=decision,
            answer={'content': text or '', 'format': 'markdown'},
        )

    @staticmethod
    def generation(
        markdown: str,
        ctx: AssistantContext,
        decision: Optional[RouteDecision] = None,
        *,
        widgets: Optional[List[Dict[str, Any]]] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        worksets: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            summary=markdown or '',
            entities=entities or [],
            widgets=widgets or [],
            session_id=ctx.session_id,
            route_decision=decision,
            answer={'content': markdown or '', 'format': 'markdown'},
            worksets=worksets or [],
        )
