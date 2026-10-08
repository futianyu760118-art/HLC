from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app import _register_request_lifecycle, _register_tenant_context
from models import (
    AttendanceDailyResult,
    AttendanceExternalPerson,
    AttendanceGroup,
    AttendanceGroupMembership,
    AttendanceHoliday,
    AttendanceRawPunch,
    AttendanceRuleSet,
    AttendanceSchedule,
    AttendanceShift,
    Employee,
    EmployeeRequest,
    Tenant,
    User,
    db,
)
from routes import hrm_bp
from services.attendance_policy import (
    AttendancePolicyError,
    recalculate_daily_results,
)
from services.tenancy import register_tenant_orm_filters, tenant_claims_for


TARGET_TENANT_ID = 'tenant-policy-00001'
OTHER_TENANT_ID = 'tenant-policy-other'
TARGET_EMPLOYEE_ID = 'employee-policy-00001'
OTHER_EMPLOYEE_ID = 'employee-policy-other'
FIXED_SHIFT_ID = 'shift-policy-fixed'
FLEX_SHIFT_ID = 'shift-policy-flex'
RULE_ID = 'rule-policy-v1'
GROUP_ID = 'group-policy-default'
MEMBERSHIP_ID = 'membership-policy-employee'
EXTERNAL_PERSON_ID = 'external-policy-101'


def _punch(punch_id: str, check_time: datetime, external_user_id: str = '101') -> AttendanceRawPunch:
    return AttendanceRawPunch(
        id=punch_id,
        tenant_id=TARGET_TENANT_ID,
        external_user_id=external_user_id,
        check_time=check_time,
        check_type='I',
        verify_code='1',
        sensor_id='sensor-1',
        serial_number='device-1',
        fingerprint=f'fingerprint-{punch_id}',
    )


@pytest.fixture()
def policy_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='policy-secret',
        JWT_SECRET_KEY='policy-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    register_tenant_orm_filters()
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    _register_request_lifecycle(app)
    _register_tenant_context(app)

    with app.app_context():
        db.create_all()
        target = Tenant(id=TARGET_TENANT_ID, slug='HPT-00000001', name='Target', status='active')
        other = Tenant(id=OTHER_TENANT_ID, slug='HPT-00000002', name='Other', status='active')
        target_admin = User(
            id='policy-admin-target', tenant_id=TARGET_TENANT_ID,
            email='policy-target@example.com', password_hash='unused',
            name='Target Admin', role='admin', status='active',
        )
        other_admin = User(
            id='policy-admin-other', tenant_id=OTHER_TENANT_ID,
            email='policy-other@example.com', password_hash='unused',
            name='Other Admin', role='admin', status='active',
        )
        target_employee = Employee(
            id=TARGET_EMPLOYEE_ID, tenant_id=TARGET_TENANT_ID,
            employee_no='POL-0001', name='考勤员工', status='active',
        )
        other_employee = Employee(
            id=OTHER_EMPLOYEE_ID, tenant_id=OTHER_TENANT_ID,
            employee_no='POL-0002', name='其他员工', status='active',
        )
        fixed_shift = AttendanceShift(
            id=FIXED_SHIFT_ID, tenant_id=TARGET_TENANT_ID,
            code='FIXED-0900', name='标准固定班', shift_type='fixed',
            start_time='09:00', end_time='18:00', required_work_hours=Decimal('8'),
            late_grace_minutes=5, early_leave_grace_minutes=5,
            require_check_in=True, require_check_out=True, status='active',
        )
        flex_shift = AttendanceShift(
            id=FLEX_SHIFT_ID, tenant_id=TARGET_TENANT_ID,
            code='FLEX-8H', name='弹性八小时', shift_type='flexible',
            required_work_hours=Decimal('8'), status='active',
        )
        rule = AttendanceRuleSet(
            id=RULE_ID, tenant_id=TARGET_TENANT_ID,
            code='RULE-V1', name='默认规则', version=1, status='active',
            absent_if_no_punch=True, missing_card_if_single_punch=True,
        )
        group = AttendanceGroup(
            id=GROUP_ID, tenant_id=TARGET_TENANT_ID,
            code='DEFAULT', name='默认考勤组', default_shift_id=FIXED_SHIFT_ID,
            default_rule_set_id=RULE_ID, priority=1, status='active',
        )
        membership = AttendanceGroupMembership(
            id=MEMBERSHIP_ID, tenant_id=TARGET_TENANT_ID,
            group_id=GROUP_ID, employee_id=TARGET_EMPLOYEE_ID,
            priority=1, status='active',
        )
        external = AttendanceExternalPerson(
            id=EXTERNAL_PERSON_ID, tenant_id=TARGET_TENANT_ID,
            external_user_id='101', badge_number='9001', name='考勤员工',
            employee_id=TARGET_EMPLOYEE_ID, mapping_status='confirmed',
        )
        db.session.add_all([
            target, other, target_admin, other_admin,
            target_employee, other_employee,
            fixed_shift, flex_shift, rule, group, membership, external,
        ])
        db.session.commit()
        tokens = {
            'target': create_access_token(
                identity=target_admin.id,
                additional_claims={'role': 'admin', 'account_type': 'hrm', **tenant_claims_for(target)},
            ),
            'other': create_access_token(
                identity=other_admin.id,
                additional_claims={'role': 'admin', 'account_type': 'hrm', **tenant_claims_for(other)},
            ),
        }
    yield app, tokens
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _recalculate(day: date):
    return recalculate_daily_results(
        TARGET_TENANT_ID,
        day.isoformat(),
        day.isoformat(),
        employee_id=TARGET_EMPLOYEE_ID,
    )


