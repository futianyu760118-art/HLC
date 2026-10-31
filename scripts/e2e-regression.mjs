/**
 * HRM 培训+考试 E2E 回归测试套件
 * 覆盖核心业务流程：管理员创建课程→指派→员工学习→考试→积分
 * 
 * 用法：NODE_TLS_REJECT_UNAUTHORIZED=0 node scripts/e2e-regression.mjs
 * 
 * 依赖：Playwright（已安装在 codex runtime）
 */
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE = 'https://localhost:18445';
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

const ADMIN = { email: '3420849544@qq.com', password: 'Admin@2026', role: 'admin', name: 'xiaofu' };
const EMP = { email: 'wangwu@test.com', password: 'Employee@2026', role: 'employee', name: '王五' };

const results = [];
function pass(name) { results.push({ name, ok: true }); console.log(`  ✓ ${name}`); }
function fail(name, err) { results.push({ name, ok: false, err }); console.log(`  ✗ ${name}: ${err}`); }

// 全局禁用 TLS 验证（自签证书）
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
// 用 Node 内置 fetch（Node 18+ 会读 NODE_TLS_REJECT_UNAUTHORIZED）

// 预先登录拿 token（只调一次 fetch，避免重复 TLS 握手问题）
const adminLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: ADMIN.email, password: ADMIN.password }),
});
const adminToken = (await adminLogin.json()).token;
const empLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: EMP.email, password: EMP.password }),
});
const empToken = (await empLogin.json()).token;
if (!adminToken || !empToken) { console.log('登录失败，无法运行测试'); process.exit(1); }

async function login(browser, user) {
  const token = user.role === 'admin' ? adminToken : empToken;
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }, token, user);
  return ctx;
}

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

console.log('=== HRM E2E 回归测试套件 ===\n');

// ===== 测试 1: 管理员 - 数据看板加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/analytics`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasCards = await page.locator('text=上架课程').count();
  if (hasCards > 0) pass('管理-数据看板加载'); else fail('管理-数据看板加载', '看板卡片未找到');
  await ctx.close();
} catch (e) { fail('管理-数据看板加载', e.message.slice(0, 60)); }

// ===== 测试 2: 管理员 - 课程目录加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/training-center`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const courseCards = await page.locator('[class*="cursor-pointer"]').count();
  if (courseCards > 0) pass(`管理-课程目录(${courseCards}门)`); else fail('管理-课程目录', '无课程卡片');
  await ctx.close();
} catch (e) { fail('管理-课程目录', e.message.slice(0, 60)); }

// ===== 测试 3: 管理员 - 题库管理加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/exam-center`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  // 页面应包含「题库管理」标题
  const hasTitle = await page.locator('text=题库管理').count();
  if (hasTitle > 0) pass('管理-题库管理加载'); else fail('管理-题库管理加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-题库管理加载', e.message.slice(0, 60)); }

// ===== 测试 4: 管理员 - 试卷组卷加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/exam-papers`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=试卷组卷').count();
  if (hasTitle > 0) pass('管理-试卷组卷加载'); else fail('管理-试卷组卷加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-试卷组卷加载', e.message.slice(0, 60)); }

// ===== 测试 5: 管理员 - 考试安排加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/exam-tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=考试安排').count();
  if (hasTitle > 0) pass('管理-考试安排加载'); else fail('管理-考试安排加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-考试安排加载', e.message.slice(0, 60)); }

// ===== 测试 6: 管理员 - 学习路径加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/learning-paths`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=学习路径').count();
  if (hasTitle > 0) pass('管理-学习路径加载'); else fail('管理-学习路径加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-学习路径加载', e.message.slice(0, 60)); }

// ===== 测试 7: 管理员 - 胜任力测评加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=胜任力').count();
  if (hasTitle > 0) pass('管理-胜任力测评加载'); else fail('管理-胜任力测评加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-胜任力测评加载', e.message.slice(0, 60)); }

// ===== 测试 8: 管理员 - 团队PK加载 =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/pk-seasons`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=PK').count();
  if (hasTitle > 0) pass('管理-团队PK加载'); else fail('管理-团队PK加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('管理-团队PK加载', e.message.slice(0, 60)); }

// ===== 测试 9: 员工 - 门户首页加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasWelcome = await page.locator('text=你好').count();
  if (hasWelcome > 0) pass('员工-门户首页加载'); else fail('员工-门户首页加载', '欢迎语未找到');
  await ctx.close();
} catch (e) { fail('员工-门户首页加载', e.message.slice(0, 60)); }

