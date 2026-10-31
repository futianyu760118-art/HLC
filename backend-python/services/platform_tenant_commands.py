"""Validated platform commands for tenant lifecycle and credential operations.

The functions in this module deliberately do not commit the SQLAlchemy session.
Route handlers own the transaction boundary so a high-risk credential change and
its success audit row can be persisted atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
import string
from typing import Any

import bcrypt

from models import Tenant, TenantSubscription, User


TENANT_STATUSES = frozenset({'active', 'inactive', 'suspended', 'expired'})
TENANT_UPDATE_FIELDS = frozenset({
    'name',
    'status',
    'planCode',
    'maxUsers',
    'maxEmployees',
    'maxStorageMb',
    'aiMonthlyQuota',
    'expiresAt',
    'settings',
})


class PlatformTenantValidationError(ValueError):
    """A stable, field-addressable platform command validation error."""

    code = 'PLATFORM_VALIDATION_ERROR'

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


class PlatformCommandError(ValueError):
    """Stable, client-safe error raised by a validated platform command."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ResetCredential:
    """The one-time credential generated for a successful administrator reset."""

    user: User
    password: str


ADMIN_ROLES = frozenset({'admin', 'hr_admin'})
_RESET_PASSWORD_ALPHABET = string.ascii_letters + string.digits + '!@#$%^&*'


def generate_one_time_password(length: int = 24) -> str:
    """Generate a high-entropy password suitable for a one-time handoff.

    A minimum of twenty characters is enforced even if an accidental shorter
    length is supplied by a future caller.  The loop guarantees a mixture of
    character classes without logging or otherwise persisting the plaintext.
    """

    length = max(int(length), 20)
    while True:
        value = ''.join(secrets.choice(_RESET_PASSWORD_ALPHABET) for _ in range(length))
        classes = (
            any(char.islower() for char in value),
            any(char.isupper() for char in value),
            any(char.isdigit() for char in value),
            any(char in '!@#$%^&*' for char in value),
        )
        if sum(classes) >= 3:
            return value


def reset_tenant_admin_password(
    tenant: Tenant,
    *,
    user_id: str | None,
    confirmation: str | None,
) -> ResetCredential:
    """Reset one explicitly selected, active administrator in ``tenant``.

    This command only mutates the target ``User`` in the caller's transaction;
    it never commits and it never accepts a caller-supplied password/email.
    Validation intentionally uses one stable target error for missing,
    cross-tenant, non-admin, and inactive accounts so the endpoint cannot be
    used to enumerate tenant users.
    """

    if not isinstance(user_id, str) or not user_id.strip():
        raise PlatformCommandError('ADMIN_TARGET_REQUIRED', '必须明确指定企业管理员账号', 400)

    normalized_user_id = user_id.strip()
    try:
        # Reject lone surrogates before passing attacker-controlled text to a
        # DB-API driver; some drivers raise UnicodeEncodeError instead of
        # returning an ordinary "not found" result.
        normalized_user_id.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise PlatformCommandError('TARGET_NOT_TENANT_ADMIN', '目标账号不是当前企业的启用管理员', 409) from exc
    target = User.query.filter_by(id=normalized_user_id, tenant_id=tenant.id).first()
    if (
        target is None
        or target.role not in ADMIN_ROLES
        or str(getattr(target, 'status', 'active') or '').lower() != 'active'
    ):
        raise PlatformCommandError('TARGET_NOT_TENANT_ADMIN', '目标账号不是当前企业的启用管理员', 409)

    expected_confirmation = f'RESET {tenant.slug}'
    if not isinstance(confirmation, str) or confirmation != expected_confirmation:
        raise PlatformCommandError('CONFIRMATION_MISMATCH', '确认短语不匹配', 400)

    password = generate_one_time_password()
    target.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    target.must_change_password = True
    target.updated_at = datetime.utcnow()
    return ResetCredential(user=target, password=password)


