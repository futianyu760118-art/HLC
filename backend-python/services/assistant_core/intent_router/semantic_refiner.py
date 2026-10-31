"""Optional strong-model reasoning pass for complex user requests."""

from __future__ import annotations

import re

from .. import llm_client
from ..model_settings import feature_enabled
from ..schemas import AssistantContext, RouteDecision


def _is_complex(message: str, decision: RouteDecision) -> bool:
    if decision.route_track == 'COMPOSITE':
        return True
    return bool(
        len(message or '') >= 14
        and re.search(r'(分析|对比|规划|计划|建议|分别|逐个|基于|然后|并且|安排|创建)', message or '')
        and decision.route_track in ('B_GENERATION', 'C_DIALOGUE_KNOWLEDGE')
    )


def enrich_complex_decision(message: str, ctx: AssistantContext, decision: RouteDecision) -> RouteDecision:
    """Add an LLM planning brief without allowing it to bypass tool/safety routes."""
    if not _is_complex(message, decision):
        return decision
    if not feature_enabled('intentReasoning') or not llm_client.is_available():
        return decision
    payload = llm_client.json_chat_profile(
        'strong',
        [
            {
                'role': 'system',
                'content': (
                    '你是 HRM 智能体的任务规划器。根据用户需求给执行器补充简短计划。'
                    '数据必须通过工具加载，写动作必须等待聊天内确认。'
                    '只输出 JSON：{"planning_brief":"...", "required_evidence":["..."], "output_focus":["..."]}。'
                ),
            },
            {
                'role': 'user',
                'content': f'请求：{message}\n初步轨道：{decision.route_track}\n初步意图：{decision.intent}',
            },
        ],
        temperature=0.1,
        max_tokens=450,
        timeout=20,
        use_case='intent_reasoning',
        ctx=ctx,
    )
    if not payload or not decision.generation_plan:
        return decision
    brief = str(payload.get('planning_brief') or '').strip()
    if brief:
        constraints = dict(decision.generation_plan.constraints or {})
        constraints['planning_brief'] = brief[:500]
        constraints['required_evidence'] = payload.get('required_evidence') or []
        constraints['output_focus'] = payload.get('output_focus') or []
        decision.generation_plan.constraints = constraints
        decision.reason = f'{decision.reason};strong_model_planning'
    return decision
