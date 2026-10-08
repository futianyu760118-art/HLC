"""参与考核人员维护：列表 + 批量标记。"""

from __future__ import annotations

from models import Department, Employee, db

PARTICIPATING_STATUSES = ('active', 'probation')


def list_participants(
    tenant_id: str,
    *,
    department_name: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    query = Employee.query.filter(
        Employee.tenant_id == tenant_id,
        Employee.status.in_(PARTICIPATING_STATUSES),
    )
    kw = (keyword or '').strip()
    if kw:
        query = query.filter(db.or_(
            Employee.name.like(f'%{kw}%'),
            Employee.employee_no.like(f'%{kw}%'),
        ))
    employees = query.order_by(Employee.department_id.asc(), Employee.name.asc()).all()

    dept_ids = {e.department_id for e in employees if e.department_id}
    dept_names = {
        d.id: d.name
        for d in Department.query.filter(Department.id.in_(dept_ids)).all()
    } if dept_ids else {}

    rows = []
    for employee in employees:
        dept_name = dept_names.get(employee.department_id)
        if department_name and dept_name != department_name:
            continue
        rows.append({
            'id': employee.id,
            'name': employee.name,
            'employeeNo': employee.employee_no,
            'departmentId': employee.department_id,
            'departmentName': dept_name,
            'positionName': employee.job_title or (employee.position.title if employee.position else None),
            'employeeType': employee.employee_type,
            'participant': bool(employee.performance_participant),
        })
    return rows


def set_participants(tenant_id: str, employee_ids: list[str], participant: bool) -> dict:
    ids = [str(item).strip() for item in (employee_ids or []) if str(item).strip()]
    if not ids:
        raise ValueError('未选择员工')
    employees = Employee.query.filter(
        Employee.tenant_id == tenant_id,
        Employee.id.in_(ids),
    ).all()
    for employee in employees:
        employee.performance_participant = bool(participant)
    db.session.flush()
    return {'updated': len(employees), 'participant': bool(participant)}
