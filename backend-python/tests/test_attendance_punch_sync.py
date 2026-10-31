from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app import _register_request_lifecycle, _register_tenant_context
from models import (
    AttendanceExternalPerson,
    AttendanceRawPunch,
    AttendanceRecord,
    AttendanceSyncRun,
    Employee,
    Tenant,
    User,
    db,
)
from services.attendance_punch_sync import (
    ATTENDANCE_TENANT_SLUG,
    AttendancePunchRow,
    AttendanceReadOnlyClient,
    AttendanceSyncDisabled,
    ExternalPersonRow,
    confirm_external_person,
    ignore_external_person,
    list_external_people,
    punch_fingerprint,
    sync_attendance_punches,
)
from services.tenancy import register_tenant_orm_filters, tenant_claims_for
from routes import hrm_bp


def _person(**overrides) -> ExternalPersonRow:
    payload = {
        'external_user_id': 101,
        'badge_number': '9001',
        'name': '张三',
        'department_name': '品质部',
    }
    payload.update(overrides)
    return ExternalPersonRow(**payload)


def _punch(**overrides) -> AttendancePunchRow:
    payload = {
        'external_user_id': 101,
        'check_time': datetime(2026, 8, 20, 8, 1, 0),
        'check_type': 'I',
        'verify_code': 1,
        'sensor_id': '1',
        'serial_number': 'ABC',
    }
    payload.update(overrides)
    return AttendancePunchRow(**payload)


