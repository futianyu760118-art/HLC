import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const PLAYWRIGHT_MODULE_DIR = process.env.NODE_REPL_NODE_MODULE_DIRS
  || 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PLAYWRIGHT_PNPM_MODULE_DIR = process.env.PLAYWRIGHT_PNPM_MODULE_DIR
  || path.join(PLAYWRIGHT_MODULE_DIR, '.pnpm', 'playwright@1.60.0', 'node_modules');
const EDGE_EXECUTABLE = process.env.HRM_BROWSER_EXECUTABLE
  || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_UI_CASE_TIMEOUT_MS || 140000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_UI_RUN_ID || `assistant-ui-${stamp}`;

const ALL_CASES = [
  {
    id: 'ui_attendance_employee_evidence',
    path: '/attendance-stats',
    question: '吴明华最近考勤异常吗？请给证据，并说明相关入口。',
    expectedText: ['吴明华', '证据来源', '执行过程', '考勤统计'],
    expectedAnyText: ['异常', '迟到', '缺卡', '考勤'],
    minTables: 1,
    minSourceButtons: 1,
  },
  {
    id: 'ui_recruitment_match_matrix',
    path: '/job-manage',
    question: '电子工程师岗位最近候选人谁更合适？给对比矩阵',
    expectedText: ['电子工程师', '证据来源', '执行过程'],
    expectedAnyText: ['邓浩', '杨琳', '罗伟'],
    minTables: 1,
    minActionButtons: 1,
  },
  {
    id: 'ui_attendance_notification_confirmation',
    path: '/attendance-stats',
    question: '帮我给本月迟到最多的5个人生成提醒',
    expectedText: ['发送考勤迟到提醒', '确认执行', '取消', '待发送提醒草稿', '证据来源'],
    expectedAnyText: ['确认后', '提醒草稿', '迟到'],
    minTables: 1,
    minConfirmationButtons: 1,
    assertNoNotificationWrite: true,
  },
];

const requested = (process.env.HRM_ASSISTANT_UI_CASE_IDS || '')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);
const CASES = requested.length ? ALL_CASES.filter((item) => requested.includes(item.id)) : ALL_CASES;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const importPlaywright = async () => {
  try {
    return await import('playwright');
  } catch {
    const packageJson = path.join(PLAYWRIGHT_PNPM_MODULE_DIR, 'playwright', 'package.json');
    const runtimeRequire = createRequire(pathToFileURL(packageJson).href);
    return runtimeRequire('playwright');
  }
};

const asJson = async (response, label = response.url) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`${label} did not return JSON`, text.slice(0, 1000));
  }
};

const postJson = async (pathName, payload, headers = {}) => {
  const response = await fetch(`${BASE_URL}${pathName}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`${pathName} failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  return response;
};

const login = async () => {
  const response = await postJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, {
    'X-Request-ID': `${runId}-login`,
  });
  const payload = await asJson(response, 'login');
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  return payload;
};

