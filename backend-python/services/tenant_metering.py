from __future__ import annotations

from datetime import datetime
from typing import Any

from models import AIUsageLedger, AssistantAuditLog, Employee, User
from services.tenant_storage_quota import tenant_storage_usage_bytes


def _storage_mb_for_tenant(tenant_id: str) -> float:
    return round(tenant_storage_usage_bytes(tenant_id) / 1024 / 1024, 4)


def tenant_usage(tenant_id: str) -> dict[str, Any]:
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ledger_calls = AIUsageLedger.query.filter(
        AIUsageLedger.tenant_id == tenant_id,
        AIUsageLedger.created_at >= month_start,
    ).count()
    legacy_audit_calls = AssistantAuditLog.query.filter(
        AssistantAuditLog.tenant_id == tenant_id,
        AssistantAuditLog.created_at >= month_start,
        AssistantAuditLog.resource_domain.is_(None),
    ).count()
    domain_rows = AIUsageLedger.query.filter(
        AIUsageLedger.tenant_id == tenant_id,
        AIUsageLedger.created_at >= month_start,
    ).all()
    by_domain: dict[str, int] = {}
    for row in domain_rows:
        by_domain[row.resource_domain] = by_domain.get(row.resource_domain, 0) + (row.units or 1)
    return {
        'users': User.query.filter_by(tenant_id=tenant_id).count(),
        'employees': Employee.query.filter_by(tenant_id=tenant_id).count(),
        'storageMb': _storage_mb_for_tenant(tenant_id),
        'aiCallsThisMonth': ledger_calls + legacy_audit_calls,
        'aiUsageByDomain': by_domain,
        'checkedAt': datetime.utcnow().isoformat() + 'Z',
    }
