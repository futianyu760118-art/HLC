"""Task 5.1 —— RetrievalIndex 单元测试。

校验目标：
- 缺少 ``trigger_examples`` 的 TaskTemplate 输出 warning 且不入库；
  description 不能单独支撑入库（Req 12.3）。
- ``search`` Top-K 排序、按 ``task_id`` 去重保留最高分。
- ``reload`` 后下一次 ``search`` 看到的是新值（atomic swap，Req 12.2）。
- 用 ``numpy.allclose`` 校验 cosine 计算等于手工 ``matrix @ query_vec``
  （在归一化向量上即为余弦相似度，Req 12.1）。

Validates: Requirements 12.1, 12.2, 12.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pytest

from services.assistant_core.intent_router import observability as obs
from services.assistant_core.intent_router.retrieval_index import RetrievalIndex


# ---------------------------------------------------------------------------
# 测试桩
# ---------------------------------------------------------------------------


@dataclass
class FakeTask:
    """精简版 TaskTemplate，足够 RetrievalIndex 用。"""
    id: str
    description: str = ''
    trigger_examples: List[str] = field(default_factory=list)


class FakeRegistry:
    def __init__(self, tasks: List[FakeTask]) -> None:
        self._tasks = list(tasks)

    def all_tasks(self) -> List[FakeTask]:
        return list(self._tasks)


def _unit(vec: List[float]) -> np.ndarray:
    """把 list 归一化为单位向量（``float32`` 一维），方便测试构造。"""
    arr = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    return (arr / max(n, 1e-12)).astype(np.float32, copy=False)


class FakeEmbeddingClient:
    """按 ``text -> vec`` 字典返回固定向量；未知文本返回 ``None``。"""

    def __init__(self, mapping: Dict[str, np.ndarray]) -> None:
        self._mapping = dict(mapping)
        self.calls: List[str] = []

    def embed_corpus(self, text: str) -> Optional[np.ndarray]:
        self.calls.append(text)
        vec = self._mapping.get(text)
        return None if vec is None else vec.copy()


# ---------------------------------------------------------------------------
# 共用 fixture：5 个 mock 任务，其中 task5 缺 trigger_examples。
# ---------------------------------------------------------------------------


def _build_5_tasks_and_client():
    """构造 5 个任务 + 对应的 mock embedding 客户端。

    任务约定：
    - task1：trigger_examples=['t1a', 't1b']，description='d1'
        → 入库 3 行（2 条样例 + 1 条 description）
    - task2：trigger_examples=['t2a']，description=''
        → 入库 1 行
    - task3：trigger_examples=['t3a', 't3b', 't3c']，description='d3'
        → 入库 4 行
    - task4：trigger_examples=['t4a']，description='d4'
        → 入库 2 行
    - task5：trigger_examples=[]，description='d5'
        → **不入库**，触发 warning

    向量取 4 维方便手算与比对。
    """
    tasks = [
        FakeTask(id='task1', trigger_examples=['t1a', 't1b'], description='d1'),
        FakeTask(id='task2', trigger_examples=['t2a'], description=''),
        FakeTask(id='task3', trigger_examples=['t3a', 't3b', 't3c'], description='d3'),
        FakeTask(id='task4', trigger_examples=['t4a'], description='d4'),
        FakeTask(id='task5', trigger_examples=[], description='d5'),
    ]
    mapping = {
        # task1
        't1a': _unit([1.0, 0.0, 0.0, 0.0]),
        't1b': _unit([0.9, 0.1, 0.0, 0.0]),
        'd1': _unit([0.8, 0.2, 0.0, 0.0]),
        # task2
        't2a': _unit([0.0, 1.0, 0.0, 0.0]),
        # task3
        't3a': _unit([0.0, 0.0, 1.0, 0.0]),
        't3b': _unit([0.0, 0.1, 0.9, 0.0]),
        't3c': _unit([0.0, 0.2, 0.8, 0.0]),
        'd3': _unit([0.0, 0.3, 0.7, 0.0]),
        # task4
        't4a': _unit([0.0, 0.0, 0.0, 1.0]),
        'd4': _unit([0.1, 0.0, 0.0, 0.9]),
        # task5 不应被嵌入
    }
    return tasks, FakeEmbeddingClient(mapping)


# ---------------------------------------------------------------------------
# build / 入库样例条数 / warning
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_skips_task_without_trigger_examples_and_warns(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        tasks, client = _build_5_tasks_and_client()
        registry = FakeRegistry(tasks)
        idx = RetrievalIndex()

        with caplog.at_level(logging.WARNING, logger=obs.LOGGER_NAME):
            inserted = idx.build(registry, client)

        # task1: 2 + 1 = 3
        # task2: 1 + 0 = 1
        # task3: 3 + 1 = 4
        # task4: 1 + 1 = 2
        # task5: 0
        assert inserted == 10
        assert idx.size() == 10
        assert idx.is_empty() is False

        # 必须输出针对 task5 的 warning，而且没有给 task5 调过 embedding。
        warnings = [
            r for r in caplog.records
            if r.name == obs.LOGGER_NAME
            and r.levelno == logging.WARNING
            and getattr(r, 'task_id', None) == 'task5'
        ]
        assert warnings, 'expected warning for task5 (missing trigger_examples)'

        assert 'd5' not in client.calls, (
            'task5 description should not be embedded when trigger_examples missing'
        )

    def test_build_skips_rows_when_embedding_returns_none(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # 让 task1 的 't1b' 嵌入失败，验证只跳过这一行。
        tasks, client = _build_5_tasks_and_client()
        client._mapping['t1b'] = None  # type: ignore[assignment]

        idx = RetrievalIndex()
        with caplog.at_level(logging.DEBUG, logger=obs.LOGGER_NAME):
            inserted = idx.build(FakeRegistry(tasks), client)

        # 比基线少 1 行
        assert inserted == 9

    def test_is_empty_before_build(self) -> None:
        idx = RetrievalIndex()
        assert idx.is_empty() is True
        assert idx.size() == 0

    def test_build_with_no_eligible_tasks_returns_empty(self) -> None:
        idx = RetrievalIndex()
        registry = FakeRegistry([FakeTask(id='only', trigger_examples=[], description='d')])
        client = FakeEmbeddingClient({})
        inserted = idx.build(registry, client)
        assert inserted == 0
        assert idx.is_empty() is True


# ---------------------------------------------------------------------------
# search Top-K + 去重 + 排序
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_topk_orders_by_score_and_dedupes_by_task_id(self) -> None:
        tasks, client = _build_5_tasks_and_client()
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), client)

        # 查询非常接近 task1 的 't1a'：[1, 0, 0, 0]
        query = _unit([1.0, 0.0, 0.0, 0.0])
        results = idx.search(query, k=5)

        # 必须按相似度降序，且每个 task_id 最多出现一次
        task_ids = [r[0] for r in results]
        assert len(task_ids) == len(set(task_ids)), 'task_id deduplication failed'
        # task1 应排第一，且其代表行是 't1a'（与 query 完全对齐）
        assert task_ids[0] == 'task1'
        assert results[0][2] == 't1a'
        # 任何分数都在 [-1, 1] 区间（归一化向量的 cosine）
        for _tid, score, _src in results:
            assert -1.0 - 1e-6 <= score <= 1.0 + 1e-6
        # 降序
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_keeps_highest_score_per_task_id(self) -> None:
        tasks, client = _build_5_tasks_and_client()
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), client)

        # 查询 [1, 0, 0, 0]：task1 内部 't1a'=1.0 > 't1b' > 'd1'。
        # 验证 task1 命中的源是 't1a'，分数等于矩阵乘法结果中的最大值。
        query = _unit([1.0, 0.0, 0.0, 0.0])
        results = idx.search(query, k=5)
        task1_hits = [r for r in results if r[0] == 'task1']
        assert len(task1_hits) == 1
        assert task1_hits[0][2] == 't1a'
        assert task1_hits[0][1] == pytest.approx(1.0, abs=1e-6)

    def test_search_top_k_truncates(self) -> None:
        tasks, client = _build_5_tasks_and_client()
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), client)

        results = idx.search(_unit([1.0, 0.0, 0.0, 0.0]), k=2)
        assert len(results) == 2

    def test_search_empty_index_returns_empty(self) -> None:
        idx = RetrievalIndex()
        out = idx.search(_unit([1.0, 0.0, 0.0, 0.0]), k=5)
        assert out == []

    def test_search_zero_k_returns_empty(self) -> None:
        tasks, client = _build_5_tasks_and_client()
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), client)
        assert idx.search(_unit([1.0, 0.0, 0.0, 0.0]), k=0) == []

    def test_search_dim_mismatch_returns_empty(self) -> None:
        tasks, client = _build_5_tasks_and_client()
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), client)
        # 维度错误（4D 索引 vs 3D query）
        bad_query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert idx.search(bad_query, k=5) == []


# ---------------------------------------------------------------------------
# cosine 计算与手工 matmul 一致（numpy.allclose）
# ---------------------------------------------------------------------------


class TestCosineComputation:
    def test_search_scores_match_manual_matrix_mul(self) -> None:
        """显式校验：search 返回的分数与 ``matrix @ q`` 完全一致（逐行）。

        通过为每个 task_id 只放一行（避免去重逻辑干扰），可以把 search
        的输出还原为完整的分数向量进行 ``numpy.allclose`` 比较。
        """
        # 每个 task 只 1 条 trigger_example 且无 description，避免去重影响
        tasks = [
            FakeTask(id=f't{i}', trigger_examples=[f'ex{i}'], description='')
            for i in range(4)
        ]
        # 构造已知的单位向量集合
        vectors = [
            _unit([1.0, 0.0, 0.0, 0.0]),
            _unit([0.0, 1.0, 0.0, 0.0]),
            _unit([0.5, 0.5, 0.5, 0.5]),
            _unit([0.1, 0.2, 0.7, 0.0]),
        ]
        mapping = {f'ex{i}': vectors[i] for i in range(4)}
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks), FakeEmbeddingClient(mapping))

        # 任意单位向量做 query
        query = _unit([0.3, 0.7, 0.5, 0.2])

        # 手工真值：M @ q
        manual_matrix = np.vstack(vectors).astype(np.float32)
        expected = manual_matrix @ query

        # search 返回的是 (task_id, score, source_text)；按 t0..t3 顺序还原
        results = idx.search(query, k=4)
        assert len(results) == 4
        score_by_task = {r[0]: r[1] for r in results}
        actual = np.array([score_by_task[f't{i}'] for i in range(4)], dtype=np.float32)

        assert np.allclose(actual, expected, atol=1e-6), (
            f'cosine mismatch: actual={actual} expected={expected}'
        )

        # 同样校验：每个分数 == 对应单位向量的点积（在单位向量上即 cosine）
        for i in range(4):
            cos_i = float(np.dot(vectors[i], query))
            assert score_by_task[f't{i}'] == pytest.approx(cos_i, abs=1e-6)


# ---------------------------------------------------------------------------
# reload atomic swap
# ---------------------------------------------------------------------------


class TestReload:
    def test_reload_swaps_index_so_next_search_sees_new_values(self) -> None:
        # 第一份注册表
        tasks_v1 = [
            FakeTask(id='alpha', trigger_examples=['a1'], description=''),
            FakeTask(id='beta', trigger_examples=['b1'], description=''),
        ]
        client = FakeEmbeddingClient({
            'a1': _unit([1.0, 0.0]),
            'b1': _unit([0.0, 1.0]),
        })
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks_v1), client)

        # 旧索引：query=[1, 0] 必然命中 alpha
        out_v1 = idx.search(_unit([1.0, 0.0]), k=2)
        ids_v1 = [r[0] for r in out_v1]
        assert ids_v1[0] == 'alpha'
        assert set(ids_v1) == {'alpha', 'beta'}

        # 第二份注册表：完全不同的 task 集合
        tasks_v2 = [
            FakeTask(id='gamma', trigger_examples=['g1'], description=''),
            FakeTask(id='delta', trigger_examples=['d1'], description=''),
        ]
        client_v2 = FakeEmbeddingClient({
            'g1': _unit([1.0, 0.0]),
            'd1': _unit([0.0, 1.0]),
        })
        n = idx.reload(FakeRegistry(tasks_v2), client_v2)
        assert n == 2

        # 新索引：alpha/beta 不再可命中；query=[1, 0] 必须命中 gamma
        out_v2 = idx.search(_unit([1.0, 0.0]), k=2)
        ids_v2 = [r[0] for r in out_v2]
        assert set(ids_v2) == {'gamma', 'delta'}
        assert ids_v2[0] == 'gamma'

    def test_reload_to_empty_index_is_handled(self) -> None:
        tasks_v1 = [FakeTask(id='alpha', trigger_examples=['a1'])]
        client = FakeEmbeddingClient({'a1': _unit([1.0, 0.0])})
        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks_v1), client)
        assert idx.is_empty() is False

        # reload 到一个全部缺 trigger_examples 的 registry → 索引应为空
        empty_tasks = [FakeTask(id='only', trigger_examples=[], description='d')]
        n = idx.reload(FakeRegistry(empty_tasks), FakeEmbeddingClient({}))
        assert n == 0
        assert idx.is_empty() is True
        assert idx.search(_unit([1.0, 0.0]), k=5) == []

    def test_search_snapshot_is_consistent_during_concurrent_reload(self) -> None:
        """简单的并发健全性检查：在 reload 与 search 交替时，
        search 始终看到一致快照（不会 panic 也不会拼 partial 矩阵）。

        这里不追求严格触发竞争，只确保 API 在多线程同时调用时不会抛出。
        """
        import threading

        tasks_v1 = [FakeTask(id='alpha', trigger_examples=['a1'])]
        tasks_v2 = [FakeTask(id='beta', trigger_examples=['b1'])]
        client_v1 = FakeEmbeddingClient({'a1': _unit([1.0, 0.0])})
        client_v2 = FakeEmbeddingClient({'b1': _unit([0.0, 1.0])})

        idx = RetrievalIndex()
        idx.build(FakeRegistry(tasks_v1), client_v1)

        errors: List[BaseException] = []
        stop = threading.Event()

        def hammer_search() -> None:
            try:
                while not stop.is_set():
                    out = idx.search(_unit([1.0, 0.0]), k=2)
                    # 每次返回的 task_id 一定属于已知集合
                    for r in out:
                        assert r[0] in ('alpha', 'beta')
            except BaseException as e:  # pragma: no cover - defensive
                errors.append(e)

        def hammer_reload() -> None:
            try:
                for _ in range(20):
                    idx.reload(FakeRegistry(tasks_v2), client_v2)
                    idx.reload(FakeRegistry(tasks_v1), client_v1)
            except BaseException as e:  # pragma: no cover - defensive
                errors.append(e)

        ts = [threading.Thread(target=hammer_search) for _ in range(3)]
        rl = threading.Thread(target=hammer_reload)
        for t in ts:
            t.start()
        rl.start()
        rl.join()
        stop.set()
        for t in ts:
            t.join()

        assert not errors, f'concurrent search/reload raised: {errors!r}'
