"""Skill-specific result augmentation for the HRM Agent Kernel."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..schemas import ExecutionResult, RouteDecision
from ..skill_first.cards import AgentSkillCard


def augment_skill_specific_result(
    card: AgentSkillCard,
    result: ExecutionResult,
    outputs: List[Dict[str, Any]],
    message: str,
    decision: RouteDecision,
) -> None:
    if card.id == 'system.page_capability':
        augment_page_capability_result(result, outputs)
    elif card.id == 'system.workflow_help':
        augment_workflow_help_result(result, outputs, message)
    elif card.id == 'candidate.job_fit':
        augment_candidate_job_fit_result(result, outputs, message, decision)


def augment_page_capability_result(result: ExecutionResult, outputs: List[Dict[str, Any]]) -> None:
    if not outputs:
        return
    data = outputs[0].get('data') if isinstance(outputs[0], dict) else {}
    facts = data.get('facts') if isinstance(data, dict) else {}
    catalog_module = facts.get('catalogModule') if isinstance(facts.get('catalogModule'), dict) else {}
    if not catalog_module:
        return
    label = str(catalog_module.get('label') or '当前页面')
    capabilities = catalog_module.get('capabilities') if isinstance(catalog_module.get('capabilities'), list) else []
    upstream = catalog_module.get('upstream') if isinstance(catalog_module.get('upstream'), list) else []
    downstream = catalog_module.get('downstream') if isinstance(catalog_module.get('downstream'), list) else []
    readable = '、'.join(capability_label(item) for item in capabilities) or '基础查询与维护'
    flow_bits = []
    if upstream:
        flow_bits.append(f'上游关联：{"、".join(str(item) for item in upstream[:4])}')
    if downstream:
        flow_bits.append(f'下游关联：{"、".join(str(item) for item in downstream[:4])}')
    flow_text = '；'.join(flow_bits) if flow_bits else '可结合当前模块数据做查询和追问'
    summary = (
        f'在{label}页面，我可以帮你做：{readable}。'
        f'也可以用自然语言查询列表、筛选状态、解释进展，并基于结果继续追问；{flow_text}。'
        '涉及新增或创建类操作时我只会生成待确认动作；删除、直接修改等高风险操作不会自动执行。'
    )
    result.summary = summary
    result.answer = {'content': summary, 'format': 'text'}


def augment_workflow_help_result(result: ExecutionResult, outputs: List[Dict[str, Any]], message: str) -> None:
    if not outputs:
        return
    data = outputs[0].get('data') if isinstance(outputs[0], dict) else {}
    facts = data.get('facts') if isinstance(data, dict) else {}
    if not isinstance(facts, dict):
        return
    view = str(facts.get('view') or 'overview')
    label = 'HRM'
    flow_text = ''
    if view == 'module':
        catalog_module = facts.get('catalogModule') if isinstance(facts.get('catalogModule'), dict) else {}
        label = str(catalog_module.get('label') or '当前模块')
        capabilities = catalog_module.get('capabilities') if isinstance(catalog_module.get('capabilities'), list) else []
        if capabilities:
            flow_text = f'核心能力：{"、".join(capability_label(item) for item in capabilities[:5])}。'
    elif view == 'flow':
        flow = facts.get('flow') if isinstance(facts.get('flow'), dict) else {}
        label = str(flow.get('name') or '业务流程')
        modules = facts.get('modules') if isinstance(facts.get('modules'), list) else []
        names = [str(item.get('label')) for item in modules if isinstance(item, dict) and item.get('label')]
        if names:
            flow_text = f'涉及模块：{" -> ".join(names[:8])}。'
    else:
        label = 'HRM 系统'
        flows = facts.get('flows') if isinstance(facts.get('flows'), list) else []
        names = [str(item.get('name')) for item in flows if isinstance(item, dict) and item.get('name')]
        if names:
            flow_text = f'可参考链路：{"、".join(names[:5])}。'
    summary = (
        f'关于“{message}”，这是{label}的只读流程说明。'
        f'{flow_text}'
        '我可以解释入口、查询条件、关联模块和下一步建议；'
        '已支持的创建或提交类动作会先生成待确认动作，确认前不写库；'
        '删除、直接修改、直接更新等高风险操作需要到对应业务页面处理或由系统明确支持后再走确认流程。'
    )
    result.summary = summary
    result.answer = {'content': summary, 'format': 'text'}


def capability_label(value: Any) -> str:
    labels = {
        'job_requisition': '岗位需求与在招岗位查询',
        'headcount_tracking': '编制和缺口跟踪',
        'jd_scoring_criteria': 'JD 要求和评分标准解读',
        'resume_upload': '简历接收和上传记录查询',
        'ai_resume_analysis': 'AI 简历分析',
        'candidate_matching': '候选人与岗位匹配',
        'candidate_pipeline': '候选人阶段跟进',
        'source_tracking': '候选人来源分析',
        'ai_recommendation': 'AI 推进建议',
        'interview_schedule': '面试排期和安排确认',
        'feedback_analysis': '面试反馈分析',
        'online_interview': '在线面试记录关联',
    }
    return labels.get(str(value), str(value))


def augment_candidate_job_fit_result(
    result: ExecutionResult,
    outputs: List[Dict[str, Any]],
    message: str,
    decision: RouteDecision,
) -> None:
    if not outputs:
        return
    data = outputs[0].get('data') if isinstance(outputs[0], dict) else {}
    facts = data.get('facts') if isinstance(data, dict) else {}
    if not isinstance(facts, dict) or not facts:
        return
    plan_input = decision.tool_plan[0].input if decision.tool_plan else {}
    candidate = facts.get('candidate') if isinstance(facts.get('candidate'), dict) else {}
    resume = facts.get('resume') if isinstance(facts.get('resume'), dict) else {}
    job = facts.get('job') if isinstance(facts.get('job'), dict) else {}
    target_job_evidence = facts.get('target_job') if isinstance(facts.get('target_job'), dict) else {}
    name = facts.get('name') or candidate.get('name') or resume.get('candidate_name') or plan_input.get('keyword') or '该候选人'
    target_job = (
        target_job_evidence.get('title')
        or plan_input.get('job_keyword')
        or extract_job_label_from_text(message)
        or job.get('title')
        or '岗位要求'
    )
    score = resume.get('score')
    match_degree = resume.get('match_degree') or resume.get('matchDegree')
    strengths = resume.get('strengths') if isinstance(resume.get('strengths'), list) else []
    weaknesses = resume.get('weaknesses') if isinstance(resume.get('weaknesses'), list) else []
    summary_bits = [f'{name}的能力与{target_job}要求已基于候选人、简历和关联岗位证据完成核对。']
    if score is not None:
        summary_bits.append(f'简历评分 {score} 分')
    if match_degree is not None:
        summary_bits.append(f'匹配度 {match_degree}%')
    if strengths:
        summary_bits.append('亮点：' + '、'.join(str(item) for item in strengths[:3]))
    if weaknesses:
        summary_bits.append('需复核：' + '、'.join(str(item) for item in weaknesses[:3]))
    if target_job_evidence.get('requirements'):
        requirements = str(target_job_evidence.get('requirements') or '').strip()
        if requirements:
            summary_bits.append(f'{target_job}要求：{requirements[:80]}')
    elif plan_input.get('job_keyword') or extract_job_label_from_text(message):
        summary_bits.append(f'未找到{target_job}的岗位详情，当前只能按候选人证据做初步适配判断')
    if job.get('title') and target_job != job.get('title'):
        summary_bits.append(f'注意：系统当前关联岗位是{job.get("title")}；本次按你指定的{target_job}做适配核对。')
    summary = '；'.join(summary_bits) + '。'
    result.summary = summary
    result.answer = {'content': summary, 'format': 'text'}


def extract_job_label_from_text(text: str) -> Optional[str]:
    match = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·]{2,18}(?:工程师|专员|经理|总监|主管|岗位|职位))(?:岗位)?(?:要求|吗|么|$)', text or '')
    if not match:
        return None
    value = match.group(1).strip(' ，,。?？')
    for _ in range(3):
        previous = value
        value = re.sub(r'^(?:符合|满足|适合|匹配|适配|胜任|能不能|是否|判断|评估|看看)(?:的)?', '', value)
        value = re.sub(r'^(?:我们|咱们|公司|本公司|贵司|团队|部门)(?:的)?', '', value)
        value = re.sub(r'^(?:当前|现在|现有|在招|招聘中|正在招聘|正在招|要招)(?:的)?', '', value)
        value = re.sub(r'^(?:岗位|职位)(?:的)?', '', value)
        if value == previous:
            break
    if value.endswith('岗位') and len(value) > 2:
        return value[:-2]
    if value.endswith('职位') and len(value) > 2:
        return value[:-2]
    return value


def augment_candidate_evidence_widgets(outputs: List[Dict[str, Any]]) -> None:
    for output in outputs:
        if not isinstance(output, dict) or output.get('tool') != 'candidate_evidence_bundle':
            continue
        data = output.get('data') if isinstance(output.get('data'), dict) else {}
        facts = data.get('facts') if isinstance(data.get('facts'), dict) else {}
        sources = facts.get('sources') if isinstance(facts.get('sources'), list) else []
        widgets = data.get('widgets') if isinstance(data.get('widgets'), list) else []
        if sources and any(isinstance(widget, dict) and widget.get('type') == 'source_citations' for widget in widgets):
            sources = []
        if sources:
            source_map = {
                'candidate': {'module': 'candidates', 'recordType': 'candidate', 'title': f'{facts.get("name") or "候选人"} 候选人记录'},
                'resume': {'module': 'resumes', 'recordType': 'resume', 'title': f'{facts.get("name") or "候选人"} 简历'},
                'job': {'module': 'jobs', 'recordType': 'job', 'title': (facts.get('job') or {}).get('title') if isinstance(facts.get('job'), dict) else '关联岗位'},
                'interview': {'module': 'interviews', 'recordType': 'interview', 'title': '面试记录'},
                'offer': {'module': 'offers', 'recordType': 'offer', 'title': 'Offer记录'},
                'employee': {'module': 'employees', 'recordType': 'employee', 'title': '关联员工档案'},
            }
            widgets.append({
                'type': 'source_citations',
                'title': '本次使用的系统记录',
                'sources': [dict(source_map.get(str(source), {'title': str(source)})) for source in sources],
            })
            data['widgets'] = widgets
        entities = data.get('entities') if isinstance(data.get('entities'), list) else []
        workset_entities = data.get('workset_entities') if isinstance(data.get('workset_entities'), list) else []
        name = facts.get('name')
        candidate = facts.get('candidate') if isinstance(facts.get('candidate'), dict) else {}
        resume = facts.get('resume') if isinstance(facts.get('resume'), dict) else {}
        job = facts.get('job') if isinstance(facts.get('job'), dict) else {}
        if not name:
            name = candidate.get('name') or resume.get('candidate_name')
        if candidate.get('candidate_id'):
            candidate_entity = {
                'type': 'candidate',
                'id': candidate.get('candidate_id'),
                'title': name or candidate.get('name') or '候选人',
                'subtitle': job.get('title') or '',
            }
            append_entity_once(entities, candidate_entity)
            append_entity_once(workset_entities, candidate_entity)
        if resume.get('resume_id'):
            resume_entity = {
                'type': 'resume',
                'id': resume.get('resume_id'),
                'title': name or resume.get('candidate_name') or '简历',
                'subtitle': job.get('title') or '',
            }
            append_entity_once(entities, resume_entity)
        if job.get('job_id'):
            job_entity = {
                'type': 'job',
                'id': job.get('job_id'),
                'title': job.get('title') or '岗位',
                'subtitle': job.get('department') or '',
            }
            append_entity_once(entities, job_entity)
        data['entities'] = entities
        data['workset_entities'] = workset_entities


def append_entity_once(items: List[Dict[str, Any]], entity: Dict[str, Any]) -> None:
    entity_id = entity.get('id')
    entity_type = entity.get('type')
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get('id') == entity_id and item.get('type') == entity_type:
            return
    items.append(entity)


__all__ = [
    'append_entity_once',
    'augment_candidate_evidence_widgets',
    'augment_candidate_job_fit_result',
    'augment_page_capability_result',
    'augment_skill_specific_result',
    'augment_workflow_help_result',
    'capability_label',
    'extract_job_label_from_text',
]
