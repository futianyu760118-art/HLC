import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  evaluateTemplateAlignment,
  formatTemplateAlignmentReport,
} from './check-go-live-evidence-templates.mjs';

const validFiles = {
  'docs/legal-filing-security-evidence-request.md': [
    'privacy policy, terms of service, and DPA/data-processing addendum',
    'production domain plus ICP filing status, or launch-scope decision that ICP is not required',
    'MLPS/等保 applicability decision, expected level, and assessment or filing plan',
  ].join('\n'),
  'docs/data-export-deletion-process.md': 'tenant export request path, requester verification, secure delivery, deletion/anonymization trigger, retention period, and audit evidence process',
  'docs/restore-drill-evidence-request.md': 'docs/restore-drill-log.md for hengpintong-saas-preview at http://localhost:18280, plus npm run verify:restore-drill-evidence output',
  'docs/go-live-owner-evidence-checklist.md': [
    'privacy policy, terms of service, and DPA/data-processing addendum',
    'production domain plus ICP filing status, or launch-scope decision that ICP is not required',
    'MLPS/等保 applicability, level decision, and assessment or filing plan',
    'tenant export request path, requester verification, secure delivery, deletion/anonymization trigger, retention period, and audit evidence process',
    'docs/restore-drill-log.md for hengpintong-saas-preview at http://localhost:18280, plus npm run verify:restore-drill-evidence output',
    'pre-final readiness, public docs sync, restore drill evidence, commercial release gate, health /api/health, ready /api/ready, npm audit, backend dependency audit, and full readiness closure',
  ].join('\n'),
};

describe('go-live evidence template alignment checker', () => {
  it('passes when owner evidence templates include readiness checker keywords', () => {
    const result = evaluateTemplateAlignment({ files: validFiles });

    assert.equal(result.ok, true);
    assert.deepEqual(result.findings, []);
    assert.match(formatTemplateAlignmentReport(result), /OK/);
  });

  it('fails when a template omits required gate details', () => {
    const files = {
      ...validFiles,
      'docs/restore-drill-evidence-request.md': 'restore completed',
    };

    const result = evaluateTemplateAlignment({ files });
    const report = formatTemplateAlignmentReport(result);

    assert.equal(result.ok, false);
    assert.match(report, /restore-drill-evidence-request/);
    assert.match(report, /hengpintong-saas-preview/);
  });
});
