import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const NPM = process.platform === 'win32' ? 'cmd.exe' : 'npm';

const SIDE_EFFECT_CASES = [
  {
    key: 'attendanceNotification',
    label: 'attendance notification confirmation',
    script: 'verify:assistant-ui-confirmed-action-e2e',
    verify: (report) => {
      assertEqual(report.notifications?.afterDraft, report.notifications?.before, 'attendance draft wrote notifications before confirmation', report.notifications);
      assertMin(count(report.notifications?.created), 1, 'attendance confirmation did not create notifications', report.notifications);
      assertEqual(Number(report.notifications?.duplicateCreated || 0), 0, 'attendance duplicate confirmation created notifications', report.notifications);
      assertMin(count(report.operationAudit?.created), 1, 'attendance confirmation did not create operation audit logs', report.operationAudit);
    },
  },
  {
    key: 'salaryAdjustment',
    label: 'salary adjustment confirmation',
    script: 'verify:assistant-ui-salary-confirmed-action-e2e',
    verify: (report) => {
      const writes = report.businessWrites || {};
      assertMin(count(writes.createdEmployeeChanges), 1, 'salary confirmation did not create employee changes', writes);
      assertMin(count(writes.createdApprovals), 1, 'salary confirmation did not create approvals', writes);
      assertMin(count(writes.createdNotifications), 1, 'salary confirmation did not create notifications', writes);
      assertMin(count(writes.createdOperationLogs), 1, 'salary confirmation did not create operation logs', writes);
      assertEqual(Number(writes.duplicateCreatedEmployeeChanges || 0), 0, 'salary duplicate confirmation created employee changes', writes);
      assertEqual(Number(writes.duplicateCreatedApprovals || 0), 0, 'salary duplicate confirmation created approvals', writes);
      assertEqual(Number(writes.duplicateCreatedOperationLogs || 0), 0, 'salary duplicate confirmation created operation logs', writes);
      assertTrue(report.salaryGuard?.unchangedBeforeApproval === true, 'salary profile changed before approval', report.salaryGuard);
    },
  },
  {
    key: 'approvalDecision',
    label: 'approval decision confirmation',
    script: 'verify:assistant-ui-approval-decision-e2e',
    verify: (report) => {
      const writes = report.businessWrites || {};
      assertTrue(['approved', 'rejected'].includes(String(writes.approvalStatus || '')), 'approval status was not updated to a terminal state', writes);
      assertEqual(writes.employeeRequestStatus, writes.approvalStatus, 'approval decision did not sync employee request status', writes);
      assertMin(count(writes.approvalRecords), 1, 'approval decision did not create approval records', writes);
      assertMin(count(writes.operationLogs), 1, 'approval decision did not create operation logs', writes);
      assertEqual(Number(writes.duplicateApprovalRecords || 0), 0, 'approval duplicate confirmation created approval records', writes);
      assertEqual(Number(writes.duplicateOperationLogs || 0), 0, 'approval duplicate confirmation created operation logs', writes);
    },
  },
  {
    key: 'employeeChangeSubmission',
    label: 'employee change confirmation',
    script: 'verify:assistant-ui-employee-change-confirmed-action-e2e',
    verify: (report) => {
      const writes = report.businessWrites || {};
      assertMin(count(writes.createdEmployeeChanges), 1, 'employee-change confirmation did not create employee changes', writes);
      assertMin(count(writes.createdApprovals), 1, 'employee-change confirmation did not create approvals', writes);
      assertMin(count(writes.createdNotifications), 1, 'employee-change confirmation did not create notifications', writes);
      assertMin(count(writes.createdOperationLogs), 1, 'employee-change confirmation did not create operation logs', writes);
      assertEqual(Number(writes.duplicateCreatedEmployeeChanges || 0), 0, 'employee-change duplicate confirmation created employee changes', writes);
      assertEqual(Number(writes.duplicateCreatedApprovals || 0), 0, 'employee-change duplicate confirmation created approvals', writes);
      assertEqual(Number(writes.duplicateCreatedOperationLogs || 0), 0, 'employee-change duplicate confirmation created operation logs', writes);
      assertTrue(report.employeeGuard?.unchangedBeforeApproval === true, 'employee profile changed before approval', report.employeeGuard);
    },
  },
  {
    key: 'employeeChangeApprovalLoop',
    label: 'employee change approval loop',
    script: 'verify:assistant-ui-employee-change-approval-loop-e2e',
    verify: (report) => {
      const writes = report.businessWrites || {};
      assertTrue(Boolean(writes.employeeChange?.id), 'employee-change approval loop did not create a change row', writes);
      assertTrue(Boolean(writes.approval?.id), 'employee-change approval loop did not create an approval row', writes);
      assertMin(count(writes.notifications), 1, 'employee-change approval loop did not create notifications', writes);
      assertTrue(Boolean(writes.changeSubmitOperationLog?.id), 'employee-change approval loop did not create change submit operation log', writes);
      assertTrue(Boolean(writes.approvalRecord?.id), 'employee-change approval loop did not create approval record', writes);
      assertTrue(Boolean(writes.approvalOperationLog?.id), 'employee-change approval loop did not create approval operation log', writes);
      assertEqual(Number(writes.duplicateApprovalRecords || 0), 0, 'employee-change approval loop duplicate confirmation created approval records', writes);
      assertEqual(Number(writes.duplicateApprovalOperationLogs || 0), 0, 'employee-change approval loop duplicate confirmation created operation logs', writes);
      assertTrue(report.employeeGuardAndEffect?.unchangedBeforeApproval === true, 'employee-change loop changed employee profile before approval', report.employeeGuardAndEffect);
      assertTrue(report.employeeGuardAndEffect?.appliedAfterApproval === true, 'employee-change loop did not apply profile change after approval', report.employeeGuardAndEffect);
    },
  },
];

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

