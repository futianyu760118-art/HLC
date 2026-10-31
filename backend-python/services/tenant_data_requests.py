from __future__ import annotations

import uuid
from datetime import datetime

from models import TenantDataRequest, db


ALLOWED_REQUEST_TYPES = {'export', 'deletion'}
ALLOWED_STATUSES = {
    'requested',
    'identity_verified',
    'approved',
    'export_generated',
    'delivered',
    'closed',
    'rejected',
}


def _normalized_required(value: object, field_name: str, *, max_length: int) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError(f'{field_name} is required')
    return text[:max_length]


def _normalize_request_type(value: object) -> str:
    request_type = str(value or '').strip().lower()
    if request_type not in ALLOWED_REQUEST_TYPES:
        raise ValueError('invalid request type')
    return request_type


def _normalize_status(value: object) -> str:
    status = str(value or '').strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ValueError('invalid status')
    return status


def list_data_requests(tenant_id: str) -> list[TenantDataRequest]:
    return (
        TenantDataRequest.query
        .filter_by(tenant_id=tenant_id)
        .order_by(TenantDataRequest.created_at.desc())
        .limit(200)
        .all()
    )


def create_data_request(
    tenant_id: str,
    *,
    request_type: object,
    requester: object,
    scope: object,
    evidence_ref: object = '',
) -> TenantDataRequest:
    row = TenantDataRequest(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        request_type=_normalize_request_type(request_type),
        requester=_normalized_required(requester, 'requester', max_length=160),
        scope=_normalized_required(scope, 'scope', max_length=240),
        status='requested',
        evidence_ref=str(evidence_ref or '').strip()[:240] or None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def update_data_request(
    tenant_id: str,
    request_id: str,
    *,
    status: object | None = None,
    evidence_ref: object | None = None,
) -> TenantDataRequest | None:
    row = TenantDataRequest.query.filter_by(id=request_id, tenant_id=tenant_id).first()
    if not row:
        return None
    if status is not None:
        row.status = _normalize_status(status)
    if evidence_ref is not None:
        row.evidence_ref = str(evidence_ref or '').strip()[:240] or None
    row.updated_at = datetime.utcnow()
    db.session.flush()
    return row
