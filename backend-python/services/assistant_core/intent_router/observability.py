"""IntentRouter v2 可观测性工具。

包含：
- ``sha256_16``：消息脱敏哈希（前 16 位十六进制）。
- ``ObservabilityRecorder``：每次路由调用写一条结构化日志，绝不记录消息原文。
- 模块级计数器（``inc`` / ``get`` / ``snapshot``），后续可平替为 ``prometheus_client``。
- 简易直方图 ``observe_latency``，桶口径与 Requirement 6.3 对齐。
- ``FallbackSampleSink``：通过独立 logger 写脱敏样本，写失败仅 warning。

设计要点：
- 所有日志均通过 ``logger.info(... extra={...})``，与 ``logging_config.JsonFormatter``
  天然兼容；非 JSON 场景下 message 字段也是结构化 key=value 摘要。
- 计数器使用 ``(name, frozenset(labels.items()))`` 做 key，保证 label 顺序无关。
- Sink 永不抛异常，主请求路径不受 logger 故障影响。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

# ---- Logger 单例 -----------------------------------------------------------

#: 主路由日志通道；不包含消息明文。
LOGGER_NAME = 'hengpintong.assistant.intent_router'

#: Fallback 离线采样通道，独立于主日志，便于离线分析。
FALLBACK_SAMPLE_LOGGER_NAME = 'router_fallback_samples'

_main_logger = logging.getLogger(LOGGER_NAME)
_fallback_logger = logging.getLogger(FALLBACK_SAMPLE_LOGGER_NAME)


# ---- 脱敏哈希 ---------------------------------------------------------------

def sha256_16(text: str) -> str:
    """返回 ``text`` 的 sha256 十六进制摘要的前 16 位。

    用于把用户消息以脱敏形式写入日志，满足 Requirement 6.2。
    输入为 ``None`` 时按空串处理，保证调用方不需要做 null 防御。
    """
    if text is None:
        text = ''
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return digest[:16]


# ---- 计数器 / 直方图 --------------------------------------------------------

#: 桶口径采用毫秒上界；最后一个 ``float('inf')`` 代表 ``+Inf`` 桶。
LATENCY_BUCKETS_MS: Tuple[float, ...] = (
    50.0, 100.0, 200.0, 500.0, 1000.0, 1500.0, 3000.0, 5000.0, float('inf'),
)

_counters_lock = threading.Lock()
_counters: Dict[Tuple[str, frozenset], int] = {}

# 直方图：{name: [count_per_bucket]}（bucket 顺序与 LATENCY_BUCKETS_MS 对齐）。
_histograms_lock = threading.Lock()
_histograms: Dict[Tuple[str, frozenset], List[int]] = {}


def _counter_key(name: str, labels: Dict[str, Any]) -> Tuple[str, frozenset]:
    """标签字典转换为顺序无关的 key。"""
    items = tuple(sorted((k, str(v)) for k, v in labels.items()))
    return (name, frozenset(items))


def inc(name: str, value: int = 1, **labels: Any) -> int:
    """对计数器 ``name{labels}`` 增加 ``value``，返回累计值。"""
    if value <= 0:
        # 计数器只增不减；非法值视作 0，方便上层不分支。
        value = 0
    key = _counter_key(name, labels)
    with _counters_lock:
        new_value = _counters.get(key, 0) + value
        _counters[key] = new_value
        return new_value


def get(name: str, **labels: Any) -> int:
    """读取计数器 ``name{labels}`` 当前值。"""
    key = _counter_key(name, labels)
    with _counters_lock:
        return _counters.get(key, 0)


def observe_latency(name: str, latency_ms: float, **labels: Any) -> None:
    """把 ``latency_ms`` 写入 ``name`` 直方图。

    采用累计桶（cumulative bucket）口径，与 Prometheus histogram 一致：
    每个上界 ``le`` 桶记录 ``<= le`` 的样本数。
    """
    key = _counter_key(name, labels)
    with _histograms_lock:
        buckets = _histograms.get(key)
        if buckets is None:
            buckets = [0] * len(LATENCY_BUCKETS_MS)
            _histograms[key] = buckets
        for idx, upper in enumerate(LATENCY_BUCKETS_MS):
            if latency_ms <= upper:
                buckets[idx] += 1


def snapshot_counters() -> Dict[Tuple[str, frozenset], int]:
    """返回计数器的快照（拷贝），供测试/调试断言使用。"""
    with _counters_lock:
        return dict(_counters)


def snapshot_histograms() -> Dict[Tuple[str, frozenset], List[int]]:
    """返回直方图的快照（拷贝），供测试/调试断言使用。"""
    with _histograms_lock:
        return {k: list(v) for k, v in _histograms.items()}


def reset_metrics() -> None:
    """清空所有计数器与直方图。仅用于测试隔离，不要在生产路径调用。"""
    with _counters_lock:
        _counters.clear()
    with _histograms_lock:
        _histograms.clear()


# ---- 计数器名称常量（避免拼写错） ------------------------------------------

COUNTER_REQUEST_TOTAL = 'router_request_total'
COUNTER_FALLBACK_TOTAL = 'router_fallback_total'
COUNTER_CLARIFICATION_TOTAL = 'router_clarification_total'
COUNTER_PRONOUN_RESOLVED_TOTAL = 'router_pronoun_resolved_total'
HISTOGRAM_LATENCY_SECONDS = 'router_latency_seconds_bucket'


# ---- ObservabilityRecorder --------------------------------------------------

class ObservabilityRecorder:
    """每次路由调用产出一条结构化日志 + 一组指标。

    日志字段满足 Requirement 6.1；不包含消息原文（Requirement 6.2）。
    调用方通过 ``message`` 与 ``message_length`` 传入脱敏后的摘要与长度。
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._logger = logger or _main_logger

    def record(
        self,
        request_id: str,
        user_id: str,
        route_path: str,
        top_k_scores: List[Tuple[str, float]],
        chosen_task_id: str,
        confidence: float,
        clarification_emitted: bool,
        entity_resolved_count: int,
        latency_ms: float,
        message_hash: Optional[str] = None,
        message_length: Optional[int] = None,
    ) -> None:
        """写一条路由调用日志并叠加相关计数器。

        Args:
            request_id: 单次请求 ID，用于 trace 关联。
            user_id: 用户 ID（建议传脱敏后的值）；本方法不再次脱敏。
            route_path: ``fast_path`` / ``retrieval`` / ``fallback`` /
                ``clarification`` / ``legacy_fallback`` / ``legacy``。
            top_k_scores: ``[(task_id, score), ...]``，顺序为 Top-K 排名。
            chosen_task_id: 最终选中的 ``task_template_id``。
            confidence: 最终置信度，应在 ``[0, 1]`` 内。
            clarification_emitted: 本次是否产出澄清轮。
            entity_resolved_count: 本次 EntityMemory 消解了多少个代词/省略。
            latency_ms: 路由总耗时（毫秒）。
            message_hash: 消息 sha256 前 16 位，可选，仅供脱敏检索。
            message_length: 消息原文长度，可选。

        Notes:
            - 计数器 ``router_request_total{route_path}`` 永远 +1。
            - 走 ``fallback`` / ``legacy_fallback`` 时 ``router_fallback_total`` +1。
            - 产出澄清时 ``router_clarification_total`` +1。
            - ``entity_resolved_count > 0`` 时 ``router_pronoun_resolved_total``
              累加该次消解的实体数。
            - 直方图 ``router_latency_seconds_bucket`` 按毫秒桶累加。
        """
        # 1) 结构化日志：所有可序列化字段经 ``extra`` 注入，message 为摘要。
        extra = {
            'request_id': request_id,
            'user_id': user_id,
            'route_path': route_path,
            'top_k_scores': [
                [task_id, float(score)] for task_id, score in (top_k_scores or [])
            ],
            'chosen_task_id': chosen_task_id,
            'confidence': float(confidence),
            'clarification_emitted': bool(clarification_emitted),
            'entity_resolved_count': int(entity_resolved_count),
            'latency_ms': float(latency_ms),
        }
        if message_hash is not None:
            extra['message_hash'] = message_hash
        if message_length is not None:
            extra['message_length'] = int(message_length)

        # 摘要 message 字段亦不包含原文，仅给出结构化要点。
        summary = (
            f'route_path={route_path} chosen={chosen_task_id} '
            f'confidence={float(confidence):.3f} latency_ms={float(latency_ms):.1f}'
        )
        self._logger.info(summary, extra=extra)

        # 2) 计数器
        inc(COUNTER_REQUEST_TOTAL, route_path=route_path)
        if route_path in ('fallback', 'legacy_fallback'):
            inc(COUNTER_FALLBACK_TOTAL)
        if clarification_emitted:
            inc(COUNTER_CLARIFICATION_TOTAL)
        if entity_resolved_count and entity_resolved_count > 0:
            inc(COUNTER_PRONOUN_RESOLVED_TOTAL, value=int(entity_resolved_count))

        # 3) 直方图
        observe_latency(HISTOGRAM_LATENCY_SECONDS, float(latency_ms))


