"""WorkSet multi-turn follow-up regression cases.

Module 4 focuses on natural follow-up references such as "these people",
"the second one", "top three", and "that previous batch". The cases here are
route/store level on purpose: they should stay deterministic and not require a
live LLM or browser.
"""

from __future__ import annotations

import pytest

from services.assistant_core import legacy_orchestrator as orchestrator
from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext, RouteDecision
from services.assistant_core.workset_store import WorkSetStore


def _ctx(session_id: str = 'sess-workset-followup') -> AssistantContext:
    return AssistantContext(user_id='u-workset-followup', role='hr_admin', session_id=session_id)


def _entities(entity_type: str, count: int = 12) -> list[dict]:
    labels = {
        'candidate': '候选人',
        'resume': '简历',
        'employee': '员工',
        'job': '岗位',
    }
    return [
        {
            'type': entity_type,
            'id': f'{entity_type}-{idx}',
            'title': f'{labels[entity_type]}{idx}',
            'subtitle': f'{labels[entity_type]}结果',
        }
        for idx in range(1, count + 1)
    ]


WORKSET_PLURAL_CASES = [
    ('candidate', '这些人分别怎么样'),
    ('candidate', '这几个人做一个排序'),
    ('candidate', '这批人里谁更合适'),
    ('candidate', '这批候选人逐个分析一下'),
    ('candidate', '刚才那批候选人帮我对比'),
    ('candidate', '刚才列出的那些候选人风险点是什么'),
    ('candidate', '上一批候选人里谁最推荐'),
    ('candidate', '上一轮候选人名单里评分最高的是谁'),
    ('candidate', '上轮这些候选人按匹配度排一下'),
    ('candidate', '前面那批候选人做个报表'),
    ('candidate', '前面这些人各自有什么亮点'),
    ('candidate', '名单里的候选人谁经验最多'),
    ('candidate', '结果里的这些候选人状态怎么样'),
    ('candidate', '上面那几个人里谁最适合'),
    ('candidate', '刚才那些人分别生成面试问题'),
    ('candidate', '这几个候选人对岗位的匹配度如何'),
    ('candidate', '这些应聘者谁优先级最高'),
    ('candidate', '那批候选人需要怎么跟进'),
    ('candidate', '刚才的候选人列表做一个排序'),
    ('candidate', '上面列表中的人逐个评价'),
    ('candidate', '以上候选人按推荐顺序列一下'),
    ('candidate', '上述这些人分别有什么短板'),
    ('candidate', '这一批候选人谁最值得推进'),
    ('candidate', '这批面试者的差异是什么'),
    ('candidate', '这些对象里哪个最合适'),
    ('resume', '这些简历分别提炼亮点'),
    ('resume', '这批简历逐个分析'),
    ('resume', '这批履历里哪份最好'),
    ('resume', '刚才那批简历做个对比'),
    ('resume', '刚才这些履历分别有什么风险'),
    ('resume', '上一批简历里哪份匹配度最高'),
    ('resume', '上一轮简历名单做个排序'),
    ('resume', '上轮这些简历逐份总结'),
    ('resume', '前面那批简历生成面试题'),
    ('resume', '前面这些履历按评分排一下'),
    ('resume', '上面那几份简历谁最合适'),
    ('resume', '结果里的这些简历分数最高的是哪份'),
    ('resume', '简历列表里的每一份都总结一下'),
    ('resume', '名单里的履历分别有什么亮点'),
    ('resume', '以上简历给出推荐顺序'),
    ('resume', '上述这些履历做一个对比报告'),
    ('resume', '这一批简历谁需要优先筛'),
    ('resume', '那批简历里面经验最多的是谁'),
    ('resume', '刚才的简历结果按匹配度排序'),
    ('resume', '这些投递记录里哪份更适合'),
    ('employee', '这些员工绩效最高的是谁'),
    ('employee', '这批员工逐个分析一下'),
    ('employee', '刚才那批员工按部门汇总'),
    ('employee', '上一批员工里谁入职最早'),
    ('employee', '上一轮员工名单里哪个快转正'),
    ('employee', '上轮这些同事合同情况如何'),
    ('employee', '前面那批成员做个概览'),
    ('employee', '前面这些同事谁需要跟进'),
    ('employee', '上面那几位员工状态怎么样'),
    ('employee', '结果里的这些成员谁绩效最好'),
    ('employee', '名单里的每位员工都总结一下'),
    ('employee', '以上同事按入职时间排一下'),
    ('employee', '上述这些员工有哪些合同风险'),
    ('employee', '这一批员工谁快到转正节点'),
    ('employee', '那批成员里谁考勤异常最多'),
    ('job', '这些岗位哪个还在招'),
    ('job', '这批岗位按优先级排一下'),
    ('job', '刚才那批岗位做个汇总'),
    ('job', '上一批职位里哪个最急'),
    ('job', '上一轮岗位名单按部门归类'),
    ('job', '上轮这些招聘需求缺口多大'),
    ('job', '前面那批职位生成报表'),
    ('job', '前面这些岗位哪个候选人最多'),
    ('job', '上面那几个岗位状态怎么样'),
    ('job', '结果里的这些职位谁优先关闭'),
    ('job', '以上招聘需求做一个对比'),
    ('job', '上述这些岗位分别缺什么人'),
    ('job', '这一批岗位哪个风险最高'),
    ('job', '那批职位里哪个发布最久'),
]


