from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Candidate,
    Contract,
    Employee,
    Job,
    Notification,
    Offer,
    OnboardingTask,
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
            name='管理员',
            role='admin',
            status='active',
        )
        job = Job(
            id='job-1',
            title='电子工程师',
            department='研发部',
            department_id='dept-rd',
            status='open',
        )
        candidate = Candidate(
            id='candidate-1',
            job_id=job.id,
            name='胡国卫',
            email='hu@example.com',
            phone='13800000000',
            status='offer_accepted',
        )
        offer = Offer(
            id='offer-1',
            candidate_id=candidate.id,
            job_id=job.id,
            title='胡国卫 - 电子工程师 Offer',
            salary=Decimal('18000.00'),
            onboarding_date=date(2026, 6, 8),
            status='accepted',
            approval_status='approved',
        )
        db.session.add_all([user, job, candidate, offer])
        db.session.commit()
        token = create_access_token(identity=user.id, additional_claims={'role': user.role, 'name': user.name})

    yield app.test_client(), app, token

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_offer_convert_creates_complete_onboarding_chain_and_is_idempotent(hrm_client):
    client, app, token = hrm_client

    first = client.post('/api/hrm/offers/offer-1/convert-to-employee', headers=auth_header(token))

    assert first.status_code == 200
    body = first.get_json()
    assert body['created'] is True
    assert body['flow']['id'] == 'recruit_to_onboard'
    assert body['employee']['name'] == '胡国卫'
    assert len(body['onboardingTasks']) == 7
    assert body['contract']['contractType'] == '劳动合同'
    assert body['contract']['startDate'] == '2026-06-08'
    assert body['salaryProfile']['baseSalary'] == 18000.0

    with app.app_context():
        employee = Employee.query.filter_by(source_offer_id='offer-1').one()
        assert employee.status == 'pending_onboard'
        assert employee.hire_date == date(2026, 6, 8)
        assert Offer.query.get('offer-1').employee_id == employee.id
        assert Candidate.query.get('candidate-1').status == 'converted'
        assert OnboardingTask.query.filter_by(employee_id=employee.id).count() == 7
        assert Contract.query.filter_by(employee_id=employee.id).count() == 1
        assert SalaryProfile.query.filter_by(employee_id=employee.id).count() == 1
        assert Notification.query.filter_by(user_id='admin-1', notice_type='employee').count() == 1

    second = client.post('/api/hrm/offers/offer-1/convert-to-employee', headers=auth_header(token))

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body['created'] is False
    assert len(second_body['onboardingTasks']) == 7
    assert second_body['contract']['contractType'] == '劳动合同'
    assert second_body['salaryProfile']['baseSalary'] == 18000.0

    with app.app_context():
        employee = Employee.query.filter_by(source_offer_id='offer-1').one()
        assert Employee.query.filter_by(source_offer_id='offer-1').count() == 1
        assert OnboardingTask.query.filter_by(employee_id=employee.id).count() == 7
        assert Contract.query.filter_by(employee_id=employee.id).count() == 1
        assert SalaryProfile.query.filter_by(employee_id=employee.id).count() == 1
        assert Notification.query.filter_by(user_id='admin-1', notice_type='employee').count() == 1
