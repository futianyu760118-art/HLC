"""Retriever 协调器：把查询文本变成 ``RetrievalCandidates``。

设计目标（对齐任务 6 与 Requirements 1.2 / 12.4）：

* 入口 :meth:`Retriever.retrieve(query, k=5)`：
    1. 空查询 → 立即返回 ``RetrievalCandidates(items=[], reason='empty_query')``，
       **不调用** embedding_client，保留可观测的失败原因。
    2. ``index.is_empty()`` → 返回 ``reason='index_empty'``，跳过 embed
       调用，避免对一个不可用索引浪费一次嵌入请求（Req 12.4 上层据此回退
       到 LegacyRouter）。
    3. ``embedding_client.embed(query)`` 返回 ``None`` →
       ``reason='embedding_unavailable'``。
    4. ``embed`` 或 ``index.search`` 抛异常 → ``reason='retrieval_failed'``，
       items 为空（异常被吞掉、通过 :data:`observability.LOGGER_NAME` 记录）。
    5. 其它情况返回正常召回结果（``reason=None``）。

* ``embedding_client`` 是 duck-typed 对象，只要求暴露
  ``embed(text) -> Optional[np.ndarray]``。**不**使用 ``embed_corpus``：
  查询文本走非缓存路径（与 :mod:`embedding_client` 设计一致），避免污染稳定
  语料的 LRU 缓存。
* ``index`` 是 duck-typed 对象，只要求暴露 ``is_empty() -> bool`` 与
  ``search(query_vec, k) -> List[Tuple[task_id, score, source_text]]``。
* 任何异常都被捕获并通过 :data:`observability.LOGGER_NAME` 记录，**不向上抛**。
  调用方可以根据 ``reason`` 决定是否回退到 LegacyRouter。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple

import numpy as np

from .observability import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


# ---------------------------------------------------------------------------
# 失败原因常量（暴露为模块级符号，避免上层拼字符串）
# ---------------------------------------------------------------------------

REASON_EMPTY_QUERY = 'empty_query'
REASON_EMBEDDING_UNAVAILABLE = 'embedding_unavailable'
REASON_INDEX_EMPTY = 'index_empty'
REASON_RETRIEVAL_FAILED = 'retrieval_failed'

#: 默认 Top-K，与 Req 1.2 对齐（``Top-K=5``）。
DEFAULT_K = 5


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetrievalCandidates:
    """Retriever 的返回结果。

    Attributes:
        items: ``[(task_id, score, source_text), ...]``，与
            :meth:`RetrievalIndex.search` 返回值结构一致；按相似度降序。
            没有命中或失败时为空列表。
        reason: 失败/空召回的原因码，命中时为 ``None``。
            合法值见模块级 ``REASON_*`` 常量。
    """

    items: List[Tuple[str, float, str]] = field(default_factory=list)
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Duck-typing 协议（仅供静态检查/IDE 提示，运行时不强制）
# ---------------------------------------------------------------------------

class _EmbeddingClientLike(Protocol):
    def embed(self, text: str) -> Optional[np.ndarray]:  # pragma: no cover
        ...


class _IndexLike(Protocol):
    def is_empty(self) -> bool:  # pragma: no cover
        ...

    def search(
        self, query_vec: np.ndarray, k: int = DEFAULT_K,
    ) -> List[Tuple[str, float, str]]:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class Retriever:
    """协调 ``EmbeddingClient`` 与 ``RetrievalIndex`` 的轻量适配器。

    Retriever 自身**无状态**，所有状态都在依赖里：嵌入服务是否可用由
    ``embedding_client`` 决定，索引快照由 ``index`` 持有。这样 Reranker /
    上层 IntentRouter 可以共享一个 Retriever 实例，无需关心生命周期。
    """

    def __init__(
        self,
        embedding_client: _EmbeddingClientLike,
        index: _IndexLike,
    ) -> None:
        self._embedding_client = embedding_client
        self._index = index

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def retrieve(self, query: str, k: int = DEFAULT_K) -> RetrievalCandidates:
        """对 ``query`` 做 Top-K 召回。

        Args:
            query: 用户查询（已经过 EntityMemory 消解的 ResolvedQuery）。
            k: Top-K 上限，默认 5（Req 1.2）。

        Returns:
            :class:`RetrievalCandidates`。失败永远不抛，调用方根据
            ``reason`` 字段决定回退策略。
        """
        # 1) 空查询：早返回，不浪费一次嵌入调用。
        if not isinstance(query, str) or not query.strip():
            return RetrievalCandidates(items=[], reason=REASON_EMPTY_QUERY)

        # 2) 索引为空：直接告诉上层回退；不调用 embedding 也不调用 search。
        try:
            if self._index.is_empty():
                return RetrievalCandidates(items=[], reason=REASON_INDEX_EMPTY)
        except Exception:  # noqa: BLE001 - 防御：is_empty 异常也视作不可用
            logger.exception('retriever_index_is_empty_failed')
            return RetrievalCandidates(items=[], reason=REASON_INDEX_EMPTY)

        # 3) 查询文本走非缓存路径；返回 None 时退化为 embedding_unavailable，
        #    抛异常时退化为 retrieval_failed（与 search 异常同档处理）。
        try:
            vec = self._embedding_client.embed(query)
        except Exception:  # noqa: BLE001 - 防御：嵌入服务异常视作通用检索失败
            logger.exception('retriever_embed_failed')
            return RetrievalCandidates(items=[], reason=REASON_RETRIEVAL_FAILED)
        if vec is None:
            return RetrievalCandidates(
                items=[], reason=REASON_EMBEDDING_UNAVAILABLE,
            )

        # 4) 索引检索；异常时返回 retrieval_failed。
        try:
            items = self._index.search(vec, k)
        except Exception:  # noqa: BLE001 - 防御：search 异常也吞掉
            logger.exception('retriever_search_failed')
            return RetrievalCandidates(items=[], reason=REASON_RETRIEVAL_FAILED)

        # 5) 正常路径：success 时 reason=None。即使 items 为空也算成功
        # （表示索引中没有足够相近的样例），上层会在 ConfidenceGate 里处理。
        return RetrievalCandidates(items=list(items or []), reason=None)


__all__ = [
    'DEFAULT_K',
    'REASON_EMPTY_QUERY',
    'REASON_EMBEDDING_UNAVAILABLE',
    'REASON_INDEX_EMPTY',
    'REASON_RETRIEVAL_FAILED',
    'RetrievalCandidates',
    'Retriever',
]
