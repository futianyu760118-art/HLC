import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
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
const TRACE_TIMEOUT_MS = Number(process.env.HRM_AI_MODEL_TRACE_TIMEOUT_MS || 45000);
const LOGIN_SPACING_MS = Number(process.env.HRM_AI_MODEL_TRACE_LOGIN_SPACING_MS || 1200);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_AI_MODEL_TRACE_RUN_ID || `ai-model-settings-request-trace-${stamp}`;

const DEFAULT_CONFIRM_REPORT_PATTERN = /^assistant-confirm-\d{14}\.json$/;
const DEFAULT_PERMISSION_REPORT_PATTERN = /^assistant-ui-write-permission-\d{14}\.json$/;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run AI model settings trace gate against old production ports', { baseUrl: BASE_URL });
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

const parseJsonFile = async (filePath) => JSON.parse(await readFile(filePath, 'utf8'));

const listArtifactReports = async (pattern) => {
  const entries = await readdir(ARTIFACT_DIR, { withFileTypes: true }).catch(() => []);
  const reports = [];
  for (const entry of entries) {
    if (!entry.isFile() || !pattern.test(entry.name)) continue;
    const filePath = path.join(ARTIFACT_DIR, entry.name);
    try {
      const report = await parseJsonFile(filePath);
      reports.push({ filePath, report });
    } catch {
      // Ignore partial or invalid artifacts.
    }
  }
  return reports.sort((a, b) => String(b.report?.checkedAt || b.report?.runId || '').localeCompare(String(a.report?.checkedAt || a.report?.runId || '')));
};

const hasUsableConfirmTrace = (report) => (
  Boolean(report?.requestIds?.draft && report?.requestIds?.confirmed)
  && report?.audits?.draft?.provider === 'siliconflow'
  && String(report?.audits?.draft?.model || '').includes('DeepSeek')
  && report?.audits?.draft?.status === 'success'
  && Number(report?.audits?.draft?.chunkCount || report?.audits?.draft?.responseMeta?.chunkCount || 0) > 0
  && report?.audits?.confirmed?.model === 'deterministic-confirmed-action-receipt'
  && report?.audits?.confirmed?.skippedProviderCall === true
);

const hasUsablePermissionTrace = (report) => (
  Array.isArray(report?.results)
  && report.results.some((item) => (
    item?.requestId
    && item?.audit?.model === 'deterministic-permission-denied-receipt'
    && item?.audit?.skippedProviderCall === true
    && item?.audit?.reason === 'permission_denied_receipt'
  ))
);

const findLatestUsableReport = async ({ envPath, pattern, predicate, label }) => {
  if (envPath) {
    if (!existsSync(envPath)) fail(`${label} report env path does not exist`, { envPath });
    const report = await parseJsonFile(envPath);
    if (!predicate(report)) fail(`${label} report env path is not usable for trace verification`, { envPath, report });
    return { filePath: envPath, report };
  }
  const candidates = await listArtifactReports(pattern);
  const found = candidates.find((item) => predicate(item.report));
  if (!found) {
    fail(`No usable ${label} report found; set HRM_AUDIT_REQUEST_ID or ${label === 'confirm' ? 'HRM_CONFIRM_REPORT' : 'HRM_PERMISSION_REPORT'}`, {
      artifactDir: ARTIFACT_DIR,
      candidateCount: candidates.length,
    });
  }
  return found;
};

const resolveTraceCases = async () => {
  const envCases = [
    {
      key: 'envTrace',
      requestId: process.env.HRM_AUDIT_REQUEST_ID,
      expectedModel: process.env.HRM_AUDIT_EXPECTED_MODEL,
      expectedCallType: process.env.HRM_AUDIT_EXPECTED_CALL_TYPE,
      expectedReason: process.env.HRM_AUDIT_EXPECTED_REASON,
    },
  ].filter((item) => item.requestId);
  if (envCases.length) return envCases;

  const confirmSource = await findLatestUsableReport({
    envPath: process.env.HRM_CONFIRM_REPORT,
    pattern: DEFAULT_CONFIRM_REPORT_PATTERN,
    predicate: hasUsableConfirmTrace,
    label: 'confirm',
  });
  const permissionSource = await findLatestUsableReport({
    envPath: process.env.HRM_PERMISSION_REPORT,
    pattern: DEFAULT_PERMISSION_REPORT_PATTERN,
    predicate: hasUsablePermissionTrace,
    label: 'permission',
  });
  const confirm = confirmSource.report;
  const permission = permissionSource.report;
  const permissionCase = (permission.results || []).find((item) => item.audit?.model === 'deterministic-permission-denied-receipt')
    || (permission.results || [])[0];

  return [
    {
      key: 'realDeepSeekDraft',
      requestId: confirm.requestIds?.draft,
      expectedModel: 'deepseek-ai/DeepSeek-V4-Pro',
      expectedCallType: '真实模型',
      expectedUseCase: 'assistant_stream_answer',
      expectedStatus: 'success',
      expectedText: ['DeepSeek', '真实模型', '流式'],
    },
    {
      key: 'confirmedActionReceipt',
      requestId: confirm.requestIds?.confirmed,
      expectedModel: 'deterministic-confirmed-action-receipt',
      expectedCallType: '系统回执',
      expectedUseCase: 'assistant_stream_answer',
      expectedStatus: 'success',
      expectedReason: '确认回执',
      expectedText: ['系统回执', '跳过 provider', '确认回执'],
    },
    {
      key: 'permissionDeniedReceipt',
      requestId: permissionCase?.requestId,
      expectedModel: 'deterministic-permission-denied-receipt',
      expectedCallType: '系统回执',
      expectedUseCase: 'assistant_stream_answer',
      expectedStatus: 'success',
      expectedReason: '权限短路',
      expectedText: ['系统回执', '跳过 provider', '权限短路'],
    },
  ].filter((item) => item.requestId);
};

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

