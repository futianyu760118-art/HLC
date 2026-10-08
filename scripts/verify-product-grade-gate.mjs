import { spawnSync } from 'node:child_process';

const FORBIDDEN_HTTP_BASE = ['localhost:', '18080'].join('');
const env = {
  ...process.env,
  COMPOSE_PROJECT_NAME: process.env.COMPOSE_PROJECT_NAME || 'hengpintong-saas-preview',
  HRM_BASE_URL: process.env.HRM_BASE_URL || 'http://localhost:18280',
};

if (env.COMPOSE_PROJECT_NAME !== 'hengpintong-saas-preview') {
  throw new Error(`Refusing product-grade gate for non-SaaS project: ${env.COMPOSE_PROJECT_NAME}`);
}
if ((env.HRM_BASE_URL || '').includes(FORBIDDEN_HTTP_BASE)) {
  throw new Error('Refusing product-grade gate against 18080 from HRM-saas');
}

const checks = [
  ['SaaS target guard', 'node', ['scripts/verify-saas-target-guard.mjs']],
  ['Commercial release gate', 'node', ['scripts/verify-commercial-release-gate.mjs']],
  ['Full HRM module browser smoke', 'node', ['scripts/verify-hrm-module-browser-smoke.mjs']],
  ['Assistant frontend contract', 'npm', ['run', 'verify:assistant-contract']],
  ['TypeScript no-check budget', 'npm', ['run', 'verify:ts-nocheck-budget']],
  ['Frontend console usage', 'npm', ['run', 'verify:frontend-console-usage']],
  ['Priority accessible labels', 'npm', ['run', 'verify:priority-accessible-labels']],
  ['Accessibility smoke', 'npm', ['run', 'verify:accessibility-smoke']],
];

const quoteShellArg = (value) => {
  const text = String(value);
  if (!/[\s"'&|<>^]/.test(text)) return text;
  return `"${text.replace(/"/g, '\\"')}"`;
};

for (const [label, cmd, args] of checks) {
  console.log(`\n=== ${label}: ${cmd} ${args.join(' ')} ===`);
  const result = process.platform === 'win32'
    ? spawnSync([cmd, ...args].map(quoteShellArg).join(' '), {
      shell: true,
      stdio: 'inherit',
      env,
    })
    : spawnSync(cmd, args, {
      shell: false,
      stdio: 'inherit',
      env,
    });
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

console.log('\nproduct-grade gate passed');
