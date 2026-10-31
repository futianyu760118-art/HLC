import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  evaluateReadiness,
  formatReadinessReport,
  PRE_FINAL_REQUIRED_GATES,
  REQUIRED_GATES,
} from './check-go-live-readiness.mjs';

function evidenceForGate(gate) {
  if (gate === 'Legal review') {
    return 'Legal approval LEGAL-123 covers privacy policy, terms of service, and DPA/data processing addendum for the production operating entity';
  }
  if (gate === 'ICP filing') {
    return 'Domain owner approval ICP-123 confirms production domain hrm.example.com filing status or no-ICP launch scope decision before public access';
  }
  if (gate === 'MLPS decision') {
    return 'Security approval SEC-123 records MLPS applicability, level 2 decision, and assessment filing plan';
  }
  if (gate === 'Data export/deletion') {
    return 'Product owner approval DATA-123 covers tenant export request path, requester verification, secure delivery, deletion/anonymization trigger, retention period, and audit evidence process';
  }
  if (gate === 'Restore drill') {
    return 'Operations approval OPS-123 references docs/restore-drill-log.md restore drill Pass row for hengpintong-saas-preview at http://localhost:18280 and npm run verify:restore-drill-evidence OK';
  }
  if (gate === 'Final release gate') {
    return 'Release owner approval REL-123 records pre-final readiness, public docs sync, restore drill evidence, commercial release gate, health /api/health ok, ready /api/ready db=up, npm audit, backend dependency audit, and full readiness closure';
  }
  return `approval artifact for ${gate}`;
}

const externalEvidenceRows = REQUIRED_GATES.map(
  (gate) => `| 2026-06-26 | ${gate} | ${gate} owner | ${evidenceForGate(gate)} | Accepted |`,
);

const trackerWithRows = (rows, evidenceRows = []) => `# SaaS Go-Live Readiness

| Gate | Required evidence | Current status | Owner evidence |
| --- | --- | --- | --- |
${rows.join('\n')}

## Evidence Rules

## External Owner Evidence

| Date | Gate | Owner | Evidence | Decision |
| --- | --- | --- | --- | --- |
${evidenceRows.join('\n')}
`;

const acceptedRows = REQUIRED_GATES.map(
  (gate) => `| ${gate} | Evidence for ${gate} | Accepted | 2026-06-26 owner approval |`,
);

