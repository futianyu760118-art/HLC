import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_KERNEL_MATRIX_TIMEOUT_MS || 90000);

const flagValue = (value) => {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return undefined;
  if (['1', 'true', 'yes', 'on'].includes(raw)) return true;
  if (['0', 'false', 'no', 'off'].includes(raw)) return false;
  return undefined;
};

const argValue = (name) => {
  const prefix = `--${name}=`;
  const hit = process.argv.find((item) => item.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : undefined;
};

const legacyFullFlag = flagValue(process.env.HRM_KERNEL_MATRIX_FULL);
const quickFlag = flagValue(process.env.HRM_KERNEL_MATRIX_QUICK);
const RUN_QUICK_MATRIX = process.argv.includes('--quick') || quickFlag === true || legacyFullFlag === false;
const RUN_FULL_MATRIX = !RUN_QUICK_MATRIX;
const REQUIRE_LLM_PARTICIPATION = String(process.env.HRM_KERNEL_MATRIX_REQUIRE_LLM || '').toLowerCase() === '1'
  || String(process.env.HRM_KERNEL_MATRIX_REQUIRE_LLM || '').toLowerCase() === 'true'
  || process.argv.includes('--require-llm');
const RESET_LLM_HEALTH = !process.argv.includes('--no-reset-llm-health')
  && (REQUIRE_LLM_PARTICIPATION || flagValue(process.env.HRM_KERNEL_MATRIX_RESET_LLM_HEALTH) === true);
const MIN_PLANNER_ACCEPTED_RATIO = Math.max(
  0,
  Number(
    argValue('min-planner-accepted-ratio')
    || process.env.HRM_KERNEL_MATRIX_MIN_PLANNER_ACCEPTED_RATIO
    || (REQUIRE_LLM_PARTICIPATION ? 0.6 : 0),
  ),
);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID || `kernel-nl-matrix-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

const DEFAULT_CONTEXT = {
  path: '/job-manage',
  moduleId: 'job-manage',
  moduleName: '岗位管理',
  pageTitle: '岗位管理 - 恒聘通',
};

const cases = [
  {
    id: 'page_capability',
    question: '在这个页面你能做什么',
    expectedSkills: ['system.page_capability'],
    expectedBlocks: ['markdown'],
    clientContext: DEFAULT_CONTEXT,
  },
  { id: 'recruitment_overview', question: '最近招聘咋样', expectedSkills: ['recruitment.overview'] },
  { id: 'open_jobs', question: '现在在招聘的岗位有哪些', expectedSkills: ['recruitment.open_jobs'], expectedBlocks: ['markdown'] },
  { id: 'job_progress', question: '电子工程师这个岗位进展到哪了', expectedSkills: ['recruitment.job_progress'] },
  { id: 'recruitment_funnel', question: '招聘漏斗现在卡在哪一段', expectedSkills: ['recruitment.funnel'] },
  {
    id: 'job_candidate_match',
    question: '电子工程师岗位最近候选人谁更合适？给对比矩阵',
    expectedSkills: ['recruitment.job_candidate_match'],
    expectedBlocks: ['markdown'],
  },
  {
    id: 'workset_second_candidate_followup',
    question: '第二个人风险和推进建议',
    expectedSkills: ['candidate.evaluation'],
    expectedBlocks: ['markdown'],
  },
  { id: 'candidate_search', question: '候选人里找一下孙悦', expectedSkills: ['candidate.search'] },
  { id: 'recent_resumes', question: '最近10天我们收到了哪些简历', expectedSkills: ['candidate.recent_resumes'] },
  { id: 'resume_analysis', question: '孙悦的简历帮我找一下', expectedSkills: ['candidate.resume_analysis'] },
  {
    id: 'interview_create_confirm',
    question: '帮我给孙悦安排一个明天早晨八点的面试',
    expectedSkills: ['interview.schedule_confirm_create'],
    expectedBlocks: ['confirmation'],
    requiresConfirmation: true,
  },
  { id: 'interview_records', question: '邓浩的面试记录查一下', expectedSkills: ['interview.records'] },
  { id: 'interview_draft', question: '先出一版面试邀请文案，不要直接创建', expectedSkills: ['interview.schedule_draft'] },
  { id: 'candidate_job_fit', question: '孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗', expectedSkills: ['candidate.job_fit'] },
  { id: 'offer_onboarding', question: 'Offer 和入职最近推进怎么样', expectedSkills: ['offer.onboarding_progress'] },
  { id: 'employee_search', question: '员工里找一下吴明华', expectedSkills: ['employee.search'] },
  { id: 'employee_profile', question: '吴明华这个员工最近状态如何', expectedSkills: ['employee.profile'] },
  { id: 'organization_overview', question: '公司组织现在什么情况', expectedSkills: ['organization.overview'] },
  { id: 'employee_lifecycle', question: '这个员工从入职到现在的生命周期链路看下', expectedSkills: ['employee.lifecycle_chain'] },
  { id: 'attrition_risk', question: '离职风险高的人有哪些', expectedSkills: ['employee.attrition_risk'] },
  { id: 'attendance_overview', question: '这个月考勤总体怎么样', expectedSkills: ['attendance.overview'] },
  { id: 'attendance_anomaly', question: '这个月谁打卡不太正常', expectedSkills: ['attendance.anomaly'] },
  { id: 'attendance_employee_evidence', question: '吴明华这个月考勤证据给我看下', expectedSkills: ['attendance.employee_evidence'] },
  { id: 'attendance_reminder_draft', question: '给迟到多的人写个提醒草稿', expectedSkills: ['attendance.reminder_draft'] },
  {
    id: 'attendance_reminder_confirm',
    question: '帮我给本月迟到最多的5个人生成提醒',
    expectedSkills: ['attendance.reminder_confirm'],
    expectedBlocks: ['confirmation'],
    requiresConfirmation: true,
  },
  { id: 'performance_distribution', question: '绩效分布怎么样', expectedSkills: ['performance.distribution'] },
  { id: 'performance_anomaly', question: '绩效哪里不正常', expectedSkills: ['performance.anomaly'] },
  { id: 'payroll_summary', question: '这个月工资总额多少', expectedSkills: ['payroll.summary'] },
  { id: 'payroll_anomaly', question: '钱这块有没有不对劲', expectedSkills: ['payroll.anomaly'] },
  { id: 'approval_todo', question: '我这边还有哪些待办审批', expectedSkills: ['approval.todo'] },
  { id: 'approval_mine', question: '我的申请现在走到哪了', expectedSkills: ['approval.mine'] },
  { id: 'approval_history', question: '之前处理过的审批给我看下', expectedSkills: ['approval.history'] },
  {
    id: 'approval_confirm',
    question: '同意第一条请假申请',
    expectedSkills: ['approval.confirm_action'],
    requiresConfirmation: true,
  },
  { id: 'feedback_summary', question: '用户最近主要在吐槽什么', expectedSkills: ['feedback.summary'] },
  { id: 'bug_todo', question: '还有什么系统 bug 没修', expectedSkills: ['feedback.bug_todo'] },
  {
    id: 'notification_confirm',
    question: '给全员推一条 HR 通知：明天下午三点全员培训',
    expectedSkills: ['notification.create_confirm'],
    expectedBlocks: ['confirmation'],
    requiresConfirmation: true,
  },
  { id: 'report_operations', question: '系统经营报表看一下', expectedSkills: ['report.operations'] },
  { id: 'smart_data_query', question: '低绩效和考勤异常交叉统计一下', expectedSkills: ['smart.data_query'] },
  {
    id: 'unsupported_interview_delete',
    question: '把邓浩的面试删除',
    expectedErrorCode: 'write_intent_blocked',
  },
  {
    id: 'unsupported_interview_update',
    question: '把邓浩的面试时间改成明天早晨9点',
    expectedErrorCode: 'write_intent_blocked',
  },
  {
    id: 'unsupported_employee_delete',
    question: '删除员工吴明华',
    expectedErrorCode: 'write_intent_blocked',
  },
];

const quickCaseIds = new Set([
  'page_capability',
  'open_jobs',
  'job_candidate_match',
  'workset_second_candidate_followup',
  'resume_analysis',
  'interview_create_confirm',
  'candidate_job_fit',
  'employee_profile',
  'attendance_anomaly',
  'performance_distribution',
  'payroll_anomaly',
  'approval_todo',
  'notification_confirm',
  'smart_data_query',
  'unsupported_interview_delete',
  'unsupported_interview_update',
]);

const fail = (message, details) => {
  const error = new Error(message);
  error.details = details;
  throw error;
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run Kernel matrix against old production ports', { baseUrl: BASE_URL });
  }
};

const asJson = async (response) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`Expected JSON from ${response.url}`, text.slice(0, 1000));
  }
};

const requestJson = async (path, payload, token, requestId, method = 'POST') => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    let response;
    try {
      response = await fetch(`${BASE_URL}${path}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(requestId ? { 'X-Request-ID': requestId } : {}),
        },
        body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
        signal: controller.signal,
      });
    } catch (error) {
      if (error?.name === 'AbortError') {
        fail(`${method} ${path} exceeded ${REQUEST_TIMEOUT_MS}ms`, { requestId, timeoutMs: REQUEST_TIMEOUT_MS });
      }
      throw error;
    }
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