const fetchAuditByRequestId = async (token, requestId) => {
  const rows = await requestJson(
    'GET',
    `/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(requestId)}&limit=20`,
    null,
    token,
    `${runId}-audit-${sanitize(requestId)}`,
  );
  const row = rows.find((item) => item.requestId === requestId && item.useCase === 'assistant_stream_answer');
  if (!row) fail('API audit lookup did not find requestId', { requestId, rows });
  return row;
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

const assertApiAudit = (row, traceCase) => {
  if (traceCase.expectedModel && row.model !== traceCase.expectedModel) {
    fail('API audit model mismatch', { traceCase, row });
  }
  if (traceCase.expectedUseCase && row.useCase !== traceCase.expectedUseCase) {
    fail('API audit useCase mismatch', { traceCase, row });
  }
  if (traceCase.expectedStatus && row.status !== traceCase.expectedStatus) {
    fail('API audit status mismatch', { traceCase, row });
  }
  if (traceCase.expectedCallType === '真实模型' && row.responseMeta?.skippedProviderCall === true) {
    fail('Real model trace unexpectedly marked skippedProviderCall', { traceCase, row });
  }
  if (traceCase.expectedCallType === '系统回执' && row.responseMeta?.skippedProviderCall !== true) {
    fail('System receipt trace did not mark skippedProviderCall', { traceCase, row });
  }
};

const runTraceCase = async ({ page, token, traceCase }) => {
  const apiAudit = await fetchAuditByRequestId(token, traceCase.requestId);
  assertApiAudit(apiAudit, traceCase);

  await page.goto(`${BASE_URL}/ai-model-settings?keyword=${encodeURIComponent(traceCase.requestId)}`, {
    waitUntil: 'networkidle',
    timeout: 30000,
  });
  await page.waitForSelector('text=AI 模型管理', { timeout: 20000 });
  const keywordInput = page.locator('input[placeholder*="搜索请求"], input[placeholder*="搜索"]').last();
  if (await keywordInput.count()) {
    await keywordInput.fill('');
    await keywordInput.type(traceCase.requestId, { delay: 2 });
    await page.getByRole('button', { name: /刷新/ }).last().click();
  }

  const bodyText = await waitForBodyText(
    page,
    (text) => text.includes(traceCase.requestId)
      && (!traceCase.expectedModel || text.includes(traceCase.expectedModel))
      && (!traceCase.expectedCallType || text.includes(traceCase.expectedCallType)),
    `${traceCase.key} audit row`,
  );
  for (const item of traceCase.expectedText || []) {
    if (!bodyText.includes(item)) fail('AI model settings page is missing trace text', { traceCase, missing: item });
  }

  const rowScreenshot = path.join(ARTIFACT_DIR, `${runId}-${sanitize(traceCase.key)}-row.png`);
  await page.screenshot({ path: rowScreenshot, fullPage: true }).catch(() => null);

  const detailButton = page.locator('button:has-text("详情")').first();
  await detailButton.click({ timeout: 10000 });
  const detailText = await waitForBodyText(
    page,
    (text) => text.includes('审计详情')
      && text.includes(traceCase.requestId)
      && (!traceCase.expectedModel || text.includes(traceCase.expectedModel))
      && (!traceCase.expectedReason || text.includes(traceCase.expectedReason)),
    `${traceCase.key} audit detail`,
  );
  const detailScreenshot = path.join(ARTIFACT_DIR, `${runId}-${sanitize(traceCase.key)}-detail.png`);
  await page.screenshot({ path: detailScreenshot, fullPage: true }).catch(() => null);
  await page.locator('button:has(.fa-times)').first().click({ timeout: 10000 }).catch(() => null);

  return {
    ok: true,
    key: traceCase.key,
    requestId: traceCase.requestId,
    expectedModel: traceCase.expectedModel,
    expectedCallType: traceCase.expectedCallType,
    apiAudit: {
      id: apiAudit.id,
      provider: apiAudit.provider,
      model: apiAudit.model,
      modelProfile: apiAudit.modelProfile,
      useCase: apiAudit.useCase,
      status: apiAudit.status,
      responseMeta: apiAudit.responseMeta || {},
    },
    uiEvidence: {
      rowContainsRequestId: bodyText.includes(traceCase.requestId),
      rowContainsCallType: traceCase.expectedCallType ? bodyText.includes(traceCase.expectedCallType) : null,
      detailContainsRequestId: detailText.includes(traceCase.requestId),
      detailContainsReason: traceCase.expectedReason ? detailText.includes(traceCase.expectedReason) : null,
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
  const traceCases = await resolveTraceCases();
  if (!traceCases.length) fail('No trace cases resolved');
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const auth = await loginApi();
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
        console.log(`PASS ${traceCase.key} ${traceCase.requestId}`);
      } catch (error) {
        const failure = {
          ok: false,
          key: traceCase.key,
          requestId: traceCase.requestId,
          error: error?.stack || error?.message || String(error),
        };
        failures.push(failure);
        results.push(failure);
        console.log(`FAIL ${traceCase.key} ${traceCase.requestId || ''}`);
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
    requestIds: results.filter((item) => item.requestId).map((item) => item.requestId),
    failures,
  }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
