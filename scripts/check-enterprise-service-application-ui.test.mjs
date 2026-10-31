import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const read = (path) => {
  const url = new URL(path, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const router = read('../src/router/index.tsx');
const login = read('../src/pages/p-login/index.tsx');
const applicationPage = read('../src/pages/p-enterprise-application/index.tsx');
const platformPage = read('../src/pages/p-platform-tenants/index.tsx');
const platformPanel = read('../src/components/platform/EnterpriseApplicationsPanel.tsx');
const api = read('../src/utils/api.ts');
const backendApp = read('../backend-python/app.py');
const packageJson = read('../package.json');
const browserVerification = read('./verify-platform-console-browser.mjs');

test('login exposes a shellless enterprise-service application route', () => {
  assert.match(login, /to=["']\/enterprise-application["']/);
  assert.match(login, /申请企业服务/);
  assert.match(router, /p-enterprise-application/);
  assert.match(router, /path:\s*["']\/enterprise-application["']/);
  assert.match(router, /<P_enterprise_application\s*\/>/);
});

test('public form exposes the approved fields and privacy-safe success state', () => {
  for (const token of [
    'companyName',
    'contactName',
    'mobile',
    'email',
    'region',
    'employeeScale',
    'interestedModules',
    'preferredContactTime',
    'notes',
    'privacyConsent',
    'website',
    '申请已提交',
    'applicationNo',
    '工作日',
  ]) {
    assert.match(applicationPage, new RegExp(token));
  }
  assert.match(applicationPage, /publicEnterpriseApplicationApi\.create/);
  assert.match(applicationPage, /type=["']checkbox["']/);
  assert.match(applicationPage, /aria-live=["']polite["']/);
  assert.match(applicationPage, /aria-invalid/);
  assert.match(applicationPage, /aria-describedby/);
  assert.match(applicationPage, /validateEnterpriseApplicationForm/);
  assert.match(applicationPage, /idempotencyKey\.current\.invalidate\(\)/);
  assert.match(applicationPage, /申请暂未提交成功，请稍后重试/);
  assert.doesNotMatch(applicationPage, /caught\s+instanceof\s+Error\s*\?\s*caught\.message/);
  assert.doesNotMatch(applicationPage, /localStorage|sessionStorage|history\.pushState|URLSearchParams/);
});

test('public form freezes every request-snapshot control while submission is pending', () => {
  assert.match(
    applicationPage,
    /<form[\s\S]*?<fieldset[^>]*disabled=\{submitting\}[\s\S]*?<\/fieldset>[\s\S]*?<\/form>/,
  );
});

test('public API uses a request-local idempotency key and exposes no auth dependency', () => {
  assert.match(api, /export interface EnterpriseApplicationCreatePayload/);
  assert.match(api, /export interface EnterpriseApplicationCreated/);
  assert.match(api, /export const publicEnterpriseApplicationApi/);
  assert.match(api, /\/public\/enterprise-applications/);
  assert.match(api, /Idempotency-Key/);
  assert.match(api, /crypto[^\n]+randomUUID|genRequestId/);
  assert.match(backendApp, /'PATCH'/);
  assert.match(backendApp, /'Idempotency-Key'/);
});

test('public enterprise submissions deliberately omit an existing bearer token', () => {
  assert.match(api, /async postPublic<T>\(/);
  assert.match(api, /this\.request<T>\(endpoint, \{[\s\S]*?method: 'POST'[\s\S]*?\}, false\)/);
  assert.match(
    api,
    /publicEnterpriseApplicationApi[\s\S]*?apiClient\.postPublic<EnterpriseApplicationCreated>/,
  );
});

test('platform console contains an enterprise-application workbench', () => {
  assert.match(platformPage, /EnterpriseApplicationsPanel/);
  assert.match(platformPage, /enterpriseApplications/);
  assert.match(platformPage, /企业申请/);
  assert.match(platformPage, /activeTab\s*===\s*['"]enterpriseApplications['"]/);
  assert.match(platformPanel, /platformEnterpriseApplicationApi/);
  for (const token of [
    '今日新增',
    '待联系',
    '跟进中',
    '有效意向',
    '关键词',
    '状态',
    '详情',
    '接手',
    '标记已联系',
    '标记有效意向',
    '关闭',
    '关联已创建企业',
    '内部备注',
    '下次跟进',
    'ProductMetricCard',
    'ProductEmptyState',
    'ProductStatusBadge',
  ]) {
    assert.match(platformPanel, new RegExp(token));
  }
});

test('typed platform API covers summary, pagination, detail, patch, and conversion', () => {
  for (const token of [
    'export interface EnterpriseApplicationListItem',
    'export interface EnterpriseServiceApplication',
    'export interface EnterpriseApplicationTimelineEvent',
    'export interface EnterpriseApplicationSummary',
    'export interface EnterpriseApplicationPage',
    'export const platformEnterpriseApplicationApi',
    '/platform/enterprise-applications/summary',
    '/platform/enterprise-applications/search',
    '/platform/enterprise-applications/${id}',
    '/platform/enterprise-applications/${id}/convert',
    'apiClient.patch',
  ]) {
    assert.match(api, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(api, /normalizeEnterpriseApplicationListItem/);
  assert.match(api, /options:\s*RequestInit/);
  assert.match(platformPanel, /AbortController/);
  assert.match(platformPanel, /LatestRequestGate/);
  assert.match(platformPanel, /runConfirmedEnterpriseConversion/);
  assert.match(platformPanel, /listError/);
  assert.match(platformPanel, /detailError/);
  assert.match(platformPanel, /writeError/);
  assert.match(platformPanel, /detailAbort\.current\?\.abort\(\)/);
  assert.match(platformPanel, /writeAbort\.current\?\.abort\(\)/);
  assert.doesNotMatch(
    api.match(/export interface EnterpriseApplicationCreatePayload[\s\S]*?\n}/)?.[0] || '',
    /\bsource\b/,
  );
});

test('platform mutations send the observed version and refresh a conflicted detail', () => {
  assert.match(
    api,
    /export interface EnterpriseApplicationUpdatePayload[\s\S]*?version:\s*number;[\s\S]*?\n}/,
  );
  assert.match(api, /\{\s*tenantId,\s*version\s*\}/);
  assert.match(platformPanel, /version:\s*selected\.version/);
  assert.match(
    platformPanel,
    /platformEnterpriseApplicationApi\.convert\([\s\S]*?selected\.version/,
  );
  assert.match(platformPanel, /caught\s+instanceof\s+ApiError/);
  assert.match(platformPanel, /APPLICATION_CONFLICT/);
  assert.match(platformPanel, /platformEnterpriseApplicationApi\.detail\(/);
});

test('conversion target options come from an independent unfiltered cancellable tenant request', () => {
  assert.doesNotMatch(
    platformPage,
    /<EnterpriseApplicationsPanel[\s\S]{0,200}?tenants=\{tenants\}/,
  );
  assert.match(platformPanel, /for\s*\(let\s+page\s*=\s*1;[\s\S]*platformApi\.listTenants\(\s*\{\s*page,\s*pageSize:\s*TENANT_OPTION_PAGE_SIZE\s*\}/);
  assert.match(platformPanel, /batch\.length\s*<\s*TENANT_OPTION_PAGE_SIZE/);
  assert.match(platformPanel, /tenantOptionsAbort\.current\?\.abort\(\)/);
  assert.match(platformPanel, /tenantOptions\.map\(/);
  assert.match(platformPanel, /listAbort\.current\?\.abort\(\)/);
  assert.match(platformPanel, /pageSize:\s*20/);
  assert.match(api, /listTenants:\s*\(\s*params\?:\s*\{[\s\S]*page\?:\s*number;[\s\S]*pageSize\?:\s*number/);
});

test('platform console test script and local-only browser acceptance are wired', () => {
  const parsed = JSON.parse(packageJson);
  assert.equal(typeof parsed.scripts['test:platform-console'], 'string');
  assert.match(parsed.scripts['test:platform-console'], /enterprise-application-behavior\.test\.mjs/);
  assert.match(browserVerification, /http:\/\/localhost:18280/);
  assert.match(browserVerification, /enterprise-application/);
  assert.match(browserVerification, /申请企业服务/);
  assert.match(browserVerification, /企业申请/);
  assert.match(browserVerification, /只允许本地 SaaS 预览/);
  assert.match(browserVerification, /page\.route\(['"]\*\*\/api\/public\/enterprise-applications/);
  assert.match(
    browserVerification,
    /page\.route\(['"]\*\*\/api\/platform\/enterprise-applications\*\*['"]/,
  );
  assert.match(browserVerification, /idempotency-key/);
  assert.match(browserVerification, /x-request-id/);
  assert.match(browserVerification, /敏感搜索必须通过 POST 正文提交/);
  assert.match(browserVerification, /第一次点击只能打开二次确认/);
  assert.match(browserVerification, /二次确认后必须且只能转换一次/);
  assert.match(
    browserVerification,
    /page\.locator\(['"]span['"]\)\.filter\(\{\s*hasText:\s*\/\^已转企业\$\/\s*\}\)\.first\(\)\.isVisible\(\)/,
  );
  assert.match(browserVerification, /申请分页未请求第二页/);
  assert.match(browserVerification, /不写入真实后端/);
});
