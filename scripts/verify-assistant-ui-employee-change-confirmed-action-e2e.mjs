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
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_CHANGE_CONFIRM_CASE_TIMEOUT_MS || 180000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_CHANGE_CONFIRM_RUN_ID || `assistant-change-confirm-${stamp}`;
const shortRun = runId.replace(/[^a-z0-9]/gi, '').slice(-12);
const employeeName = process.env.HRM_ASSISTANT_CHANGE_EMPLOYEE_NAME || `AI异动E2E员工${shortRun}`;
const sourceDeptName = `AI异动E2E原部门${shortRun}`;
const targetDeptName = `AI异动E2E目标部${shortRun}`;
const question = process.env.HRM_ASSISTANT_CHANGE_CONFIRM_QUESTION
  || `把${employeeName}调到${targetDeptName}，先分析影响并准备确认`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  if (/:(8080|8443)(?:\/|$)/.test(BASE_URL)) {
    fail('Refusing to run employee-change side-effect E2E against old production ports', { baseUrl: BASE_URL });
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const sanitize = (value) => String(value).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);
const toArray = (payload) => Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];

const asJson = async (response, label = response.url) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`${label} did not return JSON`, text.slice(0, 1000));
  }
};

const requestJson = async (method, pathName, payload, token, requestId) => {
  const response = await fetch(`${BASE_URL}${pathName}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
    body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`${method} ${pathName} failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  return asJson(response, pathName);
};

const login = async () => {
  const payload = await requestJson('POST', '/api/auth/login', { email: EMAIL, password: PASSWORD }, null, `${runId}-login`);
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  return payload;
};

const getJson = (pathName, token, requestId) => requestJson('GET', pathName, null, token, requestId);
const postJson = (pathName, payload, token, requestId) => requestJson('POST', pathName, payload, token, requestId);

const createAssistantSession = async (token) => {
  const payload = await postJson('/api/hrm/assistant/sessions/new', {}, token, `${runId}-new-session`);
  if (!payload.id) fail('Assistant new session did not return an id', payload);
  return payload;
};

const listResource = async (token, resource, params = {}) => {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return toArray(await getJson(`/api/hrm/${resource}${query ? `?${query}` : ''}`, token, `${runId}-${resource}-${Date.now()}`));
};

const createResource = (token, resource, payload) => postJson(`/api/hrm/${resource}`, payload, token, `${runId}-create-${resource}-${Date.now()}`);

const byNewIds = (beforeRows, afterRows) => {
  const beforeIds = new Set(beforeRows.map((row) => row.id).filter(Boolean));
  return afterRows.filter((row) => row.id && !beforeIds.has(row.id));
};

const seedChangeCase = async (token) => {
  const sourceDept = await createResource(token, 'departments', {
    name: sourceDeptName,
    code: `CHS${shortRun}`.slice(0, 50),
    status: 'active',
    description: 'AI 助手调岗确认 E2E 临时原部门',
  });
  const targetDept = await createResource(token, 'departments', {
    name: targetDeptName,
    code: `CHT${shortRun}`.slice(0, 50),
    status: 'active',
    description: 'AI 助手调岗确认 E2E 临时目标部门',
  });
  const sourcePosition = await createResource(token, 'positions', {
    title: `AI异动E2E原岗位${shortRun}`,
    category: '测试岗位',
    departmentId: sourceDept.id,
    level: 'M2',
    status: 'active',
  });
  const targetPosition = await createResource(token, 'positions', {
    title: `AI异动E2E目标岗${shortRun}`,
    category: '测试岗位',
    departmentId: targetDept.id,
    level: 'P5',
    status: 'active',
  });
  const employee = await createResource(token, 'employees', {
    employeeNo: `ECHG${shortRun}`.slice(0, 50),
    name: employeeName,
    email: `${shortRun.toLowerCase()}@change-e2e.local`,
    status: 'active',
    departmentId: sourceDept.id,
    positionId: sourcePosition.id,
    jobTitle: sourcePosition.title,
    hireDate: '2026-01-12',
    remark: 'AI 助手调岗确认 E2E 临时员工',
  });
  return { sourceDept, targetDept, sourcePosition, targetPosition, employee };
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
    sourceButtonCount: await queryCount(panel.locator('button:has-text("证据"), button:has-text("来源"), button:has-text("异动"), button:has-text("审批")')),
    loadingCount: await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin')),
  };
};

