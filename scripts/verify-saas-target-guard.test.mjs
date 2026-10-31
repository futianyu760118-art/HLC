import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const guardedFiles = [
  '.env.example',
  'docker-compose.yml',
  'init-readonly-user.sh',
  'init.sql',
];

test('SaaS target guard rejects old local-stack database defaults', () => {
  const findings = [];
  for (const file of guardedFiles) {
    const text = readFileSync(file, 'utf8');
    if (text.includes('hengpintong_next')) {
      findings.push(file);
    }
  }

  assert.deepEqual(findings, []);
});

test('SaaS target guard rejects stale frontend source HTTPS targets', () => {
  const tempRoot = mkdtempSync(join(tmpdir(), 'saas-target-guard-'));
  mkdirSync(join(tempRoot, 'scripts'), { recursive: true });
  mkdirSync(join(tempRoot, 'src', 'components'), { recursive: true });

  writeFileSync(
    join(tempRoot, 'scripts', 'verify-saas-target-guard.mjs'),
    readFileSync(join('scripts', 'verify-saas-target-guard.mjs'), 'utf8'),
    'utf8',
  );
  writeFileSync(
    join(tempRoot, 'src', 'components', 'AIAssistant.tsx'),
    `export const voicePrompt = '${['https://localhost:', '18443'].join('')}';\n`,
    'utf8',
  );

  const result = spawnSync(
    process.execPath,
    [join(tempRoot, 'scripts', 'verify-saas-target-guard.mjs')],
    { cwd: tempRoot, encoding: 'utf8' },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /src[/\\]components[/\\]AIAssistant\.tsx/);
  assert.match(result.stderr, new RegExp(['localhost:', '18443'].join('')));
});
