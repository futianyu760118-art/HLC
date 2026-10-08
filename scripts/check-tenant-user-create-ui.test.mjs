import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../src/pages/p-hrm/index.tsx', import.meta.url), 'utf8');
const config = readFileSync(new URL('../src/pages/p-hrm/moduleConfig.ts', import.meta.url), 'utf8');
const api = readFileSync(new URL('../src/utils/api.ts', import.meta.url), 'utf8');

test('tenant admin user creation is exposed through the guarded UI', () => {
  assert.match(config, /users:\s*\{[\s\S]*?allowAdminCreate:\s*true/);
  assert.match(page, /module === 'users' && currentUserRole === 'admin'/);
  assert.match(page, /hrmApi\.createUser\(payload\)/);
  assert.match(page, /setResetCredential\(\{[\s\S]*?新建的管理后台账号/);
  assert.match(api, /createUser:[\s\S]*?\/hrm\/users\/create/);
});
