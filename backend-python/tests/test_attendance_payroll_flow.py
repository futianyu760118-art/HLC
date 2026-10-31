from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    AttendanceRecord,
    Employee,
    EmployeeRequest,
    PayrollRecord,
    SalaryProfile,
    User,
    db,
)
from routes.hrm import hrm_bp


@pytest.fixture()
def hrm_client():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret',
        JWT_SECRET_KEY='test-jwt-secret',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')

    with app.app_context():
        db.create_all()
        user = User(
            id='admin-1',
            email='admin@example.com',
            password_hash='x',
            name='Admin',
            role='admin',
            status='active',
        )
        employee = Employee(
            id='emp-1',
            employee_no='E2026050001',
            name='Payroll User',
            email='payroll@example.com',
            status='active',
            hire_date=date(2026, 1, 1),
        )
        inactive_employee = Employee(
            id='emp-inactive',
            employee_no='E2026050002',
            name='Inactive User',
            status='resigned',
        )
        profile = SalaryProfile(
            id='profile-1',
            employee_id=employee.id,
            base_salary=Decimal('10000.00'),
            position_salary=Decimal('2000.00'),
            performance_salary=Decimal('3000.00'),
            allowance=Decimal('500.00'),
            bonus=Decimal('1000.00'),
            deduction=Decimal('300.00'),
            status='active',
        )
        inactive_profile = SalaryProfile(
            id='profile-inactive',
            employee_id=inactive_employee.id,
            base_salary=Decimal('9000.00'),
            status='active',
        )
        db.session.add_all([user, employee, inactive_employee, profile, inactive_profile])
        db.session.add_all([
            AttendanceRecord(
                id='att-normal',
                employee_id=employee.id,
                attendance_date=date(2026, 5, 4),
                work_hours=Decimal('8.00'),
                status='normal',
            ),
            AttendanceRecord(
                id='att-late',
                employee_id=employee.id,
                attendance_date=date(2026, 5, 5),
                work_hours=Decimal('8.00'),
                status='late',
            ),
            AttendanceRecord(
                id='att-missing',
                employee_id=employee.id,
                attendance_date=date(2026, 5, 6),
                status='missing_card',
            ),
            AttendanceRecord(
                id='att-other-month',
                employee_id=employee.id,
                attendance_date=date(2026, 4, 30),
                status='late',
            ),
            EmployeeRequest(
                id='req-leave',
                employee_id=employee.id,
                request_type='leave',
                title='leave request',
                start_time=datetime(2026, 5, 7, 9, 0, 0),
                end_time=datetime(2026, 5, 7, 18, 0, 0),
                duration_hours=Decimal('8.00'),
                status='approved',
            ),
            EmployeeRequest(
                id='req-overtime',
                employee_id=employee.id,
                request_type='overtime',
                title='overtime request',
                start_time=datetime(2026, 5, 8, 18, 0, 0),
                end_time=datetime(2026, 5, 8, 22, 0, 0),
                duration_hours=Decimal('4.00'),
                status='approved',
            ),
            EmployeeRequest(
                id='req-draft-leave',
                employee_id=employee.id,
                request_type='leave',
                title='draft leave request',
                start_time=datetime(2026, 5, 9, 9, 0, 0),
                end_time=datetime(2026, 5, 9, 18, 0, 0),
                duration_hours=Decimal('8.00'),
                status='draft',
            ),
            EmployeeRequest(
                id='req-approved-travel',
                employee_id=employee.id,
                request_type='travel',
                title='approved travel request',
                start_time=datetime(2026, 5, 10, 9, 0, 0),
                end_time=datetime(2026, 5, 10, 18, 0, 0),
                duration_hours=Decimal('8.00'),
                status='approved',
            ),
        ])
        db.session.commit()
        token = create_access_token(identity=user.id, additional_claims={'role': user.role, 'name': user.name})

    yield app.test_client(), app, token

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_generate_monthly_payroll_links_attendance_requests_and_salary_profile(hrm_client):
    client, app, token = hrm_client

    first = client.post(
        '/api/hrm/payroll-records/generate-month',
        json={'month': '2026-05'},
        headers=auth_header(token),
    )

    assert first.status_code == 200
    body = first.get_json()
    assert body['flow']['id'] == 'attendance_to_payroll'
    assert body['flow']['modules'] == [
        'attendance-records',
        'employee-requests',
        'salary-profiles',
        'payroll-records',
    ]
    assert body['month'] == '2026-05'
    assert body['createdCount'] == 1
    assert body['updatedCount'] == 0
    assert body['skippedCount'] == 1
    assert body['metrics']['attendanceRecords'] == 3
    assert body['metrics']['approvedLeaveHours'] == 8.0
    assert body['metrics']['approvedOvertimeHours'] == 4.0

    assert len(body['records']) == 1
    record = body['records'][0]
    assert record['employeeId'] == 'emp-1'
    assert record['payrollMonth'] == '2026-05'
    assert record['baseSalary'] == 10000.0
    assert record['positionSalary'] == 2000.0
    assert record['performanceSalary'] == 3000.0
    assert record['allowance'] == 500.0
    assert record['bonus'] == 1344.83
    assert record['grossSalary'] == 16844.83
    assert record['deduction'] == 829.77
    assert record['netSalary'] == 16015.06
    assert record['status'] == 'calculated'
    assert record['employeeVisible'] is False
    assert 'attendance: normal=1, late=1, missing_card=1' in record['remark']
    assert 'requests: leave_hours=8.00, overtime_hours=4.00' in record['remark']

    with app.app_context():
        saved = PayrollRecord.query.filter_by(employee_id='emp-1', payroll_month='2026-05').one()
        assert saved.net_salary == Decimal('16015.06')
        assert PayrollRecord.query.count() == 1

    second = client.post(
        '/api/hrm/payroll-records/generate-month',
        json={'month': '2026-05'},
        headers=auth_header(token),
    )

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body['createdCount'] == 0
    assert second_body['updatedCount'] == 1
    assert len(second_body['records']) == 1

    with app.app_context():
        assert PayrollRecord.query.filter_by(employee_id='emp-1', payroll_month='2026-05').count() == 1


def test_attendance_monthly_combines_attendance_records_and_approved_requests(hrm_client):
    client, _app, token = hrm_client

    response = client.get(
        '/api/hrm/attendance/monthly?month=2026-05',
        headers=auth_header(token),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['flow']['id'] == 'attendance_to_payroll'
    assert body['sourceCounts']['attendanceRecords'] == 4
    assert body['sourceCounts']['approvedRequests'] == 3
    assert len(body['requestSources']) == 3

    row = next(item for item in body['records'] if item['employeeId'] == 'emp-1')
    assert row['normal'] == 1
    assert row['late'] == 1
    assert row['missingCard'] == 1
    assert row['leave'] == 1
    assert row['overtime'] == 1
    assert row['travel'] == 1
    assert row['approvedRequests'] == 3
    assert row['exceptions'] == 2
