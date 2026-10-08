"""Task 13.1 —— LegacyAdapter + routing dispatch + orchestrator log tests.

Validates: Requirements 8.1, 8.2, 8.3, 8.5, 12.4

Coverage map:

* ``test_legacy_adapter_*``：``legacy_adapter.legacy_route(message, ctx)``
  调用 ``services.assistant_core.legacy_router.route``，并把缺失的 v2 字段填齐
  （``route_path='legacy'``、``top_k=[]``、``clarification_options=[]``、
  ``low_confidence_warning=False``、``entity_resolved={}``）。返回的
  ``RouterResult`` 字段集合是 legacy router 输出字段集合的超集。
* ``test_routing_*``：FeatureFlag 关闭时 ``routing.route`` → 走
  ``legacy_adapter``；开启 + ``rollout_pct=100`` 时走 ``intent_pipeline.route``。
  parity：FeatureFlag 关闭时输出在 v1 字段（``task_template_id`` / ``intent``
  / ``confidence`` / ``risk_level`` / ``candidate_skills`` /
  ``requires_confirmation`` / ``entities``）上等于 ``router.route`` 的输出。
* ``test_orchestrator_log_*``：mock ``executor.execute`` /
  ``memory.save_turn`` / ``query_cache``，捕获 ``assistant_query_done`` 日志，
  断言 ``extra`` 中包含 ``routePath``、``topK``、``latencyMs``。
"""

from __future__ import annotations

import logging
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

from services.assistant_core import legacy_orchestrator as orchestrator, legacy_router  # noqa: E402
from services.assistant_core.constants import RISK_LOW  # noqa: E402
from services.assistant_core.intent_router import (  # noqa: E402
    feature_flag,
    legacy_adapter,
    legacy_routing as routing,
)
from services.assistant_core.intent_router import legacy_pipeline as intent_pipeline  # noqa: E402
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    ExecutionResult,
    RouterResult,
)


# ---------------------------------------------------------------------------
# 共享 fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_feature_flag(monkeypatch):
    """每个测试都从干净的 FeatureFlag 状态开始。"""

    monkeypatch.delenv('ASSISTANT_INTENT_ROUTER_V2_ENABLED', raising=False)
    monkeypatch.delenv('ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT', raising=False)
    feature_flag.reload()
    yield
    feature_flag.reload()


def _ctx(role: str = 'hr_admin', user_id: str = 'user-legacy-test', **kw: Any) -> AssistantContext:
    return AssistantContext(
        user_id=user_id,
        role=role,
        session_id=kw.pop('session_id', 'sess-legacy-1'),
        history=kw.pop('history', []),
        request_id=kw.pop('request_id', 'req-legacy-1'),
        **kw,
    )


def _legacy_fixture() -> RouterResult:
    """模拟 legacy router 的典型返回（v1 字段就齐了）。

    构造时不设任何 v2 字段，让 ``RouterResult`` 用 dataclass 默认值，验证
    适配器把这些默认值统一成具体值（``route_path='legacy'`` 等）。
    """

    return RouterResult(
        intent='employee_lookup',
        task_template_id='employee_lookup',
        confidence=0.6,
        entities={'keyword': 'kw'},
        missing_fields=[],
        risk_level=RISK_LOW,
        candidate_skills=['employee_search', 'organization_search'],
        requires_confirmation=False,
        clarification_question=None,
        reason='查询动词 + 关键词',
        rule_matched=True,
        forbidden_reason=None,
    )


def _v1_field_view(r: RouterResult) -> Dict[str, Any]:
    """提取 v1 字段子集，方便 parity 比较。"""

    return {
        'intent': r.intent,
        'task_template_id': r.task_template_id,
        'confidence': r.confidence,
        'entities': r.entities,
        'missing_fields': r.missing_fields,
        'risk_level': r.risk_level,
        'candidate_skills': r.candidate_skills,
        'requires_confirmation': r.requires_confirmation,
        'clarification_question': r.clarification_question,
        'reason': r.reason,
        'rule_matched': r.rule_matched,
        'forbidden_reason': r.forbidden_reason,
    }


# ---------------------------------------------------------------------------
# 1) LegacyAdapter
# ---------------------------------------------------------------------------


