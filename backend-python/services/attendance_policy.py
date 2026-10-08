"""Attendance policy configuration and explainable daily calculation.

This phase deliberately keeps the existing ``attendance_records`` contract
unchanged.  Policy results live in their own tenant-scoped table so a policy
mistake can be recalculated without rewriting historical manual records.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
import re
import uuid

from sqlalchemy import or_

from models import (
    AttendanceDailyResult,
    AttendanceExternalPerson,
    AttendanceGroup,
    AttendanceGroupMembership,
    AttendanceHoliday,
    AttendanceRawPunch,
    AttendanceRecord,
    AttendanceRuleSet,
    AttendanceSchedule,
    AttendanceShift,
    Department,
    Employee,
    EmployeeRequest,
    Position,
    db,
)


ACTIVE_EMPLOYEE_STATUSES = {'active', 'probation'}
SHIFT_TYPES = {'fixed', 'flexible'}
POLICY_STATUSES = {'active', 'inactive'}
HOLIDAY_TYPES = {'holiday', 'working_day', 'company_rest'}
SCHEDULE_TYPES = {'workday', 'rest', 'holiday'}
CALCULATION_VERSION = 'v1'
HHMM_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class AttendancePolicyError(ValueError):
    """A user-correctable policy configuration or calculation error."""

    def __init__(self, message: str, code: str = 'ATTENDANCE_POLICY_INVALID'):
        super().__init__(message)
        self.code = code


def _clean(value) -> str:
    return str(value or '').strip()


def _as_date(value, *, field: str, required: bool = False) -> date | None:
    if value in (None, ''):
        if required:
            raise AttendancePolicyError(f'{field} 不能为空')
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _clean(value)
    try:
        return datetime.strptime(raw[:10], '%Y-%m-%d').date()
    except ValueError as exc:
        raise AttendancePolicyError(f'{field} 应为 YYYY-MM-DD') from exc


def _as_int(value, *, field: str, default: int | None = None, minimum: int | None = None) -> int | None:
    if value in (None, ''):
        result = default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise AttendancePolicyError(f'{field} 应为整数') from exc
    if result is not None and minimum is not None and result < minimum:
        raise AttendancePolicyError(f'{field} 不能小于 {minimum}')
    return result


def _as_bool(value, *, default: bool = False) -> bool:
    if value in (None, ''):
        return default
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {'1', 'true', 'yes', 'y', '是', 'on'}


def _as_decimal(value, *, field: str, default: Decimal | None = None, minimum: Decimal | None = None) -> Decimal | None:
    if value in (None, ''):
        result = default
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise AttendancePolicyError(f'{field} 应为数字') from exc
    if result is not None and minimum is not None and result < minimum:
        raise AttendancePolicyError(f'{field} 不能小于 {minimum}')
    return result


def _as_hhmm(value, *, field: str, required: bool = False) -> str | None:
    if value in (None, ''):
        if required:
            raise AttendancePolicyError(f'{field} 不能为空')
        return None
    raw = _clean(value)
    if not HHMM_RE.fullmatch(raw):
        raise AttendancePolicyError(f'{field} 应为 HH:MM')
    return raw


def _validate_effective_range(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise AttendancePolicyError('生效结束日期不能早于生效开始日期')


def _effective(row, day: date) -> bool:
    return (
        getattr(row, 'status', 'active') == 'active'
        and (getattr(row, 'effective_from', None) is None or row.effective_from <= day)
        and (getattr(row, 'effective_to', None) is None or row.effective_to >= day)
    )


def _stable_daily_id(tenant_id: str, employee_id: str, day: date) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'attendance-daily:{tenant_id}:{employee_id}:{day.isoformat()}'))


def _tenant_row(model, tenant_id: str, row_id: str | None):
    if not row_id:
        return None
    if model is Position:
        # Position was historically created without a tenant_id in some local
        # databases. Its owning department still provides a tenant boundary.
        tenant_column = getattr(model, 'tenant_id', None)
        if tenant_column is not None:
            return model.query.outerjoin(
                Department, model.department_id == Department.id,
            ).filter(
                model.id == row_id,
                (tenant_column == tenant_id) | (Department.tenant_id == tenant_id),
            ).first()
    return model.query.filter_by(id=row_id, tenant_id=tenant_id).first()


def _ensure_unique_code(model, tenant_id: str, code: str, existing_id: str | None = None) -> None:
    query = model.query.filter_by(tenant_id=tenant_id, code=code)
    if existing_id:
        query = query.filter(model.id != existing_id)
    if query.first():
        raise AttendancePolicyError('编码已存在，请换一个编码', 'ATTENDANCE_POLICY_CODE_EXISTS')


def save_shift(tenant_id: str, payload: dict, *, actor_id: str | None = None, existing: AttendanceShift | None = None) -> AttendanceShift:
    row = existing or AttendanceShift(id=str(uuid.uuid4()), tenant_id=tenant_id)
    code = _clean(payload.get('code')) if 'code' in payload or not existing else row.code
    name = _clean(payload.get('name')) if 'name' in payload or not existing else row.name
    if not code:
        raise AttendancePolicyError('班次编码不能为空')
    if not name:
        raise AttendancePolicyError('班次名称不能为空')
    _ensure_unique_code(AttendanceShift, tenant_id, code, row.id if existing else None)
    shift_type = _clean(payload.get('shiftType')) if 'shiftType' in payload or not existing else row.shift_type
    if shift_type not in SHIFT_TYPES:
        raise AttendancePolicyError('班次类型仅支持 fixed 或 flexible')

    start_time = _as_hhmm(
        payload.get('startTime') if 'startTime' in payload or not existing else row.start_time,
        field='上班时间',
        required=shift_type == 'fixed',
    )
    end_time = _as_hhmm(
        payload.get('endTime') if 'endTime' in payload or not existing else row.end_time,
        field='下班时间',
        required=shift_type == 'fixed',
    )
    required_hours = _as_decimal(
        payload.get('requiredWorkHours') if 'requiredWorkHours' in payload or not existing else row.required_work_hours,
        field='应出勤小时',
        minimum=Decimal('0.01'),
    )
    if shift_type == 'flexible' and required_hours is None:
        raise AttendancePolicyError('弹性班必须设置应出勤小时')
    if shift_type == 'fixed' and start_time and end_time:
        # Cross-day is allowed; same-day shifts may have an end time after start.
        if start_time == end_time and not _as_bool(payload.get('crossDay') if 'crossDay' in payload or not existing else row.cross_day):
            raise AttendancePolicyError('固定班上下班时间不能相同，跨日班请勾选跨日')

    cross_day = _as_bool(payload.get('crossDay') if 'crossDay' in payload or not existing else row.cross_day)
    if shift_type == 'flexible':
        cross_day = False
        start_time = None
        end_time = None
    row.code = code
    row.name = name
    row.shift_type = shift_type
    row.start_time = start_time
    row.end_time = end_time
    row.cross_day = cross_day
    row.required_work_hours = required_hours
    row.late_grace_minutes = _as_int(
        payload.get('lateGraceMinutes') if 'lateGraceMinutes' in payload or not existing else row.late_grace_minutes,
        field='允许迟到分钟', default=0, minimum=0,
    ) or 0
    row.early_leave_grace_minutes = _as_int(
        payload.get('earlyLeaveGraceMinutes') if 'earlyLeaveGraceMinutes' in payload or not existing else row.early_leave_grace_minutes,
        field='允许早退分钟', default=0, minimum=0,
    ) or 0
    row.require_check_in = _as_bool(
        payload.get('requireCheckIn') if 'requireCheckIn' in payload or not existing else row.require_check_in,
        default=True,
    )
    row.require_check_out = _as_bool(
        payload.get('requireCheckOut') if 'requireCheckOut' in payload or not existing else row.require_check_out,
        default=True,
    )
    status = _clean(payload.get('status')) if 'status' in payload or not existing else row.status
    if status not in POLICY_STATUSES:
        raise AttendancePolicyError('状态仅支持 active 或 inactive')
    row.status = status
    row.remark = payload.get('remark') if 'remark' in payload else row.remark
    if not existing:
        row.created_by = actor_id
        db.session.add(row)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def save_rule_set(tenant_id: str, payload: dict, *, actor_id: str | None = None, existing: AttendanceRuleSet | None = None) -> AttendanceRuleSet:
    row = existing or AttendanceRuleSet(id=str(uuid.uuid4()), tenant_id=tenant_id)
    code = _clean(payload.get('code')) if 'code' in payload or not existing else row.code
    name = _clean(payload.get('name')) if 'name' in payload or not existing else row.name
    if not code:
        raise AttendancePolicyError('规则编码不能为空')
    if not name:
        raise AttendancePolicyError('规则名称不能为空')
    _ensure_unique_code(AttendanceRuleSet, tenant_id, code, row.id if existing else None)
    effective_from = _as_date(payload.get('effectiveFrom') if 'effectiveFrom' in payload or not existing else row.effective_from, field='生效开始日期')
    effective_to = _as_date(payload.get('effectiveTo') if 'effectiveTo' in payload or not existing else row.effective_to, field='生效结束日期')
    _validate_effective_range(effective_from, effective_to)
    row.code = code
    row.name = name
    row.version = _as_int(payload.get('version') if 'version' in payload or not existing else row.version, field='规则版本', default=1, minimum=1) or 1
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.status = _validate_status(payload.get('status') if 'status' in payload or not existing else row.status, row.status if existing else 'active')
    row.absent_if_no_punch = _as_bool(payload.get('absentIfNoPunch') if 'absentIfNoPunch' in payload or not existing else row.absent_if_no_punch, default=True)
    row.missing_card_if_single_punch = _as_bool(payload.get('missingCardIfSinglePunch') if 'missingCardIfSinglePunch' in payload or not existing else row.missing_card_if_single_punch, default=True)
    row.late_grace_minutes = _as_int(payload.get('lateGraceMinutes') if 'lateGraceMinutes' in payload or not existing else row.late_grace_minutes, field='规则允许迟到分钟', minimum=0)
    row.early_leave_grace_minutes = _as_int(payload.get('earlyLeaveGraceMinutes') if 'earlyLeaveGraceMinutes' in payload or not existing else row.early_leave_grace_minutes, field='规则允许早退分钟', minimum=0)
    row.remark = payload.get('remark') if 'remark' in payload else row.remark
    if not existing:
        row.created_by = actor_id
        db.session.add(row)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def _validate_status(value, current: str = 'active') -> str:
    status = _clean(value) if value not in (None, '') else current
    if status not in POLICY_STATUSES:
        raise AttendancePolicyError('状态仅支持 active 或 inactive')
    return status


def save_group(tenant_id: str, payload: dict, *, actor_id: str | None = None, existing: AttendanceGroup | None = None) -> AttendanceGroup:
    row = existing or AttendanceGroup(id=str(uuid.uuid4()), tenant_id=tenant_id)
    code = _clean(payload.get('code')) if 'code' in payload or not existing else row.code
    name = _clean(payload.get('name')) if 'name' in payload or not existing else row.name
    if not code:
        raise AttendancePolicyError('考勤组编码不能为空')
    if not name:
        raise AttendancePolicyError('考勤组名称不能为空')
    _ensure_unique_code(AttendanceGroup, tenant_id, code, row.id if existing else None)
    shift_id = payload.get('defaultShiftId') if 'defaultShiftId' in payload or not existing else row.default_shift_id
    rule_id = payload.get('defaultRuleSetId') if 'defaultRuleSetId' in payload or not existing else row.default_rule_set_id
    if shift_id and not _tenant_row(AttendanceShift, tenant_id, _clean(shift_id)):
        raise AttendancePolicyError('默认班次不存在或不属于当前企业')
    if rule_id and not _tenant_row(AttendanceRuleSet, tenant_id, _clean(rule_id)):
        raise AttendancePolicyError('默认规则不存在或不属于当前企业')
    effective_from = _as_date(payload.get('effectiveFrom') if 'effectiveFrom' in payload or not existing else row.effective_from, field='生效开始日期')
    effective_to = _as_date(payload.get('effectiveTo') if 'effectiveTo' in payload or not existing else row.effective_to, field='生效结束日期')
    _validate_effective_range(effective_from, effective_to)
    row.code = code
    row.name = name
    row.default_shift_id = _clean(shift_id) or None
    row.default_rule_set_id = _clean(rule_id) or None
    row.priority = _as_int(payload.get('priority') if 'priority' in payload or not existing else row.priority, field='考勤组优先级', default=0) or 0
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.status = _validate_status(payload.get('status') if 'status' in payload or not existing else row.status, row.status if existing else 'active')
    row.remark = payload.get('remark') if 'remark' in payload else row.remark
    if not existing:
        row.created_by = actor_id
        db.session.add(row)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def save_membership(tenant_id: str, payload: dict, *, actor_id: str | None = None, existing: AttendanceGroupMembership | None = None) -> AttendanceGroupMembership:
    row = existing or AttendanceGroupMembership(id=str(uuid.uuid4()), tenant_id=tenant_id)
    group_id = _clean(payload.get('groupId')) if 'groupId' in payload or not existing else row.group_id
    if not _tenant_row(AttendanceGroup, tenant_id, group_id):
        raise AttendancePolicyError('考勤组不存在或不属于当前企业')
    scope_values = {
        'employeeId': payload.get('employeeId') if 'employeeId' in payload or not existing else row.employee_id,
        'departmentId': payload.get('departmentId') if 'departmentId' in payload or not existing else row.department_id,
        'positionId': payload.get('positionId') if 'positionId' in payload or not existing else row.position_id,
    }
    scope_values = {key: _clean(value) or None for key, value in scope_values.items()}
    selected = [value for value in scope_values.values() if value]
    if len(selected) != 1:
        raise AttendancePolicyError('成员范围只能选择员工、部门或岗位中的一种')
    model_by_key = {
        'employeeId': Employee,
        'departmentId': Department,
        'positionId': Position,
    }
    for key, value in scope_values.items():
        if value and not _tenant_row(model_by_key[key], tenant_id, value):
            raise AttendancePolicyError('成员范围对象不存在或不属于当前企业')
    effective_from = _as_date(payload.get('effectiveFrom') if 'effectiveFrom' in payload or not existing else row.effective_from, field='生效开始日期')
    effective_to = _as_date(payload.get('effectiveTo') if 'effectiveTo' in payload or not existing else row.effective_to, field='生效结束日期')
    _validate_effective_range(effective_from, effective_to)
    row.group_id = group_id
    row.employee_id = scope_values['employeeId']
    row.department_id = scope_values['departmentId']
    row.position_id = scope_values['positionId']
    row.priority = _as_int(payload.get('priority') if 'priority' in payload or not existing else row.priority, field='成员优先级', default=0) or 0
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.status = _validate_status(payload.get('status') if 'status' in payload or not existing else row.status, row.status if existing else 'active')
    row.remark = payload.get('remark') if 'remark' in payload else row.remark
    if not existing:
        row.created_by = actor_id
        db.session.add(row)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def save_holiday(tenant_id: str, payload: dict, *, actor_id: str | None = None, existing: AttendanceHoliday | None = None) -> AttendanceHoliday:
    row = existing or AttendanceHoliday(id=str(uuid.uuid4()), tenant_id=tenant_id)
    holiday_date = _as_date(payload.get('holidayDate') if 'holidayDate' in payload or not existing else row.holiday_date, field='日期', required=True)
    name = _clean(payload.get('name')) if 'name' in payload or not existing else row.name
    if not name:
        raise AttendancePolicyError('节假日名称不能为空')
    duplicate = AttendanceHoliday.query.filter_by(tenant_id=tenant_id, holiday_date=holiday_date)
    if existing:
        duplicate = duplicate.filter(AttendanceHoliday.id != existing.id)
    if duplicate.first():
        raise AttendancePolicyError('该日期已有节假日配置', 'ATTENDANCE_POLICY_DATE_EXISTS')
    day_type = _clean(payload.get('dayType')) if 'dayType' in payload or not existing else row.day_type
    if day_type not in HOLIDAY_TYPES:
        raise AttendancePolicyError('日期类型仅支持 holiday、working_day 或 company_rest')
    row.holiday_date = holiday_date
    row.name = name
    row.day_type = day_type
    row.status = _validate_status(payload.get('status') if 'status' in payload or not existing else row.status, row.status if existing else 'active')
    row.remark = payload.get('remark') if 'remark' in payload else row.remark
    if not existing:
        row.created_by = actor_id
        db.session.add(row)
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def upsert_schedule(
    tenant_id: str,
    payload: dict,
    *,
    actor_id: str | None = None,
    existing: AttendanceSchedule | None = None,
) -> AttendanceSchedule:
    employee_id = _clean(payload.get('employeeId')) if 'employeeId' in payload or not existing else existing.employee_id
    employee = _tenant_row(Employee, tenant_id, employee_id)
    if not employee:
        raise AttendancePolicyError('员工不存在或不属于当前企业')
    schedule_date = _as_date(
        payload.get('scheduleDate') if 'scheduleDate' in payload or not existing else existing.schedule_date,
        field='排班日期',
        required=True,
    )
    day_type = _clean(
        payload.get('dayType') if 'dayType' in payload or not existing else existing.day_type,
    ) or 'workday'
    if day_type not in SCHEDULE_TYPES:
        raise AttendancePolicyError('排班类型仅支持 workday、rest 或 holiday')
    shift_id = _clean(
        payload.get('shiftId') if 'shiftId' in payload or not existing else existing.shift_id,
    ) or None
    if day_type == 'workday':
        if not shift_id or not _tenant_row(AttendanceShift, tenant_id, shift_id):
            raise AttendancePolicyError('工作日排班必须选择当前企业的班次')
    else:
        shift_id = None
    duplicate_query = AttendanceSchedule.query.filter_by(
        tenant_id=tenant_id,
        employee_id=employee_id,
        schedule_date=schedule_date,
    )
    if existing:
        conflict = duplicate_query.filter(AttendanceSchedule.id != existing.id).first()
        if conflict:
            raise AttendancePolicyError('该员工该日期已有日排班', 'ATTENDANCE_POLICY_DATE_EXISTS')
        row = existing
    else:
        row = duplicate_query.first()
    if not row:
        row = AttendanceSchedule(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.session.add(row)
    row.employee_id = employee_id
    row.schedule_date = schedule_date
    row.day_type = day_type
    row.shift_id = shift_id
    source = payload.get('source') if 'source' in payload or not existing else row.source
    row.source = _clean(source or 'manual')[:30]
    row.remark = payload.get('remark') if 'remark' in payload or not existing else row.remark
    row.created_by = row.created_by or actor_id
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    return row


def remove_policy_row(model, tenant_id: str, row_id: str):
    row = model.query.filter_by(id=row_id, tenant_id=tenant_id).first()
    if not row:
        raise LookupError('policy row not found')
    if model is AttendanceShift:
        if AttendanceGroup.query.filter_by(tenant_id=tenant_id, default_shift_id=row.id).first() or AttendanceSchedule.query.filter_by(tenant_id=tenant_id, shift_id=row.id).first():
            raise AttendancePolicyError('该班次仍被考勤组或日排班使用，不能删除', 'ATTENDANCE_POLICY_IN_USE')
    elif model is AttendanceRuleSet:
        if AttendanceGroup.query.filter_by(tenant_id=tenant_id, default_rule_set_id=row.id).first():
            raise AttendancePolicyError('该规则仍被考勤组使用，不能删除', 'ATTENDANCE_POLICY_IN_USE')
    elif model is AttendanceGroup and AttendanceGroupMembership.query.filter_by(tenant_id=tenant_id, group_id=row.id).first():
        raise AttendancePolicyError('该考勤组仍有成员，不能删除')
    db.session.delete(row)
    return row


def policy_snapshot(tenant_id: str) -> dict:
    shifts = AttendanceShift.query.filter_by(tenant_id=tenant_id).order_by(AttendanceShift.status.desc(), AttendanceShift.code.asc()).all()
    rules = AttendanceRuleSet.query.filter_by(tenant_id=tenant_id).order_by(AttendanceRuleSet.status.desc(), AttendanceRuleSet.version.desc(), AttendanceRuleSet.code.asc()).all()
    groups = AttendanceGroup.query.filter_by(tenant_id=tenant_id).order_by(AttendanceGroup.status.desc(), AttendanceGroup.priority.desc(), AttendanceGroup.code.asc()).all()
    memberships = AttendanceGroupMembership.query.filter_by(tenant_id=tenant_id).order_by(AttendanceGroupMembership.created_at.asc()).all()
    holidays = AttendanceHoliday.query.filter_by(tenant_id=tenant_id).order_by(AttendanceHoliday.holiday_date.desc()).limit(500).all()
    schedules = AttendanceSchedule.query.filter_by(tenant_id=tenant_id).order_by(AttendanceSchedule.schedule_date.desc()).limit(500).all()
    return {
        'shifts': [row.to_dict() for row in shifts],
        'ruleSets': [row.to_dict() for row in rules],
        'groups': [row.to_dict() for row in groups],
        'memberships': [row.to_dict() for row in memberships],
        'holidays': [row.to_dict() for row in holidays],
        'schedules': [row.to_dict() for row in schedules],
    }


def _parse_range(start_value, end_value) -> tuple[date, date]:
    start = _as_date(start_value, field='开始日期', required=True)
    end = _as_date(end_value, field='结束日期', required=True)
    if end < start:
        raise AttendancePolicyError('结束日期不能早于开始日期')
    if (end - start).days > 366:
        raise AttendancePolicyError('单次重算最多支持 367 天')
    return start, end


def _time_for_day(day: date, value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.strptime(value, '%H:%M').time()
    return datetime.combine(day, parsed)


def _schedule_bounds(day: date, shift: AttendanceShift | None) -> tuple[datetime | None, datetime | None]:
    if not shift or shift.shift_type != 'fixed':
        return None, None
    start = _time_for_day(day, shift.start_time)
    end = _time_for_day(day, shift.end_time)
    if start and end and (shift.cross_day or end <= start):
        end += timedelta(days=1)
    return start, end


def _request_kind(request_type: str | None) -> str | None:
    raw = _clean(request_type).lower()
    if raw in {'leave', '请假', 'vacation', 'annual_leave', 'sick_leave', '调休', 'comp_time'}:
        return 'leave'
    if raw in {'travel', '出差'}:
        return 'travel'
    if raw in {'out_of_office', '外出'}:
        return 'out_of_office'
    if raw in {'makeup_card', '补卡'}:
        return 'makeup_card'
    if raw in {'overtime', '加班'}:
        return 'overtime'
    return None


def _coverage_intervals(
    requests: list[EmployeeRequest],
    start: datetime,
    end: datetime,
) -> tuple[list[tuple[datetime, datetime]], str | None, list[str]]:
    intervals = []
    request_ids = []
    labels = []
    for row in requests:
        if not row.start_time or not row.end_time:
            continue
        overlap_start = max(start, row.start_time)
        overlap_end = min(end, row.end_time)
        if overlap_end <= overlap_start:
            continue
        kind = _request_kind(row.request_type)
        if not kind or kind == 'overtime':
            continue
        intervals.append((overlap_start, overlap_end))
        request_ids.append(row.id)
        labels.append(kind)
    intervals.sort()
    merged = []
    for interval in intervals:
        if not merged or interval[0] > merged[-1][1]:
            merged.append(list(interval))
        else:
            merged[-1][1] = max(merged[-1][1], interval[1])
    label = next((item for item in ('travel', 'out_of_office', 'leave', 'makeup_card') if item in labels), None)
    return [(left, right) for left, right in merged], label, request_ids


def _merged_coverage(requests: list[EmployeeRequest], start: datetime, end: datetime) -> tuple[float, str | None, list[str]]:
    merged, label, request_ids = _coverage_intervals(requests, start, end)
    covered_seconds = sum((right - left).total_seconds() for left, right in merged)
    return covered_seconds, label, request_ids


def _uncovered_intervals(
    start: datetime,
    end: datetime,
    covered: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Return the portions of a scheduled window still requiring attendance."""
    cursor = start
    uncovered: list[tuple[datetime, datetime]] = []
    for left, right in covered:
        if right <= cursor:
            continue
        if left > cursor:
            uncovered.append((cursor, min(left, end)))
        cursor = max(cursor, right)
        if cursor >= end:
            break
    if cursor < end:
        uncovered.append((cursor, end))
    return [(left, right) for left, right in uncovered if right > left]


