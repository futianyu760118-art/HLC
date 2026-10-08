from tests.test_saas_tenancy import saas_app


def test_platform_can_record_subscription_lifecycle_event(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']

    response = client.post(
        f'/api/platform/tenants/{tenant_id}/billing-events',
        json={'eventType': 'renewal_reminder_sent', 'note': 'Sent renewal reminder for next quarter'},
        headers=headers,
    )
    assert response.status_code == 201
    event = response.get_json()
    assert event['eventType'] == 'renewal_reminder_sent'

    listed = client.get(f'/api/platform/tenants/{tenant_id}/billing-events', headers=headers)
    assert listed.status_code == 200
    assert listed.get_json()[0]['note'] == 'Sent renewal reminder for next quarter'


def test_platform_billing_event_log_hides_raw_note(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']
    sensitive_note = 'Sensitive renewal note SECRET-BILLING-1'

    response = client.post(
        f'/api/platform/tenants/{tenant_id}/billing-events',
        json={'eventType': 'renewal_reminder_sent', 'note': sensitive_note},
        headers=headers,
    )
    assert response.status_code == 201

    logs = client.get(f'/api/platform/operation-logs?tenantId={tenant_id}', headers=headers)
    assert logs.status_code == 200
    billing_log = next(row for row in logs.get_json() if row['action'] == 'create_billing_event')
    detail = billing_log['detail']
    detail_text = str(detail)

    assert 'SECRET-BILLING-1' not in detail_text
    assert sensitive_note not in detail_text
    assert detail['eventType'] == 'renewal_reminder_sent'
    assert detail['hasNote'] is True
    assert detail['noteLength'] == len(sensitive_note)