function assertTrue(condition, message, details) {
  if (!condition) fail(message, details);
}

function assertEqual(actual, expected, message, details) {
  if (actual !== expected) fail(message, { actual, expected, details });
}

function assertMin(actual, minimum, message, details) {
  if (!(Number(actual) >= minimum)) fail(message, { actual, minimum, details });
}

function count(value) {
  return Array.isArray(value) ? value.length : 0;
}

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run assistant side-effect browser acceptance against old production ports', { baseUrl: BASE_URL });
  }
};

const isRetryableProviderStreamFailure = (text) => (
  /stream call failed/i.test(text || '')
  || /request timeout/i.test(text || '')
);

const runOnce = (label, args, attempt) => new Promise((resolve) => {
  const commandArgs = process.platform === 'win32' ? ['/d', '/s', '/c', 'npm', ...args] : args;
  console.log(`\n[${label}] npm ${args.join(' ')}${attempt > 1 ? ` (attempt ${attempt})` : ''}`);
  const child = spawn(NPM, commandArgs, {
    cwd: process.cwd(),
    env: { ...process.env, HRM_BASE_URL: BASE_URL },
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
  child.on('error', (error) => {
    resolve({ code: 1, stdout, stderr: `${stderr}\n${error?.stack || error?.message || error}` });
  });
  child.on('close', (code) => {
    resolve({ code, stdout, stderr });
  });
});

const run = async (label, args, options = {}) => {
  const maxAttempts = Number(options.maxAttempts || 1);
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const result = await runOnce(label, args, attempt);
    if (result.code === 0) return result;
    const combinedOutput = `${result.stdout}\n${result.stderr}`;
    if (attempt < maxAttempts && isRetryableProviderStreamFailure(combinedOutput)) {
      console.warn(`[${label}] retrying after provider stream failure`);
      continue;
    }
    throw new Error(`${label} failed with exit code ${result.code}`);
  }
  throw new Error(`${label} failed`);
};

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

const readReport = async (summary, label) => {
  if (!summary?.ok) fail(`${label} summary is not ok`, summary);
  if (!summary.reportPath) fail(`${label} summary did not include reportPath`, summary);
  const reportPath = path.isAbsolute(summary.reportPath)
    ? summary.reportPath
    : path.resolve(summary.reportPath);
  const raw = await readFile(reportPath, 'utf8');
  const report = JSON.parse(raw);
  return { report, reportPath };
};

const verifyScreenshots = async (screenshots, label) => {
  const entries = Object.entries(screenshots || {}).filter(([, value]) => value);
  assertMin(entries.length, 1, `${label} report did not include screenshots`, screenshots);
  for (const [name, filePath] of entries) {
    await access(filePath).catch(() => fail(`${label} screenshot is missing`, { name, filePath }));
  }
};

const verifyAudits = (audits, label) => {
  const entries = Object.entries(audits || {});
  assertMin(entries.length, 2, `${label} report did not include enough assistant audit rows`, audits);
  let realModelCount = 0;
  let deterministicReceiptCount = 0;
  for (const [name, audit] of entries) {
    assertEqual(audit.provider, 'siliconflow', `${label} ${name} audit provider is not siliconflow`, audit);
    assertEqual(audit.useCase, 'assistant_stream_answer', `${label} ${name} audit useCase is not assistant_stream_answer`, audit);
    assertEqual(audit.status, 'success', `${label} ${name} audit status is not success`, audit);
    const deterministicReceipt = audit.responseMeta?.deterministicReceipt === true
      || String(audit.model || '') === 'deterministic-confirmed-action-receipt';
    if (name.toLowerCase().includes('draft') && deterministicReceipt) {
      fail(`${label} ${name} audit used deterministic receipt for a draft response that requires a real model call`, audit);
    }
    assertTrue(
      String(audit.model || '').includes('DeepSeek') || deterministicReceipt,
      `${label} ${name} audit model is neither DeepSeek nor deterministic confirmed-action receipt`,
      audit,
    );
    if (deterministicReceipt) {
      deterministicReceiptCount += 1;
      assertTrue(audit.responseMeta?.skippedProviderCall === true, `${label} ${name} deterministic receipt did not mark skippedProviderCall`, audit);
    } else {
      realModelCount += 1;
    }
    assertMin(Number(audit.chunkCount || 0), 1, `${label} ${name} audit has no chunks`, audit);
  }
  assertMin(realModelCount, 1, `${label} did not include any real DeepSeek model audit`, audits);
  return { realModelCount, deterministicReceiptCount };
};

const verifyCommonReport = async (caseConfig, report, reportPath) => {
  assertTrue(report?.ok === true, `${caseConfig.label} report is not ok`, report);
  assertEqual(report.baseUrl, BASE_URL, `${caseConfig.label} did not run against expected base URL`, report);
  assertTrue(Array.isArray(report.protectedPorts) && report.protectedPorts.includes('8080') && report.protectedPorts.includes('8443'), `${caseConfig.label} did not report protected old ports`, report.protectedPorts);
  assertEqual(report.isolatedDatabase, 'hengpintong_next', `${caseConfig.label} did not report isolated database`, report);
  assertTrue(Object.values(report.requestIds || {}).filter(Boolean).length >= 2, `${caseConfig.label} did not expose request IDs`, report.requestIds);
  await verifyScreenshots(report.screenshots, caseConfig.label);
  const auditSummary = verifyAudits(report.audits, caseConfig.label);
  caseConfig.verify(report);
  return {
    key: caseConfig.key,
    label: caseConfig.label,
    ok: true,
    runId: report.runId,
    reportPath,
    requestIds: report.requestIds,
    auditSummary,
    aiModelSettingsLookup: report.aiModelSettingsLookup,
  };
};

const main = async () => {
  assertIsolatedBaseUrl();
  await mkdir(ARTIFACT_DIR, { recursive: true });

  const results = [];
  for (const caseConfig of SIDE_EFFECT_CASES) {
    const runResult = await run(caseConfig.key, ['run', caseConfig.script], { maxAttempts: 2 });
    const summary = extractLastJson(runResult.stdout);
    const { report, reportPath } = await readReport(summary, caseConfig.label);
    results.push(await verifyCommonReport(caseConfig, report, reportPath));
  }

  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const reportPath = path.join(ARTIFACT_DIR, `assistant-side-effect-browser-acceptance-${stamp}.json`);
  const report = {
    ok: true,
    baseUrl: BASE_URL,
    sideEffectCaseCount: SIDE_EFFECT_CASES.length,
    passed: results.length,
    failed: 0,
    cases: results,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
