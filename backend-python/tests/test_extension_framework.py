from __future__ import annotations

from datetime import date, datetime, timedelta

from models import (
    AttendanceRecord,
    ApprovalInstance,
    Certificate,
    CompetencyAssessment,
    CompetencyModel,
    Contract,
    Department,
    Discussion,
    DiscussionReply,
    Employee,
    EmployeeChange,
    EmployeePortalAccount,
    EmployeeRequest,
    Feedback,
    Job,
    Notification,
    OnboardingTask,
    OperationLog,
    PayrollRecord,
    PerformanceReview,
    Position,
    Probation,
    Resignation,
    Resume,
    TenantModule,
    TrainingRecord,
    SalaryProfile,
    db,
)
from tests.test_saas_tenancy import _client, saas_app


def test_platform_extension_catalog_covers_full_hidden_backlog(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])

    response = platform.get('/api/platform/extensions/catalog')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['releaseCapabilityVersion'] == 'extension-navigation-v2'
    assert payload['featureCount'] >= 60
    assert len(payload['packages']) == 9

    features = {
        feature['key']: feature
        for package in payload['packages']
        for feature in package['features']
    }
    for key in [
        'extension.talent.profile',
        'extension.analytics.people',
        'extension.integration.open_api',
        'extension.mobile.pwa',
        'extension.security.gdpr',
    ]:
        assert key in features
        assert features[key]['defaultEnabled'] is False
        assert isinstance(features[key]['supported'], bool)
        assert features[key]['maturity'] in {'workflow', 'summary', 'configuration', 'preview'}


def test_extension_modules_are_hidden_until_platform_enables_them(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    blocked = alpha.get('/api/extensions/analytics/people/summary')
    assert blocked.status_code == 403
    assert blocked.get_json()['code'] == 'MODULE_DISABLED'
    assert blocked.get_json()['module'] == 'extension.analytics.people'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.analytics.people', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    alpha_catalog = alpha.get('/api/extensions/catalog')
    assert alpha_catalog.status_code == 200
    assert alpha_catalog.get_json()['releaseCapabilityVersion'] == 'extension-navigation-v2'
    alpha_features = {
        feature['key']: feature
        for package in alpha_catalog.get_json()['packages']
        for feature in package['features']
    }
    assert alpha_features['extension.analytics.people']['enabled'] is True
    assert alpha_features['extension.analytics.people']['supported'] is True
    assert alpha_features['extension.analytics.people']['maturity'] == 'summary'
    assert alpha_features['extension.talent.profile']['enabled'] is False
    assert alpha_features['extension.foundation.people_analytics_recovery']['supported'] is False
    assert alpha_features['extension.foundation.people_analytics_recovery']['maturity'] == 'preview'

    summary = alpha.get('/api/extensions/analytics/people/summary')
    assert summary.status_code == 200
    assert summary.get_json()['featureKey'] == 'extension.analytics.people'

    beta_blocked = beta.get('/api/extensions/analytics/people/summary')
    assert beta_blocked.status_code == 403
    assert beta_blocked.get_json()['module'] == 'extension.analytics.people'


def test_enabled_extension_feature_status_endpoint_is_gated_per_tenant(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    assert alpha.get('/api/extensions/foundation/headcount/status').status_code == 403

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.foundation.headcount', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    status = alpha.get('/api/extensions/foundation/headcount/status')
    assert status.status_code == 200
    payload = status.get_json()
    assert payload['featureKey'] == 'extension.foundation.headcount'
    assert payload['status'] == 'workflow'
    assert payload['defaultVisible'] is False

    assert beta.get('/api/extensions/foundation/headcount/status').status_code == 403


def test_extension_provider_config_is_platform_owned_and_secret_safe(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    platform = _client(app, tokens['platform'])

    assert alpha.get('/api/platform/extensions/providers').status_code == 403

    before = alpha.get('/api/extensions/integration/provider-status/video_meeting')
    assert before.status_code == 403

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.integration.prebuilt_integrations', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    unconfigured = alpha.get('/api/extensions/integration/provider-status/video_meeting')
    assert unconfigured.status_code == 200
    assert unconfigured.get_json()['configured'] is False
    assert '未配置真实供应商' in unconfigured.get_json()['message']

    saved = platform.put('/api/platform/extensions/providers/video_meeting', json={
        'providerType': 'video_meeting',
        'providerCode': 'video_meeting',
        'status': 'mock',
        'configJson': {'mode': 'mock', 'endpoint': 'https://provider.example.test'},
        'secretValue': 'super-secret-value',
    })
    assert saved.status_code == 200
    payload = saved.get_json()
    assert payload['providerType'] == 'video_meeting'
    assert payload['providerCode'] == 'video_meeting'
    assert payload['status'] == 'mock'
    assert payload['secretRef'].startswith('secret-ref:')
    assert 'super-secret-value' not in str(payload)
    assert payload['lastTestedAt'] is None

    with app.app_context():
        from models import ExtensionProviderConfig

        row = ExtensionProviderConfig.query.filter_by(provider_code='video_meeting').first()
        assert row is not None
        assert row.secret_ref == payload['secretRef']
        assert row.config_json['endpoint'] == 'https://provider.example.test'
        assert TenantModule.query.filter_by(
            tenant_id=tokens['beta_id'],
            module_key='extension.integration.prebuilt_integrations',
            enabled=True,
        ).count() == 0

    configured = alpha.get('/api/extensions/integration/provider-status/video_meeting')
    assert configured.status_code == 200
    assert configured.get_json()['configured'] is True
    assert 'secret' not in str(configured.get_json()).lower()


def test_headcount_extension_mvp_is_tenant_scoped_and_audited(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    with app.app_context():
        dept = Department(
            id='alpha-headcount-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 编制部',
            code='HC-ALPHA',
            status='active',
        )
        employee = Employee(
            id='alpha-headcount-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='HC001',
            name='Alpha 员工',
            department_id=dept.id,
            status='active',
        )
        beta_dept = Department(
            id='beta-headcount-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 编制部',
            code='HC-BETA',
            status='active',
        )
        db.session.add_all([dept, employee, beta_dept])
        db.session.commit()

    blocked = alpha.get('/api/extensions/foundation/headcount/summary')
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.foundation.headcount'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.foundation.headcount', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    initial = alpha.get('/api/extensions/foundation/headcount/summary')
    assert initial.status_code == 200
    initial_payload = initial.get_json()
    assert initial_payload['featureKey'] == 'extension.foundation.headcount'
    assert initial_payload['status'] == 'workflow'
    alpha_row = next(row for row in initial_payload['departments'] if row['departmentId'] == 'alpha-headcount-dept')
    assert alpha_row['plan'] == 0
    assert alpha_row['actual'] == 1
    assert alpha_row['status'] == 'unplanned'

    update = alpha.put('/api/extensions/foundation/headcount/departments/alpha-headcount-dept', json={
        'plan': 3,
        'note': 'Q3 hiring plan',
    })
    assert update.status_code == 200
    updated = update.get_json()
    assert updated['departmentId'] == 'alpha-headcount-dept'
    assert updated['oldPlan'] == 0
    assert updated['newPlan'] == 3
    assert updated['actual'] == 1
    assert updated['status'] == 'under'

    summary = alpha.get('/api/extensions/foundation/headcount/summary').get_json()
    assert summary['summary']['totalPlan'] == 3
    assert summary['summary']['totalActual'] == 1
    assert summary['summary']['totalVacancy'] == 2
    assert summary['summary']['usageRate'] == 33.33

    history = alpha.get('/api/extensions/foundation/headcount/history?departmentId=alpha-headcount-dept')
    assert history.status_code == 200
    history_payload = history.get_json()
    assert history_payload['items'][0]['oldPlan'] == 0
    assert history_payload['items'][0]['newPlan'] == 3
    assert history_payload['items'][0]['note'] == 'Q3 hiring plan'

    beta_cross_write = beta.put('/api/extensions/foundation/headcount/departments/alpha-headcount-dept', json={'plan': 9})
    assert beta_cross_write.status_code == 403

    beta_blocked = beta.get('/api/extensions/foundation/headcount/summary')
    assert beta_blocked.status_code == 403

    with app.app_context():
        from models import HeadcountPlan, HeadcountChange

        plan = HeadcountPlan.query.filter_by(tenant_id=tokens['alpha_id'], department_id='alpha-headcount-dept').first()
        assert plan is not None
        assert plan.plan_count == 3
        assert HeadcountChange.query.filter_by(tenant_id=tokens['alpha_id'], department_id='alpha-headcount-dept').count() == 1
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.foundation.headcount',
            action='update_department_plan',
            target_id='alpha-headcount-dept',
        ).count() == 1


def test_people_analytics_extension_insight_is_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    with app.app_context():
        alpha_dept = Department(
            id='alpha-analytics-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 人才分析部',
            code='PA-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-analytics-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 人才分析部',
            code='PA-BETA',
            status='active',
        )
        alpha_a = Employee(
            id='alpha-analytics-emp-a',
            tenant_id=tokens['alpha_id'],
            employee_no='PA001',
            name='Alpha 高绩效员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=400),
        )
        alpha_b = Employee(
            id='alpha-analytics-emp-b',
            tenant_id=tokens['alpha_id'],
            employee_no='PA002',
            name='Alpha 稳定员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=150),
        )
        alpha_left = Employee(
            id='alpha-analytics-emp-left',
            tenant_id=tokens['alpha_id'],
            employee_no='PA003',
            name='Alpha 已离职员工',
            department_id=alpha_dept.id,
            status='resigned',
            hire_date=date.today() - timedelta(days=700),
        )
        beta_employee = Employee(
            id='beta-analytics-emp',
            tenant_id=tokens['beta_id'],
            employee_no='PB001',
            name='Beta 不应泄露员工',
            department_id=beta_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=100),
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_a, alpha_b, alpha_left, beta_employee])
        db.session.flush()
        db.session.add_all([
            PerformanceReview(
                id='alpha-analytics-review-a',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_a.id,
                final_score=95,
                grade='A',
                status='completed',
            ),
            PerformanceReview(
                id='alpha-analytics-review-b',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_b.id,
                final_score=76,
                grade='B',
                status='completed',
            ),
            PerformanceReview(
                id='beta-analytics-review',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                final_score=99,
                grade='A',
                status='completed',
            ),
            Resignation(
                id='alpha-analytics-resignation',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_left.id,
                actual_leave_date=date.today() - timedelta(days=20),
                status='completed',
                reason='career change',
            ),
        ])
        db.session.commit()

    blocked = alpha.get('/api/extensions/analytics/people/summary')
    assert blocked.status_code == 403

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.analytics.people', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    response = alpha.get('/api/extensions/analytics/people/summary')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['featureKey'] == 'extension.analytics.people'
    assert payload['status'] == 'insight'
    assert payload['summary']['employeeCount'] == 2
    assert payload['summary']['totalEmployees'] == 3
    assert payload['summary']['departmentCount'] == 1
    assert payload['summary']['highPerformerCount'] == 1
    assert payload['summary']['highPerformerRate'] == 50.0
    assert payload['summary']['turnoverRate'] > 0
    assert payload['summary']['dataScope'] == 'currentTenant'
    assert payload['distributions']['byDepartment'][0]['departmentName'] == 'Alpha 人才分析部'
    assert payload['distributions']['byDepartment'][0]['employeeCount'] == 2
    assert 'Beta 不应泄露员工' not in str(payload)
    assert payload['risks'][0]['type'] in {'turnover', 'performance', 'headcount'}
    assert payload['snapshot']['id'] is None
    assert payload['snapshot']['persisted'] is False

    beta_blocked = beta.get('/api/extensions/analytics/people/summary')
    assert beta_blocked.status_code == 403

    with app.app_context():
        from models import PeopleAnalyticsSnapshot

        assert PeopleAnalyticsSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert PeopleAnalyticsSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.analytics.people',
            action='snapshot_generated',
        ).count() == 0


