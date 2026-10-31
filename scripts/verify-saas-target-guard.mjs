import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');

const forbiddenTargets = [
  ['localhost:', '18080'].join(''),
  ['localhost:', '18443'].join(''),
  ['hengpintong', '-next'].join(''),
];
const forbiddenOperationalDefaults = [
  ['hengpintong', '_next'].join(''),
];

const rootFiles = [
  '.env.example',
  'docker-compose.yml',
  'init-readonly-user.sh',
  'init.sql',
  ...readdirSync(root).filter((name) => name.endsWith('.ps1')),
];
const scriptFiles = readdirSync(join(root, 'scripts'))
  .filter((name) => name.endsWith('.mjs'))
  .map((name) => `scripts/${name}`);
const sourceExtensions = new Set(['.css', '.html', '.js', '.jsx', '.ts', '.tsx']);

function listSourceFiles(relativeDir) {
  const absoluteDir = join(root, relativeDir);
  if (!existsSync(absoluteDir)) return [];

  return readdirSync(absoluteDir, { withFileTypes: true }).flatMap((entry) => {
    const relativePath = `${relativeDir}/${entry.name}`;
    if (entry.isDirectory()) {
      return listSourceFiles(relativePath);
    }
    if (entry.isFile() && sourceExtensions.has(extname(entry.name))) {
      return [relativePath];
    }
    return [];
  });
}

const sourceFiles = listSourceFiles('src');

const findings = [];

for (const file of [...rootFiles, ...scriptFiles, ...sourceFiles]) {
  const absolutePath = join(root, file);
  if (!existsSync(absolutePath)) continue;
  const text = readFileSync(absolutePath, 'utf8');
  for (const target of forbiddenTargets) {
    if (text.includes(target)) {
      findings.push(`${file}: contains ${target}`);
    }
  }
}

for (const file of ['.env.example', 'docker-compose.yml', 'init-readonly-user.sh', 'init.sql']) {
  const absolutePath = join(root, file);
  if (!existsSync(absolutePath)) continue;
  const text = readFileSync(absolutePath, 'utf8');
  for (const target of forbiddenOperationalDefaults) {
    if (text.includes(target)) {
      findings.push(`${file}: contains operational default ${target}`);
    }
  }
}

if (findings.length) {
  console.error(findings.join('\n'));
  process.exit(1);
}

console.log('SaaS target guard passed');
