"""Navigation-module assistant matrix tests.

The left sidebar is the product's most concrete module map.  This suite turns
each small navigation item into 100 natural-language assistant cases: 20
scenarios, with 5 wording variants per scenario.  It is intentionally generated
from compact specs so adding a module or changing the expected skill stays
maintainable.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext
from services.hrm_module_catalog import all_module_specs


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-nav-matrix', role=role, session_id='s-nav-matrix')


@dataclass(frozen=True)
class NavModuleSpec:
    group: str
    label: str
    expected_tool: str
    role: str = 'hr_admin'


NAV_MODULE_SPECS = [
    NavModuleSpec(
        spec.group,
        spec.label,
        spec.ai_skill,
        role='finance' if spec.risk == 'high' else 'hr_admin',
    )
    for spec in all_module_specs()
]


SCENARIO_VARIANTS = [
    ('data', ['查看{label}列表', '列出{label}记录', '打开{label}数据', '帮我看一下{label}', '{label}有哪些记录']),
    ('data', ['{label}现在有多少条', '统计{label}数量', '现在{label}总数是多少', '{label}一共有多少', '帮我数一下{label}']),
    ('data', ['本月{label}情况', '这个月{label}数据', '近30天{label}记录', '最近一个月{label}', '{label}本月统计']),
    ('data', ['今天{label}情况', '今日{label}记录', '查看今天的{label}', '{label}今天有多少', '今天需要关注哪些{label}']),
    ('data', ['本周{label}进展', '这周{label}情况', '近7天{label}列表', '帮我看本周{label}', '{label}本周统计']),
    ('data', ['待处理{label}', '未完成的{label}', '{label}里待跟进的记录', '{label}待办有哪些', '看看待处理状态的{label}']),
    ('data', ['已完成{label}', '完成状态的{label}', '{label}已结束记录', '查看已处理{label}', '{label}历史完成情况']),
    ('data', ['按状态统计{label}', '{label}状态分布', '{label}分布情况', '给我{label}状态概览', '{label}各状态数量']),
    ('data', ['按部门看{label}', '研发部{label}情况', '销售部{label}有哪些', '{label}按部门分布', '各部门{label}对比']),
    ('data', ['搜索{label}里的张三', '查张三相关{label}', '{label}中有没有张三', '帮我找张三的{label}', '张三在{label}里的记录']),
    ('data', ['搜索{label}里的电子工程师', '电子工程师相关{label}', '{label}中有没有电子工程师', '帮我找电子工程师的{label}', '电子工程师在{label}里的记录']),
    ('data', ['{label}详情给我看', '查看{label}明细', '{label}明细数据', '打开{label}详情', '看一下{label}详情页数据']),
    ('data', ['{label}报表', '生成{label}查询报表', '查看{label}统计报表', '给我{label}概览报表', '{label}运营报表']),
    ('data', ['{label}趋势', '最近{label}趋势怎么样', '查看{label}变化趋势', '{label}趋势统计', '{label}走势概览']),
    ('data', ['{label}排名', '{label}TOP10', '按数量排名{label}', '查看{label}靠前记录', '{label}排序给我看']),
    ('data', ['异常{label}', '{label}异常记录', '需要关注的{label}', '{label}风险记录', '帮我找异常的{label}']),
    ('data', ['{label}筛选一下', '帮我筛{label}', '{label}过滤条件怎么看', '查看筛选后的{label}', '{label}条件查询']),
    ('data', ['{label}看板', '打开{label}看板数据', '{label}核心指标', '{label}关键指标', '汇总{label}指标']),
    ('boundary', ['什么是{label}', '请解释{label}的业务含义', '{label}模块通常做什么', '怎么理解{label}', '{label}和日常 HR 工作有什么关系']),
    ('forbidden', ['删除{label}第一条记录', '把{label}里的第一条移除', '批量删除{label}', '修改{label}里的第一条数据', '直接更新{label}状态']),
]


@dataclass(frozen=True)
class NavModuleCase:
    spec: NavModuleSpec
    scenario_kind: str
    scenario_index: int
    variant_index: int
    message: str


def _all_cases() -> list[NavModuleCase]:
    cases: list[NavModuleCase] = []
    for spec in NAV_MODULE_SPECS:
        for scenario_index, (kind, variants) in enumerate(SCENARIO_VARIANTS, start=1):
            assert len(variants) == 5
            for variant_index, template in enumerate(variants, start=1):
                cases.append(NavModuleCase(
                    spec=spec,
                    scenario_kind=kind,
                    scenario_index=scenario_index,
                    variant_index=variant_index,
                    message=template.format(label=spec.label),
                ))
    return cases


NAV_MODULE_CASES = _all_cases()


def _tools_for(decision) -> list[str]:
    tools: list[str] = []
    if decision.tool_plan:
        tools.extend(plan.tool for plan in decision.tool_plan)
    if decision.router_result is not None:
        tools.extend(decision.router_result.candidate_skills or [])
    return tools


def test_nav_module_matrix_shape_matches_sidebar() -> None:
    assert len(NAV_MODULE_SPECS) == 36
    assert len(SCENARIO_VARIANTS) == 20
    assert all(len(v) == 5 for _, v in SCENARIO_VARIANTS)
    assert len(NAV_MODULE_CASES) == 3600
    for spec in NAV_MODULE_SPECS:
        assert sum(1 for case in NAV_MODULE_CASES if case.spec == spec) == 100


@pytest.mark.parametrize(
    'case',
    NAV_MODULE_CASES,
    ids=lambda c: f'{c.spec.label}-{c.scenario_index:02d}-{c.variant_index}',
)
def test_nav_module_matrix_routes_to_expected_assistant_track(monkeypatch, case: NavModuleCase) -> None:
    monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
    decision = build_route_decision(case.message, _ctx(role=case.spec.role))

    if case.scenario_kind == 'boundary':
        assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
        assert decision.tool_plan == []
        return

    if case.scenario_kind == 'forbidden':
        assert decision.task_type == 'forbidden'
        assert decision.requires_confirmation is True
        return

    if decision.route_track == 'COMPOSITE':
        assert decision.task_type == 'composite'
        assert case.spec.expected_tool in _tools_for(decision)
        return

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.requires_confirmation is False
    assert case.spec.expected_tool in _tools_for(decision)

