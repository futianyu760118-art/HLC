"""Per-node health state for Skill-first LLM nodes.

The Agent Kernel should keep the model in the main loop when it is healthy, but
it should not wait for the same dead provider on every node of every request.
This module tracks recent provider failures and exposes short circuit-open
state per use case. A slow understanding call should not switch off bounded
planning, slot/reference refinement or grounded answer synthesis for the whole
request path.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from . import llm_runtime_config


FAILURE_STATUSES = {
    'timeout',
    'http_error',
    'error',
    'llm_timeout',
    'llm_http_error',
    'llm_error',
}


@dataclass
class _HealthState:
    consecutive_failures: int = 0
    opened_at: Optional[float] = None
    last_status: Optional[str] = None
    last_use_case: Optional[str] = None
    last_latency_ms: Optional[int] = None
    last_model: Optional[str] = None
    history: list[Dict[str, Any]] = field(default_factory=list)


_LOCK = threading.RLock()
_STATES: Dict[str, _HealthState] = {}


def is_enabled() -> bool:
    return llm_runtime_config.health_circuit_enabled()


def reset() -> None:
    """Reset health state.

    Tests use this directly; production can also call it from a diagnostic
    endpoint in the future after credential or provider changes.
    """

    with _LOCK:
        _STATES.clear()


def snapshot() -> Dict[str, Any]:
    with _LOCK:
        now = time.time()
        by_use_case = {
            use_case: _snapshot_for_state_locked(use_case, state, now)
            for use_case, state in sorted(_STATES.items())
        }
        open_snaps = [item for item in by_use_case.values() if item.get('state') == 'open']
        last_event = _last_event_locked()
        return {
            'enabled': is_enabled(),
            'state': 'open' if open_snaps else 'closed',
            'consecutive_failures': max(
                [int(item.get('consecutive_failures') or 0) for item in by_use_case.values()] or [0]
            ),
            'failure_threshold': llm_runtime_config.health_failure_threshold(),
            'cooldown_seconds': llm_runtime_config.health_cooldown_seconds(),
            'cooldown_remaining_seconds': max(
                [int(item.get('cooldown_remaining_seconds') or 0) for item in open_snaps] or [0]
            ),
            'opened_at': max(
                [float(item.get('opened_at') or 0.0) for item in open_snaps] or [0.0]
            ) or None,
            'last_status': last_event.get('status') if last_event else None,
            'last_use_case': last_event.get('use_case') if last_event else None,
            'last_latency_ms': last_event.get('latency_ms') if last_event else None,
            'last_model': last_event.get('model') if last_event else None,
            'by_use_case': by_use_case,
        }


def availability(use_case: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Return whether an LLM call may be attempted for this use case."""

    if not is_enabled():
        return True, 'available', {'enabled': False, 'state': 'disabled'}
    with _LOCK:
        now = time.time()
        state = _state_for_locked(use_case)
        remaining = _cooldown_remaining_locked(state, now)
        if remaining > 0:
            return False, 'llm_health_circuit_open', _snapshot_for_state_locked(use_case, state, now)
        if state.opened_at is not None:
            state.opened_at = None
        return True, 'available', _snapshot_for_state_locked(use_case, state, now)


def record_success(use_case: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = dict(meta or {})
    with _LOCK:
        state = _state_for_locked(use_case)
        state.consecutive_failures = 0
        state.opened_at = None
        state.last_status = str(meta.get('status') or 'success')
        state.last_use_case = use_case
        state.last_latency_ms = _as_int(meta.get('latency_ms'))
        state.last_model = str(meta.get('model') or '') or state.last_model
        _append_history_locked(state, use_case, state.last_status, meta)
        return _snapshot_for_state_locked(use_case, state, time.time())


def record_failure(use_case: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = dict(meta or {})
    status = _canonical_status(meta)
    with _LOCK:
        state = _state_for_locked(use_case)
        state.consecutive_failures += 1
        state.last_status = status
        state.last_use_case = use_case
        state.last_latency_ms = _as_int(meta.get('latency_ms'))
        state.last_model = str(meta.get('model') or '') or state.last_model
        opened = False
        if is_enabled() and state.consecutive_failures >= llm_runtime_config.health_failure_threshold():
            state.opened_at = time.time()
            opened = True
        _append_history_locked(state, use_case, status, meta)
        snap = _snapshot_for_state_locked(use_case, state, time.time())
        snap['opened'] = opened
        return snap


def record_call_result(use_case: str, meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = dict(meta or {})
    status = _canonical_status(meta)
    if status == 'success':
        return record_success(use_case, meta)
    if status in FAILURE_STATUSES:
        return record_failure(use_case, {**meta, 'status': status})
    return availability(use_case)[2]


def _canonical_status(meta: Dict[str, Any]) -> str:
    status = str(meta.get('status') or '')
    if status.startswith('llm_'):
        return status
    if status in {'timeout', 'http_error', 'error', 'success'}:
        return status
    if str(meta.get('json_status') or '') in {'parse_failed', 'empty_content'}:
        return 'llm_error'
    return status or 'unknown'


def _state_for_locked(use_case: str) -> _HealthState:
    key = str(use_case or 'unknown')
    state = _STATES.get(key)
    if state is None:
        state = _HealthState(last_use_case=key)
        _STATES[key] = state
    return state


def _snapshot_for_state_locked(use_case: str, state: _HealthState, now: float) -> Dict[str, Any]:
    remaining = _cooldown_remaining_locked(state, now)
    return {
        'enabled': is_enabled(),
        'state': 'open' if remaining > 0 else 'closed',
        'use_case': use_case,
        'consecutive_failures': state.consecutive_failures,
        'failure_threshold': llm_runtime_config.health_failure_threshold(),
        'cooldown_seconds': llm_runtime_config.health_cooldown_seconds(),
        'cooldown_remaining_seconds': remaining,
        'opened_at': state.opened_at if remaining > 0 else None,
        'last_status': state.last_status,
        'last_use_case': state.last_use_case,
        'last_latency_ms': state.last_latency_ms,
        'last_model': state.last_model,
    }


def _cooldown_remaining_locked(state: _HealthState, now: float) -> int:
    if state.opened_at is None:
        return 0
    cooldown = llm_runtime_config.health_cooldown_seconds()
    remaining = int(max(0.0, cooldown - (now - state.opened_at)))
    return remaining


def _append_history_locked(state: _HealthState, use_case: str, status: str, meta: Dict[str, Any]) -> None:
    state.history.append({
        'ts': round(time.time(), 3),
        'use_case': use_case,
        'status': status,
        'latency_ms': _as_int(meta.get('latency_ms')),
        'model': meta.get('model'),
    })
    del state.history[:-20]


def _last_event_locked() -> Optional[Dict[str, Any]]:
    newest: Optional[Dict[str, Any]] = None
    for state in _STATES.values():
        if not state.history:
            continue
        event = state.history[-1]
        if newest is None or float(event.get('ts') or 0.0) >= float(newest.get('ts') or 0.0):
            newest = event
    return dict(newest) if newest else None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    'availability',
    'is_enabled',
    'record_call_result',
    'record_failure',
    'record_success',
    'reset',
    'snapshot',
]
