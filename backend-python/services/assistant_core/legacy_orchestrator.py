"""Legacy助手编排入口：组装 Router → Executor → Memory。

This module is retained as migration/test source only. Ordinary product traffic
and compatibility ``orchestrator.run`` now enter the Agent Kernel shim in
``assistant_core/orchestrator.py``.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import executor, memory, skill_registry
from .cache import query_cache
from .intent_router import permission_gate
from .intent_router import legacy_routing as routing
from .intent_router.legacy_pipeline import _entity_memory
from .intent_router.entity_memory import NamedEntity
from .executors import DialogueExecutor, GenerationExecutor, ToolExecutor
from .intent_router.legacy_planner import build_route_decision
from .schemas import (
    AssistantContext, ExecutionResult, RouteDecision, route_decision_to_router_result,
    router_result_to_route_decision,
)
from . import widgets as W
from . import workset_store
from .response_contract import apply_response_contract
from services.business_time import business_now

logger = logging.getLogger('hengpintong.assistant.orchestrator')


def _maybe_merge_clarification_reply(
    message: str, ctx: AssistantContext,
) -> Tuple[str, bool]:
    """如果上一轮是澄清且本轮回答匹配某个 option，把 origin_message 与本轮
    回答合并为新 query 后返回 ``(merged, True)``；否则返回 ``(message, False)``。

    与 Requirement 3.4 对齐：澄清不得丢失上一轮已抽取的信息。``ctx.history``
    中倒数第二条（assistant 角色）若 ``metadata.routePath == 'clarification'``
    （兼容 ``meta`` 与 ``metadata`` 两种 key、``routePath`` 与 ``route_path``
    两种命名），且本轮 ``message`` 等于上一轮某个 ``option.payload`` 或
    ``option.label`` → 合并为 ``f"{origin_message} {message}"``，再次调用
    路由层。``origin_message`` 取上一轮 metadata 中 ``originMessage`` /
    ``origin_message``；找不到时返回原始 message（不合并，避免污染）。
    """

    if not message:
        return message, False
    history = getattr(ctx, 'history', None) or []
    if not history:
        return message, False

    # 找最近一条 assistant 消息（保留兼容性：history 里也可能有 user）
    last_assistant: Optional[Dict[str, Any]] = None
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        if entry.get('role') == 'assistant':
            last_assistant = entry
            break
    if last_assistant is None:
        return message, False

    meta = last_assistant.get('meta')
    if not isinstance(meta, dict):
        meta = last_assistant.get('metadata')
    if not isinstance(meta, dict):
        return message, False

    route_path = meta.get('routePath') or meta.get('route_path')
    # 也兼容把 router payload 嵌套放在 meta['router'] 下的写法
    router_meta = meta.get('router') if isinstance(meta.get('router'), dict) else None
    if route_path != 'clarification' and router_meta is not None:
        route_path = router_meta.get('routePath') or router_meta.get('route_path')
    if route_path != 'clarification':
        return message, False

    options: List[Dict[str, Any]] = []
    raw_options = meta.get('clarificationOptions') or meta.get('clarification_options')
    if isinstance(raw_options, list):
        options = [o for o in raw_options if isinstance(o, dict)]
    elif router_meta is not None:
        raw = (router_meta.get('clarificationOptions')
               or router_meta.get('clarification_options'))
        if isinstance(raw, list):
            options = [o for o in raw if isinstance(o, dict)]

    if not options:
        return message, False

    msg_strip = message.strip()
    matched = False
    for opt in options:
        payload = opt.get('payload')
        label = opt.get('label')
        if isinstance(payload, str) and payload.strip() == msg_strip:
            matched = True
            break
        if isinstance(label, str) and label.strip() == msg_strip:
            matched = True
            break
    if not matched:
        return message, False

    origin = (meta.get('originMessage') or meta.get('origin_message'))
    if (not isinstance(origin, str) or not origin.strip()) and router_meta is not None:
        origin = (router_meta.get('originMessage')
                  or router_meta.get('origin_message'))
    if not isinstance(origin, str) or not origin.strip():
        return message, False

    merged = f'{origin.strip()} {msg_strip}'
    return merged, True


def _workset_eligible_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        e for e in (entities or [])
        if isinstance(e, dict) and e.get('type') in ('candidate', 'employee', 'resume', 'job', 'approval')
    ]


def _record_workset_if_needed(
    message: str,
    ctx: AssistantContext,
    result: ExecutionResult,
    entities_override: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    entities = _workset_eligible_entities(
        (entities_override if entities_override is not None else result.entities) or []
    )
    if not entities:
        return None
    label = message[:80] if message else '助手结果集'
    ws = workset_store.create_workset_from_entities(
        ctx.session_id,
        ctx.user_id,
        label,
        entities,
    )
    if ws:
        result.worksets.append(ws)
    return ws


def _clarification_result(
    question: str,
    ctx: AssistantContext,
    decision: RouteDecision,
    options: Optional[List[Dict[str, Any]]] = None,
) -> ExecutionResult:
    decision.task_type = 'clarification'
    decision.requires_confirmation = True
    decision.clarification_question = question
    decision.clarification_options = options or [
        {'label': '先查询候选人', 'payload': '查一下最近 5 个 Java 候选人'},
        {'label': '我补充对象', 'payload': '我来补充候选人信息'},
    ]
    router_result = route_decision_to_router_result(decision)
    return ExecutionResult(
        summary=question,
        entities=[],
        widgets=[W.clarification(question, decision.clarification_options, '')],
        session_id=ctx.session_id,
        router=router_result,
        route_decision=decision,
        requires_confirmation=True,
        answer={'content': question, 'format': 'markdown'},
    )


WORKSET_CONTEXT_KEYS = {'candidate_workset', 'latest_workset', 'workset', 'entity_workset'}
MAX_CONTEXT_ITEMS = 30


def _is_workset_reference_message(message: str) -> bool:
    return bool(re.search(
        r'(其中|里面|这些|这几个人|他们|她们|上面|刚才|列表里|表格里|结果里|名单里|'
        r'谁|哪位|哪个|最高|最低|最大|最小|最多|最少|评分|匹配度|经验|学历|年龄|年纪|'
        r'排名|排行|排序|比对|对比|报表|前\s*[一二两三四五六七八九十\d]+|top\s*\d+)',
        message or '',
        re.I,
    ))


def _has_workset_pool_reference(message: str) -> bool:
    return bool(re.search(
        r'(其中|里面|这些|这几个人|他们|她们|上面|刚才|列表里|表格里|结果里|名单里|'
        r'上述|以上|这批|排名|排行|排序|比对|对比|报表|'
        r'前\s*[一二两三四五六七八九十\d]+|top\s*\d+)',
        message or '',
        re.I,
    ))


def _needs_workset_context(decision: RouteDecision) -> bool:
    return bool(WORKSET_CONTEXT_KEYS.intersection(set(decision.required_context or [])))


def _item_fallback_facts(item: Dict[str, Any]) -> Dict[str, Any]:
    display = item.get('display_fields') if isinstance(item.get('display_fields'), dict) else {}
    return {
        'entity_type': item.get('entity_type'),
        'entity_id': item.get('entity_id'),
        'title': item.get('title'),
        'name': item.get('title'),
        'job_title': item.get('subtitle') or display.get('subtitle'),
        'summary': display.get('meta') or item.get('subtitle') or '',
        'source_tool': item.get('source_tool'),
        'context_status': 'summary_only',
    }


def _load_context_details(
    items: List[Dict[str, Any]],
    ctx: AssistantContext,
) -> List[Dict[str, Any]]:
    """Load desensitized details for WorkSet items through registered tools."""
    tool = ToolExecutor()
    details: List[Dict[str, Any]] = []
    for item in items[:MAX_CONTEXT_ITEMS]:
        facts: Dict[str, Any] = {}
        entity_type = item.get('entity_type')
        entity_id = item.get('entity_id')
        if entity_type == 'candidate':
            out = tool.execute('candidate_evidence_bundle', {'candidate_id': entity_id}, ctx)
        elif entity_type == 'resume':
            out = tool.execute('candidate_evidence_bundle', {'resume_id': entity_id}, ctx)
        elif entity_type == 'employee':
            out = tool.execute('employee_evidence_bundle', {'employee_id': entity_id}, ctx)
        elif entity_type == 'job':
            out = tool.execute('job_get_detail', {'job_id': entity_id}, ctx)
        else:
            out = {'ok': False}

        if out.get('ok') and out.get('data'):
            data = out.get('data') or {}
            facts = data.get('facts') or {}
        if not facts:
            facts = _item_fallback_facts(item)
        facts.setdefault('entity_type', entity_type)
        facts.setdefault('entity_id', entity_id)
        facts.setdefault('title', item.get('title'))
        details.append(facts)
    return details


def _workset_context_widgets(
    message: str,
    items: List[Dict[str, Any]],
    details: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not items:
        return []
    target = items[0]
    detail = details[0] if details else {}
    entity_type = str(target.get('entity_type') or detail.get('entity_type') or '')
    if entity_type not in {'candidate', 'resume'} and not re.search(r'(候选|简历|面试|推进|风险)', message or ''):
        return []
    name = (
        detail.get('name')
        or detail.get('candidate_name')
        or detail.get('title')
        or target.get('title')
        or '这位候选人'
    )
    name = str(name or '这位候选人').strip()
    actions = [
        {
            'label': '生成面试题',
            'payload': f'基于{name}的简历、面试记录和风险点生成结构化面试题',
            'variant': 'primary',
            'intent': 'interview_question_generation',
            'icon': 'fa-list-check',
        },
        {
            'label': '安排面试',
            'payload': f'给{name}安排明天下午三点面试',
            'variant': 'warning',
            'intent': 'interview_schedule',
            'requiresConfirmation': True,
            'icon': 'fa-calendar-plus',
            'description': '会进入写入动作二次确认，不会直接创建面试。',
        },
        {
            'label': '查看证据',
            'payload': f'汇总{name}的候选人、简历、面试和岗位证据',
            'variant': 'secondary',
            'intent': 'candidate_evidence_bundle',
            'icon': 'fa-link',
        },
    ]
    if len(items) > 1:
        actions.insert(1, {
            'label': '对比这批候选人',
            'payload': '把上面这批候选人按匹配度、风险和推进优先级重新对比',
            'variant': 'secondary',
            'intent': 'candidate_compare',
            'icon': 'fa-table-columns',
        })
    return [W.follow_up_actions(actions, title='推荐下一步')]


def _context_from_workset(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> Tuple[Optional[Dict[str, Any]], Optional[ExecutionResult]]:
    if not _needs_workset_context(decision):
        return {}, None
    resolved = workset_store.resolve_mention(message, ctx.session_id)
    if not resolved:
        return None, _clarification_result(
            '我还不知道“这几个人”指哪些候选人。请先查询候选人，或直接告诉我要基于哪些候选人生成。',
            ctx,
            decision,
        )
    ws = resolved.get('workset')
    raw_items = [resolved['item']] if resolved.get('kind') == 'item' else (ws.get('items') or [])
    items = list(raw_items[:MAX_CONTEXT_ITEMS])
    details = _load_context_details(items, ctx)
    return {
        'workset': ws,
        'items': items,
        'details': details,
        'widgets': _workset_context_widgets(message, items, details),
        'context_source': 'workset',
    }, None


def _extract_named_subject(message: str) -> Optional[str]:
    if _has_workset_pool_reference(message):
        return None
    text = re.sub(r'^\s*(?:帮我|请|查一下|看一下|了解一下)\s*', '', message or '')
    action_target = re.search(
        r'(?:给|为)\s*([\u4e00-\u9fa5·]{2,8}?)(?:安排|创建|新建)',
        text,
    )
    if action_target and not action_target.group(1).startswith(('这', '他', '她', '该', '上面', '刚才', '最', '排名')):
        return action_target.group(1)
    leading_subject = re.search(
        r'^\s*([\u4e00-\u9fa5·]{2,4})[，,、\s]*(?:我想|帮我|请|给|为|安排|创建|新建|预约|约)',
        text,
    )
    if leading_subject and not leading_subject.group(1).startswith(('这', '他', '她', '该', '上面', '刚才', '最', '排名', '给', '为')):
        return leading_subject.group(1)
    action_target = re.search(
        r'(?:安排|创建|新建)(?:给|为)?\s*([\u4e00-\u9fa5·]{2,8}?)(?:的)?'
        r'(?:面试|复试|跟进|任务|提醒)',
        text,
    )
    if action_target and not action_target.group(1).startswith(('这', '他', '她', '该', '上面', '刚才', '最', '排名')):
        return action_target.group(1)
    leading_verb = re.search(
        r'(?:分析|评价|评判|评估|判断|推荐)(?:一下)?\s*'
        r'([\u4e00-\u9fa5·]{2,8}?)(?:的|这个人|这位候选人|候选人|$)',
        text,
    )
    if leading_verb and leading_verb.group(1) not in {'最近', '候选人', '员工', '简历', '报告'}:
        return leading_verb.group(1)
    for separator in ('这个人', '这位候选人', '有没有', '的简历', '的面试', '的资料', '怎么样', '如何', '评价', '评判', '评估'):
        if separator in text:
            prefix = text.split(separator, 1)[0].strip(' ，,。?？')
            prefix = re.sub(r'(评分|分数|得分|匹配度|匹配|年龄|年纪|学历|经验|状态)$', '', prefix)
            match = re.search(r'([\u4e00-\u9fa5·]{2,8})$', prefix)
            if match and not match.group(1).startswith(('这', '他', '她', '该', '上面', '刚才')):
                return match.group(1)
    patterns = [
        r'([\u4e00-\u9fa5·]{2,8}?)(?:这个人|这位候选人|候选人)(?:怎么样|如何|评价|评判|评估|适合|推荐|优劣势)',
        r'([\u4e00-\u9fa5·]{2,4})(?:怎么样|如何|评价|评判|评估|适合|推荐|优劣势)',
        r'([\u4e00-\u9fa5·]{2,4}).*(?:简历|面试|Offer|offer|岗位|入职|考勤|绩效|培训|记录|进度)',
        r'([\u4e00-\u9fa5·]{2,8})的(?:简历|资料|详情)',
    ]
    for pattern in patterns:
        match = re.search(pattern, message or '')
        if match:
            name = match.group(1)
            if not name.startswith(('这', '上面', '刚才', '他们', '这些')):
                return name
    return None


def _extract_named_subjects(message: str) -> List[str]:
    """Extract explicit person names for grounded multi-candidate comparison."""
    names: List[str] = []
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
    for chunk in re.split(r'[、，,和与跟及]|以及', message or ''):
        chunk = chunk.strip()
        for pattern in (
            r'(?:基于|针对|根据|给|为|帮)\s*([\u4e00-\u9fa5·]{2,4})(?:设计|生成|出|准备)',
            r'(?:分析|评价|评判|评估|判断|推荐|比较|对比|针对|基于|根据|给|为|帮|帮我|请按|围绕|从证据看|把)\s*([\u4e00-\u9fa5·]{2,4})(?:这个人|这位候选人|候选人)?',
            r'(?:基于|针对|根据)\s*([\u4e00-\u9fa5·]{2,4})(?:简历|资料|面试|项目|风险|岗位)',
            r'帮\s*([\u4e00-\u9fa5·]{2,4})(?:设计|生成|出|准备)',
            r'([\u4e00-\u9fa5·]{2,4})(?:面试时|面试中|下一轮|二面|终面)',
            r'([\u4e00-\u9fa5·]{2,4})(?:的|是否|能否|能不能|适合|匹配|满足|符合|胜任|做|需要|生成|请|谁|哪个|哪位|$)',
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
                and not re.search(r'(候选人|简历|面试|岗位|职位|最近|Java|java|个人|总监|经理|主管|专员|顾问|工程师|分析师|会计)$', name)
                and name not in names
            ):
                names.append(name)
                break
    return names[:MAX_CONTEXT_ITEMS]


def _context_for_grounded_generation(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> Tuple[Optional[Dict[str, Any]], Optional[ExecutionResult]]:
    """Assemble evidence for named subjects or previously returned WorkSets."""
    if 'named_subjects_evidence' in (decision.required_context or []):
        subjects = _extract_named_subjects(message)
        if len(subjects) < 2:
            return None, _clarification_result('请告诉我要对比的候选人姓名，至少需要两位。', ctx, decision)
        tool_executor = ToolExecutor()
        details: List[Dict[str, Any]] = []
        entities: List[Dict[str, Any]] = []
        missing: List[str] = []
        items: List[Dict[str, Any]] = []
        for subject in subjects:
            tool_out = tool_executor.execute('candidate_evidence_bundle', {'keyword': subject}, ctx)
            data = tool_out.get('data') or {}
            facts = data.get('facts') or {}
            if not tool_out.get('ok') or not facts:
                missing.append(subject)
                continue
            details.append(facts)
            entities.extend(data.get('entities') or [])
            items.append({
                'entity_type': facts.get('entity_type') or 'candidate',
                'entity_id': (facts.get('candidate') or {}).get('candidate_id') or facts.get('entity_id') or subject,
                'title': facts.get('name') or subject,
            })
        if not details:
            missing_text = '、'.join(missing or subjects)
            return None, _clarification_result(f'系统内暂未找到“{missing_text}”的可分析记录。', ctx, decision)
        context: Dict[str, Any] = {
            'subjects': subjects,
            'items': items,
            'details': details,
            'entities': entities,
            'context_source': 'candidate_evidence_bundle',
        }
        if missing:
            context['missing_subjects'] = missing
        return context, None
    if 'named_subject_evidence' in (decision.required_context or []):
        subject = _extract_named_subject(message)
        if not subject:
            return None, _clarification_result('请告诉我要分析的人员姓名。', ctx, decision)
        tool_executor = ToolExecutor()
        tool_out = tool_executor.execute('candidate_evidence_bundle', {'keyword': subject}, ctx)
        if not tool_out.get('ok') or not (tool_out.get('data') or {}).get('facts'):
            tool_out = tool_executor.execute('employee_evidence_bundle', {'keyword': subject}, ctx)
        if not tool_out.get('ok') or not (tool_out.get('data') or {}).get('facts'):
            return None, _clarification_result(f'系统内暂未找到“{subject}”的可分析记录。', ctx, decision)
        data = tool_out.get('data') or {}
        return {
            'subject': subject,
            'details': [data.get('facts') or {}],
            'entities': data.get('entities') or [],
            'context_source': 'candidate_evidence_bundle',
        }, None
    return _context_from_workset(message, ctx, decision)


def _normalize_search_keyword(value: Any, original_message: str) -> str:
    text = str(value or '').strip() or str(original_message or '').strip()
    if not text:
        return ''
    noise_re = re.compile(
        r'(我们|咱们|公司|当前|现在|目前|现有|一共|总共|共有|多少|有多少|几个|几位|几名|几份|几条|几场|数量|总数|哪些|有哪些)'
    )
    for token in ('Java', 'java', 'Python', 'python', '前端', '后端', '产品', '运营', '测试', '销售', 'HR'):
        if token in text:
            return 'Java' if token.lower() == 'java' else 'Python' if token.lower() == 'python' else token
    job_match = re.search(
        r'([\u4e00-\u9fa5A-Za-z0-9]{2,24}?(?:工程师|技术员|总监|经理|专员|主管|助理|顾问|负责人|开发|设计师|会计|出纳|HR|hr))'
        r'(?:的|岗位|职位|候选人|简历|都|有|$)',
        text,
        flags=re.IGNORECASE,
    )
    if job_match:
        job_keyword = re.sub(r'^(最近|近\d+天|本周|本月|来|应聘|投递|招聘|找|查|搜索|查看|看看)+', '', job_match.group(1))
        return job_keyword or job_match.group(1)
    person_match = re.search(r'([\u4e00-\u9fa5·]{2,8})(?:的简历|这个人|候选人|员工|面试|怎么样|如何|$)', text)
    if (
        person_match
        and not person_match.group(1).startswith(('最近', '候选人', '简历', '员工'))
        and not noise_re.search(person_match.group(1))
    ):
        return person_match.group(1)
    cleaned = re.sub(
        r'(我们|咱们|公司|当前|现在|目前|现有|一共|总共|共有|帮我|请|一下|最近|近\s*\d+\s*天|'
        r'本周|本月|今天|明天|后天|上午|下午|晚上|来|投递|应聘|招聘中|开放中|招聘|在招|招人|的|都|有|'
        r'有哪些|哪些|什么|多少|有多少|几个|几位|几名|几份|几条|几场|数量|总数|哪些人|有哪些人|'
        r'候选人|简历|岗位|职位|面试|名单|列表|记录|安排|日程|排期|找|查|搜索|查看|看看|列出|'
        r'个|名|位|份|条|场|，|,|。|？|\?)',
        ' ',
        text,
    )
    cleaned = ' '.join(cleaned.split())
    return '' if cleaned in {'人', '岗', '招聘', '系统', '库', '中'} else cleaned[:40]


def _normalize_tool_plan_inputs(
    message: str,
    decision: RouteDecision,
) -> RouteDecision:
    system_modules_without_keyword = {
        'settings',
        'model_settings',
        'users',
        'roles',
        'operation_logs',
        'notifications',
    }
    for plan in decision.tool_plan or []:
        params = dict(plan.input or {})
        is_module_catalog = plan.tool == 'system_search' and params.get('module') == 'module_catalog'
        if is_module_catalog:
            plan.input = params
            continue
        is_system_module_listing = (
            plan.tool == 'system_search'
            and str(params.get('module') or '').lower() in system_modules_without_keyword
            and not params.get('keyword')
            and not params.get('query')
        )
        if plan.tool in ('recruitment_search', 'system_search', 'global_search', 'resume_analysis'):
            raw_keyword = params.get('keyword') or params.get('query')
            if plan.tool != 'recruitment_search' and not is_system_module_listing:
                raw_keyword = raw_keyword or message
            if plan.tool == 'recruitment_search' and raw_keyword in (None, ''):
                keyword = ''
            else:
                keyword = _normalize_search_keyword(raw_keyword, message)
            if is_system_module_listing:
                params.pop('keyword', None)
                params.pop('query', None)
            elif keyword:
                params['keyword'] = keyword
            elif 'keyword' in params:
                params.pop('keyword', None)
            if plan.tool == 'recruitment_search':
                if not params.get('module'):
                    if re.search(r'(简历|投递)', message or ''):
                        params['module'] = 'resumes'
                    elif re.search(r'(岗位|职位|JD|招聘需求)', message or '', flags=re.IGNORECASE):
                        params['module'] = 'jobs'
                    else:
                        params['module'] = 'candidates'
                if re.search(r'(最近|近\s*\d+\s*天|本周|本月)', message or ''):
                    date_range = params.get('date_range') if isinstance(params.get('date_range'), dict) else {}
                    recent_days = date_range.get('recent_days') or date_range.get('recentDays')
                    try:
                        recent_days_int = int(recent_days) if recent_days is not None else 0
                    except (TypeError, ValueError):
                        recent_days_int = 0
                    if recent_days_int < 30:
                        params['date_range'] = {**date_range, 'recent_days': 30}
            if plan.tool == 'resume_analysis':
                if keyword:
                    params['keyword'] = keyword
                params.setdefault('recent_days', 30 if '最近' in (message or '') else 7)
                params.setdefault('top_n', 10)
            if plan.tool == 'system_search':
                params.setdefault('limit', 12)
            if plan.tool == 'global_search':
                params.setdefault('limit', 10)
        plan.input = params
    return decision


def _execute_generation_track(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    context: Optional[Dict[str, Any]] = None
    if decision.tool_plan:
        context = _context_from_tool_plan(message, ctx, decision)
    if context is None:
        context, clarification = _context_for_grounded_generation(message, ctx, decision)
        if clarification:
            return clarification
    else:
        clarification = None
    if decision.generation_plan is None:
        from .schemas import GenerationPlan

        decision.generation_plan = GenerationPlan(template_id=decision.intent or 'generic_generation')
    result = GenerationExecutor().execute(
        message,
        ctx,
        decision.generation_plan,
        context=context or {},
        route_decision=decision,
    )
    result.router = route_decision_to_router_result(decision)
    context_widgets = (context or {}).get('widgets') or []
    if context_widgets:
        result.widgets.extend(widget for widget in context_widgets if isinstance(widget, dict))
    evidence_entities = (context or {}).get('entities') or []
    if evidence_entities:
        result.entities = evidence_entities
        _record_workset_if_needed(message, ctx, result)
    details = (context or {}).get('details') or []
    sources = []
    for detail in details:
        for source in detail.get('sources') or []:
            if source not in sources:
                sources.append(source)
    if sources:
        result.widgets.append({
            'type': 'source_citations',
            'title': '本次分析使用的系统记录',
            'sources': [{'title': value} for value in sources],
        })
    return result


def _context_from_tool_plan(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> Dict[str, Any]:
    """Execute read/load_context tools selected by the LLM planner."""
    tool_executor = ToolExecutor()
    outputs: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []
    facts_list: List[Dict[str, Any]] = []
    widgets: List[Dict[str, Any]] = []
    summary_hints: List[str] = []

    for plan in decision.tool_plan[:MAX_CONTEXT_ITEMS]:
        if plan.purpose == 'side_effect':
            continue
        out = tool_executor.execute(plan.tool, plan.input or {}, ctx)
        outputs.append(out)
        if not out.get('ok'):
            if plan.required:
                break
            continue
        data = out.get('data') or {}
        entities.extend(data.get('entities') or [])
        widgets.extend(data.get('widgets') or [])
        if data.get('facts'):
            facts = data.get('facts') or {}
            facts_list.append(facts)
            details.append(facts)
        if data.get('summary_hint'):
            summary_hints.append(str(data.get('summary_hint')))

    ws = None
    workset_entities: List[Dict[str, Any]] = []
    for out in outputs:
        data = out.get('data') if isinstance(out, dict) else {}
        raw_workset_entities = data.get('workset_entities') if isinstance(data, dict) else None
        if isinstance(raw_workset_entities, list):
            workset_entities.extend(item for item in raw_workset_entities if isinstance(item, dict))
    if entities or workset_entities:
        ws = workset_store.create_workset_from_entities(
            ctx.session_id,
            ctx.user_id,
            message[:80],
            workset_entities or entities,
        )
        if ws and not details:
            details = _load_context_details(ws.get('items') or [], ctx)

    return {
        'context_source': 'llm_skill_plan',
        'tool_outputs': outputs,
        'entities': entities,
        'facts': facts_list[0] if len(facts_list) == 1 else {'items': facts_list},
        'details': details,
        'widgets': widgets,
        'summary_hints': summary_hints,
        'workset': ws,
        'items': (ws.get('items') or [])[:MAX_CONTEXT_ITEMS] if ws else [],
    }


def _action_message_parts(message: str) -> Tuple[Optional[str], Optional[str]]:
    match = re.match(r'\s*(确认执行动作|取消动作)\s*[：:]\s*([A-Za-z0-9_-]+)\s*$', message or '')
    if match:
        return match.group(1), match.group(2)
    text = (message or '').strip()
    if re.fullmatch(r'(好的，?|没问题，?)?(确认吧?|确认执行|可以，?执行|是的，?执行吧|执行吧|执行)', text):
        return '确认执行动作', None
    if re.fullmatch(r'(不用了，?|算了，?)?(先)?(取消|取消执行|别执行|不用执行了?)', text):
        return '取消动作', None
    return None, None


def _parse_schedule_time(message: str) -> Optional[str]:
    iso_match = re.search(r'(20\d{2}-\d{2}-\d{2})\s*(?:T|\s)?\s*(\d{1,2})(?::(\d{2}))?', message or '')
    if iso_match:
        hour = int(iso_match.group(2))
        minute = int(iso_match.group(3) or 0)
        return f'{iso_match.group(1)}T{hour:02d}:{minute:02d}:00'
    if '明天' in (message or ''):
        hour = 15 if '下午' in message else 9
        minute = 0
        chinese_hours = {
            '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6,
            '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
        }
        match = re.search(r'(\d{1,2}|十二|十一|十|[一二两三四五六七八九])\s*点(?:\s*(半|\d{1,2}\s*分))?', message)
        if match:
            raw_hour = match.group(1)
            hour = int(raw_hour) if raw_hour.isdigit() else chinese_hours[raw_hour]
            raw_minute = match.group(2) or ''
            minute = 30 if raw_minute == '半' else int(re.sub(r'\D', '', raw_minute) or 0)
            if ('下午' in message or '晚上' in message) and hour < 12:
                hour += 12
            if '中午' in message and hour < 11:
                hour += 12
        return (business_now() + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        ).isoformat()
    if '后天' in (message or ''):
        hour = 15 if '下午' in message else 9
        minute = 0
        match = re.search(r'(\d{1,2}|十二|十一|十|[一二两三四五六七八九])\s*点', message)
        if match:
            chinese_hours = {
                '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6,
                '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
            }
            raw_hour = match.group(1)
            hour = int(raw_hour) if raw_hour.isdigit() else chinese_hours[raw_hour]
            if ('下午' in message or '晚上' in message) and hour < 12:
                hour += 12
        return (business_now() + timedelta(days=2)).replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        ).isoformat()
    return None


def _chinese_numeral_to_int(value: str) -> Optional[int]:
    text = (value or '').strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    numerals = {
        '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    }
    if text in numerals:
        return numerals[text]
    if text.startswith('十') and len(text) == 2:
        return 10 + numerals.get(text[1], 0)
    if text.endswith('十') and len(text) == 2:
        return numerals.get(text[0], 0) * 10
    match = re.match(r'([一二两三四五六七八九])十([一二两三四五六七八九])?', text)
    if match:
        return numerals.get(match.group(1), 0) * 10 + numerals.get(match.group(2) or '', 0)
    return None


def _parse_top_n(message: str) -> Optional[int]:
    text = message or ''
    patterns = [
        r'排名\s*前\s*([一二两三四五六七八九十\d]+)',
        r'前\s*([一二两三四五六七八九十\d]+)\s*(?:个|名|位)?',
        r'([一二两三四五六七八九十\d]+)\s*(?:个|名|位)?\s*(?:排名)?\s*最',
        r'top\s*([0-9]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            parsed = _chinese_numeral_to_int(match.group(1))
            if parsed:
                return max(1, min(parsed, MAX_CONTEXT_ITEMS))
    if re.search(r'前三名|前三位|前三个|排名前三', text):
        return 3
    return None


def _number_from_any(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r'-?\d+(?:\.\d+)?', value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _first_detail_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _number_from_any(value)
        if number is not None:
            return number
    return None


def _detail_score(detail: Dict[str, Any]) -> Optional[float]:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    candidate = detail.get('candidate') if isinstance(detail.get('candidate'), dict) else {}
    records = candidate.get('match_records') if isinstance(candidate.get('match_records'), list) else []
    record = records[0] if records and isinstance(records[0], dict) else {}
    return _first_detail_number(
        resume.get('score'),
        detail.get('score'),
        record.get('score'),
        record.get('finalScore'),
        record.get('managerScore'),
        record.get('selfScore'),
    )


def _detail_match_degree(detail: Dict[str, Any]) -> Optional[float]:
    resume = detail.get('resume') if isinstance(detail.get('resume'), dict) else {}
    candidate = detail.get('candidate') if isinstance(detail.get('candidate'), dict) else {}
    records = candidate.get('match_records') if isinstance(candidate.get('match_records'), list) else []
    record = records[0] if records and isinstance(records[0], dict) else {}
    return _first_detail_number(
        resume.get('match_degree'),
        resume.get('matchDegree'),
        detail.get('match_degree'),
        detail.get('matchDegree'),
        record.get('matchDegree'),
        record.get('match_degree'),
        record.get('match'),
    )


def _rank_details_for_action(details: List[Dict[str, Any]], message: str) -> List[Dict[str, Any]]:
    if not re.search(r'(排名|排行|评分|分数|得分|匹配|适合|推荐|优先|top|前\s*[一二两三四五六七八九十\d]+)', message or '', re.I):
        return details
    prefer_match = bool(re.search(r'(匹配|适合|推荐|优先)', message or ''))
    def sort_key(detail: Dict[str, Any]) -> Tuple[float, float, float]:
        score = _detail_score(detail)
        match = _detail_match_degree(detail)
        primary = match if prefer_match else score
        if primary is None:
            primary = score if score is not None else match
        return (
            primary if primary is not None else -1.0,
            score if score is not None else -1.0,
            match if match is not None else -1.0,
        )
    return sorted(details, key=sort_key, reverse=True)


def _prepare_action_confirmation(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    if decision.intent == 'followup_task_create' and not _needs_workset_context(decision):
        action_id = 'act_' + uuid.uuid4().hex[:12]
        label = '创建跟进任务'
        summary = f'{label}：{message}。确认后将在系统中创建提醒。'
        pending_action = {
            'id': action_id,
            'label': label,
            'tools': [{
                'tool': 'followup_task_create',
                'input': {'title': 'AI 助手跟进任务', 'content': message, 'due_at': _parse_schedule_time(message)},
            }],
            'summary': summary,
        }
        widget = W.confirmation_card(label, summary, action_id)
        result = ExecutionResult(
            summary=summary,
            widgets=[widget],
            session_id=ctx.session_id,
            router=route_decision_to_router_result(decision),
            route_decision=decision,
            requires_confirmation=True,
            actions=widget.get('actions') or [],
            answer={'content': summary, 'format': 'text'},
        )
        result._pending_action = pending_action
        return result

    context, clarification = _context_for_grounded_generation(message, ctx, decision)
    if clarification:
        if decision.intent == 'interview_schedule' and not _parse_schedule_time(message):
            return _clarification_result('请补充面试或复试的日期和时间，我会生成待确认安排。', ctx, decision)
        return clarification
    details = (context or {}).get('details') or []
    scheduled_at = _parse_schedule_time(message)
    if decision.intent == 'interview_schedule' and not scheduled_at:
        return _clarification_result('请补充面试或复试的日期和时间，我会生成待确认安排。', ctx, decision)
    tools = []
    names: List[str] = []
    item_limit = _parse_top_n(message)
    ranked_details = _rank_details_for_action(details, message)
    selected_details = ranked_details[:item_limit] if item_limit else ranked_details
    for detail in selected_details:
        candidate = detail.get('candidate') or {}
        resume = detail.get('resume') or detail
        job = detail.get('job') or {}
        name = detail.get('name') or resume.get('candidate_name') or '候选人'
        names.append(name)
        if decision.intent == 'interview_schedule':
            if not resume.get('resume_id') or not job.get('job_id'):
                continue
            tools.append({
                'tool': 'interview_create',
                'input': {
                    'resume_id': resume.get('resume_id'),
                    'job_id': job.get('job_id'),
                    'scheduled_at': scheduled_at,
                    'notes': f'由聘小犀根据对话确认创建：{name}复试',
                },
            })
        else:
            tools.append({
                'tool': 'followup_task_create',
                'input': {'title': f'跟进{name}', 'content': message, 'due_at': scheduled_at},
            })
    if not tools:
        return _clarification_result('已识别目标对象，但缺少可创建任务的关联记录，请先补充或查询详细信息。', ctx, decision)
    action_id = 'act_' + uuid.uuid4().hex[:12]
    label = '安排复试' if decision.intent == 'interview_schedule' else '创建跟进任务'
    display_time = scheduled_at.replace('T', ' ')[:16] if scheduled_at else '待确认'
    summary = f'{label}：{"、".join(names)}；时间：{display_time}。确认后将在系统中创建记录。'
    pending_action = {'id': action_id, 'label': label, 'tools': tools, 'summary': summary}
    widget = W.confirmation_card(label, summary, action_id)
    result = ExecutionResult(
        summary=summary,
        widgets=[widget],
        session_id=ctx.session_id,
        router=route_decision_to_router_result(decision),
        route_decision=decision,
        requires_confirmation=True,
        actions=widget.get('actions') or [],
        answer={'content': summary, 'format': 'text'},
    )
    result._pending_action = pending_action
    return result


def _execute_pending_action(message: str, ctx: AssistantContext, decision: RouteDecision) -> ExecutionResult:
    verb, action_id = _action_message_parts(message)
    pending = memory.get_pending_action(ctx.user_id, ctx.session_id, action_id)
    if not pending:
        return ExecutionResult(
            summary='没有找到可执行的待确认动作，可能已完成或已过期。',
            session_id=ctx.session_id,
            router=route_decision_to_router_result(decision),
            route_decision=decision,
        )
    if verb == '取消动作':
        result = ExecutionResult(
            summary=f'已取消：{pending.get("label") or "待执行动作"}。',
            session_id=ctx.session_id,
            router=route_decision_to_router_result(decision),
            route_decision=decision,
        )
        result._resolved_action_id = pending.get('id')
        result._pending_action = pending
        return result
    executed: List[str] = []
    allowed_tools = {
        'interview_create',
        'followup_task_create',
        'notification_create',
        'approval_decision',
        'employee_change_submit',
    }
    for plan in pending.get('tools') or []:
        tool_name = plan.get('tool')
        if tool_name not in allowed_tools:
            result = ExecutionResult(
                summary=f'不支持的确认动作：{tool_name or "未知工具"}。',
                session_id=ctx.session_id,
                router=route_decision_to_router_result(decision),
                route_decision=decision,
                error_code='confirmed_action_rejected',
            )
            result._resolved_action_id = pending.get('id')
            return result
        output = ToolExecutor().execute(tool_name, plan.get('input') or {}, ctx)
        if not output.get('ok'):
            return ExecutionResult(
                summary=f'执行失败：{output.get("error") or "业务工具调用失败"}。',
                session_id=ctx.session_id,
                router=route_decision_to_router_result(decision),
                route_decision=decision,
                error_code='confirmed_action_failed',
            )
        data = output.get('data') or {}
        executed.append(data.get('summary_hint') or f'已执行 {plan.get("tool")}。')
    result = ExecutionResult(
        summary='\n'.join(executed),
        session_id=ctx.session_id,
        router=route_decision_to_router_result(decision),
        route_decision=decision,
        answer={'content': '\n'.join(executed), 'format': 'text'},
    )
    result._resolved_action_id = pending.get('id')
    return result


def _execute_composite_track(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    if not decision.tool_plan:
        return _execute_generation_track(message, ctx, decision)
    tool_executor = ToolExecutor()
    first_plan = decision.tool_plan[0]
    tool_out = tool_executor.execute(first_plan.tool, first_plan.input, ctx)
    if not tool_out.get('ok'):
        return ExecutionResult(
            summary='我没能完成前置查询，因此没有生成内容。请稍后重试或缩小查询范围。',
            widgets=[W.warning(tool_out.get('error') or '前置查询失败', level='warning')],
            session_id=ctx.session_id,
            router=route_decision_to_router_result(decision),
            route_decision=decision,
            error_code='composite_tool_failed',
        )
    data = tool_out.get('data') or {}
    entities = data.get('entities') or []
    workset_entities = data.get('workset_entities') if isinstance(data.get('workset_entities'), list) else []
    ws = workset_store.create_workset_from_entities(
        ctx.session_id,
        ctx.user_id,
        message[:80],
        workset_entities or entities,
    )
    context = {
        'tool': first_plan.tool,
        'query': first_plan.input,
        'entities': entities,
        'summary_hint': data.get('summary_hint'),
        'workset': ws,
        'items': (ws.get('items') or [])[:MAX_CONTEXT_ITEMS] if ws else [],
    }
    if context['items']:
        context['details'] = _load_context_details(context['items'], ctx)
    result = GenerationExecutor().execute(
        message,
        ctx,
        decision.generation_plan,
        context=context,
        route_decision=decision,
    )
    result.router = route_decision_to_router_result(decision)
    result.entities = entities
    result.worksets = [ws] if ws else []
    if ws:
        result.widgets.append({
            'type': 'workset_summary',
            'title': ws.get('label'),
            'workset': ws,
        })
    return result


def _compose_tool_outputs(
    outputs: List[Dict[str, Any]],
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    summaries: List[str] = []
    entities: List[Dict[str, Any]] = []
    workset_entities: List[Dict[str, Any]] = []
    widgets: List[Dict[str, Any]] = []
    trace = []
    total_rows = 0

    from .schemas import ExecutionStep

    for output in outputs:
        tool = output.get('tool') or ''
        data = output.get('data') or {}
        rows_count = int(output.get('rows_count') or 0)
        total_rows += rows_count
        trace.append(ExecutionStep(
            step_id=tool,
            type='skill',
            skill=tool,
            status='ok' if output.get('ok') else 'error',
            rows_count=rows_count,
            error=output.get('error') or None,
            risk_level=(skill_registry.get(tool).risk_level if skill_registry.get(tool) else 'low'),
        ))
        if output.get('ok'):
            if data.get('summary_hint'):
                summaries.append(str(data.get('summary_hint')))
            entities.extend(data.get('entities') or [])
            raw_workset_entities = data.get('workset_entities')
            if isinstance(raw_workset_entities, list):
                workset_entities.extend(item for item in raw_workset_entities if isinstance(item, dict))
            widgets.extend(data.get('widgets') or [])
            if data.get('facts') and tool == 'smart_data_query':
                facts = data.get('facts') or {}
                sources = [
                    {
                        'module': 'database',
                        'recordType': 'table',
                        'id': table_name,
                        'title': table_name,
                    }
                    for table_name in (facts.get('tables') or [])
                ]
                if sources and not any(w.get('type') == 'source_citations' for w in widgets):
                    widgets.append({
                        'type': 'source_citations',
                        'title': '查询来源',
                        'sources': sources,
                    })
        else:
            summaries.append(f'{tool} 执行失败：{output.get("error") or "未知错误"}')

    friendly_summary = _friendly_tool_summary(outputs, message, decision)
    summary = friendly_summary or '\n'.join([s for s in summaries if s]) or (
        f'已完成 {len(outputs)} 个系统技能调用，返回 {total_rows} 条记录。'
    )
    result = ExecutionResult(
        summary=summary,
        entities=entities,
        widgets=widgets,
        session_id=ctx.session_id,
        trace=trace,
        router=route_decision_to_router_result(decision),
        route_decision=decision,
        answer={'content': summary, 'format': 'text'},
    )
    _record_workset_if_needed(message, ctx, result, workset_entities or None)
    return result


def _friendly_tool_summary(
    outputs: List[Dict[str, Any]],
    message: str,
    decision: RouteDecision,
) -> str:
    if not outputs:
        return ''

    def data_metrics(output: Dict[str, Any]) -> Dict[str, Any]:
        data = output.get('data') or {}
        metrics = data.get('metrics')
        return metrics if isinstance(metrics, dict) else {}

    def fmt_amount(value: Any) -> str:
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0.0
        if number.is_integer():
            return f'{number:,.0f}'
        return f'{number:,.2f}'

    if len(outputs) == 1 and outputs[0].get('ok'):
        output = outputs[0]
        tool = output.get('tool')
        metrics = data_metrics(output)
        data = output.get('data') or {}
        plan_input = decision.tool_plan[0].input if decision.tool_plan else {}
        if tool == 'attendance_analysis' and metrics:
            month = metrics.get('month') or plan_input.get('month')
            scope = f'{month} ' if month else ''
            return (
                f'{scope}共有 {metrics.get("totalRecords", output.get("rows_count") or 0)} 条考勤记录，'
                f'异常 {metrics.get("anomalyRecords", 0)} 次，正常 {metrics.get("normalRecords", 0)} 次。'
            )
        if tool == 'payroll_analysis' and metrics:
            month = metrics.get('month') or plan_input.get('month') or '当前筛选范围'
            return (
                f'{month}薪酬汇总：{metrics.get("recordCount", output.get("rows_count") or 0)} 条工资条，'
                f'应发合计 {fmt_amount(metrics.get("totalGross"))} 元，'
                f'实发合计 {fmt_amount(metrics.get("totalNet"))} 元。'
                '薪酬数据为敏感信息，请仅在授权范围内使用。'
            )
        if tool == 'performance_analysis' and metrics:
            levels = metrics.get('levelCounts') if isinstance(metrics.get('levelCounts'), dict) else {}
            level_text = '、'.join(f'{level} {count} 人' for level, count in levels.items()) or '暂无等级分布'
            return (
                f'共 {metrics.get("reviewCount", output.get("rows_count") or 0)} 条绩效评估，'
                f'已完成 {metrics.get("completedCount", 0)} 条，等级分布：{level_text}。'
            )
        if tool == 'training_analysis' and metrics:
            return (
                f'当前共有 {metrics.get("courseCount", 0)} 门课程、{metrics.get("planCount", 0)} 个培训计划，'
                f'培训记录 {metrics.get("recordCount", output.get("rows_count") or 0)} 条，'
                f'已完成 {metrics.get("completedCount", 0)} 条，完成率 {metrics.get("completionRate", 0)}%。'
            )
        if tool == 'approval_search' and metrics:
            view = metrics.get('view') or plan_input.get('view') or 'pending'
            view_label = {'mine': '我的申请', 'pending': '待我审批', 'history': '审批历史'}.get(view, '审批')
            return (
                f'{view_label}共有 {metrics.get("recordCount", output.get("rows_count") or 0)} 条记录，'
                'AI 助手仅展示与汇总，不会自动审批。'
            )
        if tool == 'feedback_triage' and metrics:
            statuses = metrics.get('statusCounts') if isinstance(metrics.get('statusCounts'), dict) else {}
            return (
                f'当前共有 {metrics.get("totalCount", output.get("rows_count") or 0)} 条反馈，'
                f'待处理 {metrics.get("pendingCount", 0)} 条，'
                f'处理中 {statuses.get("in_progress", 0)} 条，已解决 {statuses.get("resolved", 0)} 条。'
            )
        if data.get('summary_hint') and tool in {
            'attendance_analysis', 'payroll_analysis', 'performance_analysis',
            'training_analysis', 'approval_search', 'feedback_triage',
        }:
            return str(data.get('summary_hint'))

    if not all((output.get('tool') == 'recruitment_search' and output.get('ok')) for output in outputs):
        return ''

    def module_of(output: Dict[str, Any]) -> str:
        data = output.get('data') or {}
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if '岗位_total' in metrics:
            return 'jobs'
        if '候选人_total' in metrics:
            return 'candidates'
        if '简历_total' in metrics:
            return 'resumes'
        if '面试_total' in metrics:
            return 'interviews'
        if 'Offer_total' in metrics:
            return 'offers'
        for entity in data.get('entities') or []:
            t = entity.get('type')
            if t == 'job':
                return 'jobs'
            if t == 'candidate':
                return 'candidates'
            if t == 'resume':
                return 'resumes'
            if t == 'interview':
                return 'interviews'
            if t == 'offer':
                return 'offers'
        return ''

    def total_of(output: Dict[str, Any]) -> int:
        data = output.get('data') or {}
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        return int(metrics.get('total') or output.get('rows_count') or 0)

    by_module = {module_of(output): output for output in outputs if module_of(output)}
    text = message or ''

    if len(outputs) == 1:
        output = outputs[0]
        module = module_of(output)
        total = total_of(output)
        plan_input = {}
        if decision.tool_plan:
            plan_input = decision.tool_plan[0].input or {}
        if module == 'jobs' and plan_input.get('count_only') and plan_input.get('status') == 'open':
            return f'目前有 {total} 个招聘中的岗位。'
        if module == 'candidates' and plan_input.get('count_only'):
            keyword = plan_input.get('keyword')
            scope = f'{keyword}相关' if keyword else '当前'
            return f'{scope}候选人共有 {total} 人。'
        if module == 'resumes' and plan_input.get('count_only'):
            keyword = plan_input.get('keyword')
            scope = f'{keyword}相关' if keyword else '当前'
            return f'{scope}简历共有 {total} 份。'
        if module == 'interviews' and plan_input.get('count_only'):
            when = '明天' if '明天' in text else '当前筛选范围内'
            return f'{when}有 {total} 场面试。'
        if module == 'jobs':
            open_text = '招聘中的' if plan_input.get('status') == 'open' else ''
            if total:
                titles = [str(entity.get('title') or entity.get('name')) for entity in (output.get('data') or {}).get('entities') or []]
                titles = [title for title in titles if title][:5]
                detail = f'，包括：{"、".join(titles)}' if titles else ''
                return f'目前有 {total} 个{open_text}岗位{detail}。'
            return f'目前没有查到{open_text}岗位。'
        if module == 'candidates':
            keyword = plan_input.get('keyword')
            scope = f'{keyword}相关' if keyword else '当前'
            return f'{scope}候选人共有 {total} 人。'
        if module == 'resumes':
            keyword = plan_input.get('keyword')
            scope = f'{keyword}相关' if keyword else '当前'
            return f'{scope}简历共有 {total} 份。'
        if module == 'interviews':
            when = '明天' if '明天' in text else '当前筛选范围内'
            return f'{when}有 {total} 场面试。'

    if re.search(r'(招聘).{0,12}(怎么样|进展|情况|如何|到哪|推进)', text):
        keyword = ''
        for plan in decision.tool_plan or []:
            value = (plan.input or {}).get('keyword')
            if value:
                keyword = str(value)
                break
        title = f'{keyword}招聘' if keyword else '招聘'
        job_total = total_of(by_module.get('jobs', {})) if by_module.get('jobs') else 0
        candidate_total = total_of(by_module.get('candidates', {})) if by_module.get('candidates') else 0
        resume_total = total_of(by_module.get('resumes', {})) if by_module.get('resumes') else 0
        interview_total = total_of(by_module.get('interviews', {})) if by_module.get('interviews') else 0
        offer_total = total_of(by_module.get('offers', {})) if by_module.get('offers') else None
        state = '开放状态' if job_total else '暂未找到开放岗位'
        parts = [
            f'{title}目前是{state}',
            f'候选人 {candidate_total} 人',
            f'简历 {resume_total} 份',
            f'面试 {interview_total} 场',
        ]
        if offer_total is not None:
            parts.append(f'Offer {offer_total} 个')
        suggestion = '建议优先查看候选人质量和面试推进情况。' if candidate_total else '建议先确认岗位是否仍在招聘并补充候选人来源。'
        return '，'.join(parts) + f'。{suggestion}'

    return ''


def _execute_direct_tool_track(
    message: str,
    ctx: AssistantContext,
    decision: RouteDecision,
) -> ExecutionResult:
    outputs: List[Dict[str, Any]] = []
    tool_executor = ToolExecutor()
    for plan in decision.tool_plan[:4]:
        if plan.purpose == 'side_effect':
            return _prepare_action_confirmation(message, ctx, decision)
        output = tool_executor.execute(plan.tool, plan.input or {}, ctx)
        outputs.append(output)
        if plan.required and not output.get('ok'):
            break
    return _compose_tool_outputs(outputs, message, ctx, decision)


def _persist_entities_to_memory(message: str, result: ExecutionResult, ctx: AssistantContext) -> None:
    """将本轮查询结果中的实体写入 entity_memory，供后续代词消解使用。"""
    entities_to_store: List[NamedEntity] = []
    turn_index = len(ctx.history) // 2 if ctx.history else 0

    # 1. 从工作集中提取实体
    for ws in (getattr(result, 'worksets', None) or []):
        items = ws.get('items') if isinstance(ws, dict) else getattr(ws, 'items', None)
        for item in (items or []):
            if isinstance(item, dict):
                entity_type = item.get('entity_type')
                title = item.get('title') or ''
                entity_id = item.get('entity_id')
            else:
                entity_type = getattr(item, 'entity_type', None)
                title = getattr(item, 'title', None) or ''
                entity_id = getattr(item, 'entity_id', None)
            if entity_type in ('candidate', 'employee') and title:
                entities_to_store.append(NamedEntity(
                    type=entity_type,
                    value=title,
                    canonical_id=entity_id,
                    source_turn_index=turn_index,
                    expires_at=time.time() + 30 * 60,
                ))

    # 2. 从消息文本中提取已识别的人名
    subject = _extract_named_subject(message)
    if subject:
        # 避免重复
        existing_values = {e.value for e in entities_to_store}
        if subject not in existing_values:
            entities_to_store.append(NamedEntity(
                type='candidate',
                value=subject,
                source_turn_index=turn_index,
                expires_at=time.time() + 30 * 60,
            ))

    # 3. 合并写入 entity_memory（追加到已有实体列表）
    if entities_to_store and ctx.session_id:
        try:
            existing = _entity_memory._store.load(ctx.session_id)
            # 过滤掉已过期的
            now_ts = time.time()
            live = [e for e in existing if e.expires_at > now_ts]
            # 合并新实体（去重：同 type+value 的更新 turn_index）
            merged_map: Dict[Tuple[str, str], NamedEntity] = {}
            for e in live:
                merged_map[(e.type, e.value)] = e
            for e in entities_to_store:
                merged_map[(e.type, e.value)] = e
            _entity_memory._store.save(ctx.session_id, list(merged_map.values()))
        except Exception:  # noqa: BLE001
            logger.debug('entity_memory_merge_failed', exc_info=True)


def run(message: str, ctx: AssistantContext) -> ExecutionResult:
    """主入口：把用户消息处理为完整的助手响应。"""
    start = time.perf_counter()
    error_code: Optional[str] = None

    try:
        # 0. 检测上一轮澄清的 option 回答 → 合并 origin_message 后再路由。
        routing_message, merged = _maybe_merge_clarification_reply(message, ctx)

        action_verb, action_id = _action_message_parts(routing_message)
        resolved_message = routing_message  # 默认值，代词消解成功后会被覆盖
        if action_verb:
            route_decision = RouteDecision(
                task_type='action',
                route_track='CONFIRMED_ACTION',
                intent='execute_pending_action',
                confidence=1.0,
                risk_level='high',
                reason='chat_confirmation',
            )
        else:
            # --- 代词消解（前置于路由决策） ---
            entity_trace: Dict[str, Any] = {}
            if ctx.session_id:
                try:
                    if _is_workset_reference_message(routing_message) and workset_store.resolve_mention(routing_message, ctx.session_id):
                        resolved_message = routing_message
                        entity_trace = {'skipped': 'workset_reference'}
                    else:
                        resolved_message, entity_trace = _entity_memory.resolve(
                            routing_message, ctx.session_id, ctx,
                        )
                except Exception:  # noqa: BLE001
                    logger.exception('orchestrator_entity_resolve_failed')
                    resolved_message = routing_message

            if merged:
                old_router_result = routing.route(routing_message, ctx)
                route_decision = router_result_to_route_decision(
                    old_router_result,
                    route_track='A_DATA_ACTION',
                    task_type='action' if old_router_result.requires_confirmation else 'data_query',
                )
            else:
                route_decision = build_route_decision(resolved_message, ctx)
            route_decision = _normalize_tool_plan_inputs(resolved_message, route_decision)
            from .intent_router.semantic_refiner import enrich_complex_decision
            route_decision = enrich_complex_decision(resolved_message, ctx, route_decision)

        # 1. Hybrid route decision. A_DATA_ACTION continues to use the legacy
        # workflow executor; B/C/COMPOSITE bypass global_search/workflow.
        t0 = time.perf_counter()
        route_ms = (time.perf_counter() - t0) * 1000
        track = route_decision.route_track

        if route_decision.task_type == 'forbidden':
            track = 'A_DATA_ACTION'

        if track == 'CONFIRMED_ACTION':
            result = _execute_pending_action(routing_message, ctx, route_decision)

        elif (track == 'A_DATA_ACTION' and route_decision.task_type == 'action'
              and bool(route_decision.tool_plan)):
            result = _prepare_action_confirmation(routing_message, ctx, route_decision)

        elif track == 'A_DATA_ACTION' and bool(route_decision.tool_plan):
            result = _execute_direct_tool_track(routing_message, ctx, route_decision)

        elif track == 'A_DATA_ACTION':
            router_result = route_decision_to_router_result(route_decision)
            router_result = permission_gate.apply(router_result, ctx)
            effective_route_decision = router_result_to_route_decision(
                router_result,
                route_track=route_decision.route_track,
                task_type=route_decision.task_type,
            )

            # 2. 缓存查找（仅低风险 + 规则命中）
            cache_hit = False
            cache_key_tid = router_result.task_template_id or ''
            cache_key_ent = router_result.entities or {}
            if (router_result.rule_matched
                    and router_result.risk_level != 'high'
                    and not router_result.requires_confirmation):
                cached = query_cache.get(ctx.role, cache_key_tid, cache_key_ent)
                if cached:
                    cache_hit = True
                    result = ExecutionResult(
                        summary=cached.get('summary', ''),
                        entities=cached.get('entities', []),
                        widgets=cached.get('widgets', []),
                        session_id=ctx.session_id,
                        trace=[],
                        router=router_result,
                        route_decision=effective_route_decision,
                        fallback_used=False,
                    )
                    result._perf = {
                        'route_ms': round(route_ms, 1),
                        'exec_ms': 0,
                        'skill_ms': 0,
                        'llm_ms': 0,
                        'cache_hit': True,
                    }

            # 3. 执行（无缓存命中）
            if not cache_hit:
                t1 = time.perf_counter()
                result = executor.execute(message, router_result, ctx)
                result.route_decision = effective_route_decision
                exec_ms = (time.perf_counter() - t1) * 1000

                exec_perf = getattr(result, '_perf', {})
                result._perf = {
                    'route_ms': round(route_ms, 1),
                    'exec_ms': round(exec_ms, 1),
                    'skill_ms': exec_perf.get('skill_ms'),
                    'llm_ms': exec_perf.get('llm_ms'),
                    'cache_hit': False,
                }

                # 写入缓存（仅成功 + 低风险 + 有实际内容）
                if (not result.error_code
                        and not result.fallback_used
                        and router_result.risk_level != 'high'
                        and (result.entities or result.widgets)):
                    query_cache.put(ctx.role, cache_key_tid, cache_key_ent, {
                        'summary': result.summary,
                        'entities': result.entities,
                        'widgets': result.widgets,
                    })
            _record_workset_if_needed(routing_message, ctx, result)

        elif track == 'C_DIALOGUE_KNOWLEDGE':
            t1 = time.perf_counter()
            result = DialogueExecutor().execute(routing_message, ctx, route_decision)
            result.router = route_decision_to_router_result(route_decision)
            result._perf = {
                'route_ms': round(route_ms, 1),
                'exec_ms': round((time.perf_counter() - t1) * 1000, 1),
                'skill_ms': 0,
                'llm_ms': None,
                'cache_hit': False,
            }

        elif track == 'B_GENERATION':
            t1 = time.perf_counter()
            result = _execute_generation_track(resolved_message, ctx, route_decision)
            result._perf = {
                'route_ms': round(route_ms, 1),
                'exec_ms': round((time.perf_counter() - t1) * 1000, 1),
                'skill_ms': None,
                'llm_ms': None,
                'cache_hit': False,
            }

        elif track == 'COMPOSITE':
            t1 = time.perf_counter()
            result = _execute_composite_track(routing_message, ctx, route_decision)
            result._perf = {
                'route_ms': round(route_ms, 1),
                'exec_ms': round((time.perf_counter() - t1) * 1000, 1),
                'skill_ms': None,
                'llm_ms': None,
                'cache_hit': False,
            }

        else:
            result = DialogueExecutor().execute(routing_message, ctx, route_decision)
            result.router = route_decision_to_router_result(route_decision)
    except Exception:
        logger.exception('orchestrator_failed')
        from . import widgets as W
        result = ExecutionResult(
            summary='抱歉，处理您的请求时发生异常，请稍后重试或换个问法。',
            widgets=[W.warning('助手内部错误，已记录日志。', level='danger')],
            session_id=ctx.session_id,
            error_code='orchestrator_exception',
        )
        error_code = 'orchestrator_exception'

    apply_response_contract(result, ctx, message=message)

    # 3. 持久化对话
    router_obj = result.router
    decision_obj = result.route_decision
    is_clarification_emitted = bool(
        router_obj
        and router_obj.requires_confirmation
        and router_obj.clarification_options
    )
    metadata: Dict[str, Any] = {
        'router': router_obj.to_dict() if router_obj else None,
        'routeDecision': decision_obj.to_dict() if decision_obj else None,
        'routeTrack': decision_obj.route_track if decision_obj else None,
        'taskType': decision_obj.task_type if decision_obj else None,
        'errorCode': result.error_code,
        'fallbackUsed': result.fallback_used,
        'usedSkills': list(dict.fromkeys([s.skill for s in result.trace if s.skill])),
        'riskLevel': router_obj.risk_level if router_obj else 'low',
        'requiresConfirmation': result.requires_confirmation,
        'routePath': router_obj.route_path if router_obj else 'unknown',
        # Req 3.4：澄清轮 metadata 留住 originMessage，下一轮 orchestrator 可
        # 把它与回答合并；非澄清轮统一写 None 避免误用。
        'originMessage': message if is_clarification_emitted else None,
        'clarificationOptions': (
            list(router_obj.clarification_options)
            if is_clarification_emitted else []
        ),
        'worksets': list(result.worksets or []),
        'pendingAction': getattr(result, '_pending_action', None),
        'resolvedActionId': getattr(result, '_resolved_action_id', None),
    }
    saved_session = memory.save_turn(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        question=message,
        summary=result.summary or '',
        entity_count=len(result.entities or []),
        metadata=metadata,
        request_id=ctx.request_id,
        entities=result.entities or [],
        widgets=result.widgets or [],
        actions=result.actions or [],
        worksets=result.worksets or [],
        answer=result.answer,
        schema_version=result.schema_version,
        render_blocks=result.render_blocks or [],
        copilot=result.copilot or {},
        client_context=result.client_context or {},
    )
    result.session_id = saved_session or ctx.session_id

    # --- 将本轮产生的实体写入 entity_memory ---
    if ctx.session_id and result and not error_code:
        try:
            _persist_entities_to_memory(message, result, ctx)
        except Exception:  # noqa: BLE001
            logger.exception('entity_memory_persist_failed')

    duration = (time.perf_counter() - start) * 1000

    # 结构化日志（不含敏感数据）
    perf = getattr(result, '_perf', {})
    router_result_obj = result.router
    route_path = router_result_obj.route_path if router_result_obj else 'unknown'
    top_k = (
        [[task_id, float(score)] for task_id, score in (router_result_obj.top_k or [])]
        if router_result_obj else []
    )
    logger.info(
        'assistant_query_done',
        extra={
            'requestId': ctx.request_id,
            'userId': ctx.user_id,
            'role': ctx.role,
            'sessionId': result.session_id,
            'taskTemplateId': result.router.task_template_id if result.router else None,
            'intent': result.router.intent if result.router else None,
            'routeTrack': decision_obj.route_track if decision_obj else None,
            'taskType': decision_obj.task_type if decision_obj else None,
            'confidence': result.router.confidence if result.router else 0,
            'usedSkills': metadata['usedSkills'],
            'riskLevel': metadata['riskLevel'],
            'requiresConfirmation': result.requires_confirmation,
            'durationMs': round(duration, 1),
            'latencyMs': round(duration, 1),
            'routePath': route_path,
            'topK': top_k,
            'routeMs': perf.get('route_ms'),
            'execMs': perf.get('exec_ms'),
            'skillMs': perf.get('skill_ms'),
            'llmMs': perf.get('llm_ms'),
            'cacheHit': perf.get('cache_hit', False),
            'fallbackUsed': result.fallback_used,
            'errorCode': error_code or result.error_code,
        },
    )
    return result
