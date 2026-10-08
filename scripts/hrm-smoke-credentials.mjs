const DEFAULT_EMAIL = 'admin@hengpintong.demo';
const DEFAULT_PASSWORD = 'Demo@123456';
const DEFAULT_TENANT_SLUG = 'HPT-00000001';
const SMOKE_TENANT_SLUG = 'smoke-browser';
const SMOKE_EMAIL = 'hrm-smoke-admin@hengpintong.demo';
const SMOKE_INITIAL_PASSWORD = 'SmokeBrowserInit123!';
const SMOKE_PASSWORD = 'SmokeBrowser123!';

const asJson = async (response, label) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${label} did not return JSON: ${text.slice(0, 500)}`);
  }
};

const requestJson = async (fetchImpl, url, options = {}) => {
  const response = await fetchImpl(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const payload = await asJson(response, url);
  if (!response.ok) {
    const message = payload?.error || payload?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
};

export function configuredCredentials(env = process.env, dotEnv = {}) {
  return {
    email: env.HRM_TEST_EMAIL || dotEnv.HRM_TEST_EMAIL || DEFAULT_EMAIL,
    password: env.HRM_TEST_PASSWORD || dotEnv.HRM_TEST_PASSWORD || DEFAULT_PASSWORD,
    tenantSlug: env.HRM_TEST_TENANT_SLUG || dotEnv.HRM_TEST_TENANT_SLUG || dotEnv.DEFAULT_TENANT_SLUG || DEFAULT_TENANT_SLUG,
  };
}

const loginHrm = async ({ baseUrl, credentials, fetchImpl, requestId }) => (
  requestJson(fetchImpl, `${baseUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': requestId },
    body: JSON.stringify({
      identifier: credentials.email,
      email: credentials.email,
      password: credentials.password,
      tenantSlug: credentials.tenantSlug,
    }),
  })
);

const platformLogin = async ({ baseUrl, env, dotEnv, fetchImpl, requestId }) => {
  const identifier = env.HRM_PLATFORM_EMAIL || env.HRM_TEST_PLATFORM_EMAIL || dotEnv.PLATFORM_ADMIN_EMAIL || 'platform@example.com';
  const password = env.HRM_PLATFORM_PASSWORD || env.HRM_TEST_PLATFORM_PASSWORD || dotEnv.PLATFORM_ADMIN_PASSWORD || '';
  if (!identifier || !password) {
    throw new Error('HRM module smoke cannot prepare a tenant because platform credentials are missing.');
  }
  return requestJson(fetchImpl, `${baseUrl}/api/platform/auth/login`, {
    method: 'POST',
    headers: { 'X-Request-ID': requestId },
    body: JSON.stringify({ identifier, password }),
  });
};

const prepareSmokeTenant = async ({ baseUrl, env, dotEnv, fetchImpl, runId }) => {
  const platform = await platformLogin({
    baseUrl,
    env,
    dotEnv,
    fetchImpl,
    requestId: `${runId}-platform-login`,
  });
  const authHeader = { Authorization: `Bearer ${platform.token}` };
  const tenants = await requestJson(fetchImpl, `${baseUrl}/api/platform/tenants`, {
    method: 'GET',
    headers: {
      ...authHeader,
      'X-Request-ID': `${runId}-list-tenants`,
    },
  });
  let tenant = Array.isArray(tenants)
    ? tenants.find((item) => item?.slug === SMOKE_TENANT_SLUG)
    : null;
  let needsPasswordChange = false;
  let initialPassword = SMOKE_INITIAL_PASSWORD;

  if (!tenant) {
    tenant = await requestJson(fetchImpl, `${baseUrl}/api/platform/tenants`, {
      method: 'POST',
      headers: {
        ...authHeader,
        'X-Request-ID': `${runId}-create-smoke-tenant`,
      },
      body: JSON.stringify({
        name: 'Browser Smoke Tenant',
        slug: SMOKE_TENANT_SLUG,
        adminEmail: SMOKE_EMAIL,
        adminName: 'Browser Smoke Admin',
        adminPassword: SMOKE_INITIAL_PASSWORD,
        planCode: 'enterprise',
      }),
    });
    needsPasswordChange = true;
  } else if (env.HRM_SMOKE_RESET_PASSWORD === '1') {
    const detail = await requestJson(fetchImpl, `${baseUrl}/api/platform/tenants/${tenant.id}`, {
      method: 'GET',
      headers: {
        ...authHeader,
        'X-Request-ID': `${runId}-get-smoke-tenant`,
      },
    });
    const target = (Array.isArray(detail.admins) ? detail.admins : [detail.admin])
      .filter(Boolean)
      .find((item) => item.email === SMOKE_EMAIL
        && item.status === 'active'
        && (item.role === 'admin' || item.role === 'hr_admin'));
    if (!target?.id) {
      throw new Error('HRM module smoke cannot reset the tenant because its active administrator was not found.');
    }
    const reset = await requestJson(fetchImpl, `${baseUrl}/api/platform/tenants/${tenant.id}/reset-admin-password`, {
      method: 'POST',
      headers: {
        ...authHeader,
        'X-Request-ID': `${runId}-reset-smoke-admin`,
      },
      body: JSON.stringify({
        userId: target.id,
        confirmation: `RESET ${tenant.slug}`,
      }),
    });
    if (!reset.initialPassword) {
      throw new Error('HRM module smoke reset did not return a one-time credential.');
    }
    initialPassword = reset.initialPassword;
    needsPasswordChange = true;
  }

  return {
    email: SMOKE_EMAIL,
    password: SMOKE_PASSWORD,
    tenantSlug: tenant.slug || SMOKE_TENANT_SLUG,
    needsPasswordChange,
    initialPassword,
  };
};

const ensureChangedPassword = async ({ baseUrl, auth, credentials, fetchImpl, runId }) => {
  if (!auth.user?.mustChangePassword) return auth;
  return requestJson(fetchImpl, `${baseUrl}/api/auth/change-password`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${auth.token}`,
      'X-Request-ID': `${runId}-change-smoke-password`,
    },
    body: JSON.stringify({
      currentPassword: credentials.password,
      newPassword: SMOKE_PASSWORD,
    }),
  });
};

export async function resolveHrmSmokeCredentials({
  baseUrl,
  env = process.env,
  dotEnv = {},
  fetchImpl = fetch,
  runId = 'hrm-module-smoke',
} = {}) {
  const configured = configuredCredentials(env, dotEnv);
  try {
    const auth = await loginHrm({
      baseUrl,
      credentials: configured,
      fetchImpl,
      requestId: `${runId}-login`,
    });
    return {
      source: 'configured',
      credentials: configured,
      auth,
    };
  } catch (error) {
    if (env.HRM_SMOKE_PREPARE_TENANT === '0') {
      throw error;
    }
  }

  const preparedTenant = await prepareSmokeTenant({ baseUrl, env, dotEnv, fetchImpl, runId });
  const prepared = {
    ...preparedTenant,
    password: preparedTenant.needsPasswordChange ? preparedTenant.initialPassword : SMOKE_PASSWORD,
  };
  const initialAuth = await loginHrm({
    baseUrl,
    credentials: prepared,
    fetchImpl,
    requestId: `${runId}-login-prepared`,
  });
  const auth = await ensureChangedPassword({
    baseUrl,
    auth: initialAuth,
    credentials: prepared,
    fetchImpl,
    runId,
  });

  return {
    source: 'prepared',
    credentials: {
      email: prepared.email,
      password: SMOKE_PASSWORD,
      tenantSlug: prepared.tenantSlug,
    },
    auth,
  };
}
