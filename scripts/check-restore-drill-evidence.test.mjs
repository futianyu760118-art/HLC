import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  evaluateRestoreDrillEvidence,
  formatRestoreDrillEvidenceReport,
  parseRestoreDrillRows,
} from './check-restore-drill-evidence.mjs';

const tracker = (rows) => `# Restore Drill Log

| Date | Environment | MySQL Backup | MinIO Backup | Uploads Backup | Duration | Result | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
${rows.join('\n')}
`;

const validRow = [
  '| 2026-06-26',
  'Docker-enabled SaaS restore env; project hengpintong-saas-preview; http://localhost:18280',
  'mysql-20260626.sql.gz',
  'minio-20260626.tar.gz',
  'uploads-20260626.tar.gz',
  '18m',
  'Pass',
  '/api/health ok; /api/ready db=up; platform login ok; tenant list ok; file download ok; employee portal login ok; evidence ticket OPS-123 |',
].join(' | ');

describe('restore drill evidence checker', () => {
  it('parses restore drill log rows', () => {
    const rows = parseRestoreDrillRows(tracker([validRow]));

    assert.equal(rows.length, 1);
    assert.equal(rows[0].date, '2026-06-26');
    assert.equal(rows[0].result, 'Pass');
  });

  it('passes when a real SaaS restore drill row records required evidence', () => {
    const result = evaluateRestoreDrillEvidence(tracker([validRow]));

    assert.equal(result.ok, true);
    assert.equal(result.acceptedRow.date, '2026-06-26');
    assert.match(formatRestoreDrillEvidenceReport(result), /OK/);
  });

  it('fails when the log only contains a pending non-drill row', () => {
    const result = evaluateRestoreDrillEvidence(tracker([
      '| 2026-06-26 | Current Codex shell | Not run | Not run | Not run | Not run | Pending | Docker CLI unavailable in current shell. |',
    ]));

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'no-valid-pass-row');
    assert.match(formatRestoreDrillEvidenceReport(result), /No valid passing restore drill row/);
  });

  it('rejects pass rows that do not prove the SaaS project and URL target', () => {
    const result = evaluateRestoreDrillEvidence(tracker([
      validRow.replace('project hengpintong-saas-preview; http://localhost:18280', 'local dev environment'),
    ]));

    assert.equal(result.ok, false);
    assert.deepEqual(result.candidateFailures[0].missing, ['hengpintong-saas-preview', 'http://localhost:18280']);
  });

  it('rejects pass rows with placeholder backup values', () => {
    const result = evaluateRestoreDrillEvidence(tracker([
      validRow.replace('mysql-20260626.sql.gz', 'Not run'),
    ]));

    assert.equal(result.ok, false);
    assert.equal(result.candidateFailures[0].missing.includes('MySQL backup'), true);
  });

  it('rejects a passing row dated in the future', () => {
    const result = evaluateRestoreDrillEvidence(tracker([
      validRow.replace('2026-06-26', '2099-01-01'),
    ]));

    assert.equal(result.ok, false);
    assert.equal(result.candidateFailures[0].missing.includes('date'), true);
  });
});
