"""Task 15.1 —— FallbackSampleSink wiring 单元测试。

校验目标（Validates: Requirements 6.4, 11.1, 11.2, 11.3, 11.4）：

* **低置信度路径写样本**：mock pipeline 子组件让 ``RouterResult.confidence
  < low_threshold``（默认 0.50）→ ``FallbackSampleSink.write`` 恰好被调用
  一次，参数包含 ``query_hash``（``sha256_16``）、``role``、
  ``top_k_task_ids``、``top_k_scores``、``chosen_task_id``、``timestamp``；
  *不* 包含原始 ``message`` / ``user_id`` / ``session_id``。
* **fallback / legacy_fallback 路径也写**：``route_path='fallback'`` /
  ``'legacy_fallback'`` 触发 sink，即使 confidence 高于阈值。
* **高置信度且非 fallback 路径不写**：``confidence > low_threshold`` 且
  ``route_path='retrieval'`` → sink 不被调用。
* **写失败不阻塞主请求**：让 ``sink.write`` 抛任意异常 →
  ``pipeline.route`` 仍正常返回 ``RouterResult``，主路径无异常逃出。
* **FeatureFlag 关闭路径**：``legacy_adapter.legacy_route`` 也调同款 sink，
  传入同样的脱敏字段集合。
* **防御深度**：sink 不接受消息原文 / ``user_id`` / ``session_id``；用 spy
  断言所有调用参数都不含原文片段。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

# Ensure backend-python is on sys.path so we can import via 'services.*'.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core import skill_registry, task_registry  # noqa: E402
from services.assistant_core.constants import RISK_HIGH, RISK_LOW  # noqa: E402
from services.assistant_core.intent_router import (  # noqa: E402
    legacy_pipeline as pipeline,
    legacy_adapter,
)
from services.assistant_core.intent_router.observability import (  # noqa: E402
    sha256_16,
)
from services.assistant_core.intent_router.retriever import (  # noqa: E402
    REASON_EMBEDDING_UNAVAILABLE,
    RetrievalCandidates,
)
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    RouterResult,
)


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_lazy_index_build(monkeypatch: pytest.MonkeyPatch):
    """禁掉懒构建路径，避免测试期触发真实嵌入调用。"""

    monkeypatch.setattr(pipeline, '_index_build_attempted', True, raising=False)
    monkeypatch.setattr(
        pipeline._retrieval_index, 'is_empty', lambda: False, raising=False,
    )
    yield


@pytest.fixture
def sink_spy(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """把 ``pipeline._fallback_sink`` 替换为 spy。

    返回 spy 对象（一个 MagicMock，``.write`` 默认返回 True）；同时
    顺手禁掉 observer 的副作用，让测试只关注 sink 调用。
    """

    spy = MagicMock(name='FallbackSampleSinkSpy')
    spy.write.return_value = True
    monkeypatch.setattr(pipeline, '_fallback_sink', spy)

    # 禁掉 observer 的实际写日志路径，避免 caplog/计数器干扰。
    silent_observer = MagicMock(name='SilentObserver')
    silent_observer.record.return_value = None
    monkeypatch.setattr(pipeline, '_observer', silent_observer)
    yield spy


def _ctx(role: str = 'hr_admin', **kw: Any) -> AssistantContext:
    return AssistantContext(
        user_id=kw.pop('user_id', 'sensitive-user-id-12345'),
        role=role,
        session_id=kw.pop('session_id', 'sensitive-session-67890'),
        history=kw.pop('history', []),
        request_id=kw.pop('request_id', 'req-1'),
        **kw,
    )


def _retrieval_result(
    *,
    task_template_id: str,
    confidence: float,
    candidate_skills: List[str],
    top_k: Optional[List[Tuple[str, float]]] = None,
    risk_level: str = RISK_LOW,
    route_path: str = 'retrieval',
) -> RouterResult:
    return RouterResult(
        intent=task_template_id,
        task_template_id=task_template_id,
        confidence=confidence,
        candidate_skills=list(candidate_skills),
        risk_level=risk_level,
        route_path=route_path,
        top_k=list(top_k or [(task_template_id, confidence)]),
    )


def _patch_pipeline_minimal(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rerank_result: RouterResult,
    candidates: Optional[RetrievalCandidates] = None,
) -> None:
    """让 ``pipeline.route`` 走 retrieval 路径，但不依赖真实嵌入 / LLM。

    具体打桩：

    * ``fastpath.match`` → ``None``（FastPath miss）
    * ``_entity_memory.resolve`` → 返回原查询，无代词
    * ``_retriever.retrieve`` → 单条候选（与 ``rerank_result.task_template_id``
      一致）
    * ``reranker.rerank`` → ``rerank_result``
    * ``confidence_gate.evaluate`` / ``permission_gate.apply`` 走真实实现
    """

    monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)

    em_spy = MagicMock(name='EntityMemorySpy')
    em_spy.resolve.return_value = (None, {'pronouns_found': [], 'substitutions': []})
    em_spy.resolve.side_effect = lambda q, sid, ctx=None: (
        q, {'pronouns_found': [], 'substitutions': []},
    )
    monkeypatch.setattr(pipeline, '_entity_memory', em_spy)

    if candidates is None:
        candidates = RetrievalCandidates(
            items=[
                (
                    rerank_result.task_template_id or 'global_search_answer',
                    float(rerank_result.confidence),
                    'src',
                ),
            ],
        )
    monkeypatch.setattr(
        pipeline._retriever, 'retrieve', lambda q, k=5: candidates,
    )
    monkeypatch.setattr(
        pipeline.reranker, 'rerank', lambda q, c, ctx: rerank_result,
    )


# ---------------------------------------------------------------------------
# 1) Low-confidence sample is written
# ---------------------------------------------------------------------------


class TestLowConfidenceWritesSample:
    def test_low_confidence_triggers_sink_with_sanitized_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """confidence=0.30 (< default 0.50) → sink.write 被调一次，含脱敏字段。"""

        # ConfidenceGate 走真实实现 → confidence 0.30 < low_threshold → 把
        # route_path 改写为 'fallback'。Reranker 把候选锁在合法 task。
        rr = _retrieval_result(
            task_template_id='recent_resume_analysis',
            confidence=0.30,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            top_k=[
                ('recent_resume_analysis', 0.30),
                ('recruitment_overview', 0.21),
            ],
        )
        _patch_pipeline_minimal(monkeypatch, rerank_result=rr)

        ctx = _ctx(role='hr_admin')
        message = '小王最近的工作内容机密原文'
        result = pipeline.route(message, ctx)

        # 主路径仍正常返回
        assert result.task_template_id == 'recent_resume_analysis'
        # ConfidenceGate 把 route_path 改成 fallback
        assert result.route_path == 'fallback'

        # sink.write 恰好被调用一次
        assert sink_spy.write.call_count == 1
        kwargs = sink_spy.write.call_args.kwargs
        # 关键脱敏字段都在
        assert kwargs['query_hash'] == sha256_16(message)
        assert len(kwargs['query_hash']) == 16
        assert kwargs['role'] == 'hr_admin'
        assert kwargs['top_k_task_ids'] == [
            'recent_resume_analysis', 'recruitment_overview',
        ]
        assert kwargs['top_k_scores'] == [pytest.approx(0.30), pytest.approx(0.21)]
        assert kwargs['chosen_task_id'] == 'recent_resume_analysis'
        assert isinstance(kwargs['timestamp'], float)
        assert kwargs['timestamp'] > 0

        # *不能* 出现原文 / 用户标识 / 会话 ID
        for key, value in kwargs.items():
            value_str = str(value)
            assert '小王' not in value_str, (
                f'plaintext leaked via sink kwarg {key!r}={value!r}'
            )
            assert '机密原文' not in value_str
            assert 'sensitive-user-id-12345' not in value_str
            assert 'sensitive-session-67890' not in value_str

        # 也不应通过 positional args 泄漏
        assert sink_spy.write.call_args.args == ()

    def test_low_confidence_threshold_respects_env_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """通过环境变量调高 low_threshold 后，0.60 也会触发 sink。"""

        from services.assistant_core.intent_router import confidence_gate

        monkeypatch.setenv(
            'ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', '0.70',
        )
        confidence_gate.reload()

        try:
            rr = _retrieval_result(
                task_template_id='recent_resume_analysis',
                confidence=0.60,
                candidate_skills=['resume_analysis', 'recruitment_search'],
                top_k=[('recent_resume_analysis', 0.60)],
            )
            _patch_pipeline_minimal(monkeypatch, rerank_result=rr)

            pipeline.route('q', _ctx())
            assert sink_spy.write.call_count == 1
        finally:
            # 重置阈值，避免污染其他用例
            monkeypatch.delenv(
                'ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', raising=False,
            )
            confidence_gate.reload()


# ---------------------------------------------------------------------------
# 2) fallback / legacy_fallback paths trigger sink
# ---------------------------------------------------------------------------


class TestFallbackPathsWriteSample:
    def test_fallback_route_path_writes_sample(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """``route_path='fallback'`` 即使 confidence 高也写样本。"""

        # 让 reranker 抛错，pipeline 顶层兜底 → route_path='fallback'
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        em_spy = MagicMock()
        em_spy.resolve.side_effect = lambda q, sid, ctx=None: (
            q, {'pronouns_found': [], 'substitutions': []},
        )
        monkeypatch.setattr(pipeline, '_entity_memory', em_spy)
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[('recent_resume_analysis', 0.9, 'src')],
            ),
        )

        def boom(*a, **kw):  # noqa: ANN001
            raise RuntimeError('rerank boom')

        monkeypatch.setattr(pipeline.reranker, 'rerank', boom)

        result = pipeline.route('q', _ctx())
        assert result.route_path == 'fallback'
        # sink 必须被触发：route_path in fallback set
        assert sink_spy.write.call_count == 1
        kwargs = sink_spy.write.call_args.kwargs
        assert kwargs['chosen_task_id'] == 'global_search_answer'

    def test_legacy_fallback_route_path_writes_sample(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """嵌入服务不可用 → ``route_path='legacy_fallback'`` 触发 sink。"""

        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: None)
        em_spy = MagicMock()
        em_spy.resolve.side_effect = lambda q, sid, ctx=None: (
            q, {'pronouns_found': [], 'substitutions': []},
        )
        monkeypatch.setattr(pipeline, '_entity_memory', em_spy)
        monkeypatch.setattr(
            pipeline._retriever, 'retrieve',
            lambda q, k=5: RetrievalCandidates(
                items=[], reason=REASON_EMBEDDING_UNAVAILABLE,
            ),
        )

        legacy_fixture = RouterResult(
            intent='recent_resume_analysis',
            task_template_id='recent_resume_analysis',
            confidence=0.9,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            risk_level=RISK_LOW,
            route_path='unknown',
            rule_matched=True,
        )
        from services.assistant_core import legacy_router as legacy_module
        monkeypatch.setattr(
            legacy_module, 'route', lambda message, ctx: legacy_fixture,
        )

        result = pipeline.route('q', _ctx())
        assert result.route_path == 'legacy_fallback'
        # 高 confidence 也写：触发条件是 route_path in fallback set
        assert sink_spy.write.call_count == 1
        kwargs = sink_spy.write.call_args.kwargs
        assert kwargs['chosen_task_id'] == 'recent_resume_analysis'
        assert kwargs['role'] == 'hr_admin'


# ---------------------------------------------------------------------------
# 3) High-confidence non-fallback paths do NOT write
# ---------------------------------------------------------------------------


class TestHighConfidenceDoesNotWrite:
    def test_high_confidence_retrieval_does_not_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """``confidence=0.90 > 0.75`` + retrieval 路径 → sink 不被调用。"""

        rr = _retrieval_result(
            task_template_id='recent_resume_analysis',
            confidence=0.90,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            top_k=[('recent_resume_analysis', 0.90)],
        )
        _patch_pipeline_minimal(monkeypatch, rerank_result=rr)

        result = pipeline.route('q', _ctx())
        assert result.task_template_id == 'recent_resume_analysis'
        assert result.route_path == 'retrieval'
        sink_spy.write.assert_not_called()

    def test_fastpath_high_risk_does_not_write_when_confidence_high(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """FastPath 命中（confidence=0.95，route_path='fast_path'）→ 不写。"""

        fp_hit = RouterResult(
            intent='payroll_month_summary',
            task_template_id='payroll_month_summary',
            confidence=0.95,
            entities={'matched_keyword': '工资条'},
            risk_level=RISK_HIGH,
            candidate_skills=['payroll_analysis'],
            requires_confirmation=False,
            reason='fastpath:payroll:工资条',
            rule_matched=True,
            route_path='fast_path',
        )
        monkeypatch.setattr(pipeline.fastpath, 'match', lambda m, c: fp_hit)

        result = pipeline.route('查一下小王本月工资条', _ctx(role='hr_admin'))
        assert result.route_path == 'fast_path'
        sink_spy.write.assert_not_called()


# ---------------------------------------------------------------------------
# 4) Sink failure does not block main request
# ---------------------------------------------------------------------------


class TestSinkFailureIsSwallowed:
    def test_sink_write_exception_does_not_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """``sink.write`` 抛任意异常 → ``route()`` 仍返回正常 RouterResult。"""

        sink_spy.write.side_effect = RuntimeError('disk full')

        rr = _retrieval_result(
            task_template_id='recent_resume_analysis',
            confidence=0.20,  # 低置信度，必触发 sink
            candidate_skills=['resume_analysis', 'recruitment_search'],
            top_k=[('recent_resume_analysis', 0.20)],
        )
        _patch_pipeline_minimal(monkeypatch, rerank_result=rr)

        # 关键：调用本身不能抛
        result = pipeline.route('q', _ctx())

        # 主路径仍然给出有意义的 RouterResult
        assert result.task_template_id == 'recent_resume_analysis'
        assert result.route_path == 'fallback'
        # sink 确实被尝试调用了一次（虽然失败）
        assert sink_spy.write.call_count == 1


# ---------------------------------------------------------------------------
# 5) FeatureFlag-off (legacy adapter) path also writes
# ---------------------------------------------------------------------------


class TestLegacyAdapterAlsoWrites:
    def test_legacy_adapter_route_invokes_sink(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """``legacy_adapter.legacy_route`` 末尾会调用同一个 sink。"""

        legacy_fixture = RouterResult(
            intent='recent_resume_analysis',
            task_template_id='recent_resume_analysis',
            confidence=0.85,
            candidate_skills=['resume_analysis', 'recruitment_search'],
            risk_level=RISK_LOW,
            route_path='unknown',
            rule_matched=True,
        )
        from services.assistant_core import legacy_router as legacy_module
        monkeypatch.setattr(
            legacy_module, 'route', lambda message, ctx: legacy_fixture,
        )

        message = '小王最近的工作概览'
        result = legacy_adapter.legacy_route(message, _ctx(role='hr_admin'))

        # legacy_adapter 强制 route_path='legacy'
        assert result.route_path == 'legacy'
        # legacy 路径同样应触发 sink（FeatureFlag 关闭时的对照采样）
        assert sink_spy.write.call_count == 1
        kwargs = sink_spy.write.call_args.kwargs
        # 字段集合与 v2 路径一致（query_hash / role / top_k_* / chosen_task_id / timestamp）
        assert set(kwargs.keys()) == {
            'query_hash', 'role',
            'top_k_task_ids', 'top_k_scores',
            'chosen_task_id', 'timestamp',
        }
        assert kwargs['query_hash'] == sha256_16(message)
        assert kwargs['role'] == 'hr_admin'
        assert kwargs['chosen_task_id'] == 'recent_resume_analysis'
        # 不带 top_k：legacy 路径没召回分数
        assert kwargs['top_k_task_ids'] == []
        assert kwargs['top_k_scores'] == []
        # 同样不能泄漏原文 / 用户标识
        for value in kwargs.values():
            value_str = str(value)
            assert '小王' not in value_str
            assert 'sensitive-user-id-12345' not in value_str
            assert 'sensitive-session-67890' not in value_str

    def test_legacy_adapter_swallows_sink_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """legacy 路径的 sink 失败也不能阻塞返回。"""

        sink_spy.write.side_effect = RuntimeError('disk full')

        legacy_fixture = RouterResult(
            intent='recent_resume_analysis',
            task_template_id='recent_resume_analysis',
            confidence=0.4,  # 低置信度也写
            candidate_skills=['resume_analysis'],
            risk_level=RISK_LOW,
            route_path='unknown',
        )
        from services.assistant_core import legacy_router as legacy_module
        monkeypatch.setattr(
            legacy_module, 'route', lambda message, ctx: legacy_fixture,
        )

        result = legacy_adapter.legacy_route('q', _ctx())
        # 仍然得到正常的 v2 超集 RouterResult
        assert result.task_template_id == 'recent_resume_analysis'
        assert result.route_path == 'legacy'
        # sink 被尝试调用过
        assert sink_spy.write.call_count == 1


# ---------------------------------------------------------------------------
# 6) Defense in depth: sink kwargs never contain plaintext / user_id
# ---------------------------------------------------------------------------


class TestSinkKwargsAreSanitized:
    def test_sink_only_receives_whitelisted_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sink_spy: MagicMock,
    ) -> None:
        """Sink 调用参数集合必须严格 ⊆ 白名单。"""

        rr = _retrieval_result(
            task_template_id='recent_resume_analysis',
            confidence=0.10,
            candidate_skills=['resume_analysis'],
            top_k=[('recent_resume_analysis', 0.10)],
        )
        _patch_pipeline_minimal(monkeypatch, rerank_result=rr)

        message = '工资条 机密 用户标识 sensitive-user-id-12345'
        pipeline.route(message, _ctx(role='hr'))

        assert sink_spy.write.call_count == 1
        # 只允许下面这组 kwargs；任何超出白名单的 key 都要拒绝
        allowed_keys = {
            'query_hash', 'role', 'top_k_task_ids', 'top_k_scores',
            'chosen_task_id', 'timestamp',
        }
        kwargs = sink_spy.write.call_args.kwargs
        assert set(kwargs.keys()) == allowed_keys, (
            f'sink received unexpected kwargs: {set(kwargs.keys()) - allowed_keys}'
        )
        # 同样不允许把原文 / user_id / session_id 当 positional 传入
        assert sink_spy.write.call_args.args == ()
        # 字段值层面：不能出现原文 / user_id / session_id
        for value in kwargs.values():
            value_str = str(value)
            assert '工资条' not in value_str
            assert '机密' not in value_str
            assert 'sensitive-user-id-12345' not in value_str
            assert 'sensitive-session-67890' not in value_str
