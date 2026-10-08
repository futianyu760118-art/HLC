"""Minimal planner for the hybrid assistant router."""

from __future__ import annotations

import re
import os
from datetime import datetime, timedelta
from typing import Optional

from ..schemas import (
    AssistantContext,
    GenerationPlan,
    RouteDecision,
    RouterResult,
    ToolCallPlan,
    router_result_to_route_decision,
)
from .classifier import (
    TRACK_A,
    TRACK_B,
    TRACK_C,
    TRACK_COMPOSITE,
    TrackClassifier,
    _extract_named_people,
)
from ..model_settings import feature_enabled
from ..constants import PAYROLL_AUTHORIZED_ROLES, RISK_HIGH, RISK_LOW
from ..guardrails import detect_write_intent
from services.business_time import business_now


_COMPOSITE_GENERATION_RE = (
    r'(生成|输出|整理|形成|给出|写|起草|设计|准备|出|'
    r'报告|报表|摘要|总结|复盘|分析|建议|方案|计划|话术|文案|要点|提醒|问题|追问|面试题|优先级)'
)
_COMPOSITE_SPLIT_RE = (
    r'(?:并|然后|再|之后|后)\s*(?:帮我|请|给我)?\s*'
    r'(?:生成|输出|整理|形成|给出|写|起草|设计|准备|出)'
)


def _composite_query_text(message: str) -> str:
    text = message or ''
    match = re.search(_COMPOSITE_SPLIT_RE, text, re.I)
    if match:
        return text[:match.start()]
    return text


def _has_workset_reference(message: str) -> bool:
    return bool(re.search(
        r'(这些|这批|这几个|上面|刚才|刚刚|上一批|上一轮|上轮|前面|那批|那些|'
        r'列表里|表格里|结果里|名单里|上述|以上|他们|她们|第\s*[一二两三四五六七八九十\d]+|'
        r'排名前三|排名前3|top\s*\d+)',
        message or '',
        re.I,
    ))


def _has_explicit_named_subject_query(message: str) -> bool:
    text = message or ''
    if _extract_named_people(text):
        return True
    return bool(re.search(
        r'(?:基于|针对|根据|给|为|分析|评价|评估|判断|推荐|查|查看|搜索)?\s*'
        r'([\u4e00-\u9fa5·]{2,4})的(?:简历|资料|详情|面试|复试|Offer|offer|投递记录|录用进度|'
        r'考勤|绩效|薪酬|工资|合同|入职|转正|离职|培训|记录)',
        text,
        re.I,
    ))


def _has_named_subject_evidence_context(decision: RouteDecision) -> bool:
    return (
        decision.route_track == TRACK_B
        and bool({'named_subject_evidence', 'named_subjects_evidence'}.intersection(
            set(decision.required_context or [])
        ))
    )


def _has_job_candidate_pool_scope(message: str) -> bool:
    text = message or ''
    job_scope = r'(岗位|职位|JD|jd|招聘需求|招聘|应聘|投递)'
    pool_scope = r'(候选人|应聘者|应聘的人|应聘.+的人|简历|人选|人才|人才库)'
    return bool(
        re.search(rf'{job_scope}.{{0,18}}{pool_scope}', text, re.I)
        or re.search(rf'{pool_scope}.{{0,18}}{job_scope}', text, re.I)
    )


def _has_domain_scoped_composite_query(message: str) -> bool:
    """Detect query scopes that are business domains, not person evidence asks."""
    text = message or ''
    return bool(
        _infer_recruitment_module(text)
        or re.search(
            r'(招聘|岗位|职位|JD|jd|候选人|简历|面试|复试|一面|二面|三面|终面|Offer|offer|投递|应聘|'
            r'考勤|迟到|缺卡|早退|请假|加班|出差|补卡|绩效|考核|评分|薪酬|薪资|工资|工资条|'
            r'培训|课程|完成率|通过率|学习进度|培训成绩|课程反馈|审批|申请|待办|报销|反馈|bug|缺陷|需求|'
            r'系统概览|整体情况|数据看板|驾驶舱|仪表盘|组织架构|部门|岗位序列|员工名单|员工花名册|员工档案|员工信息)',
            text,
            re.I,
        )
    )


def _is_readonly_composite_action_false_positive(message: str) -> bool:
    query_text = _composite_query_text(message)
    return bool(
        re.search(r'(面试安排|面试记录|面试日程|面试排期|待面试)', query_text)
        and re.search(_COMPOSITE_GENERATION_RE, message or '', re.I)
    )


def _has_composite_shape(message: str) -> bool:
    text = message or ''
    if not text or _is_direct_dialogue_boundary(text):
        return False
    has_query = bool(re.search(
        r'(查|查询|搜索|列出|查看|看看|看一下|看下|找|找出|统计|汇总|筛选|'
        r'名单|列表|记录|概览|看板|驾驶舱|仪表盘|分布|趋势|排名|进度|待|已|最近|本周|本月)',
        text,
        re.I,
    ))
    has_generation = bool(re.search(_COMPOSITE_GENERATION_RE, text, re.I))
    has_connector = bool(re.search(r'(并|然后|再|后|之后)', text))
    return has_query and has_generation and has_connector


def _is_payroll_query(text: str) -> bool:
    return bool(re.search(r'(薪酬|薪资|工资|工资条|个税|社保|奖金|年终奖|实发工资|应发工资)', text or ''))


def _infer_composite_generation_intent(message: str) -> str:
    text = message or ''
    if re.search(r'(面试题|面试问题|追问|初面问题|二面问题|复试问题|终面问题|出题)', text):
        return 'interview_questions'
    if re.search(r'(对比|比较|排名|排行|排序|优先级)', text):
        return 'candidate_compare'
    return 'analysis_report'


def _composite_tool_plan(
    *,
    tool: str,
    message: str,
    step_id: Optional[str] = None,
    module: Optional[str] = None,
    risk_level: str = RISK_LOW,
    extra: Optional[dict] = None,
) -> ToolCallPlan:
    params = {'limit': _extract_recruitment_limit(message) or 20}
    if module:
        params['module'] = module
    if extra:
        params.update(extra)
    return ToolCallPlan(
        step_id=step_id or f'{tool}_query',
        tool=tool,
        purpose='query',
        input=params,
        required=True,
        risk_level=risk_level,
        cache_policy='session',
    )


