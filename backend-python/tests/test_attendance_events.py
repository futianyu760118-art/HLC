from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from models import (
    AttendanceEvent,
    AttendanceExternalPerson,
    AttendanceRawPunch,
    AttendanceTimesheet,
    Department,
    Employee,
    Tenant,
    db,
)
from services.attendance_attribution import OFFICE, WORKSHOP, attribute_day
from services.attendance_events import list_events, sync_attendance_events
from services.attendance_timesheet import generate_timesheets
from services.oa_attendance_docs import (
    BUSINESS_TRIP,
    COMPENSATORY,
    LEAVE,
    OVERTIME,
    OUTING,
    PUNCH_FIX,
    OaAttendanceDoc,
    OaAttendanceDocClient,
)
from services.oa_schedule import OaScheduleDay, OaWorktime


class _FakeOaReader:
    def __init__(self, rows_by_marker):
        self._rows = rows_by_marker

    def _fetch_dicts(self, statement):
        for marker, rows in self._rows.items():
            if marker in statement:
                return rows
        return []


def test_oa_document_reader_normalizes_rows():
    reader = _FakeOaReader({
        'formtable_main_17': [{
            'main_id': 18723, 'request_id': 734757, 'oa_person_id': 356,
            'employee_no': '797 ', 'department_id': 3,
            'start_time': '2026-09-21 11:30', 'end_time': '2026-09-21 17:30',
            'hours': '4.50', 'subtype': 1, 'reason': '',
        }],
        'formtable_main_41_dt1': [{
            'main_id': 4403, 'request_id': 732769, 'oa_person_id': 248,
            'employee_no': '407  ', 'department_id': 2, 'subtype': 0,
            'reason': '主表原因', 'detail_id': 5254,
            'start_time': '2026-09-18 17:30', 'end_time': '2026-09-18 21:00',
            'hours': '3.50', 'detail_reason': '明细原因',
        }],
        'formtable_main_35_dt1': [{
            'main_id': 8521, 'request_id': 734758, 'oa_person_id': 64,
            'employee_no': '426', 'department_id': 45, 'reason': '忘记打卡',
            'detail_id': 8548, 'start_time': '2026-09-20 17:30',
        }],
        'formtable_main_43': [{
            'main_id': 11233, 'request_id': 733791, 'oa_person_id': 118,
            'employee_no': '754', 'department_id': 69,
            'start_time': '2026-09-20 16:30', 'end_time': '2026-09-20 17:30',
            'hours': '1.0', 'reason': '',
        }],
        'formtable_main_18': [{
            'main_id': 6300, 'request_id': 734747, 'oa_person_id': 45,
            'employee_no': '285', 'department_id': 38,
            'start_time': '2026-09-21 09:00', 'end_time': '2026-09-21 10:00',
            'reason': '外出办事',
        }],
        'formtable_main_15': [{
            'main_id': 85, 'request_id': 672698, 'oa_person_id': 153,
            'employee_no': '565', 'department_id': 4,
            'start_time': '2026-06-08', 'end_time': '2026-06-17',
            'reason': '展会',
        }],
    })
    client = OaAttendanceDocClient(reader)
    docs = {doc.source_key: doc for doc in client.fetch_documents(date(2026, 6, 1), date(2026, 10, 1))}

    leave = docs[f'{LEAVE}:18723']
    assert leave.employee_no == '797'
    assert leave.start_at == datetime(2026, 9, 21, 11, 30)
    assert leave.hours == Decimal('4.50')
    assert leave.affects_hours is True

    overtime = docs[f'{OVERTIME}:5254']
    assert overtime.oa_main_id == '4403'
    assert overtime.reason == '明细原因'
    assert overtime.hours == Decimal('3.50')

    fix = docs[f'{PUNCH_FIX}:8548']
    assert fix.start_at == datetime(2026, 9, 20, 17, 30)
    assert fix.affects_hours is False

    assert docs[f'{COMPENSATORY}:11233'].affects_hours is True
    assert docs[f'{OUTING}:6300'].affects_hours is False

    trip = docs[f'{BUSINESS_TRIP}:85']
    assert trip.start_at == datetime(2026, 6, 8, 0, 0)
    assert trip.end_at == datetime(2026, 6, 17, 23, 59, 59)
    assert trip.affects_hours is False


class _FakeDocClient:
    def __init__(self, docs):
        self._docs = docs

    def fetch_documents(self, start, end):
        return self._docs


