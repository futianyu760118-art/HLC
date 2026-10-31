"""Natural-language acceptance matrix for the Skill-first assistant.

These cases model the current product goal: keep testing the assistant with
plain Chinese single-turn and follow-up requests across HRM modules, then turn
every bug into a regression case before optimizing routing again.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from flask import Flask

from services.assistant_core.schemas import AssistantContext
from services.assistant_core.skill_first import semantic_index


def _ctx(
    session_id: str = 's-natural-language-matrix',
    role: str = 'hr_admin',
    user_id: str = 'u-natural-language-matrix',
) -> AssistantContext:
    return AssistantContext(user_id=user_id, role=role, session_id=session_id, request_id='req-natural-language-matrix')


@pytest.fixture()
def model_db():
    from models import User, db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(User(
            id='u-natural-language-matrix',
            email='nl-matrix@example.com',
            password_hash='x',
            name='Natural Language Matrix HR',
            role='hr_admin',
        ))
        db.session.commit()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize(
    ('question', 'expected_skill'),
    [
        ('这个页面你能干嘛', 'system.page_capability'),
        ('怎么创建候选人跟进任务？', 'system.workflow_help'),
        ('如何新增岗位', 'system.workflow_help'),
        ('面试安排流程说明', 'system.workflow_help'),
        ('最近招聘整体咋样', 'recruitment.overview'),
        ('现在还在招的岗位有哪些', 'recruitment.open_jobs'),
        ('电子工程师这个岗位进展到哪了', 'recruitment.job_progress'),
        ('招聘漏斗现在卡在哪一段', 'recruitment.funnel'),
        ('电子工程师岗位匹配哪些候选人', 'recruitment.job_candidate_match'),
        ('候选人里找一下孙悦', 'candidate.search'),
        ('最近10天我们收到了哪些简历', 'candidate.recent_resumes'),
        ('孙悦的简历帮我找一下', 'candidate.resume_analysis'),
        ('这个人靠不靠谱', 'candidate.evaluation'),
        ('对比上面两个候选人', 'candidate.compare'),
        ('候选人和岗位匹配矩阵给我看下', 'candidate.match_matrix'),
        ('这批候选人先约谁比较稳', 'interview.suggestion'),
        ('邓浩的面试记录查一下', 'interview.records'),
        ('先出一版面试邀请文案，不要直接创建', 'interview.schedule_draft'),
        ('给第二个安排面试', 'interview.schedule_confirm_create'),
        ('Offer 和入职最近推进怎么样', 'offer.onboarding_progress'),
        ('员工里找一下吴明华', 'employee.search'),
        ('吴明华这个员工最近状态如何', 'employee.profile'),
        ('公司组织现在什么情况', 'organization.overview'),
        ('这个员工从入职到现在的生命周期链路看下', 'employee.lifecycle_chain'),
        ('离职风险高的人有哪些', 'employee.attrition_risk'),
        ('如果把吴明华调到研发部会影响什么', 'employee.change_impact'),
        ('把吴明华调到研发部准备提交审批', 'employee.change_submit_confirm'),
        ('这个月考勤总体怎么样', 'attendance.overview'),
        ('这个月谁打卡不太正常', 'attendance.anomaly'),
        ('吴明华这个月考勤证据给我看下', 'attendance.employee_evidence'),
        ('给迟到多的人写个提醒草稿', 'attendance.reminder_draft'),
        ('帮我给本月迟到最多的5个人生成提醒', 'attendance.reminder_confirm'),
        ('最近考勤趋势怎么样', 'attendance.trend'),
        ('绩效分布怎么样', 'performance.distribution'),
        ('绩效哪里不正常', 'performance.anomaly'),
        ('低绩效员工画像看看', 'performance.employee_link'),
        ('这个月工资总额多少', 'payroll.summary'),
        ('工资这块有没有啥异常', 'payroll.anomaly'),
        ('我自己的工资条呢', 'payroll.employee_self_service'),
        ('低绩效这批人的工资和考勤有没有共同问题', 'payroll.performance_link'),
        ('给吴明华调薪 1800 元，先分析影响并准备确认', 'employee.salary_adjustment_submit_confirm'),
        ('我这边还有哪些待办审批', 'approval.todo'),
        ('我的申请现在走到哪了', 'approval.mine'),
        ('之前处理过的审批给我看下', 'approval.history'),
        ('同意第一条请假申请', 'approval.confirm_action'),
        ('用户最近主要在吐槽什么', 'feedback.summary'),
        ('还有什么系统 bug 没修', 'feedback.bug_todo'),
        ('给全员推一条 HR 通知：明天培训', 'notification.create_confirm'),
        ('创建跟进任务：明天提醒我联系候选人吴明华', 'task.followup_create_confirm'),
        ('系统经营报表看一下', 'report.operations'),
        ('上面那批里谁最合适', 'workset.analysis'),
        ('低绩效和考勤异常交叉统计一下', 'smart.data_query'),
    ],
)
def test_single_turn_natural_language_recall_covers_all_hrm_modules(question: str, expected_skill: str) -> None:
    recalled = semantic_index.recall_skills(question, top_k=16)

    assert recalled, question
    assert expected_skill in [item.skill_id for item in recalled], question


@pytest.mark.parametrize(
    'question',
    [
        '把邓浩的面试删除',
        '把邓浩的面试时间改成明天早晨9点',
        '新增一个岗位：AI 工程师',
        '删除电子工程师这个岗位',
        '把电子工程师岗位 JD 改一下',
        '录入一个候选人孙悦',
        '删除候选人孙悦',
        '把孙悦候选人状态改成淘汰',
        '上传一份孙悦的新简历',
        '删除孙悦的简历',
        '给孙悦创建 Offer',
        '把孙悦 Offer 薪资改成 20000',
        '删除孙悦的 Offer 记录',
        '添加员工吴明华',
        '删除员工吴明华',
        '把吴明华手机号改成 13800000000',
        '新增一个部门：增长部',
        '删除研发部',
        '新增一条考勤记录',
        '把吴明华昨天打卡时间改成 9 点',
        '删除考勤记录',
        '新增绩效评估',
        '把吴明华绩效改成 A',
        '删除绩效记录',
        '新增工资条',
        '编辑吴明华工资为 20000',
        '删除工资条',
        '把工资条记录直接更新一下',
        '删除审批记录',
        '把所有审批都通过',
        '删除用户反馈',
        '把反馈状态改成已处理',
        '删除通知',
        '把系统设置改成关闭审计',
        '清除操作日志',
    ],
)
def test_unsupported_update_and_delete_requests_are_blocked_by_runtime(question: str, monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    calls: list[str] = []

    def fake_execute(self, tool, params, ctx):
        calls.append(tool)
        return {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '不应执行任何业务工具。', 'entities': [], 'widgets': []},
            'rows_count': 0,
        }

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run(question, _ctx())

    assert result is not None
    assert result.error_code == 'write_intent_blocked'
    assert result.route_decision is not None
    assert result.route_decision.task_type == 'forbidden'
    assert not getattr(result, '_pending_action', None)
    assert calls == []


@pytest.mark.parametrize(
    'question',
    [
        '岗位怎么新增？',
        '候选人怎么录入？',
        '简历上传流程说明',
        'Offer 创建前为什么要确认？',
        '员工调岗流程说明',
        '考勤补卡怎么申请？',
        '绩效评分修改流程说明',
        '工资条创建流程说明',
        '审批驳回怎么操作？',
        '反馈状态怎么修改？',
        '通知删除应该怎么操作？',
    ],
)
def test_workflow_help_across_modules_is_readonly(question: str, monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run(question, _ctx())

    assert result is not None
    assert result.error_code is None
    assert result.requires_confirmation is False
    assert result.copilot['routeTrace']['selected_skill'] == 'system.workflow_help'
    assert result.route_decision is not None
    assert result.route_decision.task_type == 'data_query'
    assert result.route_decision.tool_plan[0].tool == 'system_search'
    assert result.route_decision.tool_plan[0].input['module'] == 'module_catalog'


def test_supported_create_like_requests_generate_pending_actions_not_writes(model_db, monkeypatch) -> None:
    from models import Notification
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('给全员推一条 HR 通知：明天下午三点全员培训', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'notification.create_confirm'
    assert getattr(result, '_pending_action')['tools'][0]['tool'] == 'notification_create'
    assert Notification.query.count() == 0


def test_newly_added_records_question_is_readonly_but_create_command_is_blocked(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    calls: list[tuple[str, dict]] = []

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, dict(params)))
        return {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '本月新增招聘岗位 2 个。', 'entities': [], 'widgets': []},
            'rows_count': 2,
        }

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    query_result = runtime.try_run('本月新增了哪些招聘岗位', _ctx())
    blocked_result = runtime.try_run('新增一个岗位：AI 工程师', _ctx())

    assert query_result is not None
    assert query_result.error_code is None
    assert query_result.route_decision is not None
    assert query_result.route_decision.task_type == 'data_query'
    assert calls
    assert blocked_result is not None
    assert blocked_result.error_code == 'write_intent_blocked'


def test_workflow_help_questions_are_readonly_and_not_write_blocked(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('怎么创建候选人跟进任务？', _ctx())

    assert result is not None
    assert result.error_code is None
    assert result.requires_confirmation is False
    assert result.copilot['routeTrace']['selected_skill'] == 'system.workflow_help'
    assert result.route_decision is not None
    assert result.route_decision.task_type == 'data_query'
    assert result.route_decision.tool_plan[0].tool == 'system_search'
    assert result.route_decision.tool_plan[0].input['module'] == 'module_catalog'


def test_followup_task_create_is_pending_confirmation_not_direct_write(model_db, monkeypatch) -> None:
    from models import Notification
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('创建跟进任务：明天提醒我联系候选人吴明华', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'task.followup_create_confirm'
    assert getattr(result, '_pending_action')['tools'][0]['tool'] == 'followup_task_create'
    assert Notification.query.count() == 0


def test_multi_turn_approval_followup_resolves_second_item_without_writing(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, ApprovalRecord, db
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.workset_store import default_store

    default_store.clear()
    now = datetime.utcnow()
    db.session.add_all([
        ApprovalInstance(
            id='ap-newer',
            business_type='employee_request',
            business_id='leave-newer',
            title='吴明华请假申请',
            applicant_id='u-other',
            approver_id='u-natural-language-matrix',
            status='pending',
            created_at=now,
        ),
        ApprovalInstance(
            id='ap-older',
            business_type='employee_request',
            business_id='expense-older',
            title='李雷报销申请',
            applicant_id='u-other',
            approver_id='u-natural-language-matrix',
            status='pending',
            created_at=now - timedelta(days=1),
        ),
    ])
    db.session.commit()
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    first = runtime.try_run('我这边还有哪些待办审批', _ctx())
    followup = runtime.try_run('把第二条驳回，意见：材料不完整', _ctx())

    assert first is not None
    assert first.copilot['routeTrace']['selected_skill'] == 'approval.todo'
    assert followup is not None
    assert followup.requires_confirmation is True
    assert followup.copilot['routeTrace']['selected_skill'] == 'approval.confirm_action'
    assert getattr(followup, '_pending_action')['tools'][0]['input'] == {
        'approval_id': 'ap-older',
        'action': 'reject',
        'comment': '材料不完整',
    }
    assert ApprovalInstance.query.get('ap-older').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-older').count() == 0


def test_multi_turn_approval_followup_understands_colloquial_approve(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, ApprovalRecord, db
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.workset_store import default_store

    default_store.clear()
    now = datetime.utcnow()
    db.session.add_all([
        ApprovalInstance(
            id='ap-colloquial-newer',
            business_type='employee_request',
            business_id='leave-colloquial-newer',
            title='吴明华请假申请',
            applicant_id='u-other',
            approver_id='u-natural-language-matrix',
            status='pending',
            created_at=now,
        ),
        ApprovalInstance(
            id='ap-colloquial-older',
            business_type='employee_request',
            business_id='expense-colloquial-older',
            title='李雷报销申请',
            applicant_id='u-other',
            approver_id='u-natural-language-matrix',
            status='pending',
            created_at=now - timedelta(days=1),
        ),
    ])
    db.session.commit()
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    first = runtime.try_run('我这边还有哪些待办审批', _ctx(session_id='s-natural-language-approval-approve'))
    followup = runtime.try_run('把第二条过了吧，备注资料补齐', _ctx(session_id='s-natural-language-approval-approve'))

    assert first is not None
    assert first.copilot['routeTrace']['selected_skill'] == 'approval.todo'
    assert followup is not None
    assert followup.requires_confirmation is True
    assert followup.copilot['routeTrace']['selected_skill'] == 'approval.confirm_action'
    assert getattr(followup, '_pending_action')['tools'][0]['input'] == {
        'approval_id': 'ap-colloquial-older',
        'action': 'approve',
        'comment': '资料补齐',
    }
    assert ApprovalInstance.query.get('ap-colloquial-older').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-colloquial-older').count() == 0
