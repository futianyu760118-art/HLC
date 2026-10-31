"""Employee portal learning-profile and point-idempotency regressions."""

from datetime import date, datetime, timedelta

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Certificate,
    Course,
    CourseHour,
    CourseHour,
    Department,
    Employee,
    ExamAssignment,
    ExamAttempt,
    ExamPaper,
    ExamTask,
    PointLog,
    Reward,
    Tenant,
    User,
    UserCourseProgress,
    UserHourProgress,
    db,
)
from routes.portal import portal_bp


@pytest.fixture()
def portal_env(tmp_path):
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
            id='tenant-learning-profile',
            name='学习档案测试企业',
            slug='learning-profile-test',
            status='active',
            plan_code='enterprise',
        )
        department = Department(id='dept-learning', tenant_id=tenant.id, name='产品部')
        employee = Employee(
            id='employee-learning',
            tenant_id=tenant.id,
            employee_no='LP001',
            name='学习员工',
            email='learning@example.com',
            status='active',
            hire_date=date(2025, 1, 1),
            department_id=department.id,
            job_title='产品经理',
        )
        user = User(
            id='user-learning',
            tenant_id=tenant.id,
            email='learning@example.com',
            password_hash='x',
            name='学习员工',
            role='employee',
            status='active',
            employee_id=employee.id,
        )
        completed_course = Course(
            id='course-completed', tenant_id=tenant.id, title='信息安全基础', is_show=True,
        )
        active_course = Course(
            id='course-active', tenant_id=tenant.id, title='产品需求分析', is_show=True,
        )
        completed_progress = UserCourseProgress(
            id='progress-completed', tenant_id=tenant.id, employee_id=employee.id,
            course_id=completed_course.id, hour_count=4, finished_count=4,
            progress=100, is_finished=True, finished_at=now - timedelta(days=2),
        )
        active_progress = UserCourseProgress(
            id='progress-active', tenant_id=tenant.id, employee_id=employee.id,
            course_id=active_course.id, hour_count=5, finished_count=2,
            progress=40, is_finished=False,
        )
        watched = UserHourProgress(
            id='watched-1', tenant_id=tenant.id, employee_id=employee.id,
            course_id=active_course.id, hour_id='hour-placeholder',
            total_duration=5400, watched_duration=3600, is_finished=False,
        )
        paper = ExamPaper(
            id='paper-product', tenant_id=tenant.id, title='产品能力测评卷',
            question_ids=[], total_score=100, pass_score=60,
        )
        task = ExamTask(
            id='task-product', tenant_id=tenant.id, paper_id=paper.id,
            title='产品经理能力认证', max_attempts=3, status='published',
        )
        assignment = ExamAssignment(
            id='assignment-product', tenant_id=tenant.id, task_id=task.id,
            employee_id=employee.id, attempts_used=3, status='passed',
        )
        attempts = [
            ExamAttempt(
                id='attempt-1', tenant_id=tenant.id, assignment_id=assignment.id,
                employee_id=employee.id, task_id=task.id, paper_id=paper.id,
                status='submitted', score=52, total_score=100, pass_score=60,
                passed=False, submitted_at=now - timedelta(days=3),
            ),
            ExamAttempt(
                id='attempt-2', tenant_id=tenant.id, assignment_id=assignment.id,
                employee_id=employee.id, task_id=task.id, paper_id=paper.id,
                status='submitted', score=86, total_score=100, pass_score=60,
                passed=True, submitted_at=now - timedelta(days=2),
            ),
            ExamAttempt(
                id='attempt-3', tenant_id=tenant.id, assignment_id=assignment.id,
                employee_id=employee.id, task_id=task.id, paper_id=paper.id,
                status='submitted', score=78, total_score=100, pass_score=60,
                passed=True, submitted_at=now - timedelta(days=1),
            ),
        ]
        certificate = Certificate(
            id='certificate-1', tenant_id=tenant.id, employee_id=employee.id,
            course_id=completed_course.id, employee_name=employee.name,
            course_title=completed_course.title, cert_no='CERT-TEST-0001',
            issued_at=now - timedelta(days=2),
        )
        db.session.add_all([
            tenant, department, employee, user, completed_course, active_course,
            completed_progress, active_progress, watched, paper, task, assignment,
            *attempts, certificate,
        ])
        db.session.commit()
        token = create_access_token('user-learning', additional_claims={'role': 'employee'})

    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    yield app, client


