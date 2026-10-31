import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const homePage = readFileSync('src/pages/p-home/index.tsx', 'utf8');
const layoutPage = readFileSync('src/components/Layout.tsx', 'utf8');
const navigationRules = readFileSync('src/utils/moduleNavigation.ts', 'utf8');

test('frontend navigation module mapping matches backend approval ownership for employee requests', () => {
  assert.match(navigationRules, /employee-requests.*approval|approval.*employee-requests/s);
  assert.doesNotMatch(layoutPage, /employee-requests\).*attendance|employee-requests['"]\), 'attendance'/);
});

test('home dashboard filters shortcuts and card navigation by tenant enabled modules', () => {
  assert.match(homePage, /getTenantModules\(\)/);
  assert.match(homePage, /isPathEnabled/);
  assert.match(homePage, /visiblePrimaryActions/);
  assert.match(homePage, /visibleQuickActions/);
  assert.match(homePage, /visibleStatCards\s*=\s*statCards\.filter/);
});
