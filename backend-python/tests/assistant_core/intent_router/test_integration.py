"""Task 17 —— 集成测试：四条主路径在 mock SiliconFlow 下端到端跑通。

**Validates: Requirements 1.1, 2.2, 3.1, 3.4, 5.2, 8.1, 12.4**

四条主路径覆盖：

1. **retrieval + rerank 正常路径**（17.1，Req 1.1）：FeatureFlag 开启，
   patched ``Retriever`` 返回带 ``recent_resume_analysis`` 的候选，
   patched ``/chat/completions`` 返回高置信度重排 JSON →
   ``route_path='retrieval'``，``confidence > 0.75``。
2. **FastPath 高风险薪酬**（17.2，Req 2.2 / 5.2）：role=employee + 关键词
   `工资` → FastPath 命中 → PermissionGate 改写为
   ``permission_denied_response``；零 LLM / embedding 调用。
3. **澄清轮**（17.3，Req 3.1 / 3.4）：第一轮 confidence ∈ [0.50, 0.75] →
   ConfidenceGate 输出 ClarificationWidget；第二轮 message 等于某个
   ``option.payload`` → orchestrator._maybe_merge_clarification_reply
   合并为新 query → 第二轮高置信度命中目标任务。
4. **嵌入服务不可用 → legacy_fallback**（17.4，Req 8.1 / 12.4）：
   ``/embeddings`` 返回 500 → ``Retriever.retrieve`` 返回
   ``reason='embedding_unavailable'`` → 流水线走 legacy_fallback；
   ``/chat/completions`` 不被调用。

测试约束：

* 一切 HTTP 调用均通过 monkeypatch 替换 ``requests.post``；不发起真实网络请求。
* 不依赖真实 DB：通过 ``monkeypatch`` 替换 ``memory.save_turn`` 与
  ``query_cache``，并把 ``executor`` 的 LLM 总结桩成空字符串以避免在路由层
  之外触发额外的 LLM 调用。
* 每个用例运行时间预算 < 5s。
* 使用 caplog 捕获 ``assistant_query_done`` 日志，验证 ``routePath`` 字段。

设计要点：``embedding_client`` 与 ``llm_client`` 都 ``import requests`` ——
这两个模块拿到的 ``requests`` 是**同一对象**，所以两侧的
``monkeypatch.setattr(..., 'post', ...)`` 会互相覆盖。本文件用单一调度器
按 URL 区分 ``/embeddings`` 与 ``/chat/completions``，避免重复 patch 时的
顺序敏感问题。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import pytest

# Ensure backend-python is on sys.path so we can import via 'services.*'.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'),
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core import executor, llm_client, legacy_orchestrator as orchestrator  # noqa: E402
from services.assistant_core.constants import RISK_HIGH  # noqa: E402
from services.assistant_core.intent_router import (  # noqa: E402
    embedding_client,
    feature_flag,
    legacy_pipeline as pipeline,
)
from services.assistant_core.intent_router.retriever import (  # noqa: E402
    RetrievalCandidates,
)
from services.assistant_core.schemas import AssistantContext  # noqa: E402


# ---------------------------------------------------------------------------
# 共享辅助
# ---------------------------------------------------------------------------


def _ctx(
    role: str = 'hr_admin',
    user_id: str = 'int-user',
    history: Optional[List[Dict[str, Any]]] = None,
    **kw: Any,
) -> AssistantContext:
    return AssistantContext(
        user_id=user_id,
        role=role,
        session_id=kw.pop('session_id', 'sess-int'),
        history=history or [],
        request_id=kw.pop('request_id', 'req-int'),
        **kw,
    )


class _FakeResponse:
    """最小化 ``requests.Response`` 替身。"""

    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _embedding_response(vectors: List[List[float]]) -> _FakeResponse:
    """构造 SiliconFlow ``/embeddings`` 200 响应。"""

    return _FakeResponse(200, {'data': [{'embedding': v} for v in vectors]})


def _chat_completion_response(payload: Dict[str, Any]) -> _FakeResponse:
    """把一段 JSON 包装为 ``/chat/completions`` 风格的响应。"""

    content = json.dumps(payload, ensure_ascii=False)
    return _FakeResponse(200, {
        'choices': [{'message': {'content': content}}],
    })


# ---------------------------------------------------------------------------
# 共享 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_v2(monkeypatch: pytest.MonkeyPatch):
    """启用 FeatureFlag v2 + 100% rollout，让所有用例都走新流水线。"""

    monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_V2_ENABLED', 'true')
    monkeypatch.setenv('ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT', '100')
    feature_flag.reload()
    yield
    feature_flag.reload()


@pytest.fixture(autouse=True)
def _patch_save_turn(monkeypatch: pytest.MonkeyPatch):
    """Mock memory.save_turn，避免触碰 DB；返回固定 session_id。"""

    captured: List[Dict[str, Any]] = []

    def fake_save(**kwargs: Any) -> str:
        captured.append(dict(kwargs))
        return kwargs.get('session_id') or 'sess-int'

    monkeypatch.setattr(orchestrator.memory, 'save_turn', fake_save)
    return captured


@pytest.fixture(autouse=True)
def _patch_cache(monkeypatch: pytest.MonkeyPatch):
    """关掉 orchestrator 缓存，保持每次执行确定性。"""

    class _NullCache:
        def get(self, *a: Any, **kw: Any) -> None:
            return None

        def put(self, *a: Any, **kw: Any) -> None:
            return None

    monkeypatch.setattr(orchestrator, 'query_cache', _NullCache(), raising=True)


@pytest.fixture(autouse=True)
def _patch_summarizer(monkeypatch: pytest.MonkeyPatch):
    """关掉 executor 的 LLM 总结器，让端到端测试不计入额外的 ``/chat/completions``。

    任务 17 的关注点在路由层：``executor._summarize_llm`` 的调用属于 *
    下游* 工作（生成中文总结），按本测试的口径不应被纳入 router 的 chat
    调用计数。把这个 helper 桩成空字符串可以同时避免：

    * 增加 chat 调用计数干扰断言；
    * 在 17.4 嵌入失败用例中 executor 仍尝试总结，但 chat handler 是 boom。
    """

    monkeypatch.setattr(executor, '_summarize_llm', lambda *a, **kw: '')


@pytest.fixture(autouse=True)
def _reset_pipeline_singletons(monkeypatch: pytest.MonkeyPatch):
    """跳过索引懒构建，并把 ``RetrievalIndex`` 标为非空。

    ``pipeline._retrieval_index`` 是模块级单例，懒构建会触发真实嵌入调用。
    这里直接把 ``_index_build_attempted`` 置为 True，并把 ``is_empty`` 桩成
    False。具体路径由各 case 决定：

    * 17.1 / 17.3 直接 monkeypatch ``pipeline._retriever.retrieve``，跳过索引。
    * 17.2 走 FastPath，根本不会调 ``Retriever``。
    * 17.4 *不* patch ``retrieve``，借 ``is_empty=False`` 让 ``Retriever``
      走到 ``embedding_client.embed``，真正命中 mock 的 ``/embeddings`` 500
      路径，验证 ``REASON_EMBEDDING_UNAVAILABLE`` 触发 legacy_fallback。
    """

    monkeypatch.setattr(pipeline, '_index_build_attempted', True, raising=False)
    monkeypatch.setattr(
        pipeline._retrieval_index, 'is_empty', lambda: False, raising=False,
    )
    yield


@pytest.fixture
def _patch_post(monkeypatch: pytest.MonkeyPatch):
    """单一 ``requests.post`` 调度器，按 URL 把请求分发给 embedding / chat 处理器。

    设计取舍：``embedding_client`` 与 ``llm_client`` 都做 ``import requests`` ——
    两侧拿到的 ``requests`` 是**同一对象**，分别 ``monkeypatch.setattr(...)``
    会互相覆盖。这里只 patch 一次，按 URL 分发。

    Yields:
        ``(embed_record, chat_record, embed_state, chat_state)``：分别是
        embeddings / chat completions 的调用记录列表与 ``{'handler': ...}``
        状态字典。``handler`` 可以是 ``_FakeResponse`` / 异常 / ``Callable
        (url, body) -> _FakeResponse``。
    """

    embed_record: List[Dict[str, Any]] = []
    chat_record: List[Dict[str, Any]] = []
    embed_state: Dict[str, Any] = {
        'handler': _FakeResponse(500, {'error': 'no embed handler'}),
    }
    chat_state: Dict[str, Any] = {
        'handler': _FakeResponse(500, {'error': 'no chat handler'}),
    }

    def _dispatch(url: str, headers: Optional[Dict[str, str]] = None,
                  json: Optional[Dict[str, Any]] = None,
                  timeout: Optional[float] = None, **kw: Any):
        record_entry = {'url': url, 'json': json, 'timeout': timeout}
        if '/embeddings' in url:
            embed_record.append(record_entry)
            handler = embed_state['handler']
        else:
            # 默认归入 chat（``/chat/completions``）。
            chat_record.append(record_entry)
            handler = chat_state['handler']
        if isinstance(handler, BaseException):
            raise handler
        if callable(handler):
            return handler(url, json)
        return handler

    monkeypatch.setattr(embedding_client.requests, 'post', _dispatch)
    # 双侧都显式 patch（实际是同一对象，但若未来 ``llm_client`` 改为
    # ``from requests import post``，这里仍然能命中）。
    monkeypatch.setattr(llm_client.requests, 'post', _dispatch)

    monkeypatch.setenv('SILICONFLOW_API_KEY', 'fake-key')
    monkeypatch.setattr(llm_client, 'API_KEY', 'fake-key', raising=False)
    embedding_client.clear_corpus_cache()

    yield embed_record, chat_record, embed_state, chat_state

    embedding_client.clear_corpus_cache()


# ---------------------------------------------------------------------------
# 17.1 retrieval + rerank 正常路径
# ---------------------------------------------------------------------------


def test_retrieval_rerank_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    _patch_post,
) -> None:
    """`Retriever` 给出 Top-K 候选，``/chat/completions`` 返回高置信度
    重排结果 → ``route_path='retrieval'``，``confidence > 0.75``。

    Validates: Requirements 1.1, 1.2, 1.3, 1.4
    """

    embed_record, chat_record, _embed_state, chat_state = _patch_post

    # 直接 patch Retriever，跳过 embedding/index 路径，让候选稳定可复现。
    # （任务 17 推荐策略之一：用固定 RetrievalCandidates 避免索引构建的不确定性。）
    def fake_retrieve(query: str, k: int = 5) -> RetrievalCandidates:
        return RetrievalCandidates(
            items=[
                ('recent_resume_analysis', 0.92, '最近一周高分简历'),
                ('recruitment_overview', 0.61, '招聘概览'),
                ('global_search_answer', 0.40, '兜底搜索'),
            ],
            reason=None,
        )

    monkeypatch.setattr(pipeline._retriever, 'retrieve', fake_retrieve)

    # /chat/completions 返回严格 JSON：高置信度命中 recent_resume_analysis。
    chat_state['handler'] = _chat_completion_response({
        'task_id': 'recent_resume_analysis',
        'entities': {'recent_days': 7},
        'missing_fields': [],
        'confidence': 0.85,
        'clarification_question': None,
    })

    ctx = _ctx(role='hr_admin', user_id='hr-1', session_id='sess-rr')
    with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
        result = orchestrator.run('最近一周来了几份高分简历', ctx)

    # ---- 路由结果断言 ----
    assert result.router is not None
    assert result.router.task_template_id == 'recent_resume_analysis'
    assert result.router.route_path == 'retrieval'
    assert result.router.confidence > 0.75
    # 重排结果给出的实体应当透传到 RouterResult。
    assert result.router.entities.get('recent_days') == 7
    # candidate_skills 必须 ⊆ skill_registry（pipeline 的 _enforce_postconditions
    # 已经做过过滤；这里只校验都已注册）。
    from services.assistant_core import skill_registry
    for sid in result.router.candidate_skills:
        assert skill_registry.exists(sid), f'unregistered skill leaked: {sid}'

    # ---- HTTP 调用计数：仅一次 /chat/completions；零 /embeddings ----
    assert embed_record == [], (
        f'/embeddings should not be called when Retriever is patched, got '
        f'{len(embed_record)} call(s)'
    )
    chat_calls = [r for r in chat_record if '/chat/completions' in r['url']]
    assert len(chat_calls) == 1, (
        f'expected exactly one /chat/completions call, got {len(chat_calls)}'
    )

    # ---- 结构化日志断言 ----
    log_records = [r for r in caplog.records if r.message == 'assistant_query_done']
    assert len(log_records) == 1
    assert getattr(log_records[0], 'routePath') == 'retrieval'
    # topK 至少包含 chosen task。
    top_k = getattr(log_records[0], 'topK')
    assert isinstance(top_k, list) and len(top_k) >= 1
    assert top_k[0][0] == 'recent_resume_analysis'


# ---------------------------------------------------------------------------
# 17.2 FastPath 高风险薪酬
# ---------------------------------------------------------------------------


def test_fastpath_payroll_denied_for_employee(
    caplog: pytest.LogCaptureFixture,
    _patch_post,
) -> None:
    """``employee`` 角色查薪酬：FastPath 命中 → PermissionGate 改写为
    ``permission_denied_response``；零 LLM / embedding 调用。

    Validates: Requirements 2.2, 5.2, 5.3
    """

    embed_record, chat_record, embed_state, chat_state = _patch_post

    # 任何 LLM / embedding 调用都视为测试失败：FastPath 应该在调到下游之前命中。
    def boom_handler(url: str, body: Optional[Dict[str, Any]]):
        raise AssertionError(f'unexpected HTTP call to {url}')

    embed_state['handler'] = boom_handler
    chat_state['handler'] = boom_handler

    ctx = _ctx(role='employee', user_id='emp-1', session_id='sess-fp')
    with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
        result = orchestrator.run('帮我查一下小王上个月工资', ctx)

    # ---- 路由结果断言 ----
    assert result.router is not None
    assert result.router.task_template_id == 'permission_denied_response'
    # PermissionGate 在拒绝路径上保留 FastPath 的 route_path 标记。
    assert result.router.route_path == 'fast_path'
    # 高风险锁定 + 非确认（拒绝路径不再要求用户确认）。
    assert result.router.risk_level == RISK_HIGH
    assert result.router.requires_confirmation is False
    # 候选技能被清空，避免下游误用。
    assert result.router.candidate_skills == []
    # 拒绝原因写入 reason，便于观测。
    assert 'permission_gate:role_not_allowed:employee' in (result.router.reason or '')

    # ---- HTTP 调用计数：FastPath 必须零调用 ----
    assert embed_record == [], f'unexpected /embeddings calls: {embed_record}'
    assert chat_record == [], f'unexpected /chat/completions calls: {chat_record}'

    # ---- 结构化日志断言 ----
    log_records = [r for r in caplog.records if r.message == 'assistant_query_done']
    assert len(log_records) == 1
    assert getattr(log_records[0], 'routePath') == 'fast_path'


# ---------------------------------------------------------------------------
# 17.3 澄清轮（两轮）
# ---------------------------------------------------------------------------


def test_clarification_two_round_flow(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    _patch_post,
    _patch_save_turn,
) -> None:
    """第一轮 confidence 落入窗口 → ClarificationWidget；第二轮回答某个
    ``option.payload`` → orchestrator 合并 origin_message 后再次路由命中
    高置信度任务。

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """

    embed_record, chat_record, _embed_state, chat_state = _patch_post

    # 两轮路由都用同一份候选（包含目标任务 attendance_exception_analysis）。
    candidates = RetrievalCandidates(
        items=[
            ('employee_lookup', 0.62, '员工查询'),
            ('attendance_exception_analysis', 0.58, '考勤异常分析'),
            ('global_search_answer', 0.40, '兜底搜索'),
        ],
        reason=None,
    )
    monkeypatch.setattr(
        pipeline._retriever, 'retrieve', lambda q, k=5: candidates,
    )

    # /chat/completions 按调用次序切换响应：
    # 第一次（首轮 message='看看小王'）→ confidence 0.6 落入 [0.50, 0.75] 窗口。
    # 第二次（合并后 message='看看小王 attendance_exception_analysis'）→
    #   高置信度 0.92。
    chat_call_log: List[Dict[str, Any]] = []

    def chat_handler(url: str, body: Optional[Dict[str, Any]]):
        chat_call_log.append(body or {})
        if len(chat_call_log) == 1:
            return _chat_completion_response({
                'task_id': 'attendance_exception_analysis',
                'entities': {'employee': '小王'},
                'missing_fields': [],
                'confidence': 0.6,
                'clarification_question': '你想查小王的什么信息？',
            })
        return _chat_completion_response({
            'task_id': 'attendance_exception_analysis',
            'entities': {'employee': '小王', 'keyword': '考勤'},
            'missing_fields': [],
            'confidence': 0.92,
            'clarification_question': None,
        })

    chat_state['handler'] = chat_handler

    # ---- 第一轮：模糊查询触发澄清 -------------------------------------
    ctx_round1 = _ctx(role='hr_admin', user_id='hr-clarify', session_id='sess-cl')
    with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
        result1 = orchestrator.run('看看小王', ctx_round1)
    caplog.clear()

    assert result1.router is not None
    assert result1.router.route_path == 'clarification'
    assert result1.router.requires_confirmation is True
    # ConfidenceGate 从 top_k 推导 clarification_options，目标任务必须在内。
    payloads = [opt['payload'] for opt in result1.router.clarification_options]
    assert 'attendance_exception_analysis' in payloads
    # ExecutionResult 中要有一个 type=clarification widget（任务 14 的短路逻辑）。
    clarif_widgets = [
        w for w in result1.widgets
        if isinstance(w, dict) and w.get('type') == 'clarification'
    ]
    assert len(clarif_widgets) == 1
    assert clarif_widgets[0]['origin_message'] == '看看小王'
    # 短路澄清不应消费缓存或触发额外 LLM 调用。
    assert len(chat_call_log) == 1, 'first round should trigger exactly one chat call'

    # ---- 构造第二轮 ctx：模拟会话 history 上保留了第一轮的 metadata --
    # orchestrator 在持久化时把 originMessage / clarificationOptions 写入
    # ``meta``，因此这里直接从第一轮的 save_turn 调用回放。
    saved_turns = _patch_save_turn
    assert saved_turns, 'expected save_turn to record the first round'
    last_meta = saved_turns[-1].get('metadata') or {}
    assert last_meta.get('routePath') == 'clarification'
    assert last_meta.get('originMessage') == '看看小王'
    assert last_meta.get('clarificationOptions'), (
        'expected clarificationOptions to be persisted in metadata'
    )

    history_round2 = [
        {'role': 'user', 'content': '看看小王'},
        {
            'role': 'assistant',
            'content': '你想查小王的什么信息？',
            'meta': {
                'routePath': last_meta['routePath'],
                'originMessage': last_meta['originMessage'],
                'clarificationOptions': last_meta['clarificationOptions'],
            },
        },
    ]

    # ---- 第二轮：用户回答一个 payload，orchestrator 合并后重新路由 ----
    ctx_round2 = _ctx(
        role='hr_admin', user_id='hr-clarify', session_id='sess-cl',
        history=history_round2,
    )
    with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
        result2 = orchestrator.run('attendance_exception_analysis', ctx_round2)

    assert result2.router is not None
    assert result2.router.task_template_id == 'attendance_exception_analysis'
    assert result2.router.route_path == 'retrieval'
    assert result2.router.confidence > 0.75

    # 第二次 /chat/completions 调用应当包含合并后的 query 文本。
    # _patch_summarizer 已经把 executor.summarize_llm 桩成空字符串，
    # 因此 chat_call_log 只会被 reranker 路径写入，正好两次。
    assert len(chat_call_log) == 2
    second_body = chat_call_log[1]
    user_messages = [
        m.get('content') for m in (second_body.get('messages') or [])
        if isinstance(m, dict) and m.get('role') == 'user'
    ]
    merged_signal = '看看小王 attendance_exception_analysis'
    assert any(merged_signal in (msg or '') for msg in user_messages), (
        f'expected merged origin_message in second LLM call, got: {user_messages}'
    )

    # 仍然没有真实 /embeddings 调用（patched retrieve）。
    assert embed_record == []

    # 第二轮日志 routePath='retrieval'。
    log_records = [r for r in caplog.records if r.message == 'assistant_query_done']
    assert any(getattr(r, 'routePath', None) == 'retrieval' for r in log_records)


# ---------------------------------------------------------------------------
# 17.4 嵌入服务不可用 → legacy_fallback
# ---------------------------------------------------------------------------


def test_embedding_unavailable_legacy_fallback(
    caplog: pytest.LogCaptureFixture,
    _patch_post,
) -> None:
    """``/embeddings`` 返回 500 → ``Retriever`` 报告 ``embedding_unavailable``
    → IntentRouter 走 legacy_fallback 路径，调用 LegacyRouter 完成请求。

    Validates: Requirements 8.1, 12.4
    """

    embed_record, chat_record, embed_state, chat_state = _patch_post

    # /embeddings 服务不可用：返回 500，让 embedding_client.embed → None。
    embed_state['handler'] = _FakeResponse(500, {'error': 'service unavailable'})

    # /chat/completions 在本路径不应被 *router* 调用：legacy router 走规则匹配，
    # '高分简历' 在 DOMAIN_RULES 里命中且 confidence ≥ 0.78，跳过 LLM。
    # _patch_summarizer 已经把 executor 总结桩掉，所以 chat 也不会被 executor
    # 间接调用。
    def chat_should_not_run(url: str, body: Optional[Dict[str, Any]]):
        raise AssertionError(
            f'unexpected /chat/completions call on legacy_fallback path: '
            f'body keys={list(body.keys()) if body else None}'
        )

    chat_state['handler'] = chat_should_not_run

    ctx = _ctx(role='hr_admin', user_id='hr-fallback', session_id='sess-fb')
    with caplog.at_level(logging.INFO, logger='hengpintong.assistant.orchestrator'):
        result = orchestrator.run('最近一周来了几份高分简历', ctx)

    # ---- 路由结果断言 ----
    assert result.router is not None
    assert result.router.route_path == 'legacy_fallback'
    # legacy router 的规则匹配应当落到 recent_resume_analysis（'高分简历' 关键词）。
    assert result.router.task_template_id == 'recent_resume_analysis'

    # ---- HTTP 调用计数 ----
    embed_calls = [r for r in embed_record if '/embeddings' in r['url']]
    chat_calls = [r for r in chat_record if '/chat/completions' in r['url']]
    assert len(embed_calls) >= 1, (
        f'expected at least one /embeddings call (real Retriever path), '
        f'got {len(embed_calls)}'
    )
    assert chat_calls == [], (
        f'/chat/completions should not be called on legacy_fallback, '
        f'got {chat_calls}'
    )

    # ---- 结构化日志断言 ----
    log_records = [r for r in caplog.records if r.message == 'assistant_query_done']
    assert len(log_records) == 1
    assert getattr(log_records[0], 'routePath') == 'legacy_fallback'

