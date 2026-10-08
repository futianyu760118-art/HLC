import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const apiSource = readFileSync(new URL('../src/utils/api.ts', import.meta.url), 'utf8');
const routerSource = readFileSync(new URL('../src/router/index.tsx', import.meta.url), 'utf8');
const capabilityNavigationSource = readFileSync(new URL('../src/config/capabilityNavigation.ts', import.meta.url), 'utf8');
const moduleNavigationSource = readFileSync(new URL('../src/utils/moduleNavigation.ts', import.meta.url), 'utf8');
const browserScriptSource = readFileSync(
  new URL('../scripts/verify-extension-mvp-browser.mjs', import.meta.url),
  'utf8',
);
const headcountPageSource = readFileSync(
  new URL('../src/pages/p-headcount-management/index.tsx', import.meta.url),
  'utf8',
);
const peopleAnalyticsPageSource = readFileSync(
  new URL('../src/pages/p-people-analytics-extension/index.tsx', import.meta.url),
  'utf8',
);
const continuousFeedbackPageSource = readFileSync(
  new URL('../src/pages/p-continuous-feedback/index.tsx', import.meta.url),
  'utf8',
);
const talentStrategyPageSource = readFileSync(
  new URL('../src/pages/p-talent-strategy-extension/index.tsx', import.meta.url),
  'utf8',
);
const analyticsExtensionPageSource = readFileSync(
  new URL('../src/pages/p-analytics-extension/index.tsx', import.meta.url),
  'utf8',
);
const intelligenceExtensionPageSource = readFileSync(
  new URL('../src/pages/p-intelligence-extension/index.tsx', import.meta.url),
  'utf8',
);
const collaborationExtensionPageSource = readFileSync(
  new URL('../src/pages/p-collaboration-extension/index.tsx', import.meta.url),
  'utf8',
);
const workforceExtensionPageSource = readFileSync(
  new URL('../src/pages/p-workforce-extension/index.tsx', import.meta.url),
  'utf8',
);
const integrationExtensionPageSource = readFileSync(
  new URL('../src/pages/p-integration-extension/index.tsx', import.meta.url),
  'utf8',
);
const mobileExtensionPageSource = readFileSync(
  new URL('../src/pages/p-mobile-extension/index.tsx', import.meta.url),
  'utf8',
);
const securityExtensionPageSource = readFileSync(
  new URL('../src/pages/p-security-extension/index.tsx', import.meta.url),
  'utf8',
);
const platformTenantsPageSource = readFileSync(
  new URL('../src/pages/p-platform-tenants/index.tsx', import.meta.url),
  'utf8',
);
const extensionEntitlementsUrl = new URL('../src/utils/extensionEntitlements.ts', import.meta.url);
const extensionEntitlementsSource = existsSync(extensionEntitlementsUrl)
  ? readFileSync(extensionEntitlementsUrl, 'utf8')
  : '';

