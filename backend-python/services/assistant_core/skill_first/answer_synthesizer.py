"""Grounded LLM answer synthesis for read-only Skill results."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .. import llm_client
from ..schemas import AssistantContext, ExecutionResult, RouteDecision
from . import llm_health
from .cards import AgentSkillCard
from . import llm_runtime_config


GROUNDABLE_DOMAINS = {
    'recruitment',
    'candidate',
    'interview',
    'employee',
    'organization',
    'attendance',
    'performance',
    'payroll',
    'approval',
    'feedback',
    'report',
    'workset',
}


def _enabled() -> bool:
    flag = os.getenv('ASSISTANT_SKILL_FIRST_SYNTHESIS')
    if flag is None:
        return False
    if flag.strip().lower() in {'0', 'false', 'off', 'no'}:
        return False
    if not llm_client.is_available():
        return False
    health_allowed, _reason, _health = llm_health.availability('skill_first_grounded_answer')
    return health_allowed


def _compact_output(output: Dict[str, Any]) -> Dict[str, Any]:
    data = output.get('data') if isinstance(output.get('data'), dict) else {}
    return {
        'ok': output.get('ok'),
        'tool': output.get('tool'),
        'rows_count': output.get('rows_count'),
        'error': output.get('error'),
        'summary_hint': data.get('summary_hint'),
        'metrics': data.get('metrics'),
        'facts': data.get('facts'),
        'entities': (data.get('entities') or [])[:8],
        'workset_entities': (data.get('workset_entities') or [])[:8],
    }


def _messages(
    *,
    message: str,
    card: AgentSkillCard,
    result: ExecutionResult,
    outputs: List[Dict[str, Any]],
    decision: RouteDecision,
    playbook: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    payload = {
        'user_text': message,
        'selected_skill': card.to_dict(),
        'route_decision': decision.to_dict(),
        'skill_playbook': playbook or {},
        'current_answer': result.answer or {'content': result.summary},
        'tool_outputs': [_compact_output(output) for output in outputs],
        'entities': (result.entities or [])[:12],
        'widgets': [
            {
                'type': widget.get('type'),
                'title': widget.get('title'),
                'summary': widget.get('summary') or widget.get('description'),
            }
            for widget in (result.widgets or [])[:10]
            if isinstance(widget, dict)
        ],
        'contract': {
            'must_be_grounded': True,
            'no_new_facts': True,
            'preserve_sensitive_boundaries': True,
            'language': 'Chinese',
            'format': 'concise markdown',
        },
    }
    return [
        {
            'role': 'system',
            'content': (
                '你是 HRM Agent 的证据化回答合成器。你只能基于 tool_outputs、entities、widgets '
                '和 skill_playbook/current answer 组织更自然的中文回答，不能添加系统没有返回的事实，不能伪造记录，'
                '不能承诺已执行写操作。薪酬、绩效、员工敏感信息必须遵守已返回的脱敏和权限边界。'
            ),
        },
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def synthesize_answer(
    *,
    message: str,
    ctx: AssistantContext,
    card: AgentSkillCard,
    result: ExecutionResult,
    outputs: List[Dict[str, Any]],
    decision: RouteDecision,
    playbook: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if not _enabled() or card.side_effect or card.domain not in GROUNDABLE_DOMAINS:
        return None
    if not outputs or any(not output.get('ok') for output in outputs):
        return None
    try:
        response = llm_client.chat_profile(
            'standard',
            _messages(message=message, card=card, result=result, outputs=outputs, decision=decision, playbook=playbook),
            temperature=0.2,
            max_tokens=900,
            timeout=llm_runtime_config.synthesis_timeout(),
            use_case='skill_first_grounded_answer',
            ctx=ctx,
            retry_once=False,
        )
        llm_health.record_call_result('skill_first_grounded_answer', llm_client.last_call_meta())
    except Exception:
        llm_health.record_failure('skill_first_grounded_answer', {'status': 'error'})
        return None
    content = str((response or {}).get('content') or '').strip()
    if not content:
        return None
    return content[:4000]


def apply_synthesized_answer(result: ExecutionResult, content: str) -> None:
    if not content:
        return
    result.summary = content
    answer = dict(result.answer or {})
    answer['content'] = content
    answer['format'] = answer.get('format') or 'markdown'
    result.answer = answer
    for block in result.render_blocks or []:
        if isinstance(block, dict) and block.get('id') == 'answer':
            block['content'] = content


__all__ = ['apply_synthesized_answer', 'synthesize_answer']
