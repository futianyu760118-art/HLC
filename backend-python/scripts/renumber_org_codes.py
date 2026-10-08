"""Renumber HRM department codes and employee numbers with business-friendly IDs."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('DISABLE_STUDY_REMINDER_SCHEDULER', '1')

from app import create_app  # noqa: E402
from models import Department, Employee, db  # noqa: E402


DEPARTMENT_PRIORITY = [
    ('恒剑光电', 0),
    ('总经办', 10),
    ('总经理', 10),
    ('销售中心', 20),
    ('销售', 25),
    ('研发中心', 30),
    ('研发', 35),
    ('供应链中心', 40),
    ('供应链', 45),
    ('财务', 50),
    ('人事行政', 60),
    ('人事', 61),
    ('行政', 62),
    ('信息化', 70),
    ('恒有信息', 75),
    ('咨询', 80),
    ('内销', 90),
]

TITLE_PRIORITY = [
    ('董事长', 0),
    ('总经理', 1),
    ('总裁', 1),
    ('CEO', 1),
    ('副总', 5),
    ('总监', 10),
    ('负责人', 15),
    ('经理', 20),
    ('部长', 24),
    ('主管', 30),
    ('主任', 32),
    ('主办', 35),
    ('组长', 38),
    ('工程师', 45),
    ('会计', 45),
    ('专员', 50),
    ('助理', 55),
    ('员', 60),
]

EMPLOYEE_PRIORITY = [
    ('朱剑军', 0),
    ('沈旭日', 1),
    ('朱梦倩', 2),
]


def keyword_rank(value: str | None, table: list[tuple[str, int]], default: int = 500) -> int:
    text = (value or '').upper()
    for keyword, rank in table:
        if keyword.upper() in text:
            return rank
    return default


def exact_name_rank(value: str | None, table: list[tuple[str, int]], default: int = 500) -> int:
    text = (value or '').strip()
    for name, rank in table:
        if text == name:
            return rank
    return default


def stable_text(value: str | None) -> str:
    return value or ''


def stable_date(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return ''


def ordered_departments(departments: list[Department]) -> list[Department]:
    by_parent: dict[str | None, list[Department]] = {}
    by_id = {department.id: department for department in departments}
    for department in departments:
        parent_id = department.parent_id if department.parent_id in by_id else None
        by_parent.setdefault(parent_id, []).append(department)

    def sort_key(department: Department):
        return (
            keyword_rank(department.name, DEPARTMENT_PRIORITY),
            stable_text(department.name),
            stable_text(department.id),
        )

    result: list[Department] = []

    def visit(parent_id: str | None):
        for department in sorted(by_parent.get(parent_id, []), key=sort_key):
            result.append(department)
            visit(department.id)

    visit(None)
    return result


def employee_sort_key(employee: Employee, dept_order: dict[str, int]):
    department = employee.department
    status_rank = 0 if employee.status in ('active', 'probation', 'pending_onboard') else 10
    return (
        exact_name_rank(employee.name, EMPLOYEE_PRIORITY),
        status_rank,
        keyword_rank(employee.job_title, TITLE_PRIORITY),
        dept_order.get(employee.department_id or '', 9999),
        stable_date(employee.hire_date),
        stable_text(department.name if department else ''),
        stable_text(employee.name),
        stable_text(employee.id),
    )


def renumber(*, apply: bool) -> dict[str, int | str]:
    departments = Department.query.all()
    employees = Employee.query.all()

    department_order = ordered_departments(departments)
    dept_order_index = {department.id: index for index, department in enumerate(department_order)}
    employee_order = sorted(employees, key=lambda employee: employee_sort_key(employee, dept_order_index))

    stats = {
        'mode': 'APPLY' if apply else 'DRY-RUN',
        'departments': len(department_order),
        'employees': len(employee_order),
        'department_first_code': 'HJ-001' if department_order else '',
        'employee_first_no': 'HJ-0001' if employee_order else '',
    }

    if not apply:
        return stats

    for index, department in enumerate(department_order, start=1):
        department.code = f'__REN_DEPT_{index:04d}__'
    for index, employee in enumerate(employee_order, start=1):
        employee.employee_no = f'__REN_EMP_{index:05d}__'
    db.session.flush()

    for index, department in enumerate(department_order, start=1):
        department.code = f'HJ-{index:03d}'
        department.updated_at = datetime.utcnow()
    for index, employee in enumerate(employee_order, start=1):
        employee.employee_no = f'HJ-{index:04d}'
        employee.updated_at = datetime.utcnow()

    db.session.commit()
    return stats


def main() -> int:
    apply = '--apply' in sys.argv
    app = create_app()
    with app.app_context():
        stats = renumber(apply=apply)
    for key in sorted(stats):
        print(f'{key}={stats[key]}')
    if not apply:
        print('dry_run=true; pass --apply to write changes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
