"""Task 12.1 —— IntentRouter 顶层流水线单元测试。

校验目标（Validates: Requirements 1.1, 1.5, 1.7, 5.1, 5.2, 5.3, 5.4, 6.1,
6.2, 7.1, 7.2, 12.4）：

* **FastPath 命中**：薪酬关键词 / 写动作直通时返回的 ``RouterResult``
  ``task_template_id`` 与 FastPath 一致；仍然经过 ``PermissionGate``
  （``hr_admin`` 下保留高风险薪酬路径，``employee`` 下被改写为
  ``permission_denied_response``）；``ObservabilityRecorder`` 被调用
  恰好一次，``route_path='fast_path'``（或拒绝路径上保留 ``fast_path``
  / 改写 task）。
* **retrieval 正常路径**：FastPath miss → ``EntityMemory.resolve`` →
  ``Retriever.retrieve`` 返回非空 → ``Reranker.rerank`` 选 ``task_id``
  ∈ candidates → ``ConfidenceGate.evaluate`` 设 ``route_path``（依据
  confidence）→ ``PermissionGate.apply`` 收尾。断言每个组件均被调用。
* **嵌入服务不可用**：``Retriever`` 返回 ``reason='embedding_unavailable'``
  → IntentRouter 标记 ``route_path='legacy_fallback'``，调用
  ``legacy_module.route``（patched 返回 fixture），最终 ``RouterResult``
  的 ``task_template_id`` 与 LegacyRouter 一致；``ObservabilityRecorder``
  收到 ``route_path='legacy_fallback'``。
* **未知 task_id**：构造一个 ``Reranker`` mock 返回
  ``RouterResult.task_template_id='__no_such_task__'`` → IntentRouter 强制
  改写为 ``'global_search_answer'``，``candidate_skills=['global_search']``。
* **PermissionGate 改写顺序生效**：retrieval 路径 + ``Reranker`` 选
  ``payroll_month_summary`` + ``ctx.role='employee'`` → 最终
  ``task_template_id='permission_denied_response'``。
"""

from __future__ import annotations

import dataclasses
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Ensure backend-python is on sys.path so we can import via 'services.*'.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core import skill_registry, task_registry  # noqa: E402
from services.assistant_core.constants import RISK_HIGH, RISK_LOW  # noqa: E402
from services.assistant_core.intent_router import legacy_pipeline as pipeline  # noqa: E402
from services.assistant_core.intent_router.retriever import (  # noqa: E402
    REASON_EMBEDDING_UNAVAILABLE,
    RetrievalCandidates,
)
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    RouterResult,
)


# ---------------------------------------------------------------------------
# 共享 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_lazy_index_build(monkeypatch: pytest.MonkeyPatch):
    """禁掉懒构建路径，避免测试期触发真实嵌入调用。

    把 ``_index_build_attempted`` 直接置为 True；并把 ``_retrieval_index.is_empty``
    打桩成 False，让 Retriever 不会因为 ``index_empty`` 短路（Retriever 在
    本测试里是被整体 mock 的，但留一道安全网）。
    """

    monkeypatch.setattr(pipeline, '_index_build_attempted', True, raising=False)
    monkeypatch.setattr(
        pipeline._retrieval_index, 'is_empty', lambda: False, raising=False,
    )
    yield


@pytest.fixture(autouse=True)
def _reset_observer_calls(monkeypatch: pytest.MonkeyPatch):
    """每个测试用一个独立的 spy ObservabilityRecorder。"""

    spy = _SpyObserver()
    monkeypatch.setattr(pipeline, '_observer', spy)
    yield


def _ctx(role: str = 'hr_admin', **kw: Any) -> AssistantContext:
    return AssistantContext(
        user_id=kw.pop('user_id', 'u-1'),
        role=role,
        session_id=kw.pop('session_id', 'sess-1'),
        history=kw.pop('history', []),
        request_id=kw.pop('request_id', 'req-1'),
        **kw,
    )


def _payroll_fastpath_result() -> RouterResult:
    """FastPath 命中薪酬域时的典型返回。"""

    return RouterResult(
        intent='payroll_month_summary',
        task_template_id='payroll_month_summary',
        confidence=0.95,
        entities={'matched_keyword': '工资条'},
        missing_fields=[],
        risk_level=RISK_HIGH,
        candidate_skills=['payroll_analysis'],
        requires_confirmation=False,
        clarification_question=None,
        reason='fastpath:payroll:工资条',
        rule_matched=True,
        forbidden_reason=None,
        route_path='fast_path',
    )


