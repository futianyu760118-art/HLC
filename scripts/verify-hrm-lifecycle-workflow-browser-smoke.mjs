import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { EDGE_EXECUTABLE, importPlaywright } from './resolve-playwright-runtime.mjs';
import { resolveHrmSmokeCredentials } from './hrm-smoke-credentials.mjs';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
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
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_LIFECYCLE_WORKFLOW_SMOKE_RUN_ID || `lifecycle-workflow-smoke-${stamp}`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const asJson = async (response, label) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`${label} did not return JSON`, { status: response.status, text: text.slice(0, 500) });
  }
};

const requestJson = async (token, method, urlPath, body) => {
  const response = await fetch(`${BASE_URL}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-Request-ID': `${runId}-${method.toLowerCase()}-${urlPath.replace(/[^a-z0-9]+/gi, '-').slice(0, 60)}`,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await asJson(response, `${method} ${urlPath}`);
  if (!response.ok) {
    fail(`${method} ${urlPath} failed`, { status: response.status, payload });
  }
  return payload;
};

const compactRunKey = () => runId.replace(/[^a-z0-9]+/gi, '').slice(-18) || String(Date.now()).slice(-10);

const createEmployee = async (token, suffix, status) => (
  requestJson(token, 'POST', '/api/hrm/employees', {
    employeeNo: `WF-${compactRunKey()}-${suffix}`.slice(0, 48),
    name: `工作流烟测${suffix}`,
    email: `workflow-${compactRunKey().toLowerCase()}-${suffix.toLowerCase()}@example.test`,
    hireDate: '2026-01-01',
    probationMonths: 3,
    probationEndDate: '2026-04-01',
    status,
  })
);

const prepareFixtures = async (token) => {
  const contractEmployee = await createEmployee(token, '合同', 'active');
  const probationEmployee = await createEmployee(token, '转正', 'probation');
  const resignationEmployee = await createEmployee(token, '离职', 'active');

  const contract = await requestJson(token, 'POST', '/api/hrm/contracts', {
    employeeId: contractEmployee.id,
    contractNo: `HT-WF-${compactRunKey()}`,
    contractType: '劳动合同',
    startDate: '2026-01-01',
    endDate: '2026-12-31',
    status: 'active',
    reminderDate: '2026-12-01',
  });
  const probation = await requestJson(token, 'POST', '/api/hrm/probations', {
    employeeId: probationEmployee.id,
    applyDate: '2026-03-20',
    expectedRegularDate: '2026-04-01',
    status: 'pending',
    selfReview: '浏览器工作流烟测',
  });
  const resignation = await requestJson(token, 'POST', '/api/hrm/resignations', {
    employeeId: resignationEmployee.id,
    applyDate: '2026-06-01',
    expectedLeaveDate: '2026-06-30',
    status: 'approved',
    reason: '浏览器工作流烟测',
    handoverItems: ['浏览器工作流烟测交接'],
  });

  return [
    {
      module: 'contracts',
      label: '合同工作流',
      id: contract.id,
      url: `/hrm/contracts?id=${contract.id}`,
      actionLabel: '续签合同',
      actionTrace: 'workflow_renew',
    },
    {
      module: 'probations',
      label: '转正工作流',
      id: probation.id,
      url: `/hrm/probations?id=${probation.id}`,
      actionLabel: '通过转正',
      actionTrace: 'workflow_approve',
    },
    {
      module: 'resignations',
      label: '离职工作流',
      id: resignation.id,
      url: `/hrm/resignations?id=${resignation.id}`,
      actionLabel: '确认离职',
      actionTrace: 'workflow_complete',
    },
  ];
};

const hasIgnorableConsoleError = (message) => (
  /favicon\.ico/i.test(message)
  || /ResizeObserver loop/i.test(message)
  || /net::ERR_ABORTED/i.test(message)
  || /Failed to load resource: the server responded with a status of 404 \(NOT FOUND\)/i.test(message)
);

const verifyWorkflowApis = async (token, cases) => {
  for (const testCase of cases) {
    const response = await fetch(`${BASE_URL}/api/hrm/${testCase.module}/${testCase.id}/workflow`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Request-ID': `${runId}-workflow-preflight-${testCase.module}`,
      },
    });
    if (response.status === 404) {
      fail('Lifecycle workflow smoke requires the preview backend to expose workflow APIs. Rebuild/restart only the SaaS preview backend, then rerun this check.', {
        baseUrl: BASE_URL,
        api: `/api/hrm/${testCase.module}/${testCase.id}/workflow`,
        status: response.status,
        body: (await response.text()).slice(0, 500),
      });
    }
    if (!response.ok) {
      fail('Lifecycle workflow API preflight failed', {
        baseUrl: BASE_URL,
        api: `/api/hrm/${testCase.module}/${testCase.id}/workflow`,
        status: response.status,
        body: (await response.text()).slice(0, 500),
      });
    }
  }
};

const runWorkflowCase = async (context, testCase) => {
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const startedAt = Date.now();
  let screenshotPath = null;

  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (!hasIgnorableConsoleError(text)) consoleErrors.push(text);
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error?.stack || error?.message || String(error));
  });

  try {
    await page.goto(`${BASE_URL}${testCase.url}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('main.hpt-main', { timeout: 30000 });
    await page.getByText('工作流动作').waitFor({ state: 'visible', timeout: 30000 });
    await page.getByText('流程时间线').waitFor({ state: 'visible', timeout: 10000 });
    await page.getByRole('button', { name: testCase.actionLabel, exact: true }).first().click();
    await page.getByRole('dialog').getByRole('button', { name: testCase.actionLabel, exact: true }).click();
    await page.getByText(testCase.actionTrace).waitFor({ state: 'visible', timeout: 30000 });

    if (consoleErrors.length || pageErrors.length) {
      fail('Lifecycle workflow browser case emitted errors', { testCase, consoleErrors, pageErrors });
    }

    return {
      ok: true,
      ...testCase,
      durationMs: Date.now() - startedAt,
    };
  } catch (error) {
    screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${testCase.module}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    return {
      ok: false,
      ...testCase,
      durationMs: Date.now() - startedAt,
      screenshotPath,
      consoleErrors,
      pageErrors,
      error: error?.stack || error?.message || String(error),
    };
  } finally {
    await page.close().catch(() => null);
  }
};

