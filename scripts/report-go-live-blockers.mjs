import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));

export const DEFAULT_GO_LIVE_BLOCKER_CHECKS = [
  {
    id: 'saas-target-guard',
    label: 'SaaS target guard',
    command: 'node',
    args: ['scripts/verify-saas-target-guard.mjs'],
  },
  {
    id: 'public-docs-sync',
    label: 'Public docs sync',
    command: 'npm',
    args: ['run', 'verify:public-docs-sync'],
  },
  {
    id: 'go-live-evidence-templates',
    label: 'Go-live evidence templates',
    command: 'npm',
    args: ['run', 'verify:go-live-evidence-templates'],
  },
  {
    id: 'go-live-pre-final',
    label: 'Pre-final go-live readiness',
    command: 'node',
    args: ['scripts/check-go-live-readiness.mjs', '--pre-final'],
  },
  {
    id: 'restore-drill-evidence',
    label: 'Restore drill evidence',
    command: 'npm',
    args: ['run', 'verify:restore-drill-evidence'],
  },
  {
    id: 'frontend-dependency-audit',
    label: 'Frontend dependency audit',
    command: 'npm',
    args: ['audit', '--audit-level=high'],
  },
  {
    id: 'backend-dependency-audit',
    label: 'Backend dependency audit',
    command: 'npm',
    args: ['run', 'verify:backend-dependency-audit'],
  },
];

function quoteShellArg(value) {
  if (/^[A-Za-z0-9_./:@=-]+$/.test(value)) return value;
  return `"${value.replace(/"/g, '\\"')}"`;
}

function commandForPlatform(command, args) {
  if (process.platform === 'win32' && command === 'npm') {
    return {
      command: 'cmd.exe',
      args: ['/d', '/s', '/c', [command, ...args].map(quoteShellArg).join(' ')],
    };
  }
  return { command, args };
}

function defaultRunCommand(command, args) {
  const prepared = commandForPlatform(command, args);
  return spawnSync(prepared.command, prepared.args, {
    cwd: root,
    encoding: 'utf8',
  });
}

function commandOutput(result) {
  return [result?.stdout, result?.stderr, result?.error?.message]
    .filter(Boolean)
    .join('\n')
    .trim();
}

function normalizeResult(check, result) {
  const status = result?.status ?? (result?.error ? 1 : 0);
  return {
    ...check,
    status,
    ok: status === 0,
    output: commandOutput(result),
  };
}

export function evaluateGoLiveBlockers({
  checks = DEFAULT_GO_LIVE_BLOCKER_CHECKS,
  runCommand = defaultRunCommand,
} = {}) {
  const results = checks.map((check) => normalizeResult(
    check,
    runCommand(check.command, check.args),
  ));

  return {
    ok: results.every((result) => result.ok),
    results,
    passed: results.filter((result) => result.ok),
    blocked: results.filter((result) => !result.ok),
  };
}

function usefulOutputLines(output, limit = 8) {
  const lines = (output || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => !line.startsWith('>'))
    .filter(Boolean);
  return lines.length ? lines.slice(0, limit) : ['(no output)'];
}

export function formatGoLiveBlockerReport(result) {
  const lines = [
    `Go-live blocker report: ${result.ok ? 'READY' : 'BLOCKED'}`,
    `Passed checks: ${result.passed.length}/${result.results.length}`,
  ];

  if (result.passed.length) {
    lines.push('', 'Passed:');
    for (const check of result.passed) {
      lines.push(`- ${check.label}`);
    }
  }

  if (result.blocked.length) {
    lines.push('', 'Blocked:');
    for (const check of result.blocked) {
      lines.push(`- ${check.label} (exit ${check.status})`);
      for (const outputLine of usefulOutputLines(check.output)) {
        lines.push(`  ${outputLine}`);
      }
    }
  }

  return lines.join('\n');
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('Usage: node scripts/report-go-live-blockers.mjs');
    return 0;
  }

  const result = evaluateGoLiveBlockers();
  console.log(formatGoLiveBlockerReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
