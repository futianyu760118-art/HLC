"""Platform administration APIs for the SaaS edition."""

from __future__ import annotations

import ipaddress
import re
import secrets
import shutil
import string
import uuid
import hashlib
import json
from datetime import datetime
from typing import Any

import bcrypt
from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from models import (
    AIAddonPackage,
    AIModelPolicy,
    AIProviderConfig,
    ExtensionProviderConfig,
    Plan,
    PlatformOperationLog,
    Tenant,
    TenantBillingEvent,
    TenantInvoice,
    TenantModule,
    TenantOnboardingItem,
    TenantOrder,
    TenantSubscription,
    User,
    db,
)
from routes.auth import (
    FAILED_DELAY_SEC,
    _clear_failures,
    _find_login_user,
    _is_throttled,
    _record_failure,
    _token_for_user,
)
from services.tenant_data_lifecycle import tenant_data_inventory, tenant_deletion_plan, tenant_structured_export
from services.tenant_data_requests import create_data_request, list_data_requests, update_data_request
from services.billing_lifecycle import create_billing_event, list_billing_events
from services.extension_registry import EXTENSION_MODULE_KEYS, extension_catalog_payload
from services.platform_entitlements import latest_tenant_subscription
from services.platform_tenant_commands import (
    PlatformCommandError,
    PlatformTenantValidationError,
    TenantUpdateCommand,
    reset_tenant_admin_password as execute_reset_tenant_admin_password,
)
from services.tenancy import PLATFORM_TENANT_SLUG, SAAS_MODULE_KEYS, next_tenant_slug, normalize_slug, tenant_usage
from services.ai_resource_governance import (
    AIResourceDenied,
    grant_tenant_ai_entitlement,
    save_model_policy,
    save_provider_config,
    tenant_entitlement_payload,
    tenant_usage_payload,
)
from services.tenant_storage_quota import register_storage_quota_error_handler


platform_bp = Blueprint('platform', __name__)
register_storage_quota_error_handler(platform_bp)

MANAGED_PLATFORM_MODULE_KEYS = SAAS_MODULE_KEYS + EXTENSION_MODULE_KEYS
_OPAQUE_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
MAX_PLATFORM_TENANT_PAGE = 100_000
MAX_PLATFORM_TENANT_PAGE_SIZE = 500

def _new_id() -> str:
    return str(uuid.uuid4())


def _generate_initial_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(length))
        classes = [
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(c in '!@#$%^&*' for c in value),
        ]
        if sum(classes) >= 3:
            return value


@platform_bp.route('/auth/login', methods=['POST'])
def platform_login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or data.get('email') or '').strip()
    password = data.get('password') or ''

    if not identifier or not password:
        return jsonify({'error': '账号或密码不能为空'}), 400

    remote = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
    fail_key = f'platform:{remote}:{identifier.lower()}'
    if _is_throttled(fail_key):
        import time
        time.sleep(FAILED_DELAY_SEC)

    user, duplicated_name = _find_login_user(identifier, None, platform_login=True)
    if duplicated_name:
        return jsonify({'error': '姓名账号重复，请使用邮箱登录或联系管理员处理重名账号'}), 409

    dummy_hash = b'$2b$12$00000000000000000000000000000000000000000000000000000'
    candidate_hash = (user.password_hash.encode('utf-8') if user else dummy_hash)
    try:
        is_valid = bcrypt.checkpw(password.encode('utf-8'), candidate_hash)
    except (ValueError, TypeError):
        is_valid = False

    if not user or not is_valid:
        _record_failure(fail_key)
        return jsonify({'error': '账号或密码错误'}), 401

    if getattr(user, 'status', 'active') == 'inactive':
        return jsonify({'error': '账号已停用，请联系管理员'}), 403
    if user.role != 'platform_admin':
        return jsonify({'error': '平台入口仅允许平台管理员登录'}), 403

    user.last_login_at = datetime.utcnow()
    db.session.commit()
    _clear_failures(fail_key)

    payload = user.to_dict()
    payload.update({
        'tenantId': None,
        'tenantSlug': PLATFORM_TENANT_SLUG,
        'tenantName': '平台管理',
        'isPlatformAdmin': True,
    })
    return jsonify({'token': _token_for_user(user, None, is_platform_admin=True), 'user': payload})


