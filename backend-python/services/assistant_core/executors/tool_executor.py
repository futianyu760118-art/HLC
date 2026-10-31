"""Small tool executor for hybrid orchestration."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .. import skill_registry
from ..guardrails import check_skill_permission
from ..schemas import AssistantContext

logger = logging.getLogger('hengpintong.assistant.tool_executor')


class ToolExecutor:
    def execute(self, tool: str, params: Dict[str, Any], ctx: AssistantContext) -> Dict[str, Any]:
        spec = skill_registry.get(tool)
        if not spec:
            return {
                'ok': False,
                'tool': tool,
                'data': {},
                'error': 'tool_not_found',
                'rows_count': 0,
            }
        deny = check_skill_permission(ctx.role, spec, ctx)
        if deny:
            message = deny if '权限' in deny else f'权限不足：{deny}'
            return {
                'ok': False,
                'tool': tool,
                'data': {},
                'error': message,
                'rows_count': 0,
            }
        try:
            data = spec.handler(params or {}, ctx) if spec.handler else {}
            data = data or {}
            return {
                'ok': True,
                'tool': tool,
                'data': data,
                'error': '',
                'rows_count': int(data.get('rows_count') or 0),
            }
        except Exception as exc:  # noqa: BLE001 - normalize tool errors
            logger.exception('hybrid_tool_failed', extra={'tool': tool})
            return {
                'ok': False,
                'tool': tool,
                'data': {},
                'error': type(exc).__name__,
                'rows_count': 0,
            }
