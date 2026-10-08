from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Employee,
    PerformanceCycle,
    PerformanceReview,
    TrainingCourse,
    TrainingPlan,
    TrainingRecord,
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
            role='hr_admin',
            status='active',
        )
        employee = Employee(
            id='emp-1',
            employee_no='E2026060001',
            name='Growth User',
            status='active',
            hire_date=date(2025, 1, 1),
        )
        cycle = PerformanceCycle(
            id='cycle-2026-q2',
            name='2026 Q2 Performance',
            cycle_type='quarter',
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            status='closed',
        )
        review = PerformanceReview(
            id='review-1',
            employee_id=employee.id,
            cycle_id=cycle.id,
            final_score=Decimal('58.00'),
            grade='D',
            result='Needs structured coaching on delivery quality',
            status='completed',
        )
        db.session.add_all([user, employee, cycle, review])
        db.session.commit()
        token = create_access_token(identity=user.id, additional_claims={'role': user.role, 'name': user.name})

    yield app.test_client(), app, token

    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth_header(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def test_performance_review_creates_training_development_chain_idempotently(hrm_client):
    client, app, token = hrm_client

    first = client.post(
        '/api/hrm/performance-reviews/review-1/generate-training-plan',
        json={
            'courseName': 'Delivery Quality Improvement',
            'planName': 'Growth User Q2 Coaching Plan',
            'startTime': '2026-07-01T09:00:00',
            'endTime': '2026-07-31T18:00:00',
        },
        headers=auth_header(token),
    )

    assert first.status_code == 200
    body = first.get_json()
    assert body['created'] is True
    assert body['flow']['id'] == 'performance_to_growth'
    assert body['flow']['modules'] == [
        'performance-reviews',
        'training-courses',
        'training-plans',
        'training-records',
    ]
    assert body['performanceReview']['id'] == 'review-1'
    assert body['trainingCourse']['name'] == 'Delivery Quality Improvement'
    assert body['trainingPlan']['name'] == 'Growth User Q2 Coaching Plan'
    assert body['trainingRecord']['employeeId'] == 'emp-1'
    assert body['trainingRecord']['status'] == 'registered'
    assert 'performance review review-1' in body['trainingPlan']['remark']
    assert 'final score 58.00' in body['trainingRecord']['feedback']

    with app.app_context():
        assert TrainingCourse.query.count() == 1
        assert TrainingPlan.query.count() == 1
        assert TrainingRecord.query.count() == 1

    second = client.post(
        '/api/hrm/performance-reviews/review-1/generate-training-plan',
        json={
            'courseName': 'Delivery Quality Improvement',
            'planName': 'Growth User Q2 Coaching Plan',
        },
        headers=auth_header(token),
    )

    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body['created'] is False
    assert second_body['trainingCourse']['id'] == body['trainingCourse']['id']
    assert second_body['trainingPlan']['id'] == body['trainingPlan']['id']
    assert second_body['trainingRecord']['id'] == body['trainingRecord']['id']

    with app.app_context():
        assert TrainingCourse.query.count() == 1
        assert TrainingPlan.query.count() == 1
        assert TrainingRecord.query.count() == 1
