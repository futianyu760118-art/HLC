"""SiliconFlow LLM 调用封装。

- 统一超时和重试
- 不打印 API Key
- 区分 Router/Summarizer/Draft 三档 temperature
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

import requests
from flask import g, has_app_context, has_request_context

logger = logging.getLogger('hengpintong.assistant.llm')

API_KEY = os.getenv('SILICONFLOW_API_KEY', '')
API_URL = os.getenv('SILICONFLOW_API_URL', 'https://api.siliconflow.cn/v1')
DEFAULT_MODEL = os.getenv('ASSISTANT_MODEL', 'deepseek-ai/DeepSeek-V4-Pro')
FAST_MODEL = os.getenv('ASSISTANT_FAST_MODEL', DEFAULT_MODEL)  # 可配置更快的小模型做总结
SMALL_MODEL = os.getenv('ASSISTANT_SMALL_MODEL', FAST_MODEL or DEFAULT_MODEL)
STANDARD_MODEL = os.getenv('ASSISTANT_STANDARD_MODEL', DEFAULT_MODEL)
STRONG_MODEL = os.getenv('ASSISTANT_STRONG_MODEL', 'deepseek-ai/DeepSeek-V4-Pro')
TIMEOUT = 20        # V4-Pro 推理稍慢，适当放宽超时
FAST_TIMEOUT = 15   # 总结用超时
_LAST_CALL_META: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    'assistant_llm_last_call_meta',
    default={},
)


def is_available() -> bool:
    if API_KEY:
        return True
    if not has_app_context():
        return False
    try:
        from models import AIProviderConfig

        providers = AIProviderConfig.query.filter_by(enabled=True).all()
        return any(
            bool(provider.api_key_encrypted)
            or (provider.settings_json or {}).get('_configuredByOperator') is True
            for provider in providers
        )
    except Exception:
        return False


def _set_last_call_meta(meta: Dict[str, Any]) -> None:
    _LAST_CALL_META.set(dict(meta or {}))


def _merge_last_call_meta(**updates: Any) -> None:
    current = dict(_LAST_CALL_META.get({}) or {})
    current.update({key: value for key, value in updates.items() if value is not None})
    _LAST_CALL_META.set(current)


def last_call_meta() -> Dict[str, Any]:
    """Return diagnostic metadata for the latest LLM call in this context."""

    return dict(_LAST_CALL_META.get({}) or {})


def resource_domain_for_use_case(use_case: str | None) -> str:
    value = str(use_case or '').strip()
    if value in {'exam_generation'}:
        return 'exam_ai'
    if value in {'course_qa'}:
        return 'training_ai'
    if value in {'resume_analysis'}:
        return 'resume_ai'
    if value in {'interview_analysis', 'interview_recording_transcription'}:
        return 'interview_ai'
    if value in {'copilot_evaluation', 'model_diagnostics', 'model_call_test', 'model_stream_test'}:
        return 'system_ai'
    return 'assistant'


def _tenant_id_for_ctx(ctx: Optional[Any]) -> str | None:
    explicit = getattr(ctx, 'tenant_id', None) if ctx is not None else None
    if explicit:
        return explicit
    if has_request_context():
        tenant_id = getattr(g, 'tenant_id', None)
        if tenant_id:
            return tenant_id
    user_id = getattr(ctx, 'user_id', None) if ctx is not None else None
    if user_id:
        try:
            from models import User

            user = User.query.get(user_id)
            return getattr(user, 'tenant_id', None)
        except Exception:
            return None
    return None


def _bootstrap_runtime(
    *,
    profile: str,
    use_case: Optional[str],
    max_tokens: int,
) -> Any:
    """Return the legacy environment bootstrap as an immutable request target.

    ``API_KEY`` and ``API_URL`` remain import-time aliases for the bootstrap
    environment so lightweight callers and existing test injection keep
    working. This helper is used only when the database resolver proves there
    is no operator-owned runtime configuration.
    """
    from services.ai_runtime_provider import ResolvedAIRuntime

    return ResolvedAIRuntime(
        provider_code='siliconflow',
        base_url=str(API_URL or 'https://api.siliconflow.cn/v1').strip().rstrip('/'),
        api_key=str(API_KEY or '').strip(),
        model=_model_for_profile(profile, use_case),
        max_tokens=max(int(max_tokens or 0), 1),
        source='bootstrap_environment',
    )


def _resolved_runtime(
    *,
    resource_domain: str,
    use_case: Optional[str],
    profile: str,
    max_tokens: int,
) -> tuple[Any, int]:
    if not has_app_context():
        runtime = _bootstrap_runtime(
            profile=profile,
            use_case=use_case,
            max_tokens=max_tokens,
        )
        return runtime, runtime.max_tokens

    from services.ai_runtime_provider import (
        AIRuntimeConfigurationError,
        resolve_ai_runtime,
    )

    try:
        runtime = resolve_ai_runtime(resource_domain, use_case, profile)
    except AIRuntimeConfigurationError as exc:
        # A missing bootstrap key is represented by an empty immutable target
        # so the existing request/audit path can record the attempt. Every
        # saved-configuration error remains fail-closed and is never replaced
        # with module-level credentials.
        if exc.code != 'AI_PROVIDER_UNAVAILABLE':
            raise
        runtime = _bootstrap_runtime(
            profile=profile,
            use_case=use_case,
            max_tokens=max_tokens,
        )
    if runtime.source == 'bootstrap_environment':
        # Keep a single bootstrap snapshot for the low-level client. In the
        # real app these aliases are loaded from the same environment during
        # startup; using them here also keeps explicit availability overrides
        # and the actual request credentials consistent.
        from services.ai_runtime_provider import ResolvedAIRuntime

        runtime = ResolvedAIRuntime(
            provider_code=runtime.provider_code,
            base_url=str(API_URL or runtime.base_url).strip().rstrip('/'),
            api_key=str(API_KEY or '').strip(),
            model=runtime.model,
            max_tokens=runtime.max_tokens,
            source=runtime.source,
        )
    requested_tokens = max(int(max_tokens or 0), 1)
    return runtime, min(requested_tokens, runtime.max_tokens)


def _governance_for_profile(
    *,
    ctx: Optional[Any],
    resource_domain: Optional[str],
    use_case: Optional[str],
    profile: str,
    messages: List[Dict[str, Any]],
    max_tokens: int,
) -> tuple[Any, int, Optional[Dict[str, Any]]]:
    domain = resource_domain or resource_domain_for_use_case(use_case)
    if domain == 'system_ai':
        runtime, selected_tokens = _resolved_runtime(
            resource_domain=domain,
            use_case=use_case or '*',
            profile=profile or 'standard',
            max_tokens=max_tokens,
        )
        return runtime, selected_tokens, {
            'resource_domain': domain,
            'ai_tier': profile or 'standard',
            'tenant_ai_entitlement_id': None,
            'tenant_id': None,
            'provider': runtime.provider_code,
            'runtime_source': runtime.source,
        }
    try:
        from services.ai_resource_governance import (
            AIResourceDenied,
            assert_ai_resource_allowed,
        )

        decision = assert_ai_resource_allowed(
            tenant_id=_tenant_id_for_ctx(ctx),
            user_id=getattr(ctx, 'user_id', None) if ctx is not None else None,
            resource_domain=domain,
            use_case=use_case or 'dialogue',
        )
        runtime, selected_tokens = _resolved_runtime(
            resource_domain=domain,
            use_case=use_case or '*',
            profile=decision.tier,
            max_tokens=max_tokens,
        )
        return runtime, selected_tokens, {
            'resource_domain': domain,
            'ai_tier': decision.tier,
            'tenant_ai_entitlement_id': decision.entitlement_id,
            'tenant_id': decision.tenant_id,
            'provider': runtime.provider_code,
            'runtime_source': runtime.source,
        }
    except AIResourceDenied as exc:
        _set_last_call_meta({
            'status': 'governance_denied',
            'error_code': exc.code,
            'resource_domain': domain,
            'use_case': use_case,
        })
        _audit_llm_call(
            _audit_context(ctx, profile, use_case, {
                'resource_domain': domain,
                'ai_tier': profile or 'standard',
                'tenant_ai_entitlement_id': None,
            }),
            _model_for_profile(profile, use_case),
            messages,
            None,
            {'errorCode': exc.code, 'governanceDenied': True},
            'denied',
            exc.message,
            0,
            record_usage=False,
        )
        raise


def _reserve_governed_call(
    *,
    audit_context: Optional[Dict[str, Any]],
    model: str,
    messages: List[Dict[str, Any]],
) -> bool:
    context = audit_context if isinstance(audit_context, dict) else {}
    resource_domain = context.get('resource_domain')
    tenant_id = context.get('tenant_id')
    if not resource_domain or resource_domain == 'system_ai' or not tenant_id:
        return True
    from services.ai_resource_governance import AIResourceDenied, assert_ai_resource_allowed

    try:
        assert_ai_resource_allowed(
            tenant_id=tenant_id,
            user_id=context.get('audit_user_id') or context.get('user_id'),
            resource_domain=resource_domain,
            use_case=context.get('use_case') or 'dialogue',
            reserve=True,
        )
        return True
    except AIResourceDenied as exc:
        _set_last_call_meta({
            'status': 'governance_denied',
            'error_code': exc.code,
            'resource_domain': resource_domain,
            'use_case': context.get('use_case'),
        })
        _audit_llm_call(
            context,
            model,
            messages,
            None,
            {'errorCode': exc.code, 'governanceDenied': True},
            'denied',
            exc.message,
            0,
            record_usage=False,
        )
        return False


def _record_runtime_configuration_failure(
    exc: Exception,
    *,
    ctx: Optional[Any],
    profile: str,
    use_case: Optional[str],
    resource_domain: Optional[str],
    messages: List[Dict[str, Any]],
) -> None:
    code = str(getattr(exc, 'code', 'AI_RUNTIME_CONFIGURATION_ERROR'))
    message = str(getattr(exc, 'message', str(exc)))
    domain = resource_domain or resource_domain_for_use_case(use_case)
    model = _model_for_profile(profile, use_case)
    _set_last_call_meta({
        'status': 'configuration_error',
        'error_code': code,
        'error_message': message,
        'model': model,
        'provider': 'unresolved',
        'resource_domain': domain,
        'use_case': use_case,
    })
    _audit_llm_call(
        _audit_context(ctx, profile, use_case, {
            'resource_domain': domain,
            'ai_tier': profile or 'standard',
            'tenant_ai_entitlement_id': None,
            'tenant_id': _tenant_id_for_ctx(ctx),
            'provider': 'unresolved',
            'runtime_source': 'database',
        }),
        model,
        messages,
        None,
        {'errorCode': code, 'runtimeConfiguration': 'invalid'},
        'error',
        message,
        0,
        record_usage=False,
    )


def prepare_profile_runtime(
    profile: str,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    use_case: Optional[str] = None,
    resource_domain: Optional[str] = None,
    ctx: Optional[Any] = None,
) -> tuple[Any, int, Optional[Dict[str, Any]]]:
    """Resolve one immutable provider target before crossing thread boundaries."""
    normalized_profile, _temperature, default_tokens = _profile_defaults(profile)
    requested_tokens = default_tokens if max_tokens is None else max_tokens
    runtime, selected_tokens, governance = _governance_for_profile(
        ctx=ctx,
        resource_domain=resource_domain,
        use_case=use_case,
        profile=normalized_profile,
        messages=messages,
        max_tokens=requested_tokens,
    )
    return (
        runtime,
        selected_tokens,
        _audit_context(ctx, normalized_profile, use_case, governance),
    )


def chat(messages: List[Dict[str, Any]], *,
         temperature: float = 0.3,
         max_tokens: int = 800,
         response_format: Optional[Dict[str, Any]] = None,
         retry_once: bool = True,
         model: Optional[str] = None,
         timeout: Optional[float] = None,
         audit_context: Optional[Dict[str, Any]] = None,
         runtime: Optional[Any] = None,
         resource_domain: Optional[str] = None,
         use_case: Optional[str] = None,
         profile: str = 'standard',
         ctx: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """通用 chat 调用，返回 message 对象（dict）或 None。"""
    if runtime is None and has_app_context():
        try:
            runtime, max_tokens, resolved_audit_context = prepare_profile_runtime(
                profile,
                messages,
                max_tokens=max_tokens,
                use_case=use_case,
                resource_domain=resource_domain,
                ctx=ctx,
            )
            audit_context = audit_context or resolved_audit_context
        except Exception as exc:
            if exc.__class__.__name__ == 'AIResourceDenied':
                return None
            if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
                _record_runtime_configuration_failure(
                    exc,
                    ctx=ctx,
                    profile=profile,
                    use_case=use_case,
                    resource_domain=resource_domain,
                    messages=messages,
                )
                return None
            raise
    selected_model = runtime.model if runtime is not None else (model or DEFAULT_MODEL)
    selected_provider = runtime.provider_code if runtime is not None else 'siliconflow'
    runtime_source = runtime.source if runtime is not None else 'bootstrap_environment'
    api_key = runtime.api_key if runtime is not None else API_KEY
    api_url = (runtime.base_url if runtime is not None else API_URL).rstrip('/')
    selected_tokens = min(max(int(max_tokens or 0), 1), runtime.max_tokens) if runtime is not None else max_tokens
    _set_last_call_meta({
        'status': 'not_started',
        'model': selected_model,
        'provider': selected_provider,
        'runtime_source': runtime_source,
    })
    if not api_key:
        _set_last_call_meta({
            'status': 'error',
            'error_kind': 'missing_api_key',
            'model': selected_model,
            'provider': selected_provider,
            'runtime_source': runtime_source,
        })
        _audit_llm_call(audit_context, selected_model, messages, None, {
            'configuration': 'missing_api_key',
            'provider': selected_provider,
        }, 'error', 'SILICONFLOW_API_KEY 未配置', 0, record_usage=False)
        return None
    body: Dict[str, Any] = {
        'model': selected_model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': selected_tokens,
    }
    if response_format:
        body['response_format'] = response_format

    req_timeout = timeout or TIMEOUT
    for attempt in range(1 + (1 if retry_once else 0)):
        if not _reserve_governed_call(
            audit_context=audit_context,
            model=selected_model,
            messages=messages,
        ):
            return None
        started = time.perf_counter()
        try:
            resp = requests.post(
                f'{api_url}/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json=body,
                timeout=req_timeout,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if resp.status_code != 200:
                retryable = resp.status_code in (429, 500, 502, 503, 504)
                has_next_attempt = retry_once and attempt == 0
                logger.warning(
                    'llm_non_200',
                    extra={'status': resp.status_code, 'attempt': attempt, 'model': selected_model},
                )
                _set_last_call_meta({
                    'status': 'http_error',
                    'http_status': resp.status_code,
                    'attempt': attempt,
                    'model': selected_model,
                    'provider': selected_provider,
                    'runtime_source': runtime_source,
                })
                _audit_llm_call(audit_context, selected_model, messages, None, {
                    'httpStatus': resp.status_code,
                    'attempt': attempt,
                }, 'error', f'HTTP {resp.status_code}', latency_ms)
                if retryable and has_next_attempt:
                    continue
                return None
            data = resp.json()
            message = (data.get('choices') or [{}])[0].get('message')
            _audit_llm_call(audit_context, selected_model, messages, message, {
                'attempt': attempt,
                'usage': data.get('usage') or {},
                'finishReason': (data.get('choices') or [{}])[0].get('finish_reason'),
            }, 'success', None, latency_ms)
            _set_last_call_meta({
                'status': 'success',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'finish_reason': (data.get('choices') or [{}])[0].get('finish_reason'),
                'latency_ms': latency_ms,
            })
            return message
        except requests.Timeout:
            logger.warning('llm_timeout', extra={'attempt': attempt})
            _set_last_call_meta({
                'status': 'timeout',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'latency_ms': int((time.perf_counter() - started) * 1000),
            })
            _audit_llm_call(audit_context, selected_model, messages, None, {
                'attempt': attempt,
            }, 'timeout', 'request timeout', int((time.perf_counter() - started) * 1000))
        except Exception:
            logger.exception('llm_call_failed')
            _set_last_call_meta({
                'status': 'error',
                'error_kind': 'exception',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'latency_ms': int((time.perf_counter() - started) * 1000),
            })
            _audit_llm_call(audit_context, selected_model, messages, None, {
                'attempt': attempt,
            }, 'error', 'llm call failed', int((time.perf_counter() - started) * 1000))
            return None
    return None


def _audit_llm_call(audit_context: Optional[Dict[str, Any]], model: str,
                    messages: List[Dict[str, Any]], message: Optional[Dict[str, Any]],
                    response_meta: Dict[str, Any], status: str,
                    error_message: Optional[str], latency_ms: int,
                    record_usage: bool = True) -> None:
    if not audit_context:
        return
    try:
        from .audit import record_llm_call

        sanitized_meta = dict(response_meta or {})
        if audit_context.get('runtime_source'):
            sanitized_meta['runtimeSource'] = audit_context.get('runtime_source')

        record_llm_call(
            tenant_id=audit_context.get('tenant_id'),
            user_id=audit_context.get('audit_user_id') or audit_context.get('user_id'),
            session_id=audit_context.get('audit_session_id') or audit_context.get('session_id'),
            request_id=audit_context.get('request_id'),
            provider=audit_context.get('provider') or 'siliconflow',
            model=model,
            model_profile=audit_context.get('model_profile'),
            use_case=audit_context.get('use_case'),
            messages=messages,
            response_content=(message or {}).get('content') if isinstance(message, dict) else None,
            response_meta=sanitized_meta,
            status=status,
            error_message=error_message,
            latency_ms=latency_ms,
            resource_domain=audit_context.get('resource_domain'),
            ai_tier=audit_context.get('ai_tier'),
            tenant_ai_entitlement_id=audit_context.get('tenant_ai_entitlement_id'),
            record_usage=record_usage,
        )
    except Exception:
        logger.exception('assistant_audit_log_failed')


def json_chat(messages: List[Dict[str, Any]], *,
              temperature: float = 0.1,
              max_tokens: int = 600,
              timeout: Optional[float] = None,
              retry_once: bool = True,
              runtime: Optional[Any] = None,
              audit_context: Optional[Dict[str, Any]] = None,
              resource_domain: Optional[str] = None,
              use_case: Optional[str] = None,
              profile: str = 'standard',
              ctx: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """请求 LLM 返回严格 JSON。容错解析。"""
    msg = chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
        timeout=timeout,
        retry_once=retry_once,
        runtime=runtime,
        audit_context=audit_context,
        resource_domain=resource_domain,
        use_case=use_case,
        profile=profile,
        ctx=ctx,
    )
    if not msg:
        return None
    content = (msg.get('content') or '').strip()
    if not content:
        _merge_last_call_meta(json_status='empty_content', content_length=0)
        return None
    parsed = _parse_json_object_from_model_text(content)
    if parsed is None:
        _merge_last_call_meta(
            json_status='parse_failed',
            content_length=len(content),
        )
        logger.warning('llm_json_parse_failed', extra={'preview': _sanitize_json_text(content)[:200]})
    else:
        _merge_last_call_meta(json_status='parsed', content_length=len(content))
    return parsed


def _model_for_profile(profile: str, use_case: Optional[str] = None) -> str:
    try:
        from .model_settings import model_for_profile

        return model_for_profile(profile, use_case)
    except Exception:
        pass
    p = (profile or 'standard').lower()
    if p == 'small':
        return SMALL_MODEL or FAST_MODEL or DEFAULT_MODEL
    if p == 'strong':
        return STRONG_MODEL or DEFAULT_MODEL
    return STANDARD_MODEL or DEFAULT_MODEL


def _profile_defaults(profile: str) -> tuple[str, float, int]:
    p = (profile or 'standard').lower()
    default_temp = 0.2 if p == 'small' else 0.4 if p == 'standard' else 0.35
    default_tokens = 700 if p == 'small' else 1200 if p == 'standard' else 1800
    return p, default_temp, default_tokens


def chat_profile(profile: str,
                 messages: List[Dict[str, Any]], *,
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None,
                 timeout: Optional[int] = None,
                 use_case: Optional[str] = None,
                 resource_domain: Optional[str] = None,
                 ctx: Optional[Any] = None,
                 retry_once: bool = True) -> Optional[Dict[str, Any]]:
    """Chat with a named model profile: small / standard / strong."""
    p, default_temp, default_tokens = _profile_defaults(profile)
    selected_tokens = default_tokens if max_tokens is None else max_tokens
    try:
        runtime, selected_tokens, governance = _governance_for_profile(
            ctx=ctx,
            resource_domain=resource_domain,
            use_case=use_case,
            profile=p,
            messages=messages,
            max_tokens=selected_tokens,
        )
    except Exception as exc:
        if exc.__class__.__name__ == 'AIResourceDenied':
            return None
        if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
            _record_runtime_configuration_failure(
                exc,
                ctx=ctx,
                profile=p,
                use_case=use_case,
                resource_domain=resource_domain,
                messages=messages,
            )
            return None
        raise
    audit_context = _audit_context(ctx, p, use_case, governance)
    return chat(
        messages,
        temperature=default_temp if temperature is None else temperature,
        max_tokens=selected_tokens,
        model=runtime.model,
        timeout=timeout,
        retry_once=retry_once,
        audit_context=audit_context,
        runtime=runtime,
    )


def json_chat_profile(profile: str,
                      messages: List[Dict[str, Any]], *,
                      temperature: float = 0.1,
                      max_tokens: int = 600,
                      timeout: Optional[int] = None,
                      use_case: Optional[str] = None,
                      resource_domain: Optional[str] = None,
                      retry_once: bool = True,
                      ctx: Optional[Any] = None,
                      runtime: Optional[Any] = None,
                      audit_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Request structured JSON through a configured model profile."""
    if runtime is None:
        try:
            runtime, selected_tokens, governance = _governance_for_profile(
                ctx=ctx,
                resource_domain=resource_domain,
                use_case=use_case,
                profile=profile,
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            if exc.__class__.__name__ == 'AIResourceDenied':
                return None
            if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
                _record_runtime_configuration_failure(
                    exc,
                    ctx=ctx,
                    profile=profile,
                    use_case=use_case,
                    resource_domain=resource_domain,
                    messages=messages,
                )
                return None
            raise
        audit_context = audit_context or _audit_context(ctx, profile, use_case, governance)
    else:
        selected_tokens = min(max(int(max_tokens or 0), 1), runtime.max_tokens)
    msg = chat(
        messages,
        temperature=temperature,
        max_tokens=selected_tokens,
        response_format={'type': 'json_object'},
        model=runtime.model,
        timeout=timeout,
        retry_once=retry_once,
        audit_context=audit_context,
        runtime=runtime,
    )
    if not msg:
        return None
    content = (msg.get('content') or '').strip()
    if not content:
        _merge_last_call_meta(json_status='empty_content', content_length=0)
        return None
    parsed = _parse_json_object_from_model_text(content)
    if parsed is None:
        _merge_last_call_meta(
            json_status='parse_failed',
            content_length=len(content),
        )
        logger.warning('llm_profile_json_parse_failed', extra={'preview': _sanitize_json_text(content)[:200]})
    else:
        _merge_last_call_meta(json_status='parsed', content_length=len(content))
    return parsed


def stream_chat_profile(profile: str,
                        messages: List[Dict[str, Any]], *,
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None,
                        timeout: Optional[int] = None,
                        use_case: Optional[str] = None,
                        resource_domain: Optional[str] = None,
                        ctx: Optional[Any] = None,
                        retry_once: bool = True) -> Iterator[str]:
    """Stream content deltas from the configured SiliconFlow chat model.

    The yielded values are raw text deltas. A single audit row is written when
    the provider stream finishes, including the reconstructed response and
    stream metadata, so model-management audit views can verify the real call.
    """
    p, default_temp, default_tokens = _profile_defaults(profile)
    selected_tokens = default_tokens if max_tokens is None else max_tokens
    try:
        runtime, selected_tokens, governance = _governance_for_profile(
            ctx=ctx,
            resource_domain=resource_domain,
            use_case=use_case,
            profile=p,
            messages=messages,
            max_tokens=selected_tokens,
        )
    except Exception as exc:
        if exc.__class__.__name__ == 'AIResourceDenied':
            return
        if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
            _record_runtime_configuration_failure(
                exc,
                ctx=ctx,
                profile=p,
                use_case=use_case,
                resource_domain=resource_domain,
                messages=messages,
            )
            return
        raise
    yield from stream_chat(
        messages,
        temperature=default_temp if temperature is None else temperature,
        max_tokens=selected_tokens,
        model=runtime.model,
        timeout=timeout,
        retry_once=retry_once,
        audit_context=_audit_context(ctx, p, use_case, governance),
        runtime=runtime,
    )


def stream_chat(messages: List[Dict[str, Any]], *,
                temperature: float = 0.3,
                max_tokens: int = 800,
                retry_once: bool = True,
                model: Optional[str] = None,
                timeout: Optional[int] = None,
                audit_context: Optional[Dict[str, Any]] = None,
                runtime: Optional[Any] = None,
                resource_domain: Optional[str] = None,
                use_case: Optional[str] = None,
                profile: str = 'standard',
                ctx: Optional[Any] = None) -> Iterator[str]:
    """Low-level OpenAI-compatible SSE streaming call."""
    if runtime is None and has_app_context():
        try:
            runtime, max_tokens, resolved_audit_context = prepare_profile_runtime(
                profile,
                messages,
                max_tokens=max_tokens,
                use_case=use_case,
                resource_domain=resource_domain,
                ctx=ctx,
            )
            audit_context = audit_context or resolved_audit_context
        except Exception as exc:
            if exc.__class__.__name__ == 'AIResourceDenied':
                return
            if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
                _record_runtime_configuration_failure(
                    exc,
                    ctx=ctx,
                    profile=profile,
                    use_case=use_case,
                    resource_domain=resource_domain,
                    messages=messages,
                )
                return
            raise
    selected_model = runtime.model if runtime is not None else (model or DEFAULT_MODEL)
    selected_provider = runtime.provider_code if runtime is not None else 'siliconflow'
    runtime_source = runtime.source if runtime is not None else 'bootstrap_environment'
    api_key = runtime.api_key if runtime is not None else API_KEY
    api_url = (runtime.base_url if runtime is not None else API_URL).rstrip('/')
    selected_tokens = min(max(int(max_tokens or 0), 1), runtime.max_tokens) if runtime is not None else max_tokens
    _set_last_call_meta({
        'status': 'not_started',
        'model': selected_model,
        'provider': selected_provider,
        'runtime_source': runtime_source,
        'stream': True,
    })
    if not api_key:
        _set_last_call_meta({
            'status': 'error',
            'error_kind': 'missing_api_key',
            'model': selected_model,
            'provider': selected_provider,
            'runtime_source': runtime_source,
            'stream': True,
        })
        _audit_llm_call(audit_context, selected_model, messages, None, {
            'configuration': 'missing_api_key',
            'provider': selected_provider,
            'stream': True,
        }, 'error', 'SILICONFLOW_API_KEY 未配置', 0, record_usage=False)
        return

    body: Dict[str, Any] = {
        'model': selected_model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': selected_tokens,
        'stream': True,
    }
    req_timeout = timeout or TIMEOUT
    for attempt in range(1 + (1 if retry_once else 0)):
        if not _reserve_governed_call(
            audit_context=audit_context,
            model=selected_model,
            messages=messages,
        ):
            return
        started = time.perf_counter()
        chunks: List[str] = []
        chunk_count = 0
        usage: Dict[str, Any] = {}
        finish_reason: Optional[str] = None
        try:
            with requests.post(
                f'{api_url}/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json=body,
                timeout=req_timeout,
                stream=True,
            ) as resp:
                if resp.status_code != 200:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    retryable = resp.status_code in (429, 500, 502, 503, 504)
                    has_next_attempt = retry_once and attempt == 0
                    logger.warning(
                        'llm_stream_non_200',
                        extra={'status': resp.status_code, 'attempt': attempt, 'model': selected_model},
                    )
                    _audit_llm_call(audit_context, selected_model, messages, None, {
                        'httpStatus': resp.status_code,
                        'attempt': attempt,
                        'stream': True,
                    }, 'error', f'HTTP {resp.status_code}', latency_ms)
                    _set_last_call_meta({
                        'status': 'http_error',
                        'http_status': resp.status_code,
                        'attempt': attempt,
                        'model': selected_model,
                        'provider': selected_provider,
                        'runtime_source': runtime_source,
                        'stream': True,
                        'latency_ms': latency_ms,
                    })
                    if retryable and has_next_attempt:
                        continue
                    return

                for raw_line in resp.iter_lines(decode_unicode=False):
                    if not raw_line:
                        continue
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode('utf-8', errors='ignore').strip()
                    else:
                        line = str(raw_line).strip()
                    if not line.startswith('data:'):
                        continue
                    payload_text = line[5:].strip()
                    if not payload_text:
                        continue
                    if payload_text == '[DONE]':
                        break
                    try:
                        payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        logger.warning('llm_stream_json_parse_failed', extra={'preview': payload_text[:200]})
                        continue
                    if payload.get('usage'):
                        usage = payload.get('usage') or {}
                    choice = (payload.get('choices') or [{}])[0]
                    finish_reason = choice.get('finish_reason') or finish_reason
                    delta = choice.get('delta') or {}
                    content = delta.get('content')
                    if content is None and isinstance(choice.get('message'), dict):
                        content = choice['message'].get('content')
                    if content:
                        text = str(content)
                        chunks.append(text)
                        chunk_count += 1
                        yield text

                latency_ms = int((time.perf_counter() - started) * 1000)
                _audit_llm_call(audit_context, selected_model, messages, {
                    'role': 'assistant',
                    'content': ''.join(chunks),
                }, {
                    'attempt': attempt,
                    'usage': usage,
                    'finishReason': finish_reason,
                    'stream': True,
                    'chunkCount': chunk_count,
                }, 'success', None, latency_ms)
                _set_last_call_meta({
                    'status': 'success',
                    'attempt': attempt,
                    'model': selected_model,
                    'provider': selected_provider,
                    'runtime_source': runtime_source,
                    'stream': True,
                    'finish_reason': finish_reason,
                    'latency_ms': latency_ms,
                    'chunk_count': chunk_count,
                })
                return
        except GeneratorExit:
            latency_ms = int((time.perf_counter() - started) * 1000)
            _audit_llm_call(audit_context, selected_model, messages, {
                'role': 'assistant',
                'content': ''.join(chunks),
            } if chunks else None, {
                'attempt': attempt,
                'stream': True,
                'chunkCount': chunk_count,
            }, 'cancelled', 'stream cancelled by consumer', latency_ms)
            _set_last_call_meta({
                'status': 'cancelled',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'stream': True,
                'latency_ms': latency_ms,
                'chunk_count': chunk_count,
            })
            raise
        except requests.Timeout:
            logger.warning('llm_stream_timeout', extra={'attempt': attempt})
            _audit_llm_call(audit_context, selected_model, messages, {
                'role': 'assistant',
                'content': ''.join(chunks),
            } if chunks else None, {
                'attempt': attempt,
                'stream': True,
                'chunkCount': chunk_count,
            }, 'timeout', 'request timeout', int((time.perf_counter() - started) * 1000))
            _set_last_call_meta({
                'status': 'timeout',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'stream': True,
                'latency_ms': int((time.perf_counter() - started) * 1000),
                'chunk_count': chunk_count,
            })
        except Exception:
            logger.exception('llm_stream_call_failed')
            _audit_llm_call(audit_context, selected_model, messages, {
                'role': 'assistant',
                'content': ''.join(chunks),
            } if chunks else None, {
                'attempt': attempt,
                'stream': True,
                'chunkCount': chunk_count,
            }, 'error', 'stream call failed', int((time.perf_counter() - started) * 1000))
            _set_last_call_meta({
                'status': 'error',
                'error_kind': 'exception',
                'attempt': attempt,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'stream': True,
                'latency_ms': int((time.perf_counter() - started) * 1000),
                'chunk_count': chunk_count,
            })
            return


def chat_with_tools(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], *,
                    temperature: float = 0.2,
                    max_tokens: int = 800,
                    ctx: Optional[Any] = None,
                    use_case: Optional[str] = None,
                    resource_domain: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """带 tools 参数的 function calling 调用。"""
    try:
        runtime, selected_tokens, governance = _governance_for_profile(
            ctx=ctx,
            resource_domain=resource_domain,
            use_case=use_case or 'tool_calling',
            profile='standard',
            messages=messages,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        if exc.__class__.__name__ == 'AIResourceDenied':
            return None
        if exc.__class__.__name__ == 'AIRuntimeConfigurationError':
            _record_runtime_configuration_failure(
                exc,
                ctx=ctx,
                profile='standard',
                use_case=use_case or 'tool_calling',
                resource_domain=resource_domain,
                messages=messages,
            )
            return None
        raise
    selected_model = runtime.model
    selected_provider = runtime.provider_code
    runtime_source = runtime.source
    audit_context = _audit_context(ctx, 'standard', use_case or 'tool_calling', governance)
    _set_last_call_meta({
        'status': 'not_started',
        'model': selected_model,
        'provider': selected_provider,
        'runtime_source': runtime_source,
        'tool_call': True,
    })
    if not runtime.api_key:
        _set_last_call_meta({
            'status': 'error',
            'error_kind': 'missing_api_key',
            'model': selected_model,
            'provider': selected_provider,
            'runtime_source': runtime_source,
            'tool_call': True,
        })
        _audit_llm_call(audit_context, selected_model, messages, None, {
            'configuration': 'missing_api_key',
            'tools': [t.get('function', {}).get('name') or t.get('name') for t in tools],
        }, 'error', 'SILICONFLOW_API_KEY 未配置', 0, record_usage=False)
        return None
    body = {
        'model': selected_model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': selected_tokens,
        'tools': tools,
        'tool_choice': 'auto',
    }
    if not _reserve_governed_call(
        audit_context=audit_context,
        model=selected_model,
        messages=messages,
    ):
        return None
    started = time.perf_counter()
    try:
        resp = requests.post(
            f'{runtime.base_url.rstrip("/")}/chat/completions',
            headers={'Authorization': f'Bearer {runtime.api_key}', 'Content-Type': 'application/json'},
            json=body,
            timeout=TIMEOUT,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            logger.warning('llm_tool_non_200', extra={'status': resp.status_code})
            _audit_llm_call(audit_context, selected_model, messages, None, {
                'httpStatus': resp.status_code,
                'tools': [t.get('function', {}).get('name') or t.get('name') for t in tools],
            }, 'error', f'HTTP {resp.status_code}', latency_ms)
            _set_last_call_meta({
                'status': 'http_error',
                'http_status': resp.status_code,
                'model': selected_model,
                'provider': selected_provider,
                'runtime_source': runtime_source,
                'tool_call': True,
                'latency_ms': latency_ms,
            })
            return None
        data = resp.json()
        message = (data.get('choices') or [{}])[0].get('message')
        _audit_llm_call(audit_context, selected_model, messages, message, {
            'usage': data.get('usage') or {},
            'tools': [t.get('function', {}).get('name') or t.get('name') for t in tools],
        }, 'success', None, latency_ms)
        _set_last_call_meta({
            'status': 'success',
            'model': selected_model,
            'provider': selected_provider,
            'runtime_source': runtime_source,
            'tool_call': True,
            'latency_ms': latency_ms,
        })
        return message
    except Exception:
        logger.exception('llm_tool_call_failed')
        latency_ms = int((time.perf_counter() - started) * 1000)
        _audit_llm_call(audit_context, selected_model, messages, None, {}, 'error', 'tool call failed', latency_ms)
        _set_last_call_meta({
            'status': 'error',
            'error_kind': 'exception',
            'model': selected_model,
            'provider': selected_provider,
            'runtime_source': runtime_source,
            'tool_call': True,
            'latency_ms': latency_ms,
        })
        return None


def _audit_context(ctx: Optional[Any], model_profile: Optional[str], use_case: Optional[str],
                   governance: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if ctx is None and not has_app_context():
        return None
    request_id = getattr(ctx, 'request_id', None) if ctx is not None else None
    if not request_id and has_request_context():
        request_id = getattr(g, 'request_id', None)
    if not request_id:
        request_id = f'llm-{uuid.uuid4().hex[:16]}'
    payload = {
        'user_id': getattr(ctx, 'user_id', None) if ctx is not None else None,
        'session_id': getattr(ctx, 'session_id', None) if ctx is not None else None,
        'audit_user_id': getattr(ctx, 'audit_user_id', None) if ctx is not None else None,
        'audit_session_id': getattr(ctx, 'audit_session_id', None) if ctx is not None else None,
        'request_id': request_id,
        'model_profile': model_profile,
        'use_case': use_case,
    }
    if governance:
        payload.update({
            'tenant_id': governance.get('tenant_id'),
            'resource_domain': governance.get('resource_domain'),
            'ai_tier': governance.get('ai_tier'),
            'tenant_ai_entitlement_id': governance.get('tenant_ai_entitlement_id'),
            'provider': governance.get('provider'),
            'runtime_source': governance.get('runtime_source'),
        })
    return payload


def clean_text(text: str) -> str:
    """清理 LLM 输出的 thinking 标记和过度 Markdown。"""
    if not text:
        return ''
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'</?think>', '', text)
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'(?m)^\s*-{3,}\s*$', '', text)
    return text.strip()


def _sanitize_json_text(content: str) -> str:
    """Normalize common model wrappers before JSON extraction."""
    text = str(content or '')
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE)
    text = text.strip()
    fence = re.search(r'```(?:json|JSON)?\s*(.*?)```', text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        text = re.sub(r'^```(?:json|JSON)?\s*', '', text).strip()
        text = re.sub(r'\s*```$', '', text).strip()
    return text


def _parse_json_object_from_model_text(content: str) -> Optional[Dict[str, Any]]:
    """Extract the first complete JSON object from model text.

    Some OpenAI-compatible providers still wrap JSON-mode responses in
    explanations, markdown fences, or incomplete thinking tags. Use
    ``raw_decode`` from every object start instead of slicing from the first
    ``{`` to the last ``}``, because the latter breaks when explanations contain
    braces after the actual payload.
    """

    text = _sanitize_json_text(content)
    if not text:
        return None
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            value, _end = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
