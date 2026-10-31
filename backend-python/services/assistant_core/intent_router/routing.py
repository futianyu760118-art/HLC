"""Skill-first dispatcher for the retired IntentRouter routing name.

Public ``routing.route`` always projects the Agent Kernel Skill-first planner
into the historical ``RouterResult`` shape.  It does not choose between old
route stacks.
"""

from __future__ import annotations

import logging

from ..schemas import AssistantContext, RouterResult
from . import pipeline


logger = logging.getLogger('hengpintong.assistant.intent_router.routing')


def route(message: str, ctx: AssistantContext) -> RouterResult:
    try:
        return pipeline.route(message, ctx)
    except Exception:  # noqa: BLE001 - compatibility boundary must not raise
        logger.exception('skill_first_routing_projection_failed')
        return RouterResult(
            intent='skill_first.clarification',
            task_template_id=None,
            confidence=0.0,
            entities={},
            missing_fields=[],
            risk_level='low',
            candidate_skills=[],
            requires_confirmation=False,
            clarification_question='请补充你要查询或处理的 HRM 模块、对象或时间范围。',
            reason='skill_first_routing_projection_failed',
            rule_matched=False,
            route_path='skill_first_routing_shim',
        )


__all__ = ['route']
