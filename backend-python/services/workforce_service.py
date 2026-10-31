"""Governed workforce extension MVP services."""

from __future__ import annotations

import uuid
from datetime import date
from statistics import mean
from typing import Any

from models import (
    AttendanceRecord,
    Contract,
    Department,
    Employee,
    EmployeeChange,
    EmployeeRequest,
    Probation,
    Resignation,
    WorkforceInsightSnapshot,
    db,
    money,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


WORKFORCE_FEATURES = {
    'smart_scheduling': 'extension.workforce.smart_scheduling',
    'ai_scheduling': 'extension.workforce.ai_scheduling',
    'planning': 'extension.workforce.planning',
    'leave_bank': 'extension.workforce.leave_bank',
    'lifecycle_enhancement': 'extension.workforce.lifecycle_enhancement',
    'attendance_optimization': 'extension.workforce.attendance_optimization',
    'shift_marketplace': 'extension.workforce.shift_marketplace',
}

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation', 'pending_onboard')


def _ratio(part: int | float, total: int | float) -> float:
    return round((float(part) / float(total)) * 100, 2) if total else 0


def _hours(value: Any) -> float:
    return float(money(value) or 0)


def _provider_payload() -> dict[str, Any]:
    return {
        'providerCode': 'local_workforce_rules',
        'configured': False,
        'status': 'mock',
        'message': '未配置真实供应商，当前使用本地排班与劳动力规则生成可测 MVP 快照。',
    }


class WorkforceService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in WORKFORCE_FEATURES:
            raise LookupError(feature)

        base = WorkforceService._base_context(tenant_id)
        builders = {
            'smart_scheduling': WorkforceService._smart_scheduling_payload,
            'ai_scheduling': WorkforceService._ai_scheduling_payload,
            'planning': WorkforceService._planning_payload,
            'leave_bank': WorkforceService._leave_bank_payload,
            'lifecycle_enhancement': WorkforceService._lifecycle_payload,
            'attendance_optimization': WorkforceService._attendance_payload,
            'shift_marketplace': WorkforceService._shift_marketplace_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = WORKFORCE_FEATURES[feature]
        payload.update({
            'featureKey': feature_key,
            'status': extension_feature_maturity(feature_key),
        })
        payload.setdefault('summary', {})['dataScope'] = 'currentTenant'

        payload['snapshot'] = extension_read_marker(feature_key)
        return payload

    @staticmethod
    def _base_context(tenant_id: str) -> dict[str, Any]:
        employees = Employee.query.filter(
            Employee.tenant_id == tenant_id,
            Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
        ).order_by(Employee.name.asc()).all()
        departments = Department.query.filter_by(tenant_id=tenant_id, status='active').order_by(Department.name.asc()).all()
        attendance_records = AttendanceRecord.query.filter_by(tenant_id=tenant_id).order_by(AttendanceRecord.attendance_date.desc()).all()
        requests = EmployeeRequest.query.filter_by(tenant_id=tenant_id).order_by(EmployeeRequest.created_at.desc()).all()
        probations = Probation.query.filter_by(tenant_id=tenant_id).order_by(Probation.created_at.desc()).all()
        changes = EmployeeChange.query.filter_by(tenant_id=tenant_id).order_by(EmployeeChange.created_at.desc()).all()
        resignations = Resignation.query.filter_by(tenant_id=tenant_id).order_by(Resignation.created_at.desc()).all()
        contracts = Contract.query.filter_by(tenant_id=tenant_id).order_by(Contract.created_at.desc()).all()

        employees_by_department: dict[str | None, list[Employee]] = {}
        for employee in employees:
            employees_by_department.setdefault(employee.department_id, []).append(employee)
        attendance_by_employee: dict[str, list[AttendanceRecord]] = {}
        for row in attendance_records:
            attendance_by_employee.setdefault(row.employee_id, []).append(row)
        requests_by_employee: dict[str, list[EmployeeRequest]] = {}
        for row in requests:
            requests_by_employee.setdefault(row.employee_id, []).append(row)

        return {
            'employees': employees,
            'departments': departments,
            'attendanceRecords': attendance_records,
            'requests': requests,
            'probations': probations,
            'changes': changes,
            'resignations': resignations,
            'contracts': contracts,
            'employeesByDepartment': employees_by_department,
            'attendanceByEmployee': attendance_by_employee,
            'requestsByEmployee': requests_by_employee,
        }

    @staticmethod
    def _schedule_suggestions(base: dict[str, Any]) -> list[dict[str, Any]]:
        suggestions = []
        abnormal_by_employee = {
            employee_id: [
                record for record in records
                if record.status not in ('normal', 'present') or _hours(record.work_hours) > 8
            ]
            for employee_id, records in base['attendanceByEmployee'].items()
        }
        leave_employee_ids = {
            row.employee_id for row in base['requests']
            if row.request_type in ('leave', 'annual_leave', 'sick_leave') and row.status in ('approved', 'pending')
        }
        for employee in base['employees']:
            records = base['attendanceByEmployee'].get(employee.id, [])
            abnormal_count = len(abnormal_by_employee.get(employee.id, []))
            leave_pressure = employee.id in leave_employee_ids
            score = 50 + min(30, abnormal_count * 10) + (15 if leave_pressure else 0)
            suggestions.append({
                'employeeId': employee.id,
                'employeeName': employee.name,
                'departmentName': employee.department.name if employee.department else None,
                'recommendedShift': 'flex' if abnormal_count else 'day',
                'loadScore': min(100, score),
                'attendanceRecordCount': len(records),
                'reasons': [
                    reason for reason in [
                        '近期有异常或超时考勤' if abnormal_count else None,
                        '存在请假/休假申请' if leave_pressure else None,
                        '可安排标准日班' if not abnormal_count and not leave_pressure else None,
                    ] if reason
                ],
            })
        return sorted(suggestions, key=lambda row: (-int(row['loadScore']), row['employeeName']))

    @staticmethod
    def _smart_scheduling_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        suggestions = WorkforceService._schedule_suggestions(base)
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'scheduleSuggestionCount': len(suggestions),
                'highLoadCount': sum(1 for row in suggestions if int(row['loadScore']) >= 70),
            },
            'scheduleSuggestions': suggestions[:20],
        }

    @staticmethod
    def _ai_scheduling_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        suggestions = WorkforceService._schedule_suggestions(base)
        simulations = [
            {
                'id': 'simulation-balance-workload',
                'name': '平衡工作量',
                'affectedEmployeeCount': len(suggestions),
                'expectedOutcome': '降低异常考勤和临时补班压力',
            },
            {
                'id': 'simulation-cover-leave',
                'name': '覆盖休假缺口',
                'affectedEmployeeCount': sum(1 for row in suggestions if '存在请假/休假申请' in row['reasons']),
                'expectedOutcome': '优先补齐已审批休假日的人员覆盖',
            },
        ]
        return {
            'summary': {
                'simulationCount': len(simulations),
                'scheduleSuggestionCount': len(suggestions),
                'assistantMode': 'local_mvp',
            },
            'provider': _provider_payload(),
            'simulations': simulations,
            'recommendations': suggestions[:10],
        }

    @staticmethod
    def _planning_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        demand_signals = []
        for department in base['departments']:
            employees = base['employeesByDepartment'].get(department.id, [])
            overtime_hours = sum(
                _hours(record.work_hours) - 8
                for employee in employees
                for record in base['attendanceByEmployee'].get(employee.id, [])
                if _hours(record.work_hours) > 8
            )
            demand_signals.append({
                'departmentId': department.id,
                'departmentName': department.name,
                'employeeCount': len(employees),
                'overtimeHours': round(overtime_hours, 2),
                'demandLevel': 'high' if overtime_hours >= 4 else 'normal',
            })
        demand_signals.extend([
            {
                'key': 'pending_changes',
                'label': '待生效异动',
                'value': sum(1 for row in base['changes'] if row.status in ('pending', 'submitted')),
                'demandLevel': 'watch',
            },
            {
                'key': 'pending_resignations',
                'label': '待离职交接',
                'value': sum(1 for row in base['resignations'] if row.status in ('pending', 'submitted')),
                'demandLevel': 'watch',
            },
        ])
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'departmentCount': len(base['departments']),
                'demandSignalCount': len(demand_signals),
            },
            'demandSignals': demand_signals,
        }

    @staticmethod
    def _leave_bank_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        leave_requests = [
            row for row in base['requests']
            if row.request_type in ('leave', 'annual_leave', 'sick_leave')
        ]
        leave_rows = []
        for row in leave_requests:
            used_hours = _hours(row.duration_hours)
            leave_rows.append({
                'requestId': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'requestType': row.request_type,
                'status': row.status,
                'usedHours': used_hours,
                'remainingMvpHours': max(0, 80 - used_hours),
            })
        total_used = sum(row['usedHours'] for row in leave_rows)
        return {
            'summary': {
                'leaveRequestCount': len(leave_rows),
                'usedLeaveHours': round(total_used, 2),
                'estimatedRemainingHours': round(max(0, len(base['employees']) * 80 - total_used), 2),
            },
            'leaveBalances': leave_rows[:20],
        }

    @staticmethod
    def _lifecycle_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        signals = []
        for row in base['probations']:
            days_left = (row.expected_regular_date - today).days if row.expected_regular_date else None
            signals.append({
                'id': row.id,
                'type': 'probation',
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'status': row.status,
                'dueDate': row.expected_regular_date.isoformat() if row.expected_regular_date else None,
                'daysLeft': days_left,
            })
        for row in base['changes']:
            signals.append({
                'id': row.id,
                'type': 'employee_change',
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'status': row.status,
                'dueDate': row.effective_date.isoformat() if row.effective_date else None,
                'changeType': row.change_type,
            })
        for row in base['resignations']:
            signals.append({
                'id': row.id,
                'type': 'resignation',
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'status': row.status,
                'dueDate': row.expected_leave_date.isoformat() if row.expected_leave_date else None,
            })
        for row in base['contracts']:
            days_left = (row.end_date - today).days if row.end_date else None
            if days_left is None or days_left <= 60:
                signals.append({
                    'id': row.id,
                    'type': 'contract',
                    'employeeId': row.employee_id,
                    'employeeName': row.employee.name if row.employee else None,
                    'status': row.status,
                    'dueDate': row.end_date.isoformat() if row.end_date else None,
                    'daysLeft': days_left,
                })
        return {
            'summary': {
                'lifecycleSignalCount': len(signals),
                'probationCount': len(base['probations']),
                'contractRenewalCount': sum(1 for row in signals if row['type'] == 'contract'),
            },
            'signals': signals[:30],
        }

    @staticmethod
    def _attendance_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        abnormal_records = [
            row for row in base['attendanceRecords']
            if row.status not in ('normal', 'present') or _hours(row.work_hours) > 8
        ]
        average_hours = round(mean([_hours(row.work_hours) for row in base['attendanceRecords']]), 2) if base['attendanceRecords'] else 0
        rows = [
            {
                'recordId': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'attendanceDate': row.attendance_date.isoformat() if row.attendance_date else None,
                'workHours': _hours(row.work_hours),
                'status': row.status,
                'source': row.source,
                'recommendedAction': '复核排班和补卡/加班申请' if row.status != 'normal' else '观察工时压力',
            }
            for row in abnormal_records
        ]
        return {
            'summary': {
                'attendanceRecordCount': len(base['attendanceRecords']),
                'abnormalAttendanceCount': len(abnormal_records),
                'averageWorkHours': average_hours,
                'abnormalRate': _ratio(len(abnormal_records), len(base['attendanceRecords'])),
            },
            'abnormalRecords': rows[:30],
        }

    @staticmethod
    def _shift_marketplace_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        suggestions = WorkforceService._schedule_suggestions(base)
        offers = []
        for row in suggestions:
            if row['recommendedShift'] == 'flex' or int(row['loadScore']) >= 50:
                offers.append({
                    'id': f"shift-offer-{row['employeeId']}",
                    'employeeId': row['employeeId'],
                    'employeeName': row['employeeName'],
                    'departmentName': row['departmentName'],
                    'shiftType': row['recommendedShift'],
                    'swapEligible': int(row['loadScore']) < 80,
                    'message': '可进入班次交换池' if int(row['loadScore']) < 80 else '高负荷，建议经理审批后调整',
                })
        return {
            'summary': {
                'shiftOfferCount': len(offers),
                'swapEligibleCount': sum(1 for row in offers if row['swapEligible']),
                'highLoadOfferCount': sum(1 for row in offers if not row['swapEligible']),
            },
            'shiftOffers': offers[:30],
        }
