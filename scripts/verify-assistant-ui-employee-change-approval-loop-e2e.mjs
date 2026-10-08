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
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_CHANGE_APPROVAL_LOOP_TIMEOUT_MS || 220000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_CHANGE_APPROVAL_LOOP_RUN_ID || `assistant-change-approval-loop-${stamp}`;
const shortRun = runId.replace(/[^a-z0-9]/gi, '').slice(-12);
const employeeName = process.env.HRM_ASSISTANT_CHANGE_LOOP_EMPLOYEE_NAME || `AI闭环E2E员工${shortRun}`;
const sourceDeptName = `AI闭环E2E原部${shortRun}`;
const targetDeptName = `AI闭环E2E目标部${shortRun}`;
const sourcePositionTitle = `AI闭环E2E原岗${shortRun}`;
const targetPositionTitle = `AI闭环E2E目标岗${shortRun}`;
const changeQuestion = process.env.HRM_ASSISTANT_CHANGE_LOOP_QUESTION
  || `把${employeeName}调到${targetDeptName}，目标岗位：${targetPositionTitle}，先分析影响并准备确认`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  if (/:(8080|8443)(?:\/|$)/.test(BASE_URL)) {
    fail('Refusing to run employee-change approval loop E2E against old production ports', { baseUrl: BASE_URL });
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

const findApprovalById = async (token, approvalId) => {
  const pending = await listResource(token, 'approvals/pending');
  const foundPending = pending.find((row) => row.id === approvalId);
  if (foundPending) return foundPending;
  const records = await listResource(token, 'approvals/records');
  const relatedRecord = records.find((row) => row.approvalId === approvalId);
  if (!relatedRecord) return null;
  return {
    id: approvalId,
    status: relatedRecord.action,
    businessType: relatedRecord.businessType,
    businessId: relatedRecord.businessId,
    title: relatedRecord.approvalTitle,
  };
};

const seedLoopCase = async (token) => {
  const sourceDept = await createResource(token, 'departments', {
    name: sourceDeptName,
    code: `LOOPS${shortRun}`.slice(0, 50),
    status: 'active',
    description: 'AI 助手异动审批闭环 E2E 临时原部门',
  });
  const targetDept = await createResource(token, 'departments', {
    name: targetDeptName,
    code: `LOOPT${shortRun}`.slice(0, 50),
    status: 'active',
    description: 'AI 助手异动审批闭环 E2E 临时目标部门',
  });
  const sourcePosition = await createResource(token, 'positions', {
    title: sourcePositionTitle,
    category: '测试岗位',
    departmentId: sourceDept.id,
    level: 'P2',
    status: 'active',
  });
  const targetPosition = await createResource(token, 'positions', {
    title: targetPositionTitle,
    category: '测试岗位',
    departmentId: targetDept.id,
    level: 'P5',
    status: 'active',
  });
  const employee = await createResource(token, 'employees', {
    employeeNo: `ELOOP${shortRun}`.slice(0, 50),
    name: employeeName,
    email: `${shortRun.toLowerCase()}@change-loop-e2e.local`,
    status: 'active',
    departmentId: sourceDept.id,
    positionId: sourcePosition.id,
    jobTitle: sourcePosition.title,
    hireDate: '2026-01-20',
    remark: 'AI 助手异动审批闭环 E2E 临时员工',
  });
  return { sourceDept, targetDept, sourcePosition, targetPosition, employee };
};

const fetchAuditRow = async (token, requestId) => {
  const encoded = encodeURIComponent(requestId);
  for (let attempt = 1; attempt <= 18; attempt += 1) {
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
    sourceButtonCount: await queryCount(panel.locator('button:has-text("证据"), button:has-text("来源"), button:has-text("异动"), button:has-text("审批"), button:has-text("员工")')),
    loadingCount: await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin')),
  };
};

const waitForEmployeeChangeDraftUi = async (panel) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes(employeeName)
      && last.text.includes(targetDeptName)
      && last.text.includes(targetPositionTitle)
      && last.text.includes('提交员工异动审批')
      && last.text.includes('确认执行')
      && last.tableCount >= 1
      && last.confirmationButtonCount >= 1
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail('Assistant did not render the employee-change loop confirmation draft UI', {
    snapshot: last,
    textSample: last?.text?.slice(0, 1800),
  });
};