def _direct_composite_plan(message: str, decision: RouteDecision, ctx: AssistantContext) -> Optional[RouteDecision]:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    if _is_direct_dialogue_boundary(text):
        return None
    if decision.task_type == 'forbidden':
        return None
    if _has_workset_reference(text):
        return None
    if decision.task_type == 'action' and not _is_readonly_composite_action_false_positive(text):
        return None
    query_text = _composite_query_text(text)
    explicit_nav_generation = bool(
        _nav_module_match(query_text)
        and re.search(
            r'(生成|输出|整理|形成|给出|写|起草|设计|准备).{0,24}'
            r'(查询)?(报表|报告|摘要|总结|复盘|分析|建议|方案|计划|话术|文案|要点|问题|追问|面试题|优先级)',
            text,
            re.I,
        )
    )
    if not _has_composite_shape(text) and not explicit_nav_generation:
        return None
    nav_spec = _nav_module_match(query_text)
    if (
        nav_spec
        and nav_spec.get('tool') == 'attendance_analysis'
        and re.search(r'(审批|待审批|待我审批|审批列表|审批记录|审批事项|审批中心|报销)', query_text)
    ):
        nav_spec = None
    if nav_spec and _is_nav_module_data_query(query_text):
        tool = nav_spec['tool']
        params = dict(nav_spec.get('input') or {})
        params.setdefault('limit', _extract_recruitment_limit(query_text) or 20)
        risk = nav_spec.get('risk') or (RISK_HIGH if tool == 'payroll_analysis' else RISK_LOW)
        tool_plan = [_composite_tool_plan(
            tool=tool,
            message=text,
            step_id=f'{tool}_nav_query',
            risk_level=risk,
            extra=params,
        )]
        intent = _infer_composite_generation_intent(text)
        return _with_generation_plan(RouteDecision(
            task_type='composite',
            route_track=TRACK_COMPOSITE,
            intent=intent,
            confidence=max(decision.confidence, 0.9),
            risk_level=risk,
            tool_plan=tool_plan,
            requires_confirmation=False,
            reason='direct_composite_nav_module_plan',
        ), text)
    if (
        set(decision.required_context or {}).intersection({'named_subject_evidence', 'named_subjects_evidence'})
        and _has_explicit_named_subject_query(query_text)
        and not _has_domain_scoped_composite_query(query_text)
    ):
        return None

    if _is_payroll_query(query_text):
        if ctx.role not in PAYROLL_AUTHORIZED_ROLES:
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='permission_denied',
                confidence=max(decision.confidence, 0.9),
                risk_level=RISK_HIGH,
                task_template_id='permission_denied_response',
                reason=f'direct_composite_plan:payroll_permission_denied:{ctx.role}',
            )
        tool_plan = [_composite_tool_plan(
            tool='payroll_analysis',
            message=text,
            step_id='payroll_query',
            risk_level=RISK_HIGH,
            extra=_ops_month_entities(text),
        )]
    elif re.search(r'(系统概览|总览|整体情况|系统情况|人力资源运营报表|HR\s*数据看板|管理驾驶舱|仪表盘指标|招聘报表|招聘概览|招聘进展)', query_text, re.I):
        scope = 'recruitment' if re.search(r'(招聘报表|招聘概览|招聘进展)', query_text) else 'system'
        tool_plan = [_composite_tool_plan(
            tool='dashboard_report',
            message=text,
            step_id='dashboard_query',
            extra={'scope': scope},
        )]
    elif (
        re.search(r'(审批|申请|待办|待我审批|待审批|驳回|审批通过率|报销)', query_text)
        and not re.search(r'(Offer|offer|录用)', query_text)
        and not _is_employee_lifecycle_query(query_text)
    ):
        view = 'pending'
        if re.search(r'(我的申请|我提交)', query_text):
            view = 'mine'
        elif '历史' in query_text:
            view = 'history'
        tool_plan = [_composite_tool_plan(
            tool='approval_search',
            message=text,
            step_id='approval_query',
            extra={'view': view},
        )]
    elif re.search(r'(考勤|迟到|缺卡|早退|请假|加班|出差|补卡)', query_text):
        tool_plan = [_composite_tool_plan(
            tool='attendance_analysis',
            message=text,
            step_id='attendance_query',
            extra=_ops_month_entities(text),
        )]
    elif re.search(r'(绩效|考核|评分等级|等级分布|等级员工|考核等级|绩效评分|绩效排名|绩效校准|A\s*等级)', query_text):
        tool_plan = [_composite_tool_plan(tool='performance_analysis', message=text, step_id='performance_query')]
    elif re.search(r'(培训|课程|培训员工|完成率|通过率|学习进度|培训成绩|课程反馈)', query_text) and not _is_employee_lifecycle_query(query_text):
        tool_plan = [_composite_tool_plan(tool='training_analysis', message=text, step_id='training_query')]
    elif _is_org_query(query_text) or re.search(r'[\u4e00-\u9fa5A-Za-z0-9]+部人员|[\u4e00-\u9fa5A-Za-z0-9]+中心下面', query_text):
        params = {'include_stats': True}
        keyword = _extract_org_keyword(query_text)
        if keyword:
            params['keyword'] = keyword
        tool_plan = [_composite_tool_plan(
            tool='organization_search',
            message=text,
            step_id='organization_query',
            extra=params,
        )]
    elif _is_employee_profile_query(query_text) or re.search(
        r'(已离职|离职状态|resigned|暂停状态|试用期|待入职|在职|正式员工|员工花名册|员工名单)',
        query_text,
        re.I,
    ):
        params: dict = {}
        keyword = _extract_employee_keyword(query_text)
        if keyword:
            params['keyword'] = keyword
        status = _infer_employee_status(query_text)
        if status:
            params['status'] = status
        tool_plan = [_composite_tool_plan(
            tool='employee_search',
            message=text,
            step_id='employee_query',
            extra=params,
        )]
    elif _is_employee_lifecycle_query(query_text):
        module = 'all' if _needs_all_lifecycle_modules(query_text) else 'lifecycle'
        params = {'module': module}
        keyword = _extract_lifecycle_keyword(query_text)
        if keyword:
            params['keyword'] = keyword
        tool_plan = [_composite_tool_plan(
            tool='system_search',
            message=text,
            step_id='employee_lifecycle_query',
            module=module,
            extra=params,
        )]
    else:
        module = _infer_recruitment_module(query_text)
        if not module and re.search(r'(招聘|岗位|职位|JD|jd|候选人|简历|面试|Offer|offer|投递|应聘)', query_text, re.I):
            module = 'candidates'
        if module:
            params = {
                'module': module,
                'limit': _extract_recruitment_limit(query_text) or (20 if _extract_recruitment_date_range(query_text) else 10),
            }
            keyword = _extract_recruitment_keyword(query_text, module)
            if keyword:
                params['keyword'] = keyword
            status = _infer_recruitment_status(query_text, module)
            if status:
                params['status'] = status
            date_range = _extract_recruitment_date_range(query_text)
            if date_range:
                params['date_range'] = date_range
            tool_plan = [_composite_tool_plan(
                tool='recruitment_search',
                message=text,
                step_id=f'recruitment_{module}_query',
                module=module,
                extra=params,
            )]
        elif re.search(r'(审批|申请|待办|待我审批|待审批|驳回|审批通过率|报销)', query_text):
            view = 'pending'
            if re.search(r'(我的申请|我提交)', query_text):
                view = 'mine'
            elif '历史' in query_text:
                view = 'history'
            tool_plan = [_composite_tool_plan(
                tool='approval_search',
                message=text,
                step_id='approval_query',
                extra={'view': view},
            )]
        elif re.search(r'(反馈|bug|缺陷|需求|已修复|已采纳)', query_text, re.I):
            extra: dict = {}
            if re.search(r'bug|缺陷', query_text, re.I):
                extra['feedback_type'] = 'bug'
            elif '需求' in query_text:
                extra['feedback_type'] = 'feature'
            if re.search(r'(待处理|没处理|未处理)', query_text):
                extra['status'] = 'pending'
            tool_plan = [_composite_tool_plan(
                tool='feedback_triage',
                message=text,
                step_id='feedback_query',
                extra=extra,
            )]
        else:
            return None

    intent = _infer_composite_generation_intent(text)
    return _with_generation_plan(RouteDecision(
        task_type='composite',
        route_track=TRACK_COMPOSITE,
        intent=intent,
        confidence=max(decision.confidence, 0.9),
        risk_level=RISK_HIGH if any(p.risk_level == RISK_HIGH for p in tool_plan) else RISK_LOW,
        tool_plan=tool_plan,
        requires_confirmation=False,
        reason='direct_composite_plan',
    ), text)


def _parse_limit(message: str, default: int = 5) -> int:
    match = re.search(r'(\d+)\s*(个|名|位|道|条)?', message or '')
    if not match:
        return default
    try:
        return max(1, min(int(match.group(1)), 20))
    except (TypeError, ValueError):
        return default


def _extract_keyword(message: str) -> str:
    text = message or ''
    # Keep this deliberately small. For the acceptance case it extracts Java.
    for token in ('Java', 'java', '前端', '后端', '产品', '运营', '测试', '销售', 'HR'):
        if token in text:
            return 'Java' if token.lower() == 'java' else token
    job_match = re.search(
        r'([\u4e00-\u9fa5A-Za-z0-9]{2,24}?(?:工程师|技术员|总监|经理|专员|主管|助理|顾问|负责人|开发|设计师|会计|出纳|HR|hr))'
        r'(?:的|岗位|职位|候选人|简历|都|有|$)',
        text,
        flags=re.IGNORECASE,
    )
    if job_match:
        return re.sub(r'^(最近|近\d+天|本周|本月|来|应聘|投递|招聘|找|查|搜索|查看|看看)+', '', job_match.group(1))
    cleaned = re.sub(r'(找出|查一下|最近|近\s*\d+\s*天|本周|本月|来|应聘|投递|招聘|\d+|个|名|位|候选人|简历|并|帮我|设计|生成|面试题|哪些人|有哪些人|都|有|的|，|,)', ' ', text)
    cleaned = ' '.join(cleaned.split())
    return cleaned[:30]


def _extract_recruitment_limit(message: str) -> Optional[int]:
    match = re.search(r'(\d+)\s*(个|名|位|份|条|场)', message or '')
    if not match:
        return None
    try:
        return max(1, min(int(match.group(1)), 50))
    except (TypeError, ValueError):
        return None


def _extract_recruitment_date_range(message: str) -> Optional[dict]:
    text = message or ''
    match = re.search(r'(?:近|最近)\s*(\d+)\s*天', text)
    if match:
        return {'recent_days': max(1, min(int(match.group(1)), 90))}
    today = business_now().date()
    day = None
    if '今天' in text:
        day = today
    elif '明天' in text:
        day = today + timedelta(days=1)
    elif '后天' in text:
        day = today + timedelta(days=2)
    if day is not None:
        return {
            'start': datetime.combine(day, datetime.min.time()).isoformat(),
            'end': datetime.combine(day, datetime.max.time()).replace(microsecond=0).isoformat(),
        }
    if '本周' in text:
        return {'recent_days': 7}
    if '本月' in text:
        return {'recent_days': 30}
    if re.search(r'(最近|刚投|新投|刚收到|新收到|新来的|最近来|最近投递|最近收到)', text):
        if not re.search(r'最近\s*\d+\s*(个|名|位|份|条|场)', text):
            return {'recent_days': 30}
    return None


def _ops_router_result(
    *,
    intent: str,
    skills: list[str],
    confidence: float,
    reason: str,
    risk: str = RISK_LOW,
    entities: Optional[dict] = None,
) -> RouteDecision:
    result = RouterResult(
        intent=intent,
        task_template_id=intent,
        confidence=confidence,
        entities=entities or {},
        risk_level=risk,
        candidate_skills=skills,
        requires_confirmation=False,
        reason=reason,
        rule_matched=True,
        route_path='direct_ops_domain_plan',
    )
    return router_result_to_route_decision(result, route_track=TRACK_A, task_type='data_query')


def _ops_month_entities(message: str) -> dict:
    text = message or ''
    entities: dict = {}
    match = re.search(r'(\d{4})[-年/](\d{1,2})', text)
    if match:
        entities['month'] = f'{match.group(1)}-{int(match.group(2)):02d}'
    return entities


from services.hrm_module_catalog import all_module_specs, assistant_nav_module_plans


_NAV_MODULE_PLANS = assistant_nav_module_plans(RISK_HIGH)


_MODULE_CATALOG_FLOW_HINTS = {
    'recruit_to_onboard': r'(招聘到入职|招聘.*入职|录用.*入职|Offer.*入职)',
    'employee_lifecycle': r'(员工生命周期|入职.*转正.*离职|员工.*异动|员工.*合同)',
    'attendance_to_payroll': r'(考勤到薪酬|考勤.*薪酬|考勤.*工资|请假.*工资|加班.*工资)',
    'performance_to_growth': r'(绩效与成长|绩效.*培训|培训.*绩效|学习.*绩效)',
    'workflow_governance': r'(审批与治理|审批.*通知|审批.*日志|反馈.*通知)',
}


