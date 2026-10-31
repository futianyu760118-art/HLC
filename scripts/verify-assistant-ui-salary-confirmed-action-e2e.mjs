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
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_SALARY_CONFIRM_CASE_TIMEOUT_MS || 180000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_SALARY_CONFIRM_RUN_ID || `assistant-salary-confirm-${stamp}`;
const shortRun = runId.replace(/[^a-z0-9]/gi, '').slice(-12);
const employeeName = process.env.HRM_ASSISTANT_SALARY_EMPLOYEE_NAME || `AI调薪E2E员工${shortRun}`;
const salaryAdjustment = process.env.HRM_ASSISTANT_SALARY_DELTA || '1800';
const question = process.env.HRM_ASSISTANT_SALARY_CONFIRM_QUESTION
  || `给${employeeName}调薪 ${salaryAdjustment} 元，先分析影响并准备确认`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  if (/:(8080|8443)(?:\/|$)/.test(BASE_URL)) {
    fail('Refusing to run salary side-effect E2E against old production ports', { baseUrl: BASE_URL });
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
const moneyTotal = (row) => Number(row?.totalSalary ?? row?.total_salary ?? 0);

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

const byNewIds = (beforeRows, afterRows) => {
  const beforeIds = new Set(beforeRows.map((row) => row.id).filter(Boolean));
  return afterRows.filter((row) => row.id && !beforeIds.has(row.id));
};

const listResource = async (token, resource, params = {}) => {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return toArray(await getJson(`/api/hrm/${resource}${query ? `?${query}` : ''}`, token, `${runId}-${resource}-${Date.now()}`));
};

const createResource = (token, resource, payload) => postJson(`/api/hrm/${resource}`, payload, token, `${runId}-create-${resource}-${Date.now()}`);

const seedSalaryCase = async (token) => {
  const dept = await createResource(token, 'departments', {
    name: `AI调薪E2E部${shortRun}`,
    code: `SAL${shortRun}`.slice(0, 50),
    status: 'active',
    description: 'AI 助手调薪确认 E2E 临时部门',
  });
  const position = await createResource(token, 'positions', {
    title: `AI调薪E2E岗位${shortRun}`,
    category: '测试岗位',
    departmentId: dept.id,
    level: 'P6',
    status: 'active',
  });
  const employee = await createResource(token, 'employees', {
    employeeNo: `ESAL${shortRun}`.slice(0, 50),
    name: employeeName,
    email: `${shortRun.toLowerCase()}@salary-e2e.local`,
    status: 'active',
    departmentId: dept.id,
    positionId: position.id,
    jobTitle: position.title,
    hireDate: '2026-01-10',
    remark: 'AI 助手调薪确认 E2E 临时员工',
  });
  const salaryProfile = await createResource(token, 'salary-profiles', {
    employeeId: employee.id,
    baseSalary: 12000,
    positionSalary: 8000,
    performanceSalary: 5000,
    allowance: 1200,
    bonus: 0,
    deduction: 0,
    currency: 'CNY',
    status: 'active',
    remark: 'AI 助手调薪确认 E2E 临时薪资档案',
  });
  const cycle = await createResource(token, 'performance-cycles', {
    name: `AI调薪E2E周期${shortRun}`,
    cycleType: '季度',
    startDate: '2026-04-01',
    endDate: '2026-06-30',
    status: 'active',
    remark: 'AI 助手调薪确认 E2E 临时绩效周期',
  });
  const review = await createResource(token, 'performance-reviews', {
    employeeId: employee.id,
    cycleId: cycle.id,
    selfScore: 92,
    managerScore: 94,
    finalScore: 93,
    grade: 'A',
    result: '关键项目交付稳定，建议进入调薪审批。',
    status: 'completed',
  });

  return { dept, position, employee, salaryProfile, cycle, review };
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
    sourceButtonCount: await queryCount(panel.locator('button:has-text("证据"), button:has-text("来源"), button:has-text("薪资"), button:has-text("审批")')),
    loadingCount: await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin')),
  };
};