# ---- FallbackSampleSink -----------------------------------------------------

class FallbackSampleSink:
    """把低置信度 / fallback 样本写入独立日志通道。

    遵循 Requirement 11：
    - 通过独立 logger ``router_fallback_samples`` 输出，便于离线管道单独抓取。
    - 不写消息原文与用户标识，只写 ``query_hash`` / ``role`` 等脱敏字段。
    - 写失败仅 warning 到主 logger，不抛出，不影响主请求。
    """

    def __init__(
        self,
        sample_logger: Optional[logging.Logger] = None,
        warn_logger: Optional[logging.Logger] = None,
    ) -> None:
        self._sample_logger = sample_logger or _fallback_logger
        self._warn_logger = warn_logger or _main_logger

    def write(
        self,
        query_hash: str,
        role: str,
        top_k_task_ids: List[str],
        top_k_scores: List[float],
        chosen_task_id: str,
        timestamp: float,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """写一条 fallback 样本；成功返回 True，失败返回 False。

        失败永远不抛出。
        """
        payload: Dict[str, Any] = {
            'query_hash': query_hash,
            'role': role,
            'top_k_task_ids': list(top_k_task_ids or []),
            'top_k_scores': [float(s) for s in (top_k_scores or [])],
            'chosen_task_id': chosen_task_id,
            'timestamp': float(timestamp),
        }
        if extra_fields:
            for k, v in extra_fields.items():
                # 不允许调用方塞入消息原文：拒绝 message/text/raw_query/user_id 类字段。
                if k in payload or k in ('message', 'text', 'raw_query', 'user_id'):
                    continue
                payload[k] = v

        try:
            self._sample_logger.info('router_fallback_sample', extra=payload)
            return True
        except Exception as exc:
            try:
                self._warn_logger.warning(
                    'fallback_sample_write_failed: %s', exc,
                    extra={'query_hash': query_hash, 'chosen_task_id': chosen_task_id},
                )
            except Exception:
                # 连 warning 都失败时，安静吞掉，不能影响主请求。
                pass
            return False


__all__ = [
    'sha256_16',
    'inc',
    'get',
    'observe_latency',
    'snapshot_counters',
    'snapshot_histograms',
    'reset_metrics',
    'LATENCY_BUCKETS_MS',
    'LOGGER_NAME',
    'FALLBACK_SAMPLE_LOGGER_NAME',
    'COUNTER_REQUEST_TOTAL',
    'COUNTER_FALLBACK_TOTAL',
    'COUNTER_CLARIFICATION_TOTAL',
    'COUNTER_PRONOUN_RESOLVED_TOTAL',
    'HISTOGRAM_LATENCY_SECONDS',
    'ObservabilityRecorder',
    'FallbackSampleSink',
]
