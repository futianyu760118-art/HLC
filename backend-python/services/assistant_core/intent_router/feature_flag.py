"""FeatureFlag for the intent router v2 rollout.

This module exposes a thread-safe percentage-based feature flag, gated by two
environment variables:

* ``ASSISTANT_INTENT_ROUTER_V2_ENABLED`` (truthy values: ``1``, ``true``,
  ``TRUE``, ``yes``); when falsy the flag is unconditionally ``False``.
* ``ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT`` (integer; only ``0``, ``1``, ``10``,
  ``50`` and ``100`` are accepted; invalid values fall back to ``0``).

Bucketing uses the first 4 bytes of ``sha1(user_id)`` mod 100 so the assignment
is stable for the same ``user_id`` across processes.

Configuration is loaded lazily on the first call and cached. Tests (and the
final wiring task) can call :func:`reload` to invalidate the cache; the next
``is_enabled_for`` call will pick up new environment values.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from typing import Optional

from config import IntentRouterConfig


_TRUTHY_VALUES = {"1", "true", "TRUE", "yes"}
_VALID_PCTS = {0, 1, 10, 50, 100}

# 环境变量名集中登记在 ``config.IntentRouterConfig``；本模块只引用，方便
# 全局重命名时只动 config.py 一处。
_ENV_V2_ENABLED = IntentRouterConfig.ENV_V2_ENABLED
_ENV_ROLLOUT_PCT = IntentRouterConfig.ENV_ROLLOUT_PCT


@dataclass(frozen=True)
class _FlagState:
    """Snapshot of the feature flag configuration."""

    v2_enabled: bool
    rollout_pct: int


class FeatureFlag:
    """Thread-safe feature flag with lazy, explicit reload semantics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Optional[_FlagState] = None

    def _load_state(self) -> _FlagState:
        raw_enabled = os.environ.get(_ENV_V2_ENABLED, "")
        v2_enabled = raw_enabled in _TRUTHY_VALUES

        raw_pct = os.environ.get(_ENV_ROLLOUT_PCT, "")
        try:
            pct = int(raw_pct)
        except (TypeError, ValueError):
            pct = 0
        if pct not in _VALID_PCTS:
            pct = 0

        return _FlagState(v2_enabled=v2_enabled, rollout_pct=pct)

    def _get_state(self) -> _FlagState:
        # Fast path: already loaded.
        state = self._state
        if state is not None:
            return state
        with self._lock:
            if self._state is None:
                self._state = self._load_state()
            return self._state

    def reload(self) -> None:
        """Drop the cached state so the next call re-reads ``os.environ``."""

        with self._lock:
            self._state = None

    def is_enabled_for(self, user_id: Optional[str]) -> bool:
        """Return whether the v2 router is active for the given ``user_id``.

        Returns ``False`` when the master switch is off or when ``user_id`` is
        missing (we cannot bucket an anonymous request stably).
        """

        state = self._get_state()
        if not state.v2_enabled:
            return False
        if not user_id:
            return False

        digest = hashlib.sha1(user_id.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        return bucket < state.rollout_pct


# Module-level singleton + thin functional wrappers used by callers and tests.
_default_flag = FeatureFlag()


def is_enabled_for(user_id: Optional[str]) -> bool:
    """Convenience wrapper around the module-level :class:`FeatureFlag`."""

    return _default_flag.is_enabled_for(user_id)


def reload() -> None:
    """Invalidate the cached configuration on the module-level singleton."""

    _default_flag.reload()
