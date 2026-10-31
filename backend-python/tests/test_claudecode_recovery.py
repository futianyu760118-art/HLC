import pytest

from models import ApprovalInstance, Notification, db
from tests.test_saas_tenancy import _client, saas_app


def test_notification_service_uses_existing_notification_model_fields(saas_app):
    app, tokens = saas_app

    with app.app_context():
        from services.notification_service import NotificationService

        ok = NotificationService._send_in_app(
            'alpha-admin',
            '待审批：请假申请',
            '张三提交了请假申请，请及时处理。',
            tokens['alpha_id'],
            '/approval-center/pending',
        )

        assert ok is True
        notice = Notification.query.filter_by(user_id='alpha-admin').one()
        assert notice.notice_type == 'system'
        assert notice.status == 'unread'
        assert notice.link_url == '/approval-center/pending'
        assert notice.title == '待审批：请假申请'


def test_todo_service_uses_existing_approval_model_fields(saas_app):
    app, tokens = saas_app

    with app.app_context():
        db.session.add(ApprovalInstance(
            id='approval-alpha-pending',
            tenant_id=tokens['alpha_id'],
            business_type='employee_request',
            business_id='request-alpha-1',
            title='请假申请',
            applicant_id='alpha-admin',
            approver_id='alpha-admin',
            status='pending',
        ))
        db.session.commit()

        from services.todo_service import TodoService

        todos = TodoService.get_user_todos('alpha-admin', tokens['alpha_id'])
        count = TodoService.get_todo_count('alpha-admin', tokens['alpha_id'])

    assert count == 1
    assert len(todos) == 1
    assert todos[0]['id'] == 'approval-alpha-pending'
    assert todos[0]['type'] == 'approval_pending'
    assert todos[0]['title'] == '审批：请假申请'
    assert todos[0]['link'] == '/approval-center/pending'


def test_todo_api_returns_current_tenant_approval_todos_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])

    with app.app_context():
        db.session.add_all([
            ApprovalInstance(
                id='approval-api-alpha-pending',
                tenant_id=tokens['alpha_id'],
                business_type='employee_request',
                business_id='request-api-alpha',
                title='Alpha 调休申请',
                applicant_id='alpha-admin',
                approver_id='alpha-admin',
                status='pending',
            ),
            ApprovalInstance(
                id='approval-api-beta-pending',
                tenant_id=tokens['beta_id'],
                business_type='employee_request',
                business_id='request-api-beta',
                title='Beta 调休申请',
                applicant_id='beta-admin',
                approver_id='beta-admin',
                status='pending',
            ),
        ])
        db.session.commit()

    alpha_response = alpha.get('/api/todos')
    assert alpha_response.status_code == 200
    alpha_payload = alpha_response.get_json()
    assert alpha_payload['count'] == 1
    assert [item['id'] for item in alpha_payload['todos']] == ['approval-api-alpha-pending']
    assert 'Beta 调休申请' not in str(alpha_payload)

    beta_response = beta.get('/api/todos')
    assert beta_response.status_code == 200
    beta_payload = beta_response.get_json()
    assert beta_payload['count'] == 1
    assert [item['id'] for item in beta_payload['todos']] == ['approval-api-beta-pending']


def test_unregistered_continuous_feedback_service_is_importable_but_quarantined(saas_app):
    app, tokens = saas_app

    with app.app_context():
        from services.feedback_service import FeedbackService

        with pytest.raises(RuntimeError, match='Continuous feedback models are not registered'):
            FeedbackService.get_feedback_stats(tokens['alpha_id'], 'employee-alpha-1')
