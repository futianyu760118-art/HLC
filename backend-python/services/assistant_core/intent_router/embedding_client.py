"""SiliconFlow ``/embeddings`` 客户端封装。

设计目标（对齐任务 4 与 Requirements 12.1 / 12.4）：

* 走与 :mod:`services.assistant_core.llm_client` 同源的环境变量
  (``SILICONFLOW_API_KEY`` / ``SILICONFLOW_API_URL``)，端点 ``/embeddings``。
* 提供单条 :func:`embed` 与批量 :func:`embed_batch`；返回 ``float32`` 一维
  ``np.ndarray``，已归一化为单位长度；任何失败（缺 key / 非 200 / 超时 /
  malformed JSON / 网络异常）都退化为 ``None``，**不抛**。
* 通过 :func:`embed_corpus` + ``functools.lru_cache(maxsize=2048)`` 缓存稳定
  语料的嵌入（即 ``TaskTemplate.trigger_examples`` / ``description``）。**查询
  文本不走缓存**，因此 :func:`embed` 走非缓存路径。
* 单次 HTTP 调用硬超时默认 2000ms，可通过参数覆盖。

**关于缓存返回值**：``functools.lru_cache`` 只要求入参可哈希，对返回值类型没
有约束。这里直接缓存 ``np.ndarray``，避免每次命中再用 ``np.frombuffer`` 重
构。如果后续观测到内存占用过高，可改为缓存 ``bytes`` 并在调用方按需重构。
"""

from __future__ import annotations

import functools
import logging
import os
from typing import List, Optional

import numpy as np
import requests

from config import IntentRouterConfig


logger = logging.getLogger("hengpintong.assistant.embedding")

# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------

#: SiliconFlow / OpenAI 兼容 API key。运行期通过 :func:`_get_api_key` 读取，
#: 这样测试可以在 monkeypatch 之后直接看到新值，而不需要重载模块。
_ENV_API_KEY = "SILICONFLOW_API_KEY"
_ENV_API_URL = "SILICONFLOW_API_URL"
#: ``ASSISTANT_EMBEDDING_MODEL`` 在 ``config.IntentRouterConfig`` 集中登记。
_ENV_EMBEDDING_MODEL = IntentRouterConfig.ENV_EMBEDDING_MODEL

#: 默认 embedding 模型。BAAI/bge-m3 在 SiliconFlow 上免费且支持中英文，与
#: 资历库（HR 场景）的语种分布契合。可通过 ``ASSISTANT_EMBEDDING_MODEL``
#: 覆盖。
DEFAULT_EMBEDDING_MODEL = IntentRouterConfig.DEFAULT_EMBEDDING_MODEL

#: 单次 HTTP 调用硬超时（毫秒）。
DEFAULT_TIMEOUT_MS = 2000

#: 默认 SiliconFlow API base URL。
_DEFAULT_API_URL = "https://api.siliconflow.cn/v1"

#: ``embed_corpus`` 缓存大小。
_CORPUS_CACHE_MAXSIZE = 2048

#: 数值稳定性下限，避免 0 向量除 0。
_NORM_EPS = 1e-12


# ---------------------------------------------------------------------------
# 配置读取（运行期取值，方便测试 / 配置热更）
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get(_ENV_API_KEY, "") or ""


def _get_api_url() -> str:
    return os.environ.get(_ENV_API_URL, _DEFAULT_API_URL) or _DEFAULT_API_URL


def _get_default_model() -> str:
    return os.environ.get(_ENV_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL) or DEFAULT_EMBEDDING_MODEL


def is_available() -> bool:
    """是否具备调用 SiliconFlow embeddings 的最低条件（API key 存在）。"""

    return bool(_get_api_key())


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _normalize(vec: np.ndarray) -> np.ndarray:
    """归一化为单位长度的 ``float32`` 一维向量。"""

    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    return (arr / max(norm, _NORM_EPS)).astype(np.float32, copy=False)