@pytest.fixture()
def events_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(Tenant(id='tenant-1', slug='t1', name='T1', status='active'))
        db.session.add(Department(id='dept-fin', tenant_id='tenant-1', name='财务部', status='active'))
        db.session.add(Employee(
            id='emp-hong', tenant_id='tenant-1', employee_no='595', name='洪香',
            status='active', department_id='dept-fin', employee_type='后勤', oa_person_id='13',
        ))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_sync_attendance_events_is_idempotent(events_app):
    docs = [
        OaAttendanceDoc(
            event_type=LEAVE, source_key='leave:1', oa_form_table='formtable_main_17',
            oa_main_id='1', employee_no='595', start_at=datetime(2026, 9, 1, 8, 0),
            end_at=datetime(2026, 9, 1, 12, 0), hours=Decimal('4'), subtype='1',
        ),
        OaAttendanceDoc(
            event_type=PUNCH_FIX, source_key='punch_fix:9', oa_form_table='formtable_main_35',
            oa_main_id='2', employee_no='999', start_at=datetime(2026, 9, 1, 17, 30),
        ),
    ]
    client = _FakeDocClient(docs)
    with events_app.app_context():
        result = sync_attendance_events('tenant-1', months=12, doc_client=client)
        assert result['fetched'] == 2
        assert result['created'] == 2
        assert result['unmatched'] == 1
        assert result['byType'][LEAVE] == 1

        leave = AttendanceEvent.query.filter_by(tenant_id='tenant-1', source_key='leave:1').one()
        assert leave.employee_id == 'emp-hong'
        assert leave.employee_name == '洪香'

        again = sync_attendance_events('tenant-1', months=12, doc_client=client)
        assert again['created'] == 0
        assert again['updated'] == 2
        assert AttendanceEvent.query.count() == 2


def test_list_events_filters_by_employee_and_date(events_app):
    with events_app.app_context():
        db.session.add_all([
            AttendanceEvent(
                id='e1', tenant_id='tenant-1', event_type=LEAVE, employee_id='emp-hong',
                employee_no='595', start_at=datetime(2026, 9, 1, 8, 0),
                end_at=datetime(2026, 9, 1, 12, 0), affects_hours=True, source_key='leave:1',
            ),
            AttendanceEvent(
                id='e2', tenant_id='tenant-1', event_type=COMPENSATORY, employee_id='emp-hong',
                employee_no='595', start_at=datetime(2026, 9, 2, 8, 0),
                end_at=datetime(2026, 9, 2, 12, 0), affects_hours=True, source_key='comp:1',
            ),
        ])
        db.session.commit()

        items, total, _, _ = list_events(
            'tenant-1', employee_id='emp-hong',
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
            page=1, size=50,
        )
        assert total == 1
        assert items[0].event_type == LEAVE

        _, all_total, _, _ = list_events('tenant-1', employee_id='emp-hong', page=1, size=50)
        assert all_total == 2


class _FakeScheduleClient:
    def __init__(self, worktimes, days):
        self._worktimes = worktimes
        self._days = days

    def fetch_worktimes(self):
        return self._worktimes

    def fetch_schedule(self, start, end):
        return self._days


_OFFICE_WORKTIMES = {
    1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
    2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
}


def test_office_leave_deducts_and_excuses_missing_point():
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=_OFFICE_WORKTIMES,
        punches=[datetime(2026, 9, 1, 7, 30), datetime(2026, 9, 1, 11, 30)],
        deduct_windows=[(datetime(2026, 9, 1, 11, 30), datetime(2026, 9, 1, 17, 30))],
    )
    assert day.check_in == datetime(2026, 9, 1, 7, 30)
    assert day.check_out == datetime(2026, 9, 1, 11, 30)
    assert day.work_hours == Decimal('4.00')
    assert day.missing_points == 0
    assert day.excused_points == 1
    assert day.leave_hours == Decimal('4.00')
    assert day.status == 'normal'


def test_office_full_day_leave_reports_leave_status():
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=_OFFICE_WORKTIMES,
        punches=[],
        deduct_windows=[(datetime(2026, 9, 1, 7, 0), datetime(2026, 9, 1, 18, 0))],
    )
    assert day.status == 'leave'
    assert day.work_hours == Decimal('0.00')
    assert day.missing_points == 0
    assert day.leave_hours == Decimal('8.00')


