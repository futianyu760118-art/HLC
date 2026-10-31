const DEFAULT_BASE_URL = ['http://localhost:', '18280'].join('');
const FORBIDDEN_BASE_URL = ['localhost:', '18080'].join('');
const BASE_URL = (process.env.HRM_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, '');

if (BASE_URL.includes(FORBIDDEN_BASE_URL)) {
  throw new Error('Refusing runtime observability check against 18080 from HRM-saas');
}

const endpoints = ['/api/health', '/api/ready'];

const uniqueRequestId = (path) => {
  const suffix = path.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '');
  return `observability-${suffix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const checkJson = async (path) => {
  const sentRequestId = uniqueRequestId(path);
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'X-Request-ID': sentRequestId },
  });
  const responseRequestId = response.headers.get('x-request-id') || '';
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    throw new Error(`${path} did not return valid JSON: ${error.message}`);
  }
  return {
    path,
    status: response.status,
    sentRequestId,
    responseRequestId,
    body,
  };
};

const results = [];
for (const path of endpoints) {
  const result = await checkJson(path);
  console.log(JSON.stringify(result));
  results.push(result);
}

for (const result of results) {
  if (result.status >= 400) {
    throw new Error(`${result.path} returned HTTP ${result.status}`);
  }
  if (!result.body?.ok) {
    throw new Error(`${result.path} returned ok=${String(result.body?.ok)}`);
  }
  if (!result.responseRequestId) {
    throw new Error(`${result.path} missing X-Request-ID response header`);
  }
  if (result.responseRequestId !== result.sentRequestId) {
    throw new Error(`${result.path} returned X-Request-ID ${result.responseRequestId}, expected ${result.sentRequestId}`);
  }
}

console.log('Runtime observability: OK');
