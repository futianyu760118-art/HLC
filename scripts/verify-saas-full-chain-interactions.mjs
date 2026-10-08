import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { EDGE_EXECUTABLE, importPlaywright } from './resolve-playwright-runtime.mjs';
import { resolveHrmSmokeCredentials } from './hrm-smoke-credentials.mjs';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_PREVIEW_PORT = '18080';
const parsedBaseUrl = new URL(BASE_URL);
if (parsedBaseUrl.port === FORBIDDEN_PREVIEW_PORT) {
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
const ROUTE_TIMEOUT_MS = Number(process.env.HRM_FULL_CHAIN_ROUTE_TIMEOUT_MS || 30000);
const SAFE_CLICK_LIMIT = Number(process.env.HRM_FULL_CHAIN_CLICK_LIMIT_PER_ROUTE || 6);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_FULL_CHAIN_RUN_ID || `full-chain-interactions-${stamp}`;
// Reports: full-chain-interactions-<timestamp>.json and full-chain-interactions-<timestamp>.md

const MANAGEMENT_ROUTES = [
  { path: '/home', label: '数据驾驶舱' },
  { path: '/todos', label: '待办事项' },
  { path: '/talent-intelligence', label: '人才智能' },
  { path: '/headcount-management', label: '编制管理' },
  { path: '/people-analytics', label: 'People Analytics' },
  { path: '/continuous-feedback', label: '持续反馈' },
  { path: '/job-manage', label: '岗位管理' },
  { path: '/job-create', label: '新建岗位' },
  { path: '/resume-manage', label: '简历管理' },
  { path: '/resume-upload', label: '上传简历' },
  { path: '/hrm/candidates', label: '候选人管理' },
  { path: '/interview-manage', label: '面试管理' },
  { path: '/interview-create', label: '新建面试' },
  { path: '/hrm/offers', label: 'Offer管理' },
  { path: '/hrm/departments', label: '部门管理' },
  { path: '/hrm/positions', label: '岗位体系' },
  { path: '/hrm/employees', label: '员工档案' },
  { path: '/hrm/onboarding-tasks', label: '入职管理' },
  { path: '/hrm/probations', label: '转正管理' },
  { path: '/hrm/employee-changes', label: '人事异动' },
  { path: '/hrm/resignations', label: '离职管理' },
  { path: '/hrm/contracts', label: '合同管理' },
  { path: '/hrm/attendance-records', label: '考勤记录' },
  { path: '/attendance-stats', label: '考勤统计' },
  { path: '/employee-requests', label: '请假/加班/出差/补卡' },
  { path: '/approval-center/my-applications', label: '我的申请' },
  { path: '/approval-center/pending', label: '待我审批' },
  { path: '/approval-center/records', label: '审批记录' },
  { path: '/hrm/performance-cycles', label: '绩效周期' },
  { path: '/hrm/performance-templates', label: '绩效模板' },
  { path: '/performance-review', label: '绩效评估' },
  { path: '/salary-profiles', label: '薪资档案' },
  { path: '/hrm/payroll-records', label: '工资条' },
  { path: '/analytics', label: '数据看板' },
  { path: '/training-center', label: '课程目录' },
  { path: '/hrm/training-courses', label: '培训课程' },
  { path: '/hrm/training-plans', label: '培训计划' },
  { path: '/hrm/training-records', label: '培训记录' },
  { path: '/course-categories', label: '课程分类' },
  { path: '/learning-paths', label: '学习路径' },
  { path: '/competency', label: '胜任力测评' },
  { path: '/pk-seasons', label: '团队PK竞赛' },
  { path: '/exam-center', label: '题库管理' },
  { path: '/exam-papers', label: '试卷组卷' },
  { path: '/exam-tasks', label: '考试安排' },
  { path: '/exam-attempts', label: '成绩管理' },
  { path: '/exam-generate', label: '智能出题' },
  { path: '/bigscreen', label: '数据大屏', displayOnly: true },
  { path: '/hrm/users', label: '用户管理' },
  { path: '/hrm/roles', label: '角色权限' },
  { path: '/notifications', label: '通知提醒' },
  { path: '/feedback', label: '问题反馈' },
  { path: '/operation-logs', label: '操作日志' },
  { path: '/ai-model-settings', label: 'AI 模型管理' },
  { path: '/system-settings', label: '系统设置' },
];

const PLATFORM_ROUTES = [
  { path: '/platform/tenants', label: '平台企业后台' },
];

const PORTAL_ROUTES = [
  { path: '/portal', label: '员工门户首页' },
  { path: '/portal/my-courses', label: '我的课程' },
  { path: '/portal/my-exams', label: '我的考试' },
  { path: '/portal/my-profile', label: '学习档案' },
  { path: '/portal/learning-paths', label: '学习路径' },
  { path: '/portal/wrong-questions', label: '错题本' },
  { path: '/portal/competency', label: '能力测评' },
  { path: '/portal/points', label: '学习积分' },
  { path: '/portal/certificates', label: '我的证书' },
  { path: '/portal/pk', label: 'PK竞赛' },
  { path: '/portal/shop', label: '积分商城' },
];

const PORTAL_SMOKE_EMPLOYEE_NO = `PFC-${runId.replace(/[^a-z0-9]+/gi, '').slice(-16)}`.slice(0, 48);
const PORTAL_INITIAL_PASSWORD = 'hj@123';
const PORTAL_PASSWORD = 'PortalSmoke123!';

const DYNAMIC_SCENARIOS = [
  { path: '/course-edit/:id', label: '课程编辑详情', reason: 'requires a real course id and save/cancel scenario' },
  { path: '/exam-task-progress/:id', label: '考试进度详情', reason: 'requires a real exam task id' },
  { path: '/portal/course/:id', label: '门户课程详情', reason: 'requires a portal course id and progress scenario' },
  { path: '/portal/course/:hourId/learn', label: '门户课时学习', reason: 'reports learning progress and needs fixture-backed scenario' },
  { path: '/portal/exam/:taskId', label: '门户考试介绍', reason: 'starting an exam is a commit action' },
  { path: '/portal/exam/take/:attemptId', label: '门户考试作答', reason: 'submitting answers is a commit action' },
  { path: '/portal/exam/result/:attemptId', label: '门户考试结果', reason: 'requires a real attempt id' },
];

const COMMIT_ACTION_RE = /删除|移除|提交|审批|通过|驳回|发布|生成|保存|确认|支付|导入|上传|重置|启用|禁用|兑换|开始考试|交卷|完成|终止|续签|延期|转正|离职|发送|发起|安排|全部已读|标记已读|下载|导出|AI|智能|清空|归档|恢复|锁定|发放|收款|开通|创建企业|重置密码/i;
const SAFE_ACTION_RE = /全部|筛选|搜索|查询|刷新|重试|更多|展开|收起|返回|关闭|取消|上一页|下一页|首页|末页|开通清单|数据请求|套餐管理|订阅管理|运行诊断|平台操作日志|企业客户|我的申请|待我审批|审批记录|兑换记录|基础信息|学习记录|考试记录|待处理|处理中|已解决|未读|已读|排行榜|预览|目录|选择|切换|返回课程|返回学习中心/i;
const NAVIGATION_ONLY_RE = /查看|详情|编辑|新建|新增|添加|前往|去学习|全部课程|员工档案|岗位管理|审批中心|培训计划|薪资档案|工资条|考勤统计|上传简历|面试安排|发布岗位|发起审批/i;
const ERROR_TEXT_RE = /模块不存在|页面不存在|Something went wrong|Application error|Minified React error|Cannot read properties|ReferenceError|TypeError|Unhandled|请求失败 \(500\)|网络异常，请检查连接后重试|加载失败|登录已过期/i;

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const sanitize = (value) => String(value).replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').slice(0, 80);

const readJson = async (response, label) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} did not return JSON: ${text.slice(0, 500)}`);
  }
};

const requestJson = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    signal: options.signal || AbortSignal.timeout(Number(process.env.HRM_FULL_CHAIN_API_TIMEOUT_MS || 12000)),
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const payload = await readJson(response, url);
  if (!response.ok) {
    const error = new Error(payload?.error || payload?.message || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
};

const platformLogin = async () => {
  const identifier = process.env.HRM_PLATFORM_EMAIL || process.env.HRM_TEST_PLATFORM_EMAIL || dotEnv.PLATFORM_ADMIN_EMAIL || 'platform@example.com';
  const password = process.env.HRM_PLATFORM_PASSWORD || process.env.HRM_TEST_PLATFORM_PASSWORD || dotEnv.PLATFORM_ADMIN_PASSWORD || 'Passw0rd!';
  return requestJson(`${BASE_URL}/api/platform/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': `${runId}-platform-login` },
    body: JSON.stringify({ identifier, password }),
  });
};