def _ceil_minutes(delta: timedelta) -> int:
    return max(0, int(ceil(delta.total_seconds() / 60)))


def _work_hours(first: datetime | None, last: datetime | None) -> Decimal | None:
    if not first or not last or last < first:
        return None
    return (Decimal(str((last - first).total_seconds())) / Decimal('3600')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _select_schedule_punches(
    raw_punches: list[AttendanceRawPunch],
    day: date,
    shift: AttendanceShift | None,
) -> list[AttendanceRawPunch]:
    """Keep only punches belonging to a cross-day fixed-shift window."""
    if not shift or shift.shift_type != 'fixed' or not shift.cross_day:
        return raw_punches
    scheduled_start, scheduled_end = _schedule_bounds(day, shift)
    if not scheduled_start or not scheduled_end:
        return raw_punches
    return [
        row for row in raw_punches
        if row.check_time and scheduled_start <= row.check_time <= scheduled_end
    ]


def _resolve_group(employee: Employee, day: date, groups: list[AttendanceGroup], memberships: list[AttendanceGroupMembership]):
    group_map = {row.id: row for row in groups if _effective(row, day)}
    candidates = []
    for membership in memberships:
        group = group_map.get(membership.group_id)
        if not group or not _effective(membership, day):
            continue
        specificity = 0
        if membership.employee_id and membership.employee_id == employee.id:
            specificity = 3
        elif membership.position_id and membership.position_id == employee.position_id:
            specificity = 2
        elif membership.department_id and membership.department_id == employee.department_id:
            specificity = 1
        if specificity:
            candidates.append((specificity, membership.priority or 0, group.priority or 0, group.code, group, membership))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[:4], reverse=True)
    _, _, _, _, group, membership = candidates[0]
    return group, membership


