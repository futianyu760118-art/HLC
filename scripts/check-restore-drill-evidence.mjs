import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');
const DEFAULT_LOG_PATH = 'docs/restore-drill-log.md';

const PLACEHOLDER_PATTERN = /^(|not run|pending|tbd|todo|n\/a|-|<[^>]+>)$/i;

const REQUIRED_TEXT = [
  'hengpintong-saas-preview',
  'http://localhost:18280',
  '/api/health',
  '/api/ready',
  'platform login',
  'tenant list',
  'file download',
  'employee portal',
];

export function parseRestoreDrillRows(markdown) {
  const lines = markdown.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => {
    const normalized = line.replace(/\s+/g, ' ').trim();
    return normalized === '| Date | Environment | MySQL Backup | MinIO Backup | Uploads Backup | Duration | Result | Notes |';
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
    if (cells.length < 8) continue;

    rows.push({
      date: cells[0],
      environment: cells[1],
      mysqlBackup: cells[2],
      minioBackup: cells[3],
      uploadsBackup: cells[4],
      duration: cells[5],
      result: cells[6],
      notes: cells[7],
    });
  }
  return rows;
}

function isConcrete(value) {
  return !PLACEHOLDER_PATTERN.test((value || '').trim());
}

function isValidEvidenceDate(value, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.getTime() <= now.getTime();
}

function missingEvidenceForRow(row) {
  const missing = [];
  const searchable = `${row.environment} ${row.notes}`.toLowerCase();

  if (!isValidEvidenceDate(row.date)) missing.push('date');
  if (!isConcrete(row.mysqlBackup)) missing.push('MySQL backup');
  if (!isConcrete(row.minioBackup)) missing.push('MinIO backup');
  if (!isConcrete(row.uploadsBackup)) missing.push('uploads backup');
  if (!isConcrete(row.duration)) missing.push('duration');

  for (const required of REQUIRED_TEXT) {
    if (!searchable.includes(required.toLowerCase())) missing.push(required);
  }

  return missing;
}

export function evaluateRestoreDrillEvidence(markdown) {
  const rows = parseRestoreDrillRows(markdown);
  const passRows = rows.filter((row) => row.result.toLowerCase() === 'pass');
  const candidateFailures = [];

  for (const row of passRows) {
    const missing = missingEvidenceForRow(row);
    if (missing.length === 0) {
      return {
        ok: true,
        reason: 'accepted',
        rows,
        acceptedRow: row,
        candidateFailures,
      };
    }
    candidateFailures.push({ row, missing });
  }

  return {
    ok: false,
    reason: 'no-valid-pass-row',
    rows,
    candidateFailures,
  };
}

export function formatRestoreDrillEvidenceReport(result) {
  if (result.ok) {
    return [
      'Restore drill evidence: OK',
      `Accepted row date: ${result.acceptedRow.date}`,
      `Environment: ${result.acceptedRow.environment}`,
    ].join('\n');
  }

  const lines = [
    'Restore drill evidence: NOT_ACCEPTED',
    'No valid passing restore drill row was found.',
  ];

  if (result.candidateFailures.length) {
    lines.push('', 'Rejected pass rows:');
    for (const failure of result.candidateFailures) {
      lines.push(`- ${failure.row.date || '(missing date)'} missing: ${failure.missing.join(', ')}`);
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
    console.log('Usage: node scripts/check-restore-drill-evidence.mjs [--file docs/restore-drill-log.md]');
    return 0;
  }

  const fileArg = readArgValue(args, '--file');
  const logPath = resolve(root, fileArg || DEFAULT_LOG_PATH);
  if (!existsSync(logPath)) {
    console.error(`Restore drill log not found: ${logPath}`);
    return 1;
  }

  const result = evaluateRestoreDrillEvidence(readFileSync(logPath, 'utf8'));
  console.log(formatRestoreDrillEvidenceReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = main();
}
