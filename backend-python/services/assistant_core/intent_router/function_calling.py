"""Function Calling 兜底路由。

当 Retriever + Reranker + ConfidenceGate 都无法命中时，把可用 skill 列表
以 OpenAI Function Calling 协议交给 LLM，由 LLM 自主选择调哪些工具、
传什么参数。

设计原则：

* **只在 fallback 路径触发**——正常 embedding 检索命中时不走这里，零性能开销。
* **不暴露写操作**——``side_effect=True`` 的 skill（创建面试、写提醒等）
  不会出现在 tools 列表中，防止 LLM 误触发有副作用的操作。
* **永不抛错**——LLM 调用失败 / 解析失败 / 返回空工具时统一返回 ``None``，
  让 pipeline 继续走原来的 fallback 路径（global_search）。
* **权限后置**——本模块不做角色过滤；返回的 ``candidate_skills`` 会在
  pipeline 的 PermissionGate 和 executor 中分别做二次校验。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .. import llm_client, skill_registry
from ..constants import RISK_LOW
from ..schemas import AssistantContext, RouterResult

logger = logging.getLogger('hengpintong.assistant.intent_router.function_calling')

# 特殊 task_template_id 标记：告诉 executor 走 direct-skills 路径而非 workflow
DIRECT_SKILLS_TASK_ID = '_direct_skills_'

# system prompt 指导 LLM 如何选工具
_SYSTEM_PROMPT = (
    '你是恒聘通 HRM 系统的智能助手。根据用户的问题，从可用工具中选择最合适的'
    '一个或多个工具来获取数据。\n'
    '规则：\n'
    '1. 只选择与用户问题直接相关的工具，不要选无关工具。\n'
    '2. 如果用户提到具体人名，把人名填入 keyword 参数。\n'
    '3. 如果需要分析某个人的综合能力，优先选择证据包工具（evidence_bundle）'
    '获取完整数据，而不是只做简单搜索。\n'
    '4. 如果不确定该用哪个工具，选 global_search 做全局搜索。\n'
    '5. 不要编造不存在的工具。\n'
)


def _skills_to_tools() -> List[Dict[str, Any]]:
    """把 skill_registry 中只读的 SkillSpec 转为 OpenAI tools 格式。"""
    tools: List[Dict[str, Any]] = []
    for spec in skill_registry.all_skills():
        # 有副作用的 skill 不暴露给 LLM 自由选择
        if spec.side_effect:
            continue

        properties: Dict[str, Any] = {}
        required: List[str] = []
        for param_name, param_def in (spec.input_schema or {}).items():
            prop: Dict[str, Any] = {}
            ptype = param_def.get('type', 'string')
            prop['type'] = ptype
            prop['description'] = param_def.get('description', param_name)
            if 'enum' in param_def:
                prop['enum'] = param_def['enum']
            if 'default' in param_def:
                prop['description'] += f"（默认 {param_def['default']}）"
            properties[param_name] = prop
            if param_def.get('required'):
                required.append(param_name)

        tool_def: Dict[str, Any] = {
            'type': 'function',
            'function': {
                'name': spec.id,
                'description': f'{spec.name}：{spec.description}',
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                },
            },
        }
        if required:
            tool_def['function']['parameters']['required'] = required
        tools.append(tool_def)
    return tools


def _parse_tool_calls(
    message: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """从 LLM 响应中提取 tool_calls，返回 [{name, arguments}, ...]。"""
    tool_calls = message.get('tool_calls')
    if not tool_calls or not isinstance(tool_calls, list):
        return []

    parsed: List[Dict[str, Any]] = []
    for call in tool_calls:
        fn = call.get('function') or {}
        name = fn.get('name', '')
        if not name or not skill_registry.exists(name):
            continue
        raw_args = fn.get('arguments', '{}')
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            logger.warning('fc_invalid_arguments', extra={'skill': name, 'raw': raw_args[:200]})
            args = {}
        parsed.append({'name': name, 'arguments': args or {}})
    return parsed


def try_function_calling(
    message: str,
    ctx: AssistantContext,
) -> Optional[RouterResult]:
    """Retriever 兜底时调用：LLM 自主选择 skill + 参数。

    返回 ``RouterResult``（带 ``task_template_id='_direct_skills_'``）或
    ``None``（LLM 也没选出工具 / 调用失败）。
    """
    if not llm_client.is_available():
        return None

    tools = _skills_to_tools()
    if not tools:
        return None

    # 构造消息：system + 最近 2 轮历史 + 当前用户消息
    history = (ctx.history or [])[-4:]
    messages: List[Dict[str, Any]] = [
        {'role': 'system', 'content': _SYSTEM_PROMPT},
    ]
    messages.extend(history)
    messages.append({'role': 'user', 'content': message})

    try:
        response = llm_client.chat_with_tools(
            messages=messages,
            tools=tools,
            temperature=0.2,
            max_tokens=600,
            ctx=ctx,
            use_case='skill_planning',
        )
    except Exception:
        logger.exception('fc_llm_call_failed')
        return None

    if not response:
        return None

    parsed = _parse_tool_calls(response)
    if not parsed:
        # LLM 没有选择任何工具——可能返回了纯文本回复
        # 把 LLM 的文本内容作为 summary 透传，避免完全无响应
        content = (response.get('content') or '').strip()
        if content:
            logger.info('fc_no_tools_text_response', extra={'len': len(content)})
            return RouterResult(
                intent='function_calling_text',
                task_template_id='general_dialogue',
                confidence=0.7,
                route_path='function_calling',
                reason='fc:llm_returned_text_no_tools',
            )
        return None

    # 合并所有 skill 的参数（后面的覆盖前面的同名 key）
    all_skills = [p['name'] for p in parsed]
    merged_entities: Dict[str, Any] = {}
    for p in parsed:
        merged_entities.update(p['arguments'])

    logger.info(
        'fc_matched',
        extra={'skills': all_skills, 'args_keys': list(merged_entities.keys())},
    )

    return RouterResult(
        intent='function_calling',
        task_template_id=DIRECT_SKILLS_TASK_ID,
        confidence=0.85,
        entities=merged_entities,
        candidate_skills=all_skills,
        risk_level=RISK_LOW,
        route_path='function_calling',
        reason=f'fc:matched {",".join(all_skills)}',
    )


__all__ = ['try_function_calling', 'DIRECT_SKILLS_TASK_ID']
