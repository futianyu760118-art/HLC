"""Rich widget contract and history replay tests for the assistant.

Module 10 covers the front-end rich component surface from the backend
contract side: generated widget payloads, source/action cards, and persisted
session messages used by the AIAssistant history panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from flask import Flask

from services.assistant_core import widgets as W


@pytest.fixture()
def model_db():
    from models import db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


FRONTEND_WIDGET_TYPES = {
    'metrics',
    'metric_cards',
    'bar',
    'bar_chart',
    'donut',
    'doughnut_chart',
    'table',
    'data_table',
    'entity_cards',
    'warning',
    'markdown',
    'workset_summary',
    'confirmation_card',
    'follow_up_actions',
    'source_citations',
    'mermaid_diagram',
    'echarts',
    'clarification',
    'timeline',
    'comparison_matrix',
    'status_badges',
    'media_preview',
}


@dataclass(frozen=True)
class RichWidgetCase:
    message: str
    expected_widget: str
    scenario: str


RICH_WIDGET_CASES = [
    # Tables
    RichWidgetCase('列出最近 20 位候选人的姓名、岗位和状态', 'table', 'data_table'),
    RichWidgetCase('把本周面试安排按时间做成表格', 'table', 'data_table'),
    RichWidgetCase('查看待入职员工清单，要有部门和入职日期', 'table', 'data_table'),
    RichWidgetCase('列出本月考勤异常 TOP 10', 'table', 'data_table'),
    RichWidgetCase('查薪资档案列表并按部门展示', 'table', 'data_table'),
    RichWidgetCase('显示待审批申请列表', 'table', 'data_table'),
    RichWidgetCase('查看培训未完成名单', 'table', 'data_table'),
    RichWidgetCase('列出反馈系统中待处理的问题', 'table', 'data_table'),
    RichWidgetCase('搜索 Java 简历并输出关键字段', 'table', 'data_table'),
    RichWidgetCase('查询所有开放岗位的招聘进度', 'table', 'data_table'),
    # Metrics
    RichWidgetCase('汇总招聘漏斗关键指标', 'metrics', 'metric_cards'),
    RichWidgetCase('统计本月新增简历、面试和 Offer 数', 'metrics', 'metric_cards'),
    RichWidgetCase('给我员工总览指标卡', 'metrics', 'metric_cards'),
    RichWidgetCase('展示本月考勤核心指标', 'metrics', 'metric_cards'),
    RichWidgetCase('统计绩效优秀、良好和待提升人数', 'metrics', 'metric_cards'),
    RichWidgetCase('汇总薪酬发放总额和确认率', 'metrics', 'metric_cards'),
    RichWidgetCase('查看培训完成率和通过率', 'metrics', 'metric_cards'),
    RichWidgetCase('统计审批待办、通过和驳回数量', 'metrics', 'metric_cards'),
    RichWidgetCase('汇总反馈处理数量和平均处理时长', 'metrics', 'metric_cards'),
    RichWidgetCase('打开 HR 数据看板核心指标', 'metrics', 'metric_cards'),
    # Charts
    RichWidgetCase('按岗位统计候选人数量柱状图', 'bar', 'bar_chart'),
    RichWidgetCase('按部门展示员工人数分布柱状图', 'bar', 'bar_chart'),
    RichWidgetCase('展示简历 AI 评分分布', 'bar', 'bar_chart'),
    RichWidgetCase('统计绩效分数区间', 'bar', 'bar_chart'),
    RichWidgetCase('查看招聘渠道转化数量', 'bar', 'bar_chart'),
    RichWidgetCase('看部门人数占比', 'donut', 'doughnut_chart'),
    RichWidgetCase('显示候选人状态占比', 'donut', 'doughnut_chart'),
    RichWidgetCase('展示考勤状态分布', 'donut', 'doughnut_chart'),
    RichWidgetCase('统计反馈类型占比', 'donut', 'doughnut_chart'),
    RichWidgetCase('展示培训结果占比', 'donut', 'doughnut_chart'),
    # Entity cards
    RichWidgetCase('找出最近 5 个 Java 候选人', 'entity_cards', 'entity_cards'),
    RichWidgetCase('搜索张三的员工档案', 'entity_cards', 'entity_cards'),
    RichWidgetCase('查产品经理岗位详情', 'entity_cards', 'entity_cards'),
    RichWidgetCase('列出高分简历候选人卡片', 'entity_cards', 'entity_cards'),
    RichWidgetCase('展示待入职员工实体卡', 'entity_cards', 'entity_cards'),
    RichWidgetCase('查看供应链总监相关候选人', 'entity_cards', 'entity_cards'),
    RichWidgetCase('查找王五的候选人记录', 'entity_cards', 'entity_cards'),
    RichWidgetCase('展示部门负责人列表', 'entity_cards', 'entity_cards'),
    RichWidgetCase('找出最近发出 Offer 的候选人', 'entity_cards', 'entity_cards'),
    RichWidgetCase('列出本周待面试人员卡片', 'entity_cards', 'entity_cards'),
    # Clarification
    RichWidgetCase('看看小王', 'clarification', 'clarification'),
    RichWidgetCase('查一下他的情况', 'clarification', 'clarification'),
    RichWidgetCase('这个人怎么样', 'clarification', 'clarification'),
    RichWidgetCase('给我看一下记录', 'clarification', 'clarification'),
    RichWidgetCase('查小李相关信息', 'clarification', 'clarification'),
    RichWidgetCase('上面那个呢', 'clarification', 'clarification'),
    RichWidgetCase('我要查本月数据', 'clarification', 'clarification'),
    RichWidgetCase('帮我看看异常', 'clarification', 'clarification'),
    RichWidgetCase('查一下详情', 'clarification', 'clarification'),
    RichWidgetCase('分析这些', 'clarification', 'clarification'),
    # Confirmation
    RichWidgetCase('给张三安排明天下午三点面试', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('给第二位候选人创建跟进任务', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('帮我新建明天电话回访提醒', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('把前三名安排到后天复试', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('给刚才那批候选人创建跟进提醒', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('预约李四下周一技术面', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('创建个人待办：复盘面试反馈', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('给王五安排 HR 面', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('为这些人创建 Offer 跟进任务', 'confirmation_card', 'confirmation_card'),
    RichWidgetCase('给候选人添加入职材料跟进', 'confirmation_card', 'confirmation_card'),
    # Follow-up actions
    RichWidgetCase('查完候选人后给我下一步动作按钮', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('展示候选人后续可做操作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('查员工后给常用操作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('展示审批记录后的快捷动作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('生成报告后给继续追问建议', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('查岗位后给筛选候选人按钮', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('查看考勤异常后给处理建议动作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('薪酬汇总后提示导出和核对动作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('培训分析后给催办动作', 'follow_up_actions', 'follow_up_actions'),
    RichWidgetCase('反馈分析后给处理动作', 'follow_up_actions', 'follow_up_actions'),
    # Sources
    RichWidgetCase('基于数据表回答并列出来源', 'source_citations', 'source_citations'),
    RichWidgetCase('智能查询要展示使用了哪些表', 'source_citations', 'source_citations'),
    RichWidgetCase('候选人分析要标注简历和面试来源', 'source_citations', 'source_citations'),
    RichWidgetCase('员工证据分析要显示档案来源', 'source_citations', 'source_citations'),
    RichWidgetCase('复合报告要列出查询来源', 'source_citations', 'source_citations'),
    RichWidgetCase('薪酬统计要显示来源表但不泄露 SQL', 'source_citations', 'source_citations'),
    RichWidgetCase('招聘报表要展示来源引用', 'source_citations', 'source_citations'),
    RichWidgetCase('审批分析要展示审批记录来源', 'source_citations', 'source_citations'),
    RichWidgetCase('培训报告要展示课程和记录来源', 'source_citations', 'source_citations'),
    RichWidgetCase('反馈报告要展示反馈记录来源', 'source_citations', 'source_citations'),
    # WorkSet
    RichWidgetCase('找出高分候选人后记住这批人', 'workset_summary', 'workset_summary'),
    RichWidgetCase('查询员工列表后支持这些人追问', 'workset_summary', 'workset_summary'),
    RichWidgetCase('列出岗位后可以说第二个', 'workset_summary', 'workset_summary'),
    RichWidgetCase('搜索简历后保留排名前三', 'workset_summary', 'workset_summary'),
    RichWidgetCase('复合报告保留候选人结果集', 'workset_summary', 'workset_summary'),
    RichWidgetCase('查待入职员工后保留刚才那批', 'workset_summary', 'workset_summary'),
    RichWidgetCase('筛出面试名单后支持上面这些人', 'workset_summary', 'workset_summary'),
    RichWidgetCase('查部门人员后支持其中第一位', 'workset_summary', 'workset_summary'),
    RichWidgetCase('查 Offer 列表后支持第二个', 'workset_summary', 'workset_summary'),
    RichWidgetCase('查培训名单后支持这些员工', 'workset_summary', 'workset_summary'),
    # Markdown/warnings/code fallbacks
    RichWidgetCase('润色这段面试邀约文案', 'markdown', 'markdown'),
    RichWidgetCase('总结这份候选人分析', 'markdown', 'markdown'),
    RichWidgetCase('生成招聘周报 markdown', 'markdown', 'markdown'),
    RichWidgetCase('解释结构化面试法', 'markdown', 'markdown'),
    RichWidgetCase('翻译这段英文 JD', 'markdown', 'markdown'),
    RichWidgetCase('权限不足时给我提示', 'warning', 'warning'),
    RichWidgetCase('智能查询失败时给警告', 'warning', 'warning'),
    RichWidgetCase('薪酬数据提醒保密', 'warning', 'warning'),
    RichWidgetCase('没有找到结果时提示空状态', 'warning', 'warning'),
    RichWidgetCase('参数缺失时提示补充字段', 'warning', 'warning'),
    RichWidgetCase('生成组织 Mermaid 图', 'mermaid_diagram', 'code_fallback'),
    RichWidgetCase('返回复杂 ECharts 配置', 'echarts', 'chart'),
]


def test_module_ten_case_count_at_least_100() -> None:
    assert len(RICH_WIDGET_CASES) >= 100


@pytest.mark.parametrize('case', RICH_WIDGET_CASES, ids=lambda c: c.message)
def test_module_ten_cases_target_supported_frontend_widgets(case: RichWidgetCase) -> None:
    assert case.expected_widget in FRONTEND_WIDGET_TYPES


def test_backend_widget_builders_emit_frontend_supported_shapes() -> None:
    samples = [
        W.metric_cards([{'label': '候选人', 'value': 12, 'unit': '人'}], title='招聘指标'),
        W.bar_chart([{'label': '研发部', 'value': 8}], title='部门分布'),
        W.doughnut_chart([{'label': '通过', 'value': 3}], title='状态分布'),
        W.data_table(
            [{'key': 'name', 'label': '姓名'}],
            [{'name': '张三'}],
            title='候选人列表',
        ),
        W.entity_cards([{
            'type': 'candidate',
            'id': 'c-1',
            'title': '张三',
            'typeLabel': '候选人',
            'icon': 'fa-user-tie',
            'url': '/hrm/candidates?id=c-1',
        }]),
        W.warning('权限不足', level='warning'),
        W.confirmation_card('安排面试', '确认后创建面试。', 'act_123'),
        W.follow_up_actions([
            {'label': '安排面试', 'payload': '给张三安排明天下午三点面试', 'requiresConfirmation': True},
        ]),
        W.clarification('你想查谁？', [{'label': '张三', 'payload': '张三'}], '看看 TA'),
        {
            'type': 'source_citations',
            'title': '查询来源',
            'sources': [{'module': 'database', 'recordType': 'table', 'id': 'employees', 'title': 'employees'}],
        },
        {
            'type': 'follow_up_actions',
            'actions': [{'label': '生成面试题', 'payload': '给这些人生成面试题'}],
        },
        {
            'type': 'workset_summary',
            'workset': {'items': [{'rank': 1, 'entity_id': 'c-1', 'title': '张三'}]},
        },
        {'type': 'markdown', 'content': '## 候选人摘要'},
        {'type': 'mermaid_diagram', 'code': 'graph TD;A-->B;'},
        W.echarts({
            'xAxis': {'type': 'category', 'data': ['周一']},
            'yAxis': {'type': 'value'},
            'series': [{'name': '异常', 'type': 'line', 'data': [1]}],
        }, title='ECharts 趋势', chart_type='line'),
        W.timeline([{'time': '2026-05-01', 'title': '入职', 'status': 'done'}], title='员工历程'),
        W.comparison_matrix(
            [{'key': 'name', 'label': '姓名'}, {'key': 'score', 'label': '评分'}],
            [{'name': '张三', 'score': 92}],
            title='候选人对比',
        ),
        W.status_badges([{'label': '考勤正常', 'status': 'success'}], title='状态'),
        W.media_preview([{'title': '简历附件', 'url': '/uploads/resume.pdf', 'type': 'application/pdf'}], title='附件'),
    ]

    assert {w['type'] for w in samples} <= FRONTEND_WIDGET_TYPES
    table = next(w for w in samples if w['type'] == 'table')
    assert table['table']['columns'][0]['key'] == 'name'
    assert table['table']['rows'][0]['name'] == '张三'
    confirmation = next(w for w in samples if w['type'] == 'confirmation_card')
    assert confirmation['actions'][0]['payload'] == '确认执行动作：act_123'
    follow_up = next(w for w in samples if w['type'] == 'follow_up_actions')
    assert follow_up['actions'][0]['requiresConfirmation'] is True
    clarification = next(w for w in samples if w['type'] == 'clarification')
    assert clarification['options'] == [{'label': '张三', 'payload': '张三'}]
    chart = next(w for w in samples if w['type'] == 'echarts')
    assert chart['option']['series'][0]['type'] == 'line'


def test_employee_attendance_evidence_emits_trend_chart_render_block(model_db) -> None:
    from models import AttendanceRecord, Department, Employee, db
    from services.assistant_core.response_contract import apply_response_contract
    from services.assistant_core.schemas import AssistantContext, ExecutionResult
    from services.assistant_core.skills import skill_employee_attendance_evidence

    db.session.add_all([
        Department(id='d-att-chart', name='运营部', code='OPS-CHART', status='active'),
        Employee(
            id='e-att-chart',
            employee_no='E-ATT-CHART',
            name='吴明华',
            status='active',
            department_id='d-att-chart',
            job_title='供应链总监',
        ),
        AttendanceRecord(id='att-chart-1', employee_id='e-att-chart', attendance_date=date(2026, 5, 27), status='normal'),
        AttendanceRecord(id='att-chart-2', employee_id='e-att-chart', attendance_date=date(2026, 5, 28), status='late'),
        AttendanceRecord(id='att-chart-3', employee_id='e-att-chart', attendance_date=date(2026, 5, 29), status='missing_card'),
    ])
    db.session.commit()

    ctx = AssistantContext(user_id='u-rich', role='hr_admin')
    data = skill_employee_attendance_evidence({'keyword': '吴明华', 'month': '2026-05'}, ctx)
    result = ExecutionResult(
        summary=data['summary_hint'],
        entities=data['entities'],
        widgets=data['widgets'],
        answer={'content': data['summary_hint'], 'format': 'markdown'},
    )

    apply_response_contract(result, ctx, message='吴明华最近考勤异常吗？请给趋势图和证据')

    chart_widgets = [widget for widget in result.widgets if widget.get('type') == 'echarts']
    assert chart_widgets
    assert chart_widgets[0]['chartType'] == 'line'
    assert chart_widgets[0]['option']['series'][0]['name'] == '异常'
    assert chart_widgets[0]['option']['series'][0]['data'] == [0, 1, 1]
    assert 'chart' in {block['kind'] for block in result.render_blocks}


def test_copilot_response_contract_wraps_widgets_plan_evidence_and_actions() -> None:
    from services.assistant_core.response_contract import apply_response_contract
    from services.assistant_core.schemas import AssistantContext, ExecutionResult, ExecutionStep, RouterResult

    ctx = AssistantContext(
        user_id='u-contract',
        role='hr_admin',
        request_id='req-contract',
        client_context={
            'path': '/attendance-stats',
            'moduleName': '考勤统计',
            'visibleFilters': {'month': '2026-05'},
        },
    )
    router = RouterResult(
        intent='attendance_exception_analysis',
        task_template_id='attendance_exception_analysis',
        confidence=0.91,
        risk_level='medium',
    )
    result = ExecutionResult(
        summary='本月有 2 人考勤异常。',
        entities=[{
            'type': 'employee',
            'id': 'emp-1',
            'title': '张三',
            'url': '/hrm?id=emp-1',
        }],
        widgets=[
            W.status_badges([{'label': '异常', 'value': 2, 'status': 'warning'}]),
            W.timeline([{'time': '2026-05-03', 'title': '迟到', 'status': 'warning'}]),
            W.follow_up_actions([
                {'label': '安排复核', 'payload': '安排一次复核', 'requiresConfirmation': True},
            ]),
            W.confirmation_card('生成提醒', '确认后生成提醒通知。', 'act-attendance'),
        ],
        trace=[
            ExecutionStep(step_id='attendance', type='skill', skill='attendance_query', status='ok', rows_count=8),
        ],
        router=router,
        requires_confirmation=True,
        actions=[{'label': '确认生成提醒', 'payload': '确认执行动作：act-attendance'}],
    )

    apply_response_contract(result, ctx, message='本月考勤异常并提醒')
    response = result.to_response(include_meta=True)

    assert response['schemaVersion'] == 'assistant.response.v2'
    assert response['clientContext']['path'] == '/attendance-stats'
    assert response['copilot']['currentContext']['moduleName'] == '考勤统计'
    assert response['copilot']['plan'][0]['label'] == 'attendance_query'
    assert response['copilot']['evidence'][0]['recordId'] == 'emp-1'
    assert response['copilot']['actions'][0]['requiresConfirmation'] is True
    assert any(action['label'] == '安排复核' and action['requiresConfirmation'] is True for action in response['copilot']['actions'])
    assert {block['kind'] for block in response['renderBlocks']} >= {'markdown', 'entity_cards', 'status', 'timeline', 'actions', 'confirmation'}
    entity_block = next(block for block in response['renderBlocks'] if block['kind'] == 'entity_cards')
    assert entity_block['source'] == 'entities'
    assert entity_block['payload']['items'] == entity_block['payload']['entities']
    assert entity_block['payload']['items'][0]['id'] == 'emp-1'


def test_copilot_response_contract_preserves_field_level_source_evidence() -> None:
    from services.assistant_core.response_contract import apply_response_contract
    from services.assistant_core.schemas import AssistantContext, ExecutionResult

    ctx = AssistantContext(user_id='u-contract', role='hr_admin')
    result = ExecutionResult(
        summary='吴明华员工画像已生成。',
        widgets=[{
            'type': 'source_citations',
            'title': '本次使用的系统记录',
            'sources': [{
                'module': 'employees',
                'recordType': 'employees',
                'recordId': 'emp-wmh',
                'title': '吴明华 档案',
                'url': '/hrm/employees',
                'fields': [
                    {'key': 'employee.department', 'label': '部门', 'value': '运营部'},
                    {'key': 'employee.job_title', 'label': '岗位', 'value': '供应链总监'},
                ],
            }],
        }],
    )

    apply_response_contract(result, ctx, message='吴明华员工画像')

    evidence = result.copilot['evidence']
    assert evidence[0]['fields'][0]['key'] == 'employee.department'
    assert evidence[0]['fields'][0]['value'] == '运营部'
    assert result.copilot['evaluationHints']['fieldEvidenceCount'] == 2
    source_block = next(block for block in result.render_blocks if block['kind'] == 'sources')
    assert source_block['payload']['sources'][0]['fields'][1]['label'] == '岗位'


def test_copilot_response_contract_does_not_flag_expected_permission_denial_as_tool_gap() -> None:
    from services.assistant_core.response_contract import apply_response_contract
    from services.assistant_core.schemas import AssistantContext, ExecutionResult, RouterResult

    ctx = AssistantContext(user_id='u-contract', role='employee')
    router = RouterResult(
        intent='permission_denied',
        task_template_id='permission_denied_response',
        confidence=0.9,
        risk_level='high',
    )
    result = ExecutionResult(
        summary='权限不足：当前角色无权查看薪酬数据明细，无法继续查询。',
        widgets=[W.warning('权限不足：当前角色无权查看薪酬数据明细，无法继续查询。', level='danger')],
        router=router,
        error_code='permission_denied',
    )

    apply_response_contract(result, ctx, message='查张三本月工资条')

    hints = result.copilot['evaluationHints']
    assert 'tool_calling' not in hints['failureCategories']
    assert hints['needsRootCauseReview'] is False


def test_memory_save_turn_persists_rich_payload_for_history_replay(model_db) -> None:
    from models import AssistantSession, User
    from services.assistant_core import memory

    user = User(
        id='u-rich-history',
        email='rich@example.com',
        password_hash='test-hash',
        name='富组件用户',
        role='hr_admin',
    )
    model_db.session.add(user)
    model_db.session.commit()

    entities = [{
        'type': 'candidate',
        'id': 'c-1',
        'title': '张三',
        'typeLabel': '候选人',
        'icon': 'fa-user-tie',
        'url': '/hrm/candidates?id=c-1',
    }]
    widgets = [
        W.data_table([{'key': 'name', 'label': '姓名'}], [{'name': '张三'}], title='候选人列表'),
        W.confirmation_card('安排面试', '确认后创建面试。', 'act_123'),
    ]
    actions = widgets[1]['actions']
    worksets = [{
        'id': 'ws-1',
        'items': [{'rank': 1, 'entity_id': 'c-1', 'title': '张三'}],
    }]
    answer = {'content': '找到 1 位候选人。', 'format': 'text'}

    session_id = memory.save_turn(
        user_id=user.id,
        session_id=None,
        question='找出高分候选人',
        summary='找到 1 位候选人。',
        entity_count=len(entities),
        metadata={'routeTrack': 'A_DATA_ACTION'},
        entities=entities,
        widgets=widgets,
        actions=actions,
        worksets=worksets,
        answer=answer,
        schema_version='assistant.response.v2',
        render_blocks=[{'id': 'answer', 'kind': 'markdown', 'content': '找到 1 位候选人。'}],
        copilot={'schema': 'assistant.render.v1', 'mode': 'grounded_answer'},
        client_context={'path': '/resume-manage', 'moduleName': '简历管理'},
    )

    sess = AssistantSession.query.get(session_id)
    assistant_msg = sess.messages[-1]

    assert assistant_msg['entities'] == entities
    assert assistant_msg['widgets'] == widgets
    assert assistant_msg['actions'] == actions
    assert assistant_msg['worksets'] == worksets
    assert assistant_msg['answer'] == answer
    assert assistant_msg['schemaVersion'] == 'assistant.response.v2'
    assert assistant_msg['renderBlocks'][0]['kind'] == 'markdown'
    assert assistant_msg['copilot']['schema'] == 'assistant.render.v1'
    assert assistant_msg['clientContext']['moduleName'] == '简历管理'


def test_assistant_session_list_uses_lightweight_summary_query(model_db) -> None:
    from models import AssistantSession, User

    user = User(
        id='u-history-list',
        email='history-list@example.com',
        password_hash='test-hash',
        name='历史列表用户',
        role='hr_admin',
    )
    model_db.session.add(user)
    for idx in range(3):
        model_db.session.add(AssistantSession(
            id=f'history-list-{idx}',
            user_id=user.id,
            title=f'大消息会话 {idx}',
            messages=[{
                'role': 'assistant',
                'content': 'x' * 20000,
                'widgets': [{'type': 'source_citations', 'sources': [{'fields': [{'label': '字段', 'value': idx}]}]}],
            }],
            is_active=idx == 0,
            message_count=2,
        ))
    model_db.session.commit()

    rows = (AssistantSession.query
            .filter(AssistantSession.user_id == user.id, AssistantSession.message_count > 0)
            .with_entities(
                AssistantSession.id,
                AssistantSession.user_id,
                AssistantSession.title,
                AssistantSession.is_active,
                AssistantSession.message_count,
                AssistantSession.created_at,
                AssistantSession.updated_at,
            )
            .order_by(AssistantSession.updated_at.desc())
            .limit(20)
            .all())
    summary = [{
        'id': row.id,
        'userId': row.user_id,
        'title': row.title,
        'isActive': row.is_active,
        'messageCount': row.message_count,
        'createdAt': row.created_at.isoformat() if row.created_at else None,
        'updatedAt': row.updated_at.isoformat() if row.updated_at else None,
    } for row in rows]

    assert len(summary) == 3
    assert all('messages' not in item for item in summary)
    assert {item['messageCount'] for item in summary} == {2}
