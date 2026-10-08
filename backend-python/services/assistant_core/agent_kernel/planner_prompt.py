"""Model-visible planner prompt contracts for the HRM Agent Kernel."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..schemas import AssistantContext
from .skill_provider import model_schemas_from_recall


PLANNER_CANDIDATE_LIMIT = 6
PLANNER_PROMPT_MODE = 'skill_decision_lite'
PLANNER_RETRY_CANDIDATE_LIMIT = 3
PLANNER_RETRY_PROMPT_MODE = 'skill_decision_retry'


def planner_messages(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    *,
    understanding: Optional[Any] = None,
    normalize_query: Callable[[str], str],
) -> List[Dict[str, str]]:
    bounded_candidates = list(candidates)[:PLANNER_CANDIDATE_LIMIT]
    candidate_cards = model_schemas_from_recall(
        bounded_candidates,
        limit=PLANNER_CANDIDATE_LIMIT,
        model_schema_mode='planner',
    )
    payload = {
        'user_text': message,
        'normalized_query_hint': (understanding.normalized_query if understanding else normalize_query(message)),
        'understanding_result': compact_understanding(understanding),
        'current_role': ctx.role,
        'current_page_context': getattr(ctx, 'client_context', {}) or {},
        'recent_history': compact_history(ctx.history or []),
        'top_k_skill_cards': candidate_cards,
        'candidate_boundary': [item.skill_id for item in list(candidates)[:PLANNER_CANDIDATE_LIMIT]],
        'strict_contract': planner_strict_contract(),
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Skill-first Agent Runtime 的受限 planner/reranker。'
                '你只能在用户给定 Top-K Skill Card 中选择一个 skill，不能发明 skill，'
                '不能写 SQL，不能绕过权限或直接执行副作用。'
                '你的任务是理解中文口语、多轮指代和当前页面上下文，在候选 Skill Card 内做语义 rerank、'
                '选择最终 Skill，并说明为什么拒绝其他候选。'
                '槽位只填写用户原话或上下文里非常明确的值；不要为了凑参数猜数据库 ID。'
                '不要因为缺少参数、需要多轮指代解析、需要二次确认或需要权限校验就返回 null；'
                '这些由后续节点处理。'
                '当 Top-K 中有一个 Skill 明显覆盖用户意图时，必须选择它并给出合理置信度。'
                '不要按关键词机械匹配；要判断用户真正想完成的 HRM 任务。'
                '如果候选 Skill 都不合适，selected_skill 必须为 null。返回严格 JSON。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def planner_retry_messages(
    message: str,
    ctx: AssistantContext,
    candidates: Sequence[Any],
    *,
    understanding: Optional[Any] = None,
    first_pass_status: str = '',
    normalize_query: Callable[[str], str],
    get_card: Callable[[str], Any],
) -> List[Dict[str, str]]:
    top_candidates = list(candidates)[:PLANNER_RETRY_CANDIDATE_LIMIT]
    compact_cards = []
    for index, item in enumerate(top_candidates):
        card = get_card(item.skill_id)
        if not card:
            continue
        compact_cards.append({
            'rank': index + 1,
            'id': card.id,
            'name': card.name,
            'domain': card.domain,
            'when_to_use': clip(card.when_to_use[0] if card.when_to_use else card.description, 80),
            'anti_examples': [clip(text, 34) for text in card.anti_examples[:2]],
            'examples': [clip(text, 30) for text in card.colloquial_examples[:2]],
            'required_slots': card.required_slots,
            'side_effect': card.side_effect,
            'recall_score': round(float(item.score or 0.0), 4),
            'matched_text': clip(item.matched_text, 70),
            'anti_score': round(float(getattr(item, 'anti_score', 0.0) or 0.0), 4),
        })
    payload = {
        'retry_reason': first_pass_status or 'first_pass_no_decision',
        'user_text': message,
        'normalized_query_hint': (understanding.normalized_query if understanding else normalize_query(message)),
        'understanding_result': compact_understanding(understanding),
        'current_page_context': getattr(ctx, 'client_context', {}) or {},
        'candidate_boundary': [item.skill_id for item in top_candidates],
        'top_candidates': compact_cards,
        'strict_contract': planner_retry_strict_contract(),
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Agent Kernel 的二次 Skill 裁决节点。第一轮 planner 没能稳定选择，'
                '现在你只看 Top-3 候选做最终 Skill 选择。'
                '如果其中一个候选能处理用户意图，就必须选择它；缺槽位、需要确认、需要权限校验都不是返回 null 的理由。'
                '不得创造 Skill、不得写 SQL、不得执行动作。返回严格 JSON。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def clip(value: Any, max_chars: int = 160) -> str:
    text = str(value or '')
    return text if len(text) <= max_chars else text[: max_chars - 1] + '…'


def compact_history(history: Sequence[Any]) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for item in list(history or [])[-3:]:
        if not isinstance(item, dict):
            continue
        compacted.append({
            'question': clip(item.get('question') or item.get('user') or item.get('message'), 80),
            'summary': clip(item.get('summary') or item.get('answer') or item.get('assistant'), 100),
            'selected_skill': history_selected_skill(item),
            'worksets': compact_history_worksets(item.get('worksets')),
        })
    return compacted


def history_selected_skill(item: Dict[str, Any]) -> Optional[str]:
    meta = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
    copilot = item.get('copilot') if isinstance(item.get('copilot'), dict) else {}
    route_trace = copilot.get('routeTrace') if isinstance(copilot.get('routeTrace'), dict) else {}
    router = meta.get('router') if isinstance(meta.get('router'), dict) else {}
    return (
        route_trace.get('selected_skill')
        or route_trace.get('selectedSkill')
        or router.get('intent')
        or router.get('task_template_id')
    )


def compact_history_worksets(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compacted: List[Dict[str, Any]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        compacted.append({
            'id': item.get('id'),
            'entity_type': item.get('entity_type') or item.get('entityType'),
            'size': item.get('size') or item.get('count'),
        })
    return compacted


def compact_understanding(understanding: Optional[Any]) -> Optional[Dict[str, Any]]:
    if not understanding:
        return None
    return {
        'normalized_query': understanding.normalized_query,
        'intent_summary': clip(understanding.intent_summary, 120),
        'domain_hints': list(understanding.domain_hints or [])[:6],
        'entity_mentions': dict(understanding.entity_mentions or {}),
        'slot_hints': dict(understanding.slot_hints or {}),
        'reference_hints': dict(understanding.reference_hints or {}),
        'candidate_skill_hints': list(understanding.candidate_skill_hints or [])[:8],
        'confidence': round(float(understanding.confidence or 0.0), 4),
        'source': understanding.source,
    }


def planner_strict_contract() -> Dict[str, Any]:
    return {
        'planner_mode': PLANNER_PROMPT_MODE,
        'output_json_fields': [
            'normalized_query',
            'selected_skill',
            'confidence',
            'slot_values',
            'missing_slots',
            'route_reason',
            'rejected_skills',
        ],
        'selected_skill': 'one id from candidate_boundary or null',
        'do_not_create_skill_or_tool': True,
        'do_not_write_sql_or_execute_db': True,
        'side_effect_policy': 'side-effect intent may be selected, but execution becomes pending confirmation only',
        'low_confidence_policy': 'Only return null/<0.48 when all candidates are wrong. Missing slots/IDs/side-effect confirmation/WorkSet are handled later.',
        'selection_policy': 'user intent beats keyword overlap; use anti/anti_score to reject misleading candidates',
        'confidence_calibration': [
            '0.85-0.98: explicit user intent clearly matches one candidate; missing slots may be listed.',
            '0.65-0.84: likely selected Skill but needs slot clarification or WorkSet/reference resolution.',
            '0.48-0.64: weak but still usable candidate inside Top-K.',
            '<0.48 or null: Top-K candidates are genuinely insufficient or misleading.',
        ],
        'slot_policy': 'Skill first; fill only obvious values from text/history/context. Slot-reference node refines later.',
        'strong_recall_hint': 'If rank=1 evidence is strong and intent matches its guide, select it despite shared keywords.',
        'object_vs_list_policy': 'Named person/这个人 => single-object evidence; recent/top/list/count/distribution => list/stat Skill.',
    }


def planner_retry_strict_contract() -> Dict[str, Any]:
    return {
        'planner_mode': PLANNER_RETRY_PROMPT_MODE,
        'output_json_fields': ['normalized_query', 'selected_skill', 'confidence', 'slot_values', 'missing_slots', 'route_reason', 'rejected_skills'],
        'selected_skill': 'one id from candidate_boundary or null',
        'null_policy': (
            'Only return null when every listed candidate is semantically wrong. '
            'Do not return null for missing slots, missing database IDs, permissions, desensitization, or pending confirmation.'
        ),
        'confidence_policy': (
            'If a candidate can handle the user intent, choose it with confidence >= 0.65. '
            'Use missing_slots for unresolved parameters.'
        ),
        'safety_boundary': 'You choose a registered Skill only. Later nodes enforce permissions, confirmation, slot grounding and ToolExecutor schema.',
    }


__all__ = [
    'PLANNER_CANDIDATE_LIMIT',
    'PLANNER_PROMPT_MODE',
    'PLANNER_RETRY_CANDIDATE_LIMIT',
    'PLANNER_RETRY_PROMPT_MODE',
    'clip',
    'compact_history',
    'compact_history_worksets',
    'compact_understanding',
    'history_selected_skill',
    'planner_messages',
    'planner_retry_messages',
    'planner_retry_strict_contract',
    'planner_strict_contract',
]
