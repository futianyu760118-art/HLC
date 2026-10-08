"""00001 company attendance-machine punch synchronization.

The external SQL Server is a strictly read-only source. This module only runs
fixed SELECT statements against Kaoqin and writes staging rows to HRM MySQL.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

import pymssql
from sqlalchemy import text

from models import (
    AttendanceExternalPerson,
    AttendanceRawPunch,
    AttendanceRecord,
    AttendanceSyncRun,
    Employee,
    OperationLog,
    Tenant,
    User,
    db,
)


logger = logging.getLogger('hengpintong.attendance_punch_sync')

ATTENDANCE_TENANT_SLUG = 'HPT-00000001'
ATTENDANCE_SOURCE_SYSTEM = 'kaoqin'
OA_SOURCE_SYSTEM = 'oa_ecology'
ATTENDANCE_SYNC_LOCK_NAME = 'hengpintong:attendance-punch-sync:HPT-00000001'
DEFAULT_LOOKBACK_DAYS = 90
INCREMENTAL_LOOKBACK_DAYS = 2

_running = False


class AttendanceSyncDisabled(RuntimeError):
    pass


class AttendanceSyncBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalPersonRow:
    external_user_id: int
    badge_number: str
    name: str
    department_name: str


@dataclass(frozen=True)
class AttendancePunchRow:
    external_user_id: int
    check_time: datetime
    check_type: str
    verify_code: int | str | None
    sensor_id: str
    serial_number: str


@dataclass(frozen=True)
class AttendanceSyncResult:
    run_id: str
    people_read: int
    people_upserted: int
    punches_read: int
    punches_inserted: int
    punches_duplicate: int
    unmatched_count: int
    suggested_count: int
    confirmed_count: int
    daily_records_upserted: int


def _clean(value) -> str:
    if value is None:
        return ''
    if isinstance(value, bytes):
        for encoding in ('cp936', 'gbk', 'utf-8'):
            try:
                return value.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return value.decode('cp936', errors='replace').strip()
    return str(value).strip()


def _normalize_name(value) -> str:
    return re.sub(r'\s+', '', _clean(value)).casefold()


def _stable_id(namespace: str, tenant_id: str, external_id: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'hengpintong:{namespace}:{tenant_id}:{external_id}'))


def punch_fingerprint(row: AttendancePunchRow) -> str:
    check_time = row.check_time.strftime('%Y-%m-%d %H:%M:%S') if row.check_time else ''
    raw = '|'.join([
        str(row.external_user_id),
        check_time,
        _clean(row.check_type),
        _clean(row.verify_code),
        _clean(row.sensor_id),
        _clean(row.serial_number),
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def credentials_configured() -> bool:
    return bool(os.getenv('ATTENDANCE_DB_HOST') and os.getenv('ATTENDANCE_DB_USER') and os.getenv('ATTENDANCE_DB_PASSWORD'))


class AttendanceReadOnlyClient:
    """Execute fixed Kaoqin SELECTs in a rollback-only transaction."""

    PEOPLE_SELECT = """
        SELECT
            u.USERID AS external_user_id,
            u.BADGENUMBER AS badge_number,
            u.NAME AS person_name,
            d.DEPTNAME AS department_name
        FROM dbo.USERINFO u
        LEFT JOIN dbo.DEPARTMENTS d ON d.DEPTID = u.DEFAULTDEPTID
        ORDER BY u.USERID
    """

    PUNCH_SELECT = """
        SELECT
            USERID AS external_user_id,
            CHECKTIME AS check_time,
            CHECKTYPE AS check_type,
            VERIFYCODE AS verify_code,
            SENSORID AS sensor_id,
            sn AS serial_number
        FROM dbo.CHECKINOUT
        WHERE CHECKTIME >= %s
        ORDER BY CHECKTIME, USERID
    """

    def __init__(self, *, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database

    @classmethod
    def from_environment(cls) -> 'AttendanceReadOnlyClient':
        required = {
            'host': os.getenv('ATTENDANCE_DB_HOST'),
            'user': os.getenv('ATTENDANCE_DB_USER'),
            'password': os.getenv('ATTENDANCE_DB_PASSWORD'),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise AttendanceSyncDisabled('Attendance sync credentials are not configured')
        return cls(
            host=required['host'],
            port=int(os.getenv('ATTENDANCE_DB_PORT', '2807')),
            user=required['user'],
            password=required['password'],
            database=os.getenv('ATTENDANCE_DB_NAME', 'Kaoqin'),
        )

    def _connect(self):
        return pymssql.connect(
            server=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset='CP936',
            tds_version='7.0',
            login_timeout=8,
            timeout=60,
            autocommit=False,
        )

    def fetch_people(self) -> list[ExternalPersonRow]:
        connection = self._connect()
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute('SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED')
            cursor.execute(self.PEOPLE_SELECT)
            return [self._to_person(row) for row in cursor.fetchall()]
        finally:
            connection.rollback()
            connection.close()

    def fetch_punches(self, *, since: datetime) -> list[AttendancePunchRow]:
        connection = self._connect()
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute('SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED')
            cursor.execute(self.PUNCH_SELECT, (since,))
            return [self._to_punch(row) for row in cursor.fetchall()]
        finally:
            connection.rollback()
            connection.close()

    @staticmethod
    def _to_person(row: dict) -> ExternalPersonRow:
        return ExternalPersonRow(
            external_user_id=int(row['external_user_id']),
            badge_number=_clean(row.get('badge_number')),
            name=_clean(row.get('person_name')),
            department_name=_clean(row.get('department_name')),
        )

    @staticmethod
    def _to_punch(row: dict) -> AttendancePunchRow:
        return AttendancePunchRow(
            external_user_id=int(row['external_user_id']),
            check_time=row['check_time'],
            check_type=_clean(row.get('check_type')),
            verify_code=row.get('verify_code'),
            sensor_id=_clean(row.get('sensor_id')),
            serial_number=_clean(row.get('serial_number')),
        )


def _get_sync_tenant(tenant_slug: str) -> Tenant:
    if tenant_slug != ATTENDANCE_TENANT_SLUG:
        raise AttendanceSyncDisabled('Attendance punch sync is only enabled for HPT-00000001')
    tenant = Tenant.query.filter_by(slug=tenant_slug).first()
    if not tenant:
        raise AttendanceSyncDisabled('Attendance sync tenant does not exist')
    return tenant


@contextmanager
def _sync_lock():
    if not db.engine.dialect.name.startswith('mysql'):
        yield
        return
    connection = db.engine.connect()
    try:
        acquired = connection.execute(
            text('SELECT GET_LOCK(:name, 0)'), {'name': ATTENDANCE_SYNC_LOCK_NAME}
        ).scalar()
        if acquired != 1:
            raise AttendanceSyncBusy('Attendance punch sync is already running')
        yield
    finally:
        try:
            connection.execute(
                text('SELECT RELEASE_LOCK(:name)'), {'name': ATTENDANCE_SYNC_LOCK_NAME}
            )
        finally:
            connection.close()


def _lookback_days() -> int:
    try:
        return max(1, int(os.getenv('ATTENDANCE_SYNC_LOOKBACK_DAYS', str(DEFAULT_LOOKBACK_DAYS))))
    except ValueError:
        return DEFAULT_LOOKBACK_DAYS


def _punch_since(tenant: Tenant) -> datetime:
    latest = (
        AttendanceSyncRun.query.filter_by(tenant_id=tenant.id, status='success')
        .order_by(AttendanceSyncRun.completed_at.desc())
        .first()
    )
    if latest and latest.cursor_check_time:
        return latest.cursor_check_time - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
    return datetime.utcnow() - timedelta(days=_lookback_days())


def _suggest_employee_ids(tenant: Tenant, rows: list[ExternalPersonRow]) -> dict[int, str]:
    confirmed = {
        person.employee_id
        for person in AttendanceExternalPerson.query.filter_by(tenant_id=tenant.id, mapping_status='confirmed').all()
        if person.employee_id
    }
    employees = Employee.query.filter_by(tenant_id=tenant.id).all()
    by_name: dict[str, list[Employee]] = {}
    by_employee_no: dict[str, list[Employee]] = {}
    for employee in employees:
        if employee.id in confirmed:
            continue
        key = _normalize_name(employee.name)
        if key:
            by_name.setdefault(key, []).append(employee)
        employee_no = _clean(employee.employee_no)
        if employee_no:
            by_employee_no.setdefault(employee_no, []).append(employee)

    external_by_name: dict[str, list[ExternalPersonRow]] = {}
    external_by_badge: dict[str, list[ExternalPersonRow]] = {}
    for row in rows:
        key = _normalize_name(row.name)
        if key:
            external_by_name.setdefault(key, []).append(row)
        badge = _clean(row.badge_number)
        if badge:
            external_by_badge.setdefault(badge, []).append(row)

    suggestions = {}

    def _name_candidate(row: ExternalPersonRow) -> str | None:
        key = _normalize_name(row.name)
        if not key or len(external_by_name.get(key, [])) != 1:
            return None
        candidates = by_name.get(key, [])
        return candidates[0].id if len(candidates) == 1 else None

    def _badge_candidate(row: ExternalPersonRow) -> str | None:
        badge = _clean(row.badge_number)
        if not badge or len(external_by_badge.get(badge, [])) != 1:
            return None
        candidates = by_employee_no.get(badge, [])
        return candidates[0].id if len(candidates) == 1 else None

    for row in rows:
        name_id = _name_candidate(row)
        badge_id = _badge_candidate(row)
        if badge_id and (name_id is None or name_id == badge_id):
            # 工号（BADGENUMBER）与 OA 工号一致时优先；无姓名冲突才采用
            suggestions[row.external_user_id] = badge_id
        elif name_id:
            suggestions[row.external_user_id] = name_id
    return suggestions


def sync_attendance_punches(
    *,
    people: Iterable[ExternalPersonRow] | None = None,
    punches: Iterable[AttendancePunchRow] | None = None,
    tenant_slug: str = ATTENDANCE_TENANT_SLUG,
    trigger: str = 'scheduled',
    since: datetime | None = None,
) -> AttendanceSyncResult:
    tenant = _get_sync_tenant(tenant_slug)
    with _sync_lock():
        run = AttendanceSyncRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            run_trigger=trigger,
            status='running',
            lookback_days=_lookback_days(),
        )
        db.session.add(run)
        db.session.commit()
        try:
            source_people = list(people) if people is not None else AttendanceReadOnlyClient.from_environment().fetch_people()
            source_punches = (
                list(punches)
                if punches is not None
                else AttendanceReadOnlyClient.from_environment().fetch_punches(
                    since=since or _punch_since(tenant),
                )
            )
            now = datetime.utcnow()
            suggestions = _suggest_employee_ids(tenant, source_people)
            upserted = 0
            for row in source_people:
                person_id = _stable_id('attendance-person', tenant.id, row.external_user_id)
                person = db.session.get(AttendanceExternalPerson, person_id)
                if not person:
                    person = AttendanceExternalPerson(
                        id=person_id,
                        tenant_id=tenant.id,
                        external_user_id=str(row.external_user_id),
                    )
                    db.session.add(person)
                person.badge_number = row.badge_number or None
                person.name = row.name
                person.department_name = row.department_name or None
                person.source_synced_at = now
                if person.mapping_status not in {'confirmed', 'ignored'}:
                    suggested_id = suggestions.get(row.external_user_id)
                    person.suggested_employee_id = suggested_id
                    person.mapping_status = 'suggested' if suggested_id else 'unmatched'
                    person.employee_id = None
                upserted += 1

            existing_keys = set()
            if source_punches:
                min_time = min(row.check_time for row in source_punches)
                existing_keys = {
                    (item.external_user_id, item.check_time)
                    for item in AttendanceRawPunch.query.filter(
                        AttendanceRawPunch.tenant_id == tenant.id,
                        AttendanceRawPunch.check_time >= min_time,
                    ).all()
                }
            inserted = 0
            duplicate = 0
            cursor = None
            for row in source_punches:
                key = (str(row.external_user_id), row.check_time)
                cursor = row.check_time if cursor is None or row.check_time > cursor else cursor
                if key in existing_keys:
                    duplicate += 1
                    continue
                db.session.add(AttendanceRawPunch(
                    id=_stable_id('attendance-punch', tenant.id, f'{row.external_user_id}:{row.check_time.isoformat()}'),
                    tenant_id=tenant.id,
                    external_user_id=str(row.external_user_id),
                    check_time=row.check_time,
                    check_type=_clean(row.check_type) or None,
                    verify_code=_clean(row.verify_code) or None,
                    sensor_id=_clean(row.sensor_id) or None,
                    serial_number=_clean(row.serial_number) or None,
                    fingerprint=punch_fingerprint(row),
                    sync_run_id=run.id,
                ))
                existing_keys.add(key)
                inserted += 1

            db.session.flush()
            confirmed_count = _auto_confirm_suggested_name_matches(tenant)
            _reconcile_confirmed_employee_numbers(tenant)
            daily_records_upserted = _rebuild_kaoqin_daily_records(tenant)
            unmatched_count = AttendanceExternalPerson.query.filter_by(tenant_id=tenant.id, mapping_status='unmatched').count()
            suggested_count = AttendanceExternalPerson.query.filter_by(tenant_id=tenant.id, mapping_status='suggested').count()
            run.status = 'success'
            run.people_read = len(source_people)
            run.people_upserted = upserted
            run.punches_read = len(source_punches)
            run.punches_inserted = inserted
            run.punches_duplicate = duplicate
            run.unmatched_count = unmatched_count
            run.suggested_count = suggested_count
            run.cursor_check_time = cursor or run.cursor_check_time
            run.completed_at = datetime.utcnow()
            db.session.commit()
            logger.info(
                'attendance_punch_sync_success',
                extra={
                    'runId': run.id,
                    'peopleRead': run.people_read,
                    'punchesInserted': run.punches_inserted,
                    'punchesDuplicate': run.punches_duplicate,
                    'confirmedCount': confirmed_count,
                    'dailyRecordsUpserted': daily_records_upserted,
                },
            )
            return AttendanceSyncResult(
                run_id=run.id,
                people_read=run.people_read,
                people_upserted=run.people_upserted,
                punches_read=run.punches_read,
                punches_inserted=run.punches_inserted,
                punches_duplicate=run.punches_duplicate,
                unmatched_count=run.unmatched_count,
                suggested_count=run.suggested_count,
                confirmed_count=confirmed_count,
                daily_records_upserted=daily_records_upserted,
            )
        except Exception as exc:
            db.session.rollback()
            failed_run = db.session.get(AttendanceSyncRun, run.id)
            if failed_run:
                failed_run.status = 'failed'
                failed_run.error_code = type(exc).__name__[:80]
                failed_run.error_message = str(exc)[:500]
                failed_run.completed_at = datetime.utcnow()
                db.session.commit()
            raise


def latest_sync_run(tenant_slug: str = ATTENDANCE_TENANT_SLUG) -> AttendanceSyncRun | None:
    tenant = _get_sync_tenant(tenant_slug)
    return AttendanceSyncRun.query.filter_by(tenant_id=tenant.id).order_by(
        AttendanceSyncRun.started_at.desc()
    ).first()


def mapping_summary(tenant_slug: str = ATTENDANCE_TENANT_SLUG) -> dict[str, int]:
    tenant = _get_sync_tenant(tenant_slug)
    counts = {'unmatched': 0, 'suggested': 0, 'confirmed': 0, 'ignored': 0}
    rows = (
        db.session.query(AttendanceExternalPerson.mapping_status, db.func.count(AttendanceExternalPerson.id))
        .filter_by(tenant_id=tenant.id)
        .group_by(AttendanceExternalPerson.mapping_status)
        .all()
    )
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    punch_count = AttendanceRawPunch.query.filter_by(tenant_id=tenant.id).count()
    counts['punches'] = punch_count
    counts['daily_records'] = int(
        db.session.query(db.func.count(AttendanceRecord.id))
        .join(Employee, AttendanceRecord.employee_id == Employee.id)
        .filter(Employee.tenant_id == tenant.id, AttendanceRecord.source == 'kaoqin')
        .scalar() or 0
    )
    return counts


def list_external_people(
    *,
    status: str | None = None,
    tenant_slug: str = ATTENDANCE_TENANT_SLUG,
) -> list[AttendanceExternalPerson]:
    tenant = _get_sync_tenant(tenant_slug)
    query = AttendanceExternalPerson.query.filter_by(tenant_id=tenant.id)
    if status:
        query = query.filter_by(mapping_status=status)
    return query.order_by(AttendanceExternalPerson.name, AttendanceExternalPerson.external_user_id).all()


def _resolved_actor_id(actor_user_id: str | None) -> str | None:
    if not actor_user_id:
        return None
    return actor_user_id if db.session.get(User, actor_user_id) else None


def _write_mapping_log(*, actor_user_id: str | None, action: str, person: AttendanceExternalPerson) -> None:
    db.session.add(OperationLog(
        id=str(uuid.uuid4()),
        user_id=_resolved_actor_id(actor_user_id),
        module='attendance-sync',
        action=action,
        target_id=person.id,
        detail={
            'externalUserId': person.external_user_id,
            'employeeId': person.employee_id,
            'mappingStatus': person.mapping_status,
        },
    ))


def _assign_badge_as_employee_number(person: AttendanceExternalPerson, employee: Employee) -> None:
    badge_number = _clean(person.badge_number)
    if not badge_number:
        raise ValueError('attendance badge number is blank')
    occupied = Employee.query.filter(
        Employee.tenant_id == person.tenant_id,
        Employee.employee_no == badge_number,
        Employee.id != employee.id,
    ).first()
    if occupied:
        occupied_mapping = AttendanceExternalPerson.query.filter_by(
            tenant_id=person.tenant_id,
            employee_id=occupied.id,
            mapping_status='confirmed',
        ).first()
        if occupied.source_system != OA_SOURCE_SYSTEM or occupied_mapping:
            raise ValueError('attendance badge number already assigned')
        # Release an OA workcode that an older sync incorrectly stored as employee_no.
        occupied.employee_no = None
        db.session.flush()
    employee.employee_no = badge_number


def _apply_confirmed_mapping(
    person: AttendanceExternalPerson,
    employee: Employee,
    actor_user_id: str | None,
    *,
    action: str,
) -> None:
    occupied = AttendanceExternalPerson.query.filter(
        AttendanceExternalPerson.tenant_id == person.tenant_id,
        AttendanceExternalPerson.employee_id == employee.id,
        AttendanceExternalPerson.id != person.id,
        AttendanceExternalPerson.mapping_status == 'confirmed',
    ).first()
    if occupied:
        raise ValueError('employee already mapped')
    _assign_badge_as_employee_number(person, employee)
    person.employee_id = employee.id
    person.suggested_employee_id = employee.id
    person.mapping_status = 'confirmed'
    person.mapped_at = datetime.utcnow()
    person.mapped_by = _resolved_actor_id(actor_user_id)
    _write_mapping_log(actor_user_id=actor_user_id, action=action, person=person)


def _auto_confirm_suggested_name_matches(tenant: Tenant, actor_user_id: str | None = None) -> int:
    people = AttendanceExternalPerson.query.filter_by(
        tenant_id=tenant.id, mapping_status='suggested',
    ).all()
    occupied = {
        row.employee_id
        for row in AttendanceExternalPerson.query.filter_by(
            tenant_id=tenant.id, mapping_status='confirmed',
        ).all()
        if row.employee_id
    }
    confirmed = 0
    for person in people:
        employee_id = person.suggested_employee_id
        if not employee_id or employee_id in occupied:
            continue
        employee = db.session.get(Employee, employee_id)
        if not employee or employee.tenant_id != person.tenant_id:
            continue
        try:
            _apply_confirmed_mapping(
                person, employee, actor_user_id, action='auto_confirm_name_match',
            )
        except ValueError:
            continue
        occupied.add(employee_id)
        confirmed += 1
    return confirmed


def _reconcile_confirmed_employee_numbers(tenant: Tenant) -> int:
    corrected = 0
    people = AttendanceExternalPerson.query.filter_by(
        tenant_id=tenant.id,
        mapping_status='confirmed',
    ).all()
    for person in people:
        employee = db.session.get(Employee, person.employee_id) if person.employee_id else None
        if not employee or employee.tenant_id != tenant.id:
            continue
        before = employee.employee_no
        try:
            _assign_badge_as_employee_number(person, employee)
        except ValueError:
            logger.warning(
                'attendance_employee_number_reconcile_skipped',
                extra={'personId': person.id, 'employeeId': person.employee_id},
            )
            continue
        if before != employee.employee_no:
            corrected += 1
    return corrected


def _rebuild_kaoqin_daily_records(tenant: Tenant, *, employee_id: str | None = None) -> int:
    mapping_query = AttendanceExternalPerson.query.filter_by(
        tenant_id=tenant.id, mapping_status='confirmed',
    )
    if employee_id:
        mapping_query = mapping_query.filter_by(employee_id=employee_id)
    mappings = [row for row in mapping_query.all() if row.employee_id]
    if not mappings:
        return 0
    employee_by_external = {row.external_user_id: row.employee_id for row in mappings}
    punches = AttendanceRawPunch.query.filter(
        AttendanceRawPunch.tenant_id == tenant.id,
        AttendanceRawPunch.external_user_id.in_(list(employee_by_external.keys())),
    ).all()
    grouped: dict[tuple[str, date], list[datetime]] = {}
    for punch in punches:
        mapped_employee_id = employee_by_external.get(punch.external_user_id)
        if not mapped_employee_id or not punch.check_time:
            continue
        key = (mapped_employee_id, punch.check_time.date())
        grouped.setdefault(key, []).append(punch.check_time)
    if not grouped:
        return 0
    employee_ids = {key[0] for key in grouped}
    days = {key[1] for key in grouped}
    existing_rows = AttendanceRecord.query.filter(
        AttendanceRecord.employee_id.in_(employee_ids),
        AttendanceRecord.attendance_date.in_(days),
    ).all()
    existing_map = {(row.employee_id, row.attendance_date): row for row in existing_rows}
    upserted = 0
    for (mapped_employee_id, day), times in grouped.items():
        times.sort()
        first = times[0]
        last = times[-1]
        existing = existing_map.get((mapped_employee_id, day))
        if existing and existing.source != 'kaoqin':
            continue
        if len(times) == 1:
            status = 'missing_card'
            check_out = None
            work_hours = None
        else:
            status = 'normal'
            check_out = last
            work_hours = (
                Decimal(str((last - first).total_seconds())) / Decimal('3600')
            ).quantize(Decimal('0.01'))
        record = existing
        if record is None:
            record = AttendanceRecord(
                id=_stable_id('attendance-day', tenant.id, f'{mapped_employee_id}:{day.isoformat()}'),
                employee_id=mapped_employee_id,
                tenant_id=tenant.id,
            )
            db.session.add(record)
        if getattr(record, 'tenant_id', None) in (None, ''):
            record.tenant_id = tenant.id
        record.attendance_date = day
        record.check_in_time = first
        record.check_out_time = check_out
        record.work_hours = work_hours
        record.status = status
        record.source = 'kaoqin'
        record.remark = f'考勤机打卡 {len(times)} 次'
        upserted += 1
    return upserted


def confirm_external_person(person_id: str, *, employee_id: str, actor_user_id: str | None = None) -> AttendanceExternalPerson:
    person = db.session.get(AttendanceExternalPerson, person_id)
    if not person:
        raise LookupError('external person not found')
    employee = db.session.get(Employee, employee_id)
    if not employee or employee.tenant_id != person.tenant_id:
        raise LookupError('employee not found')
    _apply_confirmed_mapping(person, employee, actor_user_id, action='confirm_mapping')
    db.session.commit()
    tenant = db.session.get(Tenant, person.tenant_id)
    if tenant:
        _rebuild_kaoqin_daily_records(tenant, employee_id=employee.id)
        db.session.commit()
    return person


def ignore_external_person(person_id: str, *, actor_user_id: str | None = None) -> AttendanceExternalPerson:
    person = db.session.get(AttendanceExternalPerson, person_id)
    if not person:
        raise LookupError('external person not found')
    person.mapping_status = 'ignored'
    person.employee_id = None
    person.mapped_at = datetime.utcnow()
    person.mapped_by = _resolved_actor_id(actor_user_id)
    _write_mapping_log(actor_user_id=actor_user_id, action='ignore_mapping', person=person)
    db.session.commit()
    return person


def run_scheduled_sync() -> AttendanceSyncResult | None:
    if os.getenv('ATTENDANCE_SYNC_ENABLED', '0') != '1':
        return None
    latest = latest_sync_run()
    if latest and latest.status == 'success' and latest.completed_at:
        interval = int(os.getenv('ATTENDANCE_SYNC_INTERVAL_SECONDS', '300') or '300')
        if datetime.utcnow() - latest.completed_at < timedelta(seconds=max(60, interval)):
            return None
    try:
        return sync_attendance_punches(trigger='scheduled')
    except AttendanceSyncBusy:
        return None
    except Exception:
        logger.exception('attendance_punch_scheduled_sync_failed')
        return None


def _loop(app) -> None:
    global _running
    interval = max(60, int(os.getenv('ATTENDANCE_SYNC_INTERVAL_SECONDS', '300') or '300'))
    while _running:
        with app.app_context():
            run_scheduled_sync()
        for _ in range(interval):
            if not _running:
                break
            threading.Event().wait(1)


def start_attendance_punch_scheduler(app) -> None:
    global _running
    if _running or os.getenv('ATTENDANCE_SYNC_ENABLED', '0') != '1':
        return
    _running = True
    thread = threading.Thread(target=_loop, args=(app,), daemon=True, name='attendance-punch-sync')
    thread.start()
    logger.info('attendance_punch_scheduler_started')


def stop_attendance_punch_scheduler() -> None:
    global _running
    _running = False
