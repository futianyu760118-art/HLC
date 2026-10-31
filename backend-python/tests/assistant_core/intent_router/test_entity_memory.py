"""Task 11.1 —— EntityMemory 单元测试。

目标：
- 用 in-memory dict 桩替代 DB（不触碰 ``models.AssistantSession``）。
- 抽取：薪酬月份格式 ``2024-03``、``time_window``（``本月`` / ``最近 7 天``）、
  ``keyword`` / ``employee`` / ``candidate`` 透传 router_entities。
- TTL 淘汰：set 后推进时间过 TTL，``get`` 返回 None；``prune`` 清空过期项。
- 覆盖语义：同类型新值覆盖最近实体（最大 ``source_turn_index`` 胜出）。
- 多候选 trace：``resolve`` 命中代词时把候选列表写入 trace 并选 ``source_turn_index`` 最大者。
- 恒等性：query 无 Pronoun 且 memory 为空 → ``resolve(q) == q``。

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import os
import sys
import time

import pytest

# 把 backend-python 加到 sys.path，便于直接以 ``services.*`` 引用真实模块。
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core.intent_router.entity_memory import (  # noqa: E402
    CANDIDATE,
    DEFAULT_TTL_MINUTES,
    DEPARTMENT,
    DRAFT_TYPE,
    EMPLOYEE,
    JOB_ID,
    KEYWORD,
    KNOWN_TYPES,
    MONTH,
    TIME_WINDOW,
    TIME_WINDOW_TTL_MINUTES,
    TRACE_KEY_PRONOUNS_FOUND,
    TRACE_KEY_SUBSTITUTIONS,
    EntityMemory,
    InMemoryEntityStore,
    NamedEntity,
    ttl_minutes_for,
)


# 固定一个 ``now`` 让 TTL 计算可预期，不依赖 wall clock。
NOW = 1_700_000_000.0
SESSION = 'sess-test'


@pytest.fixture
def store() -> InMemoryEntityStore:
    return InMemoryEntityStore()


@pytest.fixture
def memory(store: InMemoryEntityStore) -> EntityMemory:
    return EntityMemory(store)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """避免外部环境变量污染 TTL 默认值。"""
    monkeypatch.delenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_DEFAULT', raising=False)
    monkeypatch.delenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW', raising=False)
    yield


# =============================================================================
# 常量 & dataclass 行为
# =============================================================================


class TestConstants:
    def test_known_types_is_frozenset_with_eight_members(self) -> None:
        assert isinstance(KNOWN_TYPES, frozenset)
        assert KNOWN_TYPES == {
            EMPLOYEE, CANDIDATE, DEPARTMENT, MONTH,
            JOB_ID, TIME_WINDOW, DRAFT_TYPE, KEYWORD,
        }

    def test_default_ttl_values(self) -> None:
        assert DEFAULT_TTL_MINUTES == 30
        assert TIME_WINDOW_TTL_MINUTES == 10

    def test_ttl_minutes_for_uses_specialized_default_for_time_window(self) -> None:
        assert ttl_minutes_for(TIME_WINDOW) == 10
        assert ttl_minutes_for(EMPLOYEE) == 30
        # 未知类型也回到默认 30 分钟，与 employee 一致
        assert ttl_minutes_for('unknown_type_x') == 30

    def test_ttl_env_override_for_default(self, monkeypatch) -> None:
        monkeypatch.setenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_DEFAULT', '60')
        assert ttl_minutes_for(EMPLOYEE) == 60
        # time_window 仍然走自己的 env，不被默认值覆盖
        assert ttl_minutes_for(TIME_WINDOW) == 10

    def test_ttl_env_override_for_time_window(self, monkeypatch) -> None:
        monkeypatch.setenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW', '15')
        assert ttl_minutes_for(TIME_WINDOW) == 15

    def test_invalid_ttl_env_falls_back_to_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_DEFAULT', 'not-a-number')
        monkeypatch.setenv('ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW', '-3')
        assert ttl_minutes_for(EMPLOYEE) == DEFAULT_TTL_MINUTES
        assert ttl_minutes_for(TIME_WINDOW) == TIME_WINDOW_TTL_MINUTES


class TestNamedEntityRoundTrip:
    def test_to_dict_and_from_dict_round_trip(self) -> None:
        e = NamedEntity(
            type=EMPLOYEE,
            value='小王',
            canonical_id='emp-001',
            source_turn_index=3,
            expires_at=NOW + 600,
        )
        d = e.to_dict()
        assert d == {
            'type': EMPLOYEE,
            'value': '小王',
            'canonical_id': 'emp-001',
            'source_turn_index': 3,
            'expires_at': NOW + 600,
        }
        assert NamedEntity.from_dict(d) == e

    def test_from_dict_handles_missing_and_invalid(self) -> None:
        e = NamedEntity.from_dict({
            'type': MONTH,
            'value': '2024-03',
            # 缺 canonical_id / source_turn_index / expires_at
        })
        assert e.type == MONTH
        assert e.value == '2024-03'
        assert e.canonical_id is None
        assert e.source_turn_index == 0
        assert e.expires_at == 0.0

        # 非法值不应抛错
        e2 = NamedEntity.from_dict({
            'type': KEYWORD,
            'value': 'x',
            'source_turn_index': 'bad',
            'expires_at': 'also-bad',
        })
        assert e2.source_turn_index == 0
        assert e2.expires_at == 0.0

    def test_from_dict_empty(self) -> None:
        assert NamedEntity.from_dict(None) == NamedEntity(type='', value='')
        assert NamedEntity.from_dict({}) == NamedEntity(type='', value='')


# =============================================================================
# extract
# =============================================================================


class TestExtract:
    def test_extracts_employee_and_candidate_from_router_entities(self) -> None:
        out = EntityMemory.extract(
            message='看看小王的考勤',
            router_entities={'employee': '小王', 'employee_id': 'emp-001'},
            source_turn_index=2,
            now=NOW,
        )
        types = {e.type: e for e in out}
        assert EMPLOYEE in types
        assert types[EMPLOYEE].value == '小王'
        assert types[EMPLOYEE].canonical_id == 'emp-001'
        assert types[EMPLOYEE].source_turn_index == 2
        assert types[EMPLOYEE].expires_at == pytest.approx(NOW + 30 * 60)

    def test_extracts_keyword_from_router_entities(self) -> None:
        out = EntityMemory.extract(
            message='帮我查一下小李',
            router_entities={'keyword': '小李'},
            now=NOW,
        )
        types = {e.type: e for e in out}
        assert KEYWORD in types
        assert types[KEYWORD].value == '小李'

    def test_extracts_payroll_month_yyyy_mm(self) -> None:
        out = EntityMemory.extract(
            message='2024-03 的工资条',
            router_entities=None,
            now=NOW,
        )
        types = {e.type: e for e in out}
        assert MONTH in types
        assert types[MONTH].value == '2024-03'

    def test_extracts_month_chinese_yyyy_mm_normalized(self) -> None:
        out = EntityMemory.extract(message='查一下 2024年3月 的工资', now=NOW)
        types = {e.type: e for e in out}
        # 月份补零成两位，与 router._extract_default_entities 行为一致
        assert types[MONTH].value == '2024-03'

    @pytest.mark.parametrize('message,expected', [
        ('本月的考勤', 'last_30d'),
        ('看下本周的招聘进展', 'last_7d'),
        ('最近 7 天来了几份简历', 'last_7d'),
        ('最近30天的离职率', 'last_30d'),
    ])
    def test_extracts_time_window_from_phrases(self, message, expected) -> None:
        out = EntityMemory.extract(message=message, now=NOW)
        types = {e.type: e for e in out}
        assert types[TIME_WINDOW].value == expected
        # time_window 走 10 分钟 TTL（Req 4.5）
        assert types[TIME_WINDOW].expires_at == pytest.approx(NOW + 10 * 60)

    def test_extracts_multiple_entities_from_same_message(self) -> None:
        out = EntityMemory.extract(
            message='2024-03 本月小王的工资',
            router_entities={'employee': '小王'},
            source_turn_index=5,
            now=NOW,
        )
        types = {e.type for e in out}
        assert EMPLOYEE in types
        assert MONTH in types
        assert TIME_WINDOW in types

    def test_extract_passes_through_department_and_job_id_and_draft_type(self) -> None:
        out = EntityMemory.extract(
            message='',
            router_entities={
                'department': '研发',
                'job_id': 'job-1',
                'draft_type': 'interview_invite',
                'candidate': '王某某',
            },
            now=NOW,
        )
        types = {e.type: e for e in out}
        assert types[DEPARTMENT].value == '研发'
        assert types[JOB_ID].value == 'job-1'
        assert types[DRAFT_TYPE].value == 'interview_invite'
        assert types[CANDIDATE].value == '王某某'

    def test_extract_with_empty_message_and_no_router_entities(self) -> None:
        assert EntityMemory.extract(message='', router_entities=None, now=NOW) == []

    def test_extract_uses_source_turn_index_default_zero(self) -> None:
        out = EntityMemory.extract(
            message='本月',
            now=NOW,
        )
        assert out[0].source_turn_index == 0

    def test_extract_does_not_invent_employee_from_chinese_name(self) -> None:
        """抽取不重复造姓名识别（Req 4.1 注意事项）。

        当 router_entities 不提供 employee 时，单纯有「小王」这种字符串不应被
        当成 EMPLOYEE 抽出。
        """
        out = EntityMemory.extract(
            message='看看小王',
            router_entities=None,
            now=NOW,
        )
        types = {e.type for e in out}
        assert EMPLOYEE not in types
        assert CANDIDATE not in types


# =============================================================================
# set / get / prune（含 TTL 与覆盖）
# =============================================================================


class TestSetGetPrune:
    def test_set_then_get_returns_same_entity(
        self, memory: EntityMemory,
    ) -> None:
        e = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        )
        memory.set(SESSION, e)
        got = memory.get(SESSION, EMPLOYEE, now=NOW)
        assert got == e

    def test_get_returns_none_when_no_entity_of_type(
        self, memory: EntityMemory,
    ) -> None:
        assert memory.get(SESSION, EMPLOYEE, now=NOW) is None
        # 设了别的类型也不影响
        memory.set(SESSION, NamedEntity(
            type=DEPARTMENT, value='研发',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        assert memory.get(SESSION, EMPLOYEE, now=NOW) is None

    def test_ttl_eviction_via_get(self, memory: EntityMemory) -> None:
        e = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 100,
        )
        memory.set(SESSION, e)

        assert memory.get(SESSION, EMPLOYEE, now=NOW + 50) == e
        # 超过 TTL → 视为不存在
        assert memory.get(SESSION, EMPLOYEE, now=NOW + 200) is None

    def test_prune_removes_expired_entries(
        self, memory: EntityMemory, store: InMemoryEntityStore,
    ) -> None:
        live = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 1000,
        )
        expired = NamedEntity(
            type=DEPARTMENT, value='研发',
            source_turn_index=2, expires_at=NOW + 10,
        )
        memory.set(SESSION, live)
        memory.set(SESSION, expired)

        # 推进到第二个实体已过期，第一个还活着的时间点
        kept = memory.prune(SESSION, now=NOW + 100)

        assert kept == [live]
        # store 里也只剩 live
        assert store.load(SESSION) == [live]

    def test_prune_noop_when_nothing_expired(
        self, memory: EntityMemory, store: InMemoryEntityStore,
    ) -> None:
        e = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 1000,
        )
        memory.set(SESSION, e)
        kept = memory.prune(SESSION, now=NOW + 10)
        assert kept == [e]
        assert store.load(SESSION) == [e]

    def test_set_overrides_same_type(
        self, memory: EntityMemory, store: InMemoryEntityStore,
    ) -> None:
        """Req 4.6：同类型新值出现时覆盖最近实体而不是合并。"""
        first = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        )
        second = NamedEntity(
            type=EMPLOYEE, value='小李',
            source_turn_index=2, expires_at=NOW + 600,
        )
        memory.set(SESSION, first)
        memory.set(SESSION, second)

        # 仅保留新值；旧值被覆盖丢弃
        items = store.load(SESSION)
        assert items == [second]
        assert memory.get(SESSION, EMPLOYEE, now=NOW) == second

    def test_set_overrides_does_not_touch_other_types(
        self, memory: EntityMemory, store: InMemoryEntityStore,
    ) -> None:
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        memory.set(SESSION, NamedEntity(
            type=DEPARTMENT, value='研发',
            source_turn_index=2, expires_at=NOW + 600,
        ))
        # 覆盖 EMPLOYEE 类型，不应影响 DEPARTMENT
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小李',
            source_turn_index=3, expires_at=NOW + 600,
        ))
        items = {e.type: e.value for e in store.load(SESSION)}
        assert items == {EMPLOYEE: '小李', DEPARTMENT: '研发'}

    def test_session_isolation(self, memory: EntityMemory) -> None:
        a = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        )
        b = NamedEntity(
            type=EMPLOYEE, value='小李',
            source_turn_index=1, expires_at=NOW + 600,
        )
        memory.set('sess-A', a)
        memory.set('sess-B', b)
        assert memory.get('sess-A', EMPLOYEE, now=NOW) == a
        assert memory.get('sess-B', EMPLOYEE, now=NOW) == b


# =============================================================================
# resolve
# =============================================================================


class TestResolveIdentity:
    def test_empty_memory_no_pronoun_returns_query_unchanged(
        self, memory: EntityMemory,
    ) -> None:
        q = '本月的招聘进展怎么样'
        resolved, trace = memory.resolve(q, SESSION, now=NOW)
        assert resolved == q
        assert trace == {
            TRACE_KEY_PRONOUNS_FOUND: [],
            TRACE_KEY_SUBSTITUTIONS: [],
        }

    def test_query_with_no_pronoun_but_with_memory_still_identity(
        self, memory: EntityMemory,
    ) -> None:
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        q = '本月的招聘进展'
        resolved, trace = memory.resolve(q, SESSION, now=NOW)
        assert resolved == q
        assert trace[TRACE_KEY_PRONOUNS_FOUND] == []
        assert trace[TRACE_KEY_SUBSTITUTIONS] == []

    def test_empty_query_returns_empty(self, memory: EntityMemory) -> None:
        resolved, trace = memory.resolve('', SESSION, now=NOW)
        assert resolved == ''
        assert trace[TRACE_KEY_PRONOUNS_FOUND] == []


class TestResolvePronounSubstitution:
    def test_single_pronoun_replaced_with_latest_employee(
        self, memory: EntityMemory,
    ) -> None:
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        resolved, trace = memory.resolve('TA 的考勤怎么样', SESSION, now=NOW)
        assert resolved == '小王 的考勤怎么样'
        assert trace[TRACE_KEY_PRONOUNS_FOUND] == ['TA']
        sub = trace[TRACE_KEY_SUBSTITUTIONS][0]
        assert sub['pronoun'] == 'TA'
        assert sub['replaced_with'] == '小王'
        assert sub['type'] == EMPLOYEE
        assert sub['candidates'] == ['小王']

    def test_pronoun_unresolvable_when_no_compatible_entity(
        self, memory: EntityMemory,
    ) -> None:
        # memory 里只有 month，不能消解 TA
        memory.set(SESSION, NamedEntity(
            type=MONTH, value='2024-03',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        resolved, trace = memory.resolve('TA 怎么样', SESSION, now=NOW)
        # 找不到 → 保持原样
        assert resolved == 'TA 怎么样'
        sub = trace[TRACE_KEY_SUBSTITUTIONS][0]
        assert sub['pronoun'] == 'TA'
        assert sub['replaced_with'] is None
        assert sub['type'] is None
        assert sub['candidates'] == []

    def test_expired_entities_are_not_used_for_resolve(
        self, memory: EntityMemory,
    ) -> None:
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 100,
        ))
        # 推进到过期点之后
        resolved, trace = memory.resolve('TA 的考勤', SESSION, now=NOW + 200)
        assert resolved == 'TA 的考勤'
        assert trace[TRACE_KEY_SUBSTITUTIONS][0]['replaced_with'] is None

    def test_multi_candidate_picks_max_source_turn_index_and_records_all(
        self, store: InMemoryEntityStore, memory: EntityMemory,
    ) -> None:
        """Req 4.4：多候选时选 source_turn_index 最大者，候选列表写 trace。

        ``set`` 有覆盖语义，所以这里直接通过 store 注入两个 EMPLOYEE
        候选，模拟「同一 Pronoun 存在多个候选 NamedEntity」的极端情况
        （也可以是不同类型但被同一代词兼容的 employee + candidate）。
        """
        older = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        )
        newer = NamedEntity(
            type=EMPLOYEE, value='小李',
            source_turn_index=4, expires_at=NOW + 600,
        )
        # 直接注入两个同类型实体（绕过 set 的覆盖语义）
        store.save(SESSION, [older, newer])

        resolved, trace = memory.resolve('TA 的考勤', SESSION, now=NOW)
        assert resolved == '小李 的考勤'
        sub = trace[TRACE_KEY_SUBSTITUTIONS][0]
        assert sub['pronoun'] == 'TA'
        assert sub['replaced_with'] == '小李'
        # 候选列表包含全部
        assert sorted(sub['candidates']) == sorted(['小王', '小李'])

    def test_multi_candidate_across_types_for_one_pronoun(
        self, memory: EntityMemory,
    ) -> None:
        """``TA`` 同时兼容 EMPLOYEE 与 CANDIDATE → trace 应展示两个候选。"""
        memory.set(SESSION, NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        memory.set(SESSION, NamedEntity(
            type=CANDIDATE, value='张某',
            source_turn_index=3, expires_at=NOW + 600,
        ))

        resolved, trace = memory.resolve('TA 的简历', SESSION, now=NOW)
        # CANDIDATE 的 source_turn_index 更大 → 替换为「张某」
        assert resolved == '张某 的简历'
        sub = trace[TRACE_KEY_SUBSTITUTIONS][0]
        assert sub['replaced_with'] == '张某'
        assert sub['type'] == CANDIDATE
        assert sorted(sub['candidates']) == sorted(['小王', '张某'])

    def test_long_pronoun_matches_before_short_substring(
        self, memory: EntityMemory,
    ) -> None:
        """「这位候选人」要先于「这」之类短串命中，避免被部分吃掉。"""
        memory.set(SESSION, NamedEntity(
            type=CANDIDATE, value='张某',
            source_turn_index=1, expires_at=NOW + 600,
        ))
        resolved, trace = memory.resolve('这位候选人怎么样', SESSION, now=NOW)
        assert resolved == '张某怎么样'
        assert trace[TRACE_KEY_PRONOUNS_FOUND] == ['这位候选人']

    def test_resolve_does_not_mutate_underlying_entities(
        self, memory: EntityMemory, store: InMemoryEntityStore,
    ) -> None:
        before = NamedEntity(
            type=EMPLOYEE, value='小王',
            source_turn_index=1, expires_at=NOW + 600,
        )
        memory.set(SESSION, before)
        memory.resolve('TA 的考勤', SESSION, now=NOW)
        # store 里的实体保持不变（resolve 不应隐式 prune / 改动）
        assert store.load(SESSION) == [before]
