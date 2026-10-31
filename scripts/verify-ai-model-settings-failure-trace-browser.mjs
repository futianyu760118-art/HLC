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
const TRACE_TIMEOUT_MS = Number(process.env.HRM_AI_MODEL_FAILURE_TRACE_TIMEOUT_MS || 45000);
const LOGIN_SPACING_MS = Number(process.env.HRM_AI_MODEL_FAILURE_TRACE_LOGIN_SPACING_MS || 1200);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_AI_MODEL_FAILURE_TRACE_RUN_ID || `ai-model-settings-failure-trace-${stamp}`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run AI model settings failure trace gate against old production ports', { baseUrl: BASE_URL });
  }
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

const sanitize = (value) => String(value || '')
  .replace(/[^a-z0-9_-]+/gi, '-')
  .replace(/^-|-$/g, '')
  .slice(0, 80);

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const requestJson = async (method, pathName, payload, token, requestId, options = {}) => {
  const response = await fetch(`${BASE_URL}${pathName}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
    body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
  });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    if (response.status === 429 && options.allowRateLimit) {
      return { __rateLimited: true, status: response.status, body: text.slice(0, 1000) };
    }
    fail(`${method} ${pathName} did not return JSON`, text.slice(0, 1000));
  }
  if (!response.ok) fail(`${method} ${pathName} failed with HTTP ${response.status}`, data);
  return data;
};

const loginApi = async () => {
  let payload;
  for (let attempt = 1; attempt <= 8; attempt += 1) {
    payload = await requestJson(
      'POST',
      '/api/auth/login',
      { email: EMAIL, password: PASSWORD },
      null,
      `${runId}-login-${attempt}`,
      { allowRateLimit: true },
    );
    if (!payload.__rateLimited) break;
    await sleep(LOGIN_SPACING_MS * attempt);
  }
  if (payload?.__rateLimited) fail('Login kept hitting rate limit', payload);
  if (!payload.token || !payload.user) fail('Login did not return token/user', payload);
  return payload;
};

const fetchAuditRows = async (token, status) => requestJson(
  'GET',
  `/api/hrm/assistant/audit-logs?status=${encodeURIComponent(status)}&limit=20`,
  null,
  token,
  `${runId}-list-${status}`,
);

const fetchAuditDetail = async (token, id) => requestJson(
  'GET',
  `/api/hrm/assistant/audit-logs/${encodeURIComponent(id)}`,
  null,
  token,
  `${runId}-detail-${sanitize(id)}`,
);

const resolveFailureTraceCases = async (token) => {
  const requestedId = process.env.HRM_FAILURE_AUDIT_REQUEST_ID;
  if (requestedId) {
    const rows = await requestJson(
      'GET',
      `/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(requestedId)}&limit=20`,
      null,
      token,
      `${runId}-lookup-${sanitize(requestedId)}`,
    );
    const row = rows.find((item) => item.requestId === requestedId);
    if (!row) fail('Requested failure audit requestId was not found', { requestedId });
    return [{ key: row.status === 'timeout' ? 'timeoutAudit' : 'errorAudit', row }];
  }

  const timeoutRows = await fetchAuditRows(token, 'timeout');
  const errorRows = await fetchAuditRows(token, 'error');
  const timeoutRow = timeoutRows.find((item) => item.requestId && item.status === 'timeout' && item.errorMessage);
  const errorRow = errorRows.find((item) => item.requestId && item.status === 'error' && item.errorMessage);
  const cases = [
    timeoutRow ? { key: 'timeoutAudit', row: timeoutRow } : null,
    errorRow ? { key: 'errorAudit', row: errorRow } : null,
  ].filter(Boolean);
  if (!cases.length) {
    fail('No existing error or timeout audit rows found; this gate verifies real historical abnormal audits and does not synthesize failures', {
      timeoutCount: timeoutRows.length,
      errorCount: errorRows.length,
    });
  }
  return cases;
};

const waitForBodyText = async (page, predicate, label) => {
  const deadline = Date.now() + TRACE_TIMEOUT_MS;
  let text = '';
  while (Date.now() < deadline) {
    text = compact(await page.locator('body').innerText({ timeout: 5000 }).catch(() => ''));
    if (predicate(text)) return text;
    await page.waitForTimeout(800);
  }
  fail(`Timed out waiting for ${label}`, { textSample: text.slice(0, 1600) });
};

const expectedCallType = (status) => (status === 'timeout' ? '模型超时' : '模型失败');

const expectedFailureLabel = (status) => (status === 'timeout' ? 'provider 超时' : 'provider 失败');

const assertApiAudit = async (token, traceCase) => {
  const detail = await fetchAuditDetail(token, traceCase.row.id);
  if (!['error', 'timeout'].includes(detail.status)) fail('Failure trace row is not abnormal', detail);
  if (!detail.errorMessage) fail('Failure trace row does not expose an errorMessage', detail);
  if (detail.responseMeta?.skippedProviderCall === true) fail('Failure trace unexpectedly marked skippedProviderCall', detail);
  if (!String(detail.model || '').includes('DeepSeek')) fail('Failure trace does not reference a DeepSeek model', detail);
  return detail;
};

const runTraceCase = async ({ page, token, traceCase }) => {
  const apiAudit = await assertApiAudit(token, traceCase);
  const callType = expectedCallType(apiAudit.status);
  const failureLabel = expectedFailureLabel(apiAudit.status);

  await page.goto(`${BASE_URL}/ai-model-settings?keyword=${encodeURIComponent(apiAudit.requestId)}`, {
    waitUntil: 'networkidle',
    timeout: 30000,
  });
  await page.waitForSelector('text=AI 模型管理', { timeout: 20000 });
  const keywordInput = page.locator('input[placeholder*="搜索请求"], input[placeholder*="搜索"]').last();
  if (await keywordInput.count()) {
    await keywordInput.fill('');
    await keywordInput.type(apiAudit.requestId, { delay: 2 });
    await page.getByRole('button', { name: /刷新/ }).last().click();
  }

  const rowText = await waitForBodyText(
    page,
    (text) => text.includes(apiAudit.requestId)
      && text.includes(apiAudit.model)
      && text.includes(callType)
      && text.includes(failureLabel)
      && text.includes(apiAudit.errorMessage),
    `${traceCase.key} audit row`,
  );

  const rowScreenshot = path.join(ARTIFACT_DIR, `${runId}-${sanitize(traceCase.key)}-row.png`);
  await page.screenshot({ path: rowScreenshot, fullPage: true }).catch(() => null);

  await page.locator('button:has-text("详情")').first().click({ timeout: 10000 });
  const detailText = await waitForBodyText(
    page,
    (text) => text.includes('审计详情')
      && text.includes(apiAudit.requestId)
      && text.includes(apiAudit.model)
      && text.includes(callType)
      && text.includes(failureLabel)
      && text.includes('异常原因')
      && text.includes(apiAudit.errorMessage),
    `${traceCase.key} audit detail`,
  );
  const detailScreenshot = path.join(ARTIFACT_DIR, `${runId}-${sanitize(traceCase.key)}-detail.png`);
  await page.screenshot({ path: detailScreenshot, fullPage: true }).catch(() => null);
  await page.locator('button:has(.fa-times)').first().click({ timeout: 10000 }).catch(() => null);

  return {
    ok: true,
    key: traceCase.key,
    requestId: apiAudit.requestId,
    expectedCallType: callType,
    expectedFailureLabel: failureLabel,
    apiAudit: {
      id: apiAudit.id,
      provider: apiAudit.provider,
      model: apiAudit.model,
      modelProfile: apiAudit.modelProfile,
      useCase: apiAudit.useCase,
      status: apiAudit.status,
      errorMessage: apiAudit.errorMessage,
      latencyMs: apiAudit.latencyMs,
      responseMeta: apiAudit.responseMeta || {},
    },
    uiEvidence: {
      rowContainsRequestId: rowText.includes(apiAudit.requestId),
      rowContainsCallType: rowText.includes(callType),
      rowContainsFailureLabel: rowText.includes(failureLabel),
      rowContainsErrorMessage: rowText.includes(apiAudit.errorMessage),
      detailContainsRequestId: detailText.includes(apiAudit.requestId),
      detailContainsFailureLabel: detailText.includes(failureLabel),
      detailContainsErrorMessage: detailText.includes(apiAudit.errorMessage),
    },
    screenshots: {
      row: rowScreenshot,
      detail: detailScreenshot,
    },
  };
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const auth = await loginApi();
  const traceCases = await resolveFailureTraceCases(auth.token);
  const { chromium } = await importPlaywright();
  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
  }, { token: auth.token, user: auth.user });

  const results = [];
  const failures = [];
  try {
    await page.goto(`${BASE_URL}/ai-model-settings`, { waitUntil: 'networkidle', timeout: 30000 });
    for (const traceCase of traceCases) {
      try {
        const result = await runTraceCase({ page, token: auth.token, traceCase });
        results.push(result);
        console.log(`PASS ${traceCase.key} ${traceCase.row.requestId}`);
      } catch (error) {
        const failure = {
          ok: false,
          key: traceCase.key,
          requestId: traceCase.row?.requestId,
          error: error?.stack || error?.message || String(error),
        };
        failures.push(failure);
        results.push(failure);
        console.log(`FAIL ${traceCase.key} ${traceCase.row?.requestId || ''}`);
      }
    }
  } finally {
    await browser.close().catch(() => null);
  }

  const report = {
    ok: failures.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    protectedPorts: ['8080', '8443'],
    modelPolicy: {
      usesExistingAbnormalAudits: true,
      doesNotTriggerProviderCalls: true,
      note: 'This gate verifies UI traceability for existing error/timeout audit rows. It does not synthesize model failures or trigger new LLM calls.',
    },
    caseCount: results.length,
    passed: results.length - failures.length,
    failed: failures.length,
    reportPath,
    results,
    failures,
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
  }, null, 2));
  if (failures.length) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
