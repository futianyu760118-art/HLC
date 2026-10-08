import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  evaluatePublicDocsSync,
  formatPublicDocsSyncReport,
} from './check-public-docs-sync.mjs';

function withDocs(files) {
  const root = mkdtempSync(join(tmpdir(), 'hrm-public-docs-sync-'));
  for (const [file, text] of Object.entries(files)) {
    const path = join(root, ...file.split('/'));
    mkdirSync(path.slice(0, path.lastIndexOf('\\')), { recursive: true });
    writeFileSync(path, text, 'utf8');
  }
  return {
    root,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  };
}

describe('public docs sync checker', () => {
  it('passes when every public markdown file has a matching source markdown file', () => {
    const files = withDocs({
      'docs/customer-onboarding.md': '# Onboarding\r\n',
      'public/docs/customer-onboarding.md': '# Onboarding\n',
      'docs/compliance/privacy-policy.md': '# Privacy\n',
      'public/docs/compliance/privacy-policy.md': '# Privacy\n',
    });
    try {
      const result = evaluatePublicDocsSync(files.root);

      assert.equal(result.ok, true);
      assert.equal(result.checked.length, 2);
      assert.match(formatPublicDocsSyncReport(result), /OK/);
    } finally {
      files.cleanup();
    }
  });

  it('fails when a public markdown file has no source counterpart', () => {
    const files = withDocs({
      'public/docs/support-sla.md': '# SLA\n',
    });
    try {
      const result = evaluatePublicDocsSync(files.root);

      assert.equal(result.ok, false);
      assert.deepEqual(result.missingSources.map((row) => row.relativePath), ['support-sla.md']);
    } finally {
      files.cleanup();
    }
  });

  it('fails when a public markdown file differs from its source counterpart', () => {
    const files = withDocs({
      'docs/compliance/compliance-checklist.md': '# Checklist\n\nPending\n',
      'public/docs/compliance/compliance-checklist.md': '# Checklist\n\nAccepted\n',
    });
    try {
      const result = evaluatePublicDocsSync(files.root);
      const report = formatPublicDocsSyncReport(result);

      assert.equal(result.ok, false);
      assert.equal(result.mismatches[0].relativePath, 'compliance/compliance-checklist.md');
      assert.equal(result.mismatches[0].firstMismatchLine, 3);
      assert.match(report, /content differs/);
    } finally {
      files.cleanup();
    }
  });
});
