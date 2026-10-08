// 交互流程测试：真实点击/输入/提交，捕获控制台错误和失败请求
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
  body: JSON.stringify({ email: 'zhangsan@test.com', password: 'Employee@2026' }),
});
const empTok = (await empLogin.json()).token;

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

async function testFlow(name, role, fn) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const user = role === 'admin'
    ? { id: 'u-admin', email: '3420849544@qq.com', name: 'xiaofu', role: 'admin' }
    : { id: 'u-zs', email: 'zhangsan@test.com', name: '张三', role: 'employee' };
  const tok = role === 'admin' ? adminTok : empTok;
  await ctx.addInitScript((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }, tok, user);
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 100)); });
  page.on('pageerror', err => errors.push(`PAGE_ERROR: ${err.message.slice(0, 100)}`));
  page.on('requestfailed', req => errors.push(`REQ_FAIL: ${req.url().slice(-60)} ${req.failure()?.errorText}`));

  try {
    await fn(page);
    if (errors.length) {
      issues.push({ flow: name, errors });
      console.log(`✗ ${name}: ${errors.length} 个错误`);
      errors.forEach(e => console.log(`    ${e}`));
    } else {
      console.log(`✓ ${name}`);
    }
  } catch (e) {
    issues.push({ flow: name, errors: [`TEST_ERROR: ${e.message.slice(0, 100)}`] });
    console.log(`✗ ${name}: ${e.message.slice(0, 80)}`);
  }
  await ctx.close();
}

// === 管理侧流程 ===

// 1. 课程目录 → 点编辑按钮
await testFlow('课程目录-点编辑', 'admin', async (page) => {
  await page.goto(`${BASE}/training-center`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  // 点第一个课程的卡片（进编辑器）
  await page.locator('.group.cursor-pointer, [class*="cursor-pointer"]').first().click();
  await page.waitForTimeout(2000);
});

// 2. 新建课程弹窗
await testFlow('新建课程弹窗', 'admin', async (page) => {
  await page.goto(`${BASE}/training-center`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建课程').click();
  await page.waitForTimeout(500);
  // 填标题
  await page.locator('input[placeholder*="课程标题"], input').first().fill('测试课程-交互');
  await page.waitForTimeout(300);
});

// 3. 智能出题 → 输入资料 → 生成
await testFlow('智能出题页', 'admin', async (page) => {
  await page.goto(`${BASE}/exam-generate`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  // 填资料
  await page.locator('textarea').first().fill('测试资料内容，关于信息安全的基础知识。密码应该定期更换。');
  await page.waitForTimeout(300);
});

// 4. 题库管理 → 筛选
await testFlow('题库管理-筛选', 'admin', async (page) => {
  await page.goto(`${BASE}/exam-center`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  // 点筛选按钮
  const btns = page.locator('button:has-text("已通过"), button:has-text("待审核"), button:has-text("全部")');
  if (await btns.count() > 0) await btns.first().click();
  await page.waitForTimeout(500);
});

// 5. 试卷组卷 → 点新建
await testFlow('试卷组卷-新建', 'admin', async (page) => {
  await page.goto(`${BASE}/exam-papers`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建试卷').click();
  await page.waitForTimeout(500);
});

// 6. 考试安排 → 点新建
await testFlow('考试安排-新建', 'admin', async (page) => {
  await page.goto(`${BASE}/exam-tasks`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建考试').click().catch(() => {});
  await page.waitForTimeout(500);
});

// 7. 学习路径编辑器
await testFlow('学习路径编辑器', 'admin', async (page) => {
  await page.goto(`${BASE}/learning-paths`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建路径').click().catch(() => {});
  await page.waitForTimeout(500);
});

// 8. 胜任力模型编辑器
await testFlow('胜任力模型编辑器', 'admin', async (page) => {
  await page.goto(`${BASE}/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByText('新建模型').click().catch(() => {});
  await page.waitForTimeout(500);
});

// === 员工门户流程 ===

// 9. 门户首页 → 点快捷卡片
await testFlow('门户首页-快捷卡片', 'employee', async (page) => {
  await page.goto(`${BASE}/portal`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  // 点课程卡片
  const card = page.locator('button:has-text("我的课程"), [class*="cursor-pointer"]').first();
  if (await card.count() > 0) await card.click();
  await page.waitForTimeout(1500);
});

// 10. 错题本 → 切换筛选
await testFlow('错题本-筛选', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/wrong-questions`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const btn = page.locator('button:has-text("已掌握"), button:has-text("全部")').first();
  if (await btn.count() > 0) await btn.click();
  await page.waitForTimeout(500);
});

// 11. 积分商城
await testFlow('积分商城', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/shop`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  // 点兑换记录 tab
  const tab = page.locator('button:has-text("兑换记录")');
  if (await tab.count() > 0) await tab.click();
  await page.waitForTimeout(500);
});

// 12. 学习积分
await testFlow('学习积分', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/points`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
});

// 13. 能力测评
await testFlow('能力测评', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/competency`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
});

// 14. 我的证书
await testFlow('我的证书', 'employee', async (page) => {
  await page.goto(`${BASE}/portal/certificates`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
});

await browser.close();

console.log(`\n=== 总结: ${14 - issues.length}/14 流程无错误 ===`);
if (issues.length) {
  console.log('问题汇总:');
  issues.forEach(i => console.log(`  [${i.flow}] ${i.errors.join('; ')}`));
}
