"""Failure sample collection for the Skill-first learning loop."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..async_file_sink import flush_async_writes, write_jsonl

logger = logging.getLogger('hengpintong.assistant.skill_first.failure_samples')

_ARTIFACT_DIR = Path(__file__).resolve().parents[4] / 'artifacts' / 'assistant-routing'
_FAILURE_FILE = _ARTIFACT_DIR / 'skill-first-failure-samples.jsonl'


def should_capture_failure(trace: Dict[str, Any]) -> bool:
    if not trace:
        return False
    if trace.get('learning_events'):
        return True
    if trace.get('fallback_reason'):
        return True
    if trace.get('permission_result') not in (None, 'allowed'):
        return True
    if trace.get('output_verification_result') not in (None, 'ok'):
        return True
    try:
        return float(trace.get('confidence') or 0) < 0.55
    except (TypeError, ValueError):
        return True


def append_failure_sample(kind: str, trace: Dict[str, Any], extra: Dict[str, Any] | None = None) -> None:
    payload = {
        'kind': kind,
        'request_id': trace.get('request_id'),
        'user_text': trace.get('user_text'),
        'normalized_query': trace.get('normalized_query'),
        'top_k_skills': trace.get('top_k_skills'),
        'candidate_scores': trace.get('candidate_scores') or [],
        'matched_examples': trace.get('matched_examples') or {},
        'selected_skill': trace.get('selected_skill'),
        'rejected_skills': trace.get('rejected_skills') or [],
        'confidence': trace.get('confidence'),
        'fallback_reason': trace.get('fallback_reason'),
        'permission_result': trace.get('permission_result'),
        'risk_result': trace.get('risk_result'),
        'confirmation_policy': trace.get('confirmation_policy'),
        'route_reason': trace.get('route_reason'),
        'slot_fill_result': trace.get('slot_fill_result'),
        'final_executor': trace.get('final_executor'),
        'output_verification_result': trace.get('output_verification_result'),
        'planner_source': trace.get('planner_source'),
        'learning_events': trace.get('learning_events') or [],
        'extra': extra or {},
    }
    write_jsonl(
        _FAILURE_FILE,
        payload,
        logger=logger,
        error_label='skill_first_failure_sample_sink_failed',
    )


def _clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit or 50)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 200))


def _read_failure_jsonl() -> List[Dict[str, Any]]:
    flush_async_writes()
    if not _FAILURE_FILE.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with _FAILURE_FILE.open('r', encoding='utf-8') as fh:
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
        logger.debug('skill_first_failure_sample_read_failed', exc_info=True)
        return []
    return rows


def query_failure_samples(
    *,
    limit: int | None = 50,
    kind: Optional[str] = None,
    request_id: Optional[str] = None,
    selected_skill: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows = []
    for sample in _read_failure_jsonl():
        if kind and sample.get('kind') != kind:
            continue
        if request_id and sample.get('request_id') != request_id:
            continue
        if selected_skill and sample.get('selected_skill') != selected_skill:
            continue
        if keyword:
            haystack = ' '.join(str(sample.get(key) or '') for key in (
                'kind',
                'request_id',
                'user_text',
                'normalized_query',
                'top_k_skills',
                'selected_skill',
                'rejected_skills',
                'fallback_reason',
                'permission_result',
                'output_verification_result',
                'final_executor',
                'route_reason',
            ))
            if keyword.lower() not in haystack.lower():
                continue
        rows.append(sample)
    rows.reverse()
    return rows[:_clamp_limit(limit)]


__all__ = ['append_failure_sample', 'query_failure_samples', 'should_capture_failure']
