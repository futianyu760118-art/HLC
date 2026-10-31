"""Lightweight three-track classifier.

The first production version intentionally uses deterministic rules instead of
an LLM router. It only decides the broad execution track; the legacy router
still owns workflow/task selection for data/action requests.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..guardrails import detect_write_intent
from ..schemas import AssistantContext, RouteDecision


TRACK_A = 'A_DATA_ACTION'
TRACK_B = 'B_GENERATION'
TRACK_C = 'C_DIALOGUE_KNOWLEDGE'
TRACK_COMPOSITE = 'COMPOSITE'


DATA_ACTION_KEYWORDS = [
    '查', '搜索', '列出', '统计', '汇总', '筛选', '最近', 'top', 'Top',
    '员工', '候选人', '简历', '岗位', '部门', '考勤', '薪酬', '工资', '绩效',
    '审批', '培训', '反馈', '创建', '安排', '发送', '删除', '导出',
    '应聘', '投递', '名单', '有哪些人',
]

DATA_VERBS = ['查', '搜索', '列出', '统计', '筛选', '找出', '找一下', '查看', '看看', '看一下', '导出', '有哪些', '哪些人']
DATA_DOMAINS = [
    '员工', '候选人', '简历', '岗位', '部门', '考勤', '薪酬', '工资', '绩效',
    '审批', '培训', '反馈', '面试', 'offer', 'Offer', '应聘', '投递',
]

GENERATION_KEYWORDS = [
    '写', '生成', '设计', '起草', '润色', '翻译', '总结', '对比', '分析',
    '规划', '建议', '方案', '报告', '面试题', '邮件', '招聘文案', '绩效改进',
    '出题', '评价', '评判', '评估', '判断', '推荐', '排序', '适合',
    '符合', '满足', '胜任', '匹配', '达标', '合格', '够格',
]

DIALOGUE_KNOWLEDGE_KEYWORDS = [
    '是什么', '怎么理解', '如何使用', '解释', '帮我解释', '这句话什么意思',
    '翻译', '润色', '总结', '你能做什么', '帮助', '闲聊',
]

WORKSET_MENTIONS = [
    '这几个人', '这些候选人', '上面这些候选人', '刚才这些候选人',
    '这些简历', '上面这些简历', '刚才这些简历', '每个人', '每位候选人',
    '每个候选人', '每份简历', '针对每个人',
    '这个人', '这个候选人', '刚才那个候选人', '第二个', '第三个',
    '他们', '她们', '他', '她', '这些人', '这些员工', '这批', '这批人', '上面这些',
    '上面的人', '上面的', '刚才这些', '刚才那些', '列表里', '表格里',
    '上述', '以上', '逐个', '分别', '每个', '每位', '每一位', '每一份',
    '结合他们', '结合这些', '基于上面', '基于刚才', '前几个', '前五个',
    '第一个', '第1个', '他的', '她的', '该候选人', '该员工',
    '最合适的人', '最推荐的人', '排名第一', '第一名', '前三个人', '前3个人', '前三位',
    '其中', '里面', '这些里面', '结果里', '名单里', '候选人里', '简历里',
    '上面列表', '上面结果', '这批候选人',
    '上面20个人', '这20个人', '这二十个人', '排名前三', '排名前3',
    '前三名', '前3名', 'top3', 'Top3', '排名报表', '比对报表',
    '第二位', '第 2 位', '第三位', '最后一个', '最后一位', '最后一份',
    '倒数第一个', '倒数第二个', '刚才那批', '刚才的', '刚才列出的',
    '上一批', '上一轮', '上轮', '前面那批', '前面这些', '那批',
    '这一批', '这些履历', '这批简历', '那批简历', '这些投递记录',
    '这几个', '这几位', '这几份', '各自',
]


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(k in text for k in keywords)


def _is_user_text_transform(message: str) -> bool:
    """Detect translate/polish/explain/summarize over user-provided text."""
    text = message.strip()
    transform_verbs = (
        r'润色|翻译|翻成|翻为|解释|总结|摘要|提炼|提炼要点|'
        r'优化表达|调整语气|改写|改成|改得|写得|整理成|压缩成'
    )
    quoted_text_refs = r'这段话|这句话|这段|这句|下面这段|以下内容|以下邮件|会议纪要|原文'
    if re.search(rf'({transform_verbs}).{{0,24}}[：:]', text):
        return True
    if re.search(rf'({quoted_text_refs}).{{0,30}}({transform_verbs})', text):
        return True
    if re.search(
        rf'(?:把|请把|帮我把).{{0,24}}(?:这段|这句|下面|以下|内容|通知|邮件|反馈|记录|评语|说明).{{0,30}}'
        rf'({transform_verbs})',
        text,
    ):
        return True
    if re.search(r'把(这段话|这句话|下面这段|以下内容).*(翻译|润色|总结|解释)', text):
        return True
    if re.search(r'(这句话|这段话).*(什么意思|怎么翻译|怎么润色)', text):
        return True
    return False


def _has_explicit_named_private_subject(text: str) -> bool:
    """Avoid treating explicit person-record lookups as generic HR knowledge."""
    if re.search(r'^(如何|怎样|怎么).*(写|设计|组织|回复|解释|总结|避免|表达|沟通|说明|提问|复盘|开展|制定|整理)', text):
        return False
    subject_match = re.search(
        r'([\u4e00-\u9fa5·]{2,8})的(?:简历|资料|详情|考勤|绩效|薪酬|面试|Offer|offer|合同|入职|转正|离职)',
        text,
    )
    if subject_match:
        subject = subject_match.group(1)
        generic_subjects = {
            '候选人', '员工', '新员工', '部门', '岗位', '职位', '面试官',
            '试用期', '招聘中', '审批前', '薪酬信息', '礼貌',
        }
        return subject not in generic_subjects and not subject.endswith(('员工', '候选人', '面试官'))
    if re.search(r'[\u4e00-\u9fa5·]{2,4}(?:薪酬|考勤|绩效|合同)(?:怎么样|如何|情况|多少|吗|为什么)', text):
        return True
    return bool(re.search(r'(这个人|这个候选人|该候选人|该员工|他|她).*(简历|考勤|绩效|薪酬|面试|合同|入职|转正|离职)', text))


def _is_capability_or_policy_question(text: str) -> bool:
    """Questions about what the assistant can do should not trigger actions."""
    return bool(
        re.search(r'(你能|你会|你可以|能不能|会不会|可以让你|是否可以|能否).*(做什么|润色|翻译|总结|解释|自动|发送|邮件|删除|审批|创建|建议|写作)', text)
        or re.search(r'(哪些问题|什么问题).*(适合|可以).*(问你|直接问)', text)
        or re.search(r'(怎么|如何).*(使用|提问|问你|让你).*(聘小犀|助手|你)?', text)
    )


def _is_general_knowledge_question(text: str) -> bool:
    """Detect HR concept/advice questions that need a direct answer, not tools."""
    if _has_explicit_named_private_subject(text):
        return False
    if re.search(r'^(什么是|什么叫|请解释|解释一下|帮我解释|怎么理解|如何理解).{1,80}(?:[？?]|$)', text):
        return True
    if re.search(r'(是什么意思|有什么区别|的区别|的含义|的作用|为什么要|为什么需要).{0,20}[？?]?$', text):
        return True
    if re.search(
        r'^(如何|怎样|怎么).{0,50}(写|设计|组织|回复|解释|总结|避免|表达|沟通|说明|提问|复盘|开展|制定|整理).{0,60}[？?]?$',
        text,
    ):
        return True
    if re.search(r'(通常|一般).{0,24}(包含|包括|需要|问哪些|注意什么).{0,40}[？?]?$', text):
        return True
    return False


def _infer_generation_intent(message: str) -> str:
    text = message.lower()
    if re.search(r'(其中|里面|结果里|名单里|列表里|表格里|谁|哪位|哪个).*(最|最高|最低|最大|最小|最多|最少|评分|匹配|年龄|年纪|经验|学历|状态|时间|日期)', message):
        return 'workset_analysis'
    if re.search(r'(排名|排行|排序|比对|对比).*(报表|报告|分析)?', message):
        return 'candidate_compare'
    if '面试题' in message or '出题' in message:
        return 'interview_questions'
    if '对比' in message and (
        '候选人' in message or '简历' in message or '这几个人' in message
        or '这些' in message or '他们' in message or '上面' in message
    ):
        return 'candidate_compare'
    if '邮件' in message or '邀约' in message or '邀请' in message:
        return 'hr_email_draft'
    if '招聘文案' in message or '职位描述' in message or '岗位jd' in text or 'jd' in text:
        return 'job_posting'
    if '报告' in message or '分析' in message:
        return 'analysis_report'
    if re.search(r'(怎么样|评价|评判|评估|适合|推荐)', message):
        return 'candidate_assessment'
    return 'generic_generation'


def _extract_named_people(text: str) -> list[str]:
    """Extract likely explicit Chinese person names from candidate reasoning asks."""
    names: list[str] = []
    stop_words = {
        '候选人', '这个人', '这位候选人', '岗位', '职位', '简历', '面试', '记录', '风险',
        '亮点', '短板', '项目', '经历', '证据', '质量', '报告', '优劣势', '匹配度',
        '个人', '每个', '每个人', '这些人', '这几人', '这几个', '几个人', '最近',
        '销售岗位', '后端岗位', '前端工程师', '电子工程师', '产品经理', '测试工程师',
        '数据分析师', '培训专员', '人事专员', '销售经理', '客服主管',
    }
    invalid_fragments = (
        '我', '这', '他', '她', '该', '每', '个', '人', '上面', '刚才', '哪些', '什么',
        '如何', '怎么', '帮', '请', '结合', '基于', '针对', '设计', '生成', '出题',
        '面试', '个人', '怎么样', '一下', '最近', 'Java', 'java',
    )

    for chunk in re.split(r'[、，,和与跟及]|以及', text or ''):
        chunk = chunk.strip()
        if re.search(r'^(?:这批|这几|这些|那些|那批|刚才|上面|前面|上一批|上一轮|上轮)', chunk):
            continue
        for pattern in (
            r'(?:基于|针对|根据|给|为|帮)\s*([\u4e00-\u9fa5·]{2,4})(?:设计|生成|出|准备)',
            r'(?:分析|评价|评判|评估|判断|推荐|比较|对比|针对|基于|根据|给|为|帮|帮我|请按|围绕|从证据看|把)\s*([\u4e00-\u9fa5·]{2,4})(?:这个人|这位候选人|候选人)?',
            r'(?:基于|针对|根据)\s*([\u4e00-\u9fa5·]{2,4})(?:简历|资料|面试|项目|风险|岗位)',
            r'帮\s*([\u4e00-\u9fa5·]{2,4})(?:设计|生成|出|准备)',
            r'([\u4e00-\u9fa5·]{2,4})(?:面试时|面试中|下一轮|二面|终面)',
            r'([\u4e00-\u9fa5·]{2,4})(?:这个人|这位候选人)(?:怎么样|如何|评价|评判|评估|适合|推荐|优劣势|胜任力)',
            r'([\u4e00-\u9fa5·]{2,4})(?:这个候选人|候选人)的(?:胜任力|优劣势|录用风险|匹配度|风险|亮点|短板)',
            r'([\u4e00-\u9fa5·]{2,4})(?:的|是否|能否|能不能|适合|匹配|满足|符合|胜任|做|需要|生成|请|与|和|谁|哪个|哪位|$)',
            r'([\u4e00-\u9fa5·]{2,4})(?:该不该|对.+岗位|.*适配度|.*匹配度)',
        ):
            match = re.search(pattern, chunk)
            if not match:
                continue
            name = match.group(1).strip()
            if (
                name
                and name not in stop_words
                and not name.startswith(('这', '他', '她', '该', '每', '个', '上面', '刚才', '哪些', '什么', '如何', '怎么', '帮我', '请', '你'))
                and not any(fragment in name for fragment in invalid_fragments)
                and not re.search(r'(简历逐份|候选人对|这批|这几|这些|那些|那批)', name)
                and not re.search(r'(候选人|简历|面试|岗位|职位|最近|Java|java|个人|总监|经理|主管|专员|顾问|工程师|分析师|会计)$', name)
                and name not in names
            ):
                names.append(name)
                break
    return names


def _has_explicit_person_name(text: str) -> bool:
    return bool(_extract_named_people(text))


def _is_followup_generation_context(text: str) -> bool:
    """Detect generation/analysis that should inherit the latest WorkSet."""
    if _contains_any(text, WORKSET_MENTIONS):
        return True
    return bool(
        re.search(r'(谁|哪位|哪个).*(更|最)?(适合|匹配|推荐|优先)', text)
        or re.search(r'(其中|里面|结果|名单|列表|表格).*(谁|哪位|哪个|最|最高|最低|最大|最小|最多|最少|评分|匹配|年龄|年纪|经验|学历|状态|时间|日期)', text)
        or re.search(r'(结合|基于).*(经历|背景|简历|结果|列表|表格)', text)
        or re.search(r'(上面|上述|以上|这|这些|这批|名单|列表|结果)?\s*\d+\s*(?:个|名|位)?\s*(?:人|候选人|简历)', text)
        or re.search(
            r'(?:第\s*[一二两三四五六七八九十\d]+\s*(?:个|位|名|份|条|项)|'
            r'第[一二两三四五六七八九十\d]+(?:个|位|名|份|条|项)|'
            r'最后\s*(?:一)?\s*(?:个|位|名|份|条|项)|'
            r'倒数\s*第?\s*[一二两三四五六七八九十\d]+\s*(?:个|位|名|份|条|项)?)',
            text,
        )
        or re.search(
            r'(刚才|刚刚|上轮|上一轮|上一批|前一批|前面|上面|那批|那些|这一批).{0,12}'
            r'(候选人|应聘者|面试者|简历|履历|投递记录|员工|同事|成员|岗位|职位|招聘需求|名单|列表|结果)',
            text,
        )
        or re.search(r'(排名|排行|排序|比对|对比|报表|前\s*[一二两三四五六七八九十\d]+|top\s*\d+)', text, re.I)
    )


def _has_collective_workset_reference(text: str) -> bool:
    return bool(
        re.search(
            r'(这几个人|这些|这批|这几个|这几位|这几份|他们|她们|每个|每位|每一位|每一份|'
            r'分别|逐个|逐份|上面|刚才|刚刚|其中|里面|列表里|表格里|结果里|名单里|'
            r'上述|以上|上一批|上一轮|上轮|前一批|前面|那批|那些|这一批|最后|倒数|'
            r'第\s*[一二两三四五六七八九十\d]+\s*(?:个|位|名|份|条|项)|'
            r'排名|排行|排序|前\s*[一二两三四五六七八九十\d]+|top\s*\d+)',
            text,
            re.I,
        )
    )


def _is_workset_report_request(text: str) -> bool:
    """Detect a report request that is naturally about the latest result set."""
    return bool(
        re.search(r'(排名|排行|排序|比对|对比).*(报表|报告|分析)?', text)
        or re.search(r'(报表|报告).*(排名|排行|排序|比对|对比)', text)
        or re.search(r'(前\s*[一二两三四五六七八九十\d]+|top\s*\d+).*(报表|报告|分析|安排|面试)?', text, re.I)
    )


def _named_subject_assessment(text: str) -> bool:
    """Detect an assessment request grounded by an explicit person name."""
    if _has_collective_workset_reference(text):
        return False
    leading_verb = re.search(
        r'(?:分析|评价|评判|评估|判断|推荐|符合|满足|适合|胜任|匹配)(?:一下)?\s*'
        r'([\u4e00-\u9fa5·]{2,8}?)(?:的|这个人|这位候选人|候选人|$)',
        text,
    )
    if leading_verb:
        candidate = leading_verb.group(1)
        if candidate not in {'最近', '候选人', '员工', '简历', '报告', '这些人'}:
            return True
    match = re.search(
        r'([\u4e00-\u9fa5A-Za-z·]{2,20})(?:这个人|这位候选人|候选人)?'
        r'.*(怎么样|如何|评价|评判|评估|适合|推荐|优劣势|为什么|为何)',
        text,
    )
    if not match:
        return bool(
            _has_explicit_person_name(text)
            and re.search(
                r'(录用风险|风险点|亮点|短板|优劣势|录用建议|是否建议|值不值得|值得|该不该|靠谱不|靠谱吗|'
                r'进入下一轮|进入终面|继续跟进|重点争取|候选人画像|能不能录用|能否录用|综合表现|'
                r'候选人质量|胜任力|匹配度和风险|适合储备|建议发\s*Offer)',
                text,
                re.I,
            )
        )
    name = match.group(1)
    return not name.startswith(('这', '上面', '刚才', '他们', '这些', '哪个', '哪位', '他', '她', '该'))


def _named_subject_evidence_question(text: str) -> bool:
    if _is_followup_task_action(text) or _is_interview_schedule_action(text):
        return False
    if _has_collective_workset_reference(text):
        return False
    cleaned = re.sub(r'^\s*(?:帮我|请帮我|请你)?(?:查|看|了解)?(?:一下)?\s*', '', text)
    if _has_explicit_person_name(cleaned) and re.search(
        r'(简历亮点|面试反馈|复试反馈|面评结论|面试官反馈|Offer\s*进度|投递记录|岗位匹配证据|'
        r'候选人状态|推荐理由|薪资相关|面试问题集中|是否提到|来源证据|证据链|'
        r'有哪些证据|哪些记录|是什么|说明了什么|有没有异常|为什么|完整吗|有吗|记录了吗)',
        cleaned,
        re.I,
    ):
        return True
    match = re.match(
        r'([\u4e00-\u9fa5·]{2,8})(?:'
        r'(?:有没有|有无|是否有).*(?:简历|面试|Offer|offer|岗位|入职|考勤|绩效|培训|记录)'
        r'|.*(?:简历|面试|入职|考勤|绩效|培训|记录|进度).*(?:怎么样|如何|情况|多少|吗|为什么)'
        r')',
        cleaned,
    )
    if not match:
        return False
    name = match.group(1)
    return (
        name not in {'这个', '这些', '他们', '她们', '候选人', '员工'}
        and not name.startswith(('这', '他', '她', '该', '上面', '刚才'))
    )


def _named_subject_interview_questions(text: str) -> bool:
    """Detect differentiated interview-question generation for one named person."""
    if _has_collective_workset_reference(text):
        return False
    if not _has_explicit_person_name(text):
        return False
    return bool(
        re.search(
            r'(面试题|面试问题|复试问题|终面问题|技术面试题|行为面试题|结构化面试题|追问|出题|'
            r'问题清单|面试提纲|重点问什么|问哪些问题|验证哪些点|转成面试问题|二面问题|胜任力问题)',
            text,
        )
        and re.search(r'(生成|设计|准备|根据|基于|针对|为|给|出|补充|覆盖|围绕|适合|需要|该|请|怎么|帮我|匹配)', text)
    )


def _named_subject_job_fit(text: str) -> bool:
    if _has_collective_workset_reference(text):
        return False
    if not _has_explicit_person_name(text):
        return False
    return bool(
        re.search(r'(适合|适不适合|匹配|适配|胜任|满足|符合|达标|能否|能不能)', text)
        and re.search(r'(岗位|职位|要求|条件|标准|门槛|任职资格|Java|HRBP|专员|经理|主管|工程师|顾问|分析师|会计)', text, re.I)
    )


def _named_subjects_compare(text: str) -> bool:
    names = _extract_named_people(text)
    if len(names) < 2:
        return False
    return bool(
        re.search(
            r'(对比|比较|排序|排行|谁|哪个|哪位|分别|优劣势|差异|更适合|更值得|更低|更好|'
            r'推荐优先级|候选人质量|匹配度|风险点|录用建议|差异报告|对比报告)',
            text,
        )
    )


def _is_action_howto_question(text: str) -> bool:
    return bool(re.search(r'^(如何|怎样|怎么).{0,30}(安排|创建|新建|预约|约).{0,40}(面试|复试|任务|提醒|待办|跟进)', text))


def _is_followup_task_action(text: str) -> bool:
    if _is_action_howto_question(text):
        return False
    if (
        re.search(r'(通知提醒|系统设置).{0,20}(待办|待跟进|详情|排序|过滤|看板|数据|记录|有哪些|查看|打开)', text)
        and not re.search(r'(删除|移除|清除|修改|更新|改成|改为|调整状态|直接更新)', text)
    ):
        return False
    if (
        re.search(r'(查|查询|查看|搜索|列出|统计|汇总|找|找出).{0,40}(待办|任务|提醒)', text)
        and re.search(r'(并|然后|再|之后).{0,12}(生成|输出|整理|形成|写|起草|设计|分析|总结|复盘|给出)', text)
        and not re.search(r'(并|然后|再|之后).{0,12}(创建|新建|安排|添加|加个|设个|设置|帮我建|帮我创建).{0,24}(跟进|任务|提醒|待办)', text)
    ):
        return False
    return bool(
        re.search(r'(创建|新建|安排|添加|加个|设个|设置|帮我建|帮我创建).{0,24}(跟进|任务|提醒|待办|个人待办)', text)
        or re.search(r'(创建|新建|安排|添加|加个|设个|设置).{0,12}(个人)?待办[：:，, ]', text)
        or re.search(r'(跟进任务|个人待办|待办|提醒).{0,24}(跟进|联系|处理|检查|确认|复盘|催|看|找|要)', text)
        or re.search(r'(提醒我|明天提醒我|后天提醒我).{0,40}(跟进|联系|处理|检查|确认|复盘|催|看|找|给|发)', text)
    )


def _is_readonly_interview_schedule_boundary(text: str) -> bool:
    if re.search(
        r'(并|然后|再|之后).{0,12}(安排|创建|新建|约|预约|发起).{0,40}(面试|复试|初面|一面|二面|三面|终面|技术面|HR\s*面|视频面试)',
        text,
        re.I,
    ):
        return False
    if re.search(
        r'((先|优先).{0,8}(约|预约).{0,8}(谁|哪位|哪个)|'
        r'(谁|哪位|哪个).{0,16}(先|优先|比较稳|更稳|最稳|值得|适合)?.{0,12}(约|预约)|'
        r'(要不要|能不能|值不值得|适不适合).{0,8}(约|预约|进入下一轮))',
        text,
        re.I,
    ):
        return True
    return bool(
        re.search(r'(查|查询|查看|搜索|列出|统计|汇总|报表|报告|看一下|给我一个).{0,24}(面试|复试|初面|一面|二面|终面|技术面|HR\s*面).{0,24}(安排|记录|数量|报表|报告)?', text, re.I)
        or re.search(r'(面试|复试|初面|一面|二面|终面|技术面|HR\s*面).{0,24}(安排)?(报表|报告|统计|汇总|列表|数量)', text, re.I)
        or (
            re.search(r'([\u4e00-\u9fa5A-Za-z0-9]+的)?(候选人|应聘者|面试者).{0,12}(面试|复试|初面|一面|二面|终面|技术面|HR\s*面).{0,8}安排$', text, re.I)
            and not re.search(r'(安排|创建|新建|约|预约|发起).{0,40}(面试|复试|初面|一面|二面|三面|终面|技术面|HR\s*面|视频面试)', text, re.I)
        )
        or re.search(r'(生成|输出|整理|形成|写|起草|设计|分析|总结|复盘).{0,24}(面试|复试|初面|一面|二面|终面|技术面|HR\s*面).{0,24}(安排|总结|报告|报表|分析|说明|流程|是否合理)', text, re.I)
        or re.search(r'(创建|新建).{0,12}(面试流程|流程说明|面试.*说明|说明|指南|教程|SOP|模板)', text, re.I)
    )


def _is_interview_schedule_action(text: str) -> bool:
    if _is_action_howto_question(text) or _is_readonly_interview_schedule_boundary(text):
        return False
    interview_terms = r'(面试|复试|初面|一面|二面|三面|终面|技术面|HR\s*面|视频面试)'
    action_terms = r'(安排|创建|新建|约|预约|发起)'
    return bool(
        re.search(rf'{action_terms}.{{0,50}}{interview_terms}', text, re.I)
        or re.search(rf'{interview_terms}.{{0,20}}(安排|创建|新建|预约)', text, re.I)
    )


def _is_document_creation_request(text: str) -> bool:
    return bool(
        re.search(r'(创建|新建|生成|写|设计|起草).{0,24}(说明|流程|指南|SOP|模板|文档|话术|邮件|文案)', text, re.I)
    )


def _is_supported_action(text: str) -> bool:
    return _is_followup_task_action(text) or _is_interview_schedule_action(text)


class TrackClassifier:
    """Rule-based classifier for A/B/C/COMPOSITE execution tracks."""

    def classify(self, message: str, ctx: AssistantContext) -> RouteDecision:
        text = (message or '').strip()
        if not text:
            return RouteDecision(
                task_type='dialogue',
                route_track=TRACK_C,
                intent='general_dialogue',
                confidence=0.5,
                reason='empty_message_defaults_to_dialogue',
            )

        if _is_user_text_transform(text):
            return RouteDecision(
                task_type='dialogue',
                route_track=TRACK_C,
                intent='text_transform',
                confidence=0.94,
                reason='user_provided_text_transform',
            )

        if _named_subjects_compare(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='candidate_compare',
                confidence=0.91,
                required_context=['named_subjects_evidence'],
                reason='named_subjects_compare',
            )

        if _named_subject_interview_questions(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='interview_questions',
                confidence=0.91,
                required_context=['named_subject_evidence'],
                reason='named_subject_interview_questions',
            )

        if _named_subject_evidence_question(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='person_evidence_answer',
                confidence=0.91,
                required_context=['named_subject_evidence'],
                reason='named_subject_evidence_question',
            )

        if _named_subject_job_fit(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='candidate_job_fit',
                confidence=0.89,
                required_context=['named_subject_evidence'],
                reason='person_job_fit_assessment',
            )

        if _is_capability_or_policy_question(text) or _is_general_knowledge_question(text):
            return RouteDecision(
                task_type='dialogue',
                route_track=TRACK_C,
                intent='general_dialogue',
                confidence=0.9,
                reason='direct_answer_knowledge_or_capability',
            )

        if re.search(r'(岗位|职位|招聘).{0,10}(标准|要求|条件|资格|门槛|职责)', text) or \
           re.search(r'([\u4e00-\u9fa5]{2,10})(的|有什么|有哪些).{0,5}(标准|要求|条件|资格|门槛|职责)', text):
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='job_requirements_query',
                confidence=0.85,
                required_context=[],
                reason='job_requirements_detected',
            )

        if _is_supported_action(text):
            is_followup_action = _is_followup_task_action(text)
            required_context = (
                ['latest_workset'] if _is_followup_generation_context(text)
                else ([] if is_followup_action else ['named_subject_evidence'])
            )
            return RouteDecision(
                task_type='action',
                route_track=TRACK_A,
                intent='followup_task_create' if is_followup_action else 'interview_schedule',
                confidence=0.93,
                risk_level='high',
                required_context=required_context,
                requires_confirmation=True,
                reason='supported_chat_confirmed_action',
            )

        if _is_document_creation_request(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent=_infer_generation_intent(text),
                confidence=0.86,
                reason='document_creation_generation_request',
            )

        write_reason = detect_write_intent(text)
        if write_reason:
            return RouteDecision(
                task_type='forbidden',
                route_track=TRACK_A,
                intent='forbidden_action',
                confidence=0.95,
                risk_level='high',
                task_template_id='forbidden_action_response',
                requires_confirmation=True,
                safety_flags=[write_reason],
                fallback_policy='legacy',
                reason='guardrails.detect_write_intent',
            )

        has_data_verb = _contains_any(text, DATA_VERBS)
        has_data_domain = _contains_any(text, DATA_DOMAINS)
        has_generation = _contains_any(text, GENERATION_KEYWORDS)
        has_generation_action = bool(
            re.search(r'(帮我)?(写|生成|设计|起草|规划|分析|对比|总结|评价|评判|评估|判断|推荐|排序|出题|给.*建议|做.*方案)', text)
            or '面试题' in text
            or '招聘文案' in text
        )
        has_workset = _is_followup_generation_context(text)

        if _is_workset_report_request(text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='candidate_compare',
                confidence=0.9,
                required_context=['latest_workset'],
                reason='workset_ranking_report_request',
            )

        if has_workset and re.search(
            r'(其中|里面|结果里|名单里|列表里|表格里|谁|哪位|哪个|最|最高|最低|最大|最小|最多|最少|'
            r'评分|匹配|匹配度|年龄|年纪|经验|学历|状态|时间|日期|部门|岗位|薪酬|工资|绩效|考勤)',
            text,
        ):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='workset_analysis',
                confidence=0.92,
                required_context=['latest_workset'],
                reason='workset_metric_or_comparative_question',
            )

        explicit_subject_assessment = (
            _named_subject_assessment(text)
            and not re.search(r'(这几个人|这些|他们|她们|每个|每位|分别|上面|刚才|其中|里面|列表里|表格里|结果里|名单里)', text)
        )
        if explicit_subject_assessment:
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='person_assessment',
                confidence=0.91,
                required_context=['named_subject_evidence'],
                reason='named_subject_assessment',
            )

        # --- 人岗匹配评估检测 ---
        if re.search(r'([\u4e00-\u9fa5·]{2,8})\s*(?:是否|能否|能不能)?\s*(?:符合|满足|适合|胜任|匹配|达标).+(?:岗位|职位|标准|要求|条件)', text):
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent='candidate_job_fit',
                confidence=0.89,
                required_context=['named_subject_evidence'],
                reason='person_job_fit_assessment',
            )

        if (has_workset and not has_generation_action
                and re.search(r'(怎么样|评价|评判|评估|分析|推荐|适合|优劣势|判断|排序|简历|面试|记录|进度|经历|评分|为什么|风险|亮点|短板|匹配度|合同|转正|考勤|绩效|状态|优先级)', text)):
            if '对比' in text:
                grounded_intent = 'candidate_compare'
            elif '分析' in text or '报告' in text:
                grounded_intent = 'analysis_report'
            elif re.search(r'(简历|面试|记录|进度|经历|评分|为什么)', text):
                grounded_intent = 'person_evidence_answer'
            else:
                grounded_intent = 'candidate_assessment'
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent=grounded_intent,
                confidence=0.91,
                required_context=['latest_workset'],
                reason='referenced_subject_assessment',
            )

        if re.search(r'[\u4e00-\u9fa5A-Za-z0-9]{2,30}的(简历|候选人信息|资料|详情)', text):
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='legacy_data_query',
                confidence=0.84,
                reason='named_entity_detail_lookup',
            )

        if (not has_generation_action) and re.search(r'(最近|近\s*\d+\s*天|本周|本月).*(应聘|投递|简历|候选人|哪些人|名单)', text):
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='legacy_data_query',
                confidence=0.86,
                reason='recent_recruitment_query',
            )

        if has_data_verb and has_data_domain and has_generation_action:
            return RouteDecision(
                task_type='composite',
                route_track=TRACK_COMPOSITE,
                intent=_infer_generation_intent(text),
                confidence=0.9,
                required_context=['candidate_search_results']
                if ('候选人' in text or '简历' in text) else [],
                reason='data_query_plus_generation',
            )

        # Creation/generation requests should not be forced through global_search.
        if has_generation_action:
            required_context = []
            if has_workset:
                required_context.extend(['latest_workset', 'candidate_workset'])
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent=_infer_generation_intent(text),
                confidence=0.88,
                required_context=required_context,
                reason='generation_keywords',
            )

        if has_data_verb or (has_data_domain and _contains_any(text, ['最近', 'Top', 'top', '本月', '所有'])):
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='legacy_data_query',
                confidence=0.82,
                reason='data_action_keywords',
            )

        # --- 岗位标准/要求查询 → 数据查询轨道 ---
        if re.search(r'(岗位|职位|招聘).{0,10}(标准|要求|条件|资格|门槛|职责)', text) or \
           re.search(r'([\u4e00-\u9fa5]{2,10})(的|有什么|有哪些).{0,5}(标准|要求|条件|资格|门槛|职责)', text):
            return RouteDecision(
                task_type='data_query',
                route_track=TRACK_A,
                intent='job_requirements_query',
                confidence=0.85,
                required_context=[],
                reason='job_requirements_detected',
            )

        if _contains_any(text, DIALOGUE_KNOWLEDGE_KEYWORDS):
            return RouteDecision(
                task_type='dialogue',
                route_track=TRACK_C,
                intent='general_dialogue',
                confidence=0.84,
                reason='dialogue_knowledge_keywords',
            )

        if has_generation:
            required_context = []
            if has_workset:
                required_context.extend(['latest_workset', 'candidate_workset'])
            return RouteDecision(
                task_type='generation',
                route_track=TRACK_B,
                intent=_infer_generation_intent(text),
                confidence=0.72,
                required_context=required_context,
                reason='weak_generation_keywords',
            )

        return RouteDecision(
            task_type='dialogue',
            route_track=TRACK_C,
            intent='general_dialogue',
            confidence=0.55,
            reason='default_to_dialogue',
        )


__all__ = ['TrackClassifier', 'TRACK_A', 'TRACK_B', 'TRACK_C', 'TRACK_COMPOSITE']
