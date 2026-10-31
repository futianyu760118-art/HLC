"""ConfidenceGate：根据置信度三段窗对 RouterResult 二次着色。

职责：

1. 从环境变量读取 ``[low_threshold, high_threshold]`` 阈值窗（闭区间），
   非法或越界回落到默认 ``(0.50, 0.75)`` 并 warning，满足 Requirement 3.5。
2. 三段判定（Requirement 3.1）：

   * ``confidence < low``  → ``route_path='fallback'``。
   * ``low ≤ confidence ≤ high`` → 写入 ``clarification_options``（最多 4
     项；从 ``top_k`` 推导 ``label`` / ``payload``），``requires_confirmation
     =True``，``route_path='clarification'``。
   * ``confidence > high`` → ``route_path='retrieval'``。

3. 第二轮规则（Requirement 3.6）：上一轮 ``ctx.history`` 已经走过
   ``clarification``，本轮置信度仍落在窗口内 → 强制选 Top-1，
   ``low_confidence_warning=True``，``route_path='retrieval'``，跳过澄清，
   避免无限澄清；``requires_confirmation`` 不强行设 True，让下游
   ``PermissionGate`` 决定。

4. 跳过修改的输入（保留 FastPath / Legacy / 已经被拒绝的语义）：

   * ``route_path`` ∈ ``{'fast_path', 'legacy_fallback', 'legacy'}`` →
     原样返回。
   * ``task_template_id`` ∈
     ``{'forbidden_action_response', 'permission_denied_response'}`` →
     原样返回。

API 形状与 :mod:`feature_flag` 保持一致：``ConfidenceGate`` 实例 +
模块级单例 + 函数包装 ``evaluate(...)`` / ``reload()``。

实现要点：

* ``evaluate`` 通过 :func:`dataclasses.replace` 返回新的 ``RouterResult``
  实例，不可变更入参（防止上游缓存 / 日志被串改）。
* 阈值的解析与校验集中在 ``_load_thresholds`` 中，``reload()`` 会清缓存让
  下次 ``evaluate`` 重新读取，与 ``feature_flag.reload`` 同款语义。

Validates: Requirements 3.1, 3.5, 3.6, 7.3
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from config import IntentRouterConfig

from ..schemas import AssistantContext, RouterResult


logger = logging.getLogger('hengpintong.assistant.intent_router.confidence_gate')


# ---- 环境变量 / 默认值 ------------------------------------------------------

# 环境变量名与默认值集中登记在 ``config.IntentRouterConfig``；本模块只引用。
_ENV_LOW = IntentRouterConfig.ENV_LOW_THRESHOLD
_ENV_HIGH = IntentRouterConfig.ENV_HIGH_THRESHOLD

DEFAULT_LOW_THRESHOLD = IntentRouterConfig.DEFAULT_LOW_THRESHOLD
DEFAULT_HIGH_THRESHOLD = IntentRouterConfig.DEFAULT_HIGH_THRESHOLD

#: 单条澄清最多展示的快捷回复数（与 widgets.MAX_CLARIFICATION_OPTIONS 对齐）。
MAX_CLARIFICATION_OPTIONS = 4

#: 已被上游闸门覆盖、ConfidenceGate 不再二次染色的 ``route_path`` 集合。
_SKIP_ROUTE_PATHS = frozenset({'fast_path', 'legacy_fallback', 'legacy'})

#: 已被改写为终态响应、ConfidenceGate 不应再插手的 ``task_template_id``。
_SKIP_TASK_IDS = frozenset({'forbidden_action_response',
                            'permission_denied_response'})


# ---- 内部工具 ---------------------------------------------------------------


def _parse_threshold(raw: Optional[str]) -> Optional[float]:
    """把环境变量字符串解析为 ``[0, 1]`` 区间内的 float。

    返回 ``None`` 表示无法解析或越界，调用方需要回落到默认值。
    """
    if raw is None or raw == '':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float('inf'), float('-inf')):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _load_thresholds() -> Tuple[float, float]:
    """读取环境变量，校验后返回 ``(low, high)``。

    校验规则（与任务约束 ``0.0 ≤ low ≤ high ≤ 1.0`` 对齐）：

    * 任一侧显式配置但解析失败（非 float / NaN / inf / 越界 ``[0, 1]``） →
      *整体* 回落到 ``(0.50, 0.75)`` 并 warning，避免半解析后窗口不一致。
    * 两侧都解析成功但 ``low > high`` → 同样整体回落到默认值。
    * 任一侧未显式配置（``None`` 或空串）→ 该侧使用默认值；不视为非法。
    """
    raw_low = os.environ.get(_ENV_LOW)
    raw_high = os.environ.get(_ENV_HIGH)

    parsed_low = _parse_threshold(raw_low)
    parsed_high = _parse_threshold(raw_high)

    invalid_reason: Optional[str] = None
    if raw_low not in (None, '') and parsed_low is None:
        invalid_reason = f'invalid low={raw_low!r}'
    elif raw_high not in (None, '') and parsed_high is None:
        invalid_reason = f'invalid high={raw_high!r}'

    if invalid_reason is not None:
        logger.warning(
            'confidence_gate_threshold_fallback: %s; using defaults (%.2f, %.2f)',
            invalid_reason, DEFAULT_LOW_THRESHOLD, DEFAULT_HIGH_THRESHOLD,
        )
        return DEFAULT_LOW_THRESHOLD, DEFAULT_HIGH_THRESHOLD

    low = parsed_low if parsed_low is not None else DEFAULT_LOW_THRESHOLD
    high = parsed_high if parsed_high is not None else DEFAULT_HIGH_THRESHOLD

    if low > high:
        logger.warning(
            'confidence_gate_threshold_fallback: low=%s > high=%s; '
            'using defaults (%.2f, %.2f)',
            low, high, DEFAULT_LOW_THRESHOLD, DEFAULT_HIGH_THRESHOLD,
        )
        return DEFAULT_LOW_THRESHOLD, DEFAULT_HIGH_THRESHOLD

    return low, high


def _build_clarification_options(
    top_k: List[Tuple[str, float]],
) -> List[Dict[str, Any]]:
    """把 Top-K 候选转成澄清快捷回复，最多 4 项。

    每项形如 ``{label: task_id, payload: task_id}``；``label`` 后续可由
    Reranker / TaskTemplate.name 优化，本任务保稳定结构即可（Req 3.3）。
    去重以 ``task_id`` 为键，保持 Top-K 顺序，避免同一任务重复出现。
    """
    options: List[Dict[str, Any]] = []
    seen: set = set()
    for item in top_k or []:
        if not isinstance(item, (tuple, list)) or len(item) < 1:
            continue
        task_id = item[0]
        if not task_id or not isinstance(task_id, str):
            continue
        if task_id in seen:
            continue
        seen.add(task_id)
        options.append({'label': task_id, 'payload': task_id})
        if len(options) >= MAX_CLARIFICATION_OPTIONS:
            break
    return options


def _detect_previous_clarification(ctx: Optional[AssistantContext]) -> bool:
    """``ctx.history`` 上一条 assistant 消息是否记录过 ``route_path='clarification'``。

    兼容两种 metadata 容器（``metadata`` / ``meta``）与两种命名（
    ``routePath`` / ``route_path``），与 ``memory.save_turn`` 写入口径一致。
    history 为空或没有 assistant 消息时返回 ``False``，按首轮处理。
    """
    if ctx is None:
        return False
    history = getattr(ctx, 'history', None) or []
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        if entry.get('role') != 'assistant':
            continue
        for meta_key in ('metadata', 'meta'):
            meta = entry.get(meta_key)
            if not isinstance(meta, dict):
                continue
            for path_key in ('routePath', 'route_path'):
                if meta.get(path_key) == 'clarification':
                    return True
        # 只看最近一条 assistant 消息：再往前的澄清不算第二轮。
        return False
    return False


# ---- ConfidenceGate ---------------------------------------------------------


class ConfidenceGate:
    """根据三段窗对 ``RouterResult`` 做二次着色。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._low: Optional[float] = None
        self._high: Optional[float] = None

    # --- 阈值缓存与重载 -----------------------------------------------------

    def _ensure_thresholds(self) -> Tuple[float, float]:
        low, high = self._low, self._high
        if low is not None and high is not None:
            return low, high
        with self._lock:
            if self._low is None or self._high is None:
                self._low, self._high = _load_thresholds()
            return self._low, self._high  # type: ignore[return-value]

    def reload(self) -> None:
        """让下次 ``evaluate`` 重新读取环境变量。"""
        with self._lock:
            self._low = None
            self._high = None

    # --- 主入口 -------------------------------------------------------------

    def evaluate(
        self,
        router_result: RouterResult,
        ctx: Optional[AssistantContext] = None,
    ) -> RouterResult:
        """根据置信度三段窗对 ``router_result`` 做二次着色。

        通过 :func:`dataclasses.replace` 返回新实例；入参不被改动。
        """
        if router_result is None:
            # 防御：不抛错，让上游闸门继续兜底。
            return router_result  # type: ignore[return-value]

        # 1) 跳过已被上游闸门覆盖的输入：原值返回（仍走 replace 以提供新实例）。
        if router_result.route_path in _SKIP_ROUTE_PATHS:
            return dataclasses.replace(router_result)
        if router_result.task_template_id in _SKIP_TASK_IDS:
            return dataclasses.replace(router_result)

        low, high = self._ensure_thresholds()
        confidence = float(router_result.confidence)

        # 2) confidence < low：低置信度兜底
        if confidence < low:
            return dataclasses.replace(
                router_result,
                route_path='fallback',
                clarification_options=[],
            )

        in_window = low <= confidence <= high

        # 3) 第二轮规则：上一轮已走过 clarification 且本轮仍在窗口
        #    → 强制 Top-1 + low_confidence_warning，避免无限澄清。
        if in_window and _detect_previous_clarification(ctx):
            top_k = router_result.top_k or []
            forced_task_id = router_result.task_template_id
            if top_k:
                top1 = top_k[0][0]
                if top1 and top1 != forced_task_id:
                    forced_task_id = top1
            return dataclasses.replace(
                router_result,
                task_template_id=forced_task_id,
                route_path='retrieval',
                low_confidence_warning=True,
                clarification_options=[],
                # requires_confirmation 不强行设 True：保留入参原值，
                # 让下游 PermissionGate 根据 side_effect / risk_level 决定。
                requires_confirmation=router_result.requires_confirmation,
            )

        # 4) 首轮且落入窗口：写澄清选项
        if in_window:
            options = _build_clarification_options(router_result.top_k)
            if not options:
                # top_k 为空时无法构造可用的澄清，降级为 fallback；
                # 上层可在日志中据此识别「想澄清但没料」的边界情况。
                return dataclasses.replace(
                    router_result,
                    route_path='fallback',
                    clarification_options=[],
                )
            return dataclasses.replace(
                router_result,
                route_path='clarification',
                clarification_options=options,
                requires_confirmation=True,
            )

        # 5) confidence > high：常规检索路径
        return dataclasses.replace(
            router_result,
            route_path='retrieval',
        )


# ---- 模块级单例 + 函数包装（与 feature_flag 同模式） ----------------------

_default_gate = ConfidenceGate()


def evaluate(
    router_result: RouterResult,
    ctx: Optional[AssistantContext] = None,
) -> RouterResult:
    """便捷包装：使用模块级单例 :class:`ConfidenceGate` 求值。"""
    return _default_gate.evaluate(router_result, ctx)


def reload() -> None:
    """让下次 ``evaluate`` 重新读取环境变量。"""
    _default_gate.reload()


def get_thresholds() -> Tuple[float, float]:
    """返回当前生效的 ``(low_threshold, high_threshold)``。

    供下游模块（例如 :mod:`pipeline._maybe_write_fallback_sample`）共享同
    一份阈值口径，避免在多处重复读取环境变量造成漂移。带异常防御：底层
    解析失败时已经回落到默认值，不会向上抛错。
    """
    return _default_gate._ensure_thresholds()


__all__ = [
    'ConfidenceGate',
    'evaluate',
    'reload',
    'get_thresholds',
    'DEFAULT_LOW_THRESHOLD',
    'DEFAULT_HIGH_THRESHOLD',
    'MAX_CLARIFICATION_OPTIONS',
]