const main = async () => {
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const credentialResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  const auth = credentialResult.auth;
  if (!auth?.token || !auth?.user) fail('Lifecycle workflow smoke login returned no token or user');
  console.log(`Lifecycle workflow smoke credentials: ${credentialResult.source} tenant=${credentialResult.credentials.tenantSlug} email=${credentialResult.credentials.email}`);

  const cases = await prepareFixtures(auth.token);
  await verifyWorkflowApis(auth.token, cases);
  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });

  const results = [];
  try {
    for (const testCase of cases) {
      const result = await runWorkflowCase(context, testCase);
      results.push(result);
      console.log(`${result.ok ? 'PASS' : 'FAIL'} ${testCase.url} ${testCase.label} ${result.durationMs}ms`);
    }
  } finally {
    await browser.close().catch(() => null);
  }

  const failed = results.filter((item) => !item.ok);
  const report = {
    ok: failed.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    routeCount: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    reportPath,
    results,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    routeCount: report.routeCount,
    passed: report.passed,
    failed: report.failed,
    reportPath,
    failures: failed.map((item) => ({
      module: item.module,
      url: item.url,
      actionLabel: item.actionLabel,
      screenshotPath: item.screenshotPath,
      error: item.error,
      consoleErrors: item.consoleErrors?.slice(0, 3) || [],
      pageErrors: item.pageErrors?.slice(0, 2) || [],
    })),
  }, null, 2));

  if (failed.length) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
