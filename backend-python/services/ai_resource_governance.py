from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests
from flask import current_app, g, has_request_context
from sqlalchemy.orm import sessionmaker

from services.ai_runtime_provider import AIRuntimeConfigurationError, resolve_ai_runtime
from models import (
    AIAddonPackage,
    AIModelPolicy,
    AIProviderConfig,
    AIUsageLedger,
    TenantAIEntitlement,
    db,
)


AI_RESOURCE_DOMAINS = (
    'assistant',
    'resume_ai',
    'interview_ai',
    'exam_ai',
    'training_ai',
    'analytics_ai',
    'system_ai',
)

DOMAIN_LABELS = {
    'assistant': 'AI 助手',
    'resume_ai': '简历智能',
    'interview_ai': '面试智能',
    'exam_ai': '考试智能',
    'training_ai': '培训智能',
    'analytics_ai': '分析智能',
    'system_ai': '平台诊断',
}

TIER_LABELS = {
    'basic': '经济档',
    'standard': '标准档',
    'professional': '专业档',
}

DEFAULT_PROVIDER_CODE = 'siliconflow'
DEFAULT_PROVIDER_BASE_URL = 'https://api.siliconflow.cn/v1'
DEFAULT_CHAT_MODEL = 'deepseek-ai/DeepSeek-V3'
DEFAULT_ASR_MODEL = 'FunAudioLLM/SenseVoiceSmall'


class AIResourceDenied(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 403,
        detail: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}

    def to_response(self) -> tuple[dict[str, Any], int]:
        return {'error': self.message, 'code': self.code, **self.detail}, self.status_code


@dataclass(frozen=True)
class AIResourceDecision:
    tenant_id: str | None
    user_id: str | None
    resource_domain: str
    use_case: str
    tier: str
    entitlement_id: str | None
    monthly_quota: int | None
    used_this_month: int

    def to_dict(self) -> dict[str, Any]:
        return {
            'tenant_id': self.tenant_id,
            'user_id': self.user_id,
            'resource_domain': self.resource_domain,
            'use_case': self.use_case,
            'tier': self.tier,
            'entitlement_id': self.entitlement_id,
            'monthly_quota': self.monthly_quota,
            'used_this_month': self.used_this_month,
        }


def _new_id() -> str:
    return str(uuid.uuid4())


def current_period_start() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def current_period_key() -> str:
    return datetime.utcnow().strftime('%Y-%m')


def mask_api_key(value: str | None) -> str | None:
    text = str(value or '').strip()
    if not text:
        return None
    if len(text) <= 8:
        return f'{text[:2]}...{text[-2:]}'
    return f'{text[:3]}...{text[-4:]}'


def _fernet():
    secret = os.getenv('AI_PROVIDER_SECRET_KEY', '').strip()
    if not secret:
        return None
    from cryptography.fernet import Fernet

    return Fernet(secret.encode('utf-8'))


