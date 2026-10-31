import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (relativePath) => readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');

const api = read('src/utils/api.ts');
const page = read('src/pages/p-attendance-sync/index.tsx');
const statsPage = read('src/pages/p-attendance_stats/index.tsx');
const layout = read('src/components/Layout.tsx');
const router = read('src/router/index.tsx');
const navigation = read('src/utils/moduleNavigation.ts');

test('attendance sync API exposes status, run and mapping contracts', () => {
  assert.match(api, /export interface AttendanceSyncStatus/);
  assert.match(api, /attendanceSyncStatus:\s*\(\)\s*=>/);
  assert.match(api, /\/hrm\/attendance-sync\/status/);
  assert.match(api, /runAttendanceSync:\s*\(\)\s*=>/);
  assert.match(api, /\/hrm\/attendance-sync\/run/);
  assert.match(api, /listAttendanceSyncPeople:\s*\(status\?:/);
  assert.match(api, /confirmAttendanceSyncPerson:\s*\(personId:\s*string,\s*employeeId:\s*string\)/);
  assert.match(api, /attendance-sync\/people\/\$\{personId\}\/confirm/);
  assert.match(api, /ignoreAttendanceSyncPerson:\s*\(personId:\s*string\)/);
});

test('attendance sync page is a 00001-only mapping workbench', () => {
  assert.match(page, /考勤机同步/);
  assert.match(page, /同名唯一匹配会自动绑定/);
  assert.match(page, /考勤机数字编号作为员工工号/);
  assert.match(page, /考勤工号/);
  assert.match(page, /hrmApi\.attendanceSyncStatus/);
  assert.match(page, /hrmApi\.runAttendanceSync/);
  assert.match(page, /hrmApi\.listAttendanceSyncPeople/);
  assert.match(page, /hrmApi\.confirmAttendanceSyncPerson/);
  assert.match(page, /hrmApi\.ignoreAttendanceSyncPerson/);
  assert.match(page, /tenantSlug === 'HPT-00000001'/);
  assert.match(page, /\['admin', 'hr_admin'\]/);
  assert.match(page, /待确认建议/);
  assert.match(page, /未匹配/);
  assert.match(page, /已确认/);
  assert.match(page, /\/hrm\/attendance-records/);
  assert.match(page, /dailyRecordCount/);
});

test('monthly attendance stats open employee daily records for the selected month', () => {
  assert.match(statsPage, /\/hrm\/attendance-records\?employeeId=/);
  assert.match(statsPage, /month=/);
  assert.match(statsPage, /查看日报/);
});

test('attendance sync is routed, menu-gated and attendance-module scoped', () => {
  assert.match(router, /p-attendance-sync/);
  assert.match(router, /path: '\/attendance-sync'/);
  assert.match(layout, /path: '\/attendance-sync'/);
  assert.match(layout, /考勤机同步/);
  assert.match(navigation, /\/\(attendance-stats\|attendance-sync\|attendance-policy\)/);
});
