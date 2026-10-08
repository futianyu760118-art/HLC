"""Operational HR domain routing cases for the assistant.

Module 6 verifies read-only queries for attendance, performance, payroll,
training, approvals, feedback, and dashboard/reporting stay on the data track
and keep their registered task/skill/risk mapping.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-ops-domain', role=role, session_id='sess-ops-domain')


@dataclass(frozen=True)
class OpsDomainCase:
    message: str
    intent: str
    skill: str
    risk: str = 'low'


ATTENDANCE_CASES = [
    OpsDomainCase('本月谁考勤异常最多', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('张三这个月迟到几次', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('李四上周缺卡记录', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('王五本月请假天数', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('研发部本月考勤异常', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('销售部加班统计', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('今天迟到人员名单', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('昨天早退有哪些人', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('本月出差记录汇总', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('补卡申请记录', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('哪些员工连续迟到', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('本周考勤报表', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('考勤异常趋势', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('我的考勤记录', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('我这个月请假记录', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('部门考勤排名', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('近 7 天缺卡人员', 'attendance_exception_analysis', 'attendance_analysis'),
    OpsDomainCase('上午迟到统计', 'attendance_exception_analysis', 'attendance_analysis'),
]


PERFORMANCE_CASES = [
    OpsDomainCase('看一下销售部绩效分布', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效等级分布', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('本期绩效报表', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('Q1 绩效评分', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('张三绩效评分', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('研发部考核结果', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效排名前十', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('A 等级员工名单', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效待校准名单', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('年度绩效汇总', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('部门绩效对比', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效评分低于 60 的员工', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效优秀员工名单', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('本季度考核等级统计', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('销售团队绩效趋势', 'performance_distribution_report', 'performance_analysis'),
    OpsDomainCase('绩效校准结果', 'performance_distribution_report', 'performance_analysis'),
]


PAYROLL_CASES = [
    OpsDomainCase('本月薪酬汇总', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('张三工资条', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('查一下李四薪资档案', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('研发部工资总额', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('个税汇总', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('社保缴纳名单', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('2026-05 工资条', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('工资发放情况', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('薪酬报表', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('部门薪资分布', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('王五奖金记录', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('本月实发工资统计', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('社保异常人员', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('工资条未确认名单', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('薪资调整记录', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('年终奖发放汇总', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('个税异常记录', 'payroll_month_summary', 'payroll_analysis', risk='high'),
    OpsDomainCase('本月应发工资合计', 'payroll_month_summary', 'payroll_analysis', risk='high'),
]


TRAINING_CASES = [
    OpsDomainCase('培训完成率怎么样', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('谁还没完成培训', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('安全培训完成情况', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('合规课程出勤统计', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('本月培训计划进度', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('销售部培训记录', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('课程通过率', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('培训考试通过率', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('未完成课程的员工', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('培训缺勤名单', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('本周培训报表', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('新课程报名情况', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('培训成绩分布', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('线上课程学习进度', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('培训计划完成率', 'training_completion_report', 'training_analysis'),
    OpsDomainCase('课程反馈汇总', 'training_completion_report', 'training_analysis'),
]


APPROVAL_CASES = [
    OpsDomainCase('待我审批有哪些', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('我有哪些待审批', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('我的申请记录', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('审批记录', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('审批历史', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('请假审批待处理', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('加班审批列表', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('报销审批到哪一步', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('待处理审批事项', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('本周审批统计', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('被驳回的申请', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('审批通过率', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('我提交的审批', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('主管待审批任务', 'approval_pending_summary', 'approval_search'),
    OpsDomainCase('审批中心待办', 'approval_pending_summary', 'approval_search'),
]


FEEDBACK_CASES = [
    OpsDomainCase('最近有哪些 bug 反馈还没处理', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('待处理反馈', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('缺陷反馈列表', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('需求反馈统计', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('已修复 bug', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('已采纳需求', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('反馈类型分布', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('用户反馈报表', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('反馈优先级', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('我提交的反馈', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('本月反馈趋势', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('未处理缺陷数量', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('产品需求反馈有哪些', 'feedback_triage_summary', 'feedback_triage'),
    OpsDomainCase('反馈处理时长统计', 'feedback_triage_summary', 'feedback_triage'),
]


REPORT_CASES = [
    OpsDomainCase('系统概览', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('总览', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('整体情况怎么样', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('系统情况', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('做个报表', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('人力资源运营报表', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('HR 数据看板', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('管理驾驶舱', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('仪表盘指标', 'system_dashboard', 'dashboard_report'),
    OpsDomainCase('本周招聘报表', 'recruitment_overview', 'dashboard_report'),
    OpsDomainCase('招聘概览', 'recruitment_overview', 'dashboard_report'),
    OpsDomainCase('招聘进展报表', 'recruitment_overview', 'dashboard_report'),
    OpsDomainCase('招聘情况怎么样', 'recruitment_overview', 'dashboard_report'),
]


BOUNDARY_DIALOGUE_CASES = [
    '如何向员工解释考勤规则？',
    '员工转正沟通需要注意什么？',
    '什么是绩效校准？',
    '薪酬结构是什么意思？',
    '如何组织一次培训复盘？',
    '帮我润色：审批通过前请不要承诺具体薪资',
]


ALL_OPS_CASES = (
    ATTENDANCE_CASES
    + PERFORMANCE_CASES
    + PAYROLL_CASES
    + TRAINING_CASES
    + APPROVAL_CASES
    + FEEDBACK_CASES
    + REPORT_CASES
)


def test_module_six_case_count_at_least_100() -> None:
    assert len(ALL_OPS_CASES) >= 100


@pytest.mark.parametrize('case', ALL_OPS_CASES, ids=lambda c: c.message)
def test_operations_domain_queries_use_registered_readonly_tasks(case: OpsDomainCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.intent == case.intent
    assert decision.task_template_id == case.intent
    assert decision.risk_level == case.risk
    assert decision.requires_confirmation is False
    assert decision.router_result is not None
    assert case.skill in decision.router_result.candidate_skills


@pytest.mark.parametrize('case', PAYROLL_CASES, ids=lambda c: c.message)
def test_payroll_queries_are_high_risk_but_readonly(case: OpsDomainCase) -> None:
    decision = build_route_decision(case.message, _ctx(role='finance'))

    assert decision.intent == 'payroll_month_summary'
    assert decision.risk_level == 'high'
    assert decision.requires_confirmation is False
    assert decision.router_result is not None
    assert decision.router_result.candidate_skills == ['payroll_analysis']


@pytest.mark.parametrize('message', BOUNDARY_DIALOGUE_CASES)
def test_operations_domain_boundaries_keep_direct_answers_on_c_track(message: str) -> None:
    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
    assert decision.tool_plan == []

