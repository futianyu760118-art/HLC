"""LLM-first skill planner.

This module moves the assistant's primary routing decision from a static
task-template lookup to a model-selected skill plan. The planner is intentionally
bounded: the model may only choose registered skills, side-effect skills are
converted into chat confirmation plans, and the old router remains the fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from .. import llm_client, skill_registry
from ..smart_query import build_schema_summary
from ..guardrails import detect_write_intent
from ..model_settings import feature_enabled
from ..schemas import (
    AssistantContext,
    GenerationPlan,
    RouteDecision,
    SkillSpec,
    ToolCallPlan,
)
from .classifier import TRACK_A, TRACK_B, TRACK_C, TRACK_COMPOSITE

logger = logging.getLogger('hengpintong.assistant.llm_skill_planner')

MIN_ACCEPT_CONFIDENCE = 0.62
MAX_SKILL_OPTIONS = 40
MAX_TOOL_STEPS = 4
_PLAN_CACHE_TTL_SECONDS = 90
_PLAN_CACHE: Dict[str, tuple[float, RouteDecision]] = {}


def _skill_catalog(ctx: AssistantContext) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for spec in skill_registry.all_skills()[:MAX_SKILL_OPTIONS]:
        catalog.append({
            'id': spec.id,
            'name': spec.name,
            'domain': spec.domain,
            'description': spec.description,
            'input_schema': spec.input_schema,
            'risk_level': spec.risk_level,
            'side_effect': spec.side_effect,
            'action_type': spec.action_type,
            'allowed_for_current_role': (not spec.allowed_roles) or ctx.role in spec.allowed_roles,
        })
    return catalog


def _system_prompt() -> str:
    return (
        '你是恒聘通 HRM 的技能规划器。你的任务不是回答用户，而是直接选择系统技能并给出执行计划。\n'
        '第一步必须先把用户口语原话改写成“系统可执行的规范请求”：去掉我们/现在/多少/有哪些等口语噪音，'
        '保留真实业务对象、模块、状态、时间范围、数量口径和后续动作。然后再基于规范请求规划工具参数。\n'
        '必须只从 skill_catalog 中选择工具，不要创造工具名。数据读取必须通过工具；不要让大模型假装查库。\n'
        '如果用户只是解释、翻译、润色、总结自己提供的文本或闲聊，route_track 用 C_DIALOGUE_KNOWLEDGE，不要调用 global_search。\n'
        '如果用户要写邮件、生成面试题、报告、分析、评价，route_track 用 B_GENERATION；需要系统私有数据时，'
        '先在 tool_plan 里选择 evidence/search/detail 类工具加载上下文。\n'
        '如果用户要查、找、统计、列出系统数据，route_track 用 A_DATA_ACTION，并直接选择最合适的查询技能。\n'
        '当用户只给姓名、岗位、关键词，或问题可能横跨多个模块时，优先使用 system_search 找系统证据；'
        '当用户追问“其中/里面/这些人/上面结果里谁最高最低最大最小最近”等，优先使用 workset_analyze 分析上一轮结果集。\n'
        '当固定业务技能无法覆盖复杂 SELECT/JOIN/分组/聚合/排名/趋势/交叉统计时，可以使用 smart_data_query。'
        'smart_data_query 的 input 必须包含 question、sql、explanation；sql 只能是一条 SELECT 或 WITH...SELECT，'
        '可包含 JOIN、GROUP BY、ORDER BY、聚合函数，不能包含 INSERT/UPDATE/DELETE/DDL/审批/发送/创建等副作用。\n'
        '如果用户要求“先查再生成/分析/出题”，route_track 用 COMPOSITE，tool_plan 先查数据，再 generation_plan 生成。\n'
        '删除、审批、发送、创建面试/任务等副作用动作必须 requires_confirmation=true；不要直接执行。\n'
        '返回严格 JSON，字段：normalized_query, task_type, route_track, intent, confidence, risk_level, required_context, '
        'tool_plan, generation_plan, requires_confirmation, clarification_question, reason。'
        'tool_plan 项字段：tool, purpose, input, required, risk_level。'
    )


def _messages(message: str, ctx: AssistantContext) -> List[Dict[str, str]]:
    history = (ctx.history or [])[-6:]
    payload = {
        'user_message': message,
        'current_user_role': ctx.role,
        'recent_history': history,
        'skill_catalog': _skill_catalog(ctx),
        'database_schema_summary_for_smart_data_query': build_schema_summary()[:12000],
        'output_contract': {
            'normalized_query': '把用户原话改写成面向系统工具的规范中文请求，不要包含无意义口语噪音。',
            'route_track': ['A_DATA_ACTION', 'B_GENERATION', 'C_DIALOGUE_KNOWLEDGE', 'COMPOSITE'],
            'task_type': ['data_query', 'action', 'generation', 'dialogue', 'knowledge', 'composite', 'clarification', 'forbidden'],
            'tool_purpose': ['query', 'load_context', 'side_effect', 'render'],
            'generation_template_examples': [
                'generic_generation', 'interview_questions', 'candidate_compare',
                'person_assessment', 'analysis_report', 'hr_email_draft', 'job_posting',
            ],
        },
    }
    return [
        {'role': 'system', 'content': _system_prompt()},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def _cache_key(message: str, ctx: AssistantContext) -> str:
    user_id = getattr(ctx, 'user_id', None) or getattr(ctx, 'audit_user_id', None) or 'anonymous'
    return f'{user_id}|{ctx.role}|{(message or "").strip().lower()}'


def _clone_decision(decision: RouteDecision) -> RouteDecision:
    return RouteDecision(
        task_type=decision.task_type,
        route_track=decision.route_track,
        intent=decision.intent,
        confidence=decision.confidence,
        risk_level=decision.risk_level,
        task_template_id=decision.task_template_id,
        required_context=list(decision.required_context or []),
        tool_plan=[
            ToolCallPlan(
                step_id=p.step_id,
                tool=p.tool,
                purpose=p.purpose,
                input=dict(p.input or {}),
                iterate_over=p.iterate_over,
                required=p.required,
                risk_level=p.risk_level,
                cache_policy=p.cache_policy,
            )
            for p in decision.tool_plan
        ],
        generation_plan=GenerationPlan(
            template_id=decision.generation_plan.template_id,
            prompt_template=decision.generation_plan.prompt_template,
            output_format=decision.generation_plan.output_format,
            model_profile=decision.generation_plan.model_profile,
            max_tokens=decision.generation_plan.max_tokens,
            temperature=decision.generation_plan.temperature,
            constraints=dict(decision.generation_plan.constraints or {}),
        ) if decision.generation_plan else None,
        clarification_question=decision.clarification_question,
        clarification_options=list(decision.clarification_options or []),
        requires_confirmation=decision.requires_confirmation,
        safety_flags=list(decision.safety_flags or []),
        fallback_policy=decision.fallback_policy,
        reason=decision.reason,
    )


def _get_cached_plan(message: str, ctx: AssistantContext) -> Optional[RouteDecision]:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    key = _cache_key(message, ctx)
    cached = _PLAN_CACHE.get(key)
    if not cached:
        return None
    created_at, decision = cached
    if time.time() - created_at > _PLAN_CACHE_TTL_SECONDS:
        _PLAN_CACHE.pop(key, None)
        return None
    cloned = _clone_decision(decision)
    cloned.reason = (cloned.reason or '') + ';planner_cache'
    return cloned


def _set_cached_plan(message: str, ctx: AssistantContext, decision: RouteDecision) -> None:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return
    if any(plan.purpose == 'side_effect' for plan in decision.tool_plan):
        return
    _PLAN_CACHE[_cache_key(message, ctx)] = (time.time(), _clone_decision(decision))
    if len(_PLAN_CACHE) > 128:
        for key in list(_PLAN_CACHE.keys())[:32]:
            _PLAN_CACHE.pop(key, None)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, '')]
    if isinstance(value, str) and value:
        return [value]
    return []


def _normalize_generation_plan(raw: Any, intent: str) -> Optional[GenerationPlan]:
    if not isinstance(raw, dict):
        return None
    template_id = str(raw.get('template_id') or raw.get('templateId') or intent or 'generic_generation')
    output_format = str(raw.get('output_format') or raw.get('outputFormat') or 'markdown')
    if output_format not in ('text', 'markdown', 'json', 'mermaid', 'echarts'):
        output_format = 'markdown'
    model_profile = str(raw.get('model_profile') or raw.get('modelProfile') or 'standard')
    if model_profile not in ('small', 'standard', 'strong'):
        model_profile = 'standard'
    try:
        max_tokens = int(raw.get('max_tokens') or raw.get('maxTokens') or 1600)
    except (TypeError, ValueError):
        max_tokens = 1600
    try:
        temperature = float(raw.get('temperature') if raw.get('temperature') is not None else 0.4)
    except (TypeError, ValueError):
        temperature = 0.4
    constraints = raw.get('constraints') if isinstance(raw.get('constraints'), dict) else {}
    constraints = {**constraints, 'source': 'llm_skill_planner'}
    return GenerationPlan(
        template_id=template_id,
        prompt_template=str(raw.get('prompt_template') or raw.get('promptTemplate') or ''),
        output_format=output_format,
        model_profile=model_profile,
        max_tokens=max(300, min(max_tokens, 4000)),
        temperature=max(0.0, min(temperature, 1.0)),
        constraints=constraints,
    )


def _normalize_tool_plan(raw_plan: Any, ctx: AssistantContext) -> List[ToolCallPlan]:
    if isinstance(raw_plan, dict):
        raw_plan = raw_plan.get('steps') or raw_plan.get('tools') or raw_plan.get('tool_calls') or raw_plan.get('toolCalls')
    if not isinstance(raw_plan, list):
        return []
    plans: List[ToolCallPlan] = []
    for index, raw in enumerate(raw_plan[:MAX_TOOL_STEPS], start=1):
        if not isinstance(raw, dict):
            continue
        tool = str(raw.get('tool') or raw.get('tool_name') or raw.get('toolName') or raw.get('skill') or raw.get('skill_id') or '').strip()
        spec = skill_registry.get(tool)
        if spec is None:
            continue
        purpose = str(raw.get('purpose') or ('side_effect' if spec.side_effect else 'query'))
        if purpose not in ('query', 'load_context', 'side_effect', 'render'):
            purpose = 'side_effect' if spec.side_effect else 'query'
        if spec.side_effect:
            purpose = 'side_effect'
        params = raw.get('input') if isinstance(raw.get('input'), dict) else {}
        plans.append(ToolCallPlan(
            step_id=str(raw.get('step_id') or raw.get('stepId') or f'llm_step_{index}'),
            tool=tool,
            purpose=purpose,
            input=params,
            required=bool(raw.get('required', True)),
            risk_level=str(raw.get('risk_level') or raw.get('riskLevel') or spec.risk_level or 'low'),
            cache_policy=str(raw.get('cache_policy') or raw.get('cachePolicy') or 'session'),
        ))
    return plans


def _has_forbidden_write(message: str, tool_plan: List[ToolCallPlan]) -> Optional[str]:
    reason = detect_write_intent(message)
    if reason and not any(plan.purpose == 'side_effect' for plan in tool_plan):
        return reason
    return None


def _side_effect_requested(tool_plan: List[ToolCallPlan]) -> bool:
    return any((skill_registry.get(plan.tool) and skill_registry.get(plan.tool).side_effect)
               or plan.purpose == 'side_effect'
               for plan in tool_plan)


def _is_supported_side_effect(tool_plan: List[ToolCallPlan]) -> bool:
    return all(plan.tool in ('interview_create', 'followup_task_create') for plan in tool_plan)


def _normalize_decision(raw: Dict[str, Any], message: str, ctx: AssistantContext) -> Optional[RouteDecision]:
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get('route_decision'), dict):
        raw = raw['route_decision']
    elif isinstance(raw.get('routeDecision'), dict):
        raw = raw['routeDecision']
    elif isinstance(raw.get('decision'), dict):
        raw = raw['decision']

    raw_tool_plan = raw.get('tool_plan') or raw.get('toolPlan') or raw.get('tools') or raw.get('tool_calls') or raw.get('toolCalls')
    tool_plan = _normalize_tool_plan(raw_tool_plan, ctx)
    confidence = _as_float(raw.get('confidence'), 0.0)
    if confidence == 0.0 and tool_plan:
        confidence = 0.72
    if confidence < MIN_ACCEPT_CONFIDENCE:
        logger.info('llm_skill_plan_rejected', extra={'reason': 'low_confidence', 'confidence': confidence})
        return None
    route_track = str(raw.get('route_track') or raw.get('routeTrack') or '').strip()
    route_aliases = {
        'A': TRACK_A,
        'DATA': TRACK_A,
        'DATA_QUERY': TRACK_A,
        'ACTION': TRACK_A,
        'B': TRACK_B,
        'GENERATION': TRACK_B,
        'C': TRACK_C,
        'DIALOGUE': TRACK_C,
        'KNOWLEDGE': TRACK_C,
    }
    route_track = route_aliases.get(route_track.upper(), route_track)
    if not route_track:
        generation_raw = raw.get('generation_plan') or raw.get('generationPlan')
        if tool_plan and generation_raw:
            route_track = TRACK_COMPOSITE
        elif tool_plan:
            route_track = TRACK_A
        elif generation_raw:
            route_track = TRACK_B
        else:
            route_track = TRACK_C
    if route_track not in (TRACK_A, TRACK_B, TRACK_C, TRACK_COMPOSITE):
        logger.info('llm_skill_plan_rejected', extra={'reason': 'invalid_route_track', 'routeTrack': route_track})
        return None
    task_type = str(raw.get('task_type') or raw.get('taskType') or '').strip()
    if not task_type:
        task_type = {
            TRACK_A: 'data_query',
            TRACK_B: 'generation',
            TRACK_C: 'dialogue',
            TRACK_COMPOSITE: 'composite',
        }[route_track]
    intent = str(raw.get('intent') or task_type or 'assistant_task')
    generation_plan = _normalize_generation_plan(raw.get('generation_plan') or raw.get('generationPlan'), intent)

    if route_track == TRACK_A and task_type == 'data_query' and not tool_plan:
        logger.info('llm_skill_plan_rejected', extra={'reason': 'data_query_without_tool'})
        return None
    if route_track == TRACK_COMPOSITE and not tool_plan:
        logger.info('llm_skill_plan_rejected', extra={'reason': 'composite_without_tool'})
        return None
    if route_track in (TRACK_B, TRACK_COMPOSITE) and generation_plan is None:
        generation_plan = _normalize_generation_plan({'template_id': intent, 'model_profile': 'strong'}, intent)

    normalized_query = str(raw.get('normalized_query') or raw.get('normalizedQuery') or '').strip()
    tool_plan, corrected_reason = _correct_recruitment_plan(
        message=message,
        normalized_query=normalized_query,
        decision_track=route_track,
        task_type=task_type,
        tool_plan=tool_plan,
    )

    write_reason = _has_forbidden_write(message, tool_plan)
    if write_reason and not _side_effect_requested(tool_plan):
        return RouteDecision(
            task_type='forbidden',
            route_track=TRACK_A,
            intent='forbidden_action',
            confidence=max(confidence, 0.9),
            risk_level='high',
            requires_confirmation=True,
            safety_flags=[write_reason],
            reason='llm_skill_planner_write_guard',
        )

    requires_confirmation = bool(raw.get('requires_confirmation') or raw.get('requiresConfirmation'))
    risk_level = str(raw.get('risk_level') or raw.get('riskLevel') or 'low')
    if _side_effect_requested(tool_plan):
        if not _is_supported_side_effect(tool_plan):
            return RouteDecision(
                task_type='forbidden',
                route_track=TRACK_A,
                intent='forbidden_action',
                confidence=max(confidence, 0.9),
                risk_level='high',
                requires_confirmation=True,
                safety_flags=['该写入动作暂未开放对话内执行。'],
                reason='llm_skill_planner_unsupported_side_effect',
            )
        task_type = 'action'
        route_track = TRACK_A
        risk_level = 'high'
        requires_confirmation = True

    reason = 'llm_skill_planner:' + str(raw.get('reason') or '')
    if normalized_query:
        reason = f'{reason};normalized_query={normalized_query[:160]}'
    if corrected_reason:
        reason = f'{reason};{corrected_reason}'

    return RouteDecision(
        task_type=task_type,
        route_track=route_track,
        intent=intent,
        confidence=confidence,
        risk_level=risk_level,
        required_context=_as_str_list(raw.get('required_context') or raw.get('requiredContext')),
        tool_plan=tool_plan,
        generation_plan=generation_plan,
        clarification_question=raw.get('clarification_question') or raw.get('clarificationQuestion'),
        requires_confirmation=requires_confirmation,
        fallback_policy='legacy_router',
        reason=reason,
    )


def _correct_recruitment_plan(
    *,
    message: str,
    normalized_query: str,
    decision_track: str,
    task_type: str,
    tool_plan: List[ToolCallPlan],
) -> tuple[List[ToolCallPlan], str]:
    """Keep model understanding, but route recruitment requests to stable domain skills.

    Free-form SQL remains useful for cross-table analytics. For simple
    list/count/status/progress questions, the dedicated recruitment skill is
    more stable and already handles MySQL compatibility, widgets, WorkSets, and
    permissions.
    """

    if decision_track != TRACK_A or task_type != 'data_query' or not tool_plan:
        return tool_plan, ''
    text = f'{message or ""} {normalized_query or ""}'
    if not re.search(r'(招聘|岗位|职位|候选人|应聘|简历|投递|面试|复试|Offer|offer|录用)', text, re.I):
        return tool_plan, ''
    if re.search(r'(交叉|分组|趋势|同比|环比|转化率|漏斗|按.+统计|group|join)', text, re.I):
        return tool_plan, ''
    progress_plan = _build_recruitment_progress_plan(message or '', normalized_query or '')
    if progress_plan:
        return progress_plan, 'corrected_to=recruitment_progress'
    if tool_plan[0].tool in ('smart_data_query', 'system_search') or _needs_recruitment_search_correction(tool_plan[0], text):
        corrected = _build_direct_recruitment_plan(message=message, normalized_query=normalized_query)
        if corrected:
            return corrected, 'corrected_to=recruitment_search'
    if tool_plan[0].tool != 'smart_data_query':
        return tool_plan, ''
    return tool_plan, ''


def _needs_recruitment_search_correction(plan: ToolCallPlan, text: str) -> bool:
    if plan.tool != 'recruitment_search':
        return False
    params = plan.input or {}
    module = str(params.get('module') or '').lower()
    status = str(params.get('status') or '').lower()
    if module == 'jobs' and status and status not in {'open', 'closed'}:
        return True
    if (
        re.search(r'(多少|几个|几位|几名|几份|几条|几场|数量|总数|统计)', text)
        and not (params.get('count_only') or params.get('countOnly'))
    ):
        return True
    return False


def _build_direct_recruitment_plan(*, message: str, normalized_query: str) -> List[ToolCallPlan]:
    try:
        from .legacy_planner import _direct_recruitment_query_plan
        from ..schemas import RouteDecision

        base = RouteDecision(
            task_type='data_query',
            route_track=TRACK_A,
            intent='llm_normalized_recruitment_query',
            confidence=0.88,
        )
        corrected = _direct_recruitment_query_plan(normalized_query or message, base)
        if corrected and corrected.tool_plan:
            return corrected.tool_plan
    except Exception:
        logger.debug('llm_recruitment_plan_correction_failed', exc_info=True)
    return []


def _build_recruitment_progress_plan(message: str, normalized_query: str) -> List[ToolCallPlan]:
    user_text = message or ''
    combined_text = f'{message or ""} {normalized_query or ""}'
    if not re.search(r'招聘.{0,16}(怎么样|怎样|如何|进展|情况|推进|到哪|效果)', combined_text):
        return []
    if re.search(r'(候选人|简历|这个人|这些人|这几个人|匹配度|适配度|胜任|合适|表现|评价|评估|分析|对比)', user_text):
        return []
    try:
        from .legacy_planner import _extract_recruitment_keyword

        keyword = _extract_recruitment_keyword(combined_text, 'candidates') or _extract_recruitment_keyword(combined_text, 'jobs')
    except Exception:
        logger.debug('llm_recruitment_progress_keyword_failed', exc_info=True)
        keyword = None
    base = {'keyword': keyword} if keyword else {}
    return [
        ToolCallPlan(
            step_id='recruitment_progress_jobs',
            tool='recruitment_search',
            purpose='query',
            input={**base, 'module': 'jobs', 'status': 'open', 'limit': 10},
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='recruitment_progress_candidates',
            tool='recruitment_search',
            purpose='query',
            input={**base, 'module': 'candidates', 'count_only': True, 'limit': 20},
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='recruitment_progress_resumes',
            tool='recruitment_search',
            purpose='query',
            input={**base, 'module': 'resumes', 'count_only': True, 'limit': 20},
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='recruitment_progress_interviews',
            tool='recruitment_search',
            purpose='query',
            input={**base, 'module': 'interviews', 'count_only': True, 'limit': 20},
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
    ]


def plan_with_llm(message: str, ctx: AssistantContext) -> Optional[RouteDecision]:
    """Return an LLM-built RouteDecision, or None to use deterministic fallback."""
    cached = _get_cached_plan(message, ctx)
    if cached is not None:
        return cached
    try:
        from flask import has_app_context

        if not has_app_context() and os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') != '1':
            return None
    except Exception:
        if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') != '1':
            return None
    if not feature_enabled('skillPlanning') or not llm_client.is_available():
        return None
    try:
        raw = llm_client.json_chat_profile(
            'small',
            _messages(message, ctx),
            temperature=0.05,
            max_tokens=1100,
            timeout=6,
            use_case='skill_planning',
            retry_once=False,
            ctx=ctx,
        )
        decision = _normalize_decision(raw or {}, message, ctx)
        if decision:
            logger.info(
                'llm_skill_plan_accepted',
                extra={
                    'routeTrack': decision.route_track,
                    'intent': decision.intent,
                    'tools': [p.tool for p in decision.tool_plan],
                    'confidence': decision.confidence,
                },
            )
            _set_cached_plan(message, ctx, decision)
            return decision
        if raw:
            logger.info('llm_skill_plan_not_accepted', extra={'rawKeys': list(raw.keys())[:12]})
    except Exception:  # noqa: BLE001
        logger.exception('llm_skill_planner_failed')
    return None


__all__ = ['plan_with_llm']