def test_office_overtime_uses_application_hours():
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=13, employee_type=OFFICE,
        schedule=OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
        worktime_map=_OFFICE_WORKTIMES,
        punches=[datetime(2026, 9, 1, 7, 30), datetime(2026, 9, 1, 20, 0)],
        overtime_hours_override=Decimal('2.5'),
    )
    assert day.work_hours == Decimal('8.00')
    assert day.overtime_hours == Decimal('2.50')


def test_workshop_ignores_overtime_override():
    day = attribute_day(
        work_date=date(2026, 9, 1), person_id=65, employee_type=WORKSHOP,
        schedule=OaScheduleDay(65, date(2026, 9, 1), (1, 2)),
        worktime_map=_OFFICE_WORKTIMES,
        punches=[
            datetime(2026, 9, 1, 7, 30), datetime(2026, 9, 1, 11, 30),
            datetime(2026, 9, 1, 13, 0), datetime(2026, 9, 1, 18, 35),
        ],
        overtime_hours_override=Decimal('9.0'),
    )
    assert day.overtime_hours == Decimal('1.50')


def test_generate_timesheets_applies_leave_and_punch_fix(events_app):
    with events_app.app_context():
        db.session.add(AttendanceExternalPerson(
            id='person-13', tenant_id='tenant-1', external_user_id='101', badge_number='595',
            name='洪香', employee_id='emp-hong', mapping_status='confirmed',
        ))
        db.session.add(AttendanceRawPunch(
            id='p1', tenant_id='tenant-1', external_user_id='101',
            check_time=datetime(2026, 9, 1, 7, 30), fingerprint='fp1',
        ))
        db.session.add(AttendanceRawPunch(
            id='p2', tenant_id='tenant-1', external_user_id='101',
            check_time=datetime(2026, 9, 1, 11, 30), fingerprint='fp2',
        ))
        db.session.add(AttendanceEvent(
            id='ev-leave', tenant_id='tenant-1', event_type=LEAVE,
            employee_id='emp-hong', employee_no='595', employee_name='洪香',
            start_at=datetime(2026, 9, 1, 11, 30), end_at=datetime(2026, 9, 1, 17, 30),
            hours=Decimal('4.5'), affects_hours=True, source_key='leave:1',
        ))
        db.session.add(AttendanceRawPunch(
            id='p3', tenant_id='tenant-1', external_user_id='101',
            check_time=datetime(2026, 9, 2, 7, 30), fingerprint='fp3',
        ))
        db.session.add(AttendanceEvent(
            id='ev-fix', tenant_id='tenant-1', event_type=PUNCH_FIX,
            employee_id='emp-hong', employee_no='595', employee_name='洪香',
            start_at=datetime(2026, 9, 2, 17, 0), affects_hours=False, source_key='punch_fix:1',
        ))
        db.session.commit()

        client = _FakeScheduleClient(
            worktimes=_OFFICE_WORKTIMES,
            days=[
                OaScheduleDay(13, date(2026, 9, 1), (1, 2)),
                OaScheduleDay(13, date(2026, 9, 2), (1, 2)),
            ],
        )
        generate_timesheets('tenant-1', '2026-09', schedule_client=client)

        leave_day = AttendanceTimesheet.query.filter_by(
            tenant_id='tenant-1', employee_id='emp-hong', work_date=date(2026, 9, 1),
        ).one()
        assert leave_day.status == 'normal'
        assert float(leave_day.work_hours) == 4.00
        assert float(leave_day.leave_hours) == 4.00
        assert leave_day.event_summary == '请假'

        fix_day = AttendanceTimesheet.query.filter_by(
            tenant_id='tenant-1', employee_id='emp-hong', work_date=date(2026, 9, 2),
        ).one()
        # 07:30 上班 + 补卡 17:00 下班 → 后勤 8.00h，且不缺卡
        assert fix_day.status == 'normal'
        assert fix_day.check_out == datetime(2026, 9, 2, 17, 0)
        assert fix_day.check_out_fixed is True
        assert fix_day.check_in_fixed is False
        assert float(fix_day.work_hours) == 8.00
        assert fix_day.event_summary == '补卡'
        assert len(fix_day.punch_times) == 2
        assert any(p['fix'] for p in fix_day.punch_times)

        assert len(leave_day.punch_times) == 2
        assert not any(p['fix'] for p in leave_day.punch_times)
