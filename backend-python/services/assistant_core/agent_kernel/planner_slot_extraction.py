"""Deterministic planner slot extraction helpers for the HRM Agent Kernel."""

from __future__ import annotations

import re
from typing import Any, Optional


def extract_candidate_name(text: str) -> Optional[str]:
    text = text or ''
    if re.search(r'(这个人|这位|上面|刚才|第二个|第二位|前两个|这些|这几)', text):
        return None
    stop_words = {'候选人', '应聘者', '这个人', '这位', '岗位', '职位', '简历', '面试', '复试', '个人能力'}
    patterns = [
        r'(?:帮我|请|麻烦)?(?:给|为)\s*([\u4e00-\u9fa5·]{2,4})(?:安排|创建|新建|预约|约)',
        r'^([\u4e00-\u9fa5·]{2,4})[，,、\s]*(?:我想|帮我|请|给|为|安排|创建|新建|预约|约)',
        r'(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([\u4e00-\u9fa5·]{2,4})(?:的|,|，|。|；|;|\s|候选人|应聘者|简历|资料|$)',
        r'(?:候选人|应聘者|候选人里|应聘者里).{0,6}(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([\u4e00-\u9fa5·]{2,4})',
        r'(?:候选人|应聘者)[：:\s]*([\u4e00-\u9fa5·]{2,8}?)(?:的|,|，|。|；|;|\s|怎么样|如何|靠不靠谱|稳不稳|风险|依据|证据|分析|评估|评价|$)',
        r'([\u4e00-\u9fa5·]{2,4})(?:的)?(?:个人能力|能力|简历|资料|候选人|这个人|这位|符合|适合|匹配|胜任|靠不靠谱|怎么样|如何)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = clean_person_name(match.group(1))
        if (
            name
            and name not in stop_words
            and not name.startswith(('这', '他', '她', '该', '上面', '刚才', '第二'))
            and not re.search(r'(工程师|经理|专员|主管|总监|岗位|职位|简历|面试|能力)$', name)
        ):
            return name
    return None


def clean_person_name(value: str) -> str:
    cleaned = re.sub(r'\s+', '', str(value or '').strip(' ，,。?？；;:：').rstrip('的'))
    cleaned = re.sub(r'^(?:候选人|应聘者|员工|同事|这个人|这位|给|为|帮)', '', cleaned)
    cleaned = re.sub(r'(?:候选人|应聘者|员工|同事)$', '', cleaned)
    return cleaned


def extract_resume_subject(text: str) -> Optional[str]:
    match = re.search(r'([\u4e00-\u9fa5·]{2,8}?)(?:的)?(?:简历|履历|资料)', text or '')
    if not match:
        return None
    name = match.group(1).strip().rstrip('的')
    name = re.sub(r'^(?:帮我|请|麻烦|查一下|看一下|看看|分析一下|给我|找一下|找找|搜索|检索)', '', name)
    if name.startswith(('这', '他', '她', '该', '上面', '刚才', '最近')):
        return None
    return name


def extract_employee_name_for_query(text: str) -> Optional[str]:
    source = text or ''
    if re.search(r'(这个员工|这位员工|该员工|他|她|上面|刚才|第二个|第\s*\d+\s*个)', source):
        return None
    patterns = [
        r'(?:员工|同事|人员|成员)(?:里|中|列表里|名单里)?(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,8}?)(?:的|最近|本月|这个月|考勤|迟到|缺卡|早退|异常|怎么样|如何|吗|？|\?|$)',
        r'(?:找一下|找找|搜索|检索|查一下|查找|看看)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,8}?)(?:的)?(?:员工|同事|人员|成员|最近|状态|画像|$)',
        r'(?:员工|同事)[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,8}?)(?:的|最近|本月|这个月|考勤|迟到|缺卡|早退|异常|怎么样|如何|吗|？|\\?|$)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,8}?)(?:的)?(?:最近|本月|这个月)?(?:考勤|迟到|缺卡|早退|打卡)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,8}?)(?:的)?(?:考勤|打卡).{0,12}(证据|异常|情况|记录)',
    ]
    stop_words = {
        '这个月', '本月', '最近', '员工', '同事', '考勤', '迟到', '缺卡', '打卡',
        '画像', '员工画像', '低绩效', '绩效低', '评分低',
    }
    for pattern in patterns:
        match = re.search(pattern, source)
        if not match:
            continue
        value = re.sub(r'\s+', '', match.group(1).strip(' ，,。；;:：?？'))
        if (
            value
            and value not in stop_words
            and not value.startswith(('这', '他', '她', '该', '上面', '刚才'))
            and not re.search(r'(岗位|职位|工程师|经理|专员|主管|总监)$', value)
        ):
            return value
    return None


def extract_employee_name_for_action(text: str) -> Optional[str]:
    source = text or ''
    if re.search(
        r'(?:把|给|为)?\s*(?:这个员工|这位员工|该员工|上面这个员工|刚才这个员工)'
        r'(?:调到|转到|调入|转入|调岗|转岗|调薪|涨薪|加薪|降薪|减薪|薪资调整|薪酬调整)',
        source,
    ):
        return None
    patterns = [
        r'(?:把|给|为)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:调到|转到|调入|转入|调岗|转岗|调薪|涨薪|加薪|降薪|减薪|薪资调整|薪酬调整)',
        r'([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:调到|转到|调入|转入|调岗|转岗|调薪|涨薪|加薪|降薪|减薪|薪资调整|薪酬调整)',
        r'(?:员工|同事)[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:[，,。；;]|$)',
    ]
    stop_words = {'这个员工', '这位员工', '该员工', '员工', '同事', '上面这个员工', '刚才这个员工'}
    for pattern in patterns:
        match = re.search(pattern, source)
        if not match:
            continue
        value = re.sub(r'\s+', '', match.group(1).strip())
        value = value.strip('，,。；;:：')
        value = re.sub(r'^(?:把|给|为|帮我|帮|请|那就|继续|准备|提交|确认|发起|走)+', '', value)
        if (
            value
            and value not in stop_words
            and not value.startswith(('这', '他', '她', '该', '上面', '刚才', '如果', '假如', '要是'))
            and not re.search(r'^(调到|转到|调入|转入|调岗|转岗|调薪|涨薪|加薪|降薪|减薪|薪资调整|薪酬调整)', value)
            and not re.search(r'(准备|提交|审批|申请|确认|这个|这条|这次|调岗|转岗|异动)', value)
        ):
            return value
    return None


def extract_job_keyword(text: str) -> Optional[str]:
    text = text or ''
    intent_match = re.search(r'(?:符合|满足|适合|匹配|适配|胜任)(.+?)(?:要求|吗|么|$)', text)
    if intent_match:
        scoped = clean_job_keyword(intent_match.group(1))
        scoped_match = longest_job_phrase(scoped)
        if scoped_match:
            return scoped_match
    match = re.search(
        r'([\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位))'
        r'(?:岗位)?(?:要求|匹配|适配|胜任|吗|么|$)',
        text,
    )
    if match:
        return clean_job_keyword(match.group(1))
    match = re.search(r'(?:符合|满足|适合|匹配|胜任).{0,6}([\u4e00-\u9fa5A-Za-z0-9·]{2,18})(?:岗位|职位|要求)', text)
    if match:
        return clean_job_keyword(match.group(1))
    return None


def extract_job_context_keyword(text: str) -> Optional[str]:
    text = text or ''
    match = re.search(
        r'([\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位))'
        r'(?:岗位|职位)?',
        text,
    )
    if match:
        return clean_job_keyword(match.group(1))
    return None


def longest_job_phrase(text: str) -> Optional[str]:
    raw_matches = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9·]{2,24}(?:工程师|专员|经理|总监|主管|岗位|职位)', text or '')
    matches = []
    for raw in raw_matches:
        for segment in re.split(r'(?:和|及|与|、|，|,)', raw):
            match = re.search(r'[\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位)', segment)
            if match:
                cleaned = clean_job_keyword(match.group(0))
                if cleaned:
                    matches.append(cleaned)
    if not matches:
        return None
    return max(matches, key=len)


