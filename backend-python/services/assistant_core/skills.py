"""通用 Skill handlers。

设计原则：
- 少量通用 skill，不为每个业务任务造一个新 skill。
- 所有 handler 接收 (args: dict, ctx: AssistantContext) → SkillOutput dict。
- 输出格式统一：{ entities, widgets, metrics, rows_count, summary_hint }。
- 查询与证据工具只读；用户在对话内明确确认后的动作工具可按计划写入。
- 数据按角色脱敏后再返回。
- 失败抛异常由 executor 统一处理。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, or_

from models import (
    ApprovalInstance, ApprovalRecord, AttendanceRecord, Candidate, Contract,
    Department, Employee, EmployeeChange, EmployeeRequest, Feedback, Interview, Job,
    Notification, Offer, OnboardingTask, OperationLog, PayrollRecord, PerformanceCycle,
    PerformanceReview, Position, Probation, Resignation, Resume, SalaryProfile,
    Role, Setting, TrainingCourse, TrainingPlan, TrainingRecord, User, db,
)
from services.business_time import business_now, parse_business_datetime
from services.hrm_module_catalog import (
    module_catalog_detail_for_assistant,
    module_catalog_flow_for_assistant,
    module_catalog_overview_for_assistant,
)

from . import widgets as W
from .model_settings import SETTING_KEY as ASSISTANT_MODEL_SETTINGS_KEY
from .constants import (
    PAYROLL_AUTHORIZED_ROLES, PRIVILEGED_ROLES, RISK_HIGH, RISK_LOW, RISK_MEDIUM,
    ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_EXECUTIVE, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_RECRUITER,
)
from .guardrails import (
    desensitize_employee, desensitize_resume, employee_scope_filter,
    mask_email, mask_phone,
)
from .smart_query import execute_smart_sql

logger = logging.getLogger('hengpintong.assistant.skills')

# 单 skill 默认 limit
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def _clamp_limit(value: Any, default: int = DEFAULT_LIMIT, hard_max: int = MAX_LIMIT) -> int:
    try:
        n = int(value)
        return max(1, min(n, hard_max))
    except (TypeError, ValueError):
        return default


def _since(days: Any) -> Optional[datetime]:
    try:
        n = int(days)
        if n <= 0:
            return None
        return datetime.utcnow() - timedelta(days=n)
    except (TypeError, ValueError):
        return None


def _fmt_amount(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if number.is_integer():
        return f'{number:,.0f}'
    return f'{number:,.2f}'


def _parse_date_range(date_range: Optional[Dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not isinstance(date_range, dict):
        return None, None
    if date_range.get('recent_days') or date_range.get('recentDays'):
        since = _since(date_range.get('recent_days') or date_range.get('recentDays'))
        return since, None
    start = None
    end = None
    try:
        if date_range.get('start'):
            start = parse_business_datetime(date_range['start'])
        if date_range.get('end'):
            end = parse_business_datetime(date_range['end'])
    except Exception:
        pass
    return start, end


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


def _is_attendance_normal(status: Any) -> bool:
    return str(status or 'normal') == 'normal'


# ============================================================
# 实体卡片格式化（前端跳转）
# ============================================================
def _employee_card(e: Employee, role: str, ctx) -> Dict[str, Any]:
    base = {
        'type': 'employee', 'typeLabel': '员工', 'icon': 'fa-id-card',
        'id': e.id, 'title': e.name,
        'subtitle': ' · '.join(filter(None, [
            e.employee_no,
            e.department.name if e.department else None,
            e.job_title or (e.position.title if e.position else None),
        ])),
        'meta': f'状态：{e.status or "—"}',
        'url': '/hrm/employees',
    }
    return base


def _candidate_card(c: Candidate) -> Dict[str, Any]:
    return {
        'type': 'candidate', 'typeLabel': '候选人', 'icon': 'fa-user-tie',
        'id': c.id, 'title': c.name,
        'subtitle': ' · '.join(filter(None, [c.job.title if c.job else None])),
        'meta': f'状态：{c.status or "—"}',
        'url': '/hrm/candidates',
    }


def _resume_card(r: Resume, role: str) -> Dict[str, Any]:
    score = (r.ai_analysis or {}).get('score') if isinstance(r.ai_analysis, dict) else None
    return {
        'type': 'resume', 'typeLabel': '简历', 'icon': 'fa-file-alt',
        'id': r.id, 'title': r.candidate_name,
        'subtitle': r.job.title if r.job else '—',
        'meta': f'AI评分：{score}分' if score is not None else '尚未评分',
        'url': f'/resume-detail?resumeId={r.id}',
    }


def _job_card(j: Job) -> Dict[str, Any]:
    return {
        'type': 'job', 'typeLabel': '岗位', 'icon': 'fa-briefcase',
        'id': j.id, 'title': j.title,
        'subtitle': j.department or '',
        'meta': f'状态：{"招聘中" if j.status == "open" else "已关闭"}',
        'url': f'/job-detail?jobId={j.id}',
    }


def _interview_card(i: Interview) -> Dict[str, Any]:
    return {
        'type': 'interview', 'typeLabel': '面试', 'icon': 'fa-users',
        'id': i.id,
        'title': f'{i.resume.candidate_name if i.resume else "候选人"} - {i.job.title if i.job else "岗位"}',
        'subtitle': i.scheduled_at.strftime('%Y-%m-%d %H:%M') if i.scheduled_at else '',
        'meta': f'状态：{i.status or "—"}',
        'url': f'/interview-detail?interviewId={i.id}',
    }


def _recruitment_ranked_candidate_card(row: Dict[str, Any], rank: int) -> Optional[Dict[str, Any]]:
    candidate = row.get('candidate')
    resume = row.get('resume')
    if candidate:
        card = _candidate_card(candidate)
        card['source_tool'] = 'recruitment_match_matrix'
        card['rank'] = rank
        card['displayRank'] = rank
        card['matchScore'] = row.get('finalScore')
        card['subtitle'] = ' · '.join(filter(None, [
            card.get('subtitle'),
            f'综合匹配 {row.get("finalScore")} 分',
        ]))
        card['meta'] = f'第 {rank} 名 · 状态：{row.get("status") or "—"}'
        return card
    if resume:
        return {
            'type': 'resume',
            'typeLabel': '简历',
            'icon': 'fa-file-alt',
            'id': resume.id,
            'title': row.get('name') or resume.candidate_name,
            'subtitle': f'{resume.job.title if resume.job else "—"} · 综合匹配 {row.get("finalScore")} 分',
            'meta': f'第 {rank} 名 · 简历待转候选人',
            'url': f'/resume-detail?resumeId={resume.id}',
            'source_tool': 'recruitment_match_matrix',
            'rank': rank,
            'displayRank': rank,
            'matchScore': row.get('finalScore'),
        }
    return None


def _offer_card(o: Offer) -> Dict[str, Any]:
    return {
        'type': 'offer', 'typeLabel': 'Offer', 'icon': 'fa-file-signature',
        'id': o.id, 'title': o.title,
        'subtitle': o.candidate.name if o.candidate else '—',
        'meta': f'状态：{o.status or "—"}',
        'url': '/hrm/offers',
    }


def _lifecycle_entity_cards(
    employee: Employee,
    *,
    ctx,
    candidates: List[Candidate],
    resumes: List[Resume],
    jobs: List[Job],
    interviews: List[Interview],
    offers: List[Offer],
    onboarding_tasks: List[OnboardingTask],
    contracts: List[Contract],
    attendance_records: List[AttendanceRecord],
    employee_requests: List[EmployeeRequest],
    salary_profiles: List[SalaryProfile],
    payroll_records: List[PayrollRecord],
    performance_reviews: List[PerformanceReview],
    training_records: List[TrainingRecord],
    probations: List[Probation],
    employee_changes: List[EmployeeChange],
    resignations: List[Resignation],
    approvals: List[ApprovalInstance],
    notifications: List[Notification],
) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = [_employee_card(employee, ctx.role, ctx)]
    seen = {('employee', employee.id)}

    def add(card: Optional[Dict[str, Any]]) -> None:
        if not isinstance(card, dict):
            return
        key = (str(card.get('type') or ''), str(card.get('id') or ''))
        if not key[0] or not key[1] or key in seen:
            return
        seen.add(key)
        cards.append(card)

    for row in candidates[:4]:
        add(_candidate_card(row))
    for row in resumes[:4]:
        add(_resume_card(row, ctx.role))
    for row in jobs[:4]:
        add(_job_card(row))
    for row in interviews[:4]:
        add(_interview_card(row))
    for row in offers[:3]:
        add(_offer_card(row))
    for row in onboarding_tasks[:4]:
        data = row.to_dict()
        add(_generic_card('onboarding_task', row.id, data.get('name') or '入职任务', data.get('employeeName') or '', f'状态：{data.get("status") or "—"}', '/hrm/onboarding-tasks'))
    for row in contracts[:3]:
        data = row.to_dict()
        add(_generic_card('contract', row.id, data.get('contractNo') or '劳动合同', data.get('contractType') or data.get('employeeName') or '', f'状态：{data.get("status") or "—"}', '/hrm/contracts'))
    for row in probations[:3]:
        data = row.to_dict()
        add(_generic_card('probation', row.id, f'转正：{data.get("employeeName") or employee.name}', data.get('result') or '', f'状态：{data.get("status") or "—"}', '/hrm/probations'))
    for row in employee_changes[:4]:
        data = row.to_dict()
        add(_generic_card('employee_change', row.id, data.get('changeType') or '人事异动', data.get('employeeName') or '', f'状态：{data.get("status") or "—"}', '/hrm/employee-changes'))
    for row in resignations[:3]:
        data = row.to_dict()
        add(_generic_card('resignation', row.id, f'离职：{data.get("employeeName") or employee.name}', data.get('reason') or '', f'状态：{data.get("status") or "—"}', '/hrm/resignations'))
    for row in performance_reviews[:3]:
        data = row.to_dict()
        add(_generic_card('performance', row.id, data.get('employeeName') or '绩效记录', data.get('cycleName') or '', f'等级：{data.get("grade") or "—"}', '/performance-review'))
    for row in training_records[:3]:
        data = row.to_dict()
        add(_generic_card('training', row.id, data.get('employeeName') or '培训记录', data.get('courseName') or '', f'状态：{data.get("status") or "—"}', '/hrm/training-records'))
    for row in employee_requests[:3]:
        data = row.to_dict()
        add(_generic_card('employee_request', row.id, data.get('title') or data.get('requestType') or '员工申请', data.get('employeeName') or '', f'状态：{data.get("status") or "—"}', '/employee-requests'))
    for row in attendance_records[:2]:
        data = row.to_dict()
        add(_generic_card('attendance', row.id, data.get('employeeName') or '考勤记录', data.get('attendanceDate') or '', f'状态：{data.get("status") or "—"}', '/hrm/attendance-records'))
    for row in salary_profiles[:2]:
        data = row.to_dict()
        add(_generic_card('payroll', row.id, data.get('employeeName') or '薪资档案', f'总薪资：{_fmt_amount(data.get("totalSalary"))} 元', f'状态：{data.get("status") or "—"}', '/salary-profiles'))
    for row in payroll_records[:2]:
        data = row.to_dict()
        add(_generic_card('payroll', row.id, data.get('employeeName') or '工资条', data.get('payrollMonth') or '', f'状态：{data.get("status") or "—"}', '/hrm/payroll-records'))
    for row in approvals[:3]:
        data = row.to_dict()
        add(_generic_card('approval', row.id, data.get('title') or '审批记录', data.get('businessType') or '', f'状态：{data.get("status") or "—"}', '/approval-center/records'))
    for row in notifications[:2]:
        data = row.to_dict()
        add(_generic_card('notification', row.id, data.get('title') or '通知', data.get('noticeType') or '', f'状态：{data.get("status") or "—"}', data.get('linkUrl') or '/notifications'))
    return cards


def _department_card(d: Department) -> Dict[str, Any]:
    return {
        'type': 'department', 'typeLabel': '部门', 'icon': 'fa-sitemap',
        'id': d.id, 'title': d.name,
        'subtitle': d.code or '',
        'meta': '',
        'url': '/hrm/departments',
    }


def _feedback_card(f: Feedback) -> Dict[str, Any]:
    type_label = {'bug': '缺陷', 'feature': '需求', 'other': '其他'}.get(f.feedback_type, '反馈')
    return {
        'type': 'feedback', 'typeLabel': '问题反馈', 'icon': 'fa-comment-medical',
        'id': f.id, 'title': f.title,
        'subtitle': type_label,
        'meta': f'状态：{f.status or "—"}',
        'url': '/feedback',
    }


# ============================================================
# 1. global_search
# ============================================================
def skill_global_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    keyword = (args.get('keyword') or '').strip()
    limit = _clamp_limit(args.get('limit'), default=10)
    if not keyword:
        return {'entities': [], 'rows_count': 0, 'summary_hint': '关键词为空。'}

    like = f'%{keyword}%'
    entities: List[Dict[str, Any]] = []
    role = ctx.role
    per_module = max(1, min(3, limit // 3))

    try:
        for e in (Employee.query.filter(or_(
            Employee.name.like(like), Employee.employee_no.like(like),
            Employee.email.like(like), Employee.phone.like(like),
        )).limit(per_module).all()):
            entities.append(_employee_card(e, role, ctx))
    except Exception:
        logger.exception('global_search_employee')

    try:
        for c in Candidate.query.filter(or_(
            Candidate.name.like(like), Candidate.email.like(like), Candidate.phone.like(like),
        )).limit(per_module).all():
            entities.append(_candidate_card(c))
    except Exception:
        logger.exception('global_search_candidate')

    try:
        for r in Resume.query.filter(or_(
            Resume.candidate_name.like(like), Resume.email.like(like), Resume.phone.like(like),
        )).limit(per_module).all():
            entities.append(_resume_card(r, role))
    except Exception:
        logger.exception('global_search_resume')

    try:
        for j in Job.query.filter(or_(
            Job.title.like(like), Job.department.like(like), Job.location.like(like),
        )).limit(per_module).all():
            entities.append(_job_card(j))
    except Exception:
        logger.exception('global_search_job')

    try:
        for d in Department.query.filter(or_(Department.name.like(like), Department.code.like(like))).limit(per_module).all():
            entities.append(_department_card(d))
    except Exception:
        logger.exception('global_search_department')

    try:
        for f in Feedback.query.filter(or_(Feedback.title.like(like), Feedback.content.like(like))).limit(per_module).all():
            entities.append(_feedback_card(f))
    except Exception:
        logger.exception('global_search_feedback')

    return {
        'entities': entities,
        'rows_count': len(entities),
        'summary_hint': f'通过关键词"{keyword}"在多个模块中找到 {len(entities)} 条相关数据。',
    }


# ============================================================
# 2. employee_search
# ============================================================
def skill_employee_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    keyword = (args.get('keyword') or '').strip()
    department_id = args.get('department_id')
    status = args.get('status')
    limit = _clamp_limit(args.get('limit'))
    role = ctx.role

    q = Employee.query
    if keyword:
        like = f'%{keyword}%'
        q = q.filter(or_(
            Employee.name.like(like), Employee.employee_no.like(like),
            Employee.email.like(like), Employee.phone.like(like),
            Employee.job_title.like(like),
        ))
    if status:
        q = q.filter(Employee.status == status)
    if department_id:
        q = q.filter(Employee.department_id == department_id)

    # 范围限制
    scope = employee_scope_filter(role, ctx)
    if scope.get('_self_only'):
        q = q.filter(Employee.id == scope['_self_only'])
    elif scope.get('_department_id'):
        q = q.filter(Employee.department_id == scope['_department_id'])

    rows = q.order_by(desc(Employee.created_at)).limit(limit).all()

    entities = [_employee_card(e, role, ctx) for e in rows]

    columns = [
        {'key': 'employeeNo', 'label': '工号'},
        {'key': 'name', 'label': '姓名'},
        {'key': 'department', 'label': '部门'},
        {'key': 'jobTitle', 'label': '岗位'},
        {'key': 'status', 'label': '状态'},
        {'key': 'hireDate', 'label': '入职日期'},
    ]
    table_rows = []
    for e in rows:
        record = {
            'id': e.id,
            'employeeNo': e.employee_no or '—',
            'name': e.name,
            'department': e.department.name if e.department else '—',
            'jobTitle': e.job_title or (e.position.title if e.position else '—'),
            'status': e.status or '—',
            'hireDate': e.hire_date.strftime('%Y-%m-%d') if e.hire_date else '—',
            'phone': e.phone, 'email': e.email,
        }
        record = desensitize_employee(record, role, ctx.user_employee_id)
        table_rows.append(record)

    out_widgets = []
    if table_rows:
        out_widgets.append(W.data_table(columns, table_rows, title=f'员工查询结果（{len(table_rows)}）'))

    return {
        'entities': entities,
        'widgets': out_widgets,
        'rows_count': len(rows),
        'summary_hint': f'命中 {len(rows)} 名员工。' if rows else '未匹配到员工。',
    }


# ============================================================
# 3. recruitment_search
# ============================================================
def skill_recruitment_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    keyword = (args.get('keyword') or '').strip()
    module = (args.get('module') or 'all').lower()
    status = args.get('status')
    limit = _clamp_limit(args.get('limit'))
    count_only = bool(args.get('count_only') or args.get('countOnly'))
    start, end = _parse_date_range(args.get('date_range'))
    role = ctx.role

    entities: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    metrics: Dict[str, Any] = {}
    widgets_out: List[Dict[str, Any]] = []

    def record_total(label: str, total: int, unit: str = '条') -> None:
        metrics['total'] = metrics.get('total', 0) + total
        key = label.lower() if re.fullmatch(r'[A-Za-z]+', label) else label
        metrics[f'{key}_total'] = total
        text_parts.append(f'{label} {total} {unit}')

    def add_jobs():
        q = Job.query
        if keyword:
            like = f'%{keyword}%'
            q = q.filter(or_(Job.title.like(like), Job.department.like(like), Job.location.like(like)))
        if status:
            q = q.filter(Job.status == status)
        if start:
            q = q.filter(Job.created_at >= start)
        if end:
            q = q.filter(Job.created_at <= end)
        total = q.count()
        if count_only:
            record_total('岗位', total)
            return
        rows = q.order_by(desc(Job.created_at)).limit(limit).all()
        for j in rows:
            entities.append(_job_card(j))
        record_total('岗位', total)

    def add_candidates():
        q = Candidate.query
        if keyword:
            like = f'%{keyword}%'
            q = q.outerjoin(Job, Candidate.job_id == Job.id).outerjoin(
                Resume, Candidate.resume_id == Resume.id,
            ).filter(or_(
                Candidate.name.like(like),
                Candidate.email.like(like),
                Candidate.phone.like(like),
                Candidate.ai_summary.like(like),
                Candidate.ai_recommendation.like(like),
                Job.title.like(like),
                Job.department.like(like),
                Resume.candidate_name.like(like),
                Resume.email.like(like),
                Resume.phone.like(like),
            ))
        if status:
            q = q.filter(Candidate.status == status)
        if start:
            q = q.filter(Candidate.created_at >= start)
        if end:
            q = q.filter(Candidate.created_at <= end)
        total = q.count()
        if count_only:
            record_total('候选人', total)
            return
        rows = q.order_by(desc(Candidate.created_at)).limit(limit).all()
        if not rows and start is not None and keyword:
            q = Candidate.query
            like = f'%{keyword}%'
            q = q.outerjoin(Job, Candidate.job_id == Job.id).outerjoin(
                Resume, Candidate.resume_id == Resume.id,
            ).filter(or_(
                Candidate.name.like(like),
                Candidate.email.like(like),
                Candidate.phone.like(like),
                Candidate.ai_summary.like(like),
                Candidate.ai_recommendation.like(like),
                Job.title.like(like),
                Job.department.like(like),
                Resume.candidate_name.like(like),
                Resume.email.like(like),
                Resume.phone.like(like),
            ))
            if status:
                q = q.filter(Candidate.status == status)
            total = q.count()
            rows = q.order_by(desc(Candidate.created_at)).limit(limit).all()
        for c in rows:
            entities.append(_candidate_card(c))
        record_total('候选人', total)

    def add_resumes():
        q = Resume.query
        if keyword:
            like = f'%{keyword}%'
            q = q.outerjoin(Job, Resume.job_id == Job.id).filter(or_(
                Resume.candidate_name.like(like),
                Resume.email.like(like),
                Resume.phone.like(like),
                Job.title.like(like),
                Job.department.like(like),
            ))
        if start:
            q = q.filter(Resume.created_at >= start)
        if end:
            q = q.filter(Resume.created_at <= end)
        total = q.count()
        if count_only:
            record_total('简历', total)
            return
        rows = q.order_by(desc(Resume.created_at)).limit(limit).all()
        if not rows and start is not None and keyword:
            q = Resume.query
            like = f'%{keyword}%'
            q = q.outerjoin(Job, Resume.job_id == Job.id).filter(or_(
                Resume.candidate_name.like(like),
                Resume.email.like(like),
                Resume.phone.like(like),
                Job.title.like(like),
                Job.department.like(like),
            ))
            total = q.count()
            rows = q.order_by(desc(Resume.created_at)).limit(limit).all()
        for r in rows:
            entities.append(_resume_card(r, role))
        record_total('简历', total)

    def add_interviews():
        q = Interview.query
        if status:
            q = q.filter(Interview.status == status)
        if keyword:
            like = f'%{keyword}%'
            q = q.outerjoin(Resume, Interview.resume_id == Resume.id).outerjoin(
                Job, Interview.job_id == Job.id,
            ).filter(or_(
                Resume.candidate_name.like(like),
                Interview.notes.like(like),
                Job.title.like(like),
                Job.department.like(like),
            ))
        if start:
            q = q.filter(Interview.scheduled_at >= start)
        if end:
            q = q.filter(Interview.scheduled_at <= end)
        total = q.count()
        if count_only:
            record_total('面试', total, '场')
            return
        rows = q.order_by(desc(Interview.scheduled_at)).limit(limit).all()
        for i in rows:
            entities.append(_interview_card(i))
        record_total('面试', total, '场')

    def add_offers():
        q = Offer.query
        if status:
            q = q.filter(Offer.status == status)
        if keyword:
            like = f'%{keyword}%'
            q = q.outerjoin(Candidate, Offer.candidate_id == Candidate.id).outerjoin(
                Job, Offer.job_id == Job.id,
            ).filter(or_(
                Offer.title.like(like),
                Candidate.name.like(like),
                Job.title.like(like),
                Job.department.like(like),
            ))
        if start:
            q = q.filter(Offer.created_at >= start)
        if end:
            q = q.filter(Offer.created_at <= end)
        total = q.count()
        if count_only:
            record_total('Offer', total)
            return
        rows = q.order_by(desc(Offer.created_at)).limit(limit).all()
        for o in rows:
            entities.append(_offer_card(o))
        record_total('Offer', total)

    dispatch = {
        'jobs': [add_jobs], 'resumes': [add_resumes], 'candidates': [add_candidates],
        'interviews': [add_interviews], 'offers': [add_offers],
        'all': [add_jobs, add_candidates, add_resumes, add_interviews, add_offers],
    }
    for fn in dispatch.get(module, dispatch['all']):
        try:
            fn()
        except Exception:
            logger.exception(f'recruitment_search_{fn.__name__}')

    if count_only:
        label = '招聘查询'
        if module in {'jobs', 'resumes', 'candidates', 'interviews', 'offers'}:
            label = {
                'jobs': '岗位',
                'resumes': '简历',
                'candidates': '候选人',
                'interviews': '面试',
                'offers': 'Offer',
            }[module]
        widgets_out.append(W.metric_cards([{'label': label, 'value': metrics.get('total', 0)}], title='招聘统计'))

    source_defs = {
        'jobs': {
            'module': 'jobs',
            'recordType': 'jobs',
            'title': f'岗位记录 {metrics.get("岗位_total", 0)} 条',
            'url': '/job-manage',
        },
        'candidates': {
            'module': 'candidates',
            'recordType': 'candidates',
            'title': f'候选人记录 {metrics.get("候选人_total", 0)} 条',
            'url': '/candidate-manage',
        },
        'resumes': {
            'module': 'resumes',
            'recordType': 'resumes',
            'title': f'简历记录 {metrics.get("简历_total", 0)} 条',
            'url': '/resume-manage',
        },
        'interviews': {
            'module': 'interviews',
            'recordType': 'interviews',
            'title': f'面试记录 {metrics.get("面试_total", 0)} 场',
            'url': '/interview-manage',
        },
        'offers': {
            'module': 'offers',
            'recordType': 'offers',
            'title': f'Offer 记录 {metrics.get("offer_total", 0)} 条',
            'url': '/offer-manage',
        },
    }
    source_total_keys = {
        'jobs': '岗位_total',
        'candidates': '候选人_total',
        'resumes': '简历_total',
        'interviews': '面试_total',
        'offers': 'Offer_total',
    }
    source_keys = [module] if module in source_defs else ['jobs', 'candidates', 'resumes', 'interviews', 'offers']
    sources = [
        source_defs[key]
        for key in source_keys
        if key in source_defs and (
            module == key
            or module == 'all'
            or metrics.get(source_total_keys.get(key, ''), 0)
            or key == module
        )
    ]
    if sources:
        widgets_out.append({
            'type': 'source_citations',
            'title': '本次使用的招聘系统记录',
            'sources': sources,
        })

    return {
        'entities': entities,
        'widgets': widgets_out,
        'metrics': metrics,
        'rows_count': metrics.get('total', len(entities)) if count_only else len(entities),
        'summary_hint': '招聘域命中：' + '、'.join(text_parts) if text_parts else '招聘域未命中。',
    }


# ============================================================
# 4. resume_analysis
# ============================================================
def skill_resume_analysis(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    days = args.get('recent_days') or 7
    try:
        days = max(1, min(int(days), 90))
    except Exception:
        days = 7
    job_id = args.get('job_id')
    keyword = (args.get('keyword') or '').strip()
    top_n = _clamp_limit(args.get('top_n'), default=10, hard_max=30)
    role = ctx.role
    since = datetime.utcnow() - timedelta(days=days)

    q = Resume.query.filter(Resume.created_at >= since)
    if job_id:
        q = q.filter(Resume.job_id == job_id)
    if keyword:
        like = f'%{keyword}%'
        q = q.outerjoin(Job, Resume.job_id == Job.id).filter(or_(
            Resume.candidate_name.like(like),
            Job.title.like(like),
            Job.department.like(like),
        ))
    rows = q.order_by(desc(Resume.created_at)).all()

    if not rows:
        return {
            'entities': [], 'widgets': [W.empty_state(f'最近 {days} 天没有新简历。')],
            'rows_count': 0, 'summary_hint': f'近 {days} 天无简历记录。',
            'metrics': {},
        }

    total = len(rows)
    scored = [(int(r.ai_analysis['score']), r) for r in rows
              if isinstance(r.ai_analysis, dict) and r.ai_analysis.get('score') is not None]
    scored_count = len(scored)
    avg_score = round(sum(s for s, _ in scored) / scored_count, 1) if scored_count else 0
    high_count = sum(1 for s, _ in scored if s >= 80)

    # 评分分布
    bands = [('90+', 90, 101), ('80-89', 80, 90), ('70-79', 70, 80), ('60-69', 60, 70), ('<60', 0, 60)]
    score_dist = [{'label': lbl, 'value': sum(1 for s, _ in scored if lo <= s < hi)} for lbl, lo, hi in bands]

    # 岗位分布
    job_counter: Dict[str, int] = {}
    for r in rows:
        title = r.job.title if r.job else '未指定岗位'
        job_counter[title] = job_counter.get(title, 0) + 1
    job_dist = [{'label': k, 'value': v} for k, v in sorted(job_counter.items(), key=lambda x: -x[1])][:8]

    # TOP N
    scored.sort(key=lambda x: -x[0])
    top = scored[:top_n]
    cols = [
        {'key': 'name', 'label': '候选人'},
        {'key': 'job', 'label': '应聘岗位'},
        {'key': 'score', 'label': 'AI评分', 'align': 'right'},
        {'key': 'match', 'label': '匹配度', 'align': 'right'},
        {'key': 'date', 'label': '上传日期', 'align': 'right'},
    ]
    table_rows = []
    entities: List[Dict[str, Any]] = []
    for score, r in top:
        match = (r.ai_analysis or {}).get('matchDegree')
        rec = {
            'id': r.id,
            'name': r.candidate_name,
            'job': r.job.title if r.job else '—',
            'score': f'{score}分',
            'match': f'{match}%' if match is not None else '—',
            'date': r.created_at.strftime('%Y-%m-%d') if r.created_at else '—',
            'phone': r.phone, 'email': r.email,
        }
        rec = desensitize_resume(rec, role)
        table_rows.append(rec)
        entities.append(_resume_card(r, role))

    cards = [
        {'label': f'近{days}天简历', 'value': total, 'color': 'blue'},
        {'label': '已评分', 'value': scored_count, 'color': 'green'},
        {'label': '平均评分', 'value': avg_score, 'unit': '分', 'color': 'indigo'},
        {'label': '高分(≥80)', 'value': high_count, 'color': 'amber'},
    ]
    widgets_out = [
        W.metric_cards(cards, title='简历分析'),
        W.bar_chart(score_dist, title='AI 评分分布'),
        W.doughnut_chart(job_dist, title='应聘岗位分布', center_label='简历数'),
        W.data_table(cols, table_rows, title=f'TOP {len(top)} 候选人'),
    ]
    summary_hint = (f'近{days}天{total}份简历，已评分{scored_count}份（平均{avg_score}分），'
                    f'高分{high_count}份。')

    return {
        'entities': entities, 'widgets': widgets_out,
        'rows_count': total, 'summary_hint': summary_hint,
        'metrics': {'total': total, 'scored': scored_count, 'avg_score': avg_score, 'high_count': high_count},
        'top_resumes': [{'resume_id': r.id, 'name': r.candidate_name, 'score': s} for s, r in top],
    }


# ============================================================
# 5. interview_planning
# ============================================================
def skill_interview_planning(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    job_id = args.get('job_id')
    top_n = _clamp_limit(args.get('top_n'), default=10, hard_max=30)
    days = 7
    min_score = 70
    since = datetime.utcnow() - timedelta(days=days)
    role = ctx.role

    q = Resume.query.filter(Resume.created_at >= since)
    if job_id:
        q = q.filter(Resume.job_id == job_id)
    resumes = q.order_by(desc(Resume.created_at)).all()

    interviewed_ids = set()
    try:
        rows = Interview.query.with_entities(Interview.resume_id).filter(Interview.resume_id.isnot(None)).all()
        interviewed_ids = {r[0] for r in rows}
    except Exception:
        pass

    candidates = []
    for r in resumes:
        if r.id in interviewed_ids:
            continue
        if not isinstance(r.ai_analysis, dict):
            continue
        score = r.ai_analysis.get('score')
        if score is None or score < min_score:
            continue
        candidates.append((score, r))
    candidates.sort(key=lambda x: -x[0])
    candidates = candidates[:top_n]

    now = business_now()
    upcoming = Interview.query.filter(
        Interview.scheduled_at >= now,
        Interview.scheduled_at <= now + timedelta(days=14),
    ).order_by(Interview.scheduled_at.asc()).limit(20).all()

    base = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    slots = []
    day_offset = 0
    while len(slots) < len(candidates):
        d = base + timedelta(days=day_offset)
        if d.weekday() < 5:
            slots.append(d.replace(hour=10))
            slots.append(d.replace(hour=14))
            slots.append(d.replace(hour=16))
        day_offset += 1
        if day_offset > 30:
            break

    plan_cols = [
        {'key': 'priority', 'label': '优先级', 'align': 'center'},
        {'key': 'name', 'label': '候选人'},
        {'key': 'job', 'label': '应聘岗位'},
        {'key': 'score', 'label': 'AI评分', 'align': 'right'},
        {'key': 'phone', 'label': '联系电话'},
        {'key': 'suggest', 'label': '建议时段', 'align': 'center'},
    ]
    plan_rows = []
    entities: List[Dict[str, Any]] = []
    for idx, (score, r) in enumerate(candidates):
        priority = '高' if score >= 85 else ('中' if score >= 75 else '低')
        slot = slots[idx] if idx < len(slots) else None
        rec = {
            'id': r.id,
            'priority': priority,
            'name': r.candidate_name,
            'job': r.job.title if r.job else '—',
            'score': f'{score}分',
            'phone': r.phone or '—',
            'suggest': slot.strftime('%m-%d %H:%M') if slot else '待定',
        }
        rec = desensitize_resume(rec, role)
        plan_rows.append(rec)
        entities.append(_resume_card(r, role))

    upcoming_cols = [
        {'key': 'time', 'label': '时间'},
        {'key': 'name', 'label': '候选人'},
        {'key': 'job', 'label': '岗位'},
        {'key': 'status', 'label': '状态', 'align': 'center'},
    ]
    upcoming_rows = []
    for i in upcoming:
        upcoming_rows.append({
            'time': i.scheduled_at.strftime('%m-%d %H:%M') if i.scheduled_at else '—',
            'name': i.resume.candidate_name if i.resume else '—',
            'job': i.job.title if i.job else '—',
            'status': i.status or '—',
        })

    cards = [
        {'label': f'近{days}天高分简历', 'value': len(candidates), 'color': 'blue'},
        {'label': '建议立即面试', 'value': sum(1 for s, _ in candidates if s >= 85), 'color': 'red'},
        {'label': '未来14天已排', 'value': len(upcoming), 'color': 'green'},
        {'label': '最低评分门槛', 'value': min_score, 'unit': '分', 'color': 'gray'},
    ]
    widgets_out = [W.metric_cards(cards, title='面试计划')]
    if plan_rows:
        widgets_out.append(W.data_table(plan_cols, plan_rows, title=f'推荐面试候选人（{len(plan_rows)} 人）'))
    if upcoming_rows:
        widgets_out.append(W.data_table(upcoming_cols, upcoming_rows, title=f'未来 14 天已排面试'))
    widgets_out.append(W.warning(
        '此为建议计划。实际创建面试请到面试管理页面确认。',
        level='info',
    ))

    summary_hint = (f'生成 {len(plan_rows)} 位推荐面试候选人，已排面试 {len(upcoming)} 场。'
                    if plan_rows else f'近{days}天没有评分≥{min_score}的待面试候选人。')

    return {
        'entities': entities, 'widgets': widgets_out,
        'rows_count': len(plan_rows), 'summary_hint': summary_hint,
        'recommended_count': len(plan_rows),
        'upcoming_count': len(upcoming),
    }


# ============================================================
# 6. organization_search
# ============================================================
def skill_organization_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    keyword = (args.get('keyword') or '').strip()
    include_stats = args.get('include_stats', True)

    q = Department.query
    if keyword:
        like = f'%{keyword}%'
        q = q.filter(or_(Department.name.like(like), Department.code.like(like), Department.description.like(like)))
    depts = q.limit(50).all()

    entities = [_department_card(d) for d in depts]
    widgets_out = []

    if include_stats and depts:
        # 部门人数分布
        dist = []
        for d in depts:
            cnt = Employee.query.filter_by(department_id=d.id).count()
            if cnt > 0:
                dist.append({'label': d.name, 'value': cnt})
        dist.sort(key=lambda x: -x['value'])
        if dist:
            widgets_out.append(W.bar_chart(dist[:10], title='部门人数分布'))

    pos_count = Position.query.count()
    summary_hint = f'命中 {len(depts)} 个部门，共 {pos_count} 个岗位体系记录。'

    return {
        'entities': entities, 'widgets': widgets_out,
        'rows_count': len(depts), 'summary_hint': summary_hint,
    }


# ============================================================
# 7. approval_search
# ============================================================
def skill_approval_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    view = (args.get('view') or 'pending').lower()
    business_type = args.get('business_type')
    status = args.get('status')
    limit = _clamp_limit(args.get('limit'))

    q = ApprovalInstance.query
    if view == 'mine':
        q = q.filter(ApprovalInstance.applicant_id == ctx.user_id)
    elif view == 'pending':
        q = q.filter(ApprovalInstance.status == 'pending')
        if ctx.role not in ('admin', 'hr_admin', 'manager', 'executive'):
            q = q.filter(ApprovalInstance.approver_id == ctx.user_id)
    elif view == 'history':
        q = q.filter(or_(ApprovalInstance.applicant_id == ctx.user_id, ApprovalInstance.approver_id == ctx.user_id))
    if business_type:
        q = q.filter(ApprovalInstance.business_type == business_type)
    if status:
        q = q.filter(ApprovalInstance.status == status)

    rows = q.order_by(desc(ApprovalInstance.created_at)).limit(limit).all()

    cols = [
        {'key': 'title', 'label': '审批标题'},
        {'key': 'businessType', 'label': '业务类型'},
        {'key': 'status', 'label': '状态'},
        {'key': 'createdAt', 'label': '提交时间'},
    ]
    table_rows = []
    for a in rows:
        table_rows.append({
            'id': a.id,
            'title': a.title or '—',
            'businessType': a.business_type or '—',
            'status': a.status or '—',
            'createdAt': a.created_at.strftime('%Y-%m-%d %H:%M') if a.created_at else '—',
        })
    approval_entities = [
        _generic_card(
            'approval',
            a.id,
            a.title or '审批记录',
            a.business_type or '',
            f'状态：{a.status or "—"}',
            '/approval-center',
        )
        for a in rows
    ]

    widgets_out = []
    if table_rows:
        widgets_out.append(W.data_table(cols, table_rows, title={
            'mine': '我的申请', 'pending': '待我审批', 'history': '审批历史',
        }.get(view, '审批查询')))
    widgets_out.append(W.warning(
        '审批通过/驳回可在 AI 助手中发起，但必须先展示影响范围并等待二次确认；不会自动审批。',
        level='info',
    ))
    view_label = {'mine': '我的申请', 'pending': '待我审批', 'history': '审批历史'}.get(view, '审批')
    status_counter: Dict[str, int] = {}
    type_counter: Dict[str, int] = {}
    for row in rows:
        status_key = row.status or 'unknown'
        type_key = row.business_type or 'unknown'
        status_counter[status_key] = status_counter.get(status_key, 0) + 1
        type_counter[type_key] = type_counter.get(type_key, 0) + 1
    first_approval = rows[0] if rows else None
    field_citations = {
        'approvals': _field_citation_group(
            ('approval.view', '审批视图', view_label),
            ('approval.record_count', '审批记录数', len(rows)),
            ('approval.status_counts', '状态分布', [f'{k}:{v}' for k, v in status_counter.items()]),
            ('approval.business_type_counts', '业务类型分布', [f'{k}:{v}' for k, v in type_counter.items()]),
            ('approval.sample_title', '样本审批标题', first_approval.title if first_approval else None),
            ('approval.sample_status', '样本审批状态', first_approval.status if first_approval else None),
        ),
    }
    metrics = {
        'view': view,
        'recordCount': len(rows),
        'statusCounts': status_counter,
        'businessTypeCounts': type_counter,
        'fieldEvidenceCount': sum(len(v) for v in field_citations.values()),
    }
    widgets_out.append({
        'type': 'source_citations',
        'title': '审批查询证据',
        'sources': [
            {
                'module': 'approvals',
                'recordType': 'approval_instances',
                'recordId': first_approval.id if first_approval else None,
                'title': f'{view_label}审批记录 {len(rows)} 条',
                'url': '/approval-center',
                'fields': field_citations.get('approvals') or [],
            },
        ],
    })

    return {
        'entities': approval_entities, 'workset_entities': approval_entities,
        'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': len(rows),
        'summary_hint': (
            f'{view_label}共有 {len(rows)} 条记录，AI 助手仅展示与汇总，不会自动审批。'
            if rows else f'{view_label}暂无相关审批。'
        ),
    }


def skill_approval_decision(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Approve or reject one pending approval after explicit chat confirmation."""
    from services.approval_workflow import complete_approval

    approval_id = str(args.get('approval_id') or args.get('approvalId') or '').strip()
    action = str(args.get('action') or '').strip().lower()
    if action in {'approved', 'pass', 'agree', '同意', '通过', '批准'}:
        action = 'approve'
    elif action in {'rejected', 'deny', '驳回', '拒绝'}:
        action = 'reject'
    if not approval_id or action not in {'approve', 'reject'}:
        raise ValueError('approval_decision requires approval_id and action=approve/reject')
    comment = str(args.get('comment') or '').strip() or ('AI 助手确认后审批通过' if action == 'approve' else 'AI 助手确认后审批驳回')
    completed = complete_approval(
        approval_id,
        action,
        approver_id=getattr(ctx, 'user_id', None),
        comment=comment,
        operation_source='assistant_confirmed_action',
    )
    db.session.commit()
    approval = completed['approval']
    record = completed['record']
    action_label = '通过' if action == 'approve' else '驳回'
    return {
        'entities': [_generic_card(
            'approval',
            approval.id,
            approval.title,
            approval.business_type or '',
            f'状态：{approval.status or "—"}',
            '/approval-center/records',
        )],
        'facts': {
            'approval_id': approval.id,
            'record_id': record.id,
            'action': action,
            'status': approval.status,
            'business_type': approval.business_type,
            'business_id': approval.business_id,
        },
        'rows_count': 1,
        'summary_hint': f'已{action_label}审批：{approval.title}。',
    }


