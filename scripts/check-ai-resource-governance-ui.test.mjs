import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tenantAiPage = readFileSync('src/pages/p-ai_model_settings/index.tsx', 'utf8');
const platformPage = readFileSync('src/pages/p-platform-tenants/index.tsx', 'utf8');
const api = readFileSync('src/utils/api.ts', 'utf8');

test('tenant AI page does not expose provider models or real diagnostics', () => {
  assert.doesNotMatch(tenantAiPage, /DeepSeek V4|DeepSeek V3|SiliconFlow|硅基流动/);
  assert.doesNotMatch(tenantAiPage, /assistantModelCallTest|assistantModelStreamTest|assistantRunEvaluation/);
  assert.doesNotMatch(tenantAiPage, /保存 AI 设置|发起真实调用|运行全部用例/);
  assert.match(tenantAiPage, /aiEntitlements|aiUsage|selectAiTier/);
});

test('platform console owns AI resource management', () => {
  assert.match(platformPage, /AI 资源管理/);
  assert.match(platformPage, /platformAiApi/);
  assert.match(api, /platformAiApi/);
  assert.match(api, /aiEntitlements/);
  assert.match(api, /selectAiTier/);
});

test('AI resource reload clears a stale load error before retrying requests', () => {
  const effectStart = platformPage.indexOf("if (activeTab !== 'aiResources') return;");
  const requestStart = platformPage.indexOf('Promise.all([', effectStart);
  const successStart = platformPage.indexOf('.then(([providers, packages, entitlementPayload, usagePayload]) => {', requestStart);
  const failureStart = platformPage.indexOf('.catch(err =>', successStart);

  assert.notEqual(effectStart, -1, 'AI resource effect is missing');
  assert.notEqual(requestStart, -1, 'AI resource request batch is missing');
  assert.notEqual(successStart, -1, 'AI resource success branch is missing');
  assert.notEqual(failureStart, -1, 'AI resource failure branch is missing');
  assert.match(platformPage.slice(effectStart, requestStart), /setError\(''\);/);
  assert.match(platformPage.slice(successStart, failureStart), /setError\(''\);/);
});
