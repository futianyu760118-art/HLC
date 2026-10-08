"""Direct Agent Skill invocation through formal Kernel nodes.

Product launcher cards resolve to registered Agent Skill Cards before reaching
this module. The launch path skips NL retrieval/planning, but it still runs the
same provider, playbook, permission, execution, answer synthesis and
observability boundaries as ordinary Kernel traffic.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..schemas import AssistantContext, ExecutionResult
from ..skill_first.cards import AgentSkillCard
from .planning import SkillPlan


def direct_skill_message(
    card: AgentSkillCard,
    params: Dict[str, Any],
    *,
    display_name: Optional[str] = None,
) -> str:
    field_desc = ', '.join(f'{key}={value}' for key, value in params.items()) if params else ''
    message = f'[技能调用] {display_name or card.name}'
    if field_desc:
        message += f'（{field_desc}）'
    return message


def unknown_skill_result(
    skill_id: str,
    ctx: AssistantContext,
    *,
    display_name: Optional[str] = None,
    services: Any,
) -> ExecutionResult:
    text_id = str(skill_id or '').strip()
    message = f'[技能调用] {display_name or text_id}'
    start = time.perf_counter()
    trace = services.build_base_trace(message, services.normalize_query(message), [], ctx, start)
    trace.update({
        'fallback_reason': 'direct_skill_unknown_agent_card',
        'risk_result': 'unhandled',
        'direct_invoke': {
            'source': 'agent_kernel.direct_invoke.unknown_skill',
            'skill_id': text_id,
            'display_name': display_name,
            'status': 'unknown_agent_skill_card',
        },
        'output_verification_result': 'ok',
    })
    return services.skill_first_clarification_result(
        message,
        ctx,
        '我还没有足够信息处理这个 HRM 请求。请补充你要查询的模块、对象或时间范围。',
        trace,
        kind='direct_skill_unknown_agent_card',
        error_code='unknown_skill',
    )


def invoke_registered_skill(
    card: AgentSkillCard,
    params: Dict[str, Any],
    ctx: AssistantContext,
    *,
    display_name: Optional[str] = None,
    services: Any,
) -> ExecutionResult:
    clean_params = {k: v for k, v in dict(params or {}).items() if v not in (None, '')}
    message = direct_skill_message(card, clean_params, display_name=display_name)
    plan = SkillPlan(
        normalized_query=services.normalize_query(message),
        selected_skill=card.id,
        confidence=1.0,
        slot_values=clean_params,
        missing_slots=[],
        route_reason='direct_skill_invoke_agent_kernel',
        rejected_skills=[],
        fallback_reason=None,
        planner_source='direct_skill_provider_contract',
        diagnostics={
            'attempted': False,
            'accepted': True,
            'status': 'direct_skill_invoke',
            'reason': 'product_skill_card_click',
        },
    )
    start = time.perf_counter()
    trace = services.trace_from_plan(message, ctx, [], plan, card, start, understanding=None)
    provider_record = services.provide_skill_record_for_card(card)
    trace['skill_provider'] = {
        'schema_mode': 'direct_skill',
        'record_count': 1,
        'candidate_records': [{
            'rank': 1,
            'skill_id': provider_record.skill_id,
            'executor_tool': provider_record.executor_metadata.get('executor_tool'),
            'purpose': provider_record.executor_metadata.get('purpose'),
            'risk_level': provider_record.executor_metadata.get('risk_level'),
            'side_effect': provider_record.executor_metadata.get('side_effect'),
            'confirmation_policy': provider_record.executor_metadata.get('confirmation_policy'),
            'tool_schema_fields': list((provider_record.model_schema.get('tool_schema') or {}).keys()),
            'match_reason': 'direct_skill_invoke',
        }],
        'selected': {
            'skill_id': provider_record.skill_id,
            'model_schema': provider_record.model_schema,
            'executor_metadata': provider_record.executor_metadata,
            'recall_evidence': {'match_reason': 'direct_skill_invoke'},
        },
    }
    trace['kernel'] = {
        'nodes': [
            {'node': 'direct_skill_provider', 'status': 'completed'},
            {'node': 'skill_playbook', 'status': 'pending'},
            {'node': 'permission_gate', 'status': 'pending'},
            {'node': 'execution', 'status': 'pending'},
            {'node': 'answer_synthesis', 'status': 'pending'},
            {'node': 'observability', 'status': 'pending'},
        ]
    }
    trace['kernel_nodes'] = [node['node'] for node in trace['kernel']['nodes']]

    write_reason = services.unsupported_write_intent(message, card)
    if write_reason:
        plan.slot_values['_write_guard'] = write_reason
        result = services.write_guard_result(message, ctx, plan, card)
        trace.update({
            'fallback_reason': 'unsupported_write_intent',
            'final_executor': 'guardrails.detect_write_intent',
            'output_verification_result': 'ok',
        })
        services.attach_trace(result, trace)
        return result

    decision = services.build_route_decision(card, plan)
    decision = services.normalize_tool_plan_inputs(message, decision)
    services.apply_skill_specific_input_guards(card, decision, message)
    trace['route_decision'] = decision.to_dict()
    trace['skill_playbook'] = services.build_skill_playbook(
        message,
        ctx,
        card,
        decision,
        trace['skill_provider']['selected'],
    ).to_dict()
    permission = services.permission_result(card, ctx)
    trace['permission_result'] = permission
    if permission != 'allowed':
        result = services.permission_denied_result(message, ctx, decision, permission)
        trace.update({
            'fallback_reason': 'permission_denied',
            'final_executor': 'guardrails.check_skill_permission',
            'output_verification_result': 'ok',
        })
        services.attach_trace(result, trace)
        return result

    result = services.execute_skill(message, ctx, card, decision, trace)
    outputs = getattr(result, '_kernel_tool_outputs', None)
    outputs_list = list(outputs) if isinstance(outputs, list) else []
    synthesis = services.synthesize_answer(
        message,
        ctx,
        card,
        result,
        outputs_list,
        decision,
        trace,
        trace.get('skill_playbook'),
    )
    trace['answer_synthesis'] = synthesis
    trace['output_verification_result'] = services.verify_output(result, card)
    trace['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)
    if trace['output_verification_result'] != 'ok':
        result.fallback_used = True
        result.error_code = result.error_code or 'skill_first_output_verification_failed'
    services.attach_trace(result, trace)
    return result


__all__ = ['direct_skill_message', 'invoke_registered_skill', 'unknown_skill_result']
