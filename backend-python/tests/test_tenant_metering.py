from __future__ import annotations

from datetime import datetime
from pathlib import Path

from models import AIUsageLedger, AssistantAuditLog, db
from services import storage
from services.storage import StoredObject
from tests.test_saas_tenancy import _client, saas_app


def test_tenant_usage_counts_ai_audit_and_storage(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        tenant_upload_dir = Path(app.config['UPLOAD_FOLDER']) / 'tenants' / tenant_id
        tenant_upload_dir.mkdir(parents=True, exist_ok=True)
        (tenant_upload_dir / 'sample.bin').write_bytes(b'x' * 2048)
        db.session.add(AssistantAuditLog(
            id='audit-alpha-1',
            tenant_id=tenant_id,
            user_id='alpha-admin',
            request_id='metering-1',
            provider='siliconflow',
            model='test-model',
            use_case='assistant_query',
            status='success',
            created_at=datetime.utcnow(),
        ))
        db.session.commit()

        from services.tenant_metering import tenant_usage
        usage = tenant_usage(tenant_id)

    assert usage['users'] == 1
    assert usage['employees'] == 0
    assert usage['storageMb'] > 0
    assert usage['aiCallsThisMonth'] == 1
    assert usage['checkedAt']


def test_platform_diagnostics_reuses_one_authoritative_storage_measurement(
    saas_app,
    monkeypatch,
):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']
    list_calls = []

    def list_objects(requested_tenant_id):
        list_calls.append(requested_tenant_id)
        return [StoredObject(f'tenants/{requested_tenant_id}/object.bin', 1024 * 1024)]

    monkeypatch.setattr(storage, 'list_tenant_objects', list_objects)
    with app.app_context():
        tenant_upload_dir = Path(app.config['UPLOAD_FOLDER']) / 'tenants' / tenant_id
        tenant_upload_dir.mkdir(parents=True, exist_ok=True)
        (tenant_upload_dir / 'local.bin').write_bytes(b'x' * (512 * 1024))

    response = _client(app, tokens['platform']).get(
        f'/api/platform/tenants/{tenant_id}/diagnostics'
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['usage']['storageMb'] == 1.5
    assert body['tenant']['usage']['storageMb'] == 1.5
    assert list_calls == [tenant_id]


def test_assistant_query_rejects_when_ai_quota_exceeded(saas_app, monkeypatch):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        from services.ai_resource_governance import grant_tenant_ai_entitlement, seed_ai_resource_defaults

        seed_ai_resource_defaults()
        grant_tenant_ai_entitlement(
            tenant_id,
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['basic', 'standard'],
            monthly_quota=1,
        )
        db.session.add(AIUsageLedger(
            id='usage-alpha-quota',
            tenant_id=tenant_id,
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
            tier='standard',
            status='success',
            units=1,
            request_id='metering-quota',
            created_at=datetime.utcnow(),
        ))
        db.session.commit()

    monkeypatch.setattr(
        'services.assistant.assistant_query',
        lambda *args, **kwargs: {'summary': 'should not run', 'sessionId': None},
    )

    client = _client(app, tokens['alpha'])
    response = client.post('/api/hrm/assistant/query', json={'question': '本月还剩多少 AI 调用额度'})

    assert response.status_code == 403
    assert response.get_json()['code'] == 'AI_QUOTA_EXCEEDED'
