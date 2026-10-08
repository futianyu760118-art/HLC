// 截图脚本：全部培训+考试新页面
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE_URL = 'https://localhost:18445';
const ARTIFACT_DIR = path.resolve('artifacts', 'ui-preview');
const PW_MODULE = 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PW_PNPM = path.join(PW_MODULE, '.pnpm', 'playwright@1.60.0', 'node_modules');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

async function importPlaywright() {
  try { return await import('playwright'); }
  catch {
    const pkg = path.join(PW_PNPM, 'playwright', 'package.json');
    const r = createRequire(pathToFileURL(pkg).href);
    return r('playwright');
  }
}

await mkdir(ARTIFACT_DIR, { recursive: true });

const loginResp = await fetch(`${BASE_URL}/api/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: '3420849544@qq.com', password: 'Admin@2026' }),
});
const { token } = await loginResp.json();
console.log('登录成功');

const { chromium } = await importPlaywright();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
await context.addInitScript((t) => {
  localStorage.setItem('token', t);
  localStorage.setItem('user', JSON.stringify({ id: '893a756b', email: '3420849544@qq.com', name: 'xiaofu', role: 'admin' }));
}, token);

const page = await context.newPage();

const shots = [
  { url: '/training-center', file: '01-course-catalog.png', label: '课程目录' },
  { url: '/course-categories', file: '02-categories.png', label: '课程分类' },
  { url: '/exam-generate', file: '03-ai-generate.png', label: '智能出题' },
  { url: '/exam-center', file: '04-question-bank.png', label: '题库管理' },
  { url: '/exam-papers', file: '05-papers.png', label: '试卷组卷' },
  { url: '/exam-tasks', file: '06-tasks.png', label: '考试安排' },
  { url: '/exam-attempts', file: '07-results.png', label: '成绩管理' },
];

for (const s of shots) {
  try {
    await page.goto(`${BASE_URL}${s.url}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(1800);
    const p = path.join(ARTIFACT_DIR, s.file);
    await page.screenshot({ path: p, fullPage: true });
    console.log(`✓ ${s.label} → ${s.file}`);
  } catch (e) {
    console.error(`✗ ${s.label}:`, e.message.slice(0, 80));
  }
}

await browser.close();
console.log('完成');
