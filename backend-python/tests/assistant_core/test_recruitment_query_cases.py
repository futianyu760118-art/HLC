"""Recruitment-query routing regression suite.

Module 2 from the automated assistant QA checklist: pure recruitment lookups
for jobs, resumes, candidates, interviews, and Offers should use the
registered ``recruitment_search`` skill with the right module instead of
falling through to employee/global search or generation tracks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from flask import Flask

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-recruitment-query', role=role, session_id='s-recruitment-query')


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


@dataclass(frozen=True)
class RecruitmentQueryCase:
    message: str
    module: str
    keyword: str | None = None
    status: str | None = None
    recent_days: int | None = None
    date_start: str | None = None
    date_end: str | None = None
    limit: int | None = None


RECRUITMENT_QUERY_CASES = [
    # Jobs: normal, fuzzy, status, keyword, and boundary wording.
    RecruitmentQueryCase('查一下开放中的岗位', 'jobs', status='open'),
    RecruitmentQueryCase('列出招聘中的岗位', 'jobs', status='open'),
    RecruitmentQueryCase('搜索 Java 工程师岗位', 'jobs', keyword='Java'),
    RecruitmentQueryCase('查看产品经理职位详情', 'jobs', keyword='产品经理'),
    RecruitmentQueryCase('现在有哪些岗位在招', 'jobs', status='open'),
    RecruitmentQueryCase('我们现在有哪些岗位在招人', 'jobs', status='open'),
    RecruitmentQueryCase('帮我看看后端开发职位', 'jobs', keyword='后端'),
    RecruitmentQueryCase('销售顾问岗位还有吗', 'jobs', keyword='销售顾问'),
    RecruitmentQueryCase('找一下 HRBP 职位', 'jobs', keyword='HR'),
    RecruitmentQueryCase('列出上海的岗位', 'jobs', keyword='上海'),
    RecruitmentQueryCase('看一下关闭的岗位', 'jobs', status='closed'),
    RecruitmentQueryCase('查查已暂停招聘的职位', 'jobs', status='closed'),
    RecruitmentQueryCase('有没有测试工程师岗位', 'jobs', keyword='测试'),
    RecruitmentQueryCase('看看运营专员岗位详情', 'jobs', keyword='运营专员'),
    RecruitmentQueryCase('本月新增了哪些招聘岗位', 'jobs', recent_days=30),
    RecruitmentQueryCase('近 7 天发布的岗位', 'jobs', recent_days=7),
    RecruitmentQueryCase('列出 5 个在招职位', 'jobs', status='open', limit=5),
    RecruitmentQueryCase('帮我查招聘需求里的前端岗', 'jobs', keyword='前端'),
    RecruitmentQueryCase('查看算法工程师 JD', 'jobs', keyword='算法工程师'),
    RecruitmentQueryCase('岗位列表给我看一下', 'jobs'),
    RecruitmentQueryCase('有哪些职位缺人', 'jobs', status='open'),
    RecruitmentQueryCase('技术部现在招什么岗位', 'jobs', keyword='技术部'),
    RecruitmentQueryCase('查一下深圳地区的招聘职位', 'jobs', keyword='深圳'),

    # Resumes: recent lists, keyword searches, named lookups, and boundary wording.
    RecruitmentQueryCase('查一下最近投递的简历', 'resumes', recent_days=30),
    RecruitmentQueryCase('列出本月收到的简历', 'resumes', recent_days=30),
    RecruitmentQueryCase('我们现在有多少份简历', 'resumes'),
    RecruitmentQueryCase('搜索 Java 简历', 'resumes', keyword='Java'),
    RecruitmentQueryCase('看看前端工程师简历', 'resumes', keyword='前端'),
    RecruitmentQueryCase('吴明华的简历', 'resumes', keyword='吴明华'),
    RecruitmentQueryCase('查看张三的简历详情', 'resumes', keyword='张三'),
    RecruitmentQueryCase('有没有李雷的投递记录', 'resumes', keyword='李雷'),
    RecruitmentQueryCase('最近 10 天投递后端岗位的简历', 'resumes', keyword='后端', recent_days=10),
    RecruitmentQueryCase('找一下产品经理简历', 'resumes', keyword='产品经理'),
    RecruitmentQueryCase('给我 8 份最近的简历', 'resumes', recent_days=30, limit=8),
    RecruitmentQueryCase('查查高分简历列表', 'resumes'),
    RecruitmentQueryCase('列出待筛选的简历', 'resumes', status='pending'),
    RecruitmentQueryCase('看看已通过初筛的简历', 'resumes', status='screening'),
    RecruitmentQueryCase('查一下被淘汰的简历', 'resumes', status='rejected'),
    RecruitmentQueryCase('搜索候选人王芳的简历', 'resumes', keyword='王芳'),
    RecruitmentQueryCase('投递到算法岗的简历有哪些', 'resumes', keyword='算法'),
    RecruitmentQueryCase('最近收到哪些销售简历', 'resumes', keyword='销售', recent_days=30),
    RecruitmentQueryCase('简历库里有没有赵六', 'resumes', keyword='赵六'),
    RecruitmentQueryCase('看一下待评估简历', 'resumes', status='pending'),
    RecruitmentQueryCase('近 3 天新来的简历名单', 'resumes', recent_days=3),
    RecruitmentQueryCase('帮我找 C++ 简历', 'resumes', keyword='C++'),
    RecruitmentQueryCase('列出 12 条简历记录', 'resumes', limit=12),

    # Candidates: list queries, named lookups, stage/status filters, and fuzzy wording.
    RecruitmentQueryCase('列出前端候选人', 'candidates', keyword='前端'),
    RecruitmentQueryCase('搜索张三候选人', 'candidates', keyword='张三'),
    RecruitmentQueryCase('我们现在有多少候选人', 'candidates'),
    RecruitmentQueryCase('有没有后端岗位的候选人', 'candidates', keyword='后端'),
    RecruitmentQueryCase('最近来应聘电子工程师的都有哪些人', 'candidates', keyword='电子工程师', recent_days=30),
    RecruitmentQueryCase('本周新增候选人名单', 'candidates', recent_days=7),
    RecruitmentQueryCase('查一下待沟通候选人', 'candidates', status='screening'),
    RecruitmentQueryCase('看看面试中的候选人', 'candidates', status='interview'),
    RecruitmentQueryCase('列出已淘汰候选人', 'candidates', status='rejected'),
    RecruitmentQueryCase('有哪些候选人通过初筛', 'candidates', status='screening'),
    RecruitmentQueryCase('销售岗位候选人有哪些', 'candidates', keyword='销售'),
    RecruitmentQueryCase('找一下王芳这个候选人', 'candidates', keyword='王芳'),
    RecruitmentQueryCase('查看候选人李雷资料', 'candidates', keyword='李雷'),
    RecruitmentQueryCase('最近 15 天新候选人', 'candidates', recent_days=15),
    RecruitmentQueryCase('帮我筛一下候选人名单', 'candidates'),
    RecruitmentQueryCase('候选人库里有没有赵六', 'candidates', keyword='赵六'),
    RecruitmentQueryCase('列出 20 个候选人', 'candidates', limit=20),
    RecruitmentQueryCase('Java 候选人都有哪些', 'candidates', keyword='Java'),
    RecruitmentQueryCase('查一下应聘产品经理的人', 'candidates', keyword='产品经理'),
    RecruitmentQueryCase('看看刚投递的候选人', 'candidates', recent_days=30),
    RecruitmentQueryCase('哪些候选人在等待反馈', 'candidates', status='screening'),
    RecruitmentQueryCase('有没有推荐状态的候选人', 'candidates', status='recommended'),
    RecruitmentQueryCase('近 5 天来应聘的人', 'candidates', recent_days=5),

    # Interviews: schedule/record lookup must remain read-only recruitment search.
    RecruitmentQueryCase('查看张三的面试记录', 'interviews', keyword='张三'),
    RecruitmentQueryCase('查一下明天的面试安排', 'interviews'),
    RecruitmentQueryCase('明天有多少场面试', 'interviews', status='scheduled', date_start='2026-05-30T00:00:00', date_end='2026-05-30T23:59:59'),
    RecruitmentQueryCase('本月有哪些面试', 'interviews', recent_days=30),
    RecruitmentQueryCase('列出待面试的安排', 'interviews', status='scheduled'),
    RecruitmentQueryCase('搜索 Java 岗位面试记录', 'interviews', keyword='Java'),
    RecruitmentQueryCase('看看今天的面试日程', 'interviews'),
    RecruitmentQueryCase('有没有王芳的复试记录', 'interviews', keyword='王芳'),
    RecruitmentQueryCase('列出已完成面试', 'interviews', status='completed'),
    RecruitmentQueryCase('查一下取消的面试', 'interviews', status='cancelled'),
    RecruitmentQueryCase('近 7 天面试记录', 'interviews', recent_days=7),
    RecruitmentQueryCase('销售候选人的面试安排', 'interviews', keyword='销售'),
    RecruitmentQueryCase('查看二面记录', 'interviews'),
    RecruitmentQueryCase('面试列表给我看一下', 'interviews'),
    RecruitmentQueryCase('明天上午有哪些面试', 'interviews'),
    RecruitmentQueryCase('候选人李雷面试到哪一步', 'interviews', keyword='李雷'),
    RecruitmentQueryCase('最近 3 场面试', 'interviews', limit=3),
    RecruitmentQueryCase('看看待评价的面试', 'interviews', status='pending'),
    RecruitmentQueryCase('查查技术面试记录', 'interviews', keyword='技术'),
    RecruitmentQueryCase('本周面试排期', 'interviews', recent_days=7),
    RecruitmentQueryCase('有没有产品岗的面试', 'interviews', keyword='产品'),

    # Offers: Offer lookup, approval-progress lookup, status filters, and named lookups.
    RecruitmentQueryCase('列出待发 Offer', 'offers', status='pending'),
    RecruitmentQueryCase('查看王五的 Offer', 'offers', keyword='王五'),
    RecruitmentQueryCase('Offer 审批到哪一步了', 'offers'),
    RecruitmentQueryCase('看看招聘中的 offer', 'offers'),
    RecruitmentQueryCase('查一下已接受 Offer', 'offers', status='accepted'),
    RecruitmentQueryCase('列出已拒绝的 Offer', 'offers', status='rejected'),
    RecruitmentQueryCase('有没有张三的 offer 记录', 'offers', keyword='张三'),
    RecruitmentQueryCase('本月发出的 Offer', 'offers', recent_days=30),
    RecruitmentQueryCase('近 10 天 Offer 列表', 'offers', recent_days=10),
    RecruitmentQueryCase('Java 岗位 Offer 有哪些', 'offers', keyword='Java'),
    RecruitmentQueryCase('查看待审批 Offer', 'offers', status='pending'),
    RecruitmentQueryCase('Offer 列表给我看一下', 'offers'),
    RecruitmentQueryCase('查一下候选人李雷的录用通知', 'offers', keyword='李雷'),
    RecruitmentQueryCase('有没有销售岗位的 Offer', 'offers', keyword='销售'),
    RecruitmentQueryCase('已撤回的 Offer 有哪些', 'offers', status='cancelled'),
    RecruitmentQueryCase('看看还没确认的 Offer', 'offers', status='pending'),
    RecruitmentQueryCase('王芳的录用进度怎么样', 'offers', keyword='王芳'),
    RecruitmentQueryCase('近 5 条 Offer 记录', 'offers', limit=5),
    RecruitmentQueryCase('查一下 offer pending 的记录', 'offers', status='pending'),
    RecruitmentQueryCase('有没有产品经理的录用通知', 'offers', keyword='产品经理'),
]


def test_recruitment_query_case_count_is_at_least_100() -> None:
    assert len(RECRUITMENT_QUERY_CASES) >= 100


@pytest.mark.parametrize('case', RECRUITMENT_QUERY_CASES, ids=lambda c: c.message)
def test_recruitment_queries_use_recruitment_search(monkeypatch, case: RecruitmentQueryCase) -> None:
    """招聘查询应直接使用招聘域 skill，并保持只读数据查询轨道。"""
    monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
    monkeypatch.setenv('ASSISTANT_ENABLE_RECENT_RECRUITMENT_HOTPATH_OUTSIDE_APP', '1')
    monkeypatch.setattr(
        'services.assistant_core.intent_router.legacy_planner.business_now',
        lambda: datetime(2026, 5, 29, 9, 0, 0),
        raising=False,
    )

    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.tool_plan, decision.reason
    plan = decision.tool_plan[0]
    assert plan.tool == 'recruitment_search'
    assert plan.purpose == 'query'
    assert plan.risk_level == 'low'
    assert plan.input['module'] == case.module
    if case.keyword:
        assert plan.input.get('keyword') == case.keyword
    if case.status:
        assert plan.input.get('status') == case.status
    if case.recent_days:
        assert plan.input.get('date_range', {}).get('recent_days') == case.recent_days
    if case.date_start:
        assert plan.input.get('date_range', {}).get('start') == case.date_start
    if case.date_end:
        assert plan.input.get('date_range', {}).get('end') == case.date_end
    if case.limit:
        assert plan.input.get('limit') == case.limit


def test_recruitment_count_only_returns_total_without_entity_list(model_db) -> None:
    from models import Candidate
    from services.assistant_core.skills import skill_recruitment_search

    model_db.session.add_all([
        Candidate(id='c-count-1', name='候选人一', status='screening'),
        Candidate(id='c-count-2', name='候选人二', status='screening'),
        Candidate(id='c-count-3', name='候选人三', status='interview'),
    ])
    model_db.session.commit()

    result = skill_recruitment_search(
        {'module': 'candidates', 'limit': 1, 'count_only': True},
        _ctx(),
    )

    assert result['rows_count'] == 3
    assert result['metrics']['total'] == 3
    assert result['entities'] == []
    assert '候选人 3 条' in result['summary_hint']


def test_recruitment_match_matrix_emits_structured_follow_up_actions(model_db) -> None:
    from models import Candidate, Interview, Job, Resume
    from services.assistant_core.skills import skill_recruitment_match_matrix

    job = Job(id='job-actions-ee', title='电子工程师', status='open', department='研发部')
    resume_top = Resume(
        id='resume-actions-top',
        job_id=job.id,
        candidate_name='邓浩',
        file_url='/uploads/denghao.pdf',
        ai_analysis={'score': 92, 'matchDegree': 90, 'strengths': ['硬件调试'], 'weaknesses': ['英文表达待复核']},
        created_at=datetime(2026, 5, 30, 9, 0, 0),
    )
    resume_second = Resume(
        id='resume-actions-second',
        job_id=job.id,
        candidate_name='杨琳',
        file_url='/uploads/yanglin.pdf',
        ai_analysis={'score': 86, 'matchDegree': 84, 'strengths': ['量产经验'], 'weaknesses': ['独立方案设计经验不足']},
        created_at=datetime(2026, 5, 29, 9, 0, 0),
    )
    candidate_top = Candidate(
        id='candidate-actions-top',
        resume_id=resume_top.id,
        job_id=job.id,
        name='邓浩',
        status='interview',
        source='内推',
        created_at=datetime(2026, 5, 30, 10, 0, 0),
    )
    candidate_second = Candidate(
        id='candidate-actions-second',
        resume_id=resume_second.id,
        job_id=job.id,
        name='杨琳',
        status='screening',
        source='猎聘',
        created_at=datetime(2026, 5, 29, 10, 0, 0),
    )
    interview = Interview(
        id='interview-actions-top',
        job_id=job.id,
        resume_id=resume_top.id,
        scheduled_at=datetime(2026, 6, 3, 15, 0, 0),
        status='passed',
    )
    model_db.session.add_all([job, resume_top, resume_second, candidate_top, candidate_second, interview])
    model_db.session.commit()

    result = skill_recruitment_match_matrix({'keyword': '电子工程师'}, _ctx())

    actions_widget = next(widget for widget in result['widgets'] if widget['type'] == 'follow_up_actions')
    labels = [action['label'] for action in actions_widget['actions']]
    assert any('邓浩' in label for label in labels)
    assert any('杨琳' in label for label in labels)
    schedule_action = next(action for action in actions_widget['actions'] if '安排' in action['label'])
    assert schedule_action['requiresConfirmation'] is True
    assert schedule_action['payload'].startswith('给邓浩安排')