def _retrieval_result(
    *,
    task_template_id: str,
    confidence: float,
    candidate_skills: List[str],
    top_k: Optional[List[Tuple[str, float]]] = None,
    risk_level: str = RISK_LOW,
) -> RouterResult:
    """retrieval 路径上 Reranker 的典型返回。"""

    return RouterResult(
        intent=task_template_id,
        task_template_id=task_template_id,
        confidence=confidence,
        candidate_skills=list(candidate_skills),
        risk_level=risk_level,
        route_path='retrieval',
        top_k=list(top_k or [(task_template_id, confidence)]),
    )


# ---------------------------------------------------------------------------
# Spy / mock 构件
# ---------------------------------------------------------------------------


class _SpyObserver:
    """记录 ObservabilityRecorder.record 的调用。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:  # 与真实方法签名一致
        # 拷贝关键字段，便于后续断言不被后续调用覆盖。
        self.calls.append(dict(kwargs))


class _SpyEntityMemory:
    """打桩 EntityMemory.resolve；本任务不验证实体抽取细节。"""

    def __init__(
        self,
        *,
        resolve_result: Optional[Tuple[str, Dict[str, Any]]] = None,
    ) -> None:
        self._resolve_result = resolve_result
        self.resolve_calls: List[Tuple[str, str]] = []

    def resolve(
        self, query: str, session_id: str, ctx: Optional[Any] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        self.resolve_calls.append((query, session_id))
        if self._resolve_result is not None:
            return self._resolve_result
        return query, {'pronouns_found': [], 'substitutions': []}


# ---------------------------------------------------------------------------
# 1) FastPath 命中
# ---------------------------------------------------------------------------


class TestFastPathHit:
    def test_payroll_fastpath_kept_for_hr_admin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """薪酬关键词命中：``hr_admin`` 角色应保留路由，强制确认。"""
        captured: Dict[str, Any] = {}

        def fake_match(message, ctx):  # noqa: ANN001 - 只在测试里
            captured['message'] = message
            captured['ctx'] = ctx
            return _payroll_fastpath_result()

        monkeypatch.setattr(pipeline.fastpath, 'match', fake_match)
        # 确保 retrieval 路径不会被走到（不应该被调到）。
        retrieve_calls: List[Any] = []

        def boom_retrieve(*a, **kw):  # noqa: ANN001
            retrieve_calls.append((a, kw))
            raise AssertionError('Retriever should not be called on FastPath hit')

        monkeypatch.setattr(pipeline._retriever, 'retrieve', boom_retrieve)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('帮我看下小王本月的工资条', ctx)

        assert result.task_template_id == 'payroll_month_summary'
        assert result.route_path == 'fast_path'
        assert result.risk_level == RISK_HIGH
        # PermissionGate 把 payroll_analysis 的 high risk 风险锁定 → 强制 confirm
        assert result.requires_confirmation is True
        assert 'payroll_analysis' in result.candidate_skills
        # FastPath 命中不应触发 retrieval。
        assert retrieve_calls == []
        # ObservabilityRecorder 恰好一次，route_path='fast_path'
        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'fast_path'
        assert spy.calls[0]['chosen_task_id'] == 'payroll_month_summary'
        # 消息原文不能进观测；只允许 hash + length。
        for value in spy.calls[0].values():
            assert '工资条' not in str(value), (
                f'plaintext leaked into observer: {value!r}'
            )
        assert spy.calls[0]['message_length'] == len('帮我看下小王本月的工资条')

    def test_payroll_fastpath_denied_for_employee(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """薪酬命中：``employee`` 角色应被改写为 ``permission_denied_response``。"""

        monkeypatch.setattr(
            pipeline.fastpath, 'match',
            lambda message, ctx: _payroll_fastpath_result(),
        )

        ctx = _ctx(role='employee')
        result = pipeline.route('查一下我的工资条', ctx)

        assert result.task_template_id == 'permission_denied_response'
        # PermissionGate 把 route_path 保留为 fast_path（非 unknown / 空）。
        assert result.route_path == 'fast_path'
        assert result.risk_level == RISK_HIGH
        assert result.candidate_skills == []
        assert result.requires_confirmation is False
        # Observability 仍被调用一次，route_path 与最终一致。
        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'fast_path'
        assert spy.calls[0]['chosen_task_id'] == 'permission_denied_response'

    def test_forbidden_action_fastpath_observed_once(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """写动作直通：``forbidden_action_response`` 经过 PermissionGate 的
        passthrough，不被改写；Observability 记录一次。"""

        forbidden = RouterResult(
            intent='forbidden_action',
            task_template_id='forbidden_action_response',
            confidence=0.99,
            entities={'forbidden_reason': 'delete_intent'},
            risk_level=RISK_HIGH,
            requires_confirmation=True,
            forbidden_reason='delete_intent',
            route_path='fast_path',
            rule_matched=True,
        )
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: forbidden)

        ctx = _ctx(role='employee')
        result = pipeline.route('帮我删除小王的考勤', ctx)

        assert result.task_template_id == 'forbidden_action_response'
        assert result.requires_confirmation is True
        assert result.route_path == 'fast_path'
        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'fast_path'


# ---------------------------------------------------------------------------
# 2) retrieval 正常路径：组件调用编排
# ---------------------------------------------------------------------------


class TestRetrievalPath:
    def test_full_pipeline_orchestrates_all_components(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FastPath miss → EntityMemory → Retriever → Reranker → ConfidenceGate
        → PermissionGate；每个组件至少被调用一次，最终结果可用。"""

        # FastPath miss
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)

        # EntityMemory：返回原查询（无代词）。
        spy_em = _SpyEntityMemory()
        monkeypatch.setattr(pipeline, '_entity_memory', spy_em)

        # Retriever：返回 3 条候选。
        retrieve_calls: List[str] = []

        def fake_retrieve(query, k=5):  # noqa: ANN001
            retrieve_calls.append(query)
            return RetrievalCandidates(
                items=[
                    ('recent_resume_analysis', 0.85, '最近简历'),
                    ('recruitment_overview', 0.61, '招聘概览'),
                    ('global_search_answer', 0.42, '兜底'),
                ],
                reason=None,
            )

        monkeypatch.setattr(pipeline._retriever, 'retrieve', fake_retrieve)

        # Reranker：返回 task_id ∈ candidates，confidence 高。
        rerank_calls: List[Tuple[str, RetrievalCandidates]] = []

        def fake_rerank(query, candidates, ctx):  # noqa: ANN001
            rerank_calls.append((query, candidates))
            return _retrieval_result(
                task_template_id='recent_resume_analysis',
                confidence=0.88,
                candidate_skills=['resume_analysis', 'recruitment_search'],
                top_k=[
                    ('recent_resume_analysis', 0.85),
                    ('recruitment_overview', 0.61),
                ],
            )

        monkeypatch.setattr(pipeline.reranker, 'rerank', fake_rerank)

        # ConfidenceGate：spy 包装真实 evaluate 以确认被调用。
        gate_calls: List[float] = []
        real_evaluate = pipeline.confidence_gate.evaluate

        def spy_evaluate(router_result, ctx):  # noqa: ANN001
            gate_calls.append(router_result.confidence)
            return real_evaluate(router_result, ctx)

        monkeypatch.setattr(pipeline.confidence_gate, 'evaluate', spy_evaluate)

        # PermissionGate：spy 包装真实 apply 以确认被调用。
        perm_calls: List[str] = []
        real_apply = pipeline.permission_gate.apply

        def spy_apply(router_result, ctx):  # noqa: ANN001
            perm_calls.append(router_result.task_template_id or '')
            return real_apply(router_result, ctx)

        monkeypatch.setattr(pipeline.permission_gate, 'apply', spy_apply)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('最近一周来了几份高分简历', ctx)

        # 1) EntityMemory 被调用一次（带 session_id）。
        assert len(spy_em.resolve_calls) == 1
        assert spy_em.resolve_calls[0][1] == 'sess-1'

        # 2) Retriever 被调用一次。
        assert retrieve_calls == ['最近一周来了几份高分简历']

        # 3) Reranker 被调用一次，候选透传。
        assert len(rerank_calls) == 1
        _, passed_cands = rerank_calls[0]
        assert [t for t, _, _ in passed_cands.items] == [
            'recent_resume_analysis', 'recruitment_overview',
            'global_search_answer',
        ]

        # 4) ConfidenceGate 被调用一次，confidence 来自 Reranker。
        assert gate_calls == [pytest.approx(0.88)]

        # 5) PermissionGate 被调用一次（除 FastPath miss 后；如果走 legacy_fallback
        #    会再调一次，但本路径不应触发）。
        assert perm_calls == ['recent_resume_analysis']

        # 6) 结果合规
        assert result.task_template_id == 'recent_resume_analysis'
        assert result.route_path == 'retrieval'
        assert set(result.candidate_skills).issubset(
            {'resume_analysis', 'recruitment_search'},
        )
        # 候选必须 ⊆ skill_registry
        for sid in result.candidate_skills:
            assert skill_registry.exists(sid)
        # task_id 必须 ∈ task_registry
        assert task_registry.exists(result.task_template_id)

        # 7) Observability 记录一次，route_path='retrieval'，包含 top_k_scores。
        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'retrieval'
        assert spy.calls[0]['chosen_task_id'] == 'recent_resume_analysis'
        # top_k_scores 与 reranker 输出一致。
        assert list(spy.calls[0]['top_k_scores']) == [
            ('recent_resume_analysis', pytest.approx(0.85)),
            ('recruitment_overview', pytest.approx(0.61)),
        ]
        assert spy.calls[0]['clarification_emitted'] is False
        assert spy.calls[0]['entity_resolved_count'] == 0
        # latency_ms 是非负 float
        assert spy.calls[0]['latency_ms'] >= 0.0

    def test_entity_resolved_count_propagated_to_observer(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """EntityMemory 抽取到 1 个代词 → observer 看到
        ``entity_resolved_count == 1``。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)

        spy_em = _SpyEntityMemory(
            resolve_result=(
                '小王 考勤情况',
                {
                    'pronouns_found': ['他'],
                    'substitutions': [
                        {'pronoun': '他', 'replaced_with': '小王',
                         'type': 'employee', 'candidates': ['小王']},
                    ],
                },
            ),
        )
        monkeypatch.setattr(pipeline, '_entity_memory', spy_em)

        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('attendance_exception_analysis', 0.91, '考勤异常')],
            ),
        )
        monkeypatch.setattr(
            pipeline.reranker, 'rerank',
            lambda q, c, ctx: _retrieval_result(
                task_template_id='attendance_exception_analysis',
                confidence=0.91,
                candidate_skills=['attendance_analysis', 'employee_search'],
                top_k=[('attendance_exception_analysis', 0.91)],
            ),
        )

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('他的考勤情况', ctx)

        # entity_resolved trace 应该被附加到 RouterResult 上。
        assert result.entity_resolved.get('pronouns_found') == ['他']

        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['entity_resolved_count'] == 1


# ---------------------------------------------------------------------------
# 3) 嵌入服务不可用 → legacy_fallback
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    def test_embedding_unavailable_routes_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``Retriever.retrieve`` 返回 ``embedding_unavailable`` →
        IntentRouter 调用 LegacyRouter，``route_path='legacy_fallback'``。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(
            pipeline, '_entity_memory', _SpyEntityMemory(),
        )

        # 嵌入服务不可用
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[], reason=REASON_EMBEDDING_UNAVAILABLE,
            ),
        )

        # Reranker 不应被调用
        def boom_rerank(*a, **kw):  # noqa: ANN001
            raise AssertionError('Reranker should not be called on legacy_fallback')

        monkeypatch.setattr(pipeline.reranker, 'rerank', boom_rerank)

        # Patch legacy router 模块的 route()
        legacy_fixture = RouterResult(
            intent='recent_resume_analysis',
            task_template_id='recent_resume_analysis',
            confidence=0.7,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            risk_level=RISK_LOW,
            route_path='unknown',
            rule_matched=True,
        )
        from services.assistant_core import legacy_router as legacy_module
        monkeypatch.setattr(
            legacy_module, 'route', lambda message, ctx: legacy_fixture,
        )

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('最近一周来了几份高分简历', ctx)

        # task_template_id 与 LegacyRouter 一致
        assert result.task_template_id == 'recent_resume_analysis'
        # route_path 强制改为 legacy_fallback
        assert result.route_path == 'legacy_fallback'

        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'legacy_fallback'
        assert spy.calls[0]['chosen_task_id'] == 'recent_resume_analysis'

    def test_legacy_route_still_runs_permission_gate(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy 给出 payroll + employee 角色 → PermissionGate 改写为
        permission_denied_response，但 ``route_path='legacy_fallback'``。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[], reason=REASON_EMBEDDING_UNAVAILABLE,
            ),
        )

        legacy_fixture = RouterResult(
            intent='payroll_month_summary',
            task_template_id='payroll_month_summary',
            confidence=0.85,
            candidate_skills=['payroll_analysis'],
            risk_level=RISK_HIGH,
            route_path='unknown',
            rule_matched=True,
        )
        from services.assistant_core import legacy_router as legacy_module
        monkeypatch.setattr(
            legacy_module, 'route', lambda message, ctx: legacy_fixture,
        )

        ctx = _ctx(role='employee')
        result = pipeline.route('查一下我的工资', ctx)

        assert result.task_template_id == 'permission_denied_response'
        assert result.route_path == 'legacy_fallback'
        assert result.candidate_skills == []
        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'legacy_fallback'

    def test_legacy_exception_yields_fallback(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy 路径抛错 → 顶层兜底返回 ``global_search_answer``，
        ``route_path='legacy_fallback'``。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[], reason=REASON_EMBEDDING_UNAVAILABLE,
            ),
        )

        from services.assistant_core import legacy_router as legacy_module

        def boom(*a, **kw):  # noqa: ANN001
            raise RuntimeError('legacy boom')

        monkeypatch.setattr(legacy_module, 'route', boom)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('xxx', ctx)
        assert result.task_template_id == 'global_search_answer'
        assert result.route_path == 'legacy_fallback'
        assert 'global_search' in result.candidate_skills


# ---------------------------------------------------------------------------
# 4) 未知 task_id → 强制改写 global_search_answer
# ---------------------------------------------------------------------------


class TestUnknownTaskRewrite:
    def test_unknown_task_id_rewritten_to_global_search(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reranker 返回未注册 task_id → IntentRouter 强制改写。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('__no_such_task__', 0.9, 'phantom')],
            ),
        )

        # Reranker 强行返回不在 task_registry 的 id（mock）。
        bogus = _retrieval_result(
            task_template_id='__no_such_task__',
            confidence=0.95,
            candidate_skills=['__no_such_skill__'],  # 也不在 skill_registry
            top_k=[('__no_such_task__', 0.9)],
        )
        monkeypatch.setattr(pipeline.reranker, 'rerank', lambda q, c, ctx: bogus)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('something weird', ctx)

        assert result.task_template_id == 'global_search_answer'
        assert result.intent == 'global_search'
        assert result.candidate_skills == ['global_search']
        # reason 中标注重写来源（与基础 reason 相互保留）。
        assert 'intent_router:rewrote_unknown_task' in (result.reason or '')

    def test_unknown_skills_filtered_even_when_task_known(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """task_id 合法但 candidate_skills 含未注册 id → 防御深度过滤后仅留
        合法 skill。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('recent_resume_analysis', 0.9, 'src')],
            ),
        )

        rr = _retrieval_result(
            task_template_id='recent_resume_analysis',
            confidence=0.9,
            candidate_skills=[
                'resume_analysis', '__bogus__', 'recruitment_search',
            ],
            top_k=[('recent_resume_analysis', 0.9)],
        )
        monkeypatch.setattr(pipeline.reranker, 'rerank', lambda q, c, ctx: rr)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('q', ctx)

        # __bogus__ 必须被过滤掉
        assert '__bogus__' not in result.candidate_skills
        for sid in result.candidate_skills:
            assert skill_registry.exists(sid)


