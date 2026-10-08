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
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_PRIORITY_SCENARIO_TIMEOUT_MS || 30000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_PRIORITY_SCENARIO_RUN_ID || `priority-scenarios-${stamp}`;
const scenarioPrefix = `scenario-${runId}`;

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const sanitize = (value) => String(value || '').replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);

function parseArgs(args) {
  const scenarios = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--scenario') {
      const value = args[index + 1];
      if (!value) throw new Error('Missing value for --scenario');
      scenarios.push(value);
      index += 1;
    } else if (arg === '--help') {
      return { help: true, scenarios };
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return { scenarios, help: false };
}

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
    signal: options.signal || AbortSignal.timeout(Number(process.env.HRM_PRIORITY_SCENARIO_API_TIMEOUT_MS || 12000)),
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
  if (!password) throw new Error('Missing platform admin password for AI entitlement scenario');
  return requestJson(`${BASE_URL}/api/platform/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': `${runId}-platform-login` },
    body: JSON.stringify({ identifier, password }),
  });
}

async function cleanupResource({ auth, resource, predicate }) {
  const rows = await requestJson(`${BASE_URL}/api/hrm/${resource}`, {
    headers: authHeaders(auth, `${runId}-cleanup-list-${resource}`),
  }).catch(() => []);
  for (const row of Array.isArray(rows) ? rows : []) {
    if (!predicate(row)) continue;
    await requestJson(`${BASE_URL}/api/hrm/${resource}/${row.id}`, {
      method: 'DELETE',
      headers: authHeaders(auth, `${runId}-cleanup-${resource}-${row.id}`),
    }).catch(() => null);
  }
}

async function cleanupJobs({ auth, titlePrefix }) {
  const rows = await requestJson(`${BASE_URL}/api/jobs/`, {
    headers: authHeaders(auth, `${runId}-cleanup-list-jobs`),
  }).catch(() => []);
  for (const row of Array.isArray(rows) ? rows : []) {
    if (!String(row.title || '').startsWith(titlePrefix)) continue;
    await requestJson(`${BASE_URL}/api/jobs/${row.id}`, {
      method: 'DELETE',
      headers: authHeaders(auth, `${runId}-cleanup-job-${row.id}`),
    }).catch(() => null);
  }
}

async function cleanupScenarioNotifications({ auth, fixtures = [] }) {
  await cleanupResource({
    auth,
    resource: 'notifications',
    predicate: (row) => row.noticeType === 'workflow'
      && (
        [row.title, row.content, row.linkUrl]
          .some((value) => String(value || '').includes(runId))
        || fixtures.some((fixture) => {
          const recordId = fixture.record?.id;
          return Boolean(recordId) && String(row.linkUrl || '').includes(recordId);
        })
      ),
  });
}

async function createJobFixture({ auth, data }) {
  return requestJson(`${BASE_URL}/api/jobs/`, {
    method: 'POST',
    headers: authHeaders(auth, `${runId}-create-job`),
    body: JSON.stringify(data),
  });
}

async function createResource({ auth, resource, data }) {
  return requestJson(`${BASE_URL}/api/hrm/${resource}`, {
    method: 'POST',
    headers: authHeaders(auth, `${runId}-create-${resource}`),
    body: JSON.stringify(data),
  });
}

async function getSettings(auth, requestId = `${runId}-settings-get`) {
  return requestJson(`${BASE_URL}/api/settings`, {
    headers: authHeaders(auth, requestId),
  });
}

async function updateSettings(auth, settings, requestId = `${runId}-settings-update`) {
  return requestJson(`${BASE_URL}/api/settings`, {
    method: 'POST',
    headers: authHeaders(auth, requestId),
    body: JSON.stringify(settings),
  });
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
  if (text) await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => null);
}

async function waitForPath(page, pattern, text) {
  await page.waitForURL(pattern, { timeout: ROUTE_TIMEOUT_MS });
  await waitForMain(page, text);
}

async function clickAndExpectPath(page, click, pattern, text) {
  await Promise.all([
    page.waitForURL(pattern, { timeout: ROUTE_TIMEOUT_MS }),
    click(),
  ]);
  await waitForMain(page, text);
}

async function fillByLabelOrPlaceholder(page, labelOrPlaceholder, value) {
  const byLabel = page.getByLabel(labelOrPlaceholder, { exact: true }).first();
  if (await byLabel.count()) {
    await byLabel.fill(String(value));
    return;
  }
  const byPlaceholder = page.getByPlaceholder(labelOrPlaceholder, { exact: true }).first();
  if (await byPlaceholder.count()) {
    await byPlaceholder.fill(String(value));
    return;
  }
  throw new Error(`Input not found: ${labelOrPlaceholder}`);
}

async function fillFirstByPlaceholder(page, placeholder, value) {
  const locator = page.getByPlaceholder(placeholder, { exact: true }).first();
  if (!(await locator.count())) throw new Error(`Input not found by placeholder: ${placeholder}`);
  await locator.fill(String(value));
}

async function fillFilterRange(page, label, from, to) {
  const field = page.locator('.hpt-filter-field').filter({ hasText: label }).first();
  if (!(await field.count())) throw new Error(`Range filter field not found: ${label}`);
  await field.getByPlaceholder('起', { exact: true }).fill(String(from));
  await field.getByPlaceholder('止', { exact: true }).fill(String(to));
}

async function selectByLabel(page, label, valueOrLabel) {
  const locator = page.getByLabel(label, { exact: true }).first();
  if (!(await locator.count())) throw new Error(`Select not found: ${label}`);
  await locator.selectOption(valueOrLabel).catch(async () => {
    await locator.selectOption({ label: valueOrLabel });
  });
}

async function chooseSmartSelectOption(page, selectLocator, optionName) {
  await selectLocator.click();
  const menu = page.locator('.hpt-select-menu').last();
  await menu.waitFor({ state: 'visible', timeout: 8000 });
  await menu.getByRole('button', { name: optionName, exact: true }).first().click();
}

async function clickFilterSegment(page, label, optionName) {
  const field = page.locator('.hpt-filter-field').filter({ hasText: label }).first();
  if (!(await field.count())) throw new Error(`Filter field not found: ${label}`);
  await field.getByRole('button', { name: optionName, exact: true }).click();
}

async function confirmDialog(page, label = /确定|删除|确认|保存/) {
  const dialog = page.getByRole('dialog').last();
  await dialog.waitFor({ state: 'visible', timeout: 8000 });
  await dialog.getByRole('button', { name: label }).last().click();
}

async function waitForResourcePredicate({ auth, resource, predicate, expected, label }) {
  const deadline = Date.now() + ROUTE_TIMEOUT_MS;
  let lastRows = [];
  while (Date.now() < deadline) {
    lastRows = await requestJson(`${BASE_URL}/api/hrm/${resource}`, {
      headers: authHeaders(auth, `${runId}-poll-${resource}`),
    }).catch(() => []);
    const found = (Array.isArray(lastRows) ? lastRows : []).some(predicate);
    if (found === expected) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} did not reach expected state. expected=${expected} sample=${JSON.stringify(lastRows.slice(0, 5))}`);
}

