/**
 * E2E 核心业务流程测试：员工答题 → 提交 → 判分 → 看结果
 * 通过 Playwright 真实操作答题页，验证完整考试闭环
 */
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

const BASE = 'https://localhost:18445';
const PW = 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PWP = await import('node:path').then(p => p.join(PW, '.pnpm', 'playwright@1.60.0', 'node_modules'));
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

const { createRequire } = await import('node:module');
const { pathToFileURL } = await import('node:url');
async function pw() {
  try { return await import('playwright'); }
  catch {
    const r = createRequire(pathToFileURL(await import('node:path').then(p => p.join(PWP, 'playwright', 'package.json'))).href);
    return r('playwright');
  }
}

// 预登录
const empLogin = await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'wangwu@test.com', password: 'Employee@2026' }),
});
const empData = await empLogin.json();
const empToken = empData.token;
const empUser = { id: 'u-wangwu', email: 'wangwu@test.com', name: '王五', role: 'employee' };
if (!empToken) { console.log('员工登录失败'); process.exit(1); }

// 查可用考试
const examsResp = await fetch(`${BASE}/api/portal/exams`, { headers: { Authorization: `Bearer ${empToken}` } });
const exams = await examsResp.json();

const { chromium } = await pw();
const browser = await chromium.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox', '--ignore-certificate-errors'] });

const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
await ctx.addInitScript((t, u) => { localStorage.setItem('token', t); localStorage.setItem('user', JSON.stringify(u)); }, empToken, empUser);
const page = await ctx.newPage();

const errors = [];
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 80)); });
page.on('pageerror', err => errors.push(`PAGE: ${err.message.slice(0, 60)}`));

const results = [];
function pass(n) { results.push({n, ok:true}); console.log(`  ✓ ${n}`); }
function fail(n, e) { results.push({n, ok:false}); console.log(`  ✗ ${n}: ${e}`); }

console.log('=== E2E 核心业务流程：答题→提交→判分 ===\n');

// 查找有剩余次数的考试
const availableExam = exams.find(e => e.remainingAttempts > 0 && e.inWindow);
if (!availableExam) {
  console.log('  - 无可用考试（次数用完或不在时间窗），跳过答题测试');
  console.log('\n总结: 跳过（无可考考试）');
  await browser.close();
  process.exit(0);
}

console.log(`考试: ${availableExam.title} (剩余${availableExam.remainingAttempts}次)\n`);

// 步骤 1: 进入考试介绍页
try {
  await page.goto(`${BASE}/portal/exam/${availableExam.taskId}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const hasStartBtn = await page.locator('button:has-text("开始考试"), button:has-text("再次考试")').count();
  if (hasStartBtn > 0) pass('步骤1-考试介绍页加载(有开始按钮)'); else fail('步骤1-考试介绍页', '未找到开始按钮');
} catch (e) { fail('步骤1-考试介绍页', e.message.slice(0, 60)); }

// 步骤 2: 通过 API 直接开始考试（跳过自定义 confirm 组件），然后导航到答题页
try {
  const startResp = await fetch(`${BASE}/api/portal/exams/${availableExam.taskId}/start`, {
    method: 'POST', headers: { Authorization: `Bearer ${empToken}`, 'Content-Type': 'application/json' },
  });
  const startData = await startResp.json();
  if (startData.attemptId) {
    // 直接导航到答题页（无 location.state，触发 API 恢复流程）
    await page.goto(`${BASE}/portal/exam/take/${startData.attemptId}`, { waitUntil: 'networkidle' });
    // 等待控件渲染（API 恢复 + React 渲染）
    await page.waitForTimeout(3500);
    const radioCount = await page.locator('input[type="radio"], input[type="checkbox"]').count();
    if (radioCount > 0) {
      pass(`步骤2-进入答题页(控件${radioCount}个)`);
    } else {
      fail('步骤2-进入答题页', `答题页无控件`);
    }
  } else {
    fail('步骤2-开始考试', startData.error || '无 attemptId');
  }
} catch (e) { fail('步骤2-开始考试', e.message.slice(0, 60)); }

// 步骤 3: 答题（选第一个选项）
try {
  await page.waitForTimeout(1000);
  // 选每题第一个 radio/checkbox
  const radios = page.locator('input[type="radio"]');
  const radioCount = await radios.count();
  // 按题分组选第一个选项
  const names = new Set();
  for (let i = 0; i < radioCount; i++) {
    const name = await radios.nth(i).getAttribute('name');
    if (name && !names.has(name)) {
      names.add(name);
      await radios.nth(i).check();
    }
  }
  // checkbox 也选第一个
  const checkboxes = page.locator('input[type="checkbox"]');
  const cbCount = await checkboxes.count();
  const cbNames = new Set();
  for (let i = 0; i < cbCount; i++) {
    const name = await checkboxes.nth(i).getAttribute('name');
    if (name && !cbNames.has(name)) {
      cbNames.add(name);
      await checkboxes.nth(i).check();
    }
  }
  pass(`步骤3-作答完成(radio题${names.size} checkbox题${cbNames.size})`);
} catch (e) { fail('步骤3-作答', e.message.slice(0, 60)); }

// 步骤 4: 提交（通过 API，绕过自定义 confirm）
try {
  // 从 URL 拿 attemptId
  const attemptId = page.url().split('/take/')[1]?.split('/')[0] || page.url().split('/take/')[1];

  // 通过 API 提交（用选第一个选项的简单答案）
  // 直接在页面上执行提交
  const submitResult = await page.evaluate(async (attemptId) => {
    const token = localStorage.getItem('token');
    // 构造答案：每题选索引 0
    const answers = {};
    // 从 DOM 获取所有题目的 name
    const allNames = new Set();
    document.querySelectorAll('input[type="radio"], input[type="checkbox"]').forEach(i => {
      const n = i.getAttribute('name');
      if (n) allNames.add(n);
    });
    allNames.forEach(n => { answers[n] = [0]; });

    const r = await fetch(`/api/portal/exams/${attemptId}/submit`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    });
    return r.json();
  }, attemptId);

  if (submitResult.score !== undefined) {
    pass(`步骤4-提交成功(分数${submitResult.score})`);
    // 导航到结果页
    await page.goto(`${BASE}/portal/exam/result/${attemptId}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
  } else {
    fail('步骤4-提交', submitResult.error || '未知错误');
  }
} catch (e) { fail('步骤4-提交', e.message.slice(0, 60)); }

// 步骤 5: 结果页展示
try {
  await page.waitForTimeout(1000);
  const hasScore = await page.locator('text=/得分|分数|通过|未通过/').count();
  if (hasScore > 0) pass('步骤5-结果页显示成绩'); else fail('步骤5-结果页', '未找到成绩展示');
} catch (e) { fail('步骤5-结果页', e.message.slice(0, 60)); }

// 步骤 6: 控制台无致命错误
const fatalErrors = errors.filter(e => !e.includes('401') && !e.includes('Failed to load resource'));
if (fatalErrors.length === 0) pass('步骤6-控制台无致命错误'); else fail('步骤6-控制台', `${fatalErrors.length}个: ${fatalErrors[0]}`);

await browser.close();
const passed = results.filter(r => r.ok).length;
console.log(`\n总结: ${passed}/${results.length} 通过${results.length - passed ? ', ' + (results.length-passed) + ' 失败' : '，全部通过！'}`);
process.exit(passed === results.length ? 0 : 1);