# ============================================================
# 8. attendance_analysis
# ============================================================
def skill_attendance_analysis(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    month = args.get('month')
    employee_id = args.get('employee_id')
    department_id = args.get('department_id')
    anomaly_only = bool(args.get('anomaly_only'))
    explain_stats = bool(args.get('explain_stats'))
    rank_status = str(args.get('rank_status') or args.get('rankStatus') or '').strip()
    rank_statuses = {
        'late': {'late'},
        'early': {'early', 'early_leave'},
        'absent': {'absent'},
        'missing_card': {'missing_card', 'makeup_card'},
        'anomaly': set(),
    }
    if rank_status in rank_statuses:
        anomaly_only = anomaly_only or rank_status != 'late'
    role = ctx.role
    start = None
    end = None

    q = AttendanceRecord.query
    if month and len(month) >= 7:
        try:
            year, m = int(month[:4]), int(month[5:7])
            start = datetime(year, m, 1)
            end = datetime(year + (m // 12), (m % 12) + 1, 1)
            q = q.filter(AttendanceRecord.attendance_date >= start.date(), AttendanceRecord.attendance_date < end.date())
        except Exception:
            pass

    # 范围限制
    if role == ROLE_EMPLOYEE and ctx.user_employee_id:
        q = q.filter(AttendanceRecord.employee_id == ctx.user_employee_id)
    elif role == ROLE_MANAGER and ctx.user_department_id:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=ctx.user_department_id).all()]
        if emp_ids:
            q = q.filter(AttendanceRecord.employee_id.in_(emp_ids))

    if employee_id:
        q = q.filter(AttendanceRecord.employee_id == employee_id)
    if department_id and role in PRIVILEGED_ROLES:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=department_id).all()]
        if emp_ids:
            q = q.filter(AttendanceRecord.employee_id.in_(emp_ids))
    if anomaly_only:
        q = q.filter(AttendanceRecord.status != 'normal')

    rows = q.order_by(desc(AttendanceRecord.attendance_date)).limit(200).all()
    request_q = EmployeeRequest.query.filter(EmployeeRequest.status == 'approved')
    if start and end:
        request_q = request_q.filter(EmployeeRequest.start_time >= start, EmployeeRequest.start_time < end)
    if employee_id:
        request_q = request_q.filter(EmployeeRequest.employee_id == employee_id)
    if department_id and role in PRIVILEGED_ROLES:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=department_id).all()]
        if emp_ids:
            request_q = request_q.filter(EmployeeRequest.employee_id.in_(emp_ids))
    approved_requests = request_q.limit(200).all()

    # 每员工异常次数/指定状态次数
    anomaly_counter: Dict[str, int] = {}
    rank_counter: Dict[str, int] = {}
    status_counter: Dict[str, int] = {}
    for r in rows:
        st = r.status or 'normal'
        status_counter[st] = status_counter.get(st, 0) + 1
        if st != 'normal':
            anomaly_counter[r.employee_id] = anomaly_counter.get(r.employee_id, 0) + 1
        if rank_status:
            matched_statuses = rank_statuses.get(rank_status) or set()
            if (rank_status == 'anomaly' and st != 'normal') or st in matched_statuses:
                rank_counter[r.employee_id] = rank_counter.get(r.employee_id, 0) + 1

    top_anomaly = sorted(anomaly_counter.items(), key=lambda x: -x[1])[:10]
    rank_limit = _clamp_limit(args.get('limit'), default=10, hard_max=20)
    top_ranked = sorted(rank_counter.items(), key=lambda x: -x[1])[:rank_limit] if rank_status else []
    cols = [
        {'key': 'employeeName', 'label': '员工'},
        {'key': 'department', 'label': '部门'},
        {'key': 'anomalyCount', 'label': '异常次数', 'align': 'right'},
    ]
    table_rows = []
    for emp_id, cnt in top_anomaly:
        emp = Employee.query.get(emp_id)
        if not emp:
            continue
        table_rows.append({
            'id': emp_id,
            'employeeName': emp.name,
            'department': emp.department.name if emp.department else '—',
            'anomalyCount': cnt,
        })

    rank_table_rows = []
    rank_entities = []
    for emp_id, cnt in top_ranked:
        emp = Employee.query.get(emp_id)
        if not emp:
            continue
        late_records = [
            r for r in rows
            if r.employee_id == emp_id and (
                (rank_status == 'anomaly' and (r.status or 'normal') != 'normal')
                or (r.status or '') in (rank_statuses.get(rank_status) or set())
            )
        ]
        latest = max((r.attendance_date for r in late_records if r.attendance_date), default=None)
        rank_table_rows.append({
            'id': emp_id,
            'employeeId': emp_id,
            'employeeName': emp.name,
            'department': emp.department.name if emp.department else '—',
            'jobTitle': emp.job_title or (emp.position.title if emp.position else '—'),
            'count': cnt,
            'latestDate': latest.isoformat() if latest else '',
        })
        rank_entities.append(_employee_card(emp, ctx.role, ctx))

    anomaly_records = sum(v for k, v in status_counter.items() if k != 'normal')
    normal_records = status_counter.get('normal', 0)
    metrics = {
        'month': month,
        'totalRecords': len(rows),
        'anomalyRecords': anomaly_records,
        'normalRecords': normal_records,
        'approvedRequests': len(approved_requests),
        'statusCounts': dict(status_counter),
        'topAnomalyEmployees': [
            {'employeeId': emp_id, 'anomalyCount': cnt}
            for emp_id, cnt in top_anomaly
        ],
        'rankStatus': rank_status or None,
        'topRankedEmployees': rank_table_rows,
    }

    cards = [
        {'label': '总记录', 'value': metrics['totalRecords'], 'color': 'blue'},
        {'label': '异常记录', 'value': metrics['anomalyRecords'], 'color': 'red'},
        {'label': '正常出勤', 'value': metrics['normalRecords'], 'color': 'green'},
    ]

    status_label_map = {'normal': '正常', 'late': '迟到', 'early': '早退', 'absent': '缺勤',
                       'leave': '请假', 'overtime': '加班', 'business_trip': '出差',
                       'makeup': '补卡', 'missing_card': '缺卡'}
    dist = [{'label': status_label_map.get(k, k), 'value': v} for k, v in status_counter.items()]

    widgets_out = [W.metric_cards(cards, title='考勤汇总')]
    if dist:
        widgets_out.append(W.doughnut_chart(dist, title='考勤状态分布'))
    if table_rows:
        widgets_out.append(W.data_table(cols, table_rows, title='异常次数 TOP 10'))
    if rank_table_rows:
        rank_label = status_label_map.get(rank_status, '异常')
        widgets_out.append(W.data_table([
            {'key': 'employeeName', 'label': '员工'},
            {'key': 'department', 'label': '部门'},
            {'key': 'jobTitle', 'label': '岗位'},
            {'key': 'count', 'label': f'{rank_label}次数', 'align': 'right'},
            {'key': 'latestDate', 'label': '最近日期'},
        ], rank_table_rows, title=f'{rank_label}次数 TOP {len(rank_table_rows)}'))
    if explain_stats:
        widgets_out.append(W.status_badges([
            {'label': '打卡记录', 'value': len(rows), 'status': 'neutral', 'icon': 'fa-clock', 'hint': '来源于考勤记录模块'},
            {'label': '已批申请', 'value': len(approved_requests), 'status': 'info', 'icon': 'fa-calendar-check', 'hint': '来源于请假/加班/出差/补卡审批'},
            {'label': '统计口径', 'value': '打卡+已批申请', 'status': 'success', 'icon': 'fa-code-merge', 'hint': '考勤统计会合并两类来源'},
        ], title='统计口径说明'))
    first_attendance = rows[0] if rows else None
    first_request = approved_requests[0] if approved_requests else None
    first_employee = first_attendance.employee if first_attendance and first_attendance.employee else None
    field_citations = {
        'attendance_records': _field_citation_group(
            ('attendance.month', '查询月份', month or '当前筛选范围'),
            ('attendance.total_records', '打卡记录数', len(rows)),
            ('attendance.anomaly_records', '异常记录数', anomaly_records),
            ('attendance.normal_records', '正常记录数', normal_records),
            ('attendance.status_counts', '状态分布', [f'{status_label_map.get(k, k)}:{v}' for k, v in status_counter.items()]),
            ('attendance.sample_status', '样本状态', first_attendance.status if first_attendance else None),
            ('attendance.sample_date', '样本日期', first_attendance.attendance_date if first_attendance else None),
        ),
        'leave_requests': _field_citation_group(
            ('leave.approved_requests', '已批申请数', len(approved_requests)),
            ('leave.sample_type', '样本申请类型', first_request.request_type if first_request else None),
            ('leave.sample_status', '样本申请状态', first_request.status if first_request else None),
        ),
        'employees': _field_citation_group(
            ('employee.sample_name', '样本员工', first_employee.name if first_employee else None),
            ('employee.sample_department', '样本部门', first_employee.department.name if first_employee and first_employee.department else None),
        ),
    }
    field_citations = {k: v for k, v in field_citations.items() if v}
    metrics['fieldEvidenceCount'] = sum(len(v) for v in field_citations.values())
    widgets_out.append({
        'type': 'source_citations',
        'title': '考勤分析证据',
        'sources': [
            {
                'module': 'attendance_records',
                'recordType': 'attendance_records',
                'recordId': first_attendance.id if first_attendance else None,
                'title': f'考勤记录 {len(rows)} 条',
                'url': '/hrm/attendance-records',
                'fields': field_citations.get('attendance_records') or [],
            },
            {
                'module': 'leave_requests',
                'recordType': 'employee_requests',
                'recordId': first_request.id if first_request else None,
                'title': f'已批申请 {len(approved_requests)} 条',
                'url': '/employee-requests',
                'fields': field_citations.get('leave_requests') or [],
            },
            {
                'module': 'employees',
                'recordType': 'employees',
                'recordId': first_employee.id if first_employee else None,
                'title': '关联员工样本' if first_employee else '关联员工',
                'url': '/hrm/employees',
                'fields': field_citations.get('employees') or [],
            },
        ],
    })

    month_label = f'{month} ' if month else ''
    abnormal_parts = [
        f'{status_label_map.get(k, k)} {v} 次'
        for k, v in status_counter.items()
        if k != 'normal'
    ]
    abnormal_text = '，其中' + '、'.join(abnormal_parts) if abnormal_parts else ''
    if explain_stats:
        summary_hint = (
            f'{month_label}考勤统计口径为“打卡记录 + 已审批请假/加班/出差/补卡申请”。'
            f'当前读取到打卡记录 {metrics["totalRecords"]} 条，已批申请 {metrics["approvedRequests"]} 条；'
            f'打卡异常 {metrics["anomalyRecords"]} 次，正常 {metrics["normalRecords"]} 次'
            f'{abnormal_text}。如果统计页看不到记录，优先检查月份筛选、员工/部门筛选、审批状态是否为 approved，'
            '以及记录日期是否落在当前月份。'
        )
    else:
        summary_hint = (
            f'{month_label}共有 {metrics["totalRecords"]} 条考勤记录，'
            f'异常 {metrics["anomalyRecords"]} 次，正常 {metrics["normalRecords"]} 次'
            f'{abnormal_text}。'
        )

    return {
        'entities': rank_entities, 'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': len(rows), 'summary_hint': summary_hint,
    }


# ============================================================
# 9. performance_analysis
# ============================================================
def skill_performance_analysis(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    cycle_id = args.get('cycle_id')
    department_id = args.get('department_id')
    employee_id = args.get('employee_id')
    view = (args.get('view') or 'summary').lower()
    role = ctx.role

    q = PerformanceReview.query
    if cycle_id:
        q = q.filter(PerformanceReview.cycle_id == cycle_id)
    if employee_id:
        q = q.filter(PerformanceReview.employee_id == employee_id)

    # 范围限制
    if role == ROLE_EMPLOYEE and ctx.user_employee_id:
        q = q.filter(PerformanceReview.employee_id == ctx.user_employee_id)
    elif role == ROLE_MANAGER and ctx.user_department_id:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=ctx.user_department_id).all()]
        if emp_ids:
            q = q.filter(PerformanceReview.employee_id.in_(emp_ids))

    if department_id and role in PRIVILEGED_ROLES:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=department_id).all()]
        if emp_ids:
            q = q.filter(PerformanceReview.employee_id.in_(emp_ids))

    rows = q.order_by(desc(PerformanceReview.created_at)).limit(200).all()

    # 等级分布
    level_counter: Dict[str, int] = {}
    for r in rows:
        lvl = (
            getattr(r, 'grade', None)
            or getattr(r, 'level', None)
            or getattr(r, 'final_level', None)
            or '未评定'
        ) or '未评定'
        level_counter[lvl] = level_counter.get(lvl, 0) + 1

    score_band = [('S(>=90)', 90, 1000), ('A(80-89)', 80, 90), ('B(70-79)', 70, 80),
                  ('C(60-69)', 60, 70), ('D(<60)', 0, 60)]
    score_dist = []
    for lbl, lo, hi in score_band:
        cnt = sum(1 for r in rows if (getattr(r, 'final_score', None) or getattr(r, 'score', None) or 0) and
                  lo <= (getattr(r, 'final_score', None) or getattr(r, 'score', 0)) < hi)
        score_dist.append({'label': lbl, 'value': cnt})

    completed_count = sum(1 for r in rows if (r.status or '') in ('completed', 'finalized', 'closed'))
    first_review = rows[0] if rows else None
    first_employee = first_review.employee if first_review and first_review.employee else None
    first_cycle = first_review.cycle if first_review and first_review.cycle else None
    field_citations = {
        'performance_reviews': _field_citation_group(
            ('performance.review_count', '评估总数', len(rows)),
            ('performance.completed_count', '已完成数', completed_count),
            ('performance.level_counts', '等级分布', [f'{k}:{v}' for k, v in level_counter.items()]),
            ('performance.sample_grade', '样本等级', first_review.grade if first_review else None),
            ('performance.sample_score', '样本得分', first_review.final_score if first_review else None),
            ('performance.sample_status', '样本状态', first_review.status if first_review else None),
        ),
        'employees': _field_citation_group(
            ('employee.sample_name', '样本员工', first_employee.name if first_employee else None),
            ('employee.sample_department', '样本部门', first_employee.department.name if first_employee and first_employee.department else None),
            ('employee.sample_job_title', '样本岗位', first_employee.job_title if first_employee else None),
        ),
        'performance_cycles': _field_citation_group(
            ('performance_cycle.name', '样本周期', first_cycle.name if first_cycle else None),
            ('performance_cycle.type', '周期类型', first_cycle.cycle_type if first_cycle else None),
        ),
    }
    field_citations = {k: v for k, v in field_citations.items() if v}
    metrics = {
        'reviewCount': len(rows),
        'completedCount': completed_count,
        'levelCounts': dict(level_counter),
        'scoreBands': {item['label']: item['value'] for item in score_dist},
        'fieldEvidenceCount': sum(len(v) for v in field_citations.values()),
    }

    widgets_out = []
    cards = [
        {'label': '评估总数', 'value': len(rows), 'color': 'blue'},
        {'label': '已完成', 'value': completed_count, 'color': 'green'},
    ]
    widgets_out.append(W.metric_cards(cards, title='绩效概览'))
    if any(d['value'] for d in score_dist):
        widgets_out.append(W.bar_chart(score_dist, title='评分分布'))
    if level_counter:
        widgets_out.append(W.doughnut_chart(
            [{'label': k, 'value': v} for k, v in level_counter.items()],
            title='等级分布', center_label='评估数',
        ))
    widgets_out.append({
        'type': 'source_citations',
        'title': '绩效分析证据',
        'sources': [
            {
                'module': 'performance_reviews',
                'recordType': 'performance_reviews',
                'recordId': first_review.id if first_review else None,
                'title': f'绩效评估 {len(rows)} 条',
                'url': '/performance-review',
                'fields': field_citations.get('performance_reviews') or [],
            },
            {
                'module': 'employees',
                'recordType': 'employees',
                'recordId': first_employee.id if first_employee else None,
                'title': '关联员工样本' if first_employee else '关联员工',
                'url': '/hrm/employees',
                'fields': field_citations.get('employees') or [],
            },
            {
                'module': 'performance_cycles',
                'recordType': 'performance_cycles',
                'recordId': first_cycle.id if first_cycle else None,
                'title': '绩效周期' if first_cycle else '绩效周期（未指定）',
                'url': '/performance-cycle',
                'fields': field_citations.get('performance_cycles') or [],
            },
        ],
    })

    level_text = '、'.join(f'{level} {count} 人' for level, count in level_counter.items()) or '暂无等级分布'
    summary_hint = (
        f'共 {metrics["reviewCount"]} 条绩效评估，'
        f'已完成 {metrics["completedCount"]} 条，等级分布：{level_text}。'
    )

    return {
        'entities': [], 'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': len(rows),
        'summary_hint': summary_hint,
    }