class TestLegacyAdapter:
    def test_calls_legacy_route_with_same_args(self, monkeypatch):
        """``legacy_adapter.legacy_route`` 必须调用 ``legacy_router.route(message, ctx)``。"""

        captured: List[Tuple[str, AssistantContext]] = []

        def fake_route(message, ctx):
            captured.append((message, ctx))
            return _legacy_fixture()

        monkeypatch.setattr(legacy_router, 'route', fake_route)

        ctx = _ctx()
        result = legacy_adapter.legacy_route('查一下小王', ctx)

        assert len(captured) == 1
        assert captured[0][0] == '查一下小王'
        assert captured[0][1] is ctx
        assert isinstance(result, RouterResult)

    def test_v2_fields_filled_with_safe_defaults(self, monkeypatch):
        """没有 v2 字段时，适配器应填上 ``route_path='legacy'`` 等具体值。"""

        monkeypatch.setattr(legacy_router, 'route', lambda m, c: _legacy_fixture())

        out = legacy_adapter.legacy_route('查一下小王', _ctx())

        assert out.route_path == 'legacy'
        assert out.top_k == []
        assert out.clarification_options == []
        assert out.low_confidence_warning is False
        assert out.entity_resolved == {}

    def test_v1_fields_preserved_verbatim(self, monkeypatch):
        """适配器不能改写 legacy 的 v1 业务字段。"""

        legacy = _legacy_fixture()
        monkeypatch.setattr(legacy_router, 'route', lambda m, c: legacy)

        out = legacy_adapter.legacy_route('查一下小王', _ctx())

        assert _v1_field_view(out) == _v1_field_view(legacy)

    def test_field_set_is_v2_superset(self, monkeypatch):
        """``to_dict()`` 输出应当是 v2 字段超集（v1 + v2 全部具体可见）。"""

        monkeypatch.setattr(legacy_router, 'route', lambda m, c: _legacy_fixture())
        out = legacy_adapter.legacy_route('q', _ctx())

        d = out.to_dict()
        # v1 字段都在
        for key in (
            'intent', 'taskTemplateId', 'confidence', 'entities',
            'missingFields', 'riskLevel', 'candidateSkills',
            'requiresConfirmation', 'clarificationQuestion', 'reason',
            'ruleMatched', 'forbiddenReason',
        ):
            assert key in d, f'missing v1 key {key!r}'
        # v2 字段也都在
        for key in (
            'routePath', 'topK', 'clarificationOptions',
            'lowConfidenceWarning', 'entityResolved',
        ):
            assert key in d, f'missing v2 key {key!r}'

    def test_does_not_alias_legacy_collections(self, monkeypatch):
        """适配器返回的 collection 应该是 legacy 输出的拷贝，避免别名共享。"""

        legacy = _legacy_fixture()
        # 故意预填一些 v2 字段，看适配器是否拷贝
        legacy.top_k = [('foo', 0.1)]
        legacy.clarification_options = [{'label': 'L', 'payload': 'P'}]
        legacy.entity_resolved = {'a': 1}
        monkeypatch.setattr(legacy_router, 'route', lambda m, c: legacy)

        out = legacy_adapter.legacy_route('q', _ctx())

        # 内容相等
        assert out.top_k == [('foo', 0.1)]
        assert out.clarification_options == [{'label': 'L', 'payload': 'P'}]
        assert out.entity_resolved == {'a': 1}
        # 但不同对象（不共享引用）
        assert out.top_k is not legacy.top_k
        assert out.clarification_options is not legacy.clarification_options
        assert out.entity_resolved is not legacy.entity_resolved

    def test_legacy_exception_returns_safe_fallback(self, monkeypatch):
        """legacy router 抛错 → 适配器返回兜底 RouterResult，不抛出。"""

        def boom(m, c):
            raise RuntimeError('legacy boom')

        monkeypatch.setattr(legacy_router, 'route', boom)

        out = legacy_adapter.legacy_route('q', _ctx())
        assert isinstance(out, RouterResult)
        assert out.route_path == 'legacy'
        assert 'legacy_adapter' in (out.reason or '')

    def test_legacy_returns_none_returns_safe_fallback(self, monkeypatch):
        monkeypatch.setattr(legacy_router, 'route', lambda m, c: None)

        out = legacy_adapter.legacy_route('q', _ctx())
        assert isinstance(out, RouterResult)
        assert out.route_path == 'legacy'


# ---------------------------------------------------------------------------
# 2) routing.route dispatcher
# ---------------------------------------------------------------------------


