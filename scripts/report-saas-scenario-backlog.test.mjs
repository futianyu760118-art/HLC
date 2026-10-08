import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  evaluateScenarioBacklog,
  formatScenarioBacklogMarkdown,
  formatScenarioBacklogSummary,
  findLatestFullChainAuditInput,
  writeScenarioBacklogReports,
} from './report-saas-scenario-backlog.mjs';

function withAudit(data) {
  const root = mkdtempSync(join(tmpdir(), 'hrm-scenario-backlog-'));
  const input = join(root, 'audit.json');
  const outputDir = join(root, 'artifacts', 'browser-verification');
  writeFileSync(input, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  return {
    input,
    outputDir,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  };
}

describe('SaaS scenario backlog reporter', () => {
  it('groups scenario backlog by route and reason/action with samples', () => {
    const files = withAudit({
      runId: 'full-chain-interactions-test',
      baseUrl: 'http://localhost:18280',
      scenarioBacklog: [
        {
          route: '/contracts',
          routeLabel: '合同管理',
          control: 'button:续签',
          tag: 'button',
          reason: 'requires fixture-backed renewal scenario',
        },
        {
          route: '/contracts',
          routeLabel: '合同管理',
          control: 'button:终止',
          tag: 'button',
          reason: 'requires fixture-backed renewal scenario',
        },
        {
          route: '/probations',
          routeLabel: '试用期',
          control: 'button:转正',
          tag: 'button',
          action: 'click',
          reason: 'requires approved employee fixture',
        },
      ],
    });

    try {
      const report = evaluateScenarioBacklog({ inputPath: files.input, sampleLimit: 2 });

      assert.equal(report.ok, true);
      assert.equal(report.totalBacklog, 3);
      assert.equal(report.uniqueRouteCount, 2);
      assert.deepEqual(report.topRoutes.map((route) => [route.route, route.count]), [
        ['/contracts', 2],
        ['/probations', 1],
      ]);
      assert.equal(report.routes[0].groups[0].count, 2);
      assert.equal(report.routes[0].groups[0].samples.length, 2);
      assert.equal(report.routes[0].groups[0].reason, 'requires fixture-backed renewal scenario');
      assert.equal(report.routes[0].groups[0].action, 'unspecified');

      const outputs = writeScenarioBacklogReports(report, { outputDir: files.outputDir, timestamp: '20260701010101' });
      assert.match(outputs.jsonPath, /scenario-backlog-20260701010101\.json$/);
      assert.match(outputs.markdownPath, /scenario-backlog-20260701010101\.md$/);
      assert.match(formatScenarioBacklogMarkdown(report), /\/contracts/);
      assert.match(formatScenarioBacklogSummary({ ...report, outputs }), /total backlog: 3/i);
      assert.match(formatScenarioBacklogSummary({ ...report, outputs }), /unique routes: 2/i);
    } finally {
      files.cleanup();
    }
  });

  it('refuses stale 18080 targets from input audit evidence', () => {
    const files = withAudit({
      baseUrl: `http://localhost:${18080}`,
      scenarioBacklog: [],
    });

    try {
      assert.throws(
        () => evaluateScenarioBacklog({ inputPath: files.input }),
        /Refusing.*18080/,
      );
    } finally {
      files.cleanup();
    }
  });

  it('refuses stale 18080 targets inside structured target evidence', () => {
    const files = withAudit({
      baseUrl: 'http://localhost:18280',
      target: { browserBaseUrl: `http://localhost:${18080}` },
      scenarioBacklog: [],
    });

    try {
      assert.throws(
        () => evaluateScenarioBacklog({ inputPath: files.input }),
        /Refusing.*18080/,
      );
    } finally {
      files.cleanup();
    }
  });

  it('refuses stale 18080 targets inside backlog samples before writing reports', () => {
    const files = withAudit({
      baseUrl: 'http://localhost:18280',
      scenarioBacklog: [
        {
          route: '/employees',
          routeLabel: '员工档案',
          control: 'legacy link',
          tag: 'a',
          href: `http://localhost:${18080}/hrm/employees`,
          reason: 'requires fixture-backed write scenario',
        },
      ],
    });

    try {
      assert.throws(
        () => evaluateScenarioBacklog({ inputPath: files.input }),
        /Refusing.*18080/,
      );
    } finally {
      files.cleanup();
    }
  });

  it('uses the latest full-chain audit artifact as the default source', () => {
    const root = mkdtempSync(join(tmpdir(), 'hrm-scenario-backlog-latest-'));
    const artifactDir = join(root, 'artifacts', 'browser-verification');
    mkdirSync(artifactDir, { recursive: true });
    const older = join(artifactDir, 'full-chain-interactions-20260701010101.json');
    const newer = join(artifactDir, 'full-chain-interactions-20260701020202.json');
    writeFileSync(older, JSON.stringify({ baseUrl: 'http://localhost:18280', scenarioBacklog: [] }), 'utf8');
    writeFileSync(newer, JSON.stringify({ baseUrl: 'http://localhost:18280', scenarioBacklog: [] }), 'utf8');

    try {
      assert.equal(findLatestFullChainAuditInput({ artifactDir }), newer);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
