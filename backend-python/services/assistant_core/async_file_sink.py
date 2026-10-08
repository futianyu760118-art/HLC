"""Small async JSONL sink for non-blocking assistant diagnostics."""

from __future__ import annotations

import atexit
import json
import os
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

_EXECUTOR: Optional[ThreadPoolExecutor] = None
_FUTURES: list[Future] = []
_LOCK = Lock()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() not in {'0', 'false', 'off', 'no'}


def async_observability_enabled() -> bool:
    raw = os.getenv('ASSISTANT_ASYNC_OBSERVABILITY')
    if raw is not None and raw.strip() != '':
        return _env_bool('ASSISTANT_ASYNC_OBSERVABILITY', True)
    if os.getenv('PYTEST_CURRENT_TEST'):
        return False
    return True


def write_jsonl(
    path: Path,
    payload: Dict[str, Any],
    *,
    logger: Any,
    error_label: str,
) -> None:
    line = json.dumps(payload, ensure_ascii=False, default=str) + '\n'
    if not async_observability_enabled():
        _write_line(path, line, logger=logger, error_label=error_label)
        return
    try:
        future = _executor().submit(_write_line, path, line, logger=logger, error_label=error_label)
        with _LOCK:
            _FUTURES.append(future)
            _FUTURES[:] = [item for item in _FUTURES if not item.done()]
    except Exception:
        _write_line(path, line, logger=logger, error_label=error_label)


def flush_async_writes() -> None:
    with _LOCK:
        futures = list(_FUTURES)
        _FUTURES.clear()
    for future in futures:
        try:
            future.result(timeout=2)
        except Exception:
            pass


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        with _LOCK:
            if _EXECUTOR is None:
                _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='assistant-observability')
    return _EXECUTOR


def _write_line(path: Path, line: str, *, logger: Any, error_label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as fh:
            fh.write(line)
    except Exception:
        logger.debug(error_label, exc_info=True)


def _shutdown() -> None:
    flush_async_writes()
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=True)


atexit.register(_shutdown)


__all__ = ['async_observability_enabled', 'flush_async_writes', 'write_jsonl']
