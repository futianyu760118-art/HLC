"""Resolve the provider credentials and model used by a real AI request.

Database configuration is authoritative once an operator has configured a
provider. Environment variables are retained only as the bootstrap path for an
installation that has no saved provider configuration yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from models import AIModelPolicy, AIProviderConfig


@dataclass(frozen=True)
class ResolvedAIRuntime:
    provider_code: str
    base_url: str
    api_key: str
    model: str
    max_tokens: int
    source: Literal['database', 'bootstrap_environment']


class AIRuntimeConfigurationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_response(self) -> tuple[dict[str, str], int]:
        return {'error': self.message, 'code': self.code}, self.status_code


def _normalized_base_url(value: str | None) -> str:
    base_url = str(value or '').strip().rstrip('/')
    parsed = urlparse(base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_BASE_URL_INVALID',
            '已保存的 AI 供应商地址无效，请在平台 AI 资源管理中修正',
        )
    return base_url


def _positive_max_tokens(value: object) -> int:
    try:
        max_tokens = int(value)
    except (TypeError, ValueError):
        max_tokens = 0
    if max_tokens <= 0:
        raise AIRuntimeConfigurationError(
            'AI_MODEL_POLICY_INVALID',
            '已保存的 AI 模型策略最大令牌数无效，请在平台 AI 资源管理中修正',
        )
    return max_tokens


def _matching_enabled_policy(
    resource_domain: str,
    use_case: str,
    tier: str,
) -> AIModelPolicy | None:
    candidates = (
        (use_case, tier),
        ('*', tier),
        (use_case, 'standard'),
        ('*', 'standard'),
    )
    seen: set[tuple[str, str]] = set()
    for candidate_use_case, candidate_tier in candidates:
        key = (candidate_use_case, candidate_tier)
        if key in seen:
            continue
        seen.add(key)
        row = AIModelPolicy.query.filter_by(
            resource_domain=resource_domain,
            use_case=candidate_use_case,
            tier=candidate_tier,
            enabled=True,
        ).first()
        if row:
            return row
    return None


def _is_bootstrap_placeholder(provider: AIProviderConfig) -> bool:
    settings = provider.settings_json or {}
    if settings.get('_runtimeSource') == 'bootstrap_environment':
        return True
    if settings.get('_configuredByOperator') is True:
        return False
    return (
        provider.provider_code == 'siliconflow'
        and not provider.api_key_encrypted
        and str(provider.base_url or '').rstrip('/') == 'https://api.siliconflow.cn/v1'
    )


def _bootstrap_model(tier: str) -> str:
    default_model = os.getenv('ASSISTANT_MODEL', 'deepseek-ai/DeepSeek-V4-Pro').strip()
    if tier in {'basic', 'small'}:
        return (
            os.getenv('ASSISTANT_SMALL_MODEL', '').strip()
            or os.getenv('ASSISTANT_FAST_MODEL', '').strip()
            or default_model
        )
    if tier in {'professional', 'strong'}:
        return os.getenv('ASSISTANT_STRONG_MODEL', '').strip() or default_model
    return os.getenv('ASSISTANT_STANDARD_MODEL', '').strip() or default_model


def _bootstrap_runtime(*, tier: str, model: str | None = None, max_tokens: int | None = None) -> ResolvedAIRuntime:
    api_key = os.getenv('SILICONFLOW_API_KEY', '').strip()
    if not api_key:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_UNAVAILABLE',
            'AI 供应商密钥未配置，请先在平台 AI 资源管理中配置',
        )
    return ResolvedAIRuntime(
        provider_code='siliconflow',
        base_url=_normalized_base_url(
            os.getenv('SILICONFLOW_API_URL', 'https://api.siliconflow.cn/v1')
        ),
        api_key=api_key,
        model=str(model or _bootstrap_model(tier)).strip() or _bootstrap_model(tier),
        max_tokens=_positive_max_tokens(max_tokens or 1200),
        source='bootstrap_environment',
    )


def resolve_ai_runtime(
    resource_domain: str,
    use_case: str | None,
    tier: str | None,
) -> ResolvedAIRuntime:
    domain = str(resource_domain or '').strip()
    selected_use_case = str(use_case or '*').strip() or '*'
    selected_tier = str(tier or 'standard').strip() or 'standard'
    policy = _matching_enabled_policy(domain, selected_use_case, selected_tier)
    providers = AIProviderConfig.query.all()
    configured_provider_exists = any(
        not _is_bootstrap_placeholder(provider)
        for provider in providers
    )

    if policy is None:
        if configured_provider_exists:
            raise AIRuntimeConfigurationError(
                'AI_MODEL_POLICY_MISSING',
                '已保存 AI 供应商，但当前资源域没有可用模型策略',
            )
        return _bootstrap_runtime(tier=selected_tier)

    model = str(policy.model or '').strip()
    if not model:
        raise AIRuntimeConfigurationError(
            'AI_MODEL_POLICY_INVALID',
            '已保存的 AI 模型策略未配置模型名称',
        )
    max_tokens = _positive_max_tokens(policy.max_tokens)
    provider = AIProviderConfig.query.filter_by(provider_code=policy.provider_code).first()
    if not provider:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_NOT_FOUND',
            '模型策略引用的 AI 供应商不存在',
        )
    if not provider.enabled:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_DISABLED',
            '模型策略引用的 AI 供应商已停用',
        )

    if _is_bootstrap_placeholder(provider):
        if configured_provider_exists:
            raise AIRuntimeConfigurationError(
                'AI_MODEL_POLICY_MISSING',
                '已保存 AI 供应商，但当前资源域仍引用引导占位策略，请显式选择供应商',
            )
        return _bootstrap_runtime(tier=selected_tier, model=model, max_tokens=max_tokens)

    from services.ai_resource_governance import decrypt_provider_secret

    try:
        api_key = decrypt_provider_secret(provider.api_key_encrypted)
    except Exception as exc:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_SECRET_INVALID',
            '已保存的 AI 供应商密钥无法解密，请显式更换密钥',
        ) from exc
    if not api_key:
        raise AIRuntimeConfigurationError(
            'AI_PROVIDER_SECRET_INVALID',
            '已保存的 AI 供应商密钥缺失或无法解密，请显式更换密钥',
        )
    return ResolvedAIRuntime(
        provider_code=provider.provider_code,
        base_url=_normalized_base_url(provider.base_url),
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        source='database',
    )


__all__ = [
    'AIRuntimeConfigurationError',
    'ResolvedAIRuntime',
    'resolve_ai_runtime',
]
