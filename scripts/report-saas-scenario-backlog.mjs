import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');
const DEFAULT_OUTPUT_DIR = 'artifacts/browser-verification';
const STALE_TARGET_PATTERN = /(?:localhost|127\.0\.0\.1):18080/;

function portableTimestamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, '0');
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('');
}

function resolveFromRoot(path) {
  return resolve(root, path);
}

export function findLatestFullChainAuditInput({ artifactDir = resolveFromRoot(DEFAULT_OUTPUT_DIR) } = {}) {
  const resolvedArtifactDir = resolve(artifactDir);
  if (!existsSync(resolvedArtifactDir)) {
    throw new Error(`Browser verification artifact directory not found: ${resolvedArtifactDir}`);
  }

  const candidates = readdirSync(resolvedArtifactDir)
    .filter((name) => /^full-chain-interactions-\d{14}\.json$/.test(name))
    .map((name) => {
      const fullPath = join(resolvedArtifactDir, name);
      let routeCount = 0;
      try {
        const parsed = JSON.parse(readFileSync(fullPath, 'utf8'));
        routeCount = Number(parsed.routeCount || parsed.results?.length || 0);
      } catch {
        routeCount = 0;
      }
      return { fullPath, routeCount, mtimeMs: statSync(fullPath).mtimeMs };
    })
    .sort((a, b) => {
      const nameCompare = b.fullPath.localeCompare(a.fullPath);
      if (nameCompare !== 0) return nameCompare;
      return b.mtimeMs - a.mtimeMs;
    });

  if (!candidates.length) {
    throw new Error(`No full-chain interaction audit JSON reports found in: ${resolvedArtifactDir}`);
  }
  return (candidates.find((candidate) => candidate.routeCount >= 50) || candidates[0]).fullPath;
}

function assertNoStaleTarget(value, label) {
  if (typeof value === 'string') {
    if (STALE_TARGET_PATTERN.test(value)) {
      throw new Error(`Refusing ${label} with stale 18080 target: ${value}`);
    }
    return;
  }

  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoStaleTarget(item, `${label}[${index}]`));
    return;
  }

  if (value && typeof value === 'object') {
    for (const [key, nestedValue] of Object.entries(value)) {
      assertNoStaleTarget(nestedValue, `${label}.${key}`);
    }
  }
}

function groupKey(item) {
  return JSON.stringify([
    item.route || '(unknown route)',
    item.reason || '(no reason)',
    item.action || 'unspecified',
  ]);
}

function sampleFrom(item) {
  return {
    route: item.route || '',
    routeLabel: item.routeLabel || '',
    control: item.control || '',
    tag: item.tag || '',
    action: item.action || '',
    reason: item.reason || '',
    text: item.text || '',
    role: item.role || '',
    locator: item.locator || '',
    href: item.href || '',
  };
}

function compareCountThenName(a, b) {
  if (b.count !== a.count) return b.count - a.count;
  return String(a.route || a.reason || '').localeCompare(String(b.route || b.reason || ''));
}

export function evaluateScenarioBacklog({
  inputPath = findLatestFullChainAuditInput(),
  sampleLimit = 5,
} = {}) {
  const resolvedInput = resolve(inputPath);
  if (!existsSync(resolvedInput)) {
    throw new Error(`Scenario backlog audit input not found: ${resolvedInput}`);
  }

  const audit = JSON.parse(readFileSync(resolvedInput, 'utf8'));
  assertNoStaleTarget(audit, 'audit');

  if (!Array.isArray(audit.scenarioBacklog)) {
    throw new Error('Audit JSON does not include a scenarioBacklog array');
  }

  const routeMap = new Map();
  const groupMap = new Map();

  for (const item of audit.scenarioBacklog) {
    const route = item.route || '(unknown route)';
    const routeLabel = item.routeLabel || '';
    if (!routeMap.has(route)) {
      routeMap.set(route, {
        route,
        routeLabel,
        count: 0,
        groups: [],
      });
    }

    const routeEntry = routeMap.get(route);
    routeEntry.count += 1;
    if (!routeEntry.routeLabel && routeLabel) routeEntry.routeLabel = routeLabel;

    const key = groupKey(item);
    if (!groupMap.has(key)) {
      const group = {
        route,
        routeLabel,
        reason: item.reason || '(no reason)',
        action: item.action || 'unspecified',
        count: 0,
        samples: [],
      };
      groupMap.set(key, group);
      routeEntry.groups.push(group);
    }

    const group = groupMap.get(key);
    group.count += 1;
    if (group.samples.length < sampleLimit) {
      group.samples.push(sampleFrom(item));
    }
  }

  const routes = [...routeMap.values()]
    .map((route) => ({
      ...route,
      groups: route.groups.sort(compareCountThenName),
    }))
    .sort(compareCountThenName);

  return {
    ok: true,
    source: {
      inputPath: resolvedInput,
      runId: audit.runId || '',
      baseUrl: audit.baseUrl || '',
      checkedAt: audit.checkedAt || '',
    },
    generatedAt: new Date().toISOString(),
    totalBacklog: audit.scenarioBacklog.length,
    uniqueRouteCount: routes.length,
    topRoutes: routes.slice(0, 10).map((route) => ({
      route: route.route,
      routeLabel: route.routeLabel,
      count: route.count,
    })),
    routes,
  };
}