test('frontend exposes extension catalog and provider API contracts', () => {
  for (const token of [
    'export interface ExtensionFeature',
    'export interface ExtensionPackage',
    'export interface ExtensionProviderConfig',
    'export interface HeadcountExtensionSummary',
    'export interface HeadcountDepartmentRow',
    'export interface HeadcountHistoryPayload',
    'export interface PeopleAnalyticsDistributionRow',
    'export interface PeopleAnalyticsRisk',
    'export interface ContinuousFeedbackEntry',
    'export interface ContinuousFeedbackStatsPayload',
    'export type AnalyticsFeatureKey',
    'export interface AnalyticsFeatureSummary',
    'export type IntelligenceFeatureKey',
    'export interface IntelligenceFeatureSummary',
    'export type CollaborationFeatureKey',
    'export interface CollaborationFeatureSummary',
    'export type WorkforceFeatureKey',
    'export interface WorkforceFeatureSummary',
    'export type IntegrationFeatureKey',
    'export interface IntegrationFeatureSummary',
    'export type MobileFeatureKey',
    'export interface MobileFeatureSummary',
    'export type SecurityFeatureKey',
    'export interface SecurityFeatureSummary',
    'export const extensionApi',
    'export const platformExtensionApi',
    '/extensions/catalog',
    '/platform/extensions/catalog',
    '/platform/extensions/providers',
    '/extensions/analytics/people/summary',
    '/extensions/foundation/headcount/summary',
    '/extensions/foundation/headcount/departments/',
    '/extensions/foundation/headcount/history',
    '/extensions/foundation/continuous_feedback/entries',
    '/extensions/foundation/continuous_feedback/stats',
    '/extensions/foundation/continuous_feedback/entries/${entryId}/status',
    '/extensions/talent/${feature}/summary',
    '/extensions/analytics/${feature}/summary',
    '/extensions/intelligence/${feature}/summary',
    '/extensions/collaboration/${feature}/summary',
    '/extensions/workforce/${feature}/summary',
    '/extensions/integration/${feature}/summary',
    '/extensions/mobile/${feature}/summary',
    '/extensions/security/${feature}/summary',
    '/extensions/integration/provider-status/',
    '/extensions/${domain}/${feature}/status',
  ]) {
    assert.match(apiSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('headcount management page uses governed extension API paths', () => {
  assert.match(headcountPageSource, /extensionApi/);
  assert.doesNotMatch(headcountPageSource, /\/api\/headcount\/summary/);
  assert.doesNotMatch(headcountPageSource, /\/api\/departments\/\$\{editingDept\.id\}\/headcount/);
});

test('extension MVP pages are routed, menu-visible, and module-gated', () => {
  for (const token of [
    "lazy(() => import('../pages/p-headcount-management'))",
    "lazy(() => import('../pages/p-people-analytics-extension'))",
    "lazy(() => import('../pages/p-continuous-feedback'))",
    "lazy(() => import('../pages/p-talent-strategy-extension'))",
    "lazy(() => import('../pages/p-analytics-extension'))",
    "lazy(() => import('../pages/p-intelligence-extension'))",
    "lazy(() => import('../pages/p-collaboration-extension'))",
    "lazy(() => import('../pages/p-workforce-extension'))",
    "lazy(() => import('../pages/p-integration-extension'))",
    "lazy(() => import('../pages/p-mobile-extension'))",
    "lazy(() => import('../pages/p-security-extension'))",
    "path: '/headcount-management'",
    "path: '/people-analytics'",
    "path: '/continuous-feedback'",
    "path: '/talent-strategy'",
    "path: '/analytics-suite'",
    "path: '/intelligence-suite'",
    "path: '/collaboration-suite'",
    "path: '/workforce-suite'",
    "path: '/integration-suite'",
    "path: '/mobile-suite'",
    "path: '/security-suite'",
  ]) {
    assert.match(routerSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  for (const token of [
    "path: '/headcount-management'",
    "label: '编制管理'",
    "path: '/people-analytics'",
    "label: '人力分析'",
    "path: '/continuous-feedback'",
    "label: '持续反馈'",
    "path: '/talent-strategy'",
    "label: '人才盘点与发展'",
    "path: '/analytics-suite'",
    "label: '分析与报表'",
    "path: '/intelligence-suite'",
    "label: '智能助手与预测'",
    "path: '/collaboration-suite'",
    "label: '员工体验'",
    "path: '/workforce-suite'",
    "label: '排班与劳动力'",
    "path: '/integration-suite'",
    "label: '集成管理'",
    "path: '/mobile-suite'",
    "label: '员工自助与移动端'",
    "path: '/security-suite'",
    "label: '安全与合规'",
  ]) {
    assert.match(capabilityNavigationSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  for (const pattern of [
    /headcount-management.*extension\.foundation\.headcount/s,
    /people-analytics.*extension\.analytics\.people/s,
    /continuous-feedback.*extension\.foundation\.continuous_feedback/s,
    /talent-strategy.*extension\.talent\.profile/s,
    /analytics-suite.*extension\.analytics\.basic_bi/s,
    /intelligence-suite.*extension\.intelligence\.predictive/s,
    /collaboration-suite.*extension\.collaboration\.okr/s,
    /workforce-suite.*extension\.workforce\.smart_scheduling/s,
    /integration-suite.*extension\.integration\.open_api/s,
    /mobile-suite.*extension\.mobile\.self_service/s,
    /security-suite.*extension\.security\.data_masking/s,
  ]) {
    assert.match(moduleNavigationSource, pattern);
  }
});

test('extension package navigation accepts any enabled subfeature', () => {
  assert.match(moduleNavigationSource, /Array<\[RegExp, readonly string\[\]\]>/);
  assert.match(moduleNavigationSource, /moduleKeys\.some\(\(moduleKey\) => enabledModules\.has\(moduleKey\)\)/);
  for (const token of [
    'extension.talent.competency_model',
    'extension.analytics.custom_reports',
    'extension.intelligence.smart_compensation',
    'extension.collaboration.survey_enps',
    'extension.workforce.leave_bank',
    'extension.integration.webhook',
    'extension.mobile.payslip',
    'extension.security.gdpr',
  ]) {
    assert.match(moduleNavigationSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('extension package pages request and render enabled subfeatures only', () => {
  assert.match(extensionEntitlementsSource, /feature\.enabled/);
  assert.match(extensionEntitlementsSource, /feature\.supported/);
  assert.match(extensionEntitlementsSource, /packageKey/);

  for (const [source, allFeaturesName] of [
    [talentStrategyPageSource, 'talentFeatures'],
    [analyticsExtensionPageSource, 'analyticsFeatures'],
    [intelligenceExtensionPageSource, 'intelligenceFeatures'],
    [collaborationExtensionPageSource, 'collaborationFeatures'],
    [workforceExtensionPageSource, 'workforceFeatures'],
    [integrationExtensionPageSource, 'integrationFeatures'],
    [mobileExtensionPageSource, 'mobileFeatures'],
    [securityExtensionPageSource, 'securityFeatures'],
  ]) {
    assert.match(source, /extensionApi\.catalog\(\)/);
    assert.match(source, /enabledFeatures\.map/);
    assert.doesNotMatch(source, new RegExp(`Promise\\.all\\(${allFeaturesName}\\.map`));
  }
});

test('API errors never expose raw HTML error pages', () => {
  assert.match(apiSource, /looksLikeHtml/);
  assert.match(apiSource, /服务暂不可用，请稍后重试/);
  assert.doesNotMatch(apiSource, /catch \{\s*if \(text\) message = text\.slice/);
});

test('platform console exposes application capability support and maturity', () => {
  assert.match(platformTenantsPageSource, /key: 'capabilities', label: '应用与能力'/);
  assert.match(platformTenantsPageSource, /platformExtensionApi\.catalog\(\)/);
  assert.match(platformTenantsPageSource, /releaseCapabilityVersion/);
  assert.match(platformTenantsPageSource, /feature\.supported/);
  assert.match(platformTenantsPageSource, /feature\.maturity/);
  assert.match(platformTenantsPageSource, /moduleLabels\[module\.moduleKey\]/);
  assert.match(platformTenantsPageSource, /extensionPackage\.features\.forEach/);
  assert.match(platformTenantsPageSource, /moduleLabels=\{moduleLabels\}/);
});

test('AI provider secret is only submitted during an explicit replacement flow', () => {
  assert.match(platformTenantsPageSource, /editingProviderSecret \?/);
  assert.match(platformTenantsPageSource, /apiKey: editingProviderSecret/);
  assert.match(platformTenantsPageSource, /更换密钥/);
  assert.match(platformTenantsPageSource, /autoComplete="new-password"/);
});

test('extension summaries expose honest maturity and non-persisted read markers', () => {
  for (const token of [
    'export type ExtensionMaturity',
    'export interface ExtensionReadMarker',
    'id: null',
    'persisted: false',
    'status: ExtensionMaturity',
    'snapshot?: ExtensionReadMarker',
  ]) {
    assert.match(apiSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  for (const source of [
    talentStrategyPageSource,
    analyticsExtensionPageSource,
    intelligenceExtensionPageSource,
    collaborationExtensionPageSource,
    workforceExtensionPageSource,
    integrationExtensionPageSource,
    mobileExtensionPageSource,
    securityExtensionPageSource,
  ]) {
    assert.match(source, /extensionMaturityLabel\(payload\.status\)/);
    assert.doesNotMatch(source, /snapshot\?\.id/);
    assert.doesNotMatch(source, />MVP</);
  }
});

test('people analytics and continuous feedback pages use governed extension APIs', () => {
  assert.match(peopleAnalyticsPageSource, /extensionApi\.peopleAnalyticsSummary/);
  assert.doesNotMatch(peopleAnalyticsPageSource, /\/api\/analytics/);
  assert.doesNotMatch(peopleAnalyticsPageSource, /\/api\/people-analytics/);

  for (const token of [
    'extensionApi.continuousFeedbackEntries',
    'extensionApi.continuousFeedbackStats',
    'extensionApi.createContinuousFeedback',
    'extensionApi.updateContinuousFeedbackStatus',
  ]) {
    assert.match(continuousFeedbackPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(continuousFeedbackPageSource, /\/api\/feedback_api/);
  assert.doesNotMatch(continuousFeedbackPageSource, /\/api\/continuous-feedback/);
});

test('talent strategy page uses governed talent extension APIs', () => {
  for (const token of [
    'extensionApi.talentFeatureSummary',
    'profile',
    'competency_model',
    'succession',
    'review',
    'career_path',
    'idp',
    'internal_marketplace',
  ]) {
    assert.match(talentStrategyPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(talentStrategyPageSource, /\/api\/talent/);
  assert.doesNotMatch(talentStrategyPageSource, /\/api\/competency/);
});

test('analytics suite page uses governed analytics extension APIs', () => {
  for (const token of [
    'extensionApi.analyticsFeatureSummary',
    'basic_bi',
    'custom_reports',
    'realtime_dashboard',
    'benchmark',
    'visualization',
  ]) {
    assert.match(analyticsExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(analyticsExtensionPageSource, /\/api\/analytics/);
  assert.doesNotMatch(analyticsExtensionPageSource, /\/api\/reports/);
});

test('intelligence suite page uses governed intelligence extension APIs', () => {
  for (const token of [
    'extensionApi.intelligenceFeatureSummary',
    'predictive',
    'turnover_risk',
    'ai_recruiting_assistant',
    'smart_compensation',
    'hr_bot',
    'smart_performance',
    'advanced_ai_analytics',
  ]) {
    assert.match(intelligenceExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(intelligenceExtensionPageSource, /\/api\/predictions/);
  assert.doesNotMatch(intelligenceExtensionPageSource, /\/api\/ai/);
});

test('collaboration suite page uses governed collaboration extension APIs', () => {
  for (const token of [
    'extensionApi.collaborationFeatureSummary',
    'okr',
    'one_on_one',
    'survey_enps',
    'employee_care',
    'social',
    'onboarding_experience',
    'virtual_assistant',
    'feedback_experience',
  ]) {
    assert.match(collaborationExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(collaborationExtensionPageSource, /\/api\/okr/);
  assert.doesNotMatch(collaborationExtensionPageSource, /\/api\/survey/);
});

test('workforce suite page uses governed workforce extension APIs', () => {
  for (const token of [
    'extensionApi.workforceFeatureSummary',
    'smart_scheduling',
    'ai_scheduling',
    'planning',
    'leave_bank',
    'lifecycle_enhancement',
    'attendance_optimization',
    'shift_marketplace',
  ]) {
    assert.match(workforceExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(workforceExtensionPageSource, /\/api\/schedule/);
  assert.doesNotMatch(workforceExtensionPageSource, /\/api\/workforce/);
});

test('integration suite page uses governed integration extension APIs', () => {
  for (const token of [
    'extensionApi.integrationFeatureSummary',
    'open_api',
    'api_key_oauth',
    'webhook',
    'sso',
    'prebuilt_integrations',
    'realtime_sync',
    'app_marketplace',
    'video_meeting',
    'im_adapter',
    'sms_adapter',
  ]) {
    assert.match(integrationExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(integrationExtensionPageSource, /\/api\/integration/);
  assert.doesNotMatch(integrationExtensionPageSource, /secretRef/);
});

test('mobile suite page uses governed mobile extension APIs', () => {
  for (const token of [
    'extensionApi.mobileFeatureSummary',
    'self_service',
    'pwa',
    'approval',
    'attendance',
    'payslip',
    'certificate_download',
    'notifications',
    'offline_shell',
  ]) {
    assert.match(mobileExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(mobileExtensionPageSource, /React Native/);
  assert.doesNotMatch(mobileExtensionPageSource, /\/api\/mobile/);
});

test('security suite page uses governed security extension APIs', () => {
  for (const token of [
    'extensionApi.securityFeatureSummary',
    'data_masking',
    'compliance_reporting',
    'audit_logs',
    'gdpr',
    'database_encryption',
    'point_in_time_recovery',
    'globalization_locale',
    'globalization_currency',
    'globalization_timezone',
    'globalization_policy',
    'data_lifecycle',
    'mlps_evidence',
    'Pending owner evidence',
  ]) {
    assert.match(securityExtensionPageSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(securityExtensionPageSource, /Accepted gates: 6\/6/);
  assert.doesNotMatch(securityExtensionPageSource, /\/api\/security/);
});

test('extension MVP browser verification is SaaS scoped and covers visible pages', () => {
  assert.equal(
    packageJson.scripts['verify:extension-mvp-browser'],
    'node scripts/verify-extension-mvp-browser.mjs',
  );
  for (const token of [
    'http://localhost:18280',
    'Refusing to verify against 18080',
    'resolveHrmSmokeCredentials',
    'extension.foundation.todo_notification',
    'extension.foundation.headcount',
    'extension.foundation.people_analytics_recovery',
    'extension.analytics.people',
    'extension.foundation.continuous_feedback',
    'extension.talent.profile',
    'extension.talent.competency_model',
    'extension.talent.succession',
    'extension.talent.review',
    'extension.talent.career_path',
    'extension.talent.idp',
    'extension.talent.internal_marketplace',
    'extension.analytics.basic_bi',
    'extension.analytics.custom_reports',
    'extension.analytics.realtime_dashboard',
    'extension.analytics.benchmark',
    'extension.analytics.visualization',
    'extension.intelligence.predictive',
    'extension.intelligence.turnover_risk',
    'extension.intelligence.ai_recruiting_assistant',
    'extension.intelligence.smart_compensation',
    'extension.intelligence.hr_bot',
    'extension.intelligence.smart_performance',
    'extension.intelligence.advanced_ai_analytics',
    'extension.collaboration.okr',
    'extension.collaboration.one_on_one',
    'extension.collaboration.survey_enps',
    'extension.collaboration.employee_care',
    'extension.collaboration.social',
    'extension.collaboration.onboarding_experience',
    'extension.collaboration.virtual_assistant',
    'extension.collaboration.feedback_experience',
    'extension.workforce.smart_scheduling',
    'extension.workforce.ai_scheduling',
    'extension.workforce.planning',
    'extension.workforce.leave_bank',
    'extension.workforce.lifecycle_enhancement',
    'extension.workforce.attendance_optimization',
    'extension.workforce.shift_marketplace',
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
    'extension.mobile.self_service',
    'extension.mobile.pwa',
    'extension.mobile.approval',
    'extension.mobile.attendance',
    'extension.mobile.payslip',
    'extension.mobile.certificate_download',
    'extension.mobile.notifications',
    'extension.mobile.offline_shell',
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
    '/headcount-management',
    '/people-analytics',
    '/continuous-feedback',
    '/talent-strategy',
    '/analytics-suite',
    '/intelligence-suite',
    '/collaboration-suite',
    '/workforce-suite',
    '/integration-suite',
    '/mobile-suite',
    '/security-suite',
    '人力分析',
    '持续反馈',
    '编制管理',
    '人才盘点与发展',
    '分析与报表',
    '智能助手与预测',
    '员工体验',
    '排班与劳动力',
    '集成管理',
    '员工自助与移动端',
    '安全与合规',
  ]) {
    assert.match(browserScriptSource, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});
