"""Dynamic Skill retrieval for the HRM Skill-first runtime.

This module is adapted from the core pattern in ``langgraph-bigtool``:
start an agent with a retrieval control tool, let the model/search layer select
only the relevant tools, and then bind/plan against that reduced candidate set.

HRM does not depend on LangGraph here. The same idea is rewritten around
``AgentSkillCard`` and ``RecallResult`` so the runtime can scale to 100+ cards
without pushing every skill into the planner prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from .cards import AgentSkillCard, all_cards, get_card
from .semantic_index import RecallResult, recall_skills


@dataclass
class SkillRetrievalState:
    """State accumulated while building the candidate Skill set."""

    query: str
    selected_skill_ids: List[str] = field(default_factory=list)
    retrieval_batches: List[Dict[str, Any]] = field(default_factory=list)

    def add_batch(self, *, source: str, results: Sequence[RecallResult]) -> None:
        ids: List[str] = []
        for result in results:
            if not result.skill_id or result.skill_id in self.selected_skill_ids:
                continue
            self.selected_skill_ids.append(result.skill_id)
            ids.append(result.skill_id)
        self.retrieval_batches.append({
            'source': source,
            'skill_ids': ids,
            'count': len(ids),
        })


def _add_new(left: List[str], right: Iterable[str]) -> List[str]:
    """Extend left list with new items from right, preserving order.

    Ported from ``langgraph-bigtool.graph._add_new`` and kept intentionally
    tiny because this behavior is the useful contract: duplicate retrievals
    should not duplicate available tools/skills.
    """

    seen = set(left)
    return left + [item for item in right if item not in seen]


def _card_text(card: AgentSkillCard) -> str:
    return ' '.join([
        card.id,
        card.name,
        card.domain,
        card.description,
        ' '.join(card.when_to_use or []),
        ' '.join(card.colloquial_examples or []),
        ' '.join(card.aliases or []),
    ])


def _hint_score(card: AgentSkillCard, hints: Dict[str, Any]) -> float:
    score = 0.0
    domains = {
        str(item).lower()
        for item in (hints.get('domain_hints') or hints.get('domains') or [])
        if item
    }
    if domains and card.domain.lower() in domains:
        score += 1.4
    intent_summary = str(hints.get('intent_summary') or hints.get('intent') or '')
    if intent_summary:
        recalled = recall_skills(intent_summary, top_k=20, cards=[card])
        if recalled:
            score += min(2.0, recalled[0].score / 3.0)
    keywords: List[str] = []
    for key in ('keywords', 'task_keywords', 'entity_mentions', 'reference_hints'):
        raw = hints.get(key)
        if isinstance(raw, list):
            keywords.extend(str(item) for item in raw if item)
        elif isinstance(raw, dict):
            keywords.extend(str(value) for value in raw.values() if value)
    text = _card_text(card).lower()
    for keyword in keywords[:30]:
        kw = str(keyword).strip().lower()
        if len(kw) >= 2 and kw in text:
            score += 0.35
    return score


def _looks_like_side_effect_intent(query: str) -> bool:
    text = query or ''
    return any(token in text for token in (
        '创建', '新建', '新增', '安排', '预约', '约面', '发送', '推送', '通知',
        '提醒我', '提交', '发起', '同意', '通过', '批准', '驳回', '拒绝',
        '调岗', '转岗', '调薪', '涨薪', '降薪',
    ))


def _looks_like_recent_resume_intent(query: str) -> bool:
    text = query or ''
    return bool(
        ('简历' in text or '投递' in text or '履历' in text)
        and re.search(r'(最近|近\s*\d+\s*天|本周|本月|今天|昨天|收到|收到了|新来|新收|新投|哪些|有哪些|质量)', text)
        and not re.search(r'[\u4e00-\u9fa5·]{2,8}的(?:简历|履历|资料)', text)
    )


def _looks_like_open_job_listing_intent(query: str) -> bool:
    text = query or ''
    if _looks_like_workflow_help_query(text):
        return False
    if not re.search(r'(岗位|职位|JD|jd|招聘需求)', text):
        return False
    has_listing = re.search(r'(在招|招聘中|开放|还招|正在招|正在招聘|新增|新开|缺人|没招满|哪些|有哪些|列表|清单)', text)
    if not has_listing:
        return False
    return not bool(re.search(r'(候选人|简历|人选|人才|匹配|适合|合适|推荐|优先|谁)', text))


def _looks_like_job_record_listing_intent(query: str) -> bool:
    text = query or ''
    if _looks_like_workflow_help_query(text):
        return False
    return bool(
        re.search(r'(岗位|职位|JD|jd|招聘需求)', text)
        and re.search(r'(新增|新开|创建了|发布了|本月|最近|哪些|有哪些|列表|清单)', text)
        and not re.search(r'(候选人|简历|人选|人才|匹配|适合|合适|推荐|优先|谁|漏斗|转化|阶段)', text)
    )


def _looks_like_workflow_help_query(query: str) -> bool:
    text = query or ''
    if not text:
        return False
    if re.search(r'(证据|依据|来源|记录|异常|名单|列表|数据|统计|趋势|分布|排名)', text) and not re.search(
        r'(怎么|如何|怎样|流程|步骤|教程|操作|指引|指南)',
        text,
    ):
        return False
    if re.search(r'(流程|说明|步骤|教程|操作|指引|指南)', text):
        return True
    if re.search(r'(怎么样|咋样|情况如何|状态如何|质量如何|能力如何|能力怎么样|进展如何|趋势如何|分布如何)', text):
        return False
    operation = r'(新增|添加|录入|创建|新建|删除|修改|编辑|更新|变更|安排|提交|确认|审批|通过|驳回|申请|办理|处理|补卡|上传|导入|发送|推送|发通知|调岗|转岗|调薪|涨薪|降薪)'
    return bool(
        re.search(rf'(怎么|如何|怎样).{{0,16}}{operation}', text)
        or re.search(rf'{operation}.{{0,16}}(怎么|如何|怎样)', text)
    )


def _side_effect_matches_text(card: AgentSkillCard, query: str) -> bool:
    text = query or ''
    if not card.side_effect:
        return True
    if card.id == 'interview.schedule_confirm_create':
        return bool(('面试' in text or '复试' in text or '约面' in text) and any(v in text for v in ('安排', '创建', '新建', '预约', '约')))
    if card.id == 'notification.create_confirm':
        return bool(
            ('通知' in text or '推送' in text or '提醒' in text)
            and any(v in text for v in ('发', '发送', '创建', '新建', '推送', '推一条', '推个', '群发'))
        )
    if card.id == 'approval.confirm_action':
        return bool(
            ('审批' in text or '申请' in text or re.search(r'第\s*[一二两三四五六七八九十\d]+条|这条|这一条|第一条|第二条', text))
            and any(v in text for v in ('同意', '通过', '过了', '批准', '驳回', '拒绝'))
        )
    if card.id == 'attendance.reminder_confirm':
        return bool(('考勤' in text or '迟到' in text or '打卡' in text) and any(v in text for v in ('提醒', '通知', '发送', '推送')))
    if card.id == 'task.followup_create_confirm':
        return bool(any(v in text for v in ('跟进任务', '跟进提醒', '待办', '提醒我')))
    if card.id == 'employee.change_submit_confirm':
        return bool(any(v in text for v in ('调岗', '转岗', '异动', '调到', '转到')))
    if card.id == 'employee.salary_adjustment_submit_confirm':
        return bool(any(v in text for v in ('调薪', '涨薪', '降薪', '薪资调整', '工资调整')))
    return _looks_like_side_effect_intent(text)


def _adjust_for_intent_consistency(query: str, result: RecallResult) -> RecallResult:
    card = get_card(result.skill_id)
    if not card:
        return result
    score = result.score
    workflow_help_like = _looks_like_workflow_help_query(query)
    if workflow_help_like:
        if result.skill_id == 'system.workflow_help':
            score += 32.0
        else:
            score *= 0.22
    if card.side_effect and not _side_effect_matches_text(card, query):
        score = score * 0.18
    if workflow_help_like and result.skill_id in {
        'candidate.resume_analysis',
        'candidate.search',
        'candidate.recent_resumes',
    }:
        score *= 0.35
    if result.skill_id == 'candidate.recent_resumes' and _looks_like_recent_resume_intent(query):
        score += 26.0
    if _looks_like_open_job_listing_intent(query) or _looks_like_job_record_listing_intent(query):
        if result.skill_id == 'recruitment.open_jobs':
            score += 24.0
        elif result.skill_id in {'recruitment.funnel', 'recruitment.overview'}:
            score *= 0.55
        elif result.skill_id in {
            'recruitment.job_candidate_match',
            'candidate.match_matrix',
            'candidate.job_fit',
            'candidate.evaluation',
            'candidate.compare',
            'candidate.search',
            'candidate.resume_analysis',
        }:
            score *= 0.28
    if result.skill_id == 'candidate.resume_analysis' and not workflow_help_like and ('简历' in (query or '') or '履历' in (query or '')):
        score += 18.0
    if result.skill_id == 'candidate.resume_analysis' and _looks_like_recent_resume_intent(query):
        score *= 0.42
    if result.skill_id == 'candidate.search' and ('简历' in (query or '') or '履历' in (query or '')):
        score *= 0.55
    if result.skill_id == 'attendance.employee_evidence' and re.search(r'(证据|凭证|明细|详情|原因|为什么)', query or ''):
        score += 4.0
    if score == result.score:
        return result
    return RecallResult(
        skill_id=result.skill_id,
        score=score,
        matched_text=result.matched_text,
        match_reason=f'{result.match_reason};intent_consistency_adjusted',
        matched_examples=result.matched_examples,
        anti_score=result.anti_score,
    )


def recall_from_skill_ids(
    skill_ids: Sequence[str],
    *,
    source: str = 'llm_skill_hint',
    base_score: float = 18.0,
) -> List[RecallResult]:
    """Create candidate RecallResult objects for model-proposed Skill IDs.

    Understanding-stage hints are BigTool-style dynamic retrieval signals. They
    should make a Skill visible to the bounded planner, not predetermine the
    final Skill choice.
    """

    results: List[RecallResult] = []
    for index, skill_id in enumerate(skill_ids):
        card = get_card(str(skill_id))
        if not card:
            continue
        results.append(RecallResult(
            skill_id=card.id,
            score=max(1.0, base_score - index),
            matched_text=f'{source}:{card.name}',
            match_reason=f'candidate_signal:{source}',
            matched_examples=card.colloquial_examples[:2],
            anti_score=0.0,
        ))
    return results


def retrieve_skills(
    query: str,
    *,
    normalized_query: str | None = None,
    understanding: Any | None = None,
    top_k: int = 16,
) -> List[RecallResult]:
    """Retrieve candidate Skills from multiple sources and merge by ID.

    The model may suggest skill IDs through the understanding stage, but those
    IDs are only candidates. The restricted planner still has to choose from the
    merged Top-K set and execution still goes through registered tools.
    """

    state = SkillRetrievalState(query=query)
    merged: Dict[str, RecallResult] = {}

    def add(source: str, batch: Sequence[RecallResult]) -> None:
        state.add_batch(source=source, results=batch)
        for result in batch:
            existing = merged.get(result.skill_id)
            if not existing:
                merged[result.skill_id] = result
            elif result.score > existing.score:
                merged[result.skill_id] = _merge_recall_evidence(primary=result, secondary=existing)
            else:
                merged[result.skill_id] = _merge_recall_evidence(primary=existing, secondary=result)

    if understanding is not None:
        hinted_ids = []
        if hasattr(understanding, 'candidate_skill_hints'):
            hinted_ids = list(getattr(understanding, 'candidate_skill_hints') or [])
        elif isinstance(understanding, dict):
            hinted_ids = list(understanding.get('candidate_skill_hints') or [])
        add('llm_skill_hints', recall_from_skill_ids(hinted_ids))

    add('semantic_user_text', recall_skills(query, top_k=max(top_k, 20), include_structural=True))
    if normalized_query and normalized_query.strip() and normalized_query.strip() != query.strip():
        add(
            'semantic_normalized_query',
            recall_skills(normalized_query, top_k=max(top_k, 20), include_structural=False, anti_query=query),
        )

    if understanding is not None:
        hints = understanding.to_dict() if hasattr(understanding, 'to_dict') else dict(understanding or {})
        hint_results: List[RecallResult] = []
        for card in all_cards():
            if card.id in merged:
                continue
            score = _hint_score(card, hints)
            if score <= 0:
                continue
            hint_results.append(RecallResult(
                skill_id=card.id,
                score=score,
                matched_text='understanding_hint',
                match_reason='understanding_hint_overlap',
                matched_examples=card.colloquial_examples[:2],
                anti_score=0.0,
            ))
        hint_results.sort(key=lambda item: item.score, reverse=True)
        add('understanding_hint_overlap', hint_results[:top_k])

    ranked = sorted(
        (_adjust_for_intent_consistency(query, item) for item in merged.values()),
        key=lambda item: item.score,
        reverse=True,
    )
    return ranked[:max(1, top_k)]


def _merge_recall_evidence(*, primary: RecallResult, secondary: RecallResult) -> RecallResult:
    if not secondary.match_reason or secondary.match_reason in primary.match_reason:
        return primary
    matched_examples = list(dict.fromkeys([
        *list(primary.matched_examples or []),
        *list(secondary.matched_examples or []),
    ]))[:5]
    matched_text = primary.matched_text
    if secondary.matched_text and secondary.matched_text not in matched_text:
        matched_text = f'{matched_text}; {secondary.matched_text}'[:240]
    return RecallResult(
        skill_id=primary.skill_id,
        score=primary.score,
        matched_text=matched_text,
        match_reason=f'{primary.match_reason};{secondary.match_reason}',
        matched_examples=matched_examples,
        anti_score=max(primary.anti_score, secondary.anti_score),
    )


__all__ = [
    'SkillRetrievalState',
    '_add_new',
    'recall_from_skill_ids',
    'retrieve_skills',
]