def _resolve_rule(group: AttendanceGroup | None, rules: list[AttendanceRuleSet], day: date) -> AttendanceRuleSet | None:
    if group and group.default_rule_set and _effective(group.default_rule_set, day):
        return group.default_rule_set
    active = [row for row in rules if _effective(row, day)]
    active.sort(key=lambda row: (row.version or 0, row.effective_from or date.min, row.code), reverse=True)
    return active[0] if active else None


def _resolve_schedule(
    employee: Employee,
    day: date,
    *,
    groups: list[AttendanceGroup],
    memberships: list[AttendanceGroupMembership],
    schedules: dict[tuple[str, date], AttendanceSchedule],
    holidays: dict[date, AttendanceHoliday],
    shifts_by_id: dict[str, AttendanceShift],
    rules: list[AttendanceRuleSet],
):
    group, membership = _resolve_group(employee, day, groups, memberships)
    rule = _resolve_rule(group, rules, day)
    explicit = schedules.get((employee.id, day))
    if explicit:
        shift = shifts_by_id.get(explicit.shift_id) if explicit.shift_id else None
        return {
            'day_type': explicit.day_type,
            'source': 'schedule',
            'group': group,
            'membership': membership,
            'shift': shift,
            'rule': rule,
            'remark': explicit.remark,
        }
    holiday = holidays.get(day)
    if holiday and holiday.day_type in {'holiday', 'company_rest'}:
        return {
            'day_type': 'holiday' if holiday.day_type == 'holiday' else 'rest',
            'source': 'holiday',
            'group': group,
            'membership': membership,
            'shift': None,
            'rule': rule,
            'remark': holiday.name,
        }
    if day.weekday() >= 5 and not (holiday and holiday.day_type == 'working_day'):
        return {
            'day_type': 'rest',
            'source': 'weekend',
            'group': group,
            'membership': membership,
            'shift': None,
            'rule': rule,
            'remark': '周末休息日',
        } if group else None
    if not group:
        return None
    shift = group.default_shift if group.default_shift and group.default_shift.status == 'active' else None
    return {
        'day_type': 'workday' if shift else 'unscheduled',
        'source': 'group',
        'group': group,
        'membership': membership,
        'shift': shift,
        'rule': rule,
        'remark': None if shift else '考勤组未配置默认班次',
    }


