"""Operator-triggered real model diagnostics for the assistant console."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List, Optional

from . import llm_client
from .model_settings import model_for_profile, profile_for_use_case
from .schemas import AssistantContext


def _normalize_profile(profile: Optional[str], use_case: str) -> str:
    value = (profile or '').strip().lower()
    if value not in {'small', 'standard', 'strong'}:
        value = profile_for_use_case('standard', use_case)
    return value if value in {'small', 'standard', 'strong'} else 'standard'


def _build_test_messages(prompt: str, ctx: AssistantContext, marker: str) -> List[Dict[str, str]]:
    clean_prompt = (prompt or '').strip()
    if not clean_prompt:
        clean_prompt = '请用一句中文回答：恒聘通 HRM Copilot 真实模型调用链路是否可用。'
    system = (
        '你是恒聘通 HRM Copilot 的模型连通性诊断器。'
        '只验证真实模型调用链路是否可用，不执行业务写入，不编造系统数据。'
        '回答必须简洁，并原样包含测试标记。'
    )
    user = (
        f'测试标记：{marker}\n'
        f'页面：{(ctx.client_context or {}).get("path") or "-"} / {(ctx.client_context or {}).get("moduleName") or "-"}\n'
        f'测试问题：{clean_prompt}\n'
        '请返回一段 80 字以内的中文诊断结果。'
    )
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def _latest_audit_status(request_id: Optional[str], use_case: str) -> Dict[str, Any]:
    if not request_id:
        return {}
    try:
        from models import AssistantAuditLog

        row = AssistantAuditLog.query.filter_by(
            request_id=request_id,
            use_case=use_case,
        ).order_by(AssistantAuditLog.created_at.desc()).first()
        if not row:
            return {}
        return {
            'auditLogId': row.id,
            'status': row.status,
            'error': row.error_message,
            'provider': row.provider,
            'model': row.model,
            'runtimeSource': (row.response_meta or {}).get('runtimeSource'),
        }
    except Exception:
        return {}


def run_model_call_test(
    prompt: str,
    ctx: AssistantContext,
    *,
    profile: Optional[str] = None,
    use_case: str = 'model_call_test',
    resource_domain: str = 'system_ai',
) -> Dict[str, Any]:
    """Run a real provider call and rely on the normal LLM audit path.

    When the provider key is missing the same path records a failed audit row,
    so operators can still see that the diagnostic was attempted.
    """
    marker = f'Copilot真实调用测试-{uuid.uuid4().hex[:8]}'
    selected_profile = _normalize_profile(profile, use_case)
    selected_model = model_for_profile(selected_profile, use_case)
    msg = llm_client.chat_profile(
        selected_profile,
        _build_test_messages(prompt, ctx, marker),
        temperature=0.1,
        max_tokens=180,
        timeout=25,
        use_case=use_case,
        resource_domain=resource_domain,
        ctx=ctx,
    )
    content = llm_client.clean_text((msg or {}).get('content') or '')
    audit = _latest_audit_status(ctx.request_id, use_case)
    call_meta = llm_client.last_call_meta()
    return {
        'ok': bool(msg),
        'marker': marker,
        'requestId': ctx.request_id,
        'sessionId': ctx.session_id,
        'modelProfile': selected_profile,
        'provider': audit.get('provider') or call_meta.get('provider') or 'siliconflow',
        'model': audit.get('model') or call_meta.get('model') or selected_model,
        'runtimeSource': audit.get('runtimeSource') or call_meta.get('runtime_source'),
        'useCase': use_case,
        'response': content,
        'errorCode': None if msg else call_meta.get('error_code'),
        'error': None if msg else (
            call_meta.get('error_message')
            or audit.get('error')
            or '模型调用失败或模型 Key 未配置，请查看调用记录详情。'
        ),
    }


def stream_model_call_test(
    prompt: str,
    ctx: AssistantContext,
    *,
    profile: Optional[str] = None,
    use_case: str = 'model_stream_test',
    resource_domain: str = 'system_ai',
) -> Iterator[Dict[str, Any]]:
    """Run a real streaming provider call and yield UI-friendly events."""
    marker = f'Copilot流式调用测试-{uuid.uuid4().hex[:8]}'
    selected_profile = _normalize_profile(profile, use_case)
    selected_model = model_for_profile(selected_profile, use_case)
    chunks: List[str] = []
    for delta in llm_client.stream_chat_profile(
        selected_profile,
        _build_test_messages(prompt, ctx, marker),
        temperature=0.1,
        max_tokens=220,
        timeout=30,
        use_case=use_case,
        resource_domain=resource_domain,
        ctx=ctx,
        retry_once=False,
    ):
        text = str(delta or '')
        if text:
            chunks.append(text)
            yield {'event': 'delta', 'content': text}

    content = llm_client.clean_text(''.join(chunks))
    audit = _latest_audit_status(ctx.request_id, use_case)
    call_meta = llm_client.last_call_meta()
    ok = audit.get('status') == 'success' and bool(content)
    yield {
        'event': 'final',
        'payload': {
            'ok': ok,
            'marker': marker,
            'requestId': ctx.request_id,
            'sessionId': ctx.session_id,
            'modelProfile': selected_profile,
            'provider': audit.get('provider') or call_meta.get('provider') or 'siliconflow',
            'model': audit.get('model') or call_meta.get('model') or selected_model,
            'runtimeSource': audit.get('runtimeSource') or call_meta.get('runtime_source'),
            'useCase': use_case,
            'stream': True,
            'response': content,
            'auditLogId': audit.get('auditLogId'),
            'auditStatus': audit.get('status'),
            'error': None if ok else (audit.get('error') or '流式模型调用失败或模型 Key 未配置，请查看调用记录详情。'),
        },
    }
