"""日考勤明细：生成、查询、人工校对。

生成逻辑：OA 排班（不落库）+ 打卡机原始打卡 → 按 后勤/车间 规则归属到每天。
校对逻辑：人工可改上下班时间/状态/工时，首次修改自动留存原值快照。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from models import (
    AttendanceExternalPerson,
    AttendanceRawPunch,
    AttendanceTimesheet,
    Employee,
    db,
)
from services.attendance_attribution import (
    OFFICE,
    assign_punches_to_dates,
    attribute_person_month,
    expected_points_by_date,
)
from services.attendance_events import day_events_for_employee, events_for_range
from services.oa_schedule import OaScheduleClient

ACTIVE_EMPLOYEE_STATUSES = ('active', 'probation')


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(part) for part in month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    return start, end - timedelta(days=1)


def _parse_datetime(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip().replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError('时间格式无效') from exc
    # 系统内统一使用无时区的本地时间；带时区时按本地墙钟直接取值，避免时区偏移
    return parsed.replace(tzinfo=None)


def generate_timesheets(
    tenant_id: str,
    month: str,
    *,
    schedule_client: OaScheduleClient | None = None,
    overwrite_manual: bool = False,
) -> dict:
    """按月生成/刷新日考勤明细。"""
    month_start, month_end = _month_bounds(month)
    client = schedule_client or OaScheduleClient.from_environment()
    worktimes = client.fetch_worktimes()
    schedule_days = client.fetch_schedule(month_start, month_end)

    schedule_by_person: dict[int, list] = {}
    for day in schedule_days:
        schedule_by_person.setdefault(day.person_id, []).append(day)

    employees = Employee.query.filter(
        Employee.tenant_id == tenant_id,
        Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
    ).all()

    mappings = {
        person.employee_id: str(person.external_user_id)
        for person in AttendanceExternalPerson.query.filter_by(
            tenant_id=tenant_id, mapping_status='confirmed',
        ).all()
        if person.employee_id
    }

    start_dt = datetime.combine(month_start, dt_time(0, 0)) - timedelta(days=1)
    end_dt = datetime.combine(month_end, dt_time(0, 0)) + timedelta(days=2)
    punches_by_external: dict[str, list[datetime]] = {}
    for punch in AttendanceRawPunch.query.filter(
        AttendanceRawPunch.tenant_id == tenant_id,
        AttendanceRawPunch.check_time >= start_dt,
        AttendanceRawPunch.check_time < end_dt,
    ).all():
        punches_by_external.setdefault(str(punch.external_user_id), []).append(punch.check_time)

    existing_rows = {
        (row.employee_id, row.work_date): row
        for row in AttendanceTimesheet.query.filter(
            AttendanceTimesheet.tenant_id == tenant_id,
            AttendanceTimesheet.work_date >= month_start,
            AttendanceTimesheet.work_date <= month_end,
        ).all()
    }

    events_by_employee: dict[str, list] = {}
    for event in events_for_range(tenant_id, month_start, month_end):
        if event.employee_id:
            events_by_employee.setdefault(event.employee_id, []).append(event)

    created = updated = skipped = 0
    month_dates = set()
    cursor = month_start
    while cursor <= month_end:
        month_dates.add(cursor)
        cursor += timedelta(days=1)

    for employee in employees:
        person_id = int(employee.oa_person_id) if (employee.oa_person_id or '').isdigit() else None
        employee_schedule = schedule_by_person.get(person_id, []) if person_id else []
        employee_type = employee.employee_type or OFFICE
        external_id = mappings.get(employee.id)
        punches = sorted(punches_by_external.get(external_id, [])) if external_id else []

        employee_events = events_by_employee.get(employee.id, [])
        fix_punches = [
            event.start_at for event in employee_events
            if event.event_type == 'punch_fix' and event.start_at is not None
        ]
        fix_set = set(fix_punches)
        if fix_punches:
            punches = sorted(set(punches) | fix_set)
        day_contexts = {
            work_date: day_events_for_employee(employee_events, work_date)
            for work_date in month_dates
        }

        points_by_date = expected_points_by_date(employee_schedule, worktimes, employee_type)
        buckets = assign_punches_to_dates(
            punches, points_by_date, extra_dates=month_dates,
        )

        results = attribute_person_month(
            employee_type=employee_type,
            person_id=person_id or 0,
            month_start=month_start,
            month_end=month_end,
            schedule_days=employee_schedule,
            worktime_map=worktimes,
            punches_by_date=buckets,
            day_contexts=day_contexts,
            fix_punches=fix_punches,
        )
        for day in results:
            key = (employee.id, day.work_date)
            row = existing_rows.get(key)
            if row and row.manual_corrected and not overwrite_manual:
                skipped += 1
                continue
            payload = {
                'department_id': employee.department_id,
                'employee_type': employee.employee_type,
                'worktime_ids': ';'.join(str(wid) for wid in day.worktime_ids) or None,
                'check_in': day.check_in,
                'check_out': day.check_out,
                'check_in_fixed': day.check_in_fixed,
                'check_out_fixed': day.check_out_fixed,
                'punch_times': [
                    {'t': punch.isoformat(), 'fix': punch in fix_set}
                    for punch in day.punch_times
                ],
                'work_hours': day.work_hours,
                'overtime_hours': day.overtime_hours,
                'leave_hours': day.leave_hours,
                'event_summary': ';'.join(day.event_labels) or None,
                'expected_punches': len(day.expected_points),
                'actual_punches': day.actual_punches,
                'missing_count': day.missing_points,
                'status': day.status,
                'source': 'oa_schedule',
            }
            if row is None:
                row = AttendanceTimesheet(
                    id=str(uuid.uuid4()), tenant_id=tenant_id,
                    employee_id=employee.id, work_date=day.work_date,
                )
                db.session.add(row)
                existing_rows[key] = row
                created += 1
            else:
                updated += 1
            for field, value in payload.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()

    return {'month': month, 'created': created, 'updated': updated, 'skippedManual': skipped}


def list_timesheets(
    tenant_id: str,
    *,
    month: str | None = None,
    employee_id: str | None = None,
    keyword: str | None = None,
    department_id: str | None = None,
    status: str | None = None,
    work_date: date | None = None,
    employee_type: str | None = None,
    has_overtime: bool | None = None,
    has_leave: bool | None = None,
    has_event: bool | None = None,
    min_work_hours: float | None = None,
    page: int | None = None,
    size: int = 50,
    limit: int = 2000,
):
    query = AttendanceTimesheet.query.filter(AttendanceTimesheet.tenant_id == tenant_id)
    if month:
        start, end = _month_bounds(month)
        query = query.filter(
            AttendanceTimesheet.work_date >= start,
            AttendanceTimesheet.work_date <= end,
        )
    if work_date:
        query = query.filter(AttendanceTimesheet.work_date == work_date)
    if employee_id:
        query = query.filter(AttendanceTimesheet.employee_id == employee_id)
    if employee_type:
        query = query.filter(AttendanceTimesheet.employee_type == employee_type)
    if has_overtime is True:
        query = query.filter(AttendanceTimesheet.overtime_hours > 0)
    elif has_overtime is False:
        query = query.filter(db.or_(AttendanceTimesheet.overtime_hours.is_(None), AttendanceTimesheet.overtime_hours <= 0))
    if has_leave is True:
        query = query.filter(AttendanceTimesheet.leave_hours > 0)
    elif has_leave is False:
        query = query.filter(db.or_(AttendanceTimesheet.leave_hours.is_(None), AttendanceTimesheet.leave_hours <= 0))
    if has_event is True:
        query = query.filter(AttendanceTimesheet.event_summary.isnot(None), AttendanceTimesheet.event_summary != '')
    elif has_event is False:
        query = query.filter(db.or_(AttendanceTimesheet.event_summary.is_(None), AttendanceTimesheet.event_summary == ''))
    if min_work_hours is not None:
        try:
            query = query.filter(AttendanceTimesheet.work_hours >= Decimal(str(min_work_hours)))
        except (InvalidOperation, ValueError):
            pass
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
                return ([], 0, 1, max(1, min(int(size or 50), 200))) if page else []
            query = query.filter(AttendanceTimesheet.employee_id.in_(matched_ids))
    if department_id:
        query = query.filter(AttendanceTimesheet.department_id == department_id)
    if status:
        query = query.filter(AttendanceTimesheet.status == status)
    query = query.order_by(
        AttendanceTimesheet.work_date.asc(), AttendanceTimesheet.employee_id.asc(),
    )
    if not page:
        return query.limit(max(1, int(limit))).all()
    page = max(1, int(page))
    size = max(1, min(int(size or 50), 200))
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return items, total, page, size


def correct_timesheet(
    timesheet_id: str,
    *,
    tenant_id: str | None = None,
    check_in=None,
    check_out=None,
    status: str | None = None,
    work_hours=None,
    remark: str | None = None,
    actor_user_id: str | None = None,
) -> AttendanceTimesheet:
    """人工校对一条日考勤明细；首次修改留存原值快照。"""
    query = AttendanceTimesheet.query.filter(AttendanceTimesheet.id == timesheet_id)
    if tenant_id:
        query = query.filter(AttendanceTimesheet.tenant_id == tenant_id)
    row = query.first()
    if row is None:
        raise LookupError('TIMESHEET_NOT_FOUND')

    if not row.manual_corrected:
        row.original_snapshot = {
            'checkIn': row.check_in.isoformat() if row.check_in else None,
            'checkOut': row.check_out.isoformat() if row.check_out else None,
            'status': row.status,
            'workHours': str(row.work_hours) if row.work_hours is not None else None,
            'remark': row.remark,
        }

    if check_in is not None:
        row.check_in = _parse_datetime(check_in)
    if check_out is not None:
        row.check_out = _parse_datetime(check_out)
    if status:
        row.status = status
    if remark is not None:
        row.remark = remark

    if work_hours is not None and work_hours != '':
        row.work_hours = Decimal(str(work_hours))
    elif row.check_in and row.check_out:
        minutes = max(0, int((row.check_out - row.check_in).total_seconds() // 60))
        row.work_hours = (Decimal(minutes) / Decimal(60)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    row.manual_corrected = True
    row.corrected_by = actor_user_id
    row.corrected_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    return row