describe('go-live readiness checker', () => {
  it('passes only when every required go-live gate is Accepted', () => {
    const result = evaluateReadiness(trackerWithRows(acceptedRows, externalEvidenceRows));

    assert.equal(result.ready, true);
    assert.deepEqual(result.pending, []);
    assert.deepEqual(result.missing, []);
    assert.deepEqual(result.missingEvidence, []);
  });

  it('reports pending gates that are not Accepted', () => {
    const rows = [
      ...acceptedRows.slice(0, 2),
      '| MLPS decision | Security decision | Pending owner evidence | Not attached |',
      ...acceptedRows.slice(3),
    ];

    const result = evaluateReadiness(trackerWithRows(rows, externalEvidenceRows));
    const report = formatReadinessReport(result);

    assert.equal(result.ready, false);
    assert.deepEqual(result.pending.map((row) => row.gate), ['MLPS decision']);
    assert.match(report, /MLPS decision/);
    assert.match(report, /Pending owner evidence/);
  });

  it('fails readiness when a required gate row is missing', () => {
    const result = evaluateReadiness(trackerWithRows(acceptedRows.slice(1), externalEvidenceRows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missing, ['Legal review']);
  });

  it('fails readiness when an Accepted gate has no external owner evidence row', () => {
    const result = evaluateReadiness(trackerWithRows(acceptedRows, externalEvidenceRows.slice(1)));
    const report = formatReadinessReport(result);

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), ['Legal review']);
    assert.match(report, /Accepted gates: 5\/6/);
    assert.match(report, /Accepted gates without external evidence/);
    assert.match(report, /Legal review/);
  });

  it('fails readiness when an Accepted evidence row still contains placeholders', () => {
    const rows = [
      '| 2026-06-26 | Legal review | <owner role/name> | <approval artifact or ticket> | Accepted |',
      ...externalEvidenceRows.slice(1),
    ];

    const result = evaluateReadiness(trackerWithRows(acceptedRows, rows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), ['Legal review']);
  });

  it('fails readiness when data export/deletion evidence omits lifecycle controls', () => {
    const weakEvidenceRows = externalEvidenceRows.map((row) => (
      row.includes('| Data export/deletion |')
        ? '| 2026-06-26 | Data export/deletion | Product owner | Approved process DATA-123 | Accepted |'
        : row
    ));

    const result = evaluateReadiness(trackerWithRows(acceptedRows, weakEvidenceRows));
    const report = formatReadinessReport(result);

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), ['Data export/deletion']);
    assert.match(report, /Data export\/deletion/);
  });

  it('fails readiness when legal filing or security evidence omits gate details', () => {
    const weakEvidenceRows = externalEvidenceRows.map((row) => {
      if (row.includes('| Legal review |')) {
        return '| 2026-06-26 | Legal review | Legal owner | Legal approved LEGAL-123 | Accepted |';
      }
      if (row.includes('| ICP filing |')) {
        return '| 2026-06-26 | ICP filing | Domain owner | ICP approved ICP-123 | Accepted |';
      }
      if (row.includes('| MLPS decision |')) {
        return '| 2026-06-26 | MLPS decision | Security owner | Security reviewed SEC-123 | Accepted |';
      }
      return row;
    });

    const result = evaluateReadiness(trackerWithRows(acceptedRows, weakEvidenceRows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), [
      'Legal review',
      'ICP filing',
      'MLPS decision',
    ]);
  });

  it('reports invalid external evidence rows separately from missing rows', () => {
    const weakEvidenceRows = externalEvidenceRows.map((row) => (
      row.includes('| Legal review |')
        ? '| 2026-06-26 | Legal review | Legal owner | Legal approved LEGAL-123 | Accepted |'
        : row
    ));

    const result = evaluateReadiness(trackerWithRows(acceptedRows, weakEvidenceRows));
    const report = formatReadinessReport(result);

    assert.deepEqual(result.invalidEvidence.map((row) => row.gate), ['Legal review']);
    assert.match(report, /Accepted gates with invalid external evidence/);
    assert.match(report, /Legal approved LEGAL-123/);
  });

  it('fails readiness when restore or final release evidence omits command details', () => {
    const weakEvidenceRows = externalEvidenceRows.map((row) => {
      if (row.includes('| Restore drill |')) {
        return '| 2026-06-26 | Restore drill | Operations owner | Restore completed OPS-123 | Accepted |';
      }
      if (row.includes('| Final release gate |')) {
        return '| 2026-06-26 | Final release gate | Release owner | Release approved REL-123 | Accepted |';
      }
      return row;
    });

    const result = evaluateReadiness(trackerWithRows(acceptedRows, weakEvidenceRows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), [
      'Restore drill',
      'Final release gate',
    ]);
  });

  it('supports pre-final readiness before the Final release gate is recorded', () => {
    const rows = [
      ...acceptedRows.slice(0, -1),
      '| Final release gate | Final verification | Pending owner evidence | Final rerun not attached |',
    ];
    const evidenceRows = externalEvidenceRows.filter((row) => !row.includes('| Final release gate |'));

    const result = evaluateReadiness(trackerWithRows(rows, evidenceRows), {
      requiredGates: PRE_FINAL_REQUIRED_GATES,
    });
    const report = formatReadinessReport(result);

    assert.equal(result.ready, true);
    assert.equal(PRE_FINAL_REQUIRED_GATES.includes('Final release gate'), false);
    assert.match(report, /Accepted gates: 5\/5/);
  });

  it('rejects accepted evidence dated in the future', () => {
    const futureEvidenceRows = externalEvidenceRows.map((row) => (
      row.includes('| Legal review |')
        ? row.replace('2026-06-26', '2099-01-01')
        : row
    ));
    const result = evaluateReadiness(trackerWithRows(acceptedRows, futureEvidenceRows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), ['Legal review']);
  });

  it('rejects evidence that references a missing repository artifact', () => {
    const missingArtifactRows = externalEvidenceRows.map((row) => (
      row.includes('| Legal review |')
        ? row.replace('LEGAL-123', 'docs/missing-legal-approval.md')
        : row
    ));
    const result = evaluateReadiness(trackerWithRows(acceptedRows, missingArtifactRows));

    assert.equal(result.ready, false);
    assert.deepEqual(result.missingEvidence.map((row) => row.gate), ['Legal review']);
  });
});