def clean_job_keyword(value: str) -> str:
    cleaned = (value or '').strip(' ，,。?？')
    for _ in range(3):
        previous = cleaned
        cleaned = re.sub(r'^(?:符合|满足|适合|匹配|适配|胜任|能不能|是否|判断|评估|看看)(?:的)?', '', cleaned)
        cleaned = re.sub(r'^(?:我们|咱们|公司|本公司|贵司|团队|部门)(?:的)?', '', cleaned)
        cleaned = re.sub(r'^(?:当前|现在|现有|在招|招聘中|正在招聘|正在招|要招)(?:的)?', '', cleaned)
        cleaned = re.sub(r'^(?:岗位|职位)(?:的)?', '', cleaned)
        if cleaned == previous:
            break
    if cleaned.endswith('岗位') and len(cleaned) > 2:
        cleaned = cleaned[:-2]
    if cleaned.endswith('职位') and len(cleaned) > 2:
        cleaned = cleaned[:-2]
    return cleaned


def extract_target_department(text: str) -> Optional[str]:
    patterns = [
        r'(?:调到|转到|调整到|调入|转入)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:[，,。；;]|目标岗位|岗位[：:]|职位[：:]|先分析|并准备|准备|提交|确认|走|会影响|影响|会怎样|会怎么样|会有什么|会牵扯|$)',
        r'目标部门[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,60}?)(?:[，,。；;]|目标岗位|岗位[：:]|职位[：:]|先分析|并准备|准备|提交|确认|走|会影响|影响|会怎样|会怎么样|会有什么|会牵扯|$)',
    ]
    stop_words = {'目标部门', '部门', '岗位', '职位', '审批', '影响', '确认'}
    for pattern in patterns:
        match = re.search(pattern, text or '')
        if not match:
            continue
        value = re.sub(r'\s+', '', match.group(1).strip())
        value = value.rstrip('，,。；;')
        if value and value not in stop_words:
            return value
    return None


