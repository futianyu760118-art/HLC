"""LegacyAdapter for the intent router v2 rollout.

When the v2 ``FeatureFlag`` is off (or as the safety net inside the v2
pipeline), legacy-only tests still want a :class:`RouterResult` whose field set
is a **superset** of the retired router's output. This module wraps
:func:`services.assistant_core.legacy_router.route` so the v2-only fields are
filled in with safe defaults, the original business fields
(``task_template_id``, ``intent``, ``confidence``, ``entities`` …) untouched.

Notes
-----
* The adapter never raises: any exception from the legacy router falls back to
  a minimal :class:`RouterResult` describing the failure, so callers (the
  orchestrator and the v2 pipeline's ``legacy_fallback`` branch) keep a single
  contract.
* ``route_path`` is forced to ``'legacy'``. The v2 pipeline's
  ``legacy_fallback`` branch (Task 12) overrides it again to
  ``'legacy_fallback'`` after calling us, which is intentional: the same
  adapter serves both the FeatureFlag-off path and the v2 retrieval-down
  fallback path.

Validates: Requirements 8.1, 8.2, 8.3, 12.4
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Tuple

from .. import legacy_router as legacy_module
from ..constants import RISK_LOW
from ..schemas import AssistantContext, RouterResult


logger = logging.getLogger('hengpintong.assistant.intent_router.legacy_adapter')


__all__ = ['legacy_route']


def _coerce_top_k(value) -> list:
    """Normalize ``RouterResult.top_k`` to a fresh ``List[Tuple[str, float]]``.

    Tolerates ``None``/``[]`` and any iterable of 2-tuples; entries that fail
    to parse are silently dropped (mirroring :meth:`RouterResult.from_dict`).
    """

    out: list = []
    for item in (value or ()):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                out.append((str(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
    return out


def _coerce_options(value) -> list:
    out = []
    for item in (value or ()):
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _coerce_dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _fallback_result(message: str, reason: str) -> RouterResult:
    """Minimal RouterResult used when the legacy router itself misbehaves."""

    return RouterResult(
        intent='unknown',
        task_template_id=None,
        confidence=0.0,
        entities={},
        missing_fields=[],
        risk_level=RISK_LOW,
        candidate_skills=[],
        requires_confirmation=False,
        clarification_question=None,
        reason=reason,
        rule_matched=False,
        forbidden_reason=None,
        route_path='legacy',
        top_k=[],
        clarification_options=[],
        low_confidence_warning=False,
        entity_resolved={},
    )


def legacy_route(message: str, ctx: AssistantContext) -> RouterResult:
    """Wrap :func:`services.assistant_core.legacy_router.route` to v2 superset.

    The returned :class:`RouterResult` keeps every business field produced by
    the legacy router (``task_template_id``, ``intent``, ``confidence``,
    ``entities``, ``risk_level``, ``candidate_skills``,
    ``requires_confirmation``, ``rule_matched`` …) and additionally guarantees
    the v2 fields exist with concrete defaults:

    * ``route_path = 'legacy'``
    * ``top_k = []`` (legacy router does not produce candidate scores)
    * ``clarification_options = []``
    * ``low_confidence_warning = False``
    * ``entity_resolved = {}``

    Existing v2 fields on the legacy result (e.g. if a future test fixture
    pre-populates them) are normalized through fresh copies to avoid alias
    sharing between callers.
    """

    try:
        result = legacy_module.route(message, ctx)
    except Exception:  # noqa: BLE001 - the adapter must never raise
        logger.exception('legacy_adapter_route_failed')
        result = _fallback_result(message, 'legacy_adapter:route_exception')
        _emit_fallback_sample(message, ctx, result)
        return result

    if result is None:
        result = _fallback_result(message, 'legacy_adapter:legacy_returned_none')
        _emit_fallback_sample(message, ctx, result)
        return result

    normalized = dataclasses.replace(
        result,
        route_path='legacy',
        top_k=_coerce_top_k(result.top_k),
        clarification_options=_coerce_options(result.clarification_options),
        low_confidence_warning=bool(result.low_confidence_warning),
        entity_resolved=_coerce_dict(result.entity_resolved),
    )

    # FeatureFlag 关闭时也要采集对照样本（Req 11.1）。复用 pipeline 中
    # 同款 helper 与同款 sink，保证 v1/v2 的样本格式一致，便于离线对照
    # 评估。任何异常都被 helper 吞掉，下游不感知。
    _emit_fallback_sample(message, ctx, normalized)

    return normalized


def _emit_fallback_sample(
    message: str,
    ctx: AssistantContext,
    result: RouterResult,
) -> None:
    """Forward to ``legacy_pipeline._maybe_write_fallback_sample``.

    Imported lazily to avoid a hard import-time cycle: ``pipeline`` is allowed
    to depend on this module in the future, so we defer the lookup. Any
    exception is swallowed; the helper itself already has a defensive
    try/except inside, this outer guard is *defense in depth*.
    """

    try:
        from . import legacy_pipeline  # local import: avoid potential cycles

        legacy_pipeline._maybe_write_fallback_sample(message, ctx, result)
    except Exception:  # noqa: BLE001
        logger.warning(
            'legacy_adapter_fallback_sample_failed',
            exc_info=True,
        )
