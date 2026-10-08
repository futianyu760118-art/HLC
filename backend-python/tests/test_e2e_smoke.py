"""端到端冒烟测试：模拟管理员+员工完整闭环（不依赖 MySQL/compose，用 in-memory SQLite）。

覆盖审计要求的「db.create_all() 建表 + 完整业务闭环」：
1. 所有新表（培训8 + 考试5）经 db.create_all() 建成
2. 管理员：建课程分类 → 建课程 → 指派部门 → 建题库 → 建试卷 → 建考试任务 → 发布
3. 员工：看课程 → 上报进度 → 开始考试 → 提交 → 判分 → 看结果
4. 管理员：看进度看板/成绩单
"""

from datetime import date, datetime, timedelta

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import db
from routes.hrm import hrm_bp
from routes.portal import portal_bp


@pytest.fixture()
def system():
    app = Flask(__name__)
    app.config.update(
        TESTING=True, SECRET_KEY='t', JWT_SECRET_KEY='t',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    with app.app_context():
        db.create_all()
        # 部门 + 员工 + 账号
        from models import Department, Employee, User
        db.session.add_all([
            Department(id='d-eng', name='工程部'),
            Employee(id='e-1', employee_no='E001', name='张三', email='z@corp.com',
                     status='active', hire_date=date(2025, 1, 1), department_id='d-eng'),
            User(id='u-admin', email='admin@corp.com', password_hash='x',
                 name='Admin', role='hr_admin', status='active'),
            User(id='u-emp', email='z@corp.com', password_hash='x',
                 name='张三', role='employee', status='active', employee_id='e-1'),
        ])
        db.session.commit()
        admin_tok = create_access_token('u-admin', additional_claims={'role': 'hr_admin'})
        emp_tok = create_access_token('u-emp', additional_claims={'role': 'employee'})
    cadmin = app.test_client(); cadmin.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {admin_tok}'
    cemp = app.test_client(); cemp.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {emp_tok}'
    yield app, cadmin, cemp


def test_full_e2e_flow(system):
    app, cadmin, cemp = system

    # === 管理员：建课程分类 ===
    r = cadmin.post('/api/hrm/course-categories', json={'name': '入职培训'})
    assert r.status_code == 201
    cat_id = r.get_json()['id']

    # === 管理员：建课程 ===
    r = cadmin.post('/api/hrm/courses', json={'title': '新员工导论', 'categoryId': cat_id, 'isRequired': True, 'isShow': True})
    assert r.status_code == 201
    course_id = r.get_json()['id']

    # === 管理员：建课时（2个）===
    r = cadmin.post('/api/hrm/course-hours', json={'courseId': course_id, 'title': '公司文化', 'type': 'VIDEO', 'duration': 600})
    assert r.status_code == 201
    h1 = r.get_json()['id']
    cadmin.post('/api/hrm/course-hours', json={'courseId': course_id, 'title': '安全规范', 'type': 'VIDEO', 'duration': 400})
    h2 = cadmin.get('/api/hrm/course-hours').get_json()[0]['id']

    # === 管理员：指派课程到工程部 ===
    r = cadmin.post(f'/api/hrm/courses/{course_id}/assign', json={'deptIds': ['d-eng']})
    assert r.status_code == 200
    assert r.get_json()['deptCount'] == 1

    # === 员工：能看到课程 ===
    r = cemp.get('/api/portal/courses')
    assert r.status_code == 200
    assert len(r.get_json()) == 1
    assert r.get_json()[0]['title'] == '新员工导论'

    # === 员工：看课程详情 ===
    r = cemp.get(f'/api/portal/courses/{course_id}')
    assert r.get_json()['totalHours'] == 2

    # === 员工：上报第一课时完成 ===
    r = cemp.post(f'/api/portal/courses/{h1}/progress', json={'watchedDuration': 600, 'isFinished': True, 'totalDuration': 600})
    assert r.get_json()['courseProgress'] == 50

    # === 管理员：建题库（直接 approved）===
    r = cadmin.post('/api/hrm/exam-questions', json={
        'type': 'single', 'stem': '公司成立于哪年？', 'options': ['2018', '2019', '2020', '2021'],
        'answer': [2], 'score': 10, 'difficulty': 2, 'reviewStatus': 'approved'})
    assert r.status_code == 201
    q1 = r.get_json()['id']
    r = cadmin.post('/api/hrm/exam-questions', json={
        'type': 'judge', 'stem': '安全第一', 'options': ['正确', '错误'],
        'answer': [0], 'score': 10, 'difficulty': 1, 'reviewStatus': 'approved'})
    q2 = r.get_json()['id']

    # === 管理员：建试卷 ===
    r = cadmin.post('/api/hrm/exam-papers', json={
        'title': '入职测验', 'questionIds': [q1, q2], 'totalScore': 20, 'passScore': 12,
        'durationMinutes': 15, 'status': 'published'})
    assert r.status_code == 201
    paper_id = r.get_json()['id']

    # === 管理员：建考试任务 + 发布 ===
    r = cadmin.post('/api/hrm/exam-tasks', json={
        'title': '2026年6月入职测验', 'paperId': paper_id,
        'startTime': (datetime.utcnow() - timedelta(hours=1)).isoformat(),
        'endTime': (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        'maxAttempts': 1, 'targetType': 'dept', 'targetIds': ['d-eng'], 'status': 'draft'})
    assert r.status_code == 201
    task_id = r.get_json()['id']

    r = cadmin.post(f'/api/hrm/exam-tasks/{task_id}/publish')
    assert r.status_code == 200
    assert r.get_json()['assignedTotal'] == 1  # 工程部只有张三

    # === 员工：看到待考 ===
    r = cemp.get('/api/portal/exams')
    assert len(r.get_json()) == 1
    assert r.get_json()[0]['remainingAttempts'] == 1

    # === 员工：开始考试 ===
    r = cemp.post(f'/api/portal/exams/{task_id}/start')
    assert r.status_code == 200
    attempt_id = r.get_json()['attemptId']
    # 题目不含答案
    for q in r.get_json()['questions']:
        assert 'answer' not in q

    # === 员工：提交（答对 1 题答错 1 题）===
    r = cemp.post(f'/api/portal/exams/{attempt_id}/submit',
                  json={'answers': {q1: [2], q2: [1]}})  # q1对 q2错
    assert r.status_code == 200
    result = r.get_json()
    assert result['score'] == 10  # 只对 q1
    assert result['totalScore'] == 20
    assert result['passed'] is False  # 10 < 12

    # === 员工：看结果（含正确答案）===
    r = cemp.get(f'/api/portal/exams/{attempt_id}/result')
    for q in r.get_json()['questions']:
        assert 'answer' in q

    # === 管理员：看成绩单 ===
    r = cadmin.get(f'/api/hrm/exam-tasks/{task_id}/progress')
    body = r.get_json()
    assert body['total'] == 1
    assert body['attempted'] == 1
    assert body['passed'] == 0  # 张三没过
    assert body['roster'][0]['bestScore'] == 10

    # === 管理员：看课程进度看板 ===
    r = cadmin.get(f'/api/hrm/courses/{course_id}/progress')
    assert r.get_json()['assigned'] == 1
    # 张三只完成 1/2 课时，进度 50%
    assert r.get_json()['roster'][0]['progress'] == 50


def test_all_new_tables_created_by_create_all(system):
    """审计重点：db.create_all() 建出全部 13 张新表。"""
    app, _, _ = system
    from models import (Course, CourseCategory, CourseChapter, CourseHour,
                        CourseAttachment, CourseAssignment, UserCourseProgress,
                        UserHourProgress, ExamQuestion, ExamPaper, ExamTask,
                        ExamAssignment, ExamAttempt)
    with app.app_context():
        for m in [Course, CourseCategory, CourseChapter, CourseHour,
                  CourseAttachment, CourseAssignment, UserCourseProgress,
                  UserHourProgress, ExamQuestion, ExamPaper, ExamTask,
                  ExamAssignment, ExamAttempt]:
            m.query.count()  # 不报错 = 表存在