const waitForApprovalDraftUi = async (panel, approvalId) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes('审批通过')
      && last.text.includes(approvalId)
      && last.text.includes('确认执行')
      && last.text.includes('待确认审批明细')
      && last.tableCount >= 1
      && last.confirmationButtonCount >= 1
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail('Assistant did not render the approval-pass confirmation draft UI', {
    approvalId,
    snapshot: last,
    textSample: last?.text?.slice(0, 1800),
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
    textSample: last?.text?.slice(0, 1800),
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

const ensurePanelOpen = async (page) => {
  const panel = page.locator('.hpt-ai-assistant-panel');
  if (!(await panel.isVisible().catch(() => false))) {
    await page.locator('.hpt-ai-assistant-toggle').click({ timeout: 10000 });
  }
  await panel.waitFor({ state: 'visible', timeout: 10000 });
  return panel;
};

const submitAssistantQuestion = async (page, panel, question, label) => {
  const textarea = panel.locator('textarea').last();
  await textarea.fill(question, { timeout: 10000 });
  const requestPromise = waitForAssistantRequest(
    page,
    (payload) => payload.stream === true && payload.question === question,
    label,
  );
  await textarea.press('Enter', { timeout: 10000 });
  const request = await requestPromise;
  return requestIdFrom(request, label);
};

const clickLatestConfirmation = async (page, panel, label) => {
  const buttons = panel.locator('button:has-text("确认执行")');
  const count = await buttons.count();
  if (count < 1) fail(`No visible confirmation button found for ${label}`);
  const requestPromise = waitForAssistantRequest(
    page,
    (payload) => payload.stream === true && String(payload.question || '').startsWith('确认执行动作：act_'),
    label,
  );
  await buttons.last().click({ timeout: 10000 });
  const request = await requestPromise;
  const payload = parseAssistantRequest(request);
  const question = String(payload.question || '');
  const requestId = requestIdFrom(request, label);
  const actionId = question.match(/确认执行动作[：:]([A-Za-z0-9_-]+)/)?.[1];
  if (!actionId) fail(`${label} payload did not include an action id`, { question });
  return { requestId, question, actionId };
};

const clickDuplicateConfirmation = async (page, panel, question, label) => {
  const buttons = panel.locator('button:has-text("确认执行")');
  const count = await buttons.count();
  if (count < 1) fail(`No visible confirmation button found for duplicate ${label}`);
  const requestPromise = waitForAssistantRequest(
    page,
    (payload) => payload.stream === true && payload.question === question,
    `duplicate ${label}`,
  );
  await buttons.last().click({ timeout: 10000 });
  const request = await requestPromise;
  return requestIdFrom(request, `duplicate ${label}`);
};

const waitForChangeSubmission = async (token, seed, before) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let latest = {};
  while (Date.now() < deadline) {
    const employeeChanges = await listResource(token, 'employee-changes', { keyword: employeeName });
    const approvals = await listResource(token, 'approvals/pending');
    const notifications = await listResource(token, 'notifications');
    const operationLogs = await listResource(token, 'operation-logs');
    const employees = await listResource(token, 'employees', { keyword: employeeName });

    const createdChanges = byNewIds(before.employeeChanges, employeeChanges).filter((row) => (
      row.employeeId === seed.employee.id
      && row.changeType === 'transfer'
      && row.beforeDepartmentId === seed.sourceDept.id
      && row.afterDepartmentId === seed.targetDept.id
      && row.afterPositionId === seed.targetPosition.id
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
      && employee.jobTitle === seed.sourcePosition.title
    ) {
      return latest;
    }
    await sleep(1000);
  }
  fail('Confirmed employee-change submission did not create expected pending change, approval, notification, operation log, or profile guard evidence', latest);
};

const waitForApprovalApplied = async (token, seed, submitted, beforeApproval) => {
  const approvalId = submitted.createdApprovals[0].id;
  const changeId = submitted.createdChanges[0].id;
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let latest = {};
  while (Date.now() < deadline) {
    const approval = await findApprovalById(token, approvalId);
    const employeeChanges = await listResource(token, 'employee-changes', { keyword: employeeName });
    const employees = await listResource(token, 'employees', { keyword: employeeName });
    const approvalRecords = await listResource(token, 'approvals/records');
    const operationLogs = await listResource(token, 'operation-logs');
    const employee = employees.find((row) => row.id === seed.employee.id);
    const change = employeeChanges.find((row) => row.id === changeId);
    const createdApprovalRecords = byNewIds(beforeApproval.approvalRecords, approvalRecords).filter((row) => (
      row.approvalId === approvalId
      && row.action === 'approved'
      && String(row.comment || '').includes('AI助手E2E')
    ));
    const createdApprovalLogs = byNewIds(beforeApproval.operationLogs, operationLogs).filter((row) => (
      row.module === 'approval'
      && row.action === 'approve'
      && row.targetId === approvalId
      && row.detail?.source === 'assistant_confirmed_action'
    ));
    latest = { approval, employeeChanges, employees, approvalRecords, operationLogs, employee, change, createdApprovalRecords, createdApprovalLogs };
    if (
      approval?.status === 'approved'
      && change?.status === 'approved'
      && employee?.departmentId === seed.targetDept.id
      && employee?.positionId === seed.targetPosition.id
      && employee?.jobTitle === seed.targetPosition.title
      && createdApprovalRecords.length >= 1
      && createdApprovalLogs.length >= 1
    ) {
      return latest;
    }
    await sleep(1000);
  }
  fail('Confirmed approval did not apply employee change to profile or did not create approval audit evidence', latest);
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();
  const assistantSession = await createAssistantSession(auth.token);
  const seed = await seedLoopCase(auth.token);

  const beforeChange = {
    employeeChanges: await listResource(auth.token, 'employee-changes', { keyword: employeeName }),
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

    const panel = await ensurePanelOpen(page);
    const changeDraftRequestId = await submitAssistantQuestion(page, panel, changeQuestion, 'employee-change loop draft');
    const changeDraftUi = await waitForEmployeeChangeDraftUi(panel);
    const draftEmployees = await listResource(auth.token, 'employees', { keyword: employeeName });
    const draftEmployee = draftEmployees.find((row) => row.id === seed.employee.id) || seed.employee;
    if (draftEmployee.departmentId !== seed.sourceDept.id || draftEmployee.positionId !== seed.sourcePosition.id) {
      fail('Employee-change draft unexpectedly changed employee profile before confirmation', { draftEmployee, seed });
    }
    const draftChanges = await listResource(auth.token, 'employee-changes', { keyword: employeeName });
    const draftCreatedChanges = byNewIds(beforeChange.employeeChanges, draftChanges);
    if (draftCreatedChanges.length > 0) {
      fail('Employee-change draft unexpectedly wrote employee changes before confirmation', { draftCreatedChanges });
    }
    const changeDraftScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-change-draft.png`);
    await page.screenshot({ path: changeDraftScreenshotPath, fullPage: true }).catch(() => null);

    const changeConfirm = await clickLatestConfirmation(page, panel, 'confirmed employee-change submission');
    const submitted = await waitForChangeSubmission(auth.token, seed, beforeChange);
    const changeConfirmUi = await waitForAssistantIdle(panel, 'confirmed employee-change submission');
    const changeConfirmedScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-change-confirmed.png`);
    await page.screenshot({ path: changeConfirmedScreenshotPath, fullPage: true }).catch(() => null);

    const approvalId = submitted.createdApprovals[0].id;
    const approvalQuestion = `通过审批ID：${approvalId}，意见：AI助手E2E通过员工异动闭环`;
    const beforeApproval = {
      approvalRecords: await listResource(auth.token, 'approvals/records'),
      operationLogs: await listResource(auth.token, 'operation-logs'),
    };

    await page.goto(`${BASE_URL}/approval-center/pending`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('main.hpt-main', { timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);
    const approvalPanel = await ensurePanelOpen(page);

    const approvalDraftRequestId = await submitAssistantQuestion(page, approvalPanel, approvalQuestion, 'employee-change approval pass draft');
    const approvalDraftUi = await waitForApprovalDraftUi(approvalPanel, approvalId);
    const draftApproval = await findApprovalById(auth.token, approvalId);
    const draftLoopEmployee = (await listResource(auth.token, 'employees', { keyword: employeeName }))
      .find((row) => row.id === seed.employee.id);
    if (draftApproval?.status !== 'pending' || draftLoopEmployee?.departmentId !== seed.sourceDept.id || draftLoopEmployee?.positionId !== seed.sourcePosition.id) {
      fail('Approval draft unexpectedly completed approval or changed employee profile before confirmation', { draftApproval, draftLoopEmployee });
    }
    const approvalDraftScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-approval-draft.png`);
    await page.screenshot({ path: approvalDraftScreenshotPath, fullPage: true }).catch(() => null);

    const approvalConfirm = await clickLatestConfirmation(page, approvalPanel, 'confirmed employee-change approval pass');
    const applied = await waitForApprovalApplied(auth.token, seed, submitted, beforeApproval);
    const approvalConfirmUi = await waitForAssistantIdle(approvalPanel, 'confirmed employee-change approval pass');
    const approvalConfirmedScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-approval-confirmed.png`);
    await page.screenshot({ path: approvalConfirmedScreenshotPath, fullPage: true }).catch(() => null);

    const duplicateBefore = {
      approvalRecords: applied.approvalRecords,
      operationLogs: applied.operationLogs,
    };
    const duplicateRequestId = await clickDuplicateConfirmation(
      page,
      approvalPanel,
      approvalConfirm.question,
      'employee-change approval pass',
    );
    const duplicateUi = await waitForAssistantIdle(approvalPanel, 'duplicate employee-change approval pass');
    const duplicateAfter = {
      approvalRecords: await listResource(auth.token, 'approvals/records'),
      operationLogs: await listResource(auth.token, 'operation-logs'),
    };
    const duplicateRecords = byNewIds(duplicateBefore.approvalRecords, duplicateAfter.approvalRecords)
      .filter((row) => row.approvalId === approvalId);
    const duplicateLogs = byNewIds(duplicateBefore.operationLogs, duplicateAfter.operationLogs)
      .filter((row) => row.module === 'approval' && row.targetId === approvalId);
    if (duplicateRecords.length || duplicateLogs.length) {
      fail('Duplicate approval confirmation created additional approval records or operation logs', {
        duplicateRequestId,
        duplicateRecords,
        duplicateLogs,
      });
    }
    const duplicateScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-approval-duplicate-confirm.png`);
    await page.screenshot({ path: duplicateScreenshotPath, fullPage: true }).catch(() => null);

    if (consoleErrors.length || pageErrors.length) {
      fail('Assistant employee-change approval loop UI emitted browser errors', { consoleErrors, pageErrors });
    }

    const changeDraftAudit = await fetchAuditRow(auth.token, changeDraftRequestId);
    const changeConfirmAudit = await fetchAuditRow(auth.token, changeConfirm.requestId);
    const approvalDraftAudit = await fetchAuditRow(auth.token, approvalDraftRequestId);
    const approvalConfirmAudit = await fetchAuditRow(auth.token, approvalConfirm.requestId);
    const duplicateAudit = await fetchAuditRow(auth.token, duplicateRequestId);
    verifyAuditRow(changeDraftAudit, 'employee-change loop draft', { requireRealModel: true });
    verifyAuditRow(changeConfirmAudit, 'confirmed employee-change submission');
    verifyAuditRow(approvalDraftAudit, 'employee-change approval pass draft', { requireRealModel: true });
    verifyAuditRow(approvalConfirmAudit, 'confirmed employee-change approval pass');
    verifyAuditRow(duplicateAudit, 'duplicate employee-change approval pass');

    result = {
      ok: true,
      runId,
      baseUrl: BASE_URL,
      protectedPorts: ['8080', '8443'],
      isolatedDatabase: 'hengpintong_next',
      questions: {
        change: changeQuestion,
        approval: approvalQuestion,
      },
      seeded: {
        employeeId: seed.employee.id,
        employeeName: seed.employee.name,
        sourceDepartmentId: seed.sourceDept.id,
        targetDepartmentId: seed.targetDept.id,
        sourcePositionId: seed.sourcePosition.id,
        targetPositionId: seed.targetPosition.id,
      },
      actionIds: {
        changeSubmission: changeConfirm.actionId,
        approvalPass: approvalConfirm.actionId,
      },
      requestIds: {
        changeDraft: changeDraftRequestId,
        changeConfirmed: changeConfirm.requestId,
        approvalDraft: approvalDraftRequestId,
        approvalConfirmed: approvalConfirm.requestId,
        duplicateApprovalConfirmation: duplicateRequestId,
      },
      businessWrites: {
        employeeChange: submitted.createdChanges[0],
        approval: submitted.createdApprovals[0],
        notifications: submitted.createdNotifications.map((row) => ({
          id: row.id,
          title: row.title,
          noticeType: row.noticeType,
          linkUrl: row.linkUrl,
        })),
        changeSubmitOperationLog: submitted.createdOperationLogs[0],
        approvalRecord: applied.createdApprovalRecords[0],
        approvalOperationLog: applied.createdApprovalLogs[0],
        duplicateApprovalRecords: duplicateRecords.length,
        duplicateApprovalOperationLogs: duplicateLogs.length,
      },
      employeeGuardAndEffect: {
        beforeApprovalDepartmentId: seed.sourceDept.id,
        beforeApprovalPositionId: seed.sourcePosition.id,
        afterApprovalDepartmentId: applied.employee.departmentId,
        afterApprovalPositionId: applied.employee.positionId,
        afterApprovalJobTitle: applied.employee.jobTitle,
        unchangedBeforeApproval: submitted.employee.departmentId === seed.sourceDept.id
          && submitted.employee.positionId === seed.sourcePosition.id,
        appliedAfterApproval: applied.employee.departmentId === seed.targetDept.id
          && applied.employee.positionId === seed.targetPosition.id
          && applied.employee.jobTitle === seed.targetPosition.title,
      },
      uiSignals: {
        changeDraft: {
          tableCount: changeDraftUi.tableCount,
          confirmationButtonCount: changeDraftUi.confirmationButtonCount,
          sourceButtonCount: changeDraftUi.sourceButtonCount,
        },
        changeConfirmed: {
          tableCount: changeConfirmUi.tableCount,
          confirmationButtonCount: changeConfirmUi.confirmationButtonCount,
          sourceButtonCount: changeConfirmUi.sourceButtonCount,
        },
        approvalDraft: {
          tableCount: approvalDraftUi.tableCount,
          confirmationButtonCount: approvalDraftUi.confirmationButtonCount,
          sourceButtonCount: approvalDraftUi.sourceButtonCount,
        },
        approvalConfirmed: {
          tableCount: approvalConfirmUi.tableCount,
          confirmationButtonCount: approvalConfirmUi.confirmationButtonCount,
          sourceButtonCount: approvalConfirmUi.sourceButtonCount,
        },
        duplicate: {
          textMatchedExpiredAction: duplicateUi.text.includes('没有找到可执行') || duplicateUi.text.includes('已完成或已过期'),
          tableCount: duplicateUi.tableCount,
        },
      },
      screenshots: {
        changeDraft: changeDraftScreenshotPath,
        changeConfirmed: changeConfirmedScreenshotPath,
        approvalDraft: approvalDraftScreenshotPath,
        approvalConfirmed: approvalConfirmedScreenshotPath,
        duplicateApprovalConfirmation: duplicateScreenshotPath,
      },
      audits: {
        changeDraft: auditSummary(changeDraftAudit),
        changeConfirmed: auditSummary(changeConfirmAudit),
        approvalDraft: auditSummary(approvalDraftAudit),
        approvalConfirmed: auditSummary(approvalConfirmAudit),
        duplicateApprovalConfirmation: auditSummary(duplicateAudit),
      },
      aiModelSettingsLookup: `${BASE_URL}/ai-model-settings?keyword=${encodeURIComponent(approvalConfirm.requestId)}`,
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
      employeeChangeId: result.businessWrites.employeeChange.id,
      approvalId: result.businessWrites.approval.id,
      notifications: result.businessWrites.notifications.length,
      duplicateApprovalRecords: result.businessWrites.duplicateApprovalRecords,
      duplicateApprovalOperationLogs: result.businessWrites.duplicateApprovalOperationLogs,
    },
    employeeGuardAndEffect: result.employeeGuardAndEffect,
    aiModelSettingsKeyword: result.requestIds.approvalConfirmed,
    screenshots: result.screenshots,
  }, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
