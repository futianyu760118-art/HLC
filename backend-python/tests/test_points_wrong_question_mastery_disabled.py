"""错题本不再计分（2026-08-13 规则收紧）回归测试。"""

from datetime import date, datetime

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Department,
    Employee,
    PointLog,
    Tenant,
    User,
    WrongQuestion,
    db,
)
from routes.portal import portal_bp
from services.points import (
    award_points,
    get_employee_point_logs,
    get_employee_total_points,
    get_leaderboard,
    get_points_by_employee,
)


@pytest.fixture()
def points_env(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='test',
        JWT_SECRET_KEY='test',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(tmp_path / 'uploads'),
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(portal_bp, url_prefix='/api/portal')

    now = datetime.utcnow()
    with app.app_context():
        db.create_all()
        tenant = Tenant(
            id='tenant-points',
            name='积分测试企业',
            slug='points-test',
            status='active',
            plan_code='enterprise',
        )
        department = Department(id='dept-points', tenant_id=tenant.id, name='研发部')
        employee = Employee(
            id='employee-points',
            tenant_id=tenant.id,
            employee_no='PT001',
            name='积分员工',
            email='points@example.com',
            status='active',
            hire_date=date(2025, 1, 1),
            department_id=department.id,
            job_title='工程师',
        )
        user = User(
            id='user-points',
            tenant_id=tenant.id,
            email='points@example.com',
            password_hash='x',
            name='积分员工',
            role='employee',
            status='active',
            employee_id=employee.id,
        )
        wrong_questions = [
            WrongQuestion(
                id=f'wq-{index:02d}',
                employee_id=employee.id,
                question_id=f'q-{index:02d}',
                snapshot={
                    'id': f'q-{index:02d}',
                    'type': 'single',
                    'stem': f'题目{index}',
                    'options': ['A', 'B', 'C', 'D'],
                    'answer': [0],
                    'score': 2,
                },
                user_answer=[1],
                course_id='course-spc',
                category='安全合规',
                wrong_count=1,
                mastery='wrong',
                last_wrong_at=now,
            )
            for index in range(12)
        ]
        db.session.add_all([tenant, department, employee, user, *wrong_questions])
        db.session.commit()
        token = create_access_token('user-points', additional_claims={'role': 'employee'})

    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    yield app, client


def _add_mastery_logs(employee_id, count=12):
    now = datetime.utcnow()
    db.session.add_all([
        PointLog(
            id=f'mastery-{index:02d}',
            tenant_id='tenant-points',
            employee_id=employee_id,
            action='wrong_question_mastered',
            points=10,
            ref_id=f'wq-{index:02d}',
            detail='掌握错题',
            created_at=now,
        )
        for index in range(count)
    ])
    db.session.commit()


def test_award_points_rejects_wrong_question_mastery(points_env):
    app, _client = points_env
    with app.app_context():
        awarded = award_points(
            'employee-points', 'wrong_question_mastered', ref_id='wq-00'
        )
        assert awarded is False
        rows = PointLog.query.filter_by(
            employee_id='employee-points', action='wrong_question_mastered'
        ).all()
        assert len(rows) == 0


def test_total_points_excludes_historical_mastery(points_env):
    app, _client = points_env
    with app.app_context():
        db.session.add_all([
            PointLog(
                id='hour-1', tenant_id='tenant-points',
                employee_id='employee-points',
                action='course_hour_finished', points=5, ref_id='h1',
            ),
            PointLog(
                id='course-1', tenant_id='tenant-points',
                employee_id='employee-points',
                action='course_completed', points=20, ref_id='c1',
            ),
        ])
        _add_mastery_logs('employee-points', count=12)
        total = get_employee_total_points('employee-points')
        assert total == 25


def test_point_log_list_hides_mastery(points_env):
    app, _client = points_env
    with app.app_context():
        db.session.add(PointLog(
            id='exam-1', tenant_id='tenant-points',
            employee_id='employee-points',
            action='exam_passed', points=50, ref_id='task-1',
        ))
        _add_mastery_logs('employee-points', count=12)
        logs = get_employee_point_logs('employee-points', limit=50)
        actions = [row['action'] for row in logs]
        assert 'wrong_question_mastered' not in actions
        assert 'exam_passed' in actions


def test_leaderboard_and_period_points_exclude_mastery(points_env):
    app, _client = points_env
    with app.app_context():
        db.session.add_all([
            PointLog(
                id='hour-1', tenant_id='tenant-points',
                employee_id='employee-points',
                action='course_hour_finished', points=5, ref_id='h1',
            ),
            PointLog(
                id='hour-2', tenant_id='tenant-points',
                employee_id='employee-points',
                action='course_hour_finished', points=5, ref_id='h2',
            ),
        ])
        _add_mastery_logs('employee-points', count=12)
        board = get_leaderboard(limit=10)
        assert board[0]['employeeId'] == 'employee-points'
        assert board[0]['totalPoints'] == 10
        period = get_points_by_employee()
        assert period.get('employee-points') == 10


def test_practice_wrong_questions_creates_no_point_logs(points_env):
    app, client = points_env
    answers = {f'wq-0{index}': [0] for index in range(1, 4)}
    response = client.post(
        '/api/portal/wrong-questions/practice', json={'answers': answers}
    )
    assert response.status_code == 200, response.get_json()
    with app.app_context():
        mastery_rows = PointLog.query.filter_by(
            employee_id='employee-points', action='wrong_question_mastered'
        ).all()
        assert len(mastery_rows) == 0
        mastered = WrongQuestion.query.filter_by(
            employee_id='employee-points', mastery='mastered'
        ).all()
        assert len(mastered) == 3
