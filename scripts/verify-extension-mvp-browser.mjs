import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { EDGE_EXECUTABLE, importPlaywright } from './resolve-playwright-runtime.mjs';
import { resolveHrmSmokeCredentials } from './hrm-smoke-credentials.mjs';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const parsedBaseUrl = new URL(BASE_URL);
if (parsedBaseUrl.port === '18080') {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}

const dotEnvPath = path.resolve('.env');
const dotEnv = existsSync(dotEnvPath)
  ? Object.fromEntries(
    readFileSync(dotEnvPath, 'utf8')
      .split(/\r?\n/)
      .map((line) => line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/))
      .filter(Boolean)
      .map((match) => [match[1], match[2].replace(/^['"]|['"]$/g, '')]),
  )
  : {};

const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_EXTENSION_BROWSER_TIMEOUT_MS || 30000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_EXTENSION_BROWSER_RUN_ID || `extension-mvp-${stamp}`;

const extensionModuleKeys = [
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
];

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const readJson = async (response, label) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} did not return JSON: ${text.slice(0, 500)}`);
  }
};

const requestJson = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(Number(process.env.HRM_EXTENSION_BROWSER_API_TIMEOUT_MS || 12000)),
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const payload = await readJson(response, url);
  if (!response.ok) {
    const error = new Error(payload?.error || payload?.message || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
};

const authHeaders = (auth, requestId) => ({
  Authorization: `Bearer ${auth.token}`,
  'X-Request-ID': requestId,
});

async function loginPlatformAdmin() {
  const identifier = process.env.HRM_PLATFORM_EMAIL || process.env.HRM_TEST_PLATFORM_EMAIL || dotEnv.PLATFORM_ADMIN_EMAIL || 'platform@example.com';
  const password = process.env.HRM_PLATFORM_PASSWORD || process.env.HRM_TEST_PLATFORM_PASSWORD || dotEnv.PLATFORM_ADMIN_PASSWORD || '';
  if (!password) throw new Error('Missing platform admin password for extension browser verification');
  return requestJson(`${BASE_URL}/api/platform/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': `${runId}-platform-login` },
    body: JSON.stringify({ identifier, password }),
  });
}

async function tenantModules(auth) {
  return requestJson(`${BASE_URL}/api/hrm/tenant/modules`, {
    headers: authHeaders(auth, `${runId}-tenant-modules`),
  });
}

async function syncTenantModules(platformAuth, tenantId, moduleRows) {
  return requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/modules`, {
    method: 'PUT',
    headers: authHeaders(platformAuth, `${runId}-sync-modules`),
    body: JSON.stringify({
      modules: moduleRows.map((row) => ({
        moduleKey: row.moduleKey,
        enabled: Boolean(row.enabled),
        limits: row.limits || {},
      })),
    }),
  });
}

function withEnabledExtensions(moduleRows) {
  const byKey = new Map(moduleRows.map((row) => [row.moduleKey, { ...row }]));
  for (const moduleKey of extensionModuleKeys) {
    const existing = byKey.get(moduleKey) || { moduleKey, limits: {} };
    byKey.set(moduleKey, { ...existing, moduleKey, enabled: true, limits: existing.limits || {} });
  }
  return [...byKey.values()];
}

async function addAuthToContext(context, auth) {
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });
}

async function waitForMain(page, text) {
  await page.waitForSelector('main.hpt-main', { timeout: ROUTE_TIMEOUT_MS });
  if (text) {
    await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  }
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => null);
}

async function verifyPage(page, route, title, visibleTexts) {
  await page.goto(`${BASE_URL}${route}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
  await waitForMain(page, title);
  for (const text of visibleTexts) {
    await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  }
  return { route, title, ok: true };
}

