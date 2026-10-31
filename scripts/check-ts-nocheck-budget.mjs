import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const DEFAULT_BUDGET = 60;
const budget = Number(process.env.TS_NOCHECK_BUDGET || DEFAULT_BUDGET);
const roots = ['src', 'scripts'];
const extensions = new Set(['.ts', '.tsx', '.js', '.mjs']);
const directivePattern = /^\s*(?:\/\/|\/\*)\s*@ts-nocheck\b/m;

const walk = (dir, out = []) => {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === 'outputs') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (extensions.has(path.extname(entry.name))) out.push(full);
  }
  return out;
};

export function findTsNoCheckFiles(root = ROOT) {
  return roots
    .flatMap((name) => walk(path.join(root, name)))
    .filter((file) => directivePattern.test(readFileSync(file, 'utf8')))
    .map((file) => path.relative(root, file).replace(/\\/g, '/'))
    .sort();
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const files = findTsNoCheckFiles(ROOT);
  console.log(`TypeScript no-check files: ${files.length}/${budget}`);
  for (const file of files) console.log(`- ${file}`);
  if (files.length > budget) {
    console.error(`Too many @ts-nocheck files. Budget is ${budget}, found ${files.length}.`);
    process.exit(1);
  }
}
