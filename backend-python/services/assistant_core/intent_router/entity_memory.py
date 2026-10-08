"""会话级实体记忆（Task 11）。

在 ``AssistantSession`` 已有的 JSON 字段上叠加 ``entity_memory`` 子键来持久化
会话级 NamedEntity，**不**新增 SQL schema 与 migration。本模块只暴露纯逻辑：

- :class:`NamedEntity`：会话内单个命名实体的快照（带 TTL）。
- :class:`EntityStore`：抽象存储协议；生产环境会接到 ``AssistantSession.messages``
  的独立子键，测试中用 :class:`InMemoryEntityStore` 替代，避免触碰 DB。
- :class:`EntityMemory`：抽取 / 设置 / 查询 / 淘汰 / 代词消解。

设计取舍
========
- 类型集合通过 :data:`KNOWN_TYPES` 暴露，避免拼写错。
- 同类型新值出现时**覆盖**而不是合并（Req 4.6）。
- TTL 默认 30 分钟、``time_window`` 类默认 10 分钟，可通过环境变量覆盖；
  非法值（负数 / 非整数）回落到默认，便于运维误配时不炸服务。
- ``resolve`` 在不含 Pronoun 与省略模式时输出 == 输入（Req 4.8、10.3 恒等性）。
- 时间统一通过 ``time.time()``，所有公共 API 都允许测试传 ``now=`` 控制。
- 复用 ``router.py`` 已有的 ``_extract_keyword`` / ``_extract_default_entities``
  心智：抽取阶段不重复造姓名识别，``employee`` / ``candidate`` 这类需要中文姓名
  的实体由上层路由器先抽好放进 ``router_entities`` 里再传进来。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from config import IntentRouterConfig


# ---- 类型常量 ---------------------------------------------------------------

EMPLOYEE = 'employee'
CANDIDATE = 'candidate'
DEPARTMENT = 'department'
MONTH = 'month'
JOB_ID = 'job_id'
TIME_WINDOW = 'time_window'
DRAFT_TYPE = 'draft_type'
KEYWORD = 'keyword'

KNOWN_TYPES = frozenset({
    EMPLOYEE, CANDIDATE, DEPARTMENT, MONTH,
    JOB_ID, TIME_WINDOW, DRAFT_TYPE, KEYWORD,
})


# ---- 默认 TTL ---------------------------------------------------------------

# 环境变量名 + 默认值集中登记在 ``config.IntentRouterConfig``；本模块只引用。
DEFAULT_TTL_MINUTES = IntentRouterConfig.DEFAULT_ENTITY_MEMORY_TTL_MINUTES
TIME_WINDOW_TTL_MINUTES = (
    IntentRouterConfig.DEFAULT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW
)

_ENV_TTL_DEFAULT = IntentRouterConfig.ENV_ENTITY_MEMORY_TTL_MINUTES_DEFAULT
_ENV_TTL_TIME_WINDOW = (
    IntentRouterConfig.ENV_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW
)


def _read_positive_int_env(name: str, default: int) -> int:
    """读取正整数环境变量；缺失/非法/非正数 → ``default``。"""
    raw = os.environ.get(name, '')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def ttl_minutes_for(entity_type: str) -> int:
    """返回 ``entity_type`` 适用的 TTL（分钟）。"""
    if entity_type == TIME_WINDOW:
        return _read_positive_int_env(_ENV_TTL_TIME_WINDOW, TIME_WINDOW_TTL_MINUTES)
    return _read_positive_int_env(_ENV_TTL_DEFAULT, DEFAULT_TTL_MINUTES)


# ---- 代词与省略模式 ---------------------------------------------------------

_PRONOUNS: frozenset = frozenset({
    '他', '她', '它', 'TA',
    '这个人', '那个人',
    '该员工', '该候选人',
    '这位候选人', '这名候选人',
    '这位员工', '这名员工',
    '上面那个', '上面这个',
    '这条', '那条',
})

# 单个代词命中时，按下面的顺序在 EntityMemory 里挑兼容类型的最近实体。
# 多个类型都有候选时，全部进入 trace 的 ``candidates`` 列表里。
_PRONOUN_TYPE_MAP: Dict[str, Tuple[str, ...]] = {
    '他': (EMPLOYEE, CANDIDATE),
    '她': (EMPLOYEE, CANDIDATE),
    '它': (EMPLOYEE, CANDIDATE),
    'TA': (EMPLOYEE, CANDIDATE),
    '这个人': (EMPLOYEE, CANDIDATE),
    '那个人': (EMPLOYEE, CANDIDATE),
    '上面那个': (EMPLOYEE, CANDIDATE),
    '上面这个': (EMPLOYEE, CANDIDATE),
    '该员工': (EMPLOYEE,),
    '这位员工': (EMPLOYEE,),
    '这名员工': (EMPLOYEE,),
    '该候选人': (CANDIDATE,),
    '这位候选人': (CANDIDATE,),
    '这名候选人': (CANDIDATE,),
    '这条': (KEYWORD,),
    '那条': (KEYWORD,),
}

# 省略模式列表：当前为空（仅留作扩展点）。tests 只覆盖代词替换路径。
_ELLIPSIS_PATTERNS: Tuple[str, ...] = ()


# ---- 抽取阶段使用的小工具正则 ----------------------------------------------

#: 薪酬月份格式：``2024-03`` / ``2024年3月`` / ``2024/03``。
_MONTH_RE = re.compile(r'(\d{4})[-年/](\d{1,2})')

#: 「最近 N 天」/「最近N天」 → ``last_Nd``。
_RECENT_DAYS_RE = re.compile(r'最近\s*(\d+)\s*天')


def _detect_time_window(message: str) -> Optional[str]:
    """从消息中提取 ``time_window`` 标准化值。

    覆盖：
    - ``本月`` → ``last_30d``
    - ``本周`` → ``last_7d``
    - ``最近 N 天`` → ``last_Nd``
    """
    if not message:
        return None
    m = _RECENT_DAYS_RE.search(message)
    if m:
        return f'last_{int(m.group(1))}d'
    if '本月' in message:
        return 'last_30d'
    if '本周' in message:
        return 'last_7d'
    return None


# ---- NamedEntity ------------------------------------------------------------

@dataclass
class NamedEntity:
    """会话内的命名实体快照。

    Attributes:
        type: 类型，必须 ∈ :data:`KNOWN_TYPES`；不在集合里的值依然能构造，
            方便上层做透传，但 :class:`EntityMemory` 在消解时会忽略未知类型。
        value: 人类可读的值（如 ``小王`` / ``2024-03`` / ``last_7d``）。
        canonical_id: 可选的稳定 ID（如 ``employee_id``）。
        source_turn_index: 抽取该实体的会话轮次序号，用于多候选裁决。
        expires_at: epoch 秒；超过该时间点视为过期。
    """

    type: str
    value: str
    canonical_id: Optional[str] = None
    source_turn_index: int = 0
    expires_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'value': self.value,
            'canonical_id': self.canonical_id,
            'source_turn_index': self.source_turn_index,
            'expires_at': float(self.expires_at),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'NamedEntity':
        if not data:
            return cls(type='', value='')
        try:
            expires_at = float(data.get('expires_at', 0.0) or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0
        try:
            source_turn_index = int(data.get('source_turn_index', 0) or 0)
        except (TypeError, ValueError):
            source_turn_index = 0
        return cls(
            type=str(data.get('type') or ''),
            value=str(data.get('value') or ''),
            canonical_id=(
                str(data['canonical_id'])
                if data.get('canonical_id') is not None
                else None
            ),
            source_turn_index=source_turn_index,
            expires_at=expires_at,
        )


# ---- EntityStore 协议 + 内存实现 -------------------------------------------

class EntityStore(Protocol):
    """会话级实体存储协议。

    生产环境会接到 ``AssistantSession.messages`` JSON 内的 ``entity_memory``
    子键；本模块不直接 import ``models.AssistantSession``，让单元测试能完全
    脱离 DB 跑（任务 11.1 的硬性要求）。
    """

    def load(self, session_id: str) -> List[NamedEntity]: ...

    def save(self, session_id: str, entities: List[NamedEntity]) -> None: ...


class InMemoryEntityStore:
    """基于内存 dict 的 :class:`EntityStore` 实现。

    仅用于单元测试 / 演练 / 文档化协议契约；不要在生产代码路径里使用。
    每次 ``load`` / ``save`` 都做浅拷贝，避免外部修改污染内部状态。
    """

    def __init__(self) -> None:
        self._data: Dict[str, List[NamedEntity]] = {}

    def load(self, session_id: str) -> List[NamedEntity]:
        return list(self._data.get(session_id, ()))

    def save(self, session_id: str, entities: List[NamedEntity]) -> None:
        self._data[session_id] = list(entities)


# ---- EntityMemory -----------------------------------------------------------

# resolve 的 trace 字段名集中放在一起，方便外层断言时复用。
TRACE_KEY_PRONOUNS_FOUND = 'pronouns_found'
TRACE_KEY_SUBSTITUTIONS = 'substitutions'


@dataclass
class _Substitution:
    pronoun: str
    replaced_with: Optional[str]
    type: Optional[str]
    candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'pronoun': self.pronoun,
            'replaced_with': self.replaced_with,
            'type': self.type,
            'candidates': list(self.candidates),
        }


class EntityMemory:
    """会话级实体记忆。

    线程安全性：单条 ``EntityStore`` 的 load/save 由实现方负责；本类不引入额外
    锁。外层调用建议保证同一 ``session_id`` 的写操作串行（与
    ``memory.save_turn`` 同一线程上下文一致即可）。
    """

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    # ---- 抽取 ----------------------------------------------------------

    @staticmethod
    def extract(
        message: str,
        router_entities: Optional[Dict[str, Any]] = None,
        source_turn_index: int = 0,
        now: Optional[float] = None,
    ) -> List[NamedEntity]:
        """从消息与 router 实体里抽取一组 :class:`NamedEntity`。

        - ``employee`` / ``candidate`` / ``department`` / ``job_id`` /
          ``draft_type`` / ``keyword`` 直接从 ``router_entities`` 里读，
          不在这里重复造姓名识别。
        - ``month`` 与 ``time_window`` 从消息文本里抽（``router`` 历史上没有
          统一这两个字段名，只能在这一层兜底）。
        - 调用方传入的 ``source_turn_index`` 决定多轮顺序；同 ``now`` 决定 TTL。
        """
        now_ts = float(now) if now is not None else time.time()
        re_in: Dict[str, Any] = router_entities or {}
        out: List[NamedEntity] = []

        def _make(entity_type: str, value: Any, canonical: Any = None) -> NamedEntity:
            ttl = ttl_minutes_for(entity_type)
            return NamedEntity(
                type=entity_type,
                value=str(value),
                canonical_id=str(canonical) if canonical is not None else None,
                source_turn_index=source_turn_index,
                expires_at=now_ts + ttl * 60.0,
            )

        # 直接从 router_entities 透传的字段
        _direct_field_to_type: Tuple[Tuple[str, str], ...] = (
            ('employee', EMPLOYEE),
            ('candidate', CANDIDATE),
            ('department', DEPARTMENT),
            ('job_id', JOB_ID),
            ('draft_type', DRAFT_TYPE),
            ('keyword', KEYWORD),
        )
        for key, type_const in _direct_field_to_type:
            value = re_in.get(key)
            if value:
                canonical = re_in.get(f'{key}_id')
                out.append(_make(type_const, value, canonical))

        # 从消息文本里兜底抽取
        if message:
            month_match = _MONTH_RE.search(message)
            if month_match:
                month_value = f'{month_match.group(1)}-{int(month_match.group(2)):02d}'
                out.append(_make(MONTH, month_value))

            tw = _detect_time_window(message)
            if tw:
                out.append(_make(TIME_WINDOW, tw))

        return out

    # ---- 增删查 --------------------------------------------------------

    def set(self, session_id: str, entity: NamedEntity) -> None:
        """覆盖语义：同类型旧值丢弃，新值追加到末尾。"""
        items = self._store.load(session_id)
        # 同类型旧实体直接淘汰。同名（同 type+value）的旧记录也一并被清掉，
        # 避免 list 里出现「两个 small-王」这种逻辑上不合理的副本。
        kept = [e for e in items if e.type != entity.type]
        kept.append(entity)
        self._store.save(session_id, kept)

    def get(
        self,
        session_id: str,
        entity_type: str,
        now: Optional[float] = None,
    ) -> Optional[NamedEntity]:
        """返回该类型最新且未过期的实体；不存在返回 ``None``。"""
        now_ts = float(now) if now is not None else time.time()
        items = self._store.load(session_id)
        live = [
            e for e in items
            if e.type == entity_type and e.expires_at > now_ts
        ]
        if not live:
            return None
        return max(live, key=lambda e: e.source_turn_index)

    def prune(
        self,
        session_id: str,
        now: Optional[float] = None,
    ) -> List[NamedEntity]:
        """淘汰所有已过期实体并持久化；返回剩余实体列表。"""
        now_ts = float(now) if now is not None else time.time()
        items = self._store.load(session_id)
        kept = [e for e in items if e.expires_at > now_ts]
        if len(kept) != len(items):
            self._store.save(session_id, kept)
        return kept

    # ---- 代词 / 省略消解 ----------------------------------------------

    def resolve(
        self,
        query: str,
        session_id: str,
        ctx: Optional[Any] = None,
        now: Optional[float] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """把 ``query`` 中的代词替换为最近的同类型实体值。

        Returns:
            ``(resolved_query, trace)``；当 ``query`` 不含 Pronoun 也未匹配
            任何省略模式时，返回 ``(query, {'pronouns_found': [], 'substitutions': []})``，
            满足 Requirement 4.8 / 10.3 的恒等性。
        """
        empty_trace: Dict[str, Any] = {
            TRACE_KEY_PRONOUNS_FOUND: [],
            TRACE_KEY_SUBSTITUTIONS: [],
        }
        if not query:
            return query, empty_trace

        now_ts = float(now) if now is not None else time.time()
        live_entities = [
            e for e in self._store.load(session_id) if e.expires_at > now_ts
        ]
        # 按类型聚合便于 O(1) 查询
        by_type: Dict[str, List[NamedEntity]] = {}
        for ent in live_entities:
            by_type.setdefault(ent.type, []).append(ent)

        # 长代词优先匹配（如「这位候选人」要在「这」/「人」之类碎片之前命中）。
        sorted_pronouns = sorted(_PRONOUNS, key=lambda p: -len(p))

        pronouns_found: List[str] = []
        substitutions: List[Dict[str, Any]] = []
        resolved = query

        for pronoun in sorted_pronouns:
            if pronoun not in resolved:
                continue
            pronouns_found.append(pronoun)

            compatible_types = _PRONOUN_TYPE_MAP.get(pronoun, ())
            candidates: List[NamedEntity] = []
            for t in compatible_types:
                candidates.extend(by_type.get(t, ()))

            if not candidates:
                substitutions.append(_Substitution(
                    pronoun=pronoun,
                    replaced_with=None,
                    type=None,
                    candidates=[],
                ).to_dict())
                continue

            chosen = max(candidates, key=lambda e: e.source_turn_index)
            # 注意：在 resolved 上做 replace 而不是 query 上，这样多个代词
            # 之间不会互相覆盖；同时避免重复替换（已替换的代词从字符串里消失）。
            resolved = resolved.replace(pronoun, chosen.value)
            substitutions.append(_Substitution(
                pronoun=pronoun,
                replaced_with=chosen.value,
                type=chosen.type,
                candidates=[c.value for c in candidates],
            ).to_dict())

        # 省略模式占位（_ELLIPSIS_PATTERNS 当前为空）。
        for pattern in _ELLIPSIS_PATTERNS:  # pragma: no cover - 仅作扩展点
            if re.search(pattern, resolved):
                pass

        if not pronouns_found:
            return query, empty_trace

        return resolved, {
            TRACE_KEY_PRONOUNS_FOUND: pronouns_found,
            TRACE_KEY_SUBSTITUTIONS: substitutions,
        }


__all__ = [
    'EMPLOYEE', 'CANDIDATE', 'DEPARTMENT', 'MONTH',
    'JOB_ID', 'TIME_WINDOW', 'DRAFT_TYPE', 'KEYWORD',
    'KNOWN_TYPES',
    'DEFAULT_TTL_MINUTES', 'TIME_WINDOW_TTL_MINUTES',
    'ttl_minutes_for',
    'NamedEntity',
    'EntityStore', 'InMemoryEntityStore',
    'EntityMemory',
    'TRACE_KEY_PRONOUNS_FOUND', 'TRACE_KEY_SUBSTITUTIONS',
]