def test_continuous_feedback_extension_mvp_is_tenant_scoped_and_audited(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    with app.app_context():
        alpha_employee = Employee(
            id='alpha-feedback-employee',
            tenant_id=tokens['alpha_id'],
            employee_no='CF001',
            name='Alpha 反馈员工',
            status='active',
        )
        beta_employee = Employee(
            id='beta-feedback-employee',
            tenant_id=tokens['beta_id'],
            employee_no='CFB001',
            name='Beta 反馈员工',
            status='active',
        )
        db.session.add_all([alpha_employee, beta_employee])
        db.session.commit()

    blocked = alpha.post('/api/extensions/foundation/continuous_feedback/entries', json={
        'employeeId': 'alpha-feedback-employee',
        'feedbackType': 'praise',
        'category': 'collaboration',
        'content': 'Great partnership on the rollout.',
    })
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.foundation.continuous_feedback'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [
            {'moduleKey': 'extension.foundation.continuous_feedback', 'enabled': True},
        ],
    })
    assert enabled.status_code == 200

    created = alpha.post('/api/extensions/foundation/continuous_feedback/entries', json={
        'employeeId': 'alpha-feedback-employee',
        'feedbackType': 'praise',
        'category': 'collaboration',
        'content': 'Great partnership on the rollout.',
        'visibility': 'manager',
    })
    assert created.status_code == 201
    item = created.get_json()['item']
    assert item['employeeId'] == 'alpha-feedback-employee'
    assert item['giverId'] == 'alpha-admin'
    assert item['status'] == 'open'
    assert item['sentiment'] == 'positive'

    list_response = alpha.get('/api/extensions/foundation/continuous_feedback/entries?employeeId=alpha-feedback-employee')
    assert list_response.status_code == 200
    list_payload = list_response.get_json()
    assert list_payload['featureKey'] == 'extension.foundation.continuous_feedback'
    assert list_payload['total'] == 1
    assert list_payload['items'][0]['content'] == 'Great partnership on the rollout.'

    stats = alpha.get('/api/extensions/foundation/continuous_feedback/stats?employeeId=alpha-feedback-employee')
    assert stats.status_code == 200
    stats_payload = stats.get_json()
    assert stats_payload['stats']['total'] == 1
    assert stats_payload['stats']['byType']['praise'] == 1
    assert stats_payload['stats']['bySentiment']['positive'] == 1

    updated = alpha.put(f"/api/extensions/foundation/continuous_feedback/entries/{item['id']}/status", json={
        'status': 'acknowledged',
        'handlerReply': 'Captured in the next 1-on-1.',
    })
    assert updated.status_code == 200
    assert updated.get_json()['item']['status'] == 'acknowledged'
    assert updated.get_json()['item']['handlerReply'] == 'Captured in the next 1-on-1.'

    beta_enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['beta_id']), json={
        'modules': [
            {'moduleKey': 'extension.foundation.continuous_feedback', 'enabled': True},
        ],
    })
    assert beta_enabled.status_code == 200

    beta_cross_write = beta.post('/api/extensions/foundation/continuous_feedback/entries', json={
        'employeeId': 'alpha-feedback-employee',
        'feedbackType': 'coaching',
        'content': 'Cross tenant should fail.',
    })
    assert beta_cross_write.status_code == 403

    beta_empty = beta.get('/api/extensions/foundation/continuous_feedback/entries')
    assert beta_empty.status_code == 200
    assert beta_empty.get_json()['total'] == 0

    with app.app_context():
        from models import ContinuousFeedbackEntry

        row = ContinuousFeedbackEntry.query.filter_by(
            tenant_id=tokens['alpha_id'],
            employee_id='alpha-feedback-employee',
        ).first()
        assert row is not None
        assert row.status == 'acknowledged'
        assert ContinuousFeedbackEntry.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.foundation.continuous_feedback',
            action='create_feedback',
            target_id=item['id'],
        ).count() == 1
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.foundation.continuous_feedback',
            action='update_feedback_status',
            target_id=item['id'],
        ).count() == 1


