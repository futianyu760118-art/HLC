export type AppIconName =
  | 'users'
  | 'chart-line'
  | 'comments'
  | 'radar'
  | 'chart-bar'
  | 'brain'
  | 'heart'
  | 'calendar'
  | 'plug'
  | 'mobile'
  | 'shield';

export type CapabilityNavigationItem = {
  path: string;
  label: string;
  icon: AppIconName;
  group: string;
  moduleKeys: readonly string[];
  backendCapability: string;
  surface: 'management' | 'portal' | 'platform';
};

export const capabilityNavigation: readonly CapabilityNavigationItem[] = [
  {
    path: '/headcount-management', label: '编制管理', icon: 'users', group: '组织管理',
    moduleKeys: ['extension.foundation.headcount'], backendCapability: 'extension.foundation.headcount', surface: 'management',
  },
  {
    path: '/people-analytics', label: '人力分析', icon: 'chart-line', group: '首页',
    moduleKeys: ['extension.analytics.people', 'extension.foundation.people_analytics_recovery'],
    backendCapability: 'extension.analytics.people', surface: 'management',
  },
  {
    path: '/continuous-feedback', label: '持续反馈', icon: 'comments', group: '绩效管理',
    moduleKeys: ['extension.foundation.continuous_feedback'], backendCapability: 'extension.foundation.continuous_feedback', surface: 'management',
  },
  {
    path: '/talent-strategy', label: '人才盘点与发展', icon: 'radar', group: '人才战略',
    moduleKeys: ['extension.talent.profile', 'extension.talent.competency_model', 'extension.talent.succession', 'extension.talent.review', 'extension.talent.career_path', 'extension.talent.idp', 'extension.talent.internal_marketplace'],
    backendCapability: 'extension.talent.profile', surface: 'management',
  },
  {
    path: '/analytics-suite', label: '分析与报表', icon: 'chart-bar', group: '首页',
    moduleKeys: ['extension.analytics.basic_bi', 'extension.analytics.custom_reports', 'extension.analytics.realtime_dashboard', 'extension.analytics.benchmark', 'extension.analytics.visualization'],
    backendCapability: 'extension.analytics.basic_bi', surface: 'management',
  },
  {
    path: '/intelligence-suite', label: '智能助手与预测', icon: 'brain', group: '人才战略',
    moduleKeys: ['extension.intelligence.predictive', 'extension.intelligence.turnover_risk', 'extension.intelligence.ai_recruiting_assistant', 'extension.intelligence.smart_compensation', 'extension.intelligence.hr_bot', 'extension.intelligence.smart_performance', 'extension.intelligence.advanced_ai_analytics'],
    backendCapability: 'extension.intelligence.predictive', surface: 'management',
  },
  {
    path: '/collaboration-suite', label: '员工体验', icon: 'heart', group: '员工管理',
    moduleKeys: ['extension.collaboration.okr', 'extension.collaboration.one_on_one', 'extension.collaboration.survey_enps', 'extension.collaboration.employee_care', 'extension.collaboration.social', 'extension.collaboration.onboarding_experience', 'extension.collaboration.virtual_assistant', 'extension.collaboration.feedback_experience'],
    backendCapability: 'extension.collaboration.okr', surface: 'management',
  },
  {
    path: '/workforce-suite', label: '排班与劳动力', icon: 'calendar', group: '考勤与申请',
    moduleKeys: ['extension.workforce.smart_scheduling', 'extension.workforce.ai_scheduling', 'extension.workforce.planning', 'extension.workforce.leave_bank', 'extension.workforce.lifecycle_enhancement', 'extension.workforce.attendance_optimization', 'extension.workforce.shift_marketplace'],
    backendCapability: 'extension.workforce.smart_scheduling', surface: 'management',
  },
  {
    path: '/integration-suite', label: '集成管理', icon: 'plug', group: '系统管理',
    moduleKeys: ['extension.integration.open_api', 'extension.integration.api_key_oauth', 'extension.integration.webhook', 'extension.integration.sso', 'extension.integration.prebuilt_integrations', 'extension.integration.realtime_sync', 'extension.integration.app_marketplace', 'extension.integration.video_meeting', 'extension.integration.im_adapter', 'extension.integration.sms_adapter'],
    backendCapability: 'extension.integration.open_api', surface: 'management',
  },
  {
    path: '/mobile-suite', label: '员工自助与移动端', icon: 'mobile', group: '系统管理',
    moduleKeys: ['extension.mobile.self_service', 'extension.mobile.pwa', 'extension.mobile.approval', 'extension.mobile.attendance', 'extension.mobile.payslip', 'extension.mobile.certificate_download', 'extension.mobile.notifications', 'extension.mobile.offline_shell'],
    backendCapability: 'extension.mobile.self_service', surface: 'management',
  },
  {
    path: '/security-suite', label: '安全与合规', icon: 'shield', group: '系统管理',
    moduleKeys: ['extension.security.data_masking', 'extension.security.compliance_reporting', 'extension.security.audit_logs', 'extension.security.gdpr', 'extension.security.database_encryption', 'extension.security.point_in_time_recovery', 'extension.security.globalization_locale', 'extension.security.globalization_currency', 'extension.security.globalization_timezone', 'extension.security.globalization_policy', 'extension.security.data_lifecycle', 'extension.security.mlps_evidence'],
    backendCapability: 'extension.security.audit_logs', surface: 'management',
  },
] as const;

export const managementCapabilitiesForGroup = (group: string) => capabilityNavigation
  .filter((item) => item.surface === 'management' && item.group === group)
  .map(({ path, label, icon }) => ({ path, label, icon: `fa-${icon}` }));

export const backendCapabilityForPath = (path: string): string | null => (
  capabilityNavigation.find((item) => item.path === path)?.backendCapability || null
);