def _module_catalog_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    text = message or ''
    if decision.task_type in {'action', 'forbidden'}:
        return None

    normalized = re.sub(r'\s+', '', text)
    asks_catalog = bool(re.search(
        r'(有哪些模块|哪些模块|模块清单|模块目录|系统模块|HRM\s*模块|hrm\s*模块|'
        r'功能清单|功能模块|菜单结构|业务链路|上下游|连通|串联|开源|对标)',
        text,
        re.I,
    ))
    if not asks_catalog:
        return None

    named_person_flow = bool(
        re.search(r'[\u4e00-\u9fa5]{2,4}', text)
        and re.search(r'(候选人|员工|Offer|offer|入职|转正|异动|离职|合同|考勤|请假|加班|薪资|工资|绩效|培训|审批)', text, re.I)
        and re.search(r'(关联|链路|流程|进展|进度|状态|情况|详情|哪些模块|哪个模块)', text, re.I)
    )
    if named_person_flow and not re.search(r'(系统|菜单|模块清单|模块目录|功能清单|功能模块|开源|对标|架构)', text, re.I):
        return None

    module_id: Optional[str] = None
    for spec in all_module_specs():
        labels = [spec.label, *spec.aliases]
        if any(re.sub(r'\s+', '', label) in normalized for label in labels):
            module_id = spec.id
            break

    view = 'overview'
    tool_input = {'module': 'module_catalog', 'view': view}
    if module_id and re.search(r'(上下游|连通|串联|关联|关系|怎么.*通|如何.*通|链路|流程|前后)', text):
        tool_input = {'module': 'module_catalog', 'view': 'module', 'module_id': module_id}
    else:
        for flow_id, pattern in _MODULE_CATALOG_FLOW_HINTS.items():
            if re.search(pattern, text, re.I):
                tool_input = {'module': 'module_catalog', 'view': 'flow', 'flow_id': flow_id}
                break

    return RouteDecision(
        task_type='data_query',
        route_track=TRACK_A,
        intent='system_module_catalog',
        confidence=max(decision.confidence, 0.92),
        risk_level=RISK_LOW,
        tool_plan=[
            ToolCallPlan(
                step_id='module_catalog_query',
                tool='system_search',
                purpose='query',
                input=tool_input,
                required=True,
                risk_level=RISK_LOW,
                cache_policy='session',
            ),
        ],
        requires_confirmation=False,
        reason='direct_module_catalog_plan',
    )


def _nav_module_match(message: str) -> Optional[dict]:
    text = message or ''
    normalized = re.sub(r'\s+', '', text)
    for spec in _NAV_MODULE_PLANS:
        for label in spec['labels']:
            if re.sub(r'\s+', '', label) in normalized:
                return spec
    return None


def _is_nav_module_data_query(message: str) -> bool:
    text = message or ''
    return bool(re.search(
        r'(查|查询|搜索|列出|查看|看看|看一下|看下|打开|帮我看|帮我找|找|找一下|有哪些|有没有|'
        r'多少|几个|几位|几名|几份|几条|几场|数量|总数|数一下|本月|这个月|近\s*\d+|最近|今天|'
        r'今日|本周|这周|待处理|待办|未完成|已完成|完成状态|完成情况|历史|情况|相关|需要关注|'
        r'按状态|状态分布|分布|按部门|部门|详情|明细|报表|概览|趋势|排名|TOP\s*\d*|排序|异常|'
        r'风险|筛选|帮我筛|筛|过滤|看板|指标|统计|数据|记录|列表)',
        text,
        re.I,
    ))


def _direct_nav_module_plan(message: str, decision: RouteDecision, ctx: AssistantContext) -> Optional[RouteDecision]:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    if decision.route_track == TRACK_COMPOSITE or decision.task_type in {'action', 'forbidden'}:
        return None
    if _is_direct_dialogue_boundary(text) or not _is_nav_module_data_query(text):
        return None
    spec = _nav_module_match(text)
    if not spec:
        return None
    if (
        spec.get('tool') == 'attendance_analysis'
        and _is_employee_lifecycle_query(text)
        and not re.search(r'(请假[/／]加班[/／]出差[/／]补卡|考勤记录|考勤统计)', re.sub(r'\s+', '', text))
    ):
        return None
    tool = spec['tool']
    params = dict(spec.get('input') or {})
    params.setdefault('limit', _extract_recruitment_limit(text) or 10)
    if tool == 'recruitment_search':
        keyword = _extract_recruitment_keyword(text, params.get('module') or 'all')
        if keyword:
            params['keyword'] = keyword
        status = _infer_recruitment_status(text, params.get('module') or 'all')
        if status:
            params['status'] = status
        date_range = _extract_recruitment_date_range(text)
        if date_range:
            params['date_range'] = date_range
        if re.search(r'(多少|几个|几位|几名|几份|几条|几场|数量|总数)', text):
            params['count_only'] = True
    elif tool == 'approval_search':
        params.setdefault('view', 'pending')
    elif tool == 'dashboard_report':
        params.setdefault('scope', 'system')
    elif tool == 'employee_search':
        keyword = _extract_employee_keyword(text)
        if keyword:
            params['keyword'] = keyword
        status = _infer_employee_status(text)
        if status:
            params['status'] = status
    elif tool == 'organization_search':
        keyword = _extract_org_keyword(text)
        if keyword:
            params['keyword'] = keyword
    elif tool == 'system_search':
        params.setdefault('limit', 12)
        if params.get('module') == 'lifecycle':
            keyword = _extract_lifecycle_keyword(text)
            if keyword:
                params['keyword'] = keyword

    risk = spec.get('risk') or (RISK_HIGH if tool == 'payroll_analysis' else RISK_LOW)
    return RouteDecision(
        task_type='data_query',
        route_track=TRACK_A,
        intent=spec['intent'],
        confidence=max(decision.confidence, 0.9),
        risk_level=risk,
        tool_plan=[
            ToolCallPlan(
                step_id=f'{tool}_nav_query',
                tool=tool,
                purpose='query',
                input=params,
                required=True,
                risk_level=risk,
                cache_policy='session',
            ),
        ],
        requires_confirmation=False,
        reason='direct_nav_module_plan',
    )


def _direct_ops_domain_plan(message: str, decision: RouteDecision, ctx: AssistantContext) -> Optional[RouteDecision]:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    if not text or decision.task_type in {'action', 'forbidden'} or decision.route_track == TRACK_COMPOSITE:
        return None
    if _is_direct_dialogue_boundary(text):
        return None
    if decision.route_track == TRACK_B and decision.intent in {'candidate_job_fit', 'interview_questions'}:
        return None
    if decision.route_track == TRACK_B and decision.intent in {'person_evidence_answer', 'person_assessment'}:
        if re.search(r'(候选人|简历|面试|复试|Offer|offer|录用|胜任|匹配|适合|风险|亮点|短板)', text, re.I):
            return None
    if decision.route_track == TRACK_B and set(decision.required_context or {}).intersection(
        {'candidate_workset', 'entity_workset', 'named_subjects_evidence'}
    ):
        return None
    if re.search(r'(候选人|简历|Offer|offer|复试|面试反馈|面试官反馈|招聘需求|招聘岗位|等待反馈|待审批\s*Offer|Offer\s*审批)', text, re.I):
        if not re.search(r'(招聘报表|招聘概览|招聘进展|招聘情况)', text):
            return None
    if re.search(r'(入职培训|转正审批|请假申请记录|员工申请|调岗申请|合同台账|离职审批)', text):
        return None
    if decision.intent == 'workset_analysis' and re.search(r'(这些|这批|这几个|上面|刚才|上一轮|上一批|名单里|结果里|列表里|表格里)', text):
        return None
    if re.search(r'(生成|写|起草|输出|整理).{0,24}(面试题|邮件|文案|话术|方案|建议)', text):
        return None

    if _is_payroll_query(text) and not _is_employee_lifecycle_query(text):
        if ctx.role not in PAYROLL_AUTHORIZED_ROLES:
            decision = _ops_router_result(
                intent='payroll_month_summary',
                skills=['payroll_analysis'],
                confidence=max(decision.confidence, 0.9),
                risk=RISK_HIGH,
                entities=_ops_month_entities(text),
                reason=f'direct_ops_domain_plan:payroll_permission_boundary:{ctx.role}',
            )
            if decision.router_result is not None:
                decision.router_result.route_path = 'fast_path'
            return decision
        if getattr(decision, 'risk_level', 'low') == RISK_HIGH and getattr(decision, 'intent', '') == 'payroll_month_summary':
            return None
        if getattr(decision, 'risk_level', 'low') == RISK_HIGH and os.getenv('ASSISTANT_FORCE_DIRECT_PAYROLL_PLAN') != '1':
            return None
        return _ops_router_result(
            intent='payroll_month_summary',
            skills=['payroll_analysis'],
            confidence=0.9,
            risk=RISK_HIGH,
            entities=_ops_month_entities(text),
            reason='direct_ops_domain_plan:payroll',
        )

    if re.search(r'(绩效|考核|评分等级|等级分布|等级员工|考核等级|绩效评分|绩效排名|绩效校准|A\s*等级)', text):
        return _ops_router_result(
            intent='performance_distribution_report',
            skills=['performance_analysis', 'employee_search'],
            confidence=0.88,
            reason='direct_ops_domain_plan:performance',
        )

    if re.search(r'(待我审批|待审批|审批记录|审批历史|审批待处理|审批列表|审批到哪一步|审批事项|审批统计|审批通过率|提交的审批|待审批任务|审批中心待办|我的申请|被驳回的申请)', text):
        view = 'pending'
        if re.search(r'(我的申请|我提交)', text):
            view = 'mine'
        elif '历史' in text:
            view = 'history'
        return _ops_router_result(
            intent='approval_pending_summary',
            skills=['approval_search'],
            confidence=0.88,
            entities={'view': view},
            reason='direct_ops_domain_plan:approval',
        )

    if re.search(r'(培训|课程|培训计划|完成率|通过率|学习进度|培训成绩|课程反馈)', text) and not _is_employee_lifecycle_query(text):
        return _ops_router_result(
            intent='training_completion_report',
            skills=['training_analysis', 'employee_search'],
            confidence=0.87,
            reason='direct_ops_domain_plan:training',
        )

    if re.search(r'(考勤|迟到|缺卡|早退|请假|加班|出差|补卡)', text):
        if _is_employee_lifecycle_query(text):
            return None
        return _ops_router_result(
            intent='attendance_exception_analysis',
            skills=['attendance_analysis', 'employee_search'],
            confidence=0.88,
            entities=_ops_month_entities(text),
            reason='direct_ops_domain_plan:attendance',
        )

    if re.search(r'(反馈|bug|缺陷|需求|已修复|已采纳)', text, re.I):
        entities: dict = {}
        if re.search(r'bug|缺陷', text, re.I):
            entities['feedback_type'] = 'bug'
        elif '需求' in text:
            entities['feedback_type'] = 'feature'
        if re.search(r'(待处理|没处理|未处理)', text):
            entities['status'] = 'pending'
        return _ops_router_result(
            intent='feedback_triage_summary',
            skills=['feedback_triage'],
            confidence=0.87,
            entities=entities,
            reason='direct_ops_domain_plan:feedback',
        )

    if re.search(r'(招聘报表|招聘概览|招聘进展|招聘情况)', text):
        return _ops_router_result(
            intent='recruitment_overview',
            skills=['dashboard_report', 'recruitment_search', 'resume_analysis'],
            confidence=0.86,
            entities={'recent_days': 7} if '本周' in text else {},
            reason='direct_ops_domain_plan:recruitment_report',
        )

    if re.search(r'(系统概览|总览|整体情况|系统情况|做个报表|人力资源运营报表|HR\s*数据看板|管理驾驶舱|仪表盘指标)', text, re.I):
        return _ops_router_result(
            intent='system_dashboard',
            skills=['dashboard_report'],
            confidence=0.86,
            reason='direct_ops_domain_plan:dashboard',
        )

    return None


