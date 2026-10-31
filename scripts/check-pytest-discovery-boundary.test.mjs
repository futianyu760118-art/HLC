import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

test('default pytest discovery excludes service-dependent manual checks', () => {
  assert.equal(existsSync('pytest.ini'), true);
  const config = readFileSync('pytest.ini', 'utf8');

  assert.match(config, /testpaths\s*=\s*\r?\n\s*backend-python\/tests/);
  assert.match(config, /norecursedirs\s*=\s*\r?\n\s*manual_checks/);
});
