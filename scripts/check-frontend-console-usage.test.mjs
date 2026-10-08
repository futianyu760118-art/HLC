import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { findDisallowedConsoleUsage } from './check-frontend-console-usage.mjs';

test('findDisallowedConsoleUsage rejects page-level console calls but allows ErrorBoundary', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'hrm-console-'));
  mkdirSync(path.join(root, 'src', 'pages', 'p-demo'), { recursive: true });
  mkdirSync(path.join(root, 'src', 'components'), { recursive: true });
  writeFileSync(path.join(root, 'src', 'pages', 'p-demo', 'index.tsx'), 'console.log("debug");\n');
  writeFileSync(path.join(root, 'src', 'components', 'ErrorBoundary.tsx'), 'console.error("reported");\n');

  assert.deepEqual(findDisallowedConsoleUsage(root), ['src/pages/p-demo/index.tsx:1']);
});
