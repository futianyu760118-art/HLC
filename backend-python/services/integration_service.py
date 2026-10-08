"""Governed integration extension MVP services."""

from __future__ import annotations

import uuid
from typing import Any

from models import ExtensionProviderConfig, IntegrationInsightSnapshot, db
from services.extension_registry import (
    extension_feature_maturity,
    extension_read_marker,
    public_provider_config,
)


INTEGRATION_FEATURES = {
    'open_api': 'extension.integration.open_api',
    'api_key_oauth': 'extension.integration.api_key_oauth',
    'webhook': 'extension.integration.webhook',
    'sso': 'extension.integration.sso',
    'prebuilt_integrations': 'extension.integration.prebuilt_integrations',
    'realtime_sync': 'extension.integration.realtime_sync',
    'app_marketplace': 'extension.integration.app_marketplace',
    'video_meeting': 'extension.integration.video_meeting',
    'im_adapter': 'extension.integration.im_adapter',
    'sms_adapter': 'extension.integration.sms_adapter',
}

PROVIDER_BY_FEATURE = {
    'sso': 'sso',
    'video_meeting': 'video_meeting',
    'im_adapter': 'im_adapter',
    'sms_adapter': 'sms_adapter',
    'prebuilt_integrations': 'video_meeting',
}


def _provider_status(provider_code: str) -> dict[str, Any]:
    row = ExtensionProviderConfig.query.filter_by(provider_code=provider_code).first()
    if not row:
        return {
            'providerCode': provider_code,
            'configured': False,
            'status': 'unconfigured',
            'message': '未配置真实供应商，当前使用本地可测模拟适配层。',
            'configJson': {},
        }
    return {
        'providerType': row.provider_type,
        'providerCode': row.provider_code,
        'configured': row.status in ('mock', 'active'),
        'status': row.status,
        'message': '已配置供应商适配层，敏感凭据仅通过 secretRef 保存在平台侧。',
        'configJson': public_provider_config(row.config_json),
        'lastTestedAt': row.last_tested_at.isoformat() if row.last_tested_at else None,
    }


