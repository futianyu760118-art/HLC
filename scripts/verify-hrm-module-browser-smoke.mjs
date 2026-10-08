import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
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
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_MODULE_SMOKE_ROUTE_TIMEOUT_MS || 30000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_MODULE_SMOKE_RUN_ID || `module-smoke-${stamp}`;

const MODULE_ROUTES = [
  { path: '/home', label: '数据驾驶舱', expect: ['运营驾驶舱', '招聘运营链路', '快捷操作'] },
  { path: '/talent-intelligence', label: '人才智能', expect: ['人才战略图谱', '技能供给', '关键岗位继任'] },
  { path: '/job-manage', label: '岗位管理', expect: ['岗位总数', '在招岗位', '新建岗位'] },
  { path: '/resume-manage', label: '简历管理', expect: ['简历管理', '上传简历', 'AI评分'] },
  { path: '/hrm/candidates', label: '候选人管理', expect: ['候选人管理', '候选人姓名', 'AI候选人摘要'] },
  { path: '/interview-manage', label: '面试管理', expect: ['面试总数', '已安排', '新建面试'] },
  { path: '/hrm/offers', label: 'Offer管理', expect: ['Offer管理', 'Offer标题', '审批状态'] },
  { path: '/hrm/departments', label: '部门管理', expect: ['部门管理', '部门名称', '上级部门'] },
  { path: '/hrm/positions', label: '岗位体系', expect: ['岗位体系', '岗位名称', '所属部门'] },
  { path: '/hrm/employees', label: '员工档案', expect: ['员工档案', '员工编号', '所属部门'] },
  { path: '/hrm/onboarding-tasks', label: '入职管理', expect: ['入职管理', '任务名称', '负责人'] },
  { path: '/hrm/probations', label: '转正管理', expect: ['转正管理', '预计转正', '转正结果'] },
  { path: '/hrm/employee-changes', label: '人事异动', expect: ['人事异动', '异动类型', '新部门'] },
  { path: '/hrm/resignations', label: '离职管理', expect: ['离职管理', '预计离职', '离职原因'] },
  { path: '/hrm/contracts', label: '合同管理', expect: ['合同管理', '合同编号', '合同类型'] },
  { path: '/hrm/attendance-records', label: '考勤记录', expect: ['考勤记录', '考勤日期', '考勤状态'] },
  { path: '/attendance-stats', label: '考勤统计', expect: ['考勤统计', '出勤人次', '异常'] },
  { path: '/employee-requests', label: '请假/加班/出差/补卡', expect: ['请假/加班/出差/补卡', '新建申请', '申请类型'] },
  { path: '/approval-center/my-applications', label: '我的申请', expect: ['我的申请', '审批申请', '提交时间'] },
  { path: '/approval-center/pending', label: '待我审批', expect: ['待我审批', '待办审批', '审批'] },
  { path: '/approval-center/records', label: '审批记录', expect: ['审批记录', '历史审批', '审批状态'] },
  { path: '/hrm/performance-cycles', label: '绩效周期', expect: ['绩效周期', '周期类型', '状态'] },
  { path: '/hrm/performance-templates', label: '绩效模板', expect: ['绩效模板', '模板类型', '状态'] },
  { path: '/performance-review', label: '绩效评估', expect: ['绩效评估', '评估得分', '绩效周期'] },
  { path: '/salary-profiles', label: '薪资档案', expect: ['薪资档案', '档案总数', '新建薪资档案'] },
  { path: '/hrm/payroll-records', label: '工资条', expect: ['工资条', '薪资月份', '生成月度工资'] },
  { path: '/hrm/training-courses', label: '培训课程', expect: ['培训课程', '课程分类', '讲师'] },
  { path: '/hrm/training-plans', label: '培训计划', expect: ['培训计划', '培训课程', '目标部门'] },
  { path: '/hrm/training-records', label: '培训记录', expect: ['培训记录', '培训计划', '培训课程'] },
  { path: '/hrm/users', label: '用户管理', expect: ['用户管理', '角色', '关联员工'] },
  { path: '/hrm/roles', label: '角色权限', expect: ['角色权限', '角色编码', '权限标识'] },
  { path: '/notifications', label: '通知提醒', expect: ['通知提醒', '消息中心', '新建通知'] },
  { path: '/feedback', label: '问题反馈', expect: ['问题反馈', '全部反馈', '待处理'] },
  { path: '/operation-logs', label: '操作日志', expect: ['操作日志', '所属模块', '操作类型'] },
  { path: '/ai-model-settings', label: 'AI 模型管理', expect: ['AI 权益与用量', '已开通资源', '近期 AI 用量'] },
  { path: '/system-settings', label: '系统设置', expect: ['系统设置', '账户信息', '保存设置'] },
];

const requestedRoutes = (process.env.HRM_SMOKE_ROUTES || '')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);
const ROUTES = requestedRoutes.length
  ? MODULE_ROUTES.filter((route) => requestedRoutes.includes(route.path) || requestedRoutes.includes(route.label))
  : MODULE_ROUTES;

