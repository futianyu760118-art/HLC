"""Skill execution playbooks for the HRM Agent Kernel.

The playbook is a small, observable execution brief produced after the planner
has selected a registered Skill. It does not choose tools or bypass policy; it
describes how the already selected Skill should gather evidence, execute and
compose an answer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .. import llm_client
from ..schemas import AssistantContext, RouteDecision
from ..skill_first import llm_health, llm_runtime_config
from ..skill_first.cards import AgentSkillCard, all_cards, get_card


@dataclass(frozen=True)
class SkillPlaybook:
    skill_id: str
    mode: str
    executor_tool: str
    risk_level: str
    side_effect: bool
    confirmation_policy: str
    evidence_plan: List[str] = field(default_factory=list)
    execution_steps: List[Dict[str, Any]] = field(default_factory=list)
    answer_guidance: List[str] = field(default_factory=list)
    followup_prompts: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'skill_id': self.skill_id,
            'mode': self.mode,
            'executor_tool': self.executor_tool,
            'risk_level': self.risk_level,
            'side_effect': self.side_effect,
            'confirmation_policy': self.confirmation_policy,
            'evidence_plan': list(self.evidence_plan),
            'execution_steps': [dict(item) for item in self.execution_steps],
            'answer_guidance': list(self.answer_guidance),
            'followup_prompts': list(self.followup_prompts),
            'diagnostics': dict(self.diagnostics),
        }


@dataclass(frozen=True)
class SkillPlaybookGuide:
    """Optional project-local playbook guide loaded from SKILL.md."""

    name: str
    description: str
    body: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'body': self.body,
            'source': self.source,
        }


class SkillPlaybookGuideRegistry:
    """Registry for optional SKILL.md guides.

    This is retained as a CUGA-style loading mechanism, but it is now owned by
    the Agent Kernel. Guides are advisory input for playbook construction; they
    are not prompt prefixes and they cannot override provider/tool contracts.
    """

    def __init__(self, entries: Sequence[SkillPlaybookGuide]):
        self._by_name: Dict[str, SkillPlaybookGuide] = {entry.name: entry for entry in entries}

    def list(self) -> List[SkillPlaybookGuide]:
        return list(self._by_name.values())

    def get(self, name: str) -> Optional[SkillPlaybookGuide]:
        return self._by_name.get(name)

    def load_skill(self, name: str) -> str:
        entry = self.get(name)
        if not entry:
            known = ', '.join(sorted(self._by_name)) or '(none)'
            return f"Unknown skill: {name!r}. Known skills: {known}"
        return (
            f"# Loaded Skill: {entry.name}\n\n"
            f"Source: {entry.source}\n\n"
            f"{entry.body.strip()}\n"
        )


def build_playbook(
    *,
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    decision: RouteDecision,
    provider_selected: Optional[Mapping[str, Any]] = None,
) -> SkillPlaybook:
    guide = _guide_for_skill(card.id)
    base = _deterministic_playbook(
        message=message,
        card=card,
        decision=decision,
        provider_selected=provider_selected,
        guide=guide,
    )
    enriched = _llm_enriched_playbook(
        message=message,
        ctx=ctx,
        card=card,
        decision=decision,
        provider_selected=provider_selected,
        base=base,
    )
    return enriched or base


def _deterministic_playbook(
    *,
    message: str,
    card: AgentSkillCard,
    decision: RouteDecision,
    provider_selected: Optional[Mapping[str, Any]] = None,
    guide: Optional[SkillPlaybookGuide] = None,
) -> SkillPlaybook:
    provider = dict(provider_selected or {})
    executor_metadata = provider.get('executor_metadata') if isinstance(provider.get('executor_metadata'), dict) else {}
    model_schema = provider.get('model_schema') if isinstance(provider.get('model_schema'), dict) else {}
    executor_tool = str(
        executor_metadata.get('executor_tool')
        or model_schema.get('executor_tool')
        or ((card.executor or {}).get('tool') if card else '')
        or ''
    )
    tool_steps = [
        {
            'step_id': item.step_id,
            'tool': item.tool,
            'purpose': item.purpose,
            'required': item.required,
            'risk_level': item.risk_level,
            'input_keys': sorted((item.input or {}).keys()),
        }
        for item in (decision.tool_plan or [])
    ]
    evidence_plan = _evidence_plan_for_card(card, decision, model_schema)
    answer_guidance = _answer_guidance_for_card(card, message)
    diagnostics = {
        'source': 'deterministic',
        'llm_enabled': _llm_playbook_enabled(),
        'provider_skill': provider.get('skill_id'),
        'tool_plan_count': len(tool_steps),
        'model_schema_available': bool(model_schema),
        'guide_source': guide.source if guide else None,
    }
    return SkillPlaybook(
        skill_id=card.id,
        mode='pending_confirmation' if card.side_effect else 'read_only_execution',
        executor_tool=executor_tool,
        risk_level=card.risk_level,
        side_effect=card.side_effect,
        confirmation_policy=card.confirmation_policy,
        evidence_plan=_merge_list(evidence_plan, _guide_evidence_plan(guide), limit=8),
        execution_steps=tool_steps,
        answer_guidance=_merge_list(answer_guidance, _guide_answer_guidance(guide), limit=8),
        followup_prompts=_followup_prompts_for_card(card),
        diagnostics=diagnostics,
    )


def _llm_enriched_playbook(
    *,
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    decision: RouteDecision,
    provider_selected: Optional[Mapping[str, Any]],
    base: SkillPlaybook,
) -> Optional[SkillPlaybook]:
    if not _llm_playbook_enabled():
        return None
    if not llm_client.is_available():
        return _with_diagnostics(base, source='deterministic', llm_status='unavailable')
    health_allowed, reason, health = llm_health.availability('skill_first_playbook')
    if not health_allowed:
        return _with_diagnostics(base, source='deterministic', llm_status=reason, health=health)

    messages = _messages(
        message=message,
        card=card,
        decision=decision,
        provider_selected=provider_selected,
        base=base,
    )
    try:
        raw = llm_client.json_chat_profile(
            'small',
            messages,
            temperature=0.1,
            max_tokens=650,
            timeout=llm_runtime_config.playbook_timeout(),
            use_case='skill_first_playbook',
            retry_once=False,
            ctx=ctx,
        )
        llm_health.record_call_result('skill_first_playbook', llm_client.last_call_meta())
    except Exception:
        llm_health.record_failure('skill_first_playbook', {'status': 'error'})
        return _with_diagnostics(base, source='deterministic', llm_status='exception')
    if not isinstance(raw, dict):
        return _with_diagnostics(base, source='deterministic', llm_status='invalid_response')

    enriched = _bounded_enrichment(raw)
    if not enriched:
        return _with_diagnostics(base, source='deterministic', llm_status='empty_enrichment')
    return SkillPlaybook(
        skill_id=base.skill_id,
        mode=base.mode,
        executor_tool=base.executor_tool,
        risk_level=base.risk_level,
        side_effect=base.side_effect,
        confirmation_policy=base.confirmation_policy,
        evidence_plan=_merge_list(base.evidence_plan, enriched.get('evidence_plan'), limit=8),
        execution_steps=base.execution_steps,
        answer_guidance=_merge_list(base.answer_guidance, enriched.get('answer_guidance'), limit=8),
        followup_prompts=_merge_list(base.followup_prompts, enriched.get('followup_prompts'), limit=5),
        diagnostics={
            **dict(base.diagnostics),
            'source': 'llm_enriched',
            'llm_status': 'accepted',
            'llm_attempted': True,
            'llm_accepted': True,
        },
    )


def _messages(
    *,
    message: str,
    card: AgentSkillCard,
    decision: RouteDecision,
    provider_selected: Optional[Mapping[str, Any]],
    base: SkillPlaybook,
) -> List[Dict[str, str]]:
    payload = {
        'user_text': message,
        'selected_skill': {
            'id': card.id,
            'name': card.name,
            'domain': card.domain,
            'description': card.description,
            'risk_level': card.risk_level,
            'side_effect': card.side_effect,
            'confirmation_policy': card.confirmation_policy,
            'verification_rules': card.verification_rules[:5],
        },
        'provider_selected': provider_selected or {},
        'route_decision': decision.to_dict(),
        'base_playbook': base.to_dict(),
        'contract': {
            'only_enrich': True,
            'do_not_change_tool': True,
            'do_not_add_side_effect': True,
            'do_not_add_sql': True,
            'return_json_object': True,
            'allowed_keys': ['evidence_plan', 'answer_guidance', 'followup_prompts'],
        },
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Agent Kernel 的 Skill playbook 细化节点。'
                '你只能补充证据关注点、回答组织建议和自然追问建议；不能改变 Skill、tool、权限、'
                '参数、SQL、确认策略或执行结果。返回 JSON object。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def discover_skill_playbook_guides(root: Path | None = None) -> List[SkillPlaybookGuide]:
    """Discover optional project-local SKILL.md playbook guides."""

    base = root or Path(__file__).resolve().parents[4]
    search_roots = [
        base / '.agents' / 'skills',
        base / 'backend-python' / 'services' / 'assistant_core' / 'agent_kernel' / 'playbooks',
    ]
    entries: Dict[str, SkillPlaybookGuide] = {}
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob('SKILL.md'):
            entry = _parse_skill_md(path)
            if entry:
                entries[entry.name] = entry
    return list(entries.values())


def build_card_playbook_guide_registry(skill_ids: Sequence[str] | None = None) -> SkillPlaybookGuideRegistry:
    if skill_ids is None:
        return _cached_card_playbook_guide_registry(None)
    normalized = tuple(sorted({str(skill_id) for skill_id in skill_ids if skill_id}))
    return _cached_card_playbook_guide_registry(normalized)


@lru_cache(maxsize=128)
def _cached_card_playbook_guide_registry(skill_ids: tuple[str, ...] | None) -> SkillPlaybookGuideRegistry:
    cards = []
    if skill_ids is None:
        cards = all_cards()
    else:
        for skill_id in skill_ids:
            card = get_card(str(skill_id))
            if card:
                cards.append(card)
    entries = [_guide_from_card(card) for card in cards]
    external = discover_skill_playbook_guides()
    by_name = {entry.name: entry for entry in entries}
    by_name.update({entry.name: entry for entry in external})
    return SkillPlaybookGuideRegistry(list(by_name.values()))


def format_available_skill_guides(registry: SkillPlaybookGuideRegistry) -> str:
    """Format a compact guide list for diagnostics, not for planner prompts."""

    lines = ['<agent_kernel_skill_guides>']
    for entry in registry.list():
        lines.append(f'- {entry.name}: {entry.description}')
    lines.append('</agent_kernel_skill_guides>')
    lines.append(
        'Guides are advisory playbook context. They must not override selected '
        'Skill IDs, provider executor metadata, ToolWorkbench schema checks, '
        'permissions, risk gates, SQL boundaries or confirmation policy.'
    )
    return '\n'.join(lines)


def _guide_for_skill(skill_id: str) -> Optional[SkillPlaybookGuide]:
    return build_card_playbook_guide_registry([skill_id]).get(skill_id)


def clear_playbook_guide_cache() -> None:
    _cached_card_playbook_guide_registry.cache_clear()


def _guide_from_card(card: AgentSkillCard) -> SkillPlaybookGuide:
    body = f"""