const waitForDraftUi = async (panel) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes(employeeName)
      && last.text.includes(targetDeptName)
      && last.text.includes('提交员工异动审批')
      && last.text.includes('确认执行')
      && last.tableCount >= 1
      && last.confirmationButtonCount >= 1
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail('Assistant did not render the employee-change confirmation draft UI', {
    snapshot: last,
    textSample: last?.text?.slice(0, 1600),
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
    textSample: last?.text?.slice(0, 1600),
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

const waitForChangeWrite = async (token, seed, before) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let latest = {};
  while (Date.now() < deadline) {
    const employeeChanges = await listResource(token, 'employee-changes', { q: employeeName });
    const approvals = await listResource(token, 'approvals/pending');
    const notifications = await listResource(token, 'notifications');
    const operationLogs = await listResource(token, 'operation-logs');
    const employees = await listResource(token, 'employees', { q: employeeName });

    const createdChanges = byNewIds(before.employeeChanges, employeeChanges).filter((row) => (
      row.employeeId === seed.employee.id
      && row.changeType === 'transfer'
      && row.beforeDepartmentId === seed.sourceDept.id
      && row.afterDepartmentId === seed.targetDept.id
      && row.status === 'pending'
    ));
    const createdApprovals = byNewIds(before.approvals, approvals).filter((row) => (
      row.businessType === 'employee_change'
      && createdChanges.some((change) => change.id === row.businessId)
      && row.status === 'pending'
    ));
    const createdNotifications = byNewIds(before.notifications, notifications).filter((row) => (
      String(row.title || '').includes(employeeName)
      && String(row.noticeType || '').includes('approval')
    ));
    const createdOperationLogs = byNewIds(before.operationLogs, operationLogs).filter((row) => (
      row.module === 'employee_changes'
      && row.action === 'ai_confirm_submit'
      && createdChanges.some((change) => change.id === row.targetId)
      && row.detail?.source === 'assistant_confirmed_action'
    ));
    const employee = employees.find((row) => row.id === seed.employee.id) || seed.employee;
    latest = { employeeChanges, approvals, notifications, operationLogs, employees, createdChanges, createdApprovals, createdNotifications, createdOperationLogs, employee };
    if (
      createdChanges.length >= 1
      && createdApprovals.length >= 1
      && createdNotifications.length >= 1
      && createdOperationLogs.length >= 1
      && employee.departmentId === seed.sourceDept.id
      && employee.positionId === seed.sourcePosition.id
    ) {
      return latest;
    }
    await sleep(1000);
  }
  fail('Confirmed employee-change action did not create expected change, approval, notification, audit, or employee guard evidence', latest);
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();
  const assistantSession = await createAssistantSession(auth.token);
  const seed = await seedChangeCase(auth.token);

  const before = {
    employeeChanges: await listResource(auth.token, 'employee-changes', { q: employeeName }),
    approvals: await listResource(auth.token, 'approvals/pending'),
    notifications: await listResource(auth.token, 'notifications'),
    operationLogs: await listResource(auth.token, 'operation-logs'),
  };

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
    await page.goto(`${BASE_URL}/hrm/employee-changes`, { waitUntil: 'domcontentloaded', timeout: 30000 });
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
      'employee-change confirmation draft',
    );
    await textarea.press('Enter', { timeout: 10000 });
    const prepareRequest = await prepareRequestPromise;
    const prepareRequestId = requestIdFrom(prepareRequest, 'employee-change confirmation draft');

    const draftUi = await waitForDraftUi(panel);
    const draftChanges = await listResource(auth.token, 'employee-changes', { q: employeeName });
    const draftCreatedChanges = byNewIds(before.employeeChanges, draftChanges);
    if (draftCreatedChanges.length > 0) {
      fail('Employee-change confirmation draft unexpectedly wrote employee changes before user confirmation', {
        prepareRequestId,
        draftCreatedChanges,
      });
    }
    const draftEmployees = await listResource(auth.token, 'employees', { q: employeeName });
    const draftEmployee = draftEmployees.find((row) => row.id === seed.employee.id) || seed.employee;
    if (draftEmployee.departmentId !== seed.sourceDept.id || draftEmployee.positionId !== seed.sourcePosition.id) {
      fail('Employee-change confirmation draft unexpectedly changed employee profile before approval', { before: seed.employee, after: draftEmployee });
    }
    const draftScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-draft.png`);
    await page.screenshot({ path: draftScreenshotPath, fullPage: true }).catch(() => null);

    const confirmButtons = panel.locator('button:has-text("确认执行")');
    if (await confirmButtons.count() < 1) fail('No visible employee-change confirmation button found before executing action');
    const confirmRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && String(payload.question || '').startsWith('确认执行动作：act_'),
      'confirmed employee-change action',
    );
    await confirmButtons.first().click({ timeout: 10000 });
    const confirmRequest = await confirmRequestPromise;
    const confirmPayload = parseAssistantRequest(confirmRequest);
    const confirmQuestion = String(confirmPayload.question || '');
    const confirmRequestId = requestIdFrom(confirmRequest, 'confirmed employee-change action');
    const actionId = confirmQuestion.match(/确认执行动作[：:]([A-Za-z0-9_-]+)/)?.[1];
    if (!actionId) fail('Confirmed employee-change action payload did not include an action id', { confirmQuestion });

    const writeResult = await waitForChangeWrite(auth.token, seed, before);
    const confirmUi = await waitForAssistantIdle(panel, 'confirmed employee-change action');
    const confirmScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-confirmed.png`);
    await page.screenshot({ path: confirmScreenshotPath, fullPage: true }).catch(() => null);

    const duplicateBefore = {
      employeeChanges: writeResult.employeeChanges,
      approvals: writeResult.approvals,
      notifications: writeResult.notifications,
      operationLogs: writeResult.operationLogs,
    };
    const duplicateRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && payload.question === confirmQuestion,
      'duplicate confirmed employee-change action',
    );
    await panel.locator('button:has-text("确认执行")').first().click({ timeout: 10000 });
    const duplicateRequest = await duplicateRequestPromise;
    const duplicateRequestId = requestIdFrom(duplicateRequest, 'duplicate confirmed employee-change action');
    const duplicateUi = await waitForAssistantIdle(panel, 'duplicate confirmed employee-change action');
    const duplicateAfter = {
      employeeChanges: await listResource(auth.token, 'employee-changes', { q: employeeName }),
      approvals: await listResource(auth.token, 'approvals/pending'),
      notifications: await listResource(auth.token, 'notifications'),
      operationLogs: await listResource(auth.token, 'operation-logs'),
    };
    const duplicateChanges = byNewIds(duplicateBefore.employeeChanges, duplicateAfter.employeeChanges)
      .filter((row) => row.employeeId === seed.employee.id);
    const duplicateApprovals = byNewIds(duplicateBefore.approvals, duplicateAfter.approvals)
      .filter((row) => row.businessType === 'employee_change');
    const duplicateLogs = byNewIds(duplicateBefore.operationLogs, duplicateAfter.operationLogs)
      .filter((row) => row.module === 'employee_changes' && row.action === 'ai_confirm_submit');
    if (duplicateChanges.length || duplicateApprovals.length || duplicateLogs.length) {
      fail('Duplicate employee-change confirmation created additional business writes', {
        duplicateRequestId,
        duplicateChanges,
        duplicateApprovals,
        duplicateLogs,
      });
    }
    const duplicateScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-duplicate-confirm.png`);
    await page.screenshot({ path: duplicateScreenshotPath, fullPage: true }).catch(() => null);

    if (consoleErrors.length || pageErrors.length) {
      fail('Assistant employee-change confirmed-action UI emitted browser errors', { consoleErrors, pageErrors });
    }

    const prepareAudit = await fetchAuditRow(auth.token, prepareRequestId);
    const confirmAudit = await fetchAuditRow(auth.token, confirmRequestId);
    const duplicateAudit = await fetchAuditRow(auth.token, duplicateRequestId);
    verifyAuditRow(prepareAudit, 'employee-change draft', { requireRealModel: true });
    verifyAuditRow(confirmAudit, 'confirmed employee-change action');
    verifyAuditRow(duplicateAudit, 'duplicate employee-change confirmation');

    result = {
      ok: true,
      runId,
      baseUrl: BASE_URL,
      protectedPorts: ['8080', '8443'],
      isolatedDatabase: 'hengpintong_next',
      question,
      actionId,
      seeded: {
        employeeId: seed.employee.id,
        employeeName: seed.employee.name,
        sourceDepartmentId: seed.sourceDept.id,
        targetDepartmentId: seed.targetDept.id,
        sourcePositionId: seed.sourcePosition.id,
        targetPositionId: seed.targetPosition.id,
      },
      requestIds: {
        draft: prepareRequestId,
        confirmed: confirmRequestId,
        duplicateConfirmation: duplicateRequestId,
      },
      businessWrites: {
        createdEmployeeChanges: writeResult.createdChanges.map((row) => ({
          id: row.id,
          employeeId: row.employeeId,
          changeType: row.changeType,
          beforeDepartmentId: row.beforeDepartmentId,
          afterDepartmentId: row.afterDepartmentId,
          status: row.status,
        })),
        createdApprovals: writeResult.createdApprovals.map((row) => ({
          id: row.id,
          businessType: row.businessType,
          businessId: row.businessId,
          status: row.status,
        })),
        createdNotifications: writeResult.createdNotifications.map((row) => ({
          id: row.id,
          title: row.title,
          noticeType: row.noticeType,
          linkUrl: row.linkUrl,
        })),
        createdOperationLogs: writeResult.createdOperationLogs.map((row) => ({
          id: row.id,
          module: row.module,
          action: row.action,
          targetId: row.targetId,
          sourceActionId: row.detail?.sourceActionId,
        })),
        duplicateCreatedEmployeeChanges: duplicateChanges.length,
        duplicateCreatedApprovals: duplicateApprovals.length,
        duplicateCreatedOperationLogs: duplicateLogs.length,
      },
      employeeGuard: {
        beforeDepartmentId: seed.sourceDept.id,
        afterConfirmDepartmentId: writeResult.employee.departmentId,
        beforePositionId: seed.sourcePosition.id,
        afterConfirmPositionId: writeResult.employee.positionId,
        unchangedBeforeApproval: writeResult.employee.departmentId === seed.sourceDept.id
          && writeResult.employee.positionId === seed.sourcePosition.id,
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
    businessWrites: {
      employeeChanges: result.businessWrites.createdEmployeeChanges.length,
      approvals: result.businessWrites.createdApprovals.length,
      notifications: result.businessWrites.createdNotifications.length,
      operationLogs: result.businessWrites.createdOperationLogs.length,
      duplicateEmployeeChanges: result.businessWrites.duplicateCreatedEmployeeChanges,
      duplicateApprovals: result.businessWrites.duplicateCreatedApprovals,
      duplicateOperationLogs: result.businessWrites.duplicateCreatedOperationLogs,
    },
    employeeGuard: result.employeeGuard,
    aiModelSettingsKeyword: result.requestIds.confirmed,
    screenshots: result.screenshots,
  }, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
