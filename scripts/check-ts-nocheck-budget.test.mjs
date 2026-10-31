import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { findTsNoCheckFiles } from './check-ts-nocheck-budget.mjs';

test('findTsNoCheckFiles returns files containing @ts-nocheck', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'hrm-ts-nocheck-'));
  mkdirSync(path.join(root, 'src'), { recursive: true });
  mkdirSync(path.join(root, 'scripts'), { recursive: true });
  writeFileSync(path.join(root, 'src', 'a.tsx'), '// @ts-nocheck\nexport const a = 1;\n');
  writeFileSync(path.join(root, 'src', 'b.tsx'), 'export const b = 2;\n');
  writeFileSync(path.join(root, 'scripts', 'c.mjs'), '// @ts-nocheck\n');

  assert.deepEqual(findTsNoCheckFiles(root), ['scripts/c.mjs', 'src/a.tsx']);
});

test('findTsNoCheckFiles ignores non-directive text mentions', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'hrm-ts-nocheck-text-'));
  mkdirSync(path.join(root, 'src'), { recursive: true });
  writeFileSync(path.join(root, 'src', 'a.ts'), 'const message = "do not count @ts-nocheck inside strings";\n');

  assert.deepEqual(findTsNoCheckFiles(root), []);
});