def _parse_datetime(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _int_or_default(value: Any, default: int | None) -> int | None:
    if value is None or value == '':
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_positive_int(value: Any, *, default: int, maximum: int) -> int:
    parsed = _int_or_default(value, default)
    if parsed is None or parsed < 1:
        return default
    return min(parsed, maximum)


def _platform_log(action: str, *, tenant_id: str | None = None, target_type: str | None = None,
                  target_id: str | None = None, detail: dict | None = None,
                  result: str = 'success', request_id: str | None = None,
                  error_code: str | None = None) -> None:
    db.session.add(PlatformOperationLog(
        id=_new_id(),
        user_id=get_jwt_identity(),
        tenant_id=tenant_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        request_id=_sanitize_request_id(request_id),
        error_code=error_code,
        detail=detail or {},
        ip_address=_validated_audit_ip(),
    ))


def _validated_audit_ip() -> str | None:
    """Use only the framework-resolved, syntactically valid peer address.

    ``X-Forwarded-For`` is untrusted at the route layer.  In production
    ``ProxyFix`` resolves the configured proxy hop into ``request.remote_addr``;
    in tests/direct deployments an invalid value is simply omitted rather than
    persisted as arbitrary audit text.
    """

    value = request.remote_addr
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _platform_request_id() -> str:
    """Return a bounded opaque correlation ID without persisting client PII."""

    client_value = request.headers.get('X-Request-ID')
    if client_value is not None and str(client_value).strip():
        # A syntactically opaque header can still be a phone number, account
        # number, or secret. Hash every client-provided correlation value;
        # never infer sensitivity from its character set.
        request_id = hashlib.sha256(
            str(client_value).encode('utf-8', errors='surrogatepass')
        ).hexdigest()
    else:
        value = getattr(g, 'request_id', None) or uuid.uuid4().hex
        request_id = _sanitize_request_id(value) or uuid.uuid4().hex
    # Keep the response header and access log correlated to the same safe ID.
    g.request_id = request_id
    return request_id


def _sanitize_request_id(value: Any) -> str | None:
    """Keep only opaque correlation IDs in persistent audit rows."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _OPAQUE_REQUEST_ID_RE.fullmatch(text):
        return text
    return hashlib.sha256(text.encode('utf-8', errors='surrogatepass')).hexdigest()


def _reset_failure_detail(data: dict[str, Any], *, tenant_resolved: bool) -> dict[str, Any]:
    """Build a deliberately non-sensitive failure detail payload."""

    user_id = data.get('userId')
    return {
        'tenantResolved': bool(tenant_resolved),
        'targetProvided': isinstance(user_id, str) and bool(user_id.strip()),
        'confirmationProvided': isinstance(data.get('confirmation'), str)
        and bool(data.get('confirmation').strip()),
    }


def _reset_failure_target_id(value: Any) -> str | None:
    """Pseudonymize the untrusted target supplied on a failed reset."""

    if not isinstance(value, str) or not value.strip():
        return None
    digest = hashlib.sha256(value.strip().encode('utf-8', errors='surrogatepass')).hexdigest()[:24]
    return f'sha256:{digest}'


def _record_reset_failure(
    *,
    tenant_id: str | None,
    target_id: str | None,
    request_id: str,
    error_code: str,
    detail: dict[str, Any],
) -> None:
    """Persist a sanitized failure audit in its own transaction.

    A failed command must never leave a dirty SQLAlchemy transaction that could
    accidentally be committed by a later request.  If the audit itself cannot
    be persisted, only a fixed, secret-free server log is emitted.
    """

    try:
        db.session.rollback()
        _platform_log(
            'reset_admin_password',
            tenant_id=tenant_id,
            target_type='user',
            target_id=target_id,
            detail=detail,
            result='failure',
            request_id=request_id,
            error_code=error_code,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.error(
            'platform_reset_failure_audit_failed',
            extra={'request_id': request_id, 'error_code': error_code},
        )


def _data_request_create_log_detail(data: dict, row) -> dict[str, Any]:
    return {
        'requestType': row.request_type,
        'status': row.status,
        'hasRequester': bool((data.get('requester') or '').strip()),
        'scopeLength': len((data.get('scope') or '').strip()),
        'hasEvidenceRef': bool((data.get('evidenceRef') or '').strip()),
    }


def _data_request_update_log_detail(data: dict) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    if 'status' in data:
        detail['status'] = data.get('status')
    if 'evidenceRef' in data:
        detail['hasEvidenceRef'] = bool((data.get('evidenceRef') or '').strip())
        detail['clearsEvidenceRef'] = not bool((data.get('evidenceRef') or '').strip())
    return detail


def _billing_event_log_detail(data: dict, row: TenantBillingEvent) -> dict[str, Any]:
    note = (data.get('note') or '').strip()
    return {
        'eventType': row.event_type,
        'hasNote': bool(note),
        'noteLength': len(note),
    }


def _latest_subscription(tenant_id: str) -> TenantSubscription | None:
    return latest_tenant_subscription(tenant_id)


def _modules_for_tenant(tenant_id: str) -> list[TenantModule]:
    return TenantModule.query.filter_by(tenant_id=tenant_id).order_by(TenantModule.module_key.asc()).all()


def _module_payload_map(data: dict, plan: Plan | None = None) -> dict[str, dict[str, Any]]:
    enabled_defaults = set(plan.enabled_modules_json or SAAS_MODULE_KEYS) if plan else set(SAAS_MODULE_KEYS)
    result = {
        module_key: {'enabled': module_key in enabled_defaults, 'limits': {}}
        for module_key in MANAGED_PLATFORM_MODULE_KEYS
    }

    enabled_modules = data.get('enabledModules')
    if isinstance(enabled_modules, list):
        enabled_set = {str(key) for key in enabled_modules}
        for module_key in MANAGED_PLATFORM_MODULE_KEYS:
            result[module_key]['enabled'] = module_key in enabled_set

    modules = data.get('modules')
    if isinstance(modules, dict):
        for module_key, config in modules.items():
            if module_key not in result:
                continue
            if isinstance(config, dict):
                if 'enabled' in config:
                    result[module_key]['enabled'] = bool(config.get('enabled'))
                if isinstance(config.get('limits'), dict):
                    result[module_key]['limits'] = config.get('limits') or {}
            else:
                result[module_key]['enabled'] = bool(config)
    elif isinstance(modules, list):
        for item in modules:
            if not isinstance(item, dict):
                continue
            module_key = str(item.get('moduleKey') or item.get('key') or '')
            if module_key not in result:
                continue
            if 'enabled' in item:
                result[module_key]['enabled'] = bool(item.get('enabled'))
            if isinstance(item.get('limits'), dict):
                result[module_key]['limits'] = item.get('limits') or {}

    return result


def _sync_modules(tenant_id: str, payload: dict[str, dict[str, Any]]) -> None:
    existing = {module.module_key: module for module in TenantModule.query.filter_by(tenant_id=tenant_id).all()}
    for module_key in MANAGED_PLATFORM_MODULE_KEYS:
        config = payload.get(module_key) or {'enabled': False, 'limits': {}}
        module = existing.get(module_key)
        if not module:
            module = TenantModule(id=_new_id(), tenant_id=tenant_id, module_key=module_key)
            db.session.add(module)
        module.enabled = bool(config.get('enabled'))
        module.limits_json = config.get('limits') or {}
        module.updated_at = datetime.utcnow()


def _tenant_payload(
    tenant: Tenant,
    *,
    include_detail: bool = False,
    measured_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = tenant.to_dict()
    if include_detail:
        subscription = _latest_subscription(tenant.id)
        usage = measured_usage if measured_usage is not None else tenant_usage(tenant.id)
        data.update({
            'subscription': subscription.to_dict() if subscription else None,
            'modules': [module.to_dict() for module in _modules_for_tenant(tenant.id)],
            'usage': usage,
            'admins': [
                {
                    'id': user.id,
                    'email': user.email,
                    'name': user.name,
                    'role': user.role,
                    'status': user.status,
                }
                for user in User.query.filter(
                    User.tenant_id == tenant.id,
                    User.status == 'active',
                    User.role.in_(('admin', 'hr_admin')),
                ).order_by(User.name.asc(), User.id.asc()).all()
            ],
        })
    return data


def _extension_secret_ref(provider_code: str, secret_value: str) -> str:
    digest = hashlib.sha256(f'{provider_code}:{secret_value}'.encode('utf-8')).hexdigest()[:16]
    return f'secret-ref:{provider_code}:{digest}'


def _ai_error_response(exc: AIResourceDenied):
    payload, status = exc.to_response()
    return jsonify(payload), status


@platform_bp.route('/extensions/catalog', methods=['GET'])
@jwt_required()
def get_extension_catalog():
    return jsonify(extension_catalog_payload())


@platform_bp.route('/extensions/providers', methods=['GET'])
@jwt_required()
def list_extension_providers():
    rows = ExtensionProviderConfig.query.order_by(ExtensionProviderConfig.provider_code.asc()).all()
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/extensions/providers/<provider_code>', methods=['GET'])
@jwt_required()
def get_extension_provider(provider_code):
    row = ExtensionProviderConfig.query.filter_by(provider_code=provider_code).first()
    if not row:
        return jsonify({
            'providerType': provider_code,
            'providerCode': provider_code,
            'status': 'unconfigured',
            'configJson': {},
            'secretRef': '',
            'lastTestedAt': None,
        })
    return jsonify(row.to_dict())


@platform_bp.route('/extensions/providers/<provider_code>', methods=['PUT'])
@jwt_required()
def update_extension_provider(provider_code):
    data = request.get_json(silent=True) or {}
    normalized_code = str(provider_code or data.get('providerCode') or '').strip()
    if not normalized_code:
        return jsonify({'error': 'providerCode 不能为空'}), 400
    row = ExtensionProviderConfig.query.filter_by(provider_code=normalized_code).first()
    if not row:
        row = ExtensionProviderConfig(
            id=_new_id(),
            provider_code=normalized_code,
            provider_type=str(data.get('providerType') or normalized_code).strip() or normalized_code,
            status='unconfigured',
            config_json={},
        )
        db.session.add(row)
    row.provider_type = str(data.get('providerType') or row.provider_type or normalized_code).strip() or normalized_code
    row.status = str(data.get('status') or row.status or 'unconfigured').strip() or 'unconfigured'
    if isinstance(data.get('configJson'), dict):
        row.config_json = data.get('configJson') or {}
    elif isinstance(data.get('config'), dict):
        row.config_json = data.get('config') or {}
    if data.get('secretValue'):
        row.secret_ref = _extension_secret_ref(normalized_code, str(data.get('secretValue')))
    elif data.get('secretRef'):
        row.secret_ref = str(data.get('secretRef'))
    if 'lastTestedAt' in data:
        row.last_tested_at = _parse_datetime(data.get('lastTestedAt'))
    row.updated_at = datetime.utcnow()
    _platform_log('update_extension_provider', target_type='extension_provider', target_id=row.provider_code, detail={
        'providerType': row.provider_type,
        'providerCode': row.provider_code,
        'status': row.status,
        'hasSecretRef': bool(row.secret_ref),
        'configKeys': sorted((row.config_json or {}).keys()),
    })
    db.session.commit()
    return jsonify(row.to_dict())


@platform_bp.route('/ai/providers', methods=['GET'])
@jwt_required()
def list_ai_providers():
    rows = AIProviderConfig.query.order_by(AIProviderConfig.provider_code.asc()).all()
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/ai/providers/<provider_code>', methods=['PUT'])
@jwt_required()
def update_ai_provider(provider_code):
    try:
        row = save_provider_config(
            provider_code,
            request.get_json(silent=True) or {},
            commit=False,
        )
        _platform_log('update_ai_provider', target_type='ai_provider', target_id=row.provider_code, detail={
            'providerCode': row.provider_code,
            'hasApiKey': bool(row.api_key_encrypted),
            'enabled': bool(row.enabled),
        })
        db.session.commit()
    except AIResourceDenied as exc:
        db.session.rollback()
        return _ai_error_response(exc)
    except Exception:
        db.session.rollback()
        raise
    return jsonify(row.to_dict())


@platform_bp.route('/ai/model-policies', methods=['GET'])
@jwt_required()
def list_ai_model_policies():
    rows = AIModelPolicy.query.order_by(
        AIModelPolicy.resource_domain.asc(),
        AIModelPolicy.use_case.asc(),
        AIModelPolicy.tier.asc(),
    ).all()
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/ai/model-policies/<policy_id>', methods=['PUT'])
@jwt_required()
def update_ai_model_policy(policy_id):
    data = request.get_json(silent=True) or {}
    data['id'] = policy_id
    try:
        row = save_model_policy(data, commit=False)
        _platform_log('update_ai_model_policy', target_type='ai_model_policy', target_id=row.id, detail={
            'resourceDomain': row.resource_domain,
            'useCase': row.use_case,
            'tier': row.tier,
        })
        db.session.commit()
    except AIResourceDenied as exc:
        db.session.rollback()
        return _ai_error_response(exc)
    except Exception:
        db.session.rollback()
        raise
    return jsonify(row.to_dict())


@platform_bp.route('/ai/model-policies', methods=['POST'])
@jwt_required()
def create_ai_model_policy():
    try:
        row = save_model_policy(request.get_json(silent=True) or {}, commit=False)
        _platform_log('create_ai_model_policy', target_type='ai_model_policy', target_id=row.id, detail={
            'resourceDomain': row.resource_domain,
            'useCase': row.use_case,
            'tier': row.tier,
        })
        db.session.commit()
    except AIResourceDenied as exc:
        db.session.rollback()
        return _ai_error_response(exc)
    except Exception:
        db.session.rollback()
        raise
    return jsonify(row.to_dict()), 201


@platform_bp.route('/ai/addon-packages', methods=['GET'])
@jwt_required()
def list_ai_addon_packages():
    rows = AIAddonPackage.query.order_by(AIAddonPackage.code.asc()).all()
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/tenants/<tenant_id>/ai-entitlements', methods=['GET'])
@jwt_required()
def get_tenant_ai_entitlements(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    return jsonify(tenant_entitlement_payload(tenant.id))


@platform_bp.route('/tenants/<tenant_id>/ai-entitlements', methods=['PUT'])
@jwt_required()
def update_tenant_ai_entitlements(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    rows = data.get('entitlements') if isinstance(data.get('entitlements'), list) else []
    updated = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            row = grant_tenant_ai_entitlement(
                tenant.id,
                resource_domain=item.get('resourceDomain') or item.get('resource_domain'),
                package_code=item.get('packageCode') or item.get('package_code') or 'ai_assistant',
                enabled=bool(item.get('enabled')),
                selected_tier=item.get('selectedTier') or item.get('selected_tier') or 'standard',
                allowed_tiers=item.get('allowedTiers') or item.get('allowed_tiers') or ['standard'],
                monthly_quota=_int_or_default(item.get('monthlyQuota') or item.get('monthly_quota'), 0) or 0,
                commit=False,
            )
        except AIResourceDenied as exc:
            db.session.rollback()
            return _ai_error_response(exc)
        updated.append(row)
    _platform_log('update_tenant_ai_entitlements', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail={
        'count': len(updated),
        'domains': [row.resource_domain for row in updated],
    })
    db.session.commit()
    return jsonify({'tenantId': tenant.id, 'entitlements': [row.to_dict() for row in updated]})


@platform_bp.route('/tenants/<tenant_id>/ai-usage', methods=['GET'])
@jwt_required()
def get_tenant_ai_usage(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    return jsonify(tenant_usage_payload(tenant.id, tenant_safe=False))


@platform_bp.route('/ai/diagnostics/model-call-test', methods=['POST'])
@jwt_required()
def platform_ai_model_call_test():
    from services.assistant_core.memory import build_context
    from services.assistant_core.model_diagnostics import run_model_call_test

    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt') or '')[:800]
    profile = str(data.get('modelProfile') or '').strip() or None
    ctx = build_context(
        get_jwt_identity(),
        None,
        request_id=request.headers.get('X-Request-ID') or f'platform-ai-{uuid.uuid4().hex[:10]}',
        client_context={'source': 'platform_ai_diagnostics'},
    )
    return jsonify(run_model_call_test(prompt, ctx, profile=profile, use_case='model_call_test', resource_domain='system_ai'))


@platform_bp.route('/ai/diagnostics/model-stream-test', methods=['POST'])
@jwt_required()
def platform_ai_model_stream_test():
    from services.assistant_core.memory import build_context
    from services.assistant_core.model_diagnostics import stream_model_call_test

    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt') or '')[:800]
    profile = str(data.get('modelProfile') or '').strip() or None
    client_context = dict(data.get('clientContext') or {}) if isinstance(data.get('clientContext'), dict) else {}
    client_context['source'] = 'platform_ai_diagnostics'
    ctx = build_context(
        get_jwt_identity(),
        None,
        request_id=request.headers.get('X-Request-ID') or f'platform-ai-{uuid.uuid4().hex[:10]}',
        client_context=client_context,
    )

    def sse(event: str, payload: dict) -> str:
        return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n'

    @stream_with_context
    def generate():
        yield sse('status', {'message': '正在发起平台 AI 真实流式调用...'})
        try:
            for item in stream_model_call_test(
                prompt,
                ctx,
                profile=profile,
                use_case='model_stream_test',
                resource_domain='system_ai',
            ):
                event = item.get('event')
                if event == 'delta':
                    yield sse('delta', {'content': item.get('content') or ''})
                elif event == 'final':
                    yield sse('final', item.get('payload') or {})
        except Exception as exc:
            current_app.logger.exception('platform_ai_model_stream_test_failed')
            yield sse('error', {'error': str(exc) or '流式模型调用测试失败'})

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@platform_bp.route('/ai/evaluation-cases', methods=['GET'])
@jwt_required()
def platform_ai_evaluation_cases():
    from services.assistant_core.evaluation import load_evaluation_suite
    from services.assistant_core.evaluation_safety import EvaluationSafetyError

    try:
        return jsonify(load_evaluation_suite())
    except EvaluationSafetyError as exc:
        payload = {'error': str(exc), 'code': exc.code}
        if exc.case_ids:
            payload['caseIds'] = exc.case_ids
        return jsonify(payload), exc.status_code


@platform_bp.route('/ai/evaluation-runs', methods=['GET'])
@jwt_required()
def platform_ai_evaluation_runs():
    from services.assistant_core.evaluation import latest_runs

    return jsonify(latest_runs(
        limit=request.args.get('limit', default=50, type=int) or 50,
        case_id=(request.args.get('caseId') or '').strip() or None,
    ))


@platform_bp.route('/ai/evaluation-runs/<run_id>', methods=['GET'])
@jwt_required()
def platform_ai_evaluation_run_detail(run_id):
    from services.assistant_core.evaluation import run_detail

    detail = run_detail(run_id)
    if not detail:
        return jsonify({'error': '评估记录不存在'}), 404
    return jsonify(detail)


@platform_bp.route('/ai/evaluation-runs', methods=['POST'])
@jwt_required()
def platform_ai_evaluation_run_create():
    from services.assistant_core.evaluation import run_case, run_suite
    from services.assistant_core.evaluation_safety import (
        EvaluationSafetyError,
        resolve_evaluation_run_user,
    )

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({
            'error': '评估请求体必须是 JSON 对象',
            'code': 'AI_EVALUATION_PAYLOAD_INVALID',
        }), 400
    client_context = dict(data.get('clientContext') or {}) if isinstance(data.get('clientContext'), dict) else {}
    client_context['source'] = 'platform_ai_evaluation'
    try:
        if 'mode' in data and (
            not isinstance(data['mode'], str)
            or data['mode'] != 'read_only'
        ):
            raise EvaluationSafetyError(
                'AI_EVALUATION_PAYLOAD_INVALID',
                'mode 仅支持 read_only',
            )
        if 'caseIds' in data:
            case_ids_payload = data.get('caseIds')
            if (
                not isinstance(case_ids_payload, list)
                or not case_ids_payload
                or any(not isinstance(case_id, str) or not case_id.strip() for case_id in case_ids_payload)
            ):
                raise EvaluationSafetyError(
                    'AI_EVALUATION_CASE_INVALID',
                    'caseIds 必须是非空字符串数组',
                )
            if 'caseId' in data:
                raise EvaluationSafetyError(
                    'AI_EVALUATION_CASE_INVALID',
                    'caseId 与 caseIds 不能同时提交',
                )
        elif 'caseId' in data:
            case_id_payload = data.get('caseId')
            if not isinstance(case_id_payload, str) or not case_id_payload.strip():
                raise EvaluationSafetyError(
                    'AI_EVALUATION_CASE_INVALID',
                    'caseId 必须是非空字符串',
                )
        tenant_id = data.get('tenantId')
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise EvaluationSafetyError(
                'AI_EVALUATION_TENANT_REQUIRED',
                '必须显式指定评估目标企业',
            )
        tenant_id = tenant_id.strip()
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None:
            raise EvaluationSafetyError(
                'AI_EVALUATION_TENANT_INVALID',
                '评估目标企业不存在',
            )

        requested_by_user_id = get_jwt_identity()
        run_user_fields = {}
        if 'runAsUserId' in data:
            run_user_fields['run_as_user_id'] = data['runAsUserId']
        if 'runAsUserEmail' in data:
            run_user_fields['run_as_user_email'] = data['runAsUserEmail']
        run_user = resolve_evaluation_run_user(tenant=tenant, **run_user_fields)
        allow_writes = False if data.get('mode') == 'read_only' else data.get('allowWrites')

        if 'caseId' in data:
            result = run_case(
                case_id=data['caseId'].strip(),
                user_id=requested_by_user_id,
                run_user_id=run_user.id,
                tenant=tenant,
                allow_writes=allow_writes,
                client_context=client_context,
                retest_of=data.get('retestOf'),
            )
            return jsonify(result)
        return jsonify(run_suite(
            user_id=requested_by_user_id,
            run_user_id=run_user.id,
            tenant=tenant,
            allow_writes=allow_writes,
            case_ids=data.get('caseIds') if isinstance(data.get('caseIds'), list) else None,
            limit=data.get('limit', 8),
            client_context=client_context,
        ))
    except EvaluationSafetyError as exc:
        payload = {'error': str(exc), 'code': exc.code}
        if exc.case_ids:
            payload['caseIds'] = exc.case_ids
        return jsonify(payload), exc.status_code


@platform_bp.route('/plans', methods=['GET'])
@jwt_required()
def list_plans():
    plans = Plan.query.order_by(Plan.code.asc()).all()
    return jsonify([plan.to_dict() for plan in plans])


@platform_bp.route('/plans', methods=['POST'])
@jwt_required()
def create_plan():
    data = request.get_json(silent=True) or {}
    code = normalize_slug(data.get('code'), default='')
    name = (data.get('name') or '').strip()
    if not code or not name:
        return jsonify({'error': '套餐编码和名称不能为空'}), 400
    if Plan.query.get(code):
        return jsonify({'error': '套餐编码已存在'}), 409

    plan = Plan(
        code=code,
        name=name,
        enabled_modules_json=data.get('enabledModules') or list(SAAS_MODULE_KEYS),
        limits_json=data.get('limits') or {},
        is_active=bool(data.get('isActive', True)),
    )
    db.session.add(plan)
    _platform_log('create_plan', target_type='plan', target_id=plan.code, detail={'name': name})
    db.session.commit()
    return jsonify(plan.to_dict()), 201


@platform_bp.route('/plans/<code>', methods=['PUT'])
@jwt_required()
def update_plan(code):
    plan = db.session.get(Plan, code)
    if not plan:
        return jsonify({'error': '套餐不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        plan.name = (data.get('name') or plan.name).strip()
    if isinstance(data.get('enabledModules'), list):
        plan.enabled_modules_json = data.get('enabledModules')
    if isinstance(data.get('limits'), dict):
        plan.limits_json = data.get('limits') or {}
    if 'isActive' in data:
        plan.is_active = bool(data.get('isActive'))
    plan.updated_at = datetime.utcnow()
    _platform_log('update_plan', target_type='plan', target_id=plan.code, detail=data)
    db.session.commit()
    return jsonify(plan.to_dict())


@platform_bp.route('/tenants', methods=['GET'])
@jwt_required()
def list_tenants():
    query = Tenant.query
    status = request.args.get('status')
    keyword = (request.args.get('keyword') or '').strip()
    if status:
        query = query.filter(Tenant.status == status)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(Tenant.name.like(like), Tenant.slug.like(like)))
    page = _bounded_positive_int(
        request.args.get('page'),
        default=1,
        maximum=MAX_PLATFORM_TENANT_PAGE,
    )
    page_size = _bounded_positive_int(
        request.args.get('pageSize'),
        default=MAX_PLATFORM_TENANT_PAGE_SIZE,
        maximum=MAX_PLATFORM_TENANT_PAGE_SIZE,
    )
    tenants = query.order_by(
        Tenant.created_at.desc(),
        Tenant.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return jsonify([_tenant_payload(tenant) for tenant in tenants])


@platform_bp.route('/tenants', methods=['POST'])
@jwt_required()
def create_tenant():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    requested_slug = data.get('slug') or data.get('tenantSlug')
    slug = normalize_slug(requested_slug, default='') if requested_slug else next_tenant_slug()
    admin_email = (data.get('adminEmail') or '').strip().lower()
    admin_name = (data.get('adminName') or '企业管理员').strip()
    admin_password = data.get('adminPassword') or _generate_initial_password()
    plan_code = data.get('planCode') or 'enterprise'
    plan = db.session.get(Plan, plan_code) if plan_code else None

    if not name:
        return jsonify({'error': '企业名称不能为空'}), 400
    if not admin_email:
        return jsonify({'error': '企业管理员邮箱不能为空'}), 400
    if Tenant.query.filter_by(slug=slug).first():
        return jsonify({'error': '企业编码已存在'}), 409
    if plan_code and not plan:
        return jsonify({'error': '套餐不存在'}), 404
    limits = plan.limits_json if plan else {}
    tenant = Tenant(
        id=_new_id(),
        name=name,
        slug=slug,
        status=data.get('status') or 'active',
        plan_code=plan_code,
        max_users=_int_or_default(data.get('maxUsers'), limits.get('maxUsers', 50)),
        max_employees=_int_or_default(data.get('maxEmployees'), limits.get('maxEmployees', 500)),
        max_storage_mb=_int_or_default(data.get('maxStorageMb'), limits.get('maxStorageMb', 10240)),
        ai_monthly_quota=_int_or_default(data.get('aiMonthlyQuota'), limits.get('aiMonthlyQuota', 1000)),
        expires_at=_parse_datetime(data.get('expiresAt')),
        settings_json=data.get('settings') if isinstance(data.get('settings'), dict) else {},
    )
    db.session.add(tenant)
    db.session.flush()

    db.session.add(TenantSubscription(
        id=_new_id(),
        tenant_id=tenant.id,
        plan_code=plan_code,
        status='active',
        starts_at=datetime.utcnow(),
        ends_at=tenant.expires_at,
        notes=data.get('subscriptionNotes'),
    ))
    _sync_modules(tenant.id, _module_payload_map(data, plan))

    password_hash = bcrypt.hashpw(str(admin_password).encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    admin = User(
        id=_new_id(),
        email=admin_email,
        password_hash=password_hash,
        name=admin_name,
        role='admin',
        status='active',
        must_change_password=True,
        tenant_id=tenant.id,
    )
    db.session.add(admin)
    _platform_log('create_tenant', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail={
        'slug': tenant.slug,
        'planCode': plan_code,
        'adminEmail': admin_email,
    })
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': '企业创建失败，企业编码或管理员邮箱与当前数据库唯一约束冲突',
            'code': 'TENANT_CREATE_CONFLICT',
        }), 409
    payload = _tenant_payload(tenant, include_detail=True)
    payload['admin'] = admin.to_dict()
    payload['initialPassword'] = admin_password
    return jsonify(payload), 201


@platform_bp.route('/tenants/<tenant_id>', methods=['GET'])
@jwt_required()
def get_tenant(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    return jsonify(_tenant_payload(tenant, include_detail=True))


@platform_bp.route('/tenants/<tenant_id>/onboarding-checklist', methods=['GET'])
@jwt_required()
def tenant_onboarding_checklist(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    from services.tenant_onboarding import ensure_onboarding_items
    rows = ensure_onboarding_items(tenant.id)
    db.session.commit()
    return jsonify({'tenantId': tenant.id, 'items': [row.to_dict() for row in rows]})


@platform_bp.route('/tenants/<tenant_id>/onboarding-checklist/<item_key>', methods=['PUT'])
@jwt_required()
def update_tenant_onboarding_item(tenant_id, item_key):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    status = data.get('status') or 'pending'
    if status not in ('pending', 'in_progress', 'done', 'blocked'):
        return jsonify({'error': '无效状态'}), 400
    from services.tenant_onboarding import update_onboarding_item
    row = update_onboarding_item(tenant.id, item_key, status, data.get('note') or '')
    if not row:
        return jsonify({'error': '清单项不存在'}), 404
    _platform_log('update_onboarding_checklist', tenant_id=tenant.id, target_type='tenant_onboarding_item', target_id=row.id, detail=data)
    db.session.commit()
    return jsonify(row.to_dict())


@platform_bp.route('/tenants/<tenant_id>/data-inventory', methods=['GET'])
@jwt_required()
def get_tenant_data_inventory(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    include_empty = str(request.args.get('includeEmpty') or '').lower() in {'1', 'true', 'yes'}
    inventory = tenant_data_inventory(tenant.id, include_empty=include_empty)
    _platform_log('tenant_data_inventory', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail={
        'includeEmpty': include_empty,
        'tableCount': inventory['tableCount'],
        'totalRows': inventory['totalRows'],
    })
    db.session.commit()
    return jsonify(inventory)


@platform_bp.route('/tenants/<tenant_id>/structured-export', methods=['POST'])
@jwt_required()
def create_tenant_structured_export(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    include_empty = bool(data.get('includeEmpty', False))
    max_rows_per_table = _int_or_default(data.get('maxRowsPerTable'), 1000)
    package = tenant_structured_export(
        tenant.id,
        include_empty=include_empty,
        max_rows_per_table=max_rows_per_table,
    )
    _platform_log('tenant_structured_export', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail={
        'format': package['format'],
        'includeEmpty': include_empty,
        'maxRowsPerTable': package['maxRowsPerTable'],
        'tableCount': package['tableCount'],
        'totalRows': package['totalRows'],
        'exportedRows': package['exportedRows'],
        'truncatedTables': package['truncatedTables'],
    })
    db.session.commit()
    return jsonify(package)


@platform_bp.route('/tenants/<tenant_id>/deletion-plan', methods=['POST'])
@jwt_required()
def create_tenant_deletion_plan(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'delete').strip().lower()
    if mode not in {'delete', 'anonymize'}:
        return jsonify({'error': '删除计划模式仅支持 delete 或 anonymize'}), 400
    plan = tenant_deletion_plan(
        tenant.id,
        tenant_slug=tenant.slug,
        mode=mode,
        include_empty=bool(data.get('includeEmpty', False)),
    )
    _platform_log('tenant_deletion_plan', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail={
        'mode': plan['mode'],
        'tableCount': plan['tableCount'],
        'totalRows': plan['totalRows'],
        'confirmationPhrase': plan['confirmationPhrase'],
    })
    db.session.commit()
    return jsonify(plan)


@platform_bp.route('/tenants/<tenant_id>/data-requests', methods=['GET'])
@jwt_required()
def list_tenant_data_requests(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    rows = list_data_requests(tenant.id)
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/tenants/<tenant_id>/data-requests', methods=['POST'])
@jwt_required()
def create_tenant_data_request(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    try:
        row = create_data_request(
            tenant.id,
            request_type=data.get('requestType'),
            requester=data.get('requester'),
            scope=data.get('scope'),
            evidence_ref=data.get('evidenceRef') or '',
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    _platform_log(
        'create_tenant_data_request',
        tenant_id=tenant.id,
        target_type='tenant_data_request',
        target_id=row.id,
        detail=_data_request_create_log_detail(data, row),
    )
    db.session.commit()
    return jsonify(row.to_dict()), 201


@platform_bp.route('/tenants/<tenant_id>/data-requests/<request_id>', methods=['PUT'])
@jwt_required()
def update_tenant_data_request(tenant_id, request_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    try:
        row = update_data_request(
            tenant.id,
            request_id,
            status=data.get('status') if 'status' in data else None,
            evidence_ref=data.get('evidenceRef') if 'evidenceRef' in data else None,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not row:
        return jsonify({'error': '数据请求不存在'}), 404
    _platform_log(
        'update_tenant_data_request',
        tenant_id=tenant.id,
        target_type='tenant_data_request',
        target_id=row.id,
        detail=_data_request_update_log_detail(data),
    )
    db.session.commit()
    return jsonify(row.to_dict())


@platform_bp.route('/tenants/<tenant_id>/orders', methods=['GET'])
@jwt_required()
def list_tenant_orders(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    rows = (
        TenantOrder.query
        .filter_by(tenant_id=tenant.id)
        .order_by(TenantOrder.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/tenants/<tenant_id>/invoices', methods=['GET'])
@jwt_required()
def list_tenant_invoices(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    rows = (
        TenantInvoice.query
        .filter_by(tenant_id=tenant.id)
        .order_by(TenantInvoice.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/tenants/<tenant_id>/billing-events', methods=['GET'])
@jwt_required()
def list_tenant_billing_events(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    rows = list_billing_events(tenant.id)
    return jsonify([row.to_dict() for row in rows])


@platform_bp.route('/tenants/<tenant_id>/billing-events', methods=['POST'])
@jwt_required()
def create_tenant_billing_event(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    try:
        row = create_billing_event(
            tenant.id,
            event_type=data.get('eventType'),
            note=data.get('note'),
            operator_id=get_jwt_identity(),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    _platform_log(
        'create_billing_event',
        tenant_id=tenant.id,
        target_type='tenant_billing_event',
        target_id=row.id,
        detail=_billing_event_log_detail(data, row),
    )
    db.session.commit()
    return jsonify(row.to_dict()), 201


@platform_bp.route('/tenants/<tenant_id>/invoices/<invoice_id>', methods=['PUT'])
@jwt_required()
def update_tenant_invoice(tenant_id, invoice_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    invoice = TenantInvoice.query.filter_by(id=invoice_id, tenant_id=tenant.id).first()
    if not invoice:
        return jsonify({'error': '发票记录不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'status' in data:
        invoice.status = data.get('status') or invoice.status
        if invoice.status == 'issued' and not invoice.issued_at:
            invoice.issued_at = datetime.utcnow()
    if 'title' in data:
        invoice.title = (data.get('title') or invoice.title).strip()
    if 'taxNo' in data:
        invoice.tax_no = (data.get('taxNo') or '').strip() or None
    _platform_log('update_invoice', tenant_id=tenant.id, target_type='invoice', target_id=invoice.id, detail=data)
    db.session.commit()
    return jsonify(invoice.to_dict())


@platform_bp.route('/tenants/<tenant_id>', methods=['PUT'])
@jwt_required()
def update_tenant(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    try:
        command = TenantUpdateCommand.from_payload(data)
    except PlatformTenantValidationError as exc:
        return jsonify({
            'error': exc.message,
            'code': exc.code,
            'field': exc.field,
        }), 400

    if 'planCode' in command.provided_fields:
        plan_code = command.values['planCode']
        if not db.session.get(Plan, plan_code):
            return jsonify({'error': '套餐不存在', 'code': 'PLAN_NOT_FOUND'}), 404

    subscription = _latest_subscription(tenant.id)
    command.apply(tenant, subscription)
    _platform_log(
        'update_tenant',
        tenant_id=tenant.id,
        target_type='tenant',
        target_id=tenant.id,
        detail=command.audit_detail(),
    )
    db.session.commit()
    return jsonify(_tenant_payload(tenant, include_detail=True))


@platform_bp.route('/tenants/<tenant_id>/modules', methods=['PUT'])
@jwt_required()
def update_tenant_modules(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    data = request.get_json(silent=True) or {}
    plan = db.session.get(Plan, tenant.plan_code) if tenant.plan_code else None
    _sync_modules(tenant.id, _module_payload_map(data, plan))
    _platform_log('update_tenant_modules', tenant_id=tenant.id, target_type='tenant', target_id=tenant.id, detail=data)
    db.session.commit()
    return jsonify({'modules': [module.to_dict() for module in _modules_for_tenant(tenant.id)]})


@platform_bp.route('/tenants/<tenant_id>/reset-admin-password', methods=['POST'])
@jwt_required()
def reset_tenant_admin_password(tenant_id):
    request_id = _platform_request_id()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}

    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        _record_reset_failure(
            tenant_id=None,
            target_id=None,
            request_id=request_id,
            error_code='TENANT_NOT_FOUND',
            detail=_reset_failure_detail(data, tenant_resolved=False),
        )
        return jsonify({
            'error': '企业不存在',
            'code': 'TENANT_NOT_FOUND',
            'requestId': request_id,
        }), 404

    try:
        credential = execute_reset_tenant_admin_password(
            tenant,
            user_id=data.get('userId'),
            confirmation=data.get('confirmation'),
        )
        # Materialize the scalar response while the target is still attached.
        # SQLAlchemy expires ORM attributes on commit; serializing the model
        # after commit could otherwise perform a second SELECT and lose the
        # only copy of the one-time credential if that SELECT fails.
        response_payload = {
            'user': credential.user.to_dict(),
            'initialPassword': credential.password,
            'requestId': request_id,
        }
        # The user mutation and this success audit are intentionally flushed by
        # one commit.  The plaintext credential is returned only in this
        # response and is never copied into the audit detail.
        _platform_log(
            'reset_admin_password',
            tenant_id=tenant.id,
            target_type='user',
            target_id=credential.user.id,
            detail={'credentialType': 'one_time', 'mustChangePassword': True},
            result='success',
            request_id=request_id,
        )
        db.session.commit()
    except PlatformCommandError as exc:
        _record_reset_failure(
            tenant_id=tenant.id,
            target_id=_reset_failure_target_id(data.get('userId')),
            request_id=request_id,
            error_code=exc.code,
            detail=_reset_failure_detail(data, tenant_resolved=True),
        )
        return jsonify({'error': exc.message, 'code': exc.code, 'requestId': request_id}), exc.status_code
    except Exception:
        # Do not expose database/bcrypt exception text or accidentally return a
        # credential after a partial transaction failure.
        _record_reset_failure(
            tenant_id=tenant.id,
            target_id=_reset_failure_target_id(data.get('userId')),
            request_id=request_id,
            error_code='ADMIN_PASSWORD_RESET_FAILED',
            detail=_reset_failure_detail(data, tenant_resolved=True),
        )
        return jsonify({
            'error': '管理员密码重置失败，请稍后重试',
            'code': 'ADMIN_PASSWORD_RESET_FAILED',
            'requestId': request_id,
        }), 500

    return jsonify(response_payload)


@platform_bp.route('/tenants/<tenant_id>/diagnostics', methods=['GET'])
@jwt_required()
def tenant_diagnostics(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({'error': '企业不存在'}), 404
    usage = tenant_usage(tenant.id)

    disk = None
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    if upload_folder:
        try:
            total, used, free = shutil.disk_usage(upload_folder)
            disk = {
                'totalMb': round(total / 1024 / 1024, 2),
                'usedMb': round(used / 1024 / 1024, 2),
                'freeMb': round(free / 1024 / 1024, 2),
            }
        except OSError:
            disk = None

    recent_logs = (
        PlatformOperationLog.query
        .filter_by(tenant_id=tenant.id)
        .order_by(PlatformOperationLog.created_at.desc())
        .limit(20)
        .all()
    )
    return jsonify({
        'tenant': _tenant_payload(tenant, include_detail=True, measured_usage=usage),
        'usage': usage,
        'disk': disk,
        'recentPlatformLogs': [log.to_dict() for log in recent_logs],
        'checkedAt': datetime.utcnow().isoformat() + 'Z',
    })


@platform_bp.route('/operation-logs', methods=['GET'])
@jwt_required()
def list_platform_logs():
    query = PlatformOperationLog.query
    tenant_id = request.args.get('tenantId')
    action = request.args.get('action')
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    if action:
        query = query.filter_by(action=action)
    logs = query.order_by(PlatformOperationLog.created_at.desc()).limit(500).all()
    return jsonify([log.to_dict() for log in logs])