def _result_status_for_punches(
    shift: AttendanceShift,
    rule: AttendanceRuleSet | None,
    scheduled_start: datetime,
    scheduled_end: datetime,
    punch_times: list[datetime],
    require_check_in: bool | None = None,
    require_check_out: bool | None = None,
) -> tuple[str, int, int]:
    check_in_required = bool(shift.require_check_in) if require_check_in is None else bool(require_check_in)
    check_out_required = bool(shift.require_check_out) if require_check_out is None else bool(require_check_out)
    if not punch_times:
        absent_if_no_punch = rule.absent_if_no_punch if rule else True
        return ('absent' if absent_if_no_punch else 'missing_card'), 0, 0
    first = punch_times[0]
    last = punch_times[-1]
    missing_required = (
        len(punch_times) < int(check_in_required) + int(check_out_required)
    )
    if len(punch_times) == 1 and (rule.missing_card_if_single_punch if rule else True) and missing_required:
        grace_late = rule.late_grace_minutes if rule and rule.late_grace_minutes is not None else shift.late_grace_minutes or 0
        late = _ceil_minutes(first - (scheduled_start + timedelta(minutes=grace_late)))
        return 'missing_card', late, 0
    late_grace = rule.late_grace_minutes if rule and rule.late_grace_minutes is not None else shift.late_grace_minutes or 0
    early_grace = rule.early_leave_grace_minutes if rule and rule.early_leave_grace_minutes is not None else shift.early_leave_grace_minutes or 0
    late = _ceil_minutes(first - (scheduled_start + timedelta(minutes=late_grace))) if check_in_required else 0
    early = _ceil_minutes((scheduled_end - timedelta(minutes=early_grace)) - last) if check_out_required else 0
    if late and early:
        return 'late_early_leave', late, early
    if late:
        return 'late', late, 0
    if early:
        return 'early_leave', 0, early
    return 'normal', 0, 0


