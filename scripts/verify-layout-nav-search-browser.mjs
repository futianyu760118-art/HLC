import { existsSync, readFileSync } from 'node:fs';
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

const runId = `layout-nav-search-${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`;
const { chromium } = await importPlaywright();
const auth = await resolveHrmSmokeCredentials({
  baseUrl: BASE_URL,
  env: process.env,
  dotEnv,
  fetchImpl: fetch,
  runId,
}).then((result) => result.auth);

const browser = await chromium.launch({
  executablePath: EDGE_EXECUTABLE,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });

  const page = await context.newPage();
  await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('main.hpt-main', { timeout: 15000 });

  const search = page.getByRole('textbox', { name: '导航搜索' });
  await search.fill('员工档案');
  await page.getByRole('button', { name: /员工档案.*员工管理/ }).click();
  await page.waitForURL(/\/hrm\/employees$/, { timeout: 8000 });
  await page.getByText('员工档案').first().waitFor({ state: 'visible', timeout: 8000 });

  await page.goto(`${BASE_URL}/home`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: '导航搜索' }).fill('审批');
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/approval-center\/my-applications$/, { timeout: 8000 });

  console.log('layout nav search browser verification passed');
} finally {
  await browser.close();
}
