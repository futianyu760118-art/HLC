from __future__ import annotations

import uuid

from models import TenantBillingEvent, db

MAX_NOTE_LENGTH = 1000
MAX_EVENT_TYPE_LENGTH = 80


def _new_id() -> str:
    return str(uuid.uuid4())


def _clean_text(value, *, max_length: int) -> str:
    text = str(value or '').strip()
    return text[:max_length]


def list_billing_events(tenant_id: str, *, limit: int = 200) -> list[TenantBillingEvent]:
    return (
        TenantBillingEvent.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantBillingEvent.created_at.desc())
        .limit(limit)
        .all()
    )


def create_billing_event(tenant_id: str, *, event_type, note=None, operator_id=None) -> TenantBillingEvent:
    cleaned_event_type = _clean_text(event_type, max_length=MAX_EVENT_TYPE_LENGTH)
    if not cleaned_event_type:
        raise ValueError('商业跟进类型不能为空')

    row = TenantBillingEvent(
        id=_new_id(),
        tenant_id=tenant_id,
        event_type=cleaned_event_type,
        note=_clean_text(note, max_length=MAX_NOTE_LENGTH),
        operator_id=operator_id,
    )
    db.session.add(row)
    return row