def _calculate_result_payload(
    employee: Employee,
    day: date,
    resolution: dict,
    *,
    raw_punches: list[AttendanceRawPunch],
    manual_record: AttendanceRecord | None,
    requests: list[EmployeeRequest],
    today: date,
) -> dict:
    group = resolution.get('group')
    shift = resolution.get('shift')
    rule = resolution.get('rule')
    day_type = resolution.get('day_type') or 'unscheduled'
    scheduled_start, scheduled_end = _schedule_bounds(day, shift)
    source_punch_ids = [row.id for row in raw_punches]
    punch_times = sorted(row.check_time for row in raw_punches if row.check_time)
    evidence_source = 'kaoqin' if raw_punches else None
    if not punch_times and manual_record:
        manual_times = [value for value in (manual_record.check_in_time, manual_record.check_out_time) if value]
        punch_times = sorted(manual_times)
        evidence_source = manual_record.source or 'attendance_records'
    coverage_seconds = 0.0
    coverage_intervals: list[tuple[datetime, datetime]] = []
    request_kind = None
    request_ids: list[str] = []
    if scheduled_start and scheduled_end:
        coverage_intervals, request_kind, request_ids = _coverage_intervals(requests, scheduled_start, scheduled_end)
        coverage_seconds = sum((right - left).total_seconds() for left, right in coverage_intervals)
    elif requests:
        request_ids = [row.id for row in requests if _request_kind(row.request_type) in {'leave', 'travel', 'out_of_office', 'makeup_card'}]
        request_kind = next((_request_kind(row.request_type) for row in requests if _request_kind(row.request_type) in {'travel', 'out_of_office', 'leave', 'makeup_card'}), None)

    explanation = {
        'calculationVersion': CALCULATION_VERSION,
        'dayType': day_type,
        'scheduleSource': resolution.get('source'),
        'scheduleRemark': resolution.get('remark'),
        'group': {'id': group.id, 'code': group.code, 'name': group.name} if group else None,
        'membership': membership_explanation(resolution.get('membership')),
        'shift': shift.to_dict() if shift else None,
        'ruleSet': rule.to_dict() if rule else None,
        'punchSource': evidence_source,
        'punchCount': len(punch_times),
        'requestIds': request_ids,
        'requestKind': request_kind,
        'approvedCoverageMinutes': _ceil_minutes(timedelta(seconds=coverage_seconds)),
        'approvedCoverageIntervals': [
            {'start': left.isoformat(), 'end': right.isoformat()}
            for left, right in coverage_intervals
        ],
    }
    payload = {
        'day_type': day_type,
        'schedule_source': resolution.get('source'),
        'group_id': group.id if group else None,
        'shift_id': shift.id if shift else None,
        'rule_set_id': rule.id if rule else None,
        'scheduled_start': scheduled_start,
        'scheduled_end': scheduled_end,
        'check_in_time': punch_times[0] if punch_times else None,
        'check_out_time': punch_times[-1] if len(punch_times) >= 2 else None,
        'work_hours': _work_hours(punch_times[0], punch_times[-1]) if len(punch_times) >= 2 else None,
        'status': 'unscheduled',
        'late_minutes': 0,
        'early_leave_minutes': 0,
        'source_punch_ids': source_punch_ids,
        'request_ids': request_ids,
        'explanation_json': explanation,
    }
    if day_type in {'rest', 'holiday'}:
        payload['status'] = day_type
        explanation['reason'] = resolution.get('remark') or ('休息日' if day_type == 'rest' else '节假日')
        return payload
    if not shift:
        payload['status'] = 'unscheduled'
        explanation['reason'] = resolution.get('remark') or '没有匹配到有效班次'
        return payload

    if shift.shift_type == 'flexible':
        if request_kind == 'makeup_card' and not punch_times:
            payload['status'] = 'makeup_card'
            explanation['reason'] = '已批准补卡申请'
            return payload
        if not punch_times:
            payload['status'] = 'pending' if day > today else ('absent' if (rule.absent_if_no_punch if rule else True) else 'missing_card')
            explanation['reason'] = '弹性班没有有效打卡'
            return payload
        if len(punch_times) < 2 and (rule.missing_card_if_single_punch if rule else True):
            payload['status'] = 'missing_card'
            explanation['reason'] = '弹性班只有一条打卡，无法计算实际工时'
            return payload
        required_hours = shift.required_work_hours or Decimal('0')
        actual_hours = payload['work_hours'] or Decimal('0')
        if actual_hours < required_hours:
            payload['status'] = 'short_hours'
            explanation['reason'] = f'实际工时 {actual_hours:.2f} 小于应出勤 {required_hours:.2f} 小时'
        else:
            payload['status'] = 'normal'
            explanation['reason'] = '弹性班实际工时达到要求'
        return payload

    if not scheduled_start or not scheduled_end:
        payload['status'] = 'unscheduled'
        explanation['reason'] = resolution.get('remark') or '没有匹配到有效班次时间'
        return payload

    scheduled_seconds = (scheduled_end - scheduled_start).total_seconds()
    full_coverage = coverage_seconds >= scheduled_seconds
    if full_coverage and request_kind in {'travel', 'out_of_office', 'leave'}:
        payload['status'] = request_kind
        explanation['reason'] = '已批准申请覆盖整个应出勤时段'
        return payload
    if request_kind == 'makeup_card' and not punch_times:
        payload['status'] = 'makeup_card'
        explanation['reason'] = '已批准补卡申请'
        return payload

    if not punch_times and day > today:
        payload['status'] = 'pending'
        explanation['reason'] = '未来工作日，等待打卡'
        return payload
    effective_start = scheduled_start
    effective_end = scheduled_end
    if coverage_intervals and not full_coverage:
        uncovered = _uncovered_intervals(scheduled_start, scheduled_end, coverage_intervals)
        if uncovered:
            effective_start = uncovered[0][0]
            effective_end = uncovered[-1][1]
            explanation['effectiveScheduledStart'] = effective_start.isoformat()
            explanation['effectiveScheduledEnd'] = effective_end.isoformat()
            explanation['reasonPrefix'] = f'已批准申请覆盖 {_ceil_minutes(timedelta(seconds=coverage_seconds))} 分钟；'
    status, late_minutes, early_minutes = _result_status_for_punches(
        shift,
        rule,
        effective_start,
        effective_end,
        punch_times,
    )
    payload['status'] = status
    payload['late_minutes'] = late_minutes
    payload['early_leave_minutes'] = early_minutes
    reason_prefix = explanation.get('reasonPrefix', '')
    if status == 'absent':
        explanation['reason'] = f'{reason_prefix}工作日没有有效打卡'
    elif status == 'missing_card':
        explanation['reason'] = f'{reason_prefix}固定班未满足上下班打卡要求'
    elif status == 'late_early_leave':
        explanation['reason'] = f'{reason_prefix}迟到 {late_minutes} 分钟，早退 {early_minutes} 分钟'
    elif status == 'late':
        explanation['reason'] = f'{reason_prefix}超过允许迟到时间 {late_minutes} 分钟'
    elif status == 'early_leave':
        explanation['reason'] = f'{reason_prefix}早于允许下班时间 {early_minutes} 分钟离岗'
    else:
        explanation['reason'] = f'{reason_prefix}上下班打卡均在规则范围内'
    return payload


