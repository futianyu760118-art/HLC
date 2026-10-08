import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');

const TEMPLATE_REQUIREMENTS = [
  {
    file: 'docs/legal-filing-security-evidence-request.md',
    label: 'Legal review template',
    patterns: [/privacy/i, /terms/i, /\bDPA\b|data-processing|data processing/i],
  },
  {
    file: 'docs/legal-filing-security-evidence-request.md',
    label: 'ICP filing template',
    patterns: [/production domain|域名/i, /\bICP\b|备案|launch-scope|launch scope|not required|不需要|无需/i],
  },
  {
    file: 'docs/legal-filing-security-evidence-request.md',
    label: 'MLPS decision template',
    patterns: [/\bMLPS\b|等保/i, /applicability|适用|适用性/i, /level|等级/i, /assessment|filing|测评|备案|plan|计划/i],
  },
  {
    file: 'docs/data-export-deletion-process.md',
    label: 'Data export/deletion template',
    patterns: [/tenant export request path|租户.*导出/i, /requester verification|请求人.*验证|身份.*核验/i, /deletion\/anonymization trigger|删除|匿名化/i, /retention period|保留期/i, /audit evidence process|审计.*证据/i],
  },
  {
    file: 'docs/restore-drill-evidence-request.md',
    label: 'Restore drill template',
    patterns: [/docs\/restore-drill-log\.md/i, /hengpintong-saas-preview/i, /http:\/\/localhost:18280/i, /verify:restore-drill-evidence|restore-drill-evidence/i],
  },
  {
    file: 'docs/go-live-owner-evidence-checklist.md',
    label: 'Final release template',
    patterns: [/pre-final/i, /public docs sync|verify:public-docs-sync/i, /restore drill evidence|verify:restore-drill-evidence/i, /commercial release gate|verify-commercial-release-gate/i, /\/api\/health|health/i, /\/api\/ready|ready/i, /npm audit|frontend audit/i, /backend dependency audit|verify:backend-dependency-audit/i, /full readiness|closure/i],
  },
];

function readDefaultFiles() {
  const files = {};
  for (const { file } of TEMPLATE_REQUIREMENTS) {
    if (files[file] !== undefined) continue;
    const absolute = resolve(root, file);
    files[file] = existsSync(absolute) ? readFileSync(absolute, 'utf8') : null;
  }
  return files;
}

export function evaluateTemplateAlignment({ files = readDefaultFiles() } = {}) {
  const findings = [];

  for (const requirement of TEMPLATE_REQUIREMENTS) {
    const content = files[requirement.file];
    if (typeof content !== 'string') {
      findings.push(`${requirement.file}: missing file for ${requirement.label}`);
      continue;
    }

    for (const pattern of requirement.patterns) {
      if (!pattern.test(content)) {
        findings.push(`${requirement.file}: ${requirement.label} is missing ${pattern}`);
      }
    }
  }

  return {
    ok: findings.length === 0,
    findings,
  };
}

export function formatTemplateAlignmentReport(result) {
  if (result.ok) {
    return 'Go-live evidence template alignment: OK';
  }

  return [
    'Go-live evidence template alignment: FAILED',
    ...result.findings.map((finding) => `- ${finding}`),
  ].join('\n');
}

function main() {
  const result = evaluateTemplateAlignment();
  console.log(formatTemplateAlignmentReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = main();
}
