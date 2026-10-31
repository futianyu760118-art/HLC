from tests.test_saas_tenancy import saas_app


def test_platform_tenant_onboarding_checklist_can_be_read_and_updated(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']

    response = client.get(f'/api/platform/tenants/{tenant_id}/onboarding-checklist', headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['tenantId'] == tenant_id
    assert any(item['key'] == 'admin_first_login' for item in payload['items'])

    update = client.put(
        f'/api/platform/tenants/{tenant_id}/onboarding-checklist/admin_first_login',
        json={'status': 'done', 'note': 'Admin changed initial password'},
        headers=headers,
    )
    assert update.status_code == 200
    updated = update.get_json()
    assert updated['key'] == 'admin_first_login'
    assert updated['status'] == 'done'
    assert updated['note'] == 'Admin changed initial password'
