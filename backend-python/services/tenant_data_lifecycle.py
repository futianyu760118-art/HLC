from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from models import TENANT_SCOPED_MODELS, db


SENSITIVE_COLUMN_PARTS = (
    'password',
    'secret',
    'token',
    'credential',
    'private_key',
    'api_key',
)

DELETION_PLAN_MODES = {'delete', 'anonymize'}


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def _safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value


def _is_sensitive_column(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in SENSITIVE_COLUMN_PARTS)


def _safe_column_names(model: Any) -> list[str]:
    return [
        column.key
        for column in model.__table__.columns
        if not _is_sensitive_column(column.key)
    ]


def _bounded_limit(value: int | None) -> int:
    if value is None:
        return 1000
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1000
    return max(1, min(parsed, 5000))


def _ordered_query(model: Any, tenant_id: str):
    query = db.session.query(model).filter(model.tenant_id == tenant_id)
    primary_keys = list(model.__mapper__.primary_key)
    if primary_keys:
        query = query.order_by(*primary_keys)
    return query


def tenant_data_inventory(tenant_id: str, *, include_empty: bool = False) -> dict[str, Any]:
    """Return a non-destructive tenant data manifest for export/deletion review."""
    tables: list[dict[str, Any]] = []

    for model in sorted(TENANT_SCOPED_MODELS, key=lambda item: item.__tablename__):
        count = (
            db.session.query(model)
            .filter(model.tenant_id == tenant_id)
            .count()
        )
        if count == 0 and not include_empty:
            continue
        tables.append({
            'model': model.__name__,
            'table': model.__tablename__,
            'rows': int(count),
        })

    return {
        'tenantId': tenant_id,
        'generatedAt': _utc_now_iso(),
        'tableCount': len(tables),
        'totalRows': sum(row['rows'] for row in tables),
        'tables': tables,
    }


def tenant_structured_export(
    tenant_id: str,
    *,
    include_empty: bool = False,
    max_rows_per_table: int | None = 1000,
) -> dict[str, Any]:
    """Return a safe JSON-ready structured data package for one tenant."""
    row_limit = _bounded_limit(max_rows_per_table)
    data: dict[str, list[dict[str, Any]]] = {}
    tables: list[dict[str, Any]] = []

    for model in sorted(TENANT_SCOPED_MODELS, key=lambda item: item.__tablename__):
        query = _ordered_query(model, tenant_id)
        total_rows = query.count()
        if total_rows == 0 and not include_empty:
            continue

        column_names = _safe_column_names(model)
        rows = []
        if total_rows:
            for row in query.limit(row_limit).all():
                rows.append({
                    name: _safe_value(getattr(row, name))
                    for name in column_names
                })

        table_name = model.__tablename__
        data[table_name] = rows
        tables.append({
            'model': model.__name__,
            'table': table_name,
            'rows': int(total_rows),
            'exportedRows': len(rows),
            'truncated': total_rows > len(rows),
            'columns': column_names,
        })

    return {
        'tenantId': tenant_id,
        'generatedAt': _utc_now_iso(),
        'format': 'json-v1',
        'maxRowsPerTable': row_limit,
        'tableCount': len(tables),
        'totalRows': sum(row['rows'] for row in tables),
        'exportedRows': sum(row['exportedRows'] for row in tables),
        'truncatedTables': [row['table'] for row in tables if row['truncated']],
        'tables': tables,
        'data': data,
    }


def tenant_deletion_plan(
    tenant_id: str,
    *,
    tenant_slug: str | None = None,
    mode: str = 'delete',
    include_empty: bool = False,
) -> dict[str, Any]:
    """Return a non-destructive deletion/anonymization plan for owner approval."""
    normalized_mode = (mode or 'delete').strip().lower()
    if normalized_mode not in DELETION_PLAN_MODES:
        normalized_mode = 'delete'

    inventory = tenant_data_inventory(tenant_id, include_empty=include_empty)
    tenant_label = tenant_slug or tenant_id
    action = 'ANONYMIZE' if normalized_mode == 'anonymize' else 'DELETE'

    return {
        'tenantId': tenant_id,
        'tenantSlug': tenant_slug,
        'generatedAt': _utc_now_iso(),
        'mode': normalized_mode,
        'destructive': False,
        'requiresOwnerApproval': True,
        'requiresFinalBackup': True,
        'requiresDualConfirmation': True,
        'confirmationPhrase': f'{action} TENANT {tenant_label}',
        'requiredSteps': [
            'owner_approval',
            'retention_review',
            'final_backup',
            'tenant_suspension',
            'dual_confirmation',
            'execution_window',
            'post_action_isolation_check',
        ],
        'retentionReview': {
            'billingRecords': 'review_before_execution',
            'securityAuditLogs': 'review_before_execution',
            'legalHold': 'review_before_execution',
            'contractualRetention': 'review_before_execution',
        },
        'tableCount': inventory['tableCount'],
        'totalRows': inventory['totalRows'],
        'tables': inventory['tables'],
    }
