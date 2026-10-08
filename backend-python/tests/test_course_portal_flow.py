"""培训门户流程测试（Chunk 3）：指派 → 可见性 → 进度上报。

覆盖：
1. 课程指派到部门后，该部门员工可见、其他部门员工不可见
2. 课程无指派时全员可见
3. 用户指派（target_type='user'）命中
4. 祖先部门命中（指派父部门，子部门员工可见）
5. 进度上报后课程进度重算
"""

from datetime import date

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Course, CourseAssignment, CourseChapter, CourseHour, Department, Employee,
    Tenant, User, UserCourseProgress, UserHourProgress, db,
)
from routes.hrm import hrm_bp
from routes.portal import portal_bp


@pytest.fixture()
def env(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY='t', JWT_SECRET_KEY='t',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(tmp_path / 'uploads'),
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    with app.app_context():
        db.create_all()
        tenant = Tenant(
            id='course-test-tenant',
            name='课程测试企业',
            slug='course-test',
            status='active',
            plan_code='enterprise',
        )
        # 部门树：eng > backend
        eng = Department(id='d-eng', name='工程')
        backend = Department(id='d-backend', name='后端', parent_id='d-eng')
        sales = Department(id='d-sales', name='销售')
        # 员工：A 在 backend（子部门），B 在 sales
        emp_a = Employee(id='e-a', employee_no='E001', name='后端员工',
                         tenant_id=tenant.id,
                         email='a@corp.com', status='active',
                         hire_date=date(2025, 1, 1), department_id='d-backend')
        emp_b = Employee(id='e-b', employee_no='E002', name='销售员工',
                         tenant_id=tenant.id,
                         email='b@corp.com', status='active',
                         hire_date=date(2025, 1, 1), department_id='d-sales')
        # 账号绑定员工
        user_a = User(id='u-a', email='a@corp.com', password_hash='x',
                      name='后端员工', role='employee', status='active', employee_id='e-a')
        user_b = User(id='u-b', email='b@corp.com', password_hash='x',
                      name='销售员工', role='employee', status='active', employee_id='e-b')
        admin = User(id='u-admin', email='admin@corp.com', password_hash='x',
                     name='Admin', role='hr_admin', status='active')
        # 课程 + 2 课时
        course = Course(id='c-1', tenant_id=tenant.id, title='全员安全培训', is_show=True, class_hour=2)
        h1 = CourseHour(id='h-1', tenant_id=tenant.id, course_id='c-1', title='第一讲', sort=1,
                        video_key='courses/c-1/h-1.mp4', duration=600)
        h2 = CourseHour(id='h-2', tenant_id=tenant.id, course_id='c-1', title='第二讲', sort=2, duration=400)
        db.session.add_all([tenant, eng, backend, sales, emp_a, emp_b, user_a, user_b,
                            admin, course, h1, h2])
        db.session.commit()

        token_a = create_access_token('u-a', additional_claims={'role': 'employee'})
        token_b = create_access_token('u-b', additional_claims={'role': 'employee'})
        token_admin = create_access_token('u-admin', additional_claims={'role': 'hr_admin'})
    client_a = app.test_client()
    client_a.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token_a}'
    client_b = app.test_client()
    client_b.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token_b}'
    client_admin = app.test_client()
    client_admin.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token_admin}'
    yield app, client_a, client_b, client_admin


def test_unassigned_course_visible_to_all(env):
    app, ca, cb, cadm = env
    # 无指派 → 全员可见
    assert ca.get('/api/portal/courses').get_json()[0]['title'] == '全员安全培训'
    assert cb.get('/api/portal/courses').get_json()[0]['title'] == '全员安全培训'


def test_dept_assignment_scopes_visibility(env):
    app, ca, cb, cadm = env
    # 管理员指派到 d-eng（backend 的祖先）
    r = cadm.post('/api/hrm/courses/c-1/assign', json={'deptIds': ['d-eng']})
    assert r.status_code == 200
    # backend 员工 A 可见（祖先命中）
    assert len(ca.get('/api/portal/courses').get_json()) == 1
    # sales 员工 B 不可见
    assert cb.get('/api/portal/courses').get_json() == []


def test_user_assignment(env):
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/courses/c-1/assign', json={'userIds': ['e-b']})
    # 只有 B 可见
    assert ca.get('/api/portal/courses').get_json() == []
    assert len(cb.get('/api/portal/courses').get_json()) == 1


