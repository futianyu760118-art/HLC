import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  evaluateComplianceChecklistSync,
  formatComplianceChecklistSyncReport,
} from './check-compliance-checklist-sync.mjs';

function withChecklistFiles(sourceText, publicText = sourceText) {
  const root = mkdtempSync(join(tmpdir(), 'hrm-compliance-sync-'));
  const sourcePath = join(root, 'docs', 'compliance', 'compliance-checklist.md');
  const publicPath = join(root, 'public', 'docs', 'compliance', 'compliance-checklist.md');
  mkdirSync(join(root, 'docs', 'compliance'), { recursive: true });
  mkdirSync(join(root, 'public', 'docs', 'compliance'), { recursive: true });
  writeFileSync(sourcePath, sourceText, 'utf8');
  if (publicText !== null) writeFileSync(publicPath, publicText, 'utf8');

  return {
    root,
    sourcePath,
    publicPath,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  };
}

describe('compliance checklist sync checker', () => {
  it('passes when source and public compliance checklists match', () => {
    const files = withChecklistFiles('# Checklist\r\n\n| A | B |\r\n');
    try {
      const result = evaluateComplianceChecklistSync(files.sourcePath, files.publicPath);

      assert.equal(result.ok, true);
      assert.equal(result.reason, 'matched');
      assert.match(formatComplianceChecklistSyncReport(result), /in sync/);
    } finally {
      files.cleanup();
    }
  });

  it('fails when public checklist content differs from the source checklist', () => {
    const files = withChecklistFiles('# Checklist\n\n| ICP | Pending |\n', '# Checklist\n\n| ICP | Accepted |\n');
    try {
      const result = evaluateComplianceChecklistSync(files.sourcePath, files.publicPath);
      const report = formatComplianceChecklistSyncReport(result);

      assert.equal(result.ok, false);
      assert.equal(result.reason, 'content-mismatch');
      assert.equal(result.firstMismatchLine, 3);
      assert.match(report, /content differs/);
      assert.match(report, /line 3/);
    } finally {
      files.cleanup();
    }
  });

  it('fails when the public compliance checklist is missing', () => {
    const files = withChecklistFiles('# Checklist\n', null);
    try {
      const result = evaluateComplianceChecklistSync(files.sourcePath, files.publicPath);

      assert.equal(result.ok, false);
      assert.equal(result.reason, 'missing-public');
      assert.match(formatComplianceChecklistSyncReport(result), /missing public checklist/);
    } finally {
      files.cleanup();
    }
  });
});