def _strict_int(field: str, value: Any, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise PlatformTenantValidationError(field, f'{field} 必须是整数')
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PlatformTenantValidationError(field, f'{field} 必须是整数') from exc
    if isinstance(value, float) and not value.is_integer():
        raise PlatformTenantValidationError(field, f'{field} 必须是整数')
    if isinstance(value, str) and value.strip() != str(parsed):
        raise PlatformTenantValidationError(field, f'{field} 必须是整数')
    if parsed < minimum:
        raise PlatformTenantValidationError(field, f'{field} 不能小于 {minimum}')
    return parsed


def _strict_datetime(field: str, value: Any) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError as exc:
            raise PlatformTenantValidationError(field, f'{field} 必须是有效的 ISO 日期时间') from exc
    else:
        raise PlatformTenantValidationError(field, f'{field} 必须是有效的 ISO 日期时间')
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@dataclass(frozen=True)
class TenantUpdateCommand:
    values: dict[str, Any]
    provided_fields: frozenset[str]

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> 'TenantUpdateCommand':
        if not isinstance(data, dict):
            raise PlatformTenantValidationError('body', '请求体必须是 JSON 对象')
        unknown = sorted(set(data) - TENANT_UPDATE_FIELDS)
        if unknown:
            raise PlatformTenantValidationError(unknown[0], f'不支持的企业字段：{unknown[0]}')

        values: dict[str, Any] = {}
        if 'name' in data:
            name = str(data.get('name') or '').strip()
            if not name:
                raise PlatformTenantValidationError('name', '企业名称不能为空')
            if len(name) > 120:
                raise PlatformTenantValidationError('name', '企业名称不能超过 120 个字符')
            values['name'] = name

        if 'status' in data:
            status = str(data.get('status') or '').strip().lower()
            if status not in TENANT_STATUSES:
                raise PlatformTenantValidationError('status', '企业状态不合法')
            values['status'] = status

        if 'planCode' in data:
            plan_code = str(data.get('planCode') or '').strip()
            if not plan_code:
                raise PlatformTenantValidationError('planCode', '套餐编码不能为空')
            values['planCode'] = plan_code

        integer_fields = {
            'maxUsers': 1,
            'maxEmployees': 1,
            'maxStorageMb': 0,
            'aiMonthlyQuota': 0,
        }
        for field, minimum in integer_fields.items():
            if field in data:
                values[field] = _strict_int(field, data.get(field), minimum=minimum)

        if 'expiresAt' in data:
            values['expiresAt'] = _strict_datetime('expiresAt', data.get('expiresAt'))

        if 'settings' in data:
            settings = data.get('settings')
            if not isinstance(settings, dict):
                raise PlatformTenantValidationError('settings', '企业设置必须是 JSON 对象')
            values['settings'] = settings

        return cls(values=values, provided_fields=frozenset(data))

    def apply(self, tenant: Tenant, subscription: TenantSubscription | None) -> None:
        mapping = {
            'name': 'name',
            'status': 'status',
            'planCode': 'plan_code',
            'maxUsers': 'max_users',
            'maxEmployees': 'max_employees',
            'maxStorageMb': 'max_storage_mb',
            'aiMonthlyQuota': 'ai_monthly_quota',
            'expiresAt': 'expires_at',
            'settings': 'settings_json',
        }
        for source, target in mapping.items():
            if source in self.provided_fields:
                setattr(tenant, target, self.values[source])

        updated_at = datetime.utcnow()
        tenant.updated_at = updated_at
        if subscription:
            if 'planCode' in self.provided_fields:
                subscription.plan_code = tenant.plan_code
            if 'expiresAt' in self.provided_fields:
                subscription.ends_at = tenant.expires_at
            if {'planCode', 'expiresAt'} & self.provided_fields:
                subscription.updated_at = updated_at

    def audit_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {'changedFields': sorted(self.provided_fields)}
        for field in ('status', 'planCode', 'maxUsers', 'maxEmployees', 'maxStorageMb', 'aiMonthlyQuota'):
            if field in self.provided_fields:
                detail[field] = self.values[field]
        if 'expiresAt' in self.provided_fields:
            expires_at = self.values['expiresAt']
            detail['expiresAt'] = expires_at.isoformat() + 'Z' if expires_at else None
        if 'settings' in self.provided_fields:
            detail['settingsKeys'] = sorted(self.values['settings'])
        return detail
