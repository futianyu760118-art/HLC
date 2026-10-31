import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');

const DEFAULT_SOURCE_PATH = 'docs/compliance/compliance-checklist.md';
const DEFAULT_PUBLIC_PATH = 'public/docs/compliance/compliance-checklist.md';

function normalizeMarkdown(text) {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n*$/, '\n');
}

function firstMismatchLine(sourceText, publicText) {
  const sourceLines = sourceText.split('\n');
  const publicLines = publicText.split('\n');
  const max = Math.max(sourceLines.length, publicLines.length);

  for (let index = 0; index < max; index += 1) {
    if ((sourceLines[index] || '') !== (publicLines[index] || '')) {
      return {
        line: index + 1,
        sourceLine: sourceLines[index] || '',
        publicLine: publicLines[index] || '',
      };
    }
  }

  return null;
}

export function evaluateComplianceChecklistSync(
  sourcePath = resolve(root, DEFAULT_SOURCE_PATH),
  publicPath = resolve(root, DEFAULT_PUBLIC_PATH),
) {
  if (!existsSync(sourcePath)) {
    return {
      ok: false,
      reason: 'missing-source',
      sourcePath,
      publicPath,
    };
  }

  if (!existsSync(publicPath)) {
    return {
      ok: false,
      reason: 'missing-public',
      sourcePath,
      publicPath,
    };
  }

  const sourceText = normalizeMarkdown(readFileSync(sourcePath, 'utf8'));
  const publicText = normalizeMarkdown(readFileSync(publicPath, 'utf8'));

  if (sourceText === publicText) {
    return {
      ok: true,
      reason: 'matched',
      sourcePath,
      publicPath,
    };
  }

  const mismatch = firstMismatchLine(sourceText, publicText);
  return {
    ok: false,
    reason: 'content-mismatch',
    sourcePath,
    publicPath,
    firstMismatchLine: mismatch?.line || 1,
    sourceLine: mismatch?.sourceLine || '',
    publicLine: mismatch?.publicLine || '',
  };
}

export function formatComplianceChecklistSyncReport(result) {
  if (result.ok) {
    return [
      'Compliance checklist sync: OK',
      `Source and public checklists are in sync: ${result.sourcePath} -> ${result.publicPath}`,
    ].join('\n');
  }

  if (result.reason === 'missing-source') {
    return `Compliance checklist sync: FAILED\nmissing source checklist: ${result.sourcePath}`;
  }

  if (result.reason === 'missing-public') {
    return `Compliance checklist sync: FAILED\nmissing public checklist: ${result.publicPath}`;
  }

  return [
    'Compliance checklist sync: FAILED',
    `source and public checklist content differs at line ${result.firstMismatchLine}`,
    `source: ${result.sourceLine}`,
    `public: ${result.publicLine}`,
  ].join('\n');
}

function readArgValue(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return null;
  return args[index + 1] || null;
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('Usage: node scripts/check-compliance-checklist-sync.mjs [--source docs/compliance/compliance-checklist.md] [--public public/docs/compliance/compliance-checklist.md]');
    return 0;
  }

  const sourceArg = readArgValue(args, '--source');
  const publicArg = readArgValue(args, '--public');
  const result = evaluateComplianceChecklistSync(
    resolve(root, sourceArg || DEFAULT_SOURCE_PATH),
    resolve(root, publicArg || DEFAULT_PUBLIC_PATH),
  );

  console.log(formatComplianceChecklistSyncReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = main();
}