def test_talent_strategy_package_insights_are_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    talent_modules = [
        'extension.talent.profile',
        'extension.talent.competency_model',
        'extension.talent.succession',
        'extension.talent.review',
        'extension.talent.career_path',
        'extension.talent.idp',
        'extension.talent.internal_marketplace',
    ]
    feature_paths = {
        'profile': '/api/extensions/talent/profile/summary',
        'competency_model': '/api/extensions/talent/competency_model/summary',
        'succession': '/api/extensions/talent/succession/summary',
        'review': '/api/extensions/talent/review/summary',
        'career_path': '/api/extensions/talent/career_path/summary',
        'idp': '/api/extensions/talent/idp/summary',
        'internal_marketplace': '/api/extensions/talent/internal_marketplace/summary',
    }

    with app.app_context():
        alpha_dept = Department(
            id='alpha-talent-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 人才战略部',
            code='TAL-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-talent-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露部门',
            code='TAL-BETA',
            status='active',
        )
        alpha_position = Position(
            id='alpha-talent-position',
            tenant_id=tokens['alpha_id'],
            title='高级产品经理',
            category='产品',
            department_id=alpha_dept.id,
            level='P6',
            status='active',
        )
        alpha_next_position = Position(
            id='alpha-talent-next-position',
            tenant_id=tokens['alpha_id'],
            title='产品负责人',
            category='产品',
            department_id=alpha_dept.id,
            level='P7',
            status='active',
        )
        beta_position = Position(
            id='beta-talent-position',
            tenant_id=tokens['beta_id'],
            title='Beta 负责人',
            category='产品',
            department_id=beta_dept.id,
            level='P7',
            status='active',
        )
        alpha_star = Employee(
            id='alpha-talent-star',
            tenant_id=tokens['alpha_id'],
            employee_no='TAL001',
            name='Alpha 明星人才',
            department_id=alpha_dept.id,
            position_id=alpha_position.id,
            job_title='高级产品经理',
            status='active',
        )
        alpha_ready = Employee(
            id='alpha-talent-ready',
            tenant_id=tokens['alpha_id'],
            employee_no='TAL002',
            name='Alpha 继任候选',
            department_id=alpha_dept.id,
            position_id=alpha_position.id,
            job_title='产品经理',
            status='active',
        )
        beta_employee = Employee(
            id='beta-talent-employee',
            tenant_id=tokens['beta_id'],
            employee_no='BTAL001',
            name='Beta 不应泄露员工',
            department_id=beta_dept.id,
            position_id=beta_position.id,
            job_title='Beta 负责人',
            status='active',
        )
        db.session.add_all([
            alpha_dept,
            beta_dept,
            alpha_position,
            alpha_next_position,
            beta_position,
            alpha_star,
            alpha_ready,
            beta_employee,
        ])
        db.session.flush()
        alpha_dept.manager_id = alpha_star.id
        beta_dept.manager_id = beta_employee.id
        competency_model = CompetencyModel(
            id='alpha-talent-competency-model',
            tenant_id=tokens['alpha_id'],
            name='产品负责人能力模型',
            description='面向产品负责人岗位',
            dimensions=[
                {'key': 'strategy', 'name': '战略规划', 'requiredLevel': 4},
                {'key': 'collaboration', 'name': '跨部门协作', 'requiredLevel': 4},
            ],
            status='active',
        )
        beta_competency_model = CompetencyModel(
            id='beta-talent-competency-model',
            tenant_id=tokens['beta_id'],
            name='Beta 能力模型',
            dimensions=[{'key': 'secret', 'name': '不应出现', 'requiredLevel': 5}],
            status='active',
        )
        db.session.add_all([competency_model, beta_competency_model])
        db.session.flush()
        db.session.add_all([
            PerformanceReview(
                id='alpha-talent-review-star',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_star.id,
                final_score=96,
                grade='A',
                status='completed',
            ),
            PerformanceReview(
                id='alpha-talent-review-ready',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_ready.id,
                final_score=82,
                grade='B',
                status='completed',
            ),
            PerformanceReview(
                id='beta-talent-review',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                final_score=99,
                grade='A',
                status='completed',
            ),
            TrainingRecord(
                id='alpha-talent-training-star',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_star.id,
                status='completed',
                result='优秀',
                score=95,
            ),
            TrainingRecord(
                id='alpha-talent-training-ready',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_ready.id,
                status='registered',
                result='进行中',
                score=70,
            ),
            CompetencyAssessment(
                id='alpha-talent-assessment-star',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_star.id,
                model_id=competency_model.id,
                scores={'strategy': 5, 'collaboration': 4},
                gaps={},
                overall_score=96,
                weakest_dims=[],
                assessor='alpha-admin',
            ),
            CompetencyAssessment(
                id='alpha-talent-assessment-ready',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_ready.id,
                model_id=competency_model.id,
                scores={'strategy': 3, 'collaboration': 4},
                gaps={'strategy': 1},
                overall_score=82,
                weakest_dims=['strategy'],
                assessor='alpha-admin',
            ),
            Job(
                id='alpha-talent-open-job',
                tenant_id=tokens['alpha_id'],
                title='产品负责人内部机会',
                description='面向内部人才市场',
                status='open',
                category='产品',
                department_id=alpha_dept.id,
                level='P7',
                headcount=1,
            ),
            Job(
                id='beta-talent-open-job',
                tenant_id=tokens['beta_id'],
                title='Beta 不应泄露机会',
                description='不应跨租户展示',
                status='open',
                category='产品',
                department_id=beta_dept.id,
                level='P7',
                headcount=1,
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['profile'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.talent.profile'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in talent_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.talent.{feature}'
        assert payload['status'] == 'insight'
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.talent.{feature}'

    assert payloads['profile']['summary']['employeeCount'] == 2
    assert payloads['profile']['profiles'][0]['employeeName'] == 'Alpha 明星人才'
    assert '核心人才' in payloads['profile']['profiles'][0]['tags']
    assert payloads['competency_model']['summary']['modelCount'] == 1
    assert payloads['succession']['summary']['keyRoleCount'] >= 1
    assert payloads['review']['summary']['nineBoxCount'] >= 1
    assert payloads['career_path']['summary']['pathCount'] >= 1
    assert payloads['idp']['summary']['planCount'] == 2
    assert payloads['internal_marketplace']['summary']['openOpportunityCount'] == 1

    with app.app_context():
        from models import TalentStrategySnapshot

        assert TalentStrategySnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert TalentStrategySnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.talent.profile',
            action='snapshot_generated',
        ).count() == 0


def test_analytics_package_insights_are_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    analytics_modules = [
        'extension.analytics.basic_bi',
        'extension.analytics.custom_reports',
        'extension.analytics.realtime_dashboard',
        'extension.analytics.benchmark',
        'extension.analytics.visualization',
    ]
    feature_paths = {
        'basic_bi': '/api/extensions/analytics/basic_bi/summary',
        'custom_reports': '/api/extensions/analytics/custom_reports/summary',
        'realtime_dashboard': '/api/extensions/analytics/realtime_dashboard/summary',
        'benchmark': '/api/extensions/analytics/benchmark/summary',
        'visualization': '/api/extensions/analytics/visualization/summary',
    }

    with app.app_context():
        alpha_dept = Department(
            id='alpha-analytics-pack-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 数据分析部',
            code='AN-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-analytics-pack-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露分析部',
            code='AN-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-analytics-pack-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='AN001',
            name='Alpha 分析员工',
            department_id=alpha_dept.id,
            status='active',
        )
        beta_employee = Employee(
            id='beta-analytics-pack-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BAN001',
            name='Beta 不应泄露分析员工',
            department_id=beta_dept.id,
            status='active',
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, beta_employee])
        db.session.flush()
        db.session.add_all([
            PerformanceReview(
                id='alpha-analytics-pack-review',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                final_score=91,
                grade='A',
                status='completed',
            ),
            PerformanceReview(
                id='beta-analytics-pack-review',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                final_score=99,
                grade='A',
                status='completed',
            ),
            TrainingRecord(
                id='alpha-analytics-pack-training',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                status='completed',
                score=92,
                result='通过',
            ),
            Job(
                id='alpha-analytics-pack-job',
                tenant_id=tokens['alpha_id'],
                title='Alpha 数据岗位',
                description='用于分析包测试',
                status='open',
                department_id=alpha_dept.id,
                category='数据',
                headcount=2,
            ),
            Job(
                id='beta-analytics-pack-job',
                tenant_id=tokens['beta_id'],
                title='Beta 不应泄露数据岗位',
                description='不应跨租户展示',
                status='open',
                department_id=beta_dept.id,
                category='数据',
                headcount=2,
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['basic_bi'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.analytics.basic_bi'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in analytics_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.analytics.{feature}'
        assert payload['status'] == 'insight'
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.analytics.{feature}'

    assert payloads['basic_bi']['summary']['employeeCount'] >= 1
    assert payloads['custom_reports']['summary']['reportCount'] >= 3
    assert payloads['realtime_dashboard']['summary']['widgetCount'] >= 4
    assert payloads['benchmark']['summary']['benchmarkCount'] >= 3
    assert payloads['visualization']['summary']['chartCount'] >= 4

    with app.app_context():
        from models import AnalyticsInsightSnapshot

        assert AnalyticsInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert AnalyticsInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.analytics.basic_bi',
            action='snapshot_generated',
        ).count() == 0


def test_intelligence_package_mock_insights_are_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    intelligence_modules = [
        'extension.intelligence.predictive',
        'extension.intelligence.turnover_risk',
        'extension.intelligence.ai_recruiting_assistant',
        'extension.intelligence.smart_compensation',
        'extension.intelligence.hr_bot',
        'extension.intelligence.smart_performance',
        'extension.intelligence.advanced_ai_analytics',
    ]
    feature_paths = {
        'predictive': '/api/extensions/intelligence/predictive/summary',
        'turnover_risk': '/api/extensions/intelligence/turnover_risk/summary',
        'ai_recruiting_assistant': '/api/extensions/intelligence/ai_recruiting_assistant/summary',
        'smart_compensation': '/api/extensions/intelligence/smart_compensation/summary',
        'hr_bot': '/api/extensions/intelligence/hr_bot/summary',
        'smart_performance': '/api/extensions/intelligence/smart_performance/summary',
        'advanced_ai_analytics': '/api/extensions/intelligence/advanced_ai_analytics/summary',
    }

    with app.app_context():
        alpha_dept = Department(
            id='alpha-intelligence-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 智能化部',
            code='INT-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-intelligence-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露智能部',
            code='INT-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-intelligence-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='INT001',
            name='Alpha 智能员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=420),
            job_title='数据分析师',
        )
        alpha_risk = Employee(
            id='alpha-intelligence-risk',
            tenant_id=tokens['alpha_id'],
            employee_no='INT002',
            name='Alpha 风险员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=40),
            job_title='招聘顾问',
        )
        beta_employee = Employee(
            id='beta-intelligence-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BINT001',
            name='Beta 不应泄露智能员工',
            department_id=beta_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=300),
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, alpha_risk, beta_employee])
        db.session.flush()
        alpha_job = Job(
            id='alpha-intelligence-job',
            tenant_id=tokens['alpha_id'],
            title='Alpha AI 招聘岗位',
            description='用于智能化包招聘助手测试',
            status='open',
            department_id=alpha_dept.id,
            category='数据',
            headcount=2,
        )
        beta_job = Job(
            id='beta-intelligence-job',
            tenant_id=tokens['beta_id'],
            title='Beta 不应泄露智能岗位',
            description='不应跨租户展示',
            status='open',
            department_id=beta_dept.id,
            category='数据',
            headcount=2,
        )
        db.session.add_all([alpha_job, beta_job])
        db.session.flush()
        db.session.add_all([
            PerformanceReview(
                id='alpha-intelligence-review-good',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                final_score=93,
                grade='A',
                status='completed',
            ),
            PerformanceReview(
                id='alpha-intelligence-review-risk',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_risk.id,
                final_score=62,
                grade='C',
                status='completed',
            ),
            PerformanceReview(
                id='beta-intelligence-review',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                final_score=99,
                grade='A',
                status='completed',
            ),
            TrainingRecord(
                id='alpha-intelligence-training',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                status='completed',
                score=90,
                result='通过',
            ),
            Resume(
                id='alpha-intelligence-resume',
                tenant_id=tokens['alpha_id'],
                job_id=alpha_job.id,
                candidate_name='Alpha 智能候选人',
                file_url='/uploads/resumes/alpha-intelligence.pdf',
                ai_analysis={'matchScore': 88, 'summary': 'match'},
                tags=['数据'],
            ),
            Resume(
                id='beta-intelligence-resume',
                tenant_id=tokens['beta_id'],
                job_id=beta_job.id,
                candidate_name='Beta 不应泄露候选人',
                file_url='/uploads/resumes/beta-intelligence.pdf',
                ai_analysis={'matchScore': 100},
                tags=['secret'],
            ),
            SalaryProfile(
                id='alpha-intelligence-salary-good',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                base_salary=18000,
                position_salary=3000,
                performance_salary=2500,
                bonus=1000,
                status='active',
            ),
            SalaryProfile(
                id='alpha-intelligence-salary-risk',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_risk.id,
                base_salary=9000,
                position_salary=1000,
                performance_salary=500,
                deduction=300,
                status='active',
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['predictive'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.intelligence.predictive'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in intelligence_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.intelligence.{feature}'
        assert payload['status'] == 'mock'
        assert payload['provider']['configured'] is False
        assert '未配置真实供应商' in payload['provider']['message']
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.intelligence.{feature}'

    assert payloads['predictive']['summary']['signalCount'] >= 4
    assert payloads['turnover_risk']['summary']['riskEmployeeCount'] >= 1
    assert payloads['ai_recruiting_assistant']['summary']['candidateCount'] == 1
    assert payloads['smart_compensation']['summary']['profileCount'] == 2
    assert payloads['hr_bot']['summary']['intentCount'] >= 4
    assert payloads['smart_performance']['summary']['reviewCount'] == 2
    assert payloads['advanced_ai_analytics']['summary']['insightCount'] >= 4

    with app.app_context():
        from models import IntelligenceInsightSnapshot

        assert IntelligenceInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert IntelligenceInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.intelligence.predictive',
            action='snapshot_generated',
        ).count() == 0


def test_collaboration_package_insights_are_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    collaboration_modules = [
        'extension.collaboration.okr',
        'extension.collaboration.one_on_one',
        'extension.collaboration.survey_enps',
        'extension.collaboration.employee_care',
        'extension.collaboration.social',
        'extension.collaboration.onboarding_experience',
        'extension.collaboration.virtual_assistant',
        'extension.collaboration.feedback_experience',
    ]
    feature_paths = {
        'okr': '/api/extensions/collaboration/okr/summary',
        'one_on_one': '/api/extensions/collaboration/one_on_one/summary',
        'survey_enps': '/api/extensions/collaboration/survey_enps/summary',
        'employee_care': '/api/extensions/collaboration/employee_care/summary',
        'social': '/api/extensions/collaboration/social/summary',
        'onboarding_experience': '/api/extensions/collaboration/onboarding_experience/summary',
        'virtual_assistant': '/api/extensions/collaboration/virtual_assistant/summary',
        'feedback_experience': '/api/extensions/collaboration/feedback_experience/summary',
    }

    with app.app_context():
        alpha_dept = Department(
            id='alpha-collaboration-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 协同体验部',
            code='COL-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-collaboration-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露协同部',
            code='COL-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-collaboration-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='COL001',
            name='Alpha 协同员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=date.today() - timedelta(days=180),
        )
        alpha_newhire = Employee(
            id='alpha-collaboration-newhire',
            tenant_id=tokens['alpha_id'],
            employee_no='COL002',
            name='Alpha 新员工',
            department_id=alpha_dept.id,
            status='pending_onboard',
            hire_date=date.today(),
        )
        beta_employee = Employee(
            id='beta-collaboration-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BCOL001',
            name='Beta 不应泄露协同员工',
            department_id=beta_dept.id,
            status='active',
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, alpha_newhire, beta_employee])
        db.session.flush()
        alpha_discussion = Discussion(
            id='alpha-collaboration-discussion',
            tenant_id=tokens['alpha_id'],
            course_id='collaboration-course-alpha',
            employee_id=alpha_employee.id,
            title='Alpha 协同讨论',
            content='团队协同经验沉淀',
            like_count=3,
            reply_count=1,
        )
        beta_discussion = Discussion(
            id='beta-collaboration-discussion',
            tenant_id=tokens['beta_id'],
            course_id='collaboration-course-beta',
            employee_id=beta_employee.id,
            title='Beta 不应泄露讨论',
            content='不应跨租户展示',
            like_count=9,
            reply_count=0,
        )
        db.session.add_all([alpha_discussion, beta_discussion])
        db.session.flush()
        db.session.add_all([
            DiscussionReply(
                id='alpha-collaboration-reply',
                tenant_id=tokens['alpha_id'],
                discussion_id=alpha_discussion.id,
                employee_id=alpha_employee.id,
                content='收到，进入下次复盘',
                like_count=1,
            ),
            OnboardingTask(
                id='alpha-collaboration-onboarding-task',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_newhire.id,
                name='准备入职材料',
                task_type='入职准备',
                owner_id='alpha-admin',
                due_date=date.today() + timedelta(days=3),
                status='pending',
            ),
            Feedback(
                id='alpha-collaboration-feedback',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                feedback_type='feature',
                severity='medium',
                title='Alpha 反馈体验优化',
                content='希望增加员工关怀提醒',
                status='pending',
            ),
            Feedback(
                id='beta-collaboration-feedback',
                tenant_id=tokens['beta_id'],
                user_id='beta-admin',
                feedback_type='bug',
                severity='critical',
                title='Beta 不应泄露反馈',
                content='不应跨租户展示',
                status='pending',
            ),
            Notification(
                id='alpha-collaboration-notice',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                employee_id=alpha_employee.id,
                title='Alpha 员工关怀提醒',
                content='安排 1-on-1',
                notice_type='care',
                status='unread',
                link_url='/continuous-feedback',
            ),
            PerformanceReview(
                id='alpha-collaboration-review',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                final_score=86,
                grade='B',
                status='completed',
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['okr'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.collaboration.okr'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in collaboration_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.collaboration.{feature}'
        expected_status = 'mock' if feature == 'virtual_assistant' else 'insight'
        assert payload['status'] == expected_status
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.collaboration.{feature}'

    assert payloads['okr']['summary']['objectiveCount'] >= 2
    assert payloads['one_on_one']['summary']['suggestedMeetingCount'] >= 1
    assert payloads['survey_enps']['summary']['surveySignalCount'] >= 3
    assert payloads['employee_care']['summary']['careSignalCount'] >= 1
    assert payloads['social']['summary']['postCount'] == 1
    assert payloads['onboarding_experience']['summary']['taskCount'] == 1
    assert payloads['virtual_assistant']['summary']['assistantIntentCount'] >= 4
    assert payloads['feedback_experience']['summary']['feedbackCount'] == 1

    with app.app_context():
        from models import CollaborationInsightSnapshot

        assert CollaborationInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert CollaborationInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.collaboration.okr',
            action='snapshot_generated',
        ).count() == 0


def test_workforce_package_insights_are_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    workforce_modules = [
        'extension.workforce.smart_scheduling',
        'extension.workforce.ai_scheduling',
        'extension.workforce.planning',
        'extension.workforce.leave_bank',
        'extension.workforce.lifecycle_enhancement',
        'extension.workforce.attendance_optimization',
        'extension.workforce.shift_marketplace',
    ]
    feature_paths = {
        'smart_scheduling': '/api/extensions/workforce/smart_scheduling/summary',
        'ai_scheduling': '/api/extensions/workforce/ai_scheduling/summary',
        'planning': '/api/extensions/workforce/planning/summary',
        'leave_bank': '/api/extensions/workforce/leave_bank/summary',
        'lifecycle_enhancement': '/api/extensions/workforce/lifecycle_enhancement/summary',
        'attendance_optimization': '/api/extensions/workforce/attendance_optimization/summary',
        'shift_marketplace': '/api/extensions/workforce/shift_marketplace/summary',
    }

    today = date.today()
    with app.app_context():
        alpha_dept = Department(
            id='alpha-workforce-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 劳动力运营部',
            code='WF-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-workforce-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露劳动力部',
            code='WF-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-workforce-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='WF001',
            name='Alpha 排班员工',
            department_id=alpha_dept.id,
            status='active',
            hire_date=today - timedelta(days=220),
        )
        alpha_probation_employee = Employee(
            id='alpha-workforce-probation-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='WF002',
            name='Alpha 生命周期员工',
            department_id=alpha_dept.id,
            status='probation',
            hire_date=today - timedelta(days=45),
            probation_end_date=today + timedelta(days=45),
        )
        beta_employee = Employee(
            id='beta-workforce-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BWF001',
            name='Beta 不应泄露排班员工',
            department_id=beta_dept.id,
            status='active',
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, alpha_probation_employee, beta_employee])
        db.session.flush()
        db.session.add_all([
            AttendanceRecord(
                id='alpha-workforce-attendance-normal',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                attendance_date=today,
                check_in_time=datetime.combine(today, datetime.min.time()).replace(hour=9),
                check_out_time=datetime.combine(today, datetime.min.time()).replace(hour=18),
                work_hours=8,
                status='normal',
                source='manual',
            ),
            AttendanceRecord(
                id='alpha-workforce-attendance-late',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_probation_employee.id,
                attendance_date=today,
                check_in_time=datetime.combine(today, datetime.min.time()).replace(hour=10, minute=30),
                check_out_time=datetime.combine(today, datetime.min.time()).replace(hour=20),
                work_hours=9,
                status='late',
                source='device',
            ),
            AttendanceRecord(
                id='beta-workforce-attendance-secret',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                attendance_date=today,
                work_hours=12,
                status='late',
                remark='Beta 不应泄露考勤',
            ),
            EmployeeRequest(
                id='alpha-workforce-leave-request',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                request_type='leave',
                title='年假申请',
                start_time=datetime.combine(today + timedelta(days=5), datetime.min.time()).replace(hour=9),
                end_time=datetime.combine(today + timedelta(days=5), datetime.min.time()).replace(hour=18),
                duration_hours=8,
                status='approved',
            ),
            EmployeeRequest(
                id='alpha-workforce-overtime-request',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_probation_employee.id,
                request_type='overtime',
                title='项目加班',
                start_time=datetime.combine(today, datetime.min.time()).replace(hour=18),
                end_time=datetime.combine(today, datetime.min.time()).replace(hour=21),
                duration_hours=3,
                status='pending',
            ),
            EmployeeRequest(
                id='beta-workforce-request-secret',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                request_type='leave',
                title='Beta 不应泄露请假',
                duration_hours=16,
                status='approved',
            ),
            Probation(
                id='alpha-workforce-probation',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_probation_employee.id,
                apply_date=today,
                expected_regular_date=today + timedelta(days=45),
                status='pending',
                result='观察中',
            ),
            EmployeeChange(
                id='alpha-workforce-change',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                change_type='transfer',
                after_department_id=alpha_dept.id,
                effective_date=today + timedelta(days=10),
                status='pending',
                reason='旺季排班支援',
            ),
            Resignation(
                id='alpha-workforce-resignation',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                apply_date=today,
                expected_leave_date=today + timedelta(days=30),
                status='pending',
                reason='个人原因',
            ),
            Contract(
                id='alpha-workforce-contract',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_probation_employee.id,
                contract_no='WF-C-001',
                start_date=today - timedelta(days=60),
                end_date=today + timedelta(days=25),
                status='active',
                reminder_date=today + timedelta(days=15),
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['smart_scheduling'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.workforce.smart_scheduling'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in workforce_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.workforce.{feature}'
        expected_status = 'mock' if feature == 'ai_scheduling' else 'insight'
        assert payload['status'] == expected_status
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.workforce.{feature}'

    assert payloads['smart_scheduling']['summary']['scheduleSuggestionCount'] >= 2
    assert payloads['ai_scheduling']['provider']['configured'] is False
    assert '未配置真实供应商' in payloads['ai_scheduling']['provider']['message']
    assert payloads['planning']['summary']['demandSignalCount'] >= 3
    assert payloads['leave_bank']['summary']['leaveRequestCount'] == 1
    assert payloads['lifecycle_enhancement']['summary']['lifecycleSignalCount'] >= 3
    assert payloads['attendance_optimization']['summary']['abnormalAttendanceCount'] >= 1
    assert payloads['shift_marketplace']['summary']['shiftOfferCount'] >= 2

    with app.app_context():
        from models import WorkforceInsightSnapshot

        assert WorkforceInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert WorkforceInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.workforce.smart_scheduling',
            action='snapshot_generated',
        ).count() == 0


def test_integration_package_mock_adapters_are_gated_provider_safe_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    integration_modules = [
        'extension.integration.open_api',
        'extension.integration.api_key_oauth',
        'extension.integration.webhook',
        'extension.integration.sso',
        'extension.integration.prebuilt_integrations',
        'extension.integration.realtime_sync',
        'extension.integration.app_marketplace',
        'extension.integration.video_meeting',
        'extension.integration.im_adapter',
        'extension.integration.sms_adapter',
    ]
    feature_paths = {
        'open_api': '/api/extensions/integration/open_api/summary',
        'api_key_oauth': '/api/extensions/integration/api_key_oauth/summary',
        'webhook': '/api/extensions/integration/webhook/summary',
        'sso': '/api/extensions/integration/sso/summary',
        'prebuilt_integrations': '/api/extensions/integration/prebuilt_integrations/summary',
        'realtime_sync': '/api/extensions/integration/realtime_sync/summary',
        'app_marketplace': '/api/extensions/integration/app_marketplace/summary',
        'video_meeting': '/api/extensions/integration/video_meeting/summary',
        'im_adapter': '/api/extensions/integration/im_adapter/summary',
        'sms_adapter': '/api/extensions/integration/sms_adapter/summary',
    }

    blocked = alpha.get(feature_paths['open_api'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.integration.open_api'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in integration_modules],
    })
    assert enabled.status_code == 200

    provider_seed = {
        'sso': {'providerType': 'sso', 'status': 'mock', 'configJson': {'mode': 'mock', 'issuer': 'https://sso.example.test'}},
        'sms_adapter': {'providerType': 'sms', 'status': 'mock', 'configJson': {'mode': 'mock', 'region': 'cn'}},
        'video_meeting': {'providerType': 'video_meeting', 'status': 'mock', 'configJson': {'mode': 'mock', 'endpoint': 'https://meeting.example.test'}},
    }
    for provider_code, provider_payload in provider_seed.items():
        saved = platform.put('/api/platform/extensions/providers/{}'.format(provider_code), json={
            **provider_payload,
            'providerCode': provider_code,
            'secretValue': 'integration-secret-value',
        })
        assert saved.status_code == 200
        assert 'integration-secret-value' not in str(saved.get_json())

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.integration.{feature}'
        assert payload['status'] == 'mock'
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'integration-secret-value' not in str(payload)
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.integration.{feature}'

    assert payloads['open_api']['summary']['endpointCount'] >= 4
    assert payloads['api_key_oauth']['summary']['credentialFlowCount'] >= 2
    assert payloads['webhook']['summary']['eventCount'] >= 4
    assert payloads['sso']['provider']['configured'] is True
    assert payloads['prebuilt_integrations']['summary']['providerCount'] >= 6
    assert payloads['realtime_sync']['summary']['syncJobCount'] >= 3
    assert payloads['app_marketplace']['summary']['appCount'] >= 5
    assert payloads['video_meeting']['provider']['configured'] is True
    assert payloads['im_adapter']['provider']['configured'] is False
    assert '未配置真实供应商' in payloads['im_adapter']['provider']['message']
    assert payloads['sms_adapter']['provider']['configured'] is True

    with app.app_context():
        from models import IntegrationInsightSnapshot

        assert IntegrationInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert IntegrationInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.integration.open_api',
            action='snapshot_generated',
        ).count() == 0


def test_mobile_package_maturity_is_gated_tenant_scoped_and_read_only(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    mobile_modules = [
        'extension.mobile.self_service',
        'extension.mobile.pwa',
        'extension.mobile.approval',
        'extension.mobile.attendance',
        'extension.mobile.payslip',
        'extension.mobile.certificate_download',
        'extension.mobile.notifications',
        'extension.mobile.offline_shell',
    ]
    feature_paths = {
        'self_service': '/api/extensions/mobile/self_service/summary',
        'pwa': '/api/extensions/mobile/pwa/summary',
        'approval': '/api/extensions/mobile/approval/summary',
        'attendance': '/api/extensions/mobile/attendance/summary',
        'payslip': '/api/extensions/mobile/payslip/summary',
        'certificate_download': '/api/extensions/mobile/certificate_download/summary',
        'notifications': '/api/extensions/mobile/notifications/summary',
        'offline_shell': '/api/extensions/mobile/offline_shell/summary',
    }

    today = date.today()
    with app.app_context():
        alpha_dept = Department(
            id='alpha-mobile-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 移动体验部',
            code='MOB-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-mobile-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露移动部',
            code='MOB-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-mobile-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='MOB001',
            name='Alpha 移动员工',
            email='alpha-mobile@example.test',
            phone='13800000001',
            department_id=alpha_dept.id,
            status='active',
            hire_date=today - timedelta(days=120),
        )
        beta_employee = Employee(
            id='beta-mobile-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BMOB001',
            name='Beta 不应泄露移动员工',
            department_id=beta_dept.id,
            status='active',
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, beta_employee])
        db.session.flush()
        db.session.add_all([
            EmployeePortalAccount(
                id='alpha-mobile-portal',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                password_hash='hashed',
                must_change_password=False,
            ),
            ApprovalInstance(
                id='alpha-mobile-approval',
                tenant_id=tokens['alpha_id'],
                business_type='leave',
                business_id='alpha-mobile-request',
                title='移动端请假审批',
                applicant_id='alpha-admin',
                approver_id='alpha-admin',
                status='pending',
            ),
            AttendanceRecord(
                id='alpha-mobile-attendance',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                attendance_date=today,
                check_in_time=datetime.combine(today, datetime.min.time()).replace(hour=9),
                check_out_time=datetime.combine(today, datetime.min.time()).replace(hour=18),
                work_hours=8,
                status='normal',
            ),
            PayrollRecord(
                id='alpha-mobile-payroll',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                payroll_month='2026-07',
                gross_salary=20000,
                net_salary=16500,
                status='confirmed',
                employee_visible=True,
            ),
            PayrollRecord(
                id='beta-mobile-payroll-secret',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                payroll_month='2026-07',
                gross_salary=99999,
                net_salary=88888,
                status='confirmed',
                employee_visible=True,
                remark='Beta 不应泄露工资',
            ),
            Certificate(
                id='alpha-mobile-certificate',
                tenant_id=tokens['alpha_id'],
                employee_id=alpha_employee.id,
                employee_name='Alpha 移动员工',
                course_title='移动端安全课程',
                cert_no='CERT-MOBILE-ALPHA',
                image_url='/uploads/certificates/alpha-mobile.png',
            ),
            Certificate(
                id='beta-mobile-certificate-secret',
                tenant_id=tokens['beta_id'],
                employee_id=beta_employee.id,
                employee_name='Beta 不应泄露移动员工',
                course_title='不应跨租户证书',
                cert_no='CERT-MOBILE-BETA',
                image_url='/uploads/certificates/beta-mobile.png',
            ),
            Notification(
                id='alpha-mobile-notice',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                employee_id=alpha_employee.id,
                title='移动端通知',
                content='请查看工资条',
                notice_type='mobile',
                status='unread',
                link_url='/portal',
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['self_service'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.mobile.self_service'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in mobile_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.mobile.{feature}'
        expected_status = 'planned' if feature in {'pwa', 'offline_shell'} else 'insight'
        assert payload['status'] == expected_status
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.mobile.{feature}'

    assert payloads['self_service']['summary']['portalAccountCount'] == 1
    assert payloads['pwa']['summary']['installableCapabilityCount'] >= 3
    assert payloads['approval']['summary']['pendingApprovalCount'] == 1
    assert payloads['attendance']['summary']['mobileAttendanceRecordCount'] == 1
    assert payloads['payslip']['summary']['visiblePayslipCount'] == 1
    assert payloads['certificate_download']['summary']['certificateCount'] == 1
    assert payloads['notifications']['summary']['unreadNotificationCount'] == 1
    assert payloads['offline_shell']['summary']['offlineResourceCount'] >= 4

    with app.app_context():
        from models import MobileInsightSnapshot

        assert MobileInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert MobileInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.mobile.self_service',
            action='snapshot_generated',
        ).count() == 0


def test_security_package_insights_are_gated_tenant_scoped_pending_external_evidence(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    beta = _client(app, tokens['beta'])
    platform = _client(app, tokens['platform'])

    security_modules = [
        'extension.security.data_masking',
        'extension.security.compliance_reporting',
        'extension.security.audit_logs',
        'extension.security.gdpr',
        'extension.security.database_encryption',
        'extension.security.point_in_time_recovery',
        'extension.security.globalization_locale',
        'extension.security.globalization_currency',
        'extension.security.globalization_timezone',
        'extension.security.globalization_policy',
        'extension.security.data_lifecycle',
        'extension.security.mlps_evidence',
    ]
    feature_paths = {
        'data_masking': '/api/extensions/security/data_masking/summary',
        'compliance_reporting': '/api/extensions/security/compliance_reporting/summary',
        'audit_logs': '/api/extensions/security/audit_logs/summary',
        'gdpr': '/api/extensions/security/gdpr/summary',
        'database_encryption': '/api/extensions/security/database_encryption/summary',
        'point_in_time_recovery': '/api/extensions/security/point_in_time_recovery/summary',
        'globalization_locale': '/api/extensions/security/globalization_locale/summary',
        'globalization_currency': '/api/extensions/security/globalization_currency/summary',
        'globalization_timezone': '/api/extensions/security/globalization_timezone/summary',
        'globalization_policy': '/api/extensions/security/globalization_policy/summary',
        'data_lifecycle': '/api/extensions/security/data_lifecycle/summary',
        'mlps_evidence': '/api/extensions/security/mlps_evidence/summary',
    }

    with app.app_context():
        from models import AssistantAuditLog, Tenant, TenantDataRequest

        tenant = db.session.get(Tenant, tokens['alpha_id'])
        tenant.settings_json = {
            'locale': 'zh-CN',
            'currency': 'CNY',
            'timezone': 'Asia/Shanghai',
            'globalPolicy': {
                'regions': ['CN', 'EU'],
                'dataResidency': 'cn-primary',
                'crossBorderTransfer': 'approval_required',
            },
        }
        beta_tenant = db.session.get(Tenant, tokens['beta_id'])
        beta_tenant.settings_json = {'globalPolicy': {'note': 'Beta 不应泄露策略'}}

        alpha_dept = Department(
            id='alpha-security-dept',
            tenant_id=tokens['alpha_id'],
            name='Alpha 安全部',
            code='SEC-ALPHA',
            status='active',
        )
        beta_dept = Department(
            id='beta-security-dept',
            tenant_id=tokens['beta_id'],
            name='Beta 不应泄露安全部',
            code='SEC-BETA',
            status='active',
        )
        alpha_employee = Employee(
            id='alpha-security-emp',
            tenant_id=tokens['alpha_id'],
            employee_no='SEC001',
            name='Alpha 安全员工',
            email='alpha-security@example.test',
            phone='13800000001',
            department_id=alpha_dept.id,
            status='active',
        )
        beta_employee = Employee(
            id='beta-security-emp',
            tenant_id=tokens['beta_id'],
            employee_no='BSEC001',
            name='Beta 不应泄露安全员工',
            email='beta-secret@example.test',
            phone='13999999999',
            department_id=beta_dept.id,
            status='active',
        )
        db.session.add_all([alpha_dept, beta_dept, alpha_employee, beta_employee])
        db.session.flush()
        db.session.add_all([
            Resume(
                id='alpha-security-resume',
                tenant_id=tokens['alpha_id'],
                candidate_name='Alpha 候选人',
                email='candidate-alpha@example.test',
                phone='13700000001',
                file_url='/uploads/resumes/alpha.pdf',
            ),
            Resume(
                id='beta-security-resume',
                tenant_id=tokens['beta_id'],
                candidate_name='Beta 不应泄露候选人',
                email='candidate-beta@example.test',
                phone='13699999999',
                file_url='/uploads/resumes/beta.pdf',
            ),
            TenantDataRequest(
                id='alpha-security-export',
                tenant_id=tokens['alpha_id'],
                request_type='export',
                requester='Alpha DPO',
                scope='tenant structured export',
                status='export_generated',
                evidence_ref='DPO-EXPORT-1',
            ),
            TenantDataRequest(
                id='alpha-security-deletion',
                tenant_id=tokens['alpha_id'],
                request_type='deletion',
                requester='Alpha DPO',
                scope='tenant deletion/anonymization planning',
                status='approved',
                evidence_ref='DPO-DELETE-1',
            ),
            TenantDataRequest(
                id='beta-security-request',
                tenant_id=tokens['beta_id'],
                request_type='export',
                requester='Beta 不应泄露请求人',
                scope='Beta 不应泄露数据',
                status='requested',
            ),
            OperationLog(
                id='alpha-security-log',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                module='employees',
                action='update_profile',
                target_id='alpha-security-emp',
                detail={'field': 'phone'},
            ),
            OperationLog(
                id='beta-security-log',
                tenant_id=tokens['beta_id'],
                user_id='beta-admin',
                module='employees',
                action='update_profile',
                target_id='beta-security-emp',
                detail={'note': 'Beta 不应泄露日志'},
            ),
            AssistantAuditLog(
                id='alpha-security-ai-audit',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                request_id='alpha-security-ai',
                provider='local',
                model='local-mvp',
                use_case='security',
                status='success',
                response_content='安全报告摘要',
            ),
        ])
        db.session.commit()

    blocked = alpha.get(feature_paths['data_masking'])
    assert blocked.status_code == 403
    assert blocked.get_json()['module'] == 'extension.security.data_masking'

    enabled = platform.put('/api/platform/tenants/{}/modules'.format(tokens['alpha_id']), json={
        'modules': [{'moduleKey': module_key, 'enabled': True} for module_key in security_modules],
    })
    assert enabled.status_code == 200

    payloads = {}
    for feature, path in feature_paths.items():
        response = alpha.get(path)
        assert response.status_code == 200
        payload = response.get_json()
        payloads[feature] = payload
        assert payload['featureKey'] == f'extension.security.{feature}'
        assert payload['status'] == 'insight'
        assert payload['snapshot']['id'] is None
        assert payload['snapshot']['persisted'] is False
        assert payload['summary']['dataScope'] == 'currentTenant'
        assert 'Beta 不应泄露' not in str(payload)

        beta_blocked = beta.get(path)
        assert beta_blocked.status_code == 403
        assert beta_blocked.get_json()['module'] == f'extension.security.{feature}'

    assert payloads['data_masking']['summary']['maskedFieldCount'] >= 4
    assert '13800000001' not in str(payloads['data_masking'])
    assert payloads['compliance_reporting']['summary']['externalAcceptedGateCount'] == 0
    assert payloads['compliance_reporting']['summary']['externalGateAccepted'] is False
    assert payloads['audit_logs']['summary']['operationLogCount'] >= 1
    assert payloads['gdpr']['summary']['dataRequestCount'] == 2
    assert payloads['database_encryption']['summary']['secretReferenceControl'] == 'platform_secret_ref'
    assert payloads['point_in_time_recovery']['summary']['restoreDrillAccepted'] is False
    assert payloads['globalization_locale']['summary']['defaultLocale'] == 'zh-CN'
    assert payloads['globalization_currency']['summary']['defaultCurrency'] == 'CNY'
    assert payloads['globalization_timezone']['summary']['defaultTimezone'] == 'Asia/Shanghai'
    assert payloads['globalization_policy']['summary']['regionCount'] == 2
    assert payloads['data_lifecycle']['summary']['requiresOwnerApproval'] is True
    assert payloads['mlps_evidence']['summary']['mlpsAccepted'] is False

    with app.app_context():
        from models import SecurityInsightSnapshot

        assert SecurityInsightSnapshot.query.filter_by(tenant_id=tokens['alpha_id']).count() == 0
        assert SecurityInsightSnapshot.query.filter_by(tenant_id=tokens['beta_id']).count() == 0
        assert OperationLog.query.filter_by(
            tenant_id=tokens['alpha_id'],
            module='extension.security.data_masking',
            action='snapshot_generated',
        ).count() == 0