def test_learning_profile_deduplicates_exam_tasks_and_returns_business_names(portal_env):
    _app, client = portal_env

    response = client.get('/api/portal/my-profile')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['stats']['coursesFinished'] == 1
    assert payload['stats']['coursesInProgress'] == 1
    assert payload['stats']['examsTaken'] == 1
    assert payload['stats']['examsPassed'] == 1
    assert payload['stats']['certificatesEarned'] == 1
    assert payload['stats']['totalWatchedMinutes'] == 60

    assert len(payload['recentExams']) == 1
    exam = payload['recentExams'][0]
    assert exam['taskId'] == 'task-product'
    assert exam['taskTitle'] == '产品经理能力认证'
    assert exam['paperTitle'] == '产品能力测评卷'
    assert exam['attemptCount'] == 3
    assert exam['bestScore'] == 86
    assert exam['passed'] is True
    assert exam['latestAttemptId'] == 'attempt-3'

    course_names = {row['courseTitle'] for row in payload['recentCourses']}
    assert course_names == {'信息安全基础', '产品需求分析'}
    assert payload['certificates'][0]['courseTitle'] == '信息安全基础'


def test_learning_profile_deduplicates_duplicate_course_progress_and_hour_rows(portal_env):
    """同一课程的历史重复进度行只应产生一条课程记录。"""
    app, client = portal_env
    with app.app_context():
        duplicate_course = Course(
            id='course-duplicate', tenant_id='tenant-learning-profile',
            title='皓丽平板使用', is_show=True,
        )
        hour_one = CourseHour(
            id='duplicate-hour-1', tenant_id='tenant-learning-profile',
            course_id=duplicate_course.id, title='平板基础', duration=120,
        )
        hour_two = CourseHour(
            id='duplicate-hour-2', tenant_id='tenant-learning-profile',
            course_id=duplicate_course.id, title='平板进阶', duration=120,
        )
        db.session.add_all([
            duplicate_course, hour_one, hour_two,
            UserCourseProgress(
                id='duplicate-progress-zero', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id=duplicate_course.id,
                hour_count=2, finished_count=0, progress=0, is_finished=False,
            ),
            UserCourseProgress(
                id='duplicate-progress-finished', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id=duplicate_course.id,
                hour_count=2, finished_count=2, progress=100, is_finished=True,
                finished_at=datetime.utcnow(),
            ),
            UserHourProgress(
                id='duplicate-hour-zero', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id=duplicate_course.id,
                hour_id=hour_one.id, total_duration=120, watched_duration=20,
                is_finished=False,
            ),
            UserHourProgress(
                id='duplicate-hour-finished', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id=duplicate_course.id,
                hour_id=hour_one.id, total_duration=120, watched_duration=120,
                is_finished=True,
            ),
            UserHourProgress(
                id='duplicate-hour-two', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id=duplicate_course.id,
                hour_id=hour_two.id, total_duration=120, watched_duration=10,
                is_finished=False,
            ),
        ])
        db.session.commit()

    response = client.get('/api/portal/my-profile')

    assert response.status_code == 200
    payload = response.get_json()
    duplicate_rows = [
        row for row in payload['recentCourses']
        if row['courseId'] == 'course-duplicate'
    ]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0]['isFinished'] is True
    assert duplicate_rows[0]['progress'] == 100
    # 120 seconds + 10 seconds, not 20 + 120 + 10 or any duplicate sum.
    assert payload['stats']['totalWatchedMinutes'] == 62
    assert payload['stats']['coursesTotal'] == 3
    assert payload['stats']['coursesFinished'] == 2


def test_learning_profile_deduplicates_duplicate_course_rows_and_watched_hours(portal_env):
    """同一课程/课时的历史重复行只贡献一次，并保留最高有效进度。"""
    app, client = portal_env
    with app.app_context():
        db.session.add(CourseHour(
            id='hour-completed', tenant_id='tenant-learning-profile',
            course_id='course-completed', title='安全基础视频', duration=600,
        ))
        db.session.add(UserCourseProgress(
            id='progress-completed-stale', tenant_id='tenant-learning-profile',
            employee_id='employee-learning', course_id='course-completed',
            hour_count=1, finished_count=0, progress=0, is_finished=False,
        ))
        db.session.add_all([
            UserHourProgress(
                id='watched-completed', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id='course-completed',
                hour_id='hour-completed', total_duration=600,
                watched_duration=600, is_finished=True,
            ),
            UserHourProgress(
                id='watched-completed-stale', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', course_id='course-completed',
                hour_id='hour-completed', total_duration=600,
                watched_duration=30, is_finished=False,
            ),
        ])
        db.session.commit()

    payload = client.get('/api/portal/my-profile').get_json()

    assert payload['stats']['coursesTotal'] == 2
    assert payload['stats']['coursesFinished'] == 1
    assert payload['stats']['totalWatchedSeconds'] == 4200
    rows = [row for row in payload['recentCourses'] if row['courseId'] == 'course-completed']
    assert len(rows) == 1
    assert rows[0]['progress'] == 100
    assert rows[0]['isFinished'] is True
    assert rows[0]['finishedCount'] == 1
    assert rows[0]['hourCount'] == 1


