import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const layout = readFileSync(new URL('../src/components/Layout.tsx', import.meta.url), 'utf8');

test('management header omits the decorative brand logo', () => {
  assert.doesNotMatch(layout, /import BrandLogo from ['"]\.\/BrandLogo['"]/);
  assert.doesNotMatch(layout, /<BrandLogo\b/);
  assert.match(layout, /aria-label=\{collapsed \? '展开菜单' : '收起菜单'\}/);
});
