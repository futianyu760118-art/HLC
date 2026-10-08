from __future__ import annotations

import uuid
from datetime import datetime

from models import TenantOnboardingItem, db


DEFAULT_ONBOARDING_ITEMS = [
    ('admin_first_login', '企业管理员完成首次登录和改密'),
    ('company_profile', '企业基础信息确认'),
    ('modules_confirmed', '开通模块确认'),
    ('first_employee_import', '首批员工档案导入'),
    ('support_contact', '支持联系人确认'),
]


def ensure_onboarding_items(tenant_id: str):
    existing = {
        row.item_key: row
        for row in TenantOnboardingItem.query.filter_by(tenant_id=tenant_id).all()
    }
    for key, label in DEFAULT_ONBOARDING_ITEMS:
        row = existing.get(key)
        if row:
            if not row.label:
                row.label = label
            continue
        db.session.add(TenantOnboardingItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            item_key=key,
            label=label,
            status='pending',
        ))
    db.session.flush()
    return (
        TenantOnboardingItem.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantOnboardingItem.created_at.asc())
        .all()
    )


def update_onboarding_item(tenant_id: str, key: str, status: str, note: str = ''):
    ensure_onboarding_items(tenant_id)
    row = TenantOnboardingItem.query.filter_by(tenant_id=tenant_id, item_key=key).first()
    if not row:
        return None
    row.status = status
    if note:
        row.note = note
    row.updated_at = datetime.utcnow()
    if status == 'done' and not row.completed_at:
        row.completed_at = datetime.utcnow()
    if status != 'done':
        row.completed_at = None
    db.session.flush()
    return row