def test_course_detail_and_progress_report(env):
    app, ca, cb, cadm = env
    # 详情含课时与 videoUrl
    detail = ca.get('/api/portal/courses/c-1').get_json()
    assert detail['totalHours'] == 2
    assert len(detail['ungroupedHours']) == 2
    assert detail['ungroupedHours'][0]['videoUrl'] is not None  # presigned 或本地 URL

    # A 上报第一讲完成
    r = ca.post('/api/portal/courses/h-1/progress',
                json={'watchedDuration': 600, 'isFinished': True, 'totalDuration': 600})
    assert r.status_code == 200
    body = r.get_json()
    assert body['hourFinished'] is True
    assert body['courseProgress'] == 50  # 1/2

    # 再完成第二讲
    r = ca.post('/api/portal/courses/h-2/progress',
                json={'watchedDuration': 400, 'isFinished': True, 'totalDuration': 400})
    assert r.get_json()['courseProgress'] == 100
    assert r.get_json()['courseFinished'] is True

    # 课程级进度已落库
    with app.app_context():
        cp = UserCourseProgress.query.filter_by(employee_id='e-a', course_id='c-1').first()
        assert cp.progress == 100 and cp.is_finished is True
        assert cp.finished_count == 2


def test_progress_max_keeps_highest_watched(env):
    """重复上报不会回退 watched_duration（取最大值）。"""
    app, ca, cb, cadm = env
    ca.post('/api/portal/courses/h-1/progress', json={'watchedDuration': 500, 'isFinished': False})
    ca.post('/api/portal/courses/h-1/progress', json={'watchedDuration': 200, 'isFinished': False})  # 更小
    with app.app_context():
        hp = UserHourProgress.query.filter_by(employee_id='e-a', hour_id='h-1').first()
        assert hp.watched_duration == 500


def test_duplicate_course_and_hour_progress_rows_merge_finished_state(env):
    """历史并发上报留下重复行时，门户必须展示完成态且按课时去重。"""
    app, ca, _cb, _cadm = env
    with app.app_context():
        db.session.add_all([
            UserCourseProgress(
                id='cp-complete', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=1, progress=50,
                is_finished=False,
            ),
            UserCourseProgress(
                id='cp-stale-zero', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=0, progress=0,
                is_finished=False,
            ),
            UserHourProgress(
                id='hp-complete', employee_id='e-a', course_id='c-1', hour_id='h-1',
                total_duration=600, watched_duration=600, is_finished=True,
            ),
            UserHourProgress(
                id='hp-stale-zero', employee_id='e-a', course_id='c-1', hour_id='h-1',
                total_duration=600, watched_duration=0, is_finished=False,
            ),
        ])
        db.session.commit()

    courses = ca.get('/api/portal/courses').get_json()
    assert len(courses) == 1
    assert courses[0]['progress'] == 50
    assert courses[0]['isFinished'] is False

    detail = ca.get('/api/portal/courses/c-1').get_json()
    assert detail['progress'] == 50
    assert detail['finishedCount'] == 1
    assert detail['ungroupedHours'][0]['isFinished'] is True

    hour_detail = ca.get('/api/portal/hours/h-1').get_json()
    assert hour_detail['hour']['watchedDuration'] == 600
    assert hour_detail['hour']['isFinished'] is True
    assert hour_detail['course']['progress'] == 50
    assert hour_detail['course']['finishedCount'] == 1


def test_course_views_merge_duplicate_progress_rows_and_distinct_hours(env):
    """重复上报留下多行时，门户列表、详情和课程重算都按稳定身份聚合。"""
    app, ca, _cb, _cadm = env
    with app.app_context():
        db.session.add_all([
            UserCourseProgress(
                id='cp-complete', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=1, progress=50, is_finished=False,
            ),
            UserCourseProgress(
                id='cp-duplicate-complete', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=0, progress=0, is_finished=False,
            ),
            UserHourProgress(
                id='hp-complete', employee_id='e-a', course_id='c-1', hour_id='h-1',
                total_duration=600, watched_duration=600, is_finished=True,
            ),
            UserHourProgress(
                id='hp-duplicate-complete', employee_id='e-a', course_id='c-1', hour_id='h-1',
                total_duration=600, watched_duration=20, is_finished=False,
            ),
        ])
        db.session.commit()

    listing = ca.get('/api/portal/courses').get_json()
    assert len(listing) == 1
    assert listing[0]['progress'] == 50
    assert listing[0]['isFinished'] is False

    detail = ca.get('/api/portal/courses/c-1').get_json()
    assert detail['progress'] == 50
    assert detail['finishedCount'] == 1
    assert detail['ungroupedHours'][0]['watchedDuration'] == 600
    assert detail['ungroupedHours'][0]['isFinished'] is True

    # Re-reporting the already finished first hour must not count duplicate rows twice.
    response = ca.post(
        '/api/portal/courses/h-1/progress',
        json={'watchedDuration': 600, 'isFinished': True, 'totalDuration': 600},
    )
    assert response.status_code == 200
    assert response.get_json()['courseProgress'] == 50


