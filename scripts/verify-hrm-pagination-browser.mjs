import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { EDGE_EXECUTABLE, importPlaywright } from './resolve-playwright-runtime.mjs';
import { resolveHrmSmokeCredentials } from './hrm-smoke-credentials.mjs';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
if (new URL(BASE_URL).port === '18080') {
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
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_PAGINATION_BROWSER_TIMEOUT_MS || 30000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_PAGINATION_BROWSER_RUN_ID || `hrm-pagination-${stamp}`;

const routes = [
  { path: '/hrm/employees', resource: 'employees', expect: '员工档案' },
  { path: '/hrm/contracts', resource: 'contracts', expect: '合同管理' },
];

async function main() {
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const authResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  console.log(`HRM pagination browser credentials: ${authResult.source} tenant=${authResult.credentials.tenantSlug} email=${authResult.credentials.email}`);

  const { chromium } = await importPlaywright();
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
  }, { token: authResult.auth.token, user: authResult.auth.user });

  const page = await context.newPage();
  const apiHits = [];
  page.on('request', (request) => {
    const url = request.url();
    if (url.includes('/api/hrm/')) apiHits.push(url);
  });

  const results = [];
  try {
    for (const route of routes) {
      const started = Date.now();
      apiHits.length = 0;
      await page.goto(`${BASE_URL}${route.path}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
      await page.locator('main.hpt-main').waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      await page.getByText(route.expect, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      await page.getByRole('button', { name: '下一页' }).waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      await page.getByLabel('每页条数').waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      const matchingHits = apiHits.filter((url) => {
        const parsed = new URL(url);
        return parsed.pathname.endsWith(`/api/hrm/${route.resource}`)
          && parsed.searchParams.get('page') === '1'
          && parsed.searchParams.get('size') === '50';
      });
      const summaryText = await page.locator('main.hpt-main').innerText({ timeout: 5000 });
      const ok = matchingHits.length > 0 && summaryText.includes('上一页') && summaryText.includes('下一页') && summaryText.includes('共');
      const result = {
        ok,
        route: route.path,
        resource: route.resource,
        durationMs: Date.now() - started,
        matchingHits,
        apiHits: apiHits.slice(0, 12),
        textSample: summaryText.replace(/\s+/g, ' ').trim().slice(0, 300),
      };
      results.push(result);
      console.log(`${ok ? 'PASS' : 'FAIL'} ${route.path} ${result.durationMs}ms`);
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
    results,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    passed: results.length - failed.length,
    failed: failed.length,
    reportPath,
  }, null, 2));
  process.exitCode = report.ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exitCode = 1;
});

