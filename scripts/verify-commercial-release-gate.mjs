import { spawnSync } from 'node:child_process';

const SAAS_PROJECT = 'hengpintong-saas-preview';
const DEFAULT_BASE_URL = 'http://localhost:18280';
const DEFAULT_HTTPS_BASE_URL = 'https://localhost:18445';
const FORBIDDEN_HTTP_BASE = ['localhost:', '18080'].join('');
const FORBIDDEN_HTTPS_BASE = ['localhost:', '18443'].join('');

const env = {
  ...process.env,
  COMPOSE_PROJECT_NAME: process.env.COMPOSE_PROJECT_NAME || SAAS_PROJECT,
  HRM_BASE_URL: process.env.HRM_BASE_URL || DEFAULT_BASE_URL,
  HRM_HTTPS_BASE_URL: process.env.HRM_HTTPS_BASE_URL || DEFAULT_HTTPS_BASE_URL,
};

if (env.COMPOSE_PROJECT_NAME !== SAAS_PROJECT) {
  throw new Error(`Refusing commercial gate for non-SaaS project: ${env.COMPOSE_PROJECT_NAME}`);
}
if (env.HRM_BASE_URL.includes(FORBIDDEN_HTTP_BASE)) {
  throw new Error(`Refusing commercial gate against ${FORBIDDEN_HTTP_BASE} from HRM-saas`);
}
if (env.HRM_HTTPS_BASE_URL.includes(FORBIDDEN_HTTPS_BASE)) {
  throw new Error(`Refusing commercial gate against ${FORBIDDEN_HTTPS_BASE} from HRM-saas`);
}

const commands = [
  ['SaaS target guard', 'node', ['scripts/verify-saas-target-guard.mjs']],
  ['Public docs sync', 'npm', ['run', 'verify:public-docs-sync']],
  ['Go-live evidence templates', 'npm', ['run', 'verify:go-live-evidence-templates']],
  ['Capability navigation', 'npm', ['run', 'verify:capability-navigation']],
  ['Extension frontend contract', 'node', ['--test', 'scripts/check-extension-api-contract.test.mjs']],
  ['Frontend lint', 'npm', ['run', 'lint']],
  ['Frontend build', 'npm', ['run', 'build']],
  ['Preview asset build', 'npx', ['vite', 'build', '--outDir', 'outputs/saas-docker-preview/dist-prod']],
  ['Python compileall', 'python', ['-m', 'compileall', '-q', 'backend-python']],
  [
    'Backend commercial tests',
    'python',
    [
      '-m',
      'pytest',
      '-q',
      'backend-python/tests/test_saas_tenancy.py',
      'backend-python/tests/test_release_security.py',
      'backend-python/tests/test_platform_billing.py',
      'backend-python/tests/test_tenant_metering.py',
      'backend-python/tests/test_tenant_data_lifecycle.py',
      'backend-python/tests/test_proxy_redirects.py',
      'backend-python/tests/test_schema_migrations.py',
      'backend-python/tests/test_service_configuration.py',
      'backend-python/tests/test_extension_framework.py',
    ],
  ],
  ['Platform browser smoke', 'node', ['scripts/verify-platform-console-browser.mjs']],
];

const quoteShellArg = (value) => {
  if (/^[A-Za-z0-9_./:@=-]+$/.test(value)) return value;
  return `"${value.replace(/"/g, '\\"')}"`;
};

for (const [label, cmd, args] of commands) {
  console.log(`\n=== ${label}: ${cmd} ${args.join(' ')} ===`);
  const result = process.platform === 'win32'
    ? spawnSync([cmd, ...args].map(quoteShellArg).join(' '), {
      stdio: 'inherit',
      shell: true,
      env,
    })
    : spawnSync(cmd, args, {
      stdio: 'inherit',
      env,
    });
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

console.log('\ncommercial release gate passed');