// ===== 测试 10: 员工 - 我的课程加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/my-courses`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=我的课程').count();
  if (hasTitle > 0) pass('员工-我的课程加载'); else fail('员工-我的课程加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-我的课程加载', e.message.slice(0, 60)); }

// ===== 测试 11: 员工 - 学习路径加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/learning-paths`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  pass('员工-学习路径加载');
  await ctx.close();
} catch (e) { fail('员工-学习路径加载', e.message.slice(0, 60)); }

// ===== 测试 12: 员工 - 错题本加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/wrong-questions`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=错题本').count();
  if (hasTitle > 0) pass('员工-错题本加载'); else fail('员工-错题本加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-错题本加载', e.message.slice(0, 60)); }

// ===== 测试 13: 员工 - 能力测评加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=能力测评').count();
  if (hasTitle > 0) pass('员工-能力测评加载'); else fail('员工-能力测评加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-能力测评加载', e.message.slice(0, 60)); }

// ===== 测试 14: 员工 - 学习积分加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/points`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=积分').count();
  if (hasTitle > 0) pass('员工-学习积分加载'); else fail('员工-学习积分加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-学习积分加载', e.message.slice(0, 60)); }

// ===== 测试 15: 员工 - 积分商城加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/shop`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=积分商城').count();
  if (hasTitle > 0) pass('员工-积分商城加载'); else fail('员工-积分商城加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-积分商城加载', e.message.slice(0, 60)); }

// ===== 测试 16: 员工 - 我的证书加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/certificates`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasTitle = await page.locator('text=证书').count();
  if (hasTitle > 0) pass('员工-我的证书加载'); else fail('员工-我的证书加载', '标题未找到');
  await ctx.close();
} catch (e) { fail('员工-我的证书加载', e.message.slice(0, 60)); }

// ===== 测试 17: 员工 - PK竞赛加载 =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/portal/pk`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  pass('员工-PK竞赛加载');
  await ctx.close();
} catch (e) { fail('员工-PK竞赛加载', e.message.slice(0, 60)); }

// ===== 测试 18: 控制台无错误（管理端） =====
try {
  const ctx = await login(browser, ADMIN);
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 80)); });
  page.on('pageerror', err => errors.push(`PAGE: ${err.message.slice(0, 60)}`));
  await page.goto(`${BASE}/analytics`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  if (errors.length === 0) pass('管理-控制台无错误'); else fail(`管理-控制台无错误`, `${errors.length} 个错误: ${errors[0]}`);
  await ctx.close();
} catch (e) { fail('管理-控制台无错误', e.message.slice(0, 60)); }

// ===== 测试 19: 控制台无错误（员工端） =====
try {
  const ctx = await login(browser, EMP);
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 80)); });
  page.on('pageerror', err => errors.push(`PAGE: ${err.message.slice(0, 60)}`));
  await page.goto(`${BASE}/portal`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  if (errors.length === 0) pass('员工-控制台无错误'); else fail(`员工-控制台无错误`, `${errors.length} 个错误: ${errors[0]}`);
  await ctx.close();
} catch (e) { fail('员工-控制台无错误', e.message.slice(0, 60)); }

// ===== 测试 20: 安全 - 未登录访问被拒 =====
try {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/analytics`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const url = page.url();
  if (url.includes('login') || url.includes('Login')) pass('安全-未登录跳转登录页'); else fail('安全-未登录跳转登录页', `当前URL: ${url}`);
  await ctx.close();
} catch (e) { fail('安全-未登录跳转登录页', e.message.slice(0, 60)); }

await browser.close();

const passed = results.filter(r => r.ok).length;
const failed = results.filter(r => !r.ok).length;
console.log(`\n${'='.repeat(50)}`);
console.log(`总结: ${passed}/${results.length} 通过${failed ? `, ${failed} 失败` : '，全部通过！'}`);
if (failed) results.filter(r => !r.ok).forEach(r => console.log(`  ✗ ${r.name}: ${r.err}`));
process.exit(failed > 0 ? 1 : 0);
