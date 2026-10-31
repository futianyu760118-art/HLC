import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ENTRY_RE = /\{\s*path:\s*['"]([^'"]+)['"][\s\S]*?label:\s*['"]([^'"]+)['"][\s\S]*?icon:\s*['"]([^'"]+)['"][\s\S]*?group:\s*['"]([^'"]+)['"][\s\S]*?\}/g;

export const supportedNavigationIcons = new Set([
  'users', 'chart-line', 'comments', 'radar', 'chart-bar', 'brain', 'heart',
  'calendar', 'plug', 'mobile', 'shield',
]);

export function evaluateCapabilityNavigation({ catalogSource, layoutSource, pageSources = [], supportedIcons }) {
  const groupForPath = {};
  const packageLabelFindings = [];
  const unsupportedIcons = [];
  for (const match of catalogSource.matchAll(ENTRY_RE)) {
    const [, path, label, icon, group] = match;
    groupForPath[path] = group;
    if (label.endsWith('包')) packageLabelFindings.push(label);
    if (!supportedIcons.has(icon)) unsupportedIcons.push(icon);
  }
  return {
    hasExtensionGroup: /title:\s*['"]扩展功能['"]/.test(layoutSource)
      || Object.values(groupForPath).includes('扩展功能'),
    groupForPath,
    packageLabelFindings: [...new Set(packageLabelFindings)].sort(),
    customerCopyFindings: pageSources.flatMap((source) => (
      [...source.matchAll(/(?:document\.title\s*=\s*['"]|<h1[^>]*>)([^<'"]*包)(?:\s*-\s*恒聘通)?/g)].map((match) => match[1].trim())
    )),
    unsupportedIcons: [...new Set(unsupportedIcons)].sort(),
  };
}

function main() {
  const root = dirname(dirname(fileURLToPath(import.meta.url)));
  const catalogSource = readFileSync(join(root, 'src/config/capabilityNavigation.ts'), 'utf8');
  const layoutSource = readFileSync(join(root, 'src/components/Layout.tsx'), 'utf8');
  const pageSources = [
    'p-analytics-extension', 'p-intelligence-extension', 'p-collaboration-extension',
    'p-integration-extension', 'p-mobile-extension', 'p-talent-strategy-extension',
    'p-security-extension', 'p-workforce-extension',
  ].map((directory) => readFileSync(join(root, 'src/pages', directory, 'index.tsx'), 'utf8'));
  const result = evaluateCapabilityNavigation({
    catalogSource,
    layoutSource,
    pageSources,
    supportedIcons: supportedNavigationIcons,
  });
  const findings = [];
  if (result.hasExtensionGroup) findings.push('business sidebar still contains 扩展功能');
  for (const label of result.packageLabelFindings) findings.push(`package label remains: ${label}`);
  for (const label of result.customerCopyFindings) findings.push(`customer-facing package label remains: ${label}`);
  for (const icon of result.unsupportedIcons) findings.push(`unsupported navigation icon: ${icon}`);
  if (findings.length) {
    console.error(findings.join('\n'));
    process.exitCode = 1;
    return;
  }
  console.log('Capability navigation: OK');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
