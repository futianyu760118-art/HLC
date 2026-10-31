from tests.test_saas_tenancy import saas_app


def test_platform_can_create_and_progress_tenant_data_request(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']

    created = client.post(
        f'/api/platform/tenants/{tenant_id}/data-requests',
        json={'requestType': 'export', 'requester': 'customer admin', 'scope': 'tenant structured export'},
        headers=headers,
    )
    assert created.status_code == 201
    request_row = created.get_json()
    assert request_row['status'] == 'requested'
    assert request_row['requestType'] == 'export'

    progressed = client.put(
        f"/api/platform/tenants/{tenant_id}/data-requests/{request_row['id']}",
        json={'status': 'approved', 'evidenceRef': 'ticket HPT-DATA-1'},
        headers=headers,
    )
    assert progressed.status_code == 200
    assert progressed.get_json()['status'] == 'approved'

    listed = client.get(f'/api/platform/tenants/{tenant_id}/data-requests', headers=headers)
    assert listed.status_code == 200
    assert listed.get_json()[0]['evidenceRef'] == 'ticket HPT-DATA-1'


def test_tenant_data_request_logs_do_not_expose_raw_request_values(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']

    created = client.post(
        f'/api/platform/tenants/{tenant_id}/data-requests',
        json={
            'requestType': 'export',
            'requester': 'sensitive customer admin',
            'scope': 'sensitive tenant structured export',
            'evidenceRef': 'ticket SECRET-DATA-1',
        },
        headers=headers,
    )
    assert created.status_code == 201
    request_row = created.get_json()

    progressed = client.put(
        f"/api/platform/tenants/{tenant_id}/data-requests/{request_row['id']}",
        json={'status': 'approved', 'evidenceRef': 'ticket SECRET-DATA-2'},
        headers=headers,
    )
    assert progressed.status_code == 200

    logs = client.get(f'/api/platform/operation-logs?tenantId={tenant_id}', headers=headers)
    assert logs.status_code == 200
    data_request_logs = [
        row for row in logs.get_json()
        if row['action'] in {'create_tenant_data_request', 'update_tenant_data_request'}
    ]
    assert len(data_request_logs) == 2
    for row in data_request_logs:
        detail = row['detail']
        assert 'sensitive customer admin' not in str(detail)
        assert 'sensitive tenant structured export' not in str(detail)
        assert 'ticket SECRET-DATA-1' not in str(detail)
        assert 'ticket SECRET-DATA-2' not in str(detail)

    create_detail = next(row['detail'] for row in data_request_logs if row['action'] == 'create_tenant_data_request')
    assert create_detail == {
        'requestType': 'export',
        'status': 'requested',
        'hasRequester': True,
        'scopeLength': len('sensitive tenant structured export'),
        'hasEvidenceRef': True,
    }
    update_detail = next(row['detail'] for row in data_request_logs if row['action'] == 'update_tenant_data_request')
    assert update_detail == {'status': 'approved', 'hasEvidenceRef': True, 'clearsEvidenceRef': False}


def test_tenant_data_request_status_update_without_evidence_preserves_existing_evidence(saas_app):
    app, tokens = saas_app
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['platform']}"}
    tenant_id = tokens['alpha_id']

    created = client.post(
        f'/api/platform/tenants/{tenant_id}/data-requests',
        json={
            'requestType': 'export',
            'requester': 'customer admin',
            'scope': 'tenant structured export',
            'evidenceRef': 'ticket HPT-DATA-KEEP',
        },
        headers=headers,
    )
    assert created.status_code == 201
    request_row = created.get_json()
    assert request_row['evidenceRef'] == 'ticket HPT-DATA-KEEP'

    progressed = client.put(
        f"/api/platform/tenants/{tenant_id}/data-requests/{request_row['id']}",
        json={'status': 'approved'},
        headers=headers,
    )
    assert progressed.status_code == 200
    assert progressed.get_json()['status'] == 'approved'
    assert progressed.get_json()['evidenceRef'] == 'ticket HPT-DATA-KEEP'
