"""Registry for governed HRM extension packages.

The registry is the single source of truth for extension feature keys.  New
features are listed here before they become visible in tenant navigation or API
flows, and extension module rows default to disabled until a platform admin
explicitly opens them for a tenant.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


EXTENSION_PACKAGES: tuple[dict[str, Any], ...] = (
    {
        'key': 'foundation',
        'name': '基础能力',
        'features': (
            ('extension.foundation.todo_notification', '待办与通知修正'),
            ('extension.foundation.headcount', '编制管理'),
            ('extension.foundation.people_analytics_recovery', 'People Analytics 恢复'),
            ('extension.foundation.continuous_feedback', '持续反馈'),
        ),
    },
    {
        'key': 'talent',
        'name': '人才盘点与发展',
        'features': (
            ('extension.talent.profile', '人才画像'),
            ('extension.talent.competency_model', '能力模型'),
            ('extension.talent.succession', '继任计划'),
            ('extension.talent.review', '人才盘点'),
            ('extension.talent.career_path', '职业发展路径'),
            ('extension.talent.idp', '个人发展计划'),
            ('extension.talent.internal_marketplace', '内部人才市场'),
        ),
    },
    {
        'key': 'analytics',
        'name': '分析与报表',
        'features': (
            ('extension.analytics.people', 'People Analytics'),
            ('extension.analytics.basic_bi', '基础 BI'),
            ('extension.analytics.custom_reports', '自定义报表'),
            ('extension.analytics.realtime_dashboard', '实时仪表盘'),
            ('extension.analytics.benchmark', '对标分析'),
            ('extension.analytics.visualization', '高级数据可视化'),
        ),
    },
    {
        'key': 'intelligence',
        'name': '智能助手与预测',
        'features': (
            ('extension.intelligence.predictive', '预测性分析'),
            ('extension.intelligence.turnover_risk', '离职风险'),
            ('extension.intelligence.ai_recruiting_assistant', 'AI 招聘助手'),
            ('extension.intelligence.smart_compensation', '智能薪酬'),
            ('extension.intelligence.hr_bot', 'HR Bot'),
            ('extension.intelligence.smart_performance', '智能绩效'),
            ('extension.intelligence.advanced_ai_analytics', '高级 AI 分析'),
        ),
    },
    {
        'key': 'collaboration',
        'name': '员工体验',
        'features': (
            ('extension.collaboration.okr', 'OKR'),
            ('extension.collaboration.one_on_one', '1-on-1'),
            ('extension.collaboration.survey_enps', '员工调研/eNPS'),
            ('extension.collaboration.employee_care', '员工关怀'),
            ('extension.collaboration.social', '社交功能'),
            ('extension.collaboration.onboarding_experience', '新员工体验'),
            ('extension.collaboration.virtual_assistant', '虚拟助手'),
            ('extension.collaboration.feedback_experience', '反馈体验增强'),
        ),
    },
    {
        'key': 'workforce',
        'name': '排班与劳动力',
        'features': (
            ('extension.workforce.smart_scheduling', '智能排班'),
            ('extension.workforce.ai_scheduling', 'AI 排班增强'),
            ('extension.workforce.planning', '劳动力规划'),
            ('extension.workforce.leave_bank', '假期银行'),
            ('extension.workforce.lifecycle_enhancement', '生命周期增强'),
            ('extension.workforce.attendance_optimization', '考勤优化'),
            ('extension.workforce.shift_marketplace', '班次市场'),
        ),
    },
    {
        'key': 'integration',
        'name': '集成管理',
        'features': (
            ('extension.integration.open_api', '开放 API'),
            ('extension.integration.api_key_oauth', 'API Key/OAuth'),
            ('extension.integration.webhook', 'Webhook'),
            ('extension.integration.sso', 'SSO'),
            ('extension.integration.prebuilt_integrations', '预集成'),
            ('extension.integration.realtime_sync', '实时同步'),
            ('extension.integration.app_marketplace', '应用市场'),
            ('extension.integration.video_meeting', '视频会议适配'),
            ('extension.integration.im_adapter', 'IM 适配'),
            ('extension.integration.sms_adapter', '短信适配'),
        ),
    },
    {
        'key': 'mobile',
        'name': '员工自助与移动端',
        'features': (
            ('extension.mobile.self_service', '员工自助增强'),
            ('extension.mobile.pwa', '移动 Web/PWA'),
            ('extension.mobile.approval', '移动审批'),
            ('extension.mobile.attendance', '移动考勤'),
            ('extension.mobile.payslip', '工资条'),
            ('extension.mobile.certificate_download', '证明下载'),
            ('extension.mobile.notifications', '通知移动体验'),
            ('extension.mobile.offline_shell', '离线外壳'),
        ),
    },
    {
        'key': 'security',
        'name': '安全与合规',
        'features': (
            ('extension.security.data_masking', '数据脱敏'),
            ('extension.security.compliance_reporting', '合规报告'),
            ('extension.security.audit_logs', '审计日志增强'),
            ('extension.security.gdpr', 'GDPR 合规'),
            ('extension.security.database_encryption', '数据库加密'),
            ('extension.security.point_in_time_recovery', '时间点恢复'),
            ('extension.security.globalization_locale', '全球化语言'),
            ('extension.security.globalization_currency', '全球化币种'),
            ('extension.security.globalization_timezone', '全球化时区'),
            ('extension.security.globalization_policy', '全球化规则'),
            ('extension.security.data_lifecycle', '数据生命周期'),
            ('extension.security.mlps_evidence', '等保证据'),
        ),
    },
)


EXTENSION_MODULE_KEYS: tuple[str, ...] = tuple(
    feature[0]
    for package in EXTENSION_PACKAGES
    for feature in package['features']
)
EXTENSION_MODULE_KEY_SET = set(EXTENSION_MODULE_KEYS)
EXTENSION_FEATURE_LABELS = {
    feature[0]: feature[1]
    for package in EXTENSION_PACKAGES
    for feature in package['features']
}

WORKFLOW_FEATURE_KEYS = {
    'extension.foundation.todo_notification',
    'extension.foundation.headcount',
    'extension.foundation.continuous_feedback',
}
PLANNED_FEATURE_KEYS = {
    'extension.foundation.people_analytics_recovery',
    'extension.mobile.pwa',
    'extension.mobile.offline_shell',
}
MOCK_FEATURE_PREFIXES = (
    'extension.intelligence.',
    'extension.integration.',
)
MOCK_FEATURE_KEYS = {
    'extension.collaboration.virtual_assistant',
    'extension.workforce.ai_scheduling',
}
PUBLIC_PROVIDER_CONFIG_KEYS = {
    'mode', 'endpoint', 'issuer', 'region', 'baseUrl', 'audience', 'scopes',
}


def extension_feature_maturity(feature_key: str) -> str:
    if feature_key in WORKFLOW_FEATURE_KEYS:
        return 'workflow'
    if feature_key in PLANNED_FEATURE_KEYS:
        return 'planned'
    if feature_key in MOCK_FEATURE_KEYS or feature_key.startswith(MOCK_FEATURE_PREFIXES):
        return 'mock'
    return 'insight'


def extension_read_marker(feature_key: str, **metadata: Any) -> dict[str, Any]:
    return {
        'id': None,
        'featureKey': feature_key,
        'persisted': False,
        **metadata,
    }


def public_provider_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    return {
        key: value
        for key, value in config.items()
        if key in PUBLIC_PROVIDER_CONFIG_KEYS
    }


def all_managed_module_keys(base_keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(base_keys) + EXTENSION_MODULE_KEYS


def is_extension_module(module_key: Optional[str]) -> bool:
    return bool(module_key and module_key.startswith('extension.'))


def extension_module_for_path(path: str) -> Optional[str]:
    if not path.startswith('/api/extensions/'):
        return None
    suffix = path[len('/api/extensions/'):].strip('/')
    if not suffix or suffix == 'catalog':
        return None
    parts = suffix.split('/')
    if len(parts) >= 3 and parts[0] == 'analytics' and parts[1] == 'people':
        return 'extension.analytics.people'
    if len(parts) >= 2 and parts[0] == 'integration' and parts[1] == 'provider-status':
        return 'extension.integration.prebuilt_integrations'
    if len(parts) >= 2:
        candidate = f'extension.{parts[0]}.{parts[1]}'
        if candidate in EXTENSION_MODULE_KEY_SET:
            return candidate
    return None


def extension_catalog_payload(tenant_id: Optional[str] = None) -> dict[str, Any]:
    enabled_map: dict[str, bool] = {}
    if tenant_id:
        from models import TenantModule

        rows = TenantModule.query.filter(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_key.in_(EXTENSION_MODULE_KEYS),
        ).all()
        enabled_map = {row.module_key: bool(row.enabled) for row in rows}

    packages = []
    for package in EXTENSION_PACKAGES:
        features = []
        for key, name in package['features']:
            internal_maturity = extension_feature_maturity(key)
            public_maturity = {
                'workflow': 'workflow',
                'insight': 'summary',
                'mock': 'configuration',
                'planned': 'preview',
            }[internal_maturity]
            feature = {
                'key': key,
                'name': name,
                'packageKey': package['key'],
                'defaultEnabled': False,
                'maturity': public_maturity,
                'supported': internal_maturity != 'planned',
            }
            if tenant_id:
                feature['enabled'] = bool(enabled_map.get(key, False))
            features.append(feature)
        packages.append({
            'key': package['key'],
            'name': package['name'],
            'features': features,
        })

    return {
        'releaseCapabilityVersion': 'extension-navigation-v2',
        'packages': packages,
        'featureCount': len(EXTENSION_MODULE_KEYS),
        'moduleKeys': list(EXTENSION_MODULE_KEYS),
    }


def extension_feature_status_payload(feature_key: str) -> dict[str, Any]:
    maturity = extension_feature_maturity(feature_key)
    verified = maturity in {'workflow', 'insight', 'mock'}
    return {
        'featureKey': feature_key,
        'name': EXTENSION_FEATURE_LABELS.get(feature_key, feature_key),
        'status': maturity,
        'defaultVisible': False,
        'acceptance': {
            'model': 'ready' if maturity == 'workflow' else 'read_only' if maturity == 'insight' else 'adapter_mock' if maturity == 'mock' else 'pending',
            'api': 'registered' if verified else 'status_only',
            'ui': 'visible_when_enabled' if verified else 'hidden',
            'tenantIsolation': 'verified' if verified else 'gated',
            'browserVerification': 'verified' if verified else 'pending',
        },
    }
