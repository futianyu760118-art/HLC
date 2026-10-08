from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from models import (
    AttendanceExternalPerson,
    AttendanceRawPunch,
    AttendanceTimesheet,
    Department,
    Employee,
    Tenant,
    db,
)
from services.attendance_timesheet import (
    correct_timesheet,
    generate_timesheets,
    list_timesheets,
)
from services.oa_schedule import OaScheduleDay, OaWorktime


class _FakeScheduleClient:
    def __init__(self, worktimes, days):
        self._worktimes = worktimes
        self._days = days

    def fetch_worktimes(self):
        return self._worktimes

    def fetch_schedule(self, start, end):
        return self._days


@pytest.fixture()
def timesheet_app():
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
        db.session.add_all([
            Employee(
                id='emp-hong', tenant_id='tenant-1', employee_no='595', name='洪香',
                status='active', department_id='dept-fin', employee_type='后勤', oa_person_id='13',
            ),
            AttendanceExternalPerson(
                id='person-13', tenant_id='tenant-1', external_user_id='101', badge_number='595',
                name='洪香', employee_id='emp-hong', mapping_status='confirmed',
            ),
        ])
        db.session.add_all([
            AttendanceRawPunch(
                id='p1', tenant_id='tenant-1', external_user_id='101',
                check_time=datetime(2026, 9, 1, 7, 32), fingerprint='fp1',
            ),
            AttendanceRawPunch(
                id='p2', tenant_id='tenant-1', external_user_id='101',
                check_time=datetime(2026, 9, 1, 17, 5), fingerprint='fp2',
            ),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _client():
    return _FakeScheduleClient(
        worktimes={
            1: OaWorktime(1, '上午', '07:30', '11:30', Decimal('4')),
            2: OaWorktime(2, '下午', '13:00', '17:00', Decimal('4')),
        },
        days=[OaScheduleDay(13, date(2026, 9, 1), (1, 2))],
    )


def test_generate_timesheets_from_schedule_and_punches(timesheet_app):
    with timesheet_app.app_context():
        result = generate_timesheets('tenant-1', '2026-09', schedule_client=_client())
        assert result['created'] == 30

        first = AttendanceTimesheet.query.filter_by(
            tenant_id='tenant-1', employee_id='emp-hong', work_date=date(2026, 9, 1),
        ).one()
        assert first.status == 'normal'
        assert first.check_in == datetime(2026, 9, 1, 7, 32)
        assert first.check_out == datetime(2026, 9, 1, 17, 5)
        # 排班 07:30~11:30+13:00~17:00, 午休1.5h
        # clamp: in=max(07:32,07:30)=07:32, out=min(17:05,17:00)=17:00
        # 工时 = 17:00-07:32-90min = 478min → 按30分钟取整 → 450min = 7.50h
        assert float(first.work_hours) == 7.50
        assert first.employee_type == '后勤'
        assert first.expected_punches == 2
        assert first.actual_punches == 2

        rest = AttendanceTimesheet.query.filter_by(
            tenant_id='tenant-1', employee_id='emp-hong', work_date=date(2026, 9, 2),
        ).one()
        assert rest.status == 'rest'


def test_manual_correction_is_kept_on_regenerate(timesheet_app):
    with timesheet_app.app_context():
        generate_timesheets('tenant-1', '2026-09', schedule_client=_client())
        row = AttendanceTimesheet.query.filter_by(
            tenant_id='tenant-1', employee_id='emp-hong', work_date=date(2026, 9, 1),
        ).one()

        corrected = correct_timesheet(
            row.id, tenant_id='tenant-1',
            check_in='2026-09-01T08:00:00', check_out='2026-09-01T18:00:00',
            status='normal', remark='手工修正（出差）', actor_user_id='user-1',
        )
        db.session.commit()

        assert corrected.manual_corrected is True
        assert corrected.corrected_by == 'user-1'
        assert corrected.original_snapshot['checkIn'] == '2026-09-01T07:32:00'
        assert float(corrected.work_hours) == 10.0

        again = generate_timesheets('tenant-1', '2026-09', schedule_client=_client())
        assert again['skippedManual'] == 1

        row = AttendanceTimesheet.query.filter_by(id=row.id).one()
        assert row.check_in == datetime(2026, 9, 1, 8, 0)
        assert row.remark == '手工修正（出差）'


def test_list_timesheets_filters(timesheet_app):
    with timesheet_app.app_context():
        generate_timesheets('tenant-1', '2026-09', schedule_client=_client())

        items, total, page, size = list_timesheets(
            'tenant-1', month='2026-09', page=1, size=10,
        )
        assert total == 30
        assert page == 1 and size == 10
        assert len(items) == 10

        normal_items, normal_total, _, _ = list_timesheets(
            'tenant-1', month='2026-09', status='normal', page=1, size=10,
        )
        assert normal_total == 1