@pytest.fixture()
def sync_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        target = Tenant(id='tenant-00001', slug=ATTENDANCE_TENANT_SLUG, name='00001', status='active')
        other = Tenant(id='tenant-other', slug='HPT-00000002', name='Other', status='active')
        db.session.add_all([
            target,
            other,
            Employee(
                id='employee-zhang', tenant_id=target.id, employee_no='HJ-0001',
                name='张三', status='active',
            ),
            Employee(
                id='employee-li', tenant_id=target.id, employee_no='HJ-0002',
                name='李四', status='active',
            ),
            Employee(
                id='employee-other', tenant_id=other.id, employee_no='B001',
                name='张三', status='active',
            ),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def route_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-secret',
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
        tenant = Tenant(id='tenant-00001', slug=ATTENDANCE_TENANT_SLUG, name='00001', status='active')
        other = Tenant(id='tenant-other', slug='HPT-00000002', name='Other', status='active')
        admin = User(
            id='admin-00001', tenant_id=tenant.id, email='admin@example.com',
            password_hash='unused', name='Admin', role='admin', status='active',
        )
        other_admin = User(
            id='admin-other', tenant_id=other.id, email='other@example.com',
            password_hash='unused', name='Other', role='admin', status='active',
        )
        db.session.add_all([
            tenant,
            other,
            admin,
            other_admin,
            Employee(
                id='employee-zhang', tenant_id=tenant.id, employee_no='HJ-0001',
                name='张三', status='active',
            ),
        ])
        db.session.commit()
        tokens = {
            'target': create_access_token(
                identity=admin.id,
                additional_claims={'role': 'admin', 'account_type': 'hrm', **tenant_claims_for(tenant)},
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


def test_external_client_only_executes_fixed_select_and_rolls_back(monkeypatch):
    events = []

    class Cursor:
        def execute(self, sql, params=None):
            events.append(('execute', sql, params))

        def fetchall(self):
            return []

    class Connection:
        def cursor(self, as_dict=False):
            assert as_dict is True
            return Cursor()

        def rollback(self):
            events.append(('rollback', None, None))

        def close(self):
            events.append(('close', None, None))

    connect_kwargs = {}

    def fake_connect(**kwargs):
        connect_kwargs.update(kwargs)
        return Connection()

    monkeypatch.setattr('services.attendance_punch_sync.pymssql.connect', fake_connect)
    client = AttendanceReadOnlyClient(
        host='kaoqin.example', port=2807, user='reader', password='secret', database='Kaoqin',
    )
    assert client.fetch_people() == []
    assert client.fetch_punches(since=datetime(2026, 8, 1, 0, 0, 0)) == []
    assert connect_kwargs['tds_version'] == '7.0'
    assert connect_kwargs['database'] == 'Kaoqin'
    statements = [sql for action, sql, _params in events if action == 'execute']
    assert statements
    assert all(sql.lstrip().upper().startswith(('SET TRANSACTION', 'SELECT')) for sql in statements)
    assert any('USERINFO' in sql.upper() for sql in statements)
    assert any('CHECKINOUT' in sql.upper() for sql in statements)
    assert not any(token in ' '.join(statements).upper() for token in ('INSERT', 'UPDATE', 'DELETE', 'PASSWORD', 'PHOTO', 'IDCARDNO'))
    assert ('rollback', None, None) in events
    assert ('close', None, None) in events


def test_sync_refuses_non_00001_tenant(sync_app):
    with sync_app.app_context():
        with pytest.raises(AttendanceSyncDisabled):
            sync_attendance_punches(
                people=[_person()],
                punches=[],
                tenant_slug='HPT-00000002',
                trigger='test',
            )


def test_sync_upserts_external_people_without_creating_employees(sync_app):
    with sync_app.app_context():
        result = sync_attendance_punches(
            people=[_person(), _person(external_user_id=202, badge_number='9002', name='王五')],
            punches=[],
            trigger='test',
        )
        assert result.people_read == 2
        assert result.people_upserted == 2
        assert Employee.query.filter_by(tenant_id='tenant-00001').count() == 2
        people = AttendanceExternalPerson.query.filter_by(tenant_id='tenant-00001').all()
        assert {row.external_user_id for row in people} == {'101', '202'}
        wang = AttendanceExternalPerson.query.filter_by(external_user_id='202').one()
        assert wang.mapping_status == 'unmatched'
        assert wang.employee_id is None


def test_unique_name_match_is_auto_confirmed(sync_app):
    with sync_app.app_context():
        result = sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        employee = db.session.get(Employee, 'employee-zhang')
        assert person.mapping_status == 'confirmed'
        assert person.suggested_employee_id == 'employee-zhang'
        assert person.employee_id == 'employee-zhang'
        assert employee.employee_no == '9001'
        assert result.suggested_count == 0
        assert result.confirmed_count == 1


def test_badge_number_match_is_suggested_and_auto_confirmed(sync_app):
    with sync_app.app_context():
        employee = db.session.get(Employee, 'employee-zhang')
        employee.employee_no = '108'
        db.session.commit()

        # 姓名故意改成匹配不上的，验证是靠工号（BADGENUMBER）匹配的
        sync_attendance_punches(
            people=[_person(badge_number='108', name='张三改名')], punches=[], trigger='test'
        )

        person = AttendanceExternalPerson.query.filter_by(
            tenant_id='tenant-00001', external_user_id=101
        ).one()
        assert person.mapping_status == 'confirmed'
        assert person.employee_id == 'employee-zhang'


def test_existing_confirmed_mapping_reconciles_employee_number_from_badge(sync_app):
    with sync_app.app_context():
        sync_attendance_punches(
            people=[_person(badge_number='17')],
            punches=[],
            trigger='test',
        )
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        assert person.mapping_status == 'confirmed'
        db.session.commit()

        sync_attendance_punches(
            people=[_person(badge_number='18')],
            punches=[],
            trigger='test',
        )

        employee = db.session.get(Employee, 'employee-zhang')
        assert employee.employee_no == '18'


def test_badge_assignment_releases_legacy_oa_workcode_collision(sync_app):
    with sync_app.app_context():
        stale = db.session.get(Employee, 'employee-li')
        stale.source_system = 'oa_ecology'
        stale.employee_no = '9001'
        db.session.commit()

        sync_attendance_punches(people=[_person()], punches=[], trigger='test')

        assert db.session.get(Employee, 'employee-zhang').employee_no == '9001'
        assert db.session.get(Employee, 'employee-li').employee_no is None


def test_mapped_punches_become_employee_daily_attendance_records(sync_app):
    punches = [
        _punch(check_time=datetime(2026, 8, 20, 8, 1, 0)),
        _punch(check_time=datetime(2026, 8, 20, 18, 1, 0)),
        _punch(check_time=datetime(2026, 8, 21, 8, 5, 0)),
    ]
    with sync_app.app_context():
        result = sync_attendance_punches(people=[_person()], punches=punches, trigger='test')
        rows = (
            AttendanceRecord.query.filter_by(employee_id='employee-zhang')
            .order_by(AttendanceRecord.attendance_date.asc())
            .all()
        )
        assert result.daily_records_upserted == 2
        assert len(rows) == 2
        first, second = rows
        assert first.attendance_date == date(2026, 8, 20)
        assert first.status == 'normal'
        assert first.source == 'kaoqin'
        assert first.check_in_time == datetime(2026, 8, 20, 8, 1, 0)
        assert first.check_out_time == datetime(2026, 8, 20, 18, 1, 0)
        assert Decimal(str(first.work_hours)) == Decimal('10.00')
        assert second.attendance_date == date(2026, 8, 21)
        assert second.status == 'missing_card'
        assert second.check_in_time == datetime(2026, 8, 21, 8, 5, 0)
        assert second.check_out_time is None


def test_rebuild_does_not_overwrite_manual_attendance_record(sync_app):
    with sync_app.app_context():
        db.session.add(AttendanceRecord(
            id='manual-zhang-20260820',
            employee_id='employee-zhang',
            attendance_date=date(2026, 8, 20),
            status='leave',
            source='manual',
            remark='已批请假',
        ))
        db.session.commit()
        sync_attendance_punches(
            people=[_person()],
            punches=[
                _punch(check_time=datetime(2026, 8, 20, 8, 1, 0)),
                _punch(check_time=datetime(2026, 8, 20, 18, 1, 0)),
            ],
            trigger='test',
        )
        row = AttendanceRecord.query.filter_by(
            employee_id='employee-zhang', attendance_date=date(2026, 8, 20),
        ).one()
        assert row.id == 'manual-zhang-20260820'
        assert row.status == 'leave'
        assert row.source == 'manual'
        assert row.remark == '已批请假'


def test_duplicate_employee_names_are_not_auto_confirmed(sync_app):
    with sync_app.app_context():
        db.session.add(Employee(
            id='employee-zhang-2', tenant_id='tenant-00001', employee_no='HJ-0009',
            name='张三', status='active',
        ))
        db.session.commit()
        sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        assert person.mapping_status == 'unmatched'
        assert person.employee_id is None
        assert AttendanceRecord.query.count() == 0


def test_numeric_badge_suffix_is_not_used_for_matching(sync_app):
    with sync_app.app_context():
        sync_attendance_punches(
            people=[_person(external_user_id=303, badge_number='0001', name='王五')],
            punches=[],
            trigger='test',
        )
        person = AttendanceExternalPerson.query.filter_by(external_user_id='303').one()
        assert person.mapping_status == 'unmatched'
        assert person.suggested_employee_id is None
        assert person.employee_id is None


def test_confirmed_mapping_survives_name_change(sync_app):
    with sync_app.app_context():
        sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        confirm_external_person(person.id, employee_id='employee-zhang', actor_user_id='admin-00001')
        sync_attendance_punches(
            people=[_person(name='张三改名')],
            punches=[],
            trigger='test',
        )
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        assert person.name == '张三改名'
        assert person.mapping_status == 'confirmed'
        assert person.employee_id == 'employee-zhang'


def test_duplicate_punch_is_idempotent(sync_app):
    punch = _punch()
    with sync_app.app_context():
        first = sync_attendance_punches(people=[_person()], punches=[punch], trigger='test')
        second = sync_attendance_punches(people=[_person()], punches=[punch], trigger='test')
        assert first.punches_inserted == 1
        assert second.punches_inserted == 0
        assert second.punches_duplicate == 1
        assert AttendanceRawPunch.query.filter_by(tenant_id='tenant-00001').count() == 1
        stored = AttendanceRawPunch.query.one()
        assert stored.fingerprint == punch_fingerprint(punch)


def test_lookback_uses_cursor_minus_two_days(sync_app, monkeypatch):
    captured = {}

    class FakeClient:
        def fetch_people(self):
            return [_person()]

        def fetch_punches(self, *, since):
            captured['since'] = since
            return []

    monkeypatch.setattr(
        'services.attendance_punch_sync.AttendanceReadOnlyClient.from_environment',
        classmethod(lambda cls: FakeClient()),
    )
    with sync_app.app_context():
        cursor_time = datetime(2026, 8, 20, 18, 0, 0)
        db.session.add(AttendanceSyncRun(
            id='run-success',
            tenant_id='tenant-00001',
            run_trigger='manual',
            status='success',
            cursor_check_time=cursor_time,
            completed_at=datetime.utcnow(),
        ))
        db.session.commit()
        sync_attendance_punches(trigger='test')
        assert captured['since'] == cursor_time - timedelta(days=2)


def test_confirm_refuses_cross_tenant_employee(sync_app):
    with sync_app.app_context():
        sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        with pytest.raises(LookupError):
            confirm_external_person(person.id, employee_id='employee-other', actor_user_id='admin-00001')
        person = db.session.get(AttendanceExternalPerson, person.id)
        assert person.employee_id == 'employee-zhang'
        assert person.mapping_status == 'confirmed'


def test_ignore_keeps_person_out_of_auto_suggest(sync_app):
    with sync_app.app_context():
        sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        ignore_external_person(person.id, actor_user_id='admin-00001')
        sync_attendance_punches(people=[_person()], punches=[], trigger='test')
        person = AttendanceExternalPerson.query.filter_by(external_user_id='101').one()
        assert person.mapping_status == 'ignored'
        assert person.employee_id is None
        ignored = list_external_people(status='ignored')
        assert [row.external_user_id for row in ignored] == ['101']


def test_status_is_hidden_from_other_tenants(route_app):
    app, tokens = route_app
    response = app.test_client().get(
        '/api/hrm/attendance-sync/status',
        headers={'Authorization': f"Bearer {tokens['other']}"},
    )
    assert response.status_code == 404


def test_attendance_records_list_is_tenant_scoped_after_kaoqin_rollup(route_app):
    app, tokens = route_app
    with app.app_context():
        sync_attendance_punches(
            people=[_person()],
            punches=[
                _punch(check_time=datetime(2026, 8, 20, 8, 1, 0)),
                _punch(check_time=datetime(2026, 8, 20, 18, 1, 0)),
            ],
            trigger='test',
        )
    client = app.test_client()
    target = client.get(
        '/api/hrm/attendance-records?page=1&size=50',
        headers={'Authorization': f"Bearer {tokens['target']}"},
    )
    other = client.get(
        '/api/hrm/attendance-records?page=1&size=50',
        headers={'Authorization': f"Bearer {tokens['other']}"},
    )
    assert target.status_code == 200
    payload = target.get_json()
    assert payload['total'] == 1
    assert payload['items'][0]['employeeName'] == '张三'
    assert payload['items'][0]['status'] == 'normal'
    assert payload['items'][0]['source'] == 'kaoqin'
    assert other.status_code == 200
    assert other.get_json()['total'] == 0


def test_status_does_not_connect_to_external_db(route_app, monkeypatch):
    app, tokens = route_app

    def fail_connect(**_kwargs):
        raise AssertionError('status must not connect to attendance SQL Server')

    monkeypatch.setattr('services.attendance_punch_sync.pymssql.connect', fail_connect)
    response = app.test_client().get(
        '/api/hrm/attendance-sync/status',
        headers={'Authorization': f"Bearer {tokens['target']}"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['tenantSlug'] == ATTENDANCE_TENANT_SLUG
    assert payload['latestRun'] is None


def test_sync_accepts_explicit_since_for_backfill(sync_app, monkeypatch):
    """手动同步可用 since 回补更早的打卡（默认增量窗口之外）。"""
    captured = {}

    class _FakeClient:
        def fetch_people(self):
            return [_person()]

        def fetch_punches(self, *, since):
            captured['since'] = since
            return [_punch()]

    monkeypatch.setattr(
        'services.attendance_punch_sync.AttendanceReadOnlyClient.from_environment',
        classmethod(lambda cls: _FakeClient()),
    )
    with sync_app.app_context():
        result = sync_attendance_punches(trigger='manual', since=datetime(2026, 8, 1))
        assert captured['since'] == datetime(2026, 8, 1)
        assert result.punches_inserted == 1
        assert AttendanceRawPunch.query.filter_by(tenant_id='tenant-00001').count() == 1