async function verifyExtensionNavigation(context, auth) {
  const page = await context.newPage();
  try {
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '数据驾驶舱');
    for (const label of ['编制管理', '人力分析', '持续反馈', '人才盘点与发展', '分析与报表', '智能助手与预测', '员工体验', '排班与劳动力', '集成管理', '员工自助与移动端', '安全与合规']) {
      await page.getByRole('link', { name: label, exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    }
    if (await page.getByText('扩展功能', { exact: true }).count()) throw new Error('legacy extension navigation group is visible');

    const pages = [];
    pages.push(await verifyPage(page, '/headcount-management', '编制管理', ['部门编制详情']));
    pages.push(await verifyPage(page, '/people-analytics', '人力分析', ['部门人数分布', '风险信号']));
    pages.push(await verifyPage(page, '/continuous-feedback', '持续反馈', ['记录反馈', '反馈列表']));
    pages.push(await verifyPage(page, '/talent-strategy', '人才盘点与发展', ['人才画像', '内部人才市场']));
    pages.push(await verifyPage(page, '/analytics-suite', '分析与报表', ['基础 BI', '高级数据可视化']));
    pages.push(await verifyPage(page, '/intelligence-suite', '智能助手与预测', ['预测性分析', '高级 AI 分析']));
    pages.push(await verifyPage(page, '/collaboration-suite', '员工体验', ['OKR', '反馈体验增强']));
    pages.push(await verifyPage(page, '/workforce-suite', '排班与劳动力', ['智能排班', '班次市场']));
    pages.push(await verifyPage(page, '/integration-suite', '集成管理', ['开放 API', '短信适配']));
    pages.push(await verifyPage(page, '/mobile-suite', '员工自助与移动端', ['员工自助增强', '通知移动体验']));
    pages.push(await verifyPage(page, '/security-suite', '安全与合规', ['数据脱敏', 'Pending owner evidence']));

    const people = await requestJson(`${BASE_URL}/api/extensions/analytics/people/summary`, {
      headers: authHeaders(auth, `${runId}-people-summary`),
    });
    if (people.featureKey !== 'extension.analytics.people') {
      throw new Error(`Unexpected People Analytics feature key: ${people.featureKey}`);
    }
    const feedback = await requestJson(`${BASE_URL}/api/extensions/foundation/continuous_feedback/stats`, {
      headers: authHeaders(auth, `${runId}-feedback-stats`),
    });
    if (feedback.featureKey !== 'extension.foundation.continuous_feedback') {
      throw new Error(`Unexpected continuous feedback feature key: ${feedback.featureKey}`);
    }
    const talent = await requestJson(`${BASE_URL}/api/extensions/talent/profile/summary`, {
      headers: authHeaders(auth, `${runId}-talent-profile`),
    });
    if (talent.featureKey !== 'extension.talent.profile') {
      throw new Error(`Unexpected talent profile feature key: ${talent.featureKey}`);
    }
    const analytics = await requestJson(`${BASE_URL}/api/extensions/analytics/basic_bi/summary`, {
      headers: authHeaders(auth, `${runId}-analytics-basic-bi`),
    });
    if (analytics.featureKey !== 'extension.analytics.basic_bi') {
      throw new Error(`Unexpected Analytics Suite feature key: ${analytics.featureKey}`);
    }
    const intelligence = await requestJson(`${BASE_URL}/api/extensions/intelligence/predictive/summary`, {
      headers: authHeaders(auth, `${runId}-intelligence-predictive`),
    });
    if (intelligence.featureKey !== 'extension.intelligence.predictive') {
      throw new Error(`Unexpected Intelligence Suite feature key: ${intelligence.featureKey}`);
    }
    const collaboration = await requestJson(`${BASE_URL}/api/extensions/collaboration/okr/summary`, {
      headers: authHeaders(auth, `${runId}-collaboration-okr`),
    });
    if (collaboration.featureKey !== 'extension.collaboration.okr') {
      throw new Error(`Unexpected Collaboration Suite feature key: ${collaboration.featureKey}`);
    }
    const workforce = await requestJson(`${BASE_URL}/api/extensions/workforce/smart_scheduling/summary`, {
      headers: authHeaders(auth, `${runId}-workforce-smart-scheduling`),
    });
    if (workforce.featureKey !== 'extension.workforce.smart_scheduling') {
      throw new Error(`Unexpected Workforce Suite feature key: ${workforce.featureKey}`);
    }
    const integration = await requestJson(`${BASE_URL}/api/extensions/integration/open_api/summary`, {
      headers: authHeaders(auth, `${runId}-integration-open-api`),
    });
    if (integration.featureKey !== 'extension.integration.open_api') {
      throw new Error(`Unexpected Integration Suite feature key: ${integration.featureKey}`);
    }
    const mobile = await requestJson(`${BASE_URL}/api/extensions/mobile/self_service/summary`, {
      headers: authHeaders(auth, `${runId}-mobile-self-service`),
    });
    if (mobile.featureKey !== 'extension.mobile.self_service') {
      throw new Error(`Unexpected Mobile Suite feature key: ${mobile.featureKey}`);
    }
    const security = await requestJson(`${BASE_URL}/api/extensions/security/data_masking/summary`, {
      headers: authHeaders(auth, `${runId}-security-data-masking`),
    });
    if (security.featureKey !== 'extension.security.data_masking') {
      throw new Error(`Unexpected Security Suite feature key: ${security.featureKey}`);
    }

    return {
      ok: true,
      pages,
      featureKeys: [
        people.featureKey,
        feedback.featureKey,
        talent.featureKey,
        analytics.featureKey,
        intelligence.featureKey,
        collaboration.featureKey,
        workforce.featureKey,
        integration.featureKey,
        mobile.featureKey,
        security.featureKey,
      ],
    };
  } finally {
    await page.close().catch(() => null);
  }
}

async function main() {
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const hrmResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  const tenantId = hrmResult.auth.user?.tenantId;
  if (!tenantId) throw new Error('Tenant id missing from HRM auth for extension browser verification');

  const platformAuth = await loginPlatformAdmin();
  const originalModules = await tenantModules(hrmResult.auth);
  const enabledModules = withEnabledExtensions(originalModules);
  await syncTenantModules(platformAuth, tenantId, enabledModules);

  const { chromium } = await importPlaywright();
  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await addAuthToContext(context, hrmResult.auth);

  let result;
  try {
    result = await verifyExtensionNavigation(context, hrmResult.auth);
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
    await syncTenantModules(platformAuth, tenantId, originalModules).catch(() => null);
  }

  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const report = {
    ok: Boolean(result?.ok),
    runId,
    baseUrl: BASE_URL,
    tenantSlug: hrmResult.credentials.tenantSlug,
    checkedAt: new Date().toISOString(),
    enabledModules: extensionModuleKeys,
    result,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    enabledModules: extensionModuleKeys,
    pages: result?.pages?.map((page) => page.route) || [],
    reportPath,
  }, null, 2));

  return report.ok ? 0 : 1;
}

main().then((code) => {
  process.exitCode = code;
}).catch((error) => {
  console.error(compact(error?.stack || error?.message || String(error)));
  process.exitCode = 1;
});