def membership_explanation(membership: AttendanceGroupMembership | None) -> dict | None:
    if not membership:
        return None
    return {
        'id': membership.id,
        'scopeType': 'employee' if membership.employee_id else 'department' if membership.department_id else 'position' if membership.position_id else None,
        'scopeId': membership.employee_id or membership.department_id or membership.position_id,
        'priority': membership.priority or 0,
    }


def recalculate_daily_results(
    tenant_id: str,
    start_value,
    end_value,
    *,
    employee_id: str | None = None,
) -> dict:
    start, end = _parse_range(start_value, end_value)
    employee_query = Employee.query.filter(
        Employee.tenant_id == tenant_id,
        Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
    )
    if employee_id:
        employee_query = employee_query.filter(Employee.id == employee_id)
    employees = employee_query.order_by(Employee.name.asc(), Employee.id.asc()).all()
    if employee_id and not employees:
        raise LookupError('employee not found')
    if not employees:
        return {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'employees': 0, 'days': 0, 'created': 0, 'updated': 0, 'deleted': 0, 'statusCounts': {}}

    shifts = AttendanceShift.query.filter_by(tenant_id=tenant_id).all()
    shifts_by_id = {row.id: row for row in shifts if row.status == 'active'}
    rules = AttendanceRuleSet.query.filter_by(tenant_id=tenant_id).all()
    groups = AttendanceGroup.query.filter_by(tenant_id=tenant_id).all()
    memberships = AttendanceGroupMembership.query.filter_by(tenant_id=tenant_id).all()
    holidays = {
        row.holiday_date: row
        for row in AttendanceHoliday.query.filter(
            AttendanceHoliday.tenant_id == tenant_id,
            AttendanceHoliday.holiday_date >= start,
            AttendanceHoliday.holiday_date <= end,
            AttendanceHoliday.status == 'active',
        ).all()
    }
    schedules = {
        (row.employee_id, row.schedule_date): row
        for row in AttendanceSchedule.query.filter(
            AttendanceSchedule.tenant_id == tenant_id,
            AttendanceSchedule.employee_id.in_([row.id for row in employees]),
            AttendanceSchedule.schedule_date >= start,
            AttendanceSchedule.schedule_date <= end,
        ).all()
    }
    mappings = AttendanceExternalPerson.query.filter(
        AttendanceExternalPerson.tenant_id == tenant_id,
        AttendanceExternalPerson.mapping_status == 'confirmed',
        AttendanceExternalPerson.employee_id.in_([row.id for row in employees]),
    ).all()
    employee_by_external = {row.external_user_id: row.employee_id for row in mappings if row.employee_id}
    raw_by_employee_day: dict[tuple[str, date], list[AttendanceRawPunch]] = defaultdict(list)
    if employee_by_external:
        raw_rows = AttendanceRawPunch.query.filter(
            AttendanceRawPunch.tenant_id == tenant_id,
            AttendanceRawPunch.external_user_id.in_(list(employee_by_external.keys())),
            AttendanceRawPunch.check_time >= datetime.combine(start - timedelta(days=1), time.min),
            AttendanceRawPunch.check_time < datetime.combine(end + timedelta(days=2), time.min),
        ).order_by(AttendanceRawPunch.check_time.asc()).all()
        for row in raw_rows:
            mapped_employee_id = employee_by_external.get(row.external_user_id)
            if mapped_employee_id:
                raw_by_employee_day[(mapped_employee_id, row.check_time.date())].append(row)
    manual_by_employee_day = {
        (row.employee_id, row.attendance_date): row
        for row in AttendanceRecord.query.join(Employee, AttendanceRecord.employee_id == Employee.id).filter(
            Employee.tenant_id == tenant_id,
            AttendanceRecord.employee_id.in_([item.id for item in employees]),
            AttendanceRecord.attendance_date >= start,
            AttendanceRecord.attendance_date <= end,
        ).all()
    }
    requests_by_employee: dict[str, list[EmployeeRequest]] = defaultdict(list)
    request_rows = EmployeeRequest.query.execution_options(skip_tenant_criteria=True).join(
        Employee,
        EmployeeRequest.employee_id == Employee.id,
    ).filter(
        Employee.tenant_id == tenant_id,
        or_(EmployeeRequest.tenant_id == tenant_id, EmployeeRequest.tenant_id.is_(None)),
        EmployeeRequest.employee_id.in_([row.id for row in employees]),
        EmployeeRequest.status == 'approved',
        EmployeeRequest.start_time < datetime.combine(end + timedelta(days=2), time.min),
        EmployeeRequest.end_time > datetime.combine(start - timedelta(days=1), time.min),
    ).all()
    for row in request_rows:
        requests_by_employee[row.employee_id].append(row)

    existing_rows = AttendanceDailyResult.query.filter(
        AttendanceDailyResult.tenant_id == tenant_id,
        AttendanceDailyResult.employee_id.in_([row.id for row in employees]),
        AttendanceDailyResult.attendance_date >= start,
        AttendanceDailyResult.attendance_date <= end,
    ).all()
    existing_by_key = {(row.employee_id, row.attendance_date): row for row in existing_rows}
    produced_keys = set()
    status_counts: dict[str, int] = defaultdict(int)
    created = 0
    updated = 0
    today = date.today()

    current = start
    while current <= end:
        for employee in employees:
            raw = list(raw_by_employee_day.get((employee.id, current), []))
            manual = manual_by_employee_day.get((employee.id, current))
            resolution = _resolve_schedule(
                employee,
                current,
                groups=groups,
                memberships=memberships,
                schedules=schedules,
                holidays=holidays,
                shifts_by_id=shifts_by_id,
                rules=rules,
            )
            if resolution and resolution.get('shift') and resolution['shift'].cross_day:
                raw.extend(raw_by_employee_day.get((employee.id, current + timedelta(days=1)), []))
            raw = _select_schedule_punches(
                raw,
                current,
                resolution.get('shift') if resolution else None,
            )
            employee_requests = requests_by_employee.get(employee.id, [])
            has_evidence = bool(raw or manual or employee_requests)
            if resolution is None and not has_evidence:
                continue
            if resolution is None:
                resolution = {
                    'day_type': 'unscheduled',
                    'source': 'evidence',
                    'group': None,
                    'membership': None,
                    'shift': None,
                    'rule': _resolve_rule(None, rules, current),
                    'remark': '存在考勤或审批事实，但未配置考勤组',
                }
            payload = _calculate_result_payload(
                employee,
                current,
                resolution,
                raw_punches=sorted({row.id: row for row in raw}.values(), key=lambda row: row.check_time),
                manual_record=manual,
                requests=employee_requests,
                today=today,
            )
            key = (employee.id, current)
            produced_keys.add(key)
            row = existing_by_key.get(key)
            if row is None:
                row = AttendanceDailyResult(
                    id=_stable_daily_id(tenant_id, employee.id, current),
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    attendance_date=current,
                )
                db.session.add(row)
                created += 1
            else:
                updated += 1
            for field, value in payload.items():
                setattr(row, field, value)
            row.calculation_version = CALCULATION_VERSION
            row.calculated_at = datetime.utcnow()
            status_counts[row.status] += 1
        current += timedelta(days=1)

    deleted = 0
    for key, row in existing_by_key.items():
        if key not in produced_keys:
            db.session.delete(row)
            deleted += 1
    db.session.flush()
    return {
        'startDate': start.isoformat(),
        'endDate': end.isoformat(),
        'employeeId': employee_id,
        'employees': len(employees),
        'days': (end - start).days + 1,
        'created': created,
        'updated': updated,
        'deleted': deleted,
        'statusCounts': dict(sorted(status_counts.items())),
    }


def list_daily_results(tenant_id: str, *, start_value=None, end_value=None, employee_id: str | None = None, status: str | None = None, limit: int = 500) -> list[AttendanceDailyResult]:
    query = AttendanceDailyResult.query.filter_by(tenant_id=tenant_id)
    if start_value:
        start = _as_date(start_value, field='开始日期', required=True)
        query = query.filter(AttendanceDailyResult.attendance_date >= start)
    if end_value:
        end = _as_date(end_value, field='结束日期', required=True)
        query = query.filter(AttendanceDailyResult.attendance_date <= end)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    if status:
        query = query.filter_by(status=_clean(status))
    return query.order_by(AttendanceDailyResult.attendance_date.desc(), AttendanceDailyResult.employee_id.asc()).limit(max(1, min(limit, 1000))).all()