WORKSET_ORDINAL_CASES = [
    ('candidate', '第一个候选人怎么样', 1),
    ('candidate', '第一位候选人适合吗', 1),
    ('candidate', '第 1 位候选人有什么风险', 1),
    ('candidate', '第1名候选人继续推进吗', 1),
    ('candidate', '第二个适合吗', 2),
    ('candidate', '第二位适合吗', 2),
    ('candidate', '第 2 位有什么亮点', 2),
    ('candidate', '第2名候选人要不要约面试', 2),
    ('candidate', '第三个人的面试策略是什么', 3),
    ('candidate', '第三位候选人风险大吗', 3),
    ('candidate', '第 3 名怎么跟进', 3),
    ('candidate', '第四个候选人做个总结', 4),
    ('candidate', '第五位候选人生成面试题', 5),
    ('candidate', '第六个候选人是否推荐', 6),
    ('candidate', '第七位候选人状态怎么样', 7),
    ('candidate', '第八名候选人有什么短板', 8),
    ('candidate', '第九个候选人下一步建议', 9),
    ('candidate', '第十位候选人是否合适', 10),
    ('candidate', '最后一个候选人怎么样', 12),
    ('candidate', '最后一位要不要进入下一轮', 12),
    ('candidate', '倒数第一个候选人有什么风险', 12),
    ('candidate', '倒数第一位候选人怎么跟进', 12),
    ('candidate', '倒数第二个候选人适合吗', 11),
    ('resume', '第一份简历怎么样', 1),
    ('resume', '第 1 份简历提炼亮点', 1),
    ('resume', '第二份简历有什么风险', 2),
    ('resume', '第2份履历生成面试问题', 2),
    ('resume', '第三份简历总结一下', 3),
    ('resume', '最后一份简历是否值得推进', 12),
    ('employee', '第一位员工合同情况如何', 1),
    ('employee', '第二位员工什么时候转正', 2),
    ('employee', '第 3 位员工绩效怎么样', 3),
    ('employee', '最后一个员工考勤有没有异常', 12),
    ('job', '第一个岗位还开放吗', 1),
    ('job', '第二个职位缺口多大', 2),
    ('job', '第 3 个招聘需求状态如何', 3),
    ('job', '最后一个岗位发布多久了', 12),
]


