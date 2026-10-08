"""Follow-up task slot composition for the HRM Agent Kernel."""

from __future__ import annotations

import re
from typing import Any, Dict

from .. import workset_store
from ..schemas import AssistantContext
from . import planner_slot_extraction


def followup_task_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    raw = (text or '').strip()
    cleaned = re.sub(
        r'^(帮我|请|麻烦)?\s*(给|为)?\s*(这批|这些|上面|刚才|'
        r'第?\s*[一二两三四五六七八九十\d]+\s*(?:个|位|名)?)?\s*'
        r'(候选人|员工|同事|人)?\s*(创建|新建|新增|添加|安排|设个|加个|帮我建|帮我创建)?\s*'
        r'(一个|一条|个|条)?\s*(个人)?\s*(跟进任务|跟进提醒|待办|任务|提醒)\s*[:：，,。]?',
        '',
        raw,
    ).strip()
    if not cleaned:
        cleaned = raw or 'AI 助手跟进任务'
    title = cleaned[:60] if cleaned else 'AI 助手跟进任务'
    if len(title) < 4 or re.search(r'^(明天|后天|下周|本周|今天)$', title):
        title = 'AI 助手跟进任务'
    slots: Dict[str, Any] = {
        'title': title,
        'content': raw or title,
    }
    schedule_hint = planner_slot_extraction.extract_schedule_hint(raw)
    if schedule_hint:
        slots['due_at'] = schedule_hint
    resolved = workset_store.resolve_mention(raw, ctx.session_id)
    if resolved:
        item = resolved.get('item') if isinstance(resolved.get('item'), dict) else {}
        workset = resolved.get('workset') if isinstance(resolved.get('workset'), dict) else {}
        target_reference = item.get('title') or item.get('entity_id') or workset.get('id')
        if target_reference:
            slots['target_reference'] = target_reference
    return slots


__all__ = ['followup_task_slots']