def test_fixed_shift_calculates_late_and_early_leave(policy_app):
    app, _tokens = policy_app
    day = date(2026, 8, 20)
    with app.app_context():
        db.session.add_all([
            _punch('p-late', datetime(2026, 8, 20, 9, 7)),
            _punch('p-early', datetime(2026, 8, 20, 17, 54)),
        ])
        db.session.commit()

        summary = _recalculate(day)
        db.session.commit()
        row = AttendanceDailyResult.query.filter_by(
            tenant_id=TARGET_TENANT_ID, employee_id=TARGET_EMPLOYEE_ID, attendance_date=day,
        ).one()

        assert summary['created'] == 1
        assert row.status == 'late_early_leave'
        assert row.late_minutes == 2
        assert row.early_leave_minutes == 1
        assert row.check_in_time == datetime(2026, 8, 20, 9, 7)
        assert row.check_out_time == datetime(2026, 8, 20, 17, 54)
        assert row.explanation_json['calculationVersion'] == 'v1'
        assert row.explanation_json['punchCount'] == 2


def test_fixed_shift_marks_no_punch_absent_and_single_punch_missing_card(policy_app):
    app, _tokens = policy_app
    absent_day = date(2026, 8, 20)
    single_day = date(2026, 8, 21)
    with app.app_context():
        db.session.add(_punch('p-single', datetime(2026, 8, 21, 9, 0)))
        db.session.commit()

        _recalculate(absent_day)
        _recalculate(single_day)
        db.session.commit()

        absent = AttendanceDailyResult.query.filter_by(attendance_date=absent_day).one()
        single = AttendanceDailyResult.query.filter_by(attendance_date=single_day).one()
        assert absent.status == 'absent'
        assert single.status == 'missing_card'


def test_approved_leave_covers_full_fixed_shift(policy_app):
    app, _tokens = policy_app
    day = date(2026, 8, 20)
    with app.app_context():
        db.session.add(EmployeeRequest(
            id='request-full-leave', employee_id=TARGET_EMPLOYEE_ID,
            request_type='leave', title='全天请假',
            start_time=datetime(2026, 8, 20, 9, 0),
            end_time=datetime(2026, 8, 20, 18, 0),
            duration_hours=Decimal('9'), status='approved',
        ))
        db.session.commit()

        _recalculate(day)
        db.session.commit()
        row = AttendanceDailyResult.query.filter_by(attendance_date=day).one()
        assert row.status == 'leave'
        assert row.request_ids == ['request-full-leave']
        assert row.explanation_json['approvedCoverageMinutes'] == 540
        assert row.explanation_json['reason'] == '已批准申请覆盖整个应出勤时段'