async function waitForJobsPredicate({ auth, predicate, expected, label }) {
  const deadline = Date.now() + ROUTE_TIMEOUT_MS;
  let lastRows = [];
  while (Date.now() < deadline) {
    lastRows = await requestJson(`${BASE_URL}/api/jobs/`, {
      headers: authHeaders(auth, `${runId}-poll-jobs`),
    }).catch(() => []);
    const rows = Array.isArray(lastRows) ? lastRows : lastRows.items || [];
    const found = rows.some(predicate);
    if (found === expected) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const sample = Array.isArray(lastRows) ? lastRows.slice(0, 5) : lastRows?.items?.slice(0, 5);
  throw new Error(`${label} did not reach expected state. expected=${expected} sample=${JSON.stringify(sample || [])}`);
}

async function scenarioEmployeesCrud({ context, auth }) {
  const page = await context.newPage();
  const employeeNo = `SCN-${runId.slice(-10)}`.slice(0, 48);
  const createdName = `场景员工-${runId}`;
  const editedName = `${createdName}-编辑`;
  const cleanup = async () => cleanupResource({
    auth,
    resource: 'employees',
    predicate: (row) => row.employeeNo === employeeNo || row.employee_no === employeeNo || String(row.name || '').startsWith(createdName),
  });

  await cleanup();
  try {
    await page.goto(`${BASE_URL}/hrm/employees`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '员工档案');
    await page.getByRole('button', { name: /新增员工档案/ }).click();
    await fillByLabelOrPlaceholder(page, '姓名', createdName);
    await fillByLabelOrPlaceholder(page, '员工编号（留空自动生成）', employeeNo);
    await fillByLabelOrPlaceholder(page, '邮箱', `${employeeNo.toLowerCase()}@example.test`);
    await selectByLabel(page, '性别', '男');
    await fillByLabelOrPlaceholder(page, '入职日期', '2026-01-01');
    await page.getByRole('button', { name: /^保存$/ }).click();
    await page.getByText(createdName).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByPlaceholder('搜索员工档案...').fill(employeeNo);
    await page.getByText(createdName).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /^详情$/ }).first().click();
    const drawer = page.locator('.fixed.inset-0').last();
    await drawer.getByText(employeeNo, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /^关闭$/ }).last().click();

    await page.getByRole('button', { name: /^编辑$/ }).first().click();
    await fillByLabelOrPlaceholder(page, '姓名', editedName);
    await page.getByRole('button', { name: /^保存$/ }).click();
    await page.getByText(editedName).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByRole('button', { name: /^删除$/ }).first().click();
    await confirmDialog(page, /^删除$/);
    await waitForResourcePredicate({
      auth,
      resource: 'employees',
      predicate: (row) => row.employeeNo === employeeNo || row.employee_no === employeeNo || String(row.name || '').startsWith(createdName),
      expected: false,
      label: 'Employee delete scenario',
    });

    return { ok: true, scenario: 'employees-crud', cleanup: 'deleted through UI', employeeNo };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function scenarioRolesCrud({ context, auth }) {
  const page = await context.newPage();
  const code = `scn_${runId.slice(-10).toLowerCase()}`.slice(0, 48);
  const name = `场景角色-${runId}`;
  const editedName = `${name}-编辑`;
  const cleanup = async () => cleanupResource({
    auth,
    resource: 'roles',
    predicate: (row) => row.code === code || String(row.name || '').startsWith(name),
  });

  await cleanup();
  try {
    await page.goto(`${BASE_URL}/hrm/roles`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '角色权限');
    await page.getByRole('button', { name: /新增角色权限/ }).click();
    await fillByLabelOrPlaceholder(page, '角色编码', code);
    await fillByLabelOrPlaceholder(page, '角色名称', name);
    await fillByLabelOrPlaceholder(page, '说明', scenarioPrefix);
    await page.getByRole('button', { name: /^保存$/ }).click();
    await page.getByText(name).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByRole('button', { name: /^详情$/ }).first().click();
    const drawer = page.locator('.fixed.inset-0').last();
    await drawer.getByText(code, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /^关闭$/ }).last().click();

    await page.getByRole('button', { name: /^编辑$/ }).first().click();
    await fillByLabelOrPlaceholder(page, '角色名称', editedName);
    await page.getByRole('button', { name: /^保存$/ }).click();
    await page.getByText(editedName).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByRole('button', { name: /^删除$/ }).first().click();
    await confirmDialog(page, /^删除$/);
    await waitForResourcePredicate({
      auth,
      resource: 'roles',
      predicate: (row) => row.code === code || String(row.name || '').startsWith(name),
      expected: false,
      label: 'Role delete scenario',
    });

    return { ok: true, scenario: 'roles-crud', cleanup: 'deleted through UI', code };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function chooseFilterOption(page, label, optionName) {
  const field = page.locator('.hpt-filter-field').filter({ hasText: label }).first();
  if (!(await field.count())) throw new Error(`Filter field not found: ${label}`);
  await chooseSmartSelectOption(page, field.locator('.hpt-smart-select').first(), optionName);
}

async function scenarioJobManageFixtureList({ context, auth }) {
  const page = await context.newPage();
  const titlePrefix = `场景岗位管理-${runId}`;
  const department = `场景部门-${runId.slice(-6)}`;
  const category = `场景分类-${runId.slice(-6)}`;
  const level = `P${runId.slice(-1) || '6'}-场景`;
  const location = `上海场景-${runId.slice(-4)}`;
  const employmentType = '全职';
  const cleanup = async () => cleanupJobs({ auth, titlePrefix });

  await cleanup();
  let firstJob = null;
  let secondJob = null;
  try {
    firstJob = await createJobFixture({
      auth,
      data: {
        title: `${titlePrefix}-单删`,
        description: `${scenarioPrefix} 岗位管理列表筛选和单条删除夹具`,
        department,
        category,
        level,
        location,
        employmentType,
        salaryRange: '20K-30K',
      },
    });
    secondJob = await createJobFixture({
      auth,
      data: {
        title: `${titlePrefix}-批删`,
        description: `${scenarioPrefix} 岗位管理列表批量删除夹具`,
        department,
        category,
        level,
        location,
        employmentType,
        salaryRange: '21K-31K',
      },
    });

    await page.goto(`${BASE_URL}/job-manage`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '岗位总数');
    await page.getByPlaceholder('岗位/部门/地点...', { exact: true }).fill(titlePrefix);
    await page.getByText(firstJob.title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /^在招/ }).click();
    await chooseFilterOption(page, '部门', department);
    await chooseFilterOption(page, '分类', category);
    await chooseFilterOption(page, '职级', level);
    await chooseFilterOption(page, '地点', location);
    await chooseFilterOption(page, '用工', employmentType);

    const today = new Date().toISOString().slice(0, 10);
    await fillFilterRange(page, '创建时间', today, today);
    await page.locator('select').first().selectOption('50');
    await page.getByText(firstJob.title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText(secondJob.title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('columnheader', { name: /岗位名称/ }).click();
    await page.getByRole('columnheader', { name: /创建时间/ }).click();

    await page.getByRole('link', { name: /新建岗位/ }).click();
    await waitForPath(page, /\/job-create$/, '新建岗位');

    await page.goto(`${BASE_URL}/job-manage`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '岗位总数');
    await page.getByPlaceholder('岗位/部门/地点...', { exact: true }).fill(firstJob.title);
    await page.getByText(firstJob.title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.locator('tbody tr').filter({ hasText: firstJob.title }).first().getByRole('button', { name: /删除/ }).click();
    await confirmDialog(page, /^删除$/);
    await waitForJobsPredicate({
      auth,
      predicate: (row) => row.id === firstJob.id,
      expected: false,
      label: 'Job manage single delete scenario',
    });

    await page.goto(`${BASE_URL}/job-manage`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '岗位总数');
    await page.getByPlaceholder('岗位/部门/地点...', { exact: true }).fill(secondJob.title);
    await page.getByText(secondJob.title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.locator('tbody tr').filter({ hasText: secondJob.title }).first().locator('input[type="checkbox"]').check();
    await page.getByRole('button', { name: /^删除\(/ }).click();
    await confirmDialog(page, /^删除$/);
    await waitForJobsPredicate({
      auth,
      predicate: (row) => row.id === secondJob.id,
      expected: false,
      label: 'Job manage batch delete scenario',
    });

    return {
      ok: true,
      scenario: 'job-manage-fixture-list',
      cleanup: 'two isolated jobs deleted through single and batch UI flows; API cleanup also runs in finally',
      created: [firstJob.id, secondJob.id],
      filters: { department, category, level, location, employmentType },
    };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function scenarioJobCreate({ context, auth }) {
  const page = await context.newPage();
  const title = `场景岗位-${runId}`;
  const cleanup = async () => cleanupJobs({ auth, titlePrefix: title });
  await cleanup();

  try {
    await page.goto(`${BASE_URL}/job-create`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '新建岗位');
    await page.getByRole('button', { name: /恢复默认/ }).click();
    await fillByLabelOrPlaceholder(page, '岗位名称', title);
    await fillByLabelOrPlaceholder(page, '岗位描述', `${scenarioPrefix} 岗位职责覆盖提交按钮。`);
    await fillByLabelOrPlaceholder(page, '任职要求', '熟悉 SaaS 产品验证和 HR 业务流程。');
    await fillByLabelOrPlaceholder(page, '薪资范围', '15K-25K');
    await fillByLabelOrPlaceholder(page, '工作地点', '上海');
    await selectByLabel(page, '工作类型', '全职');
    await page.getByRole('button', { name: /创建岗位/ }).click();
    await page.waitForURL(/\/job-manage/, { timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '岗位总数');
    await page.getByPlaceholder('岗位/部门/地点...').fill(title);
    await page.getByText(title, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    const rows = await requestJson(`${BASE_URL}/api/jobs/`, {
      headers: authHeaders(auth, `${runId}-verify-job-create`),
    });
    if (!rows.some((row) => row.title === title)) {
      throw new Error(`Created job was visible but not found by API: ${title}; sample=${JSON.stringify(rows.slice(0, 5).map((row) => row.title))}`);
    }

    return { ok: true, scenario: 'job-create', cleanup: 'created job removed by API cleanup', title };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function scenarioAiSettingsSave({ context }) {
  const page = await context.newPage();
  try {
    await page.goto(`${BASE_URL}/ai-model-settings`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, 'AI 权益与用量');
    await page.getByRole('button', { name: /刷新/ }).click();
    await page.getByText('近期 AI 用量', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    return { ok: true, scenario: 'ai-settings-save', cleanup: 'tenant-safe entitlement refresh only' };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioAiSettingsControls({ context, auth }) {
  const page = await context.newPage();
  const platformAuth = await loginPlatformAdmin();
  const tenantId = auth.user?.tenantId;
  if (!tenantId) throw new Error('Tenant id missing from HRM auth for tenant AI controls');
  const original = await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
    headers: authHeaders(platformAuth, `${runId}-ai-settings-controls-snapshot`),
  });
  const assistant = (original.entitlements || []).find((item) => item.resourceDomain === 'assistant');
  const enabledAssistant = {
    ...(assistant || {}),
    resourceDomain: 'assistant',
    packageCode: assistant?.packageCode || 'ai_assistant',
    enabled: true,
    selectedTier: 'basic',
    allowedTiers: ['basic', 'standard'],
    monthlyQuota: Math.max(Number(assistant?.monthlyQuota || 0), 20),
  };
  try {
    await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
      method: 'PUT',
      headers: authHeaders(platformAuth, `${runId}-ai-settings-controls-enable`),
      body: JSON.stringify({ entitlements: [enabledAssistant] }),
    });

    await page.goto(`${BASE_URL}/ai-model-settings`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, 'AI 权益与用量');
    const assistantEntitlementCard = page
      .locator('section.rounded-lg.border.bg-white.p-4')
      .filter({ has: page.getByRole('heading', { name: 'AI 助手', exact: true }) })
      .first();
    await assistantEntitlementCard.waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await assistantEntitlementCard.getByRole('button', { name: '标准档', exact: true }).click();
    await page.getByText('AI 档位已更新', { exact: false }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    const payload = await requestJson(`${BASE_URL}/api/hrm/ai/entitlements`, {
      headers: authHeaders(auth, `${runId}-ai-settings-controls-verify`),
    });
    const updated = payload.entitlements.find((item) => item.resourceDomain === 'assistant');
    if (updated?.selectedTier !== 'standard') {
      throw new Error(`Tenant AI tier was not updated through UI: ${JSON.stringify(updated)}`);
    }
    await page.getByText('近期 AI 用量', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    return { ok: true, scenario: 'ai-settings-controls', cleanup: 'tenant assistant tier restored through platform API' };
  } finally {
    await page.close().catch(() => null);
    await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
      method: 'PUT',
      headers: authHeaders(platformAuth, `${runId}-ai-settings-controls-restore`),
      body: JSON.stringify({ entitlements: original.entitlements || [] }),
    }).catch(() => null);
  }
}

async function scenarioAiSettingsSafeControls({ context, auth }) {
  const page = await context.newPage();
  try {
    await page.goto(`${BASE_URL}/ai-model-settings`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, 'AI 权益与用量');
    await page.getByText('已开通资源', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('本月已用', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('月度额度', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('近期 AI 用量', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    const payload = await requestJson(`${BASE_URL}/api/hrm/ai/usage`, {
      headers: authHeaders(auth, `${runId}-tenant-ai-usage-read`),
    });
    if (!payload || typeof payload.total !== 'number') {
      throw new Error(`Tenant AI usage payload is invalid: ${JSON.stringify(payload)}`);
    }

    return { ok: true, scenario: 'ai-settings-safe-controls', cleanup: 'read-only tenant AI entitlement and usage view' };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioPlatformAiEntitlementManagement({ context, auth }) {
  const platformAuth = await loginPlatformAdmin();
  const tenantId = auth.user?.tenantId;
  if (!tenantId) throw new Error('Tenant id missing from HRM auth for platform AI entitlement scenario');
  const original = await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
    headers: authHeaders(platformAuth, `${runId}-platform-ai-snapshot`),
  });
  const page = await context.newPage();
  await addAuthToContext(context, platformAuth);
  try {
    await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
      method: 'PUT',
      headers: authHeaders(platformAuth, `${runId}-platform-ai-api-enable`),
      body: JSON.stringify({
        entitlements: [{
          resourceDomain: 'assistant',
          packageCode: 'ai_assistant',
          enabled: true,
          selectedTier: 'standard',
          allowedTiers: ['basic', 'standard'],
          monthlyQuota: 25,
        }],
      }),
    });

    await page.goto(`${BASE_URL}/platform/tenants`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('恒聘通平台后台', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: 'AI 资源管理', exact: true }).click();
    await page.getByText('客户 AI 加购包权益', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('供应商配置', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText('客户 AI 用量', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    const payload = await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
      headers: authHeaders(platformAuth, `${runId}-platform-ai-verify`),
    });
    const assistant = payload.entitlements.find((item) => item.resourceDomain === 'assistant');
    if (!assistant?.enabled || assistant.monthlyQuota !== 25) {
      throw new Error(`Platform AI entitlement API did not persist expected assistant settings: ${JSON.stringify(assistant)}`);
    }

    return { ok: true, scenario: 'platform-ai-entitlement-management', cleanup: 'tenant AI entitlements restored by API', tenantId };
  } finally {
    await page.close().catch(() => null);
    await requestJson(`${BASE_URL}/api/platform/tenants/${tenantId}/ai-entitlements`, {
      method: 'PUT',
      headers: authHeaders(platformAuth, `${runId}-platform-ai-restore`),
      body: JSON.stringify({ entitlements: original.entitlements || [] }),
    }).catch(() => null);
  }
}

async function scenarioTenantAiUsageAndTierSelection({ context, auth }) {
  const result = await scenarioAiSettingsControls({ context, auth });
  return {
    ...result,
    scenario: 'tenant-ai-usage-and-tier-selection',
  };
}

async function scenarioHomeNavigation({ context }) {
  const page = await context.newPage();

  async function fromHomeTo({ label, click, url, text }) {
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '快捷操作');
    await click();
    await waitForPath(page, url, text);
    return label;
  }

  try {
    const visited = [];
    visited.push(await fromHomeTo({
      label: '新建岗位',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /^新建岗位$/ }).click(),
      url: /\/job-create$/,
      text: '新建岗位',
    }));
    visited.push(await fromHomeTo({
      label: '员工档案',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /^员工档案$/ }).click(),
      url: /\/hrm\/employees$/,
      text: '员工档案',
    }));
    visited.push(await fromHomeTo({
      label: '审批中心',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /^审批中心$/ }).click(),
      url: /\/approval-center\/pending$/,
      text: '审批中心',
    }));
    visited.push(await fromHomeTo({
      label: '发布岗位',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /^发布岗位$/ }).click(),
      url: /\/job-manage$/,
      text: '岗位总数',
    }));
    visited.push(await fromHomeTo({
      label: '添加员工',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /^添加员工$/ }).click(),
      url: /\/hrm\/employees$/,
      text: '员工档案',
    }));
    visited.push(await fromHomeTo({
      label: '自定义快捷入口',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /自定义快捷入口/ }).click(),
      url: /\/system-settings$/,
      text: '系统设置',
    }));
    visited.push(await fromHomeTo({
      label: '员工总数',
      click: () => page.locator('main.hpt-main .stat-card').filter({ hasText: '员工总数' }).first().click(),
      url: /\/hrm\/employees$/,
      text: '员工档案',
    }));
    visited.push(await fromHomeTo({
      label: '在招岗位',
      click: () => page.locator('main.hpt-main .stat-card').filter({ hasText: '在招岗位' }).first().click(),
      url: /\/job-manage\?status=open$/,
      text: '岗位总数',
    }));
    visited.push(await fromHomeTo({
      label: '面试',
      click: () => page.locator('main.hpt-main .stat-card').filter({ hasText: '面试总数' }).first().click(),
      url: /\/interview-manage$/,
      text: '面试管理',
    }));
    visited.push(await fromHomeTo({
      label: '本月离职',
      click: () => page.locator('main.hpt-main .stat-card').filter({ hasText: '本月离职' }).first().click(),
      url: /\/hrm\/resignations$/,
      text: '离职管理',
    }));
    visited.push(await fromHomeTo({
      label: '查看全部任务',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /查看全部任务/ }).click(),
      url: /\/approval-center\/pending$/,
      text: '审批中心',
    }));

    return { ok: true, scenario: 'home-navigation', cleanup: 'read-only navigation scenario', visited };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioHomeDashboardSecondaryNavigation({ context }) {
  const page = await context.newPage();

  async function fromHomeTo({ label, click, url, text }) {
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '招聘运营链路');
    await clickAndExpectPath(page, click, url, text);
    return label;
  }

  try {
    const visited = [];
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '招聘运营链路');
    for (const label of ['简历池', 'Offer', '待入职', '本月入职', '考勤异常', '待审批']) {
      await page.locator('main.hpt-main .ops-metric-column').filter({ hasText: label }).first().click();
      await page.locator('.ops-volume-brief').filter({ hasText: label }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      visited.push(label);
    }

    visited.push(await fromHomeTo({
      label: '查看更多',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /查看更多/ }).click(),
      url: /\/notifications$/,
      text: '通知',
    }));
    visited.push(await fromHomeTo({
      label: '查看全部部门',
      click: () => page.locator('main.hpt-main').getByRole('button', { name: /查看全部部门/ }).click(),
      url: /\/hrm\/departments$/,
      text: '部门',
    }));

    return { ok: true, scenario: 'home-dashboard-secondary-navigation', cleanup: 'read-only dashboard metric and secondary link navigation', visited };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioJobCreateRequiredFields({ context, auth }) {
  const page = await context.newPage();
  const title = `场景必填岗位-${runId}`;
  const cleanup = async () => cleanupJobs({ auth, titlePrefix: title });

  await cleanup();
  try {
    await page.goto(`${BASE_URL}/job-create`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '新建岗位');

    await page.getByRole('button', { name: /创建岗位/ }).click();
    const titleValidity = await page.getByLabel('岗位名称', { exact: true }).evaluate((element) => element.validity.valueMissing);
    if (!titleValidity) throw new Error('Job title required validity did not trigger');

    await fillByLabelOrPlaceholder(page, '岗位名称', title);
    await page.getByRole('button', { name: /创建岗位/ }).click();
    const descriptionValidity = await page.getByLabel('岗位描述', { exact: true }).evaluate((element) => element.validity.valueMissing);
    if (!descriptionValidity) throw new Error('Job description required validity did not trigger');

    await fillByLabelOrPlaceholder(page, '岗位描述', `${scenarioPrefix} 岗位描述覆盖必填校验和安全提交。`);
    await fillByLabelOrPlaceholder(page, '任职要求', `${scenarioPrefix} 任职要求覆盖可选文本。`);
    await fillByLabelOrPlaceholder(page, '薪资范围', '18K-28K');
    await fillByLabelOrPlaceholder(page, '工作地点', '上海·徐汇区');
    await selectByLabel(page, '工作类型', { label: '兼职' });
    await selectByLabel(page, '工作类型', { label: '实习' });
    await selectByLabel(page, '工作类型', { label: '全职' });

    const numberInputs = page.locator('input[type="number"]');
    const firstWeight = numberInputs.first();
    await firstWeight.fill('0');
    await page.getByText(/当前总和：/).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /恢复默认/ }).click();
    await page.getByText('总权重: 100%', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByRole('button', { name: /创建岗位/ }).click();
    await page.waitForURL(/\/job-manage$/, { timeout: ROUTE_TIMEOUT_MS });
    await waitForJobsPredicate({
      auth,
      predicate: (row) => row.title === title,
      expected: true,
      label: 'Job create required fields scenario',
    });

    return { ok: true, scenario: 'job-create-required-fields', cleanup: 'created job removed by API cleanup', title };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function scenarioExamCenterNonAiControls({ context }) {
  const page = await context.newPage();
  try {
    await page.goto(`${BASE_URL}/exam-center`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '题库管理');

    await page.getByPlaceholder('搜索题干、课程、分类').fill(scenarioPrefix);
    await page.locator('select').nth(0).selectOption('all');
    await page.locator('select').nth(1).selectOption('all');
    for (const label of ['待审核', '全部', '全题型', '单选', '多选', '判断', '按课程分组', '按分类分组']) {
      await page.getByRole('button', { name: new RegExp(`^${label}$`) }).click();
    }

    const routeBefore = page.url();
    await page.getByRole('button', { name: /^智能出题$/ }).click();
    await page.waitForURL(/\/exam-generate$/, { timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '智能出题');
    await page.goto(`${BASE_URL}/exam-center`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '题库管理');
    if (routeBefore.includes('exam-generate')) {
      throw new Error('Exam center started on AI generation page unexpectedly');
    }

    const emptyAiLink = page.getByRole('button', { name: /^前往智能出题$/ });
    if (await emptyAiLink.count()) {
      await clickAndExpectPath(page, () => emptyAiLink.click(), /\/exam-generate$/, '智能出题');
    }

    return { ok: true, scenario: 'exam-center-non-ai-controls', cleanup: 'filter-only and navigation-only; did not trigger AI question generation' };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioHrmSafeFilterControls({ context }) {
  const page = await context.newPage();
  const visited = [];

  async function openCreateAndCancel(route, buttonName, dialogText) {
    const button = page.getByRole('button', { name: buttonName });
    if (!(await button.count())) return false;
    await button.first().click();
    await page.getByText(dialogText, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByRole('button', { name: /^取消$/ }).last().click();
    await page.getByText(dialogText, { exact: false }).first().waitFor({ state: 'hidden', timeout: ROUTE_TIMEOUT_MS }).catch(() => null);
    visited.push(`${route}:open-cancel`);
    return true;
  }

  async function visit(route, heading) {
    await page.goto(`${BASE_URL}${route}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, heading);
    visited.push(route);
  }

  try {
    await visit('/hrm/attendance-records', '考勤记录');
    await fillFirstByPlaceholder(page, '搜索考勤记录...', scenarioPrefix);
    await page.getByRole('button', { name: /^刷新$/ }).click();
    await page.locator('.hpt-filter-field').filter({ hasText: '员工' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await page.locator('.hpt-filter-field').filter({ hasText: '考勤状态' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await page.locator('.hpt-filter-field').filter({ hasText: '来源' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await fillFilterRange(page, '考勤日期', '2026-01-01', '2026-12-31');
    await fillFilterRange(page, '工时', '0', '12');
    await openCreateAndCancel('/hrm/attendance-records', /新增考勤记录/, '新增考勤记录');

    await visit('/employee-requests', '请假/加班/出差/补卡');
    await fillFirstByPlaceholder(page, '搜索员工/标题/原因...', scenarioPrefix);
    for (const label of ['请假', '加班', '出差', '补卡']) {
      await clickFilterSegment(page, '申请类型', label);
    }
    await page.locator('.hpt-filter-field').filter({ hasText: '状态' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await fillFilterRange(page, '开始日期', '2026-01-01', '2026-12-31');
    await fillFilterRange(page, '时长', '0', '8');
    await openCreateAndCancel('/employee-requests', /新建申请/, '新建申请');

    await visit('/hrm/performance-cycles', '绩效周期');
    await fillFirstByPlaceholder(page, '搜索绩效周期...', scenarioPrefix);
    for (const label of ['月度', '季度', '年度']) {
      await clickFilterSegment(page, '周期类型', label);
    }
    for (const label of ['草稿', '启用/在职', '已完成']) {
      await clickFilterSegment(page, '状态', label);
    }
    await fillFilterRange(page, '开始日期', '2026-01-01', '2026-06-30');
    await fillFilterRange(page, '结束日期', '2026-07-01', '2026-12-31');
    await openCreateAndCancel('/hrm/performance-cycles', /新增绩效周期/, '新增绩效周期');

    await visit('/performance-review', '绩效评估');
    await fillFirstByPlaceholder(page, '员工/周期/结果...', scenarioPrefix);
    for (const label of ['S', 'A', 'B', 'C', 'D']) {
      await clickFilterSegment(page, '等级', label);
    }
    await clickFilterSegment(page, '状态', '草稿');
    await clickFilterSegment(page, '状态', '完成');
    await clickFilterSegment(page, '状态', '发布');
    await fillFilterRange(page, '最终得分', '0', '100');

    await visit('/hrm/payroll-records', '工资条');
    await fillFirstByPlaceholder(page, '搜索工资条...', scenarioPrefix);
    await page.locator('input[type="month"]').first().fill('2026-07');
    await page.locator('.hpt-filter-field').filter({ hasText: '员工' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await page.locator('.hpt-filter-field').filter({ hasText: '状态' }).locator('.hpt-smart-select').first().click();
    await page.keyboard.press('Escape');
    await clickFilterSegment(page, '员工可见', '是');
    await clickFilterSegment(page, '员工可见', '否');
    await fillFilterRange(page, '实发工资', '0', '999999');
    await openCreateAndCancel('/hrm/payroll-records', /新增工资条/, '新增工资条');

    return { ok: true, scenario: 'hrm-safe-filter-controls', cleanup: 'filter-only and create-modal cancel interactions; no HRM records saved', visited };
  } finally {
    await page.close().catch(() => null);
  }
}

async function scenarioSystemSettingsSafeSaveReset({ context, auth }) {
  const page = await context.newPage();
  const originalSettings = await getSettings(auth, `${runId}-system-settings-original`);
  const restoredKeys = ['companyName', 'companyIndustry', 'contactEmail', 'companyAddress'];
  const nextSettings = {
    ...originalSettings,
    companyName: `场景公司-${runId}`,
    companyIndustry: `SaaS验证-${runId.slice(-6)}`,
    contactEmail: `settings-${runId.slice(-8).toLowerCase()}@example.test`,
    companyAddress: `上海市场景路 ${runId.slice(-4)} 号`,
  };

  const restoreOriginal = async () => {
    const restorePayload = { ...originalSettings };
    for (const key of restoredKeys) {
      if (!Object.prototype.hasOwnProperty.call(originalSettings, key)) restorePayload[key] = null;
    }
    await updateSettings(auth, restorePayload, `${runId}-system-settings-restore`).catch(() => null);
  };

  try {
    await page.goto(`${BASE_URL}/system-settings`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '系统设置');

    for (const tab of ['功能设置', '通知设置', '安全设置', '账户与公司']) {
      await page.getByRole('button', { name: new RegExp(tab) }).click();
      await page.getByText(tab, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    }

    await fillByLabelOrPlaceholder(page, '公司名称', nextSettings.companyName);
    await fillByLabelOrPlaceholder(page, '所属行业', nextSettings.companyIndustry);
    await fillByLabelOrPlaceholder(page, '联系邮箱', nextSettings.contactEmail);
    await fillByLabelOrPlaceholder(page, '公司地址', nextSettings.companyAddress);

    await page.getByRole('button', { name: /^重置$/ }).click();
    await confirmDialog(page, /^重置$/);
    await page.getByRole('button', { name: /账户与公司/ }).click();
    await fillByLabelOrPlaceholder(page, '公司名称', nextSettings.companyName);
    await fillByLabelOrPlaceholder(page, '所属行业', nextSettings.companyIndustry);
    await fillByLabelOrPlaceholder(page, '联系邮箱', nextSettings.contactEmail);
    await fillByLabelOrPlaceholder(page, '公司地址', nextSettings.companyAddress);

    await page.getByRole('button', { name: /保存设置/ }).click();
    await page.getByText('设置已保存成功', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    const saved = await getSettings(auth, `${runId}-system-settings-verify`);
    for (const key of restoredKeys) {
      if (saved[key] !== nextSettings[key]) {
        throw new Error(`System setting ${key} was not saved. expected=${nextSettings[key]} actual=${saved[key]}`);
      }
    }

    await restoreOriginal();
    const restored = await getSettings(auth, `${runId}-system-settings-restored`);
    for (const key of restoredKeys) {
      if ((restored[key] ?? '') !== (originalSettings[key] ?? '')) {
        throw new Error(`System setting ${key} was not restored after scenario`);
      }
    }

    return {
      ok: true,
      scenario: 'system-settings-safe-save-reset',
      cleanup: 'original settings restored through API after browser save/reset verification',
      savedKeys: restoredKeys,
    };
  } finally {
    await page.close().catch(() => null);
    await restoreOriginal();
  }
}

async function scenarioOperationLogsFixtureAudit({ context, auth }) {
  const page = await context.newPage();
  const code = `audit_${runId.slice(-10).toLowerCase()}`.slice(0, 48);
  const name = `审计场景角色-${runId}`;
  let role = null;
  let log = null;
  const cleanup = async () => cleanupResource({
    auth,
    resource: 'roles',
    predicate: (row) => row.code === code || String(row.name || '').startsWith(name),
  });

  await cleanup();
  try {
    role = await createResource({
      auth,
      resource: 'roles',
      data: {
        code,
        name,
        description: scenarioPrefix,
        permissions: [],
        status: 'active',
      },
    });

    await waitForResourcePredicate({
      auth,
      resource: 'operation-logs',
      predicate: (row) => row.targetId === role.id && row.module === 'roles' && row.action === 'create',
      expected: true,
      label: 'Operation log create scenario',
    });
    const operationRows = await requestJson(`${BASE_URL}/api/hrm/operation-logs`, {
      headers: authHeaders(auth, `${runId}-operation-log-list`),
    });
    log = operationRows.find((row) => row.targetId === role.id && row.module === 'roles' && row.action === 'create');
    if (!log) throw new Error(`Created role operation log not found for ${role.id}`);

    await page.goto(`${BASE_URL}/operation-logs`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await waitForMain(page, '操作日志');
    await page.getByPlaceholder('人/模块/对象/IP...', { exact: true }).fill(role.id);
    await fillFirstByPlaceholder(page, '输入操作人', log.userName || '');
    await fillFirstByPlaceholder(page, '输入对象ID', role.id);
    await fillFirstByPlaceholder(page, '起', '2020-01-01');
    await fillFirstByPlaceholder(page, '止', '2099-12-31');

    await chooseSmartSelectOption(
      page,
      page.locator('.hpt-filter-field').filter({ hasText: '所属模块' }).locator('.hpt-smart-select').first(),
      'roles',
    );
    await chooseSmartSelectOption(
      page,
      page.locator('.hpt-filter-field').filter({ hasText: '操作类型' }).locator('.hpt-smart-select').first(),
      '新增',
    );
    await page.locator('select').first().selectOption('50');
    await page.getByText(role.id, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    await page.getByRole('button', { name: /详情/ }).first().click();
    await page.getByText('变更详情', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.getByText(role.id, { exact: true }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });

    const download = await Promise.all([
      page.waitForEvent('download', { timeout: ROUTE_TIMEOUT_MS }),
      page.getByRole('button', { name: /导出CSV/ }).click(),
    ]).then(([item]) => item);
    const suggestedFilename = download.suggestedFilename();
    if (!/操作日志/.test(suggestedFilename)) {
      throw new Error(`Unexpected operation-log export filename: ${suggestedFilename}`);
    }

    return {
      ok: true,
      scenario: 'operation-logs-fixture-audit',
      cleanup: 'temporary role deleted; operation log retained as audit evidence',
      roleId: role.id,
      logId: log.id,
      exported: suggestedFilename,
    };
  } finally {
    await page.close().catch(() => null);
    await cleanup();
  }
}

async function createLifecycleFixture(auth, index, type) {
  const employeeNo = `LC-${runId.slice(-8)}-${index}`.slice(0, 48);
  const employeeName = `生命周期场景-${type}-${runId}`;
  const employeeStatus = type === 'probation' ? 'probation' : 'active';
  const employee = await createResource({
    auth,
    resource: 'employees',
    data: {
      employeeNo,
      name: employeeName,
      email: `${employeeNo.toLowerCase()}@example.test`,
      hireDate: '2026-01-01',
      probationMonths: 3,
      probationEndDate: '2026-04-01',
      status: employeeStatus,
      remark: scenarioPrefix,
    },
  });

  if (type === 'contract') {
    const contractNo = `HT-LC-${runId.slice(-10)}-${index}`.slice(0, 80);
    const record = await createResource({
      auth,
      resource: 'contracts',
      data: {
        employeeId: employee.id,
        contractNo,
        contractType: '劳动合同',
        startDate: '2026-01-01',
        endDate: '2026-12-31',
        status: 'active',
        reminderDate: '2026-12-01',
        remark: scenarioPrefix,
      },
    });
    return { resource: 'contracts', type, employee, employeeNo, employeeName, record, search: contractNo, visibleText: contractNo };
  }

  if (type === 'probation') {
    const resultText = `待评估-${runId.slice(-8)}`;
    const record = await createResource({
      auth,
      resource: 'probations',
      data: {
        employeeId: employee.id,
        applyDate: '2026-03-20',
        expectedRegularDate: '2026-04-01',
        status: 'pending',
        selfReview: scenarioPrefix,
        result: resultText,
      },
    });
    return { resource: 'probations', type, employee, employeeNo, employeeName, record, search: resultText, visibleText: resultText };
  }

  const record = await createResource({
    auth,
    resource: 'resignations',
    data: {
      employeeId: employee.id,
      applyDate: '2026-06-01',
      expectedLeaveDate: '2026-06-30',
      status: 'approved',
      reason: `生命周期场景离职-${runId}`,
      handoverItems: [scenarioPrefix],
    },
  });
  return { resource: 'resignations', type, employee, employeeNo, employeeName, record, search: `生命周期场景离职-${runId}`, visibleText: employeeName };
}

async function cleanupLifecycleFixtures({ auth, fixtures = [] }) {
  const resources = ['contracts', 'probations', 'resignations'];
  for (const resource of resources) {
    await cleanupResource({
      auth,
      resource,
      predicate: (row) => fixtures.some((fixture) => fixture.resource === resource && row.id === fixture.record?.id)
        || String(row.contractNo || row.contract_no || row.reason || row.selfReview || row.result || row.remark || '').includes(runId)
        || String(row.employeeName || '').includes(runId),
    });
  }
  await cleanupResource({
    auth,
    resource: 'employees',
    predicate: (row) => fixtures.some((fixture) => row.id === fixture.employee?.id)
      || String(row.employeeNo || row.employee_no || '').startsWith(`LC-${runId.slice(-8)}`)
      || String(row.name || '').includes(runId)
      || String(row.remark || '').includes(scenarioPrefix),
  });
  await cleanupScenarioNotifications({ auth, fixtures });
}

async function waitForTableText(page, text) {
  await page.locator('main.hpt-main table').getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
}

async function runLifecycleListCase(page, auth, fixture) {
  const config = {
    contracts: {
      path: '/hrm/contracts',
      title: '合同管理',
      searchPlaceholder: '搜索合同管理...',
      dateFilter: '结束日期',
      range: ['2026-01-01', '2027-12-31'],
      workflowAction: '续签合同',
      workflowTrace: 'workflow_renew',
      editField: '合同附件URL预留',
      editValue: `https://example.test/${runId}/contract.pdf`,
      editedText: `https://example.test/${runId}/contract.pdf`,
    },
    probations: {
      path: '/hrm/probations',
      title: '转正管理',
      searchPlaceholder: '搜索转正管理...',
      dateFilter: '申请日期',
      range: ['2026-01-01', '2026-12-31'],
      workflowAction: '通过转正',
      workflowTrace: 'workflow_approve',
      afterWorkflowSearch: '通过',
      afterWorkflowVisibleText: '通过',
      editField: '备注',
      editValue: `转正编辑-${runId}`,
      editedText: `转正编辑-${runId}`,
    },
    resignations: {
      path: '/hrm/resignations',
      title: '离职管理',
      searchPlaceholder: '搜索离职管理...',
      dateFilter: '申请日期',
      range: ['2026-01-01', '2026-12-31'],
      workflowAction: '确认离职',
      workflowTrace: 'workflow_complete',
      editField: 'AI离职原因总结',
      editValue: `离职编辑-${runId}`,
      editedText: `离职编辑-${runId}`,
    },
  }[fixture.resource];

  await page.goto(`${BASE_URL}${config.path}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
  await waitForMain(page, config.title);
  await page.getByPlaceholder(config.searchPlaceholder, { exact: true }).fill(fixture.search);
  await fillFilterRange(page, config.dateFilter, config.range[0], config.range[1]);
  await waitForTableText(page, fixture.visibleText);

  await page.getByRole('button', { name: /^详情$/ }).first().click();
  await page.getByText('工作流动作', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  await page.getByText('流程时间线', { exact: true }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  await page.getByRole('button', { name: config.workflowAction, exact: true }).first().click();
  await confirmDialog(page, new RegExp(config.workflowAction));
  await page.getByText(config.workflowTrace).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
  await page.getByRole('button', { name: /^关闭$/ }).last().click();

  const nextSearch = config.afterWorkflowSearch || fixture.search;
  const nextVisibleText = config.afterWorkflowVisibleText || fixture.visibleText;
  await page.getByPlaceholder(config.searchPlaceholder, { exact: true }).fill(nextSearch);
  await waitForTableText(page, nextVisibleText);
  await page.getByRole('button', { name: /^编辑$/ }).first().click();
  await fillByLabelOrPlaceholder(page, config.editField, config.editValue);
  await page.getByRole('button', { name: /^保存$/ }).click();
  await waitForResourcePredicate({
    auth,
    resource: fixture.resource,
    predicate: (row) => row.id === fixture.record.id && JSON.stringify(row).includes(config.editedText),
    expected: true,
    label: `${fixture.resource} lifecycle edit scenario`,
  });
  await page.getByPlaceholder(config.searchPlaceholder, { exact: true }).fill(nextSearch);
  await waitForTableText(page, nextVisibleText);

  const updated = await requestJson(`${BASE_URL}/api/hrm/${fixture.resource}/${fixture.record.id}`, {
    headers: authHeaders(auth, `${runId}-verify-lifecycle-edit-${fixture.resource}`),
  });
  if (!JSON.stringify(updated).includes(config.editedText)) {
    throw new Error(`Lifecycle edit was not persisted for ${fixture.resource}: ${JSON.stringify(updated).slice(0, 500)}`);
  }

  await page.getByRole('button', { name: /^删除$/ }).first().click();
  await confirmDialog(page, /^删除$/);
  await waitForResourcePredicate({
    auth,
    resource: fixture.resource,
    predicate: (row) => row.id === fixture.record.id,
    expected: false,
    label: `${fixture.resource} lifecycle delete scenario`,
  });

  return {
    resource: fixture.resource,
    path: config.path,
    searched: fixture.search,
    workflowAction: config.workflowAction,
    editField: config.editField,
  };
}

async function scenarioLifecycleListWorkflows({ context, auth }) {
  const page = await context.newPage();
  const fixtures = [];
  await cleanupLifecycleFixtures({ auth, fixtures });
  try {
    fixtures.push(await createLifecycleFixture(auth, 1, 'contract'));
    fixtures.push(await createLifecycleFixture(auth, 2, 'probation'));
    fixtures.push(await createLifecycleFixture(auth, 3, 'resignation'));

    const cases = [];
    for (const fixture of fixtures) {
      cases.push(await runLifecycleListCase(page, auth, fixture));
    }

    return {
      ok: true,
      scenario: 'lifecycle-list-workflows',
      cleanup: 'contract, probation, resignation records deleted through UI; fixture employees and workflow notifications cleaned by API',
      cases,
    };
  } finally {
    await page.close().catch(() => null);
    await cleanupLifecycleFixtures({ auth, fixtures });
  }
}

const scenarioFns = {
  'employees-crud': scenarioEmployeesCrud,
  'roles-crud': scenarioRolesCrud,
  'job-manage-fixture-list': scenarioJobManageFixtureList,
  'job-create': scenarioJobCreate,
  'ai-settings-save': scenarioAiSettingsSave,
  'ai-settings-controls': scenarioAiSettingsControls,
  'ai-settings-safe-controls': scenarioAiSettingsSafeControls,
  'platform-ai-entitlement-management': scenarioPlatformAiEntitlementManagement,
  'tenant-ai-usage-and-tier-selection': scenarioTenantAiUsageAndTierSelection,
  'home-navigation': scenarioHomeNavigation,
  'home-dashboard-secondary-navigation': scenarioHomeDashboardSecondaryNavigation,
  'job-create-required-fields': scenarioJobCreateRequiredFields,
  'exam-center-non-ai-controls': scenarioExamCenterNonAiControls,
  'hrm-safe-filter-controls': scenarioHrmSafeFilterControls,
  'system-settings-safe-save-reset': scenarioSystemSettingsSafeSaveReset,
  'operation-logs-fixture-audit': scenarioOperationLogsFixtureAudit,
  'lifecycle-list-workflows': scenarioLifecycleListWorkflows,
};

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Usage: node scripts/verify-saas-priority-scenarios.mjs [--scenario <name>]');
    console.log(`Scenarios: ${Object.keys(scenarioFns).join(', ')}`);
    return 0;
  }

  const selected = args.scenarios.length ? args.scenarios : Object.keys(scenarioFns);
  const unknown = selected.filter((name) => !scenarioFns[name]);
  if (unknown.length) throw new Error(`Unknown scenario(s): ${unknown.join(', ')}`);

  await mkdir(ARTIFACT_DIR, { recursive: true });
  const hrmResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  console.log(`Priority scenario credentials: ${hrmResult.source} tenant=${hrmResult.credentials.tenantSlug} email=${hrmResult.credentials.email}`);

  const { chromium } = await importPlaywright();
  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await addAuthToContext(context, hrmResult.auth);

  const results = [];
  try {
    for (const name of selected) {
      const started = Date.now();
      try {
        await addAuthToContext(context, hrmResult.auth);
        const result = await scenarioFns[name]({ context, auth: hrmResult.auth });
        results.push({ ...result, durationMs: Date.now() - started });
        console.log(`PASS ${name} ${Date.now() - started}ms`);
      } catch (error) {
        const screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(name)}-failure.png`);
        const page = context.pages().at(-1);
        await page?.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
        results.push({
          ok: false,
          scenario: name,
          error: error?.stack || error?.message || String(error),
          screenshotPath,
          durationMs: Date.now() - started,
        });
        console.log(`FAIL ${name} ${Date.now() - started}ms`);
      }
    }
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
  }

  const failed = results.filter((item) => !item.ok);
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const report = {
    ok: failed.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    scenarioCount: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    results,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    scenarioCount: report.scenarioCount,
    passed: report.passed,
    failed: report.failed,
    reportPath,
    failures: failed.map((item) => ({
      scenario: item.scenario,
      error: compact(item.error).slice(0, 300),
      screenshotPath: item.screenshotPath,
    })),
  }, null, 2));

  if (!report.ok) return 1;
  return 0;
}

main().then((code) => {
  process.exitCode = code;
}).catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exitCode = 1;
});
