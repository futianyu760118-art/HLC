import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const QUESTION = process.env.HRM_ASSISTANT_FIELD_HISTORY_QUESTION
  || '给我看吴明华的员工画像，包含考勤、请假审批、绩效、薪资、异动和通知，并列出字段级证据。';
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const PLAYWRIGHT_MODULE_DIR = process.env.NODE_REPL_NODE_MODULE_DIRS
  || 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';
const PLAYWRIGHT_PNPM_MODULE_DIR = process.env.PLAYWRIGHT_PNPM_MODULE_DIR
  || path.join(PLAYWRIGHT_MODULE_DIR, '.pnpm', 'playwright@1.60.0', 'node_modules');
const EDGE_EXECUTABLE = process.env.HRM_BROWSER_EXECUTABLE
  || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const CASE_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_FIELD_HISTORY_TIMEOUT_MS || 190000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_FIELD_HISTORY_RUN_ID || `assistant-field-history-${stamp}`;

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedTarget = () => {
  if (/:(8080|8443)(?:\/|$)/.test(BASE_URL)) {
    fail('Refusing to run assistant field-citation/history E2E against old production ports', {
      baseUrl: BASE_URL,
    });
  }
};

const importPlaywright = async () => {
  try {
    return await import('playwright');
  } catch {
    const packageJson = path.join(PLAYWRIGHT_PNPM_MODULE_DIR, 'playwright', 'package.json');
    const runtimeRequire = createRequire(pathToFileURL(packageJson).href);
    return runtimeRequire('playwright');
  }
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const sanitize = (value) => String(value || '')
  .replace(/[^a-z0-9_-]+/gi, '-')
  .replace(/^-|-$/g, '')
  .slice(0, 80);

const asJson = async (response, label = response.url) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`${label} did not return JSON`, text.slice(0, 1000));
  }
};