def _extract_chinese_person_name(text: str) -> Optional[str]:
    if not text:
        return None
    prefix_match = re.match(r'^\s*([\u4e00-\u9fa5·]{2})(?:从|由|在|是|属|现|的|什|试|最)', text)
    if prefix_match:
        name = prefix_match.group(1)
        if name not in {'员工', '部门', '岗位', '职位', '合同', '入职', '离职', '转正', '试用'}:
            return name
    patterns = [
        r'(?:查一下|查看|看一下|搜索|帮我找一下|帮我查一下)?\s*(?:HRBP|销售经理|研发部|技术部|市场部|财务部|客服部)?\s*([\u4e00-\u9fa5·]{2,4})(?:的)?(?:员工档案|员工信息|员工资料|员工编号|工号|入职时间|入职日期|岗位信息|岗位|职位|部门|合同情况|合同编号|转正状态|离职原因|离职审批)',
        r'^([\u4e00-\u9fa5·]{2,4})(?:在哪个部门|属于哪个部门|是什么岗位|的岗位是什么|什么时候入职|什么时候转正)',
        r'^([\u4e00-\u9fa5·]{2,4})(?:从|由).{0,12}(?:候选人|简历|Offer|offer|录用).{0,12}(?:入职|员工|转员工)',
        r'员工\s*([\u4e00-\u9fa5·]{2,4})(?:资料|信息|档案)?',
        r'([\u4e00-\u9fa5·]{2,4})的请假申请',
        r'(?:查一下|查看|看一下|搜索|帮我找一下|帮我查一下)?\s*(?:HRBP|销售经理|研发部|技术部|市场部|财务部|客服部)?\s*([\u4e00-\u9fa5·]{2,4})(?:属于|现在|是不是|什么时候|在哪个|是什么)',
        r'^([\u4e00-\u9fa5·]{2,4})(?:最近有没有|试用期|入职|离职|转正|合同)',
    ]
    stop = {
        '员工', '部门', '岗位', '职位', '组织', '架构', '名单', '列表', '档案',
        '信息', '资料', '合同', '入职', '离职', '转正', '试用期', '正式员工',
    }
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = match.group(1).strip()
        name = re.sub(r'^(?:一下|查看|看一下|查一下|搜索|经理|研发部|技术部|市场部|财务部|客服部)+', '', name)
        name = re.sub(r'(资料|信息|档案)$', '', name)
        name = name.strip(' 的')
        if name and name not in stop and not name.endswith(('员工', '部门', '岗位', '职位', '试用期')):
            return name
    return None


def _extract_employee_keyword(message: str) -> Optional[str]:
    text = message or ''
    if re.search(r'我的员工档案|我的档案|我自己的员工信息', text):
        return None
    email = re.search(r'[\w.\-+]+@[\w.\-]+\.\w+', text)
    if email:
        return email.group(0)
    phone = re.search(r'1[3-9]\d{9}', text)
    if phone:
        return phone.group(0)
    emp_no = re.search(r'\b[A-Za-z]{1,6}\d{2,8}\b', text)
    if emp_no:
        return emp_no.group(0)
    return _extract_chinese_person_name(text)


def _infer_employee_status(message: str) -> Optional[str]:
    text = message or ''
    if re.search(r'(待入职|还没正式入职|pending_onboard)', text, re.I):
        return 'pending_onboard'
    if re.search(r'(试用期|probation)', text, re.I):
        return 'probation'
    if re.search(r'(已离职|离职状态|resigned)', text, re.I):
        return 'resigned'
    if re.search(r'(暂停|停用|inactive)', text, re.I):
        return 'inactive'
    if re.search(r'(在职|正式员工|active)', text, re.I):
        return 'active'
    return None


def _extract_org_keyword(message: str) -> Optional[str]:
    text = message or ''
    for pattern in (
        r'(?:查一下|查看|看一下)?\s*([\u4e00-\u9fa5A-Za-z0-9]+部)(?:有多少人|有哪些人|人员分布|负责人|下面|有哪些岗位|$)',
        r'([\u4e00-\u9fa5A-Za-z0-9]+中心)(?:下面|有多少人|有哪些部门|$)',
        r'部门编码\s*([A-Za-z0-9_-]+)',
        r'([\u4e00-\u9fa5A-Za-z0-9]+经理)(?:属于哪个岗位序列)',
        r'([\u4e00-\u9fa5A-Za-z0-9]+)级岗位',
        r'([\u4e00-\u9fa5A-Za-z0-9]+岗位体系)',
    ):
        match = re.search(pattern, text)
        if match:
            keyword = match.group(1).strip()
            return keyword.replace('岗位体系', '') or keyword
    return None


def _extract_lifecycle_keyword(message: str) -> Optional[str]:
    return _extract_chinese_person_name(message or '')


def _needs_all_lifecycle_modules(message: str) -> bool:
    text = message or ''
    if re.search(r'(关联模块|哪些模块|哪个模块|全链路|完整链路|跨模块)', text, re.I):
        return True
    if re.search(r'(从)?(?:候选人|简历|简历录入|录入|投递).{0,24}(?:入职|员工|转员工|培训|薪酬|薪资|工资|发薪|合同|离职)', text, re.I):
        return True
    topic_hits = sum(
        1 for pattern in (
            r'转正|试用期',
            r'培训',
            r'调薪|薪酬|薪资|工资|发薪',
            r'绩效',
            r'合同',
            r'离职',
        )
        if re.search(pattern, text, re.I)
    )
    return bool(re.search(r'(链路|有哪些数据|关联记录|完整)', text, re.I) and topic_hits >= 2)


def _is_direct_dialogue_boundary(message: str) -> bool:
    text = message or ''
    if (
        re.search(r'[\u4e00-\u9fa5·]{2,4}', text)
        and re.search(r'(面试题|面试问题|复试问题|终面问题|技术面试题|行为面试题|结构化面试题|追问|出题)', text)
    ):
        return False
    if re.search(r'(润色|翻译|总结|摘要|提炼|改写|写得更).{0,24}[：:]', text):
        return True
    if re.search(r'(请把|帮我把|把).{0,24}(说明|这段|这句|内容|通知|邮件|话术).{0,30}(改成|改为|改写|写成|写得更)', text):
        return True
    if re.search(r'^(什么是|什么叫|请解释|解释一下|帮我解释|怎么理解|如何理解)', text):
        return True
    if re.search(r'(模块通常做什么|通常做什么|有什么关系|业务含义|怎么理解|如何理解)', text):
        return True
    if re.search(r'(是什么意思|有什么区别|的区别|的含义|的作用).{0,20}[？?]?$', text):
        return True
    if re.search(r'^(如何|怎样|怎么).{0,50}(写|设计|组织|回复|解释|总结|避免|表达|沟通|说明|提问|复盘|开展|制定|整理).{0,60}[？?]?$', text):
        return True
    if re.search(r'(应该|需要|可以|怎样|如何|怎么).{0,24}(表达|写|沟通|说明|解释|组织|总结|复盘).{0,40}[？?]?$', text):
        return True
    if re.search(r'(通常|一般|应该|需要).{0,24}(包含|包括|注意什么|避免|怎么做|如何做|怎么沟通).{0,40}[？?]?$', text):
        return True
    if re.search(
        r'(你|聘小犀|AI\s*助手).{0,12}(会不会|能不能|能否|可以|会|能).{0,24}'
        r'(自动)?(发送|群发|创建|新建|修改|删除|审批|执行|操作).{0,16}(吗|么|？|\?)$',
        text,
        re.I,
    ):
        return True
    return False


