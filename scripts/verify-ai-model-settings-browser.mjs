import { mkdir } from 'node:fs/promises';
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
const KEYWORD = process.env.HRM_AUDIT_KEYWORD || process.env.HRM_TEST_SUITE_ID || 'siliconflow';
const PLAYWRIGHT_MODULE_DIR = process.env.NODE_REPL_NODE_MODULE_DIRS
  || 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PLAYWRIGHT_PNPM_MODULE_DIR = process.env.PLAYWRIGHT_PNPM_MODULE_DIR
  || path.join(PLAYWRIGHT_MODULE_DIR, '.pnpm', 'playwright@1.60.0', 'node_modules');
const EDGE_EXECUTABLE = process.env.HRM_BROWSER_EXECUTABLE
  || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
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

const textIncludes = (text, needle) => text.toLowerCase().includes(String(needle).toLowerCase());

const firstVisible = async (page, selectors) => {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      await locator.waitFor({ state: 'visible', timeout: 1500 });
      return locator;
    } catch {
      // Try next selector.
    }
  }
  return null;
};

const sanitize = (value) => String(value || '')
  .replace(/[^a-z0-9_-]+/gi, '-')
  .replace(/^-|-$/g, '')
  .slice(0, 80);

const main = async () => {
  const { chromium } = await importPlaywright();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 17);
  const keywordSlug = sanitize(KEYWORD);
  const screenshotPath = path.join(
    ARTIFACT_DIR,
    `ai-model-settings-${stamp}${keywordSlug ? `-${keywordSlug}` : ''}.png`,
  );

  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

  try {
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const emailInput = await firstVisible(page, [
      'input[type="email"]',
      'input[name="email"]',
      'input[placeholder*="邮箱"]',
      'input[placeholder*="账号"]',
      'input',
    ]);
    const passwordInput = await firstVisible(page, [
      'input[type="password"]',
      'input[name="password"]',
      'input[placeholder*="密码"]',
    ]);
    if (!emailInput || !passwordInput) fail('Login form inputs were not found');

    await emailInput.fill('');
    await emailInput.type(EMAIL, { delay: 2 });
    await passwordInput.fill('');
    await passwordInput.type(PASSWORD, { delay: 2 });
    await page.getByRole('button', { name: /登录|Login/i }).click();
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 20000 });

    await page.goto(`${BASE_URL}/ai-model-settings`, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector('text=AI 模型管理', { timeout: 20000 });

    const keywordInput = page.locator('input[placeholder*="搜索请求"], input[placeholder*="搜索"]').last();
    if (await keywordInput.count()) {
      await keywordInput.fill('');
      await keywordInput.type(KEYWORD, { delay: 2 });
      await page.getByRole('button', { name: /刷新/ }).last().click();
      await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => null);
      await page.waitForTimeout(1000);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });
    const bodyText = await page.locator('body').innerText({ timeout: 10000 });
    const required = [
      'AI 模型管理',
      'Copilot 系统化评估',
      '提问与模型调用审计',
      'SiliconFlow',
      'deepseek-ai/DeepSeek-V4-Pro',
    ];
    const missing = required.filter((item) => !bodyText.includes(item));
    if (missing.length) fail('AI model settings page is missing required visible text', { missing, screenshotPath });
    if (!textIncludes(bodyText, KEYWORD) && KEYWORD !== 'siliconflow') {
      fail('AI model settings page did not show the requested audit keyword', { keyword: KEYWORD, screenshotPath });
    }

    const passRows = await page.locator('text=pass').count();
    const successRows = await page.locator('text=success').count();
    const siliconRows = await page.locator('text=SiliconFlow').count();
    if (passRows < 1) fail('No visible Copilot evaluation pass result found', { screenshotPath });
    if (successRows < 1) fail('No visible model audit success status found', { screenshotPath });
    if (siliconRows < 1) fail('No visible SiliconFlow provider found', { screenshotPath });

    console.log(JSON.stringify({
      ok: true,
      baseUrl: BASE_URL,
      keyword: KEYWORD,
      screenshotPath,
      counts: {
        passRows,
        successRows,
        siliconRows,
      },
      page: `${BASE_URL}/ai-model-settings`,
    }, null, 2));
  } finally {
    await browser.close();
  }
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
