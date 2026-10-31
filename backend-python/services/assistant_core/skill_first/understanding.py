"""LLM-first understanding stage for Skill-first routing."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .. import llm_client
from ..schemas import AssistantContext
from .cards import all_cards
from . import llm_health
from . import llm_runtime_config
from .semantic_index import normalize_query


@dataclass
class UnderstandingResult:
    normalized_query: str
    intent_summary: str = ''
    domain_hints: List[str] = field(default_factory=list)
    entity_mentions: Dict[str, Any] = field(default_factory=dict)
    slot_hints: Dict[str, Any] = field(default_factory=dict)
    reference_hints: Dict[str, Any] = field(default_factory=dict)
    candidate_skill_hints: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = 'deterministic'
    raw: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload['confidence'] = round(float(self.confidence or 0.0), 4)
        return payload


def _llm_availability() -> Tuple[bool, str]:
    flag = os.getenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING')
    if flag is not None and flag.strip().lower() in {'0', 'false', 'off', 'no'}:
        return False, 'disabled_by_env'
    if not llm_client.is_available():
        return False, 'llm_unavailable'
    health_allowed, health_reason, _health = llm_health.availability('skill_first_understanding')
    if not health_allowed:
        return False, health_reason
    return True, 'available'


def _llm_enabled() -> bool:
    enabled, _reason = _llm_availability()
    return enabled


DOMAIN_HINTS = [
    'system',
    'recruitment',
    'candidate',
    'interview',
    'offer',
    'employee',
    'organization',
    'attendance',
    'performance',
    'payroll',
    'approval',
    'feedback',
    'notification',
    'report',
    'workset',
    'smart_data_query',
]


def _messages(message: str, ctx: AssistantContext) -> List[Dict[str, str]]:
    payload = {
        'user_text': message,
        'normalized_query_hint': normalize_query(message),
        'current_page_context': getattr(ctx, 'client_context', {}) or {},
        'recent_history': _compact_history(ctx.history or []),
        'known_domains': DOMAIN_HINTS,
        'output_contract': {
            'normalized_query': 'Chinese normalized query preserving entities and operation intent',
            'intent_summary': 'short Chinese intent summary',
            'domain_hints': 'array from known_domains',
            'entity_mentions': 'object with candidate_names, employee_names, job_keywords, time_expressions, ids when present',
            'slot_hints': 'object with possible slots; do not invent database IDs',
            'reference_hints': 'object describing pronouns/ordinals/workset references such as 第二个/这个人/上面那批',
            'candidate_skill_hints': 'optional array of remembered HRM skill ids only when very obvious; otherwise []',
            'confidence': '0..1 confidence that the understanding is useful',
        },
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Agent 的自然语言理解层，职责是在召回 Skill 之前理解用户原话。'
                '你可以根据口语、多轮历史和当前页面，产出 normalized_query、意图摘要、'
                '实体/槽位/指代提示，以及可能的候选 skill id。'
                '候选 skill id 只是提示，最终 Skill 由后续召回和 planner 决定；不能创造工具，不能写 SQL，不能决定最终执行。'
                '重点理解用户真正意图，不要按关键词机械匹配。返回严格 JSON。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def _clip(value: Any, max_chars: int = 160) -> str:
    text = str(value or '')
    return text if len(text) <= max_chars else text[: max_chars - 1] + '…'


def _compact_history(history: List[Any]) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for item in list(history or [])[-3:]:
        if not isinstance(item, dict):
            continue
        meta = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
        copilot = item.get('copilot') if isinstance(item.get('copilot'), dict) else {}
        trace = copilot.get('routeTrace') if isinstance(copilot.get('routeTrace'), dict) else {}
        worksets = item.get('worksets')
        compacted.append({
            'question': _clip(item.get('question') or item.get('user') or item.get('message'), 70),
            'summary': _clip(item.get('summary') or item.get('answer') or item.get('assistant'), 90),
            'selected_skill': (
                trace.get('selected_skill')
                or trace.get('selectedSkill')
                or meta.get('selected_skill')
                or meta.get('selectedSkill')
            ),
            'worksets': _compact_worksets(worksets),
        })
    return compacted


def _compact_worksets(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        items = item.get('items')
        count = item.get('count') or item.get('size')
        if count is None and isinstance(items, list):
            count = len(items)
        result.append({
            'id': _clip(item.get('id'), 40),
            'kind': _clip(item.get('kind') or item.get('type'), 30),
            'title': _clip(item.get('title') or item.get('label'), 60),
            'count': count,
        })
    return result


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_raw(raw: Any, message: str) -> Optional[UnderstandingResult]:
    if not isinstance(raw, dict):
        return None
    allowed_skill_ids = {card.id for card in all_cards()}
    hinted = []
    for item in _as_list(raw.get('candidate_skill_hints') or raw.get('candidateSkillHints')):
        if item in allowed_skill_ids and item not in hinted:
            hinted.append(item)
    try:
        confidence = max(0.0, min(float(raw.get('confidence') or 0.0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return UnderstandingResult(
        normalized_query=str(raw.get('normalized_query') or raw.get('normalizedQuery') or normalize_query(message)),
        intent_summary=str(raw.get('intent_summary') or raw.get('intentSummary') or ''),
        domain_hints=_as_list(raw.get('domain_hints') or raw.get('domainHints')),
        entity_mentions=_as_dict(raw.get('entity_mentions') or raw.get('entityMentions')),
        slot_hints=_as_dict(raw.get('slot_hints') or raw.get('slotHints')),
        reference_hints=_as_dict(raw.get('reference_hints') or raw.get('referenceHints')),
        candidate_skill_hints=hinted[:12],
        confidence=confidence,
        source='llm',
        raw={key: value for key, value in raw.items() if key not in {'skill_signatures'}},
    )


def understand_query(message: str, ctx: AssistantContext) -> UnderstandingResult:
    enabled, availability_reason = _llm_availability()
    _health_allowed, _health_reason, health_snapshot = llm_health.availability('skill_first_understanding')
    diagnostics: Dict[str, Any] = {
        'stage': 'understanding',
        'use_case': 'skill_first_understanding',
        'llm_enabled': enabled,
        'attempted': False,
        'status': availability_reason,
        'accepted': False,
        'llm_health': health_snapshot,
    }
    deterministic = UnderstandingResult(
        normalized_query=normalize_query(message),
        intent_summary=(message or '').strip()[:120],
        confidence=0.35,
        source='deterministic',
        diagnostics=dict(diagnostics),
    )
    if not enabled:
        return deterministic
    try:
        diagnostics['attempted'] = True
        timeout_seconds = llm_runtime_config.understanding_timeout()
        diagnostics['timeout_seconds'] = timeout_seconds
        raw = llm_client.json_chat_profile(
            'small',
            _messages(message, ctx),
            temperature=0.05,
            max_tokens=450,
            timeout=timeout_seconds,
            use_case='skill_first_understanding',
            retry_once=False,
            ctx=ctx,
        )
        llm_meta = llm_client.last_call_meta()
        try:
            diagnostics['llm_health'] = llm_health.record_call_result('skill_first_understanding', llm_meta)
        except Exception as health_exc:
            diagnostics['llm_health_error'] = {
                'stage': 'health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
        diagnostics['llm_call'] = llm_meta
        diagnostics['raw_type'] = type(raw).__name__
        parsed = _normalize_raw(raw, message)
        if parsed and parsed.confidence >= 0.25:
            diagnostics.update({
                'status': 'accepted',
                'accepted': True,
                'confidence': round(float(parsed.confidence or 0.0), 4),
                'candidate_skill_hints_count': len(parsed.candidate_skill_hints or []),
            })
            parsed.diagnostics = dict(diagnostics)
            return parsed
        diagnostics.update({
            'status': 'low_confidence' if parsed else _diagnostic_status_from_llm_meta(llm_meta),
            'accepted': False,
            'confidence': round(float(parsed.confidence or 0.0), 4) if parsed else None,
        })
    except Exception as exc:
        try:
            diagnostics['llm_health'] = llm_health.record_failure(
                'skill_first_understanding',
                {
                    'status': 'error',
                    'error_type': type(exc).__name__,
                },
            )
        except Exception as health_exc:
            diagnostics['llm_health_error'] = {
                'stage': 'health_recording',
                'error_type': type(health_exc).__name__,
                'error': str(health_exc)[:180],
            }
        diagnostics.update({
            'status': 'exception',
            'accepted': False,
            'error_type': type(exc).__name__,
            'error': str(exc)[:180],
        })
        deterministic.diagnostics = dict(diagnostics)
        return deterministic
    deterministic.diagnostics = dict(diagnostics)
    return deterministic


def _diagnostic_status_from_llm_meta(meta: Dict[str, Any]) -> str:
    status = str((meta or {}).get('status') or '')
    json_status = str((meta or {}).get('json_status') or '')
    if status == 'timeout':
        return 'llm_timeout'
    if status == 'http_error':
        return 'llm_http_error'
    if status == 'error':
        return 'llm_error'
    if status == 'http_error':
        return 'llm_http_error'
    if json_status == 'empty_content':
        return 'llm_empty_content'
    if json_status == 'parse_failed':
        return 'llm_json_parse_failed'
    if status and status != 'success':
        return f'llm_{status}'
    return 'invalid_response'


__all__ = ['UnderstandingResult', 'understand_query']
