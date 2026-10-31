import { backendCapabilityForPath } from '../config/capabilityNavigation';

export const pathModuleRules: Array<[RegExp, readonly string[]]> = [
  [/^\/(headcount-management)/, ['extension.foundation.headcount']],
  [/^\/(organization)/, ['organization']],
  [/^\/(people-analytics)/, ['extension.analytics.people', 'extension.foundation.people_analytics_recovery']],
  [/^\/(continuous-feedback)/, ['extension.foundation.continuous_feedback']],
  [/^\/(talent-strategy)/, [
    'extension.talent.profile', 'extension.talent.competency_model', 'extension.talent.succession',
    'extension.talent.review', 'extension.talent.career_path', 'extension.talent.idp',
    'extension.talent.internal_marketplace',
  ]],
  [/^\/(analytics-suite)/, [
    'extension.analytics.basic_bi', 'extension.analytics.custom_reports',
    'extension.analytics.realtime_dashboard', 'extension.analytics.benchmark',
    'extension.analytics.visualization',
  ]],
  [/^\/(intelligence-suite)/, [
    'extension.intelligence.predictive', 'extension.intelligence.turnover_risk',
    'extension.intelligence.ai_recruiting_assistant', 'extension.intelligence.smart_compensation',
    'extension.intelligence.hr_bot', 'extension.intelligence.smart_performance',
    'extension.intelligence.advanced_ai_analytics',
  ]],
  [/^\/(collaboration-suite)/, [
    'extension.collaboration.okr', 'extension.collaboration.one_on_one',
    'extension.collaboration.survey_enps', 'extension.collaboration.employee_care',
    'extension.collaboration.social', 'extension.collaboration.onboarding_experience',
    'extension.collaboration.virtual_assistant', 'extension.collaboration.feedback_experience',
  ]],
  [/^\/(workforce-suite)/, [
    'extension.workforce.smart_scheduling', 'extension.workforce.ai_scheduling',
    'extension.workforce.planning', 'extension.workforce.leave_bank',
    'extension.workforce.lifecycle_enhancement', 'extension.workforce.attendance_optimization',
    'extension.workforce.shift_marketplace',
  ]],
  [/^\/(integration-suite)/, [
    'extension.integration.open_api', 'extension.integration.api_key_oauth',
    'extension.integration.webhook', 'extension.integration.sso',
    'extension.integration.prebuilt_integrations', 'extension.integration.realtime_sync',
    'extension.integration.app_marketplace', 'extension.integration.video_meeting',
    'extension.integration.im_adapter', 'extension.integration.sms_adapter',
  ]],
  [/^\/(mobile-suite)/, [
    'extension.mobile.self_service', 'extension.mobile.pwa', 'extension.mobile.approval',
    'extension.mobile.attendance', 'extension.mobile.payslip',
    'extension.mobile.certificate_download', 'extension.mobile.notifications',
    'extension.mobile.offline_shell',
  ]],
  [/^\/(security-suite)/, [
    'extension.security.data_masking', 'extension.security.compliance_reporting',
    'extension.security.audit_logs', 'extension.security.gdpr',
    'extension.security.database_encryption', 'extension.security.point_in_time_recovery',
    'extension.security.globalization_locale', 'extension.security.globalization_currency',
    'extension.security.globalization_timezone', 'extension.security.globalization_policy',
    'extension.security.data_lifecycle', 'extension.security.mlps_evidence',
  ]],
  [/^\/(job|resume|interview|talent-intelligence)/, ['recruitment']],
  [/^\/hrm\/(candidates|offers)/, ['recruitment']],
  [/^\/hrm\/(departments|positions|employees|onboarding-tasks|probations|employee-changes|resignations|contracts)/, ['organization']],
  [/^\/(attendance-stats|attendance-sync|attendance-policy|attendance-timesheet|attendance-punches)/, ['attendance']],
  [/^\/hrm\/attendance-records/, ['attendance']],
  [/^\/(employee-requests|approval-center)/, ['approval']],
  [/^\/(performance-review|performance-center|performance-indicators|performance-participants|competency)/, ['performance']],
  [/^\/hrm\/(performance|competency)/, ['performance']],
  [/^\/(salary-profiles)/, ['payroll']],
  [/^\/hrm\/payroll-records/, ['payroll']],
  [/^\/(analytics|pk-seasons|training-center|learning-paths|course-categories|exam-center|exam-papers|exam-tasks|exam-attempts|exam-generate|course-edit|exam-task-progress)/, ['training_exam']],
  [/^\/feedback/, ['feedback']],
  [/^\/ai-model-settings/, ['assistant']],
  [/^\/(notifications|operation-logs|system-settings)/, ['system']],
  [/^\/hrm\/(users|roles)/, ['system']],
];

export const moduleKeysForPath = (path: string): readonly string[] => {
  for (const [pattern, moduleKeys] of pathModuleRules) {
    if (pattern.test(path)) return moduleKeys;
  }
  return [];
};

export const moduleForPath = (path: string): string | null => {
  return moduleKeysForPath(path)[0] || null;
};

export const isPathEnabled = (
  path: string,
  enabledModules: Set<string> | null | undefined,
  supportedCapabilities?: Set<string> | null,
): boolean => {
  const moduleKeys = moduleKeysForPath(path);
  if (moduleKeys.length === 0) return true;
  if (!enabledModules) return false;
  if (!moduleKeys.some((moduleKey) => enabledModules.has(moduleKey))) return false;
  const backendCapability = backendCapabilityForPath(path);
  if (!backendCapability || supportedCapabilities === undefined) return true;
  return Boolean(supportedCapabilities?.has(backendCapability));
};