class TestRoutingDispatcher:
    def test_feature_flag_off_uses_legacy_adapter(self, monkeypatch):
        """FeatureFlag 关闭 → 走 ``legacy_adapter.legacy_route``。"""

        # 默认 fixture 已 unset env，feature_flag = False。
        legacy_calls: List[Tuple[str, AssistantContext]] = []

        def fake_legacy(message, ctx):
            legacy_calls.append((message, ctx))
            fx = _legacy_fixture()
            # 适配器在真实路径下会填 route_path='legacy'，这里直接给。
            fx.route_path = 'legacy'
            return fx

        monkeypatch.setattr(legacy_adapter, 'legacy_route', fake_legacy)

        # pipeline.route 不应被调用
        def boom(*a, **kw):
            raise AssertionError('intent_pipeline.route should not be called')

        monkeypatch.setattr(intent_pipeline, 'route', boom)

        ctx = _ctx()
        result = routing.route('查一下小王', ctx)

        assert len(legacy_calls) == 1
        assert result.route_path == 'legacy'
        assert result.task_template_id == 'employee_lookup'

    def test_feature_flag_on_full_rollout_uses_pipeline(self, monkeypatch):
        """FeatureFlag 开启 + ``rollout_pct=100`` → 走 ``intent_pipeline.route``。"""

        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_V2_ENABLED', 'true')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT', '100')
        feature_flag.reload()

        pipeline_calls: List[Tuple[str, AssistantContext]] = []

        def fake_pipeline(message, ctx):
            pipeline_calls.append((message, ctx))
            return RouterResult(
                intent='global_search',
                task_template_id='global_search_answer',
                confidence=0.9,
                candidate_skills=['global_search'],
                route_path='retrieval',
            )

        monkeypatch.setattr(intent_pipeline, 'route', fake_pipeline)

        # 适配器不应被调到
        def boom(*a, **kw):
            raise AssertionError('legacy_adapter.legacy_route should not be called')

        monkeypatch.setattr(legacy_adapter, 'legacy_route', boom)

        result = routing.route('xxx', _ctx())
        assert len(pipeline_calls) == 1
        assert result.route_path == 'retrieval'
        assert result.task_template_id == 'global_search_answer'

    def test_parity_with_legacy_when_flag_off(self, monkeypatch):
        """FeatureFlag 关闭时 ``routing.route`` 在 v1 字段上等于 ``router.route``。

        ``route_path`` 的差异是预期变化（legacy 默认 ``'unknown'``，适配器后
        统一改为 ``'legacy'``），不属于 parity 范畴。
        """

        legacy = _legacy_fixture()
        monkeypatch.setattr(legacy_router, 'route', lambda m, c: legacy)

        ctx = _ctx()
        out = routing.route('查一下小王', ctx)
        direct = legacy_router.route('查一下小王', ctx)

        assert _v1_field_view(out) == _v1_field_view(direct)
        # Adapter 把 route_path 统一为 'legacy'，与 legacy 的默认 'unknown' 区分开。
        assert out.route_path == 'legacy'

    def test_pipeline_exception_falls_back_to_legacy(self, monkeypatch):
        """v2 pipeline 顶层抛错 → routing 退到 ``legacy_adapter.legacy_route``。"""

        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_V2_ENABLED', 'true')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT', '100')
        feature_flag.reload()

        def boom(*a, **kw):
            raise RuntimeError('pipeline died')

        monkeypatch.setattr(intent_pipeline, 'route', boom)
        monkeypatch.setattr(legacy_router, 'route', lambda m, c: _legacy_fixture())

        out = routing.route('q', _ctx())
        assert out.route_path == 'legacy'
        assert out.task_template_id == 'employee_lookup'

    def test_legacy_fallback_when_user_id_missing(self, monkeypatch):
        """``ctx.user_id`` 为空时 FeatureFlag 不会启用 v2，走 legacy。"""

        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_V2_ENABLED', 'true')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT', '100')
        feature_flag.reload()

        legacy_calls: List[Any] = []

        def fake_legacy(m, c):
            legacy_calls.append((m, c))
            return _legacy_fixture()

        monkeypatch.setattr(legacy_adapter, 'legacy_route', fake_legacy)

        def boom(*a, **kw):
            raise AssertionError('pipeline should not be called when user_id missing')

        monkeypatch.setattr(intent_pipeline, 'route', boom)

        ctx = _ctx(user_id='')
        routing.route('q', ctx)
        assert len(legacy_calls) == 1


