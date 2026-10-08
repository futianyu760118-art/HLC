import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { evaluateCapabilityNavigation } from './check-capability-navigation.mjs';

const validCatalog = `
export const capabilityNavigation = [
  { path: '/headcount-management', label: '编制管理', icon: 'users', group: '组织管理' },
  { path: '/people-analytics', label: '人力分析', icon: 'chart-line', group: '首页' },
  { path: '/continuous-feedback', label: '持续反馈', icon: 'comments', group: '绩效管理' },
  { path: '/workforce-suite', label: '排班与劳动力', icon: 'calendar', group: '考勤与申请' },
  { path: '/security-suite', label: '安全与合规', icon: 'shield', group: '系统管理' },
];`;

test('accepts customer-facing domain navigation', () => {
  const result = evaluateCapabilityNavigation({
    catalogSource: validCatalog,
    layoutSource: "const menuGroups = [{ title: '组织管理', items: [] }]",
    pageSources: ["document.title = '人力分析 - 恒聘通'; <h1>人力分析</h1>"],
    supportedIcons: new Set(['users', 'chart-line', 'comments', 'calendar', 'shield']),
  });

  assert.equal(result.hasExtensionGroup, false);
  assert.deepEqual(result.packageLabelFindings, []);
  assert.deepEqual(result.customerCopyFindings, []);
  assert.equal(result.groupForPath['/headcount-management'], '组织管理');
  assert.equal(result.groupForPath['/people-analytics'], '首页');
  assert.equal(result.groupForPath['/continuous-feedback'], '绩效管理');
  assert.equal(result.groupForPath['/workforce-suite'], '考勤与申请');
  assert.equal(result.groupForPath['/security-suite'], '系统管理');
  assert.deepEqual(result.unsupportedIcons, []);
});

test('rejects internal package labels and unsupported icons', () => {
  const result = evaluateCapabilityNavigation({
    catalogSource: `export const capabilityNavigation = [
      { path: '/talent-strategy', label: '人才战略包', icon: 'users-gear', group: '扩展功能' },
    ];`,
    layoutSource: "const menuGroups = [{ title: '扩展功能', items: [] }]",
    pageSources: ["document.title = '人才战略包 - 恒聘通'; <h1>人才战略包</h1>"],
    supportedIcons: new Set(['users']),
  });

  assert.equal(result.hasExtensionGroup, true);
  assert.deepEqual(result.packageLabelFindings, ['人才战略包']);
  assert.deepEqual(result.customerCopyFindings, ['人才战略包', '人才战略包']);
  assert.deepEqual(result.unsupportedIcons, ['users-gear']);
});

test('every catalog icon has a dedicated AppIcon drawing', () => {
  const source = readFileSync(new URL('../src/components/AppIcon.tsx', import.meta.url), 'utf8');
  for (const icon of ['users', 'chart-line', 'comments', 'radar', 'chart-bar', 'brain', 'heart', 'calendar', 'plug', 'mobile', 'shield']) {
    assert.match(source, new RegExp(`case ['"]${icon}['"]:`), `${icon} must not use the question-mark fallback`);
  }
});

test('layout fails closed against the backend release capability catalog', () => {
  const source = readFileSync(new URL('../src/components/Layout.tsx', import.meta.url), 'utf8');
  assert.match(source, /extensionApi\.catalog\(\)/);
  assert.match(source, /feature\.supported/);
  assert.match(source, /isPathEnabled\(item\.path, enabledModules, supportedCapabilities\)/);
});
