"""Task 14.1 —— Executor 短路澄清轮 + 下一轮合并 origin_message 单元测试。

**Validates: Requirements 3.2, 3.3, 3.4, 10.5**

覆盖目标：

* **澄清直接短路**：``router_result.requires_confirmation=True`` 且
  ``clarification_options`` 非空 → ``executor.execute`` 直接返回
  ``ExecutionResult``，``widgets`` 中存在 type=clarification widget；
  ``requires_confirmation=True``、``fallback_used=False``；``summary`` 等于
  ``clarification_question`` 文本；不调用 skill handler / LLM summarizer。
* **下一轮合并 origin_message**：构造 ``ctx.history`` 倒数第二条
  meta.routePath='clarification' + 上一轮 ``originMessage='看看小王'`` +
  本轮 message='考勤'（匹配某个 ``option.payload``）→
  ``orchestrator._maybe_merge_clarification_reply`` 把 message 合并为
  '看看小王 考勤'，并由 orchestrator 的主流程使用合并 query 调用
  ``routing.route``。
* **信息单调性**：澄清前已抽取的实体（``ctx.entity_memory`` 已有
  employee=小王）在合并后的 query 路由时仍然存在；executor 短路澄清
  时不写 EntityMemory，确保实体集合单调不减。
* **连续两轮模糊**：本轮 ``router_result.clarification_options=[]`` 且
  ``requires_confirmation=False`` → executor 不再短路澄清而是正常执行
  workflow；测试只验证 widget 中没有 clarification 类型组件。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import pytest

# Ensure backend-python is on sys.path so we can import via 'services.*'.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core import (  # noqa: E402
    executor,
    legacy_orchestrator as orchestrator,
    skill_registry,
    task_registry,
)
from services.assistant_core.constants import RISK_LOW  # noqa: E402
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    ExecutionResult,
    RouterResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    role: str = 'hr_admin',
    history: Optional[List[Dict[str, Any]]] = None,
    **kw: Any,
) -> AssistantContext:
    return AssistantContext(
        user_id=kw.pop('user_id', 'u-clarify'),
        role=role,
        session_id=kw.pop('session_id', 'sess-clarify'),
        history=history or [],
        request_id=kw.pop('request_id', 'req-clarify'),
        **kw,
    )


def _clarification_router_result(
    *,
    task_template_id: str = 'global_search_answer',
    options: Optional[List[Dict[str, Any]]] = None,
    question: str = '你想查小王的什么信息？',
    confidence: float = 0.6,
    entities: Optional[Dict[str, Any]] = None,
) -> RouterResult:
    """澄清窗口下 Reranker → ConfidenceGate 的典型输出。"""

    if options is None:
        options = [
            {'label': '考勤', 'payload': '考勤'},
            {'label': '工资', 'payload': '工资'},
        ]
    return RouterResult(
        intent='clarification',
        task_template_id=task_template_id,
        confidence=confidence,
        entities=dict(entities or {}),
        missing_fields=[],
        risk_level=RISK_LOW,
        candidate_skills=[],
        requires_confirmation=True,
        clarification_question=question,
        reason='confidence_in_window',
        rule_matched=False,
        forbidden_reason=None,
        route_path='clarification',
        top_k=[(opt['payload'], 0.6 - i * 0.05)
               for i, opt in enumerate(options) if opt.get('payload')],
        clarification_options=list(options),
        low_confidence_warning=False,
        entity_resolved={},
    )


# ===========================================================================
# 1) executor 短路澄清
# ===========================================================================


class TestExecutorShortCircuitClarification:
    """``executor.execute`` 在 ``requires_confirmation=True`` +
    ``clarification_options`` 非空时直接返回 ClarificationWidget。"""

    def test_emits_clarification_widget_only(self, monkeypatch) -> None:
        rr = _clarification_router_result()
        ctx = _ctx()

        # 任何 skill handler 被调用都立刻失败：澄清短路必须跳过 workflow。
        boom = mock.MagicMock(side_effect=AssertionError('skill should not run'))
        monkeypatch.setattr(skill_registry, 'get', boom)
        # 任何 LLM summarizer 被调用同样视为失败。
        monkeypatch.setattr(
            executor, '_summarize_llm',
            mock.MagicMock(side_effect=AssertionError('llm should not run')),
        )
        # task_registry.get 只在非短路路径被用到，这里也设 boom 兜底。
        monkeypatch.setattr(
            task_registry, 'get',
            mock.MagicMock(side_effect=AssertionError('task should not load')),
        )

        result = executor.execute('看看小王', rr, ctx)

        assert isinstance(result, ExecutionResult)
        # widgets 中恰好一项 clarification widget。
        clarif_widgets = [w for w in result.widgets
                          if isinstance(w, dict) and w.get('type') == 'clarification']
        assert len(clarif_widgets) == 1
        widget = clarif_widgets[0]
        # 字段形状对齐 widgets.clarification 契约。
        assert widget['question'] == '你想查小王的什么信息？'
        assert widget['options'] == [
            {'label': '考勤', 'payload': '考勤'},
            {'label': '工资', 'payload': '工资'},
        ]
        assert widget['origin_message'] == '看看小王'

        # ExecutionResult 元字段
        assert result.requires_confirmation is True
        assert result.fallback_used is False
        assert result.summary == '你想查小王的什么信息？'
        assert result.session_id == ctx.session_id
        assert result.router is rr
        # 没有 entities，没有任何 skill 调用 → trace 至多有一条 skipped
        assert all(step.skill is None for step in result.trace)

    def test_default_question_when_clarification_question_missing(
        self, monkeypatch,
    ) -> None:
        """``clarification_question`` 缺省时使用中文默认提示『请进一步确认』。"""

        rr = _clarification_router_result(question='')
        rr.clarification_question = None  # 直接把字段抹掉
        ctx = _ctx()

        # 防御：依然不应触发任何 skill / llm。
        monkeypatch.setattr(
            skill_registry, 'get',
            mock.MagicMock(side_effect=AssertionError('no skill')),
        )

        result = executor.execute('看看小王', rr, ctx)
        widget = next(w for w in result.widgets if w.get('type') == 'clarification')
        assert widget['question'] == '请进一步确认'
        assert result.summary == '请进一步确认'
        assert result.requires_confirmation is True

    def test_options_truncated_to_max_4(self, monkeypatch) -> None:
        """超过 4 个候选回复时只保留前 4 个（widgets.clarification 上限）。"""

        many = [{'label': f'选项{i}', 'payload': f'p{i}'} for i in range(7)]
        rr = _clarification_router_result(options=many)
        ctx = _ctx()

        result = executor.execute('看看小王', rr, ctx)
        widget = next(w for w in result.widgets if w.get('type') == 'clarification')
        assert len(widget['options']) == 4

    def test_fallback_used_is_false_short_circuit(self) -> None:
        rr = _clarification_router_result()
        ctx = _ctx()
        result = executor.execute('看看小王', rr, ctx)
        assert result.fallback_used is False
        assert result.error_code is None


# ===========================================================================
# 2) orchestrator helper：合并 origin_message
# ===========================================================================


class TestMaybeMergeClarificationReply:
    """``orchestrator._maybe_merge_clarification_reply`` 是 helper，单独可测。"""

    @staticmethod
    def _history_with_clarification(
        *,
        meta_key: str = 'meta',
        path_key: str = 'routePath',
        origin_key: str = 'originMessage',
        options: Optional[List[Dict[str, Any]]] = None,
        origin: str = '看看小王',
    ) -> List[Dict[str, Any]]:
        if options is None:
            options = [
                {'label': '考勤', 'payload': '考勤'},
                {'label': '工资', 'payload': '工资'},
            ]
        return [
            {'role': 'user', 'content': origin},
            {
                'role': 'assistant',
                'content': '你想查小王的什么信息？',
                meta_key: {
                    path_key: 'clarification',
                    origin_key: origin,
                    'clarificationOptions': options,
                },
            },
        ]

    def test_merges_when_payload_matches(self) -> None:
        ctx = _ctx(history=self._history_with_clarification())
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤', ctx,
        )
        assert did_merge is True
        assert merged == '看看小王 考勤'

    def test_merges_when_label_matches(self) -> None:
        ctx = _ctx(history=self._history_with_clarification(
            options=[{'label': '考勤详情', 'payload': 'attendance'}],
        ))
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤详情', ctx,
        )
        assert did_merge is True
        assert merged == '看看小王 考勤详情'

    def test_recognises_metadata_alias(self) -> None:
        ctx = _ctx(history=self._history_with_clarification(
            meta_key='metadata', path_key='route_path',
            origin_key='origin_message',
        ))
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤', ctx,
        )
        assert did_merge is True
        assert merged == '看看小王 考勤'

    def test_no_merge_when_history_empty(self) -> None:
        ctx = _ctx(history=[])
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤', ctx,
        )
        assert did_merge is False
        assert merged == '考勤'

    def test_no_merge_when_last_assistant_not_clarification(self) -> None:
        history = [
            {'role': 'user', 'content': '看看小王'},
            {
                'role': 'assistant', 'content': 'hi',
                'meta': {'routePath': 'retrieval'},
            },
        ]
        ctx = _ctx(history=history)
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤', ctx,
        )
        assert did_merge is False
        assert merged == '考勤'

    def test_no_merge_when_message_not_in_options(self) -> None:
        ctx = _ctx(history=self._history_with_clarification())
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '请假', ctx,
        )
        assert did_merge is False
        assert merged == '请假'

    def test_no_merge_when_origin_message_missing(self) -> None:
        history = [
            {'role': 'user', 'content': '看看小王'},
            {
                'role': 'assistant', 'content': 'q',
                'meta': {
                    'routePath': 'clarification',
                    'clarificationOptions': [{'label': '考勤', 'payload': '考勤'}],
                    # 没有 originMessage
                },
            },
        ]
        ctx = _ctx(history=history)
        merged, did_merge = orchestrator._maybe_merge_clarification_reply(
            '考勤', ctx,
        )
        assert did_merge is False
        assert merged == '考勤'


# ===========================================================================
# 3) orchestrator.run 把合并后的 query 传给 routing.route
# ===========================================================================


class TestOrchestratorMergesAndRoutesAgain:
    """端到端层面验证：第二轮 message 命中 option payload 时，orchestrator
    会用合并后的 ``"origin_message message"`` 调用 ``routing.route``。"""

    @pytest.fixture(autouse=True)
    def _isolate_io(self, monkeypatch):
        # 屏蔽 cache / save_turn，避免依赖 DB 与缓存。
        class _NullCache:
            def get(self, *a, **kw):
                return None

            def put(self, *a, **kw):
                return None

        monkeypatch.setattr(orchestrator, 'query_cache', _NullCache(), raising=True)

        def fake_save_turn(**kwargs):
            return kwargs.get('session_id') or 'sess-saved'

        monkeypatch.setattr(orchestrator.memory, 'save_turn', fake_save_turn)
        yield

    def test_second_round_routing_receives_merged_query(self, monkeypatch) -> None:
        """合并后的 query 被传给 routing.route；不丢失上一轮 entity。"""

        history = TestMaybeMergeClarificationReply._history_with_clarification()
        # 关键：上一轮 entity 已经被 pipeline 写入；这里在 history 中体现为
        # 上一轮 router metadata 中的 entities，executor 短路时不应清空。
        # 我们额外在最后一条 assistant meta 中放上 employee 实体的快照，
        # 然后断言下一轮路由时仍能透传。
        history[-1]['meta']['entities'] = {'employee': '小王'}

        # 模拟会话上下文：employee=小王 已经在 EntityMemory（透过 history 表达）。
        ctx = _ctx(history=history)

        captured: Dict[str, Any] = {}

        def fake_route(message, c):
            captured['message'] = message
            captured['session_id'] = c.session_id
            # 第二轮路由命中考勤异常分析（高置信，不再澄清）。
            return RouterResult(
                intent='attendance_exception_analysis',
                task_template_id='attendance_exception_analysis',
                confidence=0.9,
                entities={'employee': '小王', 'keyword': '考勤'},
                missing_fields=[],
                risk_level=RISK_LOW,
                candidate_skills=['attendance_analysis'],
                requires_confirmation=False,
                clarification_question=None,
                reason='post-clarification merged route',
                rule_matched=False,
                forbidden_reason=None,
                route_path='retrieval',
                top_k=[('attendance_exception_analysis', 0.9)],
            )

        monkeypatch.setattr(orchestrator.routing, 'route', fake_route)

        # executor 不真的跑 workflow，只回声 message 与 router_result。
        def fake_execute(message, router_result, ctx_):
            return ExecutionResult(
                summary='ok',
                entities=[{'type': 'employee', 'id': 'e-小王', 'name': '小王'}],
                widgets=[],
                session_id=ctx_.session_id,
                trace=[],
                router=router_result,
                fallback_used=False,
            )

        monkeypatch.setattr(orchestrator.executor, 'execute', fake_execute)

        result = orchestrator.run('考勤', ctx)

        # 关键断言：routing.route 收到的是合并后的 query。
        assert captured['message'] == '看看小王 考勤'
        # 二次路由的 RouterResult 被透传到 ExecutionResult。
        assert result.router is not None
        assert result.router.task_template_id == 'attendance_exception_analysis'
        assert result.router.entities.get('employee') == '小王'

    def test_first_round_clarification_persists_origin_message_metadata(
        self, monkeypatch,
    ) -> None:
        """澄清轮被产出时，``memory.save_turn`` metadata 保留 ``originMessage``，
        以便下一轮 ``_maybe_merge_clarification_reply`` 能取到。"""

        rr = _clarification_router_result()

        monkeypatch.setattr(orchestrator.routing, 'route', lambda m, c: rr)

        # executor 用真实的短路逻辑。
        captured: Dict[str, Any] = {}

        def capture_save(**kwargs):
            captured.update(kwargs)
            return 'sess-saved'

        monkeypatch.setattr(orchestrator.memory, 'save_turn', capture_save)

        ctx = _ctx()
        orchestrator.run('看看小王', ctx)

        # save_turn 收到的 metadata 必须带 originMessage 与 clarificationOptions。
        meta = captured.get('metadata') or {}
        assert meta.get('originMessage') == '看看小王'
        assert meta.get('routePath') == 'clarification'
        assert meta.get('clarificationOptions') == [
            {'label': '考勤', 'payload': '考勤'},
            {'label': '工资', 'payload': '工资'},
        ]

    def test_non_clarification_round_does_not_record_origin(
        self, monkeypatch,
    ) -> None:
        """普通轮（无澄清）写入 metadata 时 ``originMessage=None``，避免污染。"""

        normal = RouterResult(
            intent='employee_lookup',
            task_template_id='employee_lookup',
            confidence=0.9,
            entities={'keyword': 'kw'},
            missing_fields=[],
            risk_level=RISK_LOW,
            candidate_skills=['employee_search'],
            requires_confirmation=False,
            clarification_question=None,
            reason='normal',
            rule_matched=True,
            forbidden_reason=None,
            route_path='retrieval',
            top_k=[('employee_lookup', 0.9)],
        )
        monkeypatch.setattr(orchestrator.routing, 'route', lambda m, c: normal)

        def fake_execute(message, router_result, ctx_):
            return ExecutionResult(
                summary='ok', session_id=ctx_.session_id, router=router_result,
            )

        monkeypatch.setattr(orchestrator.executor, 'execute', fake_execute)

        captured: Dict[str, Any] = {}

        def capture_save(**kwargs):
            captured.update(kwargs)
            return 'sess-saved'

        monkeypatch.setattr(orchestrator.memory, 'save_turn', capture_save)

        ctx = _ctx()
        orchestrator.run('查一下小王', ctx)

        meta = captured.get('metadata') or {}
        assert meta.get('originMessage') is None
        assert meta.get('routePath') == 'retrieval'
        assert meta.get('clarificationOptions') == []


# ===========================================================================
# 4) 信息单调性：澄清前后已确认实体集合单调不减
# ===========================================================================


class TestEntityMonotonicity:
    """澄清短路时 executor 不写 EntityMemory，但路由层之前已经把实体抽到
    ``router_result.entities``，因此短路前后用户已确认的实体集合至少不减。"""

    def test_short_circuit_preserves_pre_clarification_entities(self) -> None:
        """短路澄清时，``router_result.entities`` 中的实体在 ExecutionResult.router
        上原样保留（信息单调性的局部体现）。"""

        rr = _clarification_router_result(
            entities={'employee': '小王'},
        )
        ctx = _ctx()

        result = executor.execute('看看小王', rr, ctx)

        # router 透传不变 → entities 不丢
        assert result.router is rr
        assert result.router.entities == {'employee': '小王'}
        # 短路路径不引入新的实体（widgets 中无 entity_cards），但旧实体仍然
        # 通过 router 暴露给下游，下一轮可继续用。
        assert all(
            isinstance(w, dict) and w.get('type') != 'entity_cards'
            for w in result.widgets
        )

    def test_merged_query_round_preserves_origin_entities(
        self, monkeypatch,
    ) -> None:
        """合并 query 后再次路由时，先前抽到的实体必须在新 router_result 中
        仍然存在（单调不减）。这里用 mock 模拟 routing.route 在合并 query
        上做出包含旧实体的输出，并断言 orchestrator 没有把它们清空。"""

        history = TestMaybeMergeClarificationReply._history_with_clarification()
        history[-1]['meta']['entities'] = {'employee': '小王'}
        ctx = _ctx(history=history)

        def fake_route(message, c):
            assert message == '看看小王 考勤'
            return RouterResult(
                intent='attendance_exception_analysis',
                task_template_id='attendance_exception_analysis',
                confidence=0.9,
                entities={'employee': '小王', 'keyword': '考勤'},
                missing_fields=[],
                risk_level=RISK_LOW,
                candidate_skills=['attendance_analysis'],
                requires_confirmation=False,
                clarification_question=None,
                reason='merged',
                rule_matched=False,
                forbidden_reason=None,
                route_path='retrieval',
                top_k=[('attendance_exception_analysis', 0.9)],
            )

        monkeypatch.setattr(orchestrator.routing, 'route', fake_route)

        def fake_execute(message, router_result, ctx_):
            return ExecutionResult(
                summary='ok',
                session_id=ctx_.session_id,
                router=router_result,
            )

        monkeypatch.setattr(orchestrator.executor, 'execute', fake_execute)

        class _NullCache:
            def get(self, *a, **kw):
                return None

            def put(self, *a, **kw):
                return None

        monkeypatch.setattr(orchestrator, 'query_cache', _NullCache(), raising=True)
        monkeypatch.setattr(
            orchestrator.memory, 'save_turn',
            lambda **kw: kw.get('session_id') or 'sess-saved',
        )

        result = orchestrator.run('考勤', ctx)
        # 单调性：第二轮 entities ⊇ 第一轮已确认的 {'employee': '小王'}
        assert result.router.entities.get('employee') == '小王'
        assert 'keyword' in result.router.entities


# ===========================================================================
# 5) 连续两轮模糊：confidence_gate 已置 low_confidence_warning，executor 不再短路
# ===========================================================================


class TestConsecutiveLowConfidenceNoShortCircuit:
    """task 8 的 ConfidenceGate 在连续两轮落入窗口时强制 Top-1 +
    ``low_confidence_warning=True`` + 清空 ``clarification_options`` /
    ``requires_confirmation=False``。executor 收到这种 ``RouterResult`` 时
    必须按正常 workflow 执行（不输出 clarification widget）。"""

    def test_executor_does_not_emit_clarification_when_options_empty(
        self, monkeypatch,
    ) -> None:
        rr = RouterResult(
            intent='global_search',
            task_template_id='global_search_answer',
            confidence=0.6,
            entities={'keyword': '小王'},
            missing_fields=[],
            risk_level=RISK_LOW,
            candidate_skills=['global_search'],
            requires_confirmation=False,
            clarification_question=None,
            reason='second_round_low_confidence',
            rule_matched=False,
            forbidden_reason=None,
            route_path='retrieval',
            top_k=[('global_search_answer', 0.6)],
            clarification_options=[],  # ← 关键：空列表 → executor 不短路
            low_confidence_warning=True,
        )
        ctx = _ctx()

        # 模拟 task_registry 返回真实任务（不真的跑 skill），让 executor
        # 进入 workflow 分支但所有 skill 都 skip 掉。
        from services.assistant_core.schemas import TaskTemplate

        fake_task = TaskTemplate(
            id='global_search_answer',
            name='全局兜底',
            description='',
            trigger_examples=[],
            required_entities=[],
            optional_entities={},
            allowed_roles=['hr_admin', 'employee'],
            risk_level='low',
            candidate_skills=[],
            workflow=[],
            output_widgets=[],
            fallback_task=None,
            requires_confirmation=False,
        )
        monkeypatch.setattr(
            task_registry, 'get',
            lambda task_id: fake_task if task_id == 'global_search_answer' else None,
        )

        result = executor.execute('小王', rr, ctx)
        clarif = [w for w in result.widgets
                  if isinstance(w, dict) and w.get('type') == 'clarification']
        assert clarif == [], (
            'executor 在 clarification_options 为空时不得输出 clarification widget'
        )