def extract_target_position(text: str) -> Optional[str]:
    patterns = [
        r'目标岗位[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,50})(?:[，,。；;]|先分析|并准备|准备|提交|确认|$)',
        r'(?:转任|转岗为|调岗为|调整为)\s*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,50}?)(?:岗位|职位|岗)?(?:[，,。；;]|$)',
        r'(?:岗位|职位)[：:\s]*([A-Za-z0-9_\-\u4e00-\u9fa5·]{2,50})(?:[，,。；;]|先分析|并准备|准备|提交|确认|$)',
    ]
    stop_words = {'目标部门', '部门', '岗位', '职位', '审批', '影响', '确认'}
    for pattern in patterns:
        match = re.search(pattern, text or '')
        if not match:
            continue
        value = re.sub(r'\s+', '', match.group(1).strip())
        value = re.sub(r'(?:岗位|职位|岗)$', '', value)
        value = value.rstrip('，,。；;')
        if value and value not in stop_words:
            return value
    return None


def extract_schedule_hint(text: str) -> Optional[str]:
    if '明天' in (text or ''):
        return 'tomorrow'
    if re.search(r'20\d{2}-\d{2}-\d{2}', text or ''):
        return re.search(r'20\d{2}-\d{2}-\d{2}', text or '').group(0)
    if re.search(r'(上午|下午|晚上|点|半)', text or ''):
        return 'time_mentioned'
    return None


def is_attendance_reminder_confirm_question(text: str) -> bool:
    text = text or ''
    if re.search(r'(只|仅|先).{0,6}(写|生成|出).{0,8}(草稿|文案|话术)', text):
        return False
    rank = (
        re.search(r'(迟到|考勤异常|打卡异常|缺卡|早退).{0,24}(最多|排名|前\s*\d+|前[一二两三四五六七八九十]|top\s*\d*)', text, re.I)
        or re.search(r'(最多|排名|前\s*\d+|前[一二两三四五六七八九十]|top\s*\d*).{0,24}(迟到|考勤异常|打卡异常|缺卡|早退)', text, re.I)
    )
    action = re.search(r'(生成|创建|新建|发|发送|推送|通知|提醒|待发送)', text)
    return bool(rank and action)


