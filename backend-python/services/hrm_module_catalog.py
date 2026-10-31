"""Shared HRM module catalog.

The left navigation, generic HRM resource API, and AI assistant routing all
need the same module map.  Keeping this as data makes module coverage and
cross-module handoffs testable instead of relying on scattered hard-coded
lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class HrmModuleSpec:
    id: str
    label: str
    group: str
    path: str
    resource: Optional[str] = None
    special: Optional[str] = None
    icon: str = 'fa-table'
    ai_skill: str = 'system_search'
    ai_intent: str = 'system_module_query'
    ai_input: Dict[str, Any] = field(default_factory=dict)
    aliases: Tuple[str, ...] = ()
    risk: str = 'low'
    upstream: Tuple[str, ...] = ()
    downstream: Tuple[str, ...] = ()
    capabilities: Tuple[str, ...] = ()
    benchmark_patterns: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'group': self.group,
            'path': self.path,
            'resource': self.resource,
            'special': self.special,
            'icon': self.icon,
            'aiSkill': self.ai_skill,
            'aiIntent': self.ai_intent,
            'aiInput': dict(self.ai_input),
            'aliases': list(self.aliases),
            'risk': self.risk,
            'upstream': list(self.upstream),
            'downstream': list(self.downstream),
            'capabilities': list(self.capabilities),
            'benchmarkPatterns': list(self.benchmark_patterns),
        }


def _m(
    id: str,
    label: str,
    group: str,
    path: str,
    *,
    resource: Optional[str] = None,
    special: Optional[str] = None,
    icon: str = 'fa-table',
    ai_skill: str = 'system_search',
    ai_intent: str = 'system_module_query',
    ai_input: Optional[Dict[str, Any]] = None,
    aliases: Iterable[str] = (),
    risk: str = 'low',
    upstream: Iterable[str] = (),
    downstream: Iterable[str] = (),
    capabilities: Iterable[str] = (),
    benchmark_patterns: Iterable[str] = (),
) -> HrmModuleSpec:
    return HrmModuleSpec(
        id=id,
        label=label,
        group=group,
        path=path,
        resource=resource,
        special=special,
        icon=icon,
        ai_skill=ai_skill,
        ai_intent=ai_intent,
        ai_input=dict(ai_input or {}),
        aliases=tuple(aliases),
        risk=risk,
        upstream=tuple(upstream),
        downstream=tuple(downstream),
        capabilities=tuple(capabilities),
        benchmark_patterns=tuple(benchmark_patterns),
    )


MODULE_SPECS: Tuple[HrmModuleSpec, ...] = (
    _m('dashboard', '数据驾驶舱', '首页', '/home', icon='fa-gauge-high',
       ai_skill='dashboard_report', ai_intent='system_dashboard',
       ai_input={'scope': 'system'}, aliases=('HR 数据看板', '管理驾驶舱'),
       downstream=('talent-intelligence', 'jobs', 'employees', 'attendance-records',
                   'performance-reviews', 'payroll-records'),
       capabilities=('overall_metrics', 'cross_domain_alerts'),
       benchmark_patterns=('executive dashboard', 'HR analytics')),
    _m('talent-intelligence', '人才智能', '人才战略', '/talent-intelligence',
       icon='fa-radar', ai_skill='dashboard_report',
       ai_intent='talent_intelligence_overview', ai_input={'scope': 'employee'},
       aliases=('人才战略',), downstream=('jobs', 'employees', 'performance-reviews'),
       capabilities=('workforce_insights', 'talent_risk_overview'),
       benchmark_patterns=('workforce planning', 'talent analytics')),

    _m('jobs', '岗位管理', '招聘管理', '/job-manage', resource='jobs',
       icon='fa-briefcase', ai_skill='recruitment_search',
       ai_intent='recruitment_jobs_query', ai_input={'module': 'jobs'},
       downstream=('resumes', 'candidates', 'interviews', 'offers'),
       capabilities=('job_requisition', 'headcount_tracking', 'jd_scoring_criteria'),
       benchmark_patterns=('recruitment requisition', 'job opening')),
    _m('resumes', '简历管理', '招聘管理', '/resume-manage', resource='resumes',
       icon='fa-file-alt', ai_skill='recruitment_search',
       ai_intent='recruitment_resumes_query', ai_input={'module': 'resumes'},
       upstream=('jobs',), downstream=('candidates', 'interviews'),
       capabilities=('resume_upload', 'ai_resume_analysis', 'candidate_matching'),
       benchmark_patterns=('applicant tracking', 'resume parser')),
    _m('candidates', '候选人管理', '招聘管理', '/hrm/candidates',
       resource='candidates', icon='fa-user-tie', ai_skill='recruitment_search',
       ai_intent='recruitment_candidates_query', ai_input={'module': 'candidates'},
       upstream=('jobs', 'resumes'), downstream=('interviews', 'offers'),
       capabilities=('candidate_pipeline', 'source_tracking', 'ai_recommendation'),
       benchmark_patterns=('ATS pipeline', 'candidate stage')),
    _m('interviews', '面试管理', '招聘管理', '/interview-manage',
       resource='interviews', icon='fa-users', ai_skill='recruitment_search',
       ai_intent='recruitment_interviews_query', ai_input={'module': 'interviews'},
       upstream=('candidates', 'resumes'), downstream=('offers',),
       capabilities=('interview_schedule', 'feedback_analysis', 'online_interview'),
       benchmark_patterns=('interview schedule', 'evaluation')),
    _m('offers', 'Offer管理', '招聘管理', '/hrm/offers', resource='offers',
       icon='fa-file-signature', ai_skill='recruitment_search',
       ai_intent='recruitment_offers_query', ai_input={'module': 'offers'},
       aliases=('Offer 管理', 'offer管理'), upstream=('candidates', 'interviews'),
       downstream=('employees', 'onboarding-tasks', 'salary-profiles'),
       capabilities=('offer_approval', 'candidate_to_employee', 'salary_seed'),
       benchmark_patterns=('offer management', 'preboarding')),

    _m('departments', '部门管理', '组织管理', '/hrm/departments',
       resource='departments', icon='fa-sitemap', ai_skill='organization_search',
       ai_intent='organization_overview', ai_input={'include_stats': True},
       downstream=('positions', 'employees', 'attendance-records', 'performance-reviews'),
       capabilities=('org_tree', 'department_owner', 'headcount_distribution'),
       benchmark_patterns=('organization structure', 'department hierarchy')),
    _m('positions', '岗位体系', '组织管理', '/hrm/positions',
       resource='positions', icon='fa-layer-group', ai_skill='organization_search',
       ai_intent='organization_overview', ai_input={'include_stats': True},
       upstream=('departments',), downstream=('jobs', 'employees'),
       capabilities=('position_family', 'leveling', 'job_requirements'),
       benchmark_patterns=('position management', 'job catalog')),

    _m('employees', '员工档案', '员工管理', '/hrm/employees',
       resource='employees', icon='fa-id-card', ai_skill='employee_search',
       ai_intent='employee_lookup', upstream=('offers', 'departments', 'positions'),
       downstream=('onboarding-tasks', 'probations', 'employee-changes', 'resignations',
                   'contracts', 'attendance-records', 'performance-reviews',
                   'salary-profiles', 'training-records'),
       capabilities=('employee_profile', 'manager_chain', 'employment_status'),
       benchmark_patterns=('employee master data', 'personnel file')),
    _m('onboarding-tasks', '入职管理', '员工管理', '/hrm/onboarding-tasks',
       resource='onboarding-tasks', icon='fa-clipboard-check',
       ai_input={'module': 'lifecycle'}, ai_intent='employee_lifecycle_query',
       upstream=('offers', 'employees'), downstream=('probations', 'contracts'),
       capabilities=('onboarding_checklist', 'material_collection', 'task_owner'),
       benchmark_patterns=('onboarding', 'preboarding checklist')),
    _m('probations', '转正管理', '员工管理', '/hrm/probations',
       resource='probations', icon='fa-user-check', ai_input={'module': 'lifecycle'},
       ai_intent='employee_lifecycle_query', upstream=('employees', 'onboarding-tasks'),
       downstream=('approvals-pending', 'performance-reviews'),
       capabilities=('probation_review', 'regularization_approval'),
       benchmark_patterns=('probation', 'confirmation')),
    _m('employee-changes', '人事异动', '员工管理', '/hrm/employee-changes',
       resource='employee-changes', icon='fa-random', ai_input={'module': 'lifecycle'},
       ai_intent='employee_lifecycle_query', upstream=('employees', 'departments', 'positions'),
       downstream=('approvals-pending', 'salary-profiles', 'payroll-records', 'operation-logs'),
       capabilities=('transfer', 'promotion', 'salary_adjustment_seed', 'approval_before_effect'),
       benchmark_patterns=('employee movement', 'job change', 'approval before payroll impact')),
    _m('resignations', '离职管理', '员工管理', '/hrm/resignations',
       resource='resignations', icon='fa-user-minus', ai_input={'module': 'lifecycle'},
       ai_intent='employee_lifecycle_query', upstream=('employees',),
       downstream=('approvals-pending', 'contracts', 'dashboard'),
       capabilities=('offboarding', 'handover', 'exit_reason_analysis'),
       benchmark_patterns=('offboarding', 'separation')),
    _m('contracts', '合同管理', '员工管理', '/hrm/contracts',
       resource='contracts', icon='fa-file-contract', ai_input={'module': 'lifecycle'},
       ai_intent='employee_lifecycle_query', upstream=('employees',),
       downstream=('notifications', 'operation-logs'),
       capabilities=('contract_ledger', 'expiry_reminder', 'attachment_tracking'),
       benchmark_patterns=('contract management', 'compliance reminder')),

    _m('attendance-records', '考勤记录', '考勤与申请', '/hrm/attendance-records',
       resource='attendance-records', icon='fa-clock', ai_skill='attendance_analysis',
       ai_intent='attendance_exception_analysis', upstream=('employees',),
       downstream=('attendance-stats', 'employee-requests', 'payroll-records'),
       capabilities=('time_clock', 'attendance_exception', 'manual_adjustment'),
       benchmark_patterns=('time attendance', 'timesheet')),
    _m('attendance-stats', '考勤统计', '考勤与申请', '/attendance-stats',
       special='attendance-stats', resource='attendance-records',
       icon='fa-chart-line', ai_skill='attendance_analysis',
       ai_intent='attendance_exception_analysis', upstream=('attendance-records',),
       downstream=('dashboard', 'payroll-records'),
       capabilities=('monthly_attendance_summary', 'exception_ranking'),
       benchmark_patterns=('attendance analytics', 'absence summary')),
    _m('employee-requests', '请假/加班/出差/补卡', '考勤与申请',
       '/employee-requests', resource='employee-requests', icon='fa-calendar-plus',
       ai_skill='attendance_analysis', ai_intent='attendance_exception_analysis',
       aliases=('请假', '加班', '出差', '补卡'), upstream=('employees', 'attendance-records'),
       downstream=('approvals-pending', 'attendance-stats', 'payroll-records'),
       capabilities=('leave_request', 'overtime_request', 'travel_request', 'makeup_card'),
       benchmark_patterns=('leave management', 'employee self service')),

    _m('approvals-mine', '我的申请', '审批中心',
       '/approval-center/my-applications', special='approval-list',
       icon='fa-inbox', ai_skill='approval_search',
       ai_intent='approval_pending_summary', ai_input={'view': 'mine'},
       upstream=('employee-requests', 'probations', 'employee-changes', 'resignations', 'offers'),
       capabilities=('approval_applicant_view',), benchmark_patterns=('workflow inbox',)),
    _m('approvals-pending', '待我审批', '审批中心',
       '/approval-center/pending', special='approval-list',
       icon='fa-user-clock', ai_skill='approval_search',
       ai_intent='approval_pending_summary', ai_input={'view': 'pending'},
       upstream=('employee-requests', 'probations', 'employee-changes', 'resignations', 'offers'),
       downstream=('employees', 'operation-logs', 'notifications'),
       capabilities=('approval_inbox', 'controlled_approve_reject'),
       benchmark_patterns=('approval workflow',)),
    _m('approval-records', '审批记录', '审批中心',
       '/approval-center/records', special='approval-list',
       icon='fa-history', ai_skill='approval_search',
       ai_intent='approval_pending_summary', ai_input={'view': 'history'},
       upstream=('approvals-pending',), downstream=('operation-logs',),
       capabilities=('approval_audit',), benchmark_patterns=('workflow history',)),

    _m('performance-cycles', '绩效周期', '绩效管理', '/hrm/performance-cycles',
       resource='performance-cycles', icon='fa-bullseye',
       ai_skill='performance_analysis', ai_intent='performance_distribution_report',
       downstream=('performance-templates', 'performance-reviews'),
       capabilities=('review_cycle', 'period_control'),
       benchmark_patterns=('performance cycle',)),
    _m('performance-templates', '绩效模板', '绩效管理',
       '/hrm/performance-templates', resource='performance-templates',
       icon='fa-list-check', ai_skill='performance_analysis',
       ai_intent='performance_distribution_report', upstream=('performance-cycles',),
       downstream=('performance-reviews',),
       capabilities=('indicator_template', 'scoring_schema'),
       benchmark_patterns=('performance template', 'KPI template')),
    _m('performance-reviews', '绩效评估', '绩效管理',
       '/performance-review', resource='performance-reviews', icon='fa-star-half-alt',
       ai_skill='performance_analysis', ai_intent='performance_distribution_report',
       upstream=('employees', 'performance-cycles', 'performance-templates'),
       downstream=('employee-changes', 'salary-profiles', 'training-courses',
                   'training-plans', 'training-records', 'talent-intelligence'),
       capabilities=('review_record', 'grade_distribution', 'manager_feedback',
                     'compensation_adjustment_seed', 'performance_development_plan'),
       benchmark_patterns=('performance review', 'appraisal', 'performance development plan')),

    _m('salary-profiles', '薪资档案', '薪酬管理', '/salary-profiles',
       resource='salary-profiles', icon='fa-wallet', ai_skill='payroll_analysis',
       ai_intent='payroll_month_summary', risk='high', upstream=('employees', 'offers', 'employee-changes'),
       downstream=('payroll-records',), capabilities=('salary_structure', 'sensitive_access'),
       benchmark_patterns=('compensation profile', 'salary structure')),
    _m('payroll-records', '工资条', '薪酬管理', '/hrm/payroll-records',
       resource='payroll-records', icon='fa-money-check-alt',
       ai_skill='payroll_analysis', ai_intent='payroll_month_summary',
       risk='high', upstream=('salary-profiles', 'attendance-records', 'employee-requests'),
       downstream=('dashboard', 'notifications'),
       capabilities=('monthly_payroll', 'payslip_visibility', 'gross_net_calculation'),
       benchmark_patterns=('payroll', 'payslip')),

    _m('training-courses', '培训课程', '培训管理', '/hrm/training-courses',
       resource='training-courses', icon='fa-chalkboard-teacher',
       ai_skill='training_analysis', ai_intent='training_completion_report',
       downstream=('training-plans',), capabilities=('course_catalog',),
       benchmark_patterns=('learning catalog',)),
    _m('training-plans', '培训计划', '培训管理', '/hrm/training-plans',
       resource='training-plans', icon='fa-calendar-days',
       ai_skill='training_analysis', ai_intent='training_completion_report',
       upstream=('training-courses', 'departments'), downstream=('training-records',),
       capabilities=('training_plan', 'target_department'),
       benchmark_patterns=('training plan',)),
    _m('training-records', '培训记录', '培训管理', '/hrm/training-records',
       resource='training-records', icon='fa-graduation-cap',
       ai_skill='training_analysis', ai_intent='training_completion_report',
       upstream=('training-plans', 'training-courses', 'employees', 'performance-reviews'),
       downstream=('performance-reviews', 'talent-intelligence'),
       capabilities=('training_completion', 'score_feedback'),
       benchmark_patterns=('learning record', 'completion rate')),

    _m('users', '用户管理', '系统管理', '/hrm/users', resource='users',
       icon='fa-users-cog', ai_input={'module': 'users'},
       capabilities=('account_role_link', 'employee_link'),
       benchmark_patterns=('user administration',)),
    _m('roles', '角色权限', '系统管理', '/hrm/roles', resource='roles',
       icon='fa-user-shield', ai_input={'module': 'roles'},
       downstream=('users',), capabilities=('role_permission',),
       benchmark_patterns=('RBAC', 'role management')),
    _m('notifications', '通知提醒', '系统管理', '/notifications',
       resource='notifications', icon='fa-bell', ai_input={'module': 'notifications'},
       upstream=('approvals-pending', 'contracts', 'payroll-records'),
       capabilities=('in_app_notification', 'unread_tracking'),
       benchmark_patterns=('notification center',)),
    _m('feedback', '问题反馈', '系统管理', '/feedback', resource='feedbacks',
       icon='fa-comment-medical', ai_skill='feedback_triage',
       ai_intent='feedback_triage_summary',
       downstream=('operation-logs', 'notifications'),
       capabilities=('issue_feedback', 'triage_status', 'resolution_notice'),
       benchmark_patterns=('ticketing', 'employee feedback')),
    _m('operation-logs', '操作日志', '系统管理', '/operation-logs',
       resource='operation-logs', icon='fa-clipboard-list',
       ai_input={'module': 'operation_logs'},
       upstream=('all',), capabilities=('audit_log', 'request_trace'),
       benchmark_patterns=('audit trail',)),
    _m('model-settings', 'AI 模型管理', '系统管理', '/ai-model-settings',
       special='model-settings', icon='fa-brain', aliases=('AI模型管理', '模型管理'),
       ai_input={'module': 'model_settings'},
       upstream=('assistant',), downstream=('dashboard', 'feedback'),
       capabilities=('model_routing', 'assistant_feature_flags'),
       benchmark_patterns=('AI configuration',)),
    _m('settings', '系统设置', '系统管理', '/system-settings',
       special='settings', icon='fa-cog', ai_input={'module': 'settings'},
       capabilities=('company_settings', 'security_settings', 'feature_switches'),
       benchmark_patterns=('system settings',)),
)


BUSINESS_FLOWS: Tuple[Dict[str, Any], ...] = (
    {
        'id': 'recruit_to_onboard',
        'name': '招聘到入职',
        'modules': ['jobs', 'resumes', 'candidates', 'interviews', 'offers',
                    'employees', 'onboarding-tasks', 'contracts'],
    },
    {
        'id': 'employee_lifecycle',
        'name': '员工生命周期',
        'modules': ['employees', 'probations', 'employee-changes',
                    'resignations', 'contracts', 'operation-logs'],
    },
    {
        'id': 'attendance_to_payroll',
        'name': '考勤到薪酬',
        'modules': ['attendance-records', 'attendance-stats', 'employee-requests',
                    'salary-profiles', 'payroll-records'],
    },
    {
        'id': 'performance_to_growth',
        'name': '绩效与成长',
        'modules': ['performance-cycles', 'performance-templates',
                    'performance-reviews', 'training-courses',
                    'training-plans', 'training-records'],
    },
    {
        'id': 'performance_to_compensation',
        'name': '绩效到薪酬',
        'modules': ['performance-cycles', 'performance-reviews',
                    'employee-changes', 'salary-profiles', 'payroll-records'],
    },
    {
        'id': 'workflow_governance',
        'name': '审批与治理',
        'modules': ['approvals-mine', 'approvals-pending', 'approval-records',
                    'notifications', 'feedback', 'operation-logs'],
    },
)


OPEN_SOURCE_BENCHMARKS: Tuple[Dict[str, Any], ...] = (
    {
        'name': 'Frappe HRMS',
        'githubRepo': 'https://github.com/frappe/hrms',
        'stars': 8031,
        'pattern': 'employee lifecycle, leave, attendance, payroll, performance',
        'focusModules': ['employees', 'attendance-records', 'employee-requests',
                         'payroll-records', 'performance-reviews'],
        'appliedPatterns': ['employee master data as source of truth',
                            'attendance/leave/payroll chain',
                            'performance-to-compensation traceability'],
    },
    {
        'name': 'Horilla',
        'githubRepo': 'https://github.com/horilla-opensource/horilla',
        'stars': 1236,
        'pattern': 'recruitment, onboarding, attendance, leave, payroll, assets, helpdesk',
        'focusModules': ['jobs', 'candidates', 'onboarding-tasks',
                         'attendance-records', 'payroll-records', 'feedback'],
        'appliedPatterns': ['recruit-to-onboard continuity',
                            'employee service requests feeding attendance/payroll',
                            'issue feedback as HR service desk'],
    },
    {
        'name': 'OrangeHRM',
        'githubRepo': 'https://github.com/orangehrm/orangehrm',
        'stars': 1064,
        'pattern': 'PIM, leave, time, recruitment, performance, administration',
        'focusModules': ['employees', 'employee-requests', 'attendance-records',
                         'jobs', 'performance-reviews', 'roles'],
        'appliedPatterns': ['PIM-centered employee profile',
                            'leave/time/performance as connected employee modules',
                            'role-based administration boundaries'],
    },
    {
        'name': 'IceHrm',
        'githubRepo': 'https://github.com/gamonoid/icehrm',
        'stars': 709,
        'pattern': 'employee records, leave, attendance, timesheets, payroll reports',
        'focusModules': ['employees', 'employee-requests', 'attendance-stats',
                         'payroll-records', 'dashboard'],
        'appliedPatterns': ['simple HR operations coverage',
                            'attendance and leave reporting',
                            'payroll summary visibility'],
    },
    {
        'name': 'TimeOff.Management',
        'githubRepo': 'https://github.com/timeoff-management/timeoff-management-application',
        'stars': 1034,
        'pattern': 'absence management, leave calendar, employee self service',
        'focusModules': ['employee-requests', 'attendance-stats', 'notifications'],
        'appliedPatterns': ['request lifecycle clarity',
                            'absence data feeding attendance summaries',
                            'employee-facing status transparency'],
    },
    {
        'name': 'Sentrifugo',
        'githubRepo': 'https://github.com/sapplica/sentrifugo',
        'stars': 533,
        'pattern': 'HRMS with appraisal, leave, service requests, analytics, self service',
        'focusModules': ['performance-reviews', 'employee-requests', 'feedback',
                         'dashboard', 'operation-logs'],
        'appliedPatterns': ['appraisal connected to employee development',
                            'service request governance',
                            'audit-friendly HR workflows'],
    },
    {
        'name': 'Jorani',
        'githubRepo': 'https://github.com/jorani/jorani',
        'stars': 407,
        'pattern': 'leave and overtime management',
        'focusModules': ['employee-requests', 'attendance-records',
                         'approvals-pending', 'payroll-records'],
        'appliedPatterns': ['leave/overtime request specialization',
                            'approval before payroll impact',
                            'calendar-aware absence operations'],
    },
)


def all_module_specs() -> List[HrmModuleSpec]:
    return list(MODULE_SPECS)


def module_by_id(module_id: str) -> Optional[HrmModuleSpec]:
    for spec in MODULE_SPECS:
        if spec.id == module_id:
            return spec
    return None


def _module_labels(module_ids: Iterable[str]) -> List[str]:
    labels: List[str] = []
    for module_id in module_ids:
        spec = module_by_id(module_id)
        labels.append(spec.label if spec else module_id)
    return labels


def _flow_summary(flow: Dict[str, Any]) -> str:
    labels = _module_labels(flow.get('modules') or [])
    return f"{flow['name']}：" + ' -> '.join(labels)


def module_catalog_overview_for_assistant() -> Dict[str, Any]:
    modules = [spec.to_dict() for spec in MODULE_SPECS]
    flow_summaries = [_flow_summary(flow) for flow in BUSINESS_FLOWS]
    group_summaries = []
    groups: Dict[str, List[str]] = {}
    for spec in MODULE_SPECS:
        groups.setdefault(spec.group, []).append(spec.label)
    for name, labels in groups.items():
        group_summaries.append(f'{name}（{len(labels)}）：' + '、'.join(labels))

    summary = (
        f'系统共覆盖 {len(MODULE_SPECS)} 个 HRM 模块。'
        f'模块分组：{"；".join(group_summaries)}。'
        f'核心业务链路：{"；".join(flow_summaries)}。'
        '开源 HRM 对标：'
        + '；'.join(f"{item['name']}（{item['pattern']}）" for item in OPEN_SOURCE_BENCHMARKS)
        + '。'
    )
    return {
        'view': 'overview',
        'summary': summary,
        'modules': modules,
        'flows': [dict(flow) for flow in BUSINESS_FLOWS],
        'benchmarks': [dict(item) for item in OPEN_SOURCE_BENCHMARKS],
        'moduleCount': len(MODULE_SPECS),
    }


def module_catalog_detail_for_assistant(module_id: str) -> Optional[Dict[str, Any]]:
    spec = module_by_id(module_id)
    if not spec:
        return None

    upstream_labels = _module_labels(spec.upstream)
    downstream_labels = _module_labels(spec.downstream)
    flow_names = [
        flow['name']
        for flow in BUSINESS_FLOWS
        if spec.id in (flow.get('modules') or [])
    ]
    capability_text = '、'.join(spec.capabilities) if spec.capabilities else '基础查询与维护'
    benchmark_text = '、'.join(spec.benchmark_patterns) if spec.benchmark_patterns else '通用 HRM 模块'
    summary = (
        f'{spec.label}位于{spec.group}，入口是 {spec.path}。'
        f'上游：{"、".join(upstream_labels) if upstream_labels else "无显式上游"}；'
        f'下游：{"、".join(downstream_labels) if downstream_labels else "无显式下游"}。'
        f'能力点：{capability_text}。'
        f'业务链路：{"、".join(flow_names) if flow_names else "未归入核心链路"}。'
        f'开源对标模式：{benchmark_text}。'
        f'AI 技能：{spec.ai_skill}，意图：{spec.ai_intent}。'
    )
    return {
        'view': 'module',
        'summary': summary,
        'module': spec.to_dict(),
        'moduleId': spec.id,
        'flows': [dict(flow) for flow in BUSINESS_FLOWS if spec.id in (flow.get('modules') or [])],
    }


def module_catalog_flow_for_assistant(flow_id: str) -> Optional[Dict[str, Any]]:
    for flow in BUSINESS_FLOWS:
        if flow.get('id') != flow_id:
            continue
        modules = [module_by_id(module_id) for module_id in flow.get('modules') or []]
        module_dicts = [spec.to_dict() for spec in modules if spec]
        summary = _flow_summary(flow)
        return {
            'view': 'flow',
            'summary': summary,
            'flow': dict(flow),
            'modules': module_dicts,
            'moduleCount': len(module_dicts),
        }
    return None


def resource_module_ids() -> Dict[str, str]:
    return {spec.resource: spec.id for spec in MODULE_SPECS if spec.resource}


def assistant_nav_module_plans(high_risk_value: str = 'high') -> List[Dict[str, Any]]:
    plans: List[Dict[str, Any]] = []
    for spec in MODULE_SPECS:
        labels = list(dict.fromkeys([spec.label, *spec.aliases]))
        plan: Dict[str, Any] = {
            'labels': labels,
            'tool': spec.ai_skill,
            'intent': spec.ai_intent,
        }
        if spec.ai_input:
            plan['input'] = dict(spec.ai_input)
        if spec.risk == 'high':
            plan['risk'] = high_risk_value
        plans.append(plan)
    return plans


def module_catalog_payload() -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for spec in MODULE_SPECS:
        groups.setdefault(spec.group, []).append(spec.to_dict())
    return {
        'modules': [spec.to_dict() for spec in MODULE_SPECS],
        'groups': [{'name': name, 'modules': modules} for name, modules in groups.items()],
        'flows': [dict(flow) for flow in BUSINESS_FLOWS],
        'benchmarks': [dict(item) for item in OPEN_SOURCE_BENCHMARKS],
    }