TYPE_PREFERENCE_CASES = [
    ('这些候选人里谁最推荐', 'candidate'),
    ('刚才那批候选人做个对比', 'candidate'),
    ('这些简历哪份评分最高', 'resume'),
    ('上一批履历逐个总结', 'resume'),
    ('这些员工谁入职最早', 'employee'),
    ('刚才那批同事谁快转正', 'employee'),
    ('这些岗位哪个最急', 'job'),
    ('上一批职位按优先级排序', 'job'),
    ('这些招聘需求分别缺什么人', 'job'),
    ('那批成员里谁需要跟进', 'employee'),
]


ROUTE_FOLLOWUP_CASES = [
    '第二位适合吗',
    '第 2 位候选人有什么风险',
    '第三份简历总结一下',
    '最后一个怎么样',
    '倒数第二个分析一下风险',
    '刚才那批候选人分别怎么样',
    '上一批候选人做个对比',
    '这批简历逐份生成面试题',
    '上一批履历按评分排序',
    '前面这些人各自有什么亮点',
    '上面那几位员工状态怎么样',
    '这些岗位做一个优先级报表',
    '上一轮岗位名单做个分析',
    '结果里的这些成员分别总结',
    '以上候选人给出推荐顺序',
    '上述这些履历做一个对比报告',
    '这一批员工谁快转正',
    '那批职位里哪个发布最久',
    '这几个候选人对岗位的匹配度如何',
    '名单里的每位员工都总结一下',
]


WORKSET_ANALYSIS_ROUTE_CASES = [
    '其中评分最高的是谁',
    '刚才那批候选人里匹配度最高的是谁',
    '刚才那批里先约谁比较稳，别浪费面试官时间',
    '上一批简历里评分最高的是哪份',
    '这些员工里入职最早的是谁',
    '上面这些岗位哪个发布最久',
    '结果里的这些人谁经验最多',
    '名单里的员工谁绩效最低',
    '这批履历里面学历最高的是谁',
]


ACTION_ROUTE_CASES = [
    '给第二位安排明天上午十点面试',
    '给第 2 位候选人安排明天下午三点复试',
    '给最后一个候选人安排明天上午九点面试',
    '给倒数第二个安排明天下午四点复试',
    '给刚才那批候选人创建明天上午十点的跟进任务',
    '给上一批候选人创建明天下午三点的跟进提醒',
    '给前二安排明天上午十点面试',
    '给匹配度前 3 位安排明天下午两点复试',
]


def test_module_four_case_count_at_least_100() -> None:
    case_count = (
        len(WORKSET_PLURAL_CASES)
        + len(WORKSET_ORDINAL_CASES)
        + len(TYPE_PREFERENCE_CASES)
        + len(ROUTE_FOLLOWUP_CASES)
        + len(WORKSET_ANALYSIS_ROUTE_CASES)
        + len(ACTION_ROUTE_CASES)
    )
    assert case_count >= 100


@pytest.mark.parametrize('entity_type,message', WORKSET_PLURAL_CASES)
def test_workset_store_resolves_plural_followups(entity_type: str, message: str) -> None:
    store = WorkSetStore()
    ws = store.create_workset_from_entities('s-follow', 'u1', '结果集', _entities(entity_type))

    resolved = store.resolve_mention(message, 's-follow')

    assert resolved is not None, message
    assert resolved['kind'] == 'workset'
    assert resolved['workset']['id'] == ws['id']


@pytest.mark.parametrize('entity_type,message,rank', WORKSET_ORDINAL_CASES)
def test_workset_store_resolves_ordinal_followups(entity_type: str, message: str, rank: int) -> None:
    store = WorkSetStore()
    ws = store.create_workset_from_entities('s-ordinal', 'u1', '结果集', _entities(entity_type))

    resolved = store.resolve_mention(message, 's-ordinal')

    assert resolved is not None, message
    assert resolved['kind'] == 'item'
    assert resolved['workset']['id'] == ws['id']
    assert resolved['item']['entity_id'] == f'{entity_type}-{rank}'