const requestJson = async (method, pathName, payload, token, requestId) => {
  const response = await fetch(`${BASE_URL}${pathName}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
    body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`${method} ${pathName} failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  return asJson(response, pathName);
};

const login = async () => {
  const payload = await requestJson('POST', '/api/auth/login', { email: EMAIL, password: PASSWORD }, null, `${runId}-login`);
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  return payload;
};

const getJson = (pathName, token, requestId) => requestJson('GET', pathName, null, token, requestId);
const postJson = (pathName, payload, token, requestId) => requestJson('POST', pathName, payload, token, requestId);

const fetchAuditRow = async (token, requestId) => {
  const encoded = encodeURIComponent(requestId);
  for (let attempt = 1; attempt <= 18; attempt += 1) {
    const rows = await getJson(
      `/api/hrm/assistant/audit-logs?keyword=${encoded}&limit=20`,
      token,
      `${runId}-audit-${sanitize(requestId)}-${attempt}`,
    );
    const row = rows.find((item) => item.requestId === requestId && item.useCase === 'assistant_stream_answer');
    if (row) return row;
    await sleep(900);
  }
  fail('No assistant_stream_answer audit row found for UI request', { requestId });
};

const verifyAuditRow = (row) => {
  const meta = row.responseMeta || {};
  if (row.provider !== 'siliconflow') fail('UI assistant audit provider is not siliconflow', row);
  if (row.status !== 'success') fail('UI assistant audit status is not success', row);
  if (!row.model || !String(row.model).includes('DeepSeek')) fail('UI assistant audit model is not a DeepSeek SiliconFlow model', row);
  if (meta.stream !== true) fail('UI assistant audit responseMeta.stream is not true', row);
  if (!(Number(meta.chunkCount) > 0)) fail('UI assistant audit has no positive chunkCount', row);
};

const countFieldsFromSources = (sources) => (Array.isArray(sources) ? sources : [])
  .reduce((sum, source) => sum + (Array.isArray(source?.fields) ? source.fields.length : 0), 0);

const collectSourceCitationWidgets = (message) => {
  const widgets = Array.isArray(message?.widgets) ? message.widgets : [];
  const blocks = Array.isArray(message?.renderBlocks) ? message.renderBlocks : [];
  return [
    ...widgets.filter((widget) => widget?.type === 'source_citations'),
    ...blocks
      .map((block) => block?.payload)
      .filter((widget) => widget?.type === 'source_citations'),
  ];
};

const verifyPersistedSessionPayload = async (token, sessionId) => {
  if (!sessionId) fail('No sessionId was available for history replay verification');
  const detail = await getJson(`/api/hrm/assistant/sessions/${encodeURIComponent(sessionId)}`, token, `${runId}-session-detail`);
  const assistantMessages = (detail.messages || []).filter((item) => item?.role === 'assistant');
  const latest = assistantMessages.at(-1);
  if (!latest) fail('Persisted assistant session has no assistant message', detail);

  const widgets = Array.isArray(latest.widgets) ? latest.widgets : [];
  const renderBlocks = Array.isArray(latest.renderBlocks) ? latest.renderBlocks : [];
  const sourceWidgets = collectSourceCitationWidgets(latest);
  const fieldEvidenceCount = sourceWidgets.reduce((sum, widget) => {
    const sources = widget.sources || widget.data || [];
    return sum + countFieldsFromSources(sources);
  }, 0);
  const widgetTypes = Array.from(new Set(widgets.map((widget) => widget?.type).filter(Boolean)));
  const renderKinds = Array.from(new Set(renderBlocks.map((block) => block?.kind || block?.widgetType).filter(Boolean)));
  const sourceModules = Array.from(new Set(sourceWidgets.flatMap((widget) => (
    (widget.sources || widget.data || [])
      .map((source) => source?.module)
      .filter(Boolean)
  ))));
  const evaluationHints = latest.copilot?.evaluationHints || {};

  const requiredWidgetGroups = [
    { label: 'entity_cards', ok: widgetTypes.includes('entity_cards') || renderKinds.includes('entity_cards') },
    { label: 'kpi', ok: widgetTypes.includes('metrics') || widgetTypes.includes('metric_cards') || renderKinds.includes('kpi') },
    { label: 'status_badges', ok: widgetTypes.includes('status_badges') || renderKinds.includes('status') },
    { label: 'source_citations', ok: widgetTypes.includes('source_citations') || renderKinds.includes('sources') },
  ];
  const missingWidgets = requiredWidgetGroups.filter((item) => !item.ok).map((item) => item.label);
  if (missingWidgets.length) fail('Persisted assistant message is missing required rich widget types', {
    missingWidgets,
    widgetTypes,
    renderKinds,
  });
  if (!renderBlocks.length) fail('Persisted assistant message lost renderBlocks', { widgetTypes });
  if (fieldEvidenceCount < 8) fail('Persisted assistant message has too little field-level evidence', {
    fieldEvidenceCount,
    sourceModules,
  });
  if (Number(evaluationHints.fieldEvidenceCount || 0) < 8) {
    fail('Copilot evaluationHints.fieldEvidenceCount was not persisted', evaluationHints);
  }

  return {
    sessionId,
    assistantMessageCount: assistantMessages.length,
    widgetTypes,
    renderKinds,
    sourceModules,
    fieldEvidenceCount,
    evaluationHints: {
      evidenceCount: evaluationHints.evidenceCount,
      fieldEvidenceCount: evaluationHints.fieldEvidenceCount,
      widgetTypes: evaluationHints.widgetTypes,
      needsRootCauseReview: evaluationHints.needsRootCauseReview,
    },
  };
};

const queryCount = async (locator) => locator.count().catch(() => 0);

const panelSnapshot = async (panel) => {
  const text = await panel.innerText({ timeout: 5000 }).catch(() => '');
  const normalizedText = compact(text);
  const sourceMarkers = ['证据来源', '本次使用的系统记录', '字段级证据'];
  const fieldLabels = ['工号', '部门', '岗位', '员工状态', '异常考勤数', '最近等级', '最近得分', '薪资档案', '薪资合计'];
  return {
    text: normalizedText,
    tableCount: await queryCount(panel.locator('table')),
    sourceBoxCount: sourceMarkers.filter((marker) => normalizedText.includes(marker)).length,
    fieldLabelCount: fieldLabels.filter((label) => normalizedText.includes(label)).length,
    timelineCount: normalizedText.includes('关键履历时间线') ? 1 : 0,
    loadingCount: await queryCount(panel.locator('.fa-circle-notch.fa-spin, .fa-spinner.fa-spin')),
  };
};

const waitForRichProfileUi = async (panel, label) => {
  const deadline = Date.now() + CASE_TIMEOUT_MS;
  let last = null;
  while (Date.now() < deadline) {
    last = await panelSnapshot(panel);
    const ready = last.text.includes('吴明华')
      && last.text.includes('员工画像')
      && last.text.includes('证据来源')
      && last.text.includes('本次使用的系统记录')
      && last.text.includes('薪资档案')
      && last.text.includes('绩效')
      && last.text.includes('考勤')
      && last.tableCount >= 2
      && last.fieldLabelCount >= 4
      && last.loadingCount === 0;
    if (ready) return last;
    await sleep(1000);
  }
  fail(`${label} did not render employee profile rich UI with field-level evidence`, {
    snapshot: last,
    textSample: last?.text?.slice(0, 1800),
  });
};

const parseAssistantRequest = (request) => {
  try {
    return JSON.parse(request.postData() || '{}');
  } catch {
    return {};
  }
};

const openAssistant = async (page) => {
  await page.locator('.hpt-ai-assistant-toggle').click({ timeout: 10000 });
  const panel = page.locator('.hpt-ai-assistant-panel');
  await panel.waitFor({ state: 'visible', timeout: 10000 });
  return panel;
};

const submitQuestionAndVerify = async (page, token) => {
  await page.goto(`${BASE_URL}/hrm/employees`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForSelector('main.hpt-main', { timeout: 30000 });
  await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);
  const panel = await openAssistant(page);
  const textarea = panel.locator('textarea').first();
  await textarea.fill(QUESTION, { timeout: 10000 });

  const requestPromise = page.waitForRequest((request) => {
    if (request.method() !== 'POST') return false;
    if (!request.url().includes('/api/hrm/assistant/query')) return false;
    const payload = parseAssistantRequest(request);
    return payload.stream === true && payload.question === QUESTION;
  }, { timeout: 15000 });

  await textarea.press('Enter', { timeout: 10000 });
  const assistantRequest = await requestPromise;
  const requestId = assistantRequest.headers()['x-request-id'];
  if (!requestId) fail('UI assistant request did not include X-Request-ID');

  const ui = await waitForRichProfileUi(panel, 'Initial assistant answer');
  const screenshotPath = path.join(ARTIFACT_DIR, `${runId}-initial-rich-answer.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
  const audit = await fetchAuditRow(token, requestId);
  verifyAuditRow(audit);

  return {
    requestId,
    sessionId: audit.sessionId,
    screenshotPath,
    uiSignals: {
      tableCount: ui.tableCount,
      fieldLabelCount: ui.fieldLabelCount,
      sourceBoxCount: ui.sourceBoxCount,
      timelineCount: ui.timelineCount,
    },
    audit: {
      id: audit.id,
      provider: audit.provider,
      model: audit.model,
      useCase: audit.useCase,
      status: audit.status,
      latencyMs: audit.latencyMs,
      chunkCount: audit.responseMeta?.chunkCount,
      sessionId: audit.sessionId,
    },
  };
};

const verifyHistoryReplay = async (context, sessionId, token) => {
  const sessions = await getJson('/api/hrm/assistant/sessions', token, `${runId}-sessions-before-replay`);
  if (!Array.isArray(sessions) || !sessions.some((item) => item.id === sessionId)) {
    fail('Assistant session list did not include the session selected for history replay', {
      sessionId,
      sessions: Array.isArray(sessions) ? sessions.slice(0, 5) : sessions,
    });
  }
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && !/favicon\.ico|ResizeObserver loop|net::ERR_ABORTED/i.test(message.text())) {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error?.stack || error?.message || String(error)));

  try {
    await page.addInitScript((targetSessionId) => {
      for (const store of [window.localStorage, window.sessionStorage]) {
        for (const key of Object.keys(store)) {
          if (key.startsWith('ai_assistant_history:')) store.removeItem(key);
        }
      }
      window.sessionStorage.setItem('ai_assistant_open', '0');
      const user = JSON.parse(window.localStorage.getItem('user') || 'null');
      if (user?.id && targetSessionId) {
        window.localStorage.setItem(`ai_assistant_session:user:${user.id}`, targetSessionId);
      }
    }, sessionId);
    await page.goto(`${BASE_URL}/hrm/employees`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('main.hpt-main', { timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => null);
    const panel = await openAssistant(page);
    await panel.locator('text=员工画像').first().waitFor({ state: 'visible', timeout: 20000 });
    const ui = await waitForRichProfileUi(panel, 'History replay answer');
    const screenshotPath = path.join(ARTIFACT_DIR, `${runId}-history-rich-replay.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);

    if (consoleErrors.length || pageErrors.length) {
      fail('History replay page emitted browser errors', {
        consoleErrors,
        pageErrors,
        screenshotPath,
      });
    }
    return {
      screenshotPath,
      replaySource: 'server_session_auto_hydration',
      uiSignals: {
        tableCount: ui.tableCount,
        fieldLabelCount: ui.fieldLabelCount,
        sourceBoxCount: ui.sourceBoxCount,
        timelineCount: ui.timelineCount,
      },
    };
  } finally {
    await page.close().catch(() => null);
  }
};

