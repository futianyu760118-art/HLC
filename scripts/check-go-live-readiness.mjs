import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');

export const REQUIRED_GATES = [
  'Legal review',
  'ICP filing',
  'MLPS decision',
  'Data export/deletion',
  'Restore drill',
  'Final release gate',
];

export const PRE_FINAL_REQUIRED_GATES = REQUIRED_GATES.filter((gate) => gate !== 'Final release gate');

export function parseReadinessRows(markdown) {
  const lines = markdown.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => {
    const normalized = line.replace(/\s+/g, ' ').trim();
    return normalized === '| Gate | Required evidence | Current status | Owner evidence |';
  });
  if (headerIndex === -1) return [];

  const rows = [];
  for (const line of lines.slice(headerIndex + 2)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('|')) break;

    const cells = trimmed
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim());
    if (cells.length < 4) continue;

    rows.push({
      gate: cells[0],
      requiredEvidence: cells[1],
      status: cells[2],
      ownerEvidence: cells[3],
    });
  }
  return rows;
}

export function parseExternalEvidenceRows(markdown) {
  const lines = markdown.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => {
    const normalized = line.replace(/\s+/g, ' ').trim();
    return normalized === '| Date | Gate | Owner | Evidence | Decision |';
  });
  if (headerIndex === -1) return [];

  const rows = [];
  for (const line of lines.slice(headerIndex + 2)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('|')) break;

    const cells = trimmed
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim());
    if (cells.length < 5) continue;

    rows.push({
      date: cells[0],
      gate: cells[1],
      owner: cells[2],
      evidence: cells[3],
      decision: cells[4],
    });
  }
  return rows;
}

function isEvidenceDateValid(value, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.getTime() <= now.getTime();
}

function referencedArtifactsExist(text, artifactRoot = root) {
  const references = [...String(text || '').matchAll(/(?:^|[\s(])((?:docs|artifacts)\/[A-Za-z0-9_./-]+)/g)]
    .map((match) => match[1].replace(/[),.;]+$/, ''));
  return references.every((reference) => existsSync(resolve(artifactRoot, reference)));
}

function isConcreteAcceptedEvidence(row, options = {}) {
  if (!row || row.decision !== 'Accepted') return false;
  if (!isEvidenceDateValid(row.date, options.now || new Date())) return false;

  const text = [row.owner, row.evidence].join(' ').trim();
  if (!text) return false;
  if (/<[^>]+>/.test(text)) return false;

  if (/\b(TBD|TODO|pending|not attached|owner name|artifact name|ticket link)\b/i.test(text)) return false;
  if (!referencedArtifactsExist(text, options.root || root)) return false;

  return evidenceMeetsGateRequirements(row);
}

function evidenceMeetsGateRequirements(row) {
  const evidence = row.evidence || '';
  const requirementsByGate = {
    'Legal review': [
      /privacy|隐私/i,
      /terms|服务条款|条款/i,
      /\bDPA\b|data processing|数据处理/i,
    ],
    'ICP filing': [
      /domain|域名/i,
      /\bICP\b|备案|launch scope|上线范围|not required|不需要|无需/i,
    ],
    'MLPS decision': [
      /\bMLPS\b|等保/i,
      /applicability|适用|适用性/i,
      /level|等级/i,
      /assessment|filing|测评|备案|plan|计划/i,
    ],
    'Data export/deletion': [
      /export|导出/i,
      /requester verification|requester|identity verification|身份|验证|核验/i,
      /deletion|anonymization|删除|匿名化/i,
      /retention|保留/i,
      /audit|evidence|审计|证据/i,
    ],
    'Restore drill': [
      /restore drill|restore-drill-log|恢复演练/i,
      /Pass|passed|OK|通过/i,
      /hengpintong-saas-preview/i,
      /localhost:18280|http:\/\/localhost:18280/i,
      /verify:restore-drill-evidence|restore-drill-evidence/i,
    ],
    'Final release gate': [
      /pre-final|check-go-live-readiness.*--pre-final|预检/i,
      /public docs sync|verify:public-docs-sync/i,
      /restore drill evidence|verify:restore-drill-evidence/i,
      /commercial release gate|verify-commercial-release-gate/i,
      /health|\/api\/health/i,
      /ready|\/api\/ready/i,
      /npm audit|frontend audit/i,
      /backend dependency audit|verify:backend-dependency-audit/i,
      /full readiness|check-go-live-readiness|closure/i,
    ],
  };

  const requiredPatterns = requirementsByGate[row.gate];
  if (!requiredPatterns) return true;
  return requiredPatterns.every((pattern) => pattern.test(evidence));
}