@pytest.mark.parametrize('message,expected_entity_type', TYPE_PREFERENCE_CASES)
def test_workset_store_prefers_explicit_entity_type_over_latest_any(
    message: str,
    expected_entity_type: str,
) -> None:
    store = WorkSetStore()
    for entity_type in ('candidate', 'resume', 'employee', 'job'):
        store.create_workset_from_entities('s-typed', 'u1', entity_type, _entities(entity_type, count=2))

    resolved = store.resolve_mention(message, 's-typed')

    assert resolved is not None, message
    assert resolved['kind'] == 'workset'
    assert resolved['workset']['entity_type'] == expected_entity_type


@pytest.mark.parametrize('message', ROUTE_FOLLOWUP_CASES)
def test_workset_followup_routes_to_generation_with_latest_context(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'B_GENERATION', message
    assert decision.task_type == 'generation'
    assert {'latest_workset', 'candidate_workset'}.intersection(decision.required_context)


@pytest.mark.parametrize('message', WORKSET_ANALYSIS_ROUTE_CASES)
def test_workset_metric_questions_use_workset_analyze_tool(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'B_GENERATION', message
    assert decision.intent == 'workset_analysis'
    assert 'latest_workset' in decision.required_context
    assert decision.tool_plan[0].tool == 'workset_analyze'


@pytest.mark.parametrize('message', ACTION_ROUTE_CASES)
def test_workset_action_followups_require_confirmation_and_latest_context(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.task_type == 'action', message
    assert decision.intent in {'interview_schedule', 'followup_task_create'}
    assert decision.requires_confirmation is True
    assert decision.required_context == ['latest_workset']
    assert decision.tool_plan[0].purpose == 'side_effect'


def test_colloquial_workset_ask_who_to_interview_first_is_readonly() -> None:
    decision = build_route_decision('刚才那批里先约谁比较稳，别浪费面试官时间', _ctx())

    assert decision.route_track == 'B_GENERATION'
    assert decision.task_type == 'generation'
    assert decision.intent == 'workset_analysis'
    assert decision.requires_confirmation is False
    assert decision.required_context == ['latest_workset']
    assert decision.tool_plan[0].tool == 'workset_analyze'


def test_explicit_workset_interview_schedule_still_requires_confirmation() -> None:
    decision = build_route_decision('给第二位安排明天上午十点面试', _ctx())

    assert decision.task_type == 'action'
    assert decision.intent == 'interview_schedule'
    assert decision.requires_confirmation is True
    assert decision.required_context == ['latest_workset']


def test_workset_candidate_risk_followup_skips_llm_planner(monkeypatch) -> None:
    from services.assistant_core.intent_router import llm_skill_planner

    monkeypatch.setattr(
        llm_skill_planner,
        'plan_with_llm',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('WorkSet follow-up should skip LLM planner')),
    )

    decision = build_route_decision('那第二个人有什么风险，下一步怎么推进？', _ctx())

    assert decision.route_track == 'B_GENERATION'
    assert decision.task_type == 'generation'
    assert decision.intent in {'candidate_assessment', 'person_assessment', 'person_evidence_answer'}
    assert 'latest_workset' in decision.required_context
    assert decision.generation_plan is not None


def test_context_from_workset_loads_only_referenced_second_item(monkeypatch) -> None:
    items = [
        {'entity_type': 'candidate', 'entity_id': 'c-1', 'title': '候选人1', 'rank': 1},
        {'entity_type': 'candidate', 'entity_id': 'c-2', 'title': '候选人2', 'rank': 2},
    ]
    ws = {'id': 'ws-ordinal', 'items': items, 'entity_type': 'candidate'}
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        orchestrator.workset_store,
        'resolve_mention',
        lambda message, session_id: {'kind': 'item', 'item': items[1], 'workset': ws},
    )

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, dict(params)))
        return {'ok': True, 'data': {'facts': {'name': '候选人2'}}, 'rows_count': 1}

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = RouteDecision(
        task_type='generation',
        route_track='B_GENERATION',
        intent='candidate_assessment',
        confidence=0.9,
        required_context=['latest_workset'],
    )

    context, clarification = orchestrator._context_from_workset('第二位适合吗', _ctx(), decision)

    assert clarification is None
    assert context is not None
    assert [item['entity_id'] for item in context['items']] == ['c-2']
    assert calls == [('candidate_evidence_bundle', {'candidate_id': 'c-2'})]


