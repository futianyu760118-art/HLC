"""Headcount planning service for the governed extension API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from models import Department, Employee, HeadcountChange, HeadcountPlan, db
from services.extension_registry import extension_feature_maturity


ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _new_id() -> str:
    return str(uuid.uuid4())


def _actual_by_department(tenant_id: str) -> Dict[str, int]:
    rows = (
        db.session.query(Employee.department_id, func.count(Employee.id))
        .filter(
            Employee.tenant_id == tenant_id,
            Employee.department_id.isnot(None),
            Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
        )
        .group_by(Employee.department_id)
        .all()
    )
    return {department_id: int(count or 0) for department_id, count in rows}


def _status_for(plan: int, actual: int) -> str:
    if plan <= 0:
        return 'unplanned'
    if actual > plan:
        return 'over'
    if actual < plan:
        return 'under'
    return 'full'


def _usage_rate(plan: int, actual: int) -> float:
    return round((actual / plan) * 100, 2) if plan > 0 else 0


class HeadcountService:
    @staticmethod
    def get_headcount_summary(tenant_id: str) -> Dict[str, Any]:
        departments = Department.query.filter_by(tenant_id=tenant_id).order_by(Department.name.asc()).all()
        plan_rows = HeadcountPlan.query.filter_by(tenant_id=tenant_id).all()
        plan_by_department = {row.department_id: row for row in plan_rows}
        actual_by_department = _actual_by_department(tenant_id)

        department_rows: List[Dict[str, Any]] = []
        total_plan = 0
        total_actual = 0
        for department in departments:
            plan_row = plan_by_department.get(department.id)
            plan = int(plan_row.plan_count if plan_row else 0)
            actual = int(actual_by_department.get(department.id, 0))
            total_plan += plan
            total_actual += actual
            department_rows.append({
                'departmentId': department.id,
                'departmentName': department.name,
                'departmentCode': department.code,
                'parentId': department.parent_id,
                'parentName': department.parent.name if department.parent else None,
                'plan': plan,
                'actual': actual,
                'vacancy': plan - actual,
                'usageRate': _usage_rate(plan, actual),
                'status': _status_for(plan, actual),
                'note': plan_row.note if plan_row else '',
                'updatedAt': plan_row.to_dict().get('updatedAt') if plan_row else None,
            })

        return {
            'featureKey': 'extension.foundation.headcount',
            'status': extension_feature_maturity('extension.foundation.headcount'),
            'summary': {
                'totalPlan': total_plan,
                'totalActual': total_actual,
                'totalVacancy': total_plan - total_actual,
                'usageRate': _usage_rate(total_plan, total_actual),
                'departmentCount': len(department_rows),
            },
            'departments': department_rows,
        }

    @staticmethod
    def update_department_headcount(
        department_id: str,
        tenant_id: str,
        headcount_plan: int,
        operator_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if headcount_plan < 0:
            raise ValueError('编制人数不能小于 0')

        department = Department.query.filter_by(id=department_id, tenant_id=tenant_id).first()
        if not department:
            raise LookupError('部门不存在或无权访问')

        plan = HeadcountPlan.query.filter_by(tenant_id=tenant_id, department_id=department_id).first()
        if not plan:
            plan = HeadcountPlan(
                id=_new_id(),
                tenant_id=tenant_id,
                department_id=department_id,
                plan_count=0,
                created_by=operator_id,
            )
            db.session.add(plan)

        old_plan = int(plan.plan_count or 0)
        actual = Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.department_id == department_id,
            Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
        ).count()

        plan.plan_count = int(headcount_plan)
        plan.note = note or ''
        plan.updated_by = operator_id
        plan.updated_at = datetime.utcnow()

        change = HeadcountChange(
            id=_new_id(),
            tenant_id=tenant_id,
            department_id=department_id,
            old_plan=old_plan,
            new_plan=int(headcount_plan),
            actual_count=int(actual),
            note=note or '',
            operator_id=operator_id,
        )
        db.session.add(change)

        return {
            'departmentId': department.id,
            'departmentName': department.name,
            'oldPlan': old_plan,
            'newPlan': int(headcount_plan),
            'actual': int(actual),
            'vacancy': int(headcount_plan) - int(actual),
            'usageRate': _usage_rate(int(headcount_plan), int(actual)),
            'status': _status_for(int(headcount_plan), int(actual)),
            'note': note or '',
        }

    @staticmethod
    def list_history(
        tenant_id: str,
        department_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        query = HeadcountChange.query.filter_by(tenant_id=tenant_id)
        if department_id:
            query = query.filter_by(department_id=department_id)
        limit = max(1, min(int(limit or 100), 200))
        rows = query.order_by(HeadcountChange.created_at.desc()).limit(limit).all()
        return {
            'items': [row.to_dict() for row in rows],
            'total': len(rows),
            'limit': limit,
        }
