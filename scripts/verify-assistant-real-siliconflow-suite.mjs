const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const EVALUATION_TIMEOUT_MS = Number(process.env.HRM_EVALUATION_REQUEST_TIMEOUT_MS || 180000);
const DEFAULT_CASES = [
  'attendance_employee_anomaly',
  'employee_profile_cross_module',
  'recruitment_match_matrix',
  'payroll_performance_link',
  'confirmed_attendance_notification_execution',
];
const CASE_IDS = (process.env.HRM_EVAL_CASE_IDS || '')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);
const EVAL_CASES = CASE_IDS.length ? CASE_IDS : DEFAULT_CASES;

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const suiteId = process.env.HRM_TEST_SUITE_ID || `sf-suite-${stamp}-${Math.random().toString(36).slice(2, 8)}`;

const fail = (message, details) => {
  if (details) {
    console.error(JSON.stringify(details, null, 2));
  }
  throw new Error(message);
};

const asJson = async (response) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`Expected JSON from ${response.url}, got: ${text.slice(0, 500)}`);
  }
};

const postJson = async (path, payload, token, requestId) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), EVALUATION_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(requestId ? { 'X-Request-ID': requestId } : {}),
      },
      body: JSON.stringify(payload || {}),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') {
      fail(`${path} exceeded ${EVALUATION_TIMEOUT_MS}ms request timeout`, { requestId });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const text = await response.text();
    fail(`${path} failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  return response;
};

const login = async () => {
  const response = await postJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, null, `${suiteId}-login`);
  const payload = await asJson(response);
  if (!payload.token) fail('Login succeeded but no token was returned');
  return payload.token;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const fetchAuditRows = async (token, keyword, limit = 20) => {
  const encoded = encodeURIComponent(keyword);
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    const response = await fetch(`${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encoded}&limit=${limit}`, {
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

const verifyAuditRow = (row, { requestId, useCase, stream = false }) => {
  if (!row) fail(`Missing audit row for ${useCase}`, { requestId });
  if (requestId && row.requestId !== requestId) fail('Audit row requestId mismatch', row);
  if (row.provider !== 'siliconflow') fail('Audit row provider is not siliconflow', row);
  if (row.useCase !== useCase) fail('Audit row useCase mismatch', row);
  if (row.status !== 'success') fail('Audit row status is not success', row);
  if (!row.model || !String(row.model).includes('DeepSeek')) fail('Audit row does not show a DeepSeek SiliconFlow model', row);
  if (stream && row.responseMeta?.stream !== true) fail('Streaming audit row is missing responseMeta.stream=true', row);
  if (stream && !(Number(row.responseMeta?.chunkCount) > 0)) fail('Streaming audit row is missing chunkCount', row);
  return row;
};

const runModelCallDiagnostic = async (token) => {
  const requestId = `${suiteId}-diag`;
  const prompt = `【${suiteId}】请用一句话确认 HRM Copilot 正在真实调用硅基流动大模型。`;
  const payload = await asJson(await postJson('/api/hrm/assistant/model-call-test', {
    prompt,
    modelProfile: 'strong',
    clientContext: {
      path: '/ai-model-settings',
      moduleName: 'AI 模型管理',
      smokeTest: 'real_siliconflow_suite_model_call',
      suiteId,
    },
  }, token, requestId));
  if (!payload.ok) fail('Model call diagnostic did not return ok=true', payload);
  const rows = await fetchAuditRows(token, requestId);
  const audit = verifyAuditRow(rows.find((item) => item.requestId === requestId && item.useCase === 'model_call_test'), {
    requestId,
    useCase: 'model_call_test',
  });
  return { ...payload, auditLogId: audit.id, status: audit.status, provider: audit.provider };
};

const parseSseEvent = (raw) => {
  const lines = raw.split(/\r?\n/);
  let event = 'message';
  const data = [];
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  const text = data.join('\n');
  try {
    return { event, payload: JSON.parse(text) };
  } catch {
    return { event, payload: { content: text } };
  }
};

const drainEvents = (buffer, onEvent, flush = false) => {
  const parts = buffer.split(/\r?\n\r?\n/);
  const complete = flush ? parts : parts.slice(0, -1);
  for (const raw of complete) {
    const event = parseSseEvent(raw.trim());
    if (event) onEvent(event);
  }
  return flush ? '' : parts[parts.length - 1];
};

const runModelStreamDiagnostic = async (token) => {
  const requestId = `${suiteId}-stream`;
  const response = await fetch(`${BASE_URL}/api/hrm/assistant/model-stream-test`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`,
      'X-Request-ID': requestId,
    },
    body: JSON.stringify({
      prompt: `【${suiteId}】请流式确认 HRM Copilot 正在真实调用硅基流动大模型。`,
      modelProfile: 'strong',
      clientContext: {
        path: '/ai-model-settings',
        moduleName: 'AI 模型管理',
        smokeTest: 'real_siliconflow_suite_model_stream',
        suiteId,
      },
    }),
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`model-stream-test failed with HTTP ${response.status}`, text.slice(0, 1000));
  }
  if (!response.body) fail('model-stream-test did not return a readable stream');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let deltaCount = 0;
  let deltaText = '';
  let finalPayload = null;
  const onEvent = ({ event, payload }) => {
    if (event === 'delta') {
      deltaCount += 1;
      deltaText += payload.content || '';
    } else if (event === 'final') {
      finalPayload = payload;
    } else if (event === 'error') {
      fail(`model-stream-test returned an SSE error: ${payload.error || payload.content}`);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = drainEvents(buffer, onEvent);
  }
  buffer += decoder.decode();
  drainEvents(buffer, onEvent, true);

  if (deltaCount < 1) fail('No streaming delta chunks were received from SiliconFlow diagnostic');
  if (!finalPayload?.ok) fail('Streaming diagnostic final payload is not ok', { finalPayload, deltaText });
  const rows = await fetchAuditRows(token, requestId);
  const audit = verifyAuditRow(rows.find((item) => item.requestId === requestId && item.useCase === 'model_stream_test'), {
    requestId,
    useCase: 'model_stream_test',
    stream: true,
  });
  return { ...finalPayload, deltaCount, auditLogId: audit.id, provider: audit.provider, status: audit.status };
};

