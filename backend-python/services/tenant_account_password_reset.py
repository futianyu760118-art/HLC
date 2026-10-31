"""Tenant-scoped one-time password reset commands.

These commands mutate attached account models without committing. Route
handlers own the transaction so the credential change and audit row remain
atomic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Union

import bcrypt

from models import Employee, EmployeePortalAccount, User
from services.employee_portal_accounts import ACTIVE_EMPLOYEE_STATUSES
from services.platform_tenant_commands import generate_one_time_password


Account = Union[User, EmployeePortalAccount]


class TenantAccountNotFound(LookupError):
    """Stable unavailable-target signal that carries no enumeration detail."""


@dataclass(frozen=True)
class ResetCredential:
    account: Account
    password: str
    account_type: str


def _validated_identifier(value: str) -> str:
    normalized = str(value)
    try:
        normalized.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise TenantAccountNotFound from exc
    return normalized


def _reset(account: Account, account_type: str) -> ResetCredential:
    password = generate_one_time_password()
    account.password_hash = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(),
    ).decode('utf-8')
    account.must_change_password = True
    account.updated_at = datetime.utcnow()
    return ResetCredential(
        account=account,
        password=password,
        account_type=account_type,
    )


def reset_management_password(*, tenant_id: str, user_id: str) -> ResetCredential:
    """Reset one active management account in the explicit tenant."""

    target = User.query.filter_by(
        id=_validated_identifier(user_id),
        tenant_id=tenant_id,
        status='active',
    ).first()
    if target is None:
        raise TenantAccountNotFound
    return _reset(target, 'hrm')


def reset_portal_password(*, tenant_id: str, employee_id: str) -> ResetCredential:
    """Reset the active portal account of one active employee in the tenant."""

    normalized_employee_id = _validated_identifier(employee_id)
    target = (
        EmployeePortalAccount.query
        .join(Employee, EmployeePortalAccount.employee_id == Employee.id)
        .filter(
            EmployeePortalAccount.tenant_id == tenant_id,
            EmployeePortalAccount.status == 'active',
            Employee.id == normalized_employee_id,
            Employee.tenant_id == tenant_id,
            Employee.status.in_(ACTIVE_EMPLOYEE_STATUSES),
        )
        .first()
    )
    if target is None:
        raise TenantAccountNotFound
    return _reset(target, 'employee_portal')
