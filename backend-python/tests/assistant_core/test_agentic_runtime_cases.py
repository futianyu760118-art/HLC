"""Regression cases for the intelligent assistant runtime.

These tests pin the outcome users care about: colloquial phrasing should map to
the right business query/action and keep the existing frontend response shape.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from flask import Flask

from services.assistant_core import legacy_agentic_runtime as agentic_runtime
from services.assistant import handle_assistant_query
from services.assistant_core.schemas import AssistantContext


def _ctx(
    session_id: str = 's-agentic',
    role: str = 'hr_admin',
    user_id: str = 'u-agentic',
) -> AssistantContext:
    return AssistantContext(
        user_id=user_id,
        role=role,
        session_id=session_id,
    )


def _employee_ctx(session_id: str = 's-employee-self') -> AssistantContext:
    return AssistantContext(
        user_id='u-employee',
        role='employee',
        session_id=session_id,
        user_employee_id='e-self',
        user_department_id='d-rd',
    )


@pytest.fixture()
def model_db(monkeypatch):
    from models import db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        monkeypatch.setattr(
            'services.assistant_core.legacy_agentic_runtime.business_now',
            lambda: datetime(2026, 5, 29, 9, 0, 0),
            raising=False,
        )
        monkeypatch.setattr(
            'services.assistant_core.skills.business_now',
            lambda: datetime(2026, 5, 29, 9, 0, 0),
            raising=False,
        )
        yield db
        db.session.remove()
        db.drop_all()


def _seed_recruitment_data(db) -> None:
    from models import Candidate, Interview, Job, Resume

    jobs = [
        Job(id='j-supply', title='供应链总监', department='运营部', status='open', created_at=datetime(2026, 5, 20, 9, 0)),
        Job(id='j-electronic', title='电子工程师', department='研发部', status='open', created_at=datetime(2026, 5, 21, 9, 0)),
        Job(id='j-closed', title='行政专员', department='行政部', status='closed', created_at=datetime(2026, 5, 1, 9, 0)),
    ]
    resumes = [
        Resume(
            id='r-wmh',
            job_id='j-supply',
            candidate_name='吴明华',
            file_url='/uploads/wmh.pdf',
            ai_analysis={
                'score': 94,
                'matchDegree': 91,
                'skills': ['供应链规划', '采购管理', 'S&OP'],
                'summary': '供应链管理经验扎实，适合供应链负责人岗位。',
                'strengths': ['跨部门协同强', '成本优化经验丰富'],
                'weaknesses': ['需复核数字化系统落地深度'],
                'recommendation': '推荐进入终面',
                'interviewFocus': ['供应链数字化', '供应商风险管理'],
            },
            created_at=datetime(2026, 5, 28, 10, 0),
        ),
        Resume(id='r-li', job_id='j-electronic', candidate_name='李博豪', file_url='/uploads/li.pdf', created_at=datetime(2026, 5, 26, 10, 0)),
    ]
    candidates = [
        Candidate(
            id='c-wmh',
            resume_id='r-wmh',
            job_id='j-supply',
            name='吴明华',
            status='screening',
            source='简历上传',
            match_records=[{'score': 94, 'matchDegree': 91}],
            ai_summary='供应链管理经验扎实，适合供应链负责人岗位。',
            ai_recommendation='推荐进入终面',
            created_at=datetime(2026, 5, 28, 11, 0),
        ),
        Candidate(id='c-li', resume_id='r-li', job_id='j-electronic', name='李博豪', status='screening', created_at=datetime(2026, 5, 26, 11, 0)),
    ]
    interviews = [
        Interview(id='i-wmh', resume_id='r-wmh', job_id='j-supply', scheduled_at=datetime(2026, 5, 30, 9, 0), status='scheduled'),
    ]
    db.session.add_all(jobs + resumes + candidates + interviews)
    db.session.commit()


def _seed_broad_hrm_data(db) -> None:
    from models import (
        ApprovalInstance, AttendanceRecord, Department, Employee, Feedback,
        Job, Position, Resume,
    )

    dept_ops = Department(id='d-ops', name='运营部', code='OPS', status='active')
    dept_rd = Department(id='d-rd', name='研发部', code='RD', status='active')
    pos_supply = Position(id='p-supply', title='供应链总监', department_id='d-ops', status='active')
    emp_wmh = Employee(
        id='e-wmh',
        employee_no='E2026050001',
        name='吴明华',
        email='wmh@example.com',
        phone='13800000000',
        status='active',
        department_id='d-ops',
        position_id='p-supply',
        job_title='供应链总监',
        hire_date=date(2026, 5, 1),
    )
    emp_li = Employee(
        id='e-li',
        employee_no='E2026050002',
        name='李研发',
        status='probation',
        department_id='d-rd',
        job_title='后端工程师',
        hire_date=date(2026, 5, 5),
    )
    attendance = [
        AttendanceRecord(id='a-1', employee_id='e-wmh', attendance_date=date(2026, 5, 28), status='late'),
        AttendanceRecord(id='a-2', employee_id='e-wmh', attendance_date=date(2026, 5, 27), status='normal'),
        AttendanceRecord(id='a-3', employee_id='e-li', attendance_date=date(2026, 5, 28), status='absent'),
    ]
    approvals = [
        ApprovalInstance(
            id='ap-1',
            business_type='leave',
            business_id='leave-1',
            title='吴明华请假申请',
            applicant_id='u-other',
            approver_id='u-agentic',
            status='pending',
        ),
        ApprovalInstance(
            id='ap-2',
            business_type='overtime',
            business_id='ot-1',
            title='李研发加班申请',
            applicant_id='u-agentic',
            approver_id='u-other',
            status='approved',
        ),
    ]
    feedbacks = [
        Feedback(id='fb-1', user_id='u-agentic', feedback_type='bug', severity='high', title='岗位页面报错', content='打开详情白屏', status='pending'),
        Feedback(id='fb-2', user_id='u-agentic', feedback_type='feature', severity='medium', title='增加导出', content='希望导出报表', status='resolved'),
    ]
    job = Job(id='j-open', title='后端工程师', department='研发部', status='open', created_at=datetime(2026, 5, 20, 9, 0))
    resume = Resume(id='r-one', job_id='j-open', candidate_name='候选人甲', file_url='/uploads/a.pdf', created_at=datetime(2026, 5, 28, 9, 0))
    db.session.add_all([
        dept_ops, dept_rd, pos_supply, emp_wmh, emp_li, job, resume,
        *attendance, *approvals, *feedbacks,
    ])
    db.session.commit()


def _assert_write_action_forbidden(result) -> None:
    assert result is not None
    assert result.error_code == 'permission_denied'
    assert result.requires_confirmation is False
    assert result.actions == []
    assert getattr(result, '_pending_action', None) is None
    assert result.route_decision.task_type == 'forbidden'
    assert 'permission_denied' in result.route_decision.safety_flags


def _seed_employee_self_service_data(db) -> None:
    from decimal import Decimal

    from models import AttendanceRecord, Department, Employee, PayrollRecord, PerformanceReview

    dept = Department(id='d-rd', name='研发部', code='RD', status='active')
    employee = Employee(
        id='e-self',
        employee_no='E2026060001',
        name='张三',
        status='active',
        department_id='d-rd',
        job_title='后端工程师',
        hire_date=date(2024, 2, 18),
    )
    other_employee = Employee(
        id='e-other',
        employee_no='E2026060002',
        name='李四',
        status='active',
        department_id='d-rd',
        job_title='测试工程师',
    )
    records = [
        AttendanceRecord(id='att-self-1', employee_id='e-self', attendance_date=date(2026, 5, 28), status='late'),
        AttendanceRecord(id='att-self-2', employee_id='e-self', attendance_date=date(2026, 5, 29), status='normal'),
        AttendanceRecord(id='att-other-1', employee_id='e-other', attendance_date=date(2026, 5, 29), status='absent'),
    ]
    reviews = [
        PerformanceReview(
            id='perf-self-1',
            employee_id='e-self',
            final_score=Decimal('86.00'),
            grade='A',
            status='completed',
            created_at=datetime(2026, 5, 28, 9, 0),
        ),
        PerformanceReview(
            id='perf-other-1',
            employee_id='e-other',
            final_score=Decimal('58.00'),
            grade='D',
            status='completed',
            created_at=datetime(2026, 5, 28, 9, 0),
        ),
    ]
    payroll = PayrollRecord(
        id='pay-self-1',
        employee_id='e-self',
        payroll_month='2026-05',
        gross_salary=Decimal('30000.00'),
        net_salary=Decimal('25000.00'),
        deduction=Decimal('5000.00'),
    )
    db.session.add_all([dept, employee, other_employee, *records, *reviews, payroll])
    db.session.commit()


def _seed_operational_route_data(db) -> None:
    from decimal import Decimal

    from models import (
        Department, Employee, PayrollRecord, PerformanceCycle, PerformanceReview,
        TrainingCourse, TrainingPlan, TrainingRecord,
    )

    departments = [
        Department(id='dep-agentic-rd', name='研发部', code='RD'),
        Department(id='dep-agentic-sales', name='销售部', code='SALES'),
    ]
    employees = [
        Employee(id='emp-agentic-1', employee_no='EA001', name='张三', department_id='dep-agentic-rd', job_title='工程师', status='active'),
        Employee(id='emp-agentic-2', employee_no='EA002', name='李四', department_id='dep-agentic-rd', job_title='测试工程师', status='active'),
        Employee(id='emp-agentic-3', employee_no='EA003', name='王五', department_id='dep-agentic-sales', job_title='销售经理', status='active'),
    ]
    payroll_records = [
        PayrollRecord(
            id='pay-agentic-1', employee_id='emp-agentic-1', payroll_month='2026-05',
            gross_salary=Decimal('15000.00'), net_salary=Decimal('13200.00'),
            deduction=Decimal('1800.00'), status='calculated',
        ),
        PayrollRecord(
            id='pay-agentic-2', employee_id='emp-agentic-2', payroll_month='2026-05',
            gross_salary=Decimal('12000.00'), net_salary=Decimal('10600.00'),
            deduction=Decimal('1400.00'), status='calculated',
        ),
        PayrollRecord(
            id='pay-agentic-3', employee_id='emp-agentic-3', payroll_month='2026-04',
            gross_salary=Decimal('18000.00'), net_salary=Decimal('15800.00'),
            deduction=Decimal('2200.00'), status='paid',
        ),
    ]
    performance_cycle = PerformanceCycle(
        id='cycle-agentic-q2',
        name='2026 Q2 绩效',
        cycle_type='季度',
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        status='active',
    )
    reviews = [
        PerformanceReview(
            id='perf-agentic-1', employee_id='emp-agentic-1', cycle_id='cycle-agentic-q2',
            final_score=Decimal('92.00'), grade='A', status='completed',
            created_at=datetime(2026, 5, 20, 9, 0),
        ),
        PerformanceReview(
            id='perf-agentic-2', employee_id='emp-agentic-2', cycle_id='cycle-agentic-q2',
            final_score=Decimal('81.00'), grade='B', status='completed',
            created_at=datetime(2026, 5, 21, 9, 0),
        ),
        PerformanceReview(
            id='perf-agentic-3', employee_id='emp-agentic-3', cycle_id='cycle-agentic-q2',
            final_score=Decimal('59.00'), grade='C', status='draft',
            created_at=datetime(2026, 5, 22, 9, 0),
        ),
    ]
    courses = [
        TrainingCourse(id='course-agentic-safe', name='安全培训', category='合规', status='active'),
        TrainingCourse(id='course-agentic-leader', name='管理者训练营', category='管理', status='active'),
    ]
    plans = [
        TrainingPlan(
            id='plan-agentic-safe', name='5月安全培训', course_id='course-agentic-safe',
            start_time=datetime(2026, 5, 10, 9, 0), status='running',
        ),
        TrainingPlan(
            id='plan-agentic-leader', name='Q2 管理训练营', course_id='course-agentic-leader',
            start_time=datetime(2026, 5, 15, 9, 0), status='planned',
        ),
    ]
    training_records = [
        TrainingRecord(id='tr-agentic-1', plan_id='plan-agentic-safe', course_id='course-agentic-safe', employee_id='emp-agentic-1', status='completed', score=Decimal('95.00')),
        TrainingRecord(id='tr-agentic-2', plan_id='plan-agentic-safe', course_id='course-agentic-safe', employee_id='emp-agentic-2', status='passed', score=Decimal('88.00')),
        TrainingRecord(id='tr-agentic-3', plan_id='plan-agentic-safe', course_id='course-agentic-safe', employee_id='emp-agentic-3', status='registered'),
        TrainingRecord(id='tr-agentic-4', plan_id='plan-agentic-leader', course_id='course-agentic-leader', employee_id='emp-agentic-3', status='registered'),
    ]
    db.session.add_all(
        departments + employees + payroll_records + [performance_cycle]
        + reviews + courses + plans + training_records
    )
    db.session.commit()


def _field_source_modules(result) -> set[str]:
    return {
        source.get('module')
        for widget in result.widgets
        if widget.get('type') == 'source_citations'
        for source in widget.get('sources') or []
        if source.get('fields')
    }


@pytest.mark.parametrize('question', [
    '最近在招聘的岗位有哪些',
    '最近在招聘中的岗位有哪些',
    '我们现在有哪些岗位在招人',
    '当前开放的职位列一下',
])
def test_colloquial_open_job_queries_share_the_same_business_result(model_db, question: str) -> None:
    _seed_recruitment_data(model_db)

    result = agentic_runtime.try_run(question, _ctx())

    assert result is not None
    assert result.route_decision.intent == 'recruitment.jobs.open.list'
    assert result.route_decision.tool_plan[0].input == {'module': 'jobs', 'status': 'open', 'limit': 20}
    assert {entity['title'] for entity in result.entities} == {'供应链总监', '电子工程师'}
    assert '目前有 2 个招聘中的岗位' in result.summary
    assert result.answer['content'] == result.summary


@pytest.mark.parametrize('question', [
    '我们有多少简历',
    '简历库现在一共几份',
    '目前收到过多少份履历',
])
def test_colloquial_resume_count_queries_hit_resume_count(model_db, question: str) -> None:
    _seed_recruitment_data(model_db)

    result = agentic_runtime.try_run(question, _ctx())

    assert result is not None
    assert result.route_decision.intent == 'recruitment.resumes.count'
    assert result.route_decision.tool_plan[0].input == {'module': 'resumes', 'count_only': True, 'limit': 20}
    assert result.summary == '当前简历共有 2 份。'
    assert result.widgets and result.widgets[0]['type'] == 'metrics'


def test_employee_self_service_mixed_query_keeps_visible_topics_and_salary_boundary(model_db) -> None:
    _seed_employee_self_service_data(model_db)

    result = agentic_runtime.try_run(
        '我是普通员工，请查看我的考勤、绩效和工资条，说明哪些能看、哪些不能看，并给证据来源。',
        _employee_ctx(),
    )

    assert result is not None
    assert result.route_decision.intent == 'employee.self_service.multi_topic'
    assert [step.skill for step in result.trace] == [
        'attendance_analysis',
        'performance_analysis',
        'payroll_analysis',
    ]
    assert result.trace[0].rows_count == 2
    assert result.trace[1].rows_count == 1
    assert result.trace[2].status == 'error'
    assert 'payroll_performance_link' not in [step.skill for step in result.trace]
    assert '考勤 2 条' in result.summary
    assert '绩效 1 条' in result.summary
    assert '工资条/薪酬明细不能通过普通员工账号查看明细' in result.summary
    assert '当前账号绑定的员工档案' in result.summary
    assert 'permission_denied' in result.route_decision.safety_flags
    assert any(widget.get('type') == 'status_badges' for widget in result.widgets)
    sources = next(
        widget
        for widget in reversed(result.widgets)
        if widget.get('type') == 'source_citations'
    )['sources']
    assert {source['module'] for source in sources} >= {
        'attendance_records',
        'attendance_stats',
        'performance_reviews',
        'permissions',
    }


@pytest.mark.parametrize(
    ('question', 'expected_intent', 'expected_tool', 'expected_field_modules', 'summary_parts'),
    [
        (
            '绩效评估分布怎么样',
            'performance.distribution',
            'performance_analysis',
            {'performance_reviews', 'employees'},
            ['3 条绩效评估', '已完成 2 条', 'A 1 人', 'B 1 人', 'C 1 人'],
        ),
        (
            '培训完成率是多少',
            'training.completion',
            'training_analysis',
            {'training_courses', 'training_plans', 'training_records', 'employees'},
            ['2 门课程', '2 个培训计划', '培训记录 4 条', '完成率 50.0%'],
        ),
        (
            '2026-05 工资条汇总',
            'payroll.summary',
            'payroll_analysis',
            {'payroll_records', 'employees'},
            ['2026-05薪酬汇总', '2 条工资条', '应发合计 27,000 元', '敏感信息'],
        ),
    ],
)
def test_operational_domain_queries_beat_candidate_assessment_focus(
    model_db,
    question: str,
    expected_intent: str,
    expected_tool: str,
    expected_field_modules: set[str],
    summary_parts: list[str],
) -> None:
    _seed_operational_route_data(model_db)
    ctx = _ctx()
    ctx.history = [
        {'role': 'user', 'content': '吴明华的简历'},
        {
            'role': 'assistant',
            'content': '已找到吴明华的候选人证据。',
            'meta': {'lastFocus': {'entity_type': 'candidate', 'name': '吴明华', 'entity_id': 'c-wmh'}},
            'entities': [{'type': 'candidate', 'id': 'c-wmh', 'title': '吴明华'}],
        },
    ]

    result = agentic_runtime.try_run(question, ctx)

    assert result is not None
    assert result.route_decision.intent == expected_intent
    assert result.trace[0].skill == expected_tool
    assert result.route_decision.tool_plan[0].tool == expected_tool
    assert 'candidate_evidence_bundle' not in [step.skill for step in result.trace]
    for part in summary_parts:
        assert part in result.summary
    assert expected_field_modules <= _field_source_modules(result)
    if expected_tool == 'payroll_analysis':
        assert result.route_decision.risk_level == 'high'
        assert result.route_decision.tool_plan[0].risk_level == 'high'
        assert result.route_decision.tool_plan[0].cache_policy == 'none'


def test_named_resume_query_sets_focus_for_followup_assessment(model_db) -> None:
    _seed_recruitment_data(model_db)
    ctx = _ctx()

    first = agentic_runtime.try_run('吴明华的简历', ctx)
    assert first is not None
    assert first.route_decision.intent == 'recruitment.person.resume.lookup'
    assert first.entities
    assert any(entity['title'] == '吴明华' for entity in first.entities)
    assert first.worksets

    ctx.history = [
        {'role': 'user', 'content': '吴明华的简历'},
        {
            'role': 'assistant',
            'content': first.summary,
            'meta': {
                'agenticState': first.route_decision.to_dict(),
                'worksets': first.worksets,
                'lastFocus': {'entity_type': 'candidate', 'name': '吴明华', 'entity_id': 'c-wmh'},
            },
            'worksets': first.worksets,
            'entities': first.entities,
        },
    ]

    followup = agentic_runtime.try_run('分析一下这个人怎么样', ctx)

    assert followup is not None
    assert followup.route_decision.intent == 'recruitment.person.assess'
    assert '吴明华' in followup.summary
    assert '94' in followup.summary
    assert '供应链总监' in followup.summary
    assert '一下吴明华吴明华' not in followup.summary


def test_colloquial_candidate_reliability_followup_uses_last_focus(model_db) -> None:
    _seed_recruitment_data(model_db)
    ctx = _ctx()

    first = agentic_runtime.try_run('吴明华的简历', ctx)
    ctx.history = [
        {'role': 'user', 'content': '吴明华的简历'},
        {
            'role': 'assistant',
            'content': first.summary,
            'meta': {
                'lastFocus': {'entity_type': 'candidate', 'name': '吴明华', 'entity_id': 'c-wmh'},
            },
            'worksets': first.worksets,
            'entities': first.entities,
        },
    ]

    followup = agentic_runtime.try_run('这人靠谱吗，值不值得约一轮？', ctx)

    assert followup is not None
    assert followup.route_decision.intent == 'recruitment.person.assess'
    assert followup.trace[0].skill == 'candidate_evidence_bundle'
    assert '吴明华' in followup.summary
    assert '供应链总监' in followup.summary
    assert any(widget['type'] == 'source_citations' for widget in followup.widgets)


def test_colloquial_employee_late_question_uses_employee_attendance_evidence(model_db) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run('吴明华最近迟到是不是有点多，严重吗？', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'attendance.employee.anomaly'
    assert result.trace[0].skill == 'employee_attendance_evidence'
    assert result.route_decision.tool_plan[0].input['keyword'] == '吴明华'
    assert result.route_decision.tool_plan[0].input['recent_days'] == 30
    assert any(widget['type'] == 'source_citations' for widget in result.widgets)
    assert {
        source['module']
        for widget in result.widgets
        if widget.get('type') == 'source_citations'
        for source in widget.get('sources') or []
        if source.get('fields')
    } >= {'employees', 'attendance_records', 'attendance_stats', 'leave_requests'}


def test_colloquial_payroll_exception_question_stays_in_payroll_summary(model_db) -> None:
    _seed_operational_route_data(model_db)

    result = agentic_runtime.try_run('工资这块有没有啥异常，帮我看一下', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'payroll.summary'
    assert result.trace[0].skill == 'payroll_analysis'
    assert result.route_decision.risk_level == 'high'
    assert result.route_decision.tool_plan[0].risk_level == 'high'
    assert 'candidate_evidence_bundle' not in [step.skill for step in result.trace]
    assert '敏感信息' in result.summary


def test_candidate_assessment_source_citations_include_field_evidence(model_db) -> None:
    _seed_recruitment_data(model_db)

    result = agentic_runtime.try_run('分析一下候选人吴明华怎么样，并说明依据', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'recruitment.person.assess'
    sources = next(widget for widget in result.widgets if widget['type'] == 'source_citations')['sources']
    by_module = {source['module']: source for source in sources}
    assert {field['key'] for field in by_module['resumes']['fields']} >= {'resume.score', 'resume.match_degree', 'resume.summary'}
    assert {field['key'] for field in by_module['candidates']['fields']} >= {'candidate.status', 'candidate.source', 'candidate.ai_summary'}
    assert {field['key'] for field in by_module['jobs']['fields']} >= {'job.title', 'job.department'}
    assert all('139' not in str(source.get('fields')) for source in sources)


def test_resume_lookup_normalizes_candidate_name_from_role_phrase(model_db) -> None:
    _seed_recruitment_data(model_db)
    ctx = _ctx()

    result = agentic_runtime.try_run('给我看电子工程师候选人李博豪的简历附件预览和证据', ctx)

    assert result is not None
    assert result.route_decision.intent == 'recruitment.person.resume.lookup'
    assert result.route_decision.tool_plan[0].input == {'keyword': '李博豪'}
    assert any(entity['title'] == '李博豪' for entity in result.entities)
    assert any(widget['type'] == 'media_preview' for widget in result.widgets)
    assert any(
        widget['type'] == 'source_citations' and any(source.get('url') for source in widget.get('sources') or [])
        for widget in result.widgets
    )


def test_recruitment_match_workset_uses_ranked_candidate_order(model_db) -> None:
    from models import Candidate, Interview, Job, Resume, db

    db.session.add(Job(
        id='j-electronics-rank',
        title='电子工程师',
        department='研发部',
        status='open',
        created_at=datetime(2026, 5, 20, 9, 0),
    ))
    resumes = [
        Resume(
            id='r-denghao',
            job_id='j-electronics-rank',
            candidate_name='邓浩',
            file_url='/uploads/denghao.pdf',
            ai_analysis={
                'score': 91,
                'matchDegree': 94,
                'summary': '硬件调试和EMC整改经验完整。',
                'strengths': ['EMC整改', '量产导入'],
                'weaknesses': ['团队管理经验较少'],
            },
            created_at=datetime(2026, 5, 22, 10, 0),
        ),
        Resume(
            id='r-yanglin',
            job_id='j-electronics-rank',
            candidate_name='杨琳',
            file_url='/uploads/yanglin.pdf',
            ai_analysis={
                'score': 84,
                'matchDegree': 88,
                'summary': '传感器与低功耗电路经验较强。',
                'strengths': ['传感器调试', '测试规范'],
                'weaknesses': ['EMC整改项目较少'],
            },
            created_at=datetime(2026, 5, 24, 10, 0),
        ),
        Resume(
            id='r-luowei',
            job_id='j-electronics-rank',
            candidate_name='罗伟',
            file_url='/uploads/luowei.pdf',
            ai_analysis={
                'score': 76,
                'matchDegree': 72,
                'summary': '硬件测试背景扎实。',
                'strengths': ['问题复现'],
                'weaknesses': ['独立方案设计经验不足'],
            },
            created_at=datetime(2026, 5, 26, 10, 0),
        ),
    ]
    candidates = [
        Candidate(
            id='c-luowei',
            resume_id='r-luowei',
            job_id='j-electronics-rank',
            name='罗伟',
            status='new',
            match_records=[{'score': 72}],
            created_at=datetime(2026, 5, 26, 11, 0),
        ),
        Candidate(
            id='c-yanglin',
            resume_id='r-yanglin',
            job_id='j-electronics-rank',
            name='杨琳',
            status='screening',
            match_records=[{'score': 88}],
            created_at=datetime(2026, 5, 24, 11, 0),
        ),
        Candidate(
            id='c-denghao',
            resume_id='r-denghao',
            job_id='j-electronics-rank',
            name='邓浩',
            status='interview',
            match_records=[{'score': 94}],
            created_at=datetime(2026, 5, 22, 11, 0),
        ),
    ]
    interviews = [
        Interview(
            id='i-denghao',
            resume_id='r-denghao',
            job_id='j-electronics-rank',
            scheduled_at=datetime(2026, 5, 28, 15, 0),
            status='passed',
        ),
    ]
    db.session.add_all([*resumes, *candidates, *interviews])
    db.session.commit()

    result = agentic_runtime.try_run('电子工程师岗位最近候选人谁更合适？给对比矩阵', _ctx('s-ranked-candidate'))

    assert result is not None
    assert result.worksets
    ws = result.worksets[-1]
    assert ws['entity_type'] == 'candidate'
    assert [item['title'] for item in ws['items'][:3]] == ['邓浩', '杨琳', '罗伟']
    assert [item['rank'] for item in ws['items'][:3]] == [1, 2, 3]
    assert all(item['entity_type'] == 'candidate' for item in ws['items'][:3])
    assert any(entity['type'] == 'job' and entity['title'] == '电子工程师' for entity in result.entities)


def test_colloquial_interview_action_returns_existing_confirmation_card(model_db) -> None:
    _seed_recruitment_data(model_db)
    ctx = _ctx()

    lookup = agentic_runtime.try_run('吴明华的简历', ctx)
    ctx.history = [
        {'role': 'user', 'content': '吴明华的简历'},
        {
            'role': 'assistant',
            'content': lookup.summary,
            'meta': {
                'lastFocus': {'entity_type': 'candidate', 'name': '吴明华', 'entity_id': 'c-wmh'},
            },
            'worksets': lookup.worksets,
            'entities': lookup.entities,
        },
    ]

    result = agentic_runtime.try_run('给他安排明天下午三点面试', ctx)

    assert result is not None
    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'confirmation_card'
    assert result.actions
    assert '吴明华' in result.summary
    assert '2026-05-30 15:00' in result.summary


def test_agentic_interview_action_resolves_second_candidate_from_workset(model_db) -> None:
    from models import Candidate, Resume, db

    _seed_recruitment_data(model_db)
    db.session.add_all([
        Resume(
            id='r-denghao-agentic',
            job_id='j-electronic',
            candidate_name='邓浩',
            file_url='/uploads/denghao.pdf',
            ai_analysis={'score': 94, 'matchDegree': 94, 'strengths': ['量产导入']},
            created_at=datetime(2026, 5, 28, 10, 0),
        ),
        Resume(
            id='r-yanglin-agentic',
            job_id='j-electronic',
            candidate_name='杨琳',
            file_url='/uploads/yanglin.pdf',
            ai_analysis={'score': 86, 'matchDegree': 88, 'weaknesses': ['EMC整改经验不足']},
            created_at=datetime(2026, 5, 27, 10, 0),
        ),
        Resume(
            id='r-luowei-agentic',
            job_id='j-electronic',
            candidate_name='罗伟',
            file_url='/uploads/luowei.pdf',
            ai_analysis={'score': 72, 'matchDegree': 76},
            created_at=datetime(2026, 5, 25, 10, 0),
        ),
        Candidate(
            id='c-yanglin-agentic',
            resume_id='r-yanglin-agentic',
            job_id='j-electronic',
            name='杨琳',
            status='screening',
            match_records=[{'score': 86, 'matchDegree': 88}],
            created_at=datetime(2026, 5, 27, 11, 0),
        ),
        Candidate(
            id='c-denghao-agentic',
            resume_id='r-denghao-agentic',
            job_id='j-electronic',
            name='邓浩',
            status='interview',
            match_records=[{'score': 94, 'matchDegree': 94}],
            created_at=datetime(2026, 5, 28, 11, 0),
        ),
        Candidate(
            id='c-luowei-agentic',
            resume_id='r-luowei-agentic',
            job_id='j-electronic',
            name='罗伟',
            status='screening',
            match_records=[{'score': 72, 'matchDegree': 76}],
            created_at=datetime(2026, 5, 25, 11, 0),
        ),
    ])
    db.session.commit()
    ctx = _ctx('s-agentic-second-candidate')

    matrix = agentic_runtime.try_run('电子工程师岗位最近候选人谁更合适？给对比矩阵', ctx)
    agentic_runtime.persist_turn('电子工程师岗位最近候选人谁更合适？给对比矩阵', ctx, matrix)
    confirm_ctx = _ctx(matrix.session_id)
    result = agentic_runtime.try_run('给第二位安排明天下午三点面试', confirm_ctx)

    assert result is not None
    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'confirmation_card'
    assert '杨琳' in result.summary
    pending = getattr(result, '_pending_action')
    assert pending['tools'][0]['input']['resume_id'] == 'r-yanglin-agentic'
    assert pending['tools'][0]['input']['job_id'] == 'j-electronic'


def test_colloquial_second_candidate_reliability_followup_uses_workset(model_db) -> None:
    from models import Candidate, Resume, User, db

    _seed_recruitment_data(model_db)
    db.session.add_all([
        User(
            id='u-agentic-workset',
            email='agentic-workset@example.com',
            password_hash='x',
            name='测试HR',
            role='hr_admin',
        ),
        Resume(
            id='r-denghao-workset-colloquial',
            job_id='j-electronic',
            candidate_name='邓浩',
            file_url='/uploads/denghao.pdf',
            ai_analysis={
                'score': 94,
                'matchDegree': 94,
                'summary': '硬件调试和量产导入经验完整。',
                'strengths': ['量产导入', 'EMC整改'],
                'weaknesses': ['团队管理经验较少'],
            },
            created_at=datetime(2026, 5, 28, 10, 0),
        ),
        Resume(
            id='r-yanglin-workset-colloquial',
            job_id='j-electronic',
            candidate_name='杨琳',
            file_url='/uploads/yanglin.pdf',
            ai_analysis={
                'score': 86,
                'matchDegree': 88,
                'summary': '传感器与低功耗电路经验较强。',
                'strengths': ['传感器调试', '测试规范'],
                'weaknesses': ['EMC整改经验不足'],
            },
            created_at=datetime(2026, 5, 27, 10, 0),
        ),
        Candidate(
            id='c-denghao-workset-colloquial',
            resume_id='r-denghao-workset-colloquial',
            job_id='j-electronic',
            name='邓浩',
            status='interview',
            match_records=[{'score': 94, 'matchDegree': 94}],
            created_at=datetime(2026, 5, 28, 11, 0),
        ),
        Candidate(
            id='c-yanglin-workset-colloquial',
            resume_id='r-yanglin-workset-colloquial',
            job_id='j-electronic',
            name='杨琳',
            status='screening',
            match_records=[{'score': 86, 'matchDegree': 88}],
            created_at=datetime(2026, 5, 27, 11, 0),
        ),
    ])
    db.session.commit()

    first = handle_assistant_query(
        'u-agentic-workset',
        '电子工程师岗位最近候选人谁更合适？给对比矩阵',
    )
    followup = handle_assistant_query(
        'u-agentic-workset',
        '第二位靠谱吗，值不值得约一轮？',
        session_id=first['sessionId'],
    )

    assert followup['meta']['routeDecision']['intent'] in {'candidate.evaluation', 'recruitment.person.assess'}
    assert '杨琳' in followup['summary']
    assert '邓浩' not in followup['summary'].splitlines()[0]
    assert 'candidate_evidence_bundle' in followup['meta']['usedSkills']
    assert followup['meta']['routeDecision']['toolPlan'][0]['input'] == {
        'candidate_id': 'c-yanglin-workset-colloquial',
    }
    sources = [
        source
        for widget in followup['widgets']
        if widget.get('type') == 'source_citations'
        for source in widget.get('sources') or []
    ]
    assert {source['module'] for source in sources} >= {'candidates', 'resumes', 'jobs'}


def test_agentic_confirmed_action_is_consumed_after_execution(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import AssistantSession, Notification, User, db

    db.session.add(User(
        id='u-agentic',
        email='agentic-confirm@example.com',
        password_hash='x',
        name='测试HR',
        role='hr_admin',
    ))
    db.session.commit()

    ctx = _ctx()
    prepare = agentic_runtime.try_run('帮我给本月迟到最多的5个人生成提醒', ctx)
    agentic_runtime.persist_turn('帮我给本月迟到最多的5个人生成提醒', ctx, prepare)
    payload = prepare.actions[0]['payload']

    confirm_ctx = _ctx(prepare.session_id)
    confirmed = agentic_runtime.try_run(payload, confirm_ctx)
    agentic_runtime.persist_turn(payload, confirm_ctx, confirmed)

    assert Notification.query.count() == 1
    assert getattr(confirmed, '_resolved_action_id')
    session = AssistantSession.query.get(prepare.session_id)
    assert session.messages[-1]['meta']['resolvedActionId'] == getattr(confirmed, '_resolved_action_id')

    duplicate = agentic_runtime.try_run(payload, _ctx(prepare.session_id))

    assert Notification.query.count() == 1
    assert '没有找到可执行的待确认动作' in duplicate.summary


@pytest.mark.parametrize('role', ['employee', 'viewer', 'recruiter', 'finance', 'manager', 'executive'])
def test_agentic_attendance_reminder_forbids_unprivileged_roles_before_draft(model_db, role: str) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run('帮我给本月迟到最多的5个人生成提醒', _ctx(role=role))

    from models import Notification

    _assert_write_action_forbidden(result)
    assert result.route_decision.intent == 'attendance.late_top_notify'
    assert Notification.query.count() == 0


def test_agentic_approval_decision_requires_confirmation_before_write(model_db) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run('请通过审批 ap-1，意见：同意请假', _ctx())

    from models import ApprovalInstance, ApprovalRecord, EmployeeRequest, OperationLog

    assert result is not None
    assert result.requires_confirmation is True
    assert result.route_decision.intent == 'approval.decision'
    assert result.actions and result.actions[0]['payload'].startswith('确认执行动作')
    assert {widget['type'] for widget in result.widgets} >= {'status_badges', 'table', 'confirmation_card', 'source_citations'}
    assert ApprovalInstance.query.get('ap-1').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 0
    assert EmployeeRequest.query.count() == 0
    assert OperationLog.query.filter_by(module='approval', target_id='ap-1').count() == 0


@pytest.mark.parametrize('role', ['employee', 'viewer', 'recruiter', 'finance'])
def test_agentic_approval_decision_forbids_unauthorized_roles_before_pending_action(model_db, role: str) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run('请通过审批 ap-1，意见：同意请假', _ctx(role=role))

    from models import ApprovalInstance, ApprovalRecord, OperationLog

    _assert_write_action_forbidden(result)
    assert result.route_decision.intent == 'approval.decision'
    assert ApprovalInstance.query.get('ap-1').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 0
    assert OperationLog.query.filter_by(module='approval', target_id='ap-1').count() == 0


def test_agentic_approval_decision_forbids_manager_on_approval_assigned_to_other_user(model_db) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run(
        '请通过审批 ap-1，意见：同意请假',
        _ctx(role='manager', user_id='u-manager-other'),
    )

    from models import ApprovalInstance, ApprovalRecord, OperationLog

    _assert_write_action_forbidden(result)
    assert result.route_decision.intent == 'approval.decision'
    assert ApprovalInstance.query.get('ap-1').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 0
    assert OperationLog.query.filter_by(module='approval', target_id='ap-1').count() == 0


def test_agentic_approval_decision_keeps_eval_approval_id_prefix(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, db

    db.session.add(ApprovalInstance(
        id='eval-ap-abc123',
        business_type='employee_request',
        business_id='leave-eval',
        title='AI评估审批',
        applicant_id='u-other',
        approver_id='u-agentic',
        status='pending',
    ))
    db.session.commit()

    result = agentic_runtime.try_run('请通过审批 eval-ap-abc123', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert getattr(result, '_pending_action')['tools'][0]['input']['approval_id'] == 'eval-ap-abc123'


def test_agentic_approval_decision_confirm_executes_and_consumes_action(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import (
        ApprovalInstance, ApprovalRecord, AssistantSession, EmployeeRequest,
        OperationLog, User, db,
    )

    db.session.add_all([
        User(
            id='u-agentic',
            email='approval-agentic@example.com',
            password_hash='x',
            name='审批HR',
            role='hr_admin',
        ),
        EmployeeRequest(
            id='leave-1',
            employee_id='e-wmh',
            request_type='leave',
            title='吴明华请假申请',
            status='pending',
            approval_id='ap-1',
            created_by='u-other',
        ),
    ])
    db.session.commit()

    ctx = _ctx()
    prepare = agentic_runtime.try_run('请通过审批 ap-1，意见：同意请假', ctx)
    agentic_runtime.persist_turn('请通过审批 ap-1，意见：同意请假', ctx, prepare)
    payload = prepare.actions[0]['payload']

    confirm_ctx = _ctx(prepare.session_id)
    confirmed = agentic_runtime.try_run(payload, confirm_ctx)
    agentic_runtime.persist_turn(payload, confirm_ctx, confirmed)

    assert ApprovalInstance.query.get('ap-1').status == 'approved'
    assert EmployeeRequest.query.get('leave-1').status == 'approved'
    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 1
    assert OperationLog.query.filter_by(module='approval', target_id='ap-1').count() == 1
    assert getattr(confirmed, '_resolved_action_id')
    session = AssistantSession.query.get(prepare.session_id)
    assert session.messages[-1]['meta']['resolvedActionId'] == getattr(confirmed, '_resolved_action_id')

    duplicate = agentic_runtime.try_run(payload, _ctx(prepare.session_id))

    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 1
    assert OperationLog.query.filter_by(module='approval', target_id='ap-1').count() == 1
    assert '没有找到可执行的待确认动作' in duplicate.summary


def test_agentic_approval_rejection_confirm_executes_and_consumes_action(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import (
        ApprovalInstance, ApprovalRecord, AssistantSession, EmployeeRequest,
        OperationLog, User, db,
    )

    db.session.add_all([
        User(
            id='u-agentic',
            email='approval-reject-agentic@example.com',
            password_hash='x',
            name='审批HR',
            role='hr_admin',
        ),
        EmployeeRequest(
            id='leave-1',
            employee_id='e-wmh',
            request_type='leave',
            title='吴明华请假申请',
            status='pending',
            approval_id='ap-1',
            created_by='u-other',
        ),
    ])
    db.session.commit()

    ctx = _ctx()
    prepare = agentic_runtime.try_run('请驳回审批 ap-1，意见：材料不完整', ctx)
    agentic_runtime.persist_turn('请驳回审批 ap-1，意见：材料不完整', ctx, prepare)
    payload = prepare.actions[0]['payload']

    assert prepare.requires_confirmation is True
    assert getattr(prepare, '_pending_action')['tools'][0]['input']['action'] == 'reject'
    assert ApprovalInstance.query.get('ap-1').status == 'pending'
    assert EmployeeRequest.query.get('leave-1').status == 'pending'

    confirm_ctx = _ctx(prepare.session_id)
    confirmed = agentic_runtime.try_run(payload, confirm_ctx)
    agentic_runtime.persist_turn(payload, confirm_ctx, confirmed)

    assert ApprovalInstance.query.get('ap-1').status == 'rejected'
    assert EmployeeRequest.query.get('leave-1').status == 'rejected'
    records = ApprovalRecord.query.filter_by(approval_id='ap-1').all()
    assert len(records) == 1
    assert records[0].action == 'rejected'
    assert OperationLog.query.filter_by(module='approval', action='reject', target_id='ap-1').count() == 1
    assert getattr(confirmed, '_resolved_action_id')
    session = AssistantSession.query.get(prepare.session_id)
    assert session.messages[-1]['meta']['resolvedActionId'] == getattr(confirmed, '_resolved_action_id')

    duplicate = agentic_runtime.try_run(payload, _ctx(prepare.session_id))

    assert ApprovalRecord.query.filter_by(approval_id='ap-1').count() == 1
    assert OperationLog.query.filter_by(module='approval', action='reject', target_id='ap-1').count() == 1
    assert '没有找到可执行的待确认动作' in duplicate.summary


def test_agentic_approval_decision_can_resolve_first_pending_from_context(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    ctx = _ctx()

    pending = agentic_runtime.try_run('待我审批的申请有哪些', ctx)
    ctx.history = [
        {'role': 'user', 'content': '待我审批的申请有哪些'},
        {
            'role': 'assistant',
            'content': pending.summary,
            'widgets': pending.widgets,
            'entities': pending.entities,
            'meta': {'routeDecision': pending.route_decision.to_dict()},
        },
    ]
    result = agentic_runtime.try_run('把第一条审批通过', ctx)

    assert result is not None
    assert result.requires_confirmation is True
    assert result.route_decision.intent == 'approval.decision'
    assert getattr(result, '_pending_action')['tools'][0]['input']['approval_id'] == 'ap-1'


def test_agentic_employee_change_submit_requires_confirmation_before_business_write(model_db) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run('如果把吴明华调到研发部，会影响哪些岗位、薪资、通知和审批？', _ctx())

    from models import ApprovalInstance, Employee, EmployeeChange, OperationLog

    assert result is not None
    assert result.requires_confirmation is True
    assert result.route_decision.intent == 'employee.change.impact'
    assert result.actions and result.actions[0]['payload'].startswith('确认执行动作')
    assert {widget['type'] for widget in result.widgets} >= {'timeline', 'status_badges', 'table', 'confirmation_card', 'source_citations'}
    assert getattr(result, '_pending_action')['tools'][0]['tool'] == 'employee_change_submit'
    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert Employee.query.get('e-wmh').department_id == 'd-ops'


@pytest.mark.parametrize('role', ['employee', 'viewer', 'recruiter', 'finance'])
def test_agentic_employee_change_forbids_unauthorized_roles_before_pending_action(model_db, role: str) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run(
        '如果把吴明华调到研发部，会影响哪些岗位、薪资、通知和审批？',
        _ctx(role=role),
    )

    from models import ApprovalInstance, Employee, EmployeeChange, OperationLog

    _assert_write_action_forbidden(result)
    assert result.route_decision.intent == 'employee.change.impact'
    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert Employee.query.get('e-wmh').department_id == 'd-ops'


def test_agentic_employee_change_submit_confirm_executes_and_consumes_action(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, AssistantSession, Employee, EmployeeChange, Notification, OperationLog, User, db

    db.session.add(User(
        id='u-agentic',
        email='change-agentic@example.com',
        password_hash='x',
        name='异动HR',
        role='hr_admin',
    ))
    db.session.commit()

    ctx = _ctx()
    prepare = agentic_runtime.try_run('如果把吴明华调到研发部，会影响哪些岗位、薪资、通知和审批？', ctx)
    agentic_runtime.persist_turn('如果把吴明华调到研发部，会影响哪些岗位、薪资、通知和审批？', ctx, prepare)
    payload = prepare.actions[0]['payload']

    confirm_ctx = _ctx(prepare.session_id)
    confirmed = agentic_runtime.try_run(payload, confirm_ctx)
    agentic_runtime.persist_turn(payload, confirm_ctx, confirmed)

    changes = EmployeeChange.query.filter_by(employee_id='e-wmh').all()
    assert len(changes) == 1
    change = changes[0]
    assert change.status == 'pending'
    assert change.after_department_id == 'd-rd'
    assert Employee.query.get('e-wmh').department_id == 'd-ops'
    approvals = ApprovalInstance.query.filter_by(business_type='employee_change', business_id=change.id).all()
    assert len(approvals) == 1
    assert approvals[0].status == 'pending'
    notifications = Notification.query.filter_by(notice_type='approval').all()
    assert len(notifications) == 1
    assert notifications[0].user_id == 'u-agentic'
    assert '吴明华' in notifications[0].title
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit', target_id=change.id).count() == 1
    assert getattr(confirmed, '_resolved_action_id')
    session = AssistantSession.query.get(prepare.session_id)
    assert session.messages[-1]['meta']['resolvedActionId'] == getattr(confirmed, '_resolved_action_id')

    duplicate = agentic_runtime.try_run(payload, _ctx(prepare.session_id))

    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 1
    assert ApprovalInstance.query.filter_by(business_type='employee_change', business_id=change.id).count() == 1
    assert Notification.query.filter_by(notice_type='approval').count() == 1
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit', target_id=change.id).count() == 1
    assert '没有找到可执行的待确认动作' in duplicate.summary


def test_employee_change_action_resolves_mixed_employee_name_and_beats_context(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Candidate, Department, Employee, Position, db

    db.session.add_all([
        Candidate(id='c-change-wang', name='王五', status='screening'),
        Department(id='d-change-source', name='AI异动E2E原部门', status='active'),
        Department(id='d-change-target', name='AI异动E2E目标部', status='active'),
        Position(id='p-change-source', title='异动原岗位', department_id='d-change-source', status='active'),
        Employee(
            id='e-change-mixed',
            employee_no='ECHGMIX001',
            name='AI异动E2E员工260602023500',
            status='active',
            department_id='d-change-source',
            position_id='p-change-source',
            job_title='异动原岗位',
        ),
    ])
    db.session.commit()
    ctx = _ctx()
    ctx.client_context = {
        'path': '/hrm/employee-changes',
        'moduleId': 'employee-changes',
        'moduleName': '人事异动',
    }
    ctx.history = [{
        'role': 'assistant',
        'content': '王五候选人评估完成。',
        'meta': {'lastFocus': {'entity_type': 'candidate', 'entity_id': 'c-change-wang', 'name': '王五'}},
    }]

    result = agentic_runtime.try_run('把AI异动E2E员工260602023500调到AI异动E2E目标部，先分析影响并准备确认', ctx)

    assert result is not None
    assert result.route_decision.intent == 'employee.change.impact'
    assert result.requires_confirmation is True
    assert result.trace[0].skill == 'employee_change_impact'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-change-mixed'
    assert pending_tool['input']['target_department_id'] == 'd-change-target'
    assert '王五' not in result.summary


def test_employee_change_action_carries_target_position_to_confirmation(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Department, Employee, Position, db

    db.session.add_all([
        Department(id='d-change-position-source', name='AI岗位异动原部门', status='active'),
        Department(id='d-change-position-target', name='AI岗位异动目标部', status='active'),
        Position(
            id='p-change-position-source',
            title='AI岗位异动原岗位',
            department_id='d-change-position-source',
            level='P2',
            status='active',
        ),
        Position(
            id='p-change-position-target',
            title='AI岗位异动目标岗260602',
            department_id='d-change-position-target',
            level='P4',
            status='active',
        ),
        Employee(
            id='e-change-position',
            employee_no='ECHGPOS001',
            name='AI岗位异动员工260602',
            status='active',
            department_id='d-change-position-source',
            position_id='p-change-position-source',
            job_title='AI岗位异动原岗位',
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run(
        '把AI岗位异动员工260602调到AI岗位异动目标部，目标岗位：AI岗位异动目标岗260602，先分析影响并准备确认',
        _ctx(),
    )

    assert result is not None
    assert result.requires_confirmation is True
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-change-position'
    assert pending_tool['input']['target_department_id'] == 'd-change-position-target'
    assert pending_tool['input']['target_position'] == 'AI岗位异动目标岗260602'


def test_employee_change_target_department_keeps_numeric_suffix_when_names_share_prefix(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Department, Employee, Position, db

    db.session.add_all([
        Department(id='d-loop-old-target', name='AI闭环E2E目标部260602025733', status='active'),
        Department(id='d-loop-source', name='AI闭环E2E原部260603033141', status='active'),
        Department(id='d-loop-new-target', name='AI闭环E2E目标部260603033141', status='active'),
        Position(
            id='p-loop-source',
            title='AI闭环E2E原岗260603033141',
            department_id='d-loop-source',
            level='P2',
            status='active',
        ),
        Position(
            id='p-loop-new-target',
            title='AI闭环E2E目标岗260603033141',
            department_id='d-loop-new-target',
            level='P5',
            status='active',
        ),
        Employee(
            id='e-loop-suffix',
            employee_no='ELOOPSUFFIX',
            name='AI闭环E2E员工260603033141',
            status='active',
            department_id='d-loop-source',
            position_id='p-loop-source',
            job_title='AI闭环E2E原岗260603033141',
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run(
        '把AI闭环E2E员工260603033141调到AI闭环E2E目标部260603033141，目标岗位：AI闭环E2E目标岗260603033141，先分析影响并准备确认',
        _ctx(),
    )

    assert result is not None
    assert result.requires_confirmation is True
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-loop-suffix'
    assert pending_tool['input']['target_department_id'] == 'd-loop-new-target'
    assert pending_tool['input']['target_department'] == 'AI闭环E2E目标部260603033141'
    assert pending_tool['input']['target_position'] == 'AI闭环E2E目标岗260603033141'

    from services.assistant_core.skills import _resolve_position_for_change
    target_department = Department.query.get(pending_tool['input']['target_department_id'])
    assert _resolve_position_for_change(pending_tool['input'], target_department).id == 'p-loop-new-target'


def test_agentic_salary_adjustment_submit_requires_confirmation_before_business_write(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, EmployeeChange, OperationLog, SalaryProfile, db

    db.session.add(SalaryProfile(
        id='sp-wmh',
        employee_id='e-wmh',
        base_salary=12000,
        position_salary=8000,
        performance_salary=5000,
        allowance=1000,
        status='active',
    ))
    db.session.commit()

    before_salary = SalaryProfile.query.get('sp-wmh').to_dict()
    result = agentic_runtime.try_run('给吴明华调薪 1800 元，先分析影响并准备确认', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.route_decision.intent == 'employee.salary_adjustment.impact'
    assert result.actions and result.actions[0]['payload'].startswith('确认执行动作')
    assert {widget['type'] for widget in result.widgets} >= {'metrics', 'timeline', 'status_badges', 'table', 'confirmation_card', 'source_citations'}
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['salary_adjustment'] == '1800'
    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert SalaryProfile.query.get('sp-wmh').to_dict() == before_salary


@pytest.mark.parametrize('role', ['employee', 'viewer', 'recruiter', 'finance'])
def test_agentic_salary_adjustment_forbids_unauthorized_roles_before_pending_action(model_db, role: str) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, EmployeeChange, OperationLog, SalaryProfile, db

    db.session.add(SalaryProfile(
        id='sp-wmh',
        employee_id='e-wmh',
        base_salary=12000,
        position_salary=8000,
        performance_salary=5000,
        allowance=1000,
        status='active',
    ))
    db.session.commit()

    before_salary = SalaryProfile.query.get('sp-wmh').to_dict()
    result = agentic_runtime.try_run('给吴明华调薪 1800 元，先分析影响并准备确认', _ctx(role=role))

    _assert_write_action_forbidden(result)
    assert result.route_decision.intent == 'employee.salary_adjustment.impact'
    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert SalaryProfile.query.get('sp-wmh').to_dict() == before_salary


def test_salary_adjustment_amount_ignores_digits_in_employee_name(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Department, Employee, Position, SalaryProfile, db

    db.session.add_all([
        Department(id='d-salary-eval', name='AI调薪评估部', status='active'),
        Position(id='p-salary-eval', title='高级测试工程师', department_id='d-salary-eval', status='active'),
        Employee(
            id='e-salary-eval',
            employee_no='ESAL00006',
            name='AI调薪评估员工e6b1',
            status='active',
            department_id='d-salary-eval',
            position_id='p-salary-eval',
            job_title='高级测试工程师',
        ),
        SalaryProfile(
            id='sp-salary-eval',
            employee_id='e-salary-eval',
            base_salary=12000,
            position_salary=8000,
            performance_salary=5000,
            allowance=1000,
            status='active',
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run('给AI调薪评估员工e6b1调薪 1800 元，先分析影响并准备确认', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'employee.salary_adjustment.impact'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['input']['employee_id'] == 'e-salary-eval'
    assert pending_tool['input']['salary_adjustment'] == '1800'
    assert '上调 1,800 元' in result.summary


def test_salary_adjustment_action_beats_salary_page_context(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Department, Employee, Position, SalaryProfile, db

    db.session.add_all([
        Department(id='d-salary-page', name='AI调薪页面部', status='active'),
        Position(id='p-salary-page', title='薪资页面测试岗', department_id='d-salary-page', status='active'),
        Employee(
            id='e-salary-page',
            employee_no='ESALPAGE001',
            name='AI调薪E2E员工260602015000',
            status='active',
            department_id='d-salary-page',
            position_id='p-salary-page',
            job_title='薪资页面测试岗',
        ),
        SalaryProfile(
            id='sp-salary-page',
            employee_id='e-salary-page',
            base_salary=12000,
            position_salary=8000,
            performance_salary=5000,
            allowance=1200,
            status='active',
        ),
    ])
    db.session.commit()
    ctx = _ctx()
    ctx.client_context = {
        'path': '/salary-profiles',
        'moduleId': 'salary-profiles',
        'moduleName': '薪资档案',
    }

    result = agentic_runtime.try_run('给AI调薪E2E员工260602015000调薪 1800 元，先分析影响并准备确认', ctx)

    assert result is not None
    assert result.route_decision.intent == 'employee.salary_adjustment.impact'
    assert result.requires_confirmation is True
    assert result.trace[0].skill == 'employee_salary_adjustment_impact'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-salary-page'
    assert pending_tool['input']['salary_adjustment'] == '1800'


def test_salary_adjustment_action_beats_contaminated_person_focus(model_db) -> None:
    from services.assistant_core import legacy_agentic_runtime as agentic_runtime
    from models import Candidate, Department, Employee, Position, SalaryProfile, db

    db.session.add_all([
        Candidate(id='c-wang', name='王五', status='screening'),
        Department(id='d-salary-focus', name='AI调薪焦点部', status='active'),
        Position(id='p-salary-focus', title='调薪焦点测试岗', department_id='d-salary-focus', status='active'),
        Employee(
            id='e-salary-focus',
            employee_no='ESALFOCUS001',
            name='AI调薪E2E员工260602020014',
            status='active',
            department_id='d-salary-focus',
            position_id='p-salary-focus',
            job_title='调薪焦点测试岗',
        ),
        SalaryProfile(
            id='sp-salary-focus',
            employee_id='e-salary-focus',
            base_salary=12000,
            position_salary=8000,
            performance_salary=5000,
            allowance=1200,
            status='active',
        ),
    ])
    db.session.commit()
    ctx = _ctx()
    ctx.client_context = {
        'path': '/salary-profiles',
        'moduleId': 'salary-profiles',
        'moduleName': '薪资档案',
    }
    ctx.history = [{
        'role': 'assistant',
        'content': '王五候选人评估完成。',
        'meta': {
            'lastFocus': {
                'entity_type': 'candidate',
                'entity_id': 'c-wang',
                'name': '王五',
            },
        },
    }]

    result = agentic_runtime.try_run('给AI调薪E2E员工260602020014调薪 1800 元，先分析影响并准备确认', ctx)

    assert result is not None
    assert result.route_decision.intent == 'employee.salary_adjustment.impact'
    assert result.route_decision.route_track == 'A_DATA_ACTION'
    assert result.requires_confirmation is True
    assert result.trace[0].skill == 'employee_salary_adjustment_impact'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['input']['employee_id'] == 'e-salary-focus'
    assert pending_tool['input']['salary_adjustment'] == '1800'
    assert '王五' not in result.summary


def test_agentic_salary_adjustment_confirm_executes_and_consumes_action(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, AssistantSession, Employee, EmployeeChange, Notification, OperationLog, SalaryProfile, User, db

    db.session.add_all([
        User(
            id='u-agentic',
            email='salary-agentic@example.com',
            password_hash='x',
            name='调薪HR',
            role='hr_admin',
        ),
        SalaryProfile(
            id='sp-wmh',
            employee_id='e-wmh',
            base_salary=12000,
            position_salary=8000,
            performance_salary=5000,
            allowance=1000,
            status='active',
        ),
    ])
    db.session.commit()
    before_salary = SalaryProfile.query.get('sp-wmh').to_dict()

    ctx = _ctx()
    prepare = agentic_runtime.try_run('给吴明华调薪 1800 元，先分析影响并准备确认', ctx)
    agentic_runtime.persist_turn('给吴明华调薪 1800 元，先分析影响并准备确认', ctx, prepare)
    payload = prepare.actions[0]['payload']

    confirmed = agentic_runtime.try_run(payload, _ctx(prepare.session_id))
    agentic_runtime.persist_turn(payload, _ctx(prepare.session_id), confirmed)

    changes = EmployeeChange.query.filter_by(employee_id='e-wmh').all()
    assert len(changes) == 1
    change = changes[0]
    assert change.status == 'pending'
    assert change.change_type == 'salary_adjustment'
    assert float(change.salary_adjustment) == 1800.0
    assert Employee.query.get('e-wmh').department_id == 'd-ops'
    assert SalaryProfile.query.get('sp-wmh').to_dict() == before_salary
    approvals = ApprovalInstance.query.filter_by(business_type='employee_change', business_id=change.id).all()
    assert len(approvals) == 1
    assert approvals[0].status == 'pending'
    notifications = Notification.query.filter_by(notice_type='approval').all()
    assert len(notifications) == 1
    assert notifications[0].user_id == 'u-agentic'
    assert '吴明华' in notifications[0].title
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit', target_id=change.id).count() == 1
    assert getattr(confirmed, '_resolved_action_id')
    session = AssistantSession.query.get(prepare.session_id)
    assert session.messages[-1]['meta']['resolvedActionId'] == getattr(confirmed, '_resolved_action_id')

    duplicate = agentic_runtime.try_run(payload, _ctx(prepare.session_id))

    assert EmployeeChange.query.filter_by(employee_id='e-wmh').count() == 1
    assert ApprovalInstance.query.filter_by(business_type='employee_change', business_id=change.id).count() == 1
    assert Notification.query.filter_by(notice_type='approval').count() == 1
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit', target_id=change.id).count() == 1
    assert '没有找到可执行的待确认动作' in duplicate.summary


def test_agentic_confirmed_action_rejects_unapproved_tool(monkeypatch) -> None:
    pending = {
        'id': 'act-unsafe',
        'label': '异常动作',
        'tools': [{'tool': 'smart_data_query', 'input': {'sql': 'select * from employees'}}],
    }
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(agentic_runtime.memory, 'get_pending_action', lambda user_id, session_id, action_id=None: pending)
    monkeypatch.setattr(agentic_runtime.ToolExecutor, 'execute', lambda self, tool, params, ctx: calls.append((tool, params)) or {'ok': True})

    result = agentic_runtime.try_run('确认执行动作：act-unsafe', _ctx())

    assert result.error_code == 'confirmed_action_rejected'
    assert calls == []
    assert getattr(result, '_resolved_action_id') == 'act-unsafe'


def test_service_entrypoint_keeps_frontend_response_shape(model_db, monkeypatch) -> None:
    _seed_recruitment_data(model_db)
    from models import User, db

    db.session.add(User(
        id='u-agentic',
        email='agentic@example.com',
        password_hash='x',
        name='测试HR',
        role='hr_admin',
    ))
    db.session.commit()

    payload = handle_assistant_query('u-agentic', '最近在招聘中的岗位有哪些')

    assert payload['schemaVersion'] == 'assistant.response.v2'
    assert payload['meta']['routeDecision']['toolPlan'][0]['input'] == {'module': 'jobs', 'status': 'open', 'limit': 20}
    assert payload['summary'].startswith('目前有 2 个招聘中的岗位')
    assert payload['answer']['content'] == payload['summary']
    assert payload['entities']
    assert payload['sessionId']
    assert payload['meta']['routeTrack'] == 'A_DATA_ACTION'
    assert payload['meta']['taskType'] == 'data_query'
    assert payload['meta']['routeDecision']['intent'] in {'recruitment.open_jobs', 'recruitment.jobs.open.list'}
    assert payload['copilot']['routePath'] == 'skill_first_runtime'


def test_service_entrypoint_resolves_pronoun_from_persisted_focus(model_db) -> None:
    _seed_recruitment_data(model_db)
    from models import User, db

    db.session.add(User(
        id='u-agentic',
        email='agentic-focus@example.com',
        password_hash='x',
        name='测试HR',
        role='hr_admin',
    ))
    db.session.commit()

    first = handle_assistant_query('u-agentic', '吴明华的简历')
    followup = handle_assistant_query('u-agentic', '分析一下这个人怎么样', session_id=first['sessionId'])

    assert followup['meta']['routeDecision']['intent'] in {'candidate.evaluation', 'recruitment.person.assess'}
    assert followup['copilot']['routePath'] == 'skill_first_runtime'
    assert '吴明华' in followup['summary']
    assert '94' in followup['summary']
    assert '一下吴明华吴明华' not in followup['summary']


@pytest.mark.parametrize(('question', 'intent', 'skill'), [
    ('查一下吴明华员工档案', 'employee.search', 'employee_search'),
    ('运营部下面有哪些人', 'employee.search', 'employee_search'),
    ('部门架构看一下', 'organization.overview', 'organization_search'),
    ('本月考勤异常情况', 'attendance.exceptions', 'attendance_analysis'),
    ('待我审批的申请有哪些', 'approval.pending', 'approval_search'),
    ('现在还有哪些 bug 没处理', 'feedback.pending_bugs', 'feedback_triage'),
    ('系统整体情况怎么样', 'dashboard.system.overview', 'dashboard_report'),
])
def test_broader_hrm_colloquial_queries_hit_agentic_tools(
    model_db,
    question: str,
    intent: str,
    skill: str,
) -> None:
    _seed_broad_hrm_data(model_db)

    result = agentic_runtime.try_run(question, _ctx())

    assert result is not None
    assert result.route_decision.intent == intent
    assert result.trace[0].skill == skill
    assert result.answer['content'] == result.summary
    assert result.widgets or result.entities


def test_attendance_page_context_followup_uses_attendance_tool(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    ctx = _ctx()
    ctx.client_context = {
        'path': '/attendance-stats',
        'moduleId': 'attendance-stats',
        'moduleName': '考勤统计',
        'visibleFilters': {'month': '2026-05'},
    }

    result = agentic_runtime.try_run('就按当前筛选条件，解释为什么统计里没有这些记录', ctx)

    assert result is not None
    assert result.route_decision.intent == 'attendance.stats_context_explain'
    assert result.trace[0].skill == 'attendance_analysis'
    assert result.route_decision.tool_plan[0].input['month'] == '2026-05'
    widget_types = {widget['type'] for widget in result.widgets}
    assert 'source_citations' in widget_types
    assert 'status_badges' in widget_types
    assert '打卡记录 + 已审批' in result.summary


def test_explicit_employee_attendance_question_beats_attendance_page_context(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    ctx = _ctx()
    ctx.client_context = {
        'path': '/attendance-stats',
        'moduleId': 'attendance-stats',
        'moduleName': '考勤统计',
        'visibleFilters': {'month': '2026-05'},
    }

    result = agentic_runtime.try_run('吴明华最近考勤异常吗？请给证据，并说明相关入口。', ctx)

    assert result is not None
    assert result.route_decision.intent == 'attendance.employee.anomaly'
    assert result.trace[0].skill == 'employee_attendance_evidence'
    assert result.route_decision.tool_plan[0].input['keyword'] == '吴明华'
    assert result.entities and result.entities[0]['title'] == '吴明华'
    assert '吴明华' in result.summary
    assert '考勤统计口径为“打卡记录 + 已审批' not in result.summary


def test_job_page_context_followup_uses_recruitment_filter_context(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    ctx = _ctx()
    ctx.client_context = {
        'path': '/job-manage',
        'moduleId': 'job-manage',
        'moduleName': '岗位管理',
        'visibleFilters': {
            'departmentId': 'd-rd',
            'departmentIdLabel': '研发部',
            'status': 'open',
        },
    }

    result = agentic_runtime.try_run('按当前筛选分析岗位缺口和开放岗位数量', ctx)

    assert result is not None
    assert result.route_decision.intent == 'recruitment.page_context'
    assert result.trace[0].skill == 'recruitment_search'
    tool_input = result.route_decision.tool_plan[0].input
    assert tool_input['module'] == 'jobs'
    assert tool_input['keyword'] == '研发部'
    assert tool_input['status'] == 'open'
    assert tool_input['count_only'] is True
    assert result.summary.startswith('当前页面筛选')


def test_salary_page_context_followup_uses_payroll_performance_filters(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import AttendanceRecord, PerformanceCycle, PerformanceReview, SalaryProfile, db

    db.session.add_all([
        PerformanceCycle(
            id='cycle-q2',
            name='2026 Q2 绩效',
            cycle_type='季度',
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            status='active',
        ),
        PerformanceReview(
            id='pr-li',
            employee_id='e-li',
            cycle_id='cycle-q2',
            final_score=59,
            grade='C',
            status='completed',
            created_at=datetime(2026, 5, 20, 9, 0),
        ),
        SalaryProfile(
            id='sp-li',
            employee_id='e-li',
            base_salary=10000,
            position_salary=6000,
            performance_salary=3000,
            status='active',
        ),
        AttendanceRecord(
            id='a-li-late',
            employee_id='e-li',
            attendance_date=date(2026, 5, 21),
            status='late',
        ),
    ])
    db.session.commit()

    ctx = _ctx()
    ctx.client_context = {
        'path': '/salary-profiles',
        'moduleId': 'salary-profiles',
        'moduleName': '薪资档案',
        'visibleFilters': {
            'employeeId': 'e-li',
            'employeeIdLabel': '李研发',
            'cycleId': 'cycle-q2',
            'cycleIdLabel': '2026 Q2 绩效',
        },
    }

    result = agentic_runtime.try_run('按当前筛选解释薪资绩效和考勤风险', ctx)

    assert result is not None
    assert result.route_decision.intent == 'payroll.performance.link'
    assert result.trace[0].skill == 'payroll_performance_link'
    tool_input = result.route_decision.tool_plan[0].input
    assert tool_input['employee_id'] == 'e-li'
    assert tool_input['cycle_id'] == 'cycle-q2'
    assert '李研发' in result.summary or any(entity.get('title') == '李研发' for entity in result.entities)
    assert '薪资' in result.summary


def test_payroll_performance_group_query_is_not_stolen_by_employee_attendance(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import AttendanceRecord, PerformanceCycle, PerformanceReview, SalaryProfile, db

    db.session.add_all([
        PerformanceCycle(
            id='cycle-q2-link',
            name='2026 Q2 绩效',
            cycle_type='季度',
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            status='active',
        ),
        PerformanceReview(
            id='pr-li-low',
            employee_id='e-li',
            cycle_id='cycle-q2-link',
            final_score=62,
            grade='C',
            status='completed',
            created_at=datetime(2026, 5, 22, 9, 0),
        ),
        SalaryProfile(
            id='sp-li-link',
            employee_id='e-li',
            base_salary=10000,
            position_salary=6000,
            performance_salary=3000,
            status='active',
        ),
        AttendanceRecord(
            id='a-li-link-late',
            employee_id='e-li',
            attendance_date=date(2026, 5, 23),
            status='late',
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run('本季度绩效低于B的人，薪资和考勤有没有共同异常？', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'payroll.performance.link'
    assert result.trace[0].skill == 'payroll_performance_link'
    assert result.route_decision.tool_plan[0].input == {'year': 2026, 'quarter': 2}
    assert 'employee_attendance_evidence' not in [step.skill for step in result.trace]
    assert {'metrics', 'bar', 'table', 'source_citations'} <= {widget['type'] for widget in result.widgets}
    assert any(entity.get('title') == '李研发' for entity in result.entities)
    assert '低于 B' in result.summary


def test_employee_profile_connects_requests_approvals_and_notifications(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import ApprovalInstance, EmployeeRequest, Notification, db

    db.session.add_all([
        EmployeeRequest(
            id='req-wmh-leave',
            employee_id='e-wmh',
            request_type='leave',
            title='吴明华请假申请',
            status='approved',
            approval_id='ap-wmh-leave',
            created_by='u-other',
            created_at=datetime(2026, 5, 26, 9, 0),
        ),
        ApprovalInstance(
            id='ap-wmh-leave',
            business_type='employee_request',
            business_id='req-wmh-leave',
            title='吴明华请假审批',
            applicant_id='u-other',
            approver_id='u-agentic',
            status='approved',
            created_at=datetime(2026, 5, 26, 9, 30),
        ),
        Notification(
            id='notice-wmh',
            title='吴明华请假审批已通过',
            content='吴明华请假流程已经归档。',
            notice_type='approval',
            status='unread',
            link_url='/employee-requests',
            created_at=datetime(2026, 5, 26, 10, 0),
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run('给我看吴明华的员工画像，包含考勤、请假审批、异动和通知', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'employee.profile'
    assert result.trace[0].skill == 'employee_evidence_bundle'
    assert '请假/加班/出差/补卡' in result.summary
    assert '关联审批' in result.summary
    widget_types = {widget['type'] for widget in result.widgets}
    assert {'timeline', 'status_badges', 'source_citations'} <= widget_types
    sources = next(widget for widget in result.widgets if widget['type'] == 'source_citations')['sources']
    modules = {source['module'] for source in sources}
    assert {'leave_requests', 'approvals', 'notifications'} <= modules
    by_module = {source['module']: source for source in sources}
    assert {field['key'] for field in by_module['employees']['fields']} >= {
        'employee.employee_no',
        'employee.department',
        'employee.job_title',
    }
    assert {field['key'] for field in by_module['attendance_records']['fields']} >= {
        'attendance.recent_count',
        'attendance.abnormal_count',
    }
    assert 'notifications.latest_title' in {field['key'] for field in by_module['notifications']['fields']}


def test_employee_profile_read_request_beats_employee_action_keywords(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import Employee, SalaryProfile, db

    db.session.add_all([
        Employee(
            id='e-zhangsan-profile',
            employee_no='E2026060003',
            name='张三',
            status='active',
            department_id='d-rd',
            job_title='后端工程师',
            hire_date=date(2026, 5, 10),
        ),
        SalaryProfile(
            id='sp-zhangsan-profile',
            employee_id='e-zhangsan-profile',
            base_salary=16000,
            position_salary=5000,
            performance_salary=3000,
            allowance=800,
            status='active',
        ),
    ])
    db.session.commit()

    result = agentic_runtime.try_run('给我看张三的员工画像，包含考勤、请假审批、绩效、薪资、异动和通知', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'employee.profile'
    assert result.requires_confirmation is False
    assert result.trace[0].skill == 'employee_evidence_bundle'
    assert '请补充目标部门' not in result.summary
    assert '确认执行动作' not in ''.join(action.get('payload', '') for action in result.actions)


def test_lifecycle_chain_question_uses_employee_evidence_not_resume_lookup(model_db) -> None:
    _seed_broad_hrm_data(model_db)
    from models import (
        Candidate, Contract, Employee, Interview, Job, Offer, OnboardingTask, PayrollRecord,
        PerformanceCycle, PerformanceReview, Probation, Resignation, Resume,
        SalaryProfile, TrainingCourse, TrainingRecord, db,
    )

    db.session.add_all([
        Job(id='j-wmh-backend', title='后端工程师', department='研发部', status='open', created_at=datetime(2026, 4, 1, 9, 0)),
        Resume(id='r-wmh-chain', job_id='j-wmh-backend', candidate_name='吴明华', file_url='/uploads/wmh.pdf', created_at=datetime(2026, 4, 2, 9, 0)),
        Candidate(id='c-wmh-chain', resume_id='r-wmh-chain', job_id='j-wmh-backend', name='吴明华', status='converted', created_at=datetime(2026, 4, 3, 9, 0)),
        Interview(id='i-wmh-chain', resume_id='r-wmh-chain', job_id='j-wmh-backend', scheduled_at=datetime(2026, 4, 5, 10, 0), status='completed'),
        Offer(id='offer-wmh-chain', candidate_id='c-wmh-chain', job_id='j-wmh-backend', employee_id='e-wmh', title='吴明华-后端工程师 Offer', status='converted', created_at=datetime(2026, 4, 8, 9, 0)),
        OnboardingTask(id='onboard-wmh-chain', employee_id='e-wmh', name='收集入职材料', status='completed', created_at=datetime(2026, 4, 10, 9, 0)),
        Contract(id='contract-wmh-chain', employee_id='e-wmh', contract_no='HT-WMH-001', contract_type='劳动合同', status='active', created_at=datetime(2026, 4, 12, 9, 0)),
        PerformanceCycle(id='cycle-wmh-chain', name='2026 Q2', cycle_type='季度', status='active'),
        PerformanceReview(id='review-wmh-chain', employee_id='e-wmh', cycle_id='cycle-wmh-chain', final_score=88, grade='B', status='completed', created_at=datetime(2026, 5, 20, 9, 0)),
        SalaryProfile(id='salary-wmh-chain', employee_id='e-wmh', base_salary=12000, position_salary=4000, performance_salary=3000, status='active'),
        PayrollRecord(id='payroll-wmh-chain', employee_id='e-wmh', payroll_month='2026-05', net_salary=18000, status='paid', created_at=datetime(2026, 5, 31, 9, 0)),
        TrainingCourse(id='course-wmh-chain', name='质量效率提升训练营', status='active'),
        TrainingRecord(id='train-wmh-chain', employee_id='e-wmh', course_id='course-wmh-chain', status='completed', result='passed', created_at=datetime(2026, 5, 25, 9, 0)),
        Probation(id='probation-wmh-chain', employee_id='e-wmh', status='approved', result='建议转正', created_at=datetime(2026, 5, 28, 9, 0)),
        Resignation(id='resign-wmh-chain', employee_id='e-wmh', status='approved', reason='个人发展', created_at=datetime(2026, 6, 1, 9, 0)),
    ])
    employee = Employee.query.get('e-wmh')
    employee.candidate_id = 'c-wmh-chain'
    employee.source_offer_id = 'offer-wmh-chain'
    employee.status = 'resigned'
    db.session.commit()

    result = agentic_runtime.try_run('吴明华从简历录入到入职、培训、发薪和离职的完整链路有哪些记录？', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'employee.profile'
    assert result.trace[0].skill == 'employee_evidence_bundle'
    assert len(result.entities) >= 12
    entity_types = {entity['type'] for entity in result.entities}
    assert {
        'employee', 'candidate', 'resume', 'interview', 'offer', 'onboarding_task',
        'contract', 'performance', 'training', 'payroll', 'probation', 'resignation',
    } <= entity_types
    widget_types = {widget['type'] for widget in result.widgets}
    assert {'entity_cards', 'metrics', 'timeline', 'table', 'status_badges', 'source_citations'} <= widget_types
    sources = next(widget for widget in result.widgets if widget['type'] == 'source_citations')['sources']
    source_modules = {source['module'] for source in sources}
    assert {
        'employees', 'candidates', 'resumes', 'jobs', 'interviews', 'offers',
        'onboarding_tasks', 'contracts', 'performance_reviews', 'training_records',
        'salary_profiles', 'payroll_records', 'probations', 'resignations',
    } <= source_modules
    assert '简历' not in result.route_decision.intent


def test_llm_structured_fallback_can_map_unseen_colloquial_text_to_tool(model_db, monkeypatch) -> None:
    _seed_broad_hrm_data(model_db)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'intent': 'attendance.exceptions',
            'domain': 'attendance',
            'tool': 'attendance_analysis',
            'params': {'anomaly_only': True, 'month': '2026-05'},
            'summary_style': 'text',
            'confidence': 0.88,
        }

    monkeypatch.setattr(
        'services.assistant_core.llm_client.json_chat_profile',
        fake_json_chat_profile,
    )

    result = agentic_runtime.try_run('这个月谁打卡不太正常，帮我拎一下', _ctx())

    assert result is not None
    assert result.route_decision.intent == 'attendance.exceptions'
    assert result.trace[0].skill == 'attendance_analysis'
    assert result.route_decision.reason == 'agentic_llm_structured_fallback'
    assert result.widgets
