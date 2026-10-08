import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_EVALUATION_REQUEST_TIMEOUT_MS || 180000);
const DEFAULT_CASES = [
  'colloquial_candidate_reliability_followup',
  'colloquial_employee_late_severity',
  'colloquial_workset_second_candidate_reliability',
  'colloquial_workset_who_to_interview_first',
  'colloquial_payroll_exception_summary',
  'agent_kernel_mainline_page_capability',
  'agent_kernel_mainline_open_jobs',
  'agent_kernel_mainline_recent_resumes',
  'agent_kernel_mainline_candidate_job_fit',
  'agent_kernel_mainline_interview_confirm_named_candidate',
  'agent_kernel_mainline_employee_profile',
  'agent_kernel_mainline_attendance_anomaly',
  'agent_kernel_mainline_performance_anomaly',
  'agent_kernel_mainline_approval_todo',
  'agent_kernel_mainline_feedback_bug_todo',
  'agent_kernel_mainline_notification_create_confirm',
  'agent_kernel_mainline_workset_second_followup',
  'agent_kernel_mainline_smart_readonly_query',
];
const CASE_IDS = (process.env.HRM_COLLOQUIAL_CASE_IDS || process.env.HRM_EVAL_CASE_IDS || '')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);
const EVAL_CASES = CASE_IDS.length ? CASE_IDS : DEFAULT_CASES;
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID || `colloquial-real-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

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

const postJson = async (path, payload, token, requestId) => {
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
    return response;
  } finally {
    clearTimeout(timer);
  }
};

const login = async () => {
  const payload = await asJson(await postJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, null, `${suiteId}-login`));
  if (!payload.token) fail('Login succeeded but no token was returned');
  return payload.token;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const fetchAuditRows = async (token, keyword, limit = 20) => {
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    const response = await fetch(`${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(keyword)}&limit=${limit}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Request-ID': `${suiteId}-audit-${attempt}`,
      },
    });
    if (!response.ok) {
      const text = await response.text();
      fail(`audit-logs failed with HTTP ${response.status}`, text.slice(0, 800));
    }
    const rows = await asJson(response);
    if (rows.length) return rows;
    await sleep(900);
  }
  return [];
};

const runEvaluationCase = async (token, caseId, index) => {
  try {
    const payload = await asJson(await postJson('/api/hrm/assistant/evaluation-runs', {
      caseId,
      clientContext: {
        path: '/ai-model-settings',
        moduleName: 'AI 模型管理',
        smokeTest: 'colloquial_real_evaluation',
        suiteId,
        suiteIndex: index,
      },
    }, token, `${suiteId}-case-${index}`));
    const audit = payload.evaluationAudit || {};
    const rows = await fetchAuditRows(token, payload.requestId || caseId);
    const auditRow = rows.find((item) => item.requestId === payload.requestId && item.useCase === 'copilot_evaluation');
    const ok = payload.passStatus === 'pass'
      && audit.provider === 'siliconflow'
      && audit.useCase === 'copilot_evaluation'
      && audit.status === 'success'
      && audit.ok === true
      && Boolean(audit.auditLogId)
      && auditRow?.provider === 'siliconflow'
      && auditRow?.status === 'success';
    return {
      caseId,
      ok,
      passStatus: payload.passStatus,
      requestId: payload.requestId,
      actualModules: payload.actualModules || [],
      actualRenderBlocks: payload.actualRenderBlocks || [],
      missingExpectations: payload.missingExpectations || [],
      failureCategories: payload.failureCategories || [],
      evaluationAudit: audit,
      auditRow: auditRow ? {
        id: auditRow.id,
        provider: auditRow.provider,
        useCase: auditRow.useCase,
        status: auditRow.status,
        model: auditRow.model,
        latencyMs: auditRow.latencyMs,
        errorMessage: auditRow.errorMessage,
      } : null,
    };
  } catch (error) {
    return {
      caseId,
      ok: false,
      error: error?.stack || error?.message || String(error),
      details: error?.details,
    };
  }
};

const main = async () => {
  console.log(`Running colloquial real evaluation against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  console.log(`Evaluation cases: ${EVAL_CASES.join(', ')}`);
  const token = await login();
  const results = [];
  for (const [index, caseId] of EVAL_CASES.entries()) {
    results.push(await runEvaluationCase(token, caseId, index + 1));
  }
  const report = {
    ok: results.every((item) => item.ok),
    suiteId,
    baseUrl: BASE_URL,
    cases: EVAL_CASES,
    modelAuditRequirement: 'Each passing case must have provider=siliconflow/useCase=copilot_evaluation/status=success.',
    diagnostics: {
      modelCallTest: 'skipped_for_cost',
      modelStreamTest: 'skipped_for_cost',
    },
    results,
    auditLookup: `${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(suiteId)}&limit=50`,
    evaluationPage: `${BASE_URL}/ai-model-settings`,
  };
  await mkdir('artifacts/browser-verification', { recursive: true });
  const reportPath = join('artifacts/browser-verification', `assistant-colloquial-real-evaluation-${stamp}-${suiteId}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify({ ...report, reportPath }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  if (error?.details) console.error(JSON.stringify(error.details, null, 2));
  process.exit(1);
});