def test_learning_profile_collapses_duplicate_course_and_hour_progress(portal_env):
    """并发上报留下重复行时，档案按课程/课时身份合并且不重复累计时长。"""
    app, client = portal_env
    with app.app_context():
        db.session.add(UserCourseProgress(
            id='progress-completed-duplicate', tenant_id='tenant-learning-profile',
            employee_id='employee-learning', course_id='course-completed',
            hour_count=4, finished_count=0, progress=0, is_finished=False,
        ))
        db.session.add(UserHourProgress(
            id='watched-duplicate', tenant_id='tenant-learning-profile',
            employee_id='employee-learning', course_id='course-active',
            hour_id='hour-placeholder', total_duration=5400,
            watched_duration=1200, is_finished=False,
        ))
        db.session.commit()

    response = client.get('/api/portal/my-profile')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['stats']['coursesTotal'] == 2
    assert payload['stats']['coursesFinished'] == 1
    assert payload['stats']['coursesInProgress'] == 1
    assert payload['stats']['totalWatchedMinutes'] == 60
    assert len(payload['recentCourses']) == 2
    by_id = {row['courseId']: row for row in payload['recentCourses']}
    assert by_id['course-completed']['progress'] == 100
    assert by_id['course-completed']['isFinished'] is True
    assert by_id['course-active']['progress'] == 40


def test_exam_points_use_assignment_task_as_stable_identity(portal_env):
    app, client = portal_env
    now = datetime.utcnow()
    with app.app_context():
        for attempt_id in ('legacy-attempt-1', 'legacy-attempt-2'):
            db.session.add(ExamAttempt(
                id=attempt_id,
                tenant_id='tenant-learning-profile',
                assignment_id='assignment-product',
                employee_id='employee-learning',
                task_id=None,
                paper_id='paper-product',
                paper_snapshot=[],
                status='doing',
                pass_score=0,
                started_at=now,
            ))
        db.session.commit()

    for attempt_id in ('legacy-attempt-1', 'legacy-attempt-2'):
        response = client.post(
            f'/api/portal/exams/{attempt_id}/submit',
            json={'answers': {}},
        )
        assert response.status_code == 200, response.get_json()

    with app.app_context():
        attempted = PointLog.query.filter_by(
            employee_id='employee-learning', action='exam_attempted'
        ).all()
        passed = PointLog.query.filter_by(
            employee_id='employee-learning', action='exam_passed'
        ).all()
        assert len(attempted) == 1
        assert len(passed) == 1
        assert attempted[0].ref_id == 'task-product'
        assert attempted[0].detail == '产品经理能力认证'


def test_points_summary_collapses_legacy_attempt_refs_to_one_exam(portal_env):
    app, client = portal_env
    with app.app_context():
        db.session.add_all([
            PointLog(
                id='point-attempted-1', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', action='exam_attempted', points=10,
                ref_id='attempt-1',
            ),
            PointLog(
                id='point-attempted-2', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', action='exam_attempted', points=10,
                ref_id='attempt-2',
            ),
            PointLog(
                id='point-passed-1', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', action='exam_passed', points=50,
                ref_id='attempt-2',
            ),
            PointLog(
                id='point-passed-2', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', action='exam_passed', points=50,
                ref_id='attempt-3',
            ),
        ])
        db.session.commit()

    response = client.get('/api/portal/points/summary')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['totalPoints'] == 60
    assert len(payload['logs']) == 2
    assert {row['action'] for row in payload['logs']} == {'exam_attempted', 'exam_passed'}
    assert {row['detail'] for row in payload['logs']} == {'产品经理能力认证'}
    assert {row['refId'] for row in payload['logs']} == {'task-product'}


def test_same_reward_can_be_exchanged_more_than_once_with_distinct_point_rows(portal_env):
    app, client = portal_env
    with app.app_context():
        db.session.add_all([
            PointLog(
                id=f'earned-{index}', tenant_id='tenant-learning-profile',
                employee_id='employee-learning', action='course_completed', points=20,
                ref_id=f'earned-course-{index}',
            )
            for index in range(3)
        ])
        db.session.add(Reward(
            id='reward-repeatable', tenant_id='tenant-learning-profile',
            name='咖啡券', reward_type='virtual', points_cost=20,
            stock=3, is_active=True,
        ))
        db.session.commit()

    first = client.post('/api/portal/rewards/reward-repeatable/exchange')
    second = client.post('/api/portal/rewards/reward-repeatable/exchange')

    assert first.status_code == 200, first.get_json()
    assert second.status_code == 200, second.get_json()
    assert first.get_json()['remainingPoints'] == 40
    assert second.get_json()['remainingPoints'] == 20
    with app.app_context():
        rows = PointLog.query.filter_by(
            employee_id='employee-learning', action='reward_exchange'
        ).all()
        assert len(rows) == 2
        assert len({row.ref_id for row in rows}) == 2
