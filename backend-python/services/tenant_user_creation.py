"""Validated tenant-local management account creation."""

from __future__ import annotations

from dataclasses import dataclass
import re

import bcrypt
import uuid

from models import Department, Employee, User
from services.authz import ALL_ROLES
from services.platform_tenant_commands import generate_one_time_password


EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
ALLOWED_STATUSES = frozenset({'active', 'inactive'})


class TenantUserCreationError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class CreatedCredential:
    account: User
    password: str


def _optional_id(value) -> str | None:
    normalized = str(value or '').strip()
    return normalized or None


def create_management_account(*, tenant_id: str, data: dict) -> CreatedCredential:
    name = str(data.get('name') or '').strip()
    email = str(data.get('email') or '').strip().lower()
    role = str(data.get('role') or 'recruiter').strip()
    status = str(data.get('status') or 'active').strip()
    phone = str(data.get('phone') or '').strip() or None
    department_id = _optional_id(data.get('departmentId'))
    employee_id = _optional_id(data.get('employeeId'))

    if not name:
        raise TenantUserCreationError('USER_NAME_REQUIRED', '姓名不能为空')
    if len(name) > 100:
        raise TenantUserCreationError('USER_NAME_INVALID', '姓名不能超过100个字符')
    if not EMAIL_RE.fullmatch(email):
        raise TenantUserCreationError('USER_EMAIL_INVALID', '邮箱格式不正确')
    if role not in ALL_ROLES:
        raise TenantUserCreationError('USER_ROLE_INVALID', '用户角色无效')
    if status not in ALLOWED_STATUSES:
        raise TenantUserCreationError('USER_STATUS_INVALID', '用户状态无效')
    if len(phone or '') > 30:
        raise TenantUserCreationError('USER_PHONE_INVALID', '电话号码不能超过30个字符')
    if User.query.filter_by(tenant_id=tenant_id, email=email).first():
        raise TenantUserCreationError('USER_EMAIL_EXISTS', '该邮箱已存在', 409)

    if department_id and not Department.query.filter_by(id=department_id, tenant_id=tenant_id).first():
        raise TenantUserCreationError('USER_DEPARTMENT_INVALID', '所选部门不存在')
    if employee_id and not Employee.query.filter_by(id=employee_id, tenant_id=tenant_id).first():
        raise TenantUserCreationError('USER_EMPLOYEE_INVALID', '所选员工不存在')

    password = generate_one_time_password()
    account = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=email,
        password_hash=bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'),
        name=name,
        role=role,
        phone=phone,
        status=status,
        department_id=department_id,
        employee_id=employee_id,
        must_change_password=True,
    )
    return CreatedCredential(account=account, password=password)
