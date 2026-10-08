from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Employee,
    EmployeeChange,
    PayrollRecord,
    PerformanceCycle,
    PerformanceReview,
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
            employee_no='E2026060001',
            name='Performance User',
            status='active',
            hire_date=date(2025, 1, 1),
        )
        cycle = PerformanceCycle(
            id='cycle-2026-h1',
            name='2026 H1 Performance',
            cycle_type='half_year',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
            status='closed',
        )
        review = PerformanceReview(
            id='review-1',
            employee_id=employee.id,
            cycle_id=cycle.id,
            manager_score=Decimal('94.00'),
            final_score=Decimal('92.00'),
            grade='A',
            result='Exceeds expectations',
            status='completed',
        )
        profile = SalaryProfile(
            id='salary-1',
            employee_id=employee.id,
            base_salary=Decimal('10000.00'),
            position_salary=Decimal('1000.00'),
            performance_salary=Decimal('2000.00'),
            allowance=Decimal('500.00'),
            status='active',
        )
        db.session.add_all([user, employee, cycle, review, profile])
        db.session.commit()
        token = create_access_token(identity=user.id, additional_claims={'role': user.role, 'name': user.name})

    yield app.test_client(), app, token

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_performance_review_creates_audited_salary_change_before_payroll(hrm_client):
    client, app, token = hrm_client

    first = client.post(
        '/api/hrm/performance-reviews/review-1/generate-salary-change',
        json={'salaryAdjustment': 800, 'effectiveDate': '2026-07-01'},
        headers=auth_header(token),
    )

    assert first.status_code == 200
    body = first.get_json()
    assert body['created'] is True
    assert body['flow']['id'] == 'performance_to_compensation'
    assert body['flow']['modules'] == [
        'performance-reviews',
        'employee-changes',
        'salary-profiles',
        'payroll-records',
    ]
    assert body['performanceReview']['id'] == 'review-1'
    assert body['salaryChange']['changeType'] == 'performance_salary_adjustment'
    assert body['salaryChange']['status'] == 'draft'
    assert body['salaryChange']['salaryAdjustment'] == 800.0
    assert body['salaryChange']['effectiveDate'] == '2026-07-01'
    assert 'performance review review-1' in body['salaryChange']['reason']
    assert body['salaryProfile']['performanceSalary'] == 2000.0

    with app.app_context():
        assert SalaryProfile.query.get('salary-1').performance_salary == Decimal('2000.00')
        assert EmployeeChange.query.filter_by(employee_id='emp-1', change_type='performance_salary_adjustment').count() == 1

    second = client.post(
        '/api/hrm/performance-reviews/review-1/generate-salary-change',
        json={'salaryAdjustment': 800, 'effectiveDate': '2026-07-01'},
        headers=auth_header(token),
    )

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body['created'] is False

    change_id = body['salaryChange']['id']
    approved = client.put(
        f'/api/hrm/employee-changes/{change_id}',
        json={'status': 'approved'},
        headers=auth_header(token),
    )

    assert approved.status_code == 200
    assert approved.get_json()['status'] == 'approved'

    with app.app_context():
        profile = SalaryProfile.query.get('salary-1')
        assert profile.performance_salary == Decimal('2800.00')
        assert 'performance review review-1' in profile.remark
        assert profile.remark.count('performance review review-1') == 1

    approved_again = client.put(
        f'/api/hrm/employee-changes/{change_id}',
        json={'status': 'approved'},
        headers=auth_header(token),
    )

    assert approved_again.status_code == 200

    with app.app_context():
        profile = SalaryProfile.query.get('salary-1')
        assert profile.performance_salary == Decimal('2800.00')
        assert profile.remark.count('performance review review-1') == 1

    payroll = client.post(
        '/api/hrm/payroll-records/generate-month',
        json={'month': '2026-07'},
        headers=auth_header(token),
    )

    assert payroll.status_code == 200
    payroll_body = payroll.get_json()
    assert payroll_body['records'][0]['performanceSalary'] == 2800.0
    assert payroll_body['records'][0]['grossSalary'] == 14300.0
    assert payroll_body['records'][0]['netSalary'] == 14300.0

    with app.app_context():
        assert PayrollRecord.query.filter_by(employee_id='emp-1', payroll_month='2026-07').count() == 1
