"""Confirmed action cases for the assistant.

Module 8 verifies business writes are never executed directly: interview
creation and follow-up task creation must first produce confirmation cards,
and only an explicit confirmation turn may execute whitelisted pending tools.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core import legacy_orchestrator as orchestrator
from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(session_id: str = 'sess-confirmed-actions') -> AssistantContext:
    return AssistantContext(user_id='u-confirmed-actions', role='hr_admin', session_id=session_id)


@dataclass(frozen=True)
class ActionRouteCase:
    message: str
    intent: str
    tool: str
    required_context: str | None = None


INTERVIEW_ACTION_CASES = [
    ActionRouteCase('给吴明华安排明天下午三点面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮吴明华安排明天下午三点初面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给张三约明天上午十点面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮李四预约明天下午两点复试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('为王芳发起明天 10:00 面试安排', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('创建候选人赵磊明天 15:00 的二面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('新建周敏后天下午三点终面安排', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('把陈晨安排到 2026-05-29 16:00 面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮刘洋约 2026-05-30 09:30 复试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给候选人孙悦安排明天上午九点技术面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给候选人郑伟安排明天下午四点 HR 面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('请给唐佳创建明天 11:00 的面试安排', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮胡静新建明天两点复试记录', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给高强安排下周一上午十点面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('约马超明天下午三点视频面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('安排候选人何娜明天上午十点一面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('创建候选人许琳 2026-05-29 14:00 复试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给第一个候选人安排明天下午三点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给第二位安排明天上午十点复试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给前三名安排明天下午三点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给排名前三的候选人安排明天 15:00 复试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给刚才那批候选人安排明天上午十点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('把上面这些候选人安排到明天下午三点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给这几位候选人新建明天 10:00 复试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给列表里前二安排明天上午十点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给最推荐的人安排明天下午三点面试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('请安排吴明华后天上午十点一面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给林峰约下周二下午两点技术面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮候选人周杰预约后天 14:30 视频面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('为钱敏创建下周三上午九点 HR 面', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给赵倩发起 2026-06-01 10:30 终面安排', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('约候选人冯雷明天下午五点复试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('帮杨柳新建后天上午十点面试', 'interview_schedule', 'interview_create', 'named_subject_evidence'),
    ActionRouteCase('给第三位候选人安排后天 15:00 技术面', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给这些人预约下周一下午两点复试', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('把刚才筛出来的前 3 位安排到明天一面', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给列表里的候选人创建后天上午九点面试安排', 'interview_schedule', 'interview_create', 'latest_workset'),
    ActionRouteCase('给上面第一位约明天下午三点 HR 面', 'interview_schedule', 'interview_create', 'latest_workset'),
]


FOLLOWUP_ACTION_CASES = [
    ActionRouteCase('创建跟进任务：明天提醒我联系候选人吴明华', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('明天提醒我跟进张三', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('新建待办：明天跟进 Offer 审批', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我创建一个下周一回访候选人的提醒', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('安排一个明天上午十点的跟进提醒', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('新建任务：下午联系李四确认入职材料', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('创建提醒：明天催王芳补充简历附件', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我建一个任务，后天跟进销售经理候选人', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('加个待办：明天确认二面反馈', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('添加提醒，周五跟进薪酬审批进度', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('设个提醒明早联系赵磊', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('提醒我明天下午给候选人发资料清单', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我安排一个跟进任务，明天看 Offer 是否确认', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('创建个人待办：复盘今天的面试反馈', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('新建跟进任务，明天找面试官要评价', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我创建提醒，三天后跟进培训报名', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('安排待办：本周五检查合同续签名单', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('创建任务提醒我明天处理审批待办', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('给这批候选人创建明天跟进任务', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给刚才那批候选人安排跟进提醒', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给第二位创建跟进任务', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给排名前三创建跟进任务', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给上面这些人新建跟进提醒', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给列表里的前二安排跟进任务', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('创建待办：明天复核面试官评价', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('新建个人待办：下周一检查 Offer 归档', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('添加任务：下午整理候选人沟通纪要', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('设个待办：明早确认入职资料是否齐全', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我创建任务，周五复盘招聘渠道效果', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('安排提醒：后天查看试用期反馈', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('创建个人待办：明天检查培训签到表', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('新建提醒：三天后确认合同签署结果', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('提醒我下周二给部门负责人发面试反馈表', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('帮我建个待办：明天下午复核候选人背调材料', 'followup_task_create', 'followup_task_create'),
    ActionRouteCase('给第一个人创建明天电话回访任务', 'followup_task_create', 'followup_task_create', 'latest_workset'),
    ActionRouteCase('给这些候选人添加下周一跟进提醒', 'followup_task_create', 'followup_task_create', 'latest_workset'),
]


BOUNDARY_CASES = [
    '查一下明天的面试安排',
    '查看候选人吴明华的面试记录',
    '帮我生成 8 道 Java 面试题',
    '如何安排一次结构化面试？',
    '请解释创建跟进任务前为什么要确认',
    '帮我润色：明天请准时参加面试',
    '查待审批 Offer 并生成风险报告',
    '给我一个面试安排报表',
    '统计本周复试数量',
    '搜索待评价面试记录',
    '查询明天下午的复试安排',
    '列出本周技术面安排',
    '汇总这个月面试安排报告',
    '查看今天 HR 面记录',
    '搜索候选人面试安排',
    '面试安排统计表给我看一下',
    '生成本周面试安排总结',
    '帮我分析面试安排是否合理',
    '明天有哪些候选人要面试',
    '复试安排报表',
    '创建面试流程说明',
    '怎么创建候选人跟进任务？',
]


CONFIRMATION_REPLY_CASES = [
    '确认',
    '确认执行',
    '好的，确认',
    '可以，执行',
    '是的，执行吧',
    '确认执行动作：act-1',
    '没问题，确认',
    '确认吧',
    '可以执行',
]


CANCEL_REPLY_CASES = [
    '取消',
    '取消执行',
    '不用了，取消',
    '先取消',
    '取消动作：act-1',
    '算了，取消',
    '先别执行',
    '不用执行了',
]


ALL_ACTION_CASES = INTERVIEW_ACTION_CASES + FOLLOWUP_ACTION_CASES


def test_module_eight_case_count_at_least_100() -> None:
    total = len(ALL_ACTION_CASES) + len(BOUNDARY_CASES) + len(CONFIRMATION_REPLY_CASES) + len(CANCEL_REPLY_CASES)
    assert total >= 100


@pytest.mark.parametrize('case', ALL_ACTION_CASES, ids=lambda c: c.message)
def test_write_actions_route_to_side_effect_confirmation_plan(case: ActionRouteCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'action'
    assert decision.intent == case.intent
    assert decision.requires_confirmation is True
    assert decision.risk_level == 'high'
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == case.tool
    assert decision.tool_plan[0].purpose == 'side_effect'
    assert decision.tool_plan[0].risk_level == 'high'
    if case.required_context:
        assert decision.required_context == [case.required_context]


@pytest.mark.parametrize('message', BOUNDARY_CASES)
def test_confirmation_actions_do_not_steal_readonly_or_generation_boundaries(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert not (decision.task_type == 'action' and decision.tool_plan and decision.tool_plan[0].purpose == 'side_effect')
    assert not decision.requires_confirmation


def test_prepare_named_interview_confirmation_loads_evidence_but_does_not_create(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, dict(params)))
        return {
            'ok': True,
            'data': {
                'facts': {
                    'name': '吴明华',
                    'resume': {'resume_id': 'r-1'},
                    'job': {'job_id': 'j-1', 'title': '后端工程师'},
                },
            },
            'rows_count': 1,
        }

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = build_route_decision('给吴明华安排2099-12-29 15:00复试', _ctx())

    result = orchestrator._prepare_action_confirmation('给吴明华安排2099-12-29 15:00复试', _ctx(), decision)

    assert calls == [('candidate_evidence_bundle', {'keyword': '吴明华'})]
    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'confirmation_card'
    assert result.widgets[0]['actions'][0]['payload'].startswith('确认执行动作：')
    assert result._pending_action['tools'] == [{
        'tool': 'interview_create',
        'input': {
            'resume_id': 'r-1',
            'job_id': 'j-1',
            'scheduled_at': '2099-12-29T15:00:00',
            'notes': '由聘小犀根据对话确认创建：吴明华复试',
        },
    }]


def test_prepare_generic_followup_confirmation_does_not_require_candidate_evidence(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, dict(params)))
        return {'ok': False, 'error': 'should_not_call_tool', 'data': {}}

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = build_route_decision('新建待办：明天跟进 Offer 审批', _ctx())

    result = orchestrator._prepare_action_confirmation('新建待办：明天跟进 Offer 审批', _ctx(), decision)

    assert calls == []
    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'confirmation_card'
    assert result._pending_action['tools'][0]['tool'] == 'followup_task_create'
    assert result._pending_action['tools'][0]['input']['content'] == '新建待办：明天跟进 Offer 审批'


def test_interview_action_without_time_returns_clarification_instead_of_pending_action() -> None:
    decision = build_route_decision('给吴明华安排复试', _ctx())

    result = orchestrator._prepare_action_confirmation('给吴明华安排复试', _ctx(), decision)

    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'clarification'
    assert not hasattr(result, '_pending_action')
    assert '日期和时间' in result.summary


@pytest.mark.parametrize('reply', CONFIRMATION_REPLY_CASES)
def test_confirmation_replies_execute_latest_pending_action(monkeypatch, reply: str) -> None:
    pending = {
        'id': 'act-1',
        'label': '创建跟进任务',
        'tools': [{'tool': 'followup_task_create', 'input': {'title': '跟进张三', 'content': '明天提醒我跟进张三'}}],
    }
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(orchestrator.memory, 'get_pending_action', lambda user_id, session_id, action_id=None: pending)
    monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 'sess-confirmed-actions')

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, dict(params)))
        return {'ok': True, 'data': {'summary_hint': '已创建跟进提醒：跟进张三。'}, 'rows_count': 1}

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)

    result = orchestrator.run(reply, _ctx())

    assert calls == [('followup_task_create', {'title': '跟进张三', 'content': '明天提醒我跟进张三'})]
    assert '已创建跟进提醒' in result.summary
    assert getattr(result, '_resolved_action_id') == 'act-1'


@pytest.mark.parametrize('reply', CANCEL_REPLY_CASES)
def test_cancel_replies_resolve_latest_pending_action_without_execution(monkeypatch, reply: str) -> None:
    pending = {
        'id': 'act-1',
        'label': '创建跟进任务',
        'tools': [{'tool': 'followup_task_create', 'input': {'title': '跟进张三'}}],
    }
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(orchestrator.memory, 'get_pending_action', lambda user_id, session_id, action_id=None: pending)
    monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 'sess-confirmed-actions')
    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', lambda self, tool, params, ctx: calls.append((tool, params)))

    result = orchestrator.run(reply, _ctx())

    assert calls == []
    assert '已取消' in result.summary
    assert getattr(result, '_resolved_action_id') == 'act-1'


def test_confirmation_without_pending_action_does_not_execute_any_tool(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(orchestrator.memory, 'get_pending_action', lambda user_id, session_id, action_id=None: None)
    monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 'sess-confirmed-actions')
    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', lambda self, tool, params, ctx: calls.append((tool, params)))

    result = orchestrator.run('确认', _ctx())

    assert calls == []
    assert '没有找到可执行的待确认动作' in result.summary


def test_confirmed_action_rejects_unapproved_pending_tool(monkeypatch) -> None:
    pending = {
        'id': 'act-unsafe',
        'label': '异常动作',
        'tools': [{'tool': 'smart_data_query', 'input': {'sql': 'select * from employees'}}],
    }
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(orchestrator.memory, 'get_pending_action', lambda user_id, session_id, action_id=None: pending)
    monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 'sess-confirmed-actions')
    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', lambda self, tool, params, ctx: calls.append((tool, params)))

    result = orchestrator.run('确认执行动作：act-unsafe', _ctx())

    assert calls == []
    assert result.error_code == 'confirmed_action_rejected'
    assert '不支持的确认动作' in result.summary

