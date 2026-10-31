from __future__ import annotations

from datetime import datetime

from models import TenantInvoice, TenantOrder, db
from tests.test_saas_tenancy import _client, saas_app


def test_platform_billing_order_and_invoice_endpoints(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        order = TenantOrder(
            id='order-alpha-1',
            tenant_id=tenant_id,
            order_no='SO-ALPHA-0001',
            amount_cents=990000,
            currency='CNY',
            status='paid',
            paid_at=datetime.utcnow(),
        )
        invoice = TenantInvoice(
            id='invoice-alpha-1',
            tenant_id=tenant_id,
            order_id=order.id,
            title='Alpha 公司',
            tax_no='TAX-ALPHA',
            amount_cents=990000,
            status='requested',
        )
        db.session.add_all([order, invoice])
        db.session.commit()

    platform = _client(app, tokens['platform'])
    orders = platform.get(f'/api/platform/tenants/{tenant_id}/orders')
    invoices = platform.get(f'/api/platform/tenants/{tenant_id}/invoices')

    assert orders.status_code == 200
    assert invoices.status_code == 200
    assert orders.get_json()[0]['orderNo'] == 'SO-ALPHA-0001'
    assert orders.get_json()[0]['amountCents'] == 990000
    assert invoices.get_json()[0]['title'] == 'Alpha 公司'
    assert invoices.get_json()[0]['status'] == 'requested'


def test_platform_updates_invoice_status(saas_app):
    app, tokens = saas_app
    tenant_id = tokens['alpha_id']

    with app.app_context():
        db.session.add(TenantInvoice(
            id='invoice-alpha-2',
            tenant_id=tenant_id,
            title='Alpha 公司',
            amount_cents=120000,
            status='requested',
        ))
        db.session.commit()

    platform = _client(app, tokens['platform'])
    response = platform.put(
        f'/api/platform/tenants/{tenant_id}/invoices/invoice-alpha-2',
        json={'status': 'issued'},
    )

    assert response.status_code == 200
    assert response.get_json()['status'] == 'issued'
    assert response.get_json()['issuedAt']
