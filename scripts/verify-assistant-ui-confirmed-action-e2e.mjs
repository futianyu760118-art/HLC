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
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_CONFIRM_CASE_TIMEOUT_MS || 180000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_CONFIRM_RUN_ID || `assistant-confirm-${stamp}`;
const question = process.env.HRM_ASSISTANT_CONFIRM_QUESTION || '帮我给本月迟到最多的5个人生成提醒';

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  if (/:(8080|8443)(?:\/|$)/.test(BASE_URL)) {
    fail('Refusing to run side-effect E2E against old production ports', { baseUrl: BASE_URL });
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
const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const sanitize = (value) => String(value).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);
const toArray = (payload) => Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];

const login = async () => {
  const response = await postJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, {
    'X-Request-ID': `${runId}-login`,
  });
  const payload = await asJson(response, 'login');
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  return payload;
};

const createAssistantSession = async (token) => {
  const response = await postJson('/api/hrm/assistant/sessions/new', {}, {
    Authorization: `Bearer ${token}`,
    'X-Request-ID': `${runId}-new-session`,
  });
  const payload = await asJson(response, 'assistant new session');
  if (!payload.id) fail('Assistant new session did not return an id', payload);
  return payload;
};

const listNotifications = async (token) => toArray(await getJson(
  '/api/hrm/notifications',
  token,
  `${runId}-notifications-${Date.now()}`,
));

const listOperationLogs = async (token) => toArray(await getJson(
  '/api/hrm/operation-logs',
  token,
  `${runId}-operation-logs-${Date.now()}`,
));

const byNewIds = (beforeRows, afterRows) => {
  const beforeIds = new Set(beforeRows.map((row) => row.id).filter(Boolean));
  return afterRows.filter((row) => row.id && !beforeIds.has(row.id));
};

const fetchAuditRow = async (token, requestId) => {
  const encoded = encodeURIComponent(requestId);
  for (let attempt = 1; attempt <= 16; attempt += 1) {
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

const isDeterministicReceiptAudit = (row) => (
  String(row?.model || '') === 'deterministic-confirmed-action-receipt'
  || row?.responseMeta?.deterministicReceipt === true
);

const verifyAuditRow = (row, label, options = {}) => {
  const meta = row.responseMeta || {};
  if (row.provider !== 'siliconflow') fail(`${label} audit provider is not siliconflow`, row);
  const deterministicReceipt = isDeterministicReceiptAudit(row);
  if (options.requireRealModel && deterministicReceipt) {
    fail(`${label} audit used deterministic receipt but a real model call is required`, row);
  }
  if (row.status !== 'success') fail(`${label} audit status is not success`, row);
  if (deterministicReceipt) {
    if (meta.skippedProviderCall !== true) fail(`${label} deterministic receipt audit did not mark skippedProviderCall`, row);
  } else if (!row.model || !String(row.model).includes('DeepSeek')) {
    fail(`${label} audit model is neither DeepSeek nor deterministic confirmed-action receipt`, row);
  }
  if (meta.stream !== true) fail(`${label} audit responseMeta.stream is not true`, row);
  if (!(Number(meta.chunkCount) > 0)) fail(`${label} audit has no positive chunkCount`, row);
  return deterministicReceipt ? 'deterministic_receipt' : 'real_model';
};

const auditSummary = (row) => ({
  id: row.id,
  provider: row.provider,
  model: row.model,
  status: row.status,
  useCase: row.useCase,
  errorMessage: row.errorMessage,
  chunkCount: row.responseMeta?.chunkCount,
  deterministicReceipt: row.responseMeta?.deterministicReceipt === true,
  skippedProviderCall: row.responseMeta?.skippedProviderCall === true,
  responseMeta: row.responseMeta || {},
});

const queryCount = async (locator) => locator.count().catch(() => 0);

const panelSnapshot = async (panel) => {
  const text = await panel.innerText({ timeout: 5000 }).catch(() => '');
  return {
    text: compact(text),
    tableCount: await queryCount(panel.locator('table')),
    confirmationButtonCount: await queryCount(panel.locator('button:has-text("确认执行")')),
    sourceButtonCount: await queryCount(panel.locator('button:has-text("证据"), button:has-text("来源"), button:has-text("通知")')),
    loadingCount: await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin')),
  };
};

const waitForDraftUi = async (panel) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes('发送考勤迟到提醒')
      && last.text.includes('待发送提醒草稿')
      && last.text.includes('确认执行')
      && last.text.includes('取消')
      && last.tableCount >= 1
      && last.confirmationButtonCount >= 1
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail('Assistant did not render the confirmation draft UI', {
    snapshot: last,
    textSample: last?.text?.slice(0, 1200),
  });
};

const waitForAssistantIdle = async (panel, label) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    if (last.loadingCount === 0) return last;
    await sleep(1000);
  }
  fail(`${label} assistant UI stayed loading`, {
    snapshot: last,
    textSample: last?.text?.slice(0, 1200),
  });
};