def attendance_reminder_confirm_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {
        'title': '发送考勤迟到提醒',
        'content': '根据考勤统计生成迟到提醒草稿。',
        'notice_type': 'attendance',
        'link_url': '/hrm/attendance-records',
        'rank_status': 'late',
    }
    if re.search(r'(考勤异常|打卡异常)', text or '') and not re.search(r'迟到', text or ''):
        slots['rank_status'] = 'anomaly'
        slots['title'] = '发送考勤异常提醒'
        slots['content'] = '根据考勤异常统计生成提醒草稿。'
    limit = extract_limit(text)
    if limit:
        slots['limit'] = limit
    else:
        slots['limit'] = 5
    return slots


def notification_slots(text: str) -> dict[str, Any]:
    raw = (text or '').strip()
    cleaned = re.sub(
        r'^(帮我|请|麻烦)?\s*(给|向)?\s*(全员|大家|所有人|员工|同事)?\s*'
        r'(推送|推|发|发送|创建|新建|写|发个|发一条)?\s*(一条|个)?\s*'
        r'(HR|hr|系统|站内)?\s*(通知|提醒|消息)\s*[:：，,。]?',
        '',
        raw,
        flags=re.I,
    ).strip()
    cleaned = re.sub(r'(确认后|直接)?(推送|发送|发一下|通知一下)$', '', cleaned).strip()
    if not cleaned:
        cleaned = 'HR 事项提醒'
    title = cleaned[:80]
    content = cleaned
    notice_type = 'hr'
    if re.search(r'(审批|请假|报销|流程)', raw):
        notice_type = 'approval'
    elif re.search(r'(入职|offer|Offer|候选人|招聘|面试)', raw):
        notice_type = 'recruitment'
    elif re.search(r'(考勤|迟到|缺卡|打卡)', raw):
        notice_type = 'attendance'
    return {
        'title': title or 'HR 事项提醒',
        'content': content or title or '请查看相关 HRM 事项。',
        'notice_type': notice_type,
        'link_url': '/notifications',
    }


def extract_month(text: str) -> Optional[str]:
    iso = re.search(r'(20\d{2})[-年](\d{1,2})', text or '')
    if iso:
        return f'{iso.group(1)}-{int(iso.group(2)):02d}'
    if '这个月' in text or '本月' in text:
        return 'current_month'
    if '上个月' in text:
        return 'previous_month'
    return None


def extract_recent_days(text: str) -> Optional[int]:
    match = re.search(r'(?:最近|近)\s*(\d+)\s*天', text or '')
    if match:
        return int(match.group(1))
    if '最近' in text:
        return 30
    return None


def extract_limit(text: str) -> Optional[int]:
    match = re.search(r'(?:前|top\s*)(\d+)', text or '', re.I)
    if match:
        return max(1, min(int(match.group(1)), 50))
    chinese = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    match = re.search(r'前\s*([一二两三四五六七八九十])', text or '')
    if match:
        return chinese[match.group(1)]
    match = re.search(r'(\d+)\s*(?:个|位|名|人)', text or '')
    if match and re.search(r'(最多|排名|迟到|考勤异常|提醒|通知)', text or ''):
        return max(1, min(int(match.group(1)), 50))
    return None


def extract_approval_action(text: str) -> Optional[str]:
    if re.search(r'(驳回|拒绝|不同意)', text or ''):
        return 'reject'
    if re.search(r'(通过|同意|批准|过了)', text or ''):
        return 'approve'
    return None


