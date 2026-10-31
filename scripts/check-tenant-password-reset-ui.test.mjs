import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const api = readFileSync(new URL('../src/utils/api.ts', import.meta.url), 'utf8');
const page = readFileSync(new URL('../src/pages/p-hrm/index.tsx', import.meta.url), 'utf8');

test('tenant HRM API exposes management and portal password reset contracts', () => {
  assert.match(api, /export interface AccountPasswordResetResult\s*\{/);
  assert.match(api, /initialPassword:\s*string;/);
  assert.match(api, /resetUserPassword:\s*\(userId:\s*string\)/);
  assert.match(api, /`\/hrm\/users\/\$\{userId\}\/reset-password`/);
  assert.match(api, /resetEmployeePortalPassword:\s*\(employeeId:\s*string\)/);
  assert.match(api, /`\/hrm\/employees\/\$\{employeeId\}\/reset-portal-password`/);
});

test('user and employee detail drawers expose confirmed password reset actions', () => {
  assert.match(page, /const currentUserRole = authUtils\.getUser\(\)\?\.role/);
  assert.match(page, /module === 'users' && currentUserRole === 'admin'/);
  assert.match(page, /module === 'employees' && \['admin', 'hr_admin'\]\.includes\(currentUserRole \|\| ''\)/);
  assert.match(page, /module === 'users'[\s\S]{0,500}重置后台密码/);
  assert.match(page, /module === 'employees'[\s\S]{0,900}重置门户密码/);
  assert.match(page, /hrmApi\.resetUserPassword\(record\.id\)/);
  assert.match(page, /hrmApi\.resetEmployeePortalPassword\(record\.id\)/);
  assert.match(page, /确定为[^\n]*生成新的后台一次性密码/);
  assert.match(page, /确定为[^\n]*生成新的员工门户一次性密码/);
});

test('one-time credential dialog copies and clears plaintext state', () => {
  assert.match(page, /const \[resetCredential, setResetCredential\] = useState/);
  assert.match(page, /navigator\.clipboard\.writeText\(resetCredential\.initialPassword\)/);
  assert.match(page, /一次性密码已生成/);
  assert.match(page, /首次登录时必须修改密码/);
  assert.match(page, /const closeResetCredential = \(\) => \{[\s\S]{0,160}setResetCredential\(null\)/);
  assert.match(page, /onClick=\{closeResetCredential\}/);
  assert.match(page, /sticky bottom-0 bg-white flex flex-wrap gap-2/);
});
