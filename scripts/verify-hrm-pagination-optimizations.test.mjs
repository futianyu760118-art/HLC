import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const apiSource = readFileSync(new URL('../src/utils/api.ts', import.meta.url), 'utf8');
const hrmPageSource = readFileSync(new URL('../src/pages/p-hrm/index.tsx', import.meta.url), 'utf8');

test('hrm api exposes a typed paginated list contract while preserving array list compatibility', () => {
  assert.match(apiSource, /export interface HrmPageResult<T>/);
  assert.match(apiSource, /listPage:\s*<T = any>/);
  assert.match(apiSource, /apiClient\.get<HrmPageResult<T>>\(`\/hrm\/\$\{resource\}\$\{buildQuery\(params\)\}`\)/);
  assert.match(apiSource, /list:\s*<T = any>[\s\S]*apiClient\.get<T\[\]>/);
});

test('hrm module page uses server pagination for normal resource lists', () => {
  assert.match(hrmPageSource, /HRM_PAGE_SIZE_OPTIONS/);
  assert.match(hrmPageSource, /const \[pageMeta, setPageMeta\]/);
  assert.match(hrmPageSource, /const \[pageSize, setPageSize\]/);
  assert.match(hrmPageSource, /const \[currentPage, setCurrentPage\]/);
  assert.match(hrmPageSource, /hrmApi\.listPage\(config\.resource, buildHrmListParams\(\)\)/);
  assert.doesNotMatch(hrmPageSource, /return await hrmApi\.list\(config\.resource\);/);
  assert.match(hrmPageSource, /共 <span className="font-medium text-gray-600">\{pageMeta\.total\}<\/span> 条/);
  assert.match(hrmPageSource, /上一页/);
  assert.match(hrmPageSource, /下一页/);
});

test('attendance records page can view a month by employee and jump to monthly summary', () => {
  assert.match(hrmPageSource, /module === 'attendance-records'/);
  assert.match(hrmPageSource, /monthDateBounds/);
  assert.match(hrmPageSource, /searchParams\.get\('employeeId'\)/);
  assert.match(hrmPageSource, /\/attendance-stats/);
  assert.match(hrmPageSource, /按月汇总/);
});

test('hrm route cache key is declared after the month state it depends on', () => {
  const monthStateIndex = hrmPageSource.indexOf("const [month, setMonth]");
  const routeKeyIndex = hrmPageSource.indexOf('const routeKey = `${module}:${month}`');
  assert.notEqual(monthStateIndex, -1);
  assert.notEqual(routeKeyIndex, -1);
  assert.ok(routeKeyIndex > monthStateIndex, 'routeKey must not read month before the month state is initialized');
});
