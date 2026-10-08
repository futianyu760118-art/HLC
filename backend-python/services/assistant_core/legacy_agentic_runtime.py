"""Intelligent-first assistant runtime.

This module is the new front path for high-frequency HR assistant requests. It
keeps the existing frontend response contract while moving query understanding
away from scattered route patches and toward a small, stateful execution graph:

understand -> resolve entity/context -> execute tools/action -> compose output.

The legacy orchestrator remains the fallback for uncovered domains.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from models import (
    ApprovalInstance, AttendanceRecord, Candidate, Department, Employee,
    EmployeeRequest, Notification, Position, Resume,
)
from services.business_time import business_now

from . import memory, widgets as W
from .constants import (
    PRIVILEGED_ROLES, ROLE_ADMIN, ROLE_EXECUTIVE, ROLE_HR_ADMIN, ROLE_MANAGER,
    ROLE_EMPLOYEE,
)
from .response_contract import apply_response_contract
from .executors import ToolExecutor
from .schemas import (
    AssistantContext, ExecutionResult, ExecutionStep, GenerationPlan,
    RouteDecision, ToolCallPlan, route_decision_to_router_result,
)
from . import workset_store


MAX_LIMIT = 50
APPROVAL_DECISION_ROLES = {ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE}
APPROVAL_OVERRIDE_ROLES = {ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE}
EMPLOYEE_CHANGE_ROLES = {ROLE_ADMIN, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE}
LLM_TOOL_INTENTS = {
    'employee_search': ('employee', 'employee.search'),
    'organization_search': ('organization', 'organization.overview'),
    'attendance_analysis': ('attendance', 'attendance.exceptions'),
    'performance_analysis': ('performance', 'performance.distribution'),
    'training_analysis': ('training', 'training.completion'),
    'payroll_analysis': ('payroll', 'payroll.summary'),
    'approval_search': ('approval', 'approval.pending'),
    'feedback_triage': ('feedback', 'feedback.overview'),
    'dashboard_report': ('dashboard', 'dashboard.system.overview'),
    'recruitment_search': ('recruitment', 'recruitment.smart_search'),
}


@dataclass
class TaskFrame:
    """Normalized intent frame produced from colloquial user text."""

    domain: str
    intent: str
    action: str
    entity_type: str = ''
    name: Optional[str] = None
    module: Optional[str] = None
    status: Optional[str] = None
    count_only: bool = False
    recent_days: Optional[int] = None
    limit: int = 20
    needs_evidence: bool = False
    needs_confirmation: bool = False
    schedule_at: Optional[str] = None
    confidence: float = 0.9
    reason: str = ''
    slots: Dict[str, Any] = field(default_factory=dict)


def try_run(message: str, ctx: AssistantContext) -> Optional[ExecutionResult]:
    """Try the intelligent runtime. Return ``None`` to let legacy handle it."""
    text = (message or '').strip()
    if not text:
        return None

    action_verb, action_id = _action_message_parts(text)
    if action_verb:
        return _execute_pending_action(text, ctx, action_verb, action_id)

    frame = _understand(text, ctx)
    if frame is None:
        return None

    if frame.intent in {
        'recruitment.jobs.open.list',
        'recruitment.jobs.open.count',
        'recruitment.resumes.count',
        'recruitment.resumes.recent.list',
        'recruitment.candidates.count',
        'recruitment.candidates.recent.list',
    }:
        return _run_recruitment_search(text, ctx, frame)

    if frame.intent == 'recruitment.match.matrix':
        return _run_recruitment_match(text, ctx, frame)

    if frame.intent == 'employee.change.impact':
        return _run_employee_change_impact(text, ctx, frame)

    if frame.intent == 'employee.salary_adjustment.impact':
        return _run_employee_salary_adjustment_impact(text, ctx, frame)

    if frame.intent == 'payroll.performance.link':
        return _run_payroll_performance_link(text, ctx, frame)

    if frame.intent == 'employee.self_service.multi_topic':
        return _run_employee_self_service_multi_topic(text, ctx, frame)

    if frame.intent == 'person.ambiguous.clarify':
        return _run_ambiguous_person_clarify(text, ctx, frame)

    if frame.intent == 'recruitment.person.resume.lookup':
        return _run_person_lookup(text, ctx, frame)

    if frame.intent == 'recruitment.person.assess':
        return _run_person_assessment(text, ctx, frame)

    if frame.intent == 'recruitment.interview.schedule':
        return _run_interview_confirmation(text, ctx, frame)

    if frame.intent == 'employee.profile':
        return _run_employee_profile(text, ctx, frame)

    if frame.intent == 'attendance.late_top_notify':
        return _run_attendance_reminder_confirmation(text, ctx, frame)

    if frame.intent == 'attendance.employee.anomaly':
        return _run_employee_attendance_evidence(text, ctx, frame)

    if frame.intent == 'approval.decision':
        return _run_approval_decision_confirmation(text, ctx, frame)

    if frame.intent in {
        'employee.search',
        'organization.overview',
        'attendance.exceptions',
        'attendance.overview',
        'attendance.stats_context_explain',
        'approval.pending',
        'approval.mine',
        'approval.history',
        'performance.distribution',
        'training.completion',
        'payroll.summary',
        'feedback.pending_bugs',
        'feedback.overview',
        'dashboard.system.overview',
        'recruitment.page_context',
        'performance.page_context',
        'employee.page_context',
    }:
        return _run_tool_frame(text, ctx, frame)

    return None


def _understand(message: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    """Normalize colloquial Chinese HR requests into a TaskFrame."""
    text = _normalize_text(message)
    action_frame = _understand_explicit_attendance_action(text)
    if action_frame is not None:
        return action_frame
    approval_decision_frame = _understand_approval_decision(text, ctx)
    if approval_decision_frame is not None:
        return approval_decision_frame

    if _is_employee_lifecycle_evidence_request(text) or _is_employee_profile_query(text):
        name = _extract_employee_profile_name(text) or _extract_employee_keyword(text) or _last_focus(ctx).get('name')
        return TaskFrame(
            domain='employee',
            intent='employee.profile',
            action='profile',
            entity_type='employee',
            name=name,
            needs_evidence=True,
            confidence=0.95,
            reason='agentic_employee_profile',
            slots={'tool': 'employee_evidence_bundle', 'params': {'keyword': name} if name else {}},
        )

    employee_action_frame = _understand_explicit_employee_action(text, ctx)
    if employee_action_frame is not None:
        return employee_action_frame

    # Explicit employee-level attendance questions must beat page context. On
    # an attendance stats page, "吴明华最近考勤异常吗" is still an employee evidence
    # request, not a request to explain the current aggregate chart.
    if _is_employee_attendance_anomaly_request(text) and not _is_payroll_performance_link_request(text):
        name = _extract_attendance_employee_name(text) or _extract_employee_keyword(text) or _last_focus(ctx).get('name')
        params = {'keyword': name, 'recent_days': _extract_recent_days(text) or 30}
        month = _extract_month(text)
        if month:
            params['month'] = month
        return TaskFrame(
            domain='attendance',
            intent='attendance.employee.anomaly',
            action='analyze_employee',
            entity_type='employee',
            name=name,
            needs_evidence=True,
            confidence=0.95,
            reason='agentic_employee_attendance_evidence',
            slots={'tool': 'employee_attendance_evidence', 'params': params},
        )

    # Strong business-domain intents first. Generic words like "怎么样" should
    # not hijack dashboard or operational queries into person assessment.
    if _is_dashboard_query(text):
        return TaskFrame(
            domain='dashboard',
            intent='dashboard.system.overview',
            action='overview',
            entity_type='dashboard',
            confidence=0.95,
            reason='agentic_dashboard_overview',
            slots={'tool': 'dashboard_report', 'params': {'scope': 'system'}},
        )

    if _is_approval_query(text):
        view = 'history' if re.search(r'(历史|记录|办过|处理过)', text) else 'mine' if re.search(r'(我的申请|我提交|我发起)', text) else 'pending'
        return TaskFrame(
            domain='approval',
            intent=f'approval.{view}',
            action='list',
            entity_type='approval',
            confidence=0.94,
            reason='agentic_approval_query',
            slots={'tool': 'approval_search', 'params': {'view': view, 'limit': _extract_limit(text) or 20}},
        )

    if _is_feedback_query(text):
        pending = bool(re.search(r'(待处理|没处理|未处理|还没处理|pending)', text, re.I))
        bug = bool(re.search(r'(bug|缺陷|报错|错误|白屏|异常)', text, re.I))
        params: Dict[str, Any] = {'limit': _extract_limit(text) or 20}
        if pending:
            params['status'] = 'pending'
        if bug:
            params['feedback_type'] = 'bug'
        return TaskFrame(
            domain='feedback',
            intent='feedback.pending_bugs' if pending and bug else 'feedback.overview',
            action='list',
            entity_type='feedback',
            confidence=0.92,
            reason='agentic_feedback_query',
            slots={'tool': 'feedback_triage', 'params': params},
        )

    self_service_frame = _understand_employee_self_service(text, ctx)
    if self_service_frame is not None:
        return self_service_frame

    if _is_payroll_performance_link_request(text):
        year, quarter = _extract_quarter(text)
        params = _payroll_performance_params_from_context(ctx)
        if year:
            params['year'] = year
        if quarter:
            params['quarter'] = quarter
        return TaskFrame(
            domain='payroll',
            intent='payroll.performance.link',
            action='correlate',
            entity_type='employee',
            needs_evidence=True,
            confidence=0.95,
            reason='agentic_payroll_performance_link',
            slots={'tool': 'payroll_performance_link', 'params': params},
        )

    operations_frame = _understand_operational_domain_query(text)
    if operations_frame is not None:
        return operations_frame

    if _is_person_assessment_request(text):
        workset_item = _resolve_candidate_workset_item(text, ctx)
        if workset_item:
            evidence_params: Dict[str, Any] = {}
            if workset_item.get('entity_type') == 'candidate':
                evidence_params['candidate_id'] = workset_item.get('entity_id')
            elif workset_item.get('entity_type') == 'resume':
                evidence_params['resume_id'] = workset_item.get('entity_id')
            return TaskFrame(
                domain='recruitment',
                intent='recruitment.person.assess',
                action='assess',
                entity_type='candidate',
                name=workset_item.get('title') or _last_focus(ctx).get('name'),
                needs_evidence=True,
                confidence=0.95,
                reason='agentic_person_assessment_workset_followup',
                slots={'tool': 'candidate_evidence_bundle', 'params': evidence_params},
            )

    if _is_person_assessment_request(text) and _last_focus(ctx).get('name'):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.person.assess',
            action='assess',
            entity_type='candidate',
            name=_last_focus(ctx).get('name'),
            needs_evidence=True,
            confidence=0.94,
            reason='agentic_person_assessment_focus_followup',
        )

    if _is_ambiguous_person_context_request(text):
        return TaskFrame(
            domain='people',
            intent='person.ambiguous.clarify',
            action='clarify',
            entity_type='person',
            name=_extract_ambiguous_person_keyword(text),
            confidence=0.9,
            reason='agentic_ambiguous_person_clarify',
        )

    context_frame = _understand_from_page_context(text, ctx)
    if context_frame is not None:
        return context_frame

    if _is_attendance_query(text):
        if _is_attendance_reminder_request(text):
            month = _extract_month(text) or business_now().strftime('%Y-%m')
            limit = _extract_limit(text) or 5
            return TaskFrame(
                domain='attendance',
                intent='attendance.late_top_notify',
                action='draft_notification',
                entity_type='employee',
                limit=limit,
                needs_confirmation=True,
                confidence=0.95,
                reason='agentic_attendance_late_notify',
                slots={
                    'tool': 'attendance_analysis',
                    'params': {
                        'month': month,
                        'anomaly_only': True,
                        'rank_status': 'late',
                        'limit': limit,
                    },
                },
            )
        params = {'anomaly_only': bool(re.search(r'(异常|迟到|早退|缺勤|缺卡|请假|加班|出差)', text))}
        month = _extract_month(text)
        if month:
            params['month'] = month
        return TaskFrame(
            domain='attendance',
            intent='attendance.exceptions' if params['anomaly_only'] else 'attendance.overview',
            action='analyze',
            entity_type='attendance',
            confidence=0.93,
            reason='agentic_attendance_query',
            slots={'tool': 'attendance_analysis', 'params': params},
        )

    if _is_organization_query(text):
        keyword = _extract_org_keyword(text)
        params = {'include_stats': True}
        if keyword:
            params['keyword'] = keyword
        return TaskFrame(
            domain='organization',
            intent='organization.overview',
            action='list',
            entity_type='department',
            confidence=0.91,
            reason='agentic_organization_query',
            slots={'tool': 'organization_search', 'params': params},
        )

    if _is_employee_query(text):
        keyword = _extract_employee_keyword(text)
        params: Dict[str, Any] = {'limit': _extract_limit(text) or 20}
        if keyword:
            params['keyword'] = keyword
        return TaskFrame(
            domain='employee',
            intent='employee.search',
            action='list',
            entity_type='employee',
            confidence=0.92,
            reason='agentic_employee_query',
            slots={'tool': 'employee_search', 'params': params},
        )

    if _is_interview_schedule_request(text):
        name = _extract_person_name(text) or _last_focus(ctx).get('name')
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.interview.schedule',
            action='create_interview',
            entity_type='candidate',
            name=name,
            needs_evidence=True,
            needs_confirmation=True,
            schedule_at=_parse_schedule_time(text),
            confidence=0.93,
            reason='agentic_interview_schedule',
        )

    if _is_recruitment_match_request(text):
        keyword = _extract_recruitment_job_keyword(text) or _last_focus(ctx).get('job_title')
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.match.matrix',
            action='compare',
            entity_type='job',
            name=keyword,
            module='recruitment',
            limit=_extract_limit(text) or 8,
            needs_evidence=True,
            confidence=0.94,
            reason='agentic_recruitment_match_matrix',
            slots={'tool': 'recruitment_match_matrix', 'params': {'keyword': keyword, 'limit': _extract_limit(text) or 8}},
        )

    if _is_person_assessment_request(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.person.assess',
            action='assess',
            entity_type='candidate',
            name=_extract_person_name(text) or _last_focus(ctx).get('name'),
            needs_evidence=True,
            confidence=0.94,
            reason='agentic_person_assessment',
        )

    if _is_person_resume_lookup(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.person.resume.lookup',
            action='lookup_resume',
            entity_type='candidate',
            name=_extract_person_name(text),
            needs_evidence=True,
            confidence=0.95,
            reason='agentic_person_resume_lookup',
        )

    if _is_open_job_query(text):
        count_only = bool(re.search(r'(多少|几个|几条|数量|总数|一共|共有)', text))
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.jobs.open.count' if count_only else 'recruitment.jobs.open.list',
            action='count' if count_only else 'list',
            entity_type='job',
            module='jobs',
            status='open',
            count_only=count_only,
            limit=20,
            confidence=0.96,
            reason='agentic_open_job_query',
        )

    if _is_resume_count_query(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.resumes.count',
            action='count',
            entity_type='resume',
            module='resumes',
            count_only=True,
            limit=20,
            confidence=0.95,
            reason='agentic_resume_count_query',
        )

    if _is_recent_resume_list_query(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.resumes.recent.list',
            action='list',
            entity_type='resume',
            module='resumes',
            recent_days=_extract_recent_days(text) or 30,
            limit=_extract_limit(text) or 20,
            confidence=0.91,
            reason='agentic_recent_resume_query',
        )

    if _is_candidate_count_query(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.candidates.count',
            action='count',
            entity_type='candidate',
            module='candidates',
            count_only=True,
            limit=20,
            confidence=0.9,
            reason='agentic_candidate_count_query',
        )

    if _is_recent_candidate_list_query(text):
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.candidates.recent.list',
            action='list',
            entity_type='candidate',
            module='candidates',
            recent_days=_extract_recent_days(text) or 30,
            limit=_extract_limit(text) or 20,
            confidence=0.9,
            reason='agentic_recent_candidate_query',
        )

    llm_frame = _understand_with_llm(text, ctx)
    if llm_frame is not None:
        return llm_frame

    return None


def _understand_explicit_employee_action(text: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    """Route explicit employee-side-effect requests before history/page focus."""
    if _is_employee_change_impact_request(text):
        name = _extract_employee_change_name(text) or _extract_employee_keyword(text) or _last_focus(ctx).get('name')
        target_department = _extract_target_department(text)
        target_position = _extract_target_position(text, target_department)
        return TaskFrame(
            domain='employee',
            intent='employee.change.impact',
            action='simulate_change',
            entity_type='employee',
            name=name,
            needs_evidence=True,
            needs_confirmation=True,
            confidence=0.95,
            reason='agentic_employee_change_impact',
            slots={
                'tool': 'employee_change_impact',
                'params': {
                    'keyword': name,
                    'target_department': target_department,
                    'target_position': target_position,
                },
            },
        )

    if _is_employee_salary_adjustment_request(text):
        name = _extract_salary_adjustment_name(text) or _extract_employee_keyword(text) or _last_focus(ctx).get('name')
        salary_delta = _extract_salary_adjustment_amount(text)
        salary_delta_text = _format_salary_adjustment_amount(salary_delta)
        return TaskFrame(
            domain='employee',
            intent='employee.salary_adjustment.impact',
            action='simulate_salary_adjustment',
            entity_type='employee',
            name=name,
            needs_evidence=True,
            needs_confirmation=True,
            confidence=0.95 if name and salary_delta else 0.82,
            reason='agentic_employee_salary_adjustment_impact',
            slots={
                'tool': 'employee_salary_adjustment_impact',
                'params': {
                    'keyword': name,
                    'salary_adjustment': salary_delta_text,
                },
            },
        )

    return None


def _understand_employee_self_service(text: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    """Route employee-facing "my data" asks as a scoped multi-topic query.

    This prevents mixed self-service questions such as "我的考勤、绩效和工资条"
    from being swallowed by the high-sensitive payroll/performance linkage
    path. The runtime can then return visible personal data and a clear salary
    permission boundary in one response.
    """
    if ctx.role != ROLE_EMPLOYEE:
        return None
    if not re.search(r'(我的|我本人|我自己的|本人|我是普通员工|普通员工)', text):
        return None
    topics: List[str] = []
    if re.search(r'(考勤|迟到|早退|缺勤|缺卡|补卡|请假|加班|出差)', text):
        topics.append('attendance')
    if re.search(r'(绩效|考核|评分|等级|评价)', text):
        topics.append('performance')
    if re.search(r'(工资条|工资|薪资|薪酬|发薪|个税|奖金|社保|公积金)', text):
        topics.append('payroll')
    if not topics:
        return None
    if 'payroll' in topics or len(topics) >= 2:
        return TaskFrame(
            domain='employee_self_service',
            intent='employee.self_service.multi_topic',
            action='self_service_query',
            entity_type='employee',
            confidence=0.96,
            reason='agentic_employee_self_service_multi_topic',
            slots={'topics': topics},
        )
    return None


def _understand_explicit_attendance_action(text: str) -> Optional[TaskFrame]:
    if not _is_attendance_reminder_request(text):
        return None
    month = _extract_month(text) or business_now().strftime('%Y-%m')
    limit = _extract_limit(text) or 5
    return TaskFrame(
        domain='attendance',
        intent='attendance.late_top_notify',
        action='draft_notification',
        entity_type='employee',
        limit=limit,
        needs_confirmation=True,
        confidence=0.95,
        reason='agentic_attendance_late_notify',
        slots={
            'tool': 'attendance_analysis',
            'params': {
                'month': month,
                'anomaly_only': True,
                'rank_status': 'late',
                'limit': limit,
            },
        },
    )


def _understand_approval_decision(text: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    action = _extract_approval_decision_action(text)
    if not action:
        return None
    approval_id = _extract_approval_ref(text)
    target_index = _extract_approval_rank(text) if not approval_id else None
    if not approval_id and not target_index and re.search(r'(这条|这个|当前|刚才|上面|第一条|第一个|第1条|第1个)', text):
        target_index = target_index or 1
    comment = _extract_approval_comment(text)
    return TaskFrame(
        domain='approval',
        intent='approval.decision',
        action=action,
        entity_type='approval',
        needs_evidence=True,
        needs_confirmation=True,
        confidence=0.96 if approval_id or target_index else 0.82,
        reason='agentic_approval_decision',
        slots={
            'tool': 'approval_decision',
            'params': {
                'approval_id': approval_id,
                'action': action,
                'target_index': target_index,
                'comment': comment,
            },
        },
    )


def _understand_from_page_context(text: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    context = getattr(ctx, 'client_context', {}) or {}
    path = str(context.get('path') or context.get('route') or '')
    module_id = str(context.get('moduleId') or '')
    module_name = str(context.get('moduleName') or '')
    current_module = f'{path} {module_id} {module_name}'
    followup_boundary = bool(
        re.search(r'(当前|这些|这批|这页|这里|筛选|统计|记录|为什么|口径|没有|不一致|解释|按.*条件|这些记录|缺口|风险|分析|汇总|联动)', text)
        or len(text) <= 40
    )
    if not followup_boundary:
        return None

    filters = _page_visible_filters(ctx)

    if re.search(r'(attendance-stats|attendance_records|attendance-records|考勤统计|考勤记录)', current_module):
        explicit_other_domain = re.search(r'(招聘|简历|候选人|面试|薪资|工资|绩效|离职|培训|反馈|审批中心)', text)
        if explicit_other_domain:
            return None
        return _page_context_attendance_frame(text, filters)

    if re.search(r'(job-manage|jobs|candidate|resume|interview|offer|岗位管理|招聘|候选人|简历|面试|Offer)', current_module):
        frame = _page_context_recruitment_frame(text, filters, current_module)
        if frame is not None:
            return frame

    if re.search(r'(salary-profiles|payroll|performance-review|performance-cycles|performance|薪资|工资|绩效|考核)', current_module):
        frame = _page_context_payroll_performance_frame(text, filters, current_module)
        if frame is not None:
            return frame

    if re.search(r'(employees|employee-manage|员工档案|员工管理|花名册)', current_module):
        frame = _page_context_employee_frame(text, filters)
        if frame is not None:
            return frame

    return None


def _page_visible_filters(ctx: AssistantContext) -> Dict[str, Any]:
    context = getattr(ctx, 'client_context', {}) or {}
    filters = context.get('visibleFilters') if isinstance(context.get('visibleFilters'), dict) else {}
    return {str(k): v for k, v in filters.items() if v not in (None, '')}


def _page_filter_text(filters: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = filters.get(key)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _page_filter_display(filters: Dict[str, Any], key: str) -> str:
    return _page_filter_text(filters, f'{key}Label', f'{key}_label', key)


def _payroll_performance_params_from_context(ctx: AssistantContext) -> Dict[str, Any]:
    filters = _page_visible_filters(ctx)
    params: Dict[str, Any] = {}
    month = str(filters.get('month') or filters.get('payrollMonth') or '')[:7]
    department_id = _page_filter_text(filters, 'departmentId')
    employee_id = _page_filter_text(filters, 'employeeId')
    cycle_id = _page_filter_text(filters, 'cycleId')
    if month:
        params['month'] = month
    if department_id:
        params['department_id'] = department_id
    if employee_id:
        params['employee_id'] = employee_id
    if cycle_id:
        params['cycle_id'] = cycle_id
    return params


def _page_context_attendance_frame(text: str, filters: Dict[str, Any]) -> TaskFrame:
    params: Dict[str, Any] = {'anomaly_only': False, 'explain_stats': True}
    month = _extract_month(text) or str(filters.get('month') or filters.get('attendanceMonth') or '')[:7]
    if not month:
        month = business_now().strftime('%Y-%m')
    params['month'] = month
    if filters.get('employeeId'):
        params['employee_id'] = str(filters.get('employeeId'))
    if filters.get('departmentId'):
        params['department_id'] = str(filters.get('departmentId'))
    if re.search(r'(异常|迟到|早退|缺卡|缺勤)', text):
        params['anomaly_only'] = True
    return TaskFrame(
        domain='attendance',
        intent='attendance.stats_context_explain',
        action='explain',
        entity_type='attendance',
        confidence=0.94,
        reason='agentic_page_context:attendance_stats',
        slots={'tool': 'attendance_analysis', 'params': params},
    )


def _page_context_recruitment_frame(
    text: str,
    filters: Dict[str, Any],
    current_module: str,
) -> Optional[TaskFrame]:
    wants_match = bool(re.search(r'(匹配|更合适|对比|矩阵|候选人.*适合|推荐顺序)', text))
    wants_count = bool(re.search(r'(多少|几个|几条|数量|总数|一共|缺口|开放|招聘中)', text))
    module = 'all'
    if re.search(r'(job-manage|岗位管理|岗位)', current_module):
        module = 'jobs'
    elif re.search(r'(resume|简历)', current_module):
        module = 'resumes'
    elif re.search(r'(candidate|候选人)', current_module):
        module = 'candidates'
    elif re.search(r'(interview|面试)', current_module):
        module = 'interviews'
    elif re.search(r'(offer|Offer)', current_module):
        module = 'offers'

    keyword = (
        _extract_recruitment_job_keyword(text)
        or _page_filter_display(filters, 'jobId')
        or _page_filter_display(filters, 'search')
        or _page_filter_display(filters, 'departmentId')
        or _page_filter_display(filters, 'location')
        or _page_filter_text(filters, 'job', 'keyword')
        or None
    )
    status = _page_filter_text(filters, 'status')
    limit = _extract_limit(text) or 20
    if wants_match and keyword:
        return TaskFrame(
            domain='recruitment',
            intent='recruitment.match.matrix',
            action='compare',
            entity_type='job',
            name=keyword,
            module='recruitment',
            limit=min(limit, 8),
            needs_evidence=True,
            confidence=0.93,
            reason='agentic_page_context:recruitment_match',
            slots={'tool': 'recruitment_match_matrix', 'params': {'keyword': keyword, 'limit': min(limit, 8)}},
        )

    params: Dict[str, Any] = {
        'module': module,
        'limit': limit,
        'count_only': wants_count,
    }
    if keyword:
        params['keyword'] = keyword
    if status:
        params['status'] = status
    return TaskFrame(
        domain='recruitment',
        intent='recruitment.page_context',
        action='count' if wants_count else 'list',
        entity_type='recruitment',
        module=module,
        count_only=wants_count,
        limit=limit,
        confidence=0.91,
        reason=f'agentic_page_context:recruitment:{module}',
        slots={'tool': 'recruitment_search', 'params': params},
    )


def _page_context_payroll_performance_frame(
    text: str,
    filters: Dict[str, Any],
    current_module: str,
) -> Optional[TaskFrame]:
    month = _extract_month(text) or str(filters.get('month') or filters.get('payrollMonth') or '')[:7]
    department_id = _page_filter_text(filters, 'departmentId')
    employee_id = _page_filter_text(filters, 'employeeId')
    cycle_id = _page_filter_text(filters, 'cycleId')
    wants_link = bool(
        _is_payroll_performance_link_request(text)
        or re.search(r'(联动|共同异常|薪资.*绩效|绩效.*薪资|薪酬.*考勤|风险)', text)
        or re.search(r'(salary|payroll|薪资|工资|薪酬)', current_module)
    )
    if wants_link:
        params: Dict[str, Any] = {}
        if month:
            params['month'] = month
        if department_id:
            params['department_id'] = department_id
        if employee_id:
            params['employee_id'] = employee_id
        if cycle_id:
            params['cycle_id'] = cycle_id
        return TaskFrame(
            domain='payroll',
            intent='payroll.performance.link',
            action='correlate',
            entity_type='employee',
            needs_evidence=True,
            confidence=0.92,
            reason='agentic_page_context:payroll_performance',
            slots={'tool': 'payroll_performance_link', 'params': params},
        )

    params = {'view': 'summary', 'limit': _extract_limit(text) or 20}
    if department_id:
        params['department_id'] = department_id
    if employee_id:
        params['employee_id'] = employee_id
    if cycle_id:
        params['cycle_id'] = cycle_id
    return TaskFrame(
        domain='performance',
        intent='performance.page_context',
        action='analyze',
        entity_type='performance',
        confidence=0.89,
        reason='agentic_page_context:performance',
        slots={'tool': 'performance_analysis', 'params': params},
    )


def _page_context_employee_frame(text: str, filters: Dict[str, Any]) -> Optional[TaskFrame]:
    keyword = _extract_employee_keyword(text) or _page_filter_text(filters, 'search', 'keyword', 'employeeId')
    params: Dict[str, Any] = {'limit': _extract_limit(text) or 20}
    if keyword:
        params['keyword'] = keyword
    department_id = _page_filter_text(filters, 'departmentId')
    status = _page_filter_text(filters, 'status')
    if department_id:
        params['department_id'] = department_id
    if status:
        params['status'] = status
    return TaskFrame(
        domain='employee',
        intent='employee.page_context',
        action='list',
        entity_type='employee',
        confidence=0.9,
        reason='agentic_page_context:employee',
        slots={'tool': 'employee_search', 'params': params},
    )


def _run_tool_frame(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    tool = frame.slots.get('tool')
    params = dict(frame.slots.get('params') or {})
    if not tool:
        return _not_found('暂未识别到可执行工具。', ctx, _decision_from_frame(frame))
    risk_level = 'high' if tool == 'payroll_analysis' else 'low'
    cache_policy = 'none' if tool == 'payroll_analysis' else 'session'
    plan = ToolCallPlan(
        step_id=f'agentic_{tool}',
        tool=tool,
        purpose='query',
        input=params,
        required=True,
        risk_level=risk_level,
        cache_policy=cache_policy,
    )
    decision = _decision_from_frame(frame, [plan])
    decision.risk_level = risk_level
    output = ToolExecutor().execute(tool, params, ctx)
    if tool == 'employee_search' and int(output.get('rows_count') or 0) == 0:
        repaired = _repair_employee_params(params, message)
        if repaired != params:
            params = repaired
            plan.input = params
            output = ToolExecutor().execute(tool, params, ctx)
    data = output.get('data') or {}
    entities = data.get('entities') or []
    widgets = data.get('widgets') or []
    rows_count = int(output.get('rows_count') or 0)
    summary = _tool_frame_summary(frame, data, rows_count)
    widgets = _augment_tool_widgets(tool, params, data, widgets)
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        widgets=widgets,
        session_id=ctx.session_id,
        trace=[_trace(tool, output, rows_count)],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'text'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_employee_self_service_multi_topic(
    message: str,
    ctx: AssistantContext,
    frame: TaskFrame,
) -> ExecutionResult:
    topics = list(dict.fromkeys(
        str(item)
        for item in (frame.slots.get('topics') or [])
        if item in {'attendance', 'performance', 'payroll'}
    ))
    employee_id = ctx.user_employee_id
    if not employee_id:
        return _forbidden('当前账号没有绑定员工档案，无法按“我的”范围查询员工自助数据。', ctx, frame)
    if not topics:
        return _not_found('请说明要查询我的考勤、绩效、申请还是其他员工自助数据。', ctx, _decision_from_frame(frame))

    month = _extract_month(message)
    tool_plan: List[ToolCallPlan] = []
    if 'attendance' in topics:
        attendance_input: Dict[str, Any] = {'employee_id': employee_id, 'anomaly_only': False}
        if month:
            attendance_input['month'] = month
        tool_plan.append(ToolCallPlan(
            step_id='employee_self_attendance',
            tool='attendance_analysis',
            purpose='query',
            input=attendance_input,
            required=False,
            risk_level='low',
            cache_policy='session',
        ))
    if 'performance' in topics:
        tool_plan.append(ToolCallPlan(
            step_id='employee_self_performance',
            tool='performance_analysis',
            purpose='query',
            input={'employee_id': employee_id, 'view': 'personal'},
            required=False,
            risk_level='low',
            cache_policy='session',
        ))
    if 'payroll' in topics:
        payroll_input: Dict[str, Any] = {'employee_id': employee_id, 'view': 'personal'}
        if month:
            payroll_input['month'] = month
        tool_plan.append(ToolCallPlan(
            step_id='employee_self_payroll_denied',
            tool='payroll_analysis',
            purpose='query',
            input=payroll_input,
            required=False,
            risk_level='high',
            cache_policy='none',
        ))

    decision = _decision_from_frame(frame, tool_plan)
    decision.task_type = 'data_query'
    decision.route_track = 'A_DATA_ACTION'
    if 'payroll' in topics:
        decision.safety_flags.append('permission_denied')
    executor = ToolExecutor()
    trace: List[ExecutionStep] = []
    widgets: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []
    evidence_sources: List[Dict[str, Any]] = []
    rows_by_topic: Dict[str, int] = {}
    ok_topics: List[str] = []
    denied_topics: List[str] = []

    def run_tool(topic: str, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        out = executor.execute(tool, params, ctx)
        rows_count = int(out.get('rows_count') or 0)
        trace.append(_trace(tool, out, rows_count))
        rows_by_topic[topic] = rows_count
        return out

    if 'attendance' in topics:
        params = next(plan.input for plan in tool_plan if plan.step_id == 'employee_self_attendance')
        out = run_tool('attendance', 'attendance_analysis', params)
        data = out.get('data') or {}
        if out.get('ok'):
            ok_topics.append('attendance')
            entities.extend(data.get('entities') or [])
            widgets.extend(_prefix_widget_titles(
                _augment_tool_widgets('attendance_analysis', params, data, data.get('widgets') or []),
                '我的考勤',
            ))
            evidence_sources.extend([
                {
                    'module': 'attendance_records',
                    'recordType': 'attendance_records',
                    'title': f'本人考勤记录 {rows_by_topic.get("attendance", 0)} 条',
                    'url': '/hrm/attendance-records',
                },
                {
                    'module': 'attendance_stats',
                    'recordType': 'attendance_stats',
                    'title': '本人考勤统计口径',
                    'url': '/attendance-stats',
                },
            ])

    if 'performance' in topics:
        params = next(plan.input for plan in tool_plan if plan.step_id == 'employee_self_performance')
        out = run_tool('performance', 'performance_analysis', params)
        data = out.get('data') or {}
        if out.get('ok'):
            ok_topics.append('performance')
            entities.extend(data.get('entities') or [])
            widgets.extend(_prefix_widget_titles(data.get('widgets') or [], '我的绩效'))
            evidence_sources.append({
                'module': 'performance_reviews',
                'recordType': 'performance_reviews',
                'title': f'本人绩效记录 {rows_by_topic.get("performance", 0)} 条',
                'url': '/performance-review',
            })

    if 'payroll' in topics:
        params = next(plan.input for plan in tool_plan if plan.step_id == 'employee_self_payroll_denied')
        out = run_tool('payroll', 'payroll_analysis', params)
        data = out.get('data') or {}
        if out.get('ok') and not data.get('permission_denied'):
            ok_topics.append('payroll')
            widgets.extend(_prefix_widget_titles(data.get('widgets') or [], '我的工资条'))
            evidence_sources.append({
                'module': 'payroll_records',
                'recordType': 'payroll_records',
                'title': f'本人工资条记录 {rows_by_topic.get("payroll", 0)} 条',
                'url': '/hrm/payroll-records',
            })
        else:
            denied_topics.append('payroll')
            widgets.append(W.warning('工资条/薪酬数据属于敏感信息，普通员工角色当前不可通过 AI 助手查看明细。', level='danger'))
            evidence_sources.append({
                'module': 'permissions',
                'recordType': 'role_policy',
                'recordId': ctx.role,
                'title': '普通员工无薪酬明细查询权限',
                'url': '/hrm/roles',
            })

    status_items = []
    if 'attendance' in topics:
        status_items.append({
            'label': '考勤',
            'value': f'{rows_by_topic.get("attendance", 0)} 条',
            'status': 'success' if 'attendance' in ok_topics else 'warning',
            'icon': 'fa-calendar-check',
            'hint': '仅限当前登录员工本人范围',
        })
    if 'performance' in topics:
        status_items.append({
            'label': '绩效',
            'value': f'{rows_by_topic.get("performance", 0)} 条',
            'status': 'success' if 'performance' in ok_topics else 'warning',
            'icon': 'fa-chart-line',
            'hint': '仅限当前登录员工本人范围',
        })
    if 'payroll' in topics:
        status_items.append({
            'label': '工资条',
            'value': '无权限' if 'payroll' in denied_topics else f'{rows_by_topic.get("payroll", 0)} 条',
            'status': 'danger' if 'payroll' in denied_topics else 'success',
            'icon': 'fa-money-bill',
            'hint': '薪酬明细按角色权限控制',
        })
    if status_items:
        widgets.insert(0, W.status_badges(status_items, title='员工自助权限与数据范围'))
    if evidence_sources:
        widgets.append({
            'type': 'source_citations',
            'title': '本次员工自助查询证据',
            'sources': _dedupe_sources(evidence_sources),
        })
    widgets.append(W.follow_up_actions([
        {'label': '查看我的申请', 'payload': '查看我的申请记录并生成状态摘要', 'icon': 'fa-file-signature', 'url': '/approval-center/my-applications'},
        {'label': '解释考勤统计', 'payload': '解释我的考勤统计口径和异常来源', 'icon': 'fa-circle-info', 'url': '/attendance-stats'},
        {'label': '查看绩效详情', 'payload': '查看我的绩效记录和改进建议', 'icon': 'fa-chart-line', 'url': '/performance-review'},
    ], title='员工自助下一步'))

    visible_labels = []
    if 'attendance' in ok_topics:
        visible_labels.append(f'考勤 {rows_by_topic.get("attendance", 0)} 条')
    if 'performance' in ok_topics:
        visible_labels.append(f'绩效 {rows_by_topic.get("performance", 0)} 条')
    denied_labels = []
    if 'payroll' in denied_topics:
        denied_labels.append('工资条/薪酬明细')
    summary_parts = []
    if visible_labels:
        summary_parts.append(f'已按当前登录员工本人范围读取：{"、".join(visible_labels)}。')
    if denied_labels:
        summary_parts.append(f'因角色权限限制，{"、".join(denied_labels)}不能通过普通员工账号查看明细。')
    if not summary_parts:
        summary_parts.append('当前没有读取到可展示的员工自助数据。')
    summary_parts.append('本次查询没有访问其他员工数据，所有可见结果均限定在当前账号绑定的员工档案。')
    summary = ''.join(summary_parts)
    result = ExecutionResult(
        summary=summary,
        entities=_dedupe_entities(entities),
        widgets=widgets,
        session_id=ctx.session_id,
        trace=trace,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        error_code='permission_denied' if denied_topics and not ok_topics else None,
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _augment_tool_widgets(tool: str, params: Dict[str, Any], data: Dict[str, Any],
                          widgets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if tool != 'attendance_analysis':
        return widgets
    result = list(widgets or [])
    metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
    status_counts = metrics.get('statusCounts') if isinstance(metrics.get('statusCounts'), dict) else {}
    if status_counts and not any((w or {}).get('type') == 'status_badges' for w in result):
        result.append(W.status_badges([
            {
                'label': _attendance_status_label(status),
                'value': count,
                'status': 'success' if status == 'normal' else 'warning',
                'icon': 'fa-check' if status == 'normal' else 'fa-triangle-exclamation',
            }
            for status, count in status_counts.items()
        ], title='考勤状态口径'))
    if not any((w or {}).get('type') == 'source_citations' for w in result):
        month = metrics.get('month') or params.get('month') or business_now().strftime('%Y-%m')
        result.append({
            'type': 'source_citations',
            'title': '本次使用的系统记录',
            'sources': [
                {
                    'module': 'attendance_records',
                    'recordType': 'attendance_records',
                    'title': f'{month} 打卡记录 {metrics.get("totalRecords", 0)} 条',
                    'url': '/hrm/attendance-records',
                },
                {
                    'module': 'attendance_stats',
                    'recordType': 'attendance_stats',
                    'title': f'{month} 考勤统计汇总',
                    'url': '/attendance-stats',
                },
                {
                    'module': 'leave_requests',
                    'recordType': 'employee_requests',
                    'title': f'{month} 已批请假/加班/出差/补卡 {metrics.get("approvedRequests", 0)} 条',
                    'url': '/employee-requests',
                },
            ],
        })
    return result


def _prefix_widget_titles(widgets: List[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for widget in widgets or []:
        if not isinstance(widget, dict):
            continue
        item = dict(widget)
        title = item.get('title')
        if title:
            item['title'] = f'{prefix} - {title}'
        elif item.get('type') in {'metrics', 'table', 'bar', 'donut', 'status_badges'}:
            item['title'] = prefix
        table = item.get('table') if isinstance(item.get('table'), dict) else None
        if table and table.get('title'):
            item['table'] = {**table, 'title': f'{prefix} - {table.get("title")}'}
        out.append(item)
    return out


def _dedupe_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        key = (entity.get('type'), entity.get('id'), entity.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(entity)
        if len(out) >= 20:
            break
    return out


def _dedupe_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        key = (source.get('module'), source.get('recordType'), source.get('recordId') or source.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
        if len(out) >= 20:
            break
    return out


def _run_attendance_reminder_confirmation(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    if ctx.role not in PRIVILEGED_ROLES:
        return _forbidden('只有管理员或 HR 管理员可以基于考勤数据生成通知提醒。', ctx, frame)

    params = dict(frame.slots.get('params') or {})
    tool_plan = [
        ToolCallPlan(
            step_id='agentic_attendance_rank',
            tool='attendance_analysis',
            purpose='query',
            input=params,
            required=True,
            risk_level='low',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='agentic_notification_create',
            tool='notification_create',
            purpose='side_effect',
            input={'from': 'attendance_rank'},
            required=True,
            risk_level='high',
            cache_policy='none',
        ),
    ]
    decision = _decision_from_frame(frame, tool_plan)
    decision.requires_confirmation = True
    out = ToolExecutor().execute('attendance_analysis', params, ctx)
    data = out.get('data') or {}
    metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
    ranked = metrics.get('topRankedEmployees') if isinstance(metrics.get('topRankedEmployees'), list) else []
    if not out.get('ok'):
        return _not_found('考勤排名查询失败，暂时无法生成提醒草稿。', ctx, decision)
    if not ranked:
        month = params.get('month') or business_now().strftime('%Y-%m')
        return _not_found(f'{month} 没有查到迟到员工，无需生成提醒。', ctx, decision)

    month = params.get('month') or metrics.get('month') or business_now().strftime('%Y-%m')
    limit = min(frame.limit or 5, len(ranked))
    ranked = ranked[:limit]
    action_id = 'act_' + uuid.uuid4().hex[:12]
    table_rows = []
    tools = []
    for item in ranked:
        employee_id = item.get('employeeId') or item.get('id')
        employee = Employee.query.get(employee_id) if employee_id else None
        employee_name = item.get('employeeName') or (employee.name if employee else '未知员工')
        count = int(item.get('count') or 0)
        department = item.get('department') or (employee.department.name if employee and employee.department else '—')
        title = f'{month} 考勤迟到提醒 - {employee_name}'
        content = (
            f'{employee_name}，系统统计你在 {month} 有 {count} 次迟到记录。'
            '请及时核对考勤记录，如存在请假、外勤、补卡等合理原因，请在员工申请中补充说明；'
            '如无特殊原因，请注意后续出勤时间。'
        )
        table_rows.append({
            'employeeName': employee_name,
            'department': department,
            'jobTitle': item.get('jobTitle') or (employee.job_title if employee else '—'),
            'lateCount': count,
            'latestDate': item.get('latestDate') or '',
            'draftTitle': title,
        })
        tools.append({
            'tool': 'notification_create',
            'input': {
                'title': title,
                'content': content,
                'notice_type': 'hr',
                'link_url': '/hrm/attendance-records',
            },
        })

    summary = (
        f'已根据 {month} 考勤记录找出迟到最多的 {len(table_rows)} 人，并生成站内通知草稿。'
        f'确认后将写入通知中心 {len(tools)} 条 HR 提醒；未确认前不会发送。'
    )
    widgets = list(data.get('widgets') or [])
    widgets = _augment_tool_widgets('attendance_analysis', params, data, widgets)
    widgets.append(W.data_table([
        {'key': 'employeeName', 'label': '员工'},
        {'key': 'department', 'label': '部门'},
        {'key': 'jobTitle', 'label': '岗位'},
        {'key': 'lateCount', 'label': '迟到次数', 'align': 'right'},
        {'key': 'latestDate', 'label': '最近迟到'},
        {'key': 'draftTitle', 'label': '通知标题'},
    ], table_rows, title='待发送提醒草稿'))
    widget = W.confirmation_card('发送考勤迟到提醒', summary, action_id)
    widgets.append(widget)
    widgets.append({
        'type': 'source_citations',
        'title': '本次动作依据',
        'sources': [
            {
                'module': 'employees',
                'recordType': 'employees',
                'title': f'迟到提醒对象 {len(table_rows)} 人',
                'url': '/hrm/employees',
            },
            {
                'module': 'attendance_records',
                'recordType': 'attendance_records',
                'title': f'{month} 迟到考勤记录',
                'url': '/hrm/attendance-records',
            },
            {
                'module': 'attendance_stats',
                'recordType': 'attendance_stats',
                'title': f'{month} 考勤统计排名',
                'url': '/attendance-stats',
            },
            {
                'module': 'notifications',
                'recordType': 'notifications',
                'title': '确认后写入通知中心',
                'url': '/notifications',
            },
        ],
    })
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=widgets,
        session_id=ctx.session_id,
        trace=[_trace('attendance_analysis', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=True,
        actions=widget.get('actions') or [],
        answer={'content': summary, 'format': 'markdown'},
    )
    result._pending_action = {
        'id': action_id,
        'label': '发送考勤迟到提醒',
        'summary': summary,
        'tools': tools,
    }
    return result


def _run_approval_decision_confirmation(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    if ctx.role not in APPROVAL_DECISION_ROLES:
        return _forbidden('只有管理员、HR 管理员、经理或高管角色可以在 AI 助手中处理审批。', ctx, frame)

    params = dict(frame.slots.get('params') or {})
    action = params.get('action') or frame.action
    approval_id = str(params.get('approval_id') or '').strip()
    if not approval_id:
        target_index = params.get('target_index')
        approval = _resolve_approval_from_context(ctx, target_index)
        if approval:
            approval_id = approval.id
        elif target_index:
            approval = _nth_pending_approval(ctx, target_index)
            approval_id = approval.id if approval else ''
        else:
            approval = None
    else:
        approval = ApprovalInstance.query.get(approval_id)

    if not approval_id:
        return _clarify('请告诉我要处理哪条审批，例如“通过 demo-approval-overtime-lisi”或“把待我审批第一条通过”。', ctx, frame)
    if not approval:
        return _not_found(f'没有找到审批记录：{approval_id}。', ctx, _decision_from_frame(frame))
    if approval.status != 'pending':
        return _not_found(f'审批“{approval.title}”当前状态是 {approval.status or "未知"}，不能重复处理。', ctx, _decision_from_frame(frame))
    if approval.approver_id and approval.approver_id != ctx.user_id and ctx.role not in APPROVAL_OVERRIDE_ROLES:
        return _forbidden('这条审批不属于当前用户，不能在 AI 助手中处理。', ctx, frame)

    action_label = '通过' if action == 'approve' else '驳回'
    comment = str(params.get('comment') or '').strip() or f'AI 助手确认后审批{action_label}'
    action_id = 'act_' + uuid.uuid4().hex[:12]
    effect = _approval_effect_text(approval, action)
    summary = (
        f'准备审批{action_label}：{approval.title}（{approval.business_type or "未知业务"} / {approval.id}）。'
        f'{effect}确认后会写入审批记录、更新关联业务单据并记录操作日志；未确认前不会改数据。'
    )
    widgets = [
        W.status_badges([
            {'label': '审批状态', 'value': approval.status or '—', 'status': 'warning', 'icon': 'fa-hourglass-half'},
            {'label': '处理动作', 'value': action_label, 'status': 'success' if action == 'approve' else 'danger', 'icon': 'fa-check-double' if action == 'approve' else 'fa-ban'},
            {'label': '业务类型', 'value': approval.business_type or '—', 'status': 'info', 'icon': 'fa-diagram-project'},
        ], title='审批动作摘要'),
        W.data_table([
            {'key': 'field', 'label': '字段'},
            {'key': 'value', 'label': '值'},
        ], [
            {'field': '审批ID', 'value': approval.id},
            {'field': '标题', 'value': approval.title},
            {'field': '业务类型', 'value': approval.business_type or '—'},
            {'field': '业务ID', 'value': approval.business_id or '—'},
            {'field': '当前状态', 'value': approval.status or '—'},
            {'field': '审批意见', 'value': comment},
        ], title='待确认审批明细', exportable=False),
    ]
    confirm_widget = W.confirmation_card(f'审批{action_label}', summary, action_id)
    widgets.append(confirm_widget)
    widgets.append({
        'type': 'source_citations',
        'title': '本次动作依据',
        'sources': [
            {
                'module': 'approvals',
                'recordType': 'approval_instances',
                'recordId': approval.id,
                'title': approval.title,
                'url': '/approval-center',
            },
            {
                'module': _approval_business_module(approval.business_type),
                'recordType': approval.business_type or 'business_record',
                'recordId': approval.business_id,
                'title': f'关联业务单据：{approval.business_id or "—"}',
                'url': _approval_business_url(approval.business_type),
            },
            {
                'module': 'operation_logs',
                'recordType': 'operation_logs',
                'title': '确认后写入操作审计',
                'url': '/operation-logs',
            },
        ],
    })
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_approval_decision',
            tool='approval_decision',
            purpose='side_effect',
            input={'approval_id': approval.id, 'action': action, 'comment': comment},
            required=True,
            risk_level='high',
            cache_policy='none',
        )
    ])
    decision.requires_confirmation = True
    result = ExecutionResult(
        summary=summary,
        entities=[{
            'type': 'approval',
            'typeLabel': '审批',
            'icon': 'fa-check-double',
            'id': approval.id,
            'title': approval.title,
            'subtitle': approval.business_type or '',
            'meta': f'状态：{approval.status or "—"}',
            'url': '/approval-center',
        }],
        widgets=widgets,
        session_id=ctx.session_id,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=True,
        actions=confirm_widget.get('actions') or [],
        answer={'content': summary, 'format': 'markdown'},
    )
    result._pending_action = {
        'id': action_id,
        'label': f'审批{action_label}',
        'summary': summary,
        'tools': [{
            'tool': 'approval_decision',
            'input': {'approval_id': approval.id, 'action': action, 'comment': comment},
        }],
    }
    return result


def _attendance_status_label(status: Any) -> str:
    return {
        'normal': '正常',
        'late': '迟到',
        'early': '早退',
        'early_leave': '早退',
        'absent': '缺勤',
        'missing_card': '缺卡',
        'leave': '请假',
        'overtime': '加班',
        'business_trip': '出差',
        'travel': '出差',
        'makeup': '补卡',
        'makeup_card': '补卡',
    }.get(str(status or ''), str(status or '未知'))


def _request_type_label(value: Any) -> str:
    return {
        'leave': '请假',
        'overtime': '加班',
        'travel': '出差',
        'business_trip': '出差',
        'makeup': '补卡',
        'makeup_card': '补卡',
    }.get(str(value or ''), str(value or '申请'))


def _understand_with_llm(message: str, ctx: AssistantContext) -> Optional[TaskFrame]:
    """Ask the configured strong model for a structured tool frame.

    This is intentionally a fallback after deterministic high-confidence paths.
    The model can only select known tools; the runtime still executes through
    the existing ToolExecutor and frontend-compatible composer.
    """
    try:
        from . import llm_client

        raw = llm_client.json_chat_profile(
            'strong',
            [
                {
                    'role': 'system',
                    'content': (
                        '你是恒聘通 HRM 助手的语义解析器。把用户口语化请求映射为一个 JSON。'
                        '只能选择这些 tool：employee_search, organization_search, attendance_analysis, '
                        'performance_analysis, training_analysis, payroll_analysis, approval_search, '
                        'feedback_triage, dashboard_report, recruitment_search。'
                        'params 只能包含这些安全字段：keyword, department_id, status, view, business_type, '
                        'feedback_type, anomaly_only, month, scope, module, count_only, limit, date_range。'
                        '如果不适合任何工具，返回 {"tool": null}。'
                    ),
                },
                {
                    'role': 'user',
                    'content': (
                        f'用户角色：{ctx.role}\n'
                        f'用户问题：{message}\n'
                        '返回字段：intent, domain, tool, params, confidence。'
                    ),
                },
            ],
            temperature=0.05,
            max_tokens=500,
            timeout=12,
            use_case='intentReasoning',
            retry_once=False,
            ctx=ctx,
        )
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return None
    tool = raw.get('tool')
    if tool not in LLM_TOOL_INTENTS:
        return None
    domain, default_intent = LLM_TOOL_INTENTS[tool]
    params = _sanitize_llm_params(tool, raw.get('params') or {})
    if params is None:
        return None
    intent = str(raw.get('intent') or default_intent)
    if not intent or intent == 'None':
        intent = default_intent
    confidence = raw.get('confidence', 0.72)
    try:
        confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        confidence = 0.72
    if confidence < 0.55:
        return None
    return TaskFrame(
        domain=str(raw.get('domain') or domain),
        intent=intent,
        action='tool_query',
        entity_type=domain,
        confidence=confidence,
        reason='agentic_llm_structured_fallback',
        slots={'tool': tool, 'params': params},
    )


def _sanitize_llm_params(tool: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(params, dict):
        return {}
    allowed = {
        'keyword', 'department_id', 'status', 'view', 'business_type',
        'feedback_type', 'anomaly_only', 'month', 'scope', 'module',
        'count_only', 'limit', 'date_range',
    }
    cleaned: Dict[str, Any] = {}
    for key, value in params.items():
        if key not in allowed or value in (None, ''):
            continue
        if key == 'limit':
            try:
                cleaned[key] = max(1, min(int(value), MAX_LIMIT))
            except (TypeError, ValueError):
                continue
        elif key in {'count_only', 'anomaly_only'}:
            cleaned[key] = bool(value)
        elif key == 'date_range':
            cleaned[key] = value if isinstance(value, dict) else {}
        else:
            cleaned[key] = str(value)
    if tool == 'attendance_analysis' and 'month' not in cleaned:
        month = _extract_month(str(params))
        if month:
            cleaned['month'] = month
    if tool == 'dashboard_report':
        cleaned.setdefault('scope', 'system')
    if tool == 'approval_search':
        cleaned.setdefault('view', 'pending')
    if tool == 'recruitment_search':
        cleaned.setdefault('module', 'all')
    cleaned.setdefault('limit', 20)
    return cleaned


def _run_recruitment_search(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    params: Dict[str, Any] = dict(frame.slots.get('params') or {})
    params.setdefault('module', frame.module)
    params.setdefault('limit', frame.limit)
    if frame.status:
        params['status'] = frame.status
    if frame.count_only:
        params['count_only'] = True
    if frame.recent_days:
        params['date_range'] = {'recent_days': frame.recent_days}

    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_recruitment_search',
            tool='recruitment_search',
            purpose='query',
            input=params,
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    tool_executor = ToolExecutor()
    output = tool_executor.execute('recruitment_search', params, ctx)
    data = output.get('data') or {}
    entities = data.get('entities') or []
    widgets = data.get('widgets') or []
    rows_count = int(output.get('rows_count') or 0)
    summary = _recruitment_summary(frame, rows_count, entities)

    trace = [_trace('recruitment_search', output, rows_count)]
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        widgets=widgets,
        session_id=ctx.session_id,
        trace=trace,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'text'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_person_lookup(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    name = frame.name
    if not name:
        return _clarify('请告诉我要查询哪位候选人的简历。', ctx, frame)

    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_candidate_evidence',
            tool='candidate_evidence_bundle',
            purpose='load_context',
            input={'keyword': name},
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('candidate_evidence_bundle', {'keyword': name}, ctx)
    data = out.get('data') or {}
    facts = data.get('facts') or {}
    if not out.get('ok') or not facts:
        return _not_found(f'系统内暂未找到“{name}”的简历或候选人记录。', ctx, decision)

    entities = data.get('entities') or []
    summary = _resume_lookup_summary(facts)
    widgets = list(data.get('widgets') or []) + _source_widgets(facts)
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        widgets=widgets,
        session_id=ctx.session_id,
        trace=[_trace('candidate_evidence_bundle', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'text'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_person_assessment(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    name = frame.name or _last_focus(ctx).get('name')
    evidence_params = {
        key: value
        for key, value in dict(frame.slots.get('params') or {}).items()
        if key in {'candidate_id', 'resume_id'} and value
    }
    if not name and not evidence_params:
        return _clarify('请告诉我要分析哪位候选人，或先查询一份简历。', ctx, frame)
    if not evidence_params:
        evidence_params = {'keyword': name}

    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_candidate_evidence',
            tool='candidate_evidence_bundle',
            purpose='load_context',
            input=evidence_params,
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('candidate_evidence_bundle', evidence_params, ctx)
    data = out.get('data') or {}
    facts = data.get('facts') or {}
    if not out.get('ok') or not facts:
        return _not_found(f'系统内暂未找到“{name}”的可分析记录。', ctx, decision)

    summary = _assessment_summary(facts)
    widgets = list(data.get('widgets') or []) + _source_widgets(facts)
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=widgets,
        session_id=ctx.session_id,
        trace=[_trace('candidate_evidence_bundle', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_recruitment_match(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    keyword = frame.name or _extract_recruitment_job_keyword(message)
    if not keyword:
        return _clarify('请告诉我要对比哪个岗位的候选人。', ctx, frame)

    params = {'keyword': keyword, 'limit': frame.limit or 8}
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_recruitment_match_matrix',
            tool='recruitment_match_matrix',
            purpose='load_context',
            input=params,
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('recruitment_match_matrix', params, ctx)
    data = out.get('data') or {}
    if not out.get('ok'):
        return _not_found(f'招聘匹配矩阵生成失败：{out.get("error") or "未知错误"}。', ctx, decision)
    summary = str(data.get('summary_hint') or '').strip()
    if not summary:
        summary = f'已生成“{keyword}”岗位候选人匹配矩阵。'
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=data.get('widgets') or [],
        session_id=ctx.session_id,
        trace=[_trace('recruitment_match_matrix', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result, data.get('workset_entities') or None)
    return result


def _run_employee_change_impact(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    if ctx.role not in EMPLOYEE_CHANGE_ROLES:
        return _forbidden('只有管理员、HR 管理员或管理角色可以发起员工异动影响分析。', ctx, frame)
    name = frame.name
    if not name:
        return _clarify('请告诉我要分析哪位员工的异动影响。', ctx, frame)
    target_department = frame.slots.get('params', {}).get('target_department') or _extract_target_department(message)
    if not target_department:
        return _clarify('请补充目标部门，例如“把李四调到研发部”。', ctx, frame)
    target_position = frame.slots.get('params', {}).get('target_position') or _extract_target_position(message, target_department)

    action_id = 'act_' + uuid.uuid4().hex[:12]
    params = {
        'keyword': name,
        'target_department': target_department,
        'target_position': target_position,
        'action_id': action_id,
    }
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_employee_change_impact',
            tool='employee_change_impact',
            purpose='load_context',
            input=params,
            required=True,
            risk_level='medium',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='agentic_employee_change_submit',
            tool='employee_change_submit',
            purpose='side_effect',
            input={'from': 'employee_change_impact'},
            required=False,
            risk_level='high',
            cache_policy='none',
        ),
    ])
    decision.requires_confirmation = True
    out = ToolExecutor().execute('employee_change_impact', params, ctx)
    data = out.get('data') or {}
    if not out.get('ok'):
        return _not_found(f'员工异动影响分析失败：{out.get("error") or "未知错误"}。', ctx, decision)
    summary = str(data.get('summary_hint') or '').strip() or f'已分析 {name} 调岗到 {target_department} 的影响。'
    widget_actions = []
    for widget in data.get('widgets') or []:
        if isinstance(widget, dict) and widget.get('type') == 'confirmation_card':
            widget_actions = widget.get('actions') or []
            break
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=data.get('widgets') or [],
        session_id=ctx.session_id,
        trace=[_trace('employee_change_impact', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=True,
        actions=widget_actions,
        answer={'content': summary, 'format': 'markdown'},
    )
    result._pending_action = {
        'id': action_id,
        'label': '提交员工异动审批',
        'summary': f'{name} 调岗到 {target_department} 的影响已分析，确认后将提交待审批异动申请；审批通过前不会修改员工档案。',
        'tools': [{
            'tool': 'employee_change_submit',
            'input': {
                'employee_id': data.get('facts', {}).get('employee_id'),
                'keyword': name,
                'target_department_id': data.get('facts', {}).get('target_department_id'),
                'target_department': data.get('facts', {}).get('target_department_name') or target_department,
                'target_position': (
                    data.get('facts', {}).get('target_position_title')
                    or data.get('facts', {}).get('target_position')
                    or target_position
                ),
                'effective_date': business_now().date().isoformat(),
                'reason': (
                    f'AI 助手影响分析确认后提交：{name} 调岗到 '
                    f'{data.get("facts", {}).get("target_department_name") or target_department}。'
                ),
                'action_id': action_id,
            },
        }],
    }
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_employee_salary_adjustment_impact(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    if ctx.role not in EMPLOYEE_CHANGE_ROLES:
        return _forbidden('只有管理员、HR 管理员或管理角色可以发起调薪影响分析。', ctx, frame)
    name = frame.name
    if not name:
        return _clarify('请告诉我要给哪位员工发起调薪。', ctx, frame)
    salary_delta = frame.slots.get('params', {}).get('salary_adjustment') or _extract_salary_adjustment_amount(message)
    if not salary_delta:
        return _clarify('请补充调薪金额，例如“给张三调薪 2000 元”。', ctx, frame)
    salary_delta_text = _format_salary_adjustment_amount(salary_delta)

    action_id = 'act_' + uuid.uuid4().hex[:12]
    params = {'keyword': name, 'salary_adjustment': salary_delta_text, 'action_id': action_id}
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_salary_adjustment_impact',
            tool='employee_salary_adjustment_impact',
            purpose='load_context',
            input=params,
            required=True,
            risk_level='medium',
            cache_policy='session',
        ),
        ToolCallPlan(
            step_id='agentic_employee_change_submit',
            tool='employee_change_submit',
            purpose='side_effect',
            input={'from': 'salary_adjustment_impact'},
            required=False,
            risk_level='high',
            cache_policy='none',
        ),
    ])
    decision.requires_confirmation = True
    out = ToolExecutor().execute('employee_salary_adjustment_impact', params, ctx)
    data = out.get('data') or {}
    if not out.get('ok'):
        return _not_found(f'员工调薪影响分析失败：{out.get("error") or "未知错误"}。', ctx, decision)
    facts = data.get('facts') or {}
    if not facts.get('employee_id'):
        return _not_found(str(data.get('summary_hint') or f'未找到员工“{name}”。'), ctx, decision)
    summary = str(data.get('summary_hint') or '').strip() or f'已分析 {name} 调薪 {salary_delta_text} 元的影响。'
    widget_actions = []
    for widget in data.get('widgets') or []:
        if isinstance(widget, dict) and widget.get('type') == 'confirmation_card':
            widget_actions = widget.get('actions') or []
            break
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=data.get('widgets') or [],
        session_id=ctx.session_id,
        trace=[_trace('employee_salary_adjustment_impact', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=True,
        actions=widget_actions,
        answer={'content': summary, 'format': 'markdown'},
    )
    result._pending_action = {
        'id': action_id,
        'label': '提交调薪审批',
        'summary': f'{name} 调薪 {salary_delta_text} 元的影响已分析，确认后将提交待审批调薪异动；审批通过前不会修改薪资档案。',
        'tools': [{
            'tool': 'employee_change_submit',
            'input': {
                'employee_id': facts.get('employee_id'),
                'keyword': name,
                'target_department_id': facts.get('department_id'),
                'target_department': facts.get('department_name'),
                'salary_adjustment': facts.get('salary_adjustment') or salary_delta_text,
                'effective_date': business_now().date().isoformat(),
                'reason': (
                    f'AI 助手调薪影响分析确认后提交：{name} 调薪 '
                    f'{facts.get("salary_adjustment") or salary_delta_text} 元。'
                ),
                'action_id': action_id,
            },
        }],
    }
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_payroll_performance_link(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    params = dict(frame.slots.get('params') or {})
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_payroll_performance_link',
            tool='payroll_performance_link',
            purpose='load_context',
            input=params,
            required=True,
            risk_level='medium',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('payroll_performance_link', params, ctx)
    data = out.get('data') or {}
    if not out.get('ok'):
        return _not_found(f'薪资绩效联动分析失败：{out.get("error") or "未知错误"}。', ctx, decision)
    summary = str(data.get('summary_hint') or '').strip() or '已完成薪资、绩效与考勤联动分析。'
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=data.get('widgets') or [],
        session_id=ctx.session_id,
        trace=[_trace('payroll_performance_link', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_employee_attendance_evidence(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    name = frame.name
    if not name:
        return _clarify('请告诉我要分析哪位员工的考勤异常。', ctx, frame)
    params = dict(frame.slots.get('params') or {})
    params['keyword'] = name
    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_employee_attendance_evidence',
            tool='employee_attendance_evidence',
            purpose='load_context',
            input=params,
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('employee_attendance_evidence', params, ctx)
    data = out.get('data') or {}
    if not out.get('ok'):
        return _not_found(f'员工考勤证据分析失败：{out.get("error") or "未知错误"}。', ctx, decision)
    summary = str(data.get('summary_hint') or '').strip() or f'已分析 {name} 的考勤异常证据。'
    result = ExecutionResult(
        summary=summary,
        entities=data.get('entities') or [],
        widgets=data.get('widgets') or [],
        session_id=ctx.session_id,
        trace=[_trace('employee_attendance_evidence', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def _run_ambiguous_person_clarify(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    keyword = frame.name or _extract_ambiguous_person_keyword(message) or '这个人'
    decision = _decision_from_frame(frame)
    decision.task_type = 'clarification'
    decision.requires_confirmation = False
    question = f'“{keyword}”不够明确。你是想查员工档案、候选人/简历，还是考勤/绩效等具体模块？'
    widget = W.clarification(question, [
        {'label': '员工档案', 'payload': f'查员工 {keyword}'},
        {'label': '候选人/简历', 'payload': f'查候选人 {keyword}'},
        {'label': '考勤情况', 'payload': f'查 {keyword} 考勤'},
        {'label': '绩效薪资', 'payload': f'查 {keyword} 绩效薪资'},
    ], message)
    return ExecutionResult(
        summary=question,
        widgets=[widget],
        session_id=ctx.session_id,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=False,
        answer={'content': question, 'format': 'text'},
    )


def _run_interview_confirmation(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    name = frame.name or _last_focus(ctx).get('name')
    workset_item = _resolve_candidate_workset_item(message, ctx)
    if workset_item and not frame.name:
        name = workset_item.get('title') or name
    if not name and not workset_item:
        return _clarify('请告诉我要给哪位候选人安排面试。', ctx, frame)
    if not frame.schedule_at:
        return _clarify('请补充面试日期和时间。', ctx, frame)

    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_interview_create',
            tool='interview_create',
            purpose='side_effect',
            input={'request_text': message},
            required=True,
            risk_level='high',
            cache_policy='none',
        )
    ])
    decision.requires_confirmation = True
    evidence_args: Dict[str, Any] = {'keyword': name}
    if workset_item:
        if workset_item.get('entity_type') == 'candidate':
            evidence_args = {'candidate_id': workset_item.get('entity_id')}
        elif workset_item.get('entity_type') == 'resume':
            evidence_args = {'resume_id': workset_item.get('entity_id')}
    out = ToolExecutor().execute('candidate_evidence_bundle', evidence_args, ctx)
    facts = (out.get('data') or {}).get('facts') or {}
    if not out.get('ok') or not facts:
        return _not_found(f'系统内暂未找到“{name}”的候选人记录，无法安排面试。', ctx, decision)

    resume = facts.get('resume') if isinstance(facts.get('resume'), dict) else {}
    job = facts.get('job') if isinstance(facts.get('job'), dict) else {}
    if not resume.get('resume_id') or not job.get('job_id'):
        return _clarify('已识别候选人，但缺少关联简历或岗位，无法创建面试安排。', ctx, frame)

    action_id = 'act_' + uuid.uuid4().hex[:12]
    display_time = frame.schedule_at.replace('T', ' ')[:16]
    summary = f'安排面试：{facts.get("name") or name}；时间：{display_time}。确认后将在系统中创建记录。'
    widget = W.confirmation_card('安排面试', summary, action_id)
    result = ExecutionResult(
        summary=summary,
        entities=(out.get('data') or {}).get('entities') or [],
        widgets=[widget],
        session_id=ctx.session_id,
        trace=[_trace('candidate_evidence_bundle', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=True,
        actions=widget.get('actions') or [],
        answer={'content': summary, 'format': 'text'},
    )
    result._pending_action = {
        'id': action_id,
        'label': '安排面试',
        'summary': summary,
        'tools': [{
            'tool': 'interview_create',
            'input': {
                'resume_id': resume.get('resume_id'),
                'job_id': job.get('job_id'),
                'scheduled_at': frame.schedule_at,
                'notes': f'由聘小犀根据对话确认创建：{facts.get("name") or name}面试',
            },
        }],
    }
    return result


def _run_employee_profile(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    name = frame.name or _last_focus(ctx).get('name')
    if not name:
        return _clarify('请告诉我要查看哪位员工的画像。', ctx, frame)

    decision = _decision_from_frame(frame, [
        ToolCallPlan(
            step_id='agentic_employee_evidence',
            tool='employee_evidence_bundle',
            purpose='load_context',
            input={'keyword': name},
            required=True,
            risk_level='low',
            cache_policy='session',
        )
    ])
    out = ToolExecutor().execute('employee_evidence_bundle', {'keyword': name}, ctx)
    data = out.get('data') or {}
    facts = data.get('facts') or {}
    if not out.get('ok') or not facts:
        return _not_found(f'系统内暂未找到“{name}”的员工画像证据。', ctx, decision)

    entities = data.get('entities') or []
    widgets = _employee_profile_widgets(facts)
    if entities:
        widgets.insert(1, W.entity_cards(entities, title='生命周期关联记录'))
    summary = _employee_profile_summary(facts)
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        widgets=widgets,
        session_id=ctx.session_id,
        trace=[_trace('employee_evidence_bundle', out, int(out.get('rows_count') or 0))],
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'markdown'},
    )
    _record_workset_if_needed(message, ctx, result)
    return result


def persist_turn(message: str, ctx: AssistantContext, result: ExecutionResult) -> None:
    """Persist a result produced by this runtime using the existing session store."""
    apply_response_contract(result, ctx, message=message)
    metadata = {
        'router': result.router.to_dict() if result.router else None,
        'routeDecision': result.route_decision.to_dict() if result.route_decision else None,
        'routeTrack': result.route_decision.route_track if result.route_decision else None,
        'taskType': result.route_decision.task_type if result.route_decision else None,
        'errorCode': result.error_code,
        'fallbackUsed': False,
        'usedSkills': list(dict.fromkeys([s.skill for s in result.trace if s.skill])),
        'riskLevel': result.router.risk_level if result.router else 'low',
        'requiresConfirmation': result.requires_confirmation,
        'routePath': 'agentic_runtime',
        'worksets': list(result.worksets or []),
        'pendingAction': getattr(result, '_pending_action', None),
        'resolvedActionId': getattr(result, '_resolved_action_id', None),
        'lastFocus': _focus_from_result(result),
        'agenticRuntime': True,
    }
    saved = memory.save_turn(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        question=message,
        summary=result.summary or '',
        entity_count=len(result.entities or []),
        metadata=metadata,
        request_id=ctx.request_id,
        entities=result.entities or [],
        widgets=result.widgets or [],
        actions=result.actions or [],
        worksets=result.worksets or [],
        answer=result.answer,
        schema_version=result.schema_version,
        render_blocks=result.render_blocks or [],
        copilot=result.copilot or {},
        client_context=result.client_context or {},
    )
    result.session_id = saved or ctx.session_id


def _decision_from_frame(frame: TaskFrame, tool_plan: Optional[List[ToolCallPlan]] = None) -> RouteDecision:
    task_type = 'action' if frame.needs_confirmation else 'generation' if frame.needs_evidence and frame.action == 'assess' else 'data_query'
    route_track = 'A_DATA_ACTION'
    if frame.action == 'assess':
        route_track = 'B_GENERATION'
    decision = RouteDecision(
        task_type=task_type,
        route_track=route_track,
        intent=frame.intent,
        confidence=frame.confidence,
        risk_level='high' if frame.needs_confirmation else 'low',
        required_context=['candidate_evidence'] if frame.needs_evidence else [],
        tool_plan=tool_plan or [],
        generation_plan=GenerationPlan(template_id='person_assessment') if frame.action == 'assess' else None,
        requires_confirmation=frame.needs_confirmation,
        reason=frame.reason,
    )
    return decision


def _trace(tool: str, output: Dict[str, Any], rows_count: int) -> ExecutionStep:
    return ExecutionStep(
        step_id=tool,
        type='skill',
        skill=tool,
        status='ok' if output.get('ok') else 'error',
        rows_count=rows_count,
        error=output.get('error') or None,
    )


def _record_workset_if_needed(
    message: str,
    ctx: AssistantContext,
    result: ExecutionResult,
    entities_override: Optional[List[Dict[str, Any]]] = None,
) -> None:
    entities = [
        e for e in ((entities_override if entities_override is not None else result.entities) or [])
        if isinstance(e, dict) and e.get('type') in ('candidate', 'employee', 'resume', 'job')
    ]
    if not entities:
        return
    ws = workset_store.create_workset_from_entities(
        ctx.session_id,
        ctx.user_id,
        message[:80] or '助手结果集',
        entities,
    )
    if ws:
        result.worksets.append(ws)
        result.widgets.append({'type': 'workset_summary', 'title': ws.get('label'), 'workset': ws})


def _focus_from_result(result: ExecutionResult) -> Optional[Dict[str, Any]]:
    for ent in result.entities or []:
        if not isinstance(ent, dict):
            continue
        if ent.get('type') in ('candidate', 'resume', 'employee'):
            return {
                'entity_type': ent.get('type'),
                'entity_id': ent.get('id'),
                'name': ent.get('title'),
            }
    return None


def _last_focus(ctx: AssistantContext) -> Dict[str, Any]:
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        focus = meta.get('lastFocus') if isinstance(meta.get('lastFocus'), dict) else None
        if focus:
            return focus
        entities = entry.get('entities') if isinstance(entry.get('entities'), list) else []
        for ent in entities:
            if isinstance(ent, dict) and ent.get('type') in ('candidate', 'resume', 'employee'):
                return {'entity_type': ent.get('type'), 'entity_id': ent.get('id'), 'name': ent.get('title')}
    return {}


def _resolve_candidate_workset_item(message: str, ctx: AssistantContext) -> Optional[Dict[str, Any]]:
    if not re.search(r'(第\s*[一二两三四五六七八九十\d]+|第二|第一|第三|上面|刚才|列表|这些|这几|排名)', message or ''):
        return None
    try:
        resolved = workset_store.resolve_mention(message, ctx.session_id)
    except Exception:
        return None
    if not isinstance(resolved, dict):
        return None
    item = resolved.get('item')
    if resolved.get('kind') == 'item' and isinstance(item, dict):
        if item.get('entity_type') in {'candidate', 'resume'}:
            return item
        return None
    ws = resolved.get('workset') if isinstance(resolved.get('workset'), dict) else {}
    items = [row for row in (ws.get('items') or []) if isinstance(row, dict)]
    for row in items:
        if row.get('entity_type') in {'candidate', 'resume'}:
            return row
    return None


def _execute_pending_action(
    message: str,
    ctx: AssistantContext,
    verb: str,
    action_id: Optional[str],
) -> ExecutionResult:
    decision = RouteDecision(
        task_type='action',
        route_track='CONFIRMED_ACTION',
        intent='execute_pending_action',
        confidence=1.0,
        risk_level='high',
        reason='agentic_chat_confirmation',
    )
    pending = memory.get_pending_action(ctx.user_id, ctx.session_id, action_id)
    if not pending:
        return ExecutionResult(
            summary='没有找到可执行的待确认动作，可能已完成或已过期。',
            session_id=ctx.session_id,
            route_decision=decision,
            router=route_decision_to_router_result(decision),
        )
    if verb == '取消动作':
        result = ExecutionResult(
            summary=f'已取消：{pending.get("label") or pending.get("summary") or "待确认动作"}。',
            session_id=ctx.session_id,
            route_decision=decision,
            router=route_decision_to_router_result(decision),
            answer={'content': f'已取消：{pending.get("label") or pending.get("summary") or "待确认动作"}。', 'format': 'text'},
        )
        result._resolved_action_id = pending.get('id')
        return result

    outputs = []
    entities: List[Dict[str, Any]] = []
    trace: List[ExecutionStep] = []
    allowed_tools = {
        'interview_create',
        'followup_task_create',
        'notification_create',
        'approval_decision',
        'employee_change_submit',
    }
    for plan in pending.get('tools') or []:
        if not isinstance(plan, dict):
            continue
        tool = plan.get('tool')
        if tool not in allowed_tools:
            result = ExecutionResult(
                summary=f'不支持的确认动作：{tool or "未知工具"}。',
                session_id=ctx.session_id,
                trace=trace,
                route_decision=decision,
                router=route_decision_to_router_result(decision),
                error_code='confirmed_action_rejected',
                answer={'content': f'不支持的确认动作：{tool or "未知工具"}。', 'format': 'text'},
            )
            result._resolved_action_id = pending.get('id')
            return result
        out = ToolExecutor().execute(tool, plan.get('input') or {}, ctx)
        outputs.append(out)
        trace.append(_trace(tool, out, int(out.get('rows_count') or 0)))
        if out.get('ok'):
            entities.extend((out.get('data') or {}).get('entities') or [])
    ok_count = sum(1 for out in outputs if out.get('ok'))
    summary = f'已执行：{pending.get("label") or "待确认动作"}，成功 {ok_count}/{len(outputs)} 项。'
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        session_id=ctx.session_id,
        trace=trace,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': summary, 'format': 'text'},
    )
    result._resolved_action_id = pending.get('id')
    return result


def _recruitment_summary(frame: TaskFrame, rows_count: int, entities: List[Dict[str, Any]]) -> str:
    if frame.intent == 'recruitment.jobs.open.count':
        return f'目前有 {rows_count} 个招聘中的岗位。'
    if frame.intent == 'recruitment.jobs.open.list':
        if not rows_count:
            return '目前没有查到招聘中的岗位。'
        titles = [str(e.get('title')) for e in entities if e.get('title')][:5]
        detail = f'，包括：{"、".join(titles)}' if titles else ''
        return f'目前有 {rows_count} 个招聘中的岗位{detail}。'
    if frame.intent == 'recruitment.resumes.count':
        return f'当前简历共有 {rows_count} 份。'
    if frame.intent == 'recruitment.candidates.count':
        return f'当前候选人共有 {rows_count} 人。'
    if frame.intent == 'recruitment.resumes.recent.list':
        return f'最近 {frame.recent_days or 30} 天收到 {rows_count} 份简历。' if rows_count else f'最近 {frame.recent_days or 30} 天没有查到简历。'
    if frame.intent == 'recruitment.candidates.recent.list':
        return f'最近 {frame.recent_days or 30} 天新增 {rows_count} 位候选人。' if rows_count else f'最近 {frame.recent_days or 30} 天没有查到候选人。'
    return f'已返回 {rows_count} 条招聘数据。'


def _resume_lookup_summary(facts: Dict[str, Any]) -> str:
    name = facts.get('name') or (facts.get('resume') or {}).get('candidate_name') or '候选人'
    resume = facts.get('resume') if isinstance(facts.get('resume'), dict) else {}
    job = facts.get('job') if isinstance(facts.get('job'), dict) else {}
    score = resume.get('score')
    pieces = [f'{name} 的简历已找到']
    if job.get('title'):
        pieces.append(f'应聘岗位：{job["title"]}')
    if score is not None:
        pieces.append(f'AI评分：{score}分')
    if resume.get('summary'):
        pieces.append(str(resume.get('summary')))
    return '；'.join(pieces) + '。'


def _assessment_summary(facts: Dict[str, Any]) -> str:
    name = facts.get('name') or (facts.get('resume') or {}).get('candidate_name') or '候选人'
    resume = facts.get('resume') if isinstance(facts.get('resume'), dict) else {}
    candidate = facts.get('candidate') if isinstance(facts.get('candidate'), dict) else {}
    job = facts.get('job') if isinstance(facts.get('job'), dict) else {}
    score = resume.get('score')
    match_degree = resume.get('match_degree')
    strengths = resume.get('strengths') or []
    weaknesses = resume.get('weaknesses') or []
    focus = resume.get('interview_focus') or []
    lines = [f'基于系统记录看，{name}整体值得推进。']
    if job.get('title'):
        lines.append(f'- 关联岗位：{job.get("title")}')
    if score is not None:
        lines.append(f'- 简历评分：{score} 分')
    if match_degree is not None:
        lines.append(f'- 岗位匹配度：{match_degree}%')
    if candidate.get('status'):
        lines.append(f'- 当前进度：{candidate.get("status")}')
    if resume.get('summary'):
        lines.append(f'- 概览：{resume.get("summary")}')
    if strengths:
        lines.append(f'- 主要亮点：{"；".join(str(v) for v in strengths[:3])}')
    if weaknesses:
        lines.append(f'- 需要复核：{"；".join(str(v) for v in weaknesses[:3])}')
    if focus:
        lines.append(f'- 面试重点：{"；".join(str(v) for v in focus[:3])}')
    lines.append('- 建议：优先进入下一轮面试，并围绕上述风险点做针对性验证。')
    return '\n'.join(lines)


def _employee_profile_summary(facts: Dict[str, Any]) -> str:
    employee = facts.get('employee') if isinstance(facts.get('employee'), dict) else {}
    name = facts.get('name') or employee.get('name') or '该员工'
    candidates = facts.get('candidates') if isinstance(facts.get('candidates'), list) else []
    resumes = facts.get('resumes') if isinstance(facts.get('resumes'), list) else []
    jobs = facts.get('jobs') if isinstance(facts.get('jobs'), list) else []
    interviews = facts.get('interviews') if isinstance(facts.get('interviews'), list) else []
    offers = facts.get('offers') if isinstance(facts.get('offers'), list) else []
    onboarding_tasks = facts.get('onboarding_tasks') if isinstance(facts.get('onboarding_tasks'), list) else []
    contracts = facts.get('contracts') if isinstance(facts.get('contracts'), list) else []
    training = facts.get('training') if isinstance(facts.get('training'), list) else []
    payroll = facts.get('payroll') if isinstance(facts.get('payroll'), list) else []
    probations = facts.get('probations') if isinstance(facts.get('probations'), list) else []
    resignations = facts.get('resignations') if isinstance(facts.get('resignations'), list) else []
    attendance = facts.get('attendance') if isinstance(facts.get('attendance'), list) else []
    performance = facts.get('performance') if isinstance(facts.get('performance'), list) else []
    changes = facts.get('employee_changes') if isinstance(facts.get('employee_changes'), list) else []
    requests = facts.get('requests') if isinstance(facts.get('requests'), list) else []
    request_approvals = facts.get('request_approvals') if isinstance(facts.get('request_approvals'), list) else []
    change_approvals = facts.get('change_approvals') if isinstance(facts.get('change_approvals'), list) else []
    notifications = facts.get('notifications') if isinstance(facts.get('notifications'), list) else []
    salary_profile = facts.get('salary_profile') if isinstance(facts.get('salary_profile'), dict) else None
    abnormal = [row for row in attendance if isinstance(row, dict) and row.get('status') not in (None, '', 'normal')]
    approved_requests = [row for row in requests if isinstance(row, dict) and row.get('status') == 'approved']
    latest_perf = performance[0] if performance and isinstance(performance[0], dict) else {}
    lines = [
        f'### {name} 员工画像',
        f'- 档案：{employee.get("department") or "未填部门"} / {employee.get("job_title") or "未填岗位"} / 状态 {employee.get("status") or "未知"}',
        f'- 招聘源头：候选人 {len(candidates)} 条，简历 {len(resumes)} 份，岗位 {len(jobs)} 个，面试 {len(interviews)} 场，Offer {len(offers)} 条。',
        f'- 入职/合同/转正/离职：入职任务 {len(onboarding_tasks)} 条，合同 {len(contracts)} 份，转正 {len(probations)} 条，离职 {len(resignations)} 条。',
        f'- 培训与发薪：培训 {len(training)} 条，工资单 {len(payroll)} 条。',
        f'- 考勤：近 {len(attendance)} 条记录中异常 {len(abnormal)} 次。',
        f'- 请假/加班/出差/补卡：申请 {len(requests)} 条，已批 {len(approved_requests)} 条；关联审批 {len(request_approvals)} 条。',
    ]
    if latest_perf:
        lines.append(f'- 绩效：最近评估等级 {latest_perf.get("grade") or "—"}，得分 {latest_perf.get("finalScore") or latest_perf.get("final_score") or "—"}。')
    else:
        lines.append('- 绩效：暂无评估记录。')
    if salary_profile:
        lines.append(f'- 薪资：已读取薪资档案，状态 {salary_profile.get("status") or "—"}。')
    else:
        lines.append('- 薪资：当前角色无薪资档案权限或暂无薪资档案。')
    lines.append(f'- 异动：{len(changes)} 条异动记录，关联异动审批 {len(change_approvals)} 条。')
    if notifications:
        lines.append(f'- 通知：找到 {len(notifications)} 条相关提醒/归档通知，可作为流程触达证据。')
    if abnormal or changes:
        lines.append('- 风险提醒：建议结合异常考勤、最近绩效和异动原因做一次主管复盘。')
    return '\n'.join(lines)


def _employee_profile_widgets(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    employee = facts.get('employee') if isinstance(facts.get('employee'), dict) else {}
    candidates = facts.get('candidates') if isinstance(facts.get('candidates'), list) else []
    resumes = facts.get('resumes') if isinstance(facts.get('resumes'), list) else []
    jobs = facts.get('jobs') if isinstance(facts.get('jobs'), list) else []
    interviews = facts.get('interviews') if isinstance(facts.get('interviews'), list) else []
    offers = facts.get('offers') if isinstance(facts.get('offers'), list) else []
    onboarding_tasks = facts.get('onboarding_tasks') if isinstance(facts.get('onboarding_tasks'), list) else []
    contracts = facts.get('contracts') if isinstance(facts.get('contracts'), list) else []
    probations = facts.get('probations') if isinstance(facts.get('probations'), list) else []
    resignations = facts.get('resignations') if isinstance(facts.get('resignations'), list) else []
    attendance = facts.get('attendance') if isinstance(facts.get('attendance'), list) else []
    performance = facts.get('performance') if isinstance(facts.get('performance'), list) else []
    training = facts.get('training') if isinstance(facts.get('training'), list) else []
    changes = facts.get('employee_changes') if isinstance(facts.get('employee_changes'), list) else []
    requests = facts.get('requests') if isinstance(facts.get('requests'), list) else []
    request_approvals = facts.get('request_approvals') if isinstance(facts.get('request_approvals'), list) else []
    change_approvals = facts.get('change_approvals') if isinstance(facts.get('change_approvals'), list) else []
    notifications = facts.get('notifications') if isinstance(facts.get('notifications'), list) else []
    salary_profile = facts.get('salary_profile') if isinstance(facts.get('salary_profile'), dict) else None
    payroll = facts.get('payroll') if isinstance(facts.get('payroll'), list) else []
    field_citations = facts.get('field_citations') if isinstance(facts.get('field_citations'), dict) else {}
    abnormal = [row for row in attendance if isinstance(row, dict) and row.get('status') not in (None, '', 'normal')]
    approved_requests = [row for row in requests if isinstance(row, dict) and row.get('status') == 'approved']
    latest_perf = performance[0] if performance and isinstance(performance[0], dict) else {}
    employee_entity = {
        'type': 'employee',
        'typeLabel': '员工',
        'icon': 'fa-id-card',
        'id': employee.get('employee_id'),
        'title': facts.get('name') or employee.get('name') or '员工',
        'subtitle': ' · '.join(str(v) for v in [employee.get('employee_no'), employee.get('department'), employee.get('job_title')] if v),
        'meta': f'状态：{employee.get("status") or "—"}',
        'url': '/hrm/employees',
    }
    widgets: List[Dict[str, Any]] = [
        W.entity_cards([employee_entity], title='员工档案'),
        W.metric_cards([
            {'label': '招聘链路', 'value': f'{len(resumes)}/{len(interviews)}/{len(offers)}', 'color': 'teal', 'hint': '简历/面试/Offer'},
            {'label': '入职合同', 'value': f'{len(onboarding_tasks)}/{len(contracts)}', 'color': 'indigo', 'hint': '入职任务/合同'},
            {'label': '考勤记录', 'value': len(attendance), 'color': 'blue'},
            {'label': '考勤异常', 'value': len(abnormal), 'color': 'red' if abnormal else 'green'},
            {'label': '绩效记录', 'value': len(performance), 'color': 'purple'},
            {'label': '培训/工资单', 'value': f'{len(training)}/{len(payroll)}', 'color': 'emerald'},
            {'label': '异动记录', 'value': len(changes), 'color': 'orange' if changes else 'gray'},
            {'label': '离职记录', 'value': len(resignations), 'color': 'rose' if resignations else 'gray'},
        ], title='画像指标'),
        W.status_badges([
            {'label': '员工状态', 'value': employee.get('status') or '—', 'status': 'success' if employee.get('status') == 'active' else 'warning', 'icon': 'fa-id-card'},
            {'label': '部门', 'value': employee.get('department') or '—', 'status': 'neutral', 'icon': 'fa-sitemap'},
            {'label': '岗位', 'value': employee.get('job_title') or '—', 'status': 'neutral', 'icon': 'fa-briefcase'},
            {'label': '薪资档案', 'value': (salary_profile or {}).get('status') if salary_profile else '无权限/暂无', 'status': 'info' if salary_profile else 'warning', 'icon': 'fa-money-bill'},
        ], title='员工状态'),
    ]

    timeline_items: List[Dict[str, Any]] = []
    for resume in resumes[:3]:
        if isinstance(resume, dict):
            timeline_items.append({
                'time': (resume.get('createdAt') or '')[:10],
                'title': '简历录入',
                'description': resume.get('candidateName') or facts.get('name') or '',
                'status': 'info',
                'url': f'/resume-detail?resumeId={resume.get("id")}' if resume.get('id') else '/resume-manage',
            })
    for interview in interviews[:4]:
        if isinstance(interview, dict):
            timeline_items.append({
                'time': (interview.get('scheduledAt') or '')[:10],
                'title': '面试',
                'description': f'状态 {interview.get("status") or "—"}',
                'status': 'success' if interview.get('status') in {'completed', 'passed'} else 'warning',
                'url': f'/interview-detail?interviewId={interview.get("id")}' if interview.get('id') else '/interview-manage',
            })
    for offer in offers[:3]:
        if isinstance(offer, dict):
            timeline_items.append({
                'time': (offer.get('acceptedAt') or offer.get('onboardingDate') or offer.get('createdAt') or '')[:10],
                'title': 'Offer',
                'description': offer.get('title') or offer.get('status') or '',
                'status': 'success' if offer.get('status') in {'accepted', 'converted'} else 'warning',
                'url': '/hrm/offers',
            })
    for task in onboarding_tasks[:4]:
        if isinstance(task, dict):
            timeline_items.append({
                'time': (task.get('dueDate') or task.get('createdAt') or '')[:10],
                'title': f'入职任务：{task.get("name") or "任务"}',
                'description': task.get('taskType') or task.get('status') or '',
                'status': 'success' if task.get('status') == 'completed' else 'warning',
                'url': '/hrm/onboarding-tasks',
            })
    if employee.get('hire_date'):
        timeline_items.append({'time': employee.get('hire_date'), 'title': '入职', 'description': employee.get('job_title') or '', 'status': 'success', 'url': '/hrm/employees'})
    for contract in contracts[:3]:
        if isinstance(contract, dict):
            timeline_items.append({
                'time': (contract.get('startDate') or contract.get('createdAt') or '')[:10],
                'title': f'合同：{contract.get("contractNo") or contract.get("contractType") or "劳动合同"}',
                'description': f'状态 {contract.get("status") or "—"}',
                'status': 'success' if contract.get('status') in {'active', 'signed'} else 'warning',
                'url': '/hrm/contracts',
            })
    for train in training[:4]:
        if isinstance(train, dict):
            timeline_items.append({
                'time': (train.get('createdAt') or '')[:10],
                'title': f'培训：{train.get("courseName") or "培训记录"}',
                'description': train.get('result') or train.get('status') or '',
                'status': 'success' if train.get('status') in {'completed', 'passed'} else 'warning',
                'url': '/hrm/training-records',
            })
    for change in changes[:6]:
        if isinstance(change, dict):
            timeline_items.append({
                'time': change.get('effectiveDate') or change.get('createdAt') or '',
                'title': change.get('changeType') or '员工异动',
                'description': change.get('reason') or change.get('status') or '',
                'status': 'warning' if change.get('status') in {'draft', 'pending'} else 'success',
                'url': '/hrm/employee-changes',
            })
    for request in requests[:4]:
        if isinstance(request, dict):
            timeline_items.append({
                'time': (request.get('startTime') or request.get('createdAt') or '')[:10],
                'title': f'{_request_type_label(request.get("requestType"))}申请',
                'description': request.get('title') or request.get('reason') or request.get('status') or '',
                'status': 'success' if request.get('status') == 'approved' else 'warning',
                'url': '/employee-requests',
            })
    for approval in (request_approvals + change_approvals)[:6]:
        if isinstance(approval, dict):
            timeline_items.append({
                'time': (approval.get('submittedAt') or approval.get('createdAt') or '')[:10],
                'title': f'审批：{approval.get("title") or approval.get("businessType") or "流程"}',
                'description': f'状态 {approval.get("status") or "—"}',
                'status': 'success' if approval.get('status') == 'approved' else 'warning',
                'url': '/approval-center/records',
            })
    for notice in notifications[:4]:
        if isinstance(notice, dict):
            timeline_items.append({
                'time': (notice.get('createdAt') or '')[:10],
                'title': f'通知：{notice.get("title") or "相关提醒"}',
                'description': notice.get('content') or notice.get('noticeType') or '',
                'status': 'info' if notice.get('status') == 'read' else 'warning',
                'url': notice.get('linkUrl') or '/notifications',
            })
    for perf in performance[:3]:
        if isinstance(perf, dict):
            timeline_items.append({
                'time': perf.get('createdAt') or '',
                'title': f'绩效 {perf.get("grade") or "—"}',
                'description': perf.get('result') or perf.get('remark') or '',
                'status': 'success' if perf.get('grade') in {'A', 'B'} else 'warning',
                'url': '/performance-review',
            })
    for pay in payroll[:4]:
        if isinstance(pay, dict):
            timeline_items.append({
                'time': pay.get('payrollMonth') or (pay.get('createdAt') or '')[:10],
                'title': '发薪',
                'description': f'实发 {pay.get("netSalary") or "—"}，状态 {pay.get("status") or "—"}',
                'status': 'success' if pay.get('status') in {'paid', 'confirmed'} else 'warning',
                'url': '/hrm/payroll-records',
            })
    for probation in probations[:3]:
        if isinstance(probation, dict):
            timeline_items.append({
                'time': (probation.get('regularDate') or probation.get('applyDate') or probation.get('createdAt') or '')[:10],
                'title': '转正',
                'description': probation.get('result') or probation.get('status') or '',
                'status': 'success' if probation.get('status') in {'approved', 'completed'} else 'warning',
                'url': '/hrm/probations',
            })
    for resignation in resignations[:3]:
        if isinstance(resignation, dict):
            timeline_items.append({
                'time': (resignation.get('actualLeaveDate') or resignation.get('expectedLeaveDate') or resignation.get('applyDate') or resignation.get('createdAt') or '')[:10],
                'title': '离职',
                'description': resignation.get('reason') or resignation.get('status') or '',
                'status': 'danger' if resignation.get('status') in {'approved', 'completed'} else 'warning',
                'url': '/hrm/resignations',
            })
    if timeline_items:
        widgets.append(W.timeline(_sort_timeline_items(timeline_items), title='关键履历时间线'))

    lifecycle_rows = (
        _lifecycle_rows('候选人', candidates, '/hrm/candidates', 'name', 'status')
        + _lifecycle_rows('简历', resumes, '/resume-manage', 'candidateName', 'createdAt')
        + _lifecycle_rows('岗位', jobs, '/job-manage', 'title', 'status')
        + _lifecycle_rows('面试', interviews, '/interview-manage', 'scheduledAt', 'status')
        + _lifecycle_rows('Offer', offers, '/hrm/offers', 'title', 'status')
        + _lifecycle_rows('入职任务', onboarding_tasks, '/hrm/onboarding-tasks', 'name', 'status')
        + _lifecycle_rows('合同', contracts, '/hrm/contracts', 'contractNo', 'status')
        + _lifecycle_rows('培训', training, '/hrm/training-records', 'courseName', 'status')
        + _lifecycle_rows('工资单', payroll, '/hrm/payroll-records', 'payrollMonth', 'status')
        + _lifecycle_rows('转正', probations, '/hrm/probations', 'result', 'status')
        + _lifecycle_rows('离职', resignations, '/hrm/resignations', 'reason', 'status')
    )
    if lifecycle_rows:
        widgets.append(W.data_table([
            {'key': 'module', 'label': '模块'},
            {'key': 'title', 'label': '记录'},
            {'key': 'status', 'label': '状态/时间'},
            {'key': 'url', 'label': '入口'},
        ], lifecycle_rows, title='生命周期关联明细'))

    perf_rows = [
        {
            'cycle': row.get('cycleName') or row.get('cycleId') or '—',
            'grade': row.get('grade') or '—',
            'finalScore': row.get('finalScore') or '—',
            'status': row.get('status') or '—',
            'result': row.get('result') or row.get('remark') or '—',
        }
        for row in performance[:5]
        if isinstance(row, dict)
    ]
    if perf_rows:
        widgets.append(W.data_table([
            {'key': 'cycle', 'label': '周期'},
            {'key': 'grade', 'label': '等级'},
            {'key': 'finalScore', 'label': '得分'},
            {'key': 'status', 'label': '状态'},
            {'key': 'result', 'label': '结论'},
        ], perf_rows, title='绩效记录'))

    attendance_rows = [
        {
            'date': row.get('attendanceDate') or '—',
            'status': _attendance_status_label(row.get('status')),
            'workHours': row.get('workHours') or '—',
            'remark': row.get('remark') or '—',
        }
        for row in attendance[:8]
        if isinstance(row, dict)
    ]
    if attendance_rows:
        widgets.append(W.data_table([
            {'key': 'date', 'label': '日期'},
            {'key': 'status', 'label': '状态'},
            {'key': 'workHours', 'label': '工时'},
            {'key': 'remark', 'label': '说明'},
        ], attendance_rows, title='最近考勤'))

    if requests:
        widgets.append(W.status_badges([
            {'label': '申请记录', 'value': len(requests), 'status': 'info', 'icon': 'fa-calendar-check', 'hint': '请假/加班/出差/补卡记录'},
            {'label': '已批申请', 'value': len(approved_requests), 'status': 'success' if approved_requests else 'neutral', 'icon': 'fa-check'},
            {'label': '申请审批', 'value': len(request_approvals), 'status': 'info' if request_approvals else 'neutral', 'icon': 'fa-stamp'},
        ], title='申请关联'))
    if change_approvals or notifications:
        widgets.append(W.status_badges([
            {'label': '异动审批', 'value': len(change_approvals), 'status': 'warning' if any((row or {}).get('status') == 'pending' for row in change_approvals) else 'success', 'icon': 'fa-random'},
            {'label': '相关通知', 'value': len(notifications), 'status': 'info' if notifications else 'neutral', 'icon': 'fa-bell'},
        ], title='审批与通知触达'))

    widgets.append({
        'type': 'source_citations',
        'title': '本次使用的系统记录',
        'sources': [
            {'module': 'employees', 'recordType': 'employees', 'title': f'{facts.get("name") or "员工"} 档案', 'url': '/hrm/employees', 'fields': field_citations.get('employee') or []},
            {'module': 'candidates', 'recordType': 'candidates', 'title': f'候选人记录 {len(candidates)} 条', 'url': '/hrm/candidates', 'fields': field_citations.get('candidate') or []},
            {'module': 'resumes', 'recordType': 'resumes', 'title': f'简历记录 {len(resumes)} 份', 'url': '/resume-manage', 'fields': field_citations.get('resume') or []},
            {'module': 'jobs', 'recordType': 'jobs', 'title': f'关联岗位 {len(jobs)} 个', 'url': '/job-manage', 'fields': field_citations.get('job') or []},
            {'module': 'interviews', 'recordType': 'interviews', 'title': f'面试记录 {len(interviews)} 场', 'url': '/interview-manage', 'fields': field_citations.get('interview') or []},
            {'module': 'offers', 'recordType': 'offers', 'title': f'Offer记录 {len(offers)} 条', 'url': '/hrm/offers', 'fields': field_citations.get('offer') or []},
            {'module': 'onboarding_tasks', 'recordType': 'onboarding_tasks', 'title': f'入职任务 {len(onboarding_tasks)} 条', 'url': '/hrm/onboarding-tasks', 'fields': field_citations.get('onboarding') or []},
            {'module': 'contracts', 'recordType': 'contracts', 'title': f'合同记录 {len(contracts)} 份', 'url': '/hrm/contracts', 'fields': field_citations.get('contract') or []},
            {'module': 'attendance_records', 'recordType': 'attendance_records', 'title': f'考勤记录 {len(attendance)} 条', 'url': '/hrm/attendance-records', 'fields': field_citations.get('attendance') or []},
            {'module': 'performance_reviews', 'recordType': 'performance_reviews', 'title': f'绩效记录 {len(performance)} 条', 'url': '/performance-review', 'fields': field_citations.get('performance') or []},
            {'module': 'training_records', 'recordType': 'training_records', 'title': f'培训记录 {len(training)} 条', 'url': '/hrm/training-records', 'fields': field_citations.get('training') or []},
            {'module': 'salary_profiles', 'recordType': 'salary_profiles', 'title': '薪资档案' if salary_profile else '薪资档案（无权限或暂无）', 'url': '/salary-profiles', 'fields': field_citations.get('salary_profile') or []},
            {'module': 'payroll_records', 'recordType': 'payroll_records', 'title': f'工资单记录 {len(payroll)} 条', 'url': '/hrm/payroll-records', 'fields': field_citations.get('payroll') or []},
            {'module': 'probations', 'recordType': 'probations', 'title': f'转正记录 {len(probations)} 条', 'url': '/hrm/probations', 'fields': field_citations.get('probation') or []},
            {'module': 'employee_changes', 'recordType': 'employee_changes', 'title': f'异动记录 {len(changes)} 条', 'url': '/hrm/employee-changes', 'fields': field_citations.get('employee_changes') or []},
            {'module': 'resignations', 'recordType': 'resignations', 'title': f'离职记录 {len(resignations)} 条', 'url': '/hrm/resignations', 'fields': field_citations.get('resignation') or []},
            {'module': 'leave_requests', 'recordType': 'employee_requests', 'title': f'请假/加班/出差/补卡申请 {len(requests)} 条', 'url': '/employee-requests', 'fields': field_citations.get('requests') or []},
            {'module': 'approvals', 'recordType': 'approval_instances', 'title': f'员工相关审批 {len(request_approvals) + len(change_approvals)} 条', 'url': '/approval-center/records', 'fields': (field_citations.get('request_approvals') or []) + (field_citations.get('change_approvals') or [])},
            {'module': 'notifications', 'recordType': 'notifications', 'title': f'相关通知 {len(notifications)} 条', 'url': '/notifications', 'fields': field_citations.get('notifications') or []},
        ],
    })
    return widgets


def _sort_timeline_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        (item for item in items if isinstance(item, dict)),
        key=lambda item: str(item.get('time') or item.get('date') or ''),
    )


def _lifecycle_rows(
    module_label: str,
    records: List[Dict[str, Any]],
    url: str,
    title_key: str,
    status_key: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records[:4]:
        if not isinstance(record, dict):
            continue
        title = record.get(title_key) or record.get('title') or record.get('name') or record.get('id') or module_label
        status = record.get(status_key) or record.get('status') or record.get('createdAt') or '—'
        rows.append({
            'module': module_label,
            'title': title,
            'status': status,
            'url': url,
        })
    return rows


def _source_widgets(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources = facts.get('sources') if isinstance(facts.get('sources'), list) else []
    if not sources:
        return []
    field_citations = facts.get('field_citations') if isinstance(facts.get('field_citations'), dict) else {}
    source_defs = {
        'candidate': {
            'module': 'candidates',
            'recordType': 'candidate',
            'recordId': (facts.get('candidate') or {}).get('candidate_id') if isinstance(facts.get('candidate'), dict) else None,
            'title': f'{facts.get("name") or "候选人"} 候选人记录',
            'url': '/hrm/candidates',
        },
        'resume': {
            'module': 'resumes',
            'recordType': 'resume',
            'recordId': (facts.get('resume') or {}).get('resume_id') if isinstance(facts.get('resume'), dict) else None,
            'title': f'{facts.get("name") or "候选人"} 简历',
            'url': f'/resume-detail?resumeId={(facts.get("resume") or {}).get("resume_id")}' if isinstance(facts.get('resume'), dict) and (facts.get('resume') or {}).get('resume_id') else '/resume-manage',
        },
        'job': {
            'module': 'jobs',
            'recordType': 'job',
            'recordId': (facts.get('job') or {}).get('job_id') if isinstance(facts.get('job'), dict) else None,
            'title': (facts.get('job') or {}).get('title') if isinstance(facts.get('job'), dict) else '关联岗位',
            'url': f'/job-detail?jobId={(facts.get("job") or {}).get("job_id")}' if isinstance(facts.get('job'), dict) and (facts.get('job') or {}).get('job_id') else '/job-manage',
        },
        'interview': {
            'module': 'interviews',
            'recordType': 'interview',
            'title': '面试记录',
            'url': '/interview-manage',
        },
        'offer': {
            'module': 'offers',
            'recordType': 'offer',
            'title': 'Offer记录',
            'url': '/offer-manage',
        },
        'employee': {
            'module': 'employees',
            'recordType': 'employee',
            'recordId': (facts.get('linked_employee') or {}).get('employee_id') if isinstance(facts.get('linked_employee'), dict) else None,
            'title': '关联员工档案',
            'url': '/hrm/employees',
        },
    }
    normalized = []
    for source in sources:
        source_key = str(source)
        item = dict(source_defs.get(source_key, {'title': source_key}))
        if item.get('recordId') is None:
            item.pop('recordId', None)
        fields = field_citations.get(source_key)
        if isinstance(fields, list) and fields:
            item['fields'] = fields[:8]
        normalized.append(item)
    return [{
        'type': 'source_citations',
        'title': '本次使用的系统记录',
        'sources': normalized,
    }]


def _tool_frame_summary(frame: TaskFrame, data: Dict[str, Any], rows_count: int) -> str:
    hint = str(data.get('summary_hint') or '').strip()
    if frame.intent.endswith('.page_context') or frame.intent == 'recruitment.page_context':
        return f'当前页面筛选下，{hint or f"已返回 {rows_count} 条结果。"}'
    if frame.intent == 'employee.search':
        return hint or f'命中 {rows_count} 名员工。'
    if frame.intent == 'organization.overview':
        return hint or f'命中 {rows_count} 个部门。'
    if frame.intent.startswith('attendance.'):
        return hint or f'共读取 {rows_count} 条考勤记录。'
    if frame.intent.startswith('approval.'):
        if rows_count:
            label = {'pending': '待我审批', 'mine': '我的申请', 'history': '审批历史'}.get(frame.slots.get('params', {}).get('view'), '审批')
            return f'{label}共有 {rows_count} 条。'
        return hint or '暂无相关审批。'
    if frame.intent.startswith('feedback.'):
        return hint or f'命中 {rows_count} 条反馈。'
    if frame.intent == 'dashboard.system.overview':
        return '已生成系统整体概览。'
    return hint or f'已返回 {rows_count} 条结果。'


def _clarify(question: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    decision = _decision_from_frame(frame)
    decision.task_type = 'clarification'
    decision.requires_confirmation = False
    return ExecutionResult(
        summary=question,
        widgets=[W.clarification(question, [], '')],
        session_id=ctx.session_id,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        requires_confirmation=False,
        answer={'content': question, 'format': 'text'},
    )


def _not_found(message: str, ctx: AssistantContext, decision: RouteDecision) -> ExecutionResult:
    return ExecutionResult(
        summary=message,
        widgets=[W.warning(message, level='info')],
        session_id=ctx.session_id,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        answer={'content': message, 'format': 'text'},
    )


def _forbidden(message: str, ctx: AssistantContext, frame: TaskFrame) -> ExecutionResult:
    decision = _decision_from_frame(frame)
    decision.task_type = 'forbidden'
    decision.risk_level = 'high'
    decision.safety_flags.append('permission_denied')
    return ExecutionResult(
        summary=message,
        widgets=[W.warning(message, level='danger')],
        session_id=ctx.session_id,
        route_decision=decision,
        router=route_decision_to_router_result(decision),
        error_code='permission_denied',
        answer={'content': message, 'format': 'text'},
    )


def _normalize_text(message: str) -> str:
    return (
        (message or '')
        .strip()
        .replace('？', '?')
        .replace('，', ',')
        .replace('咋样', '怎么样')
        .replace('咋回事', '什么情况')
    )


def _extract_approval_decision_action(text: str) -> Optional[str]:
    if not re.search(r'(审批|申请|待办|ap-|demo-approval|approval)', text, re.I):
        return None
    if re.search(r'(驳回|拒绝|不同意|打回|退回|deny|reject)', text, re.I):
        return 'reject'
    if re.search(r'(通过|同意|批准|审批通过|准了|approve|pass)', text, re.I):
        return 'approve'
    return None


def _extract_approval_ref(text: str) -> str:
    patterns = [
        r'\b(eval-ap-[A-Za-z0-9_-]+)\b',
        r'\b((?:demo-)?approval-[A-Za-z0-9_-]+)\b',
        r'(?<![A-Za-z0-9_-])(ap-[A-Za-z0-9_-]+)\b',
        r'审批(?:ID|编号)?[：:\s#]*([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text or '', re.I)
        if match:
            return match.group(1).strip()
    return ''


def _extract_approval_rank(text: str) -> Optional[int]:
    if re.search(r'(第一条|第一个|第1条|第1个|首条|第一)', text or ''):
        return 1
    if re.search(r'(第二条|第二个|第2条|第2个)', text or ''):
        return 2
    if re.search(r'(第三条|第三个|第3条|第3个)', text or ''):
        return 3
    match = re.search(r'第\s*(\d+)\s*(?:条|个)', text or '')
    if match:
        return max(1, min(int(match.group(1)), MAX_LIMIT))
    return None


def _extract_approval_comment(text: str) -> str:
    match = re.search(r'(?:意见|备注|理由)[：:]\s*(.+)$', text or '')
    if not match:
        return ''
    return match.group(1).strip()[:300]


def _resolve_approval_from_context(ctx: AssistantContext, target_index: Optional[int] = None) -> Optional[ApprovalInstance]:
    target_index = target_index or 1
    for entry in reversed(ctx.history or []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        candidates: List[str] = []
        for ent in entry.get('entities') or []:
            if isinstance(ent, dict) and (ent.get('type') == 'approval' or ent.get('typeLabel') == '审批'):
                if ent.get('id'):
                    candidates.append(str(ent.get('id')))
        for widget in entry.get('widgets') or []:
            candidates.extend(_approval_ids_from_widget(widget))
        unique_ids = list(dict.fromkeys(candidates))
        if len(unique_ids) >= target_index:
            approval = ApprovalInstance.query.get(unique_ids[target_index - 1])
            if approval:
                return approval
    return None


def _approval_ids_from_widget(widget: Any) -> List[str]:
    if not isinstance(widget, dict):
        return []
    ids: List[str] = []
    table = widget.get('table') if isinstance(widget.get('table'), dict) else {}
    rows = table.get('rows') if isinstance(table.get('rows'), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get('id'):
            ids.append(str(row.get('id')))
    for ent in widget.get('entities') or []:
        if isinstance(ent, dict) and (ent.get('type') == 'approval' or ent.get('typeLabel') == '审批') and ent.get('id'):
            ids.append(str(ent.get('id')))
    return ids


def _nth_pending_approval(ctx: AssistantContext, target_index: Optional[int]) -> Optional[ApprovalInstance]:
    index = max(1, min(int(target_index or 1), MAX_LIMIT))
    query = ApprovalInstance.query.filter_by(status='pending')
    if ctx.role not in APPROVAL_OVERRIDE_ROLES:
        query = query.filter(ApprovalInstance.approver_id == ctx.user_id)
    rows = query.order_by(ApprovalInstance.created_at.desc()).limit(index).all()
    return rows[index - 1] if len(rows) >= index else None


def _approval_business_module(business_type: Any) -> str:
    return {
        'employee_request': 'leave_requests',
        'leave': 'leave_requests',
        'overtime': 'leave_requests',
        'offer': 'offers',
        'probation': 'probations',
        'resignation': 'resignations',
        'employee_change': 'employee_changes',
        'onboarding': 'employees',
    }.get(str(business_type or ''), 'business_record')


def _approval_business_url(business_type: Any) -> str:
    return {
        'employee_request': '/employee-requests',
        'leave': '/employee-requests',
        'overtime': '/employee-requests',
        'offer': '/hrm/offers',
        'probation': '/hrm/probations',
        'resignation': '/hrm/resignations',
        'employee_change': '/hrm/employee-changes',
        'onboarding': '/hrm/employees',
    }.get(str(business_type or ''), '/approval-center')


def _approval_effect_text(approval: ApprovalInstance, action: str) -> str:
    action_label = '同步标记为已通过' if action == 'approve' else '同步标记为已驳回'
    business_label = {
        'employee_request': '员工申请',
        'leave': '请假申请',
        'overtime': '加班申请',
        'offer': 'Offer',
        'probation': '转正记录',
        'resignation': '离职记录',
        'employee_change': '员工异动',
        'onboarding': '入职记录',
    }.get(str(approval.business_type or ''), '关联业务单据')
    return f'预计影响：{business_label}会{action_label}。'


def _is_dashboard_query(text: str) -> bool:
    return bool(
        re.search(r'(系统|整体|总览|概览|驾驶舱|仪表盘|看板|经营|运营).{0,12}(情况|怎么样|如何|概览|总览|指标|数据)', text)
        or re.search(r'(HR\s*数据看板|管理驾驶舱|系统概览|系统总览)', text, re.I)
    )


def _is_approval_query(text: str) -> bool:
    return bool(re.search(r'(审批|待办|申请).{0,16}(哪些|多少|列表|记录|历史|待我|我的|查|看|处理)', text)
                or re.search(r'(待我审批|待审批|我的申请|审批历史)', text))


def _is_feedback_query(text: str) -> bool:
    return bool(re.search(r'(反馈|bug|缺陷|报错|白屏|需求).{0,20}(哪些|多少|待处理|没处理|未处理|处理中|已解决|查|看|统计|情况)', text, re.I)
                or re.search(r'(哪些\s*bug|bug\s*没处理|bug\s*待处理)', text, re.I))


def _understand_operational_domain_query(text: str) -> Optional[TaskFrame]:
    if _is_payroll_query(text):
        params: Dict[str, Any] = {'view': 'summary'}
        month = _extract_month(text)
        if month:
            params['month'] = month
        return TaskFrame(
            domain='payroll',
            intent='payroll.summary',
            action='summarize',
            entity_type='payroll',
            confidence=0.94,
            reason='agentic_payroll_summary_query',
            slots={'tool': 'payroll_analysis', 'params': params},
        )

    if _is_performance_query(text):
        return TaskFrame(
            domain='performance',
            intent='performance.distribution',
            action='analyze',
            entity_type='performance',
            confidence=0.94,
            reason='agentic_performance_distribution_query',
            slots={'tool': 'performance_analysis', 'params': {'view': 'distribution'}},
        )

    if _is_training_query(text):
        params: Dict[str, Any] = {}
        if re.search(r'(已完成|完成的|通过|passed|completed)', text, re.I) and not re.search(r'(完成率|比例|占比)', text):
            params['status'] = 'completed'
        return TaskFrame(
            domain='training',
            intent='training.completion',
            action='analyze',
            entity_type='training',
            confidence=0.93,
            reason='agentic_training_completion_query',
            slots={'tool': 'training_analysis', 'params': params},
        )

    return None


def _is_performance_query(text: str) -> bool:
    has_performance_domain = bool(re.search(r'(绩效|考核)', text))
    has_review_distribution = bool(re.search(r'评估', text) and re.search(r'(分布|统计|汇总|等级|评分|完成|多少|几条)', text))
    if not (has_performance_domain or has_review_distribution):
        return False
    if re.search(r'(候选人|应聘者|简历|面试|招聘|岗位|职位|这个人|这位)', text):
        return False
    if re.search(r'(薪资|工资|薪酬|工资条)', text):
        return False
    return bool(re.search(r'(分布|统计|汇总|概览|总览|情况|怎么样|如何|多少|几条|等级|评分|完成|看|查|分析)', text))


def _is_training_query(text: str) -> bool:
    if not re.search(r'(培训|课程|训练营|学习)', text):
        return False
    if re.search(r'(候选人|应聘者|简历|面试|招聘)', text):
        return False
    return bool(re.search(r'(完成率|完成|通过率|参与|参训|记录|统计|汇总|分布|情况|怎么样|如何|多少|几门|计划|课程|看|查|分析)', text))


def _is_payroll_query(text: str) -> bool:
    if not re.search(r'(工资条|薪资|工资|薪酬|发薪|个税|社保|公积金)', text):
        return False
    if re.search(r'(候选人|应聘者|简历|面试|招聘|岗位|职位)', text):
        return False
    if _is_payroll_performance_link_request(text):
        return False
    return bool(re.search(r'(汇总|统计|总览|概览|情况|怎么样|如何|多少|几条|月份|月度|应发|实发|扣减|异常|风险|看|查|分析)', text))


def _is_employee_profile_query(text: str) -> bool:
    return bool(
        re.search(r'(员工画像|人员画像|员工全景|员工概览|人事画像|员工履历)', text)
        or (
            re.search(r'(画像|全景|概览|履历|档案)', text)
            and re.search(r'(考勤|绩效|薪资|工资|异动|调岗|调薪)', text)
            and bool(_extract_employee_profile_name(text) or _extract_employee_keyword(text))
        )
    )


def _is_employee_lifecycle_evidence_request(text: str) -> bool:
    return bool(
        re.search(r'[\u4e00-\u9fa5·]{2,4}', text or '')
        and re.search(r'(完整链路|全链路|跨模块|关联记录|哪些记录|有哪些记录|哪些模块|关联到了哪些模块)', text or '')
        and re.search(
            r'(简历|候选人|Offer|offer|入职|培训|发薪|工资|薪资|绩效|合同|离职|转正|异动|请假|审批)',
            text or '',
            re.I,
        )
    )


def _is_ambiguous_person_context_request(text: str) -> bool:
    if re.search(r'(员工画像|员工档案|候选人|简历|考勤|薪资|工资|绩效|异动|调岗|审批|通知|招聘)', text):
        return False
    return bool(
        _extract_ambiguous_person_keyword(text)
        and re.search(r'(最近|怎么样|如何|看看|看下|看一下|情况|状态)', text)
    )


def _extract_ambiguous_person_keyword(text: str) -> Optional[str]:
    cleaned = re.sub(r'^\s*(?:帮我|请|麻烦|看看|看下|看一下|查一下)\s*', '', text or '')
    patterns = [
        r'((?:小|老)?[\u4e00-\u9fa5·]{1,4})(?:最近|怎么样|如何|情况|状态)',
        r'(?:最近|看看|看下)\s*((?:小|老)?[\u4e00-\u9fa5·]{1,4})(?:怎么样|如何|情况|状态)?',
    ]
    stop_words = {'这个', '那个', '最近', '情况', '状态', '员工', '人员'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        keyword = _strip_temporal_suffix(match.group(1).strip())
        if keyword and keyword not in stop_words:
            return keyword
    return None


def _is_employee_change_impact_request(text: str) -> bool:
    return bool(
        re.search(r'(调岗|调动|异动|转岗|转部门|调整到|调到|转到)', text)
        and re.search(r'(影响|会影响|哪些|岗位|薪资|工资|通知|审批|分析|如果)', text)
        and not re.search(r'(招聘|候选人|简历)', text)
    )


def _is_employee_salary_adjustment_request(text: str) -> bool:
    return bool(
        re.search(r'(调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资)', text)
        and not re.search(r'(统计|汇总|分析一下哪些|多少人|列表|历史|记录)', text)
        and not re.search(r'(招聘|候选人|简历)', text)
    )


def _is_payroll_performance_link_request(text: str) -> bool:
    return bool(
        re.search(r'(绩效|考核)', text)
        and re.search(r'(薪资|工资|薪酬)', text)
        and re.search(r'(考勤|异常|共同|联动|相关|有没有)', text)
    )


def _is_employee_attendance_anomaly_request(text: str) -> bool:
    return bool(
        re.search(r'(考勤|迟到|早退|缺勤|缺卡|请假|加班|出差)', text)
        and re.search(r'(异常|怎么样|情况|证据|最近|本月|是否|吗|有点多|多不多|严重|不正常)', text)
        and bool(_extract_attendance_employee_name(text) or _extract_employee_keyword(text))
    )


def _is_attendance_query(text: str) -> bool:
    return bool(re.search(r'(考勤|迟到|早退|缺勤|缺卡|补卡|请假|加班|出差).{0,18}(异常|情况|统计|分析|多少|哪些|记录|看|查)?', text))


def _is_attendance_reminder_request(text: str) -> bool:
    return bool(
        re.search(r'(迟到).{0,20}(最多|排名|top|TOP|前\s*\d+)', text)
        and re.search(r'(提醒|通知|生成|发送|发给|发一下)', text)
    )


def _is_organization_query(text: str) -> bool:
    if re.search(r'(部门|组织|架构|岗位体系|职位体系).{0,16}(架构|结构|概览|总览|有哪些|多少|分布|看|查)', text):
        return True
    return bool(re.search(r'(部门架构|组织架构|岗位体系)', text))


def _is_employee_query(text: str) -> bool:
    if re.search(r'(员工|同事|人员|花名册|档案|下面有哪些人|有哪些人)', text):
        return bool(re.search(r'(查|看|哪些|多少|列表|档案|下面|在职|试用|离职|待入职|员工|人员)', text))
    return bool(_extract_employee_keyword(text) and re.search(r'(员工档案|员工资料|人事档案|花名册)', text))


def _extract_employee_profile_name(text: str) -> Optional[str]:
    cleaned = re.sub(r'^\s*(?:帮我|请|麻烦|给我|看一下|看看|查一下)\s*', '', text or '')
    patterns = [
        r'(?:给我看|看|查|生成|输出)?\s*([\u4e00-\u9fa5·]{2,8})的(?:员工画像|人员画像|员工全景|员工概览|人事画像|员工履历)',
        r'([\u4e00-\u9fa5·]{2,8})的.*?(?:考勤|绩效|薪资|工资|异动)',
        r'([\u4e00-\u9fa5·]{2,8})从(?:简历|候选人|入职|录入)',
        r'([\u4e00-\u9fa5·]{2,8}).{0,12}(?:完整链路|全链路|跨模块|关联记录)',
    ]
    stop_words = {'员工', '人员', '画像', '考勤', '绩效', '薪资', '异动', '最近', '当前', '完整链路', '全链路'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = match.group(1).strip()
        if name and name not in stop_words:
            return name
    return None


def _extract_employee_change_name(text: str) -> Optional[str]:
    existing_employee = _match_existing_employee_name(text)
    if existing_employee:
        return existing_employee
    cleaned = re.sub(r'^\s*(?:如果|帮我|请|麻烦|看一下|看看|分析一下)\s*', '', text or '')
    patterns = [
        r'(?:把|将)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,30})\s*(?:调到|转到|调整到|调入|转入)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,30})(?:调岗|异动|转岗|转部门)',
    ]
    stop_words = {'员工', '人员', '如果', '哪些', '岗位', '薪资', '通知', '审批'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = re.sub(r'\s+', '', match.group(1).strip())
        if name and name not in stop_words:
            return name
    return None


def _extract_salary_adjustment_name(text: str) -> Optional[str]:
    existing_employee = _match_existing_employee_name(text)
    if existing_employee:
        return existing_employee
    cleaned = re.sub(r'^\s*(?:如果|帮我|请|麻烦|看一下|看看|分析一下|给)\s*', '', text or '')
    patterns = [
        r'(?:给|把|将)?\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,30})\s*(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资)',
        r'(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资).*?(?:给|把|将)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,30})',
    ]
    stop_words = {'员工', '人员', '调薪', '薪资', '工资', '审批', '确认', '影响'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = re.sub(r'\s+', '', match.group(1).strip())
        if name and name not in stop_words:
            return name
    return None


def _match_existing_employee_name(text: str) -> Optional[str]:
    normalized = re.sub(r'\s+', '', text or '')
    if not normalized:
        return None
    try:
        candidates = (
            Employee.query
            .filter(Employee.name.isnot(None))
            .order_by(Employee.created_at.desc())
            .limit(500)
            .all()
        )
    except Exception:
        return None
    matches = [
        str(row.name).strip()
        for row in candidates
        if row.name and re.sub(r'\s+', '', str(row.name).strip()) in normalized
    ]
    if not matches:
        return None
    return max(matches, key=len)


def _extract_salary_adjustment_amount(text: str) -> Optional[float]:
    source = text or ''
    sign = -1 if re.search(r'(降薪|减薪|下调|降低|减少|-)', source) else 1
    amount_pattern = r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)\s*(?:元|块|人民币|CNY)?'
    contextual_patterns = [
        rf'(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资|上调|下调|增加|减少|降低)\s*{amount_pattern}',
        rf'{amount_pattern}\s*(?:元|块|人民币|CNY)?\s*(?:的)?\s*(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资)',
    ]
    match = None
    for pattern in contextual_patterns:
        match = re.search(pattern, source)
        if match:
            break
    if not match:
        match = re.search(rf'{amount_pattern}\s*(?:元|块|人民币|CNY)', source)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(',', ''))
    except ValueError:
        return None
    if value == 0:
        return None
    if value < 0:
        return value
    return value * sign


def _format_salary_adjustment_amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ''
    if number.is_integer():
        return str(int(number))
    return f'{number:.2f}'.rstrip('0').rstrip('.')


def _extract_target_department(text: str) -> Optional[str]:
    patterns = [
        r'(?:调到|转到|调整到|调入|转入)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:[，,。；;]|目标岗位|岗位[：:]|职位[：:]|先分析|并准备|$)',
        r'目标部门[：: ]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:[，,。；;]|目标岗位|岗位[：:]|职位[：:]|先分析|并准备|$)',
    ]
    stop_words = {'目标部门', '部门', '岗位', '职位', '审批', '影响', '确认'}
    for pattern in patterns:
        match = re.search(pattern, text or '')
        if match:
            value = re.sub(r'\s+', '', match.group(1).strip())
            value = value.rstrip('，,。；;')
            if value and value not in stop_words:
                return value
    return None


def _extract_target_position(text: str, target_department: Optional[str] = None) -> Optional[str]:
    cleaned = text or ''
    patterns = [
        r'目标岗位[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,40})',
        r'(?:转任|转岗为|调岗为|调整为)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,40}?)(?:岗位|职位|岗)?(?:[，,。；;]|$)',
        r'(?:岗位|职位)[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,40})',
    ]
    stop_words = {'目标部门', '部门', '岗位', '职位', '审批', '影响', '确认'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        title = re.sub(r'\s+', '', match.group(1).strip())
        title = re.sub(r'(?:岗位|职位|岗)$', '', title)
        title = title.rstrip('，,。；;')
        if title and title not in stop_words:
            return title
    if target_department:
        dept = Department.query.filter(Department.name == target_department).first()
        if not dept:
            dept = (
                Department.query
                .filter(Department.name.like(f'%{target_department}%'))
                .order_by(desc(Department.created_at))
                .first()
            )
        if dept:
            positions = (
                Position.query
                .filter(Position.department_id == dept.id)
                .order_by(Position.created_at.desc())
                .limit(50)
                .all()
            )
            normalized = re.sub(r'\s+', '', cleaned)
            matches = [
                str(row.title).strip()
                for row in positions
                if row.title and re.sub(r'\s+', '', str(row.title).strip()) in normalized
            ]
            if matches:
                return max(matches, key=len)
    return None


def _extract_attendance_employee_name(text: str) -> Optional[str]:
    cleaned = re.sub(r'^\s*(?:帮我|请|麻烦|看一下|看看|查一下|分析一下)\s*', '', text or '')
    patterns = [
        r'([\u4e00-\u9fa5·]{2,8})(?:最近|本月|这月|近\d+天)?.{0,8}(?:考勤|迟到|早退|缺勤|缺卡|请假|加班|出差)',
        r'(?:考勤|迟到|早退|缺勤|缺卡).{0,8}([\u4e00-\u9fa5·]{2,8})(?:怎么样|情况|异常|证据|吗)',
    ]
    stop_words = {'员工', '人员', '最近', '本月', '考勤', '异常', '情况'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = _strip_temporal_suffix(match.group(1).strip())
        if name and name not in stop_words:
            return name
    return None


def _strip_temporal_suffix(value: str) -> str:
    text = value or ''
    text = re.sub(r'(最近|本月|这月|本周|近\d+天|近)$', '', text).strip()
    return text


def _extract_quarter(text: str) -> Tuple[Optional[int], Optional[int]]:
    year = None
    quarter = None
    match = re.search(r'(20\d{2})\s*[年-]?\s*[Qq季]?\s*([1-4])\s*(?:季度|季|Q|q)?', text or '')
    if match:
        year = int(match.group(1))
        quarter = int(match.group(2))
    else:
        qmatch = re.search(r'(?:第)?([1-4])\s*(?:季度|季|Q|q)', text or '')
        if qmatch:
            quarter = int(qmatch.group(1))
        if '本季度' in (text or ''):
            now = business_now()
            year = now.year
            quarter = (now.month - 1) // 3 + 1
    return year, quarter


def _extract_employee_keyword(text: str) -> str:
    text = re.sub(r'^(查一下|看一下|看看|查询|搜索|帮我|请)\s*', '', text or '')
    name_patterns = [
        r'([\u4e00-\u9fa5·]{2,8}?)(?:员工档案|员工资料|人事档案|档案)',
        r'([\u4e00-\u9fa5·]{2,8}?)(?:这个员工|这位员工|员工)(?:怎么样|资料|档案|信息)?',
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text or '')
        if match:
            name = match.group(1).strip()
            if name not in {'员工', '人员', '同事', '部门', '组织', '当前', '现在'}:
                return name
    dept_match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9]+部)(?:下面|里|有哪些|人员|员工)', text or '')
    if dept_match:
        return dept_match.group(1)
    status_map = {
        '离职': 'resigned',
        '在职': 'active',
        '试用': 'probation',
        '待入职': 'pending_onboard',
    }
    for key, value in status_map.items():
        if key in (text or ''):
            return value
    return ''


def _repair_employee_params(params: Dict[str, Any], text: str) -> Dict[str, Any]:
    repaired = dict(params or {})
    keyword = str(repaired.get('keyword') or '').strip()
    dept_name = ''
    dept_match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9]+部)(?:下面|里|有哪些|人员|员工)', text or '')
    if dept_match:
        dept_name = dept_match.group(1)
    elif keyword.endswith('部'):
        dept_name = keyword
    if dept_name:
        dept = Department.query.filter(Department.name == dept_name).first()
        if not dept:
            dept = Department.query.filter(Department.name.like(f'%{dept_name}%')).first()
        if dept:
            repaired.pop('keyword', None)
            repaired['department_id'] = dept.id
    return repaired


def _extract_org_keyword(text: str) -> str:
    match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9]+部)(?:门)?(?:架构|结构|概览|下面|人员|员工)?', text or '')
    if match:
        return match.group(1)
    return ''


def _extract_month(text: str) -> Optional[str]:
    match = re.search(r'(20\d{2})[-年/](\d{1,2})', text or '')
    if match:
        return f'{match.group(1)}-{int(match.group(2)):02d}'
    if '本月' in (text or ''):
        now = business_now()
        return f'{now.year}-{now.month:02d}'
    return None


def _is_open_job_query(text: str) -> bool:
    has_job = bool(re.search(r'(岗位|职位|JD|招聘需求|招人)', text, re.I))
    has_open = bool(re.search(r'(招聘中|在招|招人|开放|open|正在招|还招|缺人)', text, re.I))
    is_lookup = bool(re.search(r'(哪些|有哪些|多少|几个|列|查|看|现在|目前|最近|当前|一共|总数)', text))
    return has_job and has_open and is_lookup


def _is_resume_count_query(text: str) -> bool:
    return bool(
        re.search(r'(简历|履历)', text)
        and re.search(r'(多少|几份|数量|总数|一共|共有|有多少)', text)
        and not re.search(r'(分析|评价|怎么样|面试题|安排)', text)
    )


def _is_candidate_count_query(text: str) -> bool:
    return bool(
        re.search(r'(候选人|应聘者)', text)
        and re.search(r'(多少|几位|几名|数量|总数|一共|共有|有多少)', text)
        and not re.search(r'(分析|评价|怎么样|面试题|安排)', text)
    )


def _is_recent_resume_list_query(text: str) -> bool:
    return bool(
        re.search(r'(最近|近\s*\d+\s*天|本周|本月|刚收到|新收到|收到)', text)
        and re.search(r'(简历|履历|投递)', text)
        and re.search(r'(分析|看看|看一下|列|哪些|名单|查|搜索|收到)', text)
        and not re.search(r'(多少|几份|总数|数量)', text)
    )


def _is_recent_candidate_list_query(text: str) -> bool:
    return bool(
        re.search(r'(最近|近\s*\d+\s*天|本周|本月|新来|新增|刚投|投递)', text)
        and re.search(r'(候选人|应聘者|哪些人|名单)', text)
        and not re.search(r'(多少|几位|几名|总数|数量)', text)
    )


def _is_recruitment_match_request(text: str) -> bool:
    return bool(
        re.search(r'(岗位|职位|JD|招聘需求|候选人|应聘者|简历)', text, re.I)
        and re.search(r'(更合适|最合适|谁合适|推荐|匹配|对比|比较|矩阵|排序|排名|优先推进)', text)
        and not re.search(r'(员工|薪资|绩效|考勤|异动|调岗)', text)
    )


def _extract_recruitment_job_keyword(text: str) -> Optional[str]:
    cleaned = re.sub(r'^\s*(?:帮我|请|麻烦|看一下|看看|分析一下|对比一下|给我)\s*', '', text or '')
    patterns = [
        r'([\u4e00-\u9fa5A-Za-z0-9+#·\s]{2,24}?)(?:岗位|职位|JD|招聘需求).{0,20}(?:候选人|简历|谁|哪个|哪些|更合适|匹配|对比|矩阵|推荐)',
        r'(?:岗位|职位|JD|招聘需求)[：: ]*([\u4e00-\u9fa5A-Za-z0-9+#·\s]{2,24}?).{0,20}(?:候选人|简历|谁|哪个|哪些|更合适|匹配|对比|矩阵|推荐)',
    ]
    stop_words = {'最近', '当前', '候选人', '简历', '岗位', '职位', '招聘需求'}
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if not match:
            continue
        value = re.sub(r'(最近|当前|本月|本周|来|收到|应聘|投递|这个|那个)+', '', match.group(1)).strip()
        value = re.sub(r'\s+', ' ', value)
        if value and value not in stop_words:
            return value
    return None


def _is_person_resume_lookup(text: str) -> bool:
    return bool(_extract_person_name(text) and re.search(r'(简历|履历|资料|候选人记录)', text))


def _is_person_assessment_request(text: str) -> bool:
    if not re.search(r'(分析|评价|评估|判断|怎么样|如何|适合|推荐|优劣势|靠谱|靠不靠谱|行不行|值不值得|要不要约|能不能约)', text):
        return False
    if re.search(r'(岗位|职位).*(有哪些|哪些|多少|在招)', text):
        return False
    return bool(_extract_person_name(text) or re.search(r'(这个人|这位|他|她|TA|ta|刚才那个|上面那个)', text))


def _is_interview_schedule_request(text: str) -> bool:
    return bool(re.search(r'(安排|约|创建|新建|排).{0,12}(面试|复试|终面|初面)', text))


def _extract_person_name(text: str) -> Optional[str]:
    cleaned = re.sub(r'^\s*(?:帮我|请|麻烦|查一下|看一下|看看|分析一下|评价一下|评估一下)\s*', '', text or '')
    if re.search(r'^(这个人|这位|他|她|TA|ta|刚才|上面)', cleaned):
        return None
    known = _known_candidate_name_in_text(cleaned)
    if known:
        return known
    patterns = [
        r'([\u4e00-\u9fa5·]{2,8})的(?:简历|履历|资料|候选人记录)',
        r'(?:分析|评价|评估|判断|推荐)\s*([\u4e00-\u9fa5·]{2,8})(?:这个人|这位候选人|候选人|怎么样|如何|$)',
        r'([\u4e00-\u9fa5·]{2,8})(?:这个人|这位候选人|候选人)?(?:怎么样|如何|适合|推荐|行不行|靠谱|靠不靠谱|值不值得|要不要约|能不能约)',
        r'(?:给|为)\s*([\u4e00-\u9fa5·]{2,8})(?:安排|约|创建|新建)',
        r'(?:候选人|应聘者)\s*([\u4e00-\u9fa5·]{2,8})(?:的|简历|履历|资料|候选人记录|$)',
    ]
    stop_words = {'最近', '当前', '现在', '我们', '候选人', '简历', '岗位', '职位', '这个人', '这位'}
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = match.group(1).strip()
        if name and name not in stop_words and not re.search(r'(岗位|职位|候选人|简历|员工|最近)$', name):
            return name
    return None


def _known_candidate_name_in_text(text: str) -> Optional[str]:
    """Resolve candidate names against real candidate/resume data, not keywords."""
    cleaned = re.sub(r'\s+', '', text or '')
    if not cleaned or not re.search(r'(候选人|应聘者|简历|履历|面试|招聘)', cleaned):
        return None
    names: List[str] = []
    try:
        candidate_names = (
            Candidate.query
            .with_entities(Candidate.name)
            .filter(Candidate.name.isnot(None))
            .limit(500)
            .all()
        )
        resume_names = (
            Resume.query
            .with_entities(Resume.candidate_name)
            .filter(Resume.candidate_name.isnot(None))
            .limit(500)
            .all()
        )
    except Exception:  # noqa: BLE001 - parsing must never break routing.
        return None
    for row in list(candidate_names) + list(resume_names):
        try:
            raw = row[0]
        except (TypeError, KeyError, IndexError):
            raw = row
        name = re.sub(r'\s+', '', str(raw or ''))
        if len(name) >= 2:
            names.append(name)
    for name in sorted(set(names), key=len, reverse=True):
        if name in cleaned:
            return name
    return None


def _extract_limit(text: str) -> Optional[int]:
    match = re.search(r'(\d+)\s*(?:个|名|位|份|条)?', text or '')
    if not match:
        return None
    return max(1, min(int(match.group(1)), MAX_LIMIT))


def _extract_recent_days(text: str) -> Optional[int]:
    match = re.search(r'(?:最近|近)\s*(\d+)\s*天', text or '')
    if match:
        return max(1, min(int(match.group(1)), 180))
    if '本周' in text:
        return 7
    if '本月' in text:
        return 30
    return None


def _action_message_parts(message: str) -> Tuple[Optional[str], Optional[str]]:
    match = re.match(r'\s*(确认执行动作|取消动作)\s*[：:]\s*([A-Za-z0-9_-]+)\s*$', message or '')
    if match:
        return match.group(1), match.group(2)
    text = (message or '').strip()
    if re.fullmatch(r'(好的,?|没问题,?)?(确认吧?|确认执行|可以,?执行|是的,?执行吧|执行吧|执行)', text):
        return '确认执行动作', None
    if re.fullmatch(r'(不用了,?|算了,?)?(先)?(取消|取消执行|别执行|不用执行了?)', text):
        return '取消动作', None
    return None, None


def _parse_schedule_time(message: str) -> Optional[str]:
    iso_match = re.search(r'(20\d{2}-\d{2}-\d{2})\s*(?:T|\s)?\s*(\d{1,2})(?::(\d{2}))?', message or '')
    if iso_match:
        hour = int(iso_match.group(2))
        minute = int(iso_match.group(3) or 0)
        return f'{iso_match.group(1)}T{hour:02d}:{minute:02d}:00'
    day = None
    if '明天' in (message or ''):
        day = business_now() + timedelta(days=1)
    elif '后天' in (message or ''):
        day = business_now() + timedelta(days=2)
    if day is None:
        return None
    hour = 15 if '下午' in message else 9
    minute = 0
    chinese_hours = {
        '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6,
        '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
    }
    match = re.search(r'(\d{1,2}|十二|十一|十|[一二两三四五六七八九])\s*点(?:\s*(半|\d{1,2}\s*分))?', message)
    if match:
        raw_hour = match.group(1)
        hour = int(raw_hour) if raw_hour.isdigit() else chinese_hours[raw_hour]
        raw_minute = match.group(2) or ''
        minute = 30 if raw_minute == '半' else int(re.sub(r'\D', '', raw_minute) or 0)
        if ('下午' in message or '晚上' in message) and hour < 12:
            hour += 12
        if '中午' in message and hour < 11:
            hour += 12
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