def test_partial_approval_changes_effective_late_window_and_is_explained(policy_app):
    app, _tokens = policy_app
    day = date(2026, 8, 20)
    with app.app_context():
        db.session.add_all([
            EmployeeRequest(
                id='request-morning-leave', employee_id=TARGET_EMPLOYEE_ID,
                request_type='leave', title='上午请假',
                start_time=datetime(2026, 8, 20, 9, 0),
                end_time=datetime(2026, 8, 20, 13, 0),
                duration_hours=Decimal('4'), status='approved',
            ),
            _punch('p-after-leave-in', datetime(2026, 8, 20, 13, 3)),
            _punch('p-after-leave-out', datetime(2026, 8, 20, 18, 0)),
        ])
        db.session.commit()

        _recalculate(day)
        db.session.commit()
        row = AttendanceDailyResult.query.filter_by(attendance_date=day).one()
        assert row.status == 'normal'
        assert row.late_minutes == 0
        assert row.early_leave_minutes == 0
        assert row.explanation_json['approvedCoverageMinutes'] == 240
        assert row.explanation_json['effectiveScheduledStart'] == '2026-08-20T13:00:00'
        assert row.explanation_json['reason'].startswith('已批准申请覆盖 240 分钟；')


def test_flexible_shift_uses_actual_work_hours(policy_app):
    app, _tokens = policy_app
    day = date(2026, 8, 20)
    with app.app_context():
        flex_group = AttendanceGroup(
            id='group-policy-flex', tenant_id=TARGET_TENANT_ID,
            code='FLEX', name='弹性考勤组', default_shift_id=FLEX_SHIFT_ID,
            default_rule_set_id=RULE_ID, priority=2, status='active',
        )
        flex_membership = AttendanceGroupMembership(
            id='membership-policy-flex', tenant_id=TARGET_TENANT_ID,
            group_id='group-policy-flex', employee_id=TARGET_EMPLOYEE_ID,
            priority=2, status='active',
        )
        db.session.add_all([
            flex_group,
            flex_membership,
            _punch('p-flex-in', datetime(2026, 8, 20, 8, 0)),
            _punch('p-flex-out', datetime(2026, 8, 20, 16, 0)),
        ])
        db.session.delete(db.session.get(AttendanceGroupMembership, MEMBERSHIP_ID))
        db.session.commit()

        _recalculate(day)
        db.session.commit()
        row = AttendanceDailyResult.query.filter_by(attendance_date=day).one()
        assert row.shift_id == FLEX_SHIFT_ID
        assert row.status == 'normal'
        assert Decimal(str(row.work_hours)) == Decimal('8.00')


def test_cross_day_shift_uses_only_punches_inside_overnight_window(policy_app):
    app, _tokens = policy_app
    day = date(2026, 8, 20)
    with app.app_context():
        night_shift = AttendanceShift(
            id='shift-policy-night', tenant_id=TARGET_TENANT_ID,
            code='NIGHT-2200', name='夜班跨日', shift_type='fixed',
            start_time='22:00', end_time='06:00', cross_day=True,
            required_work_hours=Decimal('8'), late_grace_minutes=0,
            early_leave_grace_minutes=0, require_check_in=True,
            require_check_out=True, status='active',
        )
        group = db.session.get(AttendanceGroup, GROUP_ID)
        group.default_shift_id = night_shift.id
        db.session.add_all([
            night_shift,
            _punch('p-night-noise', datetime(2026, 8, 20, 8, 0)),
            _punch('p-night-in', datetime(2026, 8, 20, 22, 5)),
            _punch('p-night-out', datetime(2026, 8, 21, 6, 0)),
        ])
        db.session.commit()

        _recalculate(day)
        db.session.commit()
        row = AttendanceDailyResult.query.filter_by(
            tenant_id=TARGET_TENANT_ID, employee_id=TARGET_EMPLOYEE_ID, attendance_date=day,
        ).one()

        assert row.status == 'late'
        assert row.late_minutes == 5
        assert row.early_leave_minutes == 0
        assert row.check_in_time == datetime(2026, 8, 20, 22, 5)
        assert row.check_out_time == datetime(2026, 8, 21, 6, 0)
        assert Decimal(str(row.work_hours)) == Decimal('7.92')
        assert row.source_punch_ids == ['p-night-in', 'p-night-out']


