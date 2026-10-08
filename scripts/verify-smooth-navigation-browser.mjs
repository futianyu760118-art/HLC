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
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_SMOOTH_NAV_TIMEOUT_MS || 30000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_SMOOTH_NAV_RUN_ID || `smooth-navigation-${stamp}`;

const routes = [
  { path: '/hrm/employees', expect: '员工档案' },
  { path: '/hrm/contracts', expect: '合同管理' },
  { path: '/hrm/probations', expect: '转正管理' },
  { path: '/hrm/employees', expect: '员工档案' },
];

async function main() {
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const hrmResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  console.log(`Smooth navigation credentials: ${hrmResult.source} tenant=${hrmResult.credentials.tenantSlug} email=${hrmResult.credentials.email}`);

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
    const documentLoadCount = Number(window.sessionStorage.getItem('hpt:test:documentLoadCount') || '0') + 1;
    window.sessionStorage.setItem('hpt:test:documentLoadCount', String(documentLoadCount));
  }, { token: hrmResult.auth.token, user: hrmResult.auth.user });

  const page = await context.newPage();
  let tenantModuleRequestCount = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/hrm/tenant/modules') {
      tenantModuleRequestCount += 1;
    }
  });
  const results = [];
  try {
    const initialRoute = routes[0];
    const initialModuleResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/hrm/tenant/modules',
      { timeout: ROUTE_TIMEOUT_MS },
    );
    const initialStarted = Date.now();
    await page.goto(`${BASE_URL}${initialRoute.path}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await page.locator('main.hpt-main').waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await page.locator('main.hpt-main').getByText(initialRoute.expect, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
    await initialModuleResponse;
    await page.evaluate(() => {
      window.__hptStableSidebarNode = document.querySelector('aside');
    });
    const initialState = await page.evaluate(() => ({
      documentLoadCount: Number(window.sessionStorage.getItem('hpt:test:documentLoadCount') || '0'),
      sidebarNodeStable: window.__hptStableSidebarNode === document.querySelector('aside'),
    }));
    const initialMainText = await page.locator('main.hpt-main').innerText({ timeout: 5000 });
    results.push({
      ok: Boolean(initialMainText.trim()) && initialState.documentLoadCount === 1 && initialState.sidebarNodeStable && tenantModuleRequestCount === 1,
      route: initialRoute.path,
      durationMs: Date.now() - initialStarted,
      pageLoadingCount: await page.getByText('正在加载模块...', { exact: true }).count(),
      documentLoadCount: initialState.documentLoadCount,
      sidebarNodeStable: initialState.sidebarNodeStable,
      tenantModuleRequestCount,
      mainTextSample: initialMainText.replace(/\s+/g, ' ').trim().slice(0, 240),
    });
    console.log(`${results.at(-1).ok ? 'PASS' : 'FAIL'} ${initialRoute.path} ${results.at(-1).durationMs}ms`);

    for (const route of routes.slice(1)) {
      const started = Date.now();
      const link = page.locator(`aside a[href="${route.path}"]`).first();
      await link.scrollIntoViewIfNeeded();
      await link.click();
      await page.waitForURL((url) => url.pathname === route.path, { timeout: ROUTE_TIMEOUT_MS });
      await page.locator('main.hpt-main').waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      await page.locator('main.hpt-main').getByText(route.expect, { exact: false }).first().waitFor({ state: 'visible', timeout: ROUTE_TIMEOUT_MS });
      const mainText = await page.locator('main.hpt-main').innerText({ timeout: 5000 });
      const pageLoadingCount = await page.getByText('正在加载模块...', { exact: true }).count();
      const hasFullSurface = await page.locator('main.hpt-main').boundingBox();
      const navigationState = await page.evaluate(() => ({
        documentLoadCount: Number(window.sessionStorage.getItem('hpt:test:documentLoadCount') || '0'),
        sidebarNodeStable: window.__hptStableSidebarNode === document.querySelector('aside'),
      }));
      const durationMs = Date.now() - started;
      results.push({
        ok: Boolean(mainText.trim())
          && pageLoadingCount === 0
          && Boolean(hasFullSurface)
          && navigationState.documentLoadCount === 1
          && navigationState.sidebarNodeStable
          && tenantModuleRequestCount === 1,
        route: route.path,
        durationMs,
        pageLoadingCount,
        documentLoadCount: navigationState.documentLoadCount,
        sidebarNodeStable: navigationState.sidebarNodeStable,
        tenantModuleRequestCount,
        mainTextSample: mainText.replace(/\s+/g, ' ').trim().slice(0, 240),
      });
      console.log(`${results.at(-1).ok ? 'PASS' : 'FAIL'} ${route.path} ${durationMs}ms`);
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
  return report.ok ? 0 : 1;
}

main().then((code) => {
  process.exitCode = code;
}).catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exitCode = 1;
});