def _do_embed(
    texts: List[str],
    *,
    model: Optional[str],
    timeout_ms: int,
) -> List[Optional[np.ndarray]]:
    """单次 HTTP 调用，返回与 ``texts`` 等长的向量列表；失败整体返回 None 列表。

    任何异常路径都 **不向上抛**，统一返回 ``[None, ...]``，由调用方决定降级
    策略。日志只记录最小必要信息（不打印 API key、不打印消息原文长字段）。
    """

    if not texts:
        return []

    api_key = _get_api_key()
    if not api_key:
        # 静默失败：保持与 ``llm_client.is_available()`` 一致的行为，让上层
        # 通过 :func:`is_available` 主动判定。
        return [None] * len(texts)

    url = f"{_get_api_url().rstrip('/')}/embeddings"
    body = {
        "model": model or _get_default_model(),
        "input": list(texts),
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout_seconds = max(timeout_ms, 1) / 1000.0

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
    except requests.Timeout:
        # 超时是正常容量退化，不打 stack trace。
        logger.warning(
            "embedding_timeout",
            extra={"timeout_ms": timeout_ms, "batch_size": len(texts)},
        )
        return [None] * len(texts)
    except Exception:  # noqa: BLE001 - intentional broad guard
        logger.exception("embedding_request_failed")
        return [None] * len(texts)

    if resp.status_code != 200:
        logger.warning(
            "embedding_non_200",
            extra={"status": resp.status_code, "batch_size": len(texts)},
        )
        return [None] * len(texts)

    try:
        payload = resp.json()
    except ValueError:
        logger.warning("embedding_json_decode_failed", extra={"batch_size": len(texts)})
        return [None] * len(texts)

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        logger.warning(
            "embedding_payload_shape_invalid",
            extra={"batch_size": len(texts), "got_len": len(data) if isinstance(data, list) else -1},
        )
        return [None] * len(texts)

    out: List[Optional[np.ndarray]] = []
    for item in data:
        if not isinstance(item, dict):
            out.append(None)
            continue
        emb = item.get("embedding")
        if not isinstance(emb, list) or not emb:
            out.append(None)
            continue
        try:
            out.append(_normalize(np.asarray(emb, dtype=np.float32)))
        except (TypeError, ValueError):
            logger.warning("embedding_vector_cast_failed")
            out.append(None)
    return out


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def embed(
    text: str,
    *,
    model: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Optional[np.ndarray]:
    """嵌入单条文本，返回 ``float32`` 单位向量；失败返回 ``None``。

    查询文本走该路径——**不命中缓存**，因为查询不可枚举且分布与稳定语料不同。
    """

    if not isinstance(text, str) or not text:
        return None
    result = _do_embed([text], model=model, timeout_ms=timeout_ms)
    return result[0] if result else None


def embed_batch(
    texts: List[str],
    *,
    model: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> List[Optional[np.ndarray]]:
    """批量嵌入；与 ``texts`` 等长，元素失败时为 ``None``。"""

    if not texts:
        return []
    safe_inputs = [t if isinstance(t, str) and t else "" for t in texts]
    # 全空输入时，跳过 HTTP 调用；任何空字符串都置 None。
    if not any(safe_inputs):
        return [None] * len(texts)
    raw = _do_embed(safe_inputs, model=model, timeout_ms=timeout_ms)
    # 把空串位置强制改回 None，避免污染索引。
    return [None if not safe_inputs[i] else raw[i] for i in range(len(texts))]


@functools.lru_cache(maxsize=_CORPUS_CACHE_MAXSIZE)
def embed_corpus(text: str) -> Optional[np.ndarray]:
    """嵌入稳定语料（``trigger_examples`` / ``description``），命中 LRU 缓存。

    仅供索引构建侧使用。如果命中缓存，**不会**触发 HTTP 调用。
    """

    if not isinstance(text, str) or not text:
        return None
    result = _do_embed([text], model=None, timeout_ms=DEFAULT_TIMEOUT_MS)
    return result[0] if result else None


def clear_corpus_cache() -> None:
    """重置 :func:`embed_corpus` 的 LRU 缓存（重建索引或测试时调用）。"""

    embed_corpus.cache_clear()


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_TIMEOUT_MS",
    "clear_corpus_cache",
    "embed",
    "embed_batch",
    "embed_corpus",
    "is_available",
]
