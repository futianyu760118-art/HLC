import { dirname } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EDGE_EXECUTABLE, importPlaywright } from './resolve-playwright-runtime.mjs';

const root = path.resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dotEnvPath = path.join(root, '.env');
const dotEnv = existsSync(dotEnvPath)
  ? Object.fromEntries(
    readFileSync(dotEnvPath, 'utf8')
      .split(/\r?\n/)
      .map((line) => line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/))
      .filter(Boolean)
      .map((match) => [match[1], match[2].replace(/^['"]|['"]$/g, '')]),
  )
  : {};

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
if (BASE_URL !== 'http://localhost:18280') {
  throw new Error('企业申请与平台控制台验收只允许本地 SaaS 预览 http://localhost:18280');
}

const EMAIL = process.env.HRM_PLATFORM_EMAIL || process.env.HRM_TEST_PLATFORM_EMAIL || dotEnv.PLATFORM_ADMIN_EMAIL || 'platform@example.com';
const PASSWORD = process.env.HRM_PLATFORM_PASSWORD || process.env.HRM_TEST_PLATFORM_PASSWORD || dotEnv.PLATFORM_ADMIN_PASSWORD || 'Passw0rd!';
const assertCondition = (condition, message) => {
  if (!condition) throw new Error(message);
};
const jsonResponse = (route, payload, status = 200) => route.fulfill({
  status,
  contentType: 'application/json; charset=utf-8',
  body: JSON.stringify(payload),
});
const { chromium } = await importPlaywright();
const browser = await chromium.launch({
  executablePath: EDGE_EXECUTABLE,
  headless: true,
  args: ['--no-sandbox'],
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const publicRequests = [];
  await page.route('**/api/public/enterprise-applications', async (route) => {
    const request = route.request();
    publicRequests.push({
      headers: request.headers(),
      body: request.postDataJSON(),
    });
    await new Promise(resolve => setTimeout(resolve, 120));
    await jsonResponse(route, { applicationNo: 'ESA-BROWSER-VERIFY', status: 'new' }, 201);
  });
  await page.goto(`${BASE_URL}/enterprise-application`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '申请企业服务', exact: true }).waitFor({ state: 'visible' });
  await page.getByText('企业名称 *', { exact: true }).waitFor({ state: 'visible' });
  await page.getByText('联系人 *', { exact: true }).waitFor({ state: 'visible' });
  await page.getByText('手机号 *', { exact: true }).waitFor({ state: 'visible' });
  await page.locator('[name="companyName"]').fill('浏览器验收企业');
  await page.locator('[name="contactName"]').fill('验收联系人');
  await page.locator('[name="mobile"]').fill('13800138000');
  await page.locator('[name="email"]').fill('browser-verification@example.com');
  await page.locator('[name="region"]').fill('上海市');
  await page.locator('[name="employeeScale"]').selectOption('100-499');
  await page.locator('[name="preferredContactTime"]').selectOption('weekday_afternoon');
  await page.getByRole('button', { name: '招聘管理', exact: true }).click();
  await page.locator('[name="notes"]').fill('浏览器行为验收，不写入真实后端。');
  await page.locator('[name="privacyConsent"]').check();
  await page.getByRole('button', { name: '提交申请', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('button[type="submit"]')?.disabled === true);
  await page.getByText('ESA-BROWSER-VERIFY', { exact: true }).waitFor({ state: 'visible' });
  assertCondition(publicRequests.length === 1, '公开申请重复点击必须只产生一个请求');
  const publicRequest = publicRequests[0];
  assertCondition(Boolean(publicRequest.headers['idempotency-key']), '公开申请缺少 Idempotency-Key');
  assertCondition(Boolean(publicRequest.headers['x-request-id']), '公开申请缺少 X-Request-ID');
  assertCondition(publicRequest.body.companyName === '浏览器验收企业', '公开申请正文不完整');
  assertCondition(!Object.hasOwn(publicRequest.body, 'source'), '公开申请不得由客户端声明来源');
  assertCondition(!page.url().includes('ESA-BROWSER-VERIFY'), '申请编号不得进入 URL');
  const storedApplicationData = await page.evaluate(() => JSON.stringify({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  assertCondition(!storedApplicationData.includes('ESA-BROWSER-VERIFY'), '申请编号不得进入浏览器存储');
  assertCondition(!storedApplicationData.includes('13800138000'), '申请人信息不得进入浏览器存储');

  let application = {
    id: 'browser-application-1',
    applicationNo: 'ESA-BROWSER-PLATFORM',
    companyName: '浏览器验收企业',
    region: '上海市',
    employeeScale: '100-499',
    status: 'new',
    ownerUserId: null,
    ownerName: null,
    convertedTenantId: null,
    convertedTenantName: null,
    source: 'enterprise_application',
    version: 1,
    createdAt: '2026-07-22T01:00:00Z',
    updatedAt: '2026-07-22T01:00:00Z',
    contactName: '验收联系人',
    mobile: '13800138000',
    email: 'browser-verification@example.com',
    interestedModules: ['recruitment'],
    preferredContactTime: 'weekday_afternoon',
    notes: '浏览器行为验收，不写入真实后端。',
    followUpAt: null,
    internalNote: null,
    consentAt: '2026-07-22T01:00:00Z',
    timeline: [{ status: 'new', label: '提交企业服务申请', at: '2026-07-22T01:00:00Z' }],
  };
  const searchBodies = [];
  const patchBodies = [];
  const conversionBodies = [];
  const listItem = () => Object.fromEntries([
    'id', 'applicationNo', 'companyName', 'region', 'employeeScale', 'status',
    'ownerUserId', 'ownerName', 'convertedTenantId', 'convertedTenantName',
    'source', 'version', 'createdAt', 'updatedAt',
  ].map(key => [key, application[key]]));
  await page.route('**/api/platform/enterprise-applications**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (url.pathname.endsWith('/summary')) {
      await jsonResponse(route, { todayNew: 1, new: 1, contacting: 0, qualified: 0, closed: 0, converted: 0 });
      return;
    }
    if (url.pathname.endsWith('/search')) {
      const body = request.postDataJSON() || {};
      searchBodies.push(body);
      await jsonResponse(route, {
        items: [listItem()],
        page: body.page || 1,
        pageSize: body.pageSize || 20,
        total: 21,
        totalPages: 2,
      });
      return;
    }
    if (url.pathname.endsWith('/convert') && method === 'POST') {
      const body = request.postDataJSON() || {};
      conversionBodies.push(body);
      application = {
        ...application,
        status: 'converted',
        convertedTenantId: body.tenantId,
        convertedTenantName: '浏览器验收目标企业',
        timeline: [...application.timeline, {
          status: 'converted', label: '关联既有企业', at: '2026-07-22T03:00:00Z',
        }],
      };
      await jsonResponse(route, application);
      return;
    }
    if (method === 'PATCH') {
      const body = request.postDataJSON() || {};
      patchBodies.push(body);
      const nextTimeline = body.status && body.status !== application.status
        ? [...application.timeline, {
          status: body.status,
          label: body.status === 'contacting' ? '开始人工跟进' : '标记为有效意向',
          at: new Date(Date.parse(application.updatedAt) + 60_000).toISOString(),
        }]
        : application.timeline;
      application = {
        ...application,
        ...body,
        ownerName: body.ownerUserId ? '当前平台管理员' : application.ownerName,
        timeline: nextTimeline,
        version: application.version + 1,
        updatedAt: new Date(Date.parse(application.updatedAt) + 60_000).toISOString(),
      };
      await jsonResponse(route, application);
      return;
    }
    if (method === 'GET') {
      await jsonResponse(route, application);
      return;
    }
    await route.abort();
  });

  await page.goto(`${BASE_URL}/platform/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('#platformIdentifier').fill(EMAIL);
  await page.locator('#platformPassword').fill(PASSWORD);
  await page.getByRole('button', { name: /进入平台后台/ }).click();
  await page.waitForURL(/\/platform\/tenants/, { timeout: 15000 });

  await page.getByRole('button', { name: '企业申请', exact: true }).click();
  await page.getByRole('heading', { name: '企业申请', exact: true }).waitFor({ state: 'visible' });
  await page.getByText('ESA-BROWSER-PLATFORM', { exact: true }).waitFor({ state: 'visible' });
  assertCondition(!(await page.locator('body').innerText()).includes('13800138000'), '列表不得展示手机号');

  await page.getByPlaceholder('关键词：企业、联系人、手机号或申请编号').fill('13800138000');
  const filtered = page.waitForResponse(response => (
    response.url().includes('/api/platform/enterprise-applications/search')
    && response.request().postData()?.includes('13800138000')
  ));
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await filtered;
  assertCondition(searchBodies.at(-1)?.keyword === '13800138000', '敏感搜索必须通过 POST 正文提交');
  assertCondition(!page.url().includes('13800138000'), '敏感搜索词不得进入 URL');

  await page.getByRole('button', { name: '详情', exact: true }).click();
  await page.getByText('13800138000', { exact: true }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: '标记已联系', exact: true }).click();
  await page.getByRole('button', { name: '标记有效意向', exact: true }).waitFor({ state: 'visible' });
  await page.getByRole('button', { name: '标记有效意向', exact: true }).click();
  await page.getByText('有效意向', { exact: true }).first().waitFor({ state: 'visible' });
  await page.getByRole('textbox', { name: '内部备注' }).fill('仅用于浏览器验收的内部备注');
  await page.getByRole('button', { name: '保存内部备注', exact: true }).click();
  assertCondition(patchBodies.some(body => body.internalNote === '仅用于浏览器验收的内部备注'), '内部备注未通过 PATCH 提交');
  const tenantSelect = page.getByRole('heading', {
    name: '关联已创建企业', exact: true,
  }).locator('..').locator('select');
  assertCondition(await tenantSelect.locator('option').count() > 1, '转换验收需要至少一个既有企业');
  await tenantSelect.selectOption({ index: 1 });
  await page.getByRole('button', { name: '确认关联', exact: true }).click();
  assertCondition(conversionBodies.length === 0, '第一次点击只能打开二次确认');
  await page.getByRole('button', { name: '确认关联并进入终态', exact: true }).click();
  await page.getByText(/已关联：/).waitFor({ state: 'visible' });
  assertCondition(conversionBodies.length === 1, '二次确认后必须且只能转换一次');
  assertCondition(
    await page.locator('span').filter({ hasText: /^已转企业$/ }).first().isVisible(),
    '转换后必须展示终态',
  );
  await page.getByRole('button', { name: '关闭详情', exact: true }).last().click();

  const secondPage = page.waitForResponse(response => (
    response.url().includes('/api/platform/enterprise-applications/search')
    && response.request().postData()?.includes('"page":2')
  ));
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await secondPage;
  assertCondition(searchBodies.at(-1)?.page === 2, '申请分页未请求第二页');

  const tabs = ['企业客户', '应用与能力', '开通清单', '数据请求', '套餐管理', '订阅管理', '运行诊断', '平台操作日志'];
  for (const tab of tabs) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    await page.getByRole('heading', { name: tab }).first().waitFor({ state: 'visible', timeout: 5000 });
  }

  console.log('platform console browser verification passed');
} finally {
  await browser.close();
}
