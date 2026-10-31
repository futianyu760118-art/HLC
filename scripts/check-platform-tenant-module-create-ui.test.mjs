import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('src/pages/p-platform-tenants/index.tsx', 'utf8');

test('platform tenant creation form lets platform admins choose enabled modules', () => {
  assert.match(page, /enabledModules:\s*string\[\]/);
  assert.match(page, /enabledModules:\s*\[\.\.\.ALL_MODULE_KEYS\]/);
  assert.match(page, /开通模块/);
  assert.match(page, /新建企业开放\$\{module\.label\}模块/);
  assert.match(page, /enabledModules:\s*createForm\.enabledModules/);
});

test('platform tenant creation module defaults follow selected plan', () => {
  assert.match(page, /const modulesForPlan = \(planCode: string\)/);
  assert.match(page, /enabledModules:\s*modulesForPlan\(planCode\)/);
});

test('opening tenant creation form refreshes module defaults from loaded plan data', () => {
  assert.match(page, /const openCreateTenantForm = \(\) =>/);
  assert.match(page, /enabledModules:\s*modulesForPlan\(DEFAULT_CREATE_FORM\.planCode\)/);
  assert.match(page, /onClick=\{openCreateTenantForm\}/);
});
