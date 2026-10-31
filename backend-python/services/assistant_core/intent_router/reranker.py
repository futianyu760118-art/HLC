"""Reranker：把 Retriever 给的 Top-K 候选丢给 LLM 重排，输出严格 JSON。

设计目标（对齐任务 7 与 Requirements 1.3 / 1.4 / 1.5 / 1.6 / 7.2 / 7.4 /
9.4 / 9.5）：

* :meth:`Reranker.build_prompt(query, candidates, role, history)` 构造一个
  ``[system, user]`` 双消息列表：

  - system 限定「只能从给定候选选 ``task_id``；不得创造未列出的 id；输出
    严格 JSON 含 ``task_id, entities, missing_fields, confidence,
    clarification_question``」。
  - 列出候选的 ``(task_id, score, source_text)``；``source_text`` 按 80
    字符截断避免 prompt 过长。
  - 历史取最后 4 条原文，每条按 120 字符截断（与
    :func:`router.llm_route` 风格保持一致）。

* :meth:`Reranker.parse_strict_json(raw, allowed_task_ids)`：把 LLM 给的
  原始 JSON 清洗为内部 dict；未知字段忽略，``confidence`` 非法时归零并
  记录 ``invalid_confidence`` 标记到 ``reason``，``task_id`` 不在白名单时
  整个返回 ``None``，让 :meth:`Reranker.rerank` 走 Top-1 兜底。

* :meth:`Reranker.rerank(query, candidates, ctx)`：

  1. ``candidates.items`` 为空 → 直接降级为 ``global_search_answer`` 兜底
     （``route_path='fallback'``，``reason='reranker:no_candidates'``）。
  2. 将硬截止时间直接传给 ``llm_client.json_chat`` 的网络超时，截止时间由
     ``ASSISTANT_INTENT_ROUTER_RERANKER_TIMEOUT_MS`` 控制（默认 3000ms）；
     超时 / 抛异常 / 返回 None → 选 ``candidates.items[0]``，confidence=0
     + ``reason='reranker:llm_unavailable_or_timeout'``。
  3. ``parse_strict_json`` 返回 None（缺字段 / task_id 越界）→ 选
     ``candidates.items[0]``，confidence=
     ``min(parsed_confidence_if_any, low_threshold)``，
     ``reason='reranker:invalid_response[:detail]'``。
  4. 解析成功 → 用 LLM 给的 task_id（已在白名单内），confidence 取 LLM
     返回值，``route_path='retrieval'``。

* 始终把 ``top_k = [(t, s) for t, s, _ in candidates.items]`` 写到
  ``RouterResult.top_k``，给 ConfidenceGate 用。
* 不把 ``ctx.history`` 中的消息原文记到 ``reason`` 中（脱敏）。
* 模块级单例 + 函数包装 ``rerank(...)`` / ``reload()``，与
  :mod:`feature_flag` / :mod:`fastpath` / :mod:`confidence_gate` 同模式。

Validates: Requirements 1.3, 1.4, 1.5, 1.6, 7.2, 7.4, 9.4, 9.5
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from flask import has_app_context

from config import IntentRouterConfig

from .. import llm_client
from ..constants import RISK_LOW
from ..schemas import AssistantContext, RouterResult
from .retriever import RetrievalCandidates


logger = logging.getLogger('hengpintong.assistant.intent_router.reranker')


# ---- 环境变量 / 默认值 ------------------------------------------------------

#: 环境变量名集中登记在 ``config.IntentRouterConfig``；本模块只引用。
ENV_TIMEOUT_MS = IntentRouterConfig.ENV_RERANKER_TIMEOUT_MS

#: 默认硬超时（毫秒），与 Requirement 7.4 对齐。
DEFAULT_TIMEOUT_MS = IntentRouterConfig.DEFAULT_RERANKER_TIMEOUT_MS

#: 默认低置信度阈值（与 ConfidenceGate.DEFAULT_LOW_THRESHOLD 同口径）。
DEFAULT_LOW_THRESHOLD = IntentRouterConfig.DEFAULT_LOW_THRESHOLD

#: source_text 在 prompt 中的最大长度。
_SOURCE_TEXT_MAX_LEN = 80

#: history 单条原文截断长度。
_HISTORY_SNIPPET_MAX_LEN = 120

#: history 取最后多少条进入 prompt。
_HISTORY_TAIL_LEN = 4

#: candidates 完全不可用时的兜底任务 id。
_NO_CANDIDATES_FALLBACK_TASK_ID = 'global_search_answer'
_NO_CANDIDATES_FALLBACK_SKILL = 'global_search'

#: 严格 JSON 中必须出现的字段名（含值可为 null/空，但 key 必须有）。
_REQUIRED_KEYS = ('task_id', 'entities', 'missing_fields',
                  'confidence', 'clarification_question')


# ---- 工具：env 解析 ---------------------------------------------------------

def _parse_timeout_ms(raw: Optional[str]) -> Optional[int]:
    """把 env 字符串解析为正整数毫秒；非法返回 ``None``。"""
    if raw is None or raw == '':
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _resolve_timeout_ms(explicit: Optional[int]) -> int:
    """timeout 优先级：参数 > env > 默认 3000。

    任一侧非法（非正整数 / 非 int）→ 落到默认值；env 也非法时用
    :data:`DEFAULT_TIMEOUT_MS`。
    """
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    parsed = _parse_timeout_ms(os.environ.get(ENV_TIMEOUT_MS))
    if parsed is not None:
        return parsed
    return DEFAULT_TIMEOUT_MS


# ---- Reranker ---------------------------------------------------------------


class Reranker:
    """LLM 重排器：把候选 + 查询丢给 LLM，让它在白名单里挑一个。

    无状态除了配置（``low_threshold`` / ``_timeout_seconds``）。可被多个请
    求并发使用；模型调用同步受网络截止时间约束，不留下超时后仍运行的线程。
    """

    def __init__(
        self,
        low_threshold: float = DEFAULT_LOW_THRESHOLD,
        timeout_ms: Optional[int] = None,
    ) -> None:
        try:
            low = float(low_threshold)
        except (TypeError, ValueError):
            low = DEFAULT_LOW_THRESHOLD
        if low < 0.0:
            low = 0.0
        elif low > 1.0:
            low = 1.0
        self._low_threshold = low
        self._timeout_ms = _resolve_timeout_ms(timeout_ms)
        self._timeout_seconds = self._timeout_ms / 1000.0

    # -- 只读属性（便于测试 / 调试） -------------------------------------

    @property
    def low_threshold(self) -> float:
        return self._low_threshold

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    # -- prompt 构造 ------------------------------------------------------

    def build_prompt(
        self,
        query: str,
        candidates: RetrievalCandidates,
        role: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """构造发给 LLM 的 ``[system, user]`` 消息对。

        public，可被单独测试（任务 7.1 覆盖）。
        """
        items = list(candidates.items) if candidates and candidates.items else []
        candidate_lines: List[str] = []
        for task_id, score, source_text in items:
            snippet = (source_text or '')[:_SOURCE_TEXT_MAX_LEN]
            try:
                score_f = float(score)
            except (TypeError, ValueError):
                score_f = 0.0
            candidate_lines.append(
                f'- task_id={task_id} score={score_f:.3f} '
                f'source_text="{snippet}"'
            )
        candidate_block = '\n'.join(candidate_lines) if candidate_lines else '(无)'
        allowed_ids = ', '.join(t for t, _, _ in items) or '(空)'

        system_prompt = (
            '你是恒聘通 HRM 助手的任务重排器（Reranker），不是执行器。\n'
            '严格规则：\n'
            f'1. 只能从下面的候选中选一个 task_id；不得创造未列出的 id。\n'
            f'   候选 task_id 白名单：[{allowed_ids}]\n'
            '2. 输出 *严格 JSON*，必须包含以下键（不得缺失）：\n'
            '   task_id (string), entities (object), missing_fields (string array),\n'
            '   confidence (float in [0,1]), clarification_question (string|null)。\n'
            '   可选键：candidate_skills (string array)。\n'
            '3. 不输出多余字段、不输出 markdown 代码围栏、不输出注释。\n'
            f'当前用户角色：{role or "unknown"}\n\n'
            '候选列表（按相似度降序）：\n'
            f'{candidate_block}\n'
        )

        history_text = _format_history(history)
        user_prompt = (
            f'用户当前查询：{query or ""}\n'
            f'{history_text}'
            '请仅在候选 task_id 中选一个，并输出严格 JSON。'
        )

        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

    # -- JSON 解析 --------------------------------------------------------

    def parse_strict_json(
        self,
        raw: Optional[Dict[str, Any]],
        allowed_task_ids: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """清洗 LLM 给的原始 JSON。

        Returns:
            * ``None`` —— 缺必须字段、或 ``task_id`` 不在 ``allowed_task_ids``
              白名单内（让上层走 Top-1 兜底）。
            * dict —— 含规范化后的 ``task_id`` / ``entities`` /
              ``missing_fields`` / ``confidence`` / ``clarification_question``
              / ``candidate_skills`` / ``reason_extra``。``confidence`` 非法
              时为 0.0，``reason_extra`` 含 ``invalid_confidence`` 字段。
              未知 key 静默忽略。
        """
        if not isinstance(raw, dict):
            return None

        # 必须字段缺失 → None
        for key in _REQUIRED_KEYS:
            if key not in raw:
                return None

        task_id = raw.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            return None
        # task_id 必须 ∈ 候选集；不在则返回 None（上层走 Top-1）。
        if allowed_task_ids and task_id not in allowed_task_ids:
            return None

        entities = raw.get('entities')
        if not isinstance(entities, dict):
            entities = {}

        missing_fields_raw = raw.get('missing_fields')
        if isinstance(missing_fields_raw, list):
            missing_fields = [str(x) for x in missing_fields_raw if x is not None]
        else:
            missing_fields = []

        clarification_question = raw.get('clarification_question')
        if clarification_question is not None and not isinstance(
            clarification_question, str,
        ):
            clarification_question = str(clarification_question)

        candidate_skills_raw = raw.get('candidate_skills')
        if isinstance(candidate_skills_raw, list):
            candidate_skills = [
                str(x) for x in candidate_skills_raw if isinstance(x, str) and x
            ]
        else:
            candidate_skills = []

        confidence_raw = raw.get('confidence')
        confidence, conf_reason = _sanitize_confidence(confidence_raw)

        return {
            'task_id': task_id,
            'entities': dict(entities),
            'missing_fields': missing_fields,
            'confidence': confidence,
            'clarification_question': clarification_question,
            'candidate_skills': candidate_skills,
            'reason_extra': conf_reason,  # None 或 'invalid_confidence=...'
        }

    # -- 主入口 -----------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: RetrievalCandidates,
        ctx: AssistantContext,
    ) -> RouterResult:
        """对 ``candidates`` 做 LLM 重排，返回最终的 :class:`RouterResult`。

        永不抛错：所有 LLM / 解析 / 网络异常都被吞掉、走兜底分支，并把
        诊断写到 ``reason`` 字段以便观测。
        """
        items = list(candidates.items) if candidates and candidates.items else []
        top_k = [(task_id, float(score)) for task_id, score, _ in items]

        # 1) 候选为空：直接降级，连 LLM 都不发。
        if not items:
            return RouterResult(
                intent='global_search',
                task_template_id=_NO_CANDIDATES_FALLBACK_TASK_ID,
                confidence=0.0,
                entities={},
                missing_fields=[],
                risk_level=RISK_LOW,
                candidate_skills=[_NO_CANDIDATES_FALLBACK_SKILL],
                requires_confirmation=False,
                clarification_question=None,
                reason='reranker:no_candidates',
                rule_matched=False,
                forbidden_reason=None,
                route_path='fallback',
                top_k=[],
            )

        allowed_task_ids = {task_id for task_id, _, _ in items}
        role = getattr(ctx, 'role', '') or ''
        history = getattr(ctx, 'history', None)

        messages = self.build_prompt(
            query=query, candidates=candidates, role=role, history=history,
        )

        runtime = None
        runtime_audit_context = None
        runtime_max_tokens = 600
        if has_app_context():
            try:
                runtime, runtime_max_tokens, runtime_audit_context = llm_client.prepare_profile_runtime(
                    'small',
                    messages,
                    max_tokens=600,
                    use_case='intent_reranking',
                    resource_domain='assistant',
                    ctx=ctx,
                )
            except Exception:
                logger.exception('reranker_runtime_resolution_failed')
                return self._build_top1_fallback(
                    items=items,
                    top_k=top_k,
                    confidence=0.0,
                    reason='reranker:llm_unavailable_or_timeout:runtime_configuration',
                )

        # 2) 在线程池里跑 json_chat，硬超时回收。运行时配置在主请求线程
        # 解析完成后以不可变对象传入，后台线程不再读取模块环境变量。
        raw_json, llm_error = self._call_llm_with_timeout(
            messages,
            runtime=runtime,
            audit_context=runtime_audit_context,
            max_tokens=runtime_max_tokens,
        )

        if raw_json is None:
            return self._build_top1_fallback(
                items=items,
                top_k=top_k,
                confidence=0.0,
                reason=f'reranker:llm_unavailable_or_timeout:{llm_error}'
                if llm_error else 'reranker:llm_unavailable_or_timeout',
            )

        # 3) 严格解析；失败 → Top-1 兜底
        parsed = self.parse_strict_json(raw_json, allowed_task_ids)
        if parsed is None:
            # 尝试从原始 JSON 取一个 confidence 用作上限提示（容错）。
            parsed_conf, _ = _sanitize_confidence(raw_json.get('confidence'))
            forced_conf = min(parsed_conf, self._low_threshold)
            detail = _summarize_parse_failure(raw_json, allowed_task_ids)
            return self._build_top1_fallback(
                items=items,
                top_k=top_k,
                confidence=forced_conf,
                reason=f'reranker:invalid_response:{detail}',
            )

        # 4) 解析成功：使用 LLM 选择
        task_id = parsed['task_id']
        confidence = parsed['confidence']
        # 解析失败的字段（confidence='abc'）→ reason_extra 不为 None，
        # 同时 confidence 已经被归零；写到 reason 上方便排查。
        reason_extra = parsed.get('reason_extra')
        reason = 'reranker:ok'
        if reason_extra:
            reason = f'reranker:ok|{reason_extra}'

        return RouterResult(
            intent=task_id,
            task_template_id=task_id,
            confidence=confidence,
            entities=parsed['entities'],
            missing_fields=parsed['missing_fields'],
            risk_level=RISK_LOW,
            candidate_skills=parsed['candidate_skills'],
            requires_confirmation=False,
            clarification_question=parsed['clarification_question'],
            reason=reason,
            rule_matched=False,
            forbidden_reason=None,
            route_path='retrieval',
            top_k=top_k,
        )

    # -- 内部：LLM 调用 + 超时 -------------------------------------------

    def _call_llm_with_timeout(
        self,
        messages: List[Dict[str, str]],
        *,
        runtime: Optional[Any] = None,
        audit_context: Optional[Dict[str, Any]] = None,
        max_tokens: int = 600,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """同步调 ``json_chat``，网络超时不超过路由截止时间。

        - 正常返回：``(dict, None)``
        - LLM 返回 None：``(None, 'json_chat_failed')``
        - 抛 ``requests.Timeout``：``(None, 'timeout')``
        - 其它异常：``(None, 'exception')``
        """
        payload = _invoke_json_chat(
            messages,
            runtime,
            audit_context,
            max_tokens,
            self._timeout_seconds,
        )

        if payload is _SENTINEL_TIMEOUT:
            return None, 'timeout'
        if payload is _SENTINEL_EXCEPTION:
            return None, 'exception'
        if payload is None:
            return None, 'json_chat_failed'
        if not isinstance(payload, dict):
            return None, 'json_chat_non_dict'
        return payload, None

    # -- 内部：Top-1 兜底 ------------------------------------------------

    def _build_top1_fallback(
        self,
        items: List[Tuple[str, float, str]],
        top_k: List[Tuple[str, float]],
        confidence: float,
        reason: str,
    ) -> RouterResult:
        top1_task_id = items[0][0]
        capped = min(max(float(confidence), 0.0), self._low_threshold)
        return RouterResult(
            intent=top1_task_id,
            task_template_id=top1_task_id,
            confidence=capped,
            entities={},
            missing_fields=[],
            risk_level=RISK_LOW,
            candidate_skills=[],
            requires_confirmation=False,
            clarification_question=None,
            reason=reason,
            rule_matched=False,
            forbidden_reason=None,
            route_path='fallback',
            top_k=top_k,
        )


# ---- 辅助：confidence 清洗（与 schemas._sanitize_confidence 对齐但更轻） ----

def _sanitize_confidence(raw: Any) -> Tuple[float, Optional[str]]:
    """清洗 confidence；返回 ``(value, reason_tag)``。

    - 合法 ``[0,1]`` 浮点：``(value, None)``。
    - 非法 / 越界 / NaN / inf：``(0.0, 'invalid_confidence=<repr>')``。
    """
    if isinstance(raw, bool):
        return 0.0, f'invalid_confidence={raw!r}'
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0, f'invalid_confidence={raw!r}'
    if value != value or value in (float('inf'), float('-inf')):
        return 0.0, f'invalid_confidence={raw!r}'
    if value < 0.0 or value > 1.0:
        return 0.0, f'invalid_confidence={raw!r}'
    return value, None


def _format_history(
    history: Optional[List[Dict[str, Any]]],
) -> str:
    """与 :func:`router.llm_route` 风格一致：取最后 4 条，每条 120 字符。"""
    if not history:
        return ''
    tail = list(history)[-_HISTORY_TAIL_LEN:]
    if not tail:
        return ''
    lines = []
    for entry in tail:
        if not isinstance(entry, dict):
            continue
        role = entry.get('role') or 'user'
        content = entry.get('content') or ''
        if not isinstance(content, str):
            content = str(content)
        snippet = content[:_HISTORY_SNIPPET_MAX_LEN]
        lines.append(f'[{role}] {snippet}')
    if not lines:
        return ''
    body = '\n'.join(lines)
    return f'最近对话历史：\n{body}\n'


def _summarize_parse_failure(
    raw_json: Dict[str, Any], allowed_task_ids: Set[str],
) -> str:
    """构造一条简短的解析失败原因，用于 ``RouterResult.reason``。"""
    if not isinstance(raw_json, dict):
        return 'non_dict_payload'
    missing = [k for k in _REQUIRED_KEYS if k not in raw_json]
    if missing:
        return f'missing_fields={missing}'
    task_id = raw_json.get('task_id')
    if not isinstance(task_id, str) or not task_id:
        return 'invalid_task_id_type'
    if allowed_task_ids and task_id not in allowed_task_ids:
        return f'task_id_out_of_candidates={task_id!r}'
    return 'unknown_parse_error'


# ---- 内部：在线程中调 json_chat，把异常转成 sentinel ------------------------

class _Sentinel:
    """简单的标记类型，用于线程返回值识别（避免与正常 dict 冲突）。"""

    __slots__ = ('_label',)

    def __init__(self, label: str) -> None:
        self._label = label

    def __repr__(self) -> str:  # pragma: no cover
        return f'_Sentinel({self._label!r})'


_SENTINEL_TIMEOUT = _Sentinel('timeout')
_SENTINEL_EXCEPTION = _Sentinel('exception')


def _invoke_json_chat(
    messages: List[Dict[str, str]],
    runtime: Optional[Any] = None,
    audit_context: Optional[Dict[str, Any]] = None,
    max_tokens: int = 600,
    timeout_seconds: Optional[float] = None,
) -> Any:
    """线程内调用 ``llm_client.json_chat``，把已知异常转为 sentinel。

    - ``requests.Timeout`` → :data:`_SENTINEL_TIMEOUT`
    - 其它 ``Exception`` → :data:`_SENTINEL_EXCEPTION`
    - 正常返回（dict / None）原样透传。

    通过 ``llm_client.json_chat`` 属性访问，方便测试 monkeypatch。
    """
    def invoke() -> Any:
        return llm_client.json_chat(
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            runtime=runtime,
            audit_context=audit_context,
            timeout=timeout_seconds,
            retry_once=False,
        )

    try:
        return invoke()
    except requests.Timeout:
        return _SENTINEL_TIMEOUT
    except Exception:  # noqa: BLE001 - 主路径不允许异常逃逸
        logger.exception('reranker_json_chat_failed')
        return _SENTINEL_EXCEPTION


# ---- 模块级单例 + 函数包装 --------------------------------------------------

_default_lock = threading.Lock()
_default_reranker: Optional[Reranker] = None


def _get_default() -> Reranker:
    """惰性构造模块级单例（按首次访问时的 env 读 timeout）。"""
    global _default_reranker
    if _default_reranker is None:
        with _default_lock:
            if _default_reranker is None:
                _default_reranker = Reranker()
    return _default_reranker


def rerank(
    query: str,
    candidates: RetrievalCandidates,
    ctx: AssistantContext,
) -> RouterResult:
    """模块级 ``rerank`` 包装：使用默认单例。"""
    return _get_default().rerank(query, candidates, ctx)


def reload() -> None:
    """重置默认单例：下一次 ``rerank`` 重新读 env。"""
    global _default_reranker
    with _default_lock:
        _default_reranker = None


__all__ = [
    'DEFAULT_LOW_THRESHOLD',
    'DEFAULT_TIMEOUT_MS',
    'ENV_TIMEOUT_MS',
    'Reranker',
    'rerank',
    'reload',
]
