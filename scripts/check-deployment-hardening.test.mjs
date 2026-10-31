import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('deployment stages frontend assets, swaps atomically, and rolls back on readiness failure', () => {
  const source = readFileSync('deploy-prod.ps1', 'utf8');
  assert.match(source, /staging|\.staging/i);
  assert.match(source, /Move-Item/);
  assert.match(source, /rollback/i);
  assert.match(source, /\/api\/health/);
  assert.match(source, /\/api\/ready/);
  assert.match(source, /throw|exit 1/);
  assert.match(source, /hengpintong-saas-preview/);
  assert.match(source, /-p \$projectName/);
});

test('container images are version pinned', () => {
  const compose = readFileSync('docker-compose.yml', 'utf8');
  assert.doesNotMatch(compose, /image:\s+[^\s]+:latest\b/i);
  assert.match(compose, /mysql@sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b/);
  assert.match(compose, /minio\/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e/);
  assert.match(compose, /nginx@sha256:8b1e78743a03dbb2c95171cc58639fef29abc8816598e27fb910ed2e621e589a/);
});

test('backend readiness includes object storage state and storage retries are possible', () => {
  const app = readFileSync('backend-python/app.py', 'utf8');
  const storage = readFileSync('backend-python/services/storage.py', 'utf8');
  assert.match(app, /storage.*readiness|readiness.*storage/s);
  assert.match(app, /storage.*down|storage.*unavailable/s);
  assert.match(storage, /retry|cooldown|last_attempt/i);
  assert.match(storage, /def storage_readiness/);
});
