"""降级链。"""

from __future__ import annotations

from typing import Any, Dict

from . import skill_registry
from .schemas import AssistantContext


def deterministic_summary(state: Dict[str, Any], router_result) -> str:
    """LLM 不可用时基于已有结果生成简短中文总结。"""
    parts = []
    used = set()

    for key, val in state.items():
        if not isinstance(val, dict):
            continue
        hint = val.get('summary_hint')
        if hint and hint not in used:
            parts.append(hint)
            used.add(hint)

    if not parts:
        if router_result and router_result.task_template_id == 'forbidden_action_response':
            return router_result.forbidden_reason or '该操作不会自动执行，请在对应业务页面确认。'
        return '已为您生成相关数据，请查看下方卡片和图表。'

    text = '；'.join(parts)
    if len(text) > 240:
        text = text[:240] + '...'
    if not text.endswith('。'):
        text += '。'
    return text


def keyword_denoise(message: str) -> str:
    """去停用词后再做 global_search。"""
    text = message
    stops = ['分析', '汇总', '报表', '计划', '安排', '统计', '概览', '推荐', '建议',
             '做一个', '帮我', '请', '查一下', '查询', '看一下', '相关', '系统中',
             '一下', '里', '？', '?', '。', '!', '！']
    for s in stops:
        text = text.replace(s, '')
    return text.strip()


def empty_result_fallback(ctx: AssistantContext, message: str, router_result) -> Dict[str, Any]:
    """工具结果完全为空时调一次 global_search 兜底。"""
    skill = skill_registry.get('global_search')
    if not skill:
        return {}
    keyword = router_result.entities.get('keyword') if router_result else None
    if not keyword:
        keyword = keyword_denoise(message)
    if len(keyword) < 2:
        return {}
    try:
        return skill.handler({'keyword': keyword, 'limit': 8}, ctx) or {}
    except Exception:
        return {}
