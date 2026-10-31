"""End-to-end assistant answer-quality regressions.

These cases verify the assistant can answer common real business questions
against actual seeded data, not merely choose a plausible route/tool.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from services.assistant_core import legacy_orchestrator as orchestrator
from services.assistant_core.schemas import AssistantContext, RouteDecision, ToolCallPlan


def _ctx() -> AssistantContext:
    return AssistantContext(
        user_id='u-real-answer',
        role='hr_admin',
        session_id='s-real-answer',
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
        monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda *args, **kwargs: 's-real-answer')
        monkeypatch.setattr(orchestrator.workset_store, 'create_workset_from_entities', lambda *args, **kwargs: None)
        monkeypatch.setattr(
            'services.assistant_core.intent_router.legacy_planner.business_now',
            lambda: datetime(2026, 5, 29, 9, 0, 0),
            raising=False,
        )
        monkeypatch.setattr(
            'services.assistant_core.orchestrator.business_now',
            lambda: datetime(2026, 5, 29, 9, 0, 0),
            raising=False,
        )
        yield db
        db.session.remove()
        db.drop_all()


def _seed_recruitment_data(db) -> None:
    from models import Candidate, Interview, Job, Resume

    jobs = [
        Job(id='j-electronic', title='电子工程师', department='研发部', status='open', created_at=datetime(2026, 5, 20, 9, 0)),
        Job(id='j-product', title='产品经理', department='产品部', status='open', created_at=datetime(2026, 5, 21, 9, 0)),
        Job(id='j-closed', title='行政专员', department='行政部', status='closed', created_at=datetime(2026, 5, 1, 9, 0)),
    ]
    resumes = [
        Resume(id='r-1', job_id='j-electronic', candidate_name='胡国卫', file_url='/uploads/hu.pdf', created_at=datetime(2026, 5, 25, 9, 0)),
        Resume(id='r-2', job_id='j-electronic', candidate_name='李博豪', file_url='/uploads/li.pdf', created_at=datetime(2026, 5, 26, 9, 0)),
        Resume(id='r-3', job_id='j-product', candidate_name='王产品', file_url='/uploads/wang.pdf', created_at=datetime(2026, 5, 27, 9, 0)),
    ]
    candidates = [
        Candidate(id='c-1', resume_id='r-1', job_id='j-electronic', name='胡国卫', status='screening', created_at=datetime(2026, 5, 25, 10, 0)),
        Candidate(id='c-2', resume_id='r-2', job_id='j-electronic', name='李博豪', status='screening', created_at=datetime(2026, 5, 26, 10, 0)),
        Candidate(id='c-3', resume_id='r-3', job_id='j-product', name='王产品', status='interview', created_at=datetime(2026, 5, 27, 10, 0)),
    ]
    interviews = [
        Interview(id='i-1', resume_id='r-1', job_id='j-electronic', scheduled_at=datetime(2026, 5, 30, 8, 0), status='scheduled'),
        Interview(id='i-2', resume_id='r-2', job_id='j-electronic', scheduled_at=datetime(2026, 5, 30, 10, 0), status='scheduled'),
        Interview(id='i-3', resume_id='r-3', job_id='j-product', scheduled_at=datetime(2026, 5, 31, 10, 0), status='scheduled'),
    ]
    db.session.add_all(jobs + resumes + candidates + interviews)
    db.session.commit()


def _seed_operational_data(db) -> None:
    from models import (
        ApprovalInstance, AttendanceRecord, Department, Employee, Feedback,
        PayrollRecord, PerformanceCycle, PerformanceReview, TrainingCourse,
        TrainingPlan, TrainingRecord, User,
    )

    users = [
        User(id='u-real-answer', email='hr@example.com', password_hash='x', name='HR Admin', role='hr_admin'),
        User(id='u-approver', email='manager@example.com', password_hash='x', name='审批主管', role='manager'),
        User(id='u-applicant', email='employee@example.com', password_hash='x', name='申请员工', role='employee'),
    ]
    departments = [
        Department(id='dep-rd', name='研发部', code='RD'),
        Department(id='dep-sales', name='销售部', code='SALES'),
    ]
    employees = [
        Employee(id='emp-1', employee_no='E001', name='张三', department_id='dep-rd', job_title='工程师', status='active'),
        Employee(id='emp-2', employee_no='E002', name='李四', department_id='dep-rd', job_title='测试工程师', status='active'),
        Employee(id='emp-3', employee_no='E003', name='王五', department_id='dep-sales', job_title='销售经理', status='active'),
    ]
    attendance_records = [
        AttendanceRecord(id='att-1', employee_id='emp-1', attendance_date=date(2026, 5, 6), status='normal', work_hours=Decimal('8.00')),
        AttendanceRecord(id='att-2', employee_id='emp-1', attendance_date=date(2026, 5, 7), status='late', work_hours=Decimal('8.00')),
        AttendanceRecord(id='att-3', employee_id='emp-2', attendance_date=date(2026, 5, 7), status='missing_card'),
        AttendanceRecord(id='att-4', employee_id='emp-3', attendance_date=date(2026, 5, 7), status='leave'),
        AttendanceRecord(id='att-5', employee_id='emp-2', attendance_date=date(2026, 4, 30), status='late'),
    ]
    payroll_records = [
        PayrollRecord(
            id='pay-1', employee_id='emp-1', payroll_month='2026-05',
            gross_salary=Decimal('15000.00'), net_salary=Decimal('13200.00'),
            deduction=Decimal('1800.00'), status='calculated',
        ),
        PayrollRecord(
            id='pay-2', employee_id='emp-2', payroll_month='2026-05',
            gross_salary=Decimal('12000.00'), net_salary=Decimal('10600.00'),
            deduction=Decimal('1400.00'), status='calculated',
        ),
        PayrollRecord(
            id='pay-3', employee_id='emp-3', payroll_month='2026-05',
            gross_salary=Decimal('18000.00'), net_salary=Decimal('15800.00'),
            deduction=Decimal('2200.00'), status='calculated',
        ),
        PayrollRecord(
            id='pay-4', employee_id='emp-1', payroll_month='2026-04',
            gross_salary=Decimal('14000.00'), net_salary=Decimal('12300.00'),
            deduction=Decimal('1700.00'), status='paid',
        ),
    ]
    performance_cycle = PerformanceCycle(
        id='cycle-2026-q2', name='2026 Q2 绩效', cycle_type='季度',
        start_date=date(2026, 4, 1), end_date=date(2026, 6, 30), status='active',
    )
    reviews = [
        PerformanceReview(
            id='perf-1', employee_id='emp-1', cycle_id='cycle-2026-q2',
            final_score=Decimal('92.00'), grade='A', status='completed',
        ),
        PerformanceReview(
            id='perf-2', employee_id='emp-2', cycle_id='cycle-2026-q2',
            final_score=Decimal('81.00'), grade='B', status='completed',
        ),
        PerformanceReview(
            id='perf-3', employee_id='emp-3', cycle_id='cycle-2026-q2',
            final_score=Decimal('59.00'), grade='C', status='draft',
        ),
    ]
    courses = [
        TrainingCourse(id='course-safe', name='安全培训', category='合规', status='active'),
        TrainingCourse(id='course-leader', name='管理者训练营', category='管理', status='active'),
    ]
    plans = [
        TrainingPlan(
            id='plan-safe', name='5月安全培训', course_id='course-safe',
            start_time=datetime(2026, 5, 10, 9, 0), status='running',
        ),
        TrainingPlan(
            id='plan-leader', name='Q2 管理训练营', course_id='course-leader',
            start_time=datetime(2026, 5, 15, 9, 0), status='planned',
        ),
    ]
    training_records = [
        TrainingRecord(id='tr-1', plan_id='plan-safe', course_id='course-safe', employee_id='emp-1', status='completed', score=Decimal('95.00')),
        TrainingRecord(id='tr-2', plan_id='plan-safe', course_id='course-safe', employee_id='emp-2', status='passed', score=Decimal('88.00')),
        TrainingRecord(id='tr-3', plan_id='plan-safe', course_id='course-safe', employee_id='emp-3', status='registered'),
        TrainingRecord(id='tr-4', plan_id='plan-leader', course_id='course-leader', employee_id='emp-3', status='registered'),
    ]
    approvals = [
        ApprovalInstance(
            id='appr-1', business_type='leave', business_id='leave-1',
            title='张三请假申请', applicant_id='u-applicant', approver_id='u-real-answer',
            status='pending', created_at=datetime(2026, 5, 20, 9, 0),
        ),
        ApprovalInstance(
            id='appr-2', business_type='overtime', business_id='ot-1',
            title='李四加班申请', applicant_id='u-applicant', approver_id='u-real-answer',
            status='pending', created_at=datetime(2026, 5, 21, 9, 0),
        ),
        ApprovalInstance(
            id='appr-3', business_type='expense', business_id='exp-1',
            title='王五报销申请', applicant_id='u-applicant', approver_id='u-approver',
            status='approved', created_at=datetime(2026, 5, 18, 9, 0),
        ),
    ]
    feedbacks = [
        Feedback(id='fb-1', user_id='u-applicant', feedback_type='bug', severity='high', title='登录异常', content='偶发登录失败', status='pending'),
        Feedback(id='fb-2', user_id='u-applicant', feedback_type='feature', severity='medium', title='增加导出', content='需要工资条导出', status='pending'),
        Feedback(id='fb-3', user_id='u-applicant', feedback_type='bug', severity='medium', title='列表错位', content='表格在小屏错位', status='in_progress'),
        Feedback(id='fb-4', user_id='u-applicant', feedback_type='other', severity='low', title='文案优化', content='提示更清晰', status='resolved'),
    ]
    db.session.add_all(
        users + departments + employees + attendance_records + payroll_records
        + [performance_cycle] + reviews + courses + plans + training_records + approvals + feedbacks
    )
    db.session.commit()


def _first_plan_input(result):
    return result.route_decision.tool_plan[0].input


@pytest.mark.parametrize(
    ('question', 'module', 'expected_total', 'forbidden_keywords'),
    [
        ('我们现在有多少候选人', 'candidates', 3, {'我们现在有多少', '我们'}),
        ('我们现在有多少份简历', 'resumes', 3, {'我们', '份'}),
        ('明天有多少场面试', 'interviews', 2, {'场'}),
    ],
)
def test_recruitment_count_questions_answer_from_data_without_noise_keyword(
    model_db,
    question: str,
    module: str,
    expected_total: int,
    forbidden_keywords: set[str],
) -> None:
    _seed_recruitment_data(model_db)

    result = orchestrator.run(question, _ctx())

    assert result.route_decision.route_track == 'A_DATA_ACTION'
    assert result.route_decision.tool_plan[0].tool == 'recruitment_search'
    params = _first_plan_input(result)
    assert params['module'] == module
    assert params.get('count_only') is True
    assert params.get('keyword') not in forbidden_keywords
    assert 'keyword' not in params or params['keyword']
    assert result.trace[0].rows_count == expected_total
    assert f'{expected_total}' in result.summary
    assert result.widgets


def test_open_job_list_question_returns_open_jobs_not_noise_filtered(model_db) -> None:
    _seed_recruitment_data(model_db)

    result = orchestrator.run('我们现在有哪些岗位在招人', _ctx())

    params = _first_plan_input(result)
    assert params['module'] == 'jobs'
    assert params.get('status') == 'open'
    assert 'keyword' not in params
    assert result.trace[0].rows_count == 2
    assert {entity['title'] for entity in result.entities} == {'电子工程师', '产品经理'}
    assert '目前有 2 个招聘中的岗位' in result.summary


def test_job_specific_question_keeps_real_job_title_keyword(model_db) -> None:
    _seed_recruitment_data(model_db)

    result = orchestrator.run('电子工程师的岗位在招人吗', _ctx())

    params = _first_plan_input(result)
    assert params['module'] == 'jobs'
    assert params.get('status') == 'open'
    assert params.get('keyword') == '电子工程师'
    assert result.trace[0].rows_count == 1
    assert result.entities[0]['title'] == '电子工程师'


def test_open_job_count_question_does_not_keep_normalized_query_noise(model_db) -> None:
    _seed_recruitment_data(model_db)

    result = orchestrator.run('我们现在有多少个岗位在招人', _ctx())

    params = _first_plan_input(result)
    assert params['module'] == 'jobs'
    assert params.get('status') == 'open'
    assert params.get('count_only') is True
    assert 'keyword' not in params
    assert result.trace[0].rows_count == 2
    assert '目前有 2 个招聘中的岗位' in result.summary


def test_recruitment_progress_uses_multiple_domain_queries_and_natural_summary(model_db) -> None:
    _seed_recruitment_data(model_db)

    decision = RouteDecision(
        task_type='data_query',
        route_track='A_DATA_ACTION',
        intent='recruitment_progress',
        confidence=0.95,
        tool_plan=[
            ToolCallPlan(
                step_id='job',
                tool='recruitment_search',
                input={'module': 'jobs', 'keyword': '电子工程师', 'status': 'open', 'limit': 10},
            ),
            ToolCallPlan(
                step_id='candidates',
                tool='recruitment_search',
                input={'module': 'candidates', 'keyword': '电子工程师', 'count_only': True, 'limit': 20},
            ),
            ToolCallPlan(
                step_id='resumes',
                tool='recruitment_search',
                input={'module': 'resumes', 'keyword': '电子工程师', 'count_only': True, 'limit': 20},
            ),
            ToolCallPlan(
                step_id='interviews',
                tool='recruitment_search',
                input={'module': 'interviews', 'keyword': '电子工程师', 'count_only': True, 'limit': 20},
            ),
        ],
    )

    result = orchestrator._execute_direct_tool_track('帮我看一下电子工程师招聘的怎么样了', _ctx(), decision)

    assert [step.skill for step in result.trace] == ['recruitment_search'] * 4
    assert '电子工程师招聘目前是开放状态' in result.summary
    assert '候选人 2 人' in result.summary
    assert '简历 2 份' in result.summary
    assert '面试 2 场' in result.summary


def test_recruitment_progress_question_runs_multi_query_from_real_message(model_db) -> None:
    _seed_recruitment_data(model_db)

    result = orchestrator.run('帮我看一下电子工程师招聘的怎么样了', _ctx())

    assert [plan.tool for plan in result.route_decision.tool_plan] == ['recruitment_search'] * 4
    assert [plan.input['module'] for plan in result.route_decision.tool_plan] == [
        'jobs',
        'candidates',
        'resumes',
        'interviews',
    ]
    assert '电子工程师招聘目前是开放状态' in result.summary
    assert '候选人 2 人' in result.summary
    assert '简历 2 份' in result.summary
    assert '面试 2 场' in result.summary


def test_module_catalog_question_answers_from_shared_catalog(model_db) -> None:
    result = orchestrator.run('这个 HRM 系统有哪些模块？按业务链路说明一下', _ctx())

    assert result.route_decision.reason == 'direct_module_catalog_plan'
    assert result.route_decision.tool_plan[0].tool == 'system_search'
    assert result.route_decision.tool_plan[0].input == {'module': 'module_catalog', 'view': 'overview'}
    assert result.trace[0].rows_count == 36
    assert '系统共覆盖 36 个 HRM 模块' in result.summary
    assert '招聘到入职：岗位管理 -> 简历管理 -> 候选人管理 -> 面试管理 -> Offer管理 -> 员工档案 -> 入职管理 -> 合同管理' in result.summary
    assert '考勤到薪酬：考勤记录 -> 考勤统计 -> 请假/加班/出差/补卡 -> 薪资档案 -> 工资条' in result.summary


def test_offer_flow_question_explains_upstream_and_downstream_modules(model_db) -> None:
    result = orchestrator.run('Offer管理和入职管理、员工档案之间怎么连通？', _ctx())

    assert result.route_decision.reason == 'direct_module_catalog_plan'
    assert result.route_decision.tool_plan[0].input == {
        'module': 'module_catalog',
        'view': 'module',
        'module_id': 'offers',
    }
    assert result.trace[0].rows_count == 1
    assert 'Offer管理位于招聘管理' in result.summary
    assert '上游：候选人管理、面试管理' in result.summary
    assert '下游：员工档案、入职管理、薪资档案' in result.summary
    assert 'candidate_to_employee' in result.summary


def test_model_settings_query_lists_configuration_without_tail_noise(model_db) -> None:
    from models import Setting

    model_db.session.add(Setting(key='companyName', value='恒聘通智能HRM'))
    model_db.session.add(Setting(
        key='assistantModelSettings',
        value={
            'provider': 'siliconflow',
            'smallModel': 'deepseek-ai/DeepSeek-V4-Pro',
            'standardModel': 'deepseek-ai/DeepSeek-V4-Pro',
            'strongModel': 'deepseek-ai/DeepSeek-V4-Pro',
        },
    ))
    model_db.session.commit()

    result = orchestrator.run('AI 模型管理现在有哪些模型配置？给我证据和入口', _ctx())

    assert result.route_decision.reason == 'direct_nav_module_plan'
    assert result.route_decision.tool_plan[0].tool == 'system_search'
    assert result.route_decision.tool_plan[0].input == {'module': 'model_settings', 'limit': 10}
    assert result.trace[0].rows_count == 1
    assert 'assistantModelSettings' in result.summary
    assert 'companyName' not in result.summary
    assert any(entity.get('type') == 'model_setting' and entity.get('url') == '/ai-model-settings' for entity in result.entities)
    assert not any(entity.get('id') == 'companyName' for entity in result.entities)
    assert any(widget.get('type') == 'table' for widget in result.widgets)
    sources = [
        source
        for widget in result.widgets
        if widget.get('type') == 'source_citations'
        for source in widget.get('sources') or []
    ]
    assert any(source.get('module') == 'system_settings' and source.get('url') == '/ai-model-settings' for source in sources)


@pytest.mark.parametrize(
    ('question', 'tool', 'expected_rows', 'expected_summary_parts', 'expected_field_modules'),
    [
        ('2026-05 考勤异常情况', 'attendance_analysis', 4, ['2026-05', '4 条考勤记录', '异常 3 次', '正常 1 次'], {'attendance_records', 'leave_requests', 'employees'}),
        ('2026-05 工资条汇总', 'payroll_analysis', 3, ['2026-05薪酬汇总', '3 条工资条', '应发合计 45,000 元', '实发合计 39,600 元', '敏感信息'], {'payroll_records', 'employees'}),
        ('绩效评估分布怎么样', 'performance_analysis', 3, ['3 条绩效评估', '已完成 2 条', 'A 1 人', 'B 1 人', 'C 1 人'], {'performance_reviews', 'employees'}),
        ('培训完成率是多少', 'training_analysis', 4, ['2 门课程', '2 个培训计划', '培训记录 4 条', '已完成 2 条', '完成率 50.0%'], {'training_courses', 'training_plans', 'training_records', 'employees'}),
        ('待我审批有哪些', 'approval_search', 2, ['待我审批共有 2 条记录', '不会自动审批'], {'approvals'}),
        ('待处理反馈有多少', 'feedback_triage', 2, ['当前共有 4 条反馈', '待处理 2 条', '处理中 1 条', '已解决 1 条'], {'feedback'}),
    ],
)
def test_operational_questions_answer_from_real_data_with_business_summary(
    model_db,
    question: str,
    tool: str,
    expected_rows: int,
    expected_summary_parts: list[str],
    expected_field_modules: set[str],
) -> None:
    _seed_operational_data(model_db)

    result = orchestrator.run(question, _ctx())

    assert result.route_decision.route_track == 'A_DATA_ACTION'
    assert result.trace[0].skill == tool
    assert result.trace[0].rows_count == expected_rows
    assert result.widgets
    for part in expected_summary_parts:
        assert part in result.summary
    sources = [
        source
        for widget in result.widgets
        if widget.get('type') == 'source_citations'
        for source in widget.get('sources') or []
    ]
    sources_with_fields = {
        source.get('module')
        for source in sources
        if source.get('fields')
    }
    assert expected_field_modules <= sources_with_fields
    assert sum(len(source.get('fields') or []) for source in sources) >= len(expected_field_modules) * 2

