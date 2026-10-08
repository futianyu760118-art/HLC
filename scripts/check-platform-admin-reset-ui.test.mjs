import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const api = readFileSync('src/utils/api.ts', 'utf8');
const page = readFileSync('src/pages/p-platform-tenants/index.tsx', 'utf8');

test('platform reset API requires an explicit target and confirmation payload', () => {
  assert.match(api, /export interface ResetTenantAdminPasswordPayload\s*\{[\s\S]*userId:\s*string;[\s\S]*confirmation:\s*string;/);
  assert.match(api, /resetAdminPassword:\s*\(id:\s*string,\s*data:\s*ResetTenantAdminPasswordPayload\)/);
  assert.doesNotMatch(api, /resetAdminPassword:[^\n]*data:[^\n]*=\s*\{\}/);
});

test('platform tenant workbench requires administrator selection and exact phrase', () => {
  assert.match(page, /selected\.admins/);
  assert.match(page, /value=\{resetAdminUserId\}/);
  assert.match(page, /value=\{resetConfirmation\}/);
  assert.match(page, /`RESET \$\{selected\.slug\}`/);
  assert.match(page, /userId:\s*resetAdminUserId/);
  assert.match(page, /confirmation:\s*resetConfirmation/);
  assert.match(page, /选择要重置的管理员/);
});

test('reset credential is ephemeral and closing confirmation clears sensitive inputs', () => {
  assert.doesNotMatch(page, /setMessage\(\s*`[^`]*initialPassword/);
  assert.doesNotMatch(page, /setMessage\(\s*result\.initialPassword/);
  assert.match(page, /resetCredential/);
  assert.match(page, /setResetCredential\(null\)/);
  assert.match(page, /role="dialog"/);
  assert.match(page, /navigator\.clipboard\.writeText\(resetCredential\.password\)/);
  assert.match(
    page,
    /const closeResetAdminPassword[\s\S]{0,320}setResetOpen\(false\);[\s\S]{0,160}setResetAdminUserId\(''\);[\s\S]{0,160}setResetConfirmation\(''\);/,
  );
  assert.match(page, /onCloseResetPassword/);
});