def test_holiday_and_explicit_rest_schedule_override_group_shift(policy_app):
    app, _tokens = policy_app
    holiday_day = date(2026, 8, 20)
    rest_day = date(2026, 8, 21)
    with app.app_context():
        db.session.add_all([
            AttendanceHoliday(
                id='holiday-policy-1', tenant_id=TARGET_TENANT_ID,
                holiday_date=holiday_day, name='企业节日', day_type='holiday', status='active',
            ),
            AttendanceSchedule(
                id='schedule-policy-rest', tenant_id=TARGET_TENANT_ID,
                employee_id=TARGET_EMPLOYEE_ID, schedule_date=rest_day,
                day_type='rest', source='manual', remark='调休休息',
            ),
            _punch('p-holiday-in', datetime(2026, 8, 20, 9, 0)),
            _punch('p-holiday-out', datetime(2026, 8, 20, 18, 0)),
            _punch('p-rest-in', datetime(2026, 8, 21, 9, 0)),
            _punch('p-rest-out', datetime(2026, 8, 21, 18, 0)),
        ])
        db.session.commit()

        _recalculate(holiday_day)
        _recalculate(rest_day)
        db.session.commit()
        holiday = AttendanceDailyResult.query.filter_by(attendance_date=holiday_day).one()
        rest = AttendanceDailyResult.query.filter_by(attendance_date=rest_day).one()
        assert holiday.status == 'holiday'
        assert holiday.schedule_source == 'holiday'
        assert rest.status == 'rest'
        assert rest.schedule_source == 'schedule'


def test_policy_routes_are_tenant_isolated_and_role_gated(policy_app):
    app, tokens = policy_app
    client = app.test_client()
    target_headers = {'Authorization': f'Bearer {tokens["target"]}'}
    other_headers = {'Authorization': f'Bearer {tokens["other"]}'}

    target_response = client.get('/api/hrm/attendance-policy/snapshot', headers=target_headers)
    other_response = client.get('/api/hrm/attendance-policy/snapshot', headers=other_headers)
    assert target_response.status_code == 200
    assert other_response.status_code == 200
    assert len(target_response.get_json()['shifts']) == 2
    assert other_response.get_json()['shifts'] == []
    assert other_response.get_json()['groups'] == []

    invalid_date = client.get(
        '/api/hrm/attendance-policy/daily-results?startDate=not-a-date',
        headers=target_headers,
    )
    assert invalid_date.status_code == 400
    assert invalid_date.get_json()['error'] == '开始日期 应为 YYYY-MM-DD'

    invalid_limit = client.get(
        '/api/hrm/attendance-policy/daily-results?limit=not-an-int',
        headers=target_headers,
    )
    assert invalid_limit.status_code == 400
    assert invalid_limit.get_json()['error'] == 'limit 应为整数'

    created_schedule = client.post(
        '/api/hrm/attendance-policy/schedules',
        headers=target_headers,
        json={
            'employeeId': TARGET_EMPLOYEE_ID,
            'scheduleDate': '2026-08-22',
            'dayType': 'workday',
            'shiftId': FIXED_SHIFT_ID,
            'source': 'manual',
        },
    )
    assert created_schedule.status_code == 200
    schedule_id = created_schedule.get_json()['id']
    updated_schedule = client.put(
        f'/api/hrm/attendance-policy/schedules/{schedule_id}',
        headers=target_headers,
        json={
            'employeeId': TARGET_EMPLOYEE_ID,
            'scheduleDate': '2026-08-22',
            'dayType': 'rest',
            'remark': '临时调休',
        },
    )
    assert updated_schedule.status_code == 200
    assert updated_schedule.get_json()['dayType'] == 'rest'

    with app.app_context():
        with pytest.raises(AttendancePolicyError):
            from services.attendance_policy import save_group

            save_group(
                TARGET_TENANT_ID,
                {'code': 'CROSS', 'name': '越界', 'defaultShiftId': 'shift-from-other-tenant'},
            )


def test_recalculate_rejects_cross_tenant_employee(policy_app):
    app, _tokens = policy_app
    with app.app_context():
        with pytest.raises(LookupError):
            recalculate_daily_results(
                TARGET_TENANT_ID,
                '2026-08-20',
                '2026-08-20',
                employee_id=OTHER_EMPLOYEE_ID,
            )
