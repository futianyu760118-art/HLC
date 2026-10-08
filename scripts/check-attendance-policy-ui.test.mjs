import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (relativePath) => readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');

const api = read('src/utils/api.ts');
const page = read('src/pages/p-attendance-policy/index.tsx');
const layout = read('src/components/Layout.tsx');
const router = read('src/router/index.tsx');
const preload = read('src/router/pagePreload.ts');
const navigation = read('src/utils/moduleNavigation.ts');
const backend = read('backend-python/routes/hrm.py');

test('attendance policy API exposes configuration, daily results and recalculation contracts', () => {
  assert.match(api, /export interface AttendancePolicySnapshot/);
  assert.match(api, /attendancePolicySnapshot:\s*\(\)\s*=>/);
  assert.match(api, /\/hrm\/attendance-policy\/snapshot/);
  assert.match(api, /listAttendanceDailyResults:/);
  assert.match(api, /recalculateAttendanceDailyResults:/);
  assert.match(api, /createAttendancePolicyRow:/);
  assert.match(api, /updateAttendancePolicyRow:/);
  assert.match(api, /deleteAttendancePolicyRow:/);
});

test('attendance policy page covers the phase-two workbench', () => {
  assert.match(page, /考勤制度/);
  assert.match(page, /班次/);
  assert.match(page, /考勤规则/);
  assert.match(page, /考勤组/);
  assert.match(page, /成员范围/);
  assert.match(page, /节假日/);
  assert.match(page, /日排班/);
  assert.match(page, /考勤日报/);
  assert.match(page, /局部重算/);
  assert.match(page, /查看原因/);
  assert.match(page, /hrmApi\.attendancePolicySnapshot/);
  assert.match(page, /hrmApi\.recalculateAttendanceDailyResults/);
});

test('attendance policy route is attendance-module and role scoped', () => {
  assert.match(router, /p-attendance-policy/);
  assert.match(router, /path: '\/attendance-policy'/);
  assert.match(preload, /p-attendance-policy/);
  assert.match(layout, /path: '\/attendance-policy'/);
  assert.match(layout, /考勤制度/);
  assert.match(navigation, /attendance-stats\|attendance-sync\|attendance-policy/);
});

test('attendance policy backend has tenant-scoped CRUD and result endpoints', () => {
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/snapshot', methods=\['GET'\]\)/);
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/daily-results', methods=\['GET'\]\)/);
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/recalculate', methods=\['POST'\]\)/);
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/<kind>', methods=\['POST'\]\)/);
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/<kind>\/<row_id>', methods=\['PUT'\]\)/);
  assert.match(backend, /if kind == 'schedules'/);
  assert.match(backend, /@hrm_bp\.route\('\/attendance-policy\/<kind>\/<row_id>', methods=\['DELETE'\]\)/);
  assert.match(backend, /require_roles\(\{'admin', 'hr_admin'\}/);
  assert.match(backend, /current_tenant_id\(\)/);
});