const waitForNotificationDelta = async (token, beforeRows, minDelta, label) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let afterRows = [];
  let newRows = [];
  while (Date.now() < deadline) {
    afterRows = await listNotifications(token);
    newRows = byNewIds(beforeRows, afterRows).filter((row) => String(row.title || '').includes('考勤迟到提醒'));
    if (newRows.length >= minDelta) return { afterRows, newRows };
    await sleep(1000);
  }
  fail(`${label} did not create the expected attendance reminder notifications`, {
    beforeCount: beforeRows.length,
    afterCount: afterRows.length,
    newRows,
  });
};

const waitForOperationLogs = async (token, beforeRows, newNotifications, confirmRequestId) => {
  const notificationIds = new Set(newNotifications.map((row) => row.id).filter(Boolean));
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let afterRows = [];
  let relatedLogs = [];
  while (Date.now() < deadline) {
    afterRows = await listOperationLogs(token);
    relatedLogs = byNewIds(beforeRows, afterRows).filter((row) => (
      row.module === 'notifications'
      && row.action === 'ai_confirm_create'
      && (notificationIds.has(row.targetId) || row.detail?.requestId === confirmRequestId)
    ));
    if (relatedLogs.length >= newNotifications.length) return { afterRows, relatedLogs };
    await sleep(1000);
  }
  fail('Confirmed notification writes did not create matching operation audit logs', {
    expectedNotificationIds: [...notificationIds],
    confirmRequestId,
    relatedLogs,
  });
};

const parseAssistantRequest = (request) => {
  try {
    return JSON.parse(request.postData() || '{}');
  } catch {
    return {};
  }
};

const waitForAssistantRequest = (page, predicate, label) => page.waitForRequest((request) => {
  if (request.method() !== 'POST') return false;
  if (!request.url().includes('/api/hrm/assistant/query')) return false;
  return predicate(parseAssistantRequest(request));
}, { timeout: 20000 }).catch((error) => {
  fail(`Timed out waiting for ${label} assistant request`, error?.message || String(error));
});

