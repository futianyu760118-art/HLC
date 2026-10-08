import { existsSync, readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

describe('SaaS full-chain interaction audit wiring', () => {
  it('has a script, npm command, reports, and stale-port guard', () => {
    assert.equal(existsSync('scripts/verify-saas-full-chain-interactions.mjs'), true);

    const script = readFileSync('scripts/verify-saas-full-chain-interactions.mjs', 'utf8');
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));

    assert.equal(
      pkg.scripts['verify:saas-full-chain-interactions'],
      'node scripts/verify-saas-full-chain-interactions.mjs',
    );
    assert.match(script, /localhost:18280/);
    assert.match(script, /Refusing to verify against 18080/);
    assert.match(script, /new URL\(BASE_URL\)/);
    assert.match(script, /FORBIDDEN_PREVIEW_PORT/);
    assert.match(script, /full-chain-interactions-/);
    assert.match(script, /full-chain-interactions-.*\.md/);
    for (const route of ['/todos', '/headcount-management', '/people-analytics', '/continuous-feedback']) {
      assert.match(script, new RegExp(`\\{ path: '${route.replace('/', '\\/')}', label:`));
    }
    assert.match(script, /needsPortalAudit/);
    assert.match(script, /preferredTenantSlug/);
    assert.match(script, /displayOnly/);
    assert.match(script, /display-only route/);
    assert.match(script, /region/);
    assert.match(script, /main-or-dialog control/);
    assert.match(script, /interactionFindings/);
    assert.match(script, /## Interaction Findings/);
    assert.match(script, /linkValidations/);
    assert.match(script, /## Link Target Validation/);
    assert.match(script, /filtered_route_scope/);
    assert.doesNotMatch(script, /failures\.push\(['"`]safe_click_failure/);
    assert.match(script, /HRM_FULL_CHAIN_CREATE_PORTAL_FIXTURE/);
    assert.match(script, /HRM_FULL_CHAIN_CREATE_PORTAL_FIXTURE !== '0'/);
    assert.match(script, /cleanupPortalSmokeEmployee/);
    assert.match(script, /fixtureEmployeeId/);
    assert.doesNotMatch(script, /HRM_FULL_CHAIN_SKIP_PORTAL_FIXTURE/);
  });
});
