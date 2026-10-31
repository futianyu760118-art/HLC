"""Candidate evidence-analysis routing regression suite.

Module 3 from the automated assistant QA checklist: candidate assessment,
candidate comparison, job-fit judgment, and differentiated interview-question
generation must stay on the evidence-grounded generation track. Pure record
lookups remain read-only recruitment queries.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-candidate-evidence', role=role, session_id='s-candidate-evidence')


@dataclass(frozen=True)
class EvidenceAnalysisCase:
    message: str
    intent: str
    required_context: str


NAMED_ASSESSMENT_CASES = [
    EvidenceAnalysisCase('吴明华这个人怎么样', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('分析一下张三的录用风险', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('评价李四的项目经历', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('评估王芳的稳定性', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('判断赵六能不能进入下一轮', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('刘洋这位候选人适合继续跟进吗', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('陈晨录用风险高不高', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('周敏的候选人优劣势', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('黄磊是否建议发 Offer', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('高春喜该不该淘汰', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('李博豪是否值得重点争取', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('孙悦的风险点和亮点', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('郑伟的综合表现如何', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('何娜这个候选人的胜任力怎么样', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('马超是否建议进入终面', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('唐佳的匹配度和风险', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('罗强是否适合储备', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('胡静的背景靠谱吗', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('蒋涛的录用建议', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('许琳候选人质量如何', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('帮我判断吴明华是否值得推进', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('帮我评估张三的面试表现', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('给李四做一个候选人画像', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('从证据看王芳能不能录用', 'person_assessment', 'named_subject_evidence'),
    EvidenceAnalysisCase('基于资料分析赵六是否可靠', 'person_assessment', 'named_subject_evidence'),
]


EVIDENCE_QUESTION_CASES = [
    EvidenceAnalysisCase('吴明华有没有面试记录', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('张三的简历亮点是什么', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('李四的面试反馈有哪些风险', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('王芳的 Offer 进度有没有异常', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('赵六的投递记录说明了什么', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('刘洋的项目经历有哪些证据', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('陈晨有没有复试反馈', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('周敏的简历和面试记录怎么样', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('黄磊的岗位匹配证据有哪些', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('高春喜的面评结论是什么', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('李博豪的候选人状态为什么停在初筛', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('孙悦的推荐理由来自哪些记录', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('郑伟有没有薪资相关的 Offer 记录', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('何娜的面试问题集中在哪里', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('马超的简历是否提到管理经验', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('唐佳的背调记录有吗', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('罗强有哪些来源证据', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('胡静的淘汰原因记录了吗', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('蒋涛的面试官反馈是什么', 'person_evidence_answer', 'named_subject_evidence'),
    EvidenceAnalysisCase('许琳的证据链完整吗', 'person_evidence_answer', 'named_subject_evidence'),
]


JOB_FIT_CASES = [
    EvidenceAnalysisCase('吴明华是否适合 Java 后端岗位', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('张三能不能胜任销售经理职位', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('李四和产品经理岗位匹配吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('王芳满足前端工程师要求吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('赵六符合电子工程师岗位标准吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('刘洋对运营专员岗位适配度如何', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('陈晨能否达标算法岗要求', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('周敏匹配客服主管岗位吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('黄磊是否满足测试工程师条件', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('高春喜适合招聘 HRBP 吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('李博豪能胜任数据分析师职位吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('孙悦是否符合会计岗位门槛', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('郑伟对销售顾问岗位匹配度高吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('何娜能不能做培训专员', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('马超适不适合项目经理岗位', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('唐佳是否符合岗位任职资格', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('罗强能否匹配高级后端要求', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('胡静适合转到候选岗位吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('蒋涛满足 Java 工程师硬性要求吗', 'candidate_job_fit', 'named_subject_evidence'),
    EvidenceAnalysisCase('许琳是否胜任人事专员岗位', 'candidate_job_fit', 'named_subject_evidence'),
]


INTERVIEW_QUESTION_CASES = [
    EvidenceAnalysisCase('给吴明华生成差异化面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('基于张三简历出 5 道面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('针对李四的项目经历设计追问', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('为王芳准备复试问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('根据赵六的风险点生成面试问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('帮刘洋设计技术面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('给陈晨出一组行为面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('基于周敏的面试记录补充追问', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('针对黄磊设计岗位匹配追问', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('为高春喜生成终面问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('李博豪的简历适合问哪些问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('孙悦需要哪些差异化面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('郑伟下一轮面试该重点问什么', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('何娜的项目经历要怎么追问', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('马超的风险点请转成面试问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('唐佳生成 8 道结构化面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('罗强适合出哪些追问', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('胡静面试时需要验证哪些点', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('蒋涛请给一份面试提纲', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('许琳帮我设计二面问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('如何针对吴明华设计差异化面试题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('请按张三的简历生成追问清单', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('帮我围绕李四的短板出题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('为王芳生成岗位胜任力问题', 'interview_questions', 'named_subject_evidence'),
    EvidenceAnalysisCase('赵六的面试题要覆盖哪些风险', 'interview_questions', 'named_subject_evidence'),
]


COMPARISON_CASES = [
    EvidenceAnalysisCase('对比吴明华和张三', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('比较李四和王芳的候选人质量', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('吴明华和李四谁更适合 Java 后端岗位', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('张三、李四、王芳做个排序', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('把赵六和刘洋的简历做对比', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('陈晨与周敏哪个录用风险更低', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('黄磊和高春喜谁更值得推进', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('李博豪、孙悦、郑伟分别有什么优劣势', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('何娜和马超的岗位匹配度比较一下', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('唐佳和罗强谁更适合终面', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('胡静、蒋涛、许琳做候选人对比报告', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('比较吴明华、张三和李四的面试表现', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('王芳与赵六哪个更适合销售岗位', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('刘洋和陈晨的风险点差异是什么', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('周敏和黄磊请按推荐优先级排序', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('高春喜与李博豪哪个更像合适人选', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('孙悦、郑伟谁的证据更完整', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('何娜和唐佳的短板差异', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('罗强与胡静谁更应该发 Offer', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('蒋涛和许琳哪个更适合储备', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('张三和王芳谁的稳定性更好', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('李四与赵六哪个更符合岗位要求', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('吴明华、刘洋、陈晨哪个优先邀约', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('周敏和高春喜做一份差异报告', 'candidate_compare', 'named_subjects_evidence'),
    EvidenceAnalysisCase('李博豪和孙悦的录用建议对比', 'candidate_compare', 'named_subjects_evidence'),
]


CANDIDATE_EVIDENCE_ANALYSIS_CASES = (
    NAMED_ASSESSMENT_CASES
    + EVIDENCE_QUESTION_CASES
    + JOB_FIT_CASES
    + INTERVIEW_QUESTION_CASES
    + COMPARISON_CASES
)


PURE_LOOKUP_BOUNDARY_CASES = [
    ('吴明华的简历', 'resumes'),
    ('查看张三的面试记录', 'interviews'),
    ('查一下李四的 Offer', 'offers'),
    ('候选人王芳资料', 'candidates'),
    ('搜索赵六候选人', 'candidates'),
]


def test_candidate_evidence_analysis_case_count_is_at_least_100() -> None:
    assert len(CANDIDATE_EVIDENCE_ANALYSIS_CASES) >= 100


@pytest.mark.parametrize('case', CANDIDATE_EVIDENCE_ANALYSIS_CASES, ids=lambda c: c.message)
def test_candidate_evidence_analysis_uses_grounded_generation(monkeypatch, case: EvidenceAnalysisCase) -> None:
    """候选人分析/对比/出题必须走 B 轨，并声明所需证据上下文。"""
    monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)

    decision = build_route_decision(case.message, _ctx())

    assert decision.route_track == 'B_GENERATION', decision.reason
    assert decision.task_type == 'generation'
    assert decision.intent == case.intent
    assert case.required_context in decision.required_context
    assert decision.generation_plan is not None
    assert decision.requires_confirmation is False


@pytest.mark.parametrize('message,module', PURE_LOOKUP_BOUNDARY_CASES)
def test_pure_candidate_record_lookups_remain_read_only_recruitment_queries(monkeypatch, message: str, module: str) -> None:
    """纯查记录不应被扩大后的证据分析规则误抢到生成轨。"""
    monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)

    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'A_DATA_ACTION'
    assert decision.task_type == 'data_query'
    assert decision.tool_plan[0].tool == 'recruitment_search'
    assert decision.tool_plan[0].input['module'] == module


def test_named_subjects_evidence_context_loads_each_named_candidate(monkeypatch) -> None:
    """显式多候选人对比需要分别加载每个人的证据包。"""
    from services.assistant_core import legacy_orchestrator as orchestrator

    calls = []

    def fake_execute(self, tool, params, ctx):
        calls.append((tool, params))
        keyword = params.get('keyword') or params.get('candidate_id') or params.get('resume_id')
        return {
            'ok': True,
            'tool': tool,
            'data': {
                'facts': {'name': keyword, 'candidate': {'status': 'screening'}},
                'entities': [{'type': 'candidate', 'id': f'c-{keyword}', 'title': keyword}],
                'rows_count': 1,
            },
            'rows_count': 1,
        }

    monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
    decision = build_route_decision('对比吴明华和张三的面试表现', _ctx())

    context, clarification = orchestrator._context_for_grounded_generation(
        '对比吴明华和张三的面试表现',
        _ctx(),
        decision,
    )

    assert clarification is None
    assert calls == [
        ('candidate_evidence_bundle', {'keyword': '吴明华'}),
        ('candidate_evidence_bundle', {'keyword': '张三'}),
    ]
    assert [detail['name'] for detail in context['details']] == ['吴明华', '张三']