def test_context_from_workset_emits_candidate_follow_up_actions(monkeypatch) -> None:
    items = [
        {'entity_type': 'candidate', 'entity_id': 'c-1', 'title': '邓浩', 'rank': 1},
        {'entity_type': 'candidate', 'entity_id': 'c-2', 'title': '杨琳', 'rank': 2},
    ]
    ws = {'id': 'ws-actions', 'items': items, 'entity_type': 'candidate'}
    monkeypatch.setattr(
        orchestrator.workset_store,
        'resolve_mention',
        lambda message, session_id: {'kind': 'item', 'item': items[1], 'workset': ws},
    )

    def fake_execute(self, tool, params, ctx):
        return {
            'ok': True,
            'data': {
                'facts': {
                    'entity_type': 'candidate',
                    'entity_id': 'c-2',
                    'name': '杨琳',
                    'resume': {'score': 86, 'weaknesses': ['独立方案设计经验不足']},
                    'job': {'title': '电子工程师'},
                },
            },
        }

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = RouteDecision(
        task_type='generation',
        route_track='B_GENERATION',
        intent='candidate_assessment',
        confidence=0.9,
        required_context=['latest_workset'],
    )

    context, clarification = orchestrator._context_from_workset(
        '那第二个人有什么风险，下一步怎么推进？',
        _ctx('sess-actions'),
        decision,
    )

    assert clarification is None
    assert [item['entity_id'] for item in context['items']] == ['c-2']
    actions_widget = context['widgets'][0]
    assert actions_widget['type'] == 'follow_up_actions'
    assert any(action['label'] == '生成面试题' for action in actions_widget['actions'])
    schedule_action = next(action for action in actions_widget['actions'] if action['label'] == '安排面试')
    assert schedule_action['requiresConfirmation'] is True
    assert schedule_action['payload'] == '给杨琳安排明天下午三点面试'


def test_front_two_action_confirmation_limits_pending_tools(monkeypatch) -> None:
    items = [
        {'entity_type': 'candidate', 'entity_id': f'c-{idx}', 'title': f'候选人{idx}', 'rank': idx}
        for idx in range(1, 5)
    ]
    ws = {'id': 'ws-front-two', 'items': items, 'entity_type': 'candidate'}
    monkeypatch.setattr(
        orchestrator.workset_store,
        'resolve_mention',
        lambda message, session_id: {'kind': 'workset', 'workset': ws},
    )

    def fake_execute(self, tool, params, ctx):
        idx = params['candidate_id'].split('-')[-1]
        return {
            'ok': True,
            'data': {
                'facts': {
                    'name': f'候选人{idx}',
                    'resume': {'resume_id': f'r-{idx}', 'score': 100 - int(idx)},
                    'job': {'job_id': 'j-1'},
                },
            },
        }

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = build_route_decision('给前二安排明天上午十点面试', _ctx())

    result = orchestrator._prepare_action_confirmation('给前二安排明天上午十点面试', _ctx(), decision)

    assert result.requires_confirmation is True
    assert len(result._pending_action['tools']) == 2
    assert [tool['input']['resume_id'] for tool in result._pending_action['tools']] == ['r-1', 'r-2']


def test_missing_workset_followup_returns_clarification() -> None:
    decision = build_route_decision('刚才那批候选人里谁评分最高', _ctx('sess-no-workset'))

    context, clarification = orchestrator._context_from_workset(
        '刚才那批候选人里谁评分最高',
        _ctx('sess-no-workset'),
        decision,
    )

    assert context is None
    assert clarification is not None
    assert clarification.requires_confirmation is True
    assert '请先查询候选人' in clarification.summary

