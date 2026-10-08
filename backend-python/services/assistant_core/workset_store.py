"""Session-backed WorkSet store for follow-up entity context.

Fresh WorkSets remain cached in-process for the current request, but lookup can
also restore WorkSets persisted in ``AssistantSession.messages``. This keeps
pronoun resolution stable when consecutive HTTP requests reach different
Gunicorn workers.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional


def _utc_iso() -> str:
    return datetime.utcnow().isoformat()


def _request_user_id() -> Optional[str]:
    try:
        from flask import has_request_context
        from flask_jwt_extended import get_jwt_identity
        from services.assistant_core.evaluation_safety import current_evaluation_execution_user_id

        if not has_request_context():
            return None
        execution_user_id = current_evaluation_execution_user_id()
        if execution_user_id:
            return str(execution_user_id)
        identity = get_jwt_identity()
        return str(identity) if identity else None
    except Exception:
        return None


def _request_tenant_id() -> Optional[str]:
    try:
        from flask import has_request_context
        from services.tenancy import current_tenant_id

        if not has_request_context():
            return None
        tenant_id = current_tenant_id()
        return str(tenant_id) if tenant_id else None
    except Exception:
        return None


def _workset_visible_in_current_request(workset: Dict[str, Any]) -> bool:
    request_user_id = _request_user_id()
    request_tenant_id = _request_tenant_id()
    if request_user_id:
        owner_user_id = workset.get('owner_user_id')
        if not owner_user_id or str(owner_user_id) != request_user_id:
            return False
    if request_tenant_id:
        owner_tenant_id = workset.get('owner_tenant_id')
        if owner_tenant_id and str(owner_tenant_id) != request_tenant_id:
            return False
    return True


def _infer_entity_type(entities: List[Dict[str, Any]]) -> str:
    types = {str(e.get('type') or e.get('entity_type') or '').lower() for e in entities if e}
    types.discard('')
    if len(types) == 1:
        t = next(iter(types))
        if t in ('candidate', 'employee', 'resume', 'job', 'approval'):
            return t
    return 'mixed'


def _chinese_numeral_to_int(value: str) -> Optional[int]:
    text = (value or '').strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    numerals = {
        '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    }
    if text in numerals:
        return numerals[text]
    if text.startswith('十') and len(text) == 2:
        return 10 + numerals.get(text[1], 0)
    if text.endswith('十') and len(text) == 2:
        return numerals.get(text[0], 0) * 10
    match = re.match(r'([一二两三四五六七八九])十([一二两三四五六七八九])?', text)
    if match:
        return numerals.get(match.group(1), 0) * 10 + numerals.get(match.group(2) or '', 0)
    return None


def _single_item_for_pronoun(items: List[Dict[str, Any]], entity_type: str) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    concrete = [
        item for item in items
        if isinstance(item, dict) and item.get('entity_type') in {'candidate', 'resume', 'employee'}
    ]
    if len(concrete) == 1:
        return concrete[0]
    if len(items) == 1 and isinstance(items[0], dict):
        return items[0]
    if entity_type in {'candidate', 'resume', 'employee'} and isinstance(items[0], dict):
        return items[0]
    return None


class WorkSetStore:
    """Small WorkSet cache with an optional persistent session reader."""

    def __init__(
        self,
        persistent_reader: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    ) -> None:
        self._items_by_session: Dict[str, List[Dict[str, Any]]] = {}
        self._persistent_reader = persistent_reader

    def clear(self) -> None:
        self._items_by_session.clear()

    def create_workset_from_entities(
        self,
        session_id: Optional[str],
        user_id: str,
        label: str,
        entities: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not session_id or not entities:
            return None

        normalized = []
        for idx, ent in enumerate(entities, start=1):
            if not isinstance(ent, dict):
                continue
            entity_type = ent.get('type') or ent.get('entity_type')
            entity_id = ent.get('id') or ent.get('entity_id')
            if not entity_type or not entity_id:
                continue
            normalized.append({
                'entity_type': entity_type,
                'entity_id': entity_id,
                'title': ent.get('title') or ent.get('name') or str(entity_id),
                'subtitle': ent.get('subtitle') or ent.get('meta') or '',
                'rank': idx,
                'display_fields': {
                    k: v for k, v in ent.items()
                    if k not in {'type', 'id', 'entity_type', 'entity_id'}
                },
                'source_tool': ent.get('source_tool') or 'assistant_result',
                'sensitive_level': ent.get('sensitive_level') or 'normal',
            })

        if not normalized:
            return None

        now = datetime.utcnow()
        workset = {
            'id': 'ws_' + uuid.uuid4().hex[:12],
            'session_id': session_id,
            'owner_user_id': user_id,
            'owner_tenant_id': _request_tenant_id(),
            'entity_type': _infer_entity_type(entities),
            'label': label or '助手结果集',
            'items': normalized,
            'created_at': now.isoformat(),
            'expires_at': (now + timedelta(hours=12)).isoformat(),
        }
        bucket = self._items_by_session.setdefault(session_id, [])
        bucket.append(workset)
        bucket[:] = bucket[-10:]
        return workset

    def get_latest_workset(
        self,
        session_id: Optional[str],
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        bucket = self._combined_bucket(session_id)
        for ws in reversed(bucket):
            if entity_type and ws.get('entity_type') != entity_type:
                continue
            return ws
        return None

    def _combined_bucket(self, session_id: str) -> List[Dict[str, Any]]:
        """Return persisted and local WorkSets, de-duplicated in time order."""
        persistent: List[Dict[str, Any]] = []
        if self._persistent_reader:
            try:
                persistent = list(self._persistent_reader(session_id) or [])
            except Exception:
                persistent = []
        combined = persistent + list(self._items_by_session.get(session_id) or [])
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for ws in combined:
            ws_id = ws.get('id') if isinstance(ws, dict) else None
            if not ws_id or ws_id in seen:
                continue
            if not _workset_visible_in_current_request(ws):
                continue
            seen.add(ws_id)
            deduped.append(ws)
        return deduped

    def _get_latest_workset_by_types(
        self,
        session_id: Optional[str],
        entity_types: Optional[Iterable[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        bucket = self._combined_bucket(session_id)
        wanted_order = [t for t in (entity_types or []) if t]
        if wanted_order:
            for entity_type in wanted_order:
                for ws in reversed(bucket):
                    if ws.get('entity_type') == entity_type:
                        return ws
            return None
        for ws in reversed(bucket):
            return ws
        return None

    @staticmethod
    def _desired_types_from_message(message: str) -> List[str]:
        text = message or ''
        if re.search(r'(这个人|这位|该员工|他|她).{0,12}(调到|转到|调岗|转岗|异动|状态|画像|生命周期|考勤|绩效|薪资|调薪|审批)', text):
            return ['employee']
        if re.search(r'(调到|转到|调岗|转岗|异动).{0,16}(影响|审批|提交|确认|准备)', text):
            return ['employee']
        if re.search(r'(员工|同事|成员|下属)', text):
            return ['employee']
        if re.search(r'(审批|申请|请假|报销|流程|待办)', text):
            return ['approval']
        if re.search(r'(岗位|职位|JD|jd|招聘需求)', text):
            return ['job']
        if re.search(r'(简历|履历)', text):
            return ['resume', 'candidate']
        if re.search(r'(候选人|应聘者|面试者)', text):
            return ['candidate', 'resume']
        return []

    @staticmethod
    def _ordinal_rank_from_message(text: str, item_count: int) -> Optional[int]:
        if item_count <= 0:
            return None
        if re.search(r'最后\s*(?:一)?\s*(?:个|位|名|份|条|项)', text):
            return item_count
        reverse_match = re.search(
            r'倒数\s*第?\s*([一二两三四五六七八九十\d]+)\s*(?:个|位|名|份|条|项)?',
            text,
        )
        if reverse_match:
            offset = _chinese_numeral_to_int(reverse_match.group(1))
            if offset and offset <= item_count:
                return item_count - offset + 1
            return None
        ordinal_match = re.search(
            r'第\s*([一二两三四五六七八九十\d]+)\s*(?:个|位|名|份|条|项)',
            text,
        )
        if ordinal_match:
            return _chinese_numeral_to_int(ordinal_match.group(1))
        return None

    def resolve_mention(self, message: str, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        text = message or ''
        desired_types = self._desired_types_from_message(text)
        latest_any = self.get_latest_workset(session_id)
        latest_typed = self._get_latest_workset_by_types(session_id, desired_types)
        latest_any = latest_typed or latest_any
        if not latest_any:
            return None

        items = latest_any.get('items') or []
        ordinal_rank = self._ordinal_rank_from_message(text, len(items))
        if ordinal_rank:
            for item in items:
                if item.get('rank') == ordinal_rank:
                    return {'kind': 'item', 'item': item, 'workset': latest_any}
            return None

        if re.search(r'(这个人|这个候选人|刚才那个候选人)', text):
            if items:
                return {'kind': 'item', 'item': items[0], 'workset': latest_any}

        if re.search(r'(?:^|[，,。；;\s]|给|为|把|帮)(他|她|这位|这个|刚才这个|上面这个)(?:[，,。；;\s]|$|安排|约|分析|评价|评估|状态|画像|生命周期|调到|转到|调岗|提交|怎么样|如何)', text):
            if not re.search(r'(他们|她们|这些|这几|那批|那些|每个|每位|分别|逐个|对比|比对|排名|排行|谁|哪个|哪位|哪些)', text):
                single_item = _single_item_for_pronoun(items, str(latest_any.get('entity_type') or ''))
                if single_item:
                    return {'kind': 'item', 'item': single_item, 'workset': latest_any}

        if re.search(
            r'(这几个人|这些人|这些员工|这些候选人|上面这些候选人|刚才这些候选人|基于这几个人|'
            r'这些简历|上面这些简历|刚才这些简历|每个人|每位候选人|每个候选人|'
            r'每份简历|针对每个人|他们|她们|这批|这批人|上面这些|上面的人|上面的|'
            r'刚才这些|刚才那些|列表里|表格里|上述|以上|逐个|分别|每个|每位|每一位|'
            r'每一份|结合他们|结合这些|基于上面|基于刚才|前几个|前五个|其中|里面|'
            r'这些里面|结果里|名单里|候选人里|简历里|上面列表|上面结果|这批候选人|'
            r'排名|排行|排序|比对|对比|报表|'
            r'刚才那批|刚才的|刚才列出的|刚刚那批|上一批|上一轮|上轮|前一批|前一轮|'
            r'前面那批|前面这些|上面那几|上面那批|那批|那些|这一批|'
            r'投递记录里|履历里|岗位名单|职位里|招聘需求)',
            text,
        ):
            return {'kind': 'workset', 'workset': latest_any}

        if re.search(
            r'(最合适的人|最推荐的人|排名第一|第一名|谁|哪位|哪个|最高|最低|最大|最小|最多|最少|'
            r'年龄|年纪|评分|匹配|经验|学历)',
            text,
        ):
            return {'kind': 'workset', 'workset': latest_any}

        if re.search(
            r'(?:前\s*[一二两三四五六七八九十\d]+\s*(?:个|名|位)|'
            r'排名\s*前\s*[一二两三四五六七八九十\d]+|'
            r'前\s*[一二两三四五六七八九十\d]+\s*名|'
            r'top\s*\d+|上面\s*\d+\s*(?:个|名|位)?\s*(?:人|候选人|简历)|'
            r'这\s*\d+\s*(?:个|名|位)?\s*(?:人|候选人|简历))',
            text,
            re.I,
        ):
            return {'kind': 'workset', 'workset': latest_any}

        return None


def _read_session_worksets(session_id: str) -> List[Dict[str, Any]]:
    """Read WorkSets previously committed with assistant messages."""
    try:
        from models import AssistantSession

        query = AssistantSession.query.filter_by(id=session_id)
        request_user_id = _request_user_id()
        if request_user_id:
            query = query.filter_by(user_id=request_user_id)
        session = query.first()
        messages = session.messages if session else []
    except Exception:
        return []
    worksets: List[Dict[str, Any]] = []
    for entry in messages or []:
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        for ws in meta.get('worksets') or []:
            if isinstance(ws, dict) and _workset_visible_in_current_request(ws):
                worksets.append(ws)
    return worksets


default_store = WorkSetStore(persistent_reader=_read_session_worksets)


def create_workset_from_entities(
    session_id: Optional[str],
    user_id: str,
    label: str,
    entities: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    return default_store.create_workset_from_entities(session_id, user_id, label, entities)


def get_latest_workset(
    session_id: Optional[str],
    entity_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    return default_store.get_latest_workset(session_id, entity_type)


def resolve_mention(message: str, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    return default_store.resolve_mention(message, session_id)


__all__ = [
    'WorkSetStore',
    'default_store',
    'create_workset_from_entities',
    'get_latest_workset',
    'resolve_mention',
]