# ============================================================
# 10. payroll_analysis（高敏感）
# ============================================================
def skill_payroll_analysis(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    role = ctx.role
    if role not in PAYROLL_AUTHORIZED_ROLES:
        return {
            'entities': [], 'widgets': [W.warning(
                '薪酬数据属于敏感信息，您当前角色无权查看明细。',
                level='warning',
            )],
            'rows_count': 0, 'summary_hint': '权限不足，已拒绝薪酬查询。',
            'permission_denied': True,
        }

    month = args.get('month')
    employee_id = args.get('employee_id')
    view = (args.get('view') or 'summary').lower()

    q = PayrollRecord.query
    if month and len(month) >= 7:
        q = q.filter(PayrollRecord.payroll_month == month[:7])
    if employee_id:
        q = q.filter(PayrollRecord.employee_id == employee_id)
    department_id = args.get('department_id')
    if department_id and role in PRIVILEGED_ROLES:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=department_id).all()]
        if emp_ids:
            q = q.filter(PayrollRecord.employee_id.in_(emp_ids))

    rows = q.order_by(desc(PayrollRecord.created_at)).limit(200).all()

    if not rows:
        return {
            'entities': [], 'widgets': [W.empty_state('未找到对应月份的工资条记录。')],
            'rows_count': 0, 'summary_hint': '无工资条记录。',
        }

    total_gross = sum(float(getattr(r, 'gross_salary', 0) or 0) for r in rows)
    total_net = sum(float(getattr(r, 'net_salary', 0) or 0) for r in rows)
    total_deduction = sum(float(getattr(r, 'deduction', 0) or 0) for r in rows)
    first_payroll = rows[0] if rows else None
    first_employee = first_payroll.employee if first_payroll and first_payroll.employee else None
    field_citations = {
        'payroll_records': _field_citation_group(
            ('payroll.month', '查询月份', month or '全部月份'),
            ('payroll.record_count', '工资条数', len(rows)),
            ('payroll.total_gross', '应发合计', _fmt_amount(total_gross)),
            ('payroll.total_net', '实发合计', _fmt_amount(total_net)),
            ('payroll.total_deduction', '扣减合计', _fmt_amount(total_deduction)),
            ('payroll.sample_status', '样本工资条状态', first_payroll.status if first_payroll else None),
        ),
        'employees': _field_citation_group(
            ('employee.sample_name', '样本员工', first_employee.name if first_employee else None),
            ('employee.sample_department', '样本部门', first_employee.department.name if first_employee and first_employee.department else None),
        ),
    }
    field_citations = {k: v for k, v in field_citations.items() if v}
    metrics = {
        'month': month,
        'recordCount': len(rows),
        'totalGross': total_gross,
        'totalNet': total_net,
        'totalDeduction': total_deduction,
        'fieldEvidenceCount': sum(len(v) for v in field_citations.values()),
    }

    cards = [
        {'label': '工资条数', 'value': len(rows), 'color': 'blue'},
        {'label': '应发合计', 'value': f'{total_gross:,.0f}', 'unit': '元', 'color': 'indigo'},
        {'label': '实发合计', 'value': f'{total_net:,.0f}', 'unit': '元', 'color': 'green'},
    ]
    widgets_out = [W.metric_cards(cards, title=f'薪酬汇总（{month or "全部月份"}）')]

    if view == 'personal' and employee_id:
        cols = [
            {'key': 'month', 'label': '月份'},
            {'key': 'gross', 'label': '应发', 'align': 'right'},
            {'key': 'net', 'label': '实发', 'align': 'right'},
            {'key': 'deduction', 'label': '扣减', 'align': 'right'},
        ]
        table_rows = [{
            'month': r.payroll_month,
            'gross': f'{float(getattr(r, "gross_salary", 0) or 0):,.2f}',
            'net': f'{float(getattr(r, "net_salary", 0) or 0):,.2f}',
            'deduction': f'{float(getattr(r, "deduction", 0) or 0):,.2f}',
        } for r in rows]
        widgets_out.append(W.data_table(cols, table_rows, title='工资条明细'))

    widgets_out.append(W.warning('薪酬数据为机密信息，请勿外发。', level='warning'))
    widgets_out.append({
        'type': 'source_citations',
        'title': '薪酬汇总证据',
        'sources': [
            {
                'module': 'payroll_records',
                'recordType': 'payroll_records',
                'recordId': first_payroll.id if first_payroll else None,
                'title': f'工资条记录 {len(rows)} 条',
                'url': '/hrm/payroll-records',
                'fields': field_citations.get('payroll_records') or [],
            },
            {
                'module': 'employees',
                'recordType': 'employees',
                'recordId': first_employee.id if first_employee else None,
                'title': '关联员工样本' if first_employee else '关联员工',
                'url': '/hrm/employees',
                'fields': field_citations.get('employees') or [],
            },
        ],
    })

    return {
        'entities': [], 'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': len(rows),
        'summary_hint': (
            f'{month or "当前筛选范围"}薪酬汇总：{len(rows)} 条工资条，'
            f'应发合计 {_fmt_amount(total_gross)} 元，实发合计 {_fmt_amount(total_net)} 元。'
            '薪酬数据为敏感信息，请仅在授权范围内使用。'
        ),
    }