# ---------------------------------------------------------------------------
# 5) PermissionGate 改写顺序生效
# ---------------------------------------------------------------------------


class TestPermissionRewriteOrdering:
    def test_payroll_via_retrieval_path_denied_for_employee(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """retrieval 路径 + Reranker 选 payroll_month_summary +
        ``ctx.role='employee'`` → 最终 ``permission_denied_response``。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('payroll_month_summary', 0.9, '工资条')],
            ),
        )

        rr = _retrieval_result(
            task_template_id='payroll_month_summary',
            confidence=0.9,
            candidate_skills=['payroll_analysis'],
            top_k=[('payroll_month_summary', 0.9)],
            risk_level=RISK_HIGH,
        )
        monkeypatch.setattr(pipeline.reranker, 'rerank', lambda q, c, ctx: rr)

        ctx = _ctx(role='employee')
        result = pipeline.route('查一下我的工资', ctx)

        assert result.task_template_id == 'permission_denied_response'
        assert result.intent == 'permission_denied'
        assert result.risk_level == RISK_HIGH
        assert result.requires_confirmation is False
        assert result.candidate_skills == []

        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['chosen_task_id'] == 'permission_denied_response'

    def test_payroll_via_retrieval_path_kept_for_hr_admin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """对照组：``hr_admin`` 在同一查询下保留薪酬路径，强制确认。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('payroll_month_summary', 0.9, '工资条')],
            ),
        )

        rr = _retrieval_result(
            task_template_id='payroll_month_summary',
            confidence=0.9,
            candidate_skills=['payroll_analysis'],
            top_k=[('payroll_month_summary', 0.9)],
            risk_level=RISK_HIGH,
        )
        monkeypatch.setattr(pipeline.reranker, 'rerank', lambda q, c, ctx: rr)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('查一下小王的本月薪资', ctx)

        assert result.task_template_id == 'payroll_month_summary'
        assert result.risk_level == RISK_HIGH
        assert result.requires_confirmation is True
        assert 'payroll_analysis' in result.candidate_skills