const waitForDraftUi = async (panel) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes(employeeName)
      && last.text.includes('调薪')
      && last.text.includes(salaryAdjustment)
      && last.text.includes('确认执行')
      && last.text.includes('薪资档案')
      && last.text.includes('审批')
      && last.tableCount >= 1
      && last.confirmationButtonCount >= 1
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail('Assistant did not render the salary confirmation draft UI', {
    snapshot: last,
    textSample: last?.text?.slice(0, 1400),
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
    textSample: last?.text?.slice(0, 1400),
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

const waitForSalaryWrite = async (token, seed, before) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let latest = {};
  while (Date.now() < deadline) {
    const employeeChanges = await listResource(token, 'employee-changes', { q: employeeName });
    const approvals = await listResource(token, 'approvals/pending');
    const notifications = await listResource(token, 'notifications');
    const operationLogs = await listResource(token, 'operation-logs');
    const salaryProfiles = await listResource(token, 'salary-profiles', { q: employeeName });

    const createdChanges = byNewIds(before.employeeChanges, employeeChanges).filter((row) => (
      row.employeeId === seed.employee.id
      && row.changeType === 'salary_adjustment'
      && Number(row.salaryAdjustment) === Number(salaryAdjustment)
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
    const salaryProfile = salaryProfiles.find((row) => row.id === seed.salaryProfile.id) || seed.salaryProfile;
    latest = { employeeChanges, approvals, notifications, operationLogs, salaryProfiles, createdChanges, createdApprovals, createdNotifications, createdOperationLogs, salaryProfile };
    if (
      createdChanges.length >= 1
      && createdApprovals.length >= 1
      && createdNotifications.length >= 1
      && createdOperationLogs.length >= 1
      && moneyTotal(salaryProfile) === moneyTotal(seed.salaryProfile)
    ) {
      return latest;
    }
    await sleep(1000);
  }
  fail('Confirmed salary action did not create expected employee change, approval, notification, audit, or salary guard evidence', latest);
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();
  const assistantSession = await createAssistantSession(auth.token);
  const seed = await seedSalaryCase(auth.token);

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
    await page.goto(`${BASE_URL}/salary-profiles`, { waitUntil: 'domcontentloaded', timeout: 30000 });
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
      'salary confirmation draft',
    );
    await textarea.press('Enter', { timeout: 10000 });
    const prepareRequest = await prepareRequestPromise;
    const prepareRequestId = requestIdFrom(prepareRequest, 'salary confirmation draft');

    const draftUi = await waitForDraftUi(panel);
    const afterDraftChanges = await listResource(auth.token, 'employee-changes', { q: employeeName });
    const draftCreatedChanges = byNewIds(before.employeeChanges, afterDraftChanges);
    if (draftCreatedChanges.length > 0) {
      fail('Salary confirmation draft unexpectedly wrote employee changes before user confirmation', {
        prepareRequestId,
        draftCreatedChanges,
      });
    }
    const draftSalaryProfiles = await listResource(auth.token, 'salary-profiles', { q: employeeName });
    const draftSalary = draftSalaryProfiles.find((row) => row.id === seed.salaryProfile.id) || seed.salaryProfile;
    if (moneyTotal(draftSalary) !== moneyTotal(seed.salaryProfile)) {
      fail('Salary confirmation draft unexpectedly changed salary profile before approval', { before: seed.salaryProfile, after: draftSalary });
    }
    const draftScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-draft.png`);
    await page.screenshot({ path: draftScreenshotPath, fullPage: true }).catch(() => null);

    const confirmButtons = panel.locator('button:has-text("确认执行")');
    if (await confirmButtons.count() < 1) fail('No visible salary confirmation button found before executing action');
    const confirmRequestPromise = waitForAssistantRequest(
      page,
      (payload) => payload.stream === true && String(payload.question || '').startsWith('确认执行动作：act_'),
      'confirmed salary action',
    );
    await confirmButtons.first().click({ timeout: 10000 });
    const confirmRequest = await confirmRequestPromise;
    const confirmPayload = parseAssistantRequest(confirmRequest);
    const confirmQuestion = String(confirmPayload.question || '');
    const confirmRequestId = requestIdFrom(confirmRequest, 'confirmed salary action');
    const actionId = confirmQuestion.match(/确认执行动作[：:]([A-Za-z0-9_-]+)/)?.[1];
    if (!actionId) fail('Confirmed salary action payload did not include an action id', { confirmQuestion });

    const writeResult = await waitForSalaryWrite(auth.token, seed, before);
    const confirmUi = await waitForAssistantIdle(panel, 'confirmed salary action');
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
      'duplicate confirmed salary action',
    );
    await panel.locator('button:has-text("确认执行")').first().click({ timeout: 10000 });
    const duplicateRequest = await duplicateRequestPromise;
    const duplicateRequestId = requestIdFrom(duplicateRequest, 'duplicate confirmed salary action');
    const duplicateUi = await waitForAssistantIdle(panel, 'duplicate confirmed salary action');
    const duplicateAfter = {
      employeeChanges: await listResource(auth.token, 'employee-changes', { q: employeeName }),
      approvals: await listResource(auth.token, 'approvals/pending'),
      notifications: await listResource(auth.token, 'notifications'),
      operationLogs: await listResource(auth.token, 'operation-logs'),
    };
    const duplicateCreatedChanges = byNewIds(duplicateBefore.employeeChanges, duplicateAfter.employeeChanges)
      .filter((row) => row.employeeId === seed.employee.id);
    const duplicateCreatedApprovals = byNewIds(duplicateBefore.approvals, duplicateAfter.approvals)
      .filter((row) => row.businessType === 'employee_change');
    const duplicateCreatedLogs = byNewIds(duplicateBefore.operationLogs, duplicateAfter.operationLogs)
      .filter((row) => row.module === 'employee_changes' && row.action === 'ai_confirm_submit');
    if (duplicateCreatedChanges.length || duplicateCreatedApprovals.length || duplicateCreatedLogs.length) {
      fail('Duplicate salary confirmation created additional business writes', {
        duplicateRequestId,
        duplicateCreatedChanges,
        duplicateCreatedApprovals,
        duplicateCreatedLogs,
      });
    }
    const duplicateScreenshotPath = path.join(ARTIFACT_DIR, `${runId}-duplicate-confirm.png`);
    await page.screenshot({ path: duplicateScreenshotPath, fullPage: true }).catch(() => null);

    if (consoleErrors.length || pageErrors.length) {
      fail('Assistant salary confirmed-action UI emitted browser errors', { consoleErrors, pageErrors });
    }

    const prepareAudit = await fetchAuditRow(auth.token, prepareRequestId);
    const confirmAudit = await fetchAuditRow(auth.token, confirmRequestId);
    const duplicateAudit = await fetchAuditRow(auth.token, duplicateRequestId);
    verifyAuditRow(prepareAudit, 'salary draft', { requireRealModel: true });
    verifyAuditRow(confirmAudit, 'confirmed salary action');
    verifyAuditRow(duplicateAudit, 'duplicate salary confirmation');

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
        salaryProfileId: seed.salaryProfile.id,
        performanceReviewId: seed.review.id,
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
          salaryAdjustment: row.salaryAdjustment,
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
        duplicateCreatedEmployeeChanges: duplicateCreatedChanges.length,
        duplicateCreatedApprovals: duplicateCreatedApprovals.length,
        duplicateCreatedOperationLogs: duplicateCreatedLogs.length,
      },
      salaryGuard: {
        beforeTotalSalary: moneyTotal(seed.salaryProfile),
        afterConfirmTotalSalary: moneyTotal(writeResult.salaryProfile),
        unchangedBeforeApproval: moneyTotal(seed.salaryProfile) === moneyTotal(writeResult.salaryProfile),
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
    salaryGuard: result.salaryGuard,
    aiModelSettingsKeyword: result.requestIds.confirmed,
    screenshots: result.screenshots,
  }, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
