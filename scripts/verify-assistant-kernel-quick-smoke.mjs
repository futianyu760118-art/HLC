import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_QUICK_SMOKE_TIMEOUT_MS || 90000);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID || `kernel-quick-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

const cases = [
  {
    id: 'page_capability',
    question: '在这个页面你能做什么',
    expectedSkill: 'system.page_capability',
    expectedBlocks: ['markdown', 'sources'],
    clientContext: {
      path: '/job-manage',
      moduleId: 'job-manage',
      moduleName: '岗位管理',
      pageTitle: '岗位管理 - 恒聘通',
    },
  },
  {
    id: 'open_jobs',
    question: '现在在招聘的岗位有哪些',
    expectedSkill: 'recruitment.open_jobs',
    expectedBlocks: ['markdown', 'entity_cards', 'sources'],
  },
  {
    id: 'candidate_job_match',
    question: '电子工程师岗位最近候选人谁更合适？给对比矩阵',
    expectedSkill: 'recruitment.job_candidate_match',
    expectedBlocks: ['markdown', 'matrix', 'workset', 'sources'],
  },
  {
    id: 'second_candidate_evaluation',
    question: '第二个人风险和推进建议',
    expectedSkill: 'candidate.evaluation',
    expectedBlocks: ['markdown', 'sources'],
  },
  {
    id: 'notification_confirm',
    question: '给全员推一条 HR 通知：明天下午三点全员培训',
    expectedSkill: 'notification.create_confirm',
    expectedBlocks: ['markdown', 'confirmation', 'sources'],
    requiresConfirmation: true,
  },
];

const fail = (message, details) => {
  const error = new Error(message);
  error.details = details;
  throw error;
};

const asJson = async (response) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`Expected JSON from ${response.url}`, text.slice(0, 1000));
  }
};

const requestJson = async (path, payload, token, requestId) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(requestId ? { 'X-Request-ID': requestId } : {}),
      },
      body: JSON.stringify(payload || {}),
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      fail(`${path} failed with HTTP ${response.status}`, text.slice(0, 1200));
    }
    return asJson(response);
  } finally {
    clearTimeout(timer);
  }
};

const login = async () => {
  const payload = await requestJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, null, `${suiteId}-login`);
  if (!payload.token) fail('Login succeeded but no token was returned');
  return payload.token;
};

const blockKinds = (payload) => (payload.renderBlocks || [])
  .filter((item) => item && typeof item === 'object')
  .map((item) => String(item.kind || ''));

const selectedSkill = (payload) => {
  const trace = payload?.copilot?.routeTrace || {};
  return trace.selected_skill || trace.selectedSkill || payload?.meta?.routeDecision?.intent || '';
};

const runCase = async (token, sessionId, item, index) => {
  const payload = await requestJson('/api/hrm/assistant/query', {
    question: item.question,
    sessionId,
    clientContext: item.clientContext || {
      path: '/job-manage',
      moduleId: 'job-manage',
      moduleName: '岗位管理',
      pageTitle: '岗位管理 - 恒聘通',
    },
  }, token, `${suiteId}-case-${index}`);
  const kinds = blockKinds(payload);
  const skill = selectedSkill(payload);
  const evidence = Array.isArray(payload?.copilot?.evidence) ? payload.copilot.evidence : [];
  const missing = [];
  if (skill !== item.expectedSkill) missing.push(`skill:${item.expectedSkill}`);
  for (const kind of item.expectedBlocks || []) {
    if (!kinds.includes(kind)) missing.push(`block:${kind}`);
  }
  if (item.requiresConfirmation && !payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation');
  if ((item.expectedBlocks || []).includes('sources') && evidence.length === 0) missing.push('evidence');
  return {
    id: item.id,
    ok: missing.length === 0,
    missing,
    selectedSkill: skill,
    expectedSkill: item.expectedSkill,
    renderBlocks: kinds,
    evidenceCount: evidence.length,
    requiresConfirmation: Boolean(payload?.meta?.requiresConfirmation),
    routePath: payload?.copilot?.routePath,
    plannerSource: payload?.copilot?.routeTrace?.planner_source || payload?.copilot?.routeTrace?.plannerSource,
    summary: String(payload.summary || '').slice(0, 240),
  };
};

const main = async () => {
  console.log(`Running Agent Kernel quick smoke against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  const token = await login();
  const sessionId = `${suiteId}-session`;
  const results = [];
  for (const [index, item] of cases.entries()) {
    results.push(await runCase(token, sessionId, item, index + 1));
  }
  const report = {
    ok: results.every((item) => item.ok),
    suiteId,
    baseUrl: BASE_URL,
    mode: 'direct_assistant_query_no_model_audit',
    results,
  };
  await mkdir('artifacts/browser-verification', { recursive: true });
  const reportPath = join('artifacts/browser-verification', `assistant-kernel-quick-smoke-${stamp}-${suiteId}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify({ ...report, reportPath }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  if (error?.details) console.error(JSON.stringify(error.details, null, 2));
  process.exit(1);
});
