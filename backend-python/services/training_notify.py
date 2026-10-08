"""培训通知发送辅助函数。

在关键培训行为发生时调用，给员工档案发站内通知。
复用 HRM 已有 Notification 表；后台通知走 user_id，员工门户通知走 employee_id。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from models import db, Employee, EmployeePortalAccount, Notification, User

logger = logging.getLogger('hengpintong.training_notify')


def _legacy_user_id(employee_id: str) -> Optional[str]:
    """旧版兼容：通过 employee_id 找到绑定的 HRM user_id。"""
    # 有门户账号时，员工端按 employee_id 收通知，不再需要后台 user_id。
    account = EmployeePortalAccount.query.filter_by(employee_id=employee_id).first()
    if account:
        return None
    u = User.query.filter_by(employee_id=employee_id).first()
    return u.id if u else None


def notify_employee(employee_id: str, title: str, content: str,
                    notice_type: str = 'training', link_url: str = None) -> bool:
    """给某员工发站内通知。"""
    employee = db.session.get(Employee, employee_id)
    if not employee:
        logger.info('notify_skip_missing_employee', extra={'employee': employee_id})
        return False
    has_portal_account = EmployeePortalAccount.query.filter_by(employee_id=employee_id).first() is not None
    user_id = _legacy_user_id(employee_id)
    if not has_portal_account and not user_id:
        logger.info('notify_skip_no_account', extra={'employee': employee_id})
        return False
    existing = Notification.query.filter_by(
        employee_id=employee_id,
        user_id=user_id,
        title=title[:200],
        notice_type=notice_type,
        link_url=link_url,
    ).first()
    if existing:
        return True
    n = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        employee_id=employee_id,
        tenant_id=employee.tenant_id,
        title=title[:200],
        content=content,
        notice_type=notice_type,
        status='unread',
        link_url=link_url,
    )
    db.session.add(n)
    return True


def notify_many(employee_ids: list, title: str, content: str,
                notice_type: str = 'training', link_url: str = None) -> int:
    """批量通知多个员工。返回成功发送数。"""
    count = 0
    for eid in employee_ids:
        if notify_employee(eid, title, content, notice_type, link_url):
            count += 1
    return count