const requestIdFrom = (request, label) => {
  const requestId = request.headers()['x-request-id'];
  if (!requestId) fail(`${label} request did not include X-Request-ID`, { url: request.url() });
  return requestId;
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();
  const assistantSession = await createAssistantSession(auth.token);

  const beforeNotifications = await listNotifications(auth.token);
  const beforeOperationLogs = await listOperationLogs(auth.token);

  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ token, user, sessionId }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.startsWith('ai_assistant_')) store.removeItem(key);
      }
    }
    window.localStorage.setItem(`ai_assistant_session:user:${user.id}`, sessionId);
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user, sessionId: assistantSession.id });

  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && !/favicon\.ico|ResizeObserver loop|net::ERR_ABORTED/i.test(message.text())) {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error?.stack || error?.message || String(error)));

  let result;
  try {
    await page.goto(`${BASE_URL}/attendance-stats`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('main.hpt-main', { timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);

    await page.locator('.hpt-ai-assistant-toggle').click({ timeout: 10000 });
    const panel = page.locator('.hpt-ai-assistant-panel');
    await panel.waitFor({ state: 'visible', timeout: 10000 });
    const textarea = panel.locator('textarea').first();
    await textarea.fill(question, { timeout: 10000 });

    const prepareRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && payload.question === question,
      'confirmation draft',
    );
    await textarea.press('Enter', { timeout: 10000 });
    const prepareRequest = await prepareRequestPromise;
    const prepareRequestId = requestIdFrom(prepareRequest, 'confirmation draft');

    const draftUi = await waitForDraftUi(panel);
    const draftNotifications = await listNotifications(auth.token);
    if (draftNotifications.length !== beforeNotifications.length) {
      fail('Confirmation draft unexpectedly wrote notifications before user confirmation', {
        before: beforeNotifications.length,
        after: draftNotifications.length,
        prepareRequestId,
      });
    }
    const draftScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-draft.png`);
    await page.screenshot({ path: draftScreenshotPath, fullPage: true }).catch(() => null);

    const confirmButtons = panel.locator('button:has-text("确认执行")');
    const confirmButtonCount = await confirmButtons.count();
    if (confirmButtonCount < 1) fail('No visible confirmation button found before executing action');

    const confirmRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && String(payload.question || '').startsWith('确认执行动作：act_'),
      'confirmed action',
    );
    await confirmButtons.first().click({ timeout: 10000 });
    const confirmRequest = await confirmRequestPromise;
    const confirmPayload = parseAssistantRequest(confirmRequest);
    const confirmQuestion = String(confirmPayload.question || '');
    const confirmRequestId = requestIdFrom(confirmRequest, 'confirmed action');
    const actionId = confirmQuestion.match(/确认执行动作[：:]([A-Za-z0-9_-]+)/)?.[1];
    if (!actionId) fail('Confirmed action payload did not include an action id', { confirmQuestion });

    const notificationResult = await waitForNotificationDelta(auth.token, beforeNotifications, 1, 'confirmed action');
    const operationResult = await waitForOperationLogs(
      auth.token,
      beforeOperationLogs,
      notificationResult.newRows,
      confirmRequestId,
    );
    const confirmUi = await waitForAssistantIdle(panel, 'confirmed action');
    const confirmScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-confirmed.png`);
    await page.screenshot({ path: confirmScreenshotPath, fullPage: true }).catch(() => null);

    const duplicateBeforeNotifications = notificationResult.afterRows;
    const duplicateRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && payload.question === confirmQuestion,
      'duplicate confirmed action',
    );
    await panel.locator('button:has-text("确认执行")').first().click({ timeout: 10000 });
    const duplicateRequest = await duplicateRequestPromise;
    const duplicateRequestId = requestIdFrom(duplicateRequest, 'duplicate confirmed action');
    const duplicateUi = await waitForAssistantIdle(panel, 'duplicate confirmed action');
    const duplicateNotifications = await listNotifications(auth.token);
    const duplicateNewRows = byNewIds(duplicateBeforeNotifications, duplicateNotifications)
      .filter((row) => String(row.title || '').includes('考勤迟到提醒'));
    if (duplicateNewRows.length > 0) {
      fail('Duplicate confirmation created notifications after pending action was already consumed', {
        duplicateRequestId,
        duplicateNewRows,
      });
    }
    const duplicateScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-duplicate-confirm.png`);
    await page.screenshot({ path: duplicateScreenshotPath, fullPage: true }).catch(() => null);

    if (consoleErrors.length || pageErrors.length) {
      fail('Assistant confirmed-action UI emitted browser errors', { consoleErrors, pageErrors });
    }

    const prepareAudit = await fetchAuditRow(auth.token, prepareRequestId);
    const confirmAudit = await fetchAuditRow(auth.token, confirmRequestId);
    const duplicateAudit = await fetchAuditRow(auth.token, duplicateRequestId);
    verifyAuditRow(prepareAudit, 'draft', { requireRealModel: true });
    verifyAuditRow(confirmAudit, 'confirmed action');
    verifyAuditRow(duplicateAudit, 'duplicate confirmation');

    result = {
      ok: true,
      runId,
      baseUrl: BASE_URL,
      protectedPorts: ['8080', '8443'],
      isolatedDatabase: 'hengpintong_next',
      question,
      actionId,
      requestIds: {
        draft: prepareRequestId,
        confirmed: confirmRequestId,
        duplicateConfirmation: duplicateRequestId,
      },
      notifications: {
        before: beforeNotifications.length,
        afterDraft: draftNotifications.length,
        afterConfirmed: notificationResult.afterRows.length,
        created: notificationResult.newRows.map((row) => ({
          id: row.id,
          title: row.title,
          noticeType: row.noticeType,
          linkUrl: row.linkUrl,
          createdAt: row.createdAt,
        })),
        duplicateCreated: duplicateNewRows.length,
      },
      operationAudit: {
        created: operationResult.relatedLogs.map((row) => ({
          id: row.id,
          module: row.module,
          action: row.action,
          targetId: row.targetId,
          requestId: row.detail?.requestId,
          createdAt: row.createdAt,
        })),
      },
      uiSignals: {
        draft: {
          tableCount: draftUi.tableCount,
          confirmationButtonCount: draftUi.confirmationButtonCount,
          sourceButtonCount: draftUi.sourceButtonCount,
        },
        confirmed: {
          tableCount: confirmUi.tableCount,
          confirmationButtonCount: confirmUi.confirmationButtonCount,
          sourceButtonCount: confirmUi.sourceButtonCount,
        },
        duplicate: {
          textMatchedExpiredAction: duplicateUi.text.includes('没有找到可执行') || duplicateUi.text.includes('已完成或已过期'),
          tableCount: duplicateUi.tableCount,
        },
      },
      screenshots: {
        draft: draftScreenshotPath,
        confirmed: confirmScreenshotPath,
        duplicateConfirmation: duplicateScreenshotPath,
      },
      audits: {
        draft: auditSummary(prepareAudit),
        confirmed: auditSummary(confirmAudit),
        duplicateConfirmation: auditSummary(duplicateAudit),
      },
      aiModelSettingsLookup: `${BASE_URL}/ai-model-settings?keyword=${encodeURIComponent(confirmRequestId)}`,
    };
  } finally {
    await page.close().catch(() => null);
    await browser.close().catch(() => null);
  }

  await writeFile(reportPath, `${JSON.stringify({ ...result, reportPath, checkedAt: new Date().toISOString() }, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({
    ok: true,
    runId,
    reportPath,
    requestIds: result.requestIds,
    notifications: {
      before: result.notifications.before,
      afterDraft: result.notifications.afterDraft,
      afterConfirmed: result.notifications.afterConfirmed,
      created: result.notifications.created.length,
      duplicateCreated: result.notifications.duplicateCreated,
    },
    operationAuditRows: result.operationAudit.created.length,
    aiModelSettingsKeyword: result.requestIds.confirmed,
    screenshots: result.screenshots,
  }, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
