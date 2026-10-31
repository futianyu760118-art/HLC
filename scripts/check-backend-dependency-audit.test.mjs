import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

import {
  evaluateBackendDependencyAudit,
  formatBackendDependencyAuditReport,
} from './check-backend-dependency-audit.mjs';

const expectedAuditArgs = (requirementsPath = 'backend-python/requirements.txt') => [
  '-r',
  requirementsPath,
  '--progress-spinner',
  'off',
];

function runnerFrom(results) {
  const calls = [];
  return {
    calls,
    run: (command, args, options) => {
      calls.push([command, args, options]);
      const next = results.shift();
      if (!next) throw new Error(`Unexpected command: ${command} ${args.join(' ')}`);
      return next;
    },
  };
}

describe('backend dependency audit checker', () => {
  it('passes when pip-audit succeeds against backend requirements', () => {
    const runner = runnerFrom([{ status: 0, stdout: 'No known vulnerabilities found\n', stderr: '' }]);

    const result = evaluateBackendDependencyAudit({ runCommand: runner.run, requirementsPath: 'backend-python/requirements.txt' });

    assert.equal(result.ok, true);
    assert.equal(result.tool, 'pip-audit');
    assert.deepEqual(runner.calls[0].slice(0, 2), ['pip-audit', expectedAuditArgs()]);
    assert.match(formatBackendDependencyAuditReport(result), /OK/);
  });

  it('audits the resolved dependency graph instead of direct pins only', () => {
    const runner = runnerFrom([{ status: 0, stdout: 'No known vulnerabilities found\n', stderr: '' }]);

    evaluateBackendDependencyAudit({ runCommand: runner.run, requirementsPath: 'backend-python/requirements.txt' });

    assert.deepEqual(runner.calls[0].slice(0, 2), [
      'pip-audit',
      expectedAuditArgs(),
    ]);
    assert.doesNotMatch(runner.calls[0][1].join(' '), /--no-deps|--disable-pip/);
  });

  it('runs audit tools with UTF-8 enabled and proxy variables cleared', () => {
    const runner = runnerFrom([{ status: 0, stdout: 'No known vulnerabilities found\n', stderr: '' }]);

    evaluateBackendDependencyAudit({ runCommand: runner.run, requirementsPath: 'backend-python/requirements.txt' });

    const env = runner.calls[0][2]?.env || {};
    assert.equal(env.PYTHONUTF8, '1');
    assert.equal(env.PYTHONIOENCODING, 'utf-8');
    assert.equal(env.PYTHONDONTWRITEBYTECODE, '1');
    assert.equal(env.HTTP_PROXY, '');
    assert.equal(env.HTTPS_PROXY, '');
    assert.equal(env.ALL_PROXY, '');
    assert.equal(env.http_proxy, '');
    assert.equal(env.https_proxy, '');
    assert.equal(env.all_proxy, '');
  });

  it('falls back to python -m pip_audit when pip-audit command is unavailable', () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 0, stdout: 'No known vulnerabilities found\n', stderr: '' },
    ]);

    const result = evaluateBackendDependencyAudit({ runCommand: runner.run, requirementsPath: 'backend-python/requirements.txt' });

    assert.equal(result.ok, true);
    assert.equal(result.tool, 'python -m pip_audit');
    assert.deepEqual(runner.calls[1].slice(0, 2), ['python', ['-m', 'pip_audit', ...expectedAuditArgs()]]);
  });

  it('uses PyPI JSON vulnerability data when audit entrypoints are unavailable', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'Flask==3.1.3\nWerkzeug==3.1.6\n',
      fetchPackageInfo: async () => ({
        vulnerabilities: [],
      }),
    });

    assert.equal(result.ok, true);
    assert.equal(result.tool, 'PyPI JSON API');
    assert.match(formatBackendDependencyAuditReport(result), /No known vulnerabilities found/);
  });

  it('fails when PyPI JSON reports vulnerabilities', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'Flask==3.0.0\n',
      fetchPackageInfo: async () => ({
        vulnerabilities: [{ id: 'GHSA-test', fix_versions: ['3.1.3'] }],
      }),
    });

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'audit-failed');
    assert.equal(result.tool, 'PyPI JSON API');
    assert.match(formatBackendDependencyAuditReport(result), /GHSA-test/);
  });

  it('retries transient PyPI JSON lookup failures before reporting unavailable', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);
    let calls = 0;

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'SQLAlchemy==2.0.41\n',
      fetchPackageInfo: async () => {
        calls += 1;
        if (calls === 1) throw new Error('This operation was aborted');
        return { vulnerabilities: [] };
      },
    });

    assert.equal(result.ok, true);
    assert.equal(result.tool, 'PyPI JSON API');
    assert.equal(calls, 2);
  });

  it('fails as tool-unavailable when scanner entrypoints and PyPI JSON are unavailable', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'Flask==3.1.3\n',
      fetchPackageInfo: async () => {
        throw new Error('network unavailable');
      },
    });
    const report = formatBackendDependencyAuditReport(result);

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'tool-unavailable');
    assert.match(report, /TOOL_UNAVAILABLE/);
    assert.match(report, /approved equivalent/);
  });

  it('accepts concrete security-owner evidence when audit tools and PyPI JSON are unavailable', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);
    const evidenceText = [
      '| Date | Owner | Evidence | Decision |',
      '| --- | --- | --- | --- |',
      '| 2026-06-26 | Security owner Zhang San | Approved equivalent scanner report SEC-123 for backend-python/requirements.txt; no high-severity unresolved findings | Accepted |',
    ].join('\n');

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'Flask==3.1.3\n',
      fetchPackageInfo: async () => {
        throw new Error('network unavailable');
      },
      evidenceText,
    });

    assert.equal(result.ok, true);
    assert.equal(result.reason, 'owner-evidence');
    assert.match(formatBackendDependencyAuditReport(result), /OWNER_EVIDENCE/);
  });

  it('rejects placeholder owner evidence rows', async () => {
    const runner = runnerFrom([
      { status: 1, stdout: '', stderr: "The term 'pip-audit' is not recognized" },
      { status: 1, stdout: '', stderr: 'No module named pip_audit' },
    ]);
    const evidenceText = [
      '| Date | Owner | Evidence | Decision |',
      '| --- | --- | --- | --- |',
      '| YYYY-MM-DD | <security owner role/name> | <approved equivalent scanner output or exception> | Accepted |',
    ].join('\n');

    const result = await evaluateBackendDependencyAudit({
      runCommand: runner.run,
      requirementsPath: 'backend-python/requirements.txt',
      requirementsText: 'Flask==3.1.3\n',
      fetchPackageInfo: async () => {
        throw new Error('network unavailable');
      },
      evidenceText,
    });

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'tool-unavailable');
    assert.match(formatBackendDependencyAuditReport(result), /No accepted owner evidence/);
  });

  it('fails as audit-failed when pip-audit runs and finds issues', () => {
    const runner = runnerFrom([{ status: 1, stdout: 'Found 1 known vulnerability\n', stderr: '' }]);

    const result = evaluateBackendDependencyAudit({ runCommand: runner.run, requirementsPath: 'backend-python/requirements.txt' });

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'audit-failed');
    assert.equal(result.tool, 'pip-audit');
    assert.match(formatBackendDependencyAuditReport(result), /FAILED/);
  });

  it('does not emit the Node shell args deprecation warning from the real CLI', () => {
    const result = spawnSync('node', ['scripts/check-backend-dependency-audit.mjs'], {
      cwd: new URL('..', import.meta.url),
      encoding: 'utf8',
    });

    assert.doesNotMatch(result.stderr || '', /DEP0190/);
  });
});
