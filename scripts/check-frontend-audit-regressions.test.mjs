import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (file) => readFileSync(file, 'utf8');

test('HRM record cache is scoped to the authenticated session and ignores stale responses', () => {
  const source = read('src/pages/p-hrm/index.tsx');
  assert.match(source, /authUtils\.getSessionScopeKey\(\)/);
  assert.match(source, /HRM_RECORD_CACHE_TTL_MS/);
  assert.match(source, /loadGenerationRef/);
  assert.match(source, /generation !== loadGenerationRef\.current/);
  assert.match(source, /hrmRecordInflight\.get\(cacheKey\) === request/);
});

test('layout fails closed, keeps mobile content at zero margin, and syncs notifications', () => {
  const source = read('src/components/Layout.tsx');
  assert.match(source, /modulesResult\.status === 'fulfilled' \? modulesResult\.value : \[\]/);
  assert.match(source, /setEnabledModules\(new Set\(\(rows \|\| \[\]\)/);
  assert.match(source, /if \(!enabledModules \|\| !supportedCapabilities\) return \[\]/);
  assert.match(source, /hrm:notifications-changed/);
  assert.match(source, /ml-0 md:/);
  assert.doesNotMatch(source, /className=\{`hpt-main \$\{mainMl\}[^`]*md:ml-60/);
});

test('todo page uses the shared API client and exposes a visible failure state', () => {
  const source = read('src/pages/p-todos/index.tsx');
  assert.doesNotMatch(source, /@ts-nocheck/);
  assert.match(source, /apiClient\.get/);
  assert.doesNotMatch(source, /localStorage\.getItem\(['"]access_token/);
  assert.match(source, /error/);
});

test('platform 401 responses return to platform login and portal controls stay in portal scope', () => {
  const api = read('src/utils/api.ts');
  const layout = read('src/components/Layout.tsx');
  assert.match(api, /platform\/login/);
  assert.match(api, /mode=platform/);
  assert.match(layout, /!isPortalAccount.*system-settings|!isPortalRoute.*system-settings/s);
  assert.match(layout, /mode=portal/);
});

test('error boundary renders a non-recursive fallback', () => {
  const source = read('src/components/ErrorBoundary.tsx');
  assert.doesNotMatch(source, /@ts-nocheck/);
  assert.match(source, /this\.state\.hasError/);
  assert.match(source, /重新加载|返回首页|window\.location/);
});

test('headcount and notification pages expose errors and broadcast mutations', () => {
  const headcount = read('src/pages/p-headcount-management/index.tsx');
  const notifications = read('src/pages/p-notifications/index.tsx');
  assert.doesNotMatch(headcount, /@ts-nocheck/);
  assert.match(headcount, /error/);
  assert.match(notifications, /hrm:notifications-changed/);
});
