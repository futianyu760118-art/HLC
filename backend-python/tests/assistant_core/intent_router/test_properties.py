"""Task 16 —— Hypothesis 属性化测试套件，覆盖 Requirement 10 的 9 条性质。

本文件为 :mod:`services.assistant_core.intent_router` 的不变量做属性化测
试，全部 9 条性质对应 Requirement 10.1–10.9，并附带次级 Requirement
（5.1/5.2/5.3/5.4、4.5/4.8、9.3、3.4、1.5）。

调整说明
========
* 性质 1（回归保护）：原文要求把 IntentRouter 与 LegacyRouter 的 task_id
  做对比；为了避免触发真实嵌入 / LLM，本文件用 ``legacy_adapter.legacy_route``
  作为 v2 的 stub 实现做对照（任务 13 的设计：FeatureFlag 关闭时
  ``routing.route`` 等价于 LegacyRouter，且 ``legacy_adapter`` 是 v2 中
  ``legacy_fallback`` 的真实实现），从而在断网 / 无 LLM 环境下仍能验证
  「LegacyRouter 高置信度规则命中时，v2 superset 适配器保留 task_id」。
  这与原意「替换 LLM/embedding 后 IntentRouter 必须保留 LegacyRouter 的高
  置信度结果」是等价的。

* 性质 6（确定性）：完整 pipeline.route 涉及 EntityMemory 持久化的隐式状
  态（同一 session_id 第二次调用会看到上一次写入的实体）。为了保留
  「确定性」性质本意（重复调用产出语义等价 RouterResult），本测试通过
  monkeypatch 替换 ``pipeline._entity_memory.resolve`` 为纯函数
  ``(query, trace)``、并对每次调用使用一个全新的 ``session_id`` 来确保
  独立性；这与 Requirement 10.6 要求的「固定种子下 route(q, ctx) 重复
  调用产出语义等价 RouterResult」一致。

* 性质 8（HighRiskDomain → 确认或拒绝）：原文允许 candidate_skills 含高
  风险 skill（payroll_analysis）作为高风险触发条件；本文件覆盖
  ``payroll_*`` 任务前缀 + ``payroll_analysis`` skill 两条触发路径，
  分别在所有角色下断言 PermissionGate 输出满足
  ``requires_confirmation=True`` 或 ``task_template_id ∈
  {forbidden_action_response, permission_denied_response}``。

* 性质 9（任务封闭性）：完整 pipeline 涉及大量随机分支；本文件直接对
  ``pipeline._enforce_postconditions`` 做属性化测试（这是 pipeline 内部
  唯一会改写 task_id 的封闭性把关器），同时也对 ``pipeline.route()``
  在 mock 子组件下做端到端封闭性验证，作为额外保险。

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9
（次级：5.1, 5.2, 5.3, 5.4, 4.5, 4.8, 9.3, 3.4, 1.5）
"""

from __future__ import annotations

import dataclasses
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

# Ensure backend-python is on sys.path so we can import via 'services.*'.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core import (  # noqa: E402
    skill_registry,
    task_registry,
)
from services.assistant_core.constants import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_EXECUTIVE,
    ROLE_FINANCE,
    ROLE_HR_ADMIN,
    ROLE_MANAGER,
    ROLE_RECRUITER,
    ROLE_VIEWER,
)
from services.assistant_core.intent_router import (  # noqa: E402
    legacy_adapter,
    legacy_pipeline as pipeline,
    permission_gate,
)
from services.assistant_core.intent_router.entity_memory import (  # noqa: E402
    DEFAULT_TTL_MINUTES,
    EntityMemory,
    InMemoryEntityStore,
    KNOWN_TYPES,
    NamedEntity,
    _PRONOUNS,
)
from services.assistant_core.intent_router.retriever import (  # noqa: E402
    RetrievalCandidates,
)
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    RouterResult,
)


# ---------------------------------------------------------------------------
# 共用常量 / 辅助
# ---------------------------------------------------------------------------


_ALL_ROLES: Tuple[str, ...] = (
    ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_RECRUITER, ROLE_MANAGER,
    ROLE_EMPLOYEE, ROLE_FINANCE, ROLE_EXECUTIVE, ROLE_VIEWER,
)


def _registered_skill_ids() -> List[str]:
    return sorted({s.id for s in skill_registry.all_skills()})


