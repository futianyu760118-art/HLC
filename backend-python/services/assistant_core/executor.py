"""Workflow Executor。

按 task_template.workflow 顺序执行，每步：
1. 调 Permission Gate
2. 解析 input_map
3. 调 skill handler 或 LLM summarizer
4. 写入 trace
5. 失败按 on_error 决策
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from . import fallback, llm_client, skill_registry, task_registry, widgets as W
from .constants import (
    PAYROLL_AUTHORIZED_ROLES, PRIVILEGED_ROLES, RISK_HIGH, ROLE_ADMIN, ROLE_HR_ADMIN,
)
from .guardrails import (
    check_skill_permission, check_task_permission,
)
from .schemas import (
    AssistantContext, ExecutionResult, RouterResult, TaskTemplate, WorkflowStep,
)
from .trace import Tracer

logger = logging.getLogger('hengpintong.assistant.executor')

MAX_STEPS = 8
MAX_SKILL_CALLS = 5
MAX_LLM_CALLS = 3


def _resolve_input(input_map: Dict[str, Any], state: Dict[str, Any],
                   entities: Dict[str, Any]) -> Dict[str, Any]:
    """解析 input_map：支持 entities.x / state.x / "static:..."。"""
    out: Dict[str, Any] = {}
    for k, v in (input_map or {}).items():
        if isinstance(v, str):
            if v.startswith('entities.'):
                out[k] = entities.get(v.split('.', 1)[1])
            elif v.startswith('state.'):
                out[k] = state.get(v.split('.', 1)[1])
            elif v.startswith('static:'):
                out[k] = _coerce_static(v.split(':', 1)[1])
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _coerce_static(text: str):
    """static:xxx 中的字符串转适当类型。"""
    s = text.strip()
    if s.lower() == 'true':
        return True
    if s.lower() == 'false':
        return False
    if s.lower() in ('null', 'none'):
        return None
    try:
        return int(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return s


def _permission_denied_message(router_result: RouterResult) -> str:
    """Return one stable denial sentence for all role-gated task templates."""
    domain_labels = {
        'payroll': '薪酬数据',
        'salary': '薪酬数据',
        'approval': '审批数据',
        'employee': '员工敏感数据',
        'attendance': '考勤敏感数据',
    }
    task_id = router_result.task_template_id or ''
    reason = router_result.reason or ''
    original = ''
    match = re.search(r'role_not_allowed:[^:]+:([A-Za-z0-9_-]+)', reason)
    if match:
        original = match.group(1)
    domain_key = (original or task_id).split('_', 1)[0]
    label = domain_labels.get(domain_key, '该数据')
    return f'权限不足：当前角色无权查看{label}明细，无法继续查询。'


def _summarize_llm(state: Dict[str, Any], task: TaskTemplate, message: str,
                   ctx: AssistantContext, purpose: str = 'summarizer') -> str:
    """调 LLM 生成中文总结。失败返回空串，由调用方降级。"""
    if not llm_client.is_available():
        return ''

    facts_text = []
    for key, val in state.items():
        if not isinstance(val, dict):
            continue
        hint = val.get('summary_hint')
        if hint:
            facts_text.append(f'[{key}] {hint}')
        # metrics
        m = val.get('metrics')
        if m:
            facts_text.append(f'[{key} metrics] {m}')
    facts_str = '\n'.join(facts_text) if facts_text else '（无额外事实）'

    if purpose == 'comparison':
        sys_prompt = '你正在比较多个候选人/对象，用纯中文输出 100 字以内的对比结论。不使用任何 Markdown 符号。'
    elif purpose == 'polish':
        sys_prompt = '你是 HR 文案润色助手。把已经生成的草稿改写得更自然，纯中文，不超过 250 字，不带 Markdown。'
    else:
        sys_prompt = (
            f'你是 HRM AI 助手的中文总结生成器。当前任务：{task.name}。\n'
            f'根据下面的事实生成中文总结，不超过 150 字。\n'
            f'要求：纯中文，不使用 **加粗** 或 *斜体* 或 # 标题，'
            f'不要重复用户问题，不要列出每条数据（前端会单独展示）。'
        )

    history = ctx.history[-4:] if ctx.history else []
    msgs = [{'role': 'system', 'content': sys_prompt}]
    msgs.extend(history)
    msgs.append({
        'role': 'user',
        'content': f'用户问题：{message}\n\n事实：\n{facts_str}\n\n请输出中文总结。',
    })
    msg = llm_client.chat_profile(
        'small', msgs, temperature=0.3, max_tokens=300,
        timeout=llm_client.FAST_TIMEOUT, use_case='data_summary', ctx=ctx,
    )
    if not msg:
        return ''
    return llm_client.clean_text(msg.get('content') or '')


def _has_good_summary(state: Dict[str, Any]) -> bool:
    """判断 skill 产出的 state 中是否已有足够的 summary_hint，可以跳过 LLM 总结。"""
    hints = []
    for val in state.values():
        if isinstance(val, dict):
            hint = val.get('summary_hint')
            if hint and len(str(hint)) >= 10:
                hints.append(hint)
    return len(hints) >= 1


def _collect_summary_hints(state: Dict[str, Any]) -> str:
    """拼接所有 skill 输出的 summary_hint 作为最终 summary。"""
    parts = []
    for val in state.values():
        if isinstance(val, dict):
            hint = val.get('summary_hint')
            if hint:
                parts.append(str(hint).strip())
    return '\n'.join(parts) if parts else ''


def _short_circuit_clarification(message: str, router_result: RouterResult,
                                 ctx: AssistantContext) -> ExecutionResult:
    """直接产出 ClarificationWidget，跳过 workflow 与 LLM 总结。

    与 Requirement 3.2/3.3 对齐：当 ``router_result.requires_confirmation``
    且存在 ``clarification_options`` 时，executor 不再执行 workflow，仅渲染
    一个澄清组件。EntityMemory 的写入不在这里发生 —— 实体已经在前一次
    ``routing.route`` 调用时被 pipeline 写入，本函数保持只读，确保信息
    单调性（澄清前已确认实体集合 ⊆ 澄清后）。
    """

    tracer = Tracer()
    tracer.mark_skipped(
        'clarification_short_circuit', 'clarification',
        reason='router_requires_confirmation_with_options',
    )

    question = (router_result.clarification_question or '').strip()
    if not question:
        question = '请进一步确认'

    widget = W.clarification(
        question=question,
        options=list(router_result.clarification_options or []),
        origin_message=message or '',
    )

    return ExecutionResult(
        summary=question,
        entities=[],
        widgets=[widget],
        session_id=ctx.session_id,
        trace=tracer.steps,
        router=router_result,
        requires_confirmation=True,
        fallback_used=False,
    )


def _execute_direct_skills(message: str, router_result: RouterResult,
                           ctx: AssistantContext) -> ExecutionResult:
    """Function Calling 直通路径：按 LLM 自主选择的 skill 列表顺序执行。

    与 workflow 路径的区别：

    * 没有 task template，不加载 YAML 定义
    * skill 列表和参数完全由 LLM 决定（``candidate_skills`` + ``entities``）
    * 每个 skill 独立做权限检查
    * 最后用 LLM 汇总所有 skill 输出为自然语言总结
    """
    tracer = Tracer()
    state: Dict[str, Any] = {}
    all_entities: List[Dict[str, Any]] = []
    all_widgets: List[Dict[str, Any]] = []
    seen_entities: set = set()
    skill_names = router_result.candidate_skills or []
    params = dict(router_result.entities or {})

    for skill_name in skill_names:
        spec = skill_registry.get(skill_name)
        if not spec:
            tracer.mark_skipped(skill_name, 'skill', reason='skill_not_found')
            continue

        # skill 级权限检查
        deny = check_skill_permission(ctx.role, spec, ctx)
        if deny:
            with tracer.step(skill_name, 'skill', skill_name, spec.risk_level) as rec:
                rec.status = 'error'
                rec.error = 'permission_denied'
            continue

        # 执行 skill
        with tracer.step(skill_name, 'skill', skill_name, spec.risk_level) as rec:
            try:
                t_skill = time.perf_counter()
                out = spec.handler(params, ctx) or {}
                rec.duration_ms = (time.perf_counter() - t_skill) * 1000
                state[skill_name] = out
                rec.rows_count = int(out.get('rows_count') or 0)

                if out.get('permission_denied'):
                    rec.status = 'error'
                    rec.error = 'permission_denied'
                    continue

                # 收集 entities（去重）
                for ent in out.get('entities') or []:
                    key = (ent.get('type'), ent.get('id'))
                    if key not in seen_entities:
                        seen_entities.add(key)
                        all_entities.append(ent)

                # 收集 widgets
                for w in out.get('widgets') or []:
                    all_widgets.append(w)

            except Exception as e:
                rec.status = 'error'
                rec.error = type(e).__name__
                logger.exception('fc_skill_handler_failed',
                                 extra={'skill': skill_name})

    # LLM 汇总所有 skill 输出
    summary = _summarize_fc_results(message, state, all_entities, ctx)

    # 全空时友好兜底
    if not all_entities and not all_widgets:
        all_widgets = [W.empty_state(
            f'未在系统中找到与"{message[:30]}"相关的数据。换个关键词试试。'
        )]

    # 实体卡片
    if all_entities and not any(w.get('type') == 'entity_cards' for w in all_widgets):
        all_widgets.append(W.entity_cards(all_entities, title='相关结果'))

    return ExecutionResult(
        summary=summary,
        entities=all_entities,
        widgets=all_widgets,
        session_id=ctx.session_id,
        trace=tracer.steps,
        router=router_result,
        requires_confirmation=False,
        fallback_used=False,
    )


def _summarize_fc_results(message: str, state: Dict[str, Any],
                          entities: List[Dict[str, Any]],
                          ctx: AssistantContext) -> str:
    """用 LLM 汇总 Function Calling 路径下多个 skill 的输出。

    优先复用 skill 自带的 ``summary_hint``；如果没有或不够，再调 LLM。
    """
    # 优先收集 summary_hint
    hints = []
    for key, val in state.items():
        if isinstance(val, dict):
            hint = val.get('summary_hint')
            if hint and len(str(hint)) >= 10:
                hints.append(str(hint).strip())
    if hints:
        return '\n'.join(hints)

    # 没有 summary_hint，调 LLM 生成
    if not llm_client.is_available():
        if entities:
            return f'找到 {len(entities)} 条相关记录。'
        return ''

    facts_text = []
    for key, val in state.items():
        if isinstance(val, dict):
            data = val.get('data') or val.get('metrics') or val
            facts_text.append(f'[{key}] {str(data)[:300]}')
    facts_str = '\n'.join(facts_text) if facts_text else '（无额外事实）'

    sys_prompt = (
        '你是 HRM AI 助手的中文总结生成器。根据下面的事实生成中文总结，'
        '不超过 150 字。要求：纯中文，不使用 **加粗** 或 *斜体* 或 # 标题，'
        '不要重复用户问题，不要列出每条数据（前端会单独展示）。'
    )
    history = ctx.history[-4:] if ctx.history else []
    msgs = [{'role': 'system', 'content': sys_prompt}]
    msgs.extend(history)
    msgs.append({
        'role': 'user',
        'content': f'用户问题：{message}\n\n事实：\n{facts_str}\n\n请输出中文总结。',
    })
    msg = llm_client.chat_profile(
        'small', msgs, temperature=0.3, max_tokens=300,
        timeout=llm_client.FAST_TIMEOUT, use_case='data_summary', ctx=ctx,
    )
    if msg:
        return llm_client.clean_text(msg.get('content') or '')
    if entities:
        return f'找到 {len(entities)} 条相关记录。'
    return ''


def execute(message: str, router_result: RouterResult,
            ctx: AssistantContext) -> ExecutionResult:
    """主执行入口。"""
    tracer = Tracer()
    state: Dict[str, Any] = {}
    all_entities: List[Dict[str, Any]] = []
    all_widgets: List[Dict[str, Any]] = []
    seen_entities = set()
    fallback_used = False
    summary = ''

    # ---- 高风险拦截：直接返回 ----
    if router_result.task_template_id == 'forbidden_action_response':
        msg = router_result.forbidden_reason or '该操作不会自动执行，请到对应业务页面确认。'
        return ExecutionResult(
            summary=msg,
            entities=[],
            widgets=[W.warning(msg, level='warning')],
            session_id=ctx.session_id,
            trace=tracer.steps,
            router=router_result,
            requires_confirmation=True,
        )

    if router_result.task_template_id == 'permission_denied_response':
        msg = _permission_denied_message(router_result)
        return ExecutionResult(
            summary=msg,
            entities=[],
            widgets=[W.warning(msg, level='danger')],
            session_id=ctx.session_id,
            trace=tracer.steps,
            router=router_result,
            requires_confirmation=False,
            error_code='permission_denied',
            answer={'content': msg, 'format': 'text'},
        )

    # ---- 澄清轮短路：requires_confirmation + 非空 clarification_options ----
    # 必须放在 forbidden_action_response 之后、task 加载/权限校验之前，避免
    # 模糊查询触发不必要的 workflow / LLM 调用。
    if router_result.requires_confirmation and router_result.clarification_options:
        return _short_circuit_clarification(message, router_result, ctx)

    # ---- Function Calling 直通路径：LLM 自主选择的 skill 列表 ----
    if router_result.task_template_id == '_direct_skills_':
        return _execute_direct_skills(message, router_result, ctx)

    # ---- 加载 task template ----
    task_id = router_result.task_template_id or 'global_search_answer'
    task = task_registry.get(task_id)
    if not task:
        task = task_registry.get('global_search_answer')
    if not task:
        return ExecutionResult(
            summary='任务模板未配置，无法处理。',
            session_id=ctx.session_id,
            error_code='no_task',
            router=router_result,
        )

    # ---- 任务级权限检查 ----
    deny = check_task_permission(ctx.role, task)
    if deny:
        return ExecutionResult(
            summary=f'权限不足：{deny}。',
            widgets=[W.warning(deny, level='warning')],
            session_id=ctx.session_id,
            trace=tracer.steps,
            router=router_result,
            error_code='task_denied',
        )

    # ---- candidate_skills 校验 ----
    valid_skills = set()
    for s in (router_result.candidate_skills or task.candidate_skills):
        if skill_registry.exists(s):
            valid_skills.add(s)
    # 收集 task 中实际用到的 skill（白名单）
    task_used_skills = {step.skill for step in task.workflow if step.skill}

    # ---- 实体合并：router 提供的 + task 默认 ----
    entities = dict(task.optional_entities or {})
    for k, v in (router_result.entities or {}).items():
        if v is not None and v != '':
            entities[k] = v

    # ---- 必需实体检查 ----
    missing = [e for e in (task.required_entities or []) if not entities.get(e)]
    if missing and not router_result.clarification_question:
        return ExecutionResult(
            summary=f'缺少必要信息：{"、".join(missing)}。请补充后再试。',
            widgets=[W.warning(f'请提供：{"、".join(missing)}', level='info')],
            session_id=ctx.session_id,
            trace=tracer.steps,
            router=router_result,
        )

    # ---- 顺序执行 workflow ----
    skill_calls = 0
    llm_calls = 0
    step_idx = 0
    total_skill_ms = 0.0
    total_llm_ms = 0.0

    for step in task.workflow:
        step_idx += 1
        if step_idx > MAX_STEPS:
            tracer.mark_skipped(step.id, step.type, reason='exceeded MAX_STEPS')
            break

        if step.type == 'skill':
            if skill_calls >= MAX_SKILL_CALLS:
                tracer.mark_skipped(step.id, step.type, step.skill, 'exceeded MAX_SKILL_CALLS')
                continue
            if step.skill not in task_used_skills:
                # 模板里写的 skill 不在 task 自身白名单中，跳过
                tracer.mark_skipped(step.id, step.type, step.skill, 'skill not in task whitelist')
                continue
            skill = skill_registry.get(step.skill)
            if not skill:
                tracer.mark_skipped(step.id, step.type, step.skill, 'skill_not_found')
                if step.required and step.on_error == 'stop':
                    break
                continue
            # skill 级权限检查
            deny = check_skill_permission(ctx.role, skill, ctx)
            if deny:
                with tracer.step(step.id, step.type, skill.id, skill.risk_level) as rec:
                    rec.status = 'error'
                    rec.error = 'permission_denied'
                if step.required:
                    if step.on_error == 'stop':
                        break
                    if step.on_error == 'fallback':
                        fallback_used = True
                        break
                continue

            # 执行 skill
            with tracer.step(step.id, step.type, skill.id, skill.risk_level) as rec:
                kwargs = _resolve_input(step.input_map, state, entities)
                try:
                    t_skill = time.perf_counter()
                    out = skill.handler(kwargs, ctx) or {}
                    total_skill_ms += (time.perf_counter() - t_skill) * 1000
                    state[step.output_key] = out
                    rec.rows_count = int(out.get('rows_count') or 0)
                    if out.get('permission_denied'):
                        rec.status = 'error'
                        rec.error = 'permission_denied'
                    # 收集 entities 与 widgets
                    for ent in out.get('entities') or []:
                        key = (ent.get('type'), ent.get('id'))
                        if key in seen_entities:
                            continue
                        seen_entities.add(key)
                        all_entities.append(ent)
                    for w in out.get('widgets') or []:
                        all_widgets.append(w)
                except Exception as e:
                    rec.status = 'error'
                    rec.error = type(e).__name__
                    logger.exception('skill_handler_failed', extra={'skill': skill.id})
                    if step.required:
                        if step.on_error == 'stop':
                            break
                        if step.on_error == 'fallback':
                            fallback_used = True
                            break
            skill_calls += 1

        elif step.type == 'llm':
            if llm_calls >= MAX_LLM_CALLS:
                tracer.mark_skipped(step.id, step.type, reason='exceeded MAX_LLM_CALLS')
                continue
            # 性能优化：如果 skill 步骤已经产出了足够的 summary_hint，跳过 LLM 总结
            purpose = step.llm_purpose or 'summarizer'
            if purpose == 'summarizer' and _has_good_summary(state):
                existing_summary = _collect_summary_hints(state)
                state[step.output_key] = {'summary_hint': existing_summary}
                summary = existing_summary
                tracer.mark_skipped(step.id, step.type, reason='skip_llm: summary_hint sufficient')
                continue
            with tracer.step(step.id, step.type) as rec:
                t_llm = time.perf_counter()
                summary_text = _summarize_llm(state, task, message, ctx, purpose=purpose)
                total_llm_ms += (time.perf_counter() - t_llm) * 1000
                state[step.output_key] = {'summary_hint': summary_text}
                if summary_text:
                    summary = summary_text
                else:
                    rec.status = 'error'
                    rec.error = 'llm_unavailable'
            llm_calls += 1

        elif step.type == 'permission_check':
            tracer.mark_skipped(step.id, step.type, reason='inline check passed')
            continue

        else:
            tracer.mark_skipped(step.id, step.type, reason=f'unsupported_type:{step.type}')

    # ---- 兜底：执行后无任何输出 ----
    if not all_entities and not all_widgets:
        # 触发 fallback_task（一次）
        if task.fallback_task and task.fallback_task != task_id:
            fb_task = task_registry.get(task.fallback_task)
            if fb_task:
                fallback_used = True
                fb_router = RouterResult(
                    intent=fb_task.id,
                    task_template_id=fb_task.id,
                    confidence=0.5,
                    entities=entities,
                    risk_level=fb_task.risk_level,
                    candidate_skills=fb_task.candidate_skills,
                    reason='fallback from ' + task_id,
                )
                fb_result = execute(message, fb_router, ctx)
                # 合并 fallback 输出
                if fb_result.entities:
                    all_entities.extend(fb_result.entities)
                if fb_result.widgets:
                    all_widgets.extend(fb_result.widgets)
                # 此处进入分支的前提是原 workflow 0 数据，原 summary 必然是"未找到"语义；
                # 既然 fallback 找到了实体，必须用 fallback 的 summary 替换，避免文本与卡片矛盾。
                if fb_result.summary and (not summary or fb_result.entities):
                    summary = fb_result.summary
                tracer.steps.extend(fb_result.trace)

    # ---- 仍然空 → global_search 关键词降噪兜底 ----
    if not all_entities and not all_widgets:
        keyword_search = fallback.empty_result_fallback(ctx, message, router_result)
        if keyword_search:
            fallback_used = True
            for ent in keyword_search.get('entities') or []:
                key = (ent.get('type'), ent.get('id'))
                if key not in seen_entities:
                    seen_entities.add(key)
                    all_entities.append(ent)
            for w in keyword_search.get('widgets') or []:
                all_widgets.append(w)
            if keyword_search.get('summary_hint') and not summary:
                summary = keyword_search['summary_hint']

    # ---- 最终 summary ----
    if not summary:
        summary = fallback.deterministic_summary(state, router_result)

    # 全空时友好兜底
    if not all_entities and not all_widgets:
        all_widgets = [W.empty_state(f'未在系统中找到与"{message[:30]}"相关的数据。换个关键词试试。')]

    # 实体卡片 widget（如果模板期望）
    if 'entity_cards' in (task.output_widgets or []) and all_entities:
        # 已经有 widgets 时不重复添加
        if not any(w.get('type') == 'entity_cards' for w in all_widgets):
            all_widgets.append(W.entity_cards(all_entities, title='相关结果'))

    result = ExecutionResult(
        summary=summary,
        entities=all_entities,
        widgets=all_widgets,
        session_id=ctx.session_id,
        trace=tracer.steps,
        router=router_result,
        requires_confirmation=router_result.requires_confirmation or task.requires_confirmation,
        fallback_used=fallback_used,
    )
    result._perf = {
        'skill_ms': round(total_skill_ms, 1),
        'llm_ms': round(total_llm_ms, 1),
    }
    return result
