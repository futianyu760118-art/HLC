"""Registered tool boundary for the HRM Agent Kernel.

This is inspired by Dify's provider/runtime-parameter split and AutoGen's
typed tool execution discipline. It keeps the real HRM `ToolExecutor` as the
business invocation boundary, but adds schema filtering, lightweight casting
and typed error classification before a model-planned call reaches handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .. import skill_registry
from ..executors import ToolExecutor
from ..guardrails import check_skill_permission
from ..schemas import AssistantContext

FORBIDDEN_HIDDEN_PARAMS = {
    'sql',
    'candidate_sql',
    'candidateSql',
    'raw_sql',
    'rawSql',
    'query_plan',
    'queryPlan',
}


@dataclass
class ToolWorkbenchError:
    kind: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_output(self, tool: str) -> Dict[str, Any]:
        return {
            'ok': False,
            'tool': tool,
            'data': {},
            'error': self.kind,
            'error_message': self.message,
            'error_details': dict(self.details),
            'rows_count': 0,
        }


@dataclass
class ToolInvocation:
    tool: str
    params: Dict[str, Any]
    schema: Dict[str, Any]
    hidden_params: Dict[str, Any] = field(default_factory=dict)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)


class ToolWorkbench:
    """Validate and invoke registered HRM tools."""

    def __init__(self, executor: Optional[ToolExecutor] = None) -> None:
        self.executor = executor or ToolExecutor()

    def call(
        self,
        tool: str,
        params: Mapping[str, Any] | None,
        ctx: AssistantContext,
        *,
        provider_metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        prepared = self.prepare(tool, params or {}, ctx, provider_metadata=provider_metadata)
        if isinstance(prepared, ToolWorkbenchError):
            return prepared.to_output(tool)
        output = self.executor.execute(prepared.tool, prepared.params, ctx)
        if isinstance(output, dict):
            output.setdefault('tool', prepared.tool)
            output.setdefault('workbench', {})
            if isinstance(output['workbench'], dict):
                output['workbench'].update({
                    'schema_checked': True,
                    'visible_params': list(prepared.params.keys()),
                    'hidden_params': list(prepared.hidden_params.keys()),
                    'provider_contract_checked': bool(prepared.provider_metadata),
                    'provider_skill': prepared.provider_metadata.get('skill_id'),
                    'provider_tool': prepared.provider_metadata.get('executor_tool'),
                })
        return output

    def prepare(
        self,
        tool: str,
        params: Mapping[str, Any],
        ctx: AssistantContext,
        *,
        provider_metadata: Optional[Mapping[str, Any]] = None,
    ) -> ToolInvocation | ToolWorkbenchError:
        provider = dict(provider_metadata or {})
        provider_tool = str(provider.get('executor_tool') or '').strip()
        if provider_tool and provider_tool != tool:
            return ToolWorkbenchError(
                'provider_tool_mismatch',
                f'Provider Skill 合同要求调用 {provider_tool}，但执行计划请求 {tool}',
                {
                    'tool': tool,
                    'provider_tool': provider_tool,
                    'provider_skill': provider.get('skill_id'),
                },
            )

        spec = skill_registry.get(tool)
        if not spec:
            return ToolWorkbenchError('tool_not_found', f'未注册工具：{tool}', {'tool': tool})

        deny = check_skill_permission(ctx.role, spec, ctx)
        if deny:
            message = deny if '权限' in deny else f'权限不足：{deny}'
            return ToolWorkbenchError('permission_denied', message, {'tool': tool, 'role': ctx.role})

        schema = dict(getattr(spec, 'input_schema', {}) or {})
        if not schema:
            return ToolInvocation(tool=tool, params=dict(params or {}), schema={}, provider_metadata=provider)

        clean_params: Dict[str, Any] = {}
        hidden_params: Dict[str, Any] = {}
        errors: List[Dict[str, Any]] = []
        for key, value in dict(params or {}).items():
            rule = schema.get(key)
            if rule is None:
                hidden_params[key] = value
                if key in FORBIDDEN_HIDDEN_PARAMS:
                    errors.append({'field': key, 'error': 'forbidden_hidden_param'})
                else:
                    clean_params[key] = value
                continue
            casted, error = _cast_value(value, rule)
            if error:
                errors.append({'field': key, 'error': error, 'value': value})
                continue
            clean_params[key] = casted

        for key, rule in schema.items():
            if rule.get('required') and _is_missing(clean_params.get(key)):
                errors.append({'field': key, 'error': 'required'})
            elif key not in clean_params and 'default' in rule:
                clean_params[key] = rule.get('default')

        if errors:
            return ToolWorkbenchError(
                'invalid_tool_arguments',
                f'{tool} 参数不符合注册 schema',
                {'tool': tool, 'errors': errors},
            )
        return ToolInvocation(tool=tool, params=clean_params, schema=schema, hidden_params=hidden_params, provider_metadata=provider)


def _is_missing(value: Any) -> bool:
    return value is None or value == '' or value == []


def _cast_value(value: Any, rule: Mapping[str, Any]) -> tuple[Any, Optional[str]]:
    if value is None:
        return value, None
    expected = str(rule.get('type') or '').lower()
    enum_values = rule.get('enum')
    try:
        if expected == 'integer':
            if isinstance(value, bool):
                return value, 'expected_integer'
            value = int(value)
        elif expected == 'number':
            if isinstance(value, bool):
                return value, 'expected_number'
            value = float(value)
        elif expected == 'boolean':
            if isinstance(value, bool):
                pass
            elif isinstance(value, str) and value.strip().lower() in {'true', '1', 'yes', 'y', 'on'}:
                value = True
            elif isinstance(value, str) and value.strip().lower() in {'false', '0', 'no', 'n', 'off'}:
                value = False
            else:
                return value, 'expected_boolean'
        elif expected == 'string':
            value = str(value)
        elif expected == 'object':
            if not isinstance(value, dict):
                return value, 'expected_object'
        elif expected == 'array':
            if not isinstance(value, list):
                return value, 'expected_array'
    except (TypeError, ValueError):
        return value, f'expected_{expected or "valid_value"}'

    if enum_values and value not in enum_values:
        return value, 'not_in_enum'
    return value, None


__all__ = [
    'ToolInvocation',
    'ToolWorkbench',
    'ToolWorkbenchError',
]
