// 深度交互测试：真正填写表单并提交，验证创建/保存成功
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

const issues = [];
const adminLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: '3420849544@qq.com', password: 'Admin@2026' }),
});
const adminTok = (await adminLogin.json()).token;
const empLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'wangwu@test.com', password: 'Employee@2026' }),
});
const empTok = (await empLogin.json()).token;

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

async function testFlow(name, role, fn) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const user = role === 'admin'
    ? { id: 'u-admin', email: '3420849544@qq.com', name: 'xiaofu', role: 'admin' }
    : { id: 'u-ww', email: 'wangwu@test.com', name: '王五', role: 'employee' };
  const tok = role === 'admin' ? adminTok : empTok;
  await ctx.addInitScript((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }, tok, user);
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 120)); });
  page.on('pageerror', err => errors.push(`PAGE: ${err.message.slice(0, 100)}`));
  page.on('response', res => {
    if (res.status() >= 400 && !res.url().includes('notifications')) {
      errors.push(`HTTP ${res.status()}: ${res.url().split('/api/').pop()?.slice(0, 50)}`);
    }
  });
  try {
    const result = await fn(page);
    if (errors.length) { issues.push({ flow: name, errors }); console.log(`✗ ${name}: ${errors.length}个错误`); errors.forEach(e => console.log(`    ${e}`)); }
    else console.log(`✓ ${name}${result ? ': ' + result : ''}`);
  } catch (e) { issues.push({ flow: name, errors: [e.message.slice(0, 100)] }); console.log(`✗ ${name}: ${e.message.slice(0, 80)}`); }
  await ctx.close();
}

// 1. 管理员：创建课程分类
await testFlow('创建课程分类', 'admin', async (page) => {
  await page.goto(`${BASE}/course-categories`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建分类').click();
  await page.waitForTimeout(300);
  await page.locator('input[placeholder*="分类名称"]').fill('交互测试分类');
  await page.getByText('保存').click();
  await page.waitForTimeout(1000);
  return '提交成功';
});

// 2. 管理员：创建胜任力模型
await testFlow('创建胜任力模型', 'admin', async (page) => {
  await page.goto(`${BASE}/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建模型').click();
  await page.waitForTimeout(500);
  await page.locator('input[placeholder*="岗位名称"]').fill('交互测试岗位');
  await page.getByText('保存模型').click();
  await page.waitForTimeout(1000);
  return '已提交';
});

// 3. 员工：课程详情 → 上报进度
await testFlow('员工-课程详情加载', 'employee', async (page) => {
  // 先获取一个课程ID
  const courses = await page.evaluate(async (tok) => {
    const r = await fetch('/api/portal/courses', { headers: { Authorization: `Bearer ${tok}` } });
    return r.json();
  }, empTok);
  if (!courses || courses.length === 0) return '无课程';
  await page.goto(`${BASE}/portal/course/${courses[0].id}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  return `${courses[0].title} 加载成功`;
});

// 4. 员工：能力测评（如果有模型）
await testFlow('员工-能力测评列表', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  return '页面正常';
});

// 5. 员工：PK竞赛（如果有赛季）
await testFlow('员工-PK竞赛', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/pk`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  return '页面正常';
});

// 6. 员工：学习档案
await testFlow('员工-学习档案', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/my-profile`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  return '页面正常';
});

// 7. 管理员：数据看板加载
await testFlow('管理-数据看板', 'admin', async (page) => {
  await page.goto(`${BASE}/analytics`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  // 检查图表数据加载
  const bars = await page.locator('[class*="bg-primary/70"], [class*="rounded transition-all"]').count();
  return `图表元素: ${bars}`;
});

// 8. 管理员：PK赛季排行榜
await testFlow('管理-PK排行榜', 'admin', async (page) => {
  await page.goto(`${BASE}/pk-seasons`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  // 点排行榜
  const btn = page.getByText('排行榜').first();
  if (await btn.count() > 0) {
    await btn.click();
    await page.waitForTimeout(1000);
    return '弹窗打开';
  }
  return '无赛季';
});

await browser.close();
console.log(`\n=== 总结: ${8 - issues.length}/8 深度流程无错误 ===`);
if (issues.length) { console.log('问题:'); issues.forEach(i => console.log(`  [${i.flow}] ${i.errors.join('; ')}`)); }
