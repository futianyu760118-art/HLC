"""Semantic recall over Agent Skill Cards.

The first production slice uses a deterministic sparse scorer built from card
fields, not legacy task-template triggers. It is intentionally simple and
transparent; an embedding backend can replace the scoring layer later without
changing the runtime contract.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .cards import AgentSkillCard, all_cards, get_card


_WORD_RE = re.compile(r'[A-Za-z0-9_]+|[\u4e00-\u9fa5]+')
_PHRASE_SPLIT_RE = re.compile(r'[，,。；;、\s]+')
_STOP_CHARS = set('的了呢吗啊呀吧和与及在把给看查问想要有没有一下这块这个这些那些上面刚才里面其中')
_STOP_TERMS = {
    '一下', '这个', '这些', '那些', '上面', '刚才', '里面', '其中', '我们', '公司',
    '帮我', '请问', '麻烦', '看看', '看下', '查下',
}
_SYNONYMS = {
    '工资': '薪资 薪酬 发薪 工资条 钱',
    '钱': '工资 薪资 薪酬 发薪 奖金 实发 应发',
    '打卡': '考勤 出勤 迟到 缺卡 早退',
    '不正常': '异常 不对劲 风险 问题',
    '不对劲': '异常 风险 问题 不正常',
    '咋样': '怎么样 如何 进展 概览',
    '靠不靠谱': '评估 评价 可靠 风险 推荐 推进',
    '靠谱': '评估 可靠 推荐 推进',
    '稳': '合适 推荐 风险低 可靠',
    '安排': '创建 约 面试 复试',
    '待办': '待处理 待审批 审批',
    '申请': '审批 流程',
    'bug': '反馈 问题 故障',
    '上面': '刚才 之前 结果集 workset',
    '第二个': '第二位 排名 指代 workset',
    '这个人': '指代 候选人 员工 workset 画像',
    '候选人': '应聘者 简历 投递 面试',
    '招聘': '岗位 候选人 简历 面试 offer 招人',
    '调岗': '异动 转岗 部门调整 员工变更 审批 确认',
    '转岗': '调岗 异动 部门调整 员工变更 审批 确认',
    '调薪': '涨薪 加薪 降薪 薪资调整 薪酬调整 审批 确认',
    '涨薪': '调薪 加薪 薪资调整 薪酬调整 审批 确认',
    '降薪': '调薪 减薪 薪资调整 薪酬调整 审批 确认',
}


@dataclass(frozen=True)
class RecallResult:
    skill_id: str
    score: float
    matched_text: str
    match_reason: str
    matched_examples: List[str] = field(default_factory=list)
    anti_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'skill_id': self.skill_id,
            'score': round(self.score, 4),
            'matched_text': self.matched_text,
            'match_reason': self.match_reason,
            'matched_examples': list(self.matched_examples),
            'anti_score': round(self.anti_score, 4),
        }


def normalize_query(text: str) -> str:
    normalized = (text or '').strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = normalized.replace('offer', 'Offer')
    for source, expansion in _SYNONYMS.items():
        if source.lower() in normalized.lower():
            normalized = f'{normalized} {expansion}'
    return normalized.strip()


def _tokens(text: str, *, expand_synonyms: bool = True) -> List[str]:
    raw = _WORD_RE.findall((text or '').lower())
    tokens: List[str] = []
    for tok in raw:
        if not tok or tok in _STOP_TERMS:
            continue
        if re.fullmatch(r'[\u4e00-\u9fa5]+', tok):
            tokens.extend(_cjk_terms(tok))
        elif tok not in _STOP_TERMS:
            tokens.append(tok)
    if expand_synonyms:
        for source, expansion in _SYNONYMS.items():
            if source.lower() in (text or '').lower():
                tokens.extend(_WORD_RE.findall(expansion.lower()))
    return tokens


def _cjk_terms(value: str) -> List[str]:
    text = ''.join(ch for ch in value if ch not in _STOP_CHARS)
    if not text:
        return []
    terms: List[str] = []
    if 2 <= len(text) <= 8 and text not in _STOP_TERMS:
        terms.append(text)
    for size in (2, 3, 4, 5):
        if len(text) < size:
            continue
        for index in range(0, len(text) - size + 1):
            term = text[index:index + size]
            if term in _STOP_TERMS or all(ch in _STOP_CHARS for ch in term):
                continue
            terms.append(term)
    return list(dict.fromkeys(terms))


def _phrases(text: str) -> List[str]:
    chunks = []
    for chunk in _PHRASE_SPLIT_RE.split(text or ''):
        chunk = chunk.strip().lower()
        if len(chunk) >= 2:
            chunks.append(chunk)
    return chunks


def _weighted_card_text(card: AgentSkillCard) -> List[Tuple[str, float, str]]:
    parts: List[Tuple[str, float, str]] = [
        (card.name, 3.0, 'name'),
        (card.domain, 1.4, 'domain'),
        (card.description, 2.2, 'description'),
        (' '.join(card.aliases or []), 2.8, 'aliases'),
        (' '.join(card.when_to_use), 3.0, 'when_to_use'),
        (' '.join(card.colloquial_examples), 3.6, 'colloquial_examples'),
        (' '.join(card.optional_slots), 0.9, 'optional_slots'),
        (' '.join(card.required_slots), 1.2, 'required_slots'),
        (' '.join(card.slot_extraction_hints.values()), 1.0, 'slot_extraction_hints'),
    ]
    tool = str((card.executor or {}).get('tool') or '')
    parts.append((tool, 1.6, 'executor'))
    return parts


def _anti_score(query_tokens: Sequence[str], query_phrases: Sequence[str], card: AgentSkillCard) -> float:
    score = 0.0
    for anti in card.anti_examples:
        anti_low = anti.lower()
        anti_tokens = set(_tokens(anti_low, expand_synonyms=False))
        overlap = len(set(query_tokens).intersection(anti_tokens))
        if overlap:
            score += min(0.6, overlap * 0.12)
        for phrase in query_phrases:
            if phrase and phrase in anti_low:
                score += 0.45
    return min(score, 1.5)


def _score_card(query: str, card: AgentSkillCard, *, anti_query: Optional[str] = None) -> Tuple[float, List[str], List[str], float]:
    normalized = normalize_query(query)
    query_tokens = _tokens(normalized)
    query_token_set = set(query_tokens)
    query_phrases = _phrases(query)
    anti_query_text = query if anti_query is None else anti_query
    anti_query_tokens = _tokens(anti_query_text, expand_synonyms=False)
    anti_query_phrases = _phrases(anti_query_text)
    matched_examples: List[str] = []
    reasons: List[str] = []
    score = 0.0

    if not query_token_set and not query_phrases:
        return 0.0, [], [], 0.0

    for text, weight, field_name in _weighted_card_text(card):
        if not text:
            continue
        field_tokens = set(_tokens(text))
        if not field_tokens:
            continue
        overlap = query_token_set.intersection(field_tokens)
        if overlap:
            tf_score = len(overlap) / math.sqrt(max(len(field_tokens), 1))
            score += weight * tf_score
            reasons.append(f'{field_name}:{",".join(sorted(overlap)[:6])}')
        low_text = text.lower()
        for phrase in query_phrases:
            if len(phrase) >= 2 and phrase in low_text:
                score += weight * 0.35
                reasons.append(f'{field_name}:phrase={phrase[:20]}')

    for example in card.colloquial_examples:
        example_low = example.lower()
        example_tokens = set(_tokens(example_low))
        overlap = query_token_set.intersection(example_tokens)
        if overlap:
            matched_examples.append(example)
            score += 0.55 * len(overlap)
        if any(phrase in example_low for phrase in query_phrases if len(phrase) >= 2):
            matched_examples.append(example)
            score += 1.2

    anti = _anti_score(anti_query_tokens, anti_query_phrases, card)
    final_score = max(0.0, score + (card.priority * 0.015) - anti)
    return final_score, reasons, matched_examples[:5], anti


def recall_skills(
    query: str,
    *,
    top_k: int = 8,
    cards: Iterable[AgentSkillCard] | None = None,
    include_structural: bool = True,
    anti_query: Optional[str] = None,
) -> List[RecallResult]:
    candidates: List[RecallResult] = []
    for card in cards or all_cards():
        score, reasons, matched_examples, anti = _score_card(query, card, anti_query=anti_query)
        if score <= 0:
            continue
        matched_text = '; '.join(matched_examples[:2]) or card.description[:80]
        candidates.append(RecallResult(
            skill_id=card.id,
            score=score,
            matched_text=matched_text,
            match_reason=';'.join(reasons[:8]) or 'card_semantic_overlap',
            matched_examples=matched_examples,
            anti_score=anti,
        ))
    if include_structural:
        _inject_structural_candidates(query, candidates)
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:max(1, top_k)]


def _inject_structural_candidates(query: str, candidates: List[RecallResult]) -> None:
    """Add Skill Card candidates for explicit structural intent.

    This remains Skill-first: the injected item is a formal Skill Card candidate,
    so the planner is still bounded to the Top-K card set. The score is only a
    recall signal; LLM planning and schema validation remain the decision layer.
    """
    text = query or ''
    wanted: Optional[str] = None
    if _is_approval_confirm_action_intent(text):
        wanted = 'approval.confirm_action'
    elif _is_notification_create_intent(text):
        wanted = 'notification.create_confirm'
    elif _is_recent_resume_intent(text):
        wanted = 'candidate.recent_resumes'
    elif _is_workflow_help_intent(text):
        wanted = 'system.workflow_help'
    elif _is_page_capability_intent(text):
        wanted = 'system.page_capability'
    elif _is_attendance_reminder_confirm_intent(text):
        wanted = 'attendance.reminder_confirm'
    elif _is_followup_create_intent(text):
        wanted = 'task.followup_create_confirm'
    elif _is_match_matrix_intent(text):
        wanted = 'candidate.match_matrix'
    elif _is_job_candidate_match_intent(text):
        wanted = 'recruitment.job_candidate_match'
    elif _is_interview_suggestion_intent(text):
        wanted = 'interview.suggestion'
    elif _is_interview_schedule_draft_intent(text):
        wanted = 'interview.schedule_draft'
    elif _is_candidate_job_fit_intent(text):
        wanted = 'candidate.job_fit'
    elif _is_interview_create_intent(text):
        wanted = 'interview.schedule_confirm_create'
    elif _is_salary_adjustment_submit_intent(text):
        wanted = 'employee.salary_adjustment_submit_confirm'
    elif _is_employee_change_submit_intent(text):
        wanted = 'employee.change_submit_confirm'
    elif _is_unsupported_write_boundary_intent(text):
        wanted = 'system.unsupported_write_intent'
    elif _is_pure_change_analysis_intent(text) and _has_any(text, r'(调岗|转岗|调到|转到|调入|转入|异动|部门调整|调整到)'):
        wanted = 'employee.change_impact'
    elif _is_approval_history_intent(text):
        wanted = 'approval.history'
    elif _is_feedback_summary_intent(text):
        wanted = 'feedback.summary'
    elif _is_interview_records_intent(text):
        wanted = 'interview.records'
    elif _is_employee_search_intent(text):
        wanted = 'employee.search'
    elif _is_payroll_performance_link_intent(text):
        wanted = 'payroll.performance_link'
    elif _is_complex_cross_stat_intent(text):
        wanted = 'smart.data_query'
    elif _is_open_job_intent(text):
        wanted = 'recruitment.open_jobs'
    if not wanted:
        if _is_interview_suggestion_intent(text):
            _append_neighbor_candidate(
                candidates,
                'interview.schedule_confirm_create',
                score=2.35,
                reason='neighbor_for_interview_suggestion_not_selected',
            )
        return
    card = get_card(wanted)
    if not card:
        return
    reason = wanted.replace('.', '_')
    top_existing_score = max((item.score for item in candidates), default=0.0)
    existing_score = 0.0
    for item in candidates:
        if item.skill_id == wanted:
            existing_score = max(existing_score, item.score)
    signal_score = max(
        existing_score + 1.6,
        top_existing_score + 0.8,
        9.5 + card.priority * 0.015,
    )
    boosted = RecallResult(
        skill_id=card.id,
        score=signal_score,
        matched_text=f'explicit_{reason}_candidate_signal',
        match_reason=f'candidate_signal:structural_intent:{wanted}',
        matched_examples=card.colloquial_examples[:1],
        anti_score=0.0,
    )
    for index, item in enumerate(candidates):
        if item.skill_id == wanted:
            candidates[index] = boosted if boosted.score > item.score else item
            if wanted == 'interview.suggestion':
                _append_neighbor_candidate(
                    candidates,
                    'interview.schedule_confirm_create',
                    score=2.35,
                    reason='neighbor_for_interview_suggestion_not_selected',
                )
            return
    candidates.append(boosted)
    if wanted == 'interview.suggestion':
        _append_neighbor_candidate(
            candidates,
            'interview.schedule_confirm_create',
            score=2.35,
            reason='neighbor_for_interview_suggestion_not_selected',
        )


def _append_neighbor_candidate(candidates: List[RecallResult], skill_id: str, *, score: float, reason: str) -> None:
    card = get_card(skill_id)
    if not card:
        return
    boosted = RecallResult(
        skill_id=card.id,
        score=score,
        matched_text=reason,
        match_reason=f'structural_neighbor:{reason}',
        matched_examples=card.colloquial_examples[:1],
        anti_score=0.0,
    )
    for index, item in enumerate(candidates):
        if item.skill_id == skill_id:
            if score > item.score:
                candidates[index] = boosted
            return
    candidates.append(boosted)


def _has_any(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text or '', re.I))


def _is_approval_confirm_action_intent(text: str) -> bool:
    if not _has_any(text, r'(同意|通过|过了|批准|驳回|拒绝|拒了|审批通过|审批驳回)'):
        return False
    if _has_any(text, r'(所有|全部|全都|批量|每一条|每个|都).{0,8}(审批|申请)?.{0,8}(同意|通过|过了|批准|驳回|拒绝|拒了)'):
        return False
    return _has_any(text, r'(审批|申请|请假|报销|流程|第\s*[一二两三四五六七八九十\d]+条|这条|这一条|第一条|第二条)')


def _is_unsupported_write_boundary_intent(text: str) -> bool:
    text = text or ''
    if not text or _is_workflow_help_intent(text):
        return False
    if (
        _is_interview_create_intent(text)
        or _is_notification_create_intent(text)
        or _is_attendance_reminder_confirm_intent(text)
        or _is_followup_create_intent(text)
        or _is_approval_confirm_action_intent(text)
        or _is_employee_change_submit_intent(text)
        or _is_salary_adjustment_submit_intent(text)
    ):
        return False
    return _has_any(
        text,
        r'(删除|删掉|删了|移除|清除|关闭|禁用|停用|修改|编辑|更新|改成|改为|改到|调整状态|直接更新|'
        r'上传|导入|批量上传|批量导入|新增|添加|录入|创建|新建|批量通过|全部通过|所有审批都通过)',
    )


def _is_notification_create_intent(text: str) -> bool:
    text = text or ''
    if _is_workflow_help_intent(text):
        return False
    if _has_any(text, r'(跟进任务|跟进提醒|个人待办|待办|回访|联系候选人)'):
        return False
    if _has_any(text, r'(删除|删掉|取消|改成|改为|修改|编辑|调整状态|查看|查询|历史|记录)'):
        return False
    has_notice = _has_any(text, r'(通知|提醒|消息|站内信|HR\s*通知|hr\s*通知)')
    has_create = _has_any(text, r'(推送|推一条|推个|推给|推通知|发送|群发|创建|新建|发一条|发个|发给|发通知|发消息|发提醒|发一下|通知一下)')
    has_content = _has_any(text, r'[:：]|内容是|内容为|培训|会议|入职|审批|考勤|请假|公告|提醒')
    return has_notice and has_create and has_content


def _is_recent_resume_intent(text: str) -> bool:
    text = text or ''
    if not _has_any(text, r'(简历|投递|履历)'):
        return False
    if _has_any(text, r'(安排|创建|新建|预约|约面|约一轮|面试|删除|修改|上传|导入)'):
        return False
    if _has_any(text, r'[\u4e00-\u9fa5·]{2,8}的(?:简历|履历|资料)'):
        return False
    return _has_any(text, r'(最近|近\s*\d+\s*天|本周|本月|今天|昨天|收到|收到了|新来|新收|新投|投递|哪些|有哪些|质量|TOP|top)')


def _is_approval_history_intent(text: str) -> bool:
    if _is_approval_confirm_action_intent(text):
        return False
    if not _has_any(text, r'(审批|申请|流程|报销|请假)'):
        return False
    return _has_any(text, r'(历史|之前|以前|过去|处理过|已处理|办过|通过的|驳回的|记录)')


def _is_feedback_summary_intent(text: str) -> bool:
    if _has_any(text, r'(候选人|面试反馈|绩效反馈|员工反馈|审批意见)'):
        return False
    return _has_any(text, r'(反馈|吐槽|抱怨|用户意见|用户建议|客户意见|客户建议|功能建议|都在说啥|主要在说什么)')


def _is_interview_records_intent(text: str) -> bool:
    if _has_any(text, r'(创建|新建|安排|预约|约一轮|约面|发送|通知|草稿|文案|面试题|面试问题|追问)'):
        return False
    return _has_any(text, r'(面试|复试|一面|二面|三面|终面|面评)') and _has_any(
        text,
        r'(记录|查|查询|查看|看下|看一下|有没有|面过没|安排到哪|到哪了|日程|排期)',
    )


def _is_open_job_intent(text: str) -> bool:
    text = text or ''
    has_job_target = bool(re.search(r'(岗位|职位|JD|jd|招聘需求)', text))
    has_open_status = bool(re.search(r'(在招|招聘中|开放|招人|缺人|还招|正在招|正在招聘)', text))
    return has_job_target and has_open_status


def _is_page_capability_intent(text: str) -> bool:
    text = text or ''
    if not _has_any(text, r'(你|助手|AI|ai|页面|模块|这里|当前|系统|恒聘通)'):
        return False
    return _has_any(text, r'(能做什么|能干嘛|可以做什么|可以干嘛|能帮.*什么|功能|功能清单|支持哪些|怎么用|能操作什么)')


def _is_workflow_help_intent(text: str) -> bool:
    text = text or ''
    if not text:
        return False
    if _has_any(text, r'(怎么样|咋样|最近如何|状态如何|总体如何|趋势如何|分布如何|进展如何|情况如何)'):
        return False
    if _has_any(text, r'(证据|依据|来源|记录|异常|名单|列表|数据|统计|排名)') and not _has_any(text, r'(怎么|如何|怎样|流程|教程|操作步骤|怎么做|怎么用)'):
        return False
    process_help = _has_any(text, r'(说明|流程|教程|解释|为什么|操作步骤|怎么做|怎么用)')
    help_near_operation = _has_any(
        text,
        r'(怎么|如何|怎样).{0,16}(新增|添加|录入|创建|新建|删除|修改|编辑|更新|变更|安排|提交|确认|审批|通过|驳回|申请|操作|办理|处理|补卡|上传|导入)',
    )
    operation_near_help = _has_any(
        text,
        r'(新增|添加|录入|创建|新建|删除|修改|编辑|更新|变更|安排|提交|确认|审批|通过|驳回|申请|补卡|上传|导入|跟进任务|待办|提醒).{0,16}'
        r'(怎么|如何|怎样|说明|流程|教程|解释|操作步骤)',
    )
    if not (process_help or help_near_operation or operation_near_help):
        return False
    direct_action = _has_any(
        text,
        r'^(帮我|请|麻烦|给|为|把|替我|帮).{0,12}(新增|添加|录入|创建|新建|删除|修改|编辑|更新|变更|安排|提交|通过|驳回|推送|发送)',
    )
    if direct_action and not _has_any(text, r'(怎么|如何|怎样|为什么|说明|流程|教程|解释)'):
        return False
    return True


def _is_followup_create_intent(text: str) -> bool:
    text = text or ''
    if _is_workflow_help_intent(text):
        return False
    if _is_attendance_reminder_confirm_intent(text):
        return False
    if _has_any(text, r'(删除|删掉|删了|取消|改成|改为|改到|修改|编辑|变更|重新安排|调整)'):
        return False
    has_create = _has_any(text, r'(创建|新建|新增|添加|安排|设个|加个|提醒我|帮我建|帮我创建)')
    has_task = _has_any(text, r'(跟进任务|跟进提醒|个人待办|待办|任务|提醒|回访|催|联系|复核|检查)')
    return has_create and has_task


def _is_attendance_reminder_confirm_intent(text: str) -> bool:
    text = text or ''
    if _is_workflow_help_intent(text):
        return False
    if _has_any(text, r'(删除|删掉|取消|改成|改为|修改|编辑|调整)'):
        return False
    has_attendance_rank = (
        _has_any(text, r'(迟到|考勤异常|打卡异常|缺卡|早退).{0,24}(最多|排名|前\s*\d+|前[一二两三四五六七八九十]|top\s*\d*)')
        or _has_any(text, r'(最多|排名|前\s*\d+|前[一二两三四五六七八九十]|top\s*\d*).{0,24}(迟到|考勤异常|打卡异常|缺卡|早退)')
    )
    has_reminder_action = _has_any(text, r'(生成|创建|新建|发|发送|推送|通知|提醒|待发送)')
    draft_only = _has_any(text, r'(只|仅|先).{0,6}(写|生成|出).{0,8}(草稿|文案|话术)')
    return bool(has_attendance_rank and has_reminder_action and not draft_only)


def _is_candidate_job_fit_intent(text: str) -> bool:
    text = text or ''
    if _is_match_matrix_intent(text) or _is_job_candidate_match_intent(text):
        return False
    has_candidate_context = _has_any(text, r'(候选人|简历|这个人|这位|他|她|[\u4e00-\u9fa5·]{2,4}的)')
    has_fit_word = _has_any(text, r'(岗位要求|符合|满足|适合|匹配|适配|胜任|个人能力|能力怎么样|靠不靠谱)')
    has_job_context = _has_any(text, r'(岗位|职位|工程师|经理|专员|主管|总监|要求|JD|jd)')
    return has_candidate_context and has_fit_word and has_job_context


def _is_match_matrix_intent(text: str) -> bool:
    text = text or ''
    if _looks_like_job_candidate_selection(text):
        return False
    return _has_any(text, r'(矩阵|matrix|Matrix|匹配表|匹配图谱|岗位.*候选人.*匹配|候选人.*岗位.*匹配)')


def _is_job_candidate_match_intent(text: str) -> bool:
    text = text or ''
    has_job = _has_any(text, r'(岗位|职位|工程师|经理|专员|主管|总监|JD|jd)')
    has_candidate = _has_any(text, r'(候选人|简历|人选|人才|谁|哪位|哪个)')
    has_list = _has_any(text, r'(哪些|有哪些|名单|列表|推荐|匹配|适合|合适|更合适|最合适|优先|推进|矩阵|对比)')
    return has_job and has_candidate and has_list


def _looks_like_job_candidate_selection(text: str) -> bool:
    text = text or ''
    return (
        _has_any(text, r'(岗位|职位|工程师|经理|专员|主管|总监|JD|jd)')
        and _has_any(text, r'(谁|哪位|哪个|候选人|简历|人选|人才)')
        and _has_any(text, r'(更合适|最合适|适合|匹配|推荐|优先|推进|对比|矩阵)')
    )


def _is_interview_suggestion_intent(text: str) -> bool:
    return _has_any(
        text,
        r'(先约谁|谁.*比较稳|哪位.*比较稳|哪个.*比较稳|面试建议|约面建议|该不该约|别浪费面试官时间)',
    )


def _is_interview_schedule_draft_intent(text: str) -> bool:
    return _has_any(text, r'(草稿|文案|邀请|话术|措辞)') and _has_any(text, r'(面试|复试|约面|面试官|候选人)')


def _is_interview_create_intent(text: str) -> bool:
    text = text or ''
    if _has_any(text, r'(删除|取消|改成|修改|调整|变更|改到)'):
        return False
    if _is_interview_schedule_draft_intent(text) or _has_any(text, r'(不要直接创建|不直接创建|先出|先写|只是草稿)'):
        return False
    if _has_any(text, r'(谁|哪个|哪位|比较|建议|推荐|适合|稳|该不该|先约谁|别浪费|面试官时间)'):
        return False
    has_create = _has_any(text, r'(安排|创建|新建|预约|约|约一轮|约面|排)')
    has_interview = _has_any(text, r'(面试|复试|一面|二面|三面|终面)')
    has_target = _has_any(text, r'(第二个|第二位|前两个|这个人|这位|他|她|[\u4e00-\u9fa5·]{2,4})')
    return has_create and has_interview and has_target


def _has_submit_or_confirmation_intent(text: str) -> bool:
    return _has_any(
        text,
        r'(提交|发起|创建|新建|准备确认|确认|待确认|走个|走一下|生效|执行|先分析.*准备|'
        r'(?:调岗|转岗|异动|调薪|涨薪|降薪|薪资调整|薪酬调整).{0,8}申请|'
        r'(?:提交|发起|创建|新建).{0,8}(?:审批|申请))',
    )


def _is_pure_change_analysis_intent(text: str) -> bool:
    return _has_any(text, r'(如果|假如|会影响|影响哪些|会怎样|会怎么样|先分析|模拟|看看影响|分析影响)')


def _is_employee_change_submit_intent(text: str) -> bool:
    if _is_salary_adjustment_submit_intent(text):
        return False
    if not _has_any(text, r'(调岗|转岗|调到|转到|调入|转入|异动|部门调整|调整到)'):
        return False
    if _is_pure_change_analysis_intent(text) and not _has_submit_or_confirmation_intent(text):
        return False
    return _has_submit_or_confirmation_intent(text) or _has_any(text, r'(把|给|为).{1,40}(调到|转到|调入|转入|调岗)')


def _is_salary_adjustment_submit_intent(text: str) -> bool:
    if not _has_any(text, r'(调薪|涨薪|加薪|降薪|减薪|薪资调整|薪酬调整|工资调整|调整工资|上调|下调)'):
        return False
    if _is_pure_change_analysis_intent(text) and not _has_submit_or_confirmation_intent(text):
        return False
    return _has_submit_or_confirmation_intent(text) or _has_any(text, r'(给|为|把).{1,40}(调薪|涨薪|加薪|降薪|减薪)')


def _is_employee_search_intent(text: str) -> bool:
    text = text or ''
    if _has_any(text, r'(新增|添加|录入|创建|新建|调岗|转岗|调薪|涨薪|降薪|删除|修改|编辑)'):
        return False
    return _has_any(text, r'(员工|同事|人员).{0,8}(找|查|搜|检索|在哪|资料|信息)|(?:找|查|搜|检索).{0,8}(员工|同事|人员)')


def _is_payroll_performance_link_intent(text: str) -> bool:
    return (
        _has_any(text, r'(绩效|低绩效|表现)')
        and _has_any(text, r'(工资|薪资|薪酬|钱)')
        and _has_any(text, r'(考勤|打卡|迟到|共同问题|不匹配|联动|关联|对得上)')
    )


def _is_complex_cross_stat_intent(text: str) -> bool:
    text = text or ''
    if not _has_any(text, r'(交叉|关联|联动|共同问题|相关性|综合统计|组合统计|一起统计)'):
        return False
    domains = 0
    for pattern in (r'(绩效|低绩效)', r'(考勤|打卡|迟到|缺卡)', r'(薪酬|工资|薪资)', r'(招聘|候选人|简历)', r'(离职|转正|调岗)'):
        if _has_any(text, pattern):
            domains += 1
    return domains >= 2


__all__ = ['RecallResult', 'normalize_query', 'recall_skills']