const fallbackReason = (payload) => {
  const trace = payload?.copilot?.routeTrace || {};
  return trace.fallback_reason || trace.fallbackReason || payload?.meta?.routeDecision?.fallbackPolicy || '';
};

const errorCode = (payload) => payload?.meta?.errorCode || payload?.errorCode || payload?.copilot?.errorCode || '';

const plannerSource = (payload) => {
  const trace = payload?.copilot?.routeTrace || {};
  return trace.planner_source || trace.plannerSource || '';
};

const kernelNodes = (payload) => {
  const nodes = payload?.copilot?.routeTrace?.kernel?.nodes || payload?.copilot?.routeTrace?.kernel_nodes || [];
  return Array.isArray(nodes) ? nodes.map((item) => item?.node).filter(Boolean) : [];
};

const routeTrace = (payload) => payload?.copilot?.routeTrace || {};

const nodeDetail = (payload, name) => {
  const nodes = routeTrace(payload)?.kernel?.nodes || routeTrace(payload)?.kernel_nodes || [];
  if (!Array.isArray(nodes)) return {};
  return nodes.find((item) => item?.node === name)?.detail || {};
};

const understandingDiagnostics = (payload) => (
  routeTrace(payload).understanding_diagnostics
  || routeTrace(payload).understandingDiagnostics
  || nodeDetail(payload, 'understanding')
  || {}
);