export function formatScenarioBacklogMarkdown(report) {
  const lines = [
    '# SaaS Scenario Backlog Report',
    '',
    `- Source: ${report.source.inputPath}`,
    `- Run ID: ${report.source.runId || '(unknown)'}`,
    `- Base URL: ${report.source.baseUrl || '(unknown)'}`,
    `- Generated at: ${report.generatedAt}`,
    `- Total backlog: ${report.totalBacklog}`,
    `- Unique routes: ${report.uniqueRouteCount}`,
    '',
    '## Top Routes',
    '',
  ];

  for (const route of report.topRoutes) {
    lines.push(`- ${route.route}${route.routeLabel ? ` (${route.routeLabel})` : ''}: ${route.count}`);
  }

  lines.push('', '## Groups', '');

  for (const route of report.routes) {
    lines.push(`### ${route.route}${route.routeLabel ? ` (${route.routeLabel})` : ''}`, '');
    lines.push(`Backlog items: ${route.count}`, '');

    for (const group of route.groups) {
      lines.push(`- Reason: ${group.reason}`);
      lines.push(`  Action: ${group.action}`);
      lines.push(`  Count: ${group.count}`);
      lines.push('  Samples:');
      for (const sample of group.samples) {
        const details = [
          sample.control && `control=${sample.control}`,
          sample.tag && `tag=${sample.tag}`,
          sample.text && `text=${sample.text}`,
          sample.href && `href=${sample.href}`,
        ].filter(Boolean).join('; ');
        lines.push(`  - ${details || '(no control details)'}`);
      }
      lines.push('');
    }
  }

  return `${lines.join('\n').trimEnd()}\n`;
}

export function writeScenarioBacklogReports(report, {
  outputDir = resolveFromRoot(DEFAULT_OUTPUT_DIR),
  timestamp = portableTimestamp(),
} = {}) {
  const resolvedOutputDir = resolve(outputDir);
  mkdirSync(resolvedOutputDir, { recursive: true });
  const jsonPath = join(resolvedOutputDir, `scenario-backlog-${timestamp}.json`);
  const markdownPath = join(resolvedOutputDir, `scenario-backlog-${timestamp}.md`);

  assertNoStaleTarget(jsonPath, 'JSON report path');
  assertNoStaleTarget(markdownPath, 'Markdown report path');

  const jsonReport = {
    ...report,
    outputs: {
      jsonPath,
      markdownPath,
    },
  };

  writeFileSync(jsonPath, `${JSON.stringify(jsonReport, null, 2)}\n`, 'utf8');
  writeFileSync(markdownPath, formatScenarioBacklogMarkdown(jsonReport), 'utf8');

  return { jsonPath, markdownPath };
}

export function formatScenarioBacklogSummary(report) {
  const outputs = report.outputs || {};
  const lines = [
    'SaaS scenario backlog report: OK',
    `Total backlog: ${report.totalBacklog}`,
    `Unique routes: ${report.uniqueRouteCount}`,
    'Top routes:',
  ];

  for (const route of report.topRoutes.slice(0, 5)) {
    lines.push(`- ${route.route}${route.routeLabel ? ` (${route.routeLabel})` : ''}: ${route.count}`);
  }

  if (outputs.jsonPath || outputs.markdownPath) {
    lines.push('Output paths:');
    if (outputs.jsonPath) lines.push(`- JSON: ${outputs.jsonPath}`);
    if (outputs.markdownPath) lines.push(`- Markdown: ${outputs.markdownPath}`);
  }

  return lines.join('\n');
}

function parseArgs(args) {
  const parsed = {
    inputPath: findLatestFullChainAuditInput(),
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--help') {
      parsed.help = true;
    } else if (arg === '--input') {
      const value = args[index + 1];
      if (!value) throw new Error('Missing value for --input');
      parsed.inputPath = resolve(value);
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return parsed;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Usage: node scripts/report-saas-scenario-backlog.mjs [--input <path>]');
    return 0;
  }

  const report = evaluateScenarioBacklog({ inputPath: args.inputPath });
  const outputs = writeScenarioBacklogReports(report);
  console.log(formatScenarioBacklogSummary({ ...report, outputs }));
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
