"""Task 8.1 —— ConfidenceGate 三段窗 / 第二轮规则 / 阈值热加载测试。

校验目标：

- 三段窗判定：``confidence=0.3`` → fallback；``confidence=0.6`` → clarification
  （options 1-4 项 from top_k，去重保序）；``confidence=0.9`` → retrieval。
- 边界值（闭区间）：``confidence==low`` 与 ``confidence==high`` 均落在
  窗口内，输出 clarification。
- ``top_k`` 为空时（即使 confidence 在窗口内）→ ``route_path='fallback'``，
  ``clarification_options=[]``。
- 第二轮规则：history 上一轮 ``meta.routePath='clarification'``，
  本轮 confidence 仍在窗口 → ``low_confidence_warning=True``，
  ``route_path='retrieval'``，``clarification_options=[]``，
  ``requires_confirmation`` 保留入参原值（False 时保持 False）。
- 阈值 env 覆盖：monkeypatch ``ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD=0.4`` /
  ``HIGH=0.8`` 后 ``reload()``，``confidence=0.45`` 不再 fallback 而是
  clarification。
- 不修改特殊输入：``route_path`` 已是 ``fast_path`` /
  ``legacy_fallback`` / ``legacy``，或 ``task_template_id`` 已是
  ``forbidden_action_response`` / ``permission_denied_response`` 时，
  ``evaluate`` 应保持原值不变。
- ``evaluate`` 不改动入参（不可变契约），返回新 RouterResult。

Validates: Requirements 3.1, 3.5, 3.6, 7.3
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

import pytest

# Ensure ``backend-python`` is on sys.path so we can import the package using
# its real qualified name regardless of where pytest is invoked from.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core.intent_router import confidence_gate  # noqa: E402
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    RouterResult,
)


# ---- fixtures ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_gate(monkeypatch):
    """Each test starts with a clean env and a freshly reloaded gate."""

    monkeypatch.delenv('ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', raising=False)
    monkeypatch.delenv('ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD', raising=False)
    confidence_gate.reload()
    yield
    confidence_gate.reload()


def _make_router_result(
    *,
    confidence: float,
    top_k: List[Tuple[str, float]] = None,
    task_template_id: str = 'recent_resume_analysis',
    route_path: str = 'unknown',
    requires_confirmation: bool = False,
    risk_level: str = 'low',
) -> RouterResult:
    """Build a RouterResult that already came out of Reranker."""

    return RouterResult(
        intent='resume',
        task_template_id=task_template_id,
        confidence=confidence,
        top_k=list(top_k) if top_k is not None else [
            ('recent_resume_analysis', 0.62),
            ('global_search_answer', 0.41),
        ],
        route_path=route_path,
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
    )


def _make_ctx(history: List[Dict[str, Any]] = None) -> AssistantContext:
    return AssistantContext(
        user_id='u-1',
        role='hr',
        session_id='s-1',
        history=history or [],
    )


# ============================================================================
# 三段窗判定
# ============================================================================


class TestThreeBandWindow:
    def test_confidence_below_low_falls_back(self) -> None:
        r = _make_router_result(confidence=0.3)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'fallback'
        assert out.clarification_options == []
        # 入参未被修改
        assert r.route_path == 'unknown'
        assert r.clarification_options == []

    def test_confidence_inside_window_emits_clarification(self) -> None:
        r = _make_router_result(
            confidence=0.6,
            top_k=[
                ('recent_resume_analysis', 0.62),
                ('global_search_answer', 0.41),
                ('attendance_exception_analysis', 0.35),
            ],
        )
        out = confidence_gate.evaluate(r, _make_ctx())

        assert out.route_path == 'clarification'
        assert out.requires_confirmation is True
        assert 1 <= len(out.clarification_options) <= 4
        # 每项形如 {label, payload}，且与 top_k 顺序一致
        assert out.clarification_options == [
            {'label': 'recent_resume_analysis',
             'payload': 'recent_resume_analysis'},
            {'label': 'global_search_answer',
             'payload': 'global_search_answer'},
            {'label': 'attendance_exception_analysis',
             'payload': 'attendance_exception_analysis'},
        ]

    def test_clarification_caps_at_four_options(self) -> None:
        top_k = [
            (f'task_{i}', 0.7 - i * 0.05) for i in range(6)
        ]
        r = _make_router_result(confidence=0.6, top_k=top_k)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'clarification'
        assert len(out.clarification_options) == 4
        assert [o['label'] for o in out.clarification_options] == [
            'task_0', 'task_1', 'task_2', 'task_3',
        ]

    def test_clarification_dedupes_top_k_by_task_id(self) -> None:
        # 同一 task 多条候选（不同 source_text）时只保留一项
        top_k = [
            ('task_a', 0.7),
            ('task_a', 0.65),
            ('task_b', 0.6),
            ('task_a', 0.55),
        ]
        r = _make_router_result(confidence=0.6, top_k=top_k)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert [o['label'] for o in out.clarification_options] == [
            'task_a', 'task_b',
        ]

    def test_confidence_above_high_uses_retrieval(self) -> None:
        r = _make_router_result(confidence=0.9)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'retrieval'
        assert out.clarification_options == []
        assert out.requires_confirmation is False


# ============================================================================
# 边界值（闭区间）
# ============================================================================


class TestBoundaryValues:
    @pytest.mark.parametrize('confidence', [0.50, 0.75])
    def test_threshold_boundaries_are_inside_window(
        self, confidence: float,
    ) -> None:
        r = _make_router_result(confidence=confidence)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'clarification'
        assert out.requires_confirmation is True
        assert len(out.clarification_options) >= 1


# ============================================================================
# top_k 为空时 → fallback（即使 confidence 在窗口）
# ============================================================================


class TestEmptyTopKInWindow:
    def test_empty_top_k_falls_back_even_in_window(self) -> None:
        r = _make_router_result(confidence=0.6, top_k=[])
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'fallback'
        assert out.clarification_options == []
        # 同时不强制 confirmation：fallback 走全文搜索兜底
        assert out.requires_confirmation is False


# ============================================================================
# 第二轮规则：跳过澄清 + low_confidence_warning + Top-1
# ============================================================================


def _history_with_clarification(
    *, meta_key: str = 'meta', path_key: str = 'routePath',
) -> List[Dict[str, Any]]:
    return [
        {'role': 'user', 'content': '看看小王'},
        {
            'role': 'assistant',
            'content': '你想查小王的什么信息？',
            meta_key: {path_key: 'clarification'},
        },
    ]


class TestSecondRoundRule:
    def test_second_round_in_window_skips_clarification(self) -> None:
        ctx = _make_ctx(history=_history_with_clarification())
        r = _make_router_result(
            confidence=0.6,
            top_k=[
                ('recent_resume_analysis', 0.62),
                ('attendance_exception_analysis', 0.55),
            ],
            requires_confirmation=False,
        )
        out = confidence_gate.evaluate(r, ctx)

        assert out.low_confidence_warning is True
        assert out.route_path == 'retrieval'
        assert out.clarification_options == []
        # 入参 requires_confirmation=False 时保持 False（不强行设 True）
        assert out.requires_confirmation is False

    def test_second_round_forces_top1_task_template(self) -> None:
        ctx = _make_ctx(history=_history_with_clarification())
        r = _make_router_result(
            confidence=0.6,
            task_template_id='global_search_answer',  # Reranker 选了非 Top-1
            top_k=[
                ('recent_resume_analysis', 0.62),
                ('global_search_answer', 0.41),
            ],
        )
        out = confidence_gate.evaluate(r, ctx)

        assert out.task_template_id == 'recent_resume_analysis'
        assert out.low_confidence_warning is True
        assert out.route_path == 'retrieval'

    def test_second_round_keeps_existing_requires_confirmation_true(self) -> None:
        # 上游已经因为 side_effect 设了 True，ConfidenceGate 不应回退
        ctx = _make_ctx(history=_history_with_clarification())
        r = _make_router_result(
            confidence=0.6,
            requires_confirmation=True,
        )
        out = confidence_gate.evaluate(r, ctx)
        assert out.requires_confirmation is True
        assert out.low_confidence_warning is True

    def test_second_round_recognises_metadata_alias(self) -> None:
        ctx = _make_ctx(
            history=_history_with_clarification(
                meta_key='metadata', path_key='route_path',
            ),
        )
        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, ctx)
        assert out.low_confidence_warning is True
        assert out.route_path == 'retrieval'

    def test_first_round_when_history_has_no_clarification(self) -> None:
        history = [
            {'role': 'user', 'content': 'xx'},
            {'role': 'assistant', 'content': 'yy',
             'meta': {'routePath': 'retrieval'}},
        ]
        ctx = _make_ctx(history=history)
        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, ctx)
        assert out.low_confidence_warning is False
        assert out.route_path == 'clarification'
        assert out.clarification_options  # 非空

    def test_first_round_when_history_is_empty(self) -> None:
        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, _make_ctx(history=[]))
        assert out.route_path == 'clarification'
        assert out.low_confidence_warning is False

    def test_second_round_outside_window_uses_normal_path(self) -> None:
        # 上一轮虽然是 clarification，但本轮已经走出窗口 → 不触发第二轮规则
        ctx = _make_ctx(history=_history_with_clarification())
        r = _make_router_result(confidence=0.9)
        out = confidence_gate.evaluate(r, ctx)
        assert out.route_path == 'retrieval'
        assert out.low_confidence_warning is False

    def test_second_round_below_low_still_falls_back(self) -> None:
        # confidence < low 优先走 fallback，不触发第二轮强制 Top-1
        ctx = _make_ctx(history=_history_with_clarification())
        r = _make_router_result(confidence=0.3)
        out = confidence_gate.evaluate(r, ctx)
        assert out.route_path == 'fallback'
        assert out.low_confidence_warning is False


# ============================================================================
# 阈值 env 覆盖 + reload
# ============================================================================


class TestThresholdReload:
    def test_env_overrides_take_effect_after_reload(self, monkeypatch) -> None:
        # 默认窗口下 0.45 落到 fallback（< 0.50）
        r = _make_router_result(confidence=0.45)
        baseline = confidence_gate.evaluate(r, _make_ctx())
        assert baseline.route_path == 'fallback'

        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', '0.4')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD', '0.8')
        confidence_gate.reload()

        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'clarification'
        assert out.requires_confirmation is True
        assert out.clarification_options  # 非空

    def test_invalid_env_falls_back_to_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', 'not-a-number')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD', '0.9')
        confidence_gate.reload()

        # 整体回落到默认 (0.50, 0.75)：0.45 仍为 fallback
        r = _make_router_result(confidence=0.45)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == 'fallback'

    def test_low_greater_than_high_falls_back_to_defaults(
        self, monkeypatch,
    ) -> None:
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', '0.9')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD', '0.4')
        confidence_gate.reload()

        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, _make_ctx())
        # 默认窗口下 0.6 落入窗口 → clarification
        assert out.route_path == 'clarification'

    def test_changes_without_reload_do_not_take_effect(self, monkeypatch) -> None:
        r = _make_router_result(confidence=0.45)
        # 触发一次缓存
        assert confidence_gate.evaluate(r, _make_ctx()).route_path == 'fallback'

        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD', '0.4')
        monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD', '0.8')
        # 不调 reload：行为应保持先前的快照
        assert confidence_gate.evaluate(r, _make_ctx()).route_path == 'fallback'

        confidence_gate.reload()
        assert confidence_gate.evaluate(r, _make_ctx()).route_path == 'clarification'


# ============================================================================
# 跳过修改的输入
# ============================================================================


class TestSkipPaths:
    @pytest.mark.parametrize('route_path', [
        'fast_path', 'legacy_fallback', 'legacy',
    ])
    def test_skip_route_paths_are_preserved(self, route_path: str) -> None:
        r = _make_router_result(
            confidence=0.6,  # 在窗口内，但 route_path 已被上游覆盖
            route_path=route_path,
            requires_confirmation=False,
        )
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.route_path == route_path
        assert out.clarification_options == []
        assert out.requires_confirmation is False
        assert out.low_confidence_warning is False

    @pytest.mark.parametrize('task_id', [
        'forbidden_action_response',
        'permission_denied_response',
    ])
    def test_terminal_task_ids_are_preserved(self, task_id: str) -> None:
        r = _make_router_result(
            confidence=0.6,
            task_template_id=task_id,
            route_path='unknown',
        )
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out.task_template_id == task_id
        assert out.route_path == 'unknown'
        assert out.clarification_options == []
        assert out.low_confidence_warning is False


# ============================================================================
# 不可变契约：evaluate 不改动入参
# ============================================================================


class TestImmutability:
    def test_evaluate_returns_new_instance_for_window(self) -> None:
        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, _make_ctx())
        assert out is not r
        # 入参字段保持原值
        assert r.route_path == 'unknown'
        assert r.clarification_options == []
        assert r.requires_confirmation is False

    def test_evaluate_returns_new_instance_for_skip_path(self) -> None:
        r = _make_router_result(confidence=0.6, route_path='fast_path')
        out = confidence_gate.evaluate(r, _make_ctx())
        # 即使语义不变也返回新实例，避免上游缓存被共享
        assert out is not r
        assert out == r

    def test_no_history_mutation(self) -> None:
        history = _history_with_clarification()
        snapshot = [dict(item) for item in history]
        ctx = _make_ctx(history=history)
        r = _make_router_result(confidence=0.6)
        confidence_gate.evaluate(r, ctx)
        assert history == snapshot


# ============================================================================
# 防御：ctx 为 None 时按首轮处理
# ============================================================================


class TestNoneContext:
    def test_none_ctx_treated_as_first_round(self) -> None:
        r = _make_router_result(confidence=0.6)
        out = confidence_gate.evaluate(r, None)
        assert out.route_path == 'clarification'
        assert out.low_confidence_warning is False