def encrypt_provider_secret(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    fernet = _fernet()
    if fernet:
        return fernet.encrypt(text.encode('utf-8')).decode('utf-8')
    if current_app and current_app.config.get('TESTING'):
        encoded = base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')
        return f'test-plain:{encoded}'
    raise AIResourceDenied('AI_PROVIDER_SECRET_KEY_REQUIRED', '保存 AI 供应商密钥前必须配置 AI_PROVIDER_SECRET_KEY', 500)


def decrypt_provider_secret(value: str | None) -> str | None:
    text = str(value or '').strip()
    if not text:
        return None
    if text.startswith('test-plain:'):
        try:
            return base64.urlsafe_b64decode(text.split(':', 1)[1].encode('ascii')).decode('utf-8')
        except Exception:
            return None
    fernet = _fernet()
    if not fernet:
        return None
    return fernet.decrypt(text.encode('utf-8')).decode('utf-8')


def usage_count(tenant_id: str, resource_domain: str) -> int:
    return AIUsageLedger.query.filter(
        AIUsageLedger.tenant_id == tenant_id,
        AIUsageLedger.resource_domain == resource_domain,
        AIUsageLedger.created_at >= current_period_start(),
    ).count()


def _reserved_usage(tenant_id: str, resource_domain: str, observed_used: int) -> tuple[int, dict[str, int] | None]:
    if not has_request_context():
        return observed_used, None
    reservations = getattr(g, '_ai_actual_call_reservations', None)
    if not isinstance(reservations, dict):
        reservations = {}
        g._ai_actual_call_reservations = reservations
    key = (tenant_id, resource_domain)
    state = reservations.get(key)
    if not isinstance(state, dict):
        state = {'baseline': int(observed_used), 'pending': 0, 'settled': 0}
        reservations[key] = state
    effective_used = max(
        int(observed_used),
        int(state['baseline']) + int(state['settled']) + int(state['pending']),
    )
    return effective_used, state


def settle_ai_usage_reservation(
    tenant_id: str | None,
    resource_domain: str | None,
    *,
    units: int = 1,
) -> None:
    if not has_request_context() or not tenant_id or not resource_domain:
        return
    reservations = getattr(g, '_ai_actual_call_reservations', None)
    if not isinstance(reservations, dict):
        return
    state = reservations.get((tenant_id, resource_domain))
    if not isinstance(state, dict):
        return
    settled_units = min(max(int(units or 1), 1), max(int(state.get('pending') or 0), 0))
    state['pending'] = max(int(state.get('pending') or 0) - settled_units, 0)
    state['settled'] = int(state.get('settled') or 0) + settled_units


def seed_ai_resource_defaults(*, overwrite_existing: bool = False) -> None:
    packages = [
        ('ai_assistant', 'AI 助手包', ['assistant'], ['basic', 'standard'], 1000),
        ('recruitment_ai', '招聘智能包', ['resume_ai', 'interview_ai'], ['basic', 'standard', 'professional'], 1000),
        ('training_exam_ai', '培训考试智能包', ['exam_ai', 'training_ai'], ['basic', 'standard'], 1000),
        ('analytics_ai', '经营分析智能包', ['analytics_ai'], ['standard', 'professional'], 500),
        ('enterprise_ai', '企业专业 AI 包', ['assistant', 'resume_ai', 'interview_ai', 'exam_ai', 'training_ai', 'analytics_ai'], ['basic', 'standard', 'professional'], 5000),
    ]
    for code, name, domains, tiers, quota in packages:
        row = db.session.get(AIAddonPackage, code)
        if not row:
            row = AIAddonPackage(code=code)
            db.session.add(row)
        if overwrite_existing or not row.name:
            row.name = name
        if overwrite_existing or not row.resource_domains:
            row.resource_domains = domains
        if overwrite_existing or not row.allowed_tiers:
            row.allowed_tiers = tiers
        if overwrite_existing or row.default_monthly_quota is None:
            row.default_monthly_quota = quota
        if overwrite_existing or row.is_active is None:
            row.is_active = True

    provider = AIProviderConfig.query.filter_by(provider_code=DEFAULT_PROVIDER_CODE).first()
    if not provider:
        provider = AIProviderConfig(
            id=f'provider-{DEFAULT_PROVIDER_CODE}',
            provider_code=DEFAULT_PROVIDER_CODE,
            display_name='SiliconFlow',
            base_url=DEFAULT_PROVIDER_BASE_URL,
            enabled=True,
        )
        db.session.add(provider)

    policies = [
        ('assistant', 'dialogue', 'basic', 'small', DEFAULT_CHAT_MODEL, 800),
        ('assistant', 'dialogue', 'standard', 'standard', DEFAULT_CHAT_MODEL, 1200),
        ('assistant', '*', 'basic', 'small', DEFAULT_CHAT_MODEL, 800),
        ('assistant', '*', 'standard', 'standard', DEFAULT_CHAT_MODEL, 1200),
        ('resume_ai', 'resume_analysis', 'standard', 'standard', DEFAULT_CHAT_MODEL, 3000),
        ('interview_ai', 'interview_analysis', 'standard', 'standard', DEFAULT_CHAT_MODEL, 3000),
        ('exam_ai', 'exam_generation', 'standard', 'standard', DEFAULT_CHAT_MODEL, 2500),
        ('training_ai', 'course_qa', 'standard', 'standard', DEFAULT_CHAT_MODEL, 800),
        ('assistant', 'assistant_voice_transcription', 'basic', 'asr', DEFAULT_ASR_MODEL, 1200),
        ('assistant', 'assistant_voice_transcription', 'standard', 'asr', DEFAULT_ASR_MODEL, 1200),
        ('interview_ai', 'interview_recording_transcription', 'basic', 'asr', DEFAULT_ASR_MODEL, 1200),
        ('interview_ai', 'interview_recording_transcription', 'standard', 'asr', DEFAULT_ASR_MODEL, 1200),
        ('interview_ai', 'interview_recording_transcription', 'professional', 'asr', DEFAULT_ASR_MODEL, 1200),
        ('system_ai', '*', 'standard', 'standard', DEFAULT_CHAT_MODEL, 1200),
    ]
    for domain, use_case, tier, profile, model, max_tokens in policies:
        row = AIModelPolicy.query.filter_by(resource_domain=domain, use_case=use_case, tier=tier).first()
        if not row:
            row = AIModelPolicy(id=_new_id(), resource_domain=domain, use_case=use_case, tier=tier)
            db.session.add(row)
        if overwrite_existing or not row.provider_code:
            row.provider_code = DEFAULT_PROVIDER_CODE
        if overwrite_existing or not row.model_profile:
            row.model_profile = profile
        if overwrite_existing or not row.model:
            row.model = model
        if overwrite_existing or row.max_tokens is None:
            row.max_tokens = max_tokens
        if overwrite_existing or row.enabled is None:
            row.enabled = True
    db.session.commit()


def grant_tenant_ai_entitlement(
    tenant_id: str,
    *,
    resource_domain: str,
    package_code: str,
    enabled: bool,
    selected_tier: str,
    allowed_tiers: list[str],
    monthly_quota: int,
    commit: bool = True,
) -> TenantAIEntitlement:
    domain = str(resource_domain or '').strip()
    if domain not in AI_RESOURCE_DOMAINS or domain == 'system_ai':
        raise AIResourceDenied('AI_RESOURCE_DISABLED', 'AI 资源域不存在或不可分配', 400)
    tiers = [str(tier) for tier in (allowed_tiers or []) if tier]
    selected = str(selected_tier or (tiers[0] if tiers else 'standard'))
    if selected not in tiers:
        raise AIResourceDenied('AI_TIER_NOT_ALLOWED', '所选 AI 档位不在已购权益范围内', 400)
    row = TenantAIEntitlement.query.filter_by(tenant_id=tenant_id, resource_domain=domain).first()
    if not row:
        row = TenantAIEntitlement(id=_new_id(), tenant_id=tenant_id, resource_domain=domain)
        db.session.add(row)
    row.package_code = package_code
    row.enabled = bool(enabled)
    row.selected_tier = selected
    row.allowed_tiers = tiers
    row.monthly_quota = int(monthly_quota)
    row.period_key = current_period_key()
    row.updated_at = datetime.utcnow()
    if commit:
        db.session.commit()
    return row


def assert_ai_resource_allowed(
    *,
    tenant_id: str | None,
    user_id: str | None,
    resource_domain: str,
    use_case: str,
    units: int = 1,
    reserve: bool = False,
) -> AIResourceDecision:
    domain = str(resource_domain or '').strip()
    if domain not in AI_RESOURCE_DOMAINS:
        raise AIResourceDenied('AI_RESOURCE_DISABLED', 'AI 资源域不存在或未开通')
    if domain == 'system_ai':
        raise AIResourceDenied('AI_RESOURCE_DISABLED', '平台诊断 AI 不允许企业侧调用')
    if not tenant_id:
        raise AIResourceDenied('TENANT_REQUIRED', '缺少企业租户上下文')
    entitlement = TenantAIEntitlement.query.filter_by(tenant_id=tenant_id, resource_domain=domain).first()
    if not entitlement or not entitlement.enabled:
        raise AIResourceDenied('AI_RESOURCE_DISABLED', f'{DOMAIN_LABELS.get(domain, domain)}未开通')
    observed_used = usage_count(tenant_id, domain)
    used, reservation = (
        _reserved_usage(tenant_id, domain, observed_used)
        if reserve
        else (observed_used, None)
    )
    quota = entitlement.monthly_quota
    requested_units = max(int(units or 1), 1)
    if quota is not None and quota >= 0 and used + requested_units > quota:
        raise AIResourceDenied('AI_QUOTA_EXCEEDED', 'AI 月额度已用完', 403, {'limit': quota, 'current': used})
    if reservation is not None:
        reservation['pending'] += requested_units
    return AIResourceDecision(
        tenant_id=tenant_id,
        user_id=user_id,
        resource_domain=domain,
        use_case=use_case,
        tier=entitlement.selected_tier or 'standard',
        entitlement_id=entitlement.id,
        monthly_quota=quota,
        used_this_month=used,
    )


def save_provider_config(
    provider_code: str,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> AIProviderConfig:
    code = str(provider_code or '').strip()
    if not code:
        raise AIResourceDenied('AI_PROVIDER_INVALID', '供应商编码不能为空', 400)
    row = AIProviderConfig.query.filter_by(provider_code=code).first()
    if 'baseUrl' in data:
        raw_base_url = data.get('baseUrl')
    elif 'base_url' in data:
        raw_base_url = data.get('base_url')
    else:
        if row is None:
            raise AIResourceDenied('AI_PROVIDER_BASE_URL_INVALID', 'AI 供应商地址必须是有效的 HTTP(S) URL', 400)
        raw_base_url = row.base_url
    if not isinstance(raw_base_url, str):
        raise AIResourceDenied('AI_PROVIDER_BASE_URL_INVALID', 'AI 供应商地址必须是有效的 HTTP(S) URL', 400)
    base_url = raw_base_url.strip().rstrip('/')
    try:
        parsed_base_url = urlsplit(base_url)
        valid_port = parsed_base_url.port
    except ValueError:
        parsed_base_url = None
        valid_port = None
    if (
        parsed_base_url is None
        or parsed_base_url.scheme.lower() not in {'http', 'https'}
        or not parsed_base_url.hostname
        or parsed_base_url.username is not None
        or parsed_base_url.password is not None
        or parsed_base_url.query
        or parsed_base_url.fragment
        or any(character.isspace() for character in base_url)
        or (valid_port is not None and not 1 <= valid_port <= 65535)
    ):
        raise AIResourceDenied('AI_PROVIDER_BASE_URL_INVALID', 'AI 供应商地址必须是有效的 HTTP(S) URL', 400)
    if not row:
        row = AIProviderConfig(id=f'provider-{code}', provider_code=code)
        db.session.add(row)
    row.display_name = (data.get('displayName') or data.get('display_name') or row.display_name or code).strip()
    row.base_url = base_url
    if 'enabled' in data:
        row.enabled = bool(data.get('enabled'))
    settings = dict(row.settings_json or {})
    if isinstance(data.get('settings'), dict):
        settings = dict(data.get('settings') or {})
    settings['_configuredByOperator'] = True
    row.settings_json = settings
    raw_api_key = data.get('apiKey') if 'apiKey' in data else data.get('api_key')
    api_key = str(raw_api_key or '').strip()
    if api_key:
        row.api_key_encrypted = encrypt_provider_secret(api_key)
        row.api_key_mask = mask_api_key(api_key)
    row.updated_at = datetime.utcnow()
    if commit:
        db.session.commit()
    return row


def save_model_policy(data: dict[str, Any], *, commit: bool = True) -> AIModelPolicy:
    domain = str(data.get('resourceDomain') or data.get('resource_domain') or '').strip()
    use_case = str(data.get('useCase') or data.get('use_case') or '*').strip() or '*'
    tier = str(data.get('tier') or 'standard').strip() or 'standard'
    if domain not in AI_RESOURCE_DOMAINS:
        raise AIResourceDenied('AI_RESOURCE_DISABLED', 'AI 资源域不存在', 400)
    row_id = data.get('id') or data.get('policyId')
    row = db.session.get(AIModelPolicy, row_id) if row_id else None
    if not row:
        row = AIModelPolicy.query.filter_by(resource_domain=domain, use_case=use_case, tier=tier).first()
    scope_conflict = AIModelPolicy.query.filter_by(
        resource_domain=domain,
        use_case=use_case,
        tier=tier,
    ).first()
    if scope_conflict and (not row or scope_conflict.id != row.id):
        raise AIResourceDenied(
            'AI_MODEL_POLICY_CONFLICT',
            '相同资源域、用途和档位的 AI 模型策略已存在',
            409,
        )

    if tier not in TIER_LABELS:
        raise AIResourceDenied('AI_TIER_INVALID', 'AI 模型策略档位无效', 400)
    provider_code = str(
        data.get('providerCode')
        or data.get('provider_code')
        or (row.provider_code if row else DEFAULT_PROVIDER_CODE)
    ).strip()
    provider = AIProviderConfig.query.filter_by(provider_code=provider_code).first()
    if not provider:
        raise AIResourceDenied('AI_PROVIDER_NOT_FOUND', 'AI 模型策略引用的供应商不存在', 400)
    if not provider.enabled:
        raise AIResourceDenied('AI_PROVIDER_DISABLED', 'AI 模型策略引用的供应商已停用', 400)

    if 'model' in data:
        model = str(data.get('model') or '').strip()
    else:
        model = str(row.model if row else DEFAULT_CHAT_MODEL).strip()
    if not model:
        raise AIResourceDenied('AI_MODEL_POLICY_INVALID', 'AI 模型名称不能为空', 400)

    if 'maxTokens' in data:
        raw_max_tokens = data.get('maxTokens')
    elif 'max_tokens' in data:
        raw_max_tokens = data.get('max_tokens')
    else:
        raw_max_tokens = row.max_tokens if row else 1200
    invalid_numeric_type = isinstance(raw_max_tokens, bool) or (
        isinstance(raw_max_tokens, float) and not raw_max_tokens.is_integer()
    )
    try:
        max_tokens = 0 if invalid_numeric_type else int(raw_max_tokens)
    except (TypeError, ValueError):
        max_tokens = 0
    if max_tokens <= 0:
        raise AIResourceDenied('AI_MODEL_POLICY_INVALID', 'AI 模型最大令牌数必须为正整数', 400)

    if not row:
        row = AIModelPolicy(id=_new_id(), resource_domain=domain, use_case=use_case, tier=tier)
        db.session.add(row)
    row.resource_domain = domain
    row.use_case = use_case
    row.tier = tier
    row.provider_code = provider_code
    row.model_profile = str(data.get('modelProfile') or data.get('model_profile') or 'standard')
    row.model = model
    row.max_tokens = max_tokens
    if 'enabled' in data:
        row.enabled = bool(data.get('enabled'))
    if isinstance(data.get('settings'), dict):
        row.settings_json = data.get('settings') or {}
    row.updated_at = datetime.utcnow()
    if commit:
        db.session.commit()
    return row


def resolve_model_policy(resource_domain: str, use_case: str | None, tier: str | None) -> AIModelPolicy:
    domain = str(resource_domain or '').strip()
    selected_tier = str(tier or 'standard').strip() or 'standard'
    selected_use_case = str(use_case or '*').strip() or '*'
    candidates = [
        {'resource_domain': domain, 'use_case': selected_use_case, 'tier': selected_tier},
        {'resource_domain': domain, 'use_case': '*', 'tier': selected_tier},
        {'resource_domain': domain, 'use_case': selected_use_case, 'tier': 'standard'},
        {'resource_domain': domain, 'use_case': '*', 'tier': 'standard'},
    ]
    for filters in candidates:
        row = AIModelPolicy.query.filter_by(**filters, enabled=True).first()
        if row:
            return row
    raise AIResourceDenied('AI_MODEL_POLICY_MISSING', '平台 AI 模型策略未配置', 503)


def resolve_provider_config(provider_code: str | None = None) -> tuple[AIProviderConfig, str | None]:
    code = provider_code or DEFAULT_PROVIDER_CODE
    row = AIProviderConfig.query.filter_by(provider_code=code, enabled=True).first()
    if not row:
        row = AIProviderConfig(
            id=f'provider-{code}',
            provider_code=code,
            display_name='SiliconFlow' if code == DEFAULT_PROVIDER_CODE else code,
            base_url=os.getenv('SILICONFLOW_API_URL', DEFAULT_PROVIDER_BASE_URL).rstrip('/'),
            enabled=True,
        )
    api_key = decrypt_provider_secret(row.api_key_encrypted)
    if not api_key and code == DEFAULT_PROVIDER_CODE:
        api_key = os.getenv('SILICONFLOW_API_KEY', '').strip() or None
    if not api_key:
        raise AIResourceDenied('AI_PROVIDER_UNAVAILABLE', '平台 AI 供应商密钥未配置', 503)
    return row, api_key


def resolve_governed_chat_target(resource_domain: str, use_case: str | None, tier: str | None) -> tuple[AIModelPolicy, AIProviderConfig, str]:
    policy = resolve_model_policy(resource_domain, use_case, tier)
    provider, api_key = resolve_provider_config(policy.provider_code)
    return policy, provider, api_key or ''


def _new_usage_session():
    return sessionmaker(bind=db.engine, expire_on_commit=False)()


def record_ai_usage(
    *,
    tenant_id: str | None,
    user_id: str | None,
    resource_domain: str | None,
    use_case: str | None,
    tier: str | None,
    provider: str | None,
    model: str | None,
    status: str,
    units: int = 1,
    request_id: str | None = None,
    assistant_audit_log_id: str | None = None,
    prompt_chars: int = 0,
    response_chars: int = 0,
    error_code: str | None = None,
    meta: dict[str, Any] | None = None,
    session: Any | None = None,
    commit: bool = True,
) -> AIUsageLedger | None:
    domain = str(resource_domain or '').strip()
    if not domain:
        return None
    row = AIUsageLedger(
        id=_new_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        resource_domain=domain,
        use_case=use_case,
        tier=tier,
        provider=provider,
        model=model,
        status=status or 'success',
        units=max(int(units or 1), 1),
        request_id=request_id,
        assistant_audit_log_id=assistant_audit_log_id,
        prompt_chars=prompt_chars or 0,
        response_chars=response_chars or 0,
        error_code=error_code,
        meta_json=meta or {},
    )
    owns_session = session is None
    target_session = session or _new_usage_session()
    try:
        target_session.add(row)
        if owns_session and commit:
            target_session.commit()
            settle_ai_usage_reservation(tenant_id, domain, units=row.units)
        return row
    except Exception:
        if owns_session:
            target_session.rollback()
            return None
        raise
    finally:
        if owns_session:
            target_session.close()


def tenant_entitlement_payload(tenant_id: str) -> dict[str, Any]:
    rows = TenantAIEntitlement.query.filter_by(tenant_id=tenant_id).order_by(TenantAIEntitlement.resource_domain.asc()).all()
    existing = {row.resource_domain for row in rows}
    entitlements = [row.to_dict(tenant_safe=True) for row in rows]
    for domain in AI_RESOURCE_DOMAINS:
        if domain == 'system_ai' or domain in existing:
            continue
        entitlements.append({
            'id': None,
            'tenantId': tenant_id,
            'resourceDomain': domain,
            'resourceLabel': DOMAIN_LABELS.get(domain, domain),
            'enabled': False,
            'selectedTier': None,
            'allowedTiers': [],
            'monthlyQuota': 0,
            'usedThisMonth': 0,
            'remainingQuota': 0,
        })
    for row in entitlements:
        row.setdefault('resourceLabel', DOMAIN_LABELS.get(row.get('resourceDomain'), row.get('resourceDomain')))
        row['tierLabels'] = TIER_LABELS
    return {'tenantId': tenant_id, 'entitlements': entitlements}


def tenant_usage_payload(tenant_id: str, *, tenant_safe: bool = True) -> dict[str, Any]:
    rows = (
        AIUsageLedger.query
        .filter(AIUsageLedger.tenant_id == tenant_id, AIUsageLedger.created_at >= current_period_start())
        .order_by(AIUsageLedger.created_at.desc())
        .limit(200)
        .all()
    )
    by_domain: dict[str, int] = {}
    for row in rows:
        by_domain[row.resource_domain] = by_domain.get(row.resource_domain, 0) + (row.units or 1)
    return {
        'tenantId': tenant_id,
        'periodKey': current_period_key(),
        'total': sum(by_domain.values()),
        'byDomain': by_domain,
        'items': [row.to_dict(tenant_safe=tenant_safe) for row in rows],
    }


def select_tenant_tier(tenant_id: str, resource_domain: str, tier: str) -> TenantAIEntitlement:
    row = TenantAIEntitlement.query.filter_by(tenant_id=tenant_id, resource_domain=resource_domain).first()
    if not row or not row.enabled:
        raise AIResourceDenied('AI_RESOURCE_DISABLED', '该 AI 资源未开通')
    if tier not in (row.allowed_tiers or []):
        raise AIResourceDenied('AI_TIER_NOT_ALLOWED', '所选 AI 档位不在已购权益范围内', 400)
    row.selected_tier = tier
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return row


def _record_asr_attempt(
    *,
    tenant_id: str | None,
    user_id: str | None,
    request_id: str | None,
    resource_domain: str,
    use_case: str,
    decision: AIResourceDecision,
    runtime: Any,
    status: str,
    response_content: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    http_status: int | None = None,
) -> None:
    from services.assistant_core.audit import record_llm_call

    response_meta = {
        'runtimeSource': runtime.source,
        'mediaIncluded': False,
    }
    if error_code:
        response_meta['errorCode'] = error_code
    if http_status is not None:
        response_meta['httpStatus'] = http_status
    record_llm_call(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=None,
        request_id=request_id,
        provider=runtime.provider_code,
        model=runtime.model,
        model_profile='asr',
        use_case=use_case,
        messages=[],
        response_content=response_content,
        response_meta=response_meta,
        status=status,
        error_message=error_message,
        latency_ms=None,
        resource_domain=resource_domain,
        ai_tier=decision.tier,
        tenant_ai_entitlement_id=decision.entitlement_id,
        usage_meta={'runtimeSource': runtime.source},
    )


def transcribe_audio_with_governance(
    audio_path: str,
    *,
    language: str = 'zh',
    tenant_id: str | None,
    user_id: str | None,
    resource_domain: str,
    use_case: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    if not os.path.isfile(audio_path):
        return {'success': False, 'text': '', 'error': f'文件不存在: {audio_path}'}
    decision = assert_ai_resource_allowed(
        tenant_id=tenant_id,
        user_id=user_id,
        resource_domain=resource_domain,
        use_case=use_case,
    )
    try:
        runtime = resolve_ai_runtime(resource_domain, use_case, decision.tier)
    except AIRuntimeConfigurationError as exc:
        from services.assistant_core.audit import record_llm_call

        record_llm_call(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=None,
            request_id=request_id,
            provider='unresolved',
            model=DEFAULT_ASR_MODEL,
            model_profile='asr',
            messages=[],
            response_content=None,
            response_meta={
                'errorCode': exc.code,
                'runtimeConfiguration': 'invalid',
                'mediaIncluded': False,
            },
            status='error',
            error_message=exc.message,
            latency_ms=0,
            resource_domain=resource_domain,
            use_case=use_case,
            ai_tier=decision.tier,
            tenant_ai_entitlement_id=decision.entitlement_id,
            record_usage=False,
        )
        return {'success': False, 'text': '', 'error': exc.message, 'code': exc.code}
    from services.speech_to_text import _audio_mime_type

    url = runtime.base_url.rstrip('/') + '/audio/transcriptions'
    try:
        audio_file = open(audio_path, 'rb')
    except OSError as exc:
        return {'success': False, 'text': '', 'error': f'文件读取失败: {exc}'}
    with audio_file:
        files = {'file': (os.path.basename(audio_path), audio_file, _audio_mime_type(audio_path))}
        data = {'model': runtime.model, 'language': language}
        assert_ai_resource_allowed(
            tenant_id=tenant_id,
            user_id=user_id,
            resource_domain=resource_domain,
            use_case=use_case,
            reserve=True,
        )
        try:
            response = requests.post(
                url,
                headers={'Authorization': f'Bearer {runtime.api_key}'},
                files=files,
                data=data,
                timeout=300,
            )
        except Exception:
            _record_asr_attempt(
                tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
                resource_domain=resource_domain,
                use_case=use_case,
                decision=decision,
                runtime=runtime,
                status='error',
                error_code='AI_PROVIDER_UNAVAILABLE',
                error_message='ASR provider request failed',
            )
            return {
                'success': False,
                'text': '',
                'error': 'ASR 服务暂时不可用',
                'code': 'AI_PROVIDER_UNAVAILABLE',
            }
    if response.ok:
        try:
            response_payload = response.json()
        except Exception:
            response_payload = None
        if not isinstance(response_payload, dict):
            _record_asr_attempt(
                tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
                resource_domain=resource_domain,
                use_case=use_case,
                decision=decision,
                runtime=runtime,
                status='error',
                error_code='AI_PROVIDER_INVALID_RESPONSE',
                error_message='ASR provider returned an invalid response',
                http_status=getattr(response, 'status_code', None),
            )
            return {
                'success': False,
                'text': '',
                'error': 'ASR 服务返回无效响应',
                'code': 'AI_PROVIDER_INVALID_RESPONSE',
            }
        text = str(response_payload.get('text') or '')
        _record_asr_attempt(
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
            resource_domain=resource_domain,
            use_case=use_case,
            decision=decision,
            runtime=runtime,
            status='success',
            response_content=text,
            http_status=getattr(response, 'status_code', None),
        )
        return {'success': True, 'text': text, 'error': ''}
    _record_asr_attempt(
        tenant_id=tenant_id,
        user_id=user_id,
        request_id=request_id,
        resource_domain=resource_domain,
        use_case=use_case,
        decision=decision,
        runtime=runtime,
        status='error',
        error_code='AI_PROVIDER_UNAVAILABLE',
        error_message='ASR provider returned an HTTP error',
        http_status=getattr(response, 'status_code', None),
    )
    return {
        'success': False,
        'text': '',
        'error': f'ASR 服务请求失败（HTTP {response.status_code}）',
        'code': 'AI_PROVIDER_UNAVAILABLE',
    }
