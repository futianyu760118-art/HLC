"""Skill provider boundary for model-visible Agent Kernel capabilities.

This module centralizes the Dify/AutoGen-style split between:

- model-visible Skill schema: safe descriptions, examples, slots and tool
  schema summaries that the LLM can read for planning; and
- executor metadata: registered tool id, hidden defaults, role/risk and
  confirmation boundaries used by the deterministic runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .. import skill_registry
from ..skill_first.cards import AgentSkillCard, get_card
from ..skill_first.semantic_index import RecallResult


@dataclass(frozen=True)
class SkillProviderRecord:
    skill_id: str
    model_schema: Dict[str, Any]
    executor_metadata: Dict[str, Any]
    recall_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_model_schema(self) -> Dict[str, Any]:
        return dict(self.model_schema)

    def to_prompt_optimizer_schema(self) -> Dict[str, Any]:
        payload = dict(self.model_schema)
        payload.update({
            'score': self.recall_evidence.get('score'),
            'match_reason': self.recall_evidence.get('match_reason'),
            'matched_text': self.recall_evidence.get('matched_text'),
        })
        return payload


def records_from_recall(
    candidates: Sequence[RecallResult],
    *,
    limit: Optional[int] = None,
    model_schema_mode: str = 'planner',
) -> List[SkillProviderRecord]:
    records: List[SkillProviderRecord] = []
    bounded = list(candidates)[:limit] if limit is not None else list(candidates)
    for rank, item in enumerate(bounded, start=1):
        card = get_card(item.skill_id)
        if not card:
            continue
        records.append(record_for_card(
            card,
            recall=item,
            rank=rank,
            model_schema_mode=model_schema_mode,
            next_score=_next_score(bounded, rank),
        ))
    return records


def model_schemas_from_recall(
    candidates: Sequence[RecallResult],
    *,
    limit: Optional[int] = None,
    model_schema_mode: str = 'planner',
) -> List[Dict[str, Any]]:
    return [
        record.to_model_schema()
        for record in records_from_recall(candidates, limit=limit, model_schema_mode=model_schema_mode)
    ]


def record_for_card(
    card: AgentSkillCard,
    *,
    recall: Optional[RecallResult] = None,
    rank: Optional[int] = None,
    model_schema_mode: str = 'planner',
    next_score: float = 0.0,
) -> SkillProviderRecord:
    tool = str((card.executor or {}).get('tool') or '')
    spec = skill_registry.get(tool) if tool else None
    tool_schema = _visible_tool_schema(
        getattr(spec, 'input_schema', {}) if spec else {},
        mode=model_schema_mode,
    )
    recall_score = float(getattr(recall, 'score', 0.0) or 0.0) if recall is not None else 0.0
    model_schema = {
        'rank': rank,
        'id': card.id,
        'name': card.name,
        'domain': card.domain,
        'description': _clip(card.description, 120 if model_schema_mode == 'prompt_optimizer' else 78),
        'decision_guide': _clip('；'.join(card.when_to_use[:3]) if card.when_to_use else card.description, 220 if model_schema_mode == 'prompt_optimizer' else 150),
        'anti': [_clip(text, 56 if model_schema_mode == 'prompt_optimizer' else 40) for text in card.anti_examples[:3]],
        'examples': [_clip(text, 44 if model_schema_mode == 'prompt_optimizer' else 30) for text in card.colloquial_examples[:3]],
        'required_slots': list(card.required_slots or []),
        'optional_slots': list(card.optional_slots or [])[:6 if model_schema_mode == 'planner' else 8],
        'slot_hints': _compact_mapping(card.slot_extraction_hints, max_items=5 if model_schema_mode == 'prompt_optimizer' else 4, max_value_chars=90 if model_schema_mode == 'prompt_optimizer' else 56),
        'tool_schema': tool_schema,
        'risk_level': card.risk_level,
        'side_effect': card.side_effect,
        'confirmation_policy': card.confirmation_policy,
        'executor_tool': tool,
    }
    if recall is not None:
        model_schema.update({
            'recall_score': round(recall_score, 4),
            'score_gap_to_next': round(max(0.0, recall_score - float(next_score or 0.0)), 4),
            'matched_text': _clip(getattr(recall, 'matched_text', ''), 64 if model_schema_mode == 'prompt_optimizer' else 44),
            'matched_examples': [_clip(text, 40 if model_schema_mode == 'prompt_optimizer' else 30) for text in (getattr(recall, 'matched_examples', []) or [])[:2 if model_schema_mode == 'prompt_optimizer' else 1]],
            'match_reason': _clip(getattr(recall, 'match_reason', ''), 160 if model_schema_mode == 'prompt_optimizer' else 96),
            'anti_score': round(float(getattr(recall, 'anti_score', 0.0) or 0.0), 4),
        })
    executor_metadata = {
        'skill_id': card.id,
        'executor_tool': tool,
        'purpose': (card.executor or {}).get('purpose') or ('side_effect' if card.side_effect else 'query'),
        'defaults': dict((card.executor or {}).get('defaults') or {}),
        'allowed_roles': list(card.allowed_roles or []),
        'risk_level': card.risk_level,
        'side_effect': card.side_effect,
        'confirmation_policy': card.confirmation_policy,
        'desensitization_policy': card.desensitization_policy,
        'fallback_policy': card.fallback_policy,
    }
    recall_evidence = {}
    if recall is not None:
        recall_evidence = {
            'rank': rank,
            'score': round(recall_score, 4),
            'match_reason': getattr(recall, 'match_reason', ''),
            'matched_text': getattr(recall, 'matched_text', ''),
            'matched_examples': list(getattr(recall, 'matched_examples', []) or []),
            'anti_score': round(float(getattr(recall, 'anti_score', 0.0) or 0.0), 4),
        }
    return SkillProviderRecord(
        skill_id=card.id,
        model_schema=model_schema,
        executor_metadata=executor_metadata,
        recall_evidence=recall_evidence,
    )


def _next_score(candidates: Sequence[RecallResult], rank: int) -> float:
    next_index = rank
    if next_index < len(candidates):
        return float(candidates[next_index].score or 0.0)
    return 0.0


def _visible_tool_schema(schema: Mapping[str, Any], *, mode: str) -> Dict[str, Any]:
    visible: Dict[str, Any] = {}
    max_fields = 6 if mode == 'planner' else 12
    for key, rule in dict(schema or {}).items():
        if len(visible) >= max_fields:
            break
        if key in {'sql', 'candidate_sql', 'candidateSql', 'raw_sql', 'rawSql', 'query_plan', 'queryPlan'}:
            continue
        if not isinstance(rule, Mapping):
            continue
        if mode == 'planner':
            expected = str(rule.get('type') or 'any')
            suffix = '!' if rule.get('required') else ''
            visible[str(key)] = f'{expected}{suffix}'
            continue
        item: Dict[str, Any] = {
            'type': rule.get('type'),
            'required': bool(rule.get('required')),
        }
        if 'enum' in rule:
            item['enum'] = list(rule.get('enum') or [])
        if 'default' in rule:
            item['default'] = rule.get('default')
        visible[str(key)] = {k: v for k, v in item.items() if v not in (None, [], {})}
    return visible


def _compact_mapping(mapping: Mapping[str, Any], *, max_items: int, max_value_chars: int) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for index, (key, value) in enumerate(dict(mapping or {}).items()):
        if index >= max_items:
            break
        result[str(key)] = _clip(value, max_value_chars)
    return result


def _clip(value: Any, max_chars: int = 160) -> str:
    text = str(value or '')
    return text if len(text) <= max_chars else text[: max_chars - 1] + '…'


__all__ = [
    'SkillProviderRecord',
    'model_schemas_from_recall',
    'record_for_card',
    'records_from_recall',
]
