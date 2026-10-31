import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const NPM = process.platform === 'win32' ? 'cmd.exe' : 'npm';

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run real assistant acceptance against old production ports', { baseUrl: BASE_URL });
  }
};

const run = (label, args, options = {}) => new Promise((resolve, reject) => {
  const commandArgs = process.platform === 'win32' ? ['/d', '/s', '/c', 'npm', ...args] : args;
  console.log(`\n[${label}] npm ${args.join(' ')}`);
  const child = spawn(NPM, commandArgs, {
    cwd: process.cwd(),
    env: { ...process.env, ...(options.env || {}) },
    shell: false,
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => {
    const text = chunk.toString();
    stdout += text;
    process.stdout.write(text);
  });
  child.stderr.on('data', (chunk) => {
    const text = chunk.toString();
    stderr += text;
    process.stderr.write(text);
  });
  child.on('error', reject);
  child.on('close', (code) => {
    if (code !== 0) {
      reject(new Error(`${label} failed with exit code ${code}`));
      return;
    }
    resolve({ stdout, stderr });
  });
});

const extractLastJson = (text) => {
  const starts = [...text.matchAll(/\{\s*"ok"\s*:/g)].map((match) => match.index).filter((index) => index >= 0);
  for (const start of starts.reverse()) {
    const candidate = text.slice(start).trim();
    try {
      return JSON.parse(candidate);
    } catch {
      // Keep looking for an earlier JSON object.
    }
  }
  fail('Could not extract JSON summary from command output');
};

const verifyRealSuite = (summary) => {
  if (!summary?.ok || !summary.suiteId) fail('Real SiliconFlow suite summary is not ok', summary);
  for (const diagnostic of summary.diagnostics || []) {
    if (diagnostic.provider !== 'siliconflow' || diagnostic.status !== 'success' || !diagnostic.auditLogId) {
      fail('Diagnostic did not produce a successful SiliconFlow audit', diagnostic);
    }
  }
  for (const evaluation of summary.evaluations || []) {
    if (evaluation.passStatus !== 'pass') fail('Evaluation did not pass', evaluation);
    if (evaluation.provider !== 'siliconflow' || evaluation.status !== 'success' || !evaluation.auditLogId) {
      fail('Evaluation did not produce a successful SiliconFlow audit', evaluation);
    }
  }
};

const verifyEmployeeSelfService = (summary) => {
  if (!summary?.ok || !summary.requestId) {
    fail('Employee self-service SiliconFlow summary is not ok', summary);
  }
  if (summary.provider !== 'siliconflow' || summary.status !== 'success') {
    fail('Employee self-service did not produce a successful SiliconFlow audit', summary);
  }
  if (summary.useCase !== 'assistant_stream_answer') {
    fail('Employee self-service audit useCase mismatch', summary);
  }
  if (!summary.model || !String(summary.model).includes('DeepSeek')) {
    fail('Employee self-service did not use the configured DeepSeek SiliconFlow model', summary);
  }
  if (summary.intent !== 'employee.self_service.multi_topic') {
    fail('Employee self-service intent mismatch', summary);
  }
  const usedSkills = summary.usedSkills || [];
  for (const skill of ['attendance_analysis', 'performance_analysis', 'payroll_analysis']) {
    if (!usedSkills.includes(skill)) {
      fail(`Employee self-service missing skill ${skill}`, summary);
    }
  }
  if (usedSkills.includes('payroll_performance_link')) {
    fail('Employee self-service was incorrectly routed to payroll_performance_link', summary);
  }
  const renderKinds = summary.renderKinds || [];
  for (const kind of ['status', 'table', 'sources', 'notice', 'actions']) {
    if (!renderKinds.includes(kind)) {
      fail(`Employee self-service missing render kind ${kind}`, summary);
    }
  }
};

const verifyOperationalRouting = (summary) => {
  if (!summary?.ok || !summary.runId || Number(summary.caseCount) !== 5) {
    fail('Operational routing smoke summary is not ok', summary);
  }
  const byCase = new Map((summary.results || []).map((item) => [item.caseId, item]));
  const expected = [
    ['candidate_focus_setup', 'recruitment.person.assess', 'candidate_evidence_bundle'],
    ['performance_after_candidate_focus', 'performance.distribution', 'performance_analysis'],
    ['training_after_candidate_focus', 'training.completion', 'training_analysis'],
    ['payroll_after_candidate_focus', 'payroll.summary', 'payroll_analysis'],
    ['candidate_assessment_still_available', 'recruitment.person.assess', 'candidate_evidence_bundle'],
  ];
  for (const [caseId, intent, skill] of expected) {
    const row = byCase.get(caseId);
    if (!row) fail(`Operational routing smoke missing case ${caseId}`, summary);
    if (row.intent !== intent) fail(`Operational routing intent mismatch for ${caseId}`, row);
    if (!(row.usedSkills || []).includes(skill)) fail(`Operational routing missing skill ${skill}`, row);
    if (!(Number(row.fieldEvidenceCount) >= 6)) fail(`Operational routing field evidence too low for ${caseId}`, row);
    if (caseId.includes('after_candidate_focus') && (row.usedSkills || []).includes('candidate_evidence_bundle')) {
      fail(`Operational domain case was stolen by candidate_evidence_bundle: ${caseId}`, row);
    }
  }
  const payroll = byCase.get('payroll_after_candidate_focus');
  const payrollTool = (payroll?.toolPlan || []).find((plan) => plan?.tool === 'payroll_analysis');
  if (payroll?.riskLevel !== 'high' || payrollTool?.cachePolicy !== 'none') {
    fail('Operational routing payroll risk/cache policy mismatch', payroll);
  }
};

const verifyModelSettingsLookup = (summary, expectedSuiteId) => {
  if (!summary?.ok) fail('AI model settings browser lookup is not ok', summary);
  if (summary.keyword !== expectedSuiteId) fail('AI model settings lookup keyword mismatch', summary);
  if (!summary.screenshotPath) fail('AI model settings lookup did not write a screenshot', summary);
  if (!(Number(summary.counts?.siliconRows) > 0) || !(Number(summary.counts?.successRows) > 0)) {
    fail('AI model settings lookup did not show SiliconFlow success rows', summary);
  }
};

const main = async () => {
  assertIsolatedBaseUrl();
  await mkdir(ARTIFACT_DIR, { recursive: true });

  await run('backend-tests', ['run', 'verify:backend-tests']);
  await run('assistant-contract', ['run', 'verify:assistant-contract']);

  const suiteRun = await run('real-siliconflow-suite', ['run', 'verify:assistant-real-siliconflow-suite']);
  const suiteSummary = extractLastJson(suiteRun.stdout);
  verifyRealSuite(suiteSummary);

  const employeeRun = await run(
    'real-siliconflow-employee-self-service',
    ['run', 'verify:assistant-real-siliconflow-employee-self-service'],
  );
  const employeeSummary = extractLastJson(employeeRun.stdout);
  verifyEmployeeSelfService(employeeSummary);

  const operationalRoutingRun = await run(
    'assistant-operational-routing-smoke',
    ['run', 'verify:assistant-operational-routing-smoke'],
  );
  const operationalRoutingSummary = extractLastJson(operationalRoutingRun.stdout);
  verifyOperationalRouting(operationalRoutingSummary);

  const modelSettingsRun = await run('ai-model-settings-browser-suite', ['run', 'verify:ai-model-settings-browser'], {
    env: { HRM_AUDIT_KEYWORD: suiteSummary.suiteId },
  });
  const modelSettingsSummary = extractLastJson(modelSettingsRun.stdout);
  verifyModelSettingsLookup(modelSettingsSummary, suiteSummary.suiteId);

  const employeeModelSettingsRun = await run(
    'ai-model-settings-browser-employee-self-service',
    ['run', 'verify:ai-model-settings-browser'],
    { env: { HRM_AUDIT_KEYWORD: employeeSummary.requestId } },
  );
  const employeeModelSettingsSummary = extractLastJson(employeeModelSettingsRun.stdout);
  verifyModelSettingsLookup(employeeModelSettingsSummary, employeeSummary.requestId);

  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const reportPath = path.join(ARTIFACT_DIR, `assistant-real-acceptance-${stamp}-${suiteSummary.suiteId}.json`);
  const report = {
    ok: true,
    baseUrl: BASE_URL,
    suiteId: suiteSummary.suiteId,
    diagnostics: suiteSummary.diagnostics,
    evaluations: suiteSummary.evaluations,
    employeeSelfService: employeeSummary,
    operationalRouting: operationalRoutingSummary,
    aiModelSettings: modelSettingsSummary,
    employeeSelfServiceAiModelSettings: employeeModelSettingsSummary,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf-8');
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