const extractRows = (payload) => {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.rows)) return payload.rows;
  return [];
};

const loginPortal = async ({ employeeNo, password, tenantSlug, requestId }) => (
  requestJson(`${BASE_URL}/api/portal/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': requestId },
    body: JSON.stringify({ employeeNo, identifier: employeeNo, password, tenantSlug }),
  })
);

const changePortalPassword = async ({ auth, currentPassword, newPassword }) => (
  requestJson(`${BASE_URL}/api/portal/auth/change-password`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${auth.token}`,
      'X-Request-ID': `${runId}-portal-change-password`,
    },
    body: JSON.stringify({ currentPassword, newPassword }),
  })
);

const createPortalSmokeEmployee = async ({ hrmAuth }) => (
  requestJson(`${BASE_URL}/api/hrm/employees`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${hrmAuth.token}`,
      'X-Request-ID': `${runId}-portal-smoke-employee`,
    },
    body: JSON.stringify({
      employeeNo: PORTAL_SMOKE_EMPLOYEE_NO,
      name: '全链路审计门户员工',
      email: `portal-${runId.toLowerCase()}@example.test`,
      hireDate: '2026-01-01',
      status: 'active',
    }),
  })
);

const cleanupPortalSmokeEmployee = async ({ hrmAuth, employeeId }) => {
  if (!employeeId) return;
  try {
    await requestJson(`${BASE_URL}/api/hrm/employees/${employeeId}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${hrmAuth.token}`,
        'X-Request-ID': `${runId}-portal-smoke-employee-cleanup`,
      },
    });
  } catch (error) {
    if (error?.status !== 404) throw error;
  }
};

const resolvePortalAuth = async ({ hrmAuth, preferredTenantSlug }) => {
  const tenantSlug = process.env.HRM_TEST_TENANT_SLUG || dotEnv.HRM_TEST_TENANT_SLUG || preferredTenantSlug || dotEnv.DEFAULT_TENANT_SLUG || 'HPT-00000001';
  if (process.env.HRM_FULL_CHAIN_CREATE_PORTAL_FIXTURE !== '0') {
    let fixtureEmployee = null;
    try {
      fixtureEmployee = await createPortalSmokeEmployee({ hrmAuth });
      const initialAuth = await loginPortal({
        employeeNo: PORTAL_SMOKE_EMPLOYEE_NO,
        password: PORTAL_INITIAL_PASSWORD,
        tenantSlug,
        requestId: `${runId}-portal-login-initial`,
      });
      const auth = initialAuth?.user?.mustChangePassword
        ? await changePortalPassword({
          auth: initialAuth,
          currentPassword: PORTAL_INITIAL_PASSWORD,
          newPassword: PORTAL_PASSWORD,
        })
        : initialAuth;
      if (auth?.token && auth?.user) {
        return {
          auth,
          employeeNo: PORTAL_SMOKE_EMPLOYEE_NO,
          fixtureEmployeeId: fixtureEmployee?.id || null,
          blocker: null,
        };
      }
    } catch (error) {
      return {
        auth: null,
        fixtureEmployeeId: fixtureEmployee?.id || null,
        blocker: `Could not prepare portal smoke employee ${PORTAL_SMOKE_EMPLOYEE_NO}: ${error.message}`,
      };
    }
  }

  const employeeNos = [];
  const configuredEmployeeNo = process.env.HRM_PORTAL_EMPLOYEE_NO || process.env.HRM_TEST_PORTAL_EMPLOYEE_NO || dotEnv.HRM_PORTAL_EMPLOYEE_NO;
  if (configuredEmployeeNo) employeeNos.push(configuredEmployeeNo);

  try {
    const employees = await requestJson(`${BASE_URL}/api/hrm/employees?page=1&pageSize=30`, {
      headers: {
        Authorization: `Bearer ${hrmAuth.token}`,
        'X-Request-ID': `${runId}-portal-employee-candidates`,
      },
    });
    for (const row of extractRows(employees)) {
      if (row?.employeeNo) employeeNos.push(row.employeeNo);
      if (row?.employee_no) employeeNos.push(row.employee_no);
    }
  } catch (error) {
    return { auth: null, blocker: `Could not list employees for portal login candidates: ${error.message}` };
  }

  employeeNos.push('HJ-0001', 'HJ-0002', 'zhangsan', 'wangwu');
  const uniqueEmployeeNos = [...new Set(employeeNos.map(compact).filter(Boolean))];
  const passwords = [
    process.env.HRM_PORTAL_PASSWORD,
    process.env.HRM_TEST_PORTAL_PASSWORD,
    dotEnv.HRM_PORTAL_PASSWORD,
    'Employee@2026',
    'Demo@123456',
    'hj@123',
  ].map(compact).filter(Boolean);

  const attempts = [];
  for (const employeeNo of uniqueEmployeeNos.slice(0, Number(process.env.HRM_FULL_CHAIN_PORTAL_FALLBACK_EMPLOYEE_LIMIT || 3))) {
    for (const password of [...new Set(passwords)]) {
      try {
        const auth = await loginPortal({
          employeeNo,
          password,
          tenantSlug,
          requestId: `${runId}-portal-login-${sanitize(employeeNo)}`,
        });
        if (auth?.user?.mustChangePassword) {
          attempts.push(`${employeeNo}: login requires first-password change`);
          continue;
        }
        if (auth?.token && auth?.user) return { auth, employeeNo, fixtureEmployeeId: null, blocker: null };
        attempts.push(`${employeeNo}: login returned no token`);
      } catch (error) {
        attempts.push(`${employeeNo}: ${error.status || ''} ${error.message}`.trim());
      }
    }
  }

  return {
    auth: null,
    fixtureEmployeeId: null,
    blocker: `No usable employee portal login found. Attempts: ${attempts.slice(0, 8).join('; ')}`,
  };
};

const hasIgnorableConsoleError = (message) => (
  /favicon\.ico/i.test(message)
  || /ResizeObserver loop/i.test(message)
  || /net::ERR_ABORTED/i.test(message)
);

const routeGroupForPath = (targetPath) => {
  if (!targetPath) return 'external';
  if (targetPath.startsWith('/platform')) return 'platform';
  if (targetPath.startsWith('/portal')) return 'portal';
  if (targetPath.startsWith('/hrm') || targetPath.startsWith('/approval-center') || targetPath.startsWith('/employee-requests') || targetPath.startsWith('/attendance-stats') || targetPath.startsWith('/salary-profiles') || targetPath.startsWith('/performance-review')) return 'hr-core';
  if (/^\/(training-center|course-categories|learning-paths|competency|pk-seasons|analytics|exam-|bigscreen)/.test(targetPath)) return 'learning-exam';
  return 'management';
};

const sameAppTarget = (href) => {
  if (!href) return null;
  try {
    const url = href.startsWith('/') ? new URL(href, BASE_URL) : new URL(href);
    if (url.origin !== new URL(BASE_URL).origin) return null;
    return `${url.pathname}${url.search || ''}${url.hash || ''}`;
  } catch {
    return null;
  }
};

const classifyControl = (control) => {
  const label = compact([control.label, control.text, control.placeholder, control.href].filter(Boolean).join(' '));
  if (!label) return { safe: false, reason: 'unlabeled control needs accessibility review' };
  if (control.disabled) return { safe: false, reason: 'disabled' };
  if (!['main', 'dialog'].includes(control.region || '')) return { safe: false, reason: 'main-or-dialog control policy excludes global navigation chrome' };
  if (COMMIT_ACTION_RE.test(label)) return { safe: false, reason: 'commit-or-destructive action requires scenario' };
  if (NAVIGATION_ONLY_RE.test(label)) return { safe: false, reason: 'navigation or create/edit flow recorded as cross-link/scenario' };
  if (control.tag === 'a' && control.href) return { safe: false, reason: 'navigation link inventoried only' };
  if (control.role === 'tab') return { safe: true, reason: 'tab switch' };
  if (SAFE_ACTION_RE.test(label)) return { safe: true, reason: 'read-only or reversible UI action' };
  if (control.type && ['search', 'text', 'email', 'number', 'date', 'month'].includes(control.type)) return { safe: false, reason: 'input field inventory only' };
  return { safe: false, reason: 'requires scenario classification' };
};

const collectControls = async (page) => (
  page.locator('body').evaluate(() => {
    const nodes = Array.from(document.querySelectorAll('button,a[href],input,select,textarea,[role="button"],[role="tab"],summary'));
    const visible = (node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const regionFor = (node) => {
      if (node.closest('[role="dialog"], .fixed.inset-0')) return 'dialog';
      if (node.closest('main.hpt-main')) return 'main';
      if (node.closest('aside')) return 'sidebar';
      if (node.closest('header')) return 'header';
      return 'other';
    };
    const textFor = (node) => (node.getAttribute('aria-label')
      || node.getAttribute('title')
      || node.textContent
      || node.getAttribute('placeholder')
      || node.getAttribute('name')
      || node.id
      || '').replace(/\s+/g, ' ').trim();

    return nodes.filter(visible).map((node, index) => {
      const tag = node.tagName.toLowerCase();
      const id = `fc-${index}`;
      node.setAttribute('data-full-chain-audit-id', id);
      const disabled = Boolean(node.disabled)
        || node.getAttribute('aria-disabled') === 'true'
        || node.classList.contains('disabled');
      return {
        auditId: id,
        tag,
        role: node.getAttribute('role') || '',
        type: node.getAttribute('type') || '',
        label: textFor(node),
        region: regionFor(node),
        text: (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160),
        placeholder: node.getAttribute('placeholder') || '',
        name: node.getAttribute('name') || '',
        idAttr: node.id || '',
        disabled,
        href: tag === 'a' ? node.href : '',
      };
    });
  })
);

const summarizeControls = (controls) => {
  const counts = { buttons: 0, links: 0, inputs: 0, selects: 0, textareas: 0, tabs: 0, disabled: 0 };
  for (const control of controls) {
    if (control.tag === 'button' || control.role === 'button') counts.buttons += 1;
    if (control.tag === 'a') counts.links += 1;
    if (control.tag === 'input') counts.inputs += 1;
    if (control.tag === 'select') counts.selects += 1;
    if (control.tag === 'textarea') counts.textareas += 1;
    if (control.role === 'tab') counts.tabs += 1;
    if (control.disabled) counts.disabled += 1;
  }
  return counts;
};

const waitForPageSettled = async (page) => {
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => null);
  await page.waitForTimeout(300);
};

const visibleTextSample = async (page) => {
  const main = page.locator('main.hpt-main');
  const mainText = await main.innerText({ timeout: 2500 }).catch(() => '');
  if (mainText) return compact(mainText).slice(0, 900);
  const bodyText = await page.locator('body').innerText({ timeout: 2500 }).catch(() => '');
  return compact(bodyText).slice(0, 900);
};

const clickSafeControls = async ({ page, route, controls, crossLinks, scenarioBacklog }) => {
  const clicks = [];
  const seenLabels = new Set();
  let clicked = 0;

  for (const control of controls) {
    const classification = classifyControl(control);
    const labelKey = compact(`${control.tag}:${control.role}:${control.label || control.text || control.placeholder || control.href}`).slice(0, 140);
    const target = sameAppTarget(control.href);
    if (target && target !== route.path) {
      crossLinks.push({
        sourcePath: route.path,
        sourceLabel: route.label,
        targetPath: target,
        sourceGroup: route.group,
        targetGroup: routeGroupForPath(target),
        label: control.label || control.text || control.href,
        kind: 'href',
      });
    }

    if (!classification.safe) {
      if (classification.reason !== 'disabled' && !classification.reason.includes('global navigation chrome')) {
        scenarioBacklog.push({
          route: route.path,
          routeLabel: route.label,
          control: control.label || control.text || control.placeholder || control.href || control.auditId,
          tag: control.tag,
          reason: classification.reason,
        });
      }
      continue;
    }
    if (seenLabels.has(labelKey)) continue;
    seenLabels.add(labelKey);
    if (clicked >= SAFE_CLICK_LIMIT) {
      scenarioBacklog.push({
        route: route.path,
        routeLabel: route.label,
        control: control.label || control.text || control.href || control.auditId,
        tag: control.tag,
        reason: `safe click limit ${SAFE_CLICK_LIMIT} reached; covered by inventory only`,
      });
      continue;
    }

    const locator = page.locator(`[data-full-chain-audit-id="${control.auditId}"]`).first();
    const beforeUrl = page.url();
    try {
      await locator.scrollIntoViewIfNeeded({ timeout: 1500 }).catch(() => null);
      await locator.click({ timeout: 1500, noWaitAfter: true });
      clicked += 1;
      await page.waitForTimeout(300);
      const afterUrl = page.url();
      const afterTarget = sameAppTarget(afterUrl);
      const navigated = afterUrl !== beforeUrl;
      if (navigated && afterTarget) {
        crossLinks.push({
          sourcePath: route.path,
          sourceLabel: route.label,
          targetPath: afterTarget,
          sourceGroup: route.group,
          targetGroup: routeGroupForPath(afterTarget),
          label: control.label || control.text || control.href,
          kind: 'clicked-navigation',
        });
      }
      clicks.push({
        control: control.label || control.text || control.href || control.auditId,
        ok: true,
        reason: classification.reason,
        navigated,
        afterPath: afterTarget,
      });

      await page.keyboard.press('Escape').catch(() => null);
      await page.getByRole('button', { name: /^关闭$|^取消$/ }).last().click({ timeout: 800 }).catch(() => null);
      if (navigated) {
        await page.goto(`${BASE_URL}${route.path}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
        await waitForPageSettled(page);
      }
    } catch (error) {
      clicks.push({
        control: control.label || control.text || control.href || control.auditId,
        ok: false,
        reason: classification.reason,
        error: error?.message || String(error),
      });
    }
  }

  return clicks;
};

