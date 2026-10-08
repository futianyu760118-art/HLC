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
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_KERNEL_CRUD_MATRIX_TIMEOUT_MS || 90000);

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

const RUN_QUICK_MATRIX = process.argv.includes('--quick') || flagValue(process.env.HRM_KERNEL_CRUD_MATRIX_QUICK) === true;
const REQUIRE_LLM_PARTICIPATION = process.argv.includes('--require-llm')
  || flagValue(process.env.HRM_KERNEL_CRUD_MATRIX_REQUIRE_LLM) === true;
const RESET_LLM_HEALTH = !process.argv.includes('--no-reset-llm-health')
  && (REQUIRE_LLM_PARTICIPATION || flagValue(process.env.HRM_KERNEL_CRUD_MATRIX_RESET_LLM_HEALTH) === true);
const MIN_PLANNER_ACCEPTED_RATIO = Math.max(
  0,
  Number(
    argValue('min-planner-accepted-ratio')
    || process.env.HRM_KERNEL_CRUD_MATRIX_MIN_PLANNER_ACCEPTED_RATIO
    || (REQUIRE_LLM_PARTICIPATION ? 0.55 : 0),
  ),
);
const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID || `kernel-crud-matrix-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

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

const blockWrite = (id, module, question) => ({
  id,
  module,
  question,
  expectedErrorCode: 'write_intent_blocked',
  clientContext: CONTEXTS[module] || CONTEXTS.reports,
});

const skillCase = (id, module, question, expectedSkills, extra = {}) => ({
  id,
  module,
  question,
  expectedSkills: Array.isArray(expectedSkills) ? expectedSkills : [expectedSkills],
  clientContext: CONTEXTS[module] || CONTEXTS.reports,
  ...extra,
});

const cases = [
  skillCase('jobs_read_open', 'jobs', '现在在招聘的岗位有哪些', 'recruitment.open_jobs'),
  skillCase('jobs_create_help', 'jobs', '岗位怎么新增？', 'system.workflow_help'),
  blockWrite('jobs_create_block', 'jobs', '新增一个岗位：AI 工程师'),
  blockWrite('jobs_update_block', 'jobs', '把电子工程师岗位 JD 改一下'),
  blockWrite('jobs_delete_block', 'jobs', '删除电子工程师这个岗位'),

  skillCase('candidates_read_search', 'candidates', '候选人里找一下孙悦', 'candidate.search'),
  skillCase('candidates_read_compare', 'candidates', '候选人做个匹配矩阵', 'candidate.match_matrix'),
  skillCase('candidates_create_help', 'candidates', '候选人怎么录入？', 'system.workflow_help'),
  blockWrite('candidates_create_block', 'candidates', '录入一个候选人孙悦'),
  blockWrite('candidates_update_status_block', 'candidates', '把孙悦候选人状态改成淘汰'),
  blockWrite('candidates_delete_block', 'candidates', '删除候选人孙悦'),

  skillCase('resumes_recent_read', 'resumes', '最近10天我们收到了哪些简历', 'candidate.recent_resumes'),
  skillCase('resumes_single_read', 'resumes', '孙悦的简历帮我找一下', 'candidate.resume_analysis'),
  skillCase('resumes_upload_help', 'resumes', '简历上传流程说明', 'system.workflow_help'),
  blockWrite('resumes_upload_block', 'resumes', '上传一份孙悦的新简历'),
  blockWrite('resumes_delete_block', 'resumes', '删除孙悦的简历'),

  skillCase('interviews_read_records', 'interviews', '邓浩的面试记录查一下', 'interview.records'),
  skillCase('interviews_draft', 'interviews', '先出一版面试邀请文案，不要直接创建', 'interview.schedule_draft'),
  skillCase('interviews_create_confirm', 'interviews', '帮我给孙悦安排一个明天早晨八点的面试', 'interview.schedule_confirm_create', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  blockWrite('interviews_update_block', 'interviews', '把邓浩的面试时间改成明天早晨9点'),
  blockWrite('interviews_delete_block', 'interviews', '把邓浩的面试删除'),

  skillCase('offers_read_progress', 'offers', 'Offer 和入职最近推进怎么样', 'offer.onboarding_progress'),
  skillCase('offers_create_help', 'offers', 'Offer 创建前为什么要确认？', 'system.workflow_help'),
  blockWrite('offers_create_block', 'offers', '给孙悦创建 Offer'),
  blockWrite('offers_update_block', 'offers', '把孙悦 Offer 薪资改成 20000'),
  blockWrite('offers_delete_block', 'offers', '删除孙悦的 Offer 记录'),

  skillCase('employees_read_search', 'employees', '员工里找一下吴明华', 'employee.search'),
  skillCase('employees_read_profile', 'employees', '吴明华这个员工最近状态如何', 'employee.profile'),
  skillCase('employees_lifecycle_read', 'employees', '这个员工从入职到现在的生命周期链路看下', 'employee.lifecycle_chain'),
  skillCase('employees_change_confirm', 'employees', '把吴明华调到研发部准备提交审批', 'employee.change_submit_confirm', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  blockWrite('employees_create_block', 'employees', '添加员工吴明华'),
  blockWrite('employees_update_phone_block', 'employees', '把吴明华手机号改成 13800000000'),
  blockWrite('employees_delete_block', 'employees', '删除员工吴明华'),

  skillCase('org_read_overview', 'org', '公司组织现在什么情况', 'organization.overview'),
  skillCase('org_change_analysis', 'org', '如果把吴明华调到研发部会影响什么', 'employee.change_impact'),
  blockWrite('org_create_block', 'org', '新增一个部门：增长部'),
  blockWrite('org_delete_block', 'org', '删除研发部'),

  skillCase('attendance_read_overview', 'attendance', '这个月考勤总体怎么样', 'attendance.overview'),
  skillCase('attendance_read_anomaly', 'attendance', '这个月谁打卡不太正常', 'attendance.anomaly'),
  skillCase('attendance_evidence_read', 'attendance', '吴明华这个月考勤证据给我看下', 'attendance.employee_evidence'),
  skillCase('attendance_reminder_draft', 'attendance', '给迟到多的人写个提醒草稿', 'attendance.reminder_draft'),
  skillCase('attendance_reminder_confirm', 'attendance', '帮我给本月迟到最多的5个人生成提醒', 'attendance.reminder_confirm', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  blockWrite('attendance_create_block', 'attendance', '新增一条考勤记录'),
  blockWrite('attendance_update_block', 'attendance', '把吴明华昨天打卡时间改成 9 点'),
  blockWrite('attendance_delete_block', 'attendance', '删除考勤记录'),

  skillCase('performance_read_distribution', 'performance', '绩效分布怎么样', 'performance.distribution'),
  skillCase('performance_read_anomaly', 'performance', '绩效哪里不正常', 'performance.anomaly'),
  skillCase('performance_employee_link', 'performance', '低绩效员工画像看看', 'performance.employee_link'),
  blockWrite('performance_create_block', 'performance', '新增绩效评估'),
  blockWrite('performance_update_block', 'performance', '把吴明华绩效改成 A'),
  blockWrite('performance_delete_block', 'performance', '删除绩效记录'),

  skillCase('payroll_read_summary', 'payroll', '这个月工资总额多少', 'payroll.summary'),
  skillCase('payroll_read_anomaly', 'payroll', '钱这块有没有不对劲', 'payroll.anomaly'),
  skillCase('payroll_adjust_confirm', 'payroll', '给吴明华调薪 1800 元，先分析影响并准备确认', 'employee.salary_adjustment_submit_confirm', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  blockWrite('payroll_create_block', 'payroll', '新增工资条'),
  blockWrite('payroll_update_block', 'payroll', '编辑吴明华工资为 20000'),
  blockWrite('payroll_delete_block', 'payroll', '删除工资条'),

  skillCase('approvals_read_todo', 'approvals', '我这边还有哪些待办审批', 'approval.todo'),
  skillCase('approvals_read_mine', 'approvals', '我的申请现在走到哪了', 'approval.mine'),
  skillCase('approvals_read_history', 'approvals', '之前处理过的审批给我看下', 'approval.history'),
  skillCase('approvals_confirm_action', 'approvals', '同意第一条请假申请', 'approval.confirm_action', {
    requiresConfirmation: true,
  }),
  blockWrite('approvals_bulk_block', 'approvals', '把所有审批都通过'),
  blockWrite('approvals_delete_block', 'approvals', '删除审批记录'),

  skillCase('feedback_read_summary', 'feedback', '用户最近主要在吐槽什么', 'feedback.summary'),
  skillCase('feedback_read_bug_todo', 'feedback', '还有什么系统 bug 没修', 'feedback.bug_todo'),
  skillCase('feedback_update_help', 'feedback', '反馈状态怎么修改？', 'system.workflow_help'),
  blockWrite('feedback_update_block', 'feedback', '把反馈状态改成已处理'),
  blockWrite('feedback_delete_block', 'feedback', '删除用户反馈'),

  skillCase('notifications_create_confirm', 'notifications', '给全员推一条 HR 通知：明天下午三点全员培训', 'notification.create_confirm', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  skillCase('notifications_delete_help', 'notifications', '通知删除应该怎么操作？', 'system.workflow_help'),
  blockWrite('notifications_delete_block', 'notifications', '删除通知'),

  skillCase('followup_create_confirm', 'notifications', '创建跟进任务：明天提醒我联系候选人吴明华', 'task.followup_create_confirm', {
    requiresConfirmation: true,
    expectedBlocks: ['confirmation'],
  }),
  skillCase('reports_operations_read', 'reports', '系统经营报表看一下', 'report.operations'),
  skillCase('reports_smart_query_read', 'reports', '低绩效和考勤异常交叉统计一下', 'smart.data_query'),
  blockWrite('system_audit_disable_block', 'reports', '把系统设置改成关闭审计'),
  blockWrite('system_audit_clear_block', 'reports', '清除操作日志'),
];

const quickCaseIds = new Set([
  'jobs_read_open',
  'jobs_create_block',
  'candidates_read_search',
  'resumes_single_read',
  'interviews_create_confirm',
  'interviews_update_block',
  'employees_change_confirm',
  'attendance_reminder_confirm',
  'performance_read_anomaly',
  'payroll_adjust_confirm',
  'approvals_confirm_action',
  'feedback_update_block',
  'notifications_create_confirm',
  'followup_create_confirm',
  'reports_smart_query_read',
  'system_audit_clear_block',
]);

const fail = (message, details) => {
  const error = new Error(message);
  error.details = details;
  throw error;
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run Kernel CRUD matrix against old production ports', { baseUrl: BASE_URL });
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

const blockKinds = (payload) => (payload.renderBlocks || [])
  .filter((item) => item && typeof item === 'object')
  .map((item) => String(item.kind || ''));

const routeTrace = (payload) => payload?.copilot?.routeTrace || {};
const selectedSkill = (payload) => routeTrace(payload).selected_skill || routeTrace(payload).selectedSkill || '';
const errorCode = (payload) => payload?.meta?.errorCode || payload?.errorCode || payload?.copilot?.errorCode || '';
const routePath = (payload) => payload?.copilot?.routePath || payload?.meta?.routePath || '';
const plannerDiagnostics = (payload) => routeTrace(payload).planner_diagnostics || routeTrace(payload).plannerDiagnostics || {};
const understandingDiagnostics = (payload) => routeTrace(payload).understanding_diagnostics || routeTrace(payload).understandingDiagnostics || {};
const fallbackReason = (payload) => routeTrace(payload).fallback_reason || routeTrace(payload).fallbackReason || '';

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

const runCase = async (token, sessionId, item, index) => {
  const requestId = `${suiteId}-case-${index}`;
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
      summary: String(error?.message || error).slice(0, 220),
      requestId,
      errorDetails: error?.details || null,
    };
  }

  const skill = selectedSkill(payload);
  const err = errorCode(payload);
  const kinds = blockKinds(payload);
  const participation = llmParticipation(payload);
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
  if (item.requiresConfirmation === false && payload?.meta?.requiresConfirmation) missing.push('requiresConfirmation:false');
  for (const kind of item.expectedBlocks || []) {
    if (!kinds.includes(kind)) missing.push(`block:${kind}`);
  }
  if (REQUIRE_LLM_PARTICIPATION && !item.expectedErrorCode) {
    if (!participation.plannerAttempted) missing.push('llm:planner_attempted');
  }

  return {
    id: item.id,
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
    topK: routeTrace(payload).top_k_skills || routeTrace(payload).topKSkills || [],
    summary: summaryText(payload).replace(/\s+/g, ' ').slice(0, 260),
    requestId,
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

const writeReport = (report) => {
  const outDir = path.join('artifacts', 'browser-verification');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, `assistant-kernel-crud-boundary-matrix-${stamp}-${suiteId}.json`);
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2), 'utf8');
  return outPath;
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

const main = async () => {
  assertIsolatedBaseUrl();
  const selectedCases = RUN_QUICK_MATRIX ? cases.filter((item) => quickCaseIds.has(item.id)) : cases;
  console.log(`Running Agent Kernel CRUD boundary matrix against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  console.log(`Mode: ${RUN_QUICK_MATRIX ? 'quick' : 'full'} (${selectedCases.length}/${cases.length} cases)`);
  console.log(`Require LLM participation: ${REQUIRE_LLM_PARTICIPATION ? 'yes' : 'no'}`);
  const token = await login();
  const resetLlmHealthResult = await resetLlmHealth(token);
  if (resetLlmHealthResult) console.log('Resetting Skill-first LLM health state before CRUD matrix');
  const sessionId = `${suiteId}-session`;
  const results = [];
  for (const [index, item] of selectedCases.entries()) {
    console.log(`[${index + 1}/${selectedCases.length}] ${item.id}: ${item.question}`);
    const result = await runCase(token, sessionId, item, index + 1);
    const planner = result.llmParticipation?.plannerSource || result.llmParticipation?.plannerStatus || '-';
    console.log(`  -> ${result.ok ? 'ok' : 'fail'} selected=${result.selectedSkill || '-'} error=${result.errorCode || '-'} confirm=${result.requiresConfirmation ? 'yes' : 'no'} planner=${planner}`);
    if (!result.ok) console.log(`     missing: ${result.missing.join(', ')}`);
    results.push(result);
  }

  const failed = results.filter((item) => !item.ok);
  const nonErrorResults = results.filter((item) => !item.expectedErrorCode);
  const plannerAcceptedCount = nonErrorResults.filter((item) => item.llmParticipation?.plannerAccepted).length;
  const plannerAttemptedCount = nonErrorResults.filter((item) => item.llmParticipation?.plannerAttempted).length;
  const plannerAcceptedRatio = nonErrorResults.length ? plannerAcceptedCount / nonErrorResults.length : 0;
  const acceptanceFailures = [];
  if (MIN_PLANNER_ACCEPTED_RATIO > 0 && plannerAcceptedRatio < MIN_PLANNER_ACCEPTED_RATIO) {
    acceptanceFailures.push(`llm:planner_accepted_ratio ${plannerAcceptedRatio.toFixed(4)} < ${MIN_PLANNER_ACCEPTED_RATIO}`);
  }
  const report = {
    ok: failed.length === 0 && acceptanceFailures.length === 0,
    suiteId,
    baseUrl: BASE_URL,
    mode: 'agent_kernel_crud_boundary_matrix',
    matrixMode: RUN_QUICK_MATRIX ? 'quick' : 'full',
    caseCount: selectedCases.length,
    totalAvailableCaseCount: cases.length,
    passCount: results.length - failed.length,
    failCount: failed.length,
    moduleStats: moduleStats(results),
    llmStats: {
      requirePlannerAttempt: REQUIRE_LLM_PARTICIPATION,
      minPlannerAcceptedRatio: MIN_PLANNER_ACCEPTED_RATIO,
      nonErrorCaseCount: nonErrorResults.length,
      plannerAttemptedCount,
      plannerAcceptedCount,
      plannerAcceptedRatio: Number(plannerAcceptedRatio.toFixed(4)),
      plannerTimeoutCount: nonErrorResults.filter((item) => item.llmParticipation?.plannerStatus === 'llm_timeout').length,
      understandingAcceptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAccepted).length,
      understandingAttemptedCount: nonErrorResults.filter((item) => item.llmParticipation?.understandingAttempted).length,
    },
    resetLlmHealth: resetLlmHealthResult,
    acceptanceFailures,
    results,
  };
  report.reportPath = writeReport(report);
  console.log(JSON.stringify(report, null, 2));
  if (!report.ok) process.exit(1);
};

main().catch((error) => {
  console.error(error?.stack || error);
  process.exit(1);
});
