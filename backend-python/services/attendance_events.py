"""OA 考勤单据落库与查询。

把 OA 请假/加班/补卡/调休/外出/出差单据同步到本地 `attendance_events`，
供考勤归属计算与页面展示使用。幂等：按 (tenant_id, source_key) upsert。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from models import AttendanceEvent, Employee, db
from services.oa_attendance_docs import OaAttendanceDoc, OaAttendanceDocClient


def _first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def _shift_months(value: date, delta: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + delta
    year, month = divmod(month_index, 12)
    return date(year, month + 1, 1)


def sync_attendance_events(
    tenant_id: str,
    *,
    months: int = 12,
    doc_client: OaAttendanceDocClient | None = None,
    now: datetime | None = None,
) -> dict:
    """同步近 N 个月的 OA 考勤单据。"""
    moment = now or datetime.utcnow()
    start = _shift_months(_first_day_of_month(moment.date()), -(max(1, int(months)) - 1))
    end = _shift_months(_first_day_of_month(moment.date()), 1)

    client = doc_client or OaAttendanceDocClient.from_environment()
    documents = client.fetch_documents(start, end)

    employees = Employee.query.filter(Employee.tenant_id == tenant_id).all()
    by_no: dict[str, Employee] = {}
    by_person: dict[str, Employee] = {}
    for employee in employees:
        if employee.employee_no:
            by_no.setdefault(str(employee.employee_no).strip().lstrip('0') or '0', employee)
        if employee.oa_person_id:
            by_person.setdefault(str(employee.oa_person_id).strip(), employee)

    existing = {
        row.source_key: row
        for row in AttendanceEvent.query.filter(AttendanceEvent.tenant_id == tenant_id).all()
    }

    created = updated = unmatched = 0
    by_type: dict[str, int] = {}
    synced_at = datetime.utcnow()
    for doc in documents:
        by_type[doc.event_type] = by_type.get(doc.event_type, 0) + 1
        employee = _match_employee(doc, by_no, by_person)
        if employee is None:
            unmatched += 1
        row = existing.get(doc.source_key)
        if row is None:
            row = AttendanceEvent(
                id=str(uuid.uuid4()), tenant_id=tenant_id, source_key=doc.source_key,
            )
            db.session.add(row)
            existing[doc.source_key] = row
            created += 1
        else:
            updated += 1
        _apply(row, doc, employee, synced_at)

    db.session.flush()
    return {
        'start': start.isoformat(),
        'end': end.isoformat(),
        'months': max(1, int(months)),
        'fetched': len(documents),
        'created': created,
        'updated': updated,
        'unmatched': unmatched,
        'byType': by_type,
    }


def _match_employee(
    doc: OaAttendanceDoc,
    by_no: dict[str, Employee],
    by_person: dict[str, Employee],
) -> Employee | None:
    if doc.employee_no:
        key = str(doc.employee_no).strip().lstrip('0') or '0'
        employee = by_no.get(key)
        if employee is not None:
            return employee
    if doc.oa_person_id:
        return by_person.get(str(doc.oa_person_id).strip())
    return None


def _apply(row: AttendanceEvent, doc: OaAttendanceDoc, employee: Employee | None, synced_at: datetime) -> None:
    row.event_type = doc.event_type
    row.employee_id = employee.id if employee else None
    row.employee_no = doc.employee_no
    row.employee_name = employee.name if employee else None
    row.oa_person_id = doc.oa_person_id
    row.oa_department_id = doc.oa_department_id
    row.start_at = doc.start_at
    row.end_at = doc.end_at
    row.hours = doc.hours
    row.subtype = doc.subtype
    row.reason = doc.reason
    row.status = 'approved'
    row.affects_hours = doc.affects_hours
    row.oa_request_id = doc.oa_request_id
    row.oa_workflow_id = doc.oa_workflow_id
    row.oa_form_table = doc.oa_form_table
    row.oa_main_id = doc.oa_main_id
    row.source = 'oa_workflow'
    row.synced_at = synced_at
    row.updated_at = datetime.utcnow()


def events_for_range(
    tenant_id: str,
    start: date,
    end: date,
    *,
    event_types: tuple[str, ...] | None = None,
) -> list[AttendanceEvent]:
    """取与 [start, end] 有交集的单据（含跨天）。"""
    start_dt = datetime.combine(start, time(0, 0))
    end_dt = datetime.combine(end, time(23, 59, 59))
    query = AttendanceEvent.query.filter(
        AttendanceEvent.tenant_id == tenant_id,
        AttendanceEvent.start_at.isnot(None),
        AttendanceEvent.start_at <= end_dt,
        db.or_(AttendanceEvent.end_at.is_(None), AttendanceEvent.end_at >= start_dt),
    )
    if event_types:
        query = query.filter(AttendanceEvent.event_type.in_(event_types))
    return query.all()


def list_events(
    tenant_id: str,
    *,
    month: str | None = None,
    event_type: str | None = None,
    keyword: str | None = None,
    employee_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int | None = None,
    size: int = 50,
):
    query = AttendanceEvent.query.filter(AttendanceEvent.tenant_id == tenant_id)
    if month:
        start = _first_day_of_month(date.fromisoformat(f'{month}-01'))
        end = _shift_months(start, 1) - timedelta(days=1)
        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        query = query.filter(
            AttendanceEvent.start_at.isnot(None),
            AttendanceEvent.start_at <= end_dt,
            db.or_(AttendanceEvent.end_at.is_(None), AttendanceEvent.end_at >= start_dt),
        )
    if start_date or end_date:
        window_start = start_date or end_date
        window_end = end_date or start_date
        start_dt = datetime.combine(window_start, time(0, 0))
        end_dt = datetime.combine(window_end, time(23, 59, 59))
        query = query.filter(
            AttendanceEvent.start_at.isnot(None),
            AttendanceEvent.start_at <= end_dt,
            db.or_(AttendanceEvent.end_at.is_(None), AttendanceEvent.end_at >= start_dt),
        )
    if employee_id:
        query = query.filter(AttendanceEvent.employee_id == employee_id)
    if event_type:
        query = query.filter(AttendanceEvent.event_type == event_type)
    if keyword:
        kw = keyword.strip()
        if kw:
            query = query.filter(db.or_(
                AttendanceEvent.employee_name.like(f'%{kw}%'),
                AttendanceEvent.employee_no.like(f'%{kw}%'),
            ))
    query = query.order_by(AttendanceEvent.start_at.asc(), AttendanceEvent.id.asc())
    if not page:
        return query.limit(2000).all()
    page = max(1, int(page))
    size = max(1, min(int(size or 50), 200))
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return items, total, page, size


@dataclass
class EmployeeDayEvents:
    """某员工某天的相关单据（已按类型归集）。"""

    deduct_windows: list[tuple[datetime, datetime]]
    cover_windows: list[tuple[datetime, datetime]]
    overtime_hours: float
    labels: list[str]


def day_events_for_employee(
    events: list[AttendanceEvent],
    work_date: date,
) -> EmployeeDayEvents:
    """把员工单据折算为某考勤日的时间窗与加班时长。"""
    day_start = datetime.combine(work_date, time(0, 0))
    day_end = day_start + timedelta(days=1)
    deduct: list[tuple[datetime, datetime]] = []
    cover: list[tuple[datetime, datetime]] = []
    overtime = 0.0
    labels: list[str] = []
    for event in events:
        start = event.start_at
        end = event.end_at or event.start_at
        if start is None or end is None:
            continue
        if not (start < day_end and end >= day_start):
            continue
        if event.event_type in ('leave', 'compensatory'):
            deduct.append((start, end if end > start else start))
            labels.append('请假' if event.event_type == 'leave' else '调休')
        elif event.event_type == 'overtime':
            overtime += float(event.hours or 0)
            labels.append('加班')
        elif event.event_type == 'punch_fix':
            labels.append('补卡')
        elif event.event_type in ('outing', 'business_trip'):
            cover.append((start, end))
            labels.append('外出' if event.event_type == 'outing' else '出差')
    return EmployeeDayEvents(
        deduct_windows=deduct,
        cover_windows=cover,
        overtime_hours=overtime,
        labels=labels,
    )