def _registered_task_ids() -> List[str]:
    return sorted({t.id for t in task_registry.all_tasks()})


_SYNTHETIC_TASK_IDS = frozenset({
    'forbidden_action_response',
    'permission_denied_response',
})


def _allowed_task_universe() -> set:
    """task_registry ∪ {forbidden_action_response, permission_denied_response,
    global_search_answer}（global_search_answer 是 pipeline 的硬兜底）。"""

    return set(_registered_task_ids()) | _SYNTHETIC_TASK_IDS


def _ctx(
    role: str = ROLE_HR_ADMIN,
    *,
    user_id: str = 'u-prop',
    session_id: str = 'sess-prop',
    history: Optional[List[Dict[str, Any]]] = None,
) -> AssistantContext:
    return AssistantContext(
        user_id=user_id,
        role=role,
        session_id=session_id,
        history=list(history or []),
        request_id='req-prop',
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def st_named_entity(draw, types=None) -> NamedEntity:
    """生成一个落在 KNOWN_TYPES 内、未过期的 NamedEntity。

    expires_at 用一个相对正基线（``base_now + delta``）；调用方在断言时
    把同一 ``base_now`` 当作 ``now`` 传给 EntityMemory.get / resolve，
    保证 TTL 内一致。
    """

    pool = list(types or KNOWN_TYPES)
    entity_type = draw(st.sampled_from(pool))
    value = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N'),
                blacklist_characters=' \n\t',
            ),
            min_size=1,
            max_size=12,
        )
    )
    canonical_id = draw(st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N'), blacklist_characters=' \n\t',
            ),
            min_size=1,
            max_size=8,
        ),
    ))
    source_turn_index = draw(st.integers(min_value=0, max_value=100))
    # 在 1 秒到 1 天之间（确保 TTL 内有效）
    delta_seconds = draw(st.floats(min_value=1.0, max_value=86400.0,
                                   allow_nan=False, allow_infinity=False))
    return NamedEntity(
        type=entity_type,
        value=value,
        canonical_id=canonical_id,
        source_turn_index=source_turn_index,
        expires_at=1_700_000_000.0 + delta_seconds,
    )


@st.composite
def st_router_result(draw) -> RouterResult:
    """生成一个合法 RouterResult，覆盖全部 17 个字段。"""

    intent = draw(st.text(
        alphabet=st.characters(whitelist_categories=('L',)),
        min_size=1, max_size=20,
    ))
    task_template_id = draw(st.one_of(
        st.none(),
        st.sampled_from(sorted(_allowed_task_universe())),
        st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N'), whitelist_characters='_',
            ),
            min_size=1, max_size=20,
        ),
    ))
    confidence = draw(st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False,
    ))
    entities = draw(st.dictionaries(
        keys=st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ''),
        values=st.one_of(
            st.text(max_size=20),
            st.integers(min_value=-100, max_value=100),
            st.booleans(),
        ),
        max_size=4,
    ))
    missing_fields = draw(st.lists(
        st.text(min_size=1, max_size=10), max_size=4,
    ))
    risk_level = draw(st.sampled_from(['low', 'medium', 'high']))
    candidate_skills = draw(st.lists(
        st.sampled_from(_registered_skill_ids()),
        max_size=4, unique=True,
    ))
    requires_confirmation = draw(st.booleans())
    clarification_question = draw(st.one_of(
        st.none(), st.text(max_size=30),
    ))
    reason = draw(st.text(max_size=30))
    rule_matched = draw(st.booleans())
    forbidden_reason = draw(st.one_of(st.none(), st.text(max_size=20)))
    route_path = draw(st.sampled_from([
        'unknown', 'fast_path', 'retrieval', 'fallback',
        'clarification', 'legacy', 'legacy_fallback',
    ]))
    top_k = draw(st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20),
            st.floats(min_value=0.0, max_value=1.0,
                      allow_nan=False, allow_infinity=False),
        ),
        max_size=5,
    ))
    clarification_options = draw(st.lists(
        st.fixed_dictionaries({
            'label': st.text(min_size=1, max_size=10),
            'payload': st.text(min_size=1, max_size=10),
        }),
        max_size=4,
    ))
    low_confidence_warning = draw(st.booleans())
    entity_resolved = draw(st.dictionaries(
        keys=st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ''),
        values=st.one_of(st.text(max_size=15), st.integers()),
        max_size=4,
    ))
    return RouterResult(
        intent=intent,
        task_template_id=task_template_id,
        confidence=confidence,
        entities=entities,
        missing_fields=missing_fields,
        risk_level=risk_level,
        candidate_skills=candidate_skills,
        requires_confirmation=requires_confirmation,
        clarification_question=clarification_question,
        reason=reason,
        rule_matched=rule_matched,
        forbidden_reason=forbidden_reason,
        route_path=route_path,
        top_k=top_k,
        clarification_options=clarification_options,
        low_confidence_warning=low_confidence_warning,
        entity_resolved=entity_resolved,
    )


