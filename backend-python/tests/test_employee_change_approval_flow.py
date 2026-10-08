from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    ApprovalInstance,
    ApprovalRecord,
    Department,
    Employee,
    EmployeeChange,
    Position,
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
        admin = User(
            id='admin-1',
            email='admin@example.com',
            password_hash='x',
            name='Admin',
            role='admin',
            status='active',
        )
        manager = User(
            id='manager-1',
            email='manager@example.com',
            password_hash='x',
            name='Manager',
            role='manager',
            status='active',
        )
        source_dept = Department(id='dept-source', name='Source Dept', code='SRC', status='active')
        target_dept = Department(id='dept-target', name='Target Dept', code='TGT', status='active')
        source_position = Position(
            id='pos-source',
            title='Source Engineer',
            department_id=source_dept.id,
            level='P3',
            status='active',
        )
        target_position = Position(
            id='pos-target',
            title='Target Specialist',
            department_id=target_dept.id,
            level='P4',
            status='active',
        )
        employee = Employee(
            id='emp-1',
            employee_no='E2026060001',
            name='Change User',
            status='active',
            department_id=source_dept.id,
            position_id=source_position.id,
            job_title=source_position.title,
            hire_date=date(2025, 1, 1),
        )
        profile = SalaryProfile(
            id='salary-1',
            employee_id=employee.id,
            base_salary=Decimal('10000.00'),
            performance_salary=Decimal('2000.00'),
            status='active',
        )
        change = EmployeeChange(
            id='change-1',
            employee_id=employee.id,
            change_type='salary_adjustment',
            salary_adjustment=Decimal('500.00'),
            effective_date=date(2026, 6, 1),
            reason='Annual compensation approval',
            status='draft',
            created_by=admin.id,
        )
        db.session.add_all([
            admin, manager,
            source_dept, target_dept, source_position, target_position,
            employee, profile, change,
        ])
        db.session.commit()
        tokens = {
            'admin': create_access_token(identity=admin.id, additional_claims={'role': admin.role, 'name': admin.name}),
            'manager': create_access_token(identity=manager.id, additional_claims={'role': manager.role, 'name': manager.name}),
        }

    yield app.test_client(), app, tokens

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_employee_change_applies_salary_adjustment_only_after_approval(hrm_client):
    client, app, tokens = hrm_client

    submitted = client.post(
        '/api/hrm/employee-changes/change-1/submit',
        headers=auth_header(tokens['admin']),
    )

    assert submitted.status_code == 200
    submitted_body = submitted.get_json()
    assert submitted_body['record']['status'] == 'pending'
    assert submitted_body['approval']['businessType'] == 'employee_change'
    assert submitted_body['approval']['businessId'] == 'change-1'
    approval_id = submitted_body['approval']['id']

    with app.app_context():
        profile = SalaryProfile.query.get('salary-1')
        change = EmployeeChange.query.get('change-1')
        assert profile.performance_salary == Decimal('2000.00')
        assert change.status == 'pending'
        assert ApprovalInstance.query.filter_by(
            business_type='employee_change',
            business_id='change-1',
            status='pending',
        ).count() == 1

    pending = client.get('/api/hrm/approvals/pending', headers=auth_header(tokens['admin']))

    assert pending.status_code == 200
    assert any(item['id'] == approval_id for item in pending.get_json())

    approved = client.post(
        f'/api/hrm/approvals/{approval_id}/approve',
        json={'comment': 'Approved compensation change'},
        headers=auth_header(tokens['manager']),
    )

    assert approved.status_code == 200
    approved_body = approved.get_json()
    assert approved_body['approval']['status'] == 'approved'
    assert approved_body['record']['action'] == 'approved'

    with app.app_context():
        change = EmployeeChange.query.get('change-1')
        profile = SalaryProfile.query.get('salary-1')
        assert change.status == 'approved'
        assert profile.performance_salary == Decimal('2500.00')
        assert profile.remark.count('[employee_change:change-1:applied]') == 1
        assert ApprovalRecord.query.filter_by(approval_id=approval_id).count() == 1

    approved_again = client.post(
        f'/api/hrm/approvals/{approval_id}/approve',
        json={'comment': 'Duplicate approval should not reapply'},
        headers=auth_header(tokens['manager']),
    )

    assert approved_again.status_code == 400

    with app.app_context():
        profile = SalaryProfile.query.get('salary-1')
        assert profile.performance_salary == Decimal('2500.00')
        assert profile.remark.count('[employee_change:change-1:applied]') == 1