## When To Use
{chr(10).join(f'- {item}' for item in card.when_to_use)}

## Anti Examples
{chr(10).join(f'- {item}' for item in card.anti_examples)}

## Colloquial Examples
{chr(10).join(f'- {item}' for item in card.colloquial_examples)}

## Slots
Required: {', '.join(card.required_slots) or '(none)'}
Optional: {', '.join(card.optional_slots) or '(none)'}

## Slot Extraction Hints
{chr(10).join(f'- {key}: {value}' for key, value in card.slot_extraction_hints.items()) or '- (none)'}

## Execution Contract
- Skill ID: {card.id}
- Domain: {card.domain}
- Risk level: {card.risk_level}
- Side effect: {card.side_effect}
- Executor: {card.executor}
- Confirmation policy: {card.confirmation_policy}
- Desensitization policy: {card.desensitization_policy}
- Fallback policy: {card.fallback_policy}

## Verification Rules
{chr(10).join(f'- {item}' for item in card.verification_rules)}
"""
    return SkillPlaybookGuide(
        name=card.id,
        description=card.description,
        body=body,
        source='agent_skill_card',
    )


def _parse_skill_md(path: Path) -> Optional[SkillPlaybookGuide]:
    try:
        raw = path.read_text(encoding='utf-8')
    except Exception:
        return None
    name = ''
    description = ''
    body = raw
    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) >= 3:
            header_lines = parts[1].splitlines()
            name = _frontmatter_value(header_lines, 'name') or ''
            description = _frontmatter_value(header_lines, 'description') or ''
            body = parts[2]
    if not name:
        name = path.parent.name
    if not description:
        description = body.strip().splitlines()[0][:120] if body.strip() else name
    return SkillPlaybookGuide(name=name, description=description, body=body, source=str(path))


def _frontmatter_value(lines: List[str], key: str) -> Optional[str]:
    prefix = f'{key}:'
    for line in lines:
        if line.strip().lower().startswith(prefix):
            return line.split(':', 1)[1].strip().strip('"').strip("'")
    return None


def _guide_evidence_plan(guide: Optional[SkillPlaybookGuide]) -> List[str]:
    if not guide:
        return []
    return _extract_guide_lines(guide.body, ['Verification Rules', 'Execution Contract'], limit=3, prefix='guide:')


def _guide_answer_guidance(guide: Optional[SkillPlaybookGuide]) -> List[str]:
    if not guide:
        return []
    return _extract_guide_lines(guide.body, ['When To Use', 'Anti Examples'], limit=3, prefix='guide:')


def _extract_guide_lines(body: str, section_names: Sequence[str], *, limit: int, prefix: str) -> List[str]:
    lines = []
    active = False
    wanted = {name.lower() for name in section_names}
    for raw_line in (body or '').splitlines():
        line = raw_line.strip()
        if line.startswith('## '):
            active = line[3:].strip().lower() in wanted
            continue
        if not active or not line.startswith('- '):
            continue
        text = line[2:].strip()
        if text:
            lines.append((prefix + text)[:100])
        if len(lines) >= limit:
            break
    return lines


def _bounded_enrichment(raw: Mapping[str, Any]) -> Dict[str, List[str]]:
    return {
        'evidence_plan': _bounded_text_list(raw.get('evidence_plan'), limit=4, max_chars=80),
        'answer_guidance': _bounded_text_list(raw.get('answer_guidance'), limit=4, max_chars=90),
        'followup_prompts': _bounded_text_list(raw.get('followup_prompts'), limit=3, max_chars=60),
    }


def _evidence_plan_for_card(card: AgentSkillCard, decision: RouteDecision, model_schema: Mapping[str, Any]) -> List[str]:
    steps = []
    tool_names = [item.tool for item in (decision.tool_plan or []) if item.tool]
    if tool_names:
        steps.append('execute_registered_tools:' + ','.join(tool_names[:4]))
    if card.required_slots:
        steps.append('verify_required_slots:' + ','.join(card.required_slots[:6]))
    if model_schema.get('tool_schema'):
        steps.append('validate_tool_schema:' + ','.join(list((model_schema.get('tool_schema') or {}).keys())[:6]))
    if card.side_effect:
        steps.append('prepare_pending_confirmation_only')
    else:
        steps.append('ground_answer_in_tool_outputs')
    if card.verification_rules:
        steps.append('check_verification_rules:' + ';'.join(card.verification_rules[:2]))
    return steps[:8]


def _answer_guidance_for_card(card: AgentSkillCard, message: str) -> List[str]:
    guidance = [
        'answer_in_chinese',
        'cite_available_records_and_widgets',
        'do_not_invent_missing_business_facts',
    ]
    if card.side_effect:
        guidance.append('state_pending_confirmation_not_executed')
    if card.risk_level in {'high', 'critical'}:
        guidance.append('respect_permission_and_desensitization_boundary')
    if any(word in (message or '') for word in ('为什么', '原因', '依据', '证据')):
        guidance.append('prioritize_evidence_and_reasoning')
    return guidance


def _followup_prompts_for_card(card: AgentSkillCard) -> List[str]:
    if card.side_effect:
        return ['确认执行', '取消动作']
    if card.domain == 'candidate':
        return ['继续分析这个候选人', '对比同岗位候选人']
    if card.domain == 'attendance':
        return ['查看异常证据', '生成提醒草稿']
    if card.domain == 'payroll':
        return ['查看薪资异常明细', '联动绩效分析']
    return ['继续追问这批结果', '查看证据来源']


def _merge_list(base: Sequence[str], extra: Any, *, limit: int) -> List[str]:
    values = []
    for item in list(base or []) + _bounded_text_list(extra, limit=limit, max_chars=100):
        if item and item not in values:
            values.append(item)
        if len(values) >= limit:
            break
    return values


def _bounded_text_list(value: Any, *, limit: int, max_chars: int) -> List[str]:
    raw_items = value if isinstance(value, list) else []
    result: List[str] = []
    for item in raw_items:
        text = str(item or '').strip()
        if not text:
            continue
        text = text[:max_chars]
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _with_diagnostics(base: SkillPlaybook, **updates: Any) -> SkillPlaybook:
    return SkillPlaybook(
        skill_id=base.skill_id,
        mode=base.mode,
        executor_tool=base.executor_tool,
        risk_level=base.risk_level,
        side_effect=base.side_effect,
        confirmation_policy=base.confirmation_policy,
        evidence_plan=base.evidence_plan,
        execution_steps=base.execution_steps,
        answer_guidance=base.answer_guidance,
        followup_prompts=base.followup_prompts,
        diagnostics={**dict(base.diagnostics), **{key: value for key, value in updates.items() if value is not None}},
    )


def _llm_playbook_enabled() -> bool:
    raw = os.getenv('ASSISTANT_SKILL_FIRST_PLAYBOOK_LLM')
    if raw is None or raw.strip() == '':
        return False
    return raw.strip().lower() not in {'0', 'false', 'off', 'no'}


__all__ = [
    'SkillPlaybook',
    'SkillPlaybookGuide',
    'SkillPlaybookGuideRegistry',
    'build_card_playbook_guide_registry',
    'build_playbook',
    'discover_skill_playbook_guides',
    'format_available_skill_guides',
]
