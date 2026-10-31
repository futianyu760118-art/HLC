import assert from 'node:assert/strict';
import test from 'node:test';
import {
  configuredCredentials,
  resolveHrmSmokeCredentials,
} from './hrm-smoke-credentials.mjs';

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(body),
  json: async () => body,
});

test('configuredCredentials reads tenant-specific smoke env', () => {
  const credentials = configuredCredentials({
    HRM_TEST_EMAIL: 'hr@example.com',
    HRM_TEST_PASSWORD: 'Secret123!',
    HRM_TEST_TENANT_SLUG: 'HPT-00000009',
  }, {
    HRM_TEST_EMAIL: 'ignored@example.com',
    HRM_TEST_PASSWORD: 'Ignored123!',
    DEFAULT_TENANT_SLUG: 'HPT-00000001',
  });

  assert.deepEqual(credentials, {
    email: 'hr@example.com',
    password: 'Secret123!',
    tenantSlug: 'HPT-00000009',
  });
});

test('resolveHrmSmokeCredentials returns configured login when valid', async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url: String(url), body: JSON.parse(options.body) });
    return jsonResponse(200, {
      token: 'configured-token',
      user: { tenantSlug: 'HPT-00000009', mustChangePassword: false },
    });
  };

  const result = await resolveHrmSmokeCredentials({
    baseUrl: 'http://localhost:18280',
    env: {
      HRM_TEST_EMAIL: 'hr@example.com',
      HRM_TEST_PASSWORD: 'Secret123!',
      HRM_TEST_TENANT_SLUG: 'HPT-00000009',
      HRM_SMOKE_PREPARE_TENANT: '0',
    },
    dotEnv: {},
    fetchImpl,
    runId: 'test-run',
  });

  assert.equal(result.source, 'configured');
  assert.equal(result.auth.token, 'configured-token');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.tenantSlug, 'HPT-00000009');
});

test('resolveHrmSmokeCredentials prepares a reusable smoke tenant after configured login fails', async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || 'GET';
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url: String(url), method, body });

    if (String(url).endsWith('/api/auth/login') && body?.email === 'admin@hengpintong.demo') {
      return jsonResponse(401, { error: '账号或密码错误' });
    }
    if (String(url).endsWith('/api/platform/auth/login')) {
      return jsonResponse(200, { token: 'platform-token', user: { isPlatformAdmin: true } });
    }
    if (String(url).endsWith('/api/platform/tenants') && method === 'GET') {
      return jsonResponse(200, []);
    }
    if (String(url).endsWith('/api/platform/tenants') && method === 'POST') {
      assert.equal(body.slug, 'smoke-browser');
      assert.equal(body.adminEmail, 'hrm-smoke-admin@hengpintong.demo');
      assert.equal(body.adminPassword, 'SmokeBrowserInit123!');
      return jsonResponse(201, {
        id: 'tenant-smoke',
        slug: 'smoke-browser',
        admin: { email: 'hrm-smoke-admin@hengpintong.demo' },
        initialPassword: body.adminPassword,
      });
    }
    if (String(url).endsWith('/api/auth/login') && body?.email === 'hrm-smoke-admin@hengpintong.demo') {
      assert.equal(body.password, 'SmokeBrowserInit123!');
      return jsonResponse(200, {
        token: 'initial-token',
        user: { tenantSlug: 'smoke-browser', mustChangePassword: true },
      });
    }
    if (String(url).endsWith('/api/auth/change-password')) {
      assert.equal(options.headers.Authorization, 'Bearer initial-token');
      assert.deepEqual(body, {
        currentPassword: 'SmokeBrowserInit123!',
        newPassword: 'SmokeBrowser123!',
      });
      return jsonResponse(200, {
        token: 'changed-token',
        user: { tenantSlug: 'smoke-browser', mustChangePassword: false },
      });
    }

    throw new Error(`Unexpected fetch call: ${method} ${url}`);
  };

  const result = await resolveHrmSmokeCredentials({
    baseUrl: 'http://localhost:18280',
    env: {},
    dotEnv: {
      PLATFORM_ADMIN_EMAIL: 'platform@example.com',
      PLATFORM_ADMIN_PASSWORD: 'Platform123!',
    },
    fetchImpl,
    runId: 'test-run',
  });

  assert.equal(result.source, 'prepared');
  assert.equal(result.auth.token, 'changed-token');
  assert.equal(result.credentials.password, 'SmokeBrowser123!');
  assert.ok(calls.some((call) => call.method === 'POST' && call.url.endsWith('/api/platform/tenants')));
});

test('existing smoke tenant reset selects its administrator and uses the generated credential', async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || 'GET';
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url: String(url), method, body });

    if (String(url).endsWith('/api/auth/login') && body?.email === 'admin@hengpintong.demo') {
      return jsonResponse(401, { error: '账号或密码错误' });
    }
    if (String(url).endsWith('/api/platform/auth/login')) {
      return jsonResponse(200, { token: 'platform-token', user: { isPlatformAdmin: true } });
    }
    if (String(url).endsWith('/api/platform/tenants') && method === 'GET') {
      return jsonResponse(200, [{ id: 'tenant-smoke', slug: 'smoke-browser' }]);
    }
    if (String(url).endsWith('/api/platform/tenants/tenant-smoke') && method === 'GET') {
      return jsonResponse(200, {
        id: 'tenant-smoke',
        slug: 'smoke-browser',
        admins: [{
          id: 'smoke-admin-user',
          email: 'hrm-smoke-admin@hengpintong.demo',
          role: 'admin',
          status: 'active',
        }],
      });
    }
    if (String(url).endsWith('/api/platform/tenants/tenant-smoke/reset-admin-password')) {
      assert.deepEqual(body, {
        userId: 'smoke-admin-user',
        confirmation: 'RESET smoke-browser',
      });
      return jsonResponse(200, { initialPassword: 'GeneratedReset123!Abc' });
    }
    if (String(url).endsWith('/api/auth/login') && body?.email === 'hrm-smoke-admin@hengpintong.demo') {
      assert.equal(body.password, 'GeneratedReset123!Abc');
      return jsonResponse(200, {
        token: 'generated-token',
        user: { tenantSlug: 'smoke-browser', mustChangePassword: true },
      });
    }
    if (String(url).endsWith('/api/auth/change-password')) {
      assert.deepEqual(body, {
        currentPassword: 'GeneratedReset123!Abc',
        newPassword: 'SmokeBrowser123!',
      });
      return jsonResponse(200, {
        token: 'changed-token',
        user: { tenantSlug: 'smoke-browser', mustChangePassword: false },
      });
    }

    throw new Error(`Unexpected fetch call: ${method} ${url}`);
  };

  const result = await resolveHrmSmokeCredentials({
    baseUrl: 'http://localhost:18280',
    env: { HRM_SMOKE_RESET_PASSWORD: '1' },
    dotEnv: {
      PLATFORM_ADMIN_EMAIL: 'platform@example.com',
      PLATFORM_ADMIN_PASSWORD: 'Platform123!',
    },
    fetchImpl,
    runId: 'reset-run',
  });

  assert.equal(result.source, 'prepared');
  assert.equal(result.auth.token, 'changed-token');
  assert.equal('initialPassword' in result.credentials, false);
  assert.ok(calls.some(call => call.url.endsWith('/reset-admin-password')));
});