export function evaluateReadiness(markdown, options = {}) {
  const requiredGates = options.requiredGates || REQUIRED_GATES;
  const rows = parseReadinessRows(markdown);
  const evidenceRows = parseExternalEvidenceRows(markdown);
  const byGate = new Map(rows.map((row) => [row.gate, row]));
  const evidenceOptions = { root: options.root || root, now: options.now || new Date() };
  const validEvidenceRows = evidenceRows.filter((row) => isConcreteAcceptedEvidence(row, evidenceOptions));
  const acceptedEvidenceGates = new Set(
    validEvidenceRows.map((row) => row.gate),
  );
  const invalidEvidence = evidenceRows.filter((row) => (
    requiredGates.includes(row.gate)
      && row.decision === 'Accepted'
      && !acceptedEvidenceGates.has(row.gate)
      && !isConcreteAcceptedEvidence(row, evidenceOptions)
  ));
  const missing = requiredGates.filter((gate) => !byGate.has(gate));
  const pending = requiredGates
    .map((gate) => byGate.get(gate))
    .filter((row) => row && row.status !== 'Accepted');
  const missingEvidence = requiredGates
    .map((gate) => byGate.get(gate))
    .filter((row) => row && row.status === 'Accepted' && !acceptedEvidenceGates.has(row.gate));

  return {
    ready: missing.length === 0 && pending.length === 0 && missingEvidence.length === 0,
    requiredGates,
    rows,
    evidenceRows,
    invalidEvidence,
    pending,
    missing,
    missingEvidence,
  };
}

export function formatReadinessReport(result) {
  const requiredGates = result.requiredGates || REQUIRED_GATES;
  const acceptedCount = requiredGates.length - result.pending.length - result.missing.length - result.missingEvidence.length;
  const lines = [
    `Go-live readiness: ${result.ready ? 'Accepted' : 'Not accepted'}`,
    `Accepted gates: ${acceptedCount}/${requiredGates.length}`,
  ];

  if (result.pending.length) {
    lines.push('', 'Pending gates:');
    for (const row of result.pending) {
      lines.push(`- ${row.gate}: ${row.status} (${row.ownerEvidence})`);
    }
  }

  if (result.missing.length) {
    lines.push('', 'Missing required gates:');
    for (const gate of result.missing) {
      lines.push(`- ${gate}`);
    }
  }

  if (result.invalidEvidence?.length) {
    lines.push('', 'Accepted gates with invalid external evidence:');
    for (const row of result.invalidEvidence) {
      lines.push(`- ${row.gate}: ${row.evidence}`);
    }
  }

  if (result.missingEvidence.length) {
    lines.push('', 'Accepted gates without external evidence:');
    for (const row of result.missingEvidence) {
      lines.push(`- ${row.gate}: ${row.status} (${row.ownerEvidence})`);
    }
  }

  return lines.join('\n');
}

function readArgValue(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return null;
  return args[index + 1] || null;
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('Usage: node scripts/check-go-live-readiness.mjs [--status] [--pre-final] [--file docs/go-live-readiness.md]');
    return 0;
  }

  const statusOnly = args.includes('--status');
  const preFinal = args.includes('--pre-final');
  const fileArg = readArgValue(args, '--file');
  const trackerPath = resolve(root, fileArg || 'docs/go-live-readiness.md');

  if (!existsSync(trackerPath)) {
    console.error(`Go-live readiness tracker not found: ${trackerPath}`);
    return 1;
  }

  const result = evaluateReadiness(readFileSync(trackerPath, 'utf8'), {
    requiredGates: preFinal ? PRE_FINAL_REQUIRED_GATES : REQUIRED_GATES,
  });
  console.log(formatReadinessReport(result));
  return result.ready || statusOnly ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = main();
}