def test_employee_change_supports_chinese_salary_adjustment_type(hrm_client):
    client, app, tokens = hrm_client

    with app.app_context():
        db.session.add(EmployeeChange(
            id='change-cn',
            employee_id='emp-1',
            change_type='调薪',
            salary_adjustment=Decimal('800.00'),
            effective_date=date(2026, 7, 1),
            reason='转正后薪资调整',
            status='draft',
            created_by='admin-1',
        ))
        db.session.commit()

    submitted = client.post(
        '/api/hrm/employee-changes/change-cn/submit',
        headers=auth_header(tokens['admin']),
    )
    assert submitted.status_code == 200
    approval_id = submitted.get_json()['approval']['id']

    approved = client.post(
        f'/api/hrm/approvals/{approval_id}/approve',
        json={'comment': '同意调薪'},
        headers=auth_header(tokens['manager']),
    )
    assert approved.status_code == 200

    with app.app_context():
        profile = SalaryProfile.query.get('salary-1')
        assert EmployeeChange.query.get('change-cn').status == 'approved'
        assert profile.performance_salary == Decimal('2800.00')
        assert profile.remark.count('[employee_change:change-cn:applied]') == 1


def test_employee_transfer_updates_profile_only_after_approval(hrm_client):
    client, app, tokens = hrm_client

    with app.app_context():
        db.session.add(EmployeeChange(
            id='change-transfer',
            employee_id='emp-1',
            change_type='transfer',
            before_department_id='dept-source',
            after_department_id='dept-target',
            before_position_id='pos-source',
            after_position_id='pos-target',
            before_level='P3',
            after_level='P4',
            effective_date=date(2026, 8, 1),
            reason='Organization transfer approval',
            status='draft',
            created_by='admin-1',
        ))
        db.session.commit()

    submitted = client.post(
        '/api/hrm/employee-changes/change-transfer/submit',
        headers=auth_header(tokens['admin']),
    )
    assert submitted.status_code == 200
    approval_id = submitted.get_json()['approval']['id']

    with app.app_context():
        employee = Employee.query.get('emp-1')
        change = EmployeeChange.query.get('change-transfer')
        assert change.status == 'pending'
        assert employee.department_id == 'dept-source'
        assert employee.position_id == 'pos-source'
        assert employee.job_title == 'Source Engineer'

    approved = client.post(
        f'/api/hrm/approvals/{approval_id}/approve',
        json={'comment': 'Approved transfer change'},
        headers=auth_header(tokens['manager']),
    )
    assert approved.status_code == 200

    with app.app_context():
        employee = Employee.query.get('emp-1')
        change = EmployeeChange.query.get('change-transfer')
        assert change.status == 'approved'
        assert employee.department_id == 'dept-target'
        assert employee.position_id == 'pos-target'
        assert employee.job_title == 'Target Specialist'
        assert '职级调整为：P4' in (employee.remark or '')
        assert ApprovalRecord.query.filter_by(approval_id=approval_id).count() == 1

    approved_again = client.post(
        f'/api/hrm/approvals/{approval_id}/approve',
        json={'comment': 'Duplicate transfer approval should not reapply'},
        headers=auth_header(tokens['manager']),
    )
    assert approved_again.status_code == 400

    with app.app_context():
        employee = Employee.query.get('emp-1')
        assert employee.department_id == 'dept-target'
        assert employee.position_id == 'pos-target'
        assert (employee.remark or '').count('职级调整为：P4') == 1
