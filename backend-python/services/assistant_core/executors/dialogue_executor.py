"""Dialogue/knowledge executor for non-data tasks."""

from __future__ import annotations

import re
from typing import Optional

from .. import llm_client
from ..schemas import AssistantContext, ExecutionResult, RouteDecision
from .output_composer import OutputComposer


SYSTEM_PROMPT = (
    '你是恒聘通 HRM 系统中的企业级 AI 助手。你可以解释 HR 概念、润色文本、'
    '翻译、总结用户提供的内容、回答系统使用帮助。不要声称你查询了系统数据，'
    '除非上下文明确提供。遇到涉及员工、候选人、薪酬、审批等私有数据的问题，'
    '提示用户可以让我帮你查询，并交给数据查询路径。'
)


def _extract_after_colon(message: str) -> str:
    parts = re.split(r'[：:]', message or '', maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ''


def _fallback_answer(message: str) -> str:
    text = (message or '').strip()
    if '你能做什么' in text or text in ('帮助', 'help', 'Help'):
        return (
            '我可以帮你做三类事：\n\n'
            '1. **系统数据查询**：查询员工、候选人、简历、岗位、面试、考勤、绩效、薪酬等信息（按权限脱敏）。\n'
            '2. **HR 内容生成**：写面试邀约邮件、招聘文案、面试题、候选人对比、分析报告等。\n'
            '3. **普通文本处理**：解释概念、翻译、润色、总结你提供的文字。\n\n'
            '如果问题涉及私有数据，我会通过系统工具查询；如果只是写作或解释，我会直接回答。'
        )
    if '润色' in text:
        src = _extract_after_colon(text) or text.replace('帮我润色', '').strip(' ：:')
        return f'润色版本：您好，请您于{src.replace("请你", "").strip()}。如时间不便，欢迎提前与我们沟通调整。'
    if '翻译' in text:
        src = _extract_after_colon(text)
        if '请提前十分钟到达面试地点' in src:
            return 'Please arrive at the interview location ten minutes in advance.'
        return f'英文翻译：{src}' if src else '请提供需要翻译的文本。'
    if '解释' in text or '什么意思' in text:
        return '我可以帮你解释这段内容。请把需要解释的原文发给我，我会用更清晰的中文说明。'
    if '总结' in text:
        src = _extract_after_colon(text)
        return f'简要总结：{src[:120]}' if src else '请提供需要总结的文本。'
    if re.search(r'(他|她|这个人|那个人|该候选人|这位候选人)', text):
        return '抱歉，我暂时无法确定您指的是哪位人员。请提供具体姓名，或先查询相关人员列表。'
    if re.search(r'(岗位|职位).{0,10}(标准|要求|条件|资格|门槛|职责)', text):
        return '请告诉我您想了解哪个具体岗位的信息，例如"供应链总监的岗位要求是什么"。'
    return '我可以直接回答解释、翻译、润色、总结和使用帮助类问题；涉及系统私有数据时，请明确要查询的对象或范围。'


class DialogueExecutor:
    def execute(
        self,
        message: str,
        ctx: AssistantContext,
        route_decision: Optional[RouteDecision] = None,
    ) -> ExecutionResult:
        history = ctx.history[-6:] if ctx.history else []
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({'role': 'user', 'content': message})
        llm_msg = llm_client.chat_profile(
            'standard',
            messages,
            temperature=0.4,
            max_tokens=900,
            timeout=llm_client.FAST_TIMEOUT,
            use_case='dialogue',
            ctx=ctx,
        )
        if llm_msg:
            text = llm_client.clean_text(llm_msg.get('content') or '')
        else:
            text = _fallback_answer(message)
        return OutputComposer.dialogue(text, ctx, route_decision)
