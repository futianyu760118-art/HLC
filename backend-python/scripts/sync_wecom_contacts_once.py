"""One-time import of WeCom contacts into HRM departments, employees, and users.

Default mode is a dry run. Set WeCom credentials through environment variables
and pass ``--apply`` to write changes.

Required environment variables:
  WECOM_CORP_ID
  WECOM_CONTACT_SECRET  (or WECOM_CORP_SECRET)

Optional:
  WECOM_ROOT_DEPARTMENT_ID       default: 1
  WECOM_DEFAULT_ROLE             default: employee
  WECOM_DEFAULT_PASSWORD         default: random unusable password per new user
  WECOM_SYNTHETIC_EMAIL_DOMAIN   default: wecom.local
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import bcrypt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT.parent / '.env')
os.environ.setdefault('DISABLE_STUDY_REMINDER_SCHEDULER', '1')

from app import create_app  # noqa: E402
from models import Department, Employee, EmployeePortalAccount, User, db  # noqa: E402
from services.employee_portal_accounts import ensure_employee_portal_account  # noqa: E402


API_BASE = 'https://qyapi.weixin.qq.com/cgi-bin'
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'hengpintong:wecom')


def _required_env(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def _stable_id(kind: str, source_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f'{kind}:{source_id}'))


def _employee_no(userid: str) -> str:
    raw = f'WX-{userid}'
    if len(raw) <= 50:
        return raw
    digest = hashlib.sha1(userid.encode('utf-8')).hexdigest()[:16]
    return f'WX-{digest}'


def _status(value) -> str:
    # WeCom user status: 1=activated, 2=disabled, 4=not activated.
    return 'active' if str(value or '1') == '1' else 'inactive'


def _gender(value) -> str | None:
    return {'1': '男', '2': '女', '0': '其他'}.get(str(value or ''), None)


def _json_get(path: str, params: dict[str, object]) -> dict:
    url = f'{API_BASE}{path}?{urlencode(params)}'
    with urlopen(url, timeout=20) as response:  # nosec B310 - fixed WeCom API host
        payload = json.loads(response.read().decode('utf-8'))
    if payload.get('errcode') not in (0, None):
        raise RuntimeError(
            f'WeCom API error {payload.get("errcode")}: {payload.get("errmsg")}'
        )
    return payload


def _fetch_token(corp_id: str, secret: str) -> str:
    payload = _json_get('/gettoken', {'corpid': corp_id, 'corpsecret': secret})
    token = payload.get('access_token')
    if not token:
        raise RuntimeError('WeCom token response did not include access_token')
    return token


def _fetch_departments(token: str, root_department_id: int) -> list[dict]:
    payload = _json_get(
        '/department/list',
        {'access_token': token, 'id': root_department_id},
    )
    departments = payload.get('department') or []
    return sorted(departments, key=lambda item: (item.get('parentid') or 0, item.get('order') or 0, item.get('id') or 0))


def _fetch_users(token: str, department_ids: list[int]) -> list[dict]:
    users_by_id: dict[str, dict] = {}
    for department_id in department_ids:
        payload = _json_get(
            '/user/list',
            {
                'access_token': token,
                'department_id': department_id,
                'fetch_child': 0,
            },
        )
        for user in payload.get('userlist') or []:
            userid = str(user.get('userid') or '').strip()
            if not userid:
                continue
            existing = users_by_id.get(userid)
            if existing:
                merged_departments = set(existing.get('department') or [])
                merged_departments.update(user.get('department') or [])
                existing['department'] = list(merged_departments)
                continue
            users_by_id[userid] = user
    return list(users_by_id.values())


def _primary_department_id(user: dict) -> str | None:
    main_department = user.get('main_department')
    if main_department:
        return str(main_department)
    departments = user.get('department') or []
    return str(departments[0]) if departments else None


def _email_for_user(user: dict, synthetic_domain: str) -> str:
    email = (user.get('email') or user.get('biz_mail') or '').strip().lower()
    if email:
        return email
    userid = str(user.get('userid') or '').strip().lower()
    safe_userid = ''.join(ch if ch.isalnum() or ch in '._-' else '-' for ch in userid)
    return f'{safe_userid}@{synthetic_domain}'


def _password_hash(default_password: str | None) -> str:
    password = default_password or secrets.token_urlsafe(48)
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _department_by_wecom_id(wecom_dept_id: str) -> Department | None:
    dept_id = _stable_id('department', wecom_dept_id)
    return db.session.get(Department, dept_id) or Department.query.filter_by(
        code=f'wecom:{wecom_dept_id}'
    ).first()


def _employee_by_wecom_user(user: dict, email: str) -> Employee | None:
    userid = str(user.get('userid') or '')
    employee_id = _stable_id('employee', userid)
    employee_no = _employee_no(userid)
    return (
        db.session.get(Employee, employee_id)
        or Employee.query.filter_by(employee_no=employee_no).first()
        or (Employee.query.filter_by(email=email).first() if email else None)
    )


def _user_by_wecom_user(user: dict, email: str) -> User | None:
    userid = str(user.get('userid') or '')
    return db.session.get(User, _stable_id('user', userid)) or User.query.filter_by(
        email=email
    ).first()


def sync_contacts(*, apply: bool, create_users: bool) -> dict[str, int]:
    corp_id = _required_env('WECOM_CORP_ID')
    secret = (os.getenv('WECOM_CONTACT_SECRET') or os.getenv('WECOM_CORP_SECRET') or '').strip()
    if not secret:
        raise RuntimeError('Missing WECOM_CONTACT_SECRET or WECOM_CORP_SECRET')

    root_department_id = int(os.getenv('WECOM_ROOT_DEPARTMENT_ID', '1'))
    default_role = os.getenv('WECOM_DEFAULT_ROLE', 'employee').strip() or 'employee'
    default_password = os.getenv('WECOM_DEFAULT_PASSWORD')
    synthetic_domain = os.getenv('WECOM_SYNTHETIC_EMAIL_DOMAIN', 'wecom.local').strip() or 'wecom.local'

    token = _fetch_token(corp_id, secret)
    departments = _fetch_departments(token, root_department_id)
    users = _fetch_users(token, [int(item['id']) for item in departments if item.get('id') is not None])

    stats = {
        'wecom_departments': len(departments),
        'wecom_users': len(users),
        'departments_created': 0,
        'departments_updated': 0,
        'employees_created': 0,
        'employees_updated': 0,
        'users_created': 0,
        'users_updated': 0,
        'portal_accounts_created': 0,
        'portal_accounts_updated': 0,
        'manager_links_updated': 0,
    }

    dept_id_map: dict[str, str] = {}
    employee_id_by_userid: dict[str, str] = {}

    # Pass 1: create/update departments without parent links.
    for item in departments:
        wecom_dept_id = str(item.get('id'))
        dept = _department_by_wecom_id(wecom_dept_id)
        if dept:
            stats['departments_updated'] += 1
        else:
            dept = Department(id=_stable_id('department', wecom_dept_id), code=f'wecom:{wecom_dept_id}')
            db.session.add(dept)
            stats['departments_created'] += 1
        dept.name = item.get('name') or f'企业微信部门 {wecom_dept_id}'
        dept.code = dept.code or f'wecom:{wecom_dept_id}'
        dept.status = 'active'
        dept.description = '企业微信通讯录一次性同步'
        dept_id_map[wecom_dept_id] = dept.id
    db.session.flush()

    # Pass 2: parent and department leader links.
    department_leaders: dict[str, str] = {}
    for item in departments:
        wecom_dept_id = str(item.get('id'))
        dept = db.session.get(Department, dept_id_map[wecom_dept_id])
        parent_id = str(item.get('parentid') or '')
        dept.parent_id = dept_id_map.get(parent_id)
        leaders = item.get('department_leader') or []
        if leaders:
            department_leaders[wecom_dept_id] = str(leaders[0])

    for item in users:
        userid = str(item.get('userid') or '').strip()
        if not userid:
            continue
        email = _email_for_user(item, synthetic_domain)
        primary_dept = _primary_department_id(item)
        local_dept_id = dept_id_map.get(primary_dept or '')
        employee = _employee_by_wecom_user(item, email)
        if employee:
            stats['employees_updated'] += 1
        else:
            employee = Employee(id=_stable_id('employee', userid), employee_no=_employee_no(userid))
            db.session.add(employee)
            stats['employees_created'] += 1
        employee.name = item.get('name') or userid
        employee.employee_no = employee.employee_no or _employee_no(userid)
        employee.email = email
        employee.phone = item.get('mobile') or item.get('telephone') or employee.phone
        employee.gender = _gender(item.get('gender')) or employee.gender
        employee.status = _status(item.get('status'))
        employee.department_id = local_dept_id
        employee.job_title = item.get('position') or employee.job_title
        employee.remark = employee.remark or f'企业微信同步 userid={userid}'
        employee.updated_at = datetime.utcnow()
        employee_id_by_userid[userid] = employee.id

        had_portal_account = EmployeePortalAccount.query.filter_by(employee_id=employee.id).first() is not None
        ensure_employee_portal_account(
            employee,
            initial_password=default_password,
            reset_password=not had_portal_account,
            require_password_change=True,
        )
        stats['portal_accounts_updated' if had_portal_account else 'portal_accounts_created'] += 1

        if create_users:
            account = _user_by_wecom_user(item, email)
            if account:
                stats['users_updated'] += 1
            else:
                account = User(
                    id=_stable_id('user', userid),
                    email=email,
                    password_hash=_password_hash(default_password),
                    must_change_password=True,
                    role=default_role,
                )
                db.session.add(account)
                stats['users_created'] += 1
            account.name = item.get('name') or userid
            account.phone = item.get('mobile') or item.get('telephone') or account.phone
            account.status = _status(item.get('status'))
            account.department_id = local_dept_id
            account.employee_id = employee.id
            account.updated_at = datetime.utcnow()

    db.session.flush()

    for item in users:
        userid = str(item.get('userid') or '').strip()
        employee_id = employee_id_by_userid.get(userid)
        if not employee_id:
            continue
        employee = db.session.get(Employee, employee_id)
        leaders = item.get('direct_leader') or []
        manager_id = employee_id_by_userid.get(str(leaders[0])) if leaders else None
        if manager_id and employee.manager_id != manager_id:
            employee.manager_id = manager_id
            stats['manager_links_updated'] += 1

    for wecom_dept_id, leader_userid in department_leaders.items():
        dept = db.session.get(Department, dept_id_map[wecom_dept_id])
        manager_id = employee_id_by_userid.get(leader_userid)
        if dept and manager_id:
            dept.manager_id = manager_id

    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description='One-time sync WeCom contacts into HRM')
    parser.add_argument('--apply', action='store_true', help='write to database; default is dry-run')
    parser.add_argument('--no-create-users', action='store_true', help='only sync departments/employees')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        stats = sync_contacts(apply=args.apply, create_users=not args.no_create_users)

    print(f'mode={"APPLY" if args.apply else "DRY-RUN"}')
    for key in sorted(stats):
        print(f'{key}={stats[key]}')
    if not args.apply:
        print('dry_run=true; pass --apply to write changes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