const getJson = async (pathName, token, requestId) => {
  const response = await fetch(`${BASE_URL}${pathName}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`${pathName} failed with HTTP ${response.status}`, text.slice(0, 1000));
  }
  return asJson(response, pathName);
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const sanitize = (value) => String(value).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const fetchAuditRow = async (token, requestId) => {
  const encoded = encodeURIComponent(requestId);
  for (let attempt = 1; attempt <= 14; attempt += 1) {
    const rows = await getJson(
      `/api/hrm/assistant/audit-logs?keyword=${encoded}&limit=20`,
      token,
      `${runId}-audit-${sanitize(requestId)}-${attempt}`,
    );
    const row = rows.find((item) => item.requestId === requestId && item.useCase === 'assistant_stream_answer');
    if (row) return row;
    await sleep(900);
  }
  fail('No assistant_stream_answer audit row found for UI request', { requestId });
};

const verifyAuditRow = (row) => {
  const meta = row.responseMeta || {};
  if (row.provider !== 'siliconflow') fail('UI assistant audit provider is not siliconflow', row);
  if (row.status !== 'success') fail('UI assistant audit status is not success', row);
  if (!row.model || !String(row.model).includes('DeepSeek')) fail('UI assistant audit model is not a DeepSeek SiliconFlow model', row);
  if (meta.stream !== true) fail('UI assistant audit responseMeta.stream is not true', row);
  if (!(Number(meta.chunkCount) > 0)) fail('UI assistant audit has no positive chunkCount', row);
};

const notificationCount = async (token) => {
  const rows = await getJson('/api/hrm/notifications', token, `${runId}-notifications-${Date.now()}`);
  return Array.isArray(rows) ? rows.length : 0;
};

const queryCount = async (locator) => locator.count().catch(() => 0);

const panelSnapshot = async (panel) => {
  const text = await panel.innerText({ timeout: 5000 }).catch(() => '');
  const tableCount = await queryCount(panel.locator('table'));
  const sourceButtonCount = await queryCount(panel.locator('button:has-text("证据"), button:has-text("来源"), button:has-text("员工"), button:has-text("候选人"), button:has-text("岗位")'));
  const actionButtonCount = await queryCount(panel.locator('button:has-text("安排面试"), button:has-text("分析"), button:has-text("查看关联"), button:has-text("下一步"), button:has-text("确认执行")'));
  const confirmationButtonCount = await queryCount(panel.locator('button:has-text("确认执行")'));
  const loadingCount = await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin'));
  return {
    text: compact(text),
    tableCount,
    sourceButtonCount,
    actionButtonCount,
    confirmationButtonCount,
    loadingCount,
  };
};

const matchesCase = (snapshot, testCase) => {
  const missingText = (testCase.expectedText || []).filter((item) => !snapshot.text.includes(item));
  const matchedAny = !(testCase.expectedAnyText || []).length
    || testCase.expectedAnyText.some((item) => snapshot.text.includes(item));
  const failures = [];
  if (missingText.length) failures.push(`missing_text:${missingText.join('|')}`);
  if (!matchedAny) failures.push(`missing_any_text:${(testCase.expectedAnyText || []).join('|')}`);
  if (testCase.minTables && snapshot.tableCount < testCase.minTables) failures.push(`table_count:${snapshot.tableCount}`);
  if (testCase.minSourceButtons && snapshot.sourceButtonCount < testCase.minSourceButtons) failures.push(`source_button_count:${snapshot.sourceButtonCount}`);
  if (testCase.minActionButtons && snapshot.actionButtonCount < testCase.minActionButtons) failures.push(`action_button_count:${snapshot.actionButtonCount}`);
  if (testCase.minConfirmationButtons && snapshot.confirmationButtonCount < testCase.minConfirmationButtons) failures.push(`confirmation_button_count:${snapshot.confirmationButtonCount}`);
  if (snapshot.loadingCount > 0) failures.push(`still_loading:${snapshot.loadingCount}`);
  return failures;
};

const waitForCaseUi = async (panel, testCase) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  let lastFailures = [];
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    lastFailures = matchesCase(last, testCase);
    if (!lastFailures.length) return { snapshot: last, failures: [] };
    await sleep(1000);
  }
  return { snapshot: last, failures: lastFailures };
};

const parseAssistantRequest = (request) => {
  try {
    return JSON.parse(request.postData() || '{}');
  } catch {
    return {};
  }
};

const runCase = async ({ context, token, testCase }) => {
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  let beforeNotifications = null;
  let afterNotifications = null;

  page.on('console', (message) => {
    if (message.type() === 'error' && !/favicon\.ico|ResizeObserver loop|net::ERR_ABORTED/i.test(message.text())) {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error?.stack || error?.message || String(error)));

  try {
    if (testCase.assertNoNotificationWrite) {
      beforeNotifications = await notificationCount(token);
    }
    await page.goto(`${BASE_URL}${testCase.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('main.hpt-main', { timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);

    await page.locator('.hpt-ai-assistant-toggle').click({ timeout: 10000 });
    const panel = page.locator('.hpt-ai-assistant-panel');
    await panel.waitFor({ state: 'visible', timeout: 10000 });
    const textarea = panel.locator('textarea').first();
    await textarea.fill(testCase.question, { timeout: 10000 });

    const requestPromise = page.waitForRequest((request) => {
      if (request.method() !== 'POST') return false;
      if (!request.url().includes('/api/hrm/assistant/query')) return false;
      const payload = parseAssistantRequest(request);
      return payload.stream === true && payload.question === testCase.question;
    }, { timeout: 15000 });

    await textarea.press('Enter', { timeout: 10000 });
    const assistantRequest = await requestPromise;
    const requestId = assistantRequest.headers()['x-request-id'];
    if (!requestId) fail('UI assistant request did not include X-Request-ID', { caseId: testCase.id });

    const ui = await waitForCaseUi(panel, testCase);
    const screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(testCase.id)}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    if (ui.failures.length) {
      fail('Assistant UI did not render expected rich response', {
        caseId: testCase.id,
        failures: ui.failures,
        requestId,
        screenshotPath,
        textSample: ui.snapshot?.text?.slice(0, 1200),
      });
    }
    if (consoleErrors.length || pageErrors.length) {
      fail('Assistant UI page emitted browser errors', {
        caseId: testCase.id,
        requestId,
        consoleErrors,
        pageErrors,
        screenshotPath,
      });
    }
    if (testCase.assertNoNotificationWrite) {
      afterNotifications = await notificationCount(token);
      if (afterNotifications !== beforeNotifications) {
        fail('Confirmation draft unexpectedly wrote notifications before user confirmation', {
          caseId: testCase.id,
          beforeNotifications,
          afterNotifications,
          requestId,
          screenshotPath,
        });
      }
    }

    const audit = await fetchAuditRow(token, requestId);
    verifyAuditRow(audit);

    return {
      ok: true,
      caseId: testCase.id,
      path: testCase.path,
      question: testCase.question,
      requestId,
      screenshotPath,
      uiSignals: {
        tableCount: ui.snapshot.tableCount,
        sourceButtonCount: ui.snapshot.sourceButtonCount,
        actionButtonCount: ui.snapshot.actionButtonCount,
        confirmationButtonCount: ui.snapshot.confirmationButtonCount,
      },
      notificationCheck: testCase.assertNoNotificationWrite ? {
        before: beforeNotifications,
        after: afterNotifications,
      } : null,
      audit: {
        id: audit.id,
        provider: audit.provider,
        model: audit.model,
        useCase: audit.useCase,
        status: audit.status,
        latencyMs: audit.latencyMs,
        chunkCount: audit.responseMeta?.chunkCount,
      },
    };
  } finally {
    await page.close().catch(() => null);
  }
};

const main = async () => {
  if (!CASES.length) fail('No assistant UI E2E cases selected');
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();

  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.startsWith('ai_assistant_')) store.removeItem(key);
      }
    }
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });

  const results = [];
  const failures = [];
  try {
    for (const testCase of CASES) {
      try {
        const result = await runCase({ context, token: auth.token, testCase });
        results.push(result);
        console.log(`PASS ${testCase.id} ${result.requestId}`);
      } catch (error) {
        const failure = {
          ok: false,
          caseId: testCase.id,
          path: testCase.path,
          question: testCase.question,
          error: error?.stack || error?.message || String(error),
        };
        failures.push(failure);
        results.push(failure);
        console.log(`FAIL ${testCase.id}`);
      }
    }
  } finally {
    await browser.close();
  }

  const report = {
    ok: failures.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    caseCount: CASES.length,
    passed: CASES.length - failures.length,
    failed: failures.length,
    reportPath,
    results,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    caseCount: report.caseCount,
    passed: report.passed,
    failed: report.failed,
    reportPath,
    requestIds: results.filter((item) => item.requestId).map((item) => item.requestId),
    failures,
  }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
