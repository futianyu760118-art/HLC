"""Task 6.1 —— Retriever 协调器单元测试。

校验目标：
- 正常召回：``embed`` 返回单位向量、``index.search`` 返回 Top-K 列表时，
  Retriever 应原样返回 ``items`` 且 ``reason`` 为 ``None``。
- ``embed`` 返回 ``None`` → ``reason='embedding_unavailable'``。
- 空 / ``None`` query → ``reason='empty_query'``；**不**调用 ``embed``。
- ``index.is_empty()`` 为 True → ``reason='index_empty'``；**不**调用 ``embed``。
- ``embed`` / ``search`` 抛异常 → ``reason='retrieval_failed'``，``items=[]``。
- 默认 ``k=5``；显式传 ``k`` 必须透传到 ``index.search``。

Validates: Requirements 1.2, 12.4
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pytest

from services.assistant_core.intent_router.retriever import (
    DEFAULT_K,
    REASON_EMBEDDING_UNAVAILABLE,
    REASON_EMPTY_QUERY,
    REASON_INDEX_EMPTY,
    REASON_RETRIEVAL_FAILED,
    RetrievalCandidates,
    Retriever,
)


# ---------------------------------------------------------------------------
# 测试桩
# ---------------------------------------------------------------------------


class FakeEmbeddingClient:
    """记录调用次数与最后一次入参的 ``embed`` mock。"""

    def __init__(
        self,
        return_value: Optional[np.ndarray] = None,
        raise_exc: Optional[BaseException] = None,
    ) -> None:
        self._return_value = return_value
        self._raise_exc = raise_exc
        self.calls: List[str] = []

    def embed(self, text: str) -> Optional[np.ndarray]:
        self.calls.append(text)
        if self._raise_exc is not None:
            raise self._raise_exc
        # 拷贝避免下游修改污染 mock 内部状态
        if self._return_value is None:
            return None
        return self._return_value.copy()


class FakeIndex:
    """对 ``is_empty`` / ``search`` 的可配置 mock。"""

    def __init__(
        self,
        empty: bool = False,
        results: Optional[List[Tuple[str, float, str]]] = None,
        raise_on_search: Optional[BaseException] = None,
        raise_on_is_empty: Optional[BaseException] = None,
    ) -> None:
        self._empty = empty
        self._results = list(results or [])
        self._raise_on_search = raise_on_search
        self._raise_on_is_empty = raise_on_is_empty
        self.search_calls: List[Tuple[np.ndarray, int]] = []
        self.is_empty_calls = 0

    def is_empty(self) -> bool:
        self.is_empty_calls += 1
        if self._raise_on_is_empty is not None:
            raise self._raise_on_is_empty
        return self._empty

    def search(
        self, query_vec: np.ndarray, k: int = DEFAULT_K,
    ) -> List[Tuple[str, float, str]]:
        self.search_calls.append((query_vec, k))
        if self._raise_on_search is not None:
            raise self._raise_on_search
        return list(self._results)


def _unit_vec(n: int = 4) -> np.ndarray:
    """构造一个单位向量（维度可调），方便覆盖默认 4 维。"""
    arr = np.zeros(n, dtype=np.float32)
    arr[0] = 1.0
    return arr


# ---------------------------------------------------------------------------
# 正常召回
# ---------------------------------------------------------------------------


class TestNormalRetrieval:
    def test_normal_retrieval_returns_items_with_reason_none(self) -> None:
        vec = _unit_vec()
        client = FakeEmbeddingClient(return_value=vec)
        results = [('task1', 0.9, 't1a'), ('task2', 0.8, 't2a')]
        index = FakeIndex(results=results)
        retriever = Retriever(client, index)

        out = retriever.retrieve('查一下小王最近的简历')

        assert isinstance(out, RetrievalCandidates)
        assert out.items == results
        assert out.reason is None
        # 依次走过：is_empty -> embed -> search
        assert index.is_empty_calls == 1
        assert client.calls == ['查一下小王最近的简历']
        assert len(index.search_calls) == 1

    def test_default_k_is_5(self) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(results=[])
        Retriever(client, index).retrieve('hello')
        assert index.search_calls[0][1] == DEFAULT_K == 5

    def test_explicit_k_is_passed_through(self) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(results=[])
        Retriever(client, index).retrieve('hello', k=3)
        assert index.search_calls[0][1] == 3

    def test_query_vec_is_forwarded_to_search(self) -> None:
        vec = _unit_vec()
        client = FakeEmbeddingClient(return_value=vec)
        index = FakeIndex(results=[])
        Retriever(client, index).retrieve('q')
        passed_vec, _ = index.search_calls[0]
        # 同一向量被透传（按值比较）
        assert np.array_equal(passed_vec, vec)

    def test_empty_search_results_are_success(self) -> None:
        """``items=[]`` 但 ``reason=None`` 仍是成功路径，调用方据此进入低置信度处理。"""
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(results=[])
        out = Retriever(client, index).retrieve('q')
        assert out.items == []
        assert out.reason is None


# ---------------------------------------------------------------------------
# 空 query / index 空 / 嵌入返回 None
# ---------------------------------------------------------------------------


class TestGuardOrder:
    def test_none_query_returns_empty_query_without_calling_embed(self) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(results=[('task1', 0.9, 't1a')])

        out = Retriever(client, index).retrieve(None)  # type: ignore[arg-type]

        assert out.items == []
        assert out.reason == REASON_EMPTY_QUERY
        # embed 与 is_empty 都不应被调用
        assert client.calls == []
        assert index.is_empty_calls == 0
        assert index.search_calls == []

    @pytest.mark.parametrize('query', ['', '   ', '\t\n'])
    def test_empty_or_whitespace_query_short_circuits(self, query: str) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(results=[('task1', 0.9, 't1a')])

        out = Retriever(client, index).retrieve(query)

        assert out.items == []
        assert out.reason == REASON_EMPTY_QUERY
        assert client.calls == []
        assert index.is_empty_calls == 0
        assert index.search_calls == []

    def test_index_empty_short_circuits_without_embedding(self) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(empty=True)

        out = Retriever(client, index).retrieve('q')

        assert out.items == []
        assert out.reason == REASON_INDEX_EMPTY
        # 一旦 is_empty 命中，绝不能再调 embed / search
        assert client.calls == []
        assert index.search_calls == []

    def test_embed_returns_none_yields_embedding_unavailable(self) -> None:
        client = FakeEmbeddingClient(return_value=None)
        index = FakeIndex(results=[('task1', 0.9, 't1a')])

        out = Retriever(client, index).retrieve('q')

        assert out.items == []
        assert out.reason == REASON_EMBEDDING_UNAVAILABLE
        # embed 被调用过；search 不应被调用
        assert client.calls == ['q']
        assert index.search_calls == []


# ---------------------------------------------------------------------------
# 异常路径
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_embed_raises_yields_retrieval_failed(self) -> None:
        client = FakeEmbeddingClient(raise_exc=RuntimeError('boom'))
        index = FakeIndex(results=[('task1', 0.9, 't1a')])

        out = Retriever(client, index).retrieve('q')

        assert out.items == []
        assert out.reason == REASON_RETRIEVAL_FAILED
        # 异常吞掉，主路径不抛
        assert index.search_calls == []

    def test_search_raises_yields_retrieval_failed(self) -> None:
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(raise_on_search=RuntimeError('search boom'))

        out = Retriever(client, index).retrieve('q')

        assert out.items == []
        assert out.reason == REASON_RETRIEVAL_FAILED
        # embed 已被调用，search 抛异常被吞
        assert client.calls == ['q']
        assert len(index.search_calls) == 1

    def test_is_empty_raises_yields_index_empty(self) -> None:
        """``is_empty`` 异常视为索引不可用，不再继续 embed/search。"""
        client = FakeEmbeddingClient(return_value=_unit_vec())
        index = FakeIndex(raise_on_is_empty=RuntimeError('is_empty boom'))

        out = Retriever(client, index).retrieve('q')

        assert out.items == []
        assert out.reason == REASON_INDEX_EMPTY
        assert client.calls == []
        assert index.search_calls == []


# ---------------------------------------------------------------------------
# RetrievalCandidates 数据类基本性质
# ---------------------------------------------------------------------------


class TestRetrievalCandidatesDataclass:
    def test_default_values_are_empty_and_reason_none(self) -> None:
        rc = RetrievalCandidates()
        assert rc.items == []
        assert rc.reason is None

    def test_factory_default_does_not_share_state(self) -> None:
        """``items`` 默认值用 ``field(default_factory=list)``，多个实例不应共享。"""
        a = RetrievalCandidates()
        b = RetrievalCandidates()
        assert a.items is not b.items
