const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMPLOYEE_EMAIL = process.env.HRM_EMPLOYEE_TEST_EMAIL || 'employee@hengpintong.demo';
const EMPLOYEE_PASSWORD = process.env.HRM_EMPLOYEE_TEST_PASSWORD || 'Demo@123456';
const ADMIN_EMAIL = process.env.HRM_ADMIN_TEST_EMAIL || process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const ADMIN_PASSWORD = process.env.HRM_ADMIN_TEST_PASSWORD || process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const QUESTION = process.env.HRM_TEST_QUESTION
  || '我是普通员工，请查看我的考勤、绩效和工资条，说明哪些能看、哪些不能看，并给证据来源。';
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_EVALUATION_REQUEST_TIMEOUT_MS || 180000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const requestId = process.env.HRM_TEST_REQUEST_ID
  || `employee-self-sf-${stamp}-${Math.random().toString(36).slice(2, 8)}`;
const sessionId = process.env.HRM_TEST_SESSION_ID || `employee-self-session-${stamp}`;

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

const postJson = async (path, payload, token, id) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(id ? { 'X-Request-ID': id } : {}),
      },
      body: JSON.stringify(payload || {}),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') {
      fail(`${path} exceeded ${REQUEST_TIMEOUT_MS}ms request timeout`, { requestId: id });
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