def test_unauthorized_employee_blocked(env):
    """未绑定 employee_id 的账号访问门户被 403。"""
    app, ca, cb, cadm = env
    from flask_jwt_extended import create_access_token
    with app.app_context():
        ghost = create_access_token('u-admin', additional_claims={'role': 'hr_admin'})
    c = app.test_client()
    c.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {ghost}'
    # admin 账号没绑 employee_id
    r = c.get('/api/portal/courses')
    assert r.status_code == 403


def test_duplicate_progress_rows_are_merged_for_course_list_and_detail(env):
    """历史并发上报留下重复行时，员工仍应看到完成态而不是任意 0%。"""
    app, ca, _cb, _cadm = env
    with app.app_context():
        # 模拟同一员工/课程/课时的并发首写：一行完成、一行旧的 0%。
        db.session.add_all([
            UserCourseProgress(
                id='cp-finished', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=2, progress=100,
                is_finished=True,
            ),
            UserCourseProgress(
                id='cp-stale-zero', employee_id='e-a', course_id='c-1',
                hour_count=2, finished_count=0, progress=0,
                is_finished=False,
            ),
            UserHourProgress(
                id='hp-finished', employee_id='e-a', course_id='c-1',
                hour_id='h-1', total_duration=600, watched_duration=600,
                is_finished=True,
            ),
            UserHourProgress(
                id='hp-stale-zero', employee_id='e-a', course_id='c-1',
                hour_id='h-1', total_duration=600, watched_duration=0,
                is_finished=False,
            ),
            UserHourProgress(
                id='hp-h2', employee_id='e-a', course_id='c-1',
                hour_id='h-2', total_duration=400, watched_duration=400,
                is_finished=True,
            ),
        ])
        db.session.commit()

    rows = ca.get('/api/portal/courses').get_json()
    matching = [row for row in rows if row['id'] == 'c-1']
    assert len(matching) == 1
    assert matching[0]['progress'] == 100
    assert matching[0]['isFinished'] is True

    detail = ca.get('/api/portal/courses/c-1').get_json()
    assert detail['progress'] == 100
    assert detail['isFinished'] is True
    # Existing detail clients read this nested shape; it must agree with the
    # canonical top-level completion state.
    assert detail['course']['isFinished'] is True
    assert detail['finishedCount'] == 2
    hours = {row['id']: row for row in detail['ungroupedHours']}
    assert hours['h-1']['watchedDuration'] == 600
    assert hours['h-1']['isFinished'] is True


def test_recompute_counts_each_finished_hour_once_when_hour_rows_duplicate(env):
    """重复课时进度不能把两课时课程错误算成超过 100%。"""
    app, ca, _cb, _cadm = env
    with app.app_context():
        db.session.add_all([
            UserHourProgress(
                id='hp-dup-finished-1', employee_id='e-a', course_id='c-1',
                hour_id='h-1', total_duration=600, watched_duration=600,
                is_finished=True,
            ),
            UserHourProgress(
                id='hp-dup-finished-2', employee_id='e-a', course_id='c-1',
                hour_id='h-1', total_duration=600, watched_duration=500,
                is_finished=True,
            ),
        ])
        db.session.commit()

    response = ca.post(
        '/api/portal/courses/h-2/progress',
        json={'watchedDuration': 100, 'isFinished': False, 'totalDuration': 400},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['courseProgress'] == 50
    assert payload['courseFinished'] is False


def test_current_course_roster_excludes_retired_hour_progress(env):
    """已删除课时的历史完成记录不能完成当前版本的课程。"""
    app, ca, _cb, _cadm = env
    with app.app_context():
        db.session.add_all([
            UserHourProgress(
                id='hp-current-completed', employee_id='e-a', course_id='c-1',
                hour_id='h-1', total_duration=600, watched_duration=600,
                is_finished=True,
            ),
            # h-retired 已不在 CourseHour 当前目录中；它不能让两课时课程
            # 从 1/2 错误变成已完成。
            UserHourProgress(
                id='hp-retired-completed', employee_id='e-a', course_id='c-1',
                hour_id='h-retired', total_duration=600, watched_duration=600,
                is_finished=True,
            ),
        ])
        db.session.commit()

    listing = ca.get('/api/portal/courses').get_json()
    assert listing[0]['progress'] == 50
    assert listing[0]['isFinished'] is False

    detail = ca.get('/api/portal/courses/c-1').get_json()
    assert detail['progress'] == 50
    assert detail['isFinished'] is False
    assert detail['finishedCount'] == 1