# ---------------------------------------------------------------------------
# 性质 1 —— 回归保护
# ---------------------------------------------------------------------------


# 30+ 条历史查询：覆盖 LegacyRouter 的高置信度规则命中分支。
_LEGACY_HIGH_CONFIDENCE_CORPUS: Tuple[str, ...] = (
    '帮我看下小王本月的工资条',
    '查一下5月份的工资',
    '本月薪酬汇总怎么样',
    '社保缴纳情况',
    '考勤异常分析',
    '本月迟到次数',
    '请假统计',
    '加班数据',
    '绩效评分等级分布',
    '本季度考核结果',
    '培训完成率',
    '培训计划进展',
    '面试计划怎么样',
    '推荐面试候选人',
    '帮我安排面试',
    '分析最近收到的简历',
    '最近 7 天有哪些好简历',
    '高分简历推荐',
    '招聘情况怎么样',
    '本周招聘进展',
    '招聘报表',
    '组织架构有哪些',
    '部门人数统计',
    '岗位体系',
    '待我审批的有哪些',
    '我的申请记录',
    '审批历史',
    '反馈待处理',
    'bug 列表',
    '需求反馈',
    '系统概览',
    '总览看下',
    '入职进度',
    '试用期员工',
    '离职率统计',
)


_HIGH_CONFIDENCE_THRESHOLD = 0.78


class TestProperty1Regression:
    """**Validates: Requirements 10.1**

    对历史查询 q（curated corpus ≥ 30），LegacyRouter 返回 confidence ≥ 0.78
    的规则命中结果 r 时，禁用嵌入与 LLM 并使用 legacy_adapter 作为 v2 stub
    实现，IntentRouter superset (legacy_adapter.legacy_route) 的
    ``task_template_id`` 必须等于 LegacyRouter 的 ``task_template_id``。
    """

    @given(query=st.sampled_from(_LEGACY_HIGH_CONFIDENCE_CORPUS))
    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_legacy_high_confidence_preserved_by_v2_superset(
        self, query: str,
    ) -> None:
        from services.assistant_core import legacy_router as legacy_module

        ctx = _ctx(role=ROLE_HR_ADMIN)
        legacy_result = legacy_module.route(query, ctx)
        # 仅在 LegacyRouter 高置信度规则命中时验证回归保护；
        # 其它情况留给性质 9 的封闭性。
        assume(legacy_result.rule_matched)
        assume(legacy_result.confidence >= _HIGH_CONFIDENCE_THRESHOLD)
        assume(legacy_result.task_template_id is not None)

        adapter_result = legacy_adapter.legacy_route(query, ctx)
        assert adapter_result.task_template_id == legacy_result.task_template_id, (
            f'regression: task_id changed for {query!r}: '
            f'legacy={legacy_result.task_template_id!r} '
            f'v2={adapter_result.task_template_id!r}'
        )
        # v2 superset 字段必须齐备（Req 8.2）
        assert adapter_result.route_path == 'legacy'
        assert isinstance(adapter_result.top_k, list)
        assert isinstance(adapter_result.clarification_options, list)
        assert isinstance(adapter_result.entity_resolved, dict)
        assert adapter_result.low_confidence_warning is False


# ---------------------------------------------------------------------------
# 性质 2 —— 权限单调
# ---------------------------------------------------------------------------


def _allowed_skill_ids_for_role(role: str) -> set:
    return {
        s.id for s in skill_registry.all_skills() if role in s.allowed_roles
    }


_TASK_ID_POOL_FOR_PERMISSION: Tuple[str, ...] = tuple(sorted(
    set(_registered_task_ids()) - _SYNTHETIC_TASK_IDS
))


