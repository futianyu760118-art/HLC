"""Top-level routing dispatcher (Task 13).

This is the single entry point the orchestrator calls. It picks between the
v2 pipeline (:mod:`pipeline`) and the legacy adapter
(:mod:`legacy_adapter`) according to the per-user :func:`feature_flag.is_enabled_for`
decision. Any unexpected error falls back to the legacy adapter, so the
dispatcher never raises into the orchestrator.

Validates: Requirements 8.1, 8.2, 8.3, 8.5, 12.4
"""

from __future__ import annotations

import logging

from ..schemas import AssistantContext, RouterResult
from . import feature_flag, legacy_adapter
from . import legacy_pipeline as intent_pipeline


logger = logging.getLogger('hengpintong.assistant.intent_router.routing')


__all__ = ['route']


def route(message: str, ctx: AssistantContext) -> RouterResult:
    """Dispatch a routing request to v2 or legacy based on the FeatureFlag.

    Parameters
    ----------
    message:
        The raw user message. Forwarded as-is to whichever backend is active.
    ctx:
        The :class:`AssistantContext` for this turn. ``ctx.user_id`` decides
        which bucket the request lands in.
    """

    user_id = getattr(ctx, 'user_id', None)
    try:
        if feature_flag.is_enabled_for(user_id):
            return intent_pipeline.route(message, ctx)
        return legacy_adapter.legacy_route(message, ctx)
    except Exception:  # noqa: BLE001 - top-level safety net for the orchestrator
        logger.exception('routing_dispatch_failed')
        # Even if the v2 pipeline blew up before its own try/except caught it,
        # we still want a usable :class:`RouterResult` to return.
        return legacy_adapter.legacy_route(message, ctx)
