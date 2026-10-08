"""Ephemeral approval fixtures for real Copilot confirmation-flow tests."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict

from models import (
    ApprovalInstance, AttendanceRecord, Candidate, Department, Employee,
    EmployeeRequest, Job, PerformanceCycle, PerformanceReview, Position,
    Resume, SalaryProfile, User, db,
)
from services.business_time import business_now


def _tenant_fixture_suffix(tenant_id: str) -> str:
    return hashlib.sha1(str(tenant_id).encode('utf-8')).hexdigest()[:10]


def _scoped_fixture_id(base: str, tenant_id: str) -> str:
    return f'{base}-{_tenant_fixture_suffix(tenant_id)}'


def ensure_attendance_notification_confirmation_case(
    *,
    user_id: str,
    tenant_id: str,
    request_id: str,
) -> Dict[str, str]:
    """Seed isolated current-month late records for the notification flow."""
    tenant_suffix = _tenant_fixture_suffix(tenant_id)
    request_suffix = hashlib.sha1(request_id.encode('utf-8')).hexdigest()[:8]
    dept_id = _scoped_fixture_id('eval-dept-att', tenant_id)
    dept = Department.query.get(dept_id)
    if not dept:
        dept = Department(
            id=dept_id,
            tenant_id=tenant_id,
            name='AI考勤评估部',
            code=f'AI-ATT-{tenant_suffix}',
            status='active',
        )
        db.session.add(dept)

    today = business_now().date()
    for index in range(1, 6):
        employee_id = f'eval-late-{tenant_suffix[:6]}-{request_suffix}-{index}'
        employee = Employee.query.get(employee_id)
        if not employee:
            employee = Employee(
                id=employee_id,
                tenant_id=tenant_id,
                employee_no=f'EL{tenant_suffix[:4]}{request_suffix[:4]}{index:02d}',
                name=f'AI考勤评估员工{index}',
                status='active',
                department_id=dept_id,
                job_title='测试工程师',
            )
            db.session.add(employee)
        for occurrence in range(1, 7 - index):
            record_id = f'eval-at-{tenant_suffix[:5]}-{request_suffix}-{index}-{occurrence}'
            if AttendanceRecord.query.get(record_id):
                continue
            db.session.add(AttendanceRecord(
                id=record_id,
                tenant_id=tenant_id,
                employee_id=employee_id,
                attendance_date=date(today.year, today.month, occurrence),
                status='late',
                source='evaluation_fixture',
                remark='Copilot 考勤提醒确认流评估临时数据',
                created_by=user_id,
            ))
    db.session.commit()
    return {'department_id': dept_id}


def ensure_interview_confirmation_case(
    *,
    user_id: str,
    tenant_id: str,
    request_id: str,
) -> Dict[str, str]:
    """Seed a tenant-local ranked candidate pool for the interview flow."""
    tenant_suffix = _tenant_fixture_suffix(tenant_id)
    request_suffix = hashlib.sha1(request_id.encode('utf-8')).hexdigest()[:8]
    job_id = _scoped_fixture_id('eval-job-elect', tenant_id)
    job = Job.query.get(job_id)
    if not job:
        job = Job(
            id=job_id,
            tenant_id=tenant_id,
            title='电子工程师',
            department='研发部',
            status='open',
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(job)

    names_and_scores = [('邓浩', 94), ('杨琳', 89), ('罗伟', 82)]
    second_resume_id = ''
    for index, (name, score) in enumerate(names_and_scores, start=1):
        resume_id = f'eval-r-{tenant_suffix[:5]}-{request_suffix}-{index}'
        candidate_id = f'eval-c-{tenant_suffix[:5]}-{request_suffix}-{index}'
        if index == 2:
            second_resume_id = resume_id
        if not Resume.query.get(resume_id):
            db.session.add(Resume(
                id=resume_id,
                tenant_id=tenant_id,
                job_id=job_id,
                candidate_name=name,
                email=f'eval-{request_suffix}-{index}@example.invalid',
                file_url=f'/uploads/evaluation/{resume_id}.pdf',
                ai_analysis={
                    'score': score,
                    'matchDegree': score,
                    'skills': ['电子设计', '硬件调试'],
                    'summary': f'{name} 的隔离评估简历',
                    'recommendation': '建议进入面试',
                },
                created_by=user_id,
                updated_by=user_id,
            ))
        if not Candidate.query.get(candidate_id):
            db.session.add(Candidate(
                id=candidate_id,
                tenant_id=tenant_id,
                resume_id=resume_id,
                job_id=job_id,
                name=name,
                status='screening',
                source='evaluation_fixture',
                match_records=[{'score': score, 'matchDegree': score}],
                ai_summary=f'{name} 的隔离评估候选人',
                ai_recommendation='建议进入面试',
                owner_id=user_id,
            ))
    db.session.commit()
    return {'job_id': job_id, 'second_resume_id': second_resume_id}


def ensure_approval_confirmation_case(*, user_id: str, tenant_id: str, request_id: str) -> Dict[str, str]:
    suffix = hashlib.sha1(request_id.encode('utf-8')).hexdigest()[:12]
    dept_id = _scoped_fixture_id('eval-dept-copilot', tenant_id)
    employee_id = f'eval-emp-{_tenant_fixture_suffix(tenant_id)}-{suffix}'
    request_row_id = f'eval-req-{_tenant_fixture_suffix(tenant_id)}-{suffix}'
    approval_id = f'eval-ap-{_tenant_fixture_suffix(tenant_id)}-{suffix}'

    user = User.query.get(user_id)
    dept = Department.query.get(dept_id)
    if not dept:
        dept = Department(id=dept_id, tenant_id=tenant_id, name='AI评估部', code=f'AI-EVAL-{_tenant_fixture_suffix(tenant_id)}', status='active')
        db.session.add(dept)

    employee = Employee.query.get(employee_id)
    if not employee:
        employee = Employee(
            id=employee_id,
            tenant_id=tenant_id,
            employee_no=f'EVAL{abs(hash(employee_id)) % 100000:05d}',
            name=f'AI审批评估员工{suffix[-4:]}',
            status='active',
            department_id=dept_id,
            job_title='测试工程师',
        )
        db.session.add(employee)

    request_row = EmployeeRequest.query.get(request_row_id)
    if not request_row:
        start = datetime.utcnow() + timedelta(days=2)
        request_row = EmployeeRequest(
            id=request_row_id,
            tenant_id=tenant_id,
            employee_id=employee_id,
            request_type='leave',
            title=f'AI确认流请假申请 {suffix[-8:]}',
            start_time=start,
            end_time=start + timedelta(hours=8),
            duration_hours=8,
            reason='Copilot 审批确认流评估临时数据',
            status='pending',
            created_by=user_id,
        )
        db.session.add(request_row)

    approval = ApprovalInstance.query.get(approval_id)
    if not approval:
        approval = ApprovalInstance(
            id=approval_id,
            tenant_id=tenant_id,
            business_type='employee_request',
            business_id=request_row_id,
            title=f'AI确认流审批 {suffix[-8:]}',
            applicant_id=user_id,
            approver_id=user_id,
            status='pending',
            submitted_at=datetime.utcnow(),
            remark='Copilot 评估临时审批，确认后应同步员工申请与操作审计。',
        )
        db.session.add(approval)
        db.session.flush()

    request_row.approval_id = approval_id
    request_row.status = 'pending'
    approval.status = 'pending'
    approval.completed_at = None
    approval.approver_id = user_id
    if user and not user.employee_id:
        user.employee_id = employee_id
    db.session.commit()
    return {
        'employee_id': employee_id,
        'department_id': dept_id,
        'request_id': request_row_id,
        'approval_id': approval_id,
    }


def ensure_employee_change_confirmation_case(*, user_id: str, tenant_id: str, request_id: str) -> Dict[str, str]:
    suffix = hashlib.sha1(request_id.encode('utf-8')).hexdigest()[:12]
    tenant_suffix = _tenant_fixture_suffix(tenant_id)
    source_dept_id = _scoped_fixture_id('eval-dept-change-source', tenant_id)
    target_dept_id = _scoped_fixture_id('eval-dept-change-target', tenant_id)
    source_position_id = _scoped_fixture_id('eval-pos-change-source', tenant_id)
    target_position_id = _scoped_fixture_id('eval-pos-change-target', tenant_id)
    employee_id = f'eval-change-emp-{tenant_suffix}-{suffix}'

    source_dept = Department.query.get(source_dept_id)
    if not source_dept:
        source_dept = Department(id=source_dept_id, tenant_id=tenant_id, name='AI异动评估原部门', code=f'AI-CHG-SRC-{tenant_suffix}', status='active')
        db.session.add(source_dept)
    target_dept = Department.query.get(target_dept_id)
    if not target_dept:
        target_dept = Department(id=target_dept_id, tenant_id=tenant_id, name='研发部', code=f'RD-EVAL-{tenant_suffix}', status='active')
        db.session.add(target_dept)

    source_position = Position.query.get(source_position_id)
    if not source_position:
        source_position = Position(
            id=source_position_id,
            tenant_id=tenant_id,
            title='供应链主管',
            department_id=source_dept_id,
            level='M2',
            status='active',
        )
        db.session.add(source_position)
    target_position = Position.query.get(target_position_id)
    if not target_position:
        target_position = Position(
            id=target_position_id,
            tenant_id=tenant_id,
            title='后端工程师',
            department_id=target_dept_id,
            level='P5',
            status='active',
        )
        db.session.add(target_position)

    employee = Employee.query.get(employee_id)
    if not employee:
        employee = Employee(
            id=employee_id,
            tenant_id=tenant_id,
            employee_no=f'ECHG{abs(hash(employee_id)) % 100000:05d}',
            name=f'AI异动评估员工{suffix[-4:]}',
            status='active',
            department_id=source_dept_id,
            position_id=source_position_id,
            job_title='供应链主管',
        )
        db.session.add(employee)
    else:
        employee.status = 'active'
        employee.department_id = source_dept_id
        employee.position_id = source_position_id
        employee.job_title = '供应链主管'

    user = User.query.get(user_id)
    if user and not user.employee_id:
        user.employee_id = employee_id
    db.session.commit()
    return {
        'employee_id': employee_id,
        'employee_name': employee.name,
        'source_department_id': source_dept_id,
        'target_department_id': target_dept_id,
        'target_department_name': target_dept.name,
        'target_position_id': target_position_id,
    }


def ensure_salary_adjustment_confirmation_case(*, user_id: str, tenant_id: str, request_id: str) -> Dict[str, str]:
    suffix = hashlib.sha1(request_id.encode('utf-8')).hexdigest()[:12]
    tenant_suffix = _tenant_fixture_suffix(tenant_id)
    dept_id = _scoped_fixture_id('eval-dept-salary-source', tenant_id)
    position_id = _scoped_fixture_id('eval-pos-salary-source', tenant_id)
    employee_id = f'eval-salary-emp-{tenant_suffix}-{suffix}'
    profile_id = f'eval-salary-profile-{tenant_suffix}-{suffix}'
    cycle_id = _scoped_fixture_id('eval-cycle-salary-q2', tenant_id)
    review_id = f'eval-salary-review-{tenant_suffix}-{suffix}'

    dept = Department.query.get(dept_id)
    if not dept:
        dept = Department(id=dept_id, tenant_id=tenant_id, name='AI调薪评估部', code=f'AI-SAL-{tenant_suffix}', status='active')
        db.session.add(dept)
    position = Position.query.get(position_id)
    if not position:
        position = Position(
            id=position_id,
            tenant_id=tenant_id,
            title='高级测试工程师',
            department_id=dept_id,
            level='P6',
            status='active',
        )
        db.session.add(position)

    employee = Employee.query.get(employee_id)
    if not employee:
        employee = Employee(
            id=employee_id,
            tenant_id=tenant_id,
            employee_no=f'ESAL{abs(hash(employee_id)) % 100000:05d}',
            name=f'AI调薪评估员工{suffix[-4:]}',
            status='active',
            department_id=dept_id,
            position_id=position_id,
            job_title='高级测试工程师',
            hire_date=date(2026, 1, 10),
        )
        db.session.add(employee)
    else:
        employee.status = 'active'
        employee.department_id = dept_id
        employee.position_id = position_id
        employee.job_title = '高级测试工程师'

    profile = SalaryProfile.query.filter_by(employee_id=employee_id).first()
    if not profile:
        profile = SalaryProfile(
            id=profile_id,
            tenant_id=tenant_id,
            employee_id=employee_id,
            base_salary=Decimal('12000'),
            position_salary=Decimal('8000'),
            performance_salary=Decimal('5000'),
            allowance=Decimal('1200'),
            bonus=Decimal('0'),
            deduction=Decimal('0'),
            status='active',
            remark='Copilot 调薪确认流评估临时薪资档案',
        )
        db.session.add(profile)
    else:
        profile.base_salary = Decimal('12000')
        profile.position_salary = Decimal('8000')
        profile.performance_salary = Decimal('5000')
        profile.allowance = Decimal('1200')
        profile.bonus = Decimal('0')
        profile.deduction = Decimal('0')
        profile.status = 'active'
        profile.remark = 'Copilot 调薪确认流评估临时薪资档案'

    cycle = PerformanceCycle.query.get(cycle_id)
    if not cycle:
        cycle = PerformanceCycle(
            id=cycle_id,
            tenant_id=tenant_id,
            name='AI调薪评估周期 2026Q2',
            cycle_type='季度',
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            status='active',
        )
        db.session.add(cycle)
    review = PerformanceReview.query.get(review_id)
    if not review:
        review = PerformanceReview(
            id=review_id,
            tenant_id=tenant_id,
            employee_id=employee_id,
            cycle_id=cycle_id,
            self_score=Decimal('92'),
            manager_score=Decimal('94'),
            final_score=Decimal('93'),
            grade='A',
            result='关键项目交付稳定，建议进入调薪审批。',
            status='completed',
        )
        db.session.add(review)
    else:
        review.employee_id = employee_id
        review.cycle_id = cycle_id
        review.final_score = Decimal('93')
        review.grade = 'A'
        review.status = 'completed'

    user = User.query.get(user_id)
    if user and not user.employee_id:
        user.employee_id = employee_id
    db.session.commit()
    return {
        'employee_id': employee_id,
        'employee_name': employee.name,
        'department_id': dept_id,
        'department_name': dept.name,
        'salary_profile_id': profile.id,
        'salary_adjustment': '1800',
    }
