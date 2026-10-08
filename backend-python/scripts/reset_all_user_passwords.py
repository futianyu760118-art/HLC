"""Reset HRM and employee-portal passwords to the initial password.

Usage:
  python backend-python/scripts/reset_all_user_passwords.py
  python backend-python/scripts/reset_all_user_passwords.py --apply
  python backend-python/scripts/reset_all_user_passwords.py --target portal --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from models import Employee, EmployeePortalAccount, User, db  # noqa: E402
from services.employee_portal_accounts import ensure_employee_portal_account  # noqa: E402


DEFAULT_PASSWORD = 'hj@123'


def reset_passwords(*, apply: bool, password: str, target: str) -> int:
    os.environ.setdefault('DISABLE_STUDY_REMINDER_SCHEDULER', '1')
    app = create_app()
    with app.app_context():
        users = User.query.filter(User.role != 'employee').order_by(User.id.asc()).all()
        employee_role_users = User.query.filter(User.role == 'employee').count()
        employees = Employee.query.order_by(Employee.employee_no.asc(), Employee.name.asc()).all()
        existing_portal = EmployeePortalAccount.query.count()
        print(f'hrm_users_total={len(users)}')
        print(f'hrm_employee_role_users_skipped={employee_role_users}')
        print(f'employees_total={len(employees)}')
        print(f'portal_accounts_existing={existing_portal}')
        print(f'target={target}')

        if not apply:
            print('dry_run=1')
            return 0

        hrm_updated = 0
        portal_updated = 0
        if target in ('hrm', 'both'):
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            for user in users:
                user.password_hash = password_hash
                user.must_change_password = True
                hrm_updated += 1
        if target in ('portal', 'both'):
            for employee in employees:
                ensure_employee_portal_account(
                    employee,
                    initial_password=password,
                    reset_password=True,
                    require_password_change=True,
                )
                portal_updated += 1
        db.session.commit()
        print(f'hrm_users_updated={hrm_updated}')
        print(f'portal_accounts_updated={portal_updated}')
        print(f'portal_accounts_total={EmployeePortalAccount.query.count()}')
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write changes to the database')
    parser.add_argument(
        '--password',
        default=os.getenv('HRM_INITIAL_PASSWORD') or DEFAULT_PASSWORD,
        help='initial password to set for every account',
    )
    parser.add_argument(
        '--target',
        choices=['hrm', 'portal', 'both'],
        default='both',
        help='which account system to reset',
    )
    args = parser.parse_args()
    return reset_passwords(
        apply=args.apply,
        password=args.password,
        target=args.target,
    )


if __name__ == '__main__':
    raise SystemExit(main())