const runRoute = async ({ context, route, crossLinks, scenarioBacklog }) => {
  const startedAt = Date.now();
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const apiErrors = [];
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
  page.on('response', (response) => {
    const url = response.url();
    if (!url.startsWith(`${BASE_URL}/api/`)) return;
    if (response.status() < 400) return;
    if (/\/api\/(notifications|portal\/notifications)/.test(url) && response.status() === 404) return;
    apiErrors.push({ status: response.status(), url });
  });

  try {
    await page.goto(`${BASE_URL}${route.path}`, { waitUntil: 'domcontentloaded', timeout: ROUTE_TIMEOUT_MS });
    await page.waitForSelector('body', { timeout: ROUTE_TIMEOUT_MS });
    await waitForPageSettled(page);

    const finalUrl = page.url();
    const currentPath = new URL(finalUrl).pathname;
    const textSample = await visibleTextSample(page);
    const controls = await collectControls(page);
    const controlSummary = summarizeControls(controls);
    const visibleErrors = ERROR_TEXT_RE.test(textSample) ? [textSample.match(ERROR_TEXT_RE)?.[0]].filter(Boolean) : [];
    const failures = [];

    if (currentPath.includes('/login')) failures.push('redirected_to_login');
    if (visibleErrors.length) failures.push(`visible_error_text:${visibleErrors.join('|')}`);
    if (consoleErrors.length) failures.push('console_error');
    if (pageErrors.length) failures.push('page_error');
    if (apiErrors.some((item) => item.status >= 500)) failures.push('api_5xx');
    if (!controls.length && !route.displayOnly) failures.push('no_visible_controls');
    if (!controls.length && route.displayOnly && !textSample) failures.push('display-only route rendered no text');

    const safeClicks = await clickSafeControls({ page, route, controls, crossLinks, scenarioBacklog });
    const clickFailures = safeClicks.filter((item) => !item.ok);
    const interactionFindings = clickFailures.map((item) => ({
      type: 'safe_click_failure',
      route: route.path,
      routeLabel: route.label,
      control: item.control,
      reason: item.reason,
      error: item.error,
    }));
    for (const finding of interactionFindings) {
      scenarioBacklog.push({
        route: route.path,
        routeLabel: route.label,
        control: finding.control,
        tag: 'safe-click',
        reason: `safe click needs scenario review: ${finding.error}`,
      });
    }

    if (failures.length) {
      screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(route.group)}-${sanitize(route.label)}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    }

    return {
      ok: failures.length === 0,
      ...route,
      finalUrl,
      failures,
      consoleErrors,
      pageErrors,
      apiErrors,
      controlSummary,
      controlCount: controls.length,
      controls,
      safeClicks,
      interactionFindings,
      screenshotPath,
      durationMs: Date.now() - startedAt,
      textSample,
    };
  } catch (error) {
    screenshotPath = path.join(ARTIFACT_DIR, `${runId}-${sanitize(route.group)}-${sanitize(route.label)}-exception.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    return {
      ok: false,
      ...route,
      finalUrl: page.url(),
      failures: ['exception'],
      error: error?.stack || error?.message || String(error),
      consoleErrors,
      pageErrors,
      apiErrors,
      controlSummary: summarizeControls([]),
      controlCount: 0,
      controls: [],
      safeClicks: [],
      interactionFindings: [],
      screenshotPath,
      durationMs: Date.now() - startedAt,
      textSample: '',
    };
  } finally {
    await page.close().catch(() => null);
  }
};

const addAuthToContext = async (context, auth) => {
  await context.addInitScript(({ token, user }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user });
};

const writeReports = async (report) => {
  const jsonPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const markdownPath = path.join(ARTIFACT_DIR, `${runId}.md`);
  await writeFile(jsonPath, `${JSON.stringify({ ...report, jsonPath, markdownPath }, null, 2)}\n`, 'utf8');

  const failed = report.results.filter((item) => !item.ok);
  const interactionFindings = report.results.flatMap((item) => item.interactionFindings || []);
  const failedLinkValidations = (report.linkValidations || []).filter((item) => !item.ok);
  const lines = [
    `# SaaS Full-Chain Interaction Audit`,
    '',
    `- Run ID: \`${report.runId}\``,
    `- Base URL: \`${report.baseUrl}\``,
    `- Checked at: \`${report.checkedAt}\``,
    `- Routes: ${report.routeCount}, passed: ${report.passed}, failed: ${report.failed}, skipped: ${report.skippedRoutes.length}`,
    `- Controls inventoried: ${report.controlTotals.total}, safe clicks attempted: ${report.controlTotals.safeClicks}, interaction findings: ${interactionFindings.length}, scenario backlog: ${report.scenarioBacklog.length}`,
    `- Cross-module links found: ${report.crossLinks.length}`,
    `- Link target validations: ${(report.linkValidations || []).length}, failed: ${failedLinkValidations.length}`,
    '',
    '## Route Results',
    '',
    '| Status | Group | Route | Label | Controls | Safe Clicks | Failures |',
    '| --- | --- | --- | --- | ---: | ---: | --- |',
    ...report.results.map((item) => `| ${item.ok ? 'PASS' : 'FAIL'} | ${item.group} | \`${item.path}\` | ${item.label} | ${item.controlCount} | ${item.safeClicks.length} | ${item.failures.join(', ') || '-'} |`),
  ];

  if (report.skippedRoutes.length) {
    lines.push('', '## Skipped Routes', '');
    for (const item of report.skippedRoutes) {
      lines.push(`- \`${item.path}\` ${item.label}: ${item.reason}`);
    }
  }

  if (failed.length) {
    lines.push('', '## Failures', '');
    for (const item of failed) {
      lines.push(`- \`${item.path}\` ${item.label}: ${item.failures.join(', ')}`);
      if (item.screenshotPath) lines.push(`  - Screenshot: \`${item.screenshotPath}\``);
      if (item.consoleErrors.length) lines.push(`  - Console: ${item.consoleErrors.slice(0, 3).join(' | ')}`);
      if (item.pageErrors.length) lines.push(`  - Page errors: ${item.pageErrors.slice(0, 2).join(' | ')}`);
      if (item.apiErrors.length) lines.push(`  - API: ${item.apiErrors.slice(0, 5).map((api) => `${api.status} ${api.url.replace(BASE_URL, '')}`).join(' | ')}`);
    }
  }

  if (interactionFindings.length) {
    lines.push('', '## Interaction Findings', '');
    for (const item of interactionFindings.slice(0, 120)) {
      lines.push(`- \`${item.route}\` ${item.routeLabel}: ${compact(item.control).slice(0, 100)} (${item.type}; ${compact(item.reason || '').slice(0, 80)})`);
    }
    if (interactionFindings.length > 120) lines.push(`- ... ${interactionFindings.length - 120} more findings in JSON report`);
  }

  lines.push('', '## Link Target Validation', '');
  const statusCounts = (report.linkValidations || []).reduce((acc, item) => {
    const key = String(item.status);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  lines.push(`- Status counts: ${Object.entries(statusCounts).map(([key, count]) => `${key}=${count}`).join(', ') || '-'}`);
  for (const item of failedLinkValidations.slice(0, 80)) {
    lines.push(`- FAIL \`${item.targetPath}\`: ${item.status}${item.error ? ` (${item.error})` : ''}`);
  }
  if (failedLinkValidations.length > 80) lines.push(`- ... ${failedLinkValidations.length - 80} more failed link validations in JSON report`);

  lines.push('', '## Cross-Module Links', '');
  for (const link of report.crossLinks.slice(0, 120)) {
    lines.push(`- ${link.sourceGroup} \`${link.sourcePath}\` -> ${link.targetGroup} \`${link.targetPath}\` via ${link.kind}: ${compact(link.label).slice(0, 80)}`);
  }
  if (report.crossLinks.length > 120) lines.push(`- ... ${report.crossLinks.length - 120} more links in JSON report`);

  lines.push('', '## Scenario Backlog', '');
  for (const item of report.scenarioBacklog.slice(0, 160)) {
    lines.push(`- \`${item.route}\` ${item.routeLabel}: ${compact(item.control).slice(0, 100)} (${item.reason})`);
  }
  if (report.scenarioBacklog.length > 160) lines.push(`- ... ${report.scenarioBacklog.length - 160} more backlog items in JSON report`);

  if (report.blockers.length) {
    lines.push('', '## Blockers', '');
    for (const blocker of report.blockers) lines.push(`- ${blocker}`);
  }

  await writeFile(markdownPath, `${lines.join('\n')}\n`, 'utf8');
  return { jsonPath, markdownPath };
};

const makeRoutes = (routes, group) => routes.map((route) => ({ ...route, group }));

const selectedRoutes = (routes) => {
  const requested = (process.env.HRM_FULL_CHAIN_ROUTES || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (!requested.length) return routes;
  return routes.filter((route) => requested.includes(route.path) || requested.includes(route.label) || requested.includes(route.group));
};

const isFilteredRouteScope = () => Boolean((process.env.HRM_FULL_CHAIN_ROUTES || '').trim());

const escapeRegex = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const dynamicScenarioForPath = (targetPath) => DYNAMIC_SCENARIOS.find((item) => {
  const pattern = item.path
    .split('/')
    .map((part) => (part.startsWith(':') ? '[^/]+' : escapeRegex(part)))
    .join('/');
  return new RegExp(`^${pattern}$`).test(targetPath);
});

const validateLinkTargets = async ({ crossLinks, auditedPaths, filteredRouteScope = false }) => {
  const targets = [...new Set(crossLinks.map((link) => {
    const target = sameAppTarget(link.targetPath);
    return (target || link.targetPath || '').split(/[?#]/)[0];
  }).filter(Boolean))].sort();
  const validations = [];
  for (const targetPath of targets) {
    if (auditedPaths.has(targetPath)) {
      validations.push({ targetPath, ok: true, status: 'covered_by_route_audit' });
      continue;
    }
    const dynamicScenario = dynamicScenarioForPath(targetPath);
    if (dynamicScenario) {
      validations.push({
        targetPath,
        ok: true,
        status: 'dynamic_scenario_backlog',
        scenario: dynamicScenario.path,
      });
      continue;
    }
    if (targetPath.startsWith('/docs/')) {
      try {
        const response = await fetch(`${BASE_URL}${targetPath}`, {
          signal: AbortSignal.timeout(Number(process.env.HRM_FULL_CHAIN_LINK_TIMEOUT_MS || 8000)),
        });
        validations.push({ targetPath, ok: response.ok, status: response.status });
      } catch (error) {
        validations.push({ targetPath, ok: false, status: 'fetch_error', error: error?.message || String(error) });
      }
      continue;
    }
    validations.push({
      targetPath,
      ok: filteredRouteScope,
      status: filteredRouteScope ? 'filtered_route_scope' : 'not_in_route_inventory',
    });
  }
  return validations;
};

const main = async () => {
  await mkdir(ARTIFACT_DIR, { recursive: true });

  const hrmResult = await resolveHrmSmokeCredentials({
    baseUrl: BASE_URL,
    env: process.env,
    dotEnv,
    fetchImpl: fetch,
    runId,
  });
  console.log(`Full-chain HRM credentials: ${hrmResult.source} tenant=${hrmResult.credentials.tenantSlug} email=${hrmResult.credentials.email}`);

  const hrmRoutes = selectedRoutes(makeRoutes(MANAGEMENT_ROUTES, 'management'));
  const platformRoutes = selectedRoutes(makeRoutes(PLATFORM_ROUTES, 'platform'));
  const portalRoutes = selectedRoutes(makeRoutes(PORTAL_ROUTES, 'portal'));
  const needsPortalAudit = portalRoutes.length > 0;
  const needsPlatformAudit = platformRoutes.length > 0;

  const blockers = [];
  let platformAuth = null;
  if (needsPlatformAudit) {
    try {
      platformAuth = await platformLogin();
    } catch (error) {
      blockers.push(`Platform login unavailable: ${error.message}`);
    }
  }

  const portalResult = needsPortalAudit
    ? await resolvePortalAuth({
      hrmAuth: hrmResult.auth,
      preferredTenantSlug: hrmResult.credentials.tenantSlug,
    })
    : { auth: null, fixtureEmployeeId: null, blocker: null };
  if (needsPortalAudit && !portalResult.auth) blockers.push(`Employee portal routes blocked: ${portalResult.blocker}`);
  else if (portalResult.auth) console.log(`Full-chain portal credentials: employeeNo=${portalResult.employeeNo}`);

  const { chromium } = await importPlaywright();
  let browser = null;

  const results = [];
  const skippedRoutes = [];
  const crossLinks = [];
  const scenarioBacklog = DYNAMIC_SCENARIOS.map((item) => ({
    route: item.path,
    routeLabel: item.label,
    control: item.path,
    tag: 'dynamic-route',
    reason: item.reason,
  }));

  try {
    browser = await chromium.launch({
      headless: true,
      executablePath: EDGE_EXECUTABLE,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    const hrmContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await addAuthToContext(hrmContext, hrmResult.auth);
    for (const route of hrmRoutes) {
      console.log(`RUN ${route.path} ${route.label}`);
      const result = await runRoute({ context: hrmContext, route, crossLinks, scenarioBacklog });
      results.push(result);
      console.log(`${result.ok ? 'PASS' : 'FAIL'} ${route.path} ${route.label} controls=${result.controlCount} clicks=${result.safeClicks.length}`);
    }
    await hrmContext.close();

    if (platformAuth) {
      const platformContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await addAuthToContext(platformContext, platformAuth);
      for (const route of platformRoutes) {
        console.log(`RUN ${route.path} ${route.label}`);
        const result = await runRoute({ context: platformContext, route, crossLinks, scenarioBacklog });
        results.push(result);
        console.log(`${result.ok ? 'PASS' : 'FAIL'} ${route.path} ${route.label} controls=${result.controlCount} clicks=${result.safeClicks.length}`);
      }
      await platformContext.close();
    } else {
      for (const route of platformRoutes) {
        skippedRoutes.push({ ...route, reason: 'platform login unavailable' });
      }
    }

    if (portalResult.auth) {
      const portalContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await addAuthToContext(portalContext, portalResult.auth);
      for (const route of portalRoutes) {
        console.log(`RUN ${route.path} ${route.label}`);
        const result = await runRoute({ context: portalContext, route, crossLinks, scenarioBacklog });
        results.push(result);
        console.log(`${result.ok ? 'PASS' : 'FAIL'} ${route.path} ${route.label} controls=${result.controlCount} clicks=${result.safeClicks.length}`);
      }
      await portalContext.close();
    } else {
      for (const route of portalRoutes) {
        skippedRoutes.push({ ...route, reason: portalResult.blocker || 'portal login unavailable' });
      }
    }
  } finally {
    await browser?.close().catch(() => null);
    if (portalResult.fixtureEmployeeId) {
      try {
        await cleanupPortalSmokeEmployee({
          hrmAuth: hrmResult.auth,
          employeeId: portalResult.fixtureEmployeeId,
        });
      } catch (error) {
        blockers.push(`Portal smoke employee cleanup failed: ${error.message}`);
      }
    }
  }

  const failed = results.filter((item) => !item.ok);
  const auditedPaths = new Set(results.map((item) => item.path));
  const linkValidations = await validateLinkTargets({ crossLinks, auditedPaths, filteredRouteScope: isFilteredRouteScope() });
  const failedLinkValidations = linkValidations.filter((item) => !item.ok);
  const controlTotals = results.reduce((acc, item) => {
    acc.total += item.controlCount;
    acc.safeClicks += item.safeClicks.length;
    acc.buttons += item.controlSummary.buttons;
    acc.links += item.controlSummary.links;
    acc.inputs += item.controlSummary.inputs;
    acc.selects += item.controlSummary.selects;
    acc.textareas += item.controlSummary.textareas;
    acc.tabs += item.controlSummary.tabs;
    acc.disabled += item.controlSummary.disabled;
    return acc;
  }, { total: 0, safeClicks: 0, buttons: 0, links: 0, inputs: 0, selects: 0, textareas: 0, tabs: 0, disabled: 0 });

  const report = {
    ok: failed.length === 0 && failedLinkValidations.length === 0 && skippedRoutes.length === 0 && blockers.length === 0,
    runId,
    baseUrl: BASE_URL,
    checkedAt: new Date().toISOString(),
    routeCount: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    skippedRoutes,
    blockers,
    controlTotals,
    crossLinks,
    linkValidations,
    scenarioBacklog,
    results,
  };
  const paths = await writeReports(report);

  console.log(JSON.stringify({
    ok: report.ok,
    runId,
    baseUrl: BASE_URL,
    routes: report.routeCount,
    passed: report.passed,
    failed: report.failed,
    skipped: skippedRoutes.length,
    controls: controlTotals,
    crossLinks: crossLinks.length,
    linkValidations: {
      total: linkValidations.length,
      failed: failedLinkValidations.length,
    },
    scenarioBacklog: scenarioBacklog.length,
    blockers,
    ...paths,
  }, null, 2));

  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
});