def extract_approval_id(text: str) -> Optional[str]:
    patterns = [
        r'\b(eval-ap-[A-Za-z0-9_-]+)\b',
        r'\b((?:demo-)?approval-[A-Za-z0-9_-]+)\b',
        r'(?<![A-Za-z0-9_-])(ap-[A-Za-z0-9_-]+)\b',
        r'审批(?:ID|编号)?[：:\s#]*([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text or '', re.I)
        if match:
            return match.group(1).strip()
    return None


def extract_approval_rank(text: str) -> Optional[int]:
    if re.search(r'(第一条|第一个|第1条|第1个|首条|第一)', text or ''):
        return 1
    if re.search(r'(第二条|第二个|第2条|第2个)', text or ''):
        return 2
    if re.search(r'(第三条|第三个|第3条|第3个)', text or ''):
        return 3
    match = re.search(r'第\s*(\d+)\s*(?:条|个|项)', text or '')
    if match:
        return max(1, min(int(match.group(1)), 50))
    return None


def extract_approval_comment(text: str) -> Optional[str]:
    match = re.search(r'(?:意见|备注|理由)[：:]\s*(.+)$', text or '')
    if match:
        return match.group(1).strip()[:300]
    match = re.search(r'(?:意见|备注|理由)\s*([\u4e00-\u9fa5A-Za-z0-9_，,。；;\s-]{2,80})$', text or '')
    if match:
        value = match.group(1).strip(' ，,。；;')
        if value:
            return value[:300]
    return None


def extract_salary_adjustment_amount(text: str) -> Optional[float]:
    source = text or ''
    sign = -1 if re.search(r'(降薪|减薪|下调|降低|减少|-)', source) else 1
    amount_pattern = r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)\s*(?:元|块|人民币|CNY)?'
    contextual_patterns = [
        rf'(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资|上调|下调|增加|减少|降低)\s*{amount_pattern}',
        rf'{amount_pattern}\s*(?:元|块|人民币|CNY)?\s*(?:的)?\s*(?:调薪|薪资调整|薪酬调整|涨薪|加薪|降薪|减薪|工资调整|调整工资)',
    ]
    match = None
    for pattern in contextual_patterns:
        match = re.search(pattern, source)
        if match:
            break
    if not match:
        match = re.search(rf'{amount_pattern}\s*(?:元|块|人民币|CNY)', source)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(',', ''))
    except ValueError:
        return None
    if value == 0:
        return None
    if value < 0:
        return value
    return value * sign


def format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ''
    if number.is_integer():
        return str(int(number))
    return f'{number:.2f}'.rstrip('0').rstrip('.')


def extract_effective_date_hint(text: str) -> Optional[str]:
    match = re.search(r'20\d{2}-\d{1,2}-\d{1,2}', text or '')
    if match:
        return match.group(0)
    if re.search(r'(明天|后天|下周|本周|今天|月底|月初)', text or ''):
        return re.search(r'(明天|后天|下周[一二三四五六日天]?|本周[一二三四五六日天]?|今天|月底|月初)', text or '').group(0)
    return None


def extract_action_reason(text: str) -> Optional[str]:
    match = re.search(r'(?:原因|理由|备注)[：:]\s*(.+)$', text or '')
    if not match:
        return None
    return match.group(1).strip()[:300]


__all__ = [
    'clean_person_name',
    'clean_job_keyword',
    'extract_action_reason',
    'extract_approval_action',
    'extract_approval_comment',
    'extract_approval_id',
    'extract_approval_rank',
    'extract_candidate_name',
    'extract_effective_date_hint',
    'extract_employee_name_for_action',
    'extract_employee_name_for_query',
    'extract_job_context_keyword',
    'extract_job_keyword',
    'extract_limit',
    'extract_month',
    'extract_recent_days',
    'extract_resume_subject',
    'extract_schedule_hint',
    'extract_salary_adjustment_amount',
    'extract_target_department',
    'extract_target_position',
    'format_number',
    'attendance_reminder_confirm_slots',
    'is_attendance_reminder_confirm_question',
    'longest_job_phrase',
    'notification_slots',
]
