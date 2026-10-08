import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');

function normalizeMarkdown(text) {
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n*$/, '\n');
}

function walkMarkdownFiles(dir) {
  if (!existsSync(dir)) return [];
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkMarkdownFiles(path));
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      files.push(path);
    }
  }
  return files.sort();
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

function toPortablePath(path) {
  return path.split(sep).join('/');
}

export function evaluatePublicDocsSync(rootDir = root) {
  const sourceRoot = resolve(rootDir, 'docs');
  const publicRoot = resolve(rootDir, 'public/docs');
  const publicFiles = walkMarkdownFiles(publicRoot);
  const checked = [];
  const missingSources = [];
  const mismatches = [];

  for (const publicPath of publicFiles) {
    const relativePath = toPortablePath(relative(publicRoot, publicPath));
    const sourcePath = resolve(sourceRoot, relativePath);
    checked.push({ relativePath, sourcePath, publicPath });

    if (!existsSync(sourcePath)) {
      missingSources.push({ relativePath, sourcePath, publicPath });
      continue;
    }

    const sourceText = normalizeMarkdown(readFileSync(sourcePath, 'utf8'));
    const publicText = normalizeMarkdown(readFileSync(publicPath, 'utf8'));
    if (sourceText !== publicText) {
      const mismatch = firstMismatchLine(sourceText, publicText);
      mismatches.push({
        relativePath,
        sourcePath,
        publicPath,
        firstMismatchLine: mismatch?.line || 1,
        sourceLine: mismatch?.sourceLine || '',
        publicLine: mismatch?.publicLine || '',
      });
    }
  }

  return {
    ok: missingSources.length === 0 && mismatches.length === 0,
    checked,
    missingSources,
    mismatches,
  };
}

export function formatPublicDocsSyncReport(result) {
  if (result.ok) {
    return [
      'Public docs sync: OK',
      `Checked markdown files: ${result.checked.length}`,
    ].join('\n');
  }

  const lines = ['Public docs sync: FAILED'];

  if (result.missingSources.length) {
    lines.push('', 'Missing source docs:');
    for (const row of result.missingSources) {
      lines.push(`- ${row.relativePath}`);
    }
  }

  if (result.mismatches.length) {
    lines.push('', 'Public docs with content differs:');
    for (const row of result.mismatches) {
      lines.push(`- ${row.relativePath} at line ${row.firstMismatchLine}`);
    }
  }

  return lines.join('\n');
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('Usage: node scripts/check-public-docs-sync.mjs');
    return 0;
  }

  const result = evaluatePublicDocsSync(root);
  console.log(formatPublicDocsSyncReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = main();
}
