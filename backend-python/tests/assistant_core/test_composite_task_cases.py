"""Composite task routing cases for the assistant.

Module 7 verifies "query first, then generate" requests keep the COMPOSITE
track, use registered read-only tools for the query step, and never turn
business writes into unconfirmed composite execution.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-composite', role=role, session_id='sess-composite')


@dataclass(frozen=True)
class CompositeCase:
    message: str
    tool: str
    intent: str = 'analysis_report'
    module: str | None = None
    role: str = 'hr_admin'


RECRUITMENT_COMPOSITE_CASES = [
    CompositeCase('找出最近 5 个 Java 候选人，并帮我设计面试题', 'recruitment_search', 'interview_questions', 'candidates'),
    CompositeCase('查一下待沟通候选人，然后生成跟进建议', 'recruitment_search', module='candidates'),
    CompositeCase('搜索产品经理候选人并输出对比报告', 'recruitment_search', 'candidate_compare', 'candidates'),
    CompositeCase('列出面试中的候选人并生成风险分析', 'recruitment_search', module='candidates'),
    CompositeCase('查找新候选人，再生成筛选建议', 'recruitment_search', module='candidates'),
    CompositeCase('看一下推荐候选人名单并生成优先级报告', 'recruitment_search', 'candidate_compare', 'candidates'),
    CompositeCase('查 C++ 候选人并生成技术面追问', 'recruitment_search', 'interview_questions', 'candidates'),
    CompositeCase('找上海销售候选人然后生成沟通建议', 'recruitment_search', module='candidates'),
    CompositeCase('查看候选人库里的 HR 候选人并生成初面问题', 'recruitment_search', 'interview_questions', 'candidates'),
    CompositeCase('列出已淘汰候选人并生成淘汰原因复盘', 'recruitment_search', module='candidates'),
    CompositeCase('查最近投递 Java 简历并生成筛选报告', 'recruitment_search', module='resumes'),
    CompositeCase('查看待筛选简历并生成初筛建议', 'recruitment_search', module='resumes'),
    CompositeCase('搜索高分简历并输出候选人摘要', 'recruitment_search', module='resumes'),
    CompositeCase('列出淘汰简历并生成原因复盘', 'recruitment_search', module='resumes'),
    CompositeCase('查产品岗投递记录并生成筛选优先级', 'recruitment_search', 'candidate_compare', 'resumes'),
    CompositeCase('查看通过初筛简历并生成二面问题', 'recruitment_search', 'interview_questions', 'resumes'),
    CompositeCase('查开放中的岗位并生成招聘推进建议', 'recruitment_search', module='jobs'),
    CompositeCase('搜索 Java 工程师岗位并生成岗位卖点摘要', 'recruitment_search', module='jobs'),
    CompositeCase('查看产品经理 JD 并生成候选人面试题', 'recruitment_search', 'interview_questions', 'jobs'),
    CompositeCase('列出暂停招聘的职位并生成风险说明', 'recruitment_search', module='jobs'),
    CompositeCase('查今天待面试安排并生成面试官提醒要点', 'recruitment_search', module='interviews'),
    CompositeCase('查看待评价面试记录并生成反馈催办建议', 'recruitment_search', module='interviews'),
    CompositeCase('搜索取消的面试并生成排期风险报告', 'recruitment_search', module='interviews'),
    CompositeCase('查二面记录并生成复试追问', 'recruitment_search', 'interview_questions', 'interviews'),
    CompositeCase('查待审批 Offer 并生成风险报告', 'recruitment_search', module='offers'),
    CompositeCase('查看已接受 offer 列表并生成入职准备建议', 'recruitment_search', module='offers'),
    CompositeCase('搜索已拒绝 Offer 并生成原因分析', 'recruitment_search', module='offers'),
    CompositeCase('列出待确认录用通知并生成候选人沟通建议', 'recruitment_search', module='offers'),
]


EMPLOYEE_ORG_COMPOSITE_CASES = [
    CompositeCase('查一下试用期员工并生成转正风险报告', 'employee_search'),
    CompositeCase('列出在职员工并生成部门分布摘要', 'employee_search'),
    CompositeCase('查看待入职员工并生成入职准备建议', 'employee_search'),
    CompositeCase('搜索已离职员工并生成离职原因复盘', 'employee_search'),
    CompositeCase('查员工张三的档案并生成管理建议', 'employee_search'),
    CompositeCase('查看销售经理高强的员工信息并生成沟通要点', 'employee_search'),
    CompositeCase('列出暂停状态员工并生成风险说明', 'employee_search'),
    CompositeCase('查正式员工名单并生成组织健康摘要', 'employee_search'),
    CompositeCase('查看员工花名册并生成人员结构报告', 'employee_search'),
    CompositeCase('搜索研发部张伟的岗位信息并生成发展建议', 'employee_search'),
    CompositeCase('查组织架构并生成管理摘要', 'organization_search'),
    CompositeCase('查看部门人数分布并生成组织效率报告', 'organization_search'),
    CompositeCase('列出研发部人员并生成团队配置建议', 'organization_search'),
    CompositeCase('搜索销售部岗位体系并生成招聘建议', 'organization_search'),
    CompositeCase('查看客服部负责人和人员分布并生成交接建议', 'organization_search'),
    CompositeCase('查岗位序列并生成职级沟通话术', 'organization_search'),
    CompositeCase('列出各部门人数并生成扩编建议', 'organization_search'),
    CompositeCase('查看技术中心下面的部门并生成组织调整建议', 'organization_search'),
    CompositeCase('查入职进度并生成入职风险报告', 'system_search', module='lifecycle'),
    CompositeCase('查看本周入职员工进度并生成跟进建议', 'system_search', module='lifecycle'),
    CompositeCase('列出快到转正的员工并生成转正提醒', 'system_search', module='lifecycle'),
    CompositeCase('查转正未通过的人并生成原因复盘', 'system_search', module='lifecycle'),
    CompositeCase('查看离职交接未完成的员工并生成风险报告', 'system_search', module='lifecycle'),
    CompositeCase('搜索合同快到期员工并生成续签建议', 'system_search', module='lifecycle'),
    CompositeCase('查员工异动记录并生成组织影响分析', 'system_search', module='lifecycle'),
    CompositeCase('查看调岗申请并生成审批建议', 'system_search', module='lifecycle'),
    CompositeCase('列出员工合同台账并生成合规报告', 'system_search', module='lifecycle'),
    CompositeCase('查入职审批并生成处理优先级', 'system_search', 'candidate_compare', 'lifecycle'),
]


OPERATIONS_COMPOSITE_CASES = [
    CompositeCase('查本月考勤异常并生成改进建议', 'attendance_analysis'),
    CompositeCase('统计迟到最多的员工并生成管理建议', 'attendance_analysis'),
    CompositeCase('查看缺卡记录并生成补卡提醒话术', 'attendance_analysis'),
    CompositeCase('列出请假天数较多的员工并生成风险报告', 'attendance_analysis'),
    CompositeCase('查研发部加班统计并生成工时优化建议', 'attendance_analysis'),
    CompositeCase('查看连续迟到人员并生成沟通建议', 'attendance_analysis'),
    CompositeCase('查本周考勤报表并生成团队摘要', 'attendance_analysis'),
    CompositeCase('统计近 7 天缺卡人员并生成处理建议', 'attendance_analysis'),
    CompositeCase('查看早退记录并生成制度宣导要点', 'attendance_analysis'),
    CompositeCase('查出差记录汇总并生成成本提示', 'attendance_analysis'),
    CompositeCase('看一下销售部绩效分布并生成校准建议', 'performance_analysis'),
    CompositeCase('统计绩效等级分布并生成管理报告', 'performance_analysis'),
    CompositeCase('查看 Q1 绩效评分并生成复盘摘要', 'performance_analysis'),
    CompositeCase('列出绩效排名前十并生成激励建议', 'performance_analysis', 'candidate_compare'),
    CompositeCase('查 A 等级员工名单并生成保留建议', 'performance_analysis'),
    CompositeCase('查看绩效待校准名单并生成会议议程', 'performance_analysis'),
    CompositeCase('查年度绩效汇总并生成组织洞察', 'performance_analysis'),
    CompositeCase('统计部门绩效对比并生成差异报告', 'performance_analysis', 'candidate_compare'),
    CompositeCase('查看绩效低于 60 的员工并生成辅导建议', 'performance_analysis'),
    CompositeCase('查销售团队绩效趋势并生成行动建议', 'performance_analysis'),
    CompositeCase('查本月薪酬汇总并生成薪酬分析报告', 'payroll_analysis', role='finance'),
    CompositeCase('查看研发部工资总额并生成预算说明', 'payroll_analysis', role='finance'),
    CompositeCase('统计个税汇总并生成异常提示', 'payroll_analysis', role='finance'),
    CompositeCase('查社保缴纳名单并生成合规报告', 'payroll_analysis', role='finance'),
    CompositeCase('查看工资条未确认名单并生成提醒文案', 'payroll_analysis', role='finance'),
    CompositeCase('查年终奖发放汇总并生成管理摘要', 'payroll_analysis', role='finance'),
    CompositeCase('查培训完成率并生成培训复盘', 'training_analysis'),
    CompositeCase('查看未完成培训员工并生成催办建议', 'training_analysis'),
    CompositeCase('统计安全培训完成情况并生成风险报告', 'training_analysis'),
    CompositeCase('查合规课程出勤统计并生成改进建议', 'training_analysis'),
    CompositeCase('查看销售部培训记录并生成能力提升建议', 'training_analysis'),
    CompositeCase('统计课程通过率并生成课程优化建议', 'training_analysis'),
    CompositeCase('查培训缺勤名单并生成提醒话术', 'training_analysis'),
    CompositeCase('查看培训成绩分布并生成复盘摘要', 'training_analysis'),
    CompositeCase('统计线上课程学习进度并生成跟进计划', 'training_analysis'),
    CompositeCase('查课程反馈汇总并生成优化报告', 'training_analysis'),
    CompositeCase('查待我审批事项并生成处理优先级', 'approval_search', 'candidate_compare'),
    CompositeCase('查看我的申请记录并生成状态摘要', 'approval_search'),
    CompositeCase('列出请假审批待处理并生成审批建议', 'approval_search'),
    CompositeCase('查加班审批列表并生成风险说明', 'approval_search'),
    CompositeCase('查看报销审批进度并生成催办话术', 'approval_search'),
    CompositeCase('统计本周审批数据并生成效率报告', 'approval_search'),
    CompositeCase('查被驳回的申请并生成原因复盘', 'approval_search'),
    CompositeCase('查看审批通过率并生成流程改进建议', 'approval_search'),
    CompositeCase('列出主管待审批任务并生成优先级建议', 'approval_search', 'candidate_compare'),
    CompositeCase('查审批中心待办并生成今日处理计划', 'approval_search'),
    CompositeCase('查最近 bug 反馈并生成修复优先级', 'feedback_triage', 'candidate_compare'),
    CompositeCase('查看待处理反馈并生成处理建议', 'feedback_triage'),
    CompositeCase('列出缺陷反馈并生成风险报告', 'feedback_triage'),
    CompositeCase('统计需求反馈并生成产品建议', 'feedback_triage'),
    CompositeCase('查已修复 bug 并生成发布摘要', 'feedback_triage'),
    CompositeCase('查看已采纳需求并生成迭代复盘', 'feedback_triage'),
    CompositeCase('统计反馈类型分布并生成运营报告', 'feedback_triage'),
    CompositeCase('查看用户反馈报表并生成管理摘要', 'feedback_triage'),
    CompositeCase('查未处理缺陷数量并生成处理计划', 'feedback_triage'),
    CompositeCase('统计反馈处理时长并生成流程建议', 'feedback_triage'),
    CompositeCase('查系统概览并生成管理摘要', 'dashboard_report'),
    CompositeCase('查看整体情况并生成运营报告', 'dashboard_report'),
    CompositeCase('查 HR 数据看板并生成高管摘要', 'dashboard_report'),
    CompositeCase('查看管理驾驶舱并生成本周重点', 'dashboard_report'),
    CompositeCase('查仪表盘指标并生成异常说明', 'dashboard_report'),
    CompositeCase('查看本周招聘报表并生成管理摘要', 'dashboard_report'),
    CompositeCase('查招聘概览并生成风险建议', 'dashboard_report'),
    CompositeCase('查看招聘进展报表并生成下一步建议', 'dashboard_report'),
]


ALL_COMPOSITE_CASES = (
    RECRUITMENT_COMPOSITE_CASES
    + EMPLOYEE_ORG_COMPOSITE_CASES
    + OPERATIONS_COMPOSITE_CASES
)


def test_module_seven_case_count_at_least_100() -> None:
    assert len(ALL_COMPOSITE_CASES) >= 100


@pytest.mark.parametrize('case', ALL_COMPOSITE_CASES, ids=lambda c: c.message)
def test_query_then_generate_requests_use_composite_readonly_plan(case: CompositeCase) -> None:
    decision = build_route_decision(case.message, _ctx(role=case.role))

    assert decision.route_track == 'COMPOSITE'
    assert decision.task_type == 'composite'
    assert decision.intent == case.intent
    assert decision.requires_confirmation is False
    assert decision.tool_plan
    first = decision.tool_plan[0]
    assert first.tool == case.tool
    assert first.purpose == 'query'
    assert first.risk_level in {'low', 'high'}
    assert first.tool not in {'interview_create', 'followup_task_create'}
    if case.module:
        assert first.input.get('module') == case.module
    assert decision.generation_plan is not None
    assert decision.generation_plan.template_id == case.intent
    assert decision.generation_plan.output_format == 'markdown'


@pytest.mark.parametrize('message', [
    '请解释先查证据再生成报告的流程',
    '什么是先查数据再生成报告？',
    '如何设计“查询后生成报告”的测试用例？',
    '帮我润色：先查考勤异常，再生成沟通建议',
])
def test_composite_boundaries_keep_direct_knowledge_on_c_track(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
    assert decision.tool_plan == []


@pytest.mark.parametrize('message, track, task_type', [
    ('查一下最近 5 个 Java 候选人', 'A_DATA_ACTION', 'data_query'),
    ('生成 8 道 Java 后端面试题', 'B_GENERATION', 'generation'),
])
def test_composite_boundaries_do_not_steal_pure_query_or_generation(
    message: str,
    track: str,
    task_type: str,
) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == track
    assert decision.task_type == task_type


@pytest.mark.parametrize('message', [
    '查一下张三的候选人记录并安排明天面试',
    '找出最近 5 个 Java 候选人并创建跟进任务',
])
def test_composite_boundaries_keep_write_actions_confirmed(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'action'
    assert decision.requires_confirmation is True
    assert decision.tool_plan
    assert decision.tool_plan[0].purpose == 'side_effect'
    assert decision.tool_plan[0].risk_level == 'high'


def test_unauthorized_payroll_composite_is_denied_before_generation() -> None:
    decision = build_route_decision('查本月薪酬汇总并生成薪酬分析报告', _ctx(role='employee'))

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.intent == 'permission_denied'
    assert decision.task_template_id == 'permission_denied_response'
    assert decision.tool_plan == []
    assert decision.requires_confirmation is False