const obviousErrorTexts = [
  '模块不存在',
  '页面不存在',
  'Something went wrong',
  'Application error',
  'Minified React error',
  'Cannot read properties',
  'ReferenceError',
  'TypeError',
  'Unhandled',
  '请求失败 (500)',
  '网络异常，请检查连接后重试',
];

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const login = async () => {
  const result = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  const payload = result.auth;
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  console.log(`HRM module smoke credentials: ${result.source} tenant=${result.credentials.tenantSlug} email=${result.credentials.email}`);
  return payload;
};

const sanitize = (value) => String(value).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const hasIgnorableConsoleError = (message) => (
  /favicon\.ico/i.test(message)
  || /ResizeObserver loop/i.test(message)
  || /net::ERR_ABORTED/i.test(message)
);

const waitForRouteContent = async (page, route) => {
  let lastMainText = '';
  let lastBodyText = '';
  let matched = '';

  for (let attempt = 0; attempt < 8; attempt += 1) {
    const main = page.locator('main.hpt-main');
    const mainText = await main.innerText({ timeout: 5000 }).catch(() => '');
    const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
    lastMainText = compact(mainText);
    lastBodyText = compact(bodyText);
    matched = route.expect.find((item) => lastMainText.includes(item)) || '';

    const stillLoading = /加载中|正在加载|正在生成/.test(lastMainText);
    if (matched && !stillLoading) break;
    await page.waitForTimeout(700);
  }

  return {
    mainText: lastMainText,
    bodyText: lastBodyText,
    matched,
  };
};

const runRoute = async (context, route) => {
  const startedAt = Date.now();
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  let screenshotPath = null;

  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (hasIgnorableConsoleError(text)) return;
    consoleErrors.push(text);
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error?.stack || error?.message || String(error));
  });

  try {
    const targetUrl = `${BASE_URL}${route.path}`;
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await page.waitForSelector('main.hpt-main', { timeout: ROUTE_TIMEOUT_MS }).catch(() => null);
    await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);
    await page.waitForTimeout(400);

    const finalUrl = page.url();
    const currentPath = new URL(finalUrl).pathname;
    const title = await page.title().catch(() => '');
    const content = await waitForRouteContent(page, route);
    const errorHits = obviousErrorTexts.filter((item) => content.mainText.includes(item) || content.bodyText.includes(item));
    const failures = [];

    if (currentPath.includes('/login')) failures.push('redirected_to_login');
    if (currentPath !== route.path) failures.push(`unexpected_path:${currentPath}`);
    if (!content.matched) failures.push('missing_expected_main_content');
    if (errorHits.length) failures.push(`visible_error_text:${errorHits.join('|')}`);
    if (consoleErrors.length) failures.push('console_error');
    if (pageErrors.length) failures.push('page_error');

    if (failures.length) {
      screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(route.label)}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    }

    return {
      ok: failures.length === 0,
      route: route.path,
      label: route.label,
      expected: route.expect,
      matched: content.matched || null,
      finalUrl,
      title,
      failures,
      consoleErrors,
      pageErrors,
      screenshotPath,
      durationMs: Date.now() - startedAt,
      mainTextSample: content.mainText.slice(0, 600),
    };
  } catch (error) {
    screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(route.label)}-exception.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    return {
      ok: false,
      route: route.path,
      label: route.label,
      expected: route.expect,
      matched: null,
      finalUrl: page.url(),
      failures: ['exception'],
      error: error?.stack || error?.message || String(error),
      consoleErrors,
      pageErrors,
      screenshotPath,
      durationMs: Date.now() - startedAt,
      mainTextSample: '',
    };
  } finally {
    await page.close().catch(() => null);
  }
};

const main = async () => {
  if (!ROUTES.length) fail('No routes selected for module smoke verification');
  const { chromium } = await importPlaywright();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const auth = await login();

  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });

  const results = [];
  try {
    for (const route of ROUTES) {
      const result = await runRoute(context, route);
      results.push(result);
      const marker = result.ok ? 'PASS' : 'FAIL';
      console.log(`${marker} ${route.path} ${route.label} ${result.durationMs}ms`);
    }
  } finally {
    await browser.close();
  }

  const failed = results.filter((item) => !item.ok);
  const report = {
    ok: failed.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    routeCount: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    reportPath,
    results,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

  const summary = {
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    routeCount: report.routeCount,
    passed: report.passed,
    failed: report.failed,
    reportPath,
    failures: failed.map((item) => ({
      route: item.route,
      label: item.label,
      failures: item.failures,
      screenshotPath: item.screenshotPath,
      consoleErrors: item.consoleErrors.slice(0, 3),
      pageErrors: item.pageErrors.slice(0, 2),
    })),
  };
  console.log(JSON.stringify(summary, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
