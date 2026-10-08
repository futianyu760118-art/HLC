"""Employee portal account helpers.

The HRM backend users table is for management-side access. Employee portal
accounts are separate and map one-to-one to employee records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import bcrypt

from models import Employee, EmployeePortalAccount, db


DEFAULT_PORTAL_PASSWORD = 'hj@123'
ACTIVE_EMPLOYEE_STATUSES = {'active', 'probation', 'pending_onboard'}


def password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def portal_status_for_employee(employee: Employee) -> str:
    return 'active' if (employee.status or 'active') in ACTIVE_EMPLOYEE_STATUSES else 'inactive'


def ensure_employee_portal_account(
    employee: Employee,
    *,
    initial_password: str | None = DEFAULT_PORTAL_PASSWORD,
    reset_password: bool = False,
    require_password_change: bool = True,
) -> EmployeePortalAccount:
    account = EmployeePortalAccount.query.filter_by(employee_id=employee.id).first()
    if not account:
        account = EmployeePortalAccount(id=str(uuid.uuid4()), employee_id=employee.id)
        db.session.add(account)
        reset_password = True

    if getattr(employee, 'tenant_id', None):
        account.tenant_id = employee.tenant_id
    account.status = portal_status_for_employee(employee)
    account.updated_at = datetime.utcnow()

    if reset_password:
        password = initial_password or DEFAULT_PORTAL_PASSWORD
        account.password_hash = password_hash(password)
        account.must_change_password = require_password_change
    elif not account.password_hash:
        password = initial_password or DEFAULT_PORTAL_PASSWORD
        account.password_hash = password_hash(password)
        account.must_change_password = require_password_change

    return account