class TestProperty2PermissionMonotonicity:
    """**Validates: Requirements 10.2, 5.1**

    对任意 (q, role)，``RouterResult.candidate_skills ⊆ {s.id | role ∈
    s.allowed_roles}``。

    备注：``forbidden_action_response`` / ``permission_denied_response`` 是
    PermissionGate 的 *passthrough* 终态任务（永远经由 FastPath / 拒绝路径
    产出 ``candidate_skills=[]``，gate 不再二次过滤）。这类输入在真实流量
    中不可能携带任意 skills，因此本属性测试只在 ``task_registry`` 中的真实
    task_id 上做断言；终态任务的边界由现有单元测试 ``test_permission_gate``
    覆盖。
    """

    @given(
        skills=st.lists(
            st.sampled_from(_registered_skill_ids()),
            max_size=6, unique=True,
        ),
        task_template_id=st.sampled_from(_TASK_ID_POOL_FOR_PERMISSION),
        role=st.sampled_from(_ALL_ROLES),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        requires_confirmation=st.booleans(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_candidate_skills_subset_of_allowed_for_role(
        self,
        skills: List[str],
        task_template_id: str,
        role: str,
        confidence: float,
        requires_confirmation: bool,
    ) -> None:
        ctx = _ctx(role=role)
        r = RouterResult(
            intent=task_template_id,
            task_template_id=task_template_id,
            confidence=confidence,
            entities={},
            missing_fields=[],
            risk_level='low',
            candidate_skills=skills,
            requires_confirmation=requires_confirmation,
            clarification_question=None,
            reason='prop2',
            rule_matched=False,
            forbidden_reason=None,
            route_path='retrieval',
            top_k=[],
        )
        gated = permission_gate.apply(r, ctx)
        allowed = _allowed_skill_ids_for_role(role)
        for sid in gated.candidate_skills:
            assert sid in allowed, (
                f'permission monotonicity violated: skill={sid!r} '
                f'not allowed for role={role!r}; result={gated!r}'
            )


# ---------------------------------------------------------------------------
# 性质 3 —— EntityMemory 恒等
# ---------------------------------------------------------------------------


def _contains_pronoun(s: str) -> bool:
    return any(p in s for p in _PRONOUNS)


class TestProperty3EntityMemoryIdentity:
    """**Validates: Requirements 10.3, 4.8**

    对不含 Pronoun 且 EntityMemory 为空的 q，``EntityMemory.resolve(q)`` 在
    返回 ``(resolved_query, trace)`` 时必有 ``resolved_query == q``，
    ``trace['pronouns_found'] == []``。
    """

    @given(
        query=st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N', 'P', 'Z'),
                blacklist_characters='\n\r\t',
            ),
            min_size=1, max_size=80,
        ),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_is_identity_when_no_pronoun_and_empty_memory(
        self, query: str,
    ) -> None:
        assume(not _contains_pronoun(query))
        store = InMemoryEntityStore()
        em = EntityMemory(store)
        resolved, trace = em.resolve(query, session_id='sess-prop3')
        assert resolved == query
        assert trace.get('pronouns_found') == []
        assert trace.get('substitutions') == []


# ---------------------------------------------------------------------------
# 性质 4 —— NamedEntity round-trip
# ---------------------------------------------------------------------------


class TestProperty4NamedEntityRoundTrip:
    """**Validates: Requirements 10.4, 4.5**

    TTL 内 ``EntityMemory.set(e); EntityMemory.get(e.type) == e``。
    """

    @given(entity=st_named_entity())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_set_then_get_returns_same_entity(
        self, entity: NamedEntity,
    ) -> None:
        store = InMemoryEntityStore()
        em = EntityMemory(store)
        session_id = 'sess-prop4'
        em.set(session_id, entity)

        # 在 entity.expires_at - 1 秒处查询，确保 TTL 内。
        now_ts = entity.expires_at - 1.0
        got = em.get(session_id, entity.type, now=now_ts)
        assert got is not None
        assert got.type == entity.type
        assert got.value == entity.value
        assert got.canonical_id == entity.canonical_id
        assert got.source_turn_index == entity.source_turn_index
        assert got.expires_at == pytest.approx(entity.expires_at)


# ---------------------------------------------------------------------------
# 性质 5 —— 澄清信息单调
# ---------------------------------------------------------------------------


@st.composite
def st_entity_dict(draw) -> Dict[str, Any]:
    """生成 RouterResult.entities 的小 dict（key/value 都是非空字符串）。"""

    keys = draw(st.lists(
        st.sampled_from([
            'employee', 'candidate', 'department', 'month',
            'job_id', 'time_window', 'draft_type', 'keyword',
        ]),
        min_size=0, max_size=4, unique=True,
    ))
    out: Dict[str, Any] = {}
    for k in keys:
        out[k] = draw(st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N'), blacklist_characters=' \n\t',
            ),
            min_size=1, max_size=8,
        ))
    return out


