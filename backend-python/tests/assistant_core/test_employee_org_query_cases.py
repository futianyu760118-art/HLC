"""Employee and organization query routing cases for the assistant.

Module 5 verifies that employee/org/lifecycle questions are treated as
deterministic read-only data queries, rather than generic dialogue,
recruitment lookup, or candidate evidence generation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-employee-org', role=role, session_id='sess-employee-org')


@dataclass(frozen=True)
class EmployeeOrgQueryCase:
    message: str
    tool: str
    intent: str
    keyword: str | None = None
    status: str | None = None
    module: str | None = None


EMPLOYEE_PROFILE_CASES = [
    EmployeeOrgQueryCase('查一下张三的员工档案', 'employee_search', 'employee_lookup', keyword='张三'),
    EmployeeOrgQueryCase('张三在哪个部门', 'employee_search', 'employee_lookup', keyword='张三'),
    EmployeeOrgQueryCase('李四的入职时间是什么', 'employee_search', 'employee_lookup', keyword='李四'),
    EmployeeOrgQueryCase('王五是什么岗位', 'employee_search', 'employee_lookup', keyword='王五'),
    EmployeeOrgQueryCase('赵六的员工信息', 'employee_search', 'employee_lookup', keyword='赵六'),
    EmployeeOrgQueryCase('员工陈晨资料', 'employee_search', 'employee_lookup', keyword='陈晨'),
    EmployeeOrgQueryCase('看一下何娜的工号', 'employee_search', 'employee_lookup', keyword='何娜'),
    EmployeeOrgQueryCase('孙悦属于哪个部门', 'employee_search', 'employee_lookup', keyword='孙悦'),
    EmployeeOrgQueryCase('郑伟现在什么职位', 'employee_search', 'employee_lookup', keyword='郑伟'),
    EmployeeOrgQueryCase('刘洋的岗位是什么', 'employee_search', 'employee_lookup', keyword='刘洋'),
    EmployeeOrgQueryCase('唐佳什么时候入职', 'employee_search', 'employee_lookup', keyword='唐佳'),
    EmployeeOrgQueryCase('马超的部门和岗位', 'employee_search', 'employee_lookup', keyword='马超'),
    EmployeeOrgQueryCase('胡静是不是在职', 'employee_search', 'employee_lookup', keyword='胡静'),
    EmployeeOrgQueryCase('许琳员工编号是多少', 'employee_search', 'employee_lookup', keyword='许琳'),
    EmployeeOrgQueryCase('查工号 E001 的员工', 'employee_search', 'employee_lookup', keyword='E001'),
    EmployeeOrgQueryCase('搜索邮箱 amy@example.com 对应员工', 'employee_search', 'employee_lookup', keyword='amy@example.com'),
    EmployeeOrgQueryCase('手机号 13812345678 是哪个员工', 'employee_search', 'employee_lookup', keyword='13812345678'),
    EmployeeOrgQueryCase('查看 HRBP 王芳的员工档案', 'employee_search', 'employee_lookup', keyword='王芳'),
    EmployeeOrgQueryCase('帮我找一下销售经理高强的员工信息', 'employee_search', 'employee_lookup', keyword='高强'),
    EmployeeOrgQueryCase('研发部张伟的岗位信息', 'employee_search', 'employee_lookup', keyword='张伟'),
    EmployeeOrgQueryCase('查一下在职员工', 'employee_search', 'employee_lookup', status='active'),
    EmployeeOrgQueryCase('列出所有在职员工', 'employee_search', 'employee_lookup', status='active'),
    EmployeeOrgQueryCase('查看试用期员工名单', 'employee_search', 'employee_lookup', status='probation'),
    EmployeeOrgQueryCase('试用期员工有哪些', 'employee_search', 'employee_lookup', status='probation'),
    EmployeeOrgQueryCase('待入职员工有哪些', 'employee_search', 'employee_lookup', status='pending_onboard'),
    EmployeeOrgQueryCase('本月待入职员工有哪些', 'employee_search', 'employee_lookup', status='pending_onboard'),
    EmployeeOrgQueryCase('员工状态为已离职的名单', 'employee_search', 'employee_lookup', status='resigned'),
    EmployeeOrgQueryCase('列出 resigned 状态员工', 'employee_search', 'employee_lookup', status='resigned'),
    EmployeeOrgQueryCase('暂停状态员工有哪些', 'employee_search', 'employee_lookup', status='inactive'),
    EmployeeOrgQueryCase('哪些员工还没正式入职', 'employee_search', 'employee_lookup', status='pending_onboard'),
    EmployeeOrgQueryCase('正式员工名单', 'employee_search', 'employee_lookup', status='active'),
    EmployeeOrgQueryCase('当前员工花名册', 'employee_search', 'employee_lookup'),
    EmployeeOrgQueryCase('员工列表', 'employee_search', 'employee_lookup'),
]


DEPARTMENT_ORG_CASES = [
    EmployeeOrgQueryCase('组织架构', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('公司组织架构怎么样', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('部门列表给我看一下', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('有哪些部门', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('部门人数分布', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('研发部有多少人', 'organization_search', 'organization_overview', keyword='研发部'),
    EmployeeOrgQueryCase('销售部有哪些人', 'organization_search', 'organization_overview', keyword='销售部'),
    EmployeeOrgQueryCase('财务部人员分布', 'organization_search', 'organization_overview', keyword='财务部'),
    EmployeeOrgQueryCase('技术中心下面有哪些部门', 'organization_search', 'organization_overview', keyword='技术中心'),
    EmployeeOrgQueryCase('查一下市场部', 'organization_search', 'organization_overview', keyword='市场部'),
    EmployeeOrgQueryCase('客服部负责人是谁', 'organization_search', 'organization_overview', keyword='客服部'),
    EmployeeOrgQueryCase('部门编码 RD 是哪个部门', 'organization_search', 'organization_overview', keyword='RD'),
    EmployeeOrgQueryCase('岗位体系', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('岗位序列有哪些', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('职位体系给我看一下', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('研发部有哪些岗位', 'organization_search', 'organization_overview', keyword='研发部'),
    EmployeeOrgQueryCase('销售岗位体系是什么', 'organization_search', 'organization_overview', keyword='销售'),
    EmployeeOrgQueryCase('产品经理属于哪个岗位序列', 'organization_search', 'organization_overview', keyword='产品经理'),
    EmployeeOrgQueryCase('主管级岗位有哪些', 'organization_search', 'organization_overview', keyword='主管'),
    EmployeeOrgQueryCase('部门有哪些人', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('公司有哪些组织单元', 'organization_search', 'organization_overview'),
    EmployeeOrgQueryCase('各部门人数是多少', 'organization_search', 'organization_overview'),
]


EMPLOYEE_LIFECYCLE_CASES = [
    EmployeeOrgQueryCase('入职进度', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('入职任务完成情况', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('新员工入职清单', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('张三的入职任务完成了吗', 'system_search', 'employee_lifecycle_query', keyword='张三', module='lifecycle'),
    EmployeeOrgQueryCase('李四入职资料是否齐全', 'system_search', 'employee_lifecycle_query', keyword='李四', module='lifecycle'),
    EmployeeOrgQueryCase('待入职人员的入职任务', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('本周入职员工进度', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('谁还没完成入职培训', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('快到转正的员工', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('谁快到转正', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('转正审批有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('试用期到期员工', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('张三的转正状态', 'system_search', 'employee_lifecycle_query', keyword='张三', module='lifecycle'),
    EmployeeOrgQueryCase('李四试用期什么时候结束', 'system_search', 'employee_lifecycle_query', keyword='李四', module='lifecycle'),
    EmployeeOrgQueryCase('王五的转正审批到哪一步', 'system_search', 'employee_lifecycle_query', keyword='王五', module='lifecycle'),
    EmployeeOrgQueryCase('转正未通过的人有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('离职员工名单', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('最近离职员工', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('离职交接未完成的员工', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('张三的离职原因', 'system_search', 'employee_lifecycle_query', keyword='张三', module='lifecycle'),
    EmployeeOrgQueryCase('李四离职审批状态', 'system_search', 'employee_lifecycle_query', keyword='李四', module='lifecycle'),
    EmployeeOrgQueryCase('本月离职人员有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('合同快到期的员工', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('劳动合同即将到期名单', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('张三的合同情况', 'system_search', 'employee_lifecycle_query', keyword='张三', module='lifecycle'),
    EmployeeOrgQueryCase('王五的合同编号是多少', 'system_search', 'employee_lifecycle_query', keyword='王五', module='lifecycle'),
    EmployeeOrgQueryCase('无固定期限合同员工有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('合同待续签的人员', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('员工异动记录', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('张三最近有没有调岗', 'system_search', 'employee_lifecycle_query', keyword='张三', module='lifecycle'),
    EmployeeOrgQueryCase('调薪异动审批有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('员工申请记录', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('王芳的请假申请记录', 'system_search', 'employee_lifecycle_query', keyword='王芳', module='lifecycle'),
    EmployeeOrgQueryCase('我的员工申请到哪一步了', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('待处理的调岗申请', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('员工合同台账', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('入职审批有哪些', 'system_search', 'employee_lifecycle_query', module='lifecycle'),
    EmployeeOrgQueryCase('孙悦从候选人到入职现在关联到了哪些模块？', 'system_search', 'employee_lifecycle_query', keyword='孙悦', module='all'),
    EmployeeOrgQueryCase('孙悦从简历录入到入职、培训、薪资现在关联到了哪些模块？', 'system_search', 'employee_lifecycle_query', keyword='孙悦', module='all'),
    EmployeeOrgQueryCase('李四的转正、培训和调薪链路现在有哪些数据？', 'system_search', 'employee_lifecycle_query', keyword='李四', module='all'),
]


BOUNDARY_CASES = [
    EmployeeOrgQueryCase('吴明华的简历', 'recruitment_search', 'recruitment_resumes_query', keyword='吴明华', module='resumes'),
    EmployeeOrgQueryCase('查一下候选人张三资料', 'recruitment_search', 'recruitment_candidates_query', keyword='张三', module='candidates'),
    EmployeeOrgQueryCase('搜索 Java 工程师岗位', 'recruitment_search', 'recruitment_jobs_query', keyword='Java', module='jobs'),
    EmployeeOrgQueryCase('什么是无固定期限劳动合同？', '', 'general_dialogue'),
    EmployeeOrgQueryCase('如何组织一次有效的离职交接？', '', 'general_dialogue'),
    EmployeeOrgQueryCase('如何设计一份新员工入职清单？', '', 'general_dialogue'),
    EmployeeOrgQueryCase('请解释岗位职级和岗位序列的区别', '', 'general_dialogue'),
    EmployeeOrgQueryCase('帮我润色：员工合同到期前需要提前提醒', '', 'text_transform'),
    EmployeeOrgQueryCase('总结下面的 HR 政策说明：试用期内需完成导师评估和转正申请', '', 'text_transform'),
    EmployeeOrgQueryCase('翻译这句：employee lifecycle management', '', 'text_transform'),
]


ALL_EMPLOYEE_ORG_CASES = (
    EMPLOYEE_PROFILE_CASES
    + DEPARTMENT_ORG_CASES
    + EMPLOYEE_LIFECYCLE_CASES
    + BOUNDARY_CASES
)


def test_module_five_case_count_at_least_100() -> None:
    assert len(ALL_EMPLOYEE_ORG_CASES) >= 100


@pytest.mark.parametrize('case', EMPLOYEE_PROFILE_CASES, ids=lambda c: c.message)
def test_employee_profile_queries_use_employee_search(case: EmployeeOrgQueryCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.intent == case.intent
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == case.tool
    assert decision.tool_plan[0].purpose == 'query'
    if case.keyword:
        assert decision.tool_plan[0].input.get('keyword') == case.keyword
    if case.status:
        assert decision.tool_plan[0].input.get('status') == case.status


@pytest.mark.parametrize('case', DEPARTMENT_ORG_CASES, ids=lambda c: c.message)
def test_department_and_position_queries_use_organization_search(case: EmployeeOrgQueryCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.intent == case.intent
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == case.tool
    assert decision.tool_plan[0].purpose == 'query'
    assert decision.tool_plan[0].input.get('include_stats') is True
    if case.keyword:
        assert decision.tool_plan[0].input.get('keyword') == case.keyword


@pytest.mark.parametrize('case', EMPLOYEE_LIFECYCLE_CASES, ids=lambda c: c.message)
def test_employee_lifecycle_queries_use_system_search_lifecycle(case: EmployeeOrgQueryCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.intent == case.intent
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == case.tool
    assert decision.tool_plan[0].input.get('module') == case.module
    if case.keyword:
        assert decision.tool_plan[0].input.get('keyword') == case.keyword


@pytest.mark.parametrize('case', BOUNDARY_CASES, ids=lambda c: c.message)
def test_employee_org_boundaries_do_not_steal_other_tracks(case: EmployeeOrgQueryCase) -> None:
    decision = build_route_decision(case.message, _ctx())

    assert decision.intent == case.intent
    if case.tool:
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.tool_plan[0].tool == case.tool
        if case.module:
            assert decision.tool_plan[0].input.get('module') == case.module
    else:
        assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
        assert decision.tool_plan == []


def test_employee_role_self_query_still_uses_permission_checked_employee_search() -> None:
    ctx = AssistantContext(
        user_id='u-employee',
        role='employee',
        session_id='sess-employee-self',
        user_employee_id='emp-self',
    )

    decision = build_route_decision('查一下我的员工档案', ctx)

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.tool_plan[0].tool == 'employee_search'
    assert decision.tool_plan[0].input.get('keyword') in (None, '', '我的')


def test_employee_sensitive_salary_query_is_not_routed_to_employee_profile_lookup() -> None:
    decision = build_route_decision('查一下张三的薪酬档案', _ctx(role='employee'))

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.intent != 'employee_lookup'
    assert decision.risk_level == 'high'


def test_cross_module_lifecycle_query_with_salary_and_training_keeps_full_scope() -> None:
    decision = build_route_decision('孙悦从简历录入到入职、培训、薪资现在关联到了哪些模块？', _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.intent == 'employee_lifecycle_query'
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == 'system_search'
    assert decision.tool_plan[0].input.get('module') == 'all'
    assert decision.tool_plan[0].input.get('keyword') == '孙悦'


def test_multi_topic_employee_chain_query_is_not_stolen_by_training_or_payroll() -> None:
    decision = build_route_decision('李四的转正、培训和调薪链路现在有哪些数据？', _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.intent == 'employee_lifecycle_query'
    assert decision.tool_plan
    assert decision.tool_plan[0].tool == 'system_search'
    assert decision.tool_plan[0].input.get('module') == 'all'
    assert decision.tool_plan[0].input.get('keyword') == '李四'

