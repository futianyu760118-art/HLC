"""Planner catalog slot helpers for page and workflow assistance."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..schemas import AssistantContext


def page_capability_slots(ctx: AssistantContext) -> Dict[str, Any]:
    module_id = module_id_from_client_context(getattr(ctx, 'client_context', None) or {})
    if module_id:
        return {'module': 'module_catalog', 'view': 'module', 'module_id': module_id, 'limit': 12}
    return {'module': 'module_catalog', 'view': 'overview', 'limit': 12}


def workflow_help_slots(text: str, ctx: AssistantContext) -> Dict[str, Any]:
    flow_id = flow_id_from_text(text)
    if flow_id:
        return {'module': 'module_catalog', 'view': 'flow', 'flow_id': flow_id, 'limit': 12}
    module_id = module_id_from_text(text) or module_id_from_client_context(getattr(ctx, 'client_context', None) or {})
    if module_id:
        return {'module': 'module_catalog', 'view': 'module', 'module_id': module_id, 'limit': 12}
    return {'module': 'module_catalog', 'view': 'overview', 'limit': 12}


def flow_id_from_text(text: str) -> Optional[str]:
    raw = text or ''
    if re.search(r'(招聘到入职|招聘.*入职|候选人.*入职|offer.*入职|Offer.*入职)', raw):
        return 'recruit_to_onboard'
    if re.search(r'(员工生命周期|入职.*转正.*离职|调岗.*离职|合同.*离职)', raw):
        return 'employee_lifecycle'
    if re.search(r'(考勤到薪酬|考勤.*薪酬|考勤.*工资|打卡.*工资|请假.*工资)', raw):
        return 'attendance_to_payroll'
    if re.search(r'(绩效与成长|绩效.*培训|绩效.*成长)', raw):
        return 'performance_to_growth'
    if re.search(r'(绩效到薪酬|绩效.*薪酬|绩效.*工资|调薪.*绩效)', raw):
        return 'performance_to_compensation'
    if re.search(r'(审批与治理|审批.*通知|审批.*反馈|流程.*治理|待办.*审批)', raw):
        return 'workflow_governance'
    return None


def module_id_from_text(text: str) -> Optional[str]:
    raw = text or ''
    aliases = [
        ('岗位', 'jobs'),
        ('职位', 'jobs'),
        ('JD', 'jobs'),
        ('jd', 'jobs'),
        ('简历', 'resumes'),
        ('候选人', 'candidates'),
        ('应聘者', 'candidates'),
        ('面试', 'interviews'),
        ('复试', 'interviews'),
        ('Offer', 'offers'),
        ('offer', 'offers'),
        ('入职', 'onboarding-tasks'),
        ('员工', 'employees'),
        ('同事', 'employees'),
        ('部门', 'departments'),
        ('组织', 'departments'),
        ('调岗', 'employee-changes'),
        ('转岗', 'employee-changes'),
        ('异动', 'employee-changes'),
        ('离职', 'resignations'),
        ('转正', 'probations'),
        ('合同', 'contracts'),
        ('考勤', 'attendance-records'),
        ('打卡', 'attendance-records'),
        ('迟到', 'attendance-records'),
        ('绩效', 'performance-reviews'),
        ('薪酬', 'payroll-records'),
        ('薪资', 'payroll-records'),
        ('工资', 'payroll-records'),
        ('审批', 'approvals-pending'),
        ('申请', 'employee-requests'),
        ('待办', 'approvals-pending'),
        ('跟进任务', 'notifications'),
        ('提醒', 'notifications'),
        ('通知', 'notifications'),
        ('反馈', 'feedback'),
        ('bug', 'feedback'),
        ('Bug', 'feedback'),
        ('日志', 'operation-logs'),
    ]
    for marker, module_id in aliases:
        if marker in raw:
            return module_id
    return None


def module_id_from_client_context(client_context: Dict[str, Any]) -> Optional[str]:
    raw_values = [
        client_context.get('moduleId'),
        client_context.get('module_id'),
        client_context.get('path'),
        client_context.get('pageTitle'),
        client_context.get('moduleName'),
    ]
    text = ' '.join(str(value or '') for value in raw_values)
    path = str(client_context.get('path') or '').strip().lower()
    path_map = {
        '/home': 'dashboard',
        '/job-manage': 'jobs',
        '/resume-manage': 'resumes',
        '/candidate-manage': 'candidates',
        '/hrm/candidates': 'candidates',
        '/interview-manage': 'interviews',
        '/offer-manage': 'offers',
        '/hrm/offers': 'offers',
        '/hrm/employees': 'employees',
        '/employee-manage': 'employees',
        '/hrm/departments': 'departments',
        '/hrm/positions': 'positions',
        '/attendance-stats': 'attendance-stats',
        '/hrm/attendance-records': 'attendance-records',
        '/performance-review': 'performance-reviews',
        '/performance-cycle': 'performance-cycles',
        '/salary-profiles': 'salary-profiles',
        '/hrm/payroll-records': 'payroll-records',
        '/approval-center': 'approvals-pending',
        '/employee-requests': 'employee-requests',
        '/feedback': 'feedback',
        '/notifications': 'notifications',
    }
    if path in path_map:
        return path_map[path]
    aliases = [
        ('岗位管理', 'jobs'),
        ('简历管理', 'resumes'),
        ('候选人', 'candidates'),
        ('面试管理', 'interviews'),
        ('Offer管理', 'offers'),
        ('员工管理', 'employees'),
        ('员工档案', 'employees'),
        ('部门管理', 'departments'),
        ('岗位体系', 'positions'),
        ('考勤', 'attendance-records'),
        ('绩效', 'performance-reviews'),
        ('薪酬', 'payroll-records'),
        ('工资', 'payroll-records'),
        ('审批', 'approvals-pending'),
        ('申请', 'employee-requests'),
        ('反馈', 'feedback'),
        ('通知', 'notifications'),
        ('驾驶舱', 'dashboard'),
    ]
    for marker, module_id in aliases:
        if marker in text:
            return module_id
    raw_module = str(client_context.get('moduleId') or client_context.get('module_id') or '').strip()
    if raw_module:
        normalized = raw_module.strip('/').replace('_', '-').lower()
        if normalized == 'job-manage':
            return 'jobs'
        return normalized
    return None


__all__ = [
    'flow_id_from_text',
    'module_id_from_client_context',
    'module_id_from_text',
    'page_capability_slots',
    'workflow_help_slots',
]
