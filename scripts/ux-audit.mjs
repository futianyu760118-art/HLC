// 全量页面截图体验测试
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE = 'https://localhost:18445';
const ART = path.resolve('artifacts', 'ux-audit');
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

const adminLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: '3420849544@qq.com', password: 'Admin@2026' }),
});
const adminTok = (await adminLogin.json()).token;

const empLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'zhangsan@test.com', password: 'Employee@2026' }),
});
const empTok = (await empLogin.json()).token;

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

async function shot(token, role, url, file, label, actions) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const user = role === 'admin'
    ? { id: 'u-admin', email: '3420849544@qq.com', name: 'xiaofu', role: 'admin' }
    : { id: 'u-zhangsan', email: 'zhangsan@test.com', name: '张三', role: 'employee' };
  await ctx.addInitScript((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }, token, user);
  const page = await ctx.newPage();
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(2000);
    if (actions) await actions(page);
    await page.screenshot({ path: path.join(ART, file), fullPage: true });
    console.log(`✓ ${label} → ${file}`);
  } catch (e) { console.error(`✗ ${label}: ${e.message.slice(0, 80)}`); }
  await ctx.close();
}

// 管理侧页面
await shot(adminTok, 'admin', '/training-center', 'admin-01-courses.png', '课程目录');
await shot(adminTok, 'admin', '/course-categories', 'admin-02-categories.png', '课程分类');
await shot(adminTok, 'admin', '/exam-generate', 'admin-03-ai-generate.png', '智能出题');
await shot(adminTok, 'admin', '/exam-center', 'admin-04-question-bank.png', '题库管理');
await shot(adminTok, 'admin', '/exam-papers', 'admin-05-papers.png', '试卷组卷');
await shot(adminTok, 'admin', '/exam-tasks', 'admin-06-tasks.png', '考试安排');
await shot(adminTok, 'admin', '/exam-attempts', 'admin-07-results.png', '成绩管理');
await shot(adminTok, 'admin', '/learning-paths', 'admin-08-paths.png', '学习路径');
await shot(adminTok, 'admin', '/competency', 'admin-09-competency.png', '胜任力测评');
await shot(adminTok, 'admin', '/analytics', 'admin-10-dashboard.png', '数据看板');
await shot(adminTok, 'admin', '/pk-seasons', 'admin-11-pk.png', '团队PK竞赛');

// 课程编辑器（点编辑按钮进编辑页）
await shot(adminTok, 'admin', '/course-edit/' + await fetch(`${BASE}/api/hrm/courses`, {
  headers: { Authorization: `Bearer ${adminTok}` }
}).then(r => r.json()).then(d => (d[0] || d.items?.[0])?.id || ''), 'admin-12-course-edit.png', '课程编辑器');

// 员工门户页面
await shot(empTok, 'employee', '/portal', 'emp-01-home.png', '门户首页');
await shot(empTok, 'employee', '/portal/my-courses', 'emp-02-courses.png', '我的课程');
await shot(empTok, 'employee', '/portal/learning-paths', 'emp-03-paths.png', '学习路径');
await shot(empTok, 'employee', '/portal/wrong-questions', 'emp-04-wrong.png', '错题本');
await shot(empTok, 'employee', '/portal/competency', 'emp-05-competency.png', '能力测评');
await shot(empTok, 'employee', '/portal/points', 'emp-06-points.png', '学习积分');
await shot(empTok, 'employee', '/portal/shop', 'emp-07-shop.png', '积分商城');
await shot(empTok, 'employee', '/portal/certificates', 'emp-08-certificates.png', '我的证书');
await shot(empTok, 'employee', '/portal/my-profile', 'emp-09-profile.png', '学习档案');
await shot(empTok, 'employee', '/portal/pk', 'emp-10-pk.png', 'PK竞赛');

await browser.close();
console.log('完成');