const login = async (email, password, suffix) => {
  const payload = await asJson(await postJson(
    '/api/auth/login',
    { email, password },
    null,
    `${requestId}-login-${suffix}`,
  ));
  if (!payload.token) fail(`Login for ${suffix} succeeded but no token was returned`);
  return { token: payload.token, user: payload.user || null };
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

const streamEmployeeSelfService = async (employeeToken) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${BASE_URL}/api/hrm/assistant/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream, application/json',
        Authorization: `Bearer ${employeeToken}`,
        'X-Request-ID': requestId,
      },
      body: JSON.stringify({
        question: QUESTION,
        sessionId,
        stream: true,
        clientContext: {
          path: '/employee-self-service',
          route: '/employee-self-service',
          moduleName: '员工自助',
          smokeTest: 'real_siliconflow_employee_self_service',
          requestId,
        },
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') {
      fail(`assistant/query exceeded ${REQUEST_TIMEOUT_MS}ms request timeout`, { requestId });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const text = await response.text();
    fail(`assistant/query failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  if (!response.body) fail('assistant/query did not return a readable stream');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let deltaText = '';
  let deltaCount = 0;
  let finalPayload = null;
  const statuses = [];

  const onEvent = ({ event, payload }) => {
    if (event === 'status') {
      statuses.push(payload.message || payload.content || '');
      return;
    }
    if (event === 'delta') {
      deltaCount += 1;
      deltaText += payload.content || '';
      return;
    }
    if (event === 'final') {
      finalPayload = payload;
      return;
    }
    if (event === 'error') {
      fail(`assistant/query stream error: ${payload.error || payload.content || 'unknown error'}`);
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

  if (deltaCount < 1) fail('No SSE delta chunks were received from SiliconFlow assistant stream');
  if (!finalPayload) fail('No final assistant payload was received');

  return { finalPayload, deltaCount, deltaChars: deltaText.length, statuses };
};

const widgetTypes = (payload) => (payload.widgets || [])
  .map((item) => item?.type)
  .filter(Boolean);

const renderKinds = (payload) => (payload.renderBlocks || [])
  .map((item) => item?.kind || item?.widgetType)
  .filter(Boolean);

const verifyEmployeePayload = ({ finalPayload, deltaCount }) => {
  const meta = finalPayload.meta || {};
  const routeDecision = meta.routeDecision || {};
  const usedSkills = meta.usedSkills || [];
  const kinds = renderKinds(finalPayload);
  const types = widgetTypes(finalPayload);
  const evidence = finalPayload.copilot?.evidence || [];
  const answerText = String(finalPayload.summary || finalPayload.answer?.content || '');

  if (routeDecision.intent !== 'employee.self_service.multi_topic') {
    fail('Employee self-service query did not route to employee.self_service.multi_topic', {
      intent: routeDecision.intent,
      routeDecision,
      summary: answerText.slice(0, 500),
    });
  }
  for (const skill of ['attendance_analysis', 'performance_analysis', 'payroll_analysis']) {
    if (!usedSkills.includes(skill)) {
      fail(`Employee self-service query did not use ${skill}`, { usedSkills });
    }
  }
  if (usedSkills.includes('payroll_performance_link')) {
    fail('Employee self-service query was incorrectly stolen by payroll_performance_link', { usedSkills });
  }
  if (!Array.isArray(routeDecision.safetyFlags) || !routeDecision.safetyFlags.includes('permission_denied')) {
    fail('Employee self-service route did not expose a permission_denied boundary', { routeDecision });
  }
  if (!/考勤/.test(answerText) || !/绩效/.test(answerText)) {
    fail('Streamed answer did not explain visible attendance and performance topics', {
      summary: answerText.slice(0, 800),
    });
  }
  if (!/(工资条|薪酬|薪资|工资)/.test(answerText) || !/(不能|不可|无权限|权限限制|拒绝)/.test(answerText)) {
    fail('Streamed answer did not explain the salary/payroll permission boundary', {
      summary: answerText.slice(0, 800),
    });
  }
  for (const required of ['status_badges', 'source_citations', 'warning', 'follow_up_actions']) {
    if (!types.includes(required)) {
      fail(`Employee self-service response is missing widget type ${required}`, { types, kinds });
    }
  }
  for (const required of ['status', 'sources', 'notice', 'actions']) {
    if (!kinds.includes(required)) {
      fail(`Employee self-service response is missing render block kind ${required}`, { types, kinds });
    }
  }
  if (evidence.length < 3) {
    fail('Employee self-service response did not provide enough evidence sources', { evidence });
  }
  if (deltaCount < 1 || finalPayload.copilot?.responseGeneration?.useCase !== 'assistant_stream_answer') {
    fail('Final payload did not mark the streamed SiliconFlow answer use case', {
      deltaCount,
      responseGeneration: finalPayload.copilot?.responseGeneration,
    });
  }

  return { usedSkills, kinds, types, evidenceCount: evidence.length, routeDecision };
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const fetchAuditRows = async (adminToken, keyword, limit = 20) => {
  const encoded = encodeURIComponent(keyword);
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    const response = await fetch(`${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encoded}&limit=${limit}`, {
      headers: {
        Authorization: `Bearer ${adminToken}`,
        'X-Request-ID': `${requestId}-audit-${attempt}`,
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

const verifyAudit = (rows) => {
  const row = rows.find((item) => item.requestId === requestId && item.useCase === 'assistant_stream_answer');
  if (!row) fail('No assistant_stream_answer audit row was found for the employee request id', { requestId, rows });
  if (row.provider !== 'siliconflow') fail('Audit row provider is not siliconflow', row);
  if (row.status !== 'success') fail('Audit row status is not success', row);
  if (!row.model || !String(row.model).includes('DeepSeek')) {
    fail('Audit row does not show the configured DeepSeek SiliconFlow model', row);
  }
  if (row.responseMeta?.stream !== true) fail('Streaming audit row is missing responseMeta.stream=true', row);
  if (!(Number(row.responseMeta?.chunkCount) > 0)) fail('Streaming audit row is missing chunkCount', row);
  return row;
};

const main = async () => {
  console.log(`Running real SiliconFlow employee self-service verification against ${BASE_URL}`);
  console.log(`Request ID: ${requestId}`);
  const employeeLogin = await login(EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD, 'employee');
  const adminLogin = await login(ADMIN_EMAIL, ADMIN_PASSWORD, 'admin');
  if (employeeLogin.user?.role && employeeLogin.user.role !== 'employee') {
    fail('Employee test account did not log in with employee role', employeeLogin.user);
  }

  const streamResult = await streamEmployeeSelfService(employeeLogin.token);
  const payloadCheck = verifyEmployeePayload(streamResult);
  const audit = verifyAudit(await fetchAuditRows(adminLogin.token, requestId));

  const summary = {
    ok: true,
    requestId,
    question: QUESTION,
    provider: audit.provider,
    model: audit.model,
    useCase: audit.useCase,
    status: audit.status,
    latencyMs: audit.latencyMs,
    promptChars: audit.promptChars,
    responseChars: audit.responseChars,
    chunkCount: audit.responseMeta?.chunkCount,
    deltaCount: streamResult.deltaCount,
    deltaChars: streamResult.deltaChars,
    intent: payloadCheck.routeDecision.intent,
    safetyFlags: payloadCheck.routeDecision.safetyFlags || [],
    usedSkills: payloadCheck.usedSkills,
    widgetTypes: payloadCheck.types,
    renderKinds: payloadCheck.kinds,
    evidenceCount: payloadCheck.evidenceCount,
    auditLookup: `${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(requestId)}&limit=20`,
    page: `${BASE_URL}/ai-model-settings`,
  };
  console.log(JSON.stringify(summary, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
