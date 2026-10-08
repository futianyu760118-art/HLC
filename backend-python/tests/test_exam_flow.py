"""考试闭环集成测试（Chunk 6）：发布 → 开始 → 提交 → 判分 → 结果。

覆盖：
1. 任务发布：部门指派展开为 per-员工 assignment
2. 员工 start：校验授权/次数/时间窗，返回无答案的题目
3. submit：判分正确、写成绩、assignment 状态更新
4. 幂等提交：重复 submit 返回已有结果
5. result：含正确答案与解析（仅提交后可见）
6. 次数用完：第二次 start 被拒
7. 未被指派的员工 start 被拒
8. 进度统计：publish 后 progress 接口可查
"""

from datetime import date, datetime, timedelta

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from models import (
    Course, Department, Employee, ExamAssignment, ExamAttempt, ExamPaper,
    ExamQuestion, ExamTask, User, db,
)
from routes.hrm import hrm_bp
from routes.portal import portal_bp


@pytest.fixture()
def env():
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
        dept = Department(id='d-1', name='工程部')
        # 两个员工，A 在工程部（被指派），B 在销售部（未被指派）
        emp_a = Employee(id='e-a', employee_no='E001', name='员工A',
                         email='a@corp.com', status='active',
                         hire_date=date(2025, 1, 1), department_id='d-1')
        emp_b = Employee(id='e-b', employee_no='E002', name='员工B',
                         email='b@corp.com', status='active',
                         hire_date=date(2025, 1, 1), department_id='d-2')
        user_a = User(id='u-a', email='a@corp.com', password_hash='x',
                      name='A', role='employee', status='active', employee_id='e-a')
        user_b = User(id='u-b', email='b@corp.com', password_hash='x',
                      name='B', role='employee', status='active', employee_id='e-b')
        admin = User(id='u-admin', email='admin@corp.com', password_hash='x',
                     name='Admin', role='hr_admin', status='active')
        # 3 道已审核题目
        q1 = ExamQuestion(id='q1', type='single', stem='单选1',
                          options=['A', 'B', 'C', 'D'], answer=[1],
                          score=10, review_status='approved', difficulty=3)
        q2 = ExamQuestion(id='q2', type='multiple', stem='多选1',
                          options=['A', 'B', 'C', 'D'], answer=[0, 2],
                          score=20, review_status='approved', difficulty=4)
        q3 = ExamQuestion(id='q3', type='judge', stem='判断1',
                          options=['正确', '错误'], answer=[0],
                          score=10, review_status='approved', difficulty=2)
        # 试卷：总分 40，及格 24
        paper = ExamPaper(id='p-1', title='测试卷',
                          question_ids=['q1', 'q2', 'q3'],
                          total_score=40, pass_score=24, duration_minutes=30)
        # 任务：指派工程部，时间窗包含 now，1 次机会
        task = ExamTask(id='t-1', paper_id='p-1', title='月度测验',
                        start_time=datetime.utcnow() - timedelta(hours=1),
                        end_time=datetime.utcnow() + timedelta(hours=1),
                        max_attempts=1, target_type='dept',
                        target_ids=['d-1'], status='draft')
        db.session.add_all([dept, emp_a, emp_b, user_a, user_b, admin,
                            q1, q2, q3, paper, task])
        db.session.commit()

        ta = create_access_token('u-a', additional_claims={'role': 'employee'})
        tb = create_access_token('u-b', additional_claims={'role': 'employee'})
        tadmin = create_access_token('u-admin', additional_claims={'role': 'hr_admin'})
    ca = app.test_client(); ca.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {ta}'
    cb = app.test_client(); cb.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {tb}'
    cadm = app.test_client(); cadm.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {tadmin}'
    yield app, ca, cb, cadm


def test_publish_expands_dept_to_assignments(env):
    app, ca, cb, cadm = env
    r = cadm.post('/api/hrm/exam-tasks/t-1/publish')
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['status'] == 'published'
    assert body['assignedTotal'] == 1  # 工程部只有 emp_a
    with app.app_context():
        assert ExamAssignment.query.count() == 1
        assert ExamAssignment.query.first().employee_id == 'e-a'


def test_publish_blocks_if_pending_questions(env):
    app, ca, cb, cadm = env
    with app.app_context():
        ExamQuestion.query.get('q1').review_status = 'pending'
        db.session.commit()
    r = cadm.post('/api/hrm/exam-tasks/t-1/publish')
    assert r.status_code == 400
    assert '审核' in r.get_json()['error']


def test_full_flow_pass(env):
    """完整闭环：发布 → 开始 → 全对提交 → 通过。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')

    # A 开始考试
    r = ca.post('/api/portal/exams/t-1/start')
    assert r.status_code == 200, r.get_json()
    started = r.get_json()
    assert started['totalScore'] == 40
    assert started['passScore'] == 24
    # 题目不含 answer/explanation
    for q in started['questions']:
        assert 'answer' not in q
        assert 'explanation' not in q
    attempt_id = started['attemptId']

    # 全对提交
    r = ca.post(f'/api/portal/exams/{attempt_id}/submit',
                json={'answers': {'q1': [1], 'q2': [0, 2], 'q3': [0]}})
    assert r.status_code == 200
    result = r.get_json()
    assert result['score'] == 40
    assert result['passed'] is True
    assert result['status'] == 'submitted'

    # assignment 状态更新为 passed
    with app.app_context():
        assert ExamAssignment.query.filter_by(employee_id='e-a').first().status == 'passed'


def test_submit_partial_score_fail(env):
    """漏选+错答 → 不过半。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    attempt_id = ca.post('/api/portal/exams/t-1/start').get_json()['attemptId']
    # q1 错(0 分) + q2 漏选 [0](半分 10) + q3 对(10) = 20 < 24 → 不过
    r = ca.post(f'/api/portal/exams/{attempt_id}/submit',
                json={'answers': {'q1': [0], 'q2': [0], 'q3': [0]}})
    result = r.get_json()
    assert result['score'] == 20
    assert result['passed'] is False
    with app.app_context():
        assert ExamAssignment.query.filter_by(employee_id='e-a').first().status == 'failed'