# ============================================================
# 11. training_analysis
# ============================================================
def skill_training_analysis(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    department_id = args.get('department_id')
    employee_id = args.get('employee_id')
    status = args.get('status')

    course_count = TrainingCourse.query.count()
    plan_count = TrainingPlan.query.count()

    q = TrainingRecord.query
    if employee_id:
        q = q.filter(TrainingRecord.employee_id == employee_id)
    if status:
        q = q.filter(TrainingRecord.status == status)
    if department_id:
        emp_ids = [r[0] for r in Employee.query.with_entities(Employee.id).filter_by(
            department_id=department_id).all()]
        if emp_ids:
            q = q.filter(TrainingRecord.employee_id.in_(emp_ids))

    records = q.limit(500).all()
    total = len(records)
    completed = sum(1 for r in records if (r.status or '') in ('completed', 'passed'))
    rate = round(completed / total * 100, 1) if total else 0

    status_counter: Dict[str, int] = {}
    for r in records:
        st = r.status or '未开始'
        status_counter[st] = status_counter.get(st, 0) + 1
    first_record = records[0] if records else None
    first_employee = first_record.employee if first_record and first_record.employee else None
    first_course = first_record.course if first_record and first_record.course else None
    field_citations = {
        'training_courses': _field_citation_group(
            ('training.course_count', '培训课程数', course_count),
            ('training.sample_course', '样本课程', first_course.name if first_course else None),
            ('training.sample_course_status', '样本课程状态', first_course.status if first_course else None),
        ),
        'training_plans': _field_citation_group(
            ('training.plan_count', '培训计划数', plan_count),
        ),
        'training_records': _field_citation_group(
            ('training.record_count', '培训记录数', total),
            ('training.completed_count', '已完成数', completed),
            ('training.completion_rate', '完成率', f'{rate}%'),
            ('training.status_counts', '状态分布', [f'{k}:{v}' for k, v in status_counter.items()]),
            ('training.sample_status', '样本记录状态', first_record.status if first_record else None),
            ('training.sample_result', '样本结果', first_record.result if first_record else None),
        ),
        'employees': _field_citation_group(
            ('employee.sample_name', '样本员工', first_employee.name if first_employee else None),
            ('employee.sample_department', '样本部门', first_employee.department.name if first_employee and first_employee.department else None),
        ),
    }
    field_citations = {k: v for k, v in field_citations.items() if v}

    cards = [
        {'label': '培训课程', 'value': course_count, 'color': 'indigo'},
        {'label': '培训计划', 'value': plan_count, 'color': 'blue'},
        {'label': '记录总数', 'value': total, 'color': 'gray'},
        {'label': '完成率', 'value': rate, 'unit': '%', 'color': 'green'},
    ]
    widgets_out = [W.metric_cards(cards, title='培训分析')]
    if status_counter:
        widgets_out.append(W.doughnut_chart(
            [{'label': k, 'value': v} for k, v in status_counter.items()],
            title='培训状态分布',
        ))
    widgets_out.append({
        'type': 'source_citations',
        'title': '培训分析证据',
        'sources': [
            {
                'module': 'training_courses',
                'recordType': 'training_courses',
                'recordId': first_course.id if first_course else None,
                'title': f'培训课程 {course_count} 门',
                'url': '/hrm/training-courses',
                'fields': field_citations.get('training_courses') or [],
            },
            {
                'module': 'training_plans',
                'recordType': 'training_plans',
                'title': f'培训计划 {plan_count} 个',
                'url': '/hrm/training-plans',
                'fields': field_citations.get('training_plans') or [],
            },
            {
                'module': 'training_records',
                'recordType': 'training_records',
                'recordId': first_record.id if first_record else None,
                'title': f'培训记录 {total} 条',
                'url': '/hrm/training-records',
                'fields': field_citations.get('training_records') or [],
            },
            {
                'module': 'employees',
                'recordType': 'employees',
                'recordId': first_employee.id if first_employee else None,
                'title': '参训员工样本' if first_employee else '参训员工',
                'url': '/hrm/employees',
                'fields': field_citations.get('employees') or [],
            },
        ],
    })
    metrics = {
        'courseCount': course_count,
        'planCount': plan_count,
        'recordCount': total,
        'completedCount': completed,
        'completionRate': rate,
        'statusCounts': dict(status_counter),
        'fieldEvidenceCount': sum(len(v) for v in field_citations.values()),
    }

    return {
        'entities': [], 'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': total,
        'summary_hint': (
            f'当前共有 {course_count} 门课程、{plan_count} 个培训计划，'
            f'培训记录 {total} 条，已完成 {completed} 条，完成率 {rate}%。'
        ),
    }


# ============================================================
# 12. feedback_triage
# ============================================================
def skill_feedback_triage(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    feedback_type = args.get('feedback_type')
    status = args.get('status')
    limit = _clamp_limit(args.get('limit'))

    q = Feedback.query
    if feedback_type:
        q = q.filter(Feedback.feedback_type == feedback_type)
    if status:
        q = q.filter(Feedback.status == status)
    rows = q.order_by(desc(Feedback.created_at)).limit(limit).all()

    type_counter: Dict[str, int] = {}
    status_counter: Dict[str, int] = {}
    for r in Feedback.query.all():
        type_counter[r.feedback_type or 'other'] = type_counter.get(r.feedback_type or 'other', 0) + 1
        status_counter[r.status or 'pending'] = status_counter.get(r.status or 'pending', 0) + 1

    type_label = {'bug': '缺陷', 'feature': '需求', 'other': '其他'}
    status_label = {'pending': '待处理', 'in_progress': '处理中', 'resolved': '已解决', 'closed': '已关闭'}

    cards = [
        {'label': '反馈总数', 'value': sum(type_counter.values()), 'color': 'blue'},
        {'label': '待处理', 'value': status_counter.get('pending', 0), 'color': 'amber'},
        {'label': '处理中', 'value': status_counter.get('in_progress', 0), 'color': 'indigo'},
        {'label': '已解决', 'value': status_counter.get('resolved', 0), 'color': 'green'},
    ]
    type_dist = [{'label': type_label.get(k, k), 'value': v} for k, v in type_counter.items()]
    status_dist = [{'label': status_label.get(k, k), 'value': v} for k, v in status_counter.items()]
    first_feedback = rows[0] if rows else None
    field_citations = {
        'feedback': _field_citation_group(
            ('feedback.total_count', '反馈总数', sum(type_counter.values())),
            ('feedback.pending_count', '待处理数', status_counter.get('pending', 0)),
            ('feedback.status_counts', '状态分布', [f'{k}:{v}' for k, v in status_counter.items()]),
            ('feedback.type_counts', '类型分布', [f'{k}:{v}' for k, v in type_counter.items()]),
            ('feedback.sample_title', '样本标题', first_feedback.title if first_feedback else None),
            ('feedback.sample_status', '样本状态', first_feedback.status if first_feedback else None),
            ('feedback.sample_type', '样本类型', first_feedback.feedback_type if first_feedback else None),
        ),
    }

    entities = [_feedback_card(f) for f in rows]
    widgets_out = [W.metric_cards(cards, title='问题反馈')]
    if type_dist:
        widgets_out.append(W.doughnut_chart(type_dist, title='反馈类型分布'))
    if status_dist:
        widgets_out.append(W.doughnut_chart(status_dist, title='反馈状态分布'))
    widgets_out.append({
        'type': 'source_citations',
        'title': '反馈分析证据',
        'sources': [
            {
                'module': 'feedback',
                'recordType': 'feedback',
                'recordId': first_feedback.id if first_feedback else None,
                'title': f'反馈记录 {len(rows)} 条 / 总数 {sum(type_counter.values())} 条',
                'url': '/feedback',
                'fields': field_citations.get('feedback') or [],
            },
        ],
    })
    metrics = {
        'recordCount': len(rows),
        'totalCount': sum(type_counter.values()),
        'pendingCount': status_counter.get('pending', 0),
        'statusCounts': dict(status_counter),
        'typeCounts': dict(type_counter),
        'fieldEvidenceCount': sum(len(v) for v in field_citations.values()),
    }

    return {
        'entities': entities, 'widgets': widgets_out,
        'metrics': metrics,
        'facts': {'field_citations': field_citations},
        'rows_count': len(rows),
        'summary_hint': (
            f'当前共有 {metrics["totalCount"]} 条反馈，待处理 {metrics["pendingCount"]} 条，'
            f'处理中 {status_counter.get("in_progress", 0)} 条，已解决 {status_counter.get("resolved", 0)} 条。'
        ),
    }


# ============================================================
# 13. dashboard_report
# ============================================================
def skill_dashboard_report(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    scope = (args.get('scope') or 'system').lower()

    cards: List[Dict[str, Any]] = []
    extra_widgets: List[Dict[str, Any]] = []

    if scope in ('system', 'employee'):
        emp_total = Employee.query.count()
        emp_active = Employee.query.filter(Employee.status.in_(['probation', 'active'])).count()
        emp_pending = Employee.query.filter(Employee.status == 'pending_onboard').count()
        cards.extend([
            {'label': '员工总数', 'value': emp_total, 'color': 'blue', 'trendText': f'在职 {emp_active}'},
            {'label': '待入职', 'value': emp_pending, 'color': 'amber'},
        ])

    if scope in ('system', 'recruitment'):
        job_open = Job.query.filter(Job.status == 'open').count()
        cand = Candidate.query.count()
        recent_resume = Resume.query.filter(Resume.created_at >= datetime.utcnow() - timedelta(days=7)).count()
        upcoming_iv = Interview.query.filter(
        Interview.scheduled_at >= business_now(),
        Interview.scheduled_at <= business_now() + timedelta(days=7),
        ).count()
        cards.extend([
            {'label': '招聘中岗位', 'value': job_open, 'color': 'indigo'},
            {'label': '候选人', 'value': cand, 'color': 'green'},
            {'label': '近7天新简历', 'value': recent_resume, 'color': 'gray'},
            {'label': '近7天面试', 'value': upcoming_iv, 'color': 'blue'},
        ])

    if scope in ('system', 'attendance'):
        ex = AttendanceRecord.query.filter(AttendanceRecord.status != 'normal').count()
        cards.append({'label': '考勤异常', 'value': ex, 'color': 'red' if ex > 0 else 'gray'})

    if scope in ('system',):
        fb = Feedback.query.filter(Feedback.status == 'pending').count()
        cards.append({'label': '待处理反馈', 'value': fb, 'color': 'red' if fb > 0 else 'gray'})

    if not cards:
        cards.append({'label': '系统运行正常', 'value': '✓', 'color': 'green'})

    widgets_out = [W.metric_cards(cards, title=f'{scope} 概览')]
    widgets_out.extend(extra_widgets)

    return {
        'entities': [], 'widgets': widgets_out,
        'rows_count': len(cards),
        'summary_hint': f'已生成 {scope} 维度概览。',
    }


# ============================================================
# 14. draft_generator（生成草稿，不发送）
# ============================================================
DRAFT_TEMPLATES = {
    'interview_invite': '尊敬的{name}：\n\n您好！感谢您应聘我司{job}岗位。经过初步筛选，我们诚邀您参加面试。\n建议时间：{time}\n面试方式：{way}\n如有疑问请回复本消息。\n\n祝顺利',
    'interview_plan': '面试计划草稿\n\n本期推荐面试 {count} 位候选人，按 AI 评分降序：\n{candidates}\n\n请审核后到面试管理页面创建。',
    'offer_communication': '尊敬的{name}：\n\n经过综合评估，我们决定向您提供{job}岗位的录用机会。\n薪资：{salary}\n入职日期：{date}\n请于 3 个工作日内回复确认。',
    'onboarding_notice': '尊敬的{name}：\n\n欢迎加入{company}！您的入职日期为{date}，请按入职清单准备相关材料。',
    'training_notice': '各位同事：\n\n{course} 培训将于 {date} 在 {location} 举行，请按时参加。',
    'approval_comment': '已审核：{decision}。理由：{reason}',
    'resignation_summary': '离职汇总：{name}（{department}）于 {date} 离职。原因归类：{category}。建议加强 {improvement}。',
    'probation_notice': '尊敬的{name}：\n\n您的试用期即将于 {date} 结束，请准备转正申请。',
}


def skill_draft_generator(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    draft_type = (args.get('draft_type') or 'general').lower()
    facts = args.get('facts') or {}
    tone = args.get('tone') or '正式'
    audience = args.get('audience') or '员工'

    template = DRAFT_TEMPLATES.get(draft_type)
    base_text = ''
    if template:
        try:
            base_text = template.format_map(_DefaultDict(facts))
        except Exception:
            base_text = template

    # 调用 LLM 润色（如果有）
    from .llm_client import chat_profile, is_available, clean_text
    polished = base_text
    if is_available() and base_text:
        try:
            msg = chat_profile(
                'standard',
                messages=[
                    {'role': 'system',
                     'content': f'你是 HR 文案助手，请用{tone}的语气改写下面的草稿，受众是{audience}。'
                                f'输出纯中文，不带 Markdown 符号，不超过 300 字。'},
                    {'role': 'user', 'content': base_text or '请帮我生成一份HR文案草稿。'},
                ],
                temperature=0.5,
                max_tokens=400,
                use_case='draft_generation',
                resource_domain='assistant',
                ctx=ctx,
            )
            if msg:
                polished = clean_text(msg.get('content') or base_text)
        except Exception:
            polished = base_text

    if not polished:
        polished = '草稿生成失败，请补充关键字段后重试。'

    return {
        'entities': [],
        'widgets': [W.warning(f'以下为 AI 生成的{draft_type}草稿，请审核后再使用，不会自动发送。',
                              level='info')],
        'rows_count': 1,
        'summary_hint': polished,
        'draft_text': polished,
        'draft_type': draft_type,
    }


def _safe_resume_facts(r: Resume, role: str) -> Dict[str, Any]:
    data = desensitize_resume(r.to_dict(), role)
    analysis = data.get('aiAnalysis') if isinstance(data.get('aiAnalysis'), dict) else {}
    analysis_fields = {
        k: v for k, v in analysis.items()
        if k not in {'raw_text', 'rawText', 'phone', 'email', 'fileUrl', 'file_url'}
    }
    return {
        'resume_id': r.id,
        'candidate_name': data.get('candidateName'),
        'job_id': data.get('jobId'),
        'job_title': r.job.title if r.job else None,
        'tags': data.get('tags') or [],
        'score': analysis.get('score'),
        'match_degree': analysis.get('matchDegree'),
        'skills': analysis.get('skills') or [],
        'experience': analysis.get('experience'),
        'education': analysis.get('education'),
        'summary': analysis.get('summary'),
        'strengths': analysis.get('strengths') or [],
        'weaknesses': analysis.get('weaknesses') or [],
        'recommendation': analysis.get('recommendation'),
        'interview_focus': analysis.get('interviewFocus') or [],
        'interview_questions': analysis.get('interviewQuestions') or [],
        'analysis_fields': analysis_fields,
        # Do not expose phone/email/fileUrl to LLM context.
    }


def _compact_citation_value(value: Any) -> Optional[Any]:
    if value in (None, '', []):
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return _fmt_amount(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return '、'.join(parts[:3]) if parts else None
    if isinstance(value, dict):
        return None
    text = re.sub(r'\s+', ' ', str(value)).strip()
    if not text:
        return None
    return text[:120] + ('...' if len(text) > 120 else '')


def _field_citation(key: str, label: str, value: Any) -> Optional[Dict[str, Any]]:
    compact = _compact_citation_value(value)
    if compact in (None, ''):
        return None
    return {'key': key, 'label': label, 'value': compact}


def _field_citation_group(*items: tuple[str, str, Any]) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    for key, label, value in items:
        citation = _field_citation(key, label, value)
        if citation:
            citations.append(citation)
    return citations


def _resume_media_widget(resume: Optional[Resume], role: str) -> Optional[Dict[str, Any]]:
    if not resume or role not in PRIVILEGED_ROLES | {ROLE_RECRUITER}:
        return None
    file_url = str(resume.file_url or '').strip()
    if not file_url:
        return None
    name = resume.candidate_name or '候选人'
    ext = file_url.rsplit('.', 1)[-1].lower() if '.' in file_url else ''
    mime_map = {
        'pdf': 'application/pdf',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'webp': 'image/webp',
        'doc': 'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }
    return W.media_preview([{
        'title': f'{name} 简历附件',
        'url': file_url,
        'mimeType': mime_map.get(ext, ''),
        'description': resume.job.title if resume.job else '简历附件',
    }], title='简历附件预览')


def skill_resume_get_detail(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Load one resume/candidate detail for generation context, desensitized."""
    resume_id = args.get('resume_id') or args.get('resumeId')
    candidate_id = args.get('candidate_id') or args.get('candidateId')
    candidate = None
    if candidate_id:
        candidate = Candidate.query.get(candidate_id)
        if candidate and not resume_id:
            resume_id = candidate.resume_id
    resume = Resume.query.get(resume_id) if resume_id else None
    if not resume and candidate:
        # Candidate may not have a linked Resume. Return safe candidate facts.
        facts = {
            'candidate_id': candidate.id,
            'candidate_name': candidate.name,
            'job_title': candidate.job.title if candidate.job else None,
            'status': candidate.status,
            'source': candidate.source,
            'tags': candidate.tags or [],
            'ai_summary': candidate.ai_summary,
            'ai_recommendation': candidate.ai_recommendation,
        }
        return {
            'entities': [_candidate_card(candidate)],
            'facts': facts,
            'rows_count': 1,
            'summary_hint': f'已加载候选人 {candidate.name} 的脱敏上下文。',
        }
    if not resume:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': '未找到简历。'}
    facts = _safe_resume_facts(resume, ctx.role)
    entities = [_resume_card(resume, ctx.role)]
    if candidate:
        entities.insert(0, _candidate_card(candidate))
        facts['candidate_id'] = candidate.id
        facts['candidate_status'] = candidate.status
        facts['candidate_tags'] = candidate.tags or []
        facts['candidate_ai_summary'] = candidate.ai_summary
        facts['candidate_ai_recommendation'] = candidate.ai_recommendation
    widgets_out = []
    media_widget = _resume_media_widget(resume, ctx.role)
    if media_widget:
        widgets_out.append(media_widget)
    return {
        'entities': entities,
        'facts': facts,
        'widgets': widgets_out,
        'rows_count': 1,
        'summary_hint': f'已加载 {facts.get("candidate_name") or "候选人"} 的脱敏简历上下文。',
    }


def skill_employee_get_detail(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Load one employee detail with role-based desensitization."""
    employee_id = args.get('employee_id') or args.get('employeeId')
    if not employee_id:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': '缺少 employee_id。'}
    emp = Employee.query.get(employee_id)
    if not emp:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': '未找到员工。'}
    safe = desensitize_employee(emp.to_dict(), ctx.role, ctx.user_employee_id)
    facts = {
        'employee_id': safe.get('id'),
        'employee_no': safe.get('employeeNo'),
        'name': safe.get('name'),
        'department': safe.get('departmentName') or (emp.department.name if emp.department else None),
        'job_title': safe.get('jobTitle') or (emp.position.title if emp.position else None),
        'status': safe.get('status'),
        'hire_date': safe.get('hireDate'),
        'probation_end_date': safe.get('probationEndDate'),
        'remark': safe.get('remark') if ctx.role in PRIVILEGED_ROLES else None,
    }
    return {
        'entities': [_employee_card(emp, ctx.role, ctx)],
        'facts': facts,
        'rows_count': 1,
        'summary_hint': f'已加载员工 {emp.name} 的脱敏上下文。',
    }


def skill_job_get_detail(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Load job detail for generation context."""
    job_id = args.get('job_id') or args.get('jobId')
    if not job_id:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': '缺少 job_id。'}
    job = Job.query.get(job_id)
    if not job:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': '未找到岗位。'}
    facts = {
        'job_id': job.id,
        'title': job.title,
        'department': job.department or (job.department_ref.name if job.department_ref else None),
        'category': job.category,
        'level': job.level,
        'location': job.location,
        'employment_type': job.employment_type,
        'headcount': job.headcount,
        'responsibilities': job.responsibilities,
        'requirements': job.requirements,
        'salary_range': job.salary_range,
        'scoring_criteria': job.scoring_criteria or [],
    }
    return {
        'entities': [_job_card(job)],
        'facts': facts,
        'rows_count': 1,
        'summary_hint': f'已加载岗位 {job.title} 的上下文。',
    }


def _job_evidence(job: Optional[Job]) -> Dict[str, Any]:
    if not job:
        return {}
    return {
        'job_id': job.id,
        'title': job.title,
        'department': job.department or (job.department_ref.name if job.department_ref else None),
        'level': job.level,
        'responsibilities': job.responsibilities,
        'requirements': job.requirements,
        'scoring_criteria': job.scoring_criteria or [],
        'status': job.status,
    }


def skill_candidate_evidence_bundle(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Assemble one candidate's connected recruitment evidence for reasoning."""
    candidate_id = args.get('candidate_id') or args.get('candidateId')
    resume_id = args.get('resume_id') or args.get('resumeId')
    keyword = str(args.get('keyword') or '').strip()
    job_id = args.get('job_id') or args.get('jobId')
    job_keyword = str(args.get('job_keyword') or args.get('jobKeyword') or '').strip()
    explicit_candidate_keyword = _keyword_looks_like_person_name(keyword)
    candidate = Candidate.query.get(candidate_id) if candidate_id else None
    resume = Resume.query.get(resume_id) if resume_id else None
    if explicit_candidate_keyword and candidate and not _candidate_record_matches_keyword(candidate, keyword):
        candidate = None
        candidate_id = None
    if explicit_candidate_keyword and resume and not _resume_record_matches_keyword(resume, keyword):
        resume = None
        resume_id = None
    if not candidate and resume:
        candidate = Candidate.query.filter_by(resume_id=resume.id).order_by(desc(Candidate.created_at)).first()
        if explicit_candidate_keyword and candidate and not _candidate_record_matches_keyword(candidate, keyword):
            candidate = None
    if not candidate and keyword:
        candidate = (Candidate.query.filter(Candidate.name == keyword)
                     .order_by(desc(Candidate.created_at)).first())
        if not candidate:
            candidate = (Candidate.query.filter(Candidate.name.like(f'%{keyword}%'))
                         .order_by(desc(Candidate.created_at)).first())
    if candidate and not resume and candidate.resume_id:
        resume = Resume.query.get(candidate.resume_id)
        if explicit_candidate_keyword and resume and not _resume_record_matches_keyword(resume, keyword):
            resume = None
    if not resume and keyword:
        resume = (Resume.query.filter(Resume.candidate_name == keyword)
                  .order_by(desc(Resume.created_at)).first())
        if not resume:
            resume = (Resume.query.filter(Resume.candidate_name.like(f'%{keyword}%'))
                      .order_by(desc(Resume.created_at)).first())
    if not candidate and resume:
        candidate = Candidate.query.filter_by(resume_id=resume.id).order_by(desc(Candidate.created_at)).first()
        if explicit_candidate_keyword and candidate and not _candidate_record_matches_keyword(candidate, keyword):
            candidate = None
    if explicit_candidate_keyword and not candidate and not resume:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': f'未找到与“{keyword}”关联的候选人或简历。'}
    if not candidate and not resume:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': f'未找到与“{keyword}”关联的候选人或简历。'}

    job = (candidate.job if candidate and candidate.job else None) or (resume.job if resume else None)
    target_job = Job.query.get(job_id) if job_id else None
    if not target_job and job_keyword:
        target_job = Job.query.filter(Job.title == job_keyword).order_by(desc(Job.created_at)).first()
        if not target_job:
            target_job = Job.query.filter(Job.title.like(f'%{job_keyword}%')).order_by(desc(Job.created_at)).first()
    interview_query = Interview.query
    if resume:
        interview_query = interview_query.filter(Interview.resume_id == resume.id)
    elif job:
        interview_query = interview_query.filter(Interview.job_id == job.id)
    else:
        interview_query = interview_query.filter(Interview.id == '__none__')
    interviews = interview_query.order_by(desc(Interview.scheduled_at)).limit(20).all()
    offers = (
        Offer.query.filter(Offer.candidate_id == candidate.id)
        .order_by(desc(Offer.created_at)).limit(10).all()
        if candidate else []
    )
    employee = (
        Employee.query.filter(Employee.candidate_id == candidate.id)
        .order_by(desc(Employee.created_at)).first()
        if candidate else None
    )
    candidate_facts = {
        'candidate_id': candidate.id,
        'status': candidate.status,
        'source': candidate.source,
        'tags': candidate.tags or [],
        'ai_summary': candidate.ai_summary,
        'ai_recommendation': candidate.ai_recommendation,
        'match_records': candidate.match_records or [],
        'created_at': candidate.created_at.isoformat() if candidate.created_at else None,
    } if candidate else {}
    resume_facts = _safe_resume_facts(resume, ctx.role) if resume else {}
    job_facts = _job_evidence(job)
    target_job_facts = _job_evidence(target_job)
    interview_facts = [{
        'interview_id': row.id,
        'scheduled_at': row.scheduled_at.isoformat() if row.scheduled_at else None,
        'status': row.status,
        'notes': row.notes,
        'feedback': row.feedback_text,
        'ai_analysis': row.ai_analysis or {},
    } for row in interviews]
    offer_facts = [{
        'offer_id': row.id,
        'title': row.title,
        'status': row.status,
        'approval_status': row.approval_status,
        'onboarding_date': row.onboarding_date.isoformat() if row.onboarding_date else None,
        'work_location': row.work_location,
    } for row in offers]
    employee_facts = {
        'employee_id': employee.id,
        'status': employee.status,
        'department': employee.department.name if employee.department else None,
        'job_title': employee.job_title,
        'hire_date': employee.hire_date.isoformat() if employee.hire_date else None,
    } if employee else {}
    latest_interview = interview_facts[0] if interview_facts else {}
    latest_offer = offer_facts[0] if offer_facts else {}
    field_citations = {
        'candidate': _field_citation_group(
            ('candidate.status', '候选状态', candidate_facts.get('status')),
            ('candidate.source', '来源渠道', candidate_facts.get('source')),
            ('candidate.ai_summary', 'AI摘要', candidate_facts.get('ai_summary')),
            ('candidate.ai_recommendation', 'AI建议', candidate_facts.get('ai_recommendation')),
        ),
        'resume': _field_citation_group(
            ('resume.score', '简历评分', resume_facts.get('score')),
            ('resume.match_degree', '岗位匹配度', resume_facts.get('match_degree')),
            ('resume.summary', '简历概览', resume_facts.get('summary')),
            ('resume.strengths', '主要亮点', resume_facts.get('strengths')),
            ('resume.weaknesses', '待复核项', resume_facts.get('weaknesses')),
            ('resume.recommendation', '简历建议', resume_facts.get('recommendation')),
        ),
        'job': _field_citation_group(
            ('job.title', '岗位名称', job_facts.get('title')),
            ('job.department', '所属部门', job_facts.get('department')),
            ('job.requirements', '任职要求', job_facts.get('requirements')),
            ('job.responsibilities', '岗位职责', job_facts.get('responsibilities')),
        ),
        'interview': _field_citation_group(
            ('interview.count', '面试记录数', len(interview_facts) if interview_facts else None),
            ('interview.latest_status', '最近面试状态', latest_interview.get('status')),
            ('interview.latest_feedback', '最近面试反馈', latest_interview.get('feedback')),
            ('interview.latest_notes', '最近面试备注', latest_interview.get('notes')),
        ),
        'offer': _field_citation_group(
            ('offer.count', 'Offer记录数', len(offer_facts) if offer_facts else None),
            ('offer.latest_status', '最近Offer状态', latest_offer.get('status')),
            ('offer.latest_approval_status', '最近审批状态', latest_offer.get('approval_status')),
        ),
        'employee': _field_citation_group(
            ('employee.status', '员工状态', employee_facts.get('status')),
            ('employee.department', '入职部门', employee_facts.get('department')),
            ('employee.job_title', '入职岗位', employee_facts.get('job_title')),
            ('employee.hire_date', '入职日期', employee_facts.get('hire_date')),
        ),
    }
    facts: Dict[str, Any] = {
        'entity_type': 'candidate',
        'name': candidate.name if candidate else resume.candidate_name,
        'candidate': candidate_facts,
        'resume': resume_facts,
        'job': job_facts,
        'target_job': target_job_facts,
        'interviews': interview_facts,
        'offers': offer_facts,
        'linked_employee': employee_facts,
        'field_citations': {k: v for k, v in field_citations.items() if v},
        'sources': [
            source for source, exists in (
                ('candidate', candidate is not None),
                ('resume', resume is not None),
                ('job', job is not None),
                ('interview', bool(interviews)),
                ('offer', bool(offers)),
                ('employee', employee is not None),
            ) if exists
        ],
    }
    entities: List[Dict[str, Any]] = []
    if candidate:
        entities.append(_candidate_card(candidate))
    if resume:
        entities.append(_resume_card(resume, ctx.role))
    if job:
        entities.append(_job_card(job))
    widgets_out = []
    media_widget = _resume_media_widget(resume, ctx.role)
    if media_widget:
        widgets_out.append(media_widget)
    score = resume_facts.get('score')
    match_degree = resume_facts.get('match_degree')
    status = candidate_facts.get('status')
    job_title = job_facts.get('title') or resume_facts.get('job_title')
    recommendation = resume_facts.get('recommendation') or candidate_facts.get('ai_recommendation')
    summary_parts = [f'已汇集 {facts["name"]} 的招聘证据']
    detail_parts = []
    if job_title:
        detail_parts.append(f'应聘岗位：{job_title}')
    if score is not None:
        detail_parts.append(f'简历评分 {score} 分')
    if match_degree is not None:
        detail_parts.append(f'岗位匹配度 {match_degree}')
    if status:
        detail_parts.append(f'候选状态：{status}')
    if recommendation:
        detail_parts.append(f'系统建议：{recommendation}')
    if detail_parts:
        summary_parts.append('；'.join(detail_parts))
    else:
        summary_parts.append(f'来源：{", ".join(facts["sources"])}')
    return {
        'entities': entities,
        'facts': facts,
        'widgets': widgets_out,
        'rows_count': len(entities),
        'summary_hint': '。'.join(summary_parts) + '。',
    }


def _keyword_looks_like_person_name(value: str) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    if re.search(r'(工程师|专员|经理|总监|主管|岗位|职位|部门|中心|团队|候选人|简历|面试|offer|Offer)', text):
        return False
    return bool(re.fullmatch(r'[\u4e00-\u9fa5·]{2,4}', text))


def _candidate_record_matches_keyword(candidate: Candidate, keyword: str) -> bool:
    name = str(getattr(candidate, 'name', '') or '').strip()
    return _entity_name_matches_keyword(name, keyword)


def _resume_record_matches_keyword(resume: Resume, keyword: str) -> bool:
    name = str(getattr(resume, 'candidate_name', '') or '').strip()
    return _entity_name_matches_keyword(name, keyword)


def _entity_name_matches_keyword(name: str, keyword: str) -> bool:
    left = re.sub(r'\s+', '', str(name or '').strip())
    right = re.sub(r'\s+', '', str(keyword or '').strip())
    if not left or not right:
        return False
    return left == right or right in left or left in right


def skill_recruitment_match_matrix(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Compare candidates for one job with connected resume/interview evidence."""
    keyword = str(
        args.get('keyword') or args.get('job_keyword') or args.get('jobKeyword')
        or args.get('job_title') or args.get('jobTitle') or ''
    ).strip()
    job_id = args.get('job_id') or args.get('jobId')
    limit = _clamp_limit(args.get('limit'), default=8, hard_max=12)
    role = ctx.role

    job = Job.query.get(job_id) if job_id else None
    if not job and keyword:
        exact = Job.query.filter(Job.title == keyword).order_by(desc(Job.created_at)).first()
        if exact:
            job = exact
        else:
            like = f'%{keyword}%'
            job = (Job.query.filter(or_(
                Job.title.like(like),
                Job.department.like(like),
                Job.requirements.like(like),
                Job.responsibilities.like(like),
                Job.description.like(like),
            )).order_by(desc(Job.created_at)).first())
    if not job:
        subject = keyword or job_id or '指定岗位'
        return {
            'entities': [],
            'widgets': [W.empty_state(f'未找到“{subject}”对应的岗位。')],
            'facts': {},
            'rows_count': 0,
            'summary_hint': f'未找到“{subject}”对应的岗位。',
        }

    candidate_rows = Candidate.query.filter(Candidate.job_id == job.id).order_by(desc(Candidate.created_at)).limit(limit * 3).all()
    resume_rows = Resume.query.filter(Resume.job_id == job.id).order_by(desc(Resume.created_at)).limit(limit * 3).all()
    resume_ids = [row.id for row in resume_rows]
    if resume_ids:
        linked = Candidate.query.filter(Candidate.resume_id.in_(resume_ids)).order_by(desc(Candidate.created_at)).limit(limit * 3).all()
        seen_candidate_ids = {row.id for row in candidate_rows}
        candidate_rows.extend(row for row in linked if row.id not in seen_candidate_ids)

    items: Dict[str, Dict[str, Any]] = {}

    def remember(candidate: Optional[Candidate] = None, resume: Optional[Resume] = None) -> None:
        if candidate and not resume and candidate.resume_id:
            resume = candidate.resume
        if resume and resume.job_id and resume.job_id != job.id:
            return
        if candidate and candidate.job_id and candidate.job_id != job.id:
            return
        key = candidate.id if candidate else f'resume:{resume.id if resume else uuid.uuid4().hex}'
        current = items.get(key) or {}
        items[key] = {
            'candidate': candidate or current.get('candidate'),
            'resume': resume or current.get('resume'),
        }

    for candidate in candidate_rows:
        remember(candidate=candidate)
    for resume in resume_rows:
        candidate = next((row for row in candidate_rows if row.resume_id == resume.id), None)
        remember(candidate=candidate, resume=resume)

    interview_rows = Interview.query.filter(Interview.job_id == job.id).order_by(desc(Interview.scheduled_at)).limit(limit * 5).all()
    for interview in interview_rows:
        if interview.resume:
            candidate = next((row for row in candidate_rows if row.resume_id == interview.resume_id), None)
            remember(candidate=candidate, resume=interview.resume)

    if not items:
        return {
            'entities': [_job_card(job)],
            'widgets': [
                W.entity_cards([_job_card(job)], title='岗位'),
                W.empty_state(f'{job.title} 暂未查到候选人、简历或面试记录。'),
                _recruitment_sources_widget(job, 0, 0, 0),
            ],
            'facts': {'job': _job_evidence(job), 'candidates': []},
            'rows_count': 0,
            'summary_hint': f'{job.title} 暂未查到候选人、简历或面试记录。',
        }

    interviews_by_resume: Dict[str, List[Interview]] = {}
    for interview in interview_rows:
        if interview.resume_id:
            interviews_by_resume.setdefault(interview.resume_id, []).append(interview)

    ranked_rows: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = [_job_card(job)]
    candidate_count = 0
    resume_count = 0
    interview_count = 0
    for item in items.values():
        candidate = item.get('candidate')
        resume = item.get('resume')
        if not candidate and not resume:
            continue
        resume_facts = _safe_resume_facts(resume, role) if resume else {}
        candidate_count += 1 if candidate else 0
        resume_count += 1 if resume else 0
        row_interviews = interviews_by_resume.get(resume.id if resume else '', [])
        interview_count += len(row_interviews)
        score = _safe_number(resume_facts.get('score'))
        match_degree = _safe_number(resume_facts.get('match_degree'))
        record_score = _candidate_match_record_score(candidate.match_records if candidate else [])
        base_score = score if score is not None else record_score if record_score is not None else match_degree
        if base_score is None:
            base_score = 60
        interview_bonus = min(len(row_interviews) * 3, 9)
        latest_status = row_interviews[0].status if row_interviews else ''
        if latest_status in {'passed', 'offer', 'hired'}:
            interview_bonus += 5
        if latest_status in {'rejected', 'failed'}:
            interview_bonus -= 12
        status_bonus = {
            'offer': 8, 'hired': 10, 'interview': 5, 'screening': 3,
            'new': 0, 'rejected': -15, 'closed': -8,
        }.get(str(candidate.status if candidate else '').lower(), 0)
        final_score = max(0, min(100, round(float(base_score) + interview_bonus + status_bonus, 1)))
        strengths = resume_facts.get('strengths') or []
        weaknesses = resume_facts.get('weaknesses') or []
        name = (candidate.name if candidate else None) or resume_facts.get('candidate_name') or '候选人'
        ranked_rows.append({
            'candidate': candidate,
            'resume': resume,
            'interviews': row_interviews,
            'name': name,
            'status': candidate.status if candidate else '简历待转候选人',
            'source': candidate.source if candidate else '简历',
            'resumeScore': score,
            'matchDegree': match_degree,
            'finalScore': final_score,
            'strengths': strengths[:3],
            'weaknesses': weaknesses[:3],
            'recommendation': resume_facts.get('recommendation') or (candidate.ai_recommendation if candidate else ''),
            'latestInterviewAt': row_interviews[0].scheduled_at.strftime('%Y-%m-%d') if row_interviews and row_interviews[0].scheduled_at else '',
            'latestInterviewStatus': latest_status,
        })
        if candidate:
            entities.append(_candidate_card(candidate))
        if resume:
            entities.append(_resume_card(resume, role))
        entities.extend(_interview_card(row) for row in row_interviews[:1])

    ranked_rows.sort(key=lambda row: (-float(row['finalScore']), -(row.get('matchDegree') or 0), -(row.get('resumeScore') or 0)))
    ranked_rows = ranked_rows[:limit]
    best = ranked_rows[0] if ranked_rows else {}

    matrix_rows = []
    table_rows = []
    workset_entities = []
    for idx, row in enumerate(ranked_rows, start=1):
        ranked_card = _recruitment_ranked_candidate_card(row, idx)
        if ranked_card:
            workset_entities.append(ranked_card)
        matrix_rows.append({
            'rank': idx,
            'name': row['name'],
            'fit': f'{row["finalScore"]}分',
            'resumeScore': f'{row["resumeScore"]}分' if row.get('resumeScore') is not None else '未评分',
            'matchDegree': f'{row["matchDegree"]}%' if row.get('matchDegree') is not None else '—',
            'interviews': len(row.get('interviews') or []),
            'strengths': '；'.join(str(v) for v in row.get('strengths') or []) or '待补充',
            'risks': '；'.join(str(v) for v in row.get('weaknesses') or []) or '暂无明显风险',
            'nextStep': _recruitment_next_step(row),
        })
        table_rows.append({
            'rank': idx,
            'name': row['name'],
            'status': row.get('status') or '—',
            'source': row.get('source') or '—',
            'resumeScore': f'{row["resumeScore"]}分' if row.get('resumeScore') is not None else '未评分',
            'matchDegree': f'{row["matchDegree"]}%' if row.get('matchDegree') is not None else '—',
            'interviews': len(row.get('interviews') or []),
            'latestInterview': ' / '.join(str(v) for v in [row.get('latestInterviewAt'), row.get('latestInterviewStatus')] if v) or '未面试',
            'recommendation': row.get('recommendation') or _recruitment_next_step(row),
        })

    avg_fit = round(sum(float(row['finalScore']) for row in ranked_rows) / len(ranked_rows), 1) if ranked_rows else 0
    top_candidate = best.get('candidate') if best else None
    top_resume = best.get('resume') if best else None
    top_interviews = best.get('interviews') or [] if best else []
    latest_top_interview = top_interviews[0] if top_interviews else None
    recruitment_field_citations = {
        'jobs': _field_citation_group(
            ('job.title', '岗位名称', job.title),
            ('job.department', '所属部门', job.department or (job.department_ref.name if job.department_ref else None)),
            ('job.requirements', '任职要求', job.requirements),
            ('job.responsibilities', '岗位职责', job.responsibilities),
        ),
        'candidates': _field_citation_group(
            ('candidate.top_name', '当前推荐候选人', top_candidate.name if top_candidate else best.get('name')),
            ('candidate.status', '当前推荐阶段', top_candidate.status if top_candidate else best.get('status')),
            ('candidate.source', '候选来源', top_candidate.source if top_candidate else best.get('source')),
            ('candidate.ai_recommendation', '候选建议', top_candidate.ai_recommendation if top_candidate else best.get('recommendation')),
        ),
        'resumes': _field_citation_group(
            ('resume.score', '简历评分', best.get('resumeScore')),
            ('resume.match_degree', '岗位匹配度', best.get('matchDegree')),
            ('resume.summary', '简历概览', (top_resume.ai_analysis or {}).get('summary') if top_resume and isinstance(top_resume.ai_analysis, dict) else None),
            ('resume.weaknesses', '待复核项', best.get('weaknesses')),
        ),
        'interviews': _field_citation_group(
            ('interview.count', '面试记录数', len(top_interviews) if top_interviews else None),
            ('interview.latest_status', '最近面试状态', latest_top_interview.status if latest_top_interview else None),
            ('interview.latest_feedback', '最近面试反馈', latest_top_interview.feedback_text if latest_top_interview else None),
        ),
    }
    recruitment_field_citations = {k: v for k, v in recruitment_field_citations.items() if v}
    summary = (
        f'### {job.title} 候选人匹配结论\n'
        f'- 已关联岗位、候选人、简历和面试记录，纳入 {len(ranked_rows)} 位候选人对比。\n'
        f'- 当前最推荐：{best.get("name") or "暂无"}，综合匹配 {best.get("finalScore") or 0} 分。\n'
        f'- 建议优先推进排名靠前者，并对矩阵里的风险项做面试复核。'
    )
    widgets_out = [
        W.entity_cards(entities[:12], title='岗位与候选人证据'),
        W.metric_cards([
            {'label': '候选人', 'value': candidate_count, 'color': 'blue'},
            {'label': '简历', 'value': resume_count, 'color': 'green'},
            {'label': '面试', 'value': interview_count, 'color': 'purple'},
            {'label': '平均匹配', 'value': avg_fit, 'unit': '分', 'color': 'amber'},
        ], title='招聘匹配指标'),
        W.comparison_matrix([
            {'key': 'rank', 'label': '推荐'},
            {'key': 'name', 'label': '候选人'},
            {'key': 'fit', 'label': '综合匹配'},
            {'key': 'resumeScore', 'label': '简历评分'},
            {'key': 'matchDegree', 'label': '岗位匹配'},
            {'key': 'interviews', 'label': '面试'},
            {'key': 'strengths', 'label': '优势'},
            {'key': 'risks', 'label': '风险'},
            {'key': 'nextStep', 'label': '下一步'},
        ], matrix_rows, title='候选人对比矩阵'),
        W.data_table([
            {'key': 'rank', 'label': '推荐', 'align': 'center'},
            {'key': 'name', 'label': '候选人'},
            {'key': 'status', 'label': '阶段'},
            {'key': 'source', 'label': '来源'},
            {'key': 'resumeScore', 'label': '简历评分', 'align': 'right'},
            {'key': 'matchDegree', 'label': '匹配度', 'align': 'right'},
            {'key': 'interviews', 'label': '面试数', 'align': 'right'},
            {'key': 'latestInterview', 'label': '最近面试'},
            {'key': 'recommendation', 'label': '建议'},
        ], table_rows, title='候选人匹配明细'),
        _recruitment_follow_up_actions(ranked_rows, job),
        _recruitment_sources_widget(job, candidate_count, resume_count, interview_count, recruitment_field_citations),
    ]

    return {
        'entities': entities[:20],
        'widgets': widgets_out,
        'facts': {
            'job': _job_evidence(job),
            'candidates': [
                {
                    'name': row['name'],
                    'final_score': row['finalScore'],
                    'resume_score': row.get('resumeScore'),
                    'match_degree': row.get('matchDegree'),
                    'interview_count': len(row.get('interviews') or []),
                }
                for row in ranked_rows
            ],
            'field_citations': recruitment_field_citations,
        },
        'workset_entities': workset_entities,
        'metrics': {
            'candidate_count': candidate_count,
            'resume_count': resume_count,
            'interview_count': interview_count,
            'avg_fit': avg_fit,
        },
        'rows_count': len(ranked_rows),
        'summary_hint': summary,
    }


def skill_employee_change_impact(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Simulate an employee transfer and show affected HR modules."""
    keyword = str(args.get('keyword') or args.get('employee_keyword') or args.get('employeeKeyword') or '').strip()
    employee_id = args.get('employee_id') or args.get('employeeId')
    target_department = str(args.get('target_department') or args.get('targetDepartment') or '').strip()
    target_position_title = str(args.get('target_position') or args.get('targetPosition') or '').strip()
    action_id = str(args.get('action_id') or args.get('actionId') or '').strip()

    employee = Employee.query.get(employee_id) if employee_id else None
    if not employee and keyword:
        employee = Employee.query.filter(Employee.name == keyword).order_by(desc(Employee.created_at)).first()
        if not employee:
            employee = Employee.query.filter(Employee.name.like(f'%{keyword}%')).order_by(desc(Employee.created_at)).first()
    if not employee:
        return {
            'entities': [],
            'widgets': [W.empty_state(f'未找到员工“{keyword or employee_id or "未指定"}”。')],
            'facts': {},
            'rows_count': 0,
            'summary_hint': f'未找到员工“{keyword or employee_id or "未指定"}”。',
        }

    target_dept = None
    if target_department:
        target_dept = Department.query.filter(Department.name == target_department).first()
        if not target_dept:
            target_dept = (
                Department.query
                .filter(Department.name.like(f'%{target_department}%'))
                .order_by(desc(Department.created_at))
                .first()
            )
    current_dept = employee.department
    current_position = employee.position
    selected_target_position = None
    if target_position_title and target_dept:
        selected_target_position = (
            Position.query
            .filter(Position.department_id == target_dept.id, Position.title == target_position_title)
            .first()
        )
        if not selected_target_position:
            selected_target_position = (
                Position.query
                .filter(Position.department_id == target_dept.id, Position.title.like(f'%{target_position_title}%'))
                .first()
            )
    target_positions = (
        Position.query.filter(Position.department_id == target_dept.id)
        .order_by(Position.level.asc(), Position.title.asc()).limit(8).all()
        if target_dept else []
    )
    target_jobs = (
        Job.query.filter(or_(Job.department_id == target_dept.id, Job.department == target_dept.name))
        .order_by(desc(Job.created_at)).limit(8).all()
        if target_dept else []
    )
    existing_changes = (
        EmployeeChange.query.filter_by(employee_id=employee.id)
        .order_by(desc(EmployeeChange.created_at)).limit(8).all()
    )
    change_ids = [row.id for row in existing_changes]
    approvals = []
    if change_ids:
        approvals = (ApprovalInstance.query.filter(
            ApprovalInstance.business_type == 'employee_change',
            ApprovalInstance.business_id.in_(change_ids),
        ).order_by(desc(ApprovalInstance.created_at)).limit(8).all())
    pending_approvals = [row for row in approvals if row.status == 'pending']
    salary_profile = SalaryProfile.query.filter_by(employee_id=employee.id).first() if ctx.role in PAYROLL_AUTHORIZED_ROLES else None
    like = f'%{employee.name}%'
    notifications = (
        Notification.query.filter(or_(Notification.title.like(like), Notification.content.like(like), Notification.title.like('%异动%')))
        .order_by(desc(Notification.created_at)).limit(8).all()
    )

    entities = [_employee_card(employee, ctx.role, ctx)]
    if current_dept:
        entities.append(_department_card(current_dept))
    if target_dept and (not current_dept or target_dept.id != current_dept.id):
        entities.append(_department_card(target_dept))
    entities.extend(_job_card(job) for job in target_jobs[:4])

    salary_delta = None
    if salary_profile:
        salary_delta = float(getattr(salary_profile, 'position_salary', 0) or 0) * 0.1
    status_items = [
        {
            'label': '当前部门',
            'value': current_dept.name if current_dept else '未设置',
            'status': 'neutral',
            'icon': 'fa-sitemap',
        },
        {
            'label': '目标部门',
            'value': target_dept.name if target_dept else (target_department or '待确认'),
            'status': 'success' if target_dept else 'warning',
            'icon': 'fa-arrow-right',
        },
        {
            'label': '可选岗位',
            'value': len(target_positions) or len(target_jobs),
            'status': 'info',
            'icon': 'fa-briefcase',
            'hint': '来自目标部门岗位/招聘需求',
        },
        {
            'label': '待处理审批',
            'value': len(pending_approvals),
            'status': 'warning' if pending_approvals else 'success',
            'icon': 'fa-stamp',
        },
        {
            'label': '薪资档案',
            'value': '可评估' if salary_profile else '无权限/暂无',
            'status': 'info' if salary_profile else 'warning',
            'icon': 'fa-money-bill',
        },
        {
            'label': '通知触达',
            'value': f'{len(notifications)} 条相关',
            'status': 'neutral',
            'icon': 'fa-bell',
        },
    ]

    timeline_items = []
    if employee.hire_date:
        timeline_items.append({
            'time': employee.hire_date.isoformat(),
            'title': '入职',
            'description': employee.job_title or (current_position.title if current_position else ''),
            'status': 'success',
            'url': '/hrm/employees',
        })
    for change in reversed(existing_changes[:5]):
        timeline_items.append({
            'time': change.effective_date.isoformat() if change.effective_date else (change.created_at.isoformat()[:10] if change.created_at else ''),
            'title': change.change_type or '员工异动',
            'description': change.reason or change.status or '',
            'status': 'warning' if change.status in {'draft', 'pending'} else 'success',
            'url': '/hrm/employee-changes',
        })
    timeline_items.append({
        'time': '模拟',
        'title': f'拟调入 {target_dept.name if target_dept else target_department or "目标部门"}',
        'description': '需要确认岗位承接、薪资口径、审批流和通知对象后才能写入。',
        'status': 'warning',
        'url': '/hrm/employee-changes',
    })

    impact_rows = [
        {
            'module': '员工档案',
            'current': current_dept.name if current_dept else '未设置',
            'after': target_dept.name if target_dept else target_department or '待确认',
            'impact': '部门、直属上级和组织统计会变化',
            'action': '确认目标部门与生效日期',
        },
        {
            'module': '岗位',
            'current': employee.job_title or (current_position.title if current_position else '未设置'),
            'after': (
                selected_target_position.title if selected_target_position
                else target_position_title
                or ' / '.join(row.title for row in target_positions[:2])
                or '待选择'
            ),
            'impact': '岗位序列、职级、招聘缺口和岗位编制可能变化',
            'action': '选择目标岗位并校验编制',
        },
        {
            'module': '薪资',
            'current': _fmt_amount((salary_profile.to_dict() if salary_profile else {}).get('totalSalary')) if salary_profile else '无权限/暂无',
            'after': f'预计需复核岗位工资，参考调整约 {_fmt_amount(salary_delta)} 元' if salary_delta else '需薪酬负责人复核',
            'impact': '岗位工资、绩效工资和工资条生成口径可能变化',
            'action': '进入薪资变更审批前二次确认',
        },
        {
            'module': '审批',
            'current': f'{len(pending_approvals)} 条待处理',
            'after': '新增异动审批',
            'impact': '需要部门负责人/HR/高管按流程审批',
            'action': '确认后发起审批或待办通知',
        },
        {
            'module': '通知',
            'current': f'{len(notifications)} 条相关通知',
            'after': '员工、原部门、目标部门、HR 同步',
            'impact': '需要明确通知对象和生效日期',
            'action': '确认后生成通知草稿',
        },
    ]

    summary = (
        f'### {employee.name} 调岗影响模拟\n'
        f'- 当前：{current_dept.name if current_dept else "未设置部门"} / {employee.job_title or "未设置岗位"}。\n'
        f'- 目标：{target_dept.name if target_dept else target_department or "待确认部门"}。\n'
        '- 这是模拟分析，不会直接改员工档案；如要发起异动，需要先确认岗位、薪资、审批流和通知对象。'
    )
    widgets_out = [
        W.entity_cards(entities, title='异动相关对象'),
        W.status_badges(status_items, title='影响范围状态'),
        W.timeline(timeline_items, title='异动影响时间线'),
        W.data_table([
            {'key': 'module', 'label': '模块'},
            {'key': 'current', 'label': '当前'},
            {'key': 'after', 'label': '拟变更后'},
            {'key': 'impact', 'label': '影响'},
            {'key': 'action', 'label': '建议动作'},
        ], impact_rows, title='跨模块影响清单'),
    ]
    if action_id:
        widgets_out.append(W.confirmation_card(
            '提交员工异动审批',
            (
                f'{employee.name} 调岗到 {target_dept.name if target_dept else target_department or "目标部门"} 的影响已分析。'
                '确认后将创建待审批员工异动申请、审批实例和操作审计；审批通过前不会直接修改员工档案。'
            ),
            action_id,
        ))
    widgets_out.append({
        'type': 'source_citations',
        'title': '本次使用的异动影响证据',
        'sources': [
            {'module': 'employees', 'recordType': 'employees', 'recordId': employee.id, 'title': f'员工档案：{employee.name}', 'url': '/hrm/employees'},
            {'module': 'departments', 'recordType': 'departments', 'recordId': target_dept.id if target_dept else None, 'title': f'目标部门：{target_dept.name if target_dept else target_department or "待确认"}', 'url': '/hrm/departments'},
            {'module': 'jobs', 'recordType': 'jobs', 'title': f'目标部门岗位/招聘需求 {len(target_positions) + len(target_jobs)} 条', 'url': '/hrm/positions'},
            {'module': 'salary_profiles', 'recordType': 'salary_profiles', 'title': '薪资档案' if salary_profile else '薪资档案（无权限或暂无）', 'url': '/salary-profiles'},
            {'module': 'employee_changes', 'recordType': 'employee_changes', 'title': f'历史异动 {len(existing_changes)} 条', 'url': '/hrm/employee-changes'},
            {'module': 'approvals', 'recordType': 'approval_instances', 'title': f'异动审批 {len(approvals)} 条', 'url': '/approval-center'},
            {'module': 'notifications', 'recordType': 'notifications', 'title': f'相关通知 {len(notifications)} 条', 'url': '/notifications'},
        ],
    })

    return {
        'entities': entities,
        'widgets': widgets_out,
        'facts': {
            'employee_id': employee.id,
            'employee_name': employee.name,
            'current_department_id': current_dept.id if current_dept else None,
            'current_department_name': current_dept.name if current_dept else None,
            'target_department_id': target_dept.id if target_dept else None,
            'target_department_name': target_dept.name if target_dept else target_department or None,
            'target_position_id': selected_target_position.id if selected_target_position else None,
            'target_position_title': selected_target_position.title if selected_target_position else target_position_title or None,
            'target_position': selected_target_position.title if selected_target_position else target_position_title or None,
            'pending_approvals': len(pending_approvals),
            'has_salary_profile': bool(salary_profile),
        },
        'rows_count': 1 + len(existing_changes) + len(approvals),
        'summary_hint': summary,
    }


def _parse_effective_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    if text:
        try:
            return parse_business_datetime(text).date()
        except Exception:
            pass
    return business_now().date()


def _parse_salary_adjustment(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r'[-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?', text)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def _resolve_employee_for_salary_adjustment(args: Dict[str, Any]) -> Optional[Employee]:
    employee_id = args.get('employee_id') or args.get('employeeId')
    employee = Employee.query.get(employee_id) if employee_id else None
    if employee:
        return employee
    keyword = str(args.get('keyword') or args.get('employee_keyword') or args.get('employeeKeyword') or '').strip()
    if not keyword:
        return None
    employee = Employee.query.filter(Employee.name == keyword).order_by(desc(Employee.created_at)).first()
    if employee:
        return employee
    return Employee.query.filter(Employee.name.like(f'%{keyword}%')).order_by(desc(Employee.created_at)).first()


def skill_employee_salary_adjustment_impact(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Analyze a salary adjustment and prepare a confirmation card without writing."""
    if ctx.role not in PAYROLL_AUTHORIZED_ROLES:
        return {
            'entities': [],
            'widgets': [W.warning('调薪影响分析需要薪酬授权角色。', level='warning')],
            'rows_count': 0,
            'summary_hint': '权限不足，无法分析或发起调薪。',
        }
    employee = _resolve_employee_for_salary_adjustment(args)
    if not employee:
        return {'entities': [], 'rows_count': 0, 'summary_hint': '未找到需要调薪的员工。'}
    salary_delta = _parse_salary_adjustment(args.get('salary_adjustment') or args.get('salaryAdjustment'))
    if salary_delta is None or salary_delta == Decimal('0'):
        raise ValueError('employee_salary_adjustment_impact requires a non-zero salary_adjustment')

    evidence = skill_employee_evidence_bundle({'employee_id': employee.id}, ctx)
    facts = evidence.get('facts') or {}
    employee_facts = facts.get('employee') if isinstance(facts.get('employee'), dict) else {}
    salary_profile = facts.get('salary_profile') if isinstance(facts.get('salary_profile'), dict) else None
    performance = facts.get('performance') if isinstance(facts.get('performance'), list) else []
    changes = facts.get('employee_changes') if isinstance(facts.get('employee_changes'), list) else []
    approvals = facts.get('change_approvals') if isinstance(facts.get('change_approvals'), list) else []
    notifications = facts.get('notifications') if isinstance(facts.get('notifications'), list) else []
    latest_perf = performance[0] if performance and isinstance(performance[0], dict) else {}
    current_total = (salary_profile or {}).get('totalSalary')
    try:
        after_total = Decimal(str(current_total or '0')) + salary_delta if current_total is not None else None
    except (InvalidOperation, ValueError):
        after_total = None

    action_id = str(args.get('action_id') or args.get('actionId') or '').strip()
    direction = '上调' if salary_delta > 0 else '下调'
    delta_text = _fmt_amount(salary_delta)
    summary = (
        f'### {employee.name} 调薪影响模拟\n'
        f'- 动作：薪资{direction} {delta_text} 元。\n'
        f'- 当前：{employee_facts.get("department") or "未填部门"} / {employee_facts.get("job_title") or employee.job_title or "未填岗位"}。\n'
        f'- 依据：读取员工档案、薪资档案、绩效、历史异动、审批和通知证据；确认前不会写入调薪申请或修改薪资档案。\n'
        '- 确认后只会提交待审批调薪异动，审批通过前薪资档案不会直接变化。'
    )

    impact_rows = [
        {
            'module': '薪资档案',
            'current': _fmt_amount(current_total) if current_total is not None else '暂无档案金额',
            'after': _fmt_amount(after_total) if after_total is not None else f'{direction} {delta_text} 元待审批',
            'impact': '影响薪资合计和后续工资条生成口径',
            'action': '确认后生成待审批调薪异动',
        },
        {
            'module': '绩效',
            'current': f'{latest_perf.get("grade") or "暂无等级"} / {latest_perf.get("finalScore") or latest_perf.get("final_score") or "—"}',
            'after': '作为调薪依据随审批留痕',
            'impact': '绩效与薪资联动需要可追溯证据',
            'action': '在审批意见中保留调薪原因',
        },
        {
            'module': '员工异动',
            'current': f'{len(changes)} 条历史异动',
            'after': '新增 salary_adjustment 异动申请',
            'impact': '审批通过后才可影响薪资档案',
            'action': '确认后创建异动和审批实例',
        },
        {
            'module': '审批',
            'current': f'{len(approvals)} 条异动审批',
            'after': '新增调薪审批待处理',
            'impact': '需要授权审批人确认',
            'action': '提交审批中心',
        },
        {
            'module': '通知',
            'current': f'{len(notifications)} 条相关通知',
            'after': '生成审批待办通知',
            'impact': '确保 HR/审批人收到待办',
            'action': '确认后写入通知中心',
        },
    ]
    widgets_out = [
        W.entity_cards(evidence.get('entities') or [_employee_card(employee, ctx.role, ctx)], title='调薪相关员工'),
        W.metric_cards([
            {'label': '调薪金额', 'value': delta_text, 'unit': '元', 'color': 'green' if salary_delta > 0 else 'amber'},
            {'label': '绩效记录', 'value': len(performance), 'color': 'purple'},
            {'label': '历史异动', 'value': len(changes), 'color': 'blue'},
            {'label': '相关审批', 'value': len(approvals), 'color': 'amber' if approvals else 'green'},
        ], title='调薪影响指标'),
        W.status_badges([
            {'label': '薪资档案', 'value': (salary_profile or {}).get('status') if salary_profile else '暂无/无金额', 'status': 'info' if salary_profile else 'warning', 'icon': 'fa-money-bill'},
            {'label': '确认前写入', 'value': '不会写入', 'status': 'success', 'icon': 'fa-user-shield'},
            {'label': '审批后生效', 'value': '必须审批', 'status': 'warning', 'icon': 'fa-stamp'},
        ], title='调薪安全边界'),
        W.timeline([
            {'time': '当前', 'title': '读取证据', 'description': '员工档案、薪资、绩效、异动、审批和通知', 'status': 'success', 'url': '/salary-profiles'},
            {'time': '确认后', 'title': '提交调薪异动', 'description': f'{direction} {delta_text} 元，状态为 pending', 'status': 'warning', 'url': '/hrm/employee-changes'},
            {'time': '审批后', 'title': '薪资档案联动', 'description': '仅审批通过后由审批工作流影响薪资档案', 'status': 'info', 'url': '/approval-center'},
        ], title='调薪执行路径'),
        W.data_table([
            {'key': 'module', 'label': '模块'},
            {'key': 'current', 'label': '当前'},
            {'key': 'after', 'label': '确认后/审批后'},
            {'key': 'impact', 'label': '影响'},
            {'key': 'action', 'label': '动作'},
        ], impact_rows, title='调薪跨模块影响清单'),
    ]
    if action_id:
        widgets_out.append(W.confirmation_card(
            '提交调薪审批',
            (
                f'{employee.name} 薪资{direction} {delta_text} 元的影响已分析。'
                '确认后将创建待审批调薪异动、审批实例、待办通知和操作审计；审批通过前不会直接修改薪资档案。'
            ),
            action_id,
        ))
    widgets_out.append({
        'type': 'source_citations',
        'title': '本次使用的调薪影响证据',
        'sources': [
            {'module': 'employees', 'recordType': 'employees', 'recordId': employee.id, 'title': f'员工档案：{employee.name}', 'url': '/hrm/employees'},
            {'module': 'salary_profiles', 'recordType': 'salary_profiles', 'recordId': (salary_profile or {}).get('id'), 'title': '薪资档案' if salary_profile else '薪资档案（暂无或无金额）', 'url': '/salary-profiles'},
            {'module': 'performance_reviews', 'recordType': 'performance_reviews', 'title': f'绩效记录 {len(performance)} 条', 'url': '/performance-review'},
            {'module': 'employee_changes', 'recordType': 'employee_changes', 'title': f'历史异动 {len(changes)} 条', 'url': '/hrm/employee-changes'},
            {'module': 'approvals', 'recordType': 'approval_instances', 'title': f'异动审批 {len(approvals)} 条', 'url': '/approval-center'},
            {'module': 'notifications', 'recordType': 'notifications', 'title': f'相关通知 {len(notifications)} 条', 'url': '/notifications'},
        ],
    })
    return {
        'entities': evidence.get('entities') or [_employee_card(employee, ctx.role, ctx)],
        'widgets': widgets_out,
        'facts': {
            'employee_id': employee.id,
            'employee_name': employee.name,
            'department_id': employee.department_id,
            'department_name': employee.department.name if employee.department else None,
            'salary_adjustment': str(salary_delta),
            'current_total_salary': str(current_total) if current_total is not None else None,
            'after_total_salary': str(after_total) if after_total is not None else None,
            'change_type': 'salary_adjustment',
            'direct_salary_update': False,
        },
        'rows_count': 1 + len(performance) + len(changes) + len(approvals),
        'summary_hint': summary,
    }


def _resolve_employee_for_change(args: Dict[str, Any]) -> Optional[Employee]:
    employee_id = args.get('employee_id') or args.get('employeeId')
    employee = Employee.query.get(employee_id) if employee_id else None
    if employee:
        return employee
    keyword = str(args.get('keyword') or args.get('employee_keyword') or args.get('employeeKeyword') or '').strip()
    if not keyword:
        return None
    employee = Employee.query.filter(Employee.name == keyword).order_by(desc(Employee.created_at)).first()
    if employee:
        return employee
    return Employee.query.filter(Employee.name.like(f'%{keyword}%')).order_by(desc(Employee.created_at)).first()


def _resolve_department_for_change(args: Dict[str, Any]) -> Optional[Department]:
    department_id = args.get('target_department_id') or args.get('targetDepartmentId') or args.get('after_department_id')
    department = Department.query.get(department_id) if department_id else None
    if department:
        return department
    name = str(args.get('target_department') or args.get('targetDepartment') or args.get('department') or '').strip()
    if not name:
        return None
    department = Department.query.filter(Department.name == name).first()
    if department:
        return department
    return (
        Department.query
        .filter(Department.name.like(f'%{name}%'))
        .order_by(desc(Department.created_at))
        .first()
    )


def _resolve_position_for_change(args: Dict[str, Any], department: Optional[Department]) -> Optional[Position]:
    position_id = args.get('target_position_id') or args.get('targetPositionId') or args.get('after_position_id')
    position = Position.query.get(position_id) if position_id else None
    if position:
        return position
    title = str(args.get('target_position') or args.get('targetPosition') or args.get('position') or '').strip()
    if not title:
        return None
    query = Position.query
    if department:
        query = query.filter(Position.department_id == department.id)
    position = query.filter(Position.title == title).first()
    if position:
        return position
    return query.filter(Position.title.like(f'%{title}%')).first()


def _approval_user_for_change(target_department: Optional[Department], fallback_user_id: Optional[str]) -> Optional[str]:
    if target_department and target_department.manager_id:
        manager_user = User.query.filter_by(employee_id=target_department.manager_id, status='active').first()
        if manager_user:
            return manager_user.id
    for role in (ROLE_HR_ADMIN, ROLE_ADMIN, ROLE_EXECUTIVE, ROLE_MANAGER):
        user = User.query.filter_by(role=role, status='active').order_by(User.created_at.asc()).first()
        if user:
            return user.id
    return fallback_user_id


def skill_employee_change_submit(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Submit a confirmed employee change application without applying it."""
    employee = _resolve_employee_for_change(args)
    if not employee:
        raise ValueError('employee_change_submit requires a resolvable employee')
    salary_delta = _parse_salary_adjustment(
        args.get('salary_adjustment') or args.get('salaryAdjustment')
    )
    target_dept = _resolve_department_for_change(args)
    if not target_dept and salary_delta and salary_delta != Decimal('0'):
        target_dept = employee.department
    if not target_dept:
        raise ValueError('employee_change_submit requires a target department or a salary adjustment on an employee with a department')

    action_id = str(args.get('action_id') or args.get('actionId') or '').strip()
    marker = f'[assistant_action:{action_id}]' if action_id else ''
    if marker:
        existing = (
            EmployeeChange.query.filter(EmployeeChange.reason.like(f'%{marker}%'))
            .order_by(desc(EmployeeChange.created_at)).first()
        )
        if existing:
            approval = ApprovalInstance.query.filter_by(
                business_type='employee_change',
                business_id=existing.id,
            ).order_by(desc(ApprovalInstance.created_at)).first()
            return {
                'entities': [
                    _generic_card(
                        'employee_change', existing.id, f'员工异动申请：{employee.name}',
                        existing.change_type or '', f'状态：{existing.status or "—"}', '/hrm/employee-changes',
                    ),
                ],
                'facts': {
                    'employee_change_id': existing.id,
                    'approval_id': approval.id if approval else None,
                    'created': False,
                    'idempotent': True,
                },
                'rows_count': 0,
                'summary_hint': f'该确认动作已提交过员工异动申请：{existing.id}，未重复写入。',
            }

    target_position = _resolve_position_for_change(args, target_dept)
    source_dept = employee.department
    source_position = employee.position
    effective_date = _parse_effective_date(args.get('effective_date') or args.get('effectiveDate'))
    change_type = 'transfer'
    if salary_delta and salary_delta != Decimal('0') and source_dept and source_dept.id == target_dept.id:
        change_type = 'salary_adjustment'
    elif salary_delta and salary_delta != Decimal('0'):
        change_type = 'transfer_salary_adjustment'

    base_reason = str(args.get('reason') or '').strip()
    if not base_reason:
        base_reason = (
            f'AI 助手确认后提交：{employee.name} 从 '
            f'{source_dept.name if source_dept else "未设置部门"} 调整到 {target_dept.name}。'
        )
    reason = f'{base_reason}\n{marker}'.strip() if marker else base_reason
    approver_id = _approval_user_for_change(target_dept, getattr(ctx, 'user_id', None))
    change = EmployeeChange(
        id=str(uuid.uuid4()),
        employee_id=employee.id,
        change_type=change_type,
        before_department_id=employee.department_id,
        after_department_id=target_dept.id,
        before_position_id=employee.position_id,
        after_position_id=target_position.id if target_position else None,
        before_level=source_position.level if source_position else None,
        after_level=target_position.level if target_position else None,
        salary_adjustment=salary_delta,
        effective_date=effective_date,
        reason=reason,
        status='pending',
        created_by=getattr(ctx, 'user_id', None),
    )
    db.session.add(change)
    db.session.flush()

    approval = ApprovalInstance(
        id=str(uuid.uuid4()),
        business_type='employee_change',
        business_id=change.id,
        title=f'员工异动审批：{employee.name} -> {target_dept.name}',
        applicant_id=getattr(ctx, 'user_id', None),
        approver_id=approver_id,
        status='pending',
        submitted_at=business_now(),
        remark='由 HRM Copilot 二次确认后提交；审批通过前不会修改员工档案。',
    )
    db.session.add(approval)
    approval_notification = Notification(
        id=str(uuid.uuid4()),
        user_id=approver_id,
        title=f'员工异动审批待处理：{employee.name}',
        content=(
            f'{employee.name} 拟从 {source_dept.name if source_dept else "未设置部门"} '
            f'调整到 {target_dept.name}，请在审批中心复核。审批通过前员工档案不会被直接修改。'
        ),
        notice_type='approval',
        status='unread',
        link_url='/approval-center',
    )
    db.session.add(approval_notification)
    requester_id = getattr(ctx, 'user_id', None)
    requester_notification = None
    if requester_id and requester_id != approver_id:
        requester_notification = Notification(
            id=str(uuid.uuid4()),
            user_id=requester_id,
            title=f'员工异动审批已提交：{employee.name}',
            content=(
                f'{employee.name} 的员工异动/调薪申请已由 HRM Copilot 提交至审批中心；'
                '审批通过前员工档案和薪资档案不会被直接修改。'
            ),
            notice_type='approval',
            status='unread',
            link_url='/approval-center',
        )
        db.session.add(requester_notification)
    notification_entities = [approval_notification]
    if requester_notification:
        notification_entities.append(requester_notification)
    operation_detail = {
        'source': 'assistant_confirmed_action',
        'sourceActionId': action_id or None,
        'employeeId': employee.id,
        'employeeName': employee.name,
        'beforeDepartmentId': employee.department_id,
        'beforeDepartmentName': source_dept.name if source_dept else None,
        'afterDepartmentId': target_dept.id,
        'afterDepartmentName': target_dept.name,
        'beforePositionId': employee.position_id,
        'afterPositionId': target_position.id if target_position else None,
        'salaryAdjustment': str(salary_delta) if salary_delta is not None else None,
        'effectiveDate': effective_date.isoformat() if effective_date else None,
        'approvalId': approval.id,
        'directEmployeeUpdate': False,
    }
    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=getattr(ctx, 'user_id', None),
        module='employee_changes',
        action='ai_confirm_submit',
        target_id=change.id,
        detail=operation_detail,
    ))
    db.session.commit()

    entities = [
        _employee_card(employee, ctx.role, ctx),
        _generic_card(
            'employee_change', change.id, f'员工异动申请：{employee.name}',
            change.change_type, f'状态：{change.status}', '/hrm/employee-changes',
        ),
        _generic_card(
            'approval', approval.id, approval.title,
            approval.business_type, f'状态：{approval.status}', '/approval-center',
        ),
    ]
    entities.extend(
        _generic_card(
            'notification', notification.id, notification.title,
            notification.notice_type, f'状态：{notification.status}', '/notifications',
        )
        for notification in notification_entities
    )
    notification_sources = [
        {
            'module': 'notifications',
            'recordType': 'notifications',
            'recordId': notification.id,
            'title': notification.title,
            'url': '/notifications',
        }
        for notification in notification_entities
    ]
    widgets_out = [
        W.status_badges([
            {'label': '异动申请', 'value': change.status, 'status': 'warning', 'icon': 'fa-random'},
            {'label': '审批流', 'value': approval.status, 'status': 'warning', 'icon': 'fa-stamp'},
            {'label': '员工档案', 'value': '未直接修改', 'status': 'success', 'icon': 'fa-user-shield'},
            {'label': '操作审计', 'value': '已记录', 'status': 'success', 'icon': 'fa-clipboard-list'},
        ], title='确认执行结果'),
        W.data_table([
            {'key': 'field', 'label': '字段'},
            {'key': 'before', 'label': '确认前'},
            {'key': 'after', 'label': '提交后待审批'},
        ], [
            {'field': '部门', 'before': source_dept.name if source_dept else '未设置', 'after': target_dept.name},
            {'field': '岗位', 'before': employee.job_title or (source_position.title if source_position else '未设置'), 'after': target_position.title if target_position else '待审批时确认'},
            {'field': '薪资调整', 'before': '原薪资口径', 'after': _fmt_amount(salary_delta) if salary_delta is not None else '无直接调薪'},
            {'field': '生效日期', 'before': '未生效', 'after': effective_date.isoformat()},
        ], title='异动提交明细', exportable=False),
        {
            'type': 'source_citations',
            'title': '员工异动确认执行证据',
            'sources': [
                {'module': 'employees', 'recordType': 'employees', 'recordId': employee.id, 'title': f'员工档案：{employee.name}', 'url': '/hrm/employees'},
                {'module': 'departments', 'recordType': 'departments', 'recordId': target_dept.id, 'title': f'目标部门：{target_dept.name}', 'url': '/hrm/departments'},
                {'module': 'employee_changes', 'recordType': 'employee_changes', 'recordId': change.id, 'title': '确认后写入员工异动申请', 'url': '/hrm/employee-changes'},
                {'module': 'approvals', 'recordType': 'approval_instances', 'recordId': approval.id, 'title': '确认后创建异动审批', 'url': '/approval-center'},
                {'module': 'operation_logs', 'recordType': 'operation_logs', 'recordId': change.id, 'title': 'AI 确认提交操作审计', 'url': '/operation-logs'},
                *notification_sources,
            ],
        },
    ]
    return {
        'entities': entities,
        'widgets': widgets_out,
        'facts': {
            'employee_change_id': change.id,
            'approval_id': approval.id,
            'notification_id': approval_notification.id,
            'notification_ids': [notification.id for notification in notification_entities],
            'status': change.status,
            'approval_status': approval.status,
            'employee_department_id': employee.department_id,
            'target_department_id': target_dept.id,
            'direct_employee_update': False,
            'created': True,
        },
        'rows_count': 2 + len(notification_entities),
        'summary_hint': (
            f'已提交 {employee.name} 调整到 {target_dept.name} 的员工异动申请，并创建待审批记录；'
            '审批通过前不会直接修改员工档案。'
        ),
    }


def skill_payroll_performance_link(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Correlate low performance with salary and attendance anomalies."""
    if ctx.role not in PAYROLL_AUTHORIZED_ROLES:
        return {
            'entities': [],
            'widgets': [W.warning('薪酬绩效联动分析需要薪酬授权角色。', level='warning')],
            'rows_count': 0,
            'summary_hint': '权限不足，已拒绝薪酬绩效联动分析。',
        }

    now = business_now()
    quarter = int(args.get('quarter') or ((now.month - 1) // 3 + 1))
    year = int(args.get('year') or now.year)
    start_month = (quarter - 1) * 3 + 1
    start_date = datetime(year, start_month, 1)
    end_month = start_month + 3
    end_date = datetime(year + (1 if end_month > 12 else 0), ((end_month - 1) % 12) + 1, 1)
    low_grades = {'C', 'D', 'E', 'F', '不合格', '待改进'}

    review_query = PerformanceReview.query.filter(
        PerformanceReview.created_at >= start_date,
        PerformanceReview.created_at < end_date,
    )
    employee_id = str(args.get('employee_id') or '').strip()
    department_id = str(args.get('department_id') or '').strip()
    cycle_id = str(args.get('cycle_id') or '').strip()
    if cycle_id:
        review_query = review_query.filter(PerformanceReview.cycle_id == cycle_id)
    if employee_id:
        review_query = review_query.filter(PerformanceReview.employee_id == employee_id)
    elif department_id:
        department_employee_ids = [
            row[0] for row in Employee.query.with_entities(Employee.id).filter_by(
                department_id=department_id,
            ).all()
        ]
        if department_employee_ids:
            review_query = review_query.filter(PerformanceReview.employee_id.in_(department_employee_ids))
        else:
            review_query = review_query.filter(False)

    reviews = review_query.order_by(desc(PerformanceReview.created_at)).limit(300).all()
    low_reviews = []
    for review in reviews:
        score = _safe_number(review.final_score)
        grade = str(review.grade or '').upper()
        if grade in low_grades or (score is not None and score < 70):
            low_reviews.append(review)
    if not low_reviews:
        fallback_query = PerformanceReview.query
        if cycle_id:
            fallback_query = fallback_query.filter(PerformanceReview.cycle_id == cycle_id)
        if employee_id:
            fallback_query = fallback_query.filter(PerformanceReview.employee_id == employee_id)
        elif department_id:
            department_employee_ids = [
                row[0] for row in Employee.query.with_entities(Employee.id).filter_by(
                    department_id=department_id,
                ).all()
            ]
            if department_employee_ids:
                fallback_query = fallback_query.filter(PerformanceReview.employee_id.in_(department_employee_ids))
            else:
                fallback_query = fallback_query.filter(False)
        fallback = fallback_query.order_by(desc(PerformanceReview.created_at)).limit(300).all()
        for review in fallback:
            score = _safe_number(review.final_score)
            grade = str(review.grade or '').upper()
            if grade in low_grades or (score is not None and score < 70):
                low_reviews.append(review)
        if low_reviews:
            start_date = min((row.created_at for row in low_reviews if row.created_at), default=start_date)
            end_date = now

    employee_ids = list(dict.fromkeys(row.employee_id for row in low_reviews if row.employee_id))
    salary_profiles = {
        row.employee_id: row for row in SalaryProfile.query.filter(SalaryProfile.employee_id.in_(employee_ids)).all()
    } if employee_ids else {}
    attendance_rows = (
        AttendanceRecord.query.filter(
            AttendanceRecord.employee_id.in_(employee_ids),
            AttendanceRecord.attendance_date >= start_date.date(),
            AttendanceRecord.attendance_date < end_date.date(),
        ).order_by(desc(AttendanceRecord.attendance_date)).limit(500).all()
        if employee_ids else []
    )
    attendance_by_employee: Dict[str, List[AttendanceRecord]] = {}
    for row in attendance_rows:
        attendance_by_employee.setdefault(row.employee_id, []).append(row)

    rows_out = []
    entities = []
    for review in low_reviews[:30]:
        employee = review.employee
        if not employee:
            continue
        profile = salary_profiles.get(employee.id)
        att = attendance_by_employee.get(employee.id, [])
        abnormal = [row for row in att if (row.status or 'normal') != 'normal']
        total_salary = profile.to_dict().get('totalSalary') if profile else None
        rows_out.append({
            'employeeName': employee.name,
            'department': employee.department.name if employee.department else '—',
            'grade': review.grade or '—',
            'finalScore': _fmt_amount(review.final_score),
            'salaryStatus': profile.status if profile else '暂无档案',
            'totalSalary': _fmt_amount(total_salary) if total_salary is not None else '—',
            'attendanceAnomaly': len(abnormal),
            'commonRisk': _performance_payroll_risk(review, profile, abnormal),
        })
        entities.append(_employee_card(employee, ctx.role, ctx))

    anomaly_count = sum(1 for row in rows_out if int(row['attendanceAnomaly'] or 0) > 0)
    salary_issue_count = sum(1 for row in rows_out if row['salaryStatus'] not in {'active', '暂无档案'})
    first_row = rows_out[0] if rows_out else {}
    link_field_citations = {
        'employees': _field_citation_group(
            ('employee.count', '纳入员工数', len(rows_out)),
            ('employee.sample_name', '样本员工', first_row.get('employeeName')),
            ('employee.sample_department', '样本部门', first_row.get('department')),
        ),
        'performance_reviews': _field_citation_group(
            ('performance.period', '绩效周期', f'{year}Q{quarter}'),
            ('performance.low_count', '低绩效人数', len(rows_out)),
            ('performance.sample_grade', '样本绩效等级', first_row.get('grade')),
            ('performance.sample_score', '样本绩效得分', first_row.get('finalScore')),
        ),
        'salary_profiles': _field_citation_group(
            ('salary.profile_count', '薪资档案数', len(salary_profiles)),
            ('salary.issue_count', '需复核档案数', salary_issue_count),
            ('salary.sample_status', '样本薪资状态', first_row.get('salaryStatus')),
            ('salary.sample_total', '样本薪资合计', first_row.get('totalSalary')),
        ),
        'attendance_records': _field_citation_group(
            ('attendance.record_count', '覆盖考勤记录', len(attendance_rows)),
            ('attendance.anomaly_employee_count', '有考勤异常员工数', anomaly_count),
            ('attendance.window', '考勤窗口', f'{start_date.date().isoformat()} 至 {end_date.date().isoformat()}'),
            ('attendance.sample_anomaly_count', '样本异常次数', first_row.get('attendanceAnomaly')),
        ),
    }
    link_field_citations = {k: v for k, v in link_field_citations.items() if v}
    widgets_out = [
        W.metric_cards([
            {'label': '低绩效人数', 'value': len(rows_out), 'color': 'red' if rows_out else 'green'},
            {'label': '有考勤异常', 'value': anomaly_count, 'color': 'orange'},
            {'label': '薪资档案异常', 'value': salary_issue_count, 'color': 'amber'},
            {'label': '覆盖考勤记录', 'value': len(attendance_rows), 'color': 'blue'},
        ], title=f'{year}Q{quarter} 绩效薪资考勤联动'),
        W.bar_chart([
            {'label': '低绩效', 'value': len(rows_out)},
            {'label': '考勤异常', 'value': anomaly_count},
            {'label': '薪资需复核', 'value': salary_issue_count},
        ], title='共性异常分布'),
        W.data_table([
            {'key': 'employeeName', 'label': '员工'},
            {'key': 'department', 'label': '部门'},
            {'key': 'grade', 'label': '绩效'},
            {'key': 'finalScore', 'label': '得分', 'align': 'right'},
            {'key': 'salaryStatus', 'label': '薪资档案'},
            {'key': 'totalSalary', 'label': '薪资合计', 'align': 'right'},
            {'key': 'attendanceAnomaly', 'label': '考勤异常', 'align': 'right'},
            {'key': 'commonRisk', 'label': '共性判断'},
        ], rows_out, title='低绩效员工联动明细'),
        {
            'type': 'source_citations',
            'title': '本次使用的联动证据',
            'sources': [
                {'module': 'employees', 'recordType': 'employees', 'title': f'员工 {len(rows_out)} 人', 'url': '/hrm/employees', 'fields': link_field_citations.get('employees') or []},
                {'module': 'performance_reviews', 'recordType': 'performance_reviews', 'title': f'低绩效评估 {len(low_reviews)} 条', 'url': '/performance-review', 'fields': link_field_citations.get('performance_reviews') or []},
                {'module': 'salary_profiles', 'recordType': 'salary_profiles', 'title': f'薪资档案 {len(salary_profiles)} 条', 'url': '/salary-profiles', 'fields': link_field_citations.get('salary_profiles') or []},
                {'module': 'attendance_records', 'recordType': 'attendance_records', 'title': f'考勤记录 {len(attendance_rows)} 条', 'url': '/hrm/attendance-records', 'fields': link_field_citations.get('attendance_records') or []},
            ],
        },
    ]
    summary = (
        f'### {year}Q{quarter} 绩效薪资考勤联动\n'
        f'- 识别绩效低于 B 或得分低于 70 的员工 {len(rows_out)} 人。\n'
        f'- 其中 {anomaly_count} 人同时存在考勤异常，{salary_issue_count} 人薪资档案需要复核。\n'
        '- 建议先做主管复盘，再决定是否进入调薪、绩效改进或考勤辅导流程。'
    )
    return {
        'entities': entities,
        'widgets': widgets_out,
        'metrics': {
            'lowPerformanceEmployees': len(rows_out),
            'attendanceAnomalyEmployees': anomaly_count,
            'salaryIssueEmployees': salary_issue_count,
            'fieldEvidenceCount': sum(len(v) for v in link_field_citations.values()),
        },
        'facts': {
            'field_citations': link_field_citations,
        },
        'rows_count': len(rows_out),
        'summary_hint': summary,
    }


def skill_employee_attendance_evidence(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Assemble one employee's attendance records and approved request evidence."""
    keyword = str(args.get('keyword') or args.get('employee_keyword') or args.get('employeeKeyword') or '').strip()
    employee_id = args.get('employee_id') or args.get('employeeId')
    recent_days = _clamp_limit(args.get('recent_days') or args.get('recentDays'), default=30, hard_max=180)
    month = str(args.get('month') or '').strip()

    employee = Employee.query.get(employee_id) if employee_id else None
    if not employee and keyword:
        employee = Employee.query.filter(Employee.name == keyword).order_by(desc(Employee.created_at)).first()
        if not employee:
            employee = Employee.query.filter(Employee.name.like(f'%{keyword}%')).order_by(desc(Employee.created_at)).first()
    if not employee:
        return {
            'entities': [],
            'widgets': [W.empty_state(f'未找到员工“{keyword or employee_id or "未指定"}”。')],
            'rows_count': 0,
            'summary_hint': f'未找到员工“{keyword or employee_id or "未指定"}”。',
        }

    start_dt = None
    end_dt = None
    range_label = f'最近 {recent_days} 天'
    if month and len(month) >= 7:
        try:
            year, m = int(month[:4]), int(month[5:7])
            start_dt = datetime(year, m, 1)
            end_dt = datetime(year + (m // 12), (m % 12) + 1, 1)
            range_label = f'{year}-{m:02d}'
        except Exception:
            start_dt = None
            end_dt = None
    if start_dt is None:
        end_dt = business_now()
        start_dt = end_dt - timedelta(days=recent_days)

    records = (
        AttendanceRecord.query.filter(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.attendance_date >= start_dt.date(),
            AttendanceRecord.attendance_date <= end_dt.date(),
        ).order_by(desc(AttendanceRecord.attendance_date)).limit(120).all()
    )
    requests = (
        EmployeeRequest.query.filter(
            EmployeeRequest.employee_id == employee.id,
            EmployeeRequest.status == 'approved',
            EmployeeRequest.start_time >= start_dt,
            EmployeeRequest.start_time <= end_dt,
        ).order_by(desc(EmployeeRequest.start_time)).limit(60).all()
    )
    status_counter: Dict[str, int] = {}
    for row in records:
        status = row.status or 'normal'
        status_counter[status] = status_counter.get(status, 0) + 1
    abnormal = [row for row in records if not _is_attendance_normal(row.status)]

    daily_buckets: Dict[str, Dict[str, int]] = {}
    for row in sorted(records, key=lambda item: item.attendance_date or date.min):
        if not row.attendance_date:
            continue
        key = row.attendance_date.isoformat()
        bucket = daily_buckets.setdefault(key, {'total': 0, 'anomaly': 0})
        bucket['total'] += 1
        if not _is_attendance_normal(row.status):
            bucket['anomaly'] += 1

    record_rows = [{
        'date': row.attendance_date.isoformat() if row.attendance_date else '—',
        'status': _attendance_status_label(row.status),
        'workHours': _fmt_amount(row.work_hours) if row.work_hours is not None else '—',
        'source': row.source or '—',
        'remark': row.remark or '—',
    } for row in records[:20]]
    timeline_items = []
    for row in reversed(records[:12]):
        timeline_items.append({
            'time': row.attendance_date.isoformat() if row.attendance_date else '',
            'title': _attendance_status_label(row.status),
            'description': row.remark or row.source or '',
            'status': 'success' if (row.status or 'normal') == 'normal' else 'warning',
            'url': '/hrm/attendance-records',
        })
    for request in requests[:8]:
        timeline_items.append({
            'time': request.start_time.isoformat()[:10] if request.start_time else '',
            'title': f'已批{_request_type_label(request.request_type)}',
            'description': request.title or request.reason or '',
            'status': 'info',
            'url': '/employee-requests',
        })
    timeline_items.sort(key=lambda item: item.get('time') or '')

    status_items = [
        {
            'label': _attendance_status_label(status),
            'value': count,
            'status': 'success' if status == 'normal' else 'warning',
            'icon': 'fa-clock',
        }
        for status, count in status_counter.items()
    ]
    if requests:
        status_items.append({
            'label': '已批申请',
            'value': len(requests),
            'status': 'info',
            'icon': 'fa-calendar-check',
            'hint': '请假/加班/出差/补卡等审批记录',
        })

    latest_record = records[0] if records else None
    latest_request = requests[0] if requests else None
    field_citations = {
        'employees': _field_citation_group(
            ('employee.name', '员工姓名', employee.name),
            ('employee.department', '所属部门', employee.department.name if employee.department else None),
            ('employee.job_title', '岗位', employee.job_title),
        ),
        'attendance_records': _field_citation_group(
            ('attendance.range', '统计范围', range_label),
            ('attendance.record_count', '考勤记录数', len(records)),
            ('attendance.abnormal_count', '异常记录数', len(abnormal)),
            (
                'attendance.latest_status',
                '最近考勤状态',
                _attendance_status_label(latest_record.status) if latest_record else None,
            ),
            (
                'attendance.latest_date',
                '最近考勤日期',
                latest_record.attendance_date.isoformat() if latest_record and latest_record.attendance_date else None,
            ),
        ),
        'attendance_stats': _field_citation_group(
            (
                'attendance.status_counts',
                '状态分布',
                '、'.join(
                    f'{_attendance_status_label(status)}:{count}'
                    for status, count in status_counter.items()
                ) if status_counter else None,
            ),
        ),
        'leave_requests': _field_citation_group(
            ('requests.approved_count', '已批申请数', len(requests)),
            ('requests.latest_type', '最近申请类型', _request_type_label(latest_request.request_type) if latest_request else None),
            ('requests.latest_status', '最近申请状态', latest_request.status if latest_request else None),
        ),
    }
    field_citations = {key: value for key, value in field_citations.items() if value}

    widgets_out = [
        W.entity_cards([_employee_card(employee, ctx.role, ctx)], title='员工档案'),
        W.metric_cards([
            {'label': '考勤记录', 'value': len(records), 'color': 'blue'},
            {'label': '异常记录', 'value': len(abnormal), 'color': 'red' if abnormal else 'green'},
            {'label': '已批申请', 'value': len(requests), 'color': 'purple'},
            {'label': '统计范围', 'value': range_label, 'color': 'gray'},
        ], title='个人考勤证据'),
    ]
    if daily_buckets:
        dates = list(daily_buckets.keys())[-14:]
        widgets_out.append(W.echarts({
            'xAxis': {'type': 'category', 'data': dates},
            'yAxis': {'type': 'value'},
            'series': [
                {
                    'name': '异常',
                    'type': 'line',
                    'data': [daily_buckets[item]['anomaly'] for item in dates],
                },
                {
                    'name': '记录',
                    'type': 'bar',
                    'data': [daily_buckets[item]['total'] for item in dates],
                },
            ],
        }, title=f'{employee.name} 考勤记录/异常趋势', chart_type='line'))
    if status_items:
        widgets_out.append(W.status_badges(status_items, title='状态分布'))
    if record_rows:
        widgets_out.append(W.data_table([
            {'key': 'date', 'label': '日期'},
            {'key': 'status', 'label': '状态'},
            {'key': 'workHours', 'label': '工时', 'align': 'right'},
            {'key': 'source', 'label': '来源'},
            {'key': 'remark', 'label': '说明'},
        ], record_rows, title=f'{employee.name} 考勤明细'))
    if timeline_items:
        widgets_out.append(W.timeline(timeline_items, title='考勤与审批时间线'))
    widgets_out.append({
        'type': 'source_citations',
        'title': '本次使用的考勤证据',
        'sources': [
            {'module': 'employees', 'recordType': 'employees', 'recordId': employee.id, 'title': f'员工档案：{employee.name}', 'url': '/hrm/employees', 'fields': field_citations.get('employees') or []},
            {'module': 'attendance_records', 'recordType': 'attendance_records', 'title': f'{range_label} 考勤记录 {len(records)} 条', 'url': '/hrm/attendance-records', 'fields': field_citations.get('attendance_records') or []},
            {'module': 'attendance_stats', 'recordType': 'attendance_stats', 'title': f'{range_label} 个人考勤统计口径', 'url': '/attendance-stats', 'fields': field_citations.get('attendance_stats') or []},
            {'module': 'leave_requests', 'recordType': 'employee_requests', 'title': f'已批请假/加班/出差/补卡 {len(requests)} 条', 'url': '/employee-requests', 'fields': field_citations.get('leave_requests') or []},
        ],
    })

    abnormal_parts = [
        f'{_attendance_status_label(status)} {count} 次'
        for status, count in status_counter.items()
        if status != 'normal'
    ]
    summary = (
        f'### {employee.name} {range_label}考勤异常分析\n'
        f'- 共读取考勤记录 {len(records)} 条，异常 {len(abnormal)} 次。'
        f'{("其中" + "、".join(abnormal_parts) + "。") if abnormal_parts else "未发现异常。"}\n'
        f'- 同期已批申请 {len(requests)} 条，可用于解释加班、请假、出差或补卡类记录。'
    )
    return {
        'entities': [_employee_card(employee, ctx.role, ctx)],
        'widgets': widgets_out,
        'metrics': {
            'totalRecords': len(records),
            'anomalyRecords': len(abnormal),
            'approvedRequests': len(requests),
            'statusCounts': status_counter,
            'fieldEvidenceCount': sum(len(value) for value in field_citations.values()),
        },
        'facts': {'field_citations': field_citations},
        'rows_count': len(records),
        'summary_hint': summary,
    }


def _request_type_label(value: Any) -> str:
    return {
        'leave': '请假',
        'overtime': '加班',
        'travel': '出差',
        'business_trip': '出差',
        'makeup': '补卡',
        'makeup_card': '补卡',
    }.get(str(value or ''), str(value or '申请'))


def _performance_payroll_risk(review: PerformanceReview, profile: Optional[SalaryProfile],
                              abnormal: List[AttendanceRecord]) -> str:
    risks = []
    if abnormal:
        risks.append('绩效低且有考勤异常')
    if profile and profile.status != 'active':
        risks.append('薪资档案非有效状态')
    if not profile:
        risks.append('缺少薪资档案')
    return '；'.join(risks) if risks else '绩效低，暂未发现薪资/考勤共同异常'


def _safe_number(value: Any) -> Optional[float]:
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_match_record_score(records: Any) -> Optional[float]:
    if not isinstance(records, list):
        return None
    scores: List[float] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ('score', 'matchScore', 'match_score', 'fitScore', 'fit_score'):
            number = _safe_number(record.get(key))
            if number is not None:
                scores.append(number)
                break
    return max(scores) if scores else None


def _recruitment_next_step(row: Dict[str, Any]) -> str:
    status = str(row.get('status') or '').lower()
    if status in {'offer', 'hired'}:
        return '推进 Offer/入职衔接'
    if status in {'rejected', 'closed'}:
        return '不建议继续推进'
    if not row.get('interviews'):
        return '优先安排首轮面试'
    if float(row.get('finalScore') or 0) >= 85:
        return '建议进入下一轮/Offer 评审'
    return '补充面试验证风险项'


def _recruitment_follow_up_actions(rows: List[Dict[str, Any]], job: Optional[Job] = None) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []
    top = rows[0] if rows else {}
    top_name = str(top.get('name') or '').strip()
    second = rows[1] if len(rows) > 1 else {}
    second_name = str(second.get('name') or '').strip()
    job_title = job.title if job else str((top.get('job') or {}).get('title') or '').strip()
    if top_name:
        actions.append({
            'label': f'分析{top_name}面试重点',
            'payload': f'分析{top_name}的风险、面试重点和推进建议',
            'variant': 'primary',
            'intent': 'candidate_followup_analysis',
            'icon': 'fa-user-check',
        })
        actions.append({
            'label': f'安排{top_name}面试',
            'payload': f'给{top_name}安排明天下午三点面试',
            'variant': 'warning',
            'intent': 'interview_schedule',
            'requiresConfirmation': True,
            'icon': 'fa-calendar-plus',
            'description': '会进入写入动作二次确认，不会直接创建面试。',
        })
    if second_name:
        actions.append({
            'label': f'复核{second_name}风险',
            'payload': f'第二个人{second_name}有什么风险，下一步怎么推进？',
            'variant': 'secondary',
            'intent': 'workset_followup',
            'icon': 'fa-triangle-exclamation',
        })
    if job_title:
        actions.append({
            'label': '生成结构化面试题',
            'payload': f'基于{job_title}岗位和上面候选人，生成结构化面试题和评分维度',
            'variant': 'secondary',
            'intent': 'interview_question_generation',
            'icon': 'fa-list-check',
        })
    actions.append({
        'label': '查看关联记录',
        'payload': '打开这些候选人的候选人、简历和面试关联记录',
        'variant': 'ghost',
        'intent': 'open_related_records',
        'icon': 'fa-link',
    })
    return W.follow_up_actions(actions, title='推荐下一步')


def _recruitment_sources_widget(
    job: Job,
    candidate_count: int,
    resume_count: int,
    interview_count: int,
    field_citations: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    field_citations = field_citations or {}
    return {
        'type': 'source_citations',
        'title': '本次使用的招聘证据',
        'sources': [
            {
                'module': 'jobs',
                'recordType': 'jobs',
                'recordId': job.id,
                'title': f'岗位：{job.title}',
                'url': f'/job-detail?jobId={job.id}',
                'fields': field_citations.get('jobs') or [],
            },
            {
                'module': 'candidates',
                'recordType': 'candidates',
                'title': f'关联候选人 {candidate_count} 人',
                'url': '/hrm/candidates',
                'fields': field_citations.get('candidates') or [],
            },
            {
                'module': 'resumes',
                'recordType': 'resumes',
                'title': f'关联简历 {resume_count} 份',
                'url': '/resume-manage',
                'fields': field_citations.get('resumes') or [],
            },
            {
                'module': 'interviews',
                'recordType': 'interviews',
                'title': f'关联面试 {interview_count} 场',
                'url': '/interview-manage',
                'fields': field_citations.get('interviews') or [],
            },
        ],
    }


def skill_employee_evidence_bundle(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Assemble an employee's connected HR lifecycle evidence for reasoning."""
    employee_id = args.get('employee_id') or args.get('employeeId')
    keyword = str(args.get('keyword') or '').strip()
    employee = Employee.query.get(employee_id) if employee_id else None
    if not employee and keyword:
        employee = (Employee.query.filter(Employee.name == keyword)
                    .order_by(desc(Employee.created_at)).first())
        if not employee:
            employee = (Employee.query.filter(Employee.name.like(f'%{keyword}%'))
                        .order_by(desc(Employee.created_at)).first())
    if not employee:
        return {'entities': [], 'facts': {}, 'rows_count': 0, 'summary_hint': f'未找到员工“{keyword}”。'}
    safe = desensitize_employee(employee.to_dict(), ctx.role, ctx.user_employee_id)
    candidate_data: Dict[str, Any] = {}
    candidates: List[Candidate] = []
    if employee.candidate_id:
        candidate = Candidate.query.get(employee.candidate_id)
        if candidate:
            candidates.append(candidate)
            candidate_out = skill_candidate_evidence_bundle({'candidate_id': employee.candidate_id}, ctx)
            candidate_data = candidate_out.get('facts') or {}
    if employee.name:
        for candidate in Candidate.query.filter(Candidate.name == employee.name).order_by(desc(Candidate.created_at)).limit(4).all():
            if candidate.id not in {row.id for row in candidates}:
                candidates.append(candidate)
    resume_ids = {row.resume_id for row in candidates if row.resume_id}
    resumes: List[Resume] = []
    if resume_ids:
        resumes.extend(Resume.query.filter(Resume.id.in_(resume_ids)).order_by(desc(Resume.created_at)).limit(6).all())
    if employee.name:
        for resume in Resume.query.filter(Resume.candidate_name == employee.name).order_by(desc(Resume.created_at)).limit(6).all():
            if resume.id not in {row.id for row in resumes}:
                resumes.append(resume)
                resume_ids.add(resume.id)
    offers: List[Offer] = []
    offer_filters = [Offer.employee_id == employee.id]
    if employee.source_offer_id:
        offer_filters.append(Offer.id == employee.source_offer_id)
    candidate_ids = {row.id for row in candidates}
    if candidate_ids:
        offer_filters.append(Offer.candidate_id.in_(candidate_ids))
    if offer_filters:
        seen_offers = set()
        for offer in Offer.query.filter(or_(*offer_filters)).order_by(desc(Offer.created_at)).limit(6).all():
            if offer.id not in seen_offers:
                offers.append(offer)
                seen_offers.add(offer.id)
    interviews: List[Interview] = []
    if resume_ids:
        interviews = Interview.query.filter(Interview.resume_id.in_(resume_ids)).order_by(desc(Interview.scheduled_at)).limit(8).all()
    job_ids = {
        row.job_id
        for row in [*candidates, *resumes, *interviews, *offers]
        if getattr(row, 'job_id', None)
    }
    jobs: List[Job] = []
    if job_ids:
        jobs = Job.query.filter(Job.id.in_(job_ids)).order_by(desc(Job.created_at)).limit(8).all()
    attendance = (AttendanceRecord.query.filter_by(employee_id=employee.id)
                  .order_by(desc(AttendanceRecord.attendance_date)).limit(30).all())
    performance = (PerformanceReview.query.filter_by(employee_id=employee.id)
                   .order_by(desc(PerformanceReview.created_at)).limit(10).all())
    training = (TrainingRecord.query.filter_by(employee_id=employee.id)
                .order_by(desc(TrainingRecord.created_at)).limit(20).all())
    requests = (EmployeeRequest.query.filter_by(employee_id=employee.id)
                .order_by(desc(EmployeeRequest.created_at)).limit(20).all())
    request_ids = [request.id for request in requests]
    request_approvals = []
    if request_ids:
        request_approvals = (ApprovalInstance.query.filter(
            ApprovalInstance.business_type == 'employee_request',
            ApprovalInstance.business_id.in_(request_ids),
        ).order_by(desc(ApprovalInstance.created_at)).limit(20).all())
    onboarding = (OnboardingTask.query.filter_by(employee_id=employee.id)
                  .order_by(desc(OnboardingTask.created_at)).limit(20).all())
    contracts = (Contract.query.filter_by(employee_id=employee.id)
                 .order_by(desc(Contract.created_at)).limit(10).all())
    probations = (Probation.query.filter_by(employee_id=employee.id)
                  .order_by(desc(Probation.created_at)).limit(10).all())
    employee_changes = (EmployeeChange.query.filter_by(employee_id=employee.id)
                        .order_by(desc(EmployeeChange.created_at)).limit(20).all())
    resignations = (Resignation.query.filter_by(employee_id=employee.id)
                    .order_by(desc(Resignation.created_at)).limit(10).all())
    change_ids = [change.id for change in employee_changes]
    change_approvals = []
    if change_ids:
        change_approvals = (ApprovalInstance.query.filter(
            ApprovalInstance.business_type == 'employee_change',
            ApprovalInstance.business_id.in_(change_ids),
        ).order_by(desc(ApprovalInstance.created_at)).limit(20).all())
    notification_like = f'%{employee.name}%'
    notification_filters = [
        Notification.title.like(notification_like),
        Notification.content.like(notification_like),
        Notification.link_url.like(f'%{employee.id}%'),
    ]
    if ctx.role in PRIVILEGED_ROLES or (ctx.role == ROLE_EMPLOYEE and ctx.user_employee_id == employee.id):
        bound_user_ids = [
            row[0]
            for row in User.query.with_entities(User.id).filter(User.employee_id == employee.id).all()
            if row[0]
        ]
        if bound_user_ids:
            notification_filters.append(Notification.user_id.in_(bound_user_ids))
    notifications = (
        Notification.query.filter(or_(*notification_filters))
        .order_by(desc(Notification.created_at)).limit(12).all()
    )
    salary_profile = None
    salary_profiles: List[SalaryProfile] = []
    payroll = []
    if ctx.role in PAYROLL_AUTHORIZED_ROLES:
        salary_profile = SalaryProfile.query.filter_by(employee_id=employee.id).first()
        if salary_profile:
            salary_profiles.append(salary_profile)
        payroll = (PayrollRecord.query.filter_by(employee_id=employee.id)
                   .order_by(desc(PayrollRecord.created_at)).limit(6).all())
    sources = ['employee', 'attendance', 'performance', 'training', 'requests', 'onboarding']
    if candidates:
        sources.append('candidate')
    if resumes:
        sources.append('resume')
    if jobs:
        sources.append('job')
    if interviews:
        sources.append('interview')
    if offers:
        sources.append('offer')
    if contracts:
        sources.append('contract')
    if probations:
        sources.append('probation')
    if resignations:
        sources.append('resignation')
    if request_approvals:
        sources.append('request_approvals')
    if employee_changes:
        sources.append('employee_changes')
    if change_approvals:
        sources.append('change_approvals')
    if notifications:
        sources.append('notifications')
    if salary_profile:
        sources.append('salary_profile')
    if payroll:
        sources.append('payroll')
    latest_attendance = attendance[0].to_dict() if attendance else {}
    abnormal_attendance_count = sum(1 for row in attendance if row.status not in (None, '', 'normal'))
    latest_candidate = candidates[0].to_dict() if candidates else {}
    latest_resume = resumes[0].to_dict() if resumes else {}
    latest_job = jobs[0].to_dict() if jobs else {}
    latest_interview = interviews[0].to_dict() if interviews else {}
    latest_offer = offers[0].to_dict() if offers else {}
    latest_onboarding = onboarding[0].to_dict() if onboarding else {}
    latest_contract = contracts[0].to_dict() if contracts else {}
    latest_performance = performance[0].to_dict() if performance else {}
    latest_training = training[0].to_dict() if training else {}
    latest_request = requests[0].to_dict() if requests else {}
    latest_probation = probations[0].to_dict() if probations else {}
    latest_change = employee_changes[0].to_dict() if employee_changes else {}
    latest_resignation = resignations[0].to_dict() if resignations else {}
    latest_notification = notifications[0].to_dict() if notifications else {}
    salary_profile_facts = salary_profile.to_dict() if salary_profile else None
    payroll_facts = [row.to_dict() for row in payroll]
    latest_payroll = payroll_facts[0] if payroll_facts else {}
    field_citations = {
        'employee': _field_citation_group(
            ('employee.employee_no', '工号', safe.get('employeeNo')),
            ('employee.department', '部门', safe.get('departmentName')),
            ('employee.job_title', '岗位', safe.get('jobTitle')),
            ('employee.status', '员工状态', safe.get('status')),
            ('employee.hire_date', '入职日期', safe.get('hireDate')),
        ),
        'candidate': _field_citation_group(
            ('candidate.count', '候选人记录数', len(candidates) if candidates else None),
            ('candidate.latest_status', '最近候选人状态', latest_candidate.get('status')),
            ('candidate.source', '来源', latest_candidate.get('source')),
        ),
        'resume': _field_citation_group(
            ('resume.count', '简历记录数', len(resumes) if resumes else None),
            ('resume.latest_created_at', '最近简历录入时间', latest_resume.get('createdAt')),
            ('resume.job_id', '应聘岗位ID', latest_resume.get('jobId')),
        ),
        'job': _field_citation_group(
            ('job.count', '关联岗位数', len(jobs) if jobs else None),
            ('job.latest_title', '最近关联岗位', latest_job.get('title')),
            ('job.latest_status', '岗位状态', latest_job.get('status')),
        ),
        'interview': _field_citation_group(
            ('interview.count', '面试记录数', len(interviews) if interviews else None),
            ('interview.latest_scheduled_at', '最近面试时间', latest_interview.get('scheduledAt')),
            ('interview.latest_status', '最近面试状态', latest_interview.get('status')),
        ),
        'offer': _field_citation_group(
            ('offer.count', 'Offer记录数', len(offers) if offers else None),
            ('offer.latest_status', '最近Offer状态', latest_offer.get('status')),
            ('offer.onboarding_date', '入职日期', latest_offer.get('onboardingDate')),
        ),
        'onboarding': _field_citation_group(
            ('onboarding.count', '入职任务数', len(onboarding) if onboarding else None),
            ('onboarding.latest_task', '最近入职任务', latest_onboarding.get('name')),
            ('onboarding.latest_status', '最近任务状态', latest_onboarding.get('status')),
        ),
        'contract': _field_citation_group(
            ('contract.count', '合同记录数', len(contracts) if contracts else None),
            ('contract.latest_no', '最近合同编号', latest_contract.get('contractNo')),
            ('contract.latest_status', '最近合同状态', latest_contract.get('status')),
        ),
        'attendance': _field_citation_group(
            ('attendance.recent_count', '近30条考勤数', len(attendance) if attendance else None),
            ('attendance.abnormal_count', '异常考勤数', abnormal_attendance_count if attendance else None),
            ('attendance.latest_date', '最近考勤日期', latest_attendance.get('attendanceDate')),
            ('attendance.latest_status', '最近考勤状态', latest_attendance.get('status')),
        ),
        'performance': _field_citation_group(
            ('performance.recent_count', '绩效记录数', len(performance) if performance else None),
            ('performance.latest_grade', '最近等级', latest_performance.get('grade')),
            ('performance.latest_score', '最近得分', latest_performance.get('finalScore')),
            ('performance.latest_result', '最近结论', latest_performance.get('result') or latest_performance.get('remark')),
        ),
        'training': _field_citation_group(
            ('training.record_count', '培训记录数', len(training) if training else None),
            ('training.latest_course', '最近课程', latest_training.get('courseName')),
            ('training.latest_status', '最近培训状态', latest_training.get('status')),
            ('training.latest_result', '最近培训结果', latest_training.get('result')),
        ),
        'requests': _field_citation_group(
            ('requests.count', '申请记录数', len(requests) if requests else None),
            ('requests.latest_type', '最近申请类型', latest_request.get('requestType')),
            ('requests.latest_status', '最近申请状态', latest_request.get('status')),
        ),
        'request_approvals': _field_citation_group(
            ('request_approvals.count', '申请审批数', len(request_approvals) if request_approvals else None),
            ('request_approvals.latest_status', '最近审批状态', (request_approvals[0].to_dict() if request_approvals else {}).get('status')),
        ),
        'employee_changes': _field_citation_group(
            ('employee_changes.count', '异动记录数', len(employee_changes) if employee_changes else None),
            ('employee_changes.latest_type', '最近异动类型', latest_change.get('changeType')),
            ('employee_changes.latest_status', '最近异动状态', latest_change.get('status')),
            ('employee_changes.latest_reason', '最近异动原因', latest_change.get('reason')),
        ),
        'change_approvals': _field_citation_group(
            ('change_approvals.count', '异动审批数', len(change_approvals) if change_approvals else None),
            ('change_approvals.latest_status', '最近审批状态', (change_approvals[0].to_dict() if change_approvals else {}).get('status')),
        ),
        'notifications': _field_citation_group(
            ('notifications.count', '相关通知数', len(notifications) if notifications else None),
            ('notifications.latest_title', '最近通知标题', latest_notification.get('title')),
            ('notifications.latest_status', '最近通知状态', latest_notification.get('status')),
        ),
        'salary_profile': _field_citation_group(
            ('salary_profile.status', '薪资档案状态', (salary_profile_facts or {}).get('status')),
            ('salary_profile.total_salary', '薪资合计', (salary_profile_facts or {}).get('totalSalary')),
            ('salary_profile.currency', '币种', (salary_profile_facts or {}).get('currency')),
        ),
        'payroll': _field_citation_group(
            ('payroll.count', '工资单记录数', len(payroll_facts) if payroll_facts else None),
            ('payroll.latest_month', '最近薪资月份', latest_payroll.get('payrollMonth')),
            ('payroll.latest_status', '最近工资单状态', latest_payroll.get('status')),
        ),
        'probation': _field_citation_group(
            ('probation.count', '转正记录数', len(probations) if probations else None),
            ('probation.latest_status', '最近转正状态', latest_probation.get('status')),
            ('probation.latest_result', '最近转正结论', latest_probation.get('result')),
        ),
        'resignation': _field_citation_group(
            ('resignation.count', '离职记录数', len(resignations) if resignations else None),
            ('resignation.latest_status', '最近离职状态', latest_resignation.get('status')),
            ('resignation.latest_reason', '最近离职原因', latest_resignation.get('reason')),
        ),
    }
    facts = {
        'entity_type': 'employee',
        'name': employee.name,
        'employee': {
            'employee_id': employee.id,
            'employee_no': safe.get('employeeNo'),
            'department': safe.get('departmentName'),
            'job_title': safe.get('jobTitle'),
            'status': safe.get('status'),
            'hire_date': safe.get('hireDate'),
            'probation_end_date': safe.get('probationEndDate'),
        },
        'recruitment_origin': candidate_data,
        'candidates': [row.to_dict() for row in candidates],
        'resumes': [row.to_dict() for row in resumes],
        'jobs': [row.to_dict() for row in jobs],
        'interviews': [row.to_dict() for row in interviews],
        'offers': [row.to_dict() for row in offers],
        'contracts': [row.to_dict() for row in contracts],
        'probations': [row.to_dict() for row in probations],
        'resignations': [row.to_dict() for row in resignations],
        'attendance': [row.to_dict() for row in attendance],
        'performance': [row.to_dict() for row in performance],
        'training': [row.to_dict() for row in training],
        'requests': [row.to_dict() for row in requests],
        'request_approvals': [row.to_dict() for row in request_approvals],
        'onboarding_tasks': [row.to_dict() for row in onboarding],
        'employee_changes': [row.to_dict() for row in employee_changes],
        'change_approvals': [row.to_dict() for row in change_approvals],
        'notifications': [row.to_dict() for row in notifications],
        'salary_profile': salary_profile_facts,
        'payroll': payroll_facts,
        'field_citations': {k: v for k, v in field_citations.items() if v},
        'sources': sources,
    }
    entities = _lifecycle_entity_cards(
        employee,
        ctx=ctx,
        candidates=candidates,
        resumes=resumes,
        jobs=jobs,
        interviews=interviews,
        offers=offers,
        onboarding_tasks=onboarding,
        contracts=contracts,
        attendance_records=attendance,
        employee_requests=requests,
        salary_profiles=salary_profiles,
        payroll_records=payroll,
        performance_reviews=performance,
        training_records=training,
        probations=probations,
        employee_changes=employee_changes,
        resignations=resignations,
        approvals=request_approvals + change_approvals,
        notifications=notifications,
    )
    return {
        'entities': entities,
        'facts': facts,
        'rows_count': len(entities),
        'summary_hint': f'已汇集员工 {employee.name} 的跨模块履历证据。',
    }


# ============================================================
# 通用系统证据层：跨模块检索 + WorkSet 分析
# ============================================================
def _generic_card(entity_type: str, entity_id: str, title: str,
                  subtitle: str = '', meta: str = '', url: str = '') -> Dict[str, Any]:
    icon_map = {
        'position': 'fa-id-badge',
        'onboarding_task': 'fa-clipboard-check',
        'probation': 'fa-user-clock',
        'employee_change': 'fa-random',
        'resignation': 'fa-door-open',
        'contract': 'fa-file-contract',
        'attendance': 'fa-calendar-check',
        'employee_request': 'fa-file-alt',
        'approval': 'fa-check-double',
        'performance': 'fa-chart-line',
        'payroll': 'fa-money-bill',
        'training': 'fa-graduation-cap',
        'notification': 'fa-bell',
        'user': 'fa-users-cog',
        'role': 'fa-user-shield',
        'operation_log': 'fa-clipboard-list',
        'setting': 'fa-cog',
        'model_setting': 'fa-brain',
    }
    label_map = {
        'position': '职位',
        'onboarding_task': '入职任务',
        'probation': '试用期',
        'employee_change': '异动',
        'resignation': '离职',
        'contract': '合同',
        'attendance': '考勤',
        'employee_request': '员工申请',
        'approval': '审批',
        'performance': '绩效',
        'payroll': '薪酬',
        'training': '培训',
        'notification': '通知',
        'user': '用户',
        'role': '角色',
        'operation_log': '操作日志',
        'setting': '系统设置',
        'model_setting': 'AI 模型配置',
    }
    return {
        'type': entity_type,
        'typeLabel': label_map.get(entity_type, entity_type),
        'icon': icon_map.get(entity_type, 'fa-database'),
        'id': entity_id,
        'title': title,
        'subtitle': subtitle,
        'meta': meta,
        'url': url,
    }


def _row_facts(entity_type: str, row: Any, fields: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'entity_type': entity_type,
        'entity_id': getattr(row, 'id', None),
        **{k: v for k, v in fields.items() if v not in (None, '', [])},
    }


def _search_text_columns(query, columns: List[Any], keyword: str):
    if not keyword:
        return query
    like = f'%{keyword}%'
    return query.filter(or_(*[col.like(like) for col in columns]))


def skill_system_search(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Search across HRM modules with one bounded read-only skill.

    This is the LLM planner's broad retrieval primitive: when the exact module
    is unclear, it can search current system tables first, then use evidence
    bundle/detail tools for deeper reasoning.
    """
    module = str(args.get('module') or 'all').lower()
    if module in {'module_catalog', 'modules', 'catalog'}:
        return _module_catalog_search(args)

    keyword = str(args.get('keyword') or args.get('query') or '').strip()
    limit = _clamp_limit(args.get('limit'), default=12, hard_max=40)
    role = ctx.role
    entities: List[Dict[str, Any]] = []
    widgets_out: List[Dict[str, Any]] = []
    facts: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    def remember(name: str, card: Dict[str, Any], row_facts: Dict[str, Any]) -> None:
        if len(entities) >= limit:
            return
        entities.append(card)
        facts.append(row_facts)
        counts[name] = counts.get(name, 0) + 1

    def add_candidates() -> None:
        q = Candidate.query.outerjoin(Job, Candidate.job_id == Job.id).outerjoin(Resume, Candidate.resume_id == Resume.id)
        if keyword:
            like = f'%{keyword}%'
            q = q.filter(or_(
                Candidate.name.like(like), Candidate.email.like(like), Candidate.phone.like(like),
                Candidate.status.like(like), Candidate.source.like(like), Candidate.ai_summary.like(like),
                Candidate.ai_recommendation.like(like), Job.title.like(like), Job.department.like(like),
                Resume.candidate_name.like(like),
            ))
        for row in q.order_by(desc(Candidate.created_at)).limit(limit).all():
            remember('候选人', _candidate_card(row), _row_facts('candidate', row, {
                'name': row.name,
                'job_title': row.job.title if row.job else None,
                'status': row.status,
                'source': row.source,
                'created_at': row.created_at.isoformat() if row.created_at else None,
                'resume_id': row.resume_id,
                'job_id': row.job_id,
                'ai_summary': row.ai_summary,
                'ai_recommendation': row.ai_recommendation,
            }))

    def add_resumes() -> None:
        q = Resume.query.outerjoin(Job, Resume.job_id == Job.id)
        if keyword:
            like = f'%{keyword}%'
            q = q.filter(or_(
                Resume.candidate_name.like(like), Resume.email.like(like), Resume.phone.like(like),
                Job.title.like(like), Job.department.like(like), Job.requirements.like(like),
            ))
        for row in q.order_by(desc(Resume.created_at)).limit(limit).all():
            remember('简历', _resume_card(row, role), _row_facts('resume', row, _safe_resume_facts(row, role)))

    def add_jobs() -> None:
        q = Job.query
        q = _search_text_columns(q, [
            Job.title, Job.description, Job.department, Job.level, Job.responsibilities,
            Job.requirements, Job.location, Job.salary_range,
        ], keyword)
        for row in q.order_by(desc(Job.created_at)).limit(limit).all():
            remember('岗位', _job_card(row), _row_facts('job', row, _job_evidence(row)))

    def add_employees() -> None:
        q = Employee.query.outerjoin(Department, Employee.department_id == Department.id).outerjoin(Position, Employee.position_id == Position.id)
        if keyword:
            like = f'%{keyword}%'
            q = q.filter(or_(
                Employee.name.like(like), Employee.employee_no.like(like), Employee.email.like(like),
                Employee.phone.like(like), Employee.job_title.like(like), Employee.status.like(like),
                Department.name.like(like), Position.title.like(like),
            ))
        scope = employee_scope_filter(role, ctx)
        if scope.get('_self_only'):
            q = q.filter(Employee.id == scope['_self_only'])
        if scope.get('_department_id'):
            q = q.filter(Employee.department_id == scope['_department_id'])
        for row in q.order_by(desc(Employee.created_at)).limit(limit).all():
            safe = desensitize_employee(row.to_dict(), role, ctx.user_employee_id)
            remember('员工', _employee_card(row, role, ctx), _row_facts('employee', row, {
                'name': safe.get('name'),
                'employee_no': safe.get('employeeNo'),
                'department': safe.get('departmentName'),
                'position': safe.get('positionTitle'),
                'job_title': safe.get('jobTitle'),
                'status': safe.get('status'),
                'hire_date': safe.get('hireDate'),
                'probation_end_date': safe.get('probationEndDate'),
            }))

    def add_departments_positions() -> None:
        dq = _search_text_columns(Department.query, [Department.name, Department.code, Department.description], keyword)
        for row in dq.order_by(desc(Department.created_at)).limit(max(1, limit // 2)).all():
            remember('部门', _department_card(row), _row_facts('department', row, {
                'name': row.name,
                'code': row.code,
                'status': row.status,
                'manager_id': row.manager_id,
                'manager_name': row.to_dict().get('managerName'),
                'description': row.description,
            }))
        pq = Position.query.outerjoin(Department, Position.department_id == Department.id)
        if keyword:
            like = f'%{keyword}%'
            pq = pq.filter(or_(
                Position.title.like(like), Position.category.like(like), Position.level.like(like),
                Position.responsibilities.like(like), Position.requirements.like(like), Department.name.like(like),
            ))
        for row in pq.order_by(desc(Position.created_at)).limit(max(1, limit // 2)).all():
            remember('职位', _generic_card(
                'position', row.id, row.title, row.department.name if row.department else '',
                f'状态：{row.status or "—"}', '/hrm/positions',
            ), _row_facts('position', row, {
                'title': row.title,
                'category': row.category,
                'department': row.department.name if row.department else None,
                'level': row.level,
                'responsibilities': row.responsibilities,
                'requirements': row.requirements,
                'status': row.status,
            }))

    def add_interviews_offers() -> None:
        iq = Interview.query.outerjoin(Resume, Interview.resume_id == Resume.id).outerjoin(Job, Interview.job_id == Job.id)
        if keyword:
            like = f'%{keyword}%'
            iq = iq.filter(or_(Resume.candidate_name.like(like), Job.title.like(like), Interview.status.like(like), Interview.notes.like(like)))
        for row in iq.order_by(desc(Interview.scheduled_at)).limit(max(1, limit // 2)).all():
            remember('面试', _interview_card(row), _row_facts('interview', row, {
                'candidate_name': row.resume.candidate_name if row.resume else None,
                'job_title': row.job.title if row.job else None,
                'scheduled_at': row.scheduled_at.isoformat() if row.scheduled_at else None,
                'status': row.status,
                'notes': row.notes,
            }))
        oq = Offer.query.outerjoin(Candidate, Offer.candidate_id == Candidate.id).outerjoin(Job, Offer.job_id == Job.id)
        if keyword:
            like = f'%{keyword}%'
            oq = oq.filter(or_(Offer.title.like(like), Offer.status.like(like), Offer.approval_status.like(like), Candidate.name.like(like), Job.title.like(like)))
        for row in oq.order_by(desc(Offer.created_at)).limit(max(1, limit // 2)).all():
            remember('Offer', _offer_card(row), _row_facts('offer', row, {
                'title': row.title,
                'candidate_name': row.candidate.name if row.candidate else None,
                'job_title': row.job.title if row.job else None,
                'status': row.status,
                'approval_status': row.approval_status,
                'onboarding_date': row.onboarding_date.isoformat() if row.onboarding_date else None,
                'work_location': row.work_location,
            }))

    def add_employee_lifecycle() -> None:
        like = f'%{keyword}%' if keyword else None
        tables = [
            ('入职任务', OnboardingTask, 'onboarding_task', '/hrm/onboarding-tasks', [OnboardingTask.name, OnboardingTask.task_type, OnboardingTask.status, OnboardingTask.remark]),
            ('试用期', Probation, 'probation', '/hrm/probations', [Probation.status, Probation.self_review, Probation.manager_review, Probation.result, Probation.remark]),
            ('异动', EmployeeChange, 'employee_change', '/hrm/employee-changes', [EmployeeChange.change_type, EmployeeChange.before_level, EmployeeChange.after_level, EmployeeChange.reason, EmployeeChange.status]),
            ('离职', Resignation, 'resignation', '/hrm/resignations', [Resignation.reason, Resignation.status, Resignation.ai_summary]),
            ('合同', Contract, 'contract', '/hrm/contracts', [Contract.contract_no, Contract.contract_type, Contract.status, Contract.remark]),
            ('员工申请', EmployeeRequest, 'employee_request', '/employee-requests', [EmployeeRequest.request_type, EmployeeRequest.title, EmployeeRequest.reason, EmployeeRequest.status]),
        ]
        for label, model, entity_type, url, columns in tables:
            q = model.query.outerjoin(Employee, model.employee_id == Employee.id)
            if like:
                q = q.filter(or_(Employee.name.like(like), *[col.like(like) for col in columns]))
            for row in q.order_by(desc(getattr(model, 'created_at'))).limit(max(1, limit // 3)).all():
                row_dict = row.to_dict()
                remember(label, _generic_card(
                    entity_type, row.id,
                    row_dict.get('name') or row_dict.get('title') or row_dict.get('employeeName') or label,
                    row_dict.get('employeeName') or row_dict.get('contractType') or row_dict.get('changeType') or '',
                    f'状态：{row_dict.get("status") or "—"}',
                    url,
                ), _row_facts(entity_type, row, row_dict))

    def add_attendance_performance_payroll() -> None:
        like = f'%{keyword}%' if keyword else None
        aq = AttendanceRecord.query.outerjoin(Employee, AttendanceRecord.employee_id == Employee.id)
        if like:
            aq = aq.filter(or_(Employee.name.like(like), AttendanceRecord.status.like(like), AttendanceRecord.source.like(like), AttendanceRecord.remark.like(like)))
        for row in aq.order_by(desc(AttendanceRecord.attendance_date)).limit(max(1, limit // 3)).all():
            d = row.to_dict()
            remember('考勤', _generic_card('attendance', row.id, d.get('employeeName') or '考勤记录', d.get('attendanceDate') or '', f'状态：{d.get("status") or "—"}', '/hrm/attendance-records'), _row_facts('attendance', row, d))

        pq = PerformanceReview.query.outerjoin(Employee, PerformanceReview.employee_id == Employee.id).outerjoin(PerformanceCycle, PerformanceReview.cycle_id == PerformanceCycle.id)
        if like:
            pq = pq.filter(or_(Employee.name.like(like), PerformanceCycle.name.like(like), PerformanceReview.grade.like(like), PerformanceReview.result.like(like), PerformanceReview.status.like(like)))
        for row in pq.order_by(desc(PerformanceReview.created_at)).limit(max(1, limit // 3)).all():
            d = row.to_dict()
            remember('绩效', _generic_card('performance', row.id, d.get('employeeName') or '绩效记录', d.get('cycleName') or '', f'等级：{d.get("grade") or "—"}', '/performance-review'), _row_facts('performance', row, d))

        if role in PAYROLL_AUTHORIZED_ROLES:
            profile_query = SalaryProfile.query.outerjoin(Employee, SalaryProfile.employee_id == Employee.id)
            if like:
                profile_query = profile_query.filter(or_(
                    Employee.name.like(like),
                    SalaryProfile.status.like(like),
                    SalaryProfile.remark.like(like),
                ))
            for row in profile_query.order_by(desc(SalaryProfile.updated_at)).limit(max(1, limit // 3)).all():
                d = row.to_dict()
                remember('薪资档案', _generic_card(
                    'payroll',
                    row.id,
                    d.get('employeeName') or '薪资档案',
                    f'总薪资：{_fmt_amount(d.get("totalSalary"))} 元',
                    f'状态：{d.get("status") or "—"}',
                    '/salary-profiles',
                ), _row_facts('salary_profile', row, d))

            sq = PayrollRecord.query.outerjoin(Employee, PayrollRecord.employee_id == Employee.id)
            if like:
                sq = sq.filter(or_(Employee.name.like(like), PayrollRecord.payroll_month.like(like), PayrollRecord.status.like(like)))
            for row in sq.order_by(desc(PayrollRecord.created_at)).limit(max(1, limit // 3)).all():
                d = row.to_dict()
                remember('薪酬', _generic_card('payroll', row.id, d.get('employeeName') or '薪酬记录', d.get('payrollMonth') or '', f'状态：{d.get("status") or "—"}', '/hrm/payroll-records'), _row_facts('payroll', row, d))

    def add_training_feedback_notifications() -> None:
        like = f'%{keyword}%' if keyword else None
        cq = TrainingCourse.query
        if like:
            cq = cq.filter(or_(TrainingCourse.name.like(like), TrainingCourse.category.like(like), TrainingCourse.lecturer.like(like), TrainingCourse.description.like(like)))
        for row in cq.order_by(desc(TrainingCourse.created_at)).limit(max(1, limit // 4)).all():
            d = row.to_dict()
            remember('培训', _generic_card('training', row.id, row.name, row.category or '', f'状态：{row.status or "—"}', '/hrm/training-courses'), _row_facts('training_course', row, d))
        rq = TrainingRecord.query.outerjoin(Employee, TrainingRecord.employee_id == Employee.id).outerjoin(
            TrainingCourse, TrainingRecord.course_id == TrainingCourse.id
        ).outerjoin(TrainingPlan, TrainingRecord.plan_id == TrainingPlan.id)
        if like:
            rq = rq.filter(or_(
                Employee.name.like(like),
                TrainingRecord.status.like(like),
                TrainingRecord.result.like(like),
                TrainingRecord.feedback.like(like),
                TrainingCourse.name.like(like),
                TrainingPlan.name.like(like),
            ))
        for row in rq.order_by(desc(TrainingRecord.created_at)).limit(max(1, limit // 4)).all():
            d = row.to_dict()
            remember('培训记录', _generic_card(
                'training',
                row.id,
                d.get('employeeName') or '培训记录',
                d.get('courseName') or d.get('planName') or '',
                f'状态：{d.get("status") or "—"}',
                '/hrm/training-records',
            ), _row_facts('training_record', row, d))
        fq = Feedback.query
        if like:
            fq = fq.filter(or_(Feedback.title.like(like), Feedback.content.like(like), Feedback.feedback_type.like(like), Feedback.severity.like(like), Feedback.status.like(like)))
        for row in fq.order_by(desc(Feedback.created_at)).limit(max(1, limit // 4)).all():
            remember('反馈', _feedback_card(row), _row_facts('feedback', row, row.to_dict()))
        nq = Notification.query.filter(or_(Notification.user_id == ctx.user_id, Notification.user_id.is_(None)))
        if like:
            nq = nq.filter(or_(Notification.title.like(like), Notification.content.like(like), Notification.notice_type.like(like), Notification.status.like(like)))
        for row in nq.order_by(desc(Notification.created_at)).limit(max(1, limit // 4)).all():
            d = row.to_dict()
            remember('通知', _generic_card('notification', row.id, row.title, row.notice_type or '', f'状态：{row.status or "—"}', '/notifications'), _row_facts('notification', row, d))

    def add_admin_system() -> None:
        like = f'%{keyword}%' if keyword else None
        setting_rows: List[Any] = []
        if module in ('all', 'users'):
            q = User.query
            if like:
                q = q.filter(or_(User.name.like(like), User.email.like(like), User.role.like(like), User.status.like(like)))
            for row in q.order_by(desc(User.created_at)).limit(max(1, limit // 4)).all():
                d = row.to_dict()
                remember('用户', _generic_card('user', row.id, row.name, row.email or '', f'角色：{row.role or "—"}', '/hrm/users'), _row_facts('user', row, d))
        if module in ('all', 'roles'):
            q = Role.query
            if like:
                q = q.filter(or_(Role.code.like(like), Role.name.like(like), Role.description.like(like), Role.status.like(like)))
            for row in q.order_by(Role.code.asc()).limit(max(1, limit // 4)).all():
                d = row.to_dict()
                remember('角色', _generic_card('role', row.id, row.name, row.code or '', f'状态：{row.status or "—"}', '/hrm/roles'), _row_facts('role', row, d))
        if module in ('all', 'operation_logs'):
            q = OperationLog.query
            if like:
                q = q.filter(or_(OperationLog.module.like(like), OperationLog.action.like(like), OperationLog.target_id.like(like)))
            for row in q.order_by(desc(OperationLog.created_at)).limit(max(1, limit // 4)).all():
                d = row.to_dict()
                remember('操作日志', _generic_card('operation_log', row.id, row.action or '操作日志', row.module or '', row.target_id or '', '/operation-logs'), _row_facts('operation_log', row, d))
        if module in ('all', 'settings', 'model_settings'):
            q = Setting.query
            if module == 'model_settings':
                q = q.filter(Setting.key == ASSISTANT_MODEL_SETTINGS_KEY)
            elif like:
                q = q.filter(Setting.key.like(like))
            setting_rows = q.limit(max(1, limit // 4)).all()
            for row in setting_rows:
                d = row.to_dict()
                key_text = row.key or ''
                is_model_setting = key_text == ASSISTANT_MODEL_SETTINGS_KEY
                entity_type = 'model_setting' if is_model_setting else 'setting'
                label = 'AI 模型配置' if entity_type == 'model_setting' else '系统设置'
                url = '/ai-model-settings' if entity_type == 'model_setting' else '/system-settings'
                remember(label, _generic_card(entity_type, row.key, row.key, '', '配置项', url), _row_facts(entity_type, row, {
                    **d,
                    'key': row.key,
                    'entry': url,
                }))
            if setting_rows and module in ('settings', 'model_settings'):
                columns = [
                    {'key': 'key', 'label': '配置键'},
                    {'key': 'category', 'label': '类型'},
                    {'key': 'entry', 'label': '入口'},
                ]
                table_rows = []
                sources = []
                for row in setting_rows[:MAX_LIMIT]:
                    key_text = row.key or ''
                    is_model = key_text == ASSISTANT_MODEL_SETTINGS_KEY
                    entry = '/ai-model-settings' if is_model else '/system-settings'
                    category = 'AI 模型配置' if is_model else '系统设置'
                    table_rows.append({'key': key_text, 'category': category, 'entry': entry})
                    sources.append({
                        'module': 'system_settings',
                        'recordType': 'model_setting' if is_model else 'setting',
                        'recordId': key_text,
                        'title': key_text,
                        'url': entry,
                    })
                widgets_out.append(W.data_table(columns, table_rows, title='系统设置配置项', exportable=False))
                widgets_out.append({
                    'type': 'source_citations',
                    'title': '设置来源',
                    'sources': sources,
                })

    dispatch = {
        'candidate': [add_candidates], 'candidates': [add_candidates],
        'resume': [add_resumes], 'resumes': [add_resumes],
        'job': [add_jobs], 'jobs': [add_jobs],
        'employee': [add_employees], 'employees': [add_employees],
        'organization': [add_departments_positions], 'department': [add_departments_positions], 'position': [add_departments_positions],
        'recruitment': [add_candidates, add_resumes, add_jobs, add_interviews_offers],
        'interview': [add_interviews_offers], 'offer': [add_interviews_offers],
        'lifecycle': [add_employee_lifecycle],
        'attendance': [add_attendance_performance_payroll],
        'performance': [add_attendance_performance_payroll],
        'payroll': [add_attendance_performance_payroll],
        'training': [add_training_feedback_notifications],
        'feedback': [add_training_feedback_notifications],
        'notifications': [add_training_feedback_notifications],
        'users': [add_admin_system],
        'roles': [add_admin_system],
        'operation_logs': [add_admin_system],
        'settings': [add_admin_system],
        'model_settings': [add_admin_system],
        'all': [
            add_candidates, add_resumes, add_jobs, add_employees,
            add_departments_positions, add_interviews_offers,
            add_employee_lifecycle, add_attendance_performance_payroll,
            add_training_feedback_notifications, add_admin_system,
        ],
    }
    for fn in dispatch.get(module, dispatch['all']):
        if len(entities) >= limit:
            break
        try:
            fn()
        except Exception:
            logger.exception('system_search_%s_failed', getattr(fn, '__name__', 'unknown'))

    subject_prefix = f'{keyword}：' if keyword else ''
    module_summary = '、'.join(f'{k}{v}条' for k, v in counts.items())
    if module in ('settings', 'model_settings') and facts:
        setting_keys = [
            str(item.get('entity_id') or item.get('key') or '').strip()
            for item in facts
            if isinstance(item, dict)
        ]
        setting_keys = [item for item in setting_keys if item][:5]
        if setting_keys:
            module_summary = f'{module_summary}（配置键：{"、".join(setting_keys)}）'
    summary = (
        f'{subject_prefix}系统检索命中 {len(entities)} 条：{module_summary}'
        if entities else f'系统内未找到与“{keyword or module}”匹配的记录。'
    )
    return {
        'entities': entities,
        'widgets': widgets_out,
        'facts': {'keyword': keyword, 'module': module, 'results': facts, 'module_counts': counts},
        'rows_count': len(entities),
        'summary_hint': summary,
    }


def _module_catalog_search(args: Dict[str, Any]) -> Dict[str, Any]:
    view = str(args.get('view') or 'overview').lower()
    module_id = str(args.get('module_id') or args.get('moduleId') or '').strip()
    flow_id = str(args.get('flow_id') or args.get('flowId') or '').strip()

    if view == 'module' and module_id:
        payload = module_catalog_detail_for_assistant(module_id)
        if payload:
            module = payload['module']
            return {
                'entities': [_generic_card(
                    'hrm_module',
                    module['id'],
                    module['label'],
                    module['group'],
                    '模块连通性',
                    module['path'],
                )],
                'facts': {
                    'module': 'module_catalog',
                    'view': 'module',
                    'moduleId': module['id'],
                    'catalogModule': payload['module'],
                    'flows': payload['flows'],
                },
                'rows_count': 1,
                'summary_hint': payload['summary'],
            }
    elif view == 'flow' and flow_id:
        payload = module_catalog_flow_for_assistant(flow_id)
        if payload:
            return {
                'entities': [
                    _generic_card('hrm_module', module['id'], module['label'], module['group'], '业务链路节点', module['path'])
                    for module in payload['modules']
                ],
                'facts': {
                    'module': 'module_catalog',
                    'view': 'flow',
                    'flowId': flow_id,
                    'flow': payload['flow'],
                    'modules': payload['modules'],
                },
                'rows_count': payload['moduleCount'],
                'summary_hint': payload['summary'],
            }

    payload = module_catalog_overview_for_assistant()
    return {
        'entities': [
            _generic_card('hrm_module', module['id'], module['label'], module['group'], 'HRM 模块', module['path'])
            for module in payload['modules']
        ],
        'facts': {
            'module': 'module_catalog',
            'view': 'overview',
            'moduleCount': payload['moduleCount'],
            'flows': payload['flows'],
            'benchmarks': payload['benchmarks'],
        },
        'rows_count': payload['moduleCount'],
        'summary_hint': payload['summary'],
    }


def _flatten_facts(value: Any, prefix: str = '', out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if out is None:
        out = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_key = f'{prefix}.{key}' if prefix else str(key)
            _flatten_facts(child, child_key, out)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:8]):
            child_key = f'{prefix}.{idx}' if prefix else str(idx)
            _flatten_facts(child, child_key, out)
    elif value not in (None, ''):
        out[prefix] = value
    return out


def _number_from_value(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or '').strip()
    if not text:
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _age_from_value(key: str, value: Any) -> Optional[float]:
    key_l = key.lower()
    text = str(value or '').strip()
    if re.search(r'(age|年龄|年纪)', key_l):
        return _number_from_value(value)
    if re.search(r'(birth|birthday|出生)', key_l):
        year = None
        m = re.search(r'(19\d{2}|20\d{2})', text)
        if m:
            year = int(m.group(1))
        if year:
            return float(max(0, business_now().year - year))
    m = re.search(r'(\d{1,2})\s*岁', text)
    return float(m.group(1)) if m else None


def _infer_metric(question: str) -> Dict[str, Any]:
    text = question or ''
    if re.search(r'(年龄|年纪|岁|出生|年轻|年长)', text):
        return {'id': 'age', 'label': '年龄', 'order': 'asc', 'aliases': ['age', '年龄', '年纪', 'birth', 'birthday', '出生']}
    if re.search(r'(评分|分数|得分|score|最高分|最低分)', text, re.I):
        order = 'asc' if re.search(r'(最低|最差|低分)', text) else 'desc'
        return {'id': 'score', 'label': '评分', 'order': order, 'aliases': ['score', '评分', '分数', '得分', 'selfScore', 'managerScore', 'finalScore']}
    if re.search(r'(匹配|match|适配)', text, re.I):
        order = 'asc' if re.search(r'(最低|最弱|最不)', text) else 'desc'
        return {'id': 'match', 'label': '匹配度', 'order': order, 'aliases': ['match', 'match_degree', 'matchDegree', '匹配']}
    if re.search(r'(经验|年限|资历|工龄)', text):
        order = 'asc' if re.search(r'(最少|最短|最浅)', text) else 'desc'
        return {'id': 'experience', 'label': '经验年限', 'order': order, 'aliases': ['experience', '工作年限', '年限', '工龄']}
    if re.search(r'(最近|最早|时间|日期|投递|创建|入职|面试)', text):
        order = 'asc' if re.search(r'(最早|最久|最先)', text) else 'desc'
        return {'id': 'date', 'label': '时间', 'order': order, 'aliases': ['created_at', 'createdAt', 'updated_at', 'scheduled_at', 'hire_date', 'date', '时间', '日期']}
    if re.search(r'(学历|教育)', text):
        return {'id': 'education', 'label': '学历', 'order': 'desc', 'aliases': ['education', '学历']}
    return {'id': 'generic', 'label': '可比指标', 'order': 'desc', 'aliases': []}


def _metric_value(flat: Dict[str, Any], metric: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if metric['id'] == 'age':
        for key, value in flat.items():
            age = _age_from_value(key, value)
            if age is not None:
                return {'value': age, 'display': f'{age:g}岁', 'field': key}
        return None
    aliases = [a.lower() for a in metric.get('aliases') or []]
    for key, value in flat.items():
        key_l = key.lower()
        leaf = key_l.rsplit('.', 1)[-1]
        compact_leaf = leaf.replace('_', '').replace('-', '')
        compact_key = key_l.replace('_', '').replace('-', '')
        if aliases:
            compact_aliases = [alias.replace('_', '').replace('-', '') for alias in aliases]
            if metric['id'] in ('match', 'score'):
                if not any(alias == compact_leaf or alias in leaf for alias in compact_aliases):
                    continue
            elif not any(alias in compact_key for alias in compact_aliases):
                continue
        if metric['id'] == 'date':
            text = str(value)
            ts = None
            try:
                ts = datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
            except Exception:
                pass
            if ts is not None:
                return {'value': ts, 'display': text[:16].replace('T', ' '), 'field': key}
        number = _number_from_value(value)
        if number is not None:
            suffix = '%' if metric['id'] == 'match' else ''
            return {'value': number, 'display': f'{number:g}{suffix}', 'field': key}
        if metric['id'] == 'education':
            rank_map = {'博士': 6, '硕士': 5, '研究生': 5, '本科': 4, '大专': 3, '专科': 3, '高中': 2, '中专': 2}
            text = str(value)
            for label, rank in rank_map.items():
                if label in text:
                    return {'value': float(rank), 'display': text, 'field': key}
    return None


def _available_metrics(flattened: List[Dict[str, Any]]) -> List[str]:
    joined_keys = ' '.join(' '.join(row.keys()).lower() for row in flattened)
    labels = []
    for metric in [
        {'label': '评分', 'aliases': ['score', '评分']},
        {'label': '匹配度', 'aliases': ['match', '匹配']},
        {'label': '经验年限', 'aliases': ['experience', '年限', '工龄']},
        {'label': '学历', 'aliases': ['education', '学历']},
        {'label': '状态', 'aliases': ['status', '状态']},
        {'label': '时间', 'aliases': ['created_at', 'createdat', 'scheduled_at', 'hire_date', 'date']},
        {'label': '部门/岗位', 'aliases': ['department', 'job_title', 'position', 'title']},
    ]:
        if any(alias in joined_keys for alias in metric['aliases']):
            labels.append(metric['label'])
    return labels[:8]


def _workset_item_details(item: Dict[str, Any], ctx) -> Dict[str, Any]:
    entity_type = item.get('entity_type')
    entity_id = item.get('entity_id')
    data: Dict[str, Any] = {}
    if entity_type == 'candidate':
        data = skill_candidate_evidence_bundle({'candidate_id': entity_id}, ctx).get('facts') or {}
    elif entity_type == 'resume':
        data = skill_candidate_evidence_bundle({'resume_id': entity_id}, ctx).get('facts') or {}
    elif entity_type == 'employee':
        data = skill_employee_evidence_bundle({'employee_id': entity_id}, ctx).get('facts') or {}
    elif entity_type == 'job':
        data = skill_job_get_detail({'job_id': entity_id}, ctx).get('facts') or {}
    if not data:
        data = {
            'entity_type': entity_type,
            'entity_id': entity_id,
            'name': item.get('title'),
            'title': item.get('title'),
            'subtitle': item.get('subtitle'),
            **(item.get('display_fields') if isinstance(item.get('display_fields'), dict) else {}),
        }
    return data


def _workset_follow_up_actions(
    items: List[Dict[str, Any]],
    details: List[Dict[str, Any]],
    question: str,
) -> Optional[Dict[str, Any]]:
    target_item = items[0] if items else {}
    target_detail = details[0] if details else {}
    if not target_item:
        return None
    entity_type = str(target_item.get('entity_type') or target_detail.get('entity_type') or '')
    name = (
        target_detail.get('name')
        or target_detail.get('candidate_name')
        or target_detail.get('title')
        or target_item.get('title')
        or ''
    )
    name = str(name or '').strip()
    if entity_type not in {'candidate', 'resume'} and not any(word in (question or '') for word in ('候选', '简历', '面试')):
        return None
    label_name = name or '这位候选人'
    actions = [
        {
            'label': '生成面试题',
            'payload': f'基于{label_name}的简历、面试记录和风险点生成结构化面试题',
            'variant': 'primary',
            'intent': 'interview_question_generation',
            'icon': 'fa-list-check',
        },
        {
            'label': '安排面试',
            'payload': f'给{label_name}安排明天下午三点面试',
            'variant': 'warning',
            'intent': 'interview_schedule',
            'requiresConfirmation': True,
            'icon': 'fa-calendar-plus',
            'description': '会进入写入动作二次确认，不会直接创建面试。',
        },
        {
            'label': '查看证据',
            'payload': f'汇总{label_name}的候选人、简历、面试和岗位证据',
            'variant': 'secondary',
            'intent': 'candidate_evidence_bundle',
            'icon': 'fa-link',
        },
    ]
    return W.follow_up_actions(actions, title='针对当前对象的下一步')


def skill_workset_analyze(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Analyze the latest WorkSet using generic field extraction.

    It supports arbitrary follow-up questions over the previous result set:
    highest score, earliest date, youngest person when age exists, status
    comparison, and so on. Missing fields are reported explicitly instead of
    falling back to an unrelated global search.
    """
    question = str(args.get('question') or args.get('query') or '').strip()
    entity_type = args.get('entity_type') or args.get('entityType')
    resolved = None
    try:
        from . import workset_store

        resolved = workset_store.resolve_mention(question or '这些结果', ctx.session_id)
        ws = (resolved or {}).get('workset') or workset_store.get_latest_workset(ctx.session_id, entity_type)
    except Exception:
        ws = None
    if not ws:
        return {
            'entities': [],
            'facts': {'direct_answer': '没有可分析的上轮结果集。请先查询一组对象，再继续追问。'},
            'rows_count': 0,
            'summary_hint': '没有可分析的上轮结果集。请先查询一组对象，再继续追问。',
        }

    if isinstance(resolved, dict) and resolved.get('kind') == 'item' and isinstance(resolved.get('item'), dict):
        items = [resolved['item']]
    else:
        items = list((ws.get('items') or [])[:_clamp_limit(args.get('limit'), default=20, hard_max=40)])
    details = [_workset_item_details(item, ctx) for item in items]
    follow_actions = _workset_follow_up_actions(items, details, question)
    flattened = [_flatten_facts(detail) for detail in details]
    metric = _infer_metric(question)
    ranked = []
    for item, detail, flat in zip(items, details, flattened):
        hit = _metric_value(flat, metric)
        if hit is None:
            continue
        ranked.append({'item': item, 'detail': detail, **hit})

    entities = []
    for item in items:
        if item.get('entity_type') == 'candidate':
            candidate = Candidate.query.get(item.get('entity_id'))
            if candidate:
                entities.append(_candidate_card(candidate))
        elif item.get('entity_type') == 'resume':
            resume = Resume.query.get(item.get('entity_id'))
            if resume:
                entities.append(_resume_card(resume, ctx.role))
        elif item.get('entity_type') == 'employee':
            employee = Employee.query.get(item.get('entity_id'))
            if employee:
                entities.append(_employee_card(employee, ctx.role, ctx))
        elif item.get('entity_type') == 'job':
            job = Job.query.get(item.get('entity_id'))
            if job:
                entities.append(_job_card(job))

    if not ranked:
        available = _available_metrics(flattened)
        label = metric['label']
        answer = (
            f'上轮结果集中没有可比较的“{label}”字段。'
            f'我已读取 {len(items)} 条记录；当前可比较的信息包括：{"、".join(available) if available else "名称、状态、岗位/摘要等基础信息"}。'
        )
        return {
            'entities': entities,
            'widgets': [follow_actions] if follow_actions else [],
            'facts': {
                'workset': ws,
                'question': question,
                'metric': metric,
                'details': details,
                'available_metrics': available,
                'direct_answer': answer,
            },
            'rows_count': len(items),
            'summary_hint': answer,
        }

    reverse = metric.get('order') != 'asc'
    ranked.sort(key=lambda row: row['value'], reverse=reverse)
    best = ranked[0]
    name = (
        best['detail'].get('name')
        or best['detail'].get('candidate_name')
        or best['item'].get('title')
        or '目标对象'
    )
    direction = '最高' if reverse else '最低/最小'
    if metric['id'] == 'age' and not reverse:
        direction = '最小'
    answer = (
        f'按“{metric["label"]}”比较，{direction}的是 {name}，'
        f'字段值为 {best["display"]}（来源字段：{best["field"]}）。'
    )
    return {
        'entities': entities,
        'widgets': [follow_actions] if follow_actions else [],
        'facts': {
            'workset': ws,
            'question': question,
            'metric': metric,
            'details': details,
            'ranked': [
                {
                    'name': row['detail'].get('name') or row['detail'].get('candidate_name') or row['item'].get('title'),
                    'value': row['value'],
                    'display': row['display'],
                    'field': row['field'],
                    'entity_id': row['item'].get('entity_id'),
                    'entity_type': row['item'].get('entity_type'),
                }
                for row in ranked[:10]
            ],
            'direct_answer': answer,
        },
        'rows_count': len(ranked),
        'summary_hint': answer,
    }


def skill_smart_data_query(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Execute a validated read-only SQL query for open-ended analytics.

    This is the assistant's intelligent data fallback. Fixed business skills
    remain preferred; when they cannot cover a question, the planner may pass a
    model-generated SELECT here. The handler validates the SQL again, appends a
    bounded LIMIT, executes through SQLAlchemy, and redacts row fields by role.
    """
    question = str(args.get('question') or args.get('query') or '').strip()
    sql = args.get('sql') or args.get('candidate_sql') or args.get('candidateSql')
    explanation = str(args.get('explanation') or args.get('query_plan') or args.get('queryPlan') or '').strip()
    limit = _clamp_limit(args.get('limit'), default=50, hard_max=200)
    return execute_smart_sql(
        question=question,
        sql=str(sql).strip() if sql else None,
        explanation=explanation,
        ctx=ctx,
        limit=limit,
    )


def skill_interview_create(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Create a confirmed interview schedule from an assistant action plan."""
    resume_id = args.get('resume_id') or args.get('resumeId')
    job_id = args.get('job_id') or args.get('jobId')
    raw_time = args.get('scheduled_at') or args.get('scheduledAt')
    if not resume_id or not job_id or not raw_time:
        raise ValueError('interview_create requires resume_id, job_id and scheduled_at')
    scheduled_at = parse_business_datetime(raw_time)
    resume = Resume.query.get(resume_id)
    job = Job.query.get(job_id)
    if not resume or not job:
        raise ValueError('linked resume or job not found')
    existing = Interview.query.filter_by(
        resume_id=resume_id,
        job_id=job_id,
        scheduled_at=scheduled_at,
    ).first()
    if existing:
        return {
            'entities': [_interview_card(existing)],
            'facts': {'interview_id': existing.id, 'created': False},
            'rows_count': 1,
            'summary_hint': f'{resume.candidate_name} 在 {scheduled_at.strftime("%Y-%m-%d %H:%M")} 的面试安排已存在，未重复创建。',
        }
    interview = Interview(
        id=str(uuid.uuid4()),
        resume_id=resume_id,
        job_id=job_id,
        scheduled_at=scheduled_at,
        status='scheduled',
        notes=args.get('notes') or '由聘小犀在对话确认后创建',
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    db.session.add(interview)
    db.session.commit()
    return {
        'entities': [_interview_card(interview)],
        'facts': {'interview_id': interview.id, 'created': True},
        'rows_count': 1,
        'summary_hint': f'已为 {resume.candidate_name} 创建 {scheduled_at.strftime("%Y-%m-%d %H:%M")} 的面试安排。',
    }


def skill_followup_task_create(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Create a confirmed personal follow-up reminder in notifications."""
    title = str(args.get('title') or 'AI 助手跟进任务').strip()
    content = str(args.get('content') or '').strip() or '请按计划完成跟进。'
    notification = Notification(
        id=str(uuid.uuid4()),
        user_id=ctx.user_id,
        title=title,
        content=content,
        notice_type='assistant_task',
        status='unread',
        link_url='/notifications',
    )
    db.session.add(notification)
    db.session.commit()
    return {
        'entities': [],
        'facts': {'notification_id': notification.id, 'created': True},
        'rows_count': 1,
        'summary_hint': f'已创建跟进提醒：{title}。',
    }


def skill_notification_create(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Create one confirmed in-system notification."""
    title = str(args.get('title') or 'AI 助手通知').strip()[:200]
    content = str(args.get('content') or '').strip() or '请查看相关 HRM 事项。'
    notice_type = str(args.get('notice_type') or args.get('noticeType') or 'hr').strip()[:60] or 'hr'
    link_url = str(args.get('link_url') or args.get('linkUrl') or '/notifications').strip()[:500] or '/notifications'
    user_id = str(args.get('user_id') or args.get('userId') or '').strip() or None
    if user_id and not User.query.get(user_id):
        user_id = None
    notification = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        content=content,
        notice_type=notice_type,
        status='unread',
        link_url=link_url,
    )
    db.session.add(notification)
    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=getattr(ctx, 'user_id', None),
        module='notifications',
        action='ai_confirm_create',
        target_id=notification.id,
        detail={
            'source': 'assistant_confirmed_action',
            'requestId': getattr(ctx, 'request_id', None),
            'sessionId': getattr(ctx, 'session_id', None),
            'title': notification.title,
            'noticeType': notification.notice_type,
            'linkUrl': notification.link_url,
        },
    ))
    db.session.commit()
    return {
        'entities': [_generic_card(
            'notification',
            notification.id,
            notification.title,
            notification.notice_type or '',
            f'状态：{notification.status or "—"}',
            notification.link_url or '/notifications',
        )],
        'facts': {
            'notification_id': notification.id,
            'created': True,
            'user_id': notification.user_id,
            'title': notification.title,
        },
        'rows_count': 1,
        'summary_hint': f'已创建通知：{title}。',
    }


def skill_render_document(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    """Placeholder for future document rendering."""
    title = args.get('title') or 'AI 生成文档'
    return {
        'entities': [],
        'widgets': [W.warning(f'{title} 暂未启用下载渲染，可先复制 markdown 内容使用。', level='info')],
        'rows_count': 0,
        'summary_hint': '文档渲染暂未实现。',
        'not_implemented': True,
    }


class _DefaultDict(dict):
    def __missing__(self, key):
        return f'{{{key}}}'
