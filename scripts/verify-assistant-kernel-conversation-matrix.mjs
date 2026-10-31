#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_KERNEL_CONVERSATION_TIMEOUT_MS || 90000);

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

const RUN_QUICK_MATRIX = process.argv.includes('--quick')
  || flagValue(process.env.HRM_KERNEL_CONVERSATION_QUICK) === true;
const REQUIRE_LLM_PARTICIPATION = process.argv.includes('--require-llm')
  || flagValue(process.env.HRM_KERNEL_CONVERSATION_REQUIRE_LLM) === true;
const RESET_LLM_HEALTH = !process.argv.includes('--no-reset-llm-health')
  && (REQUIRE_LLM_PARTICIPATION || flagValue(process.env.HRM_KERNEL_CONVERSATION_RESET_LLM_HEALTH) === true);
const MIN_PLANNER_ACCEPTED_RATIO = Math.max(
  0,
  Number(
    argValue('min-planner-accepted-ratio')
    || process.env.HRM_KERNEL_CONVERSATION_MIN_PLANNER_ACCEPTED_RATIO
    || (REQUIRE_LLM_PARTICIPATION ? 0.55 : 0),
  ),
);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID
  || `kernel-conversation-matrix-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

const ctx = (pathName, moduleId, moduleName, pageTitle = `${moduleName} - 恒聘通`) => ({
  path: pathName,
  moduleId,
  moduleName,
  pageTitle,
});

const CONTEXTS = {
  jobs: ctx('/job-manage', 'job-manage', '岗位管理'),
  resumes: ctx('/hrm/resumes', 'resumes', '简历管理'),
  candidates: ctx('/hrm/candidates', 'candidates', '候选人管理'),
  interviews: ctx('/hrm/interviews', 'interviews', '面试管理'),
  offers: ctx('/hrm/offers', 'offers', 'Offer管理'),
  employees: ctx('/hrm/users', 'users', '员工档案'),
  org: ctx('/hrm/departments', 'departments', '部门管理'),
  attendance: ctx('/hrm/attendance', 'attendance', '考勤记录'),
  performance: ctx('/hrm/performance', 'performance', '绩效评估'),
  payroll: ctx('/hrm/payroll', 'payroll', '薪酬管理'),
  approvals: ctx('/hrm/approvals', 'approvals', '审批中心'),
  feedback: ctx('/hrm/feedback', 'feedback', '反馈管理'),
  notifications: ctx('/hrm/notifications', 'notifications', '通知中心'),
  reports: ctx('/dashboard', 'dashboard', '数据驾驶舱'),
};

const turn = (id, module, question, expectedSkills, extra = {}) => ({
  id,
  module,
  question,
  expectedSkills: Array.isArray(expectedSkills) ? expectedSkills : [expectedSkills],
  clientContext: CONTEXTS[module] || CONTEXTS.reports,
  ...extra,
});

const blockTurn = (id, module, question, extra = {}) => ({
  id,
  module,
  question,
  expectedErrorCode: 'write_intent_blocked',
  clientContext: CONTEXTS[module] || CONTEXTS.reports,
  ...extra,
});

const flows = [
  {
    id: 'recruitment_workset_to_interview',
    requiredModules: ['jobs', 'candidates', 'interviews'],
    turns: [
      turn('job_match_matrix', 'jobs', '电子工程师岗位最近候选人谁更合适？给对比矩阵', 'recruitment.job_candidate_match'),
      turn('second_candidate_eval', 'candidates', '第二个人风险和推进建议', 'candidate.evaluation', {
        requiresPriorTurn: 'job_match_matrix',
      }),
      turn('second_candidate_interview_confirm', 'interviews', '给他安排明天早晨八点面试', 'interview.schedule_confirm_create', {
        expectedBlocks: ['confirmation'],
        requiresConfirmation: true,
        requiresPriorTurn: 'second_candidate_eval',
      }),
      blockTurn('interview_update_block', 'interviews', '把邓浩的面试时间改成明天早晨9点'),
    ],
  },
  {
    id: 'resume_candidate_offer_followup',
    requiredModules: ['resumes', 'candidates', 'offers'],
    turns: [
      turn('resume_lookup', 'resumes', '孙悦的简历帮我找一下', 'candidate.resume_analysis'),
      turn('candidate_job_fit_followup', 'candidates', '这个人符合产品经理岗位要求吗', 'candidate.job_fit', {
        requiresPriorTurn: 'resume_lookup',
      }),
      turn('offer_onboarding_progress', 'offers', 'Offer 和入职最近推进怎么样', 'offer.onboarding_progress'),
      blockTurn('offer_update_block', 'offers', '把孙悦 Offer 薪资改成 20000'),
    ],
  },
  {
    id: 'employee_org_change_followup',
    requiredModules: ['employees', 'org'],
    turns: [
      turn('employee_lookup', 'employees', '员工里找一下吴明华', 'employee.search'),
      turn('employee_profile_followup', 'employees', '这个人最近状态如何', 'employee.profile', {
        requiresPriorTurn: 'employee_lookup',
      }),
      turn('employee_lifecycle_followup', 'employees', '这个人从入职到现在的生命周期链路看下', 'employee.lifecycle_chain', {
        requiresPriorTurn: 'employee_profile_followup',
      }),
      turn('org_change_impact', 'org', '如果把他调到研发部会影响什么', 'employee.change_impact', {
        requiresPriorTurn: 'employee_lifecycle_followup',
        summaryIncludes: ['吴明华', '研发部'],
        summaryExcludes: ['如果把他', '未找到员工'],
      }),
      turn('employee_change_confirm', 'employees', '那就准备提交这个调岗审批', 'employee.change_submit_confirm', {
        expectedBlocks: ['confirmation'],
        requiresConfirmation: true,
        requiresPriorTurn: 'org_change_impact',
        summaryIncludes: ['吴明华', '研发部'],
      }),
      blockTurn('employee_delete_block', 'employees', '删除员工吴明华'),
    ],
  },
  {
    id: 'attendance_performance_payroll_chain',
    requiredModules: ['attendance', 'performance', 'payroll'],
    turns: [
      turn('attendance_anomaly', 'attendance', '这个月谁打卡不太正常', 'attendance.anomaly'),
      turn('attendance_first_person_evidence', 'attendance', '第一个人的考勤证据展开看', 'attendance.employee_evidence', {
        requiresPriorTurn: 'attendance_anomaly',
      }),
      turn('performance_employee_link', 'performance', '低绩效员工画像看看', 'performance.employee_link'),
      turn('payroll_anomaly', 'payroll', '钱这块有没有不对劲', 'payroll.anomaly'),
      turn('payroll_adjust_confirm', 'payroll', '给吴明华调薪 1800 元，先分析影响并准备确认', 'employee.salary_adjustment_submit_confirm', {
        expectedBlocks: ['confirmation'],
        requiresConfirmation: true,
      }),
      blockTurn('payroll_delete_block', 'payroll', '删除工资条'),
    ],
  },
  {
    id: 'approval_notification_feedback_report_chain',
    requiredModules: ['approvals', 'feedback', 'notifications', 'reports'],
    turns: [
      turn('approval_todo', 'approvals', '我这边还有哪些待办审批', 'approval.todo'),
      turn('approval_confirm_first_leave', 'approvals', '同意第一条请假申请', 'approval.confirm_action', {
        expectedBlocks: ['confirmation'],
        requiresConfirmation: true,
        requiresPriorTurn: 'approval_todo',
      }),
      blockTurn('approval_bulk_block', 'approvals', '把所有审批都通过'),
      turn('feedback_summary', 'feedback', '用户最近主要在吐槽什么', 'feedback.summary'),
      turn('feedback_bug_todo', 'feedback', '还有什么系统 bug 没修', 'feedback.bug_todo'),
      turn('notification_confirm', 'notifications', '给全员推一条 HR 通知：明天下午三点全员培训', 'notification.create_confirm', {
        expectedBlocks: ['confirmation'],
        requiresConfirmation: true,
      }),
      turn('operations_report', 'reports', '系统经营报表看一下', 'report.operations'),
      turn('smart_data_query', 'reports', '低绩效和考勤异常交叉统计一下', 'smart.data_query'),
      blockTurn('system_audit_clear_block', 'reports', '清除操作日志'),
    ],
  },
];

const quickFlowIds = new Set([
  'recruitment_workset_to_interview',
  'employee_org_change_followup',
  'approval_notification_feedback_report_chain',
]);

const expectedModuleCoverage = new Set([
  'jobs',
  'resumes',
  'candidates',
  'interviews',
  'offers',
  'employees',
  'org',
  'attendance',
  'performance',
  'payroll',
  'approvals',
  'feedback',
  'notifications',
  'reports',
]);

const fail = (message, details) => {
  const error = new Error(message);
  error.details = details;
  throw error;
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run Kernel conversation matrix against old production ports', { baseUrl: BASE_URL });
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

const requestJson = async (urlPath, payload, token, requestId, method = 'POST') => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    let response;
    try {
      response = await fetch(`${BASE_URL}${urlPath}`, {
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
        fail(`${method} ${urlPath} exceeded ${REQUEST_TIMEOUT_MS}ms`, { requestId, timeoutMs: REQUEST_TIMEOUT_MS });
      }
      throw error;
    }
    if (!response.ok) {
      const text = await response.text();
      fail(`${urlPath} failed with HTTP ${response.status}`, text.slice(0, 1200));
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

const blockKinds = (payload) => {
  const renderBlocks = Array.isArray(payload?.renderBlocks) ? payload.renderBlocks : [];
  const widgets = Array.isArray(payload?.widgets) ? payload.widgets : [];
  const raw = [
    ...renderBlocks.map((item) => item?.kind || item?.type),
    ...widgets.map((item) => item?.kind || item?.type),
  ].filter(Boolean);
  return raw.map((item) => {
    const value = String(item);
    if (value === 'confirmation_card') return 'confirmation';
    return value;
  });
};

const routeTrace = (payload) => payload?.copilot?.routeTrace || {};
const selectedSkill = (payload) => routeTrace(payload).selected_skill || routeTrace(payload).selectedSkill || '';
const errorCode = (payload) => payload?.meta?.errorCode || payload?.errorCode || payload?.copilot?.errorCode || '';
const routePath = (payload) => payload?.copilot?.routePath || payload?.meta?.routePath || '';
const fallbackReason = (payload) => routeTrace(payload).fallback_reason || routeTrace(payload).fallbackReason || '';
const pendingAction = (payload) => payload?.copilot?.pendingAction || payload?.meta?.pendingAction || null;

const confirmationActionIds = (payload) => {
  const allBlocks = [
    ...(Array.isArray(payload?.renderBlocks) ? payload.renderBlocks : []),
    ...(Array.isArray(payload?.widgets) ? payload.widgets : []),
  ];
  const ids = [];
  for (const block of allBlocks) {
    if (!block || typeof block !== 'object') continue;
    if (!['confirmation', 'confirmation_card'].includes(String(block.kind || block.type || ''))) continue;
    const direct = block.actionId || block.action_id;
    if (direct) ids.push(String(direct));
    for (const action of Array.isArray(block.actions) ? block.actions : []) {
      if (!action || typeof action !== 'object') continue;
      const actionId = action.actionId || action.action_id || action.id;
      if (actionId) ids.push(String(actionId));
      const payloadText = String(action.payload || action.value || action.question || '');
      const match = payloadText.match(/确认执行动作[：:]([A-Za-z0-9_-]+)/);
      if (match) ids.push(match[1]);
    }
  }
  return [...new Set(ids)];
};

const nodeDetail = (payload, name) => {
  const nodes = routeTrace(payload)?.kernel?.nodes || routeTrace(payload)?.kernel_nodes || [];
  if (!Array.isArray(nodes)) return {};
  return nodes.find((item) => item?.node === name)?.detail || {};
};

const plannerDiagnostics = (payload) => (
  routeTrace(payload).planner_diagnostics
  || routeTrace(payload).plannerDiagnostics
  || nodeDetail(payload, 'planning')
  || {}
);

const understandingDiagnostics = (payload) => (
  routeTrace(payload).understanding_diagnostics
  || routeTrace(payload).understandingDiagnostics
  || nodeDetail(payload, 'understanding')
  || {}
);

const llmParticipation = (payload) => {
  const planner = plannerDiagnostics(payload);
  const understanding = understandingDiagnostics(payload);
  return {
    plannerAttempted: Boolean(planner.attempted ?? planner.llm_attempted),
    plannerAccepted: Boolean(planner.accepted ?? planner.llm_accepted),
    plannerStatus: String(planner.status || planner.llm_status || ''),
    plannerSource: String(routeTrace(payload).planner_source || routeTrace(payload).plannerSource || ''),
    understandingAttempted: Boolean(understanding.attempted ?? understanding.llm_attempted),
    understandingAccepted: Boolean(understanding.accepted ?? understanding.llm_accepted),
    understandingStatus: String(understanding.status || understanding.llm_status || ''),
  };
};

const summaryText = (payload) => {
  const answer = payload?.answer;
  if (typeof answer === 'string') return answer;
  if (answer && typeof answer === 'object') return String(answer.content || '');
  return String(payload?.summary || '');
};

const runTurn = async (token, sessionId, flow, item, turnIndex) => {
  const requestId = `${suiteId}-${flow.id}-${turnIndex + 1}`;
  let payload;
  try {
    payload = await requestJson('/api/hrm/assistant/query', {
      question: item.question,
      sessionId,
      clientContext: item.clientContext,
    }, token, requestId);
  } catch (error) {
    return {
      id: item.id,
      flowId: flow.id,
      module: item.module,
      ok: false,
      missing: ['request_failed'],
      question: item.question,
      selectedSkill: '',
      expectedSkills: item.expectedSkills || [],
      errorCode: error?.name === 'AbortError' ? 'request_timeout' : 'request_failed',
      expectedErrorCode: item.expectedErrorCode || '',
      requiresConfirmation: false,
      routePath: '',
      fallbackReason: '',
      llmParticipation: {},
      renderBlocks: [],
      pendingAction: null,
      summary: String(error?.message || error).slice(0, 220),
      requestId,
      sessionId,
      errorDetails: error?.details || null,
    };
  }

  const skill = selectedSkill(payload);
  const err = errorCode(payload);
  const kinds = blockKinds(payload);
  const participation = llmParticipation(payload);
  const action = pendingAction(payload);
  const actionIds = confirmationActionIds(payload);
  const missing = [];

  if (routePath(payload) !== 'skill_first_runtime') missing.push('routePath:skill_first_runtime');
  if (item.expectedErrorCode) {
    if (err !== item.expectedErrorCode) missing.push(`errorCode:${item.expectedErrorCode}`);
    if (payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation:false');
  } else {
    if (!(item.expectedSkills || []).includes(skill)) missing.push(`skill:${(item.expectedSkills || []).join('|')}`);
    if (err) missing.push(`errorCode:- got ${err}`);
    if (skill === 'skill_first_clarification' || fallbackReason(payload) === 'llm_planner_unusable') {
      missing.push('no_skill_first_clarification');
    }
  }
  if (item.requiresConfirmation && !payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation');
  if (item.requiresConfirmation && !action && actionIds.length === 0) missing.push('confirmationActionId');
  if (item.requiresConfirmation === false && payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation:false');
  for (const kind of item.expectedBlocks || []) {
    if (!kinds.includes(kind)) missing.push(`block:${kind}`);
  }
  const summary = summaryText(payload).replace(/\s+/g, ' ');
  for (const expectedText of item.summaryIncludes || []) {
    if (!summary.includes(expectedText)) missing.push(`summaryIncludes:${expectedText}`);
  }
  for (const rejectedText of item.summaryExcludes || []) {
    if (summary.includes(rejectedText)) missing.push(`summaryExcludes:${rejectedText}`);
  }
  if (REQUIRE_LLM_PARTICIPATION && !item.expectedErrorCode) {
    if (!participation.plannerAttempted) missing.push('llm:planner_attempted');
  }

  return {
    id: item.id,
    flowId: flow.id,
    module: item.module,
    ok: missing.length === 0,
    missing,
    question: item.question,
    selectedSkill: skill,
    expectedSkills: item.expectedSkills || [],
    errorCode: err,
    expectedErrorCode: item.expectedErrorCode || '',
    requiresConfirmation: Boolean(payload?.meta?.requiresConfirmation),
    routePath: routePath(payload),
    fallbackReason: fallbackReason(payload),
    llmParticipation: participation,
    renderBlocks: kinds,
    pendingAction: action ? {
      id: action.id || action.actionId || null,
      label: action.label || action.action || null,
      toolCount: Array.isArray(action.tools) ? action.tools.length : 0,
    } : null,
    confirmationActionIds: actionIds,
    topK: routeTrace(payload).top_k_skills || routeTrace(payload).topKSkills || [],
    summary: summary.slice(0, 260),
    requestId,
    sessionId: payload?.sessionId || sessionId,
  };
};

const resetLlmHealth = async (token) => {
  if (!RESET_LLM_HEALTH) return null;
  try {
    return await requestJson(
      '/api/hrm/assistant/skill-first/llm-health',
      {},
      token,
      `${suiteId}-llm-health-reset`,
      'POST',
    );
  } catch (error) {
    return { ok: false, error: String(error?.message || error) };
  }
};

const moduleStats = (results) => {
  const grouped = {};
  for (const result of results) {
    const key = result.module || 'unknown';
    grouped[key] ||= { total: 0, passed: 0, failed: 0 };
    grouped[key].total += 1;
    if (result.ok) grouped[key].passed += 1;
    else grouped[key].failed += 1;
  }
  return grouped;
};

const flowStats = (flowsAndResults) => Object.fromEntries(
  flowsAndResults.map((item) => [
    item.id,
    {
      total: item.results.length,
      passed: item.results.filter((result) => result.ok).length,
      failed: item.results.filter((result) => !result.ok).length,
      requiredModules: item.requiredModules,
    },
  ]),
);

const coverageFailures = (selectedFlows, results) => {
  if (RUN_QUICK_MATRIX) return [];
  const covered = new Set(results.filter((item) => item.ok).map((item) => item.module));
  const declared = new Set(selectedFlows.flatMap((item) => item.requiredModules || []));
  const missing = [];
  for (const module of expectedModuleCoverage) {
    if (!declared.has(module)) missing.push(`declared_module:${module}`);
    if (!covered.has(module)) missing.push(`passed_module:${module}`);
  }
  return missing;
};

const writeReport = (report) => {
  const outDir = path.join('artifacts', 'browser-verification');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, `assistant-kernel-conversation-matrix-${stamp}-${suiteId}.json`);
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2), 'utf8');
  return outPath;
};

const main = async () => {
  assertIsolatedBaseUrl();
  const selectedFlows = RUN_QUICK_MATRIX ? flows.filter((item) => quickFlowIds.has(item.id)) : flows;
  console.log(`Running Agent Kernel conversation matrix against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  console.log(`Mode: ${RUN_QUICK_MATRIX ? 'quick' : 'full'} (${selectedFlows.length}/${flows.length} flows)`);
  console.log(`Require LLM participation: ${REQUIRE_LLM_PARTICIPATION ? 'yes' : 'no'}`);

  const health = await requestJson('/api/health', null, null, `${suiteId}-health`, 'GET');
  const ready = await requestJson('/api/ready', null, null, `${suiteId}-ready`, 'GET');
  if (health.ok !== true) fail('/api/health did not return ok=true', health);
  if (ready.ok !== true || ready.db !== 'up') fail('/api/ready did not return ok=true, db=up', ready);

  const token = await login();
  const resetLlmHealthResult = await resetLlmHealth(token);
  if (resetLlmHealthResult) console.log('Resetting Skill-first LLM health state before conversation matrix');

  const flowResults = [];
  for (const flow of selectedFlows) {
    let sessionId = `${suiteId}-${flow.id}-session`;
    const results = [];
    console.log(`\n[flow] ${flow.id}`);
    for (const [index, item] of flow.turns.entries()) {
      console.log(`  [${index + 1}/${flow.turns.length}] ${item.id}: ${item.question}`);
      const result = await runTurn(token, sessionId, flow, item, index);
      const planner = result.llmParticipation?.plannerSource || result.llmParticipation?.plannerStatus || '-';
      console.log(
        `    -> ${result.ok ? 'ok' : 'fail'} selected=${result.selectedSkill || '-'} `
        + `error=${result.errorCode || '-'} confirm=${result.requiresConfirmation ? 'yes' : 'no'} planner=${planner}`,
      );
      if (!result.ok) console.log(`       missing: ${result.missing.join(', ')}`);
      results.push(result);
      if (result.sessionId) sessionId = result.sessionId;
    }
    flowResults.push({
      id: flow.id,
      requiredModules: flow.requiredModules,
      sessionId,
      results,
      ok: results.every((item) => item.ok),
    });
  }

  const results = flowResults.flatMap((item) => item.results);
  const failed = results.filter((item) => !item.ok);
  const nonErrorResults = results.filter((item) => !item.expectedErrorCode);
  const plannerAcceptedCount = nonErrorResults.filter((item) => item.llmParticipation?.plannerAccepted).length;
  const plannerAttemptedCount = nonErrorResults.filter((item) => item.llmParticipation?.plannerAttempted).length;
  const plannerAcceptedRatio = nonErrorResults.length ? plannerAcceptedCount / nonErrorResults.length : 0;
  const acceptanceFailures = coverageFailures(selectedFlows, results);
  if (MIN_PLANNER_ACCEPTED_RATIO > 0 && plannerAcceptedRatio < MIN_PLANNER_ACCEPTED_RATIO) {
    acceptanceFailures.push(`llm:planner_accepted_ratio ${plannerAcceptedRatio.toFixed(4)} < ${MIN_PLANNER_ACCEPTED_RATIO}`);
  }

  const report = {
    ok: failed.length === 0 && acceptanceFailures.length === 0,
    suiteId,
    baseUrl: BASE_URL,
    mode: 'agent_kernel_conversation_matrix',
    matrixMode: RUN_QUICK_MATRIX ? 'quick' : 'full',
    flowCount: selectedFlows.length,
    totalAvailableFlowCount: flows.length,
    turnCount: results.length,
    passCount: results.length - failed.length,
    failCount: failed.length + acceptanceFailures.length,
    acceptanceFailures,
    moduleStats: moduleStats(results),
    flowStats: flowStats(flowResults),
    llmStats: {
      requirePlannerAttempt: REQUIRE_LLM_PARTICIPATION,
      minPlannerAcceptedRatio: MIN_PLANNER_ACCEPTED_RATIO,
      nonErrorTurnCount: nonErrorResults.length,
      plannerAttemptedCount,
      plannerAcceptedCount,
      plannerAcceptedRatio: Number(plannerAcceptedRatio.toFixed(4)),
      plannerTimeoutCount: nonErrorResults.filter((item) => item.llmParticipation?.plannerStatus === 'llm_timeout').length,
      understandingAttemptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAttempted).length,
      understandingAcceptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAccepted).length,
    },
    resetLlmHealth: resetLlmHealthResult,
    flows: flowResults,
  };
  report.reportPath = writeReport(report);
  console.log(JSON.stringify(report, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error);
  if (error?.details) console.error(JSON.stringify(error.details, null, 2));
  process.exit(1);
});
