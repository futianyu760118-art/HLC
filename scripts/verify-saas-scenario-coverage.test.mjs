import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  evaluateScenarioCoverage,
  matchCoverageDefinition,
} from './verify-saas-scenario-coverage.mjs';

const commitReason = 'commit-or-destructive action requires scenario';
const navigationReason = 'navigation or create/edit flow recorded as cross-link/scenario';

describe('SaaS scenario coverage verifier', () => {
  it('counts exact and regex-backed coverage without double-counting backlog items', () => {
    const audit = {
      runId: 'full-chain-interactions-test',
      baseUrl: 'http://localhost:18280',
      scenarioBacklog: [
        { route: '/hrm/employees', routeLabel: '员工档案', reason: navigationReason, tag: 'button', control: '新增员工档案' },
        { route: '/hrm/employees', routeLabel: '员工档案', reason: navigationReason, tag: 'button', control: '详情' },
        { route: '/hrm/employees', routeLabel: '员工档案', reason: navigationReason, tag: 'button', control: '详情' },
        { route: '/hrm/employees', routeLabel: '员工档案', reason: commitReason, tag: 'button', control: '删除' },
        { route: '/hrm/contracts', routeLabel: '合同管理', reason: commitReason, tag: 'button', control: '终止' },
      ],
    };
    const definitions = [
      {
        id: 'employees-crud',
        route: '/hrm/employees',
        reason: navigationReason,
        controls: ['新增员工档案', /^详情$/],
        status: 'implemented',
        command: 'node scripts/verify-saas-priority-scenarios.mjs --scenario employees-crud',
      },
      {
        id: 'employees-delete',
        route: '/hrm/employees',
        reason: commitReason,
        control: /^删除$/,
        status: 'implemented',
        command: 'node scripts/verify-saas-priority-scenarios.mjs --scenario employees-crud',
      },
    ];

    const report = evaluateScenarioCoverage({ audit, definitions });

    assert.equal(report.ok, true);
    assert.equal(report.totalBacklog, 5);
    assert.equal(report.coveredItems, 4);
    assert.equal(report.remainingItems, 1);
    assert.equal(report.coveredGroups, 2);
    assert.equal(report.remainingGroups, 1);
    assert.deepEqual(report.unmatchedDefinitions, []);
    assert.deepEqual(report.duplicateDefinitionIds, []);
    assert.deepEqual(report.topRemainingRoutes.map((route) => [route.route, route.count]), [['/hrm/contracts', 1]]);
  });

  it('matches route, reason, tag, and control constraints', () => {
    const definition = {
      id: 'contracts-renew',
      route: '/hrm/contracts',
      reason: commitReason,
      tags: ['button'],
      control: /续签|终止/,
    };

    assert.equal(matchCoverageDefinition(definition, {
      route: '/hrm/contracts',
      reason: commitReason,
      tag: 'button',
      control: '续签',
    }), true);
    assert.equal(matchCoverageDefinition(definition, {
      route: '/hrm/contracts',
      reason: commitReason,
      tag: 'input',
      control: '续签',
    }), false);
    assert.equal(matchCoverageDefinition(definition, {
      route: '/hrm/probations',
      reason: commitReason,
      tag: 'button',
      control: '续签',
    }), false);
  });

  it('rejects stale 18080 evidence anywhere in the source audit', () => {
    assert.throws(
      () => evaluateScenarioCoverage({
        audit: {
          baseUrl: `http://localhost:${18080}`,
          scenarioBacklog: [],
        },
        definitions: [],
      }),
      /18080/,
    );
    assert.throws(
      () => evaluateScenarioCoverage({
        audit: {
          baseUrl: 'http://localhost:18280',
          scenarioBacklog: [{ route: '/home', reason: 'x', control: `http://localhost:${18080}/home` }],
        },
        definitions: [],
      }),
      /18080/,
    );
  });

  it('reports duplicate definition ids and definitions that no longer match current backlog', () => {
    const audit = {
      baseUrl: 'http://localhost:18280',
      scenarioBacklog: [
        { route: '/hrm/roles', reason: commitReason, tag: 'button', control: '删除' },
      ],
    };
    const report = evaluateScenarioCoverage({
      audit,
      definitions: [
        { id: 'same', route: '/hrm/roles', reason: commitReason, control: '删除' },
        { id: 'same', route: '/hrm/employees', reason: commitReason, control: '删除' },
        { id: 'missing', route: '/hrm/contracts', reason: commitReason, control: '删除' },
      ],
    });

    assert.equal(report.ok, false);
    assert.deepEqual(report.duplicateDefinitionIds, ['same']);
    assert.deepEqual(report.unmatchedDefinitions.map((item) => item.id), ['missing']);
  });
});
