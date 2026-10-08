"""Schema-aware slot/entity normalization for the HRM Agent Kernel.

Planner and slot refiner outputs are advisory language-understanding results.
Before a tool handler sees those values, the Kernel runs this deterministic
normalizer to trim common Chinese conversational wrappers from entity slots
without changing the selected Skill, tool, permissions or side-effect policy.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


PERSON_ENTITY_SLOT_KEYS = {
    'keyword',
    'target_candidate',
    'target_employee',
    'employee_keyword',
    'employeeKeyword',
    'candidate_keyword',
    'candidateKeyword',
}

PERSONISH_SKILL_IDS = {
    'candidate.search',
    'candidate.resume_analysis',
    'candidate.evaluation',
    'candidate.job_fit',
    'interview.schedule_confirm_create',
    'employee.search',
    'employee.profile',
    'employee.lifecycle_chain',
    'employee.change_impact',
    'employee.change_submit_confirm',
    'employee.salary_adjustment_submit_confirm',
    'attendance.employee_evidence',
    'performance.employee_link',
}

PERSONISH_DOMAINS = {'candidate', 'employee', 'attendance', 'performance'}

JOB_SLOT_KEYS = {'job_keyword', 'jobKeyword'}

STOP_VALUES = {
    '员工',
    '同事',
    '候选人',
    '应聘者',
    '这个人',
    '这位',
    '这个员工',
    '这位员工',
    '该员工',
    '个人能力',
    '员工画像',
    '低绩效',
    '绩效低',
    '评分低',
}


def normalize_slot_values(
    *,
    message: str,
    card: Any,
    slot_values: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Normalize selected Skill slots and return an observable trace."""

    values = dict(slot_values or {})
    trace: Dict[str, Any] = {
        'source': 'agent_kernel.slot_normalizer',
        'status': 'completed',
        'applied': False,
        'changes': [],
    }
    if not card or not values:
        return values, trace

    for key, raw in list(values.items()):
        key_text = str(key)
        if not isinstance(raw, str):
            continue
        if _is_person_entity_slot(card, key_text):
            normalized = _normalize_person_entity(raw, message)
        elif key_text in JOB_SLOT_KEYS:
            normalized = _normalize_job_entity(raw)
        else:
            continue
        if normalized != raw:
            if normalized:
                values[key] = normalized
            else:
                values.pop(key, None)
            trace['changes'].append({
                'field': key_text,
                'before': raw,
                'after': normalized,
                'reason': 'trimmed_colloquial_entity_wrapper',
            })

    trace['applied'] = bool(trace['changes'])
    return _drop_empty(values), trace


def _is_person_entity_slot(card: Any, key: str) -> bool:
    if key not in PERSON_ENTITY_SLOT_KEYS:
        return False
    card_id = str(getattr(card, 'id', '') or '')
    domain = str(getattr(card, 'domain', '') or '')
    if card_id in PERSONISH_SKILL_IDS:
        return True
    if domain in PERSONISH_DOMAINS and key != 'job_keyword':
        return True
    return False


def _normalize_person_entity(value: str, message: str) -> str:
    original = _compact_text(value)
    if not original:
        return ''
    explicit = _extract_explicit_person_from_message(message, original)
    cleaned = explicit or original
    cleaned = _trim_person_wrappers(cleaned)
    if not _valid_personish_value(cleaned):
        return ''
    return cleaned


def _normalize_job_entity(value: str) -> str:
    cleaned = _compact_text(value)
    for _ in range(3):
        previous = cleaned
        cleaned = re.sub(r'^(?:符合|满足|适合|匹配|适配|胜任|是否|能不能|看看|评估)(?:的)?', '', cleaned)
        cleaned = re.sub(r'^(?:我们|咱们|公司|本公司|团队|部门)(?:的)?', '', cleaned)
        cleaned = re.sub(r'(?:岗位|职位)?(?:要求|条件|画像|情况)$', '', cleaned)
        if cleaned == previous:
            break
    return cleaned.strip(' ，,。?？；;:：')


def _extract_explicit_person_from_message(message: str, current: str) -> str:
    text = message or ''
    patterns = [
        r'(?:员工|同事|人员|成员|候选人|应聘者)(?:里|中|列表里|名单里)?(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,12}?)(?:的|最近|本月|这个月|整体|综合|画像|状态|情况|怎么样|如何|$)',
        r'(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,12}?)(?:的)?(?:员工|同事|人员|成员|候选人|应聘者|最近|整体|综合|画像|状态|情况|怎么样|如何|$)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,12}?)(?:这个|这位)?(?:员工|同事|候选人|应聘者)(?:最近|本月|这个月|整体|综合|画像|状态|情况|怎么样|如何|$)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,12}?)(?:这个人|这位)(?:最近|本月|这个月|整体|综合|画像|状态|情况|怎么样|如何|$)',
        r'(?:员工|同事|候选人|应聘者)[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,12}?)(?:的|最近|本月|这个月|整体|综合|画像|状态|情况|怎么样|如何|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = _trim_person_wrappers(match.group(1))
        if candidate and (
            current.startswith(candidate)
            or candidate.startswith(current)
            or candidate in text
        ):
            if _valid_personish_value(candidate):
                return candidate
    return ''


def _trim_person_wrappers(value: str) -> str:
    cleaned = _compact_text(value)
    for _ in range(4):
        previous = cleaned
        cleaned = re.sub(r'^(?:帮我|帮|请|麻烦|给|为|查一下|查找|搜索|找一下|看看)', '', cleaned)
        cleaned = re.sub(r'^(?:员工|同事|候选人|应聘者|这个人|这位|这个员工|这位员工|该员工)', '', cleaned)
        cleaned = re.sub(r'(?:这个员工|这位员工|该员工|员工|同事|候选人|应聘者|这个人|这位|这个|的)$', '', cleaned)
        cleaned = re.sub(r'(?:最近状态|最近情况|整体情况|综合情况|员工画像|画像|状态如何|怎么样|如何|靠不靠谱)$', '', cleaned)
        cleaned = cleaned.strip(' ，,。?？；;:：')
        if cleaned == previous:
            break
    return cleaned


def _valid_personish_value(value: str) -> bool:
    if not value or value in STOP_VALUES:
        return False
    if len(value) < 2:
        return False
    if value.startswith(('这', '他', '她', '该', '上面', '刚才', '第二')):
        return False
    if re.search(r'(岗位|职位|工程师|经理|专员|主管|总监)$', value):
        return False
    return True


def _compact_text(value: Any) -> str:
    return re.sub(r'\s+', '', str(value or '').strip(' ，,。?？；;:：'))


def _drop_empty(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value not in (None, '', [])
    }


__all__ = ['normalize_slot_values']
