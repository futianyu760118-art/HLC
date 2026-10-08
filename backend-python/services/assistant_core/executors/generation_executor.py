"""Generation executor for creative HR tasks."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .. import llm_client, model_settings
from ..guardrails import redact_generation_output
from ..schemas import AssistantContext, ExecutionResult, GenerationPlan, RouteDecision
from .output_composer import OutputComposer


GENERATION_SYSTEM_PROMPT = (
    '你是恒聘通 HRM 系统中的企业级 HR 内容生成助手。始终使用中文。'
    '如果 context 为空，不要编造员工、候选人、薪酬等私有数据。'
    '如果使用了 context，只基于已提供的 context 生成。'
    '不要输出未授权敏感信息。输出清爽的中文文本；可以用编号和短标题，'
    '不要使用 # 标题、--- 分割线或过度 Markdown。'
    '当 context 标明来自系统工具时，它就是系统工具已加载的真实证据；'
    '必须基于该证据回答，不得声称无法访问系统内已提供的数据，也不得否认已提供的查询结果。'
)

REVIEW_SYSTEM_PROMPT = (
    '你是恒聘通 HRM 系统中的第二模型复核协作者。你的任务是审阅第一模型草稿，'
    '基于系统工具已加载的真实证据补强结论、证据链、风险点和下一步建议。'
    '不得声称无法访问系统内已提供的数据，不得编造 context 之外的事实，'
    '不得输出未授权敏感信息。只输出复核后的最终中文答案，不要解释复核过程。'
)

COMPLEX_REVIEW_TEMPLATES = {
    'analysis_report',
    'candidate_assessment',
    'candidate_compare',
    'interview_questions',
    'person_assessment',
    'person_evidence_answer',
}


def _parse_count(message: str, default: int = 6) -> int:
    m = re.search(r'(\d+)\s*道', message or '')
    if not m:
        return default
    try:
        return max(1, min(int(m.group(1)), 20))
    except (TypeError, ValueError):
        return default


def _topic_from_message(message: str) -> str:
    text = message or ''
    if 'Java' in text or 'java' in text:
        return 'Java 后端'
    if '前端' in text:
        return '前端'
    if '产品' in text:
        return '产品经理'
    return '目标岗位'


def _context_text(context: Optional[Dict[str, Any]]) -> str:
    if not context:
        return '（无私有上下文）'
    try:
        return json.dumps(context, ensure_ascii=False, default=str)[:16000]
    except Exception:
        return str(context)[:16000]


def _direct_answer_from_context(context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(context, dict):
        return None
    direct_answer = context.get('direct_answer') or (context.get('facts') or {}).get('direct_answer')
    if direct_answer:
        return str(direct_answer)
    for detail in context.get('details') or []:
        if isinstance(detail, dict) and detail.get('direct_answer'):
            return str(detail.get('direct_answer'))
    for output in context.get('tool_outputs') or []:
        data = output.get('data') if isinstance(output, dict) else {}
        facts = data.get('facts') if isinstance(data, dict) else {}
        if isinstance(facts, dict) and facts.get('direct_answer'):
            return str(facts.get('direct_answer'))
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ''):
        return []
    return [value]


def _question_text(raw: Any) -> Optional[str]:
    if isinstance(raw, dict):
        q = raw.get('question') or raw.get('title') or raw.get('content')
        purpose = raw.get('purpose')
        if q and purpose:
            return f'{q}（考察：{purpose}）'
        return str(q) if q else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _short_text(value: Any, limit: int = 80) -> str:
    text = str(value or '').replace('\n', ' ').strip()
    return text[:limit]


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r'-?\d+(?:\.\d+)?', value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _as_number(value)
        if number is not None:
            return number
    return None


def _candidate_metric(detail: Dict[str, Any], metric: str) -> Optional[float]:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    candidate = detail.get('candidate') if isinstance(detail.get('candidate'), dict) else {}
    records = candidate.get('match_records') if isinstance(candidate.get('match_records'), list) else []
    first_record = records[0] if records and isinstance(records[0], dict) else {}
    if metric == 'match':
        return _first_number(
            resume.get('match_degree'),
            resume.get('matchDegree'),
            detail.get('match_degree'),
            detail.get('matchDegree'),
            first_record.get('matchDegree'),
            first_record.get('match_degree'),
            first_record.get('match'),
        )
    return _first_number(
        resume.get('score'),
        detail.get('score'),
        first_record.get('score'),
        first_record.get('finalScore'),
        first_record.get('managerScore'),
        first_record.get('selfScore'),
    )


def _candidate_name(detail: Dict[str, Any], item: Dict[str, Any], index: int) -> str:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    return str(
        detail.get('name')
        or detail.get('candidate_name')
        or resume.get('candidate_name')
        or item.get('title')
        or f'候选人{index}'
    )


def _candidate_job(detail: Dict[str, Any], item: Dict[str, Any]) -> str:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    job = detail.get('job') if isinstance(detail.get('job'), dict) else {}
    return str(
        job.get('title')
        or resume.get('job_title')
        or detail.get('job_title')
        or item.get('subtitle')
        or '未标明岗位'
    )


def _candidate_strengths(detail: Dict[str, Any]) -> str:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    strengths = _as_list(resume.get('strengths') or detail.get('strengths'))
    skills = _as_list(resume.get('skills') or detail.get('skills'))
    summary = resume.get('summary') or detail.get('summary')
    if strengths:
        return '；'.join(_short_text(v, 36) for v in strengths[:2])
    if skills:
        return '技能：' + '、'.join(_short_text(v, 16) for v in skills[:4])
    return _short_text(summary, 50) or '暂无更多优势字段'


def _candidate_risks(detail: Dict[str, Any]) -> str:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    weaknesses = _as_list(resume.get('weaknesses') or detail.get('weaknesses'))
    focus = _as_list(resume.get('interview_focus') or resume.get('interviewFocus')
                     or detail.get('interview_focus') or detail.get('interviewFocus'))
    if weaknesses:
        cleaned = []
        for value in weaknesses[:2]:
            text = _short_text(value, 36)
            if re.search(r'(薪酬|薪资|工资|月薪|年薪|期望薪资|岗位预算)', text):
                text = re.sub(r'[：:][ \t]*[¥￥]?\d+(?:,\d{3})*(?:\.\d+)?[ \t]*(?:元|人民币|k|K|万)?', '需复核', text)
                text = re.sub(r'(期望薪资|岗位预算|薪酬|薪资|工资|月薪|年薪).*', '待遇期望需复核', text)
            cleaned.append(text)
        return '；'.join(cleaned)
    if focus:
        return '面试重点：' + '；'.join(_short_text(v, 32) for v in focus[:2])
    return '建议面试中补充验证'


def _candidate_followup_risk_answer(message: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(context, dict):
        return None
    if not re.search(r'(风险|短板|问题|下一步|推进|建议|怎么推|如何推|重点验证|关注点)', message or ''):
        return None
    details = [d for d in (context.get('details') or []) if isinstance(d, dict)]
    items = [i for i in (context.get('items') or []) if isinstance(i, dict)]
    if len(details) != 1:
        return None

    detail = details[0]
    item = items[0] if items else {}
    entity_type = str(item.get('entity_type') or detail.get('entity_type') or 'candidate')
    if entity_type not in {'candidate', 'resume'}:
        return None

    name = _candidate_name(detail, item, 1)
    job = _candidate_job(detail, item)
    candidate = detail.get('candidate') if isinstance(detail.get('candidate'), dict) else {}
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    job_facts = detail.get('job') if isinstance(detail.get('job'), dict) else {}
    interviews = [row for row in (detail.get('interviews') or []) if isinstance(row, dict)]
    latest_interview = interviews[0] if interviews else {}
    score = _candidate_metric(detail, 'score')
    match = _candidate_metric(detail, 'match')
    strengths = _as_list(resume.get('strengths') or detail.get('strengths'))
    weaknesses = _as_list(resume.get('weaknesses') or detail.get('weaknesses'))
    focus = _as_list(
        resume.get('interview_focus') or resume.get('interviewFocus')
        or detail.get('interview_focus') or detail.get('interviewFocus')
    )
    recommendation = (
        resume.get('recommendation')
        or candidate.get('ai_recommendation')
        or detail.get('recommendation')
    )
    summary = resume.get('summary') or candidate.get('ai_summary') or detail.get('summary')
    requirements = job_facts.get('requirements') or detail.get('job_requirements')

    evidence_lines = [f'- 对象：{name}｜{job}']
    if candidate.get('status'):
        evidence_lines.append(f'- 当前阶段：{candidate.get("status")}')
    metric_parts = []
    if score is not None:
        metric_parts.append(f'评分 {score:g}')
    if match is not None:
        metric_parts.append(f'匹配度 {match:g}%')
    if metric_parts:
        evidence_lines.append(f'- 量化信号：{"，".join(metric_parts)}')
    if summary:
        evidence_lines.append(f'- 证据摘要：{_short_text(summary, 120)}')
    if latest_interview:
        interview_hint = latest_interview.get('feedback') or latest_interview.get('notes') or latest_interview.get('status')
        evidence_lines.append(f'- 最近面试：{_short_text(interview_hint, 120) or "已有面试记录"}')

    risk_lines: List[str] = []
    for idx, value in enumerate(weaknesses[:4], start=1):
        risk_lines.append(f'{idx}. {_short_text(value, 90)}')
    if not risk_lines and focus:
        for idx, value in enumerate(focus[:3], start=1):
            risk_lines.append(f'{idx}. 需在下一轮验证：{_short_text(value, 80)}')
    if not risk_lines and requirements:
        risk_lines.append(f'1. 当前证据未给出明确短板，建议按岗位要求复核：{_short_text(requirements, 100)}')
    if not risk_lines:
        risk_lines.append('1. 当前证据未暴露明确风险，但仍建议在下一轮面试中复核岗位关键能力。')

    next_steps: List[str] = []
    if focus:
        next_steps.append(f'围绕{ "、".join(_short_text(v, 24) for v in focus[:3]) }做结构化追问。')
    if requirements:
        next_steps.append(f'对照岗位要求复核：{_short_text(requirements, 80)}。')
    if recommendation:
        next_steps.append(f'结合系统建议执行：{_short_text(recommendation, 80)}。')
    if latest_interview and latest_interview.get('status') in {'scheduled', 'pending'}:
        next_steps.append('已有待推进面试记录，建议在该轮面试后再决定是否进入 Offer 或保留备选。')
    if not next_steps:
        next_steps.append('补充一次针对性面试或业务案例追问，再根据结果决定是否推进。')

    strengths_text = '；'.join(_short_text(v, 40) for v in strengths[:3]) if strengths else '当前证据未提供明确优势字段'
    return '\n'.join([
        f'{name} 风险与推进建议',
        '',
        '证据基础：',
        *evidence_lines,
        '',
        f'可用优势：{strengths_text}',
        '',
        '主要风险：',
        *risk_lines,
        '',
        '下一步建议：',
        *[f'{idx}. {step}' for idx, step in enumerate(next_steps, start=1)],
        '',
        '可执行动作：',
        f'- 生成面试题：基于{name}的简历、面试记录和风险点生成结构化面试题。',
        f'- 安排面试：给{name}安排明天下午三点面试。该动作必须二次确认后才会写入。',
    ])


def _ranking_metric_from_message(message: str) -> str:
    return 'match' if re.search(r'(匹配|适配|契合)', message or '') else 'score'


def _candidate_ranking_report(message: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(context, dict):
        return None
    details = [d for d in (context.get('details') or []) if isinstance(d, dict)]
    items = [i for i in (context.get('items') or []) if isinstance(i, dict)]
    if not details and not items:
        return None

    rows: List[Dict[str, Any]] = []
    metric = _ranking_metric_from_message(message)
    for idx, detail in enumerate(details or [{} for _ in items], start=1):
        item = items[idx - 1] if idx - 1 < len(items) else {}
        score = _candidate_metric(detail, 'score')
        match = _candidate_metric(detail, 'match')
        primary = match if metric == 'match' else score
        if primary is None:
            primary = score if score is not None else match
        rows.append({
            'original_index': idx,
            'name': _candidate_name(detail, item, idx),
            'job': _candidate_job(detail, item),
            'score': score,
            'match': match,
            'primary': primary if primary is not None else -1,
            'strengths': _candidate_strengths(detail),
            'risks': _candidate_risks(detail),
        })

    if not rows:
        return None
    rows.sort(key=lambda row: (row['primary'], row['score'] or -1, row['match'] or -1), reverse=True)
    metric_label = '匹配度' if metric == 'match' else 'AI评分'
    lines = [
        '排名比对报表',
        f'排序口径：优先按{metric_label}降序；缺少该字段时参考另一个可比字段。',
        f'范围：当前上下文中的 {len(rows)} 位对象。',
        '',
        '排名明细：',
    ]
    for rank, row in enumerate(rows, start=1):
        score_text = f'{row["score"]:g}分' if row['score'] is not None else '缺失'
        match_text = f'{row["match"]:g}%' if row['match'] is not None else '缺失'
        lines.extend([
            f'{rank}. {row["name"]}｜{row["job"]}｜评分 {score_text}｜匹配度 {match_text}',
            f'   优势：{row["strengths"]}',
            f'   风险/追问：{row["risks"]}',
        ])
    top = rows[:3]
    if top:
        lines.extend([
            '',
            '优先建议：',
            '、'.join(f'{idx + 1}. {row["name"]}' for idx, row in enumerate(top)),
            '后续可以直接说“给排名前三安排明天上午8点面试”，我会基于这份排序继续操作。',
        ])
    return '\n'.join(lines)


def _personalized_interview_questions(
    detail: Dict[str, Any],
    item: Dict[str, Any],
    topic: str,
    count: int = 4,
) -> List[str]:
    questions: List[str] = []
    for raw in _as_list(detail.get('interview_questions') or detail.get('interviewQuestions')):
        q = _question_text(raw)
        if q and q not in questions:
            questions.append(q)

    focus_items = [
        _short_text(v, 50)
        for v in _as_list(detail.get('interview_focus') or detail.get('interviewFocus'))
        if _short_text(v, 50)
    ]
    skills = [
        _short_text(v, 32)
        for v in _as_list(detail.get('skills'))
        if _short_text(v, 32)
    ]
    strengths = [
        _short_text(v, 50)
        for v in _as_list(detail.get('strengths'))
        if _short_text(v, 50)
    ]
    weaknesses = [
        _short_text(v, 50)
        for v in _as_list(detail.get('weaknesses'))
        if _short_text(v, 50)
    ]
    summary = _short_text(detail.get('summary') or item.get('subtitle'), 90)

    for focus in focus_items:
        questions.append(f'请结合你在“{focus}”方面的具体项目，说明当时的目标、技术方案、你本人负责的部分和最终结果。')
    if skills:
        questions.append(f'你简历中提到的关键技能包括“{"、".join(skills[:4])}”，请选一个最能代表你能力的项目展开说明。')
    if strengths:
        questions.append(f'简历分析中的优势是“{strengths[0]}”，请用一个真实项目证明这一点，并说明可量化结果。')
    if weaknesses:
        questions.append(f'针对简历中暴露的风险点“{weaknesses[0]}”，你过去如何补齐或规避类似短板？')
    if summary:
        questions.append(f'围绕当前摘要“{summary}”，请说明你认为自己最匹配{topic}岗位的三条证据。')

    fallback_focus = focus_items[0] if focus_items else (skills[0] if skills else item.get('subtitle') or topic)
    while len(questions) < count:
        idx = len(questions) + 1
        questions.append(
            f'结合你与“{fallback_focus}”相关的经历，说明一个最复杂的问题、你的拆解过程和复盘收获（问题 {idx}）。'
        )
    return questions[:count]


def _wants_per_item_output(message: str) -> bool:
    return bool(re.search(r'(每个人|每位|每个|每一位|分别|逐个|针对.*人|他们|这些|上面这些|刚才这些)', message or ''))


def _fallback_generation(message: str, plan: GenerationPlan, context: Optional[Dict[str, Any]]) -> str:
    template_id = plan.template_id or 'generic_generation'
    topic = _topic_from_message(message)
    direct_answer = _direct_answer_from_context(context)
    if template_id == 'workset_analysis' and direct_answer:
        return str(direct_answer)
    if template_id == 'interview_questions':
        count = _parse_count(message, default=8 if '8' in message else 6)
        items = (context or {}).get('items') or []
        details = (context or {}).get('details') or []
        if items and _wants_per_item_output(message):
            sections = [f'{topic}逐人面试题']
            for idx, item in enumerate(items, start=1):
                name = item.get('title') or item.get('entity_id') or f'候选人{idx}'
                detail = details[idx - 1] if idx - 1 < len(details) and isinstance(details[idx - 1], dict) else {}
                skills = '、'.join((detail.get('skills') or [])[:5]) if detail else ''
                focus = '、'.join((detail.get('interview_focus') or [])[:3]) if detail else ''
                hint = f'重点关注：{focus or skills or item.get("subtitle") or "岗位核心能力"}'
                questions = _personalized_interview_questions(detail, item, topic, count=4)
                question_lines = '\n'.join(f'{q_idx}. {q}' for q_idx, q in enumerate(questions, start=1))
                sections.append(
                    f'\n{idx}. {name}\n'
                    f'- 背景线索：{hint}\n'
                    f'{question_lines}'
                )
            return '\n'.join(sections)
        lines = [f'{topic}面试题']
        if context:
            lines.append('\n> 以下问题仅基于当前已提供的候选人/简历上下文生成。')
        for idx in range(1, count + 1):
            lines.append(
                f'\n{idx}. **{topic}核心问题 {idx}**：请候选人结合项目经历说明相关能力。'
                f'\n   - 考察点：基础知识、工程实践、问题拆解与沟通表达。'
            )
        return '\n'.join(lines)
    if template_id == 'candidate_compare':
        report = _candidate_ranking_report(message, context)
        if report:
            return report
        return (
            '候选人对比分析\n\n'
            '请基于已提供的候选人上下文，从岗位匹配度、核心技能、项目经验、风险点和面试关注点五个维度对比。'
            if context else
            '缺少候选人上下文，无法进行真实对比。请先查询候选人，或明确要比较的对象。'
        )
    if template_id in ('person_assessment', 'candidate_assessment', 'person_evidence_answer'):
        details = (context or {}).get('details') or []
        if direct_answer:
            return str(direct_answer)
        if not details:
            return '系统内未找到可用于评价的对象证据，请先明确姓名或查询结果集。'
        sections: List[str] = ['基于系统记录的评估']
        for index, detail in enumerate(details, start=1):
            name = detail.get('name') or detail.get('candidate_name') or detail.get('title') or f'对象{index}'
            resume = detail.get('resume') or detail
            candidate = detail.get('candidate') or {}
            job = detail.get('job') or {}
            score = resume.get('score')
            strengths = _as_list(resume.get('strengths') or detail.get('strengths'))
            weaknesses = _as_list(resume.get('weaknesses') or detail.get('weaknesses'))
            sections.append(f'\n{index}. {name}')
            if job.get('title') or detail.get('job_title'):
                sections.append(f'- 关联岗位：{job.get("title") or detail.get("job_title")}')
            if score is not None:
                sections.append(f'- 简历评分：{score} 分')
            if candidate.get('status'):
                sections.append(f'- 当前进度：{candidate.get("status")}')
            if strengths:
                sections.append(f'- 主要优势：{"；".join(str(v) for v in strengths[:3])}')
            if weaknesses:
                sections.append(f'- 关注风险：{"；".join(str(v) for v in weaknesses[:3])}')
            interviews = detail.get('interviews') or []
            sections.append(f'- 已记录面试：{len(interviews)} 场')
            sections.append('- 判断建议：建议围绕已呈现的优势与风险进行针对性复核后决定下一阶段。')
        return '\n'.join(sections)
    if template_id == 'hr_email_draft':
        return (
            '面试邀约邮件草稿\n\n'
            '主题：面试邀请\n\n'
            '候选人您好：\n\n'
            '感谢您关注并应聘我司岗位。经过初步评估，我们诚邀您参加下一轮面试。\n\n'
            '- 面试时间：待确认\n'
            '- 面试形式：待确认\n'
            '- 面试地点/会议链接：待确认\n\n'
            '请您回复确认是否方便参加。如需调整时间，也欢迎提前告知。\n\n'
            '祝好！'
        )
    if template_id == 'job_posting':
        return (
            '招聘文案草稿\n\n'
            '岗位亮点\n- 业务成长空间清晰\n- 团队协作氛围开放\n\n'
            '岗位职责\n- 负责核心业务目标的推进与交付\n\n'
            '任职要求\n- 具备相关岗位经验和良好的沟通协作能力'
        )
    if template_id == 'analysis_report':
        report = _candidate_ranking_report(message, context)
        if report:
            return report
        return '分析报告\n\n目前未提供系统数据上下文，以下只能给出报告框架：背景、关键发现、风险点、建议动作、下一步计划。'
    return '请补充生成目标、受众、语气和关键信息，我可以据此生成一版 HR 文案。'


def _should_review_generation(plan: GenerationPlan, context: Optional[Dict[str, Any]], draft: str) -> bool:
    if not model_settings.feature_enabled('multiAgentReasoning'):
        return False
    if (plan.template_id or '') not in COMPLEX_REVIEW_TEMPLATES:
        return False
    if not draft or len(draft.strip()) < 6:
        return False
    if not isinstance(context, dict) or not context:
        return False
    return bool(context.get('items') or context.get('details') or context.get('facts') or context.get('tool_outputs'))


def _review_generation_output(
    message: str,
    plan: GenerationPlan,
    context: Optional[Dict[str, Any]],
    draft: str,
    ctx: Optional[AssistantContext] = None,
) -> Optional[str]:
    if not _should_review_generation(plan, context, draft):
        return None
    prompt = (
        f'用户请求：{message}\n\n'
        f'生成类型：{plan.template_id}\n'
        f'约束：{json.dumps(plan.constraints or {}, ensure_ascii=False)}\n\n'
        f'context（系统工具已加载的真实证据）：\n{_context_text(context)}\n\n'
        f'第一模型草稿：\n{draft[:12000]}\n\n'
        '请作为第二模型复核并直接输出最终答案：\n'
        '1. 保留草稿中有证据支撑的正确结论；\n'
        '2. 补足遗漏的证据、排序依据、候选人差异、风险和建议动作；\n'
        '3. 如果草稿说“无法访问系统数据”但 context 已有证据，必须改为基于证据回答；\n'
        '4. 不新增 context 中没有的人名、分数、薪酬、电话、业务记录；\n'
        '5. 输出清爽中文文本，不要写“复核过程”或元说明。'
    )
    try:
        reviewed = llm_client.chat_profile(
            'strong',
            [
                {'role': 'system', 'content': REVIEW_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            temperature=min(plan.temperature, 0.35),
            max_tokens=max(plan.max_tokens, 1600),
            timeout=None,
            use_case='evidenceAnalysis',
            ctx=ctx,
        )
    except Exception:
        return None
    if not reviewed:
        return None
    text = llm_client.clean_text(reviewed.get('content') or '')
    return text.strip() or None


class GenerationExecutor:
    def execute(
        self,
        message: str,
        ctx: AssistantContext,
        generation_plan: GenerationPlan,
        context: Optional[Dict[str, Any]] = None,
        route_decision: Optional[RouteDecision] = None,
    ) -> ExecutionResult:
        if generation_plan.template_id == 'workset_analysis':
            direct_answer = _direct_answer_from_context(context)
            if direct_answer:
                text = redact_generation_output(direct_answer, ctx.role)
                return OutputComposer.generation(text, ctx, route_decision)
        if generation_plan.template_id in ('candidate_compare', 'analysis_report'):
            report = _candidate_ranking_report(message, context)
            if report:
                text = redact_generation_output(report, ctx.role)
                return OutputComposer.generation(text, ctx, route_decision)
        if generation_plan.template_id in ('candidate_assessment', 'person_assessment', 'person_evidence_answer', 'analysis_report'):
            followup_answer = _candidate_followup_risk_answer(message, context)
            if followup_answer:
                text = redact_generation_output(followup_answer, ctx.role)
                return OutputComposer.generation(text, ctx, route_decision)

        prompt = (
            f'用户请求：{message}\n\n'
            f'生成类型：{generation_plan.template_id}\n'
            f'约束：{json.dumps(generation_plan.constraints or {}, ensure_ascii=False)}\n\n'
            f'context：\n{_context_text(context)}\n\n'
            '请输出清爽的中文文本。可以用编号和短标题，不要使用 # 标题、--- 分割线或大段模板化 Markdown。\n'
            '如果 context.items/details 包含多个人或多份简历，且用户要求“每个/每位/分别/逐个/他们/这些/上面这些”，'
            '必须逐个对象单独成节，结合每个对象的 summary、skills、strengths、weaknesses、interview_focus、interview_questions 生成，'
            '不要输出多份完全相同的模板。若某个对象只有摘要信息，请明确写“基于当前摘要信息”。'
        )
        llm_msg = llm_client.chat_profile(
            generation_plan.model_profile,
            [
                {'role': 'system', 'content': GENERATION_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            temperature=generation_plan.temperature,
            max_tokens=generation_plan.max_tokens,
            timeout=None,
            use_case=generation_plan.template_id,
            ctx=ctx,
        )
        if llm_msg:
            markdown = llm_client.clean_text(llm_msg.get('content') or '')
            reviewed = _review_generation_output(message, generation_plan, context, markdown, ctx)
            if reviewed:
                markdown = reviewed
                generation_plan.constraints = dict(generation_plan.constraints or {})
                generation_plan.constraints['multiAgentReview'] = {
                    'used': True,
                    'reviewProfile': 'strong',
                }
        else:
            markdown = _fallback_generation(message, generation_plan, context)
        markdown = redact_generation_output(markdown, ctx.role)
        return OutputComposer.generation(markdown, ctx, route_decision)
