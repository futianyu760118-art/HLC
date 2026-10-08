"""LLM Router / Intent Planner。

设计：
- 先跑轻量规则匹配（关键字 + 写动作拦截）。
- 规则不确定时再调 LLM 路由器，并提供精简 task 列表给 LLM 选择。
- LLM Router 不能调用任何工具/skill，只输出 RouterResult JSON。
- 所有 candidate_skills 必须存在于 skill_registry。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from . import llm_client, skill_registry, task_registry
from .constants import (
    PAYROLL_AUTHORIZED_ROLES, RISK_HIGH, RISK_LOW, RISK_MEDIUM,
)
from .guardrails import detect_write_intent
from .schemas import AssistantContext, RouterResult

logger = logging.getLogger('hengpintong.assistant.router')


# ============================================================
# 关键词 → 任务/领域映射
# ============================================================
DOMAIN_RULES: List[tuple] = [
    # (匹配关键词列表, 主任务 id, 候选 skills, confidence)
    (['工资', '工资条', '薪资', '薪酬', '社保', '个税'],
     'payroll_month_summary', ['payroll_analysis'], 0.85),
    (['考勤', '迟到', '缺卡', '早退', '请假', '加班', '出差', '补卡', '考勤异常'],
     'attendance_exception_analysis', ['attendance_analysis', 'employee_search'], 0.85),
    (['绩效', '评分等级', '考核', '等级分布'],
     'performance_distribution_report', ['performance_analysis', 'employee_search'], 0.82),
    (['培训', '课程', '培训计划', '完成率', '出勤'],
     'training_completion_report', ['training_analysis'], 0.82),
    (['面试计划', '面试安排', '排面试', '推荐面试'],
     'interview_schedule_plan', ['resume_analysis', 'interview_planning'], 0.86),
    (['分析最近', '最近简历', '最近的简历', '高分简历', '推荐简历', '评分最高的简历'],
     'recent_resume_analysis', ['resume_analysis', 'recruitment_search'], 0.86),
    (['招聘情况', '招聘进展', '招聘报表', '招聘概览', '本周招聘'],
     'recruitment_overview', ['dashboard_report', 'recruitment_search', 'resume_analysis'], 0.84),
    (['组织架构', '部门人数', '部门有哪些人', '岗位体系'],
     'organization_overview', ['organization_search', 'employee_search', 'dashboard_report'], 0.82),
    (['入职进度', '入职任务', '入职清单', '新员工入职'],
     'onboarding_progress_check', ['employee_search'], 0.78),
    (['试用期', '快到转正', '转正审批'],
     'probation_review_summary', ['employee_search', 'approval_search'], 0.78),
    (['离职', '辞职', '离职率', '离职原因'],
     'resignation_reason_summary', ['employee_search', 'dashboard_report'], 0.78),
    (['待审批', '待我审批', '我的申请', '审批记录'],
     'approval_pending_summary', ['approval_search'], 0.85),
    (['反馈', 'bug', '缺陷', '需求', '已修复', '已采纳'],
     'feedback_triage_summary', ['feedback_triage'], 0.82),
    (['写一封', '帮我写', '草稿', '邮件', '邀请函', '生成话术', '通知文案'],
     'hr_draft_generation', ['draft_generator', 'global_search'], 0.78),
    (['系统概览', '总览', '整体情况', '系统情况'],
     'system_dashboard', ['dashboard_report'], 0.86),
    (['比较', '谁更适合', '哪个更适合', '更适合做'],
     'candidate_compare', ['recruitment_search', 'resume_analysis'], 0.74),
    (['匹配度', '适合', '胜任'],
     'job_fit_analysis', ['recruitment_search', 'resume_analysis'], 0.7),
    (['在哪个部门', '入职时间', '什么岗位', '哪个部门'],
     'employee_lookup', ['employee_search', 'organization_search'], 0.78),
]

# 模糊任务关键词 → 兜底任务
FUZZY_KEYWORDS_RECRUIT = ['简历', '候选人', '应聘']
FUZZY_KEYWORDS_INTERVIEW = ['面试']
FUZZY_KEYWORDS_RECRUITMENT = ['招聘']
FUZZY_KEYWORDS_ATTENDANCE = ['考勤']
FUZZY_KEYWORDS_PERFORMANCE = ['绩效', '考核']
FUZZY_KEYWORDS_PAYROLL = ['薪资', '工资', '薪酬']
FUZZY_KEYWORDS_FEEDBACK = ['反馈', 'bug']
FUZZY_VERBS = ['分析', '汇总', '报表', '计划', '安排', '统计', '概览', '推荐', '建议', '做一个', '看一下', '看下', '帮我做', '看看', '瞅瞅', '瞧瞧']


# ============================================================
# 规则路由
# ============================================================
_CN_NAME_RE = re.compile(r'[\u4e00-\u9fa5]{2,4}')
_NAMED_RESUME_LOOKUP_RE = re.compile(
    r'^\s*[\u4e00-\u9fa5A-Za-z0-9·]{2,30}\s*的\s*(简历|候选人信息|候选人资料|资料|详情)\s*$'
)

# 注意：长串短语必须在子串之前，避免被部分匹配吃掉
_STOP_PHRASES = [
    # 多字短语优先
    '帮我查查', '帮我查一下', '帮我查找', '帮我看一下', '帮我看看', '帮我看下',
    '帮我找一下', '帮我搜一下', '帮我瞅瞅', '帮我瞄一眼', '帮我瞧瞧',
    '查一下', '找一下', '搜一下', '看一下', '看看', '看下', '瞅瞅', '瞧瞧', '瞄一眼',
    '这个员工', '这位员工', '这名员工', '这个候选人', '这位候选人', '这名候选人',
    '这个人', '这位', '这名', '此人', '该员工', '该候选人',
    '的简历', '的候选人信息', '的员工信息',
    '的信息', '的资料', '的详情', '的情况', '的档案',
    '在哪个部门', '在哪个岗位', '是哪个部门', '是哪个岗位', '是谁', '在哪', '什么部门', '什么岗位',
    '怎么样', '怎么', '什么情况',
    '系统里', '系统中', '里面', '相关',
    '帮我', '帮我看', '帮我找', '麻烦', '请帮我', '请你',
    # 短助词
    '查查', '查询', '查找', '搜索', '找找',
    '我想', '我要', '请', '你', '能否', '可以', '一下',
]


def _extract_keyword(message: str) -> Optional[str]:
    """简单关键词抽取：先去停用短语，再用中文姓名兜底。"""
    if not message:
        return None
    text = message
    for s in _STOP_PHRASES:
        text = text.replace(s, '')
    text = text.strip().strip('?？.。!！,，、的 ')
    # 去掉首尾的标点/空白
    if 2 <= len(text) <= 30:
        return text
    # 长度不符 → 用中文姓名模式兜底（2-4 个汉字）
    candidates = _CN_NAME_RE.findall(message)
    # 去掉明显的常见词
    blacklist = {'员工', '候选人', '部门', '岗位', '面试', '简历', '人员', '同事', '老板',
                 '上级', '下属', '同学', '朋友', '系统', '信息', '资料', '详情'}
    for c in candidates:
        if c not in blacklist and 2 <= len(c) <= 4:
            return c
    return None


def _extract_recruitment_keyword(message: str) -> Optional[str]:
    """Extract job/candidate keyword from recruitment list queries."""
    if not message:
        return None

    def clean_kw(value: str) -> Optional[str]:
        kw = (value or '').strip(' 的都有哪哪些人名单好多')
        # 清除前导时间修饰语，如 "10天收到的"、"3周来"、"本月收到的" 等
        kw = re.sub(r'^[\d一二三四五六七八九十百]+\s*[天周月年]\s*(?:来|内|的|收到|收到?的)*\s*', '', kw)
        kw = re.sub(r'^(最近|这|本[周月年]|上[周月])\s*', '', kw)
        for token in ['投递', '应聘', '简历', '候选人', '应聘者', '几位', '几名', '岗位', '职位',
                       '评分', '最高', '分析', '推荐', '面试', '有谁', '有哪些']:
            kw = kw.replace(token, ' ')
        kw = ' '.join(kw.split()).strip(' ，,。?？')
        _generic = {'最近', '投递', '应聘', '简历', '候选人', '评分', '最高',
                    '有哪些', '有谁', '好的', '分析', '推荐'}
        if kw and kw not in _generic and 2 <= len(kw) <= 30:
            return kw
        return None

    patterns = [
        r'应聘\s*([A-Za-z0-9\u4e00-\u9fa5+#.\- ]{2,30})\s*的',
        r'投递\s*([A-Za-z0-9\u4e00-\u9fa5+#.\- ]{2,30})\s*(?:岗位|职位|简历|的)',
        r'最近(?:来)?应聘\s*([A-Za-z0-9\u4e00-\u9fa5+#.\- ]{2,30})',
        r'最近\s*([A-Za-z0-9\u4e00-\u9fa5+#.\- ]{2,30})\s*(?:候选人|简历|应聘者)',
    ]
    for pattern in patterns:
        m = re.search(pattern, message)
        if m:
            kw = clean_kw(m.group(1))
            if kw:
                return kw[:30]

    text = message
    for token in [
        '帮我', '找一下', '查一下', '最近', '来', '应聘', '投递', '简历',
        '候选人', '应聘者', '几位', '几名', '哪些人', '都有哪些人',
        '有哪些人', '名单', '的', '一下', '收到',
    ]:
        text = text.replace(token, ' ')
    # 清除时间表达式，如 "10天"、"3周"、"本月" 等
    text = re.sub(r'[\d一二三四五六七八九十百]+\s*[天周月年]', ' ', text)
    text = re.sub(r'(这|本[周月年]|上[周月])\s*', ' ', text)
    text = ' '.join(text.split()).strip(' ，,。?？')
    return clean_kw(text)


def _is_recent_recruitment_query(message: str) -> bool:
    if not message:
        return False
    has_recent = bool(re.search(r'(最近|近\s*\d+\s*天|本周|本月)', message))
    has_recruit = any(k in message for k in ('应聘', '投递', '简历', '候选人'))
    asks_list = any(k in message for k in ('哪些', '哪些人', '都有谁', '有谁', '名单', '几位', '几名', '找一下', '查一下'))
    return has_recent and has_recruit and asks_list


def rule_route(message: str, ctx: AssistantContext) -> RouterResult:
    """基于关键词的快速规则路由。"""
    if not message:
        return RouterResult(
            intent='empty', task_template_id=None, confidence=0.0,
            reason='空消息',
        )

    # 先做高风险写动作拦截
    forbidden = detect_write_intent(message)
    if forbidden:
        return RouterResult(
            intent='forbidden_action',
            task_template_id='forbidden_action_response',
            confidence=0.95,
            entities={'forbidden_reason': forbidden},
            risk_level=RISK_HIGH,
            requires_confirmation=True,
            candidate_skills=[],
            reason='识别到高风险动作请求',
            forbidden_reason=forbidden,
            rule_matched=True,
        )

    if _is_recent_recruitment_query(message):
        return _rule_result(
            'recent_resume_analysis',
            ['resume_analysis', 'recruitment_search'],
            0.88,
            _extract_default_entities(message, 'recent_resume_analysis'),
            '最近招聘/投递查询',
        )

    if _NAMED_RESUME_LOOKUP_RE.search(message):
        keyword = _extract_keyword(message)
        if keyword:
            return RouterResult(
                intent='global_search_answer',
                task_template_id='global_search_answer',
                confidence=0.86,
                entities={'keyword': keyword},
                risk_level=RISK_LOW,
                candidate_skills=['global_search', 'recruitment_search'],
                reason=f'点名查询候选人简历/资料："{keyword}"',
                rule_matched=True,
            )

    # 关键词命中
    text_lower = message.lower()
    for keywords, task_id, skills, confidence in DOMAIN_RULES:
        for kw in keywords:
            if kw in message or kw.lower() in text_lower:
                # 薪酬域必须 high risk
                risk = RISK_HIGH if 'payroll' in task_id else RISK_LOW
                # 提取常用实体
                entities = _extract_default_entities(message, task_id)
                return RouterResult(
                    intent=task_id, task_template_id=task_id,
                    confidence=confidence, entities=entities,
                    risk_level=risk,
                    candidate_skills=skills[:5],
                    requires_confirmation=False,
                    reason=f'规则命中关键词：{kw}',
                    rule_matched=True,
                )

    # 模糊任务（"分析一下/汇总一下"）
    has_verb = any(v in message for v in FUZZY_VERBS)
    if has_verb:
        if any(k in message for k in FUZZY_KEYWORDS_RECRUIT):
            return _rule_result('recent_resume_analysis', ['resume_analysis', 'recruitment_search'], 0.7,
                                _extract_default_entities(message, 'recent_resume_analysis'),
                                '模糊任务+简历关键词')
        if any(k in message for k in FUZZY_KEYWORDS_INTERVIEW):
            return _rule_result('interview_schedule_plan', ['resume_analysis', 'interview_planning'], 0.7,
                                _extract_default_entities(message, 'interview_schedule_plan'),
                                '模糊任务+面试关键词')
        if any(k in message for k in FUZZY_KEYWORDS_RECRUITMENT):
            return _rule_result('recruitment_overview', ['dashboard_report', 'recruitment_search'], 0.7,
                                {}, '模糊任务+招聘关键词')
        if any(k in message for k in FUZZY_KEYWORDS_ATTENDANCE):
            return _rule_result('attendance_exception_analysis', ['attendance_analysis'], 0.7,
                                {}, '模糊任务+考勤关键词')
        if any(k in message for k in FUZZY_KEYWORDS_PERFORMANCE):
            return _rule_result('performance_distribution_report', ['performance_analysis'], 0.7,
                                {}, '模糊任务+绩效关键词')
        if any(k in message for k in FUZZY_KEYWORDS_PAYROLL):
            return _rule_result('payroll_month_summary', ['payroll_analysis'], 0.85,
                                {}, '模糊任务+薪酬关键词', risk=RISK_HIGH)
        if any(k in message for k in FUZZY_KEYWORDS_FEEDBACK):
            return _rule_result('feedback_triage_summary', ['feedback_triage'], 0.7,
                                {}, '模糊任务+反馈关键词')
        # 没有具体域关键词 → 系统总览
        return _rule_result('system_dashboard', ['dashboard_report'], 0.6,
                            {}, '模糊任务但无明确域 → 系统总览')

    # 没规则命中——人名提取兜底
    keyword = _extract_keyword(message)
    # "查一下/找一下/有没有/看看 + 人名/对象" 这类问句默认走搜索兜底
    lookup_verbs = ['查一下', '找一下', '查查', '找找', '有没有', '查找',
                    '帮我查', '帮我找', '看看', '瞅瞅', '瞧瞧', '帮我看看', '帮我看']
    if keyword and any(v in message for v in lookup_verbs):
        # 有"简历"关键词→走全局搜索（覆盖候选人+简历）
        resume_signals = ['简历', '候选人', '应聘', '投递']
        if any(s in message for s in resume_signals):
            return RouterResult(
                intent='global_search_answer',
                task_template_id='global_search_answer',
                confidence=0.75,
                entities={'keyword': keyword},
                risk_level=RISK_LOW,
                candidate_skills=['global_search', 'recruitment_search'],
                reason=f'查询动词+简历信号+关键词："{keyword}"',
                rule_matched=True,
            )
        return RouterResult(
            intent='employee_lookup',
            task_template_id='employee_lookup',
            confidence=0.6,
            entities={'keyword': keyword},
            risk_level=RISK_LOW,
            candidate_skills=['employee_search', 'organization_search', 'global_search'],
            reason=f'查询动词 + 关键词："{keyword}"',
            rule_matched=True,
        )

    # 有关键词但没匹配到动词 → 也走全局搜索
    if keyword:
        return RouterResult(
            intent='global_search_answer',
            task_template_id='global_search_answer',
            confidence=0.5,
            entities={'keyword': keyword},
            risk_level=RISK_LOW,
            candidate_skills=['global_search'],
            reason=f'提取到关键词兜底搜索："{keyword}"',
            rule_matched=True,
        )

    return RouterResult(
        intent='unknown',
        task_template_id=None,
        confidence=0.4,
        entities={},
        risk_level=RISK_LOW,
        candidate_skills=['global_search'],
        reason='规则未命中',
        rule_matched=False,
    )


def _rule_result(task_id: str, skills: List[str], confidence: float,
                 entities: Dict, reason: str, risk: str = RISK_LOW) -> RouterResult:
    return RouterResult(
        intent=task_id, task_template_id=task_id,
        confidence=confidence, entities=entities,
        risk_level=risk,
        candidate_skills=skills[:5],
        reason=reason, rule_matched=True,
    )


def _extract_default_entities(message: str, task_id: str) -> Dict[str, Any]:
    """从消息里抽取常用实体值（支持默认值）。"""
    entities: Dict[str, Any] = {}

    # 时间窗
    m = re.search(r'(\d+)\s*天', message)
    if m:
        entities['recent_days'] = int(m.group(1))
    elif '本周' in message:
        entities['recent_days'] = 7
    elif '本月' in message:
        entities['recent_days'] = 30
    else:
        # 简历分析默认 7 天
        if task_id in ('recent_resume_analysis', 'interview_schedule_plan'):
            entities['recent_days'] = 7

    # top n
    m = re.search(r'top\s*(\d+)|前\s*(\d+)', message, re.IGNORECASE)
    if m:
        entities['top_n'] = int(m.group(1) or m.group(2))

    # 月份 yyyy-mm
    m = re.search(r'(\d{4})[-年/](\d{1,2})', message)
    if m:
        entities['month'] = f'{m.group(1)}-{int(m.group(2)):02d}'

    # 草稿类型
    if task_id == 'hr_draft_generation':
        if '面试' in message and ('邀请' in message or '通知' in message):
            entities['draft_type'] = 'interview_invite'
        elif 'offer' in message.lower():
            entities['draft_type'] = 'offer_communication'
        elif '入职' in message:
            entities['draft_type'] = 'onboarding_notice'
        elif '培训' in message:
            entities['draft_type'] = 'training_notice'
        else:
            entities['draft_type'] = 'interview_invite'
        kw = _extract_keyword(message)
        if kw:
            entities['keyword'] = kw

    # 关键词（用于 search 类任务）
    if task_id in ('global_search_answer', 'employee_lookup', 'candidate_compare', 'job_fit_analysis'):
        kw = _extract_keyword(message)
        if kw:
            entities['keyword'] = kw

    if task_id in ('recent_resume_analysis', 'interview_schedule_plan'):
        kw = _extract_recruitment_keyword(message)
        if kw:
            entities['keyword'] = kw

    # 反馈类型
    if task_id == 'feedback_triage_summary':
        if 'bug' in message.lower() or '缺陷' in message:
            entities['feedback_type'] = 'bug'
        elif '需求' in message:
            entities['feedback_type'] = 'feature'
        if '待处理' in message or '没处理' in message:
            entities['status'] = 'pending'

    # 审批 view
    if task_id == 'approval_pending_summary':
        if '待我审批' in message or '待审批' in message:
            entities['view'] = 'pending'
        elif '我的申请' in message:
            entities['view'] = 'mine'
        elif '历史' in message:
            entities['view'] = 'history'
        else:
            entities['view'] = 'pending'

    return entities


# ============================================================
# LLM 实体精炼：规则匹配到 task 后，用 LLM 提取参数
# ============================================================
def _llm_refine_entities(
    message: str,
    task_id: str,
    entity_schema: Dict[str, Any],
    ctx: AssistantContext,
) -> Optional[Dict[str, Any]]:
    """用 LLM 从用户消息中提取 task 所需的实体参数。

    规则路由确定了 task_id，但 regex 提取的实体往往不准确。
    这里把实体 schema 和用户消息交给 LLM，让它精确提取参数。
    只做一次轻量调用（~200 tokens），延迟可控。
    """
    if not llm_client.is_available() or not entity_schema:
        return None

    schema_desc = '\n'.join(
        f'  - {k} ({v.get("type", "any")}): {v.get("description", "")}'
        if isinstance(v, dict) else f'  - {k}: {v}'
        for k, v in entity_schema.items()
    )

    system_prompt = (
        '你是参数提取器，不是对话助手。根据用户消息提取指定参数。\n'
        f'当前任务: {task_id}\n'
        f'需要提取的参数:\n{schema_desc}\n\n'
        '规则:\n'
        '1. 只输出 JSON，不输出任何其他文字\n'
        '2. 消息中未提及的参数设为 null\n'
        '3. recent_days 必须是整数\n'
        '4. keyword 是用户查询的核心对象名称（人名、岗位名等），不是整句话\n'
        '5. 时间表达转换：最近10天→10，本周→7，本月→30\n'
        '6. 只从当前消息提取参数，忽略任何历史对话内容\n'
    )

    # 不传对话历史：实体精炼只看当前消息，避免上一轮参数污染
    user_prompt = f'用户消息: {message}'

    try:
        data = llm_client.json_chat_profile(
            'small',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=0.0,
            max_tokens=200,
            use_case='legacy_entity_refinement',
            resource_domain='assistant',
            ctx=ctx,
        )
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k in entity_schema and v is not None}
    except Exception:
        logger.exception('llm_refine_entities_failed')
    return None


# ============================================================
# LLM 路由器
# ============================================================
def _is_empty_entity_value(value: Any) -> bool:
    return value is None or value == '' or value == [] or value == {}


def _merge_entities_preserving_rules(
    base_entities: Optional[Dict[str, Any]],
    llm_entities: Any,
) -> Dict[str, Any]:
    """Merge LLM-extracted entities without erasing rule-extracted values.

    The rule layer often extracts deterministic fields such as ``keyword`` and
    date windows. The LLM router may return empty placeholders for those fields;
    those must not overwrite usable rule values, otherwise downstream skills see
    a missing required parameter.
    """
    merged: Dict[str, Any] = dict(base_entities or {})
    if not isinstance(llm_entities, dict):
        return merged
    for key, value in llm_entities.items():
        if _is_empty_entity_value(value):
            continue
        merged[key] = value
    return merged


def llm_route(message: str, ctx: AssistantContext, base_result: RouterResult) -> RouterResult:
    """规则不确定时调用 LLM 路由。"""
    if not llm_client.is_available():
        return base_result

    tasks_brief = task_registry.list_brief(role=ctx.role)
    skills_brief = skill_registry.list_brief()

    system_prompt = (
        '你是恒聘通 HRM AI 助手的任务路由器，不是执行器。\n'
        '只能从下面给定的 task_templates 中选择一个；不能创造新的 id。\n'
        '只能从下面给定的 skills 中选 1-5 个 candidate_skills；不能创造新的 id。\n'
        '不允许直接调用任何工具，只输出 JSON 计划。\n'
        '如果无法判断，task_template_id 设为 global_search_answer 并降低 confidence。\n\n'
        f'可用 task_templates: {json.dumps(tasks_brief, ensure_ascii=False)}\n\n'
        f'可用 skills: {json.dumps(skills_brief, ensure_ascii=False)}\n\n'
        '输出严格 JSON：{"intent","task_template_id","confidence","entities","missing_fields",'
        '"risk_level","candidate_skills","requires_confirmation","clarification_question","reason"}'
    )

    history_text = ''
    if ctx.history:
        last = ctx.history[-4:]
        history_text = '\n最近对话历史:\n' + '\n'.join(
            f'[{h.get("role")}] {(h.get("content") or "")[:120]}' for h in last
        )

    user_prompt = f'用户问题: {message}{history_text}\n请输出 JSON 路由结果。'

    data = llm_client.json_chat_profile(
        'small',
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        temperature=0.1,
        max_tokens=600,
        use_case='legacy_route',
        resource_domain='assistant',
        ctx=ctx,
    )
    if not data:
        return base_result

    # 校验 task_template_id
    task_id = data.get('task_template_id')
    if task_id and not task_registry.exists(task_id):
        logger.warning('llm_router_invalid_task', extra={'task': task_id})
        task_id = base_result.task_template_id or 'global_search_answer'

    # 校验 candidate_skills
    cand = [s for s in (data.get('candidate_skills') or []) if skill_registry.exists(s)][:5]
    if not cand and task_id:
        t = task_registry.get(task_id)
        if t:
            cand = [s for s in t.candidate_skills if skill_registry.exists(s)][:5]

    # 数值容错
    try:
        confidence = float(data.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    risk = data.get('risk_level') or RISK_LOW
    if risk not in (RISK_LOW, RISK_MEDIUM, RISK_HIGH):
        risk = RISK_LOW
    # payroll 强制 high
    if any('payroll' in s for s in cand) or task_id == 'payroll_month_summary':
        risk = RISK_HIGH

    entities = _merge_entities_preserving_rules(base_result.entities, data.get('entities'))
    if task_id in ('global_search_answer', 'employee_lookup', 'candidate_compare', 'job_fit_analysis'):
        if _is_empty_entity_value(entities.get('keyword')):
            kw = _extract_keyword(message)
            if kw:
                entities['keyword'] = kw

    return RouterResult(
        intent=str(data.get('intent') or task_id or 'unknown'),
        task_template_id=task_id,
        confidence=confidence,
        entities=entities,
        missing_fields=data.get('missing_fields') or [],
        risk_level=risk,
        candidate_skills=cand,
        requires_confirmation=bool(data.get('requires_confirmation', False)),
        clarification_question=data.get('clarification_question'),
        reason=data.get('reason') or 'LLM 路由',
        rule_matched=False,
    )


# ============================================================
# 主入口
# ============================================================
def route(message: str, ctx: AssistantContext) -> RouterResult:
    """规则 + LLM 混合路由。"""
    base = rule_route(message, ctx)

    # 高置信度规则命中 → task_id 确定，但用 LLM 精炼实体参数
    if base.rule_matched and base.confidence >= 0.78:
        allow_entity_refine = os.getenv('ASSISTANT_ENABLE_ENTITY_REFINE_OUTSIDE_APP') == '1'
        try:
            from flask import has_app_context

            allow_entity_refine = allow_entity_refine or has_app_context()
        except Exception:
            pass
        if allow_entity_refine and base.task_template_id:
            task = task_registry.get(base.task_template_id)
            if task and (task.optional_entities or task.required_entities):
                schema = {}
                if task.optional_entities:
                    schema.update(task.optional_entities)
                if task.required_entities:
                    for e in task.required_entities:
                        schema.setdefault(e, {'type': 'string'})
                refined = _llm_refine_entities(
                    message, base.task_template_id, schema, ctx,
                )
                if refined:
                    # LLM 提取的实体覆盖 regex 实体（LLM 更准确）
                    base.entities.update(refined)
        return base

    # 规则置信度低 → 走 LLM
    if base.confidence < 0.55 or not base.task_template_id:
        result = llm_route(message, ctx, base)
        # 兜底
        if not result.task_template_id or result.confidence < 0.55:
            result.task_template_id = 'global_search_answer'
            keyword = _extract_keyword(message)
            if keyword and 'keyword' not in result.entities:
                result.entities['keyword'] = keyword
            if not result.candidate_skills:
                result.candidate_skills = ['global_search']
            result.reason = (result.reason or '') + ' → 兜底 global_search_answer'
        return result

    # 中等置信度（0.55-0.78）：使用规则结果
    return base