const plannerDiagnostics = (payload) => (
  routeTrace(payload).planner_diagnostics
  || routeTrace(payload).plannerDiagnostics
  || nodeDetail(payload, 'planning')
  || {}
);

const llmParticipation = (payload) => {
  const understanding = understandingDiagnostics(payload);
  const planner = plannerDiagnostics(payload);
  return {
    understandingAttempted: Boolean(understanding.attempted ?? understanding.llm_attempted),
    understandingAccepted: Boolean(understanding.accepted ?? understanding.llm_accepted),
    understandingStatus: String(understanding.status || understanding.llm_status || ''),
    plannerAttempted: Boolean(planner.attempted ?? planner.llm_attempted),
    plannerAccepted: Boolean(planner.accepted ?? planner.llm_accepted),
    plannerStatus: String(planner.status || planner.llm_status || ''),
    plannerAvailability: String(planner.availability || ''),
    plannerHealthState: String(planner?.llm_health?.state || ''),
    plannerHealthUseCase: String(planner?.llm_health?.use_case || ''),
  };
};

const runCase = async (token, sessionId, item, index) => {
  const requestId = `${suiteId}-case-${index}`;
  let payload;
  try {
    payload = await requestJson('/api/hrm/assistant/query', {
      question: item.question,
      sessionId,
      clientContext: item.clientContext || DEFAULT_CONTEXT,
    }, token, requestId);
  } catch (error) {
    return {
      id: item.id,
      ok: false,
      missing: ['request_failed'],
      question: item.question,
      selectedSkill: '',
      expectedSkills: item.expectedSkills || [],
      errorCode: error?.name === 'AbortError' ? 'request_timeout' : 'request_failed',
      expectedErrorCode: item.expectedErrorCode || '',
      renderBlocks: [],
      requiresConfirmation: false,
      routePath: '',
      plannerSource: '',
      fallbackReason: '',
      llmParticipation: {},
      topK: [],
      kernelNodes: [],
      summary: String(error?.message || error).slice(0, 220),
      errorDetails: error?.details || null,
      requestId,
    };
  }
  const kinds = blockKinds(payload);
  const skill = selectedSkill(payload);
  const err = errorCode(payload);
  const missing = [];
  const participation = llmParticipation(payload);
  if (item.expectedErrorCode) {
    if (err !== item.expectedErrorCode) missing.push(`errorCode:${item.expectedErrorCode}`);
    if (payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation:false');
  } else {
    if (!(item.expectedSkills || []).includes(skill)) missing.push(`skill:${(item.expectedSkills || []).join('|')}`);
    if (skill === 'skill_first_clarification' || fallbackReason(payload) === 'llm_planner_unusable') {
      missing.push('no_skill_first_clarification');
    }
  }
  for (const kind of item.expectedBlocks || []) {
    if (!kinds.includes(kind)) missing.push(`block:${kind}`);
  }
  if (item.requiresConfirmation && !payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation');
  const nodes = kernelNodes(payload);
  if (!item.expectedErrorCode && !nodes.includes('planning')) missing.push('kernel:planning');
  if (REQUIRE_LLM_PARTICIPATION && !item.expectedErrorCode) {
    if (!participation.plannerAttempted) missing.push('llm:planner_attempted');
    if (participation.plannerStatus === 'llm_health_circuit_open') missing.push('llm:planner_circuit_open');
  }
  return {
    id: item.id,
    ok: missing.length === 0,
    missing,
    question: item.question,
    selectedSkill: skill,
    expectedSkills: item.expectedSkills || [],
    errorCode: err,
    expectedErrorCode: item.expectedErrorCode || '',
    renderBlocks: kinds,
    requiresConfirmation: Boolean(payload?.meta?.requiresConfirmation),
    routePath: payload?.copilot?.routePath,
    plannerSource: plannerSource(payload),
    fallbackReason: fallbackReason(payload),
    llmParticipation: participation,
    topK: (payload?.copilot?.routeTrace?.top_k_skills || []).slice(0, 8),
    kernelNodes: nodes,
    summary: String(payload.summary || '').slice(0, 220),
  };
};

const main = async () => {
  assertIsolatedBaseUrl();
  console.log(`Running Agent Kernel natural-language matrix against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  const selectedCases = RUN_FULL_MATRIX ? cases : cases.filter((item) => quickCaseIds.has(item.id));
  console.log(`Mode: ${RUN_FULL_MATRIX ? 'full' : 'quick'} (${selectedCases.length}/${cases.length} cases)`);
  console.log(`Require LLM participation: ${REQUIRE_LLM_PARTICIPATION ? 'yes' : 'no'}`);
  const health = await requestJson('/api/health', null, null, `${suiteId}-health`, 'GET');
  const ready = await requestJson('/api/ready', null, null, `${suiteId}-ready`, 'GET');
  if (health.ok !== true) fail('/api/health did not return ok=true', health);
  if (ready.ok !== true || ready.db !== 'up') fail('/api/ready did not return ok=true, db=up', ready);

  const token = await login();
  let resetLlmHealth = null;
  if (RESET_LLM_HEALTH) {
    console.log('Resetting Skill-first LLM health state before matrix');
    resetLlmHealth = await requestJson(
      '/api/hrm/assistant/skill-first/llm-health',
      {},
      token,
      `${suiteId}-reset-llm-health`,
    );
    if (resetLlmHealth?.ok !== true) fail('Skill-first LLM health reset did not return ok=true', resetLlmHealth);
  }
  const sessionId = `${suiteId}-session`;
  const results = [];
  for (const [index, item] of selectedCases.entries()) {
    console.log(`[${index + 1}/${selectedCases.length}] ${item.id}: ${item.question}`);
    const result = await runCase(token, sessionId, item, index + 1);
    const llm = result.llmParticipation || {};
    console.log(
      `  -> ${result.ok ? 'ok' : 'fail'} selected=${result.selectedSkill || '-'} error=${result.errorCode || '-'} `
      + `planner=${result.plannerSource || '-'} `
      + `llm(u:${llm.understandingAttempted ? 'try' : 'skip'}/${llm.understandingStatus || '-'}, `
      + `p:${llm.plannerAttempted ? 'try' : 'skip'}/${llm.plannerStatus || '-'})`,
    );
    results.push(result);
  }
  const failed = results.filter((item) => !item.ok);
  const nonErrorResults = results.filter((item) => !item.expectedErrorCode);
  const plannerAcceptedCount = nonErrorResults.filter((item) => item.llmParticipation?.plannerAccepted).length;
  const plannerAcceptedRatio = nonErrorResults.length ? plannerAcceptedCount / nonErrorResults.length : 0;
  const llmStats = {
    requirePlannerAttempt: REQUIRE_LLM_PARTICIPATION,
    minPlannerAcceptedRatio: MIN_PLANNER_ACCEPTED_RATIO,
    nonErrorCaseCount: nonErrorResults.length,
    plannerAttemptedCount: nonErrorResults.filter((item) => item.llmParticipation?.plannerAttempted).length,
    plannerAcceptedCount,
    plannerAcceptedRatio: Number(plannerAcceptedRatio.toFixed(4)),
    plannerTimeoutCount: nonErrorResults.filter((item) => item.llmParticipation?.plannerStatus === 'llm_timeout').length,
    plannerCircuitOpenCount: nonErrorResults.filter((item) => item.llmParticipation?.plannerStatus === 'llm_health_circuit_open').length,
    understandingAttemptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAttempted).length,
    understandingAcceptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAccepted).length,
  };
  const acceptanceFailures = [];
  if (MIN_PLANNER_ACCEPTED_RATIO > 0 && plannerAcceptedRatio < MIN_PLANNER_ACCEPTED_RATIO) {
    acceptanceFailures.push(
      `llm:planner_accepted_ratio ${plannerAcceptedRatio.toFixed(4)} < ${MIN_PLANNER_ACCEPTED_RATIO}`,
    );
  }
  const report = {
    ok: failed.length === 0 && acceptanceFailures.length === 0,
    suiteId,
    baseUrl: BASE_URL,
    mode: 'agent_kernel_natural_language_matrix',
    matrixMode: RUN_FULL_MATRIX ? 'full' : 'quick',
    caseCount: selectedCases.length,
    totalAvailableCaseCount: cases.length,
    passCount: results.length - failed.length,
    failCount: failed.length + acceptanceFailures.length,
    acceptanceFailures,
    llmStats,
    resetLlmHealth,
    results,
  };
  await mkdir('artifacts/browser-verification', { recursive: true });
  const reportPath = join('artifacts/browser-verification', `assistant-kernel-natural-language-matrix-${stamp}-${suiteId}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify({ ...report, reportPath }, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  if (error?.details) console.error(JSON.stringify(error.details, null, 2));
  process.exit(1);
});
