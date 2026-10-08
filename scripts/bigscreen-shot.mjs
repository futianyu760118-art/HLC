// 大屏截图
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

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

await mkdir('artifacts/ui-preview', { recursive: true });
const loginResp = await fetch('https://localhost:18445/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: '3420849544@qq.com', password: 'Admin@2026' }),
});
const { token } = await loginResp.json();
const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1920, height: 1080 } });
await ctx.addInitScript((t) => {
  localStorage.setItem('token', t);
  localStorage.setItem('user', JSON.stringify({ id: '893a756b', email: '3420849544@qq.com', name: 'xiaofu', role: 'admin' }));
}, token);
const page = await ctx.newPage();
await page.goto('https://localhost:18445/bigscreen', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3000);
await page.screenshot({ path: 'artifacts/ui-preview/bigscreen.png' });
console.log('✓ 大屏截图完成');
await browser.close();
