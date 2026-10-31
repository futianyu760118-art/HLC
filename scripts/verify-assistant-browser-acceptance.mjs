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
    fail('Refusing to run assistant browser acceptance against old production ports', { baseUrl: BASE_URL });
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

const verifyModuleSmoke = (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('HRM module browser smoke failed', summary);
  if (Number(summary.routeCount) < 36 || Number(summary.passed) < 36) {
    fail('HRM module browser smoke did not cover all expected core routes', summary);
  }
  if (!summary.reportPath) fail('HRM module browser smoke did not write a report', summary);
};

const verifyAssistantUi = (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('Assistant UI browser E2E failed', summary);
  if (Number(summary.caseCount) < 3 || Number(summary.passed) < 3) {
    fail('Assistant UI browser E2E did not cover all expected cases', summary);
  }
  if (!Array.isArray(summary.requestIds) || summary.requestIds.length < 3) {
    fail('Assistant UI browser E2E did not return request IDs', summary);
  }
};

const verifyFieldHistory = (summary) => {
  if (!summary?.ok || !summary.requestId || !summary.sessionId) {
    fail('Assistant field-citation history E2E summary is not ok', summary);
  }
  if (summary.provider !== 'siliconflow' || !String(summary.model || '').includes('DeepSeek')) {
    fail('Assistant field-citation history E2E did not audit SiliconFlow DeepSeek usage', summary);
  }
  if (!(Number(summary.chunkCount) > 0)) fail('Assistant field-citation history E2E has no positive chunkCount', summary);
  if (!(Number(summary.fieldEvidenceCount) >= 8)) {
    fail('Assistant field-citation history E2E has too little field evidence', summary);
  }
  const widgetTypes = summary.widgetTypes || [];
  for (const widget of ['entity_cards', 'source_citations']) {
    if (!widgetTypes.includes(widget)) fail(`Assistant field-citation history E2E missing widget ${widget}`, summary);
  }
  const modules = summary.sourceModules || [];
  for (const moduleName of ['employees', 'attendance_records', 'performance_reviews', 'salary_profiles', 'notifications']) {
    if (!modules.includes(moduleName)) fail(`Assistant field-citation history E2E missing source module ${moduleName}`, summary);
  }
};

const verifySideEffectAcceptance = (summary) => {
  if (!summary?.ok || Number(summary.failed) !== 0) fail('Assistant side-effect browser acceptance failed', summary);
  if (Number(summary.sideEffectCaseCount) < 5 || Number(summary.passed) < 5) {
    fail('Assistant side-effect browser acceptance did not cover all expected write confirmation cases', summary);
  }
  if (!Array.isArray(summary.cases) || summary.cases.length < 5) {
    fail('Assistant side-effect browser acceptance did not return case results', summary);
  }
  for (const caseResult of summary.cases) {
    if (!caseResult.ok || !caseResult.reportPath || !caseResult.requestIds) {
      fail('Assistant side-effect browser acceptance case is missing core evidence', caseResult);
    }
  }
};

const main = async () => {
  assertIsolatedBaseUrl();
  await mkdir(ARTIFACT_DIR, { recursive: true });

  const moduleRun = await run('hrm-module-browser-smoke', ['run', 'verify:hrm-module-browser-smoke']);
  const moduleSummary = extractLastJson(moduleRun.stdout);
  verifyModuleSmoke(moduleSummary);

  const assistantUiRun = await run('assistant-ui-browser-e2e', ['run', 'verify:assistant-ui-browser-e2e']);
  const assistantUiSummary = extractLastJson(assistantUiRun.stdout);
  verifyAssistantUi(assistantUiSummary);

  const fieldHistoryRun = await run(
    'assistant-ui-field-citations-history-e2e',
    ['run', 'verify:assistant-ui-field-citations-history-e2e'],
  );
  const fieldHistorySummary = extractLastJson(fieldHistoryRun.stdout);
  verifyFieldHistory(fieldHistorySummary);

  const sideEffectRun = await run(
    'assistant-side-effect-browser-acceptance',
    ['run', 'verify:assistant-side-effect-browser-acceptance'],
  );
  const sideEffectSummary = extractLastJson(sideEffectRun.stdout);
  verifySideEffectAcceptance(sideEffectSummary);

  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const reportPath = path.join(ARTIFACT_DIR, `assistant-browser-acceptance-${stamp}.json`);
  const report = {
    ok: true,
    baseUrl: BASE_URL,
    moduleSmoke: moduleSummary,
    assistantUi: assistantUiSummary,
    fieldCitationHistory: fieldHistorySummary,
    sideEffectAcceptance: sideEffectSummary,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
