"""Route trace and debug sinks for Skill-first runtime."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..async_file_sink import flush_async_writes, write_jsonl

logger = logging.getLogger('hengpintong.assistant.skill_first.observability')

_ARTIFACT_DIR = Path(__file__).resolve().parents[4] / 'artifacts' / 'assistant-routing'
_ROUTE_TRACE_FILE = _ARTIFACT_DIR / 'skill-first-routes.jsonl'


REQUIRED_TRACE_FIELDS = [
    'request_id',
    'user_text',
    'normalized_query',
    'understanding_result',
    'understanding_diagnostics',
    'skill_retrieval_trace',
    'top_k_skills',
    'candidate_scores',
    'matched_examples',
    'selected_skill',
    'rejected_skills',
    'slot_fill_result',
    'confidence',
    'route_reason',
    'planner_diagnostics',
    'skill_provider',
    'skill_playbook',
    'tool_workbench',
    'permission_result',
    'risk_result',
    'confirmation_policy',
    'fallback_reason',
    'latency_ms',
    'final_executor',
    'answer_synthesis',
    'output_verification_result',
]


def ensure_trace_fields(trace: Dict[str, Any]) -> Dict[str, Any]:
    for field in REQUIRED_TRACE_FIELDS:
        trace.setdefault(field, None)
    return trace


def append_route_trace(trace: Dict[str, Any]) -> None:
    payload = ensure_trace_fields(dict(trace))
    write_jsonl(
        _ROUTE_TRACE_FILE,
        payload,
        logger=logger,
        error_label='skill_first_route_trace_sink_failed',
    )


def _clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit or 50)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 200))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    flush_async_writes()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        logger.debug('skill_first_route_trace_read_failed', exc_info=True)
        return []
    return rows


def _matches_trace_filters(
    trace: Dict[str, Any],
    *,
    request_id: Optional[str] = None,
    selected_skill: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    permission_result: Optional[str] = None,
    keyword: Optional[str] = None,
) -> bool:
    if request_id and trace.get('request_id') != request_id:
        return False
    if selected_skill and trace.get('selected_skill') != selected_skill:
        return False
    if fallback_reason and trace.get('fallback_reason') != fallback_reason:
        return False
    if permission_result and trace.get('permission_result') != permission_result:
        return False
    if keyword:
        haystack = ' '.join(str(trace.get(key) or '') for key in (
            'request_id',
            'user_text',
            'normalized_query',
            'selected_skill',
            'route_reason',
            'fallback_reason',
        ))
        if keyword.lower() not in haystack.lower():
            return False
    return True


def query_route_traces(
    *,
    limit: int | None = 50,
    request_id: Optional[str] = None,
    selected_skill: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    permission_result: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows = [
        ensure_trace_fields(dict(trace))
        for trace in _read_jsonl(_ROUTE_TRACE_FILE)
        if _matches_trace_filters(
            trace,
            request_id=request_id,
            selected_skill=selected_skill,
            fallback_reason=fallback_reason,
            permission_result=permission_result,
            keyword=keyword,
        )
    ]
    rows.reverse()
    return rows[:_clamp_limit(limit)]


def get_route_trace(request_id: str) -> Optional[Dict[str, Any]]:
    if not request_id:
        return None
    rows = query_route_traces(limit=1, request_id=request_id)
    return rows[0] if rows else None


__all__ = [
    'REQUIRED_TRACE_FIELDS',
    'append_route_trace',
    'ensure_trace_fields',
    'get_route_trace',
    'query_route_traces',
]
