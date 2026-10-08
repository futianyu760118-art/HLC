// @ts-nocheck
/** 移动端响应式验证：手机(375) + 桌面(1440) 各截门户首页 */
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE = 'https://localhost:18445';
const ART = path.resolve('artifacts', 'mobile-test');
const PW = 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PWP = path.join(PW, '.pnpm', 'playwright@1.60.0', 'node_modules');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

async function pw() {
  try { return await import('playwright'); }
  catch {
    const r = createRequire(pathToFileURL(path.join(PWP, 'playwright', 'package.json')).href);
    return r('playwright');
  }
}

await mkdir(ART, { recursive: true });

const loginResp = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'zhangsan@test.com', password: 'Employee@2026' }),
});
const { token } = await loginResp.json();

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

const shots = [
  { w: 1440, h: 900, file: 'desktop-portal.png', label: '桌面1440-门户' },
  { w: 375, h: 812, file: 'mobile-portal.png', label: '手机375-门户' },
  { w: 375, h: 812, file: 'mobile-courses.png', label: '手机375-课程', path: '/portal/my-courses' },
];

for (const s of shots) {
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: s.w, height: s.h },
  });
  await ctx.addInitScript((t) => {
    localStorage.setItem('token', t);
    localStorage.setItem('user', JSON.stringify({ id: 'u1', email: 'zhangsan@test.com', name: '张三', role: 'employee' }));
  }, token);
  const page = await ctx.newPage();
  try {
    await page.goto(`${BASE}${s.path || '/portal'}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(ART, s.file), fullPage: true });
    console.log(`✓ ${s.label} → ${s.file}`);
  } catch (e) { console.error(`✗ ${s.label}: ${e.message.slice(0, 80)}`); }
  await ctx.close();
}

await browser.close();
console.log('完成');
