import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

describe('SaaS priority fixture-backed scenario script wiring', () => {
  it('has a browser scenario command scoped to SaaS preview only', () => {
    assert.equal(existsSync('scripts/verify-saas-priority-scenarios.mjs'), true);

    const script = readFileSync('scripts/verify-saas-priority-scenarios.mjs', 'utf8');
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));

    assert.equal(
      pkg.scripts['verify:saas-priority-scenarios'],
      'node scripts/verify-saas-priority-scenarios.mjs',
    );
    assert.match(script, /http:\/\/localhost:18280/);
    assert.match(script, /Refusing to verify against 18080/);
    assert.match(script, /resolveHrmSmokeCredentials/);
    assert.match(script, /employees-crud/);
    assert.match(script, /roles-crud/);
    assert.match(script, /job-create/);
    assert.match(script, /ai-settings-save/);
    assert.match(script, /ai-settings-controls/);
    assert.match(script, /ai-settings-safe-controls/);
    assert.match(script, /platform-ai-entitlement-management/);
    assert.match(script, /tenant-ai-usage-and-tier-selection/);
    assert.match(script, /assistantEntitlementCard/);
    assert.match(script, /section\.rounded-lg\.border\.bg-white\.p-4/);
    assert.match(script, /filter\(\{\s*has:\s*page\.getByRole\('heading',\s*\{\s*name:\s*'AI 助手'/);
    assert.match(script, /home-navigation/);
    assert.match(script, /home-dashboard-secondary-navigation/);
    assert.match(script, /job-create-required-fields/);
    assert.match(script, /exam-center-non-ai-controls/);
    assert.match(script, /hrm-safe-filter-controls/);
    assert.match(script, /operation-logs-fixture-audit/);
    assert.match(script, /lifecycle-list-workflows/);
    assert.match(script, /system-settings-safe-save-reset/);
    assert.match(script, /job-manage-fixture-list/);
    assert.match(script, /scenario-/);
    assert.match(script, /cleanup/);
    const staleHttpTarget = ['localhost:', '18080'].join('');
    const staleProject = ['hengpintong', '-next'].join('');
    assert.equal(script.includes(staleHttpTarget), false);
    assert.equal(script.includes(staleProject), false);
  });

  it('maps high-risk remaining backlog controls to implemented fixture-backed definitions', async () => {
    const { scenarioCoverageDefinitions } = await import('./saas-scenario-coverage-definitions.mjs');

    const byId = new Map(scenarioCoverageDefinitions.map((definition) => [definition.id, definition]));
    for (const id of [
      'home-cross-module-navigation',
      'operation-logs-fixture-detail-filter-export',
      'system-settings-safe-save-reset',
      'contracts-lifecycle-list-detail-workflow',
      'probations-lifecycle-list-detail-workflow',
      'resignations-lifecycle-list-detail-workflow',
      'job-manage-fixture-filters',
      'job-manage-fixture-date-range',
      'job-manage-new-job-navigation',
      'home-secondary-dashboard-controls',
      'job-create-required-field-validation',
      'job-create-unlabeled-numeric-inputs',
      'exam-center-filter-controls',
      'exam-center-status-tab-controls',
      'attendance-records-safe-filters',
      'employee-requests-safe-filters',
      'performance-cycles-safe-filters',
      'performance-review-safe-filters',
      'payroll-records-safe-filters',
    ]) {
      assert.equal(byId.get(id)?.status, 'implemented', `${id} should be implemented`);
      assert.match(byId.get(id)?.command || '', /verify-(saas-priority-scenarios|hrm-lifecycle-workflow-browser-smoke)\.mjs/);
    }

    assert.equal(byId.get('home-cross-module-navigation')?.route, '/home');
    assert.equal(byId.get('operation-logs-fixture-detail-filter-export')?.route, '/operation-logs');
    assert.equal(byId.get('system-settings-safe-save-reset')?.route, '/system-settings');
    assert.equal(byId.get('contracts-lifecycle-list-detail-workflow')?.route, '/hrm/contracts');
    assert.equal(byId.get('probations-lifecycle-list-detail-workflow')?.route, '/hrm/probations');
    assert.equal(byId.get('resignations-lifecycle-list-detail-workflow')?.route, '/hrm/resignations');
    assert.equal(byId.get('job-manage-fixture-filters')?.route, '/job-manage');
    assert.equal(byId.get('job-manage-fixture-date-range')?.route, '/job-manage');
    assert.equal(byId.get('job-manage-new-job-navigation')?.route, '/job-manage');
    assert.equal(byId.get('home-secondary-dashboard-controls')?.route, '/home');
    assert.equal(byId.get('job-create-required-field-validation')?.route, '/job-create');
    assert.equal(byId.get('job-create-unlabeled-numeric-inputs')?.route, '/job-create');
    assert.equal(byId.get('exam-center-filter-controls')?.route, '/exam-center');
    assert.equal(byId.get('exam-center-status-tab-controls')?.route, '/exam-center');
    assert.equal(byId.get('attendance-records-safe-filters')?.route, '/hrm/attendance-records');
    assert.equal(byId.get('employee-requests-safe-filters')?.route, '/employee-requests');
    assert.equal(byId.get('performance-cycles-safe-filters')?.route, '/hrm/performance-cycles');
    assert.equal(byId.get('performance-review-safe-filters')?.route, '/performance-review');
    assert.equal(byId.get('payroll-records-safe-filters')?.route, '/hrm/payroll-records');
  });

  it('does not let deep-link lifecycle smoke claim list-level CRUD or filter coverage', async () => {
    const { scenarioCoverageDefinitions } = await import('./saas-scenario-coverage-definitions.mjs');
    const smokeDefinitions = scenarioCoverageDefinitions.filter(
      (definition) => definition.command === 'node scripts/verify-hrm-lifecycle-workflow-browser-smoke.mjs',
    );
    const flattenedControls = smokeDefinitions
      .flatMap((definition) => [definition.control, ...(definition.controls || [])])
      .filter(Boolean)
      .map(String)
      .join('\n');

    assert.equal(
      smokeDefinitions.length,
      0,
      `deep-link lifecycle smoke should not claim list-level backlog controls:\n${flattenedControls}`,
    );

    for (const id of [
      'contracts-lifecycle-list-detail-workflow',
      'probations-lifecycle-list-detail-workflow',
      'resignations-lifecycle-list-detail-workflow',
    ]) {
      assert.equal(
        scenarioCoverageDefinitions.find((definition) => definition.id === id)?.command,
        'node scripts/verify-saas-priority-scenarios.mjs --scenario lifecycle-list-workflows',
      );
    }
  });

  it('removes lifecycle workflow notifications created by each fixture run', () => {
    const script = readFileSync('scripts/verify-saas-priority-scenarios.mjs', 'utf8');

    assert.match(script, /cleanupScenarioNotifications/);
    assert.match(script, /cleanupScenarioNotifications\(\{\s*auth,\s*fixtures\s*=\s*\[\]\s*\}\)/);
    assert.match(script, /resource:\s*'notifications'/);
    assert.match(script, /notice_type|noticeType/);
    assert.match(script, /includes\(runId\)/);
    assert.match(script, /fixtures\.some\(\(fixture\)\s*=>[\s\S]*row\.linkUrl[\s\S]*fixture\.record\?\.id/);
    assert.match(script, /cleanupLifecycleFixtures[\s\S]*cleanupScenarioNotifications\(\{\s*auth,\s*fixtures\s*\}\)/);
  });
});
