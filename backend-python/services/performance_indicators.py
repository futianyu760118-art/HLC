"""岗位考核指标维护与考核表生成（按 部门 + 岗位 匹配）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from models import (
    Department,
    Employee,
    PerformanceCycle,
    PerformanceIndicator,
    PerformanceReview,
    PerformanceReviewItem,
    db,
)

PARTICIPATING_STATUSES = ('active', 'probation')


def replace_indicators(
    tenant_id: str,
    *,
    department_name: str | None,
    position_name: str | None,
    indicators: list[dict],
) -> int:
    """用给定指标替换某 部门+岗位 的全部指标；返回写入条数。"""
    PerformanceIndicator.query.filter_by(
        tenant_id=tenant_id,
        department_name=department_name,
        position_name=position_name,
    ).delete(synchronize_session=False)

    created = 0
    for index, item in enumerate(indicators, start=1):
        name = (item.get('name') or '').strip()
        if not name:
            continue
        db.session.add(PerformanceIndicator(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            department_name=department_name,
            position_name=position_name,
            seq=item.get('seq') or index,
            name=name,
            target_value=item.get('targetValue'),
            definition=item.get('definition'),
            scoring_rule=item.get('scoringRule'),
            weight=item.get('weight'),
            evaluator_department=item.get('evaluatorDepartment'),
            linked_to_salary=item.get('linkedToSalary', True),
            status='active',
        ))
        created += 1
    return created


def indicators_for(tenant_id: str, department_name: str | None, position_name: str | None) -> list[PerformanceIndicator]:
    """按 部门 + 岗位 取启用中的指标（按序号）。"""
    return (
        PerformanceIndicator.query.filter_by(
            tenant_id=tenant_id,
            department_name=department_name,
            position_name=position_name,
            status='active',
        )
        .order_by(PerformanceIndicator.seq.asc())
        .all()
    )


def ensure_monthly_cycle(tenant_id: str, month: str) -> PerformanceCycle:
    """按 YYYY-MM 取得或创建月度绩效周期。"""
    cycle = PerformanceCycle.query.filter_by(
        tenant_id=tenant_id, name=month, cycle_type='月度',
    ).first()
    if cycle:
        return cycle
    year, mon = (int(part) for part in month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    from datetime import timedelta
    cycle = PerformanceCycle(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=month,
        cycle_type='月度',
        start_date=start,
        end_date=end - timedelta(days=1),
        status='draft',
    )
    db.session.add(cycle)
    db.session.flush()
    return cycle


def generate_reviews(
    tenant_id: str,
    *,
    month: str,
    department_names: list[str] | None = None,
    employee_ids: list[str] | None = None,
) -> dict:
    """为"参与考核"的员工按 部门+岗位 生成考核表（含指标明细）。"""
    cycle = ensure_monthly_cycle(tenant_id, month)

    query = Employee.query.filter(
        Employee.tenant_id == tenant_id,
        Employee.performance_participant.is_(True),
        Employee.status.in_(PARTICIPATING_STATUSES),
    )
    if employee_ids:
        query = query.filter(Employee.id.in_(employee_ids))
    employees = query.all()

    created = 0
    skipped = 0
    without_indicators: list[str] = []
    department_ids = {employee.department_id for employee in employees if employee.department_id}
    department_names_by_id = {
        row.id: row.name
        for row in Department.query.filter(Department.id.in_(department_ids)).all()
    } if department_ids else {}

    for employee in employees:
        dept_name = department_names_by_id.get(employee.department_id)
        if department_names and dept_name not in department_names:
            continue
        position_name = employee.job_title or (employee.position.title if employee.position else None)
        indicators = indicators_for(tenant_id, dept_name, position_name)
        if not indicators:
            without_indicators.append(employee.name)
            continue

        existing = PerformanceReview.query.filter_by(
            tenant_id=tenant_id, employee_id=employee.id, cycle_id=cycle.id,
        ).first()
        if existing:
            skipped += 1
            continue

        review = PerformanceReview(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            employee_id=employee.id,
            cycle_id=cycle.id,
            manager_id=employee.manager_id,
            status='draft',
        )
        db.session.add(review)
        db.session.flush()
        for indicator in indicators:
            db.session.add(PerformanceReviewItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                review_id=review.id,
                indicator_code=indicator.id,
                indicator_name=indicator.name,
                weight=indicator.weight,
                data_source=indicator.evaluator_department,
                manager_score=None,
                comment=indicator.scoring_rule,
                sort_order=indicator.seq or 0,
            ))
        created += 1

    return {
        'cycleId': cycle.id,
        'month': month,
        'created': created,
        'skipped': skipped,
        'withoutIndicators': without_indicators,
    }
