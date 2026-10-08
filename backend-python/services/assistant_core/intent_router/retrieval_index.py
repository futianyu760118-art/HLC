"""内存向量索引 ``RetrievalIndex``。

设计目标（对齐任务 5 与 Requirements 12.1 / 12.2 / 12.3 / 12.4）：

* 存储格式：
    - ``self._matrix: np.ndarray(shape=(N, D), dtype=float32)``，**已归一化**为
      单位向量，因此 cosine 直接用 ``matrix @ query_vec`` 计算。
    - ``self._meta: List[Tuple[task_id, source_text]]``，与 ``_matrix`` 行号
      一一对应。
* :meth:`build` 遍历 ``task_registry.all_tasks()``，把每条 ``trigger_examples``
  和（如果非空）``description`` 各嵌入为单独一行；缺少 ``trigger_examples``
  的 TaskTemplate **不入库**且打 warning（Req 12.3）。
* :meth:`reload` 在新的矩阵就绪后做 atomic swap：构建过程在锁外进行，最后
  在 ``with self._lock`` 内一次性替换 ``_matrix`` / ``_meta``，保证当前请求
  始终看到一致快照（Req 12.2 "不中断当前请求"）。
* :meth:`search` 在锁内拿快照引用，锁外做矩阵乘法，避免阻塞 reload；
  按 ``task_id`` 去重保留每个 task 的最高分；返回 ``(task_id, score,
  source_text)`` Top-K 列表。
* :meth:`is_empty` 供上层判定是否回退到 LegacyRouter（Req 12.4）。

``embedding_client`` 是 duck-typed 对象，只要求暴露
``embed_corpus(text) -> Optional[np.ndarray]``（已归一化的单位向量），
方便测试用 mock 替换。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional, Protocol, Tuple

import numpy as np

from .observability import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class _EmbeddingClientLike(Protocol):
    """``RetrievalIndex`` 仅依赖 ``embed_corpus`` 这一接口。"""

    def embed_corpus(self, text: str) -> Optional[np.ndarray]:  # pragma: no cover
        ...


class _TaskRegistryLike(Protocol):
    """``RetrievalIndex`` 仅依赖 ``all_tasks`` 这一接口。"""

    def all_tasks(self) -> List[Any]:  # pragma: no cover
        ...


class RetrievalIndex:
    """内存中的稠密向量索引，用于任务模板召回。

    线程模型：
    - 写路径（:meth:`build` / :meth:`reload`）在锁外完成繁重计算，
      仅在最后一刻进入锁做 ``self._matrix, self._meta = ...`` 的原子替换。
    - 读路径（:meth:`search`）在锁内取出 ``_matrix`` / ``_meta`` 的引用快照，
      然后在锁外做 ``matrix @ query_vec`` 与排序，避免阻塞 reload。
    - numpy 数组与 Python list 的引用替换是 GIL 原子的；只要快照在锁内拷贝
      了引用，后续即使 reload 把成员变量指向新数组，老快照仍然有效。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._matrix: Optional[np.ndarray] = None
        self._meta: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # 构建 / 刷新
    # ------------------------------------------------------------------
    def build(
        self,
        task_registry: _TaskRegistryLike,
        embedding_client: _EmbeddingClientLike,
    ) -> int:
        """从 ``task_registry`` 全量重建索引，返回入库样例条数。

        - 缺少 ``trigger_examples`` 的 TaskTemplate **不入库**，并打 warning。
        - ``description`` 仅在 trigger_examples 存在时作为额外一行入库。
        - 单条 ``embed_corpus`` 返回 ``None`` 时跳过该行（debug 日志），不影响
          其它行。
        """
        matrix, meta = self._compute_snapshot(task_registry, embedding_client)
        with self._lock:
            self._matrix = matrix
            self._meta = meta
        return len(meta)

    def reload(
        self,
        task_registry: _TaskRegistryLike,
        embedding_client: _EmbeddingClientLike,
    ) -> int:
        """原子重建索引；构建在锁外完成，仅最后一步替换走锁。"""

        # NOTE: 与 :meth:`build` 等价，但单独命名是为了在调用点明确语义；
        # 上层（任务 12）会把这个方法挂到 ``task_registry.reload()`` 钩子上。
        matrix, meta = self._compute_snapshot(task_registry, embedding_client)
        with self._lock:
            self._matrix = matrix
            self._meta = meta
        return len(meta)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def search(
        self,
        query_vec: np.ndarray,
        k: int = 5,
    ) -> List[Tuple[str, float, str]]:
        """对单位向量 ``query_vec`` 做 Top-K 召回。

        Args:
            query_vec: 已归一化的查询向量（``float32`` 一维）。
            k: Top-K 上限；按 ``task_id`` 去重后最多返回 k 条。

        Returns:
            ``[(task_id, score, source_text), ...]``，按相似度降序。
            索引为空或 ``k <= 0`` 时返回 ``[]``。
        """
        if k <= 0:
            return []

        # 在锁内只取引用快照；矩阵运算放在锁外，避免长持锁阻塞 reload。
        with self._lock:
            matrix = self._matrix
            meta = self._meta

        if matrix is None or matrix.shape[0] == 0 or not meta:
            return []

        # 防御性处理：保证 query 是单位向量的 float32 一维。如果维度不匹配
        # 直接返回空，调用方会回落到 LegacyRouter。
        try:
            q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return []
        if q.shape[0] != matrix.shape[1]:
            logger.warning(
                'retrieval_index_dim_mismatch',
                extra={'index_dim': int(matrix.shape[1]), 'query_dim': int(q.shape[0])},
            )
            return []

        scores = matrix @ q  # shape (N,)

        # 按 task_id 去重保留最高分。
        # 使用 dict 保序：先按分数降序遍历，每个 task_id 第一次出现时收录。
        order = np.argsort(-scores, kind='stable')
        best: dict = {}
        for idx in order:
            task_id, source_text = meta[int(idx)]
            if task_id in best:
                continue
            best[task_id] = (float(scores[int(idx)]), source_text)
            if len(best) >= k:
                break

        return [
            (task_id, score, source_text)
            for task_id, (score, source_text) in best.items()
        ]

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        """索引为空时返回 True；上层据此回退到 LegacyRouter。"""

        with self._lock:
            return self._matrix is None or self._matrix.shape[0] == 0

    def size(self) -> int:
        """当前已入库样例条数（含 trigger_examples 与 description）。"""

        with self._lock:
            return 0 if self._matrix is None else int(self._matrix.shape[0])

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_snapshot(
        task_registry: _TaskRegistryLike,
        embedding_client: _EmbeddingClientLike,
    ) -> Tuple[Optional[np.ndarray], List[Tuple[str, str]]]:
        """遍历任务注册表，产出待原子替换的 ``(matrix, meta)`` 快照。"""

        rows: List[np.ndarray] = []
        meta: List[Tuple[str, str]] = []

        try:
            tasks = list(task_registry.all_tasks())
        except Exception:  # noqa: BLE001 - 防御性
            logger.exception('retrieval_index_registry_iteration_failed')
            return None, []

        for task in tasks:
            task_id = getattr(task, 'id', None)
            if not task_id:
                continue
            trigger_examples = list(getattr(task, 'trigger_examples', []) or [])
            description = getattr(task, 'description', '') or ''

            # Req 12.3：缺少 trigger_examples 的 TaskTemplate 必须输出 warning
            # 且不入库；description 不能单独支撑入库。
            if not trigger_examples:
                logger.warning(
                    'retrieval_index_missing_trigger_examples',
                    extra={'task_id': task_id},
                )
                continue

            # 1) 每条 trigger_example 单独嵌入。
            for example in trigger_examples:
                if not isinstance(example, str) or not example:
                    continue
                vec = _safe_embed(embedding_client, example)
                if vec is None:
                    logger.debug(
                        'retrieval_index_skip_row',
                        extra={'task_id': task_id, 'reason': 'embed_returned_none'},
                    )
                    continue
                rows.append(vec)
                meta.append((task_id, example))

            # 2) description 作为额外一行（非空时）。
            if isinstance(description, str) and description:
                vec = _safe_embed(embedding_client, description)
                if vec is None:
                    logger.debug(
                        'retrieval_index_skip_row',
                        extra={'task_id': task_id, 'reason': 'embed_returned_none_desc'},
                    )
                else:
                    rows.append(vec)
                    meta.append((task_id, description))

        if not rows:
            return None, []

        # 统一 dtype/shape 为 float32 (N, D)。所有向量都应当来自同一 embedding
        # 模型，因此维度一致；为稳妥起见，过滤掉维度异常的行。
        target_dim = rows[0].shape[0]
        clean_rows: List[np.ndarray] = []
        clean_meta: List[Tuple[str, str]] = []
        for vec, m in zip(rows, meta):
            if vec.ndim != 1 or vec.shape[0] != target_dim:
                logger.warning(
                    'retrieval_index_skip_dim_mismatch',
                    extra={'task_id': m[0], 'expected': target_dim, 'got': int(vec.shape[0])},
                )
                continue
            clean_rows.append(vec.astype(np.float32, copy=False))
            clean_meta.append(m)

        if not clean_rows:
            return None, []

        matrix = np.vstack(clean_rows).astype(np.float32, copy=False)
        return matrix, clean_meta


def _safe_embed(
    embedding_client: _EmbeddingClientLike,
    text: str,
) -> Optional[np.ndarray]:
    """调用 ``embed_corpus`` 并吞掉异常，统一退化为 ``None``。"""

    try:
        return embedding_client.embed_corpus(text)
    except Exception:  # noqa: BLE001 - 防御性，避免单条样例毒化整个 build
        logger.exception('retrieval_index_embed_corpus_failed')
        return None


__all__ = ['RetrievalIndex']
