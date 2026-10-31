"""月度考勤汇总：由日考勤明细聚合。

口径：应出勤天数 = 有排班的天数（非休息）；实际出勤 = 正常 + 缺卡；其余按状态计数。
工时合计取日明细 work_hours 之和（暂不扣减）。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func

from models import AttendanceTimesheet, Employee, db

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation')


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(part) for part in month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    return start, end - timedelta(days=1)


def monthly_summary(
    tenant_id: str,
    month: str,
    *,
    department_id: str | None = None,
    employee_id: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    start, end = _month_bounds(month)

    query = AttendanceTimesheet.query.filter(
        AttendanceTimesheet.tenant_id == tenant_id,
        AttendanceTimesheet.work_date >= start,
        AttendanceTimesheet.work_date <= end,
    )
    if department_id:
        query = query.filter(AttendanceTimesheet.department_id == department_id)
    if employee_id:
        query = query.filter(AttendanceTimesheet.employee_id == employee_id)
    if keyword:
        kw = keyword.strip()
        if kw:
            matched = Employee.query.filter(
                Employee.tenant_id == tenant_id,
                db.or_(
                    Employee.name.like(f'%{kw}%'),
                    Employee.employee_no.like(f'%{kw}%'),
                ),
            ).all()
            matched_ids = [employee.id for employee in matched]
            if not matched_ids:
                return []
            query = query.filter(AttendanceTimesheet.employee_id.in_(matched_ids))

    rows = query.order_by(AttendanceTimesheet.employee_id).all()
    employee_ids = {row.employee_id for row in rows}
    employees = {
        employee.id: employee
        for employee in Employee.query.filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}
    department_names = _department_names(employee_ids, employees)

    summary: dict[str, dict] = {}
    for row in rows:
        bucket = summary.setdefault(row.employee_id, _empty_bucket(
            employee=employees.get(row.employee_id),
            department_name=department_names.get(row.employee_id),
        ))
        bucket['totalDays'] += 1
        hours = float(row.work_hours or 0)
        bucket['workHours'] = round(bucket['workHours'] + hours, 2)
        bucket['overtimeHours'] = round(bucket['overtimeHours'] + float(row.overtime_hours or 0), 2)
        status = row.status or 'normal'
        if status == 'rest':
            bucket['restDays'] += 1
            continue
        bucket['expectedDays'] += 1
        if status == 'normal':
            bucket['presentDays'] += 1
            bucket['normalDays'] += 1
        elif status == 'missing_card':
            bucket['presentDays'] += 1
            bucket['missingCardDays'] += 1
        elif status == 'absent':
            bucket['absentDays'] += 1
        else:
            bucket['otherDays'] += 1

    for bucket in summary.values():
        expected = bucket['expectedDays']
        bucket['attendanceRate'] = round(bucket['presentDays'] / expected, 4) if expected else None

    return sorted(summary.values(), key=lambda item: (item['employeeName'] or ''))


def _empty_bucket(*, employee: Employee | None, department_name: str | None) -> dict:
    return {
        'employeeId': employee.id if employee else None,
        'employeeName': employee.name if employee else None,
        'employeeNo': employee.employee_no if employee else None,
        'employeeType': employee.employee_type if employee else None,
        'departmentId': employee.department_id if employee else None,
        'departmentName': department_name,
        'totalDays': 0,
        'expectedDays': 0,
        'presentDays': 0,
        'normalDays': 0,
        'missingCardDays': 0,
        'absentDays': 0,
        'restDays': 0,
        'otherDays': 0,
        'workHours': 0.0,
        'overtimeHours': 0.0,
        'attendanceRate': None,
    }


def _department_names(employee_ids: set, employees: dict) -> dict:
    department_ids = {
        employee.department_id for employee in employees.values() if employee.department_id
    }
    if not department_ids:
        return {}
    from models import Department

    names = {
        row.id: row.name
        for row in Department.query.filter(Department.id.in_(department_ids)).all()
    }
    return {
        employee_id: names.get(employee.department_id)
        for employee_id, employee in employees.items()
    }
