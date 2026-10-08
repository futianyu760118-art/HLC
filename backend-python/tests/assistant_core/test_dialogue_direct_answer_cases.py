"""Direct-answer routing regression suite.

Module 1 from the automated assistant QA checklist: polish, translation,
summary, explanation, and general HR knowledge questions must stay on the
dialogue/knowledge track and must not invoke business tools.
"""

from __future__ import annotations

import pytest

from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-direct-answer', role=role, session_id='s-direct-answer')


DIRECT_ANSWER_CASES = [
    # Polish: explicit user-provided text.
    '帮我润色：请你明天下午三点来公司面试',
    '润色：我们已经收到你的简历，稍后会安排同事联系你',
    '请帮我润色：这个岗位需要会 Java 和 MySQL',
    '把这段话润色得更正式：请尽快补充身份证复印件',
    '下面这段帮我润色：由于项目调整，面试时间改到周五下午',
    '请把以下内容润色成招聘邮件：我们想邀请你参加技术面试',
    '这句话怎么润色：你明天来面试别迟到',
    '帮我优化表达：请候选人提前十分钟到达面试地点',
    '帮我把这段通知写得礼貌一点：面试改期了',
    '请润色这段 HR 通知：本周五下午进行绩效面谈',
    '把下面这句话改得专业一些：我们觉得你还不错',
    '帮我调整语气：你的简历不太符合我们的要求',
    '请把这段候选人回复润色一下：谢谢你的投递，我们会尽快反馈',
    '帮我把这句话变得更温和：暂时不能给你发 offer',
    '把这段面试邀请改得更清楚：周三线上聊半小时',
    '请润色一段入职提醒：带上身份证和银行卡',
    '帮我把离职交接提醒写得更正式：请下周完成交接',
    '润色以下绩效反馈：你需要加强沟通和计划管理',
    '帮我润色一段招聘 JD 的开头：我们正在寻找优秀工程师',
    '请把这段说明改成候选人能看懂的版本：薪酬结构包含固定和绩效',
    # Translation: explicit user-provided text.
    '翻译：请提前十分钟到达面试地点',
    '请翻译成英文：我们会在三个工作日内反馈面试结果',
    '把这句话翻译成英文：欢迎加入恒聘通团队',
    '下面这段翻译成英文：请携带身份证原件办理入职',
    '请把以下内容翻译成中文：Please confirm your interview availability.',
    '这句话怎么翻译：probation period',
    '帮我翻译：offer acceptance deadline',
    '翻译为英文：我们需要确认你的期望到岗时间',
    '请把这段候选人沟通内容翻译成英文：感谢你的耐心等待',
    '翻译：面试官会重点了解你的项目经验',
    '请翻译成英文：请在邮件中回复是否接受 Offer',
    '把下面的英文翻译成中文：Your onboarding documents are incomplete.',
    '翻译为中文：The salary package is subject to final approval.',
    '帮我翻译这句 HR 术语：employee lifecycle management',
    '请把这段话翻成英文：我们会为你安排第二轮面试',
    '翻译以下通知：培训课程将在下周一开始',
    '请翻译：绩效面谈不是处罚，而是沟通改进方向',
    '把这句中文翻译成英文：请更新你的联系方式',
    '帮我翻译：background check consent form',
    '请把这段面试反馈翻译成英文：候选人沟通清晰但经验不足',
    # Summary: explicit user-provided text.
    '总结：候选人有五年 Java 经验，做过支付系统，沟通顺畅',
    '请总结这段内容：张三本周完成了入职材料提交和电脑领取',
    '把下面这段总结成三点：面试中候选人表现稳定，基础扎实，但项目深度一般',
    '这段话帮我总结一下：员工申请调岗，原因是通勤距离和职业发展',
    '帮我提炼要点：部门本月新增三人，离职一人，还有两人待入职',
    '总结以下会议纪要：招聘进度落后，需要加快简历筛选和面试安排',
    '请用一句话总结：培训完成率较高，但考试通过率偏低',
    '把这段反馈总结成行动项：候选人希望了解团队规模和加班情况',
    '请总结：绩效结果分布集中在 B，A 类员工比例较低',
    '总结下面的 HR 政策说明：试用期内需完成导师评估和转正申请',
    '帮我压缩成摘要：员工离职原因包括薪酬、发展空间和管理沟通',
    '这段候选人电话沟通帮我总结：他最快下月到岗，期望薪资需再谈',
    '请总结成 bullet：岗位职责包括招聘、培训、员工关系',
    '帮我总结以下邮件：候选人确认周五上午十点参加线上面试',
    '把这段话总结为风险点：候选人频繁跳槽且空窗期较长',
    '总结这段面试记录：算法基础好，业务理解一般，需要复试确认',
    '请提炼三条结论：部门考勤异常主要集中在迟到和补卡',
    '帮我总结为一句候选人评语：稳定、认真、项目复杂度一般',
    '总结：这个 Offer 还在审批中，候选人希望本周得到答复',
    '请把这段员工访谈整理成摘要：员工希望获得更多培训机会',
    # Explanation and general HR knowledge.
    '解释一下什么是结构化面试',
    '什么是胜任力模型？',
    'HRBP 是什么角色？',
    '怎么理解试用期转正评估？',
    '请解释 OKR 和 KPI 的区别',
    '员工生命周期管理是什么意思？',
    '招聘漏斗是什么？',
    '人才盘点通常包括哪些内容？',
    '解释一下背调授权书的作用',
    '面试评分表为什么要标准化？',
    '什么是无固定期限劳动合同？',
    '怎么理解绩效校准会？',
    '请解释一下候选人体验',
    '什么是入职 buddy 制度？',
    '离职面谈一般问哪些问题？',
    '解释一下 360 度评估',
    '什么是岗位说明书？',
    '怎么理解薪酬带宽？',
    '请解释岗位职级和岗位序列的区别',
    '招聘需求冻结是什么意思？',
    # HR knowledge phrased as how-to/advice without system data lookup.
    '如何写一段礼貌的面试改期说明？',
    '面试邀约邮件通常包含哪些信息？',
    '如何设计一份新员工入职清单？',
    '绩效反馈应该怎么表达更容易被接受？',
    '如何向候选人解释 Offer 审批还没完成？',
    '招聘 JD 里应该避免哪些夸张表述？',
    '员工转正沟通需要注意什么？',
    '如何组织一次有效的离职交接？',
    '培训通知一般需要写哪些要素？',
    '如何给面试官写一份候选人简报？',
    '怎样解释调薪不是即时生效？',
    '如何总结一次部门招聘复盘？',
    '面试问题如何避免歧视性提问？',
    '如何回复候选人“为什么还没有反馈”？',
    '怎样写拒信既清楚又尊重候选人？',
    '如何向员工解释考勤规则？',
    '怎么写试用期目标更清晰？',
    '如何设计部门培训满意度问卷？',
    '怎样把绩效改进建议写得具体？',
    '如何给管理者解释招聘优先级？',
    # Boundary wording that mentions HR domains but still asks knowledge/text.
    '请解释“绩效面谈不是绩效审批”这句话',
    '帮我解释这句话：薪酬信息需要按权限查看',
    '总结一下这句话：候选人数据只能用于招聘目的',
    '翻译这句：员工合同到期前需要提前提醒',
    '润色这句：审批通过前请不要承诺具体薪资',
    '解释一下岗位要求和任职资格有什么区别',
    '什么是候选人差异化面试题？',
    '怎么理解招聘中的“证据驱动评估”？',
    '请解释“先查证据再生成报告”的含义',
    '总结：AI 助手可以查询数据，但写入动作需要确认',
    # Casual capability/help.
    '你能做什么？',
    '你是谁？',
    '怎么使用聘小犀？',
    '我可以让你帮我润色文本吗？',
    '你能不能解释 HR 术语？',
    '你会自动发送邮件吗？',
    '哪些问题适合直接问你？',
    '如果我只想翻译一句话，该怎么问？',
    '你能帮我总结会议纪要吗？',
    '你能给我 HR 写作建议吗？',
]


def test_direct_answer_case_count_is_at_least_100() -> None:
    assert len(DIRECT_ANSWER_CASES) >= 100


@pytest.mark.parametrize('message', DIRECT_ANSWER_CASES)
def test_direct_answer_cases_stay_dialogue_without_tools(monkeypatch, message: str) -> None:
    """直答类请求必须留在 C 轨，避免无意义调用搜索/业务技能。"""
    monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)

    decision = build_route_decision(message, _ctx())

    assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
    assert decision.task_type == 'dialogue'
    assert not decision.tool_plan