def _is_employee_lifecycle_query(message: str) -> bool:
    text = message or ''
    if _is_direct_dialogue_boundary(text) or re.search(r'^(如何组织|如何设计)', text):
        return False
    lifecycle_domain_terms = (
        r'候选人|简历|Offer|offer|录用|入职|转正|试用期|离职|合同|异动|调岗|调薪|'
        r'请假|加班|出差|补卡|审批|培训|绩效|薪酬|薪资|工资'
    )
    if (
        re.search(r'[\u4e00-\u9fa5·]{2,4}', text)
        and re.search(lifecycle_domain_terms, text, re.I)
        and re.search(r'(链路|关联|关联到|关联了|哪些模块|哪个模块|全链路|流程|流转|贯通|打通|现在有哪些数据|有哪些数据)', text, re.I)
    ):
        return True
    if re.search(
        r'(从)?(?:候选人|简历|简历录入|录入|投递).{0,24}(?:入职|员工|转员工|培训|薪酬|薪资|工资|发薪|合同)',
        text,
        re.I,
    ):
        return True
    lifecycle_terms = (
        r'入职进度|入职任务|入职清单|入职资料|待入职人员|入职培训|入职审批|本周入职员工进度|'
        r'候选人.*入职|候选人.*员工|简历.*入职|简历.*员工|Offer.*入职|offer.*入职|录用.*入职|转员工|'
        r'快到转正|转正审批|转正状态|试用期.*(结束|到期)|转正未通过|'
        r'离职员工|最近离职|离职交接|离职原因|离职审批|离职人员|'
        r'合同快到期|劳动合同|合同情况|合同编号|合同待续签|合同台账|无固定期限合同|'
        r'员工异动|调岗|调薪|调薪异动|员工申请|请假申请|请假申请记录|调岗申请'
    )
    return bool(re.search(lifecycle_terms, text))


def _is_org_query(message: str) -> bool:
    text = message or ''
    if _is_direct_dialogue_boundary(text):
        return False
    return bool(
        re.search(r'(组织架构|部门列表|有哪些部门|部门有哪些人|部门人数|人员分布|组织单元|各部门人数|岗位体系|岗位序列|职位体系)', text)
        or re.search(r'[\u4e00-\u9fa5A-Za-z0-9]+部(?:有多少人|有哪些人|人员分布|负责人|下面有哪些部门|有哪些岗位|$)', text)
        or re.search(r'(部门编码|属于哪个岗位序列|主管级岗位)', text)
    )


def _is_employee_profile_query(message: str) -> bool:
    text = message or ''
    if _is_direct_dialogue_boundary(text) or re.search(r'^(如何组织|如何设计)', text):
        return False
    if _is_employee_lifecycle_query(text) or _is_org_query(text):
        return False
    if re.search(r'(薪酬|薪资|工资|工资条|社保|个税)', text):
        return False
    if re.search(r'(Java|java|C\+\+|Python|前端|后端).{0,12}(工程师|岗位|职位)', text):
        return False
    if re.search(r'(发布|新增|在招|招聘|开放|关闭|暂停).{0,12}(岗位|职位)', text):
        return False
    if re.search(r'(北京|上海|深圳|广州|杭州|成都|武汉|南京|苏州|远程|异地|地区).{0,8}(岗位|职位)', text):
        return False
    if re.search(r'(招聘|在招|缺人|开放中|关闭|已暂停).{0,12}(岗位|职位)|'
                 r'(岗位|职位).{0,8}(候选人|Offer|offer|在招|招聘|缺人|还有吗|详情)|'
                 r'(工程师|经理|专员|顾问).{0,4}(岗位|职位)(?:详情|还有吗|$)', text, re.I):
        return False
    if re.search(r'(匹配|适配|胜任|符合|满足|适合|岗位匹配|岗位要求|任职资格|面试题|追问|比较|对比|哪个更|谁更)', text):
        return False
    if re.search(r'(这些|这批|这几个|上面|刚才|上一轮|上一批|那批|名单里|结果里|每位|每个)', text):
        return False
    return bool(
        re.search(r'(员工档案|员工信息|员工资料|员工编号|员工花名册|员工列表|工号|入职时间|入职日期|在哪个部门|属于哪个部门|什么岗位|岗位是什么|什么职位|现在什么职位|部门和岗位|是不是在职)', text)
        or re.search(r'(查|查询|搜索|列出|查看|看看|看一下|找|找一下).{0,20}(员工|在职|正式员工|试用期|待入职|resigned|inactive)', text, re.I)
        or re.search(r'(在职员工|正式员工|当前员工|试用期员工|待入职员工|员工状态为已离职|resigned 状态员工|暂停状态员工)', text, re.I)
        or bool(_extract_employee_keyword(text) and re.search(r'(员工|部门|岗位|职位|入职|工号|编号|在职)', text))
    )


def _direct_employee_org_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    if decision.route_track == TRACK_COMPOSITE or decision.task_type in {'action', 'forbidden'}:
        return None
    if _is_direct_dialogue_boundary(text):
        return None
    if decision.route_track == TRACK_B and (
        decision.intent == 'workset_analysis'
        or set(decision.required_context or {}).intersection(
            {'latest_workset', 'candidate_workset', 'entity_workset', 'workset'}
        )
    ):
        return None
    if re.search(r'(生成|写|起草|输出|整理).{0,24}(报告|方案|建议|面试题|邮件|文案|话术|总结|分析)', text):
        return None
    if re.search(r'(薪酬|薪资|工资|工资条|社保|个税)', text) and not _is_employee_lifecycle_query(text):
        return None
    if _is_org_query(text):
        params = {'include_stats': True}
        keyword = _extract_org_keyword(text)
        if keyword:
            params['keyword'] = keyword
        decision.task_type = 'data_query'
        decision.route_track = TRACK_A
        decision.intent = 'organization_overview'
        decision.confidence = max(decision.confidence, 0.88)
        decision.task_template_id = None
        decision.router_result = None
        decision.required_context = []
        decision.generation_plan = None
        decision.requires_confirmation = False
        decision.tool_plan = [
            ToolCallPlan(
                step_id='organization_search',
                tool='organization_search',
                purpose='query',
                input=params,
                required=True,
                risk_level='low',
                cache_policy='session',
            ),
        ]
        decision.reason = 'direct_employee_org_plan'
        return decision
    if _is_employee_lifecycle_query(text):
        module = 'all' if _needs_all_lifecycle_modules(text) else 'lifecycle'
        params = {'module': module, 'limit': 12}
        keyword = _extract_lifecycle_keyword(text)
        if keyword:
            params['keyword'] = keyword
        decision.task_type = 'data_query'
        decision.route_track = TRACK_A
        decision.intent = 'employee_lifecycle_query'
        decision.confidence = max(decision.confidence, 0.88)
        decision.task_template_id = None
        decision.router_result = None
        decision.required_context = []
        decision.generation_plan = None
        decision.requires_confirmation = False
        decision.tool_plan = [
            ToolCallPlan(
                step_id='employee_lifecycle_search',
                tool='system_search',
                purpose='query',
                input=params,
                required=True,
                risk_level='low',
                cache_policy='session',
            ),
        ]
        decision.reason = 'direct_employee_org_plan'
        return decision
    if _is_employee_profile_query(text):
        params = {'limit': 10}
        keyword = _extract_employee_keyword(text)
        if keyword:
            params['keyword'] = keyword
        status = _infer_employee_status(text)
        if status:
            params['status'] = status
        decision.task_type = 'data_query'
        decision.route_track = TRACK_A
        decision.intent = 'employee_lookup'
        decision.confidence = max(decision.confidence, 0.88)
        decision.task_template_id = None
        decision.router_result = None
        decision.required_context = []
        decision.generation_plan = None
        decision.requires_confirmation = False
        decision.tool_plan = [
            ToolCallPlan(
                step_id='employee_search',
                tool='employee_search',
                purpose='query',
                input=params,
                required=True,
                risk_level='low',
                cache_policy='session',
            ),
        ]
        decision.reason = 'direct_employee_org_plan'
        return decision
    return None


def _infer_recruitment_module(message: str) -> Optional[str]:
    text = message or ''
    if re.search(r'(offer|Offer|录用通知|录用进度|录用记录)', text):
        return 'offers'
    if (
        re.search(r'(面试|复试|一面|二面|三面|终面|面评)', text)
        and '面试题' not in text
        and not re.search(r'(面试中|待面试).{0,6}候选人', text)
    ):
        return 'interviews'
    if re.search(r'(简历|投递记录|投递)', text):
        if '候选人' in text and '简历' not in text and '投递记录' not in text:
            return 'candidates'
        return 'resumes'
    if re.search(r'(候选人|应聘者|应聘的人|来应聘的人|来应聘|应聘.+的人|候选人库)', text):
        return 'candidates'
    if re.search(r'(岗位|职位|JD|jd|招聘需求|在招|招人|招什么|缺人)', text, re.IGNORECASE):
        return 'jobs'
    return None