class IntegrationService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in INTEGRATION_FEATURES:
            raise LookupError(feature)

        builders = {
            'open_api': IntegrationService._open_api_payload,
            'api_key_oauth': IntegrationService._credential_payload,
            'webhook': IntegrationService._webhook_payload,
            'sso': IntegrationService._sso_payload,
            'prebuilt_integrations': IntegrationService._prebuilt_payload,
            'realtime_sync': IntegrationService._realtime_sync_payload,
            'app_marketplace': IntegrationService._marketplace_payload,
            'video_meeting': IntegrationService._video_meeting_payload,
            'im_adapter': IntegrationService._im_payload,
            'sms_adapter': IntegrationService._sms_payload,
        }
        payload = builders[feature](tenant_id)
        feature_key = INTEGRATION_FEATURES[feature]
        payload.update({
            'featureKey': feature_key,
            'status': extension_feature_maturity(feature_key),
        })
        payload.setdefault('summary', {})['dataScope'] = 'currentTenant'

        payload['snapshot'] = extension_read_marker(feature_key)
        return payload

    @staticmethod
    def _open_api_payload(_tenant_id: str) -> dict[str, Any]:
        endpoints = [
            {'method': 'GET', 'path': '/api/extensions/catalog', 'scope': 'extension:read'},
            {'method': 'GET', 'path': '/api/hrm/employees', 'scope': 'employee:read'},
            {'method': 'GET', 'path': '/api/hrm/departments', 'scope': 'organization:read'},
            {'method': 'POST', 'path': '/api/platform/extensions/providers/{providerCode}', 'scope': 'platform:provider:write'},
        ]
        return {
            'summary': {
                'endpointCount': len(endpoints),
                'scopeCount': len({row['scope'] for row in endpoints}),
                'version': 'v1',
            },
            'endpoints': endpoints,
        }

    @staticmethod
    def _credential_payload(_tenant_id: str) -> dict[str, Any]:
        flows = [
            {
                'key': 'api_key',
                'name': 'API Key',
                'status': 'mvp',
                'secretStorage': 'platform_secret_ref',
            },
            {
                'key': 'oauth_client_credentials',
                'name': 'OAuth Client Credentials',
                'status': 'mvp',
                'secretStorage': 'platform_secret_ref',
            },
        ]
        return {
            'summary': {
                'credentialFlowCount': len(flows),
                'secretLeakGuard': 'enabled',
            },
            'credentialFlows': flows,
        }

    @staticmethod
    def _webhook_payload(_tenant_id: str) -> dict[str, Any]:
        events = [
            {'event': 'employee.created', 'deliveryMode': 'signed_http'},
            {'event': 'employee.updated', 'deliveryMode': 'signed_http'},
            {'event': 'approval.completed', 'deliveryMode': 'signed_http'},
            {'event': 'extension.snapshot_generated', 'deliveryMode': 'signed_http'},
        ]
        return {
            'summary': {
                'eventCount': len(events),
                'retryPolicy': 'exponential_backoff',
            },
            'events': events,
        }

    @staticmethod
    def _sso_payload(_tenant_id: str) -> dict[str, Any]:
        provider = _provider_status('sso')
        return {
            'summary': {
                'protocolCount': 2,
                'configuredProviderCount': 1 if provider['configured'] else 0,
            },
            'provider': provider,
            'protocols': [
                {'key': 'saml2', 'name': 'SAML 2.0', 'status': 'adapter_ready'},
                {'key': 'oidc', 'name': 'OpenID Connect', 'status': 'adapter_ready'},
            ],
        }

    @staticmethod
    def _prebuilt_payload(_tenant_id: str) -> dict[str, Any]:
        providers = [
            {'providerCode': 'video_meeting', 'name': '视频会议', 'status': _provider_status('video_meeting')['status']},
            {'providerCode': 'im_adapter', 'name': '即时通讯', 'status': _provider_status('im_adapter')['status']},
            {'providerCode': 'sms_adapter', 'name': '短信', 'status': _provider_status('sms_adapter')['status']},
            {'providerCode': 'sso', 'name': '单点登录', 'status': _provider_status('sso')['status']},
            {'providerCode': 'pay_benchmark', 'name': '薪酬对标', 'status': _provider_status('pay_benchmark')['status']},
            {'providerCode': 'app_marketplace', 'name': '应用市场', 'status': _provider_status('app_marketplace')['status']},
        ]
        return {
            'summary': {
                'providerCount': len(providers),
                'configuredProviderCount': sum(1 for row in providers if row['status'] in ('mock', 'active')),
            },
            'providers': providers,
        }

    @staticmethod
    def _realtime_sync_payload(_tenant_id: str) -> dict[str, Any]:
        jobs = [
            {'id': 'sync-employees', 'name': '员工主数据同步', 'status': 'mock_ready', 'cadence': 'near_realtime'},
            {'id': 'sync-organization', 'name': '组织结构同步', 'status': 'mock_ready', 'cadence': 'near_realtime'},
            {'id': 'sync-approvals', 'name': '审批状态同步', 'status': 'mock_ready', 'cadence': 'event_driven'},
        ]
        return {
            'summary': {
                'syncJobCount': len(jobs),
                'eventDrivenCount': sum(1 for row in jobs if row['cadence'] == 'event_driven'),
            },
            'syncJobs': jobs,
        }

    @staticmethod
    def _marketplace_payload(_tenant_id: str) -> dict[str, Any]:
        apps = [
            {'id': 'app-sso', 'name': '企业 SSO', 'category': 'identity', 'status': _provider_status('sso')['status']},
            {'id': 'app-im', 'name': 'IM 通知', 'category': 'communication', 'status': _provider_status('im_adapter')['status']},
            {'id': 'app-sms', 'name': '短信通知', 'category': 'communication', 'status': _provider_status('sms_adapter')['status']},
            {'id': 'app-meeting', 'name': '视频会议', 'category': 'collaboration', 'status': _provider_status('video_meeting')['status']},
            {'id': 'app-webhook', 'name': 'Webhook 推送', 'category': 'developer', 'status': 'mock_ready'},
        ]
        return {
            'summary': {
                'appCount': len(apps),
                'configuredAppCount': sum(1 for row in apps if row['status'] in ('mock', 'active')),
            },
            'apps': apps,
        }

    @staticmethod
    def _video_meeting_payload(_tenant_id: str) -> dict[str, Any]:
        provider = _provider_status('video_meeting')
        return {
            'summary': {
                'templateCount': 3,
                'configuredProviderCount': 1 if provider['configured'] else 0,
            },
            'provider': provider,
            'meetingTemplates': [
                {'key': 'interview', 'name': '面试会议', 'auditAction': 'meeting_link_requested'},
                {'key': 'one_on_one', 'name': '1-on-1 会议', 'auditAction': 'meeting_link_requested'},
                {'key': 'training', 'name': '培训直播', 'auditAction': 'meeting_link_requested'},
            ],
        }

    @staticmethod
    def _im_payload(_tenant_id: str) -> dict[str, Any]:
        provider = _provider_status('im_adapter')
        return {
            'summary': {
                'messageTemplateCount': 4,
                'configuredProviderCount': 1 if provider['configured'] else 0,
            },
            'provider': provider,
            'messageTemplates': [
                {'key': 'approval_reminder', 'name': '审批提醒'},
                {'key': 'interview_notice', 'name': '面试通知'},
                {'key': 'onboarding_task', 'name': '入职任务'},
                {'key': 'payroll_notice', 'name': '薪资通知'},
            ],
        }

    @staticmethod
    def _sms_payload(_tenant_id: str) -> dict[str, Any]:
        provider = _provider_status('sms_adapter')
        return {
            'summary': {
                'smsTemplateCount': 3,
                'configuredProviderCount': 1 if provider['configured'] else 0,
            },
            'provider': provider,
            'smsTemplates': [
                {'key': 'login_mfa', 'name': '登录二次验证'},
                {'key': 'interview_reminder', 'name': '面试提醒'},
                {'key': 'approval_urgent', 'name': '紧急审批提醒'},
            ],
        }