def test_random_paper_draws_from_pool_and_freezes_snapshot(env):
    """随机试卷：开始考试时从题池抽题，并把个人试卷快照冻结下来。"""
    app, ca, cb, cadm = env
    with app.app_context():
        paper = ExamPaper.query.get('p-1')
        paper.question_mode = 'random'
        paper.draw_count = 2
        paper.total_score = 20
        paper.pass_score = 12
        db.session.commit()

    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    exams = ca.get('/api/portal/exams').get_json()
    assert exams[0]['questionMode'] == 'random'
    assert exams[0]['drawCount'] == 2
    assert exams[0]['poolCount'] == 3
    assert exams[0]['questionCount'] == 2

    r = ca.post('/api/portal/exams/t-1/start')
    assert r.status_code == 200, r.get_json()
    started = r.get_json()
    assert started['totalScore'] == 20
    assert started['passScore'] == 12
    assert len(started['questions']) == 2

    correct_answers = {
        'q1': [1],
        'q2': [0, 2],
        'q3': [0],
    }
    chosen_ids = {item['id'] for item in started['questions']}
    assert chosen_ids.issubset({'q1', 'q2', 'q3'})

    attempt_id = started['attemptId']
    submit_payload = {
        'answers': {question_id: correct_answers[question_id] for question_id in chosen_ids}
    }
    submitted = ca.post(f'/api/portal/exams/{attempt_id}/submit', json=submit_payload)
    assert submitted.status_code == 200, submitted.get_json()
    result = submitted.get_json()
    assert result['score'] == 20
    assert result['totalScore'] == 20
    assert result['passed'] is True

    with app.app_context():
        attempt = ExamAttempt.query.get(attempt_id)
        assert attempt is not None
        assert len(attempt.paper_snapshot or []) == 2
        assert round(sum(item['score'] for item in (attempt.paper_snapshot or [])), 2) == 20


def test_submit_is_idempotent(env):
    """重复提交返回已有结果，不重新判分/不改状态。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    attempt_id = ca.post('/api/portal/exams/t-1/start').get_json()['attemptId']
    ca.post(f'/api/portal/exams/{attempt_id}/submit',
            json={'answers': {'q1': [1], 'q2': [0, 2], 'q3': [0]}})
    r2 = ca.post(f'/api/portal/exams/{attempt_id}/submit',
                 json={'answers': {'q1': [0]}})  # 不同的答案应被忽略
    assert r2.status_code == 200
    assert r2.get_json()['score'] == 40  # 仍是首次结果


def test_result_includes_correct_answers(env):
    """结果接口含正确答案与解析（仅提交后可见）。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    attempt_id = ca.post('/api/portal/exams/t-1/start').get_json()['attemptId']
    ca.post(f'/api/portal/exams/{attempt_id}/submit',
            json={'answers': {'q1': [1], 'q2': [0, 2], 'q3': [0]}})
    r = ca.get(f'/api/portal/exams/{attempt_id}/result')
    result = r.get_json()
    for q in result['questions']:
        assert 'answer' in q  # 提交后能看到正确答案
        assert 'explanation' in q


def test_result_blocked_before_submit(env):
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    attempt_id = ca.post('/api/portal/exams/t-1/start').get_json()['attemptId']
    r = ca.get(f'/api/portal/exams/{attempt_id}/result')
    assert r.status_code == 400


def test_attempts_exhausted(env):
    """次数用完后再次 start 被拒。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    ca.post('/api/portal/exams/t-1/start')
    r = ca.post('/api/portal/exams/t-1/start')
    assert r.status_code == 400
    assert '次数' in r.get_json()['error']


def test_unassigned_employee_blocked(env):
    """未被指派的员工 B 不能开始考试。"""
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    r = cb.post('/api/portal/exams/t-1/start')
    assert r.status_code == 403
    assert '指派' in r.get_json()['error']


def test_task_progress_endpoint(env):
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    # A 参加并通过
    aid = ca.post('/api/portal/exams/t-1/start').get_json()['attemptId']
    ca.post(f'/api/portal/exams/{aid}/submit',
            json={'answers': {'q1': [1], 'q2': [0, 2], 'q3': [0]}})
    r = cadm.get('/api/hrm/exam-tasks/t-1/progress')
    body = r.get_json()
    assert body['total'] == 1
    assert body['attempted'] == 1
    assert body['passed'] == 1
    assert body['passRate'] == 1.0
    assert body['roster'][0]['bestScore'] == 40


def test_my_exams_lists_assignments(env):
    app, ca, cb, cadm = env
    cadm.post('/api/hrm/exam-tasks/t-1/publish')
    r = ca.get('/api/portal/exams')
    exams = r.get_json()
    assert len(exams) == 1
    assert exams[0]['taskId'] == 't-1'
    assert exams[0]['inWindow'] is True
    assert exams[0]['remainingAttempts'] == 1
