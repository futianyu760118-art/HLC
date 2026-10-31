import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const NPM = process.platform === 'win32' ? 'cmd.exe' : 'npm';
const INCLUDE_FAILURE_TRACE = process.env.HRM_INCLUDE_FAILURE_TRACE_GATE === '1'
  || process.env.HRM_INCLUDE_FAILURE_TRACE_GATE === 'true';

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run assistant governance browser acceptance against old production ports', { baseUrl: BASE_URL });
  }
};

const run = (label, args, options = {}) => new Promise((resolve, reject) => {
  const commandArgs = process.platform === 'win32' ? ['/d', '/s', '/c', 'npm', ...args] : args;
  console.log(`\n[${label}] npm ${args.join(' ')}`);
  const child = spawn(NPM, commandArgs, {
    cwd: process.cwd(),
    env: { ...process.env, HRM_BASE_URL: BASE_URL, ...(options.env || {}) },
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

const loadReport = async (reportPath) => JSON.parse(await readFile(reportPath, 'utf8'));

const verifyApiPermissionGate = (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('Assistant write-permission API gate failed', summary);
  if (Number(summary.caseCount) < 19 || Number(summary.passed) < 19) {
    fail('Assistant write-permission API gate did not cover the expected role matrix', summary);
  }
  if (!summary.reportPath) fail('Assistant write-permission API gate did not write a report', summary);
};

const verifyUiPermissionGate = async (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('Assistant UI write-permission gate failed', summary);
  if (Number(summary.caseCount) < 4 || Number(summary.passed) < 4) {
    fail('Assistant UI write-permission gate did not cover the expected high-risk UI cases', summary);
  }
  if (!(Number(summary.deterministicPermissionReceipts) >= 4)) {
    fail('Assistant UI write-permission gate did not return deterministic permission receipts', summary);
  }
  if (!summary.reportPath) fail('Assistant UI write-permission gate did not write a report', summary);
  const report = await loadReport(summary.reportPath);
  for (const result of report.results || []) {
    if (result.actionCount !== 0 || result.requiresConfirmation !== false || result.taskType !== 'forbidden') {
      fail('UI permission result exposed executable or confirmable action', result);
    }
    if (result.audit?.model !== 'deterministic-permission-denied-receipt'
      || result.audit?.skippedProviderCall !== true
      || result.audit?.reason !== 'permission_denied_receipt') {
      fail('UI permission result did not expose deterministic skipped-provider audit', result);
    }
  }
  return report;
};

const verifyRequestTrace = async (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('AI model settings request trace gate failed', summary);
  if (Number(summary.caseCount) < 3 || Number(summary.passed) < 3) {
    fail('AI model settings request trace gate did not cover all expected trace classes', summary);
  }
  if (!summary.reportPath) fail('AI model settings request trace gate did not write a report', summary);
  const report = await loadReport(summary.reportPath);
  const byKey = new Map((report.results || []).map((item) => [item.key, item]));
  const real = byKey.get('realDeepSeekDraft');
  const confirmed = byKey.get('confirmedActionReceipt');
  const permission = byKey.get('permissionDeniedReceipt');
  if (!real || !String(real.apiAudit?.model || '').includes('DeepSeek') || real.expectedCallType !== '真实模型') {
    fail('Request trace did not prove real DeepSeek draft visibility', real);
  }
  if (!confirmed || confirmed.apiAudit?.model !== 'deterministic-confirmed-action-receipt'
    || confirmed.apiAudit?.responseMeta?.skippedProviderCall !== true
    || confirmed.uiEvidence?.detailContainsReason !== true) {
    fail('Request trace did not prove confirmed-action receipt visibility', confirmed);
  }
  if (!permission || permission.apiAudit?.model !== 'deterministic-permission-denied-receipt'
    || permission.apiAudit?.responseMeta?.skippedProviderCall !== true
    || permission.uiEvidence?.detailContainsReason !== true) {
    fail('Request trace did not prove permission-denied receipt visibility', permission);
  }
  return report;
};

const verifyFailureTrace = async (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('AI model settings failure trace gate failed', summary);
  if (Number(summary.caseCount) < 1 || Number(summary.passed) < 1) {
    fail('AI model settings failure trace gate did not cover an abnormal audit row', summary);
  }
  if (!summary.reportPath) fail('AI model settings failure trace gate did not write a report', summary);
  const report = await loadReport(summary.reportPath);
  if (report.modelPolicy?.doesNotTriggerProviderCalls !== true) {
    fail('Failure trace gate did not declare non-provider-call policy', report.modelPolicy);
  }
  for (const result of report.results || []) {
    if (!result.ok) continue;
    if (!['error', 'timeout'].includes(result.apiAudit?.status)) {
      fail('Failure trace result did not verify an abnormal audit status', result);
    }
    if (result.apiAudit?.responseMeta?.skippedProviderCall === true) {
      fail('Failure trace result unexpectedly marked skippedProviderCall', result);
    }
    if (result.uiEvidence?.detailContainsErrorMessage !== true) {
      fail('Failure trace result did not prove detail error-message visibility', result);
    }
  }
  return report;
};

const main = async () => {
  assertIsolatedBaseUrl();
  await mkdir(ARTIFACT_DIR, { recursive: true });

  const apiPermissionRun = await run(
    'assistant-write-permission-api-gate',
    ['run', 'verify:assistant-write-permission-api-gate'],
  );
  const apiPermissionSummary = extractLastJson(apiPermissionRun.stdout);
  verifyApiPermissionGate(apiPermissionSummary);

  const uiPermissionRun = await run(
    'assistant-ui-write-permission-gate',
    ['run', 'verify:assistant-ui-write-permission-gate'],
  );
  const uiPermissionSummary = extractLastJson(uiPermissionRun.stdout);
  const uiPermissionReport = await verifyUiPermissionGate(uiPermissionSummary);

  const traceRun = await run(
    'ai-model-settings-request-trace-browser',
    ['run', 'verify:ai-model-settings-request-trace-browser'],
    {
      env: {
        HRM_PERMISSION_REPORT: uiPermissionSummary.reportPath,
      },
    },
  );
  const traceSummary = extractLastJson(traceRun.stdout);
  const traceReport = await verifyRequestTrace(traceSummary);

  let failureTraceSummary = null;
  let failureTraceReport = null;
  if (INCLUDE_FAILURE_TRACE) {
    const failureTraceRun = await run(
      'ai-model-settings-failure-trace-browser',
      ['run', 'verify:ai-model-settings-failure-trace-browser'],
    );
    failureTraceSummary = extractLastJson(failureTraceRun.stdout);
    failureTraceReport = await verifyFailureTrace(failureTraceSummary);
  }

  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const reportPath = path.join(ARTIFACT_DIR, `assistant-governance-browser-acceptance-${stamp}.json`);
  const report = {
    ok: true,
    baseUrl: BASE_URL,
    protectedPorts: ['8080', '8443'],
    modelPolicy: {
      realModelEvidenceMustUseDeepSeekAudit: true,
      permissionDeniedShortCircuitsBeforeProvider: true,
      deterministicReceiptsMustMarkSkippedProviderCall: true,
      failureTraceGate: INCLUDE_FAILURE_TRACE ? 'included' : 'opt-in',
      note: 'This governance gate validates permission and audit traceability. It reuses prior real-model requestIds for trace checks instead of triggering extra model calls. Failure/timeout trace is opt-in until the updated AI Model Settings UI is deployed to the target baseUrl.',
    },
    apiPermissionGate: apiPermissionSummary,
    uiPermissionGate: uiPermissionSummary,
    requestTrace: traceSummary,
    failureTrace: failureTraceSummary || {
      skipped: true,
      reason: 'opt_in_required',
      enableWith: 'HRM_INCLUDE_FAILURE_TRACE_GATE=1',
      note: 'Enable after the target baseUrl serves the updated AI Model Settings UI with failure/timeout labels.',
    },
    evidence: {
      apiPermissionReportPath: apiPermissionSummary.reportPath,
      uiPermissionReportPath: uiPermissionSummary.reportPath,
      traceReportPath: traceSummary.reportPath,
      failureTraceReportPath: failureTraceSummary?.reportPath || null,
      uiPermissionRequestIds: (uiPermissionReport.results || []).map((item) => item.requestId).filter(Boolean),
      tracedRequestIds: (traceReport.results || []).map((item) => item.requestId).filter(Boolean),
      failureTraceRequestIds: failureTraceReport
        ? (failureTraceReport.results || []).map((item) => item.requestId).filter(Boolean)
        : [],
    },
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
