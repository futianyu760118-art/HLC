"""Slot, entity and cross-turn reference resolution for the HRM Agent Kernel."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from .. import workset_store
from ..schemas import AssistantContext
from ..skill_first.cards import AgentSkillCard, get_card
from ..skill_first.slot_reference_refiner import refine_slots
from .planning import SkillPlan
from .state import SlotReferenceResolution


def resolve_slots_and_references(
    message: str,
    ctx: AssistantContext,
    card: Optional[AgentSkillCard],
    plan: SkillPlan,
    understanding: Any = None,
) -> SlotReferenceResolution:
    slot_values = dict(getattr(plan, 'slot_values', {}) or {})
    slot_guard_changes = slot_values.pop('_slot_guard_changes', None)
    missing_slots = list(getattr(plan, 'missing_slots', []) or [])
    required_slots = list(getattr(card, 'required_slots', []) or []) if card else []
    optional_slots = list(getattr(card, 'optional_slots', []) or []) if card else []
    reference_hints = getattr(understanding, 'reference_hints', {}) or {}
    reference_detected = has_reference_signal(message, reference_hints, slot_values)
    resolved = None
    try:
        resolved = workset_store.resolve_mention(message, ctx.session_id)
    except Exception:
        resolved = None
    workset_reference_detected = bool(resolved or looks_like_workset_reference_text(message, slot_values, reference_hints))
    if resolved:
        item = resolved.get('item') or {}
        workset = resolved.get('workset') or {}
        current_reference = slot_values.get('latest_workset_or_item') if isinstance(slot_values.get('latest_workset_or_item'), dict) else {}
        resolved_kind = resolved.get('kind')
        resolved_entity_id = item.get('entity_id')
        resolved_entity_type = item.get('entity_type') or workset.get('entity_type')
        slot_values['latest_workset_or_item'] = {
            **current_reference,
            # WorkSet resolution is grounded in the persisted result set. It
            # should override advisory planner slots, especially when a model
            # read "第二个人" as the whole workset instead of the resolved item.
            'kind': resolved_kind or current_reference.get('kind'),
            'workset_id': workset.get('id') or current_reference.get('workset_id'),
            'entity_type': resolved_entity_type or current_reference.get('entity_type'),
            'entity_id': resolved_entity_id or current_reference.get('entity_id'),
        }
        slot_values = apply_resolved_item_slots(card, slot_values, item)
    if should_run_slot_refiner(
        message=message,
        card=card,
        missing_slots=missing_slots,
        reference_detected=reference_detected,
        workset_reference_detected=workset_reference_detected,
    ):
        slot_values, refiner_trace = refine_slots(
            message=message,
            ctx=ctx,
            card=card,
            current_slots=slot_values,
            missing_slots=missing_slots,
            understanding=understanding,
        )
    else:
        refiner_trace = {
            'enabled': False,
            'status': 'skipped_not_needed',
            'source': 'deterministic',
            'applied': False,
            'reason': 'no_missing_slots_or_reference_signal',
        }
    if isinstance(slot_guard_changes, list) and slot_guard_changes:
        refiner_trace = {
            **dict(refiner_trace or {}),
            'normalizer': {
                'source': 'planner.slot_guard',
                'status': 'completed',
                'applied': True,
                'changes': slot_guard_changes,
            },
        }
    grounding_trace = None
    if card and card.id == 'approval.confirm_action':
        slot_values, grounding_trace = ground_approval_confirmation_slots(message, ctx, slot_values)
        if grounding_trace:
            refiner_trace = {
                **dict(refiner_trace or {}),
                'grounding': grounding_trace,
            }
            if grounding_trace.get('applied'):
                source = str(refiner_trace.get('source') or 'deterministic')
                if 'approval_grounding' not in source:
                    refiner_trace['source'] = f'{source}+approval_grounding'
    if card and card.id == 'employee.change_submit_confirm':
        slot_values, employee_grounding = ground_employee_change_slots_from_history(message, ctx, slot_values)
        if employee_grounding:
            refiner_trace = {
                **dict(refiner_trace or {}),
                'employee_change_grounding': employee_grounding,
            }
            if employee_grounding.get('applied'):
                source = str(refiner_trace.get('source') or 'deterministic')
                if 'employee_change_history_grounding' not in source:
                    refiner_trace['source'] = f'{source}+employee_change_history_grounding'
    missing_slots = recompute_missing_slots(card, slot_values, ctx, missing_slots)
    return SlotReferenceResolution(
        slot_values=slot_values,
        missing_slots=missing_slots,
        required_slots=required_slots,
        optional_slots=optional_slots,
        reference_detected=reference_detected,
        workset_reference_detected=workset_reference_detected,
        side_effect=bool(getattr(card, 'side_effect', False)) if card else False,
        planner_source=str(getattr(plan, 'planner_source', '') or ''),
        resolution_source=(
            'planner_guarded_slots+llm_refiner+schema+workset'
            if refiner_trace.get('source') == 'llm'
            else 'planner_guarded_slots+schema+workset'
        ),
        refiner=refiner_trace,
    )


def recompute_missing_slots(
    card: Optional[AgentSkillCard],
    slot_values: Dict[str, Any],
    ctx: AssistantContext,
    previous_missing: List[str],
) -> List[str]:
    if not card:
        return []
    missing: List[str] = []
    for slot in list(getattr(card, 'required_slots', []) or []):
        if not slot_values.get(slot):
            missing.append(slot)
    if card.id == 'interview.schedule_confirm_create':
        latest = slot_values.get('latest_workset_or_item') if isinstance(slot_values.get('latest_workset_or_item'), dict) else {}
        if latest.get('kind') == 'item' and latest.get('entity_type') in {'candidate', 'resume'} and latest.get('entity_id'):
            missing = [slot for slot in missing if slot != 'target_candidate']
    if card.id == 'workset.analysis' and not slot_values.get('latest_workset_or_item'):
        missing.append('latest_workset_or_item')
    if card.id == 'payroll.employee_self_service' and not getattr(ctx, 'user_employee_id', None):
        missing.append('employee_scope')
    for slot in previous_missing or []:
        if slot in set(getattr(card, 'required_slots', []) or []) and not slot_values.get(slot):
            missing.append(slot)
    return list(dict.fromkeys(missing))


def apply_resolved_item_slots(
    card: Optional[AgentSkillCard],
    slot_values: Dict[str, Any],
    item: Dict[str, Any],
) -> Dict[str, Any]:
    if not card or not item:
        return slot_values
    slots = dict(slot_values or {})
    entity_type = str(item.get('entity_type') or '').strip()
    entity_id = item.get('entity_id')
    title = item.get('title')
    if card.id == 'interview.schedule_confirm_create' and entity_type in {'candidate', 'resume'}:
        slots.setdefault('target_candidate', title or entity_id)
    if card.id in {'employee.search', 'employee.profile', 'employee.lifecycle_chain', 'employee.change_impact', 'employee.change_submit_confirm'} and entity_type == 'employee':
        if entity_id:
            slots['employee_id'] = entity_id
        if title or entity_id:
            slots['keyword'] = title or entity_id
    return slots


def ground_employee_change_slots_from_history(
    message: str,
    ctx: AssistantContext,
    slot_values: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if not re.search(r'(这个|这条|这次|调岗|转岗|异动|审批|提交|确认|准备|那就|继续)', message or ''):
        return slot_values, None
    slots = dict(slot_values or {})
    if slots.get('target_department') and (slots.get('keyword') or slots.get('employee_id')):
        return slots, None
    allowed = {
        'employee_id', 'keyword', 'target_department_id', 'target_department',
        'target_position_id', 'target_position', 'effective_date', 'reason',
    }
    trace: Dict[str, Any] = {
        'enabled': True,
        'source': 'deterministic_history_route_decision',
        'applied': False,
    }
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        route_trace = None
        copilot = entry.get('copilot') if isinstance(entry.get('copilot'), dict) else {}
        if isinstance(copilot.get('routeTrace'), dict):
            route_trace = copilot.get('routeTrace')
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        if route_trace is None and isinstance(meta.get('routeTrace'), dict):
            route_trace = meta.get('routeTrace')
        route_decision = meta.get('routeDecision') if isinstance(meta.get('routeDecision'), dict) else {}
        selected = str((route_trace or {}).get('selected_skill') or (route_trace or {}).get('selectedSkill') or '')
        intent = str(route_decision.get('intent') or '')
        if selected not in {'employee.change_impact', 'employee.change_submit_confirm'} and intent not in {'employee.change_impact', 'employee_change_submit'}:
            continue

        recovered: Dict[str, Any] = {}
        slot_fill = (route_trace or {}).get('slot_fill_result') if isinstance((route_trace or {}).get('slot_fill_result'), dict) else {}
        slot_candidates = slot_fill.get('slot_values') if isinstance(slot_fill.get('slot_values'), dict) else {}
        for key, value in slot_candidates.items():
            if key in allowed and value not in (None, '', []):
                recovered[key] = value
        for step in route_decision.get('toolPlan') or []:
            if not isinstance(step, dict):
                continue
            params = step.get('input') if isinstance(step.get('input'), dict) else {}
            for key, value in params.items():
                if key in allowed and value not in (None, '', []):
                    recovered[key] = value
        pending = meta.get('pendingAction') if isinstance(meta.get('pendingAction'), dict) else {}
        for tool in pending.get('tools') or []:
            if not isinstance(tool, dict):
                continue
            params = tool.get('input') if isinstance(tool.get('input'), dict) else {}
            for key, value in params.items():
                if key in allowed and value not in (None, '', []):
                    recovered[key] = value
        if not recovered:
            continue
        before = dict(slots)
        for key, value in recovered.items():
            slots.setdefault(key, value)
        changed = {key: slots.get(key) for key in allowed if before.get(key) != slots.get(key) and slots.get(key)}
        if changed:
            trace.update({
                'applied': True,
                'selected_skill': selected or intent,
                'recovered_slots': changed,
            })
            return slots, trace
    trace['status'] = 'no_history_change_context'
    return slots, trace


def ground_approval_confirmation_slots(
    message: str,
    ctx: AssistantContext,
    slot_values: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    slots = dict(slot_values or {})
    if slots.get('approval_id'):
        return slots, None
    action = normalize_approval_action(slots.get('action') or message)
    if action:
        slots.setdefault('action', action)
    target_index = approval_target_index(slots, message)
    business_terms = approval_business_terms(message)
    trace: Dict[str, Any] = {
        'enabled': True,
        'source': 'deterministic_pending_approval_lookup',
        'applied': False,
        'target_index': target_index,
        'business_terms': business_terms,
    }
    if not action:
        trace['status'] = 'missing_action'
        return slots, trace
    if not target_index and not business_terms:
        trace['status'] = 'missing_rank_or_business_hint'
        return slots, trace
    try:
        from models import ApprovalInstance
    except Exception as exc:
        trace.update({'status': 'model_import_failed', 'error_type': type(exc).__name__})
        return slots, trace

    try:
        query = ApprovalInstance.query.filter(ApprovalInstance.status == 'pending')
        if ctx.role not in {'admin', 'hr_admin', 'manager', 'executive'}:
            query = query.filter(ApprovalInstance.approver_id == ctx.user_id)
        rows = query.order_by(ApprovalInstance.created_at.desc()).limit(50).all()
    except Exception as exc:
        trace.update({'status': 'lookup_failed', 'error_type': type(exc).__name__, 'error': str(exc)[:160]})
        return slots, trace

    filtered = [_approval for _approval in rows if approval_matches_terms(_approval, business_terms)]
    candidates = filtered or ([] if business_terms else rows)
    trace.update({
        'status': 'candidate_lookup',
        'candidate_count': len(rows),
        'filtered_count': len(filtered),
    })
    if not candidates:
        trace['status'] = 'no_matching_pending_approval'
        return slots, trace
    index = target_index or (1 if len(candidates) == 1 else None)
    if not index or index < 1 or index > len(candidates):
        trace['status'] = 'ambiguous_pending_approval'
        return slots, trace
    selected = candidates[index - 1]
    slots['approval_id'] = selected.id
    trace.update({
        'status': 'applied',
        'applied': True,
        'selected_approval_id': selected.id,
        'selected_title': selected.title,
    })
    return slots, trace


def normalize_approval_action(value: Any) -> Optional[str]:
    text = str(value or '').strip().lower()
    if not text:
        return None
    if text in {'approve', 'approved'} or re.search(r'(通过|同意|批准|过了|pass|agree)', text, re.I):
        return 'approve'
    if text in {'reject', 'rejected'} or re.search(r'(驳回|拒绝|不同意|退回|reject|deny)', text, re.I):
        return 'reject'
    return None


def approval_target_index(slot_values: Dict[str, Any], message: str) -> Optional[int]:
    raw = slot_values.get('target_index') or slot_values.get('rank') or slot_values.get('index')
    try:
        value = int(raw)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    text = message or ''
    mapping = {
        '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    }
    match = re.search(r'第\s*([一二两三四五六七八九十\d]+)\s*(?:条|个|项|笔|单)?', text)
    if match:
        token = match.group(1)
        if token.isdigit():
            return int(token)
        return mapping.get(token)
    if re.search(r'(第一条|第一个|首条|第一)', text):
        return 1
    if re.search(r'(第二条|第二个)', text):
        return 2
    return None


def approval_business_terms(message: str) -> List[str]:
    text = message or ''
    groups = [
        (r'请假|休假|调休', ['请假', '休假', '调休', 'leave']),
        (r'报销|费用|差旅', ['报销', '费用', '差旅', 'expense', 'reimbursement']),
        (r'加班', ['加班', 'overtime']),
        (r'调岗|异动|转岗', ['调岗', '异动', '转岗', 'employee_change']),
        (r'调薪|涨薪|降薪|薪资|薪酬', ['调薪', '涨薪', '降薪', '薪资', '薪酬', 'salary']),
        (r'offer|Offer|录用', ['offer', '录用']),
    ]
    terms: List[str] = []
    for pattern, values in groups:
        if re.search(pattern, text, re.I):
            terms.extend(values)
    return list(dict.fromkeys(terms))


def approval_matches_terms(approval: Any, terms: List[str]) -> bool:
    if not terms:
        return True
    haystack = ' '.join([
        str(getattr(approval, 'title', '') or ''),
        str(getattr(approval, 'business_type', '') or ''),
        str(getattr(approval, 'business_id', '') or ''),
    ]).lower()
    return any(str(term).lower() in haystack for term in terms)


def should_run_slot_refiner(
    *,
    message: str,
    card: Optional[AgentSkillCard],
    missing_slots: List[str],
    reference_detected: bool,
    workset_reference_detected: bool,
) -> bool:
    flag = os.getenv('ASSISTANT_SKILL_FIRST_SLOT_LLM')
    if flag is not None and flag.strip().lower() in {'1', 'true', 'on', 'yes'}:
        return True
    if flag is not None and flag.strip().lower() in {'0', 'false', 'off', 'no'}:
        return False
    if not card:
        return False
    if missing_slots or reference_detected or workset_reference_detected:
        return True
    text = message or ''
    return bool(re.search(r'(最近|近\s*\d+\s*[天日周月]|前\s*\d+\s*(?:个|名|位|条)|top\s*\d+|最多|最少|排名|第二个|第一条)', text, re.I))


def refine_skill_after_reference(
    message: str,
    ctx: AssistantContext,
    card: Optional[AgentSkillCard],
    plan: SkillPlan,
    slot_reference: SlotReferenceResolution,
) -> Optional[tuple[SkillPlan, AgentSkillCard]]:
    if not card:
        return None
    if not looks_like_candidate_evaluation_followup(message):
        return None
    latest = (slot_reference.slot_values or {}).get('latest_workset_or_item')
    if not isinstance(latest, dict) or latest.get('kind') != 'item':
        return None
    entity_type = str(latest.get('entity_type') or '').strip()
    entity_id = str(latest.get('entity_id') or '').strip()
    if entity_type not in {'candidate', 'resume'} or not entity_id:
        return None
    refined_card = get_card('candidate.evaluation')
    if not refined_card:
        return None
    if card.id not in {'workset.analysis', 'candidate.search', 'candidate.resume_analysis', 'candidate.recent_resumes', 'candidate.compare'}:
        return None
    slots = dict(slot_reference.slot_values or {})
    slots['question'] = message
    slots.pop('module', None)
    slots.pop('limit', None)
    slots.pop('latest_workset_or_item', None)
    if entity_type == 'candidate':
        slots['candidate_id'] = entity_id
    else:
        slots['resume_id'] = entity_id
    refined_plan = SkillPlan(
        normalized_query=plan.normalized_query,
        selected_skill='candidate.evaluation',
        confidence=max(float(getattr(plan, 'confidence', 0.0) or 0.0), 0.84),
        slot_values=slots,
        missing_slots=[],
        route_reason=f'reference_refinement:{card.id}_single_candidate_evaluation',
        rejected_skills=[
            *list(getattr(plan, 'rejected_skills', []) or []),
            {'skill_id': card.id, 'reason': 'resolved_single_candidate_followup_requires_candidate_evaluation'},
        ],
        fallback_reason=None,
        planner_source=f'{getattr(plan, "planner_source", "") or "planner"}+reference_refinement',
        diagnostics={
            **dict(getattr(plan, 'diagnostics', {}) or {}),
            'reference_refinement_used': True,
            'reference_refinement_from': card.id,
            'reference_refinement_to': 'candidate.evaluation',
            'reference_entity_type': entity_type,
        },
    )
    return refined_plan, refined_card


def looks_like_candidate_evaluation_followup(message: str) -> bool:
    text = message or ''
    return bool(
        re.search(r'(风险|推进|建议|靠不靠谱|稳不稳|怎么样|评价|评估|短板|亮点|是否推荐|值不值得|该不该)', text)
        and re.search(r'(这个人|这位|他|她|第\s*[一二两三四五六七八九十\d]+\s*(?:个|位|名)|第二个|第二位|候选人|简历)', text)
    )


def has_reference_signal(message: str, reference_hints: Dict[str, Any], slot_values: Dict[str, Any]) -> bool:
    if reference_hints:
        return True
    text = message or ''
    if re.search(r'(这个人|这个员工|这个候选人|这位|他|她|上面|刚才|上一批|上轮|第二个|第一条|第\s*\d+\s*(?:个|位|条|项|份))', text):
        return True
    return any(key in slot_values for key in {'latest_workset_or_item', 'target_index'})


def looks_like_workset_reference_text(
    message: str,
    slot_values: Dict[str, Any],
    reference_hints: Dict[str, Any],
) -> bool:
    haystack = ' '.join([
        message or '',
        str(slot_values.get('target_candidate') or ''),
        str(slot_values.get('target_reference') or ''),
        str(reference_hints or ''),
    ])
    return bool(re.search(
        r'(这个|这位|这些|这几|上面|刚才|上一批|上一轮|上轮|前面|第二|第一|第三|'
        r'第\s*\d+|前\s*[一二两三四五六七八九十\d]+|排名|那批|那些|其中|里面|'
        r'ws_|workset)',
        haystack,
        re.I,
    ))


__all__ = [
    'apply_resolved_item_slots',
    'approval_business_terms',
    'approval_matches_terms',
    'approval_target_index',
    'ground_approval_confirmation_slots',
    'ground_employee_change_slots_from_history',
    'has_reference_signal',
    'looks_like_candidate_evaluation_followup',
    'looks_like_workset_reference_text',
    'normalize_approval_action',
    'recompute_missing_slots',
    'refine_skill_after_reference',
    'resolve_slots_and_references',
    'should_run_slot_refiner',
]
