"""LLM-backed prompt enhancement for the HRM assistant composer."""

from __future__ import annotations

from typing import Any, Dict, List

from . import llm_client
from .agent_kernel.skill_provider import records_from_recall
from .model_settings import feature_enabled, model_for_profile
from .schemas import AssistantContext
from .skill_first.semantic_index import normalize_query
from .skill_first.skill_retriever import retrieve_skills


def _skill_first_brief(raw: str, ctx: AssistantContext) -> Dict[str, Any]:
    normalized_query = normalize_query(raw or '分析最近收到的简历')
    candidates = retrieve_skills(raw or normalized_query, normalized_query=normalized_query, top_k=8)
    top_skills: List[Dict[str, Any]] = [
        record.to_prompt_optimizer_schema()
        for record in records_from_recall(candidates, limit=8, model_schema_mode='prompt_optimizer')
    ]
    selected = top_skills[0] if top_skills else {}
    return {
        'routeTrack': 'AGENT_KERNEL_SKILL_FIRST',
        'intent': selected.get('id') or 'skill_first_unhandled',
        'normalizedQuery': normalized_query,
        'topSkills': top_skills,
        'currentPageContext': getattr(ctx, 'client_context', {}) or {},
    }


def _fallback_prompt(raw: str, brief: Dict[str, Any]) -> str:
    text = (raw or '').strip()
    intent = str(brief.get('intent') or '')
    top_skills = brief.get('topSkills') if isinstance(brief.get('topSkills'), list) else []
    selected = top_skills[0] if top_skills and isinstance(top_skills[0], dict) else {}
    if not text:
        return (
            '查询最近 7 天投递目标岗位的候选人，按评分和匹配度列出名单；'
            '随后基于每位候选人的简历、项目经历和面试记录分别分析优势、风险与建议动作。'
        )
    if bool(selected.get('side_effect')):
        return f'{text}。请先检索系统证据并生成待确认动作，未确认前不要创建、发送、审批或修改任何业务记录。'
    if intent in ('candidate.evaluation', 'candidate.resume_analysis', 'candidate.job_fit'):
        return f'{text}。请先加载该对象在系统中的简历、岗位、面试和 Offer 证据，再给出结论、依据、风险与下一步建议。'
    if intent in ('candidate.compare', 'candidate.match_matrix', 'workset.analysis'):
        return f'{text}。请基于当前对话中的对象集合逐一加载系统证据，输出差异化结论，不要使用通用模板或编造信息。'
    if selected:
        domain = selected.get('domain') or 'HRM'
        return f'{text}。请按 {domain} 模块从系统真实记录中检索证据，列出关键结果、时间范围、来源和可继续追问的对象。'
    return f'{text}。请明确目标、对象、时间范围、需要引用的系统证据以及期望输出格式。'


def optimize_prompt(raw: str, ctx: AssistantContext) -> Dict[str, Any]:
    """Rewrite a user's intent into an executable, grounded assistant prompt."""
    brief = _skill_first_brief(raw, ctx)
    optimized = None
    used_model = None
    if feature_enabled('promptOptimization') and llm_client.is_available():
        system = (
            '你是恒聘通聘小犀的提示词规划器。你的工作是把用户的口语需求改写成更容易执行的请求，'
            '而不是回答请求。系统采用 Skill-first Agent Kernel：先理解用户原话，再召回候选 Skill，'
            '由受限 planner 在候选 Skill 内选择，随后通过 Schema、WorkSet、权限、确认和 ToolExecutor 执行。'
            '改写时保留用户原意，补清对象指代、数据来源、时间范围、分析维度和输出形式；'
            '涉及人员分析时明确要求先检索系统中的简历、岗位、面试、Offer或员工相关记录；'
            '涉及创建面试、审批、通知、调岗、调薪或任务时明确先形成待确认动作，不直接执行。'
            '只能围绕给定候选 Skill 能力改写，不要发明系统不存在的工具。只输出一条可直接发送的新提示词，不要解释。'
        )
        user = (
            f'原始需求：{(raw or "").strip() or "我不知道怎么提问，请给一个能体验系统智能检索与分析能力的请求"}\n'
            f'normalized_query：{brief["normalizedQuery"]}\n'
            f'Agent Kernel 候选 Skill：{brief["topSkills"]}\n'
            '请将其改写为聘小犀能稳定执行的自然语言请求。'
        )
        msg = llm_client.chat_profile(
            'strong',
            [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            temperature=0.25,
            max_tokens=500,
            timeout=25,
            use_case='prompt_optimization',
            ctx=ctx,
        )
        if msg:
            optimized = llm_client.clean_text(msg.get('content') or '').strip(' "\n')
            used_model = model_for_profile('strong', 'prompt_optimization')
    return {
        'original': raw or '',
        'optimized': optimized or _fallback_prompt(raw, brief),
        'routeTrack': brief['routeTrack'],
        'intent': brief['intent'],
        'selectedSkill': brief['intent'],
        'topSkills': brief['topSkills'],
        'normalizedQuery': brief['normalizedQuery'],
        'modelProfile': 'strong' if used_model else 'fallback',
        'model': used_model,
    }