const runEvaluationCase = async (token, caseId, index) => {
  const payload = await asJson(await postJson('/api/hrm/assistant/evaluation-runs', {
    caseId,
    clientContext: {
      path: '/ai-model-settings',
      moduleName: 'AI 模型管理',
      smokeTest: 'real_siliconflow_suite_evaluation',
      suiteId,
      suiteIndex: index,
    },
  }, token, `${suiteId}-case-${index}`));
  if (!payload.requestId) fail('Evaluation run did not return requestId', payload);
  if (payload.passStatus !== 'pass') fail(`Evaluation case ${caseId} did not pass`, payload);
  const evaluationAudit = payload.evaluationAudit || {};
  if (evaluationAudit.provider !== 'siliconflow') fail(`Evaluation case ${caseId} did not record siliconflow provider`, payload);
  if (evaluationAudit.useCase !== 'copilot_evaluation') fail(`Evaluation case ${caseId} did not record copilot_evaluation useCase`, payload);
  if (evaluationAudit.status !== 'success' || evaluationAudit.ok !== true || !evaluationAudit.auditLogId) {
    fail(`Evaluation case ${caseId} does not have a successful real model audit`, payload);
  }
  const rows = await fetchAuditRows(token, payload.requestId);
  const audit = verifyAuditRow(rows.find((item) => item.requestId === payload.requestId && item.useCase === 'copilot_evaluation'), {
    requestId: payload.requestId,
    useCase: 'copilot_evaluation',
  });
  return {
    caseId,
    passStatus: payload.passStatus,
    requestId: payload.requestId,
    auditLogId: audit.id,
    provider: audit.provider,
    model: audit.model,
    status: audit.status,
    actualModules: payload.actualModules || [],
    actualRenderBlocks: payload.actualRenderBlocks || [],
  };
};

const main = async () => {
  console.log(`Running real SiliconFlow verification suite against ${BASE_URL}`);
  console.log(`Suite ID: ${suiteId}`);
  console.log(`Evaluation cases: ${EVAL_CASES.join(', ')}`);
  const token = await login();
  const diagnostics = [
    await runModelCallDiagnostic(token),
    await runModelStreamDiagnostic(token),
  ];
  const evaluations = [];
  for (const [index, caseId] of EVAL_CASES.entries()) {
    evaluations.push(await runEvaluationCase(token, caseId, index + 1));
  }
  const summary = {
    ok: true,
    suiteId,
    baseUrl: BASE_URL,
    diagnostics,
    evaluations,
    auditLookup: `${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(suiteId)}&limit=50`,
    evaluationPage: `${BASE_URL}/ai-model-settings`,
  };
  console.log(JSON.stringify(summary, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
