const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const QUESTION = process.env.HRM_TEST_QUESTION || '吴明华最近考勤异常吗？请给证据，并说明相关入口。';

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const requestId = process.env.HRM_TEST_REQUEST_ID || `real-sf-main-${stamp}-${Math.random().toString(36).slice(2, 8)}`;
const sessionId = process.env.HRM_TEST_SESSION_ID || `real-sf-session-${stamp}`;

const fail = (message, details) => {
  if (details) {
    console.error(details);
  }
  throw new Error(message);
};

const asJson = async (response) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`Expected JSON from ${response.url}, got: ${text.slice(0, 300)}`);
  }
};

const postJson = async (path, payload, headers = {}) => {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    fail(`${path} failed with HTTP ${response.status}`, text.slice(0, 600));
  }
  return response;
};

const login = async () => {
  const response = await postJson('/api/auth/login', { email: EMAIL, password: PASSWORD }, {
    'X-Request-ID': `${requestId}-login`,
  });
  const payload = await asJson(response);
  if (!payload.token) fail('Login succeeded but no token was returned');
  return payload.token;
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
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = { content: text };
  }
  return { event, payload };
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

const streamAssistant = async (token) => {
  const response = await fetch(`${BASE_URL}/api/hrm/assistant/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream, application/json',
      Authorization: `Bearer ${token}`,
      'X-Request-ID': requestId,
    },
    body: JSON.stringify({
      question: QUESTION,
      sessionId,
      stream: true,
      clientContext: {
        path: '/attendance-stats',
        route: '/attendance-stats',
        moduleName: '考勤统计',
        visibleFilters: {
          employee: '吴明华',
          month: '最近',
        },
        smokeTest: 'real_siliconflow_main_assistant',
      },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    fail(`assistant/query failed with HTTP ${response.status}`, text.slice(0, 1000));
  }
  if (!response.body) fail('assistant/query did not return a readable stream');

  const decoder = new TextDecoder('utf-8');
  const reader = response.body.getReader();
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

  if (deltaCount < 1) fail('No SSE delta chunks were received from the main assistant');
  if (!finalPayload) fail('No final assistant payload was received');

  const entityTitles = (finalPayload.entities || []).map((item) => item.title).filter(Boolean);
  const usedSkills = finalPayload.meta?.usedSkills || [];
  const responseGeneration = finalPayload.copilot?.responseGeneration || {};
  const answerText = String(finalPayload.summary || finalPayload.answer?.content || deltaText || '');

  if (!entityTitles.includes('吴明华')) {
    fail('Final payload did not preserve the explicit employee entity 吴明华', { entityTitles, summary: answerText.slice(0, 300) });
  }
  if (!usedSkills.includes('employee_attendance_evidence')) {
    fail('Final payload did not use employee_attendance_evidence for the explicit employee attendance question', { usedSkills });
  }
  if (responseGeneration.useCase !== 'assistant_stream_answer') {
    fail('Final payload did not mark the streamed SiliconFlow answer use case', responseGeneration);
  }

  return {
    deltaCount,
    deltaChars: deltaText.length,
    statuses,
    entityTitles,
    usedSkills,
    responseGeneration,
    finalPayload,
  };
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const fetchAudit = async (token) => {
  const encoded = encodeURIComponent(requestId);
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    const response = await fetch(`${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encoded}&limit=10`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Request-ID': `${requestId}-audit-${attempt}`,
      },
    });
    if (!response.ok) {
      const text = await response.text();
      fail(`audit-logs failed with HTTP ${response.status}`, text.slice(0, 600));
    }
    const rows = await asJson(response);
    const row = rows.find((item) => item.requestId === requestId && item.useCase === 'assistant_stream_answer');
    if (row) return row;
    await sleep(700);
  }
  fail('No assistant_stream_answer audit row was found for the request id', { requestId });
};

const verifyAudit = (row) => {
  const meta = row.responseMeta || {};
  if (row.provider !== 'siliconflow') fail('Audit row provider is not siliconflow', row);
  if (row.status !== 'success') fail('Audit row is not successful', row);
  if (!row.model || !String(row.model).includes('DeepSeek')) fail('Audit row does not show the configured DeepSeek model', row);
  if (meta.stream !== true) fail('Audit row responseMeta.stream is not true', row);
  if (!(Number(meta.chunkCount) > 0)) fail('Audit row responseMeta.chunkCount is missing or zero', row);
};

const main = async () => {
  console.log(`Running real SiliconFlow assistant smoke against ${BASE_URL}`);
  console.log(`Request ID: ${requestId}`);
  const token = await login();
  const streamResult = await streamAssistant(token);
  const audit = await fetchAudit(token);
  verifyAudit(audit);

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
    entityTitles: streamResult.entityTitles,
    usedSkills: streamResult.usedSkills,
    auditLookup: `${BASE_URL}/api/hrm/assistant/audit-logs?keyword=${encodeURIComponent(requestId)}&limit=10`,
    page: `${BASE_URL}/ai-model-settings`,
  };
  console.log(JSON.stringify(summary, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