# ---------------------------------------------------------------------------
# 6) 异常防御：内部组件抛错 → 兜底 RouterResult
# ---------------------------------------------------------------------------


class TestExceptionDefense:
    def test_reranker_exception_yields_fallback(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('recent_resume_analysis', 0.9, 'src')],
            ),
        )

        def boom(*a, **kw):  # noqa: ANN001
            raise RuntimeError('rerank boom')

        monkeypatch.setattr(pipeline.reranker, 'rerank', boom)

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('q', ctx)
        # 异常被吞掉 → 兜底 global_search_answer，route_path='fallback'
        assert result.task_template_id == 'global_search_answer'
        assert result.route_path == 'fallback'
        assert 'reranker_exception' in (result.reason or '')

        spy: _SpyObserver = pipeline._observer
        assert len(spy.calls) == 1
        assert spy.calls[0]['route_path'] == 'fallback'

    def test_observer_exception_does_not_break_route(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ObservabilityRecorder 抛错时主路径仍正常返回结果。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        monkeypatch.setattr(pipeline, '_entity_memory', _SpyEntityMemory())
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('recent_resume_analysis', 0.9, 'src')],
            ),
        )
        monkeypatch.setattr(
            pipeline.reranker, 'rerank',
            lambda q, c, ctx: _retrieval_result(
                task_template_id='recent_resume_analysis',
                confidence=0.9,
                candidate_skills=['resume_analysis'],
                top_k=[('recent_resume_analysis', 0.9)],
            ),
        )

        class ExplodingObserver:
            def record(self, **kwargs: Any) -> None:
                raise RuntimeError('obs boom')

        monkeypatch.setattr(pipeline, '_observer', ExplodingObserver())

        ctx = _ctx(role='hr_admin')
        result = pipeline.route('q', ctx)
        # 主路径保留正常输出
        assert result.task_template_id == 'recent_resume_analysis'


