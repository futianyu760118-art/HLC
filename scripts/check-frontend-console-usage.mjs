import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const allowedFiles = new Set([
  'src/main.tsx',
  'src/router/ErrorPage.tsx',
  'src/components/ErrorBoundary.tsx',
  'src/pages/p-approval_center/index.tsx',
  'src/pages/p-attendance_stats/index.tsx',
  'src/pages/p-employee_requests/index.tsx',
  'src/pages/p-feedback/index.tsx',
  'src/pages/p-home/index.tsx',
  'src/pages/p-interview_room/index.tsx',
  'src/pages/p-interview_manage/index.tsx',
  'src/pages/p-login/index.tsx',
  'src/pages/p-notifications/index.tsx',
  'src/pages/p-operation_logs/index.tsx',
  'src/pages/p-performance_review/index.tsx',
  'src/pages/p-report/index.tsx',
  'src/pages/p-salary_profiles/index.tsx',
  'src/pages/p-system_settings/index.tsx',
]);
const consolePattern = /\bconsole\.(log|warn|error|debug|info)\s*\(/g;

const walk = (dir, out = []) => {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
};

export function findDisallowedConsoleUsage(root = ROOT) {
  return walk(path.join(root, 'src'))
    .flatMap((file) => {
      const rel = path.relative(root, file).replace(/\\/g, '/');
      if (allowedFiles.has(rel)) return [];
      const text = readFileSync(file, 'utf8');
      const hits = [];
      const lines = text.split(/\r?\n/);
      for (let index = 0; index < lines.length; index += 1) {
        if (consolePattern.test(lines[index])) hits.push(`${rel}:${index + 1}`);
        consolePattern.lastIndex = 0;
      }
      return hits;
    })
    .sort();
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const hits = findDisallowedConsoleUsage(ROOT);
  if (hits.length) {
    console.error('Disallowed frontend console usage:');
    for (const hit of hits) console.error(`- ${hit}`);
    process.exit(1);
  }
  console.log('Frontend console usage: OK');
}
