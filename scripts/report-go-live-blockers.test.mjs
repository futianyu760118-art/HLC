import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

import {
  DEFAULT_GO_LIVE_BLOCKER_CHECKS,
  evaluateGoLiveBlockers,
  formatGoLiveBlockerReport,
} from './report-go-live-blockers.mjs';

function runnerFrom(results) {
  const calls = [];
  return {
    calls,
    run: (command, args) => {
      calls.push([command, args]);
      const next = results.shift();
      if (!next) throw new Error(`Unexpected command: ${command} ${args.join(' ')}`);
      return next;
    },
  };
}

describe('go-live blocker reporter', () => {
  it('includes go-live evidence template alignment in default checks', () => {
    assert.ok(DEFAULT_GO_LIVE_BLOCKER_CHECKS.some((check) => check.id === 'go-live-evidence-templates'));
  });

  it('passes when every blocker check exits zero', () => {
    const runner = runnerFrom(DEFAULT_GO_LIVE_BLOCKER_CHECKS.map(() => ({ status: 0, stdout: 'ok\n', stderr: '' })));

    const result = evaluateGoLiveBlockers({ runCommand: runner.run });

    assert.equal(result.ok, true);
    assert.equal(result.blocked.length, 0);
    assert.equal(result.passed.length, DEFAULT_GO_LIVE_BLOCKER_CHECKS.length);
    assert.match(formatGoLiveBlockerReport(result), /READY/);
  });

  it('runs every blocker check and aggregates all failures', () => {
    const runner = runnerFrom([
      { status: 0, stdout: 'target ok\n', stderr: '' },
      { status: 0, stdout: 'docs ok\n', stderr: '' },
      { status: 0, stdout: 'templates ok\n', stderr: '' },
      { status: 1, stdout: 'Accepted gates: 0/5\n', stderr: '' },
      { status: 1, stdout: 'Restore drill evidence: NOT_ACCEPTED\n', stderr: '' },
      { status: 0, stdout: 'found 0 vulnerabilities\n', stderr: '' },
      { status: 1, stdout: 'Backend dependency audit: TOOL_UNAVAILABLE\n', stderr: '' },
    ]);

    const result = evaluateGoLiveBlockers({ runCommand: runner.run });
    const report = formatGoLiveBlockerReport(result);

    assert.equal(result.ok, false);
    assert.equal(runner.calls.length, DEFAULT_GO_LIVE_BLOCKER_CHECKS.length);
    assert.deepEqual(result.blocked.map((row) => row.id), [
      'go-live-pre-final',
      'restore-drill-evidence',
      'backend-dependency-audit',
    ]);
    assert.match(report, /BLOCKED/);
    assert.match(report, /Accepted gates: 0\/5/);
    assert.match(report, /TOOL_UNAVAILABLE/);
  });

  it('does not report npm spawn EINVAL from the real CLI', () => {
    const result = spawnSync('node', ['scripts/report-go-live-blockers.mjs'], {
      cwd: new URL('..', import.meta.url),
      encoding: 'utf8',
    });
    const output = [result.stdout, result.stderr].filter(Boolean).join('\n');

    assert.doesNotMatch(output, /spawnSync npm\.cmd EINVAL/);
  });

  it('formats npm script failures with the first useful blocker line', () => {
    const report = formatGoLiveBlockerReport({
      ok: false,
      results: [],
      passed: [],
      blocked: [{
        label: 'Restore drill evidence',
        status: 1,
        output: '> hengpintong-hrm@1.0.0 verify:restore-drill-evidence\n> node scripts/check-restore-drill-evidence.mjs\n\nRestore drill evidence: NOT_ACCEPTED\nNo valid passing restore drill row was found.',
      }],
    });

    assert.match(report, /Restore drill evidence: NOT_ACCEPTED/);
    assert.doesNotMatch(report, /> hengpintong-hrm/);
  });

  it('includes multiple useful blocker lines for readiness details', () => {
    const report = formatGoLiveBlockerReport({
      ok: false,
      results: [],
      passed: [],
      blocked: [{
        label: 'Pre-final go-live readiness',
        status: 1,
        output: [
          'Go-live readiness: Not accepted',
          'Accepted gates: 0/5',
          '',
          'Pending gates:',
          '- Legal review: Pending owner evidence',
          '- ICP filing: Pending owner evidence',
        ].join('\n'),
      }],
    });

    assert.match(report, /Go-live readiness: Not accepted/);
    assert.match(report, /Legal review: Pending owner evidence/);
    assert.match(report, /ICP filing: Pending owner evidence/);
  });
});