# ---------------------------------------------------------------------------
# 7) task_registry reload listener 集成
# ---------------------------------------------------------------------------


class TestTaskRegistryReloadIntegration:
    def test_reload_listener_is_registered(self) -> None:
        """``intent_router._on_task_registry_reload`` 应当在 import 时被注册到
        ``task_registry`` 的 reload 监听器列表上。"""

        listeners = task_registry._list_reload_listeners()
        assert pipeline._on_task_registry_reload in listeners

    def test_reload_invokes_index_reload(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``task_registry.reload_registry()`` 应当触发监听器，监听器调用
        ``RetrievalIndex.reload``（被 spy 起来观察）。"""

        spy_calls: List[Tuple[Any, Any]] = []

        def spy_reload(reg, embed):  # noqa: ANN001
            spy_calls.append((reg, embed))
            return 0

        monkeypatch.setattr(pipeline._retrieval_index, 'reload', spy_reload)
        # 触发一次 reload。
        task_registry.reload_registry()
        # 监听器至少被调用一次（reload_registry 触发监听器，监听器再调
        # _retrieval_index.reload）。
        assert spy_calls, 'expected RetrievalIndex.reload to be called'
        registry_arg, embed_arg = spy_calls[-1]
        # 传入的是 task_registry 模块本身与 facade 实例。
        assert registry_arg is task_registry
        assert isinstance(embed_arg, pipeline._EmbeddingClientFacade)