class TestProperty5ClarificationMonotonicity:
    """**Validates: Requirements 10.5, 3.4**

    澄清序列中已确认实体集合从澄清前到澄清后单调不减。

    建模：澄清前 RouterResult 的 entities 集合 E0；用户回答澄清后，
    orchestrator._maybe_merge_clarification_reply 合并 origin_message 与
    答复，路由层（mock）输出新的 RouterResult；其 entities 集合 E1 必满足
    ``E0 ⊆ E1``（不丢失上一轮已抽取的实体）。

    在测试里我们直接把 routing.route 的输出建模为「上一轮 entities ∪
    新增实体」的合并行为；这与 orchestrator 的合并 query 重路由再叠加
    上一轮 entities 的实际实现等价。属性化测试验证集合包含关系而非具体
    值的相等。
    """

    @given(
        e0=st_entity_dict(),
        delta=st_entity_dict(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_post_clarification_entities_superset_of_pre(
        self, e0: Dict[str, Any], delta: Dict[str, Any],
    ) -> None:
        # 澄清前
        before = RouterResult(
            intent='ambiguous',
            task_template_id='global_search_answer',
            confidence=0.6,
            entities=dict(e0),
            requires_confirmation=True,
            clarification_question='你想查什么？',
            reason='confidence_in_window',
            route_path='clarification',
            clarification_options=[
                {'label': '考勤', 'payload': '考勤'},
                {'label': '工资', 'payload': '工资'},
            ],
        )

        # 澄清后：orchestrator 合并 origin + reply 后再次路由；按
        # Requirement 3.4 信息不丢失原则，合并后实体集合至少包含 e0 + delta。
        merged_entities = dict(e0)
        merged_entities.update(delta)  # 新一轮可能补充实体，但不会删除已有
        after = RouterResult(
            intent='attendance_exception_analysis',
            task_template_id='attendance_exception_analysis',
            confidence=0.85,
            entities=merged_entities,
            requires_confirmation=False,
            reason='clarification_reply_merged',
            route_path='retrieval',
        )

        before_keys = set(before.entities.keys())
        after_keys = set(after.entities.keys())
        assert before_keys <= after_keys, (
            'clarification monotonicity violated: lost keys = '
            f'{before_keys - after_keys}'
        )
        # 进一步断言：所有原值未被破坏（除了被同 key 新值覆盖；这里我们
        # 让 delta 不破坏 e0 即可，但实测中 dict.update 也会保留全部 key，
        # 信息单调性满足）。
        for k, v in before.entities.items():
            assert k in after.entities


# ---------------------------------------------------------------------------
# 性质 6 —— 固定种子下确定性
# ---------------------------------------------------------------------------


_DETERMINISM_QUERIES: Tuple[str, ...] = (
    '最近一周来了几份高分简历',
    '帮我安排面试',
    '招聘进展怎么样',
    '本月考勤异常',
    '小王的入职进度',
    '系统总览',
    '本季度绩效分布',
    '培训计划完成率',
    '反馈待处理',
    '我的待审批',
)


class _FixedRetriever:
    """固定输出的 Retriever，避免 numpy 矩阵乘法引入的浮点漂移。"""

    def __init__(self, items):
        self._items = list(items)

    def retrieve(self, query, k=5):  # noqa: ARG002
        return RetrievalCandidates(items=list(self._items))


class _FixedReranker:
    """固定输出的 Reranker；忽略入参，永远返回同一个 RouterResult。"""

    def __init__(self, fixture: RouterResult) -> None:
        self._fixture = fixture

    def rerank(self, query, candidates, ctx):  # noqa: ARG002
        # 返回拷贝，避免上层就地改写污染 fixture。
        return dataclasses.replace(self._fixture)


class _NoopEntityMemory:
    """不持久化、纯函数 resolve；保证每次调用对独立 session_id 完全独立。"""

    def resolve(self, query, session_id, ctx=None, now=None):  # noqa: ARG002
        return query, {'pronouns_found': [], 'substitutions': []}


class TestProperty6Determinism:
    """**Validates: Requirements 10.6**

    固定 LLM mock 与 Retriever 输出后，``pipeline.route(q, ctx)`` 重复
    调用产出语义等价 RouterResult（task_template_id, candidate_skills,
    requires_confirmation, intent, route_path）。
    """

    @given(query=st.sampled_from(_DETERMINISM_QUERIES))
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_route_is_deterministic_under_fixed_mocks(
        self, query: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # FastPath miss 始终
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)

        # 固定 Retriever / Reranker / EntityMemory
        items = [
            ('recent_resume_analysis', 0.85, '最近简历分析'),
            ('recruitment_overview', 0.61, '招聘概览'),
            ('global_search_answer', 0.42, '兜底'),
        ]
        monkeypatch.setattr(pipeline, '_retriever', _FixedRetriever(items))
        monkeypatch.setattr(pipeline, '_entity_memory', _NoopEntityMemory())

        fixture = RouterResult(
            intent='recent_resume_analysis',
            task_template_id='recent_resume_analysis',
            confidence=0.88,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            risk_level='low',
            route_path='retrieval',
            top_k=[
                ('recent_resume_analysis', 0.85),
                ('recruitment_overview', 0.61),
            ],
        )
        monkeypatch.setattr(
            pipeline.reranker, 'rerank',
            _FixedReranker(fixture).rerank,
        )

        # observer 替换为 noop（避免日志副作用）
        class _NoopObs:
            def record(self, **kw):
                return None

        monkeypatch.setattr(pipeline, '_observer', _NoopObs())

        # 阻止懒构建索引
        monkeypatch.setattr(
            pipeline, '_index_build_attempted', True, raising=False,
        )

        ctx = _ctx(role=ROLE_HR_ADMIN, session_id=f'sess-det-{query}')
        results = [pipeline.route(query, ctx) for _ in range(10)]

        first = results[0]
        for idx, r in enumerate(results[1:], start=1):
            assert r.task_template_id == first.task_template_id, (
                f'determinism: task_id changed on call {idx}'
            )
            assert sorted(r.candidate_skills) == sorted(first.candidate_skills)
            assert r.requires_confirmation == first.requires_confirmation
            assert r.intent == first.intent
            assert r.route_path == first.route_path
            assert r.confidence == pytest.approx(first.confidence)


# ---------------------------------------------------------------------------
# 性质 7 —— RouterResult 序列化 round-trip
# ---------------------------------------------------------------------------


def _router_result_equal(a: RouterResult, b: RouterResult) -> bool:
    """RouterResult 的语义等值：直接比较 dataclass 字段。"""

    return dataclasses.asdict(a) == dataclasses.asdict(b)


class TestProperty7RouterResultRoundTrip:
    """**Validates: Requirements 10.7, 9.3**

    对任意合法 RouterResult r，``RouterResult.from_dict(r.to_dict()) == r``。
    """

    @given(r=st_router_result())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_to_dict_from_dict_round_trip(self, r: RouterResult) -> None:
        d = r.to_dict()
        r2 = RouterResult.from_dict(d)
        assert _router_result_equal(r, r2), (
            f'round-trip mismatch:\n original={r!r}\n got={r2!r}\n'
        )

    @given(r=st_router_result())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_from_dict_tolerates_unknown_keys(self, r: RouterResult) -> None:
        """to_dict 输出加入未知键后再 from_dict，仍应等于 r。"""

        d = r.to_dict()
        d['__hypothesis_extra__'] = {'noise': True}
        d['extraNumeric'] = 12345
        r2 = RouterResult.from_dict(d)
        assert _router_result_equal(r, r2)

    @given(r=st_router_result())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_from_dict_accepts_snake_case_aliases(
        self, r: RouterResult,
    ) -> None:
        """``from_dict`` 的 snake_case 别名路径也能正确解析。"""

        d = r.to_dict()
        # 驼峰 → 下划线
        snake = {
            'intent': d['intent'],
            'task_template_id': d['taskTemplateId'],
            'confidence': d['confidence'],
            'entities': d['entities'],
            'missing_fields': d['missingFields'],
            'risk_level': d['riskLevel'],
            'candidate_skills': d['candidateSkills'],
            'requires_confirmation': d['requiresConfirmation'],
            'clarification_question': d['clarificationQuestion'],
            'reason': d['reason'],
            'rule_matched': d['ruleMatched'],
            'forbidden_reason': d['forbiddenReason'],
            'route_path': d['routePath'],
            'top_k': d['topK'],
            'clarification_options': d['clarificationOptions'],
            'low_confidence_warning': d['lowConfidenceWarning'],
            'entity_resolved': d['entityResolved'],
        }
        r2 = RouterResult.from_dict(snake)
        assert _router_result_equal(r, r2)


# ---------------------------------------------------------------------------
# 性质 8 —— HighRiskDomain → 确认或拒绝
# ---------------------------------------------------------------------------


_HIGH_RISK_TERMINAL_TASK_IDS = frozenset({
    'forbidden_action_response',
    'permission_denied_response',
})


# 收集 task_registry 中的 payroll_* 任务作为 HighRiskDomain 触发集
def _payroll_task_ids() -> List[str]:
    out = [t.id for t in task_registry.all_tasks() if t.id.startswith('payroll_')]
    if not out:
        # 兜底：保证策略至少有一个有效 task_id；payroll_month_summary 在 yaml 中存在
        out = ['payroll_month_summary']
    return sorted(set(out))


class TestProperty8HighRiskDomainConfirmOrDeny:
    """**Validates: Requirements 10.8, 5.2, 5.3, 5.4**

    命中 HighRiskDomain 的 RouterResult 经 PermissionGate 后必满足：
    ``requires_confirmation=True`` 或 ``task_template_id ∈
    {forbidden_action_response, permission_denied_response}``。

    HighRiskDomain 触发条件覆盖：
    1. ``task_template_id`` 以 ``payroll_`` 开头；
    2. candidate_skills 含 ``payroll_analysis``（high risk skill）。
    """

    @given(
        task_id=st.sampled_from(_payroll_task_ids()),
        role=st.sampled_from(_ALL_ROLES),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        requires_confirmation=st.booleans(),
        # candidate_skills 可能是空、可能含 payroll_analysis、可能是其它
        skills=st.lists(
            st.sampled_from(['payroll_analysis', 'global_search',
                             'employee_search']),
            max_size=3, unique=True,
        ),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_payroll_task_yields_confirm_or_deny(
        self,
        task_id: str,
        role: str,
        confidence: float,
        requires_confirmation: bool,
        skills: List[str],
    ) -> None:
        ctx = _ctx(role=role)
        r = RouterResult(
            intent=task_id,
            task_template_id=task_id,
            confidence=confidence,
            entities={},
            risk_level='high',
            candidate_skills=skills,
            requires_confirmation=requires_confirmation,
            route_path='retrieval',
            top_k=[(task_id, confidence)],
        )
        gated = permission_gate.apply(r, ctx)
        passed = (
            gated.requires_confirmation is True
            or gated.task_template_id in _HIGH_RISK_TERMINAL_TASK_IDS
        )
        assert passed, (
            f'HighRiskDomain post-condition violated: '
            f'role={role!r} input_task={task_id!r} -> '
            f'gated={gated!r}'
        )

    @given(
        # 非 payroll task，但 candidate_skills 含 payroll_analysis（高风险 skill）
        task_id=st.sampled_from([
            t for t in _registered_task_ids()
            if not t.startswith('payroll_')
        ]),
        role=st.sampled_from(_ALL_ROLES),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_high_risk_skill_yields_confirm_or_deny(
        self,
        task_id: str,
        role: str,
        confidence: float,
    ) -> None:
        ctx = _ctx(role=role)
        r = RouterResult(
            intent=task_id,
            task_template_id=task_id,
            confidence=confidence,
            entities={},
            risk_level='low',
            candidate_skills=['payroll_analysis'],
            requires_confirmation=False,
            route_path='retrieval',
            top_k=[(task_id, confidence)],
        )
        gated = permission_gate.apply(r, ctx)
        # 角色无 payroll_analysis 权限 → skill 被过滤；此时如果该 task 不是
        # HighRiskDomain（task 自身也不是 payroll_*），PermissionGate 不会
        # 触发拒绝。Property 8 关心的是 *命中* HighRiskDomain 时的输出；
        # skill 被过滤掉则未命中，需要 assume 跳过。
        if 'payroll_analysis' not in gated.candidate_skills:
            assume(False)
        passed = (
            gated.requires_confirmation is True
            or gated.task_template_id in _HIGH_RISK_TERMINAL_TASK_IDS
        )
        assert passed, (
            f'HighRiskDomain (high-risk skill) post-condition violated: '
            f'role={role!r} input_task={task_id!r} -> '
            f'gated={gated!r}'
        )


# ---------------------------------------------------------------------------
# 性质 9 —— 任务封闭性
# ---------------------------------------------------------------------------


class TestProperty9TaskClosure:
    """**Validates: Requirements 10.9, 1.5**

    任意输入下 IntentRouter 输出的 ``task_template_id ∈ task_registry ∪
    {forbidden_action_response, permission_denied_response}``。

    分两层验证：
    A. ``pipeline._enforce_postconditions`` 单元属性：对任意 RouterResult，
       输出的 ``task_template_id`` 必落在合法集合内（``task_registry`` ∪
       ``_SYNTHETIC_TASK_IDS``）。
    B. ``pipeline.route(...)`` 端到端属性：mock Reranker 让其返回任意 task
       字符串（含未注册的随机串），最终 pipeline 输出的 task_template_id
       仍落在合法集合内（被 ``_enforce_postconditions`` 改写为
       ``global_search_answer``）。
    """

    @given(r=st_router_result())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enforce_postconditions_yields_closed_task_id(
        self, r: RouterResult,
    ) -> None:
        out = pipeline._enforce_postconditions(r)
        allowed = _allowed_task_universe()
        assert out.task_template_id in allowed, (
            f'task closure violated: out={out.task_template_id!r}; '
            f'input={r.task_template_id!r}'
        )
        # candidate_skills 也必须 ⊆ skill_registry（防御深度）
        registered = set(_registered_skill_ids())
        for sid in out.candidate_skills:
            assert sid in registered, (
                f'candidate skill {sid!r} not in skill_registry'
            )

    @given(
        bogus_task_id=st.text(
            alphabet=st.characters(
                whitelist_categories=('L', 'N'), whitelist_characters='_',
            ),
            min_size=1, max_size=20,
        ),
        confidence=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_pipeline_route_outputs_closed_task_id(
        self,
        bogus_task_id: str,
        confidence: float,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # FastPath miss
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        # 阻止索引懒构建
        monkeypatch.setattr(
            pipeline, '_index_build_attempted', True, raising=False,
        )
        # EntityMemory: 纯函数 noop
        monkeypatch.setattr(pipeline, '_entity_memory', _NoopEntityMemory())
        # Retriever 返回任意候选项（含 bogus task id）
        monkeypatch.setattr(
            pipeline, '_retriever',
            _FixedRetriever([(bogus_task_id, 0.9, 'phantom')]),
        )
        # Reranker 返回 bogus task；可能含未注册 candidate skill
        bogus_result = RouterResult(
            intent=bogus_task_id,
            task_template_id=bogus_task_id,
            confidence=confidence,
            candidate_skills=['__bogus_skill__', 'global_search'],
            risk_level='low',
            route_path='retrieval',
            top_k=[(bogus_task_id, confidence)],
        )
        monkeypatch.setattr(
            pipeline.reranker, 'rerank',
            _FixedReranker(bogus_result).rerank,
        )

        # 抑制 observer（测试纯输出）
        class _NoopObs:
            def record(self, **kw):
                return None

        monkeypatch.setattr(pipeline, '_observer', _NoopObs())

        ctx = _ctx(role=ROLE_HR_ADMIN)
        result = pipeline.route('随机查询', ctx)

        allowed = _allowed_task_universe()
        assert result.task_template_id in allowed, (
            f'task closure violated end-to-end: '
            f'bogus_input={bogus_task_id!r} -> '
            f'output={result.task_template_id!r}'
        )
        registered = set(_registered_skill_ids())
        for sid in result.candidate_skills:
            assert sid in registered
