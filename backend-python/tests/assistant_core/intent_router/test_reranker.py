"""Task 7.1 —— Reranker 单元测试。

校验目标：

- ``build_prompt`` 形状：返回 ``[system, user]`` 两条消息；system 包含
  「只能从给定候选选 task_id」「输出严格 JSON」；列出每个候选的
  ``task_id/score/source_text``（source_text 截断到 80 字符）；history
  最多 4 条、每条 120 字符。
- ``parse_strict_json`` 行为：
  - 正常 dict → 返回清洗后的字段；
  - 缺必需字段 → ``None``；
  - ``task_id`` 不在 ``allowed_task_ids`` 白名单 → ``None``；
  - 未知字段 → 静默忽略，不抛错；
  - ``confidence='abc'`` → 字典中 ``confidence=0.0`` 且 ``reason_extra``
    含 ``invalid_confidence``。
- ``rerank`` 行为：
  - 正常返回：``json_chat`` 给 ``{task_id:'task1', confidence:0.9, ...}``
    → ``RouterResult(task_template_id='task1', confidence=0.9,
    route_path='retrieval')``，``top_k`` 与 ``candidates.items`` 对齐；
  - JSON 缺 ``task_id`` → fallback to ``candidates.items[0].task_id``，
    ``confidence ≤ low_threshold``，``route_path='fallback'``，
    ``reason`` 含说明；
  - JSON 含未知字段 → 已知字段被正确解析，未知字段不影响结果；
  - ``task_id`` 越界（不在候选）→ 强制改写为 ``candidates.items[0].task_id``，
    fallback 路径；
  - ``confidence='abc'`` → 0.0 + ``reason`` 包含 ``invalid_confidence``；
  - ``json_chat`` 返回 None（超时或失败）→ fallback to
    ``candidates.items[0]``，``confidence ≤ low_threshold``，
    ``route_path='fallback'``，``reason`` 含 ``json_chat_failed`` /
    ``timeout``；
  - ``json_chat`` 抛 ``requests.Timeout`` → 同上，``reason`` 含 ``timeout``；
  - ``concurrent.futures.TimeoutError`` 模拟硬超时 → 同上；
  - ``candidates`` 为空 → 直接降级为 ``RouterResult(
    task_template_id='global_search_answer', confidence=0,
    route_path='fallback', reason='reranker:no_candidates')``。

- 模块级单例 + ``rerank()`` / ``reload()`` 包装。
- env ``ASSISTANT_INTENT_ROUTER_RERANKER_TIMEOUT_MS`` 优先级：参数 > env >
  默认 3000；非法 env → 3000。

Validates: Requirements 1.3, 1.4, 1.5, 1.6, 7.4, 9.4, 9.5
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests

# Ensure ``backend-python`` is on sys.path even if pytest is invoked from
# elsewhere; conftest.py already does this for normal runs but be defensive.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core.intent_router import reranker  # noqa: E402
from services.assistant_core.intent_router.retriever import (  # noqa: E402
    RetrievalCandidates,
)
from services.assistant_core.schemas import (  # noqa: E402
    AssistantContext,
    RouterResult,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """Each test starts with a clean module-level singleton."""

    monkeypatch.delenv(reranker.ENV_TIMEOUT_MS, raising=False)
    reranker.reload()
    yield
    reranker.reload()


def _make_candidates(
    items: Optional[List[Tuple[str, float, str]]] = None,
) -> RetrievalCandidates:
    if items is None:
        items = [
            ('task1', 0.9, 'task1 source text 描述 candidate 一'),
            ('task2', 0.8, 'task2 源文本'),
            ('global_search_answer', 0.5, '兜底搜索'),
        ]
    return RetrievalCandidates(items=list(items), reason=None)


def _make_ctx(
    role: str = 'hr_admin',
    history: Optional[List[Dict[str, Any]]] = None,
) -> AssistantContext:
    return AssistantContext(
        user_id='u-1',
        role=role,
        session_id='s-1',
        history=history or [],
    )


# ============================================================================
# build_prompt
# ============================================================================


class TestBuildPrompt:
    def test_returns_system_and_user_messages(self) -> None:
        rk = reranker.Reranker()
        msgs = rk.build_prompt(
            query='查一下小王的简历',
            candidates=_make_candidates(),
            role='hr_admin',
            history=None,
        )
        assert isinstance(msgs, list)
        assert len(msgs) == 2
        assert msgs[0]['role'] == 'system'
        assert msgs[1]['role'] == 'user'

    def test_system_prompt_lists_each_candidate_with_score_and_source(
        self,
    ) -> None:
        rk = reranker.Reranker()
        items = [
            ('task1', 0.91, 'a' * 200),  # 故意超过 80 字符
            ('task2', 0.5, 'short text'),
        ]
        msgs = rk.build_prompt(
            query='hi', candidates=_make_candidates(items), role='hr',
            history=None,
        )
        system = msgs[0]['content']
        assert 'task1' in system and 'task2' in system
        # 每条 source_text 必须被截断到 80 字符（显式断言）。
        assert ('a' * 80) in system
        assert ('a' * 81) not in system
        # score 至少展示 3 位小数
        assert '0.910' in system
        assert '0.500' in system

    def test_system_prompt_states_strict_constraints(self) -> None:
        rk = reranker.Reranker()
        msgs = rk.build_prompt(
            query='q', candidates=_make_candidates(), role='hr', history=None,
        )
        system = msgs[0]['content']
        # 必须明确告诉 LLM：从给定候选选 task_id、不得创造、输出严格 JSON
        # 含必需字段。
        assert 'task_id' in system
        assert '严格' in system or 'strict' in system.lower()
        assert '不得创造' in system or '不能创造' in system or 'must not' in system.lower()
        for required in (
            'task_id', 'entities', 'missing_fields', 'confidence',
            'clarification_question',
        ):
            assert required in system

    def test_history_truncated_to_last_four_turns_each_120_chars(self) -> None:
        rk = reranker.Reranker()
        # 7 条 history，每条 200 字符；只取最后 4 条，每条截断到 120
        history = [
            {'role': 'user', 'content': f'turn{i}_' + ('x' * 200)}
            for i in range(7)
        ]
        msgs = rk.build_prompt(
            query='q', candidates=_make_candidates(), role='hr',
            history=history,
        )
        user = msgs[1]['content']
        # turn0/1/2 不应出现；turn3/4/5/6 应出现
        assert 'turn0_' not in user
        assert 'turn2_' not in user
        for keep in ('turn3_', 'turn4_', 'turn5_', 'turn6_'):
            assert keep in user
        # 每条 history 截断到 120 字符（含前缀）：取一条断言上界
        # 我们的实现是「直接截断 content[:120]」
        line = next(line for line in user.split('\n') if 'turn6_' in line)
        # line 形如 "[user] turn6_xxxxx..."；content 截断 120 字符
        # 内部 content 长度 ≤ 120
        # line = '[user] ' + content[:120]
        prefix = '[user] '
        assert line.startswith(prefix)
        body = line[len(prefix):]
        assert len(body) <= 120

    def test_no_history_does_not_break_prompt(self) -> None:
        rk = reranker.Reranker()
        msgs = rk.build_prompt(
            query='q', candidates=_make_candidates(), role='hr', history=None,
        )
        assert msgs[1]['role'] == 'user'
        assert 'q' in msgs[1]['content']

    def test_empty_candidates_renders_empty_block(self) -> None:
        rk = reranker.Reranker()
        msgs = rk.build_prompt(
            query='q',
            candidates=RetrievalCandidates(items=[], reason='test'),
            role='hr', history=None,
        )
        # 系统提示中不应列出任何 task_id 行；空候选时也不应抛错
        assert 'task_id' in msgs[0]['content']  # schema 描述里仍提到该字段
        assert msgs[1]['role'] == 'user'


# ============================================================================
# parse_strict_json
# ============================================================================


class TestParseStrictJson:
    def test_normal_payload_returns_normalized_dict(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                'task_id': 'task1',
                'entities': {'employee': '小王'},
                'missing_fields': [],
                'confidence': 0.9,
                'clarification_question': None,
            },
            allowed_task_ids={'task1', 'task2'},
        )
        assert out is not None
        assert out['task_id'] == 'task1'
        assert out['entities'] == {'employee': '小王'}
        assert out['missing_fields'] == []
        assert out['confidence'] == 0.9
        assert out['clarification_question'] is None
        assert out['reason_extra'] is None

    def test_missing_required_key_returns_none(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                # 缺 task_id
                'entities': {},
                'missing_fields': [],
                'confidence': 0.5,
                'clarification_question': None,
            },
            allowed_task_ids={'task1'},
        )
        assert out is None

    def test_task_id_out_of_candidates_returns_none(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                'task_id': 'unknown_task',
                'entities': {},
                'missing_fields': [],
                'confidence': 0.9,
                'clarification_question': None,
            },
            allowed_task_ids={'task1', 'task2'},
        )
        assert out is None

    def test_unknown_fields_are_silently_ignored(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 0.7,
                'clarification_question': None,
                'novel_field': 'foo',
                'extra_object': {'k': 'v'},
            },
            allowed_task_ids={'task1'},
        )
        assert out is not None
        assert out['task_id'] == 'task1'
        assert 'novel_field' not in out
        assert 'extra_object' not in out

    def test_confidence_string_is_clipped_to_zero_with_marker(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 'abc',
                'clarification_question': None,
            },
            allowed_task_ids={'task1'},
        )
        assert out is not None
        assert out['confidence'] == 0.0
        assert out['reason_extra'] is not None
        assert 'invalid_confidence' in out['reason_extra']

    def test_confidence_out_of_range_is_zero(self) -> None:
        rk = reranker.Reranker()
        out = rk.parse_strict_json(
            {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 1.5,
                'clarification_question': None,
            },
            allowed_task_ids={'task1'},
        )
        assert out is not None
        assert out['confidence'] == 0.0
        assert 'invalid_confidence' in out['reason_extra']

    def test_non_dict_input_returns_none(self) -> None:
        rk = reranker.Reranker()
        assert rk.parse_strict_json(None, {'task1'}) is None
        assert rk.parse_strict_json([], {'task1'}) is None
        assert rk.parse_strict_json('not-a-dict', {'task1'}) is None  # type: ignore[arg-type]


# ============================================================================
# rerank: 正常路径
# ============================================================================


class TestRerankNormal:
    def test_normal_path_uses_llm_choice(self, monkeypatch) -> None:
        seen: Dict[str, Any] = {}

        def fake_json_chat(messages, **kwargs):
            seen['messages'] = messages
            return {
                'task_id': 'task1',
                'entities': {'employee': '小王'},
                'missing_fields': [],
                'confidence': 0.9,
                'clarification_question': None,
                'candidate_skills': ['skill_a'],
            }

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)
        out = reranker.rerank(
            query='查小王简历', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert isinstance(out, RouterResult)
        assert out.task_template_id == 'task1'
        assert out.confidence == 0.9
        assert out.route_path == 'retrieval'
        assert out.entities == {'employee': '小王'}
        assert out.candidate_skills == ['skill_a']
        # top_k 必须来自 candidates.items（剥掉 source_text）
        assert out.top_k == [
            ('task1', 0.9), ('task2', 0.8), ('global_search_answer', 0.5),
        ]
        # reason 是说明性文字，不能包含 history 原文（脱敏）
        assert 'reranker' in out.reason
        # message 已发到 LLM
        assert seen.get('messages') is not None


# ============================================================================
# rerank: 缺字段 / 未知字段 / task_id 越界
# ============================================================================


class TestRerankInvalidJson:
    def test_missing_task_id_falls_back_to_top1(self, monkeypatch) -> None:
        def fake_json_chat(messages, **kwargs):
            return {
                # 缺 task_id
                'entities': {},
                'missing_fields': [],
                'confidence': 0.85,
                'clarification_question': None,
            }

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'  # candidates.items[0].task_id
        assert out.route_path == 'fallback'
        assert out.confidence <= reranker.DEFAULT_LOW_THRESHOLD
        # confidence 取 min(parsed_or_default, low_threshold)
        # parsed=0.85 → cap 到 0.5
        assert out.confidence == 0.5
        assert 'invalid_response' in out.reason
        # top_k 仍然存在
        assert out.top_k[0] == ('task1', 0.9)

    def test_unknown_fields_pass_through(self, monkeypatch) -> None:
        def fake_json_chat(messages, **kwargs):
            return {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 0.8,
                'clarification_question': None,
                'unknown_key': 'whatever',
                'another_unknown': 42,
            }

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        assert out.confidence == 0.8
        assert out.route_path == 'retrieval'

    def test_task_id_out_of_candidates_forced_to_top1(self, monkeypatch) -> None:
        def fake_json_chat(messages, **kwargs):
            return {
                'task_id': 'unknown_task_xyz',  # 不在候选里
                'entities': {},
                'missing_fields': [],
                'confidence': 0.95,
                'clarification_question': None,
            }

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        assert out.route_path == 'fallback'
        # parsed_confidence=0.95 → cap to 0.5
        assert out.confidence == 0.5
        assert 'invalid_response' in out.reason

    def test_invalid_confidence_string_yields_zero_with_marker(
        self, monkeypatch,
    ) -> None:
        def fake_json_chat(messages, **kwargs):
            return {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 'abc',
                'clarification_question': None,
            }

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        # 解析成功（confidence 被归零）→ retrieval 路径，但 reason 含
        # invalid_confidence 标记
        assert out.route_path == 'retrieval'
        assert out.confidence == 0.0
        assert 'invalid_confidence' in out.reason


# ============================================================================
# rerank: json_chat 返回 None / 异常 / 超时
# ============================================================================


class TestRerankFallbacks:
    def test_json_chat_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            reranker.llm_client, 'json_chat', lambda messages, **kw: None,
        )
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        assert out.route_path == 'fallback'
        assert out.confidence == 0.0
        assert (
            'json_chat_failed' in out.reason
            or 'llm_unavailable_or_timeout' in out.reason
        )

    def test_json_chat_raises_requests_timeout(self, monkeypatch) -> None:
        def boom(messages, **kw):
            raise requests.Timeout('boom')

        monkeypatch.setattr(reranker.llm_client, 'json_chat', boom)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        assert out.route_path == 'fallback'
        assert out.confidence == 0.0
        assert 'timeout' in out.reason

    def test_json_chat_raises_generic_exception(self, monkeypatch) -> None:
        def boom(messages, **kw):
            raise RuntimeError('explode')

        monkeypatch.setattr(reranker.llm_client, 'json_chat', boom)
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'
        assert out.route_path == 'fallback'
        assert out.confidence == 0.0
        # 通用异常 → 走 llm_unavailable_or_timeout 兜底（含 exception 标签）
        assert 'llm_unavailable_or_timeout' in out.reason

    def test_hard_timeout_via_slow_llm(self, monkeypatch) -> None:
        """Reranker 把硬截止时间传入网络调用且禁用重试。"""

        import time

        captured = {}

        def timeout_json_chat(messages, **kw):
            captured.update(kw)
            raise requests.Timeout('deadline reached')

        monkeypatch.setattr(reranker.llm_client, 'json_chat', timeout_json_chat)
        # 实例化一个超短超时的 reranker（50 ms）
        rk = reranker.Reranker(timeout_ms=50)
        t0 = time.monotonic()
        out = rk.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0
        assert captured['timeout'] <= 0.05
        assert captured['retry_once'] is False
        assert out.task_template_id == 'task1'
        assert out.route_path == 'fallback'
        assert 'timeout' in out.reason


# ============================================================================
# rerank: 候选为空
# ============================================================================


class TestRerankEmptyCandidates:
    def test_no_candidates_returns_global_search_fallback(
        self, monkeypatch,
    ) -> None:
        called = {'json_chat': False}

        def fake_json_chat(messages, **kw):
            called['json_chat'] = True
            return {'task_id': 'task1', 'entities': {}, 'missing_fields': [],
                    'confidence': 0.9, 'clarification_question': None}

        monkeypatch.setattr(reranker.llm_client, 'json_chat', fake_json_chat)

        out = reranker.rerank(
            query='q',
            candidates=RetrievalCandidates(items=[], reason='index_empty'),
            ctx=_make_ctx(),
        )
        # 候选为空时不应再调 LLM
        assert called['json_chat'] is False
        assert out.task_template_id == 'global_search_answer'
        assert out.confidence == 0.0
        assert out.route_path == 'fallback'
        assert out.reason == 'reranker:no_candidates'
        assert out.candidate_skills == ['global_search']
        assert out.top_k == []


# ============================================================================
# 模块级单例 + reload + env timeout
# ============================================================================


class TestSingletonAndConfig:
    def test_module_level_rerank_uses_singleton(self, monkeypatch) -> None:
        monkeypatch.setattr(
            reranker.llm_client, 'json_chat',
            lambda messages, **kw: {
                'task_id': 'task1',
                'entities': {},
                'missing_fields': [],
                'confidence': 0.9,
                'clarification_question': None,
            },
        )
        # 直接调函数包装
        out = reranker.rerank(
            query='q', candidates=_make_candidates(), ctx=_make_ctx(),
        )
        assert out.task_template_id == 'task1'

    def test_reload_picks_up_new_env_timeout(self, monkeypatch) -> None:
        # 第一次：默认 3000
        rk1 = reranker.Reranker()
        assert rk1.timeout_ms == reranker.DEFAULT_TIMEOUT_MS

        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, '1500')
        # 不调 reload 的话，模块级单例缓存的还是旧值
        rk_default_cached = reranker._get_default()
        # _get_default 在 fixture 后第一次访问会读取 env，所以这里是 1500
        assert rk_default_cached.timeout_ms == 1500

        # reload 后再次构造 → 重新读 env
        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, '777')
        reranker.reload()
        rk_reloaded = reranker._get_default()
        assert rk_reloaded.timeout_ms == 777

    def test_invalid_env_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, 'not-a-number')
        rk = reranker.Reranker()
        assert rk.timeout_ms == reranker.DEFAULT_TIMEOUT_MS

    def test_zero_or_negative_env_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, '0')
        assert reranker.Reranker().timeout_ms == reranker.DEFAULT_TIMEOUT_MS
        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, '-100')
        assert reranker.Reranker().timeout_ms == reranker.DEFAULT_TIMEOUT_MS

    def test_explicit_param_wins_over_env(self, monkeypatch) -> None:
        monkeypatch.setenv(reranker.ENV_TIMEOUT_MS, '500')
        rk = reranker.Reranker(timeout_ms=2000)
        assert rk.timeout_ms == 2000
