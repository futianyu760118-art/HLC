"""Answer synthesis node for the HRM Agent Kernel."""

from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import AssistantContext, ExecutionResult, RouteDecision
from ..skill_first.answer_synthesizer import apply_synthesized_answer, synthesize_answer
from ..skill_first.cards import AgentSkillCard


def synthesize_answer_node(
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    result: ExecutionResult,
    outputs: List[Dict[str, Any]],
    decision: RouteDecision,
    trace: Dict[str, Any],
    playbook: Any = None,
) -> Dict[str, Any]:
    playbook_payload = playbook.to_dict() if hasattr(playbook, 'to_dict') else (playbook if isinstance(playbook, dict) else None)
    content = synthesize_answer(
        message=message,
        ctx=ctx,
        card=card,
        result=result,
        outputs=outputs,
        decision=decision,
        playbook=playbook_payload,
    )
    if content:
        apply_synthesized_answer(result, content)
        return {
            'source': 'llm',
            'use_case': 'skill_first_grounded_answer',
            'applied': True,
            'playbook_used': bool(playbook_payload),
        }
    return {
        'source': 'deterministic',
        'applied': False,
        'playbook_used': bool(playbook_payload),
    }


__all__ = ['synthesize_answer_node']
