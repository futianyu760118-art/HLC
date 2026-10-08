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
const runId = `accessibility-smoke-${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`;

const readJson = async (response, label) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} did not return JSON: ${text.slice(0, 400)}`);
  }
};

const platformLogin = async () => {
  const identifier = process.env.HRM_PLATFORM_EMAIL || process.env.HRM_TEST_PLATFORM_EMAIL || dotEnv.PLATFORM_ADMIN_EMAIL || 'platform@example.com';
  const password = process.env.HRM_PLATFORM_PASSWORD || process.env.HRM_TEST_PLATFORM_PASSWORD || dotEnv.PLATFORM_ADMIN_PASSWORD || 'Passw0rd!';
  const response = await fetch(`${BASE_URL}/api/platform/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': `${runId}-platform-login` },
    body: JSON.stringify({ identifier, password }),
  });
  const payload = await readJson(response, 'platform login');
  if (!response.ok) throw new Error(payload?.error || `Platform login failed: ${response.status}`);
  return payload;
};

const checkRoute = async (context, route, auth, findings) => {
  const page = await context.newPage();
  await page.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });
  await page.goto(`${BASE_URL}${route}`, { waitUntil: 'domcontentloaded' });
  if (route.startsWith('/platform')) {
    await page.getByText('恒聘通平台后台').waitFor({ state: 'visible', timeout: 10000 });
  } else {
    await page.waitForSelector('main.hpt-main', { timeout: 10000 });
  }
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => null);
  await page.keyboard.press('Tab');
  const activeTag = await page.evaluate(() => document.activeElement?.tagName || '');
  if (!activeTag || activeTag === 'BODY') findings.push(`${route}: no meaningful active element after Tab`);

  const iconButtonsWithoutLabel = await page.locator('button:has(i), button:has(svg)').evaluateAll((nodes) => nodes
    .filter((node) => !node.getAttribute('aria-label') && !node.textContent?.trim())
    .map((node) => node.outerHTML.slice(0, 160)));
  if (iconButtonsWithoutLabel.length) {
    findings.push(`${route}: ${iconButtonsWithoutLabel.length} icon buttons without text or aria-label`);
  }
  await page.close();
};

const main = async () => {
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const [{ auth: hrmAuth }, platformAuth] = await Promise.all([
    resolveHrmSmokeCredentials({
      baseUrl: BASE_URL,
      env: process.env,
      dotEnv,
      fetchImpl: fetch,
      runId,
    }),
    platformLogin(),
  ]);

  const { chromium } = await importPlaywright();
  const browser = await chromium.launch({
    executablePath: EDGE_EXECUTABLE,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const findings = [];

  try {
    await checkRoute(context, '/home', hrmAuth, findings);
    await checkRoute(context, '/feedback', hrmAuth, findings);
    await checkRoute(context, '/platform/tenants', platformAuth, findings);
  } finally {
    await browser.close();
  }

  const report = { ok: findings.length === 0, runId, baseUrl: BASE_URL, findings };
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ ...report, reportPath }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
});
