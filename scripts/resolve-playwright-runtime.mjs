import { existsSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const DEFAULT_NODE_MODULE_DIR = 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules';

const candidateModuleDirs = () => {
  const roots = [
    process.env.PLAYWRIGHT_PNPM_MODULE_DIR,
    process.env.NODE_REPL_NODE_MODULE_DIRS,
    process.env.PLAYWRIGHT_MODULE_DIR,
    DEFAULT_NODE_MODULE_DIR,
    path.resolve('node_modules'),
  ].filter(Boolean);
  return [...new Set(roots)];
};

const findPnpmPlaywrightDir = (moduleDir) => {
  const pnpmRoot = path.join(moduleDir, '.pnpm');
  if (!existsSync(pnpmRoot)) return null;
  const names = readdirSync(pnpmRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => name.startsWith('playwright@'))
    .sort()
    .reverse();
  if (!names.length) return null;
  return path.join(pnpmRoot, names[0], 'node_modules');
};

export async function importPlaywright() {
  try {
    return await import('playwright');
  } catch {
    for (const moduleDir of candidateModuleDirs()) {
      const pnpmDir = findPnpmPlaywrightDir(moduleDir);
      if (pnpmDir) {
        const packageJson = path.join(pnpmDir, 'playwright', 'package.json');
        const corePackageJson = path.join(pnpmDir, 'playwright-core', 'package.json');
        if (existsSync(packageJson) && existsSync(corePackageJson)) {
          const runtimeRequire = createRequire(pathToFileURL(packageJson).href);
          return runtimeRequire('playwright');
        }
      }

      const directPackage = path.join(moduleDir, 'playwright', 'package.json');
      const directCorePackage = path.join(moduleDir, 'playwright-core', 'package.json');
      if (existsSync(directPackage) && existsSync(directCorePackage)) {
        const runtimeRequire = createRequire(pathToFileURL(directPackage).href);
        return runtimeRequire('playwright');
      }
    }

    throw new Error('Playwright runtime was not found. Set PLAYWRIGHT_MODULE_DIR or NODE_REPL_NODE_MODULE_DIRS to a node_modules directory containing playwright and playwright-core.');
  }
}

export const EDGE_EXECUTABLE = process.env.HRM_BROWSER_EXECUTABLE
  || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