const main = async () => {
  assertIsolatedTarget();
  await mkdir(ARTIFACT_DIR, { recursive: true });
  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const { chromium } = await importPlaywright();
  const auth = await login();
  const freshSession = await postJson('/api/hrm/assistant/sessions/new', {}, auth.token, `${runId}-new-session`);

  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ token, user, sessionId }) => {
    window.localStorage.setItem('token', token);
    window.localStorage.setItem('user', JSON.stringify(user));
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.startsWith('ai_assistant_')) store.removeItem(key);
      }
    }
    window.localStorage.setItem(`ai_assistant_session:user:${user.id}`, sessionId);
    window.sessionStorage.setItem('ai_assistant_open', '0');
  }, { token: auth.token, user: auth.user, sessionId: freshSession.id });

  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && !/favicon\.ico|ResizeObserver loop|net::ERR_ABORTED/i.test(message.text())) {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error?.stack || error?.message || String(error)));

  try {
    const initial = await submitQuestionAndVerify(page, auth.token);
    if (consoleErrors.length || pageErrors.length) {
      fail('Initial assistant page emitted browser errors', {
        consoleErrors,
        pageErrors,
        screenshotPath: initial.screenshotPath,
      });
    }
    const sessionId = initial.sessionId || freshSession.id;
    const persisted = await verifyPersistedSessionPayload(auth.token, sessionId);
    const historyReplay = await verifyHistoryReplay(context, sessionId, auth.token);
    const report = {
      ok: true,
      runId,
      baseUrl: BASE_URL,
      checkedAt: new Date().toISOString(),
      question: QUESTION,
      initial,
      persisted,
      historyReplay,
      reportPath,
      aiModelSettingsKeyword: initial.requestId,
      aiModelSettingsPage: `${BASE_URL}/ai-model-settings`,
    };
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify({
      ok: true,
      runId,
      baseUrl: BASE_URL,
      requestId: initial.requestId,
      sessionId,
      provider: initial.audit.provider,
      model: initial.audit.model,
      chunkCount: initial.audit.chunkCount,
      fieldEvidenceCount: persisted.fieldEvidenceCount,
      widgetTypes: persisted.widgetTypes,
      sourceModules: persisted.sourceModules,
      initialScreenshot: initial.screenshotPath,
      historyScreenshot: historyReplay.screenshotPath,
      reportPath,
      aiModelSettingsLookup: `${BASE_URL}/ai-model-settings`,
    }, null, 2));
  } finally {
    await page.close().catch(() => null);
    await browser.close().catch(() => null);
  }
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