# ---------------------------------------------------------------------------
# 3) Orchestrator structured log includes routePath / topK / latencyMs
# ---------------------------------------------------------------------------


class _StubExecutionResult(ExecutionResult):
    """thin wrapper to allow setting _perf without warnings."""


@pytest.fixture
def _orchestrator_isolated(monkeypatch):
    """Patch executor / memory / cache so orchestrator.run can be exercised
    deterministically without DB or skill execution."""

    # No cache hits.
    from services.assistant_core import cache as cache_mod

    class _NullCache:
        def get(self, *a, **kw):
            return None

        def put(self, *a, **kw):
            return None

    monkeypatch.setattr(cache_mod, 'query_cache', _NullCache(), raising=True)
    monkeypatch.setattr(orchestrator, 'query_cache', _NullCache(), raising=True)

    def fake_save_turn(**kwargs):
        return kwargs.get('session_id') or 'sess-saved'

    monkeypatch.setattr(orchestrator.memory, 'save_turn', fake_save_turn)
    yield


def _build_router_result(*, route_path: str, top_k: List[Tuple[str, float]]) -> RouterResult:
    return RouterResult(
        intent='employee_lookup',
        task_template_id='employee_lookup',
        confidence=0.7,
        entities={'keyword': 'kw'},
        missing_fields=[],
        risk_level=RISK_LOW,
        candidate_skills=['employee_search'],
        requires_confirmation=False,
        clarification_question=None,
        reason='unit-test',
        rule_matched=True,
        forbidden_reason=None,
        route_path=route_path,
        top_k=list(top_k),
    )


class TestOrchestratorLogging:
    def test_log_extra_includes_route_path_top_k_latency(
        self, monkeypatch, caplog, _orchestrator_isolated,
    ):
        """``assistant_query_done`` extra 必须包含 routePath / topK / latencyMs。"""

        rr = _build_router_result(
            route_path='retrieval',
            top_k=[('employee_lookup', 0.91), ('global_search_answer', 0.42)],
        )

        monkeypatch.setattr(orchestrator.routing, 'route', lambda m, c: rr)

        def fake_execute(message, router_result, ctx):
            res = ExecutionResult(
                summary='ok',
                entities=[],
                widgets=[],
                session_id=ctx.session_id,
                trace=[],
                router=router_result,
                fallback_used=False,
            )
            return res

        monkeypatch.setattr(orchestrator.executor, 'execute', fake_execute)

        ctx = _ctx()
        with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
            orchestrator.run('查一下小王', ctx)

        records = [r for r in caplog.records if r.message == 'assistant_query_done']
        assert len(records) == 1, f'unexpected log records: {[r.message for r in caplog.records]}'
        rec = records[0]

        # routePath
        assert getattr(rec, 'routePath') == 'retrieval'

        # topK 是序列化后的列表（每项 [task_id, score]）
        top_k_logged = getattr(rec, 'topK')
        assert isinstance(top_k_logged, list)
        assert top_k_logged == [
            ['employee_lookup', pytest.approx(0.91)],
            ['global_search_answer', pytest.approx(0.42)],
        ]

        # latencyMs 是非负浮点数
        latency = getattr(rec, 'latencyMs')
        assert isinstance(latency, (int, float))
        assert latency >= 0.0

    def test_log_route_path_legacy_when_flag_off(
        self, monkeypatch, caplog, _orchestrator_isolated,
    ):
        """FeatureFlag 关闭时，结构化日志的 ``routePath`` 应为 ``'legacy'``。"""

        monkeypatch.setattr(legacy_router, 'route', lambda m, c: _legacy_fixture())

        def fake_execute(message, router_result, ctx):
            return ExecutionResult(
                summary='ok',
                session_id=ctx.session_id,
                router=router_result,
            )

        monkeypatch.setattr(orchestrator.executor, 'execute', fake_execute)

        ctx = _ctx()
        with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
            orchestrator.run('查一下小王', ctx)

        records = [r for r in caplog.records if r.message == 'assistant_query_done']
        assert len(records) == 1
        rec = records[0]
        assert getattr(rec, 'routePath') == 'legacy'
        # 当 legacy adapter 没产生 top_k 时也必须记录空列表（不是 None）。
        assert getattr(rec, 'topK') == []
        assert getattr(rec, 'latencyMs') >= 0.0