def _is_plain_recruitment_lookup(message: str, module: Optional[str]) -> bool:
    if not module:
        return False
    text = message or ''
    if re.search(r'^\s*(什么是|什么叫|请解释|解释一下|帮我解释|怎么理解|如何理解)', text):
        return False
    if re.search(r'^\s*(如何|怎样|怎么).*(写|设计|组织|回复|解释|总结|避免|表达|沟通|说明|提问|复盘|开展|制定|整理)', text):
        return False
    if re.search(r'(通常|一般|应该|需要|如何|怎么|怎样).{0,30}(包含|包括|避免|写|表达|说明|信息|表述)', text):
        return False
    if re.search(r'(邮件|文案|话术|表述|措辞|说明|JD|jd).{0,30}(通常|一般|包含|包括|应该|避免|如何|怎么|哪些)', text):
        return False
    if re.search(r'(润色|翻译|总结|摘要|提炼).{0,24}[：:]', text):
        return False
    if re.search(r'(待评估|待评价).{0,8}(简历|面试|候选人)', text):
        return True
    if re.search(r'(推荐状态|状态).{0,8}候选人|候选人.{0,8}(推荐状态|状态)', text):
        return True
    if re.search(r'(删除|移除|审批通过|批准|驳回|发送|群发|发邮件|导入|更新|修改|写入)', text):
        return False
    if re.search(r'(安排|创建|新建).{0,24}(面试|复试|跟进|任务|提醒)', text):
        return False
    if re.search(r'(生成|写|起草|设计).{0,24}(面试题|邮件|文案|话术|报告|方案|建议|JD|jd)', text, re.IGNORECASE):
        return False
    if re.search(r'(分析|评价|评估|推荐|排序|对比|比较).{0,40}(候选人|简历|岗位|面试|Offer|offer)', text):
        if not re.search(r'(列表|名单|记录|详情|状态|有哪些|有没有|查|搜索|列出|查看|看看|找|到哪一步|进度)', text):
            return False
    if re.search(r'(高分|评分|推荐).{0,12}(简历|候选人)|(简历|候选人).{0,12}(高分|评分|推荐)', text):
        if not re.search(r'(查|查询|搜索|列出|查看|看看|列表|名单|记录)', text):
            return False
    if re.search(r'[\u4e00-\u9fa5·]{2,8}的(?:简历|面试|复试|Offer|offer|投递记录|录用通知|录用进度)', text):
        return True
    if re.search(r'候选人\s*[\u4e00-\u9fa5·]{2,8}\s*(?:资料|详情|记录|信息)?$', text):
        return True
    return bool(re.search(
        r'(查|查询|搜索|列出|查看|看看|看一下|看下|找|找一下|有没有|还有吗|有哪些|哪些|'
        r'多少|几个|几位|几名|几份|几条|几场|数量|总数|名单|列表|详情|记录|安排|日程|排期|'
        r'到哪一步|进度|状态|库里|本周|本月|最近|近\s*\d+|今天|明天|后天|待|已|开放|在招|招人|招聘中|'
        r'缺人|收到|投递|应聘|发布)',
        text,
        re.IGNORECASE,
    ))


def _clean_recruitment_keyword(raw: str, module: str) -> str:
    text = raw or ''
    text = re.sub(r'^\s*(帮我|请|麻烦|能否|可以)?\s*', '', text)
    text = re.sub(r'(查一下|查查|查询|搜索|列出|查看|看看|看一下|看下|找一下|找|有没有|还有吗|给我|一下|库里)', ' ', text)
    text = re.sub(r'(我们|咱们|公司|系统|当前|目前|现有|统计|汇总|实时|最近|近\s*\d+\s*天|本周|本月|今天|明天|上午|下午|晚上|现在|当前|系统里|系统中|库里|里面)', ' ', text)
    text = re.sub(r'(当前)?状态为|状态是|状态为|处于|总数', ' ', text)
    text = re.sub(r'(有哪些|哪些|哪几个|哪几类)', ' ', text)
    text = re.sub(r'(\d+)\s*(个|名|位|份|条|场)', ' ', text)
    text = re.sub(r'(有多少|多少|几个|几位|几名|几份|几条|几场|数量|总数)', ' ', text)
    text = re.sub(r'(开放中|在招人|正在招人|在招|招聘中|正在招聘|正招聘|招聘的|已关闭|关闭|暂停|停止|待发|待审批|已接受|已拒绝|已撤回|还没确认|'
                  r'待沟通|等待反馈|推荐状态|面试中|已淘汰|通过初筛|待筛选|待评估|待评价|待面试|已完成|取消|已取消|pending)', ' ', text, flags=re.I)
    module_words = {
        'jobs': r'(岗位|职位|招聘需求|JD|jd|缺人|发布|招什么|在招|招人|岗)',
        'resumes': r'(简历|投递记录|投递到|投递|收到|高分|初筛|记录|列表|名单|岗)',
        'candidates': r'(候选人|应聘者|应聘|来应聘|这个|有哪些人|哪些人|的人|人|名单|列表|资料|记录|状态)',
        'interviews': r'(面试记录|面试安排|面试日程|面试排期|面试|复试|一面|二面|三面|终面|记录|安排|日程|排期|到哪一步|评价|岗)',
        'offers': r'(Offer|offer|录用通知|录用进度|录用记录|录用|审批|到哪一步|记录|列表|发出)',
    }
    text = re.sub(module_words.get(module, ''), ' ', text, flags=re.I)
    text = text.replace('地区', ' ')
    text = re.sub(r'岗(?=$|的|有|还有|都|哪些)', ' ', text)
    text = re.sub(r'[，,。？?！!\s]+', ' ', text).strip(' 的')
    generic = {
        '招聘', '岗位', '职位', '候选人', '简历', '面试', 'Offer', 'offer', '记录', '列表', '名单', '详情',
        '正 聘', '正在 招聘', '招聘 中', '统计 正 聘', '当前 招聘', '状态为',
    }
    return '' if text in generic else text[:30]


def _clean_person_keyword(value: str) -> str:
    text = re.sub(r'^(?:帮我|请|查一下|查查|查询|搜索|查看|看看|看一下|找一下|找|有没有|候选人|库里)+', '', value or '')
    text = re.sub(r'(?:这个|这个候选人|这位候选人|候选人|资料|详情|记录|面试|复试|到哪一步)$', '', text)
    return text.strip(' 的，,。?？')[:20]


def _extract_recruitment_keyword(message: str, module: str) -> Optional[str]:
    text = message or ''

    if re.search(r'Java|java', text):
        return 'Java'
    if re.search(r'C\+\+', text):
        return 'C++'

    if re.search(r'(JD|jd|详情)', text):
        detail_title = re.search(
            r'([\u4e00-\u9fa5A-Za-z0-9+#.\- ]{2,24}?(?:工程师|经理|专员|顾问|开发|设计师|会计|出纳|HRBP|hrbp))'
            r'\s*(?:JD|jd|详情)',
            text,
            re.IGNORECASE,
        )
        if detail_title:
            keyword = _clean_recruitment_keyword(detail_title.group(1), module)
            if keyword:
                return keyword

    for token in ('电子工程师', '产品经理', '销售顾问', '运营专员', '前端', '后端', '测试', '销售', '上海', '深圳', 'HR'):
        if token in text:
            return token

    product_job = re.search(r'产品\s*岗', text)
    if product_job:
        return '产品'

    if re.search(r'算法\s*岗', text):
        return '算法'

    person_patterns = [
        r'(?:搜索|查看|查一下)?候选人\s*([\u4e00-\u9fa5·]{2,8}?)(?:的录用通知|录用通知|的录用进度|录用进度)',
        r'(?:搜索|查看|查一下)?候选人\s*([\u4e00-\u9fa5·]{2,8}?)(?:的简历|简历|的面试|面试|资料|记录|$)',
        r'候选人\s*([\u4e00-\u9fa5·]{2,8}?)(?:面试|复试|Offer|offer|录用|$)',
        r'([\u4e00-\u9fa5·]{2,8})的(?:简历|面试|复试|Offer|offer|投递记录|录用通知|录用进度)',
        r'(?:候选人|搜索候选人|查看候选人|查一下候选人)\s*([\u4e00-\u9fa5·]{2,8})(?:资料|记录|面试|的|$)',
        r'候选人\s*([\u4e00-\u9fa5·]{2,8})(?:资料|详情|记录|信息)?$',
        r'([\u4e00-\u9fa5·]{2,8})(?:这个候选人|这位候选人|候选人|的录用进度)',
    ]
    for pattern in person_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = _clean_person_keyword(match.group(1))
            if name not in {'候选人', '岗位', '职位', '简历', '面试', '最近', '本月'}:
                return name

    title_patterns = [
        r'([A-Za-z0-9+#.\-\u4e00-\u9fa5 ]{0,24}?(?:工程师|经理|专员|顾问|开发|设计师|会计|出纳|HRBP|hrbp))'
        r'(?:岗位|职位|岗|简历|候选人|面试|Offer|offer|的|$)',
        r'(?:应聘|投递(?:到)?|招聘需求里的)\s*([A-Za-z0-9+#.\-\u4e00-\u9fa5 ]{2,24}?)(?:的|的人|岗位|职位|岗|简历|候选人|$)',
        r'([A-Za-z0-9+#.\-\u4e00-\u9fa5 ]{2,24}?)(?:岗位|职位|岗)(?:的|有|还有|Offer|面试|候选人|简历|$)',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            keyword = _clean_recruitment_keyword(match.group(1), module)
            if keyword:
                return keyword

    for token in ('产品', '运营', '算法', '技术'):
        if token in text:
            return token

    keyword = _clean_recruitment_keyword(text, module)
    return keyword or None


def _infer_recruitment_status(message: str, module: str) -> Optional[str]:
    text = message or ''
    if module == 'jobs':
        if re.search(r'(开放|在招|招聘中|缺人)', text):
            return 'open'
        if re.search(r'(关闭|已关闭|暂停|停止)', text):
            return 'closed'
    if module == 'candidates':
        if re.search(r'(已淘汰|淘汰|不合适|已拒绝)', text):
            return 'rejected'
        if re.search(r'(面试中|面试阶段)', text):
            return 'interview'
        if re.search(r'(Offer中|offer中|录用中)', text):
            return 'offer'
        if re.search(r'(待沟通|等待反馈|通过初筛|筛选中|初筛)', text):
            return 'screening'
        if re.search(r'(推荐状态|推荐候选人)', text):
            return 'recommended'
        if re.search(r'(新候选人|新来的)', text):
            return 'new'
    if module == 'interviews':
        if re.search(r'(取消|已取消)', text):
            return 'cancelled'
        if re.search(r'(已完成|完成面试)', text):
            return 'completed'
        if re.search(r'(进行中)', text):
            return 'in_progress'
        if re.search(r'(待面试|已安排|安排|日程|排期|今天|明天|后天)', text):
            return 'scheduled'
        if re.search(r'(待评价)', text):
            return 'pending'
    if module == 'offers':
        if re.search(r'(已接受|接受)', text):
            return 'accepted'
        if re.search(r'(已拒绝|拒绝)', text):
            return 'rejected'
        if re.search(r'(已撤回|撤回|取消|已取消)', text):
            return 'cancelled'
        if re.search(r'(待发|待审批|待确认|还没确认|pending)', text, re.IGNORECASE):
            return 'pending'
    if module == 'resumes':
        if re.search(r'(待筛选|待评估)', text):
            return 'pending'
        if re.search(r'(通过初筛|已通过)', text):
            return 'screening'
        if re.search(r'(淘汰|被淘汰|不合适|拒绝)', text):
            return 'rejected'
    return None


def _is_recruitment_match_matrix_request(message: str) -> bool:
    text = message or ''
    if _has_workset_reference(text):
        return False
    if _has_explicit_named_subject_query(text) and not _has_job_candidate_pool_scope(text):
        return False
    if re.search(r'(员工|薪资|工资|绩效|考勤|异动|调岗|请假|审批)', text):
        return False
    if re.search(r'(推荐状态|状态).{0,8}候选人|候选人.{0,8}(推荐状态|状态)', text):
        return False
    has_candidate_pool_scope = _has_job_candidate_pool_scope(text)
    wants_match_matrix = bool(re.search(
        r'(更合适|最合适|谁合适|谁更|哪个更|哪位更|推荐|匹配|适配|胜任|对比|比较|矩阵|排序|排名|优先推进)',
        text,
    ))
    return has_candidate_pool_scope and wants_match_matrix


def _direct_recruitment_match_matrix_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    """Route explicit job-candidate matching asks to the evidence-backed matrix skill.

    These requests mention a concrete recruitment scope and ask for comparison,
    ranking, fit or a matrix. They are not follow-ups about an existing WorkSet;
    the first turn must create one from recruitment data before generation.
    """
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    if _has_named_subject_evidence_context(decision) and not _has_job_candidate_pool_scope(text):
        return None
    if not _is_recruitment_match_matrix_request(text):
        return None
    keyword = _extract_recruitment_keyword(text, 'jobs') or _extract_keyword(text)
    if not keyword:
        return None
    limit = _extract_recruitment_limit(text) or _parse_limit(text, default=8)
    decision.task_type = 'generation'
    decision.route_track = TRACK_B
    decision.intent = 'candidate_compare'
    decision.confidence = max(decision.confidence, 0.92)
    decision.risk_level = RISK_LOW
    decision.task_template_id = None
    decision.router_result = None
    decision.required_context = []
    decision.requires_confirmation = False
    decision.tool_plan = [
        ToolCallPlan(
            step_id='recruitment_match_matrix',
            tool='recruitment_match_matrix',
            purpose='load_context',
            input={'keyword': keyword, 'limit': max(1, min(limit, 12))},
            required=True,
            risk_level=RISK_LOW,
            cache_policy='session',
        ),
    ]
    decision.generation_plan = _generation_plan_for('candidate_compare', text)
    decision.reason = 'direct_recruitment_match_matrix_plan'
    return decision


def _direct_recruitment_query_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    """Stable direct plan for pure recruitment lookups across all submodules."""
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    text = message or ''
    progress_decision = _direct_recruitment_progress_plan(text, decision)
    if progress_decision is not None:
        return progress_decision
    module = _infer_recruitment_module(text)
    is_lookup = _is_plain_recruitment_lookup(text, module)
    explicit_lookup = bool(re.search(
        r'(查|查询|搜索|列出|查看|看看|看一下|看下|找|找一下|有没有|还有吗|有哪些|哪些|'
        r'多少|几个|几位|几名|几份|几条|几场|数量|总数|名单|列表|详情|状态|进度|到哪一步|待评估|待评价|推荐状态)',
        text,
        re.IGNORECASE,
    ))
    evidence_context = {
        'named_subject_evidence',
        'named_subjects_evidence',
        'latest_workset',
        'candidate_workset',
        'workset',
        'entity_workset',
    }
    if (
        decision.route_track == TRACK_B
        and evidence_context.intersection(set(decision.required_context or []))
        and not explicit_lookup
    ):
        return None
    if (
        decision.route_track == TRACK_B
        and {'latest_workset', 'candidate_workset', 'workset', 'entity_workset'}.intersection(set(decision.required_context or []))
    ):
        return None
    if (
        decision.route_track == TRACK_B
        and 'named_subject_evidence' in set(decision.required_context or [])
        and module in {'interviews', 'resumes'}
        and re.search(r'[\u4e00-\u9fa5·]{2,8}(?:有没有|的).*(面试记录|简历和面试记录|简历).*(怎么样)?$', text)
    ):
        return None
    if (
        decision.route_track == TRACK_B
        and {'named_subject_evidence', 'named_subjects_evidence'}.intersection(set(decision.required_context or []))
        and re.search(
            r'(风险|亮点|短板|优劣势|异常|说明了什么|为什么|证据|证据链|来源证据|推荐理由|'
            r'反馈.*风险|复试反馈|面评结论|面试官反馈|问题集中|是否提到|完整吗|薪资相关|'
            r'验证哪些点|面试时需要验证)',
            text,
        )
    ):
        return None
    if decision.task_type in ('action', 'composite'):
        return None
    if decision.task_type == 'forbidden':
        return None
    if not is_lookup:
        return None
    if re.search(r'(最近|近\s*\d+\s*天|本周|本月).*(投递|应聘).*(简历).*(候选人|几位|几名)', text):
        return None

    params = {
        'module': module,
        'limit': _extract_recruitment_limit(text) or (20 if _extract_recruitment_date_range(text) else 10),
    }
    if re.search(r'(多少|几个|几位|几名|几份|几条|几场|数量|总数)', text):
        params['count_only'] = True
    keyword = _extract_recruitment_keyword(text, module)
    if keyword:
        params['keyword'] = keyword
    status = _infer_recruitment_status(text, module)
    if status:
        params['status'] = status
    date_range = _extract_recruitment_date_range(text)
    if date_range:
        params['date_range'] = date_range

    decision.task_type = 'data_query'
    decision.route_track = TRACK_A
    decision.intent = f'recruitment_{module}_query'
    decision.confidence = max(decision.confidence, 0.88)
    decision.task_template_id = None
    decision.router_result = None
    decision.required_context = []
    decision.generation_plan = None
    decision.requires_confirmation = False
    decision.tool_plan = [
        ToolCallPlan(
            step_id=f'recruitment_{module}_search',
            tool='recruitment_search',
            purpose='query',
            input=params,
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
    ]
    decision.reason = 'direct_recruitment_query_plan'
    return decision


def _direct_recruitment_progress_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    text = message or ''
    if not re.search(r'招聘.{0,16}(怎么样|怎样|如何|进展|情况|推进|到哪|效果)', text):
        return None
    if re.search(r'(候选人|简历|这个人|这些人|这几个人|匹配度|适配度|胜任|合适|表现|评价|评估|分析|对比)', text):
        return None
    if decision.task_type in ('action', 'forbidden', 'composite'):
        return None
    keyword = _extract_recruitment_keyword(text, 'candidates') or _extract_recruitment_keyword(text, 'jobs')
    base = {'keyword': keyword} if keyword else {}
    decision.task_type = 'data_query'
    decision.route_track = TRACK_A
    decision.intent = 'recruitment_progress'
    decision.confidence = max(decision.confidence, 0.9)
    decision.task_template_id = None
    decision.router_result = None
    decision.required_context = []
    decision.generation_plan = None
    decision.requires_confirmation = False
    decision.tool_plan = [
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
    decision.reason = 'direct_recruitment_progress_plan'
    return decision


def _generation_plan_for(intent: str, message: str) -> GenerationPlan:
    profile = 'standard'
    max_tokens = 1200
    temperature = 0.5
    if intent in (
        'candidate_compare',
        'analysis_report',
        'candidate_assessment',
        'person_assessment',
        'person_evidence_answer',
        'candidate_job_fit',
    ):
        profile = 'strong' if feature_enabled('evidenceReasoning') else 'standard'
        max_tokens = 2200
        temperature = 0.35
    elif intent == 'interview_questions':
        max_tokens = 2600
    return GenerationPlan(
        template_id=intent,
        prompt_template='',
        output_format='markdown',
        model_profile=profile,
        max_tokens=max_tokens,
        temperature=temperature,
        constraints={'language': 'zh-CN', 'source': 'hybrid_planner'},
    )


def _direct_recent_recruitment_plan(message: str, decision: RouteDecision) -> Optional[RouteDecision]:
    """Stable hot path for common applicant list queries.

    The LLM planner remains available for open-ended tool selection, but this
    query shape is high-frequency and unambiguous. Routing it directly avoids
    slow/variable model planning while still using the normal recruitment
    skill and WorkSet persistence.
    """
    if os.getenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP') == '1':
        return None
    try:
        from flask import has_app_context

        if not has_app_context() and os.getenv('ASSISTANT_ENABLE_RECENT_RECRUITMENT_HOTPATH_OUTSIDE_APP') != '1':
            return None
    except Exception:
        if os.getenv('ASSISTANT_ENABLE_RECENT_RECRUITMENT_HOTPATH_OUTSIDE_APP') != '1':
            return None
    text = message or ''
    if not re.search(r'(最近|近\s*\d+\s*天|本周|本月|刚投|新投|来应聘|投递)', text):
        return None
    if not re.search(r'(应聘|投递|候选人|应聘者|哪些人|名单)', text):
        return None
    if re.search(r'(分析|报告|对比|面试题|安排|创建|生成|写|高分|平均|统计|汇总|几份|多少)', text):
        return None
    keyword = _extract_keyword(text)
    module = 'resumes' if re.search(r'(简历|投递)', text) else 'candidates'
    decision.task_template_id = None
    decision.router_result = None
    decision.tool_plan = [
        ToolCallPlan(
            step_id='recent_recruitment_search',
            tool='recruitment_search',
            purpose='query',
            input={
                'keyword': keyword,
                'module': module,
                'limit': _parse_limit(text, default=20),
                'date_range': {'recent_days': 30},
            },
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
    ]
    decision.reason = 'direct_recent_recruitment_hot_path'
    return decision


def _with_generation_plan(decision: RouteDecision, message: str) -> RouteDecision:
    if decision.intent == 'workset_analysis' and not decision.tool_plan:
        decision.tool_plan = [
            ToolCallPlan(
                step_id='analyze_latest_workset',
                tool='workset_analyze',
                purpose='load_context',
                input={'question': message},
                required=True,
                risk_level='low',
                cache_policy='session',
            ),
        ]
    decision.generation_plan = _generation_plan_for(decision.intent, message)
    return decision


def _with_action_tool_plan(decision: RouteDecision, message: str) -> RouteDecision:
    tool = 'interview_create' if decision.intent == 'interview_schedule' else 'followup_task_create'
    decision.tool_plan = [
        ToolCallPlan(
            step_id='confirmed_action',
            tool=tool,
            purpose='side_effect',
            input={'request_text': message},
            required=True,
            risk_level='high',
            cache_policy='none',
        ),
    ]
    return decision


def _should_try_smart_sql_before_legacy(message: str, decision: RouteDecision) -> bool:
    """Use model-planned SQL for complex analytics that fixed skills rarely cover."""
    if os.getenv('ASSISTANT_DISABLE_SMART_SQL') == '1':
        return False
    if decision.route_track != TRACK_A or decision.task_type != 'data_query':
        return False
    text = message or ''
    if re.search(r'(删除|审批|批准|发送|创建|新建|安排|更新|修改|导入|写入)', text):
        return False
    return bool(re.search(
        r'(交叉|分组|按.+统计|趋势|环比|同比|排名|排行|分布|占比|平均|中位|最高|最低|'
        r'大于|小于|超过|低于|关联|同时|分别按|每个部门|各部门|各岗位|各状态|'
        r'多维|透视|漏斗|转化|明细和汇总)',
        text,
    ))


def _smart_sql_decision(message: str, ctx: AssistantContext) -> Optional[RouteDecision]:
    try:
        from ..smart_query import generate_sql_from_question

        plan = generate_sql_from_question(message, role=ctx.role, limit=50, ctx=ctx)
    except Exception:
        plan = None
    if not plan:
        return None
    return RouteDecision(
        task_type='data_query',
        route_track=TRACK_A,
        intent='smart_analytics_query',
        confidence=0.74,
        risk_level='medium',
        tool_plan=[
            ToolCallPlan(
                step_id='smart_sql_query',
                tool='smart_data_query',
                purpose='query',
                input={
                    'question': message,
                    'sql': plan.get('sql'),
                    'explanation': plan.get('explanation') or '',
                    'limit': 50,
                },
                required=True,
                risk_level='medium',
                cache_policy='none',
            ),
        ],
        reason='smart_sql_fallback_planner',
    )


def _should_use_fast_decision(decision: RouteDecision) -> bool:
    """Keep deterministic paths for unsafe writes and context follow-ups.

    The LLM planner is still the default for open-ended system search, but
    these cases are already unambiguous and should not wait for or be hijacked
    by a model planning call.
    """
    if decision.task_type in ('action', 'forbidden'):
        return True
    if decision.intent == 'workset_analysis':
        return True
    if decision.route_track == TRACK_C:
        return True
    if decision.route_track == TRACK_B and set(decision.required_context or {}).intersection(
        {'latest_workset', 'candidate_workset', 'entity_workset', 'workset'}
    ):
        return True
    if decision.route_track == TRACK_B and decision.required_context == ['named_subject_evidence']:
        return True
    if decision.route_track == TRACK_B and decision.required_context == ['named_subjects_evidence']:
        return True
    return False


def build_route_decision(
    message: str,
    ctx: AssistantContext,
    old_router_result: Optional[RouterResult] = None,
) -> RouteDecision:
    """Build a RouteDecision from classifier output and optional legacy route."""

    decision = TrackClassifier().classify(message, ctx)
    if _is_direct_dialogue_boundary(message):
        return RouteDecision(
            task_type='dialogue',
            route_track=TRACK_C,
            intent=decision.intent if decision.route_track == TRACK_C else 'general_dialogue',
            confidence=max(decision.confidence, 0.9),
            task_template_id='general_dialogue',
            reason='planner_direct_dialogue_boundary',
        )
    write_reason = None if decision.task_type == 'action' else detect_write_intent(message)
    if write_reason:
        return RouteDecision(
            task_type='forbidden',
            route_track=TRACK_A,
            intent='forbidden_action',
            confidence=max(decision.confidence, 0.95),
            risk_level=RISK_HIGH,
            task_template_id='forbidden_action_response',
            requires_confirmation=True,
            safety_flags=[write_reason],
            reason='guardrails.detect_write_intent',
        )
    if decision.task_type == 'forbidden':
        return decision

    module_catalog_decision = _module_catalog_plan(message, decision)
    if module_catalog_decision is not None:
        return module_catalog_decision

    direct_composite_decision = _direct_composite_plan(message, decision, ctx)
    if direct_composite_decision is not None:
        return direct_composite_decision

    direct_ops_decision = _direct_ops_domain_plan(message, decision, ctx)
    if direct_ops_decision is not None:
        return direct_ops_decision

    direct_nav_decision = _direct_nav_module_plan(message, decision, ctx)
    if direct_nav_decision is not None:
        return direct_nav_decision

    direct_employee_org_decision = _direct_employee_org_plan(message, decision)
    if direct_employee_org_decision is not None:
        return direct_employee_org_decision

    direct_recruitment_match_decision = _direct_recruitment_match_matrix_plan(message, decision)
    if direct_recruitment_match_decision is not None:
        return direct_recruitment_match_decision

    direct_recruitment_decision = _direct_recruitment_query_plan(message, decision)
    if direct_recruitment_decision is not None:
        return direct_recruitment_decision

    if _should_use_fast_decision(decision):
        if decision.task_type == 'action':
            return _with_action_tool_plan(decision, message)
        if decision.route_track == TRACK_B:
            return _with_generation_plan(decision, message)
        if decision.route_track == TRACK_C:
            decision.task_template_id = decision.task_template_id or 'general_dialogue'
        return decision

    if old_router_result is None and decision.task_type != 'action':
        try:
            from .llm_skill_planner import plan_with_llm

            llm_decision = plan_with_llm(message, ctx)
            if llm_decision is not None:
                return llm_decision
        except Exception:
            # The deterministic router remains the fallback.
            pass

    module_catalog_decision = _module_catalog_plan(message, decision)
    if module_catalog_decision is not None:
        return module_catalog_decision

    direct_composite_decision = _direct_composite_plan(message, decision, ctx)
    if direct_composite_decision is not None:
        return direct_composite_decision

    direct_ops_decision = _direct_ops_domain_plan(message, decision, ctx)
    if direct_ops_decision is not None:
        return direct_ops_decision

    direct_nav_decision = _direct_nav_module_plan(message, decision, ctx)
    if direct_nav_decision is not None:
        return direct_nav_decision

    direct_employee_org_decision = _direct_employee_org_plan(message, decision)
    if direct_employee_org_decision is not None:
        return direct_employee_org_decision

    direct_recruitment_match_decision = _direct_recruitment_match_matrix_plan(message, decision)
    if direct_recruitment_match_decision is not None:
        return direct_recruitment_match_decision

    direct_recruitment_decision = _direct_recruitment_query_plan(message, decision)
    if direct_recruitment_decision is not None:
        return direct_recruitment_decision

    if _should_use_fast_decision(decision):
        if decision.task_type == 'action':
            return _with_action_tool_plan(decision, message)
        if decision.route_track == TRACK_B:
            return _with_generation_plan(decision, message)
        if decision.route_track == TRACK_C:
            decision.task_template_id = decision.task_template_id or 'general_dialogue'
        return decision

    direct_decision = _direct_recent_recruitment_plan(message, decision)
    if direct_decision is not None:
        return direct_decision

    if _should_try_smart_sql_before_legacy(message, decision):
        smart_decision = _smart_sql_decision(message, ctx)
        if smart_decision is not None:
            return smart_decision

    if decision.task_type == 'forbidden':
        return decision

    if decision.task_type == 'action':
        return _with_action_tool_plan(decision, message)

    if decision.route_track == TRACK_A:
        if old_router_result is None:
            from . import legacy_routing as routing

            old_router_result = routing.route(message, ctx)
        return router_result_to_route_decision(
            old_router_result,
            route_track=TRACK_A,
            task_type='action' if old_router_result.requires_confirmation else 'data_query',
        )

    if decision.route_track == TRACK_C:
        decision.task_template_id = decision.task_template_id or 'general_dialogue'
        return decision

    if decision.route_track == TRACK_B:
        return _with_generation_plan(decision, message)

    if decision.route_track == TRACK_COMPOSITE:
        keyword = _extract_keyword(message)
        decision.tool_plan = [
            ToolCallPlan(
                step_id='candidate_search',
                tool='recruitment_search',
                purpose='query',
                input={
                    'keyword': keyword,
                    'module': 'candidates',
                    'limit': _parse_limit(message, default=5),
                },
                required=True,
                risk_level='low',
                cache_policy='session',
            ),
        ]
        return _with_generation_plan(decision, message)

    # Defensive fallback: stay conversational rather than forcing global_search.
    return RouteDecision(
        task_type='dialogue',
        route_track=TRACK_C,
        intent='general_dialogue',
        confidence=0.5,
        reason='planner_fallback_to_dialogue',
    )


__all__ = ['build_route_decision']
