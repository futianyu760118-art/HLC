import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { scenarioCoverageDefinitions } from './saas-scenario-coverage-definitions.mjs';
import { findLatestFullChainAuditInput } from './report-saas-scenario-backlog.mjs';

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

function assertNoStaleTarget(value, label = 'value') {
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

const compact = (value) => String(value || '').replace(/\s+/g, ' ').trim();

function normalizeControlMatcher(value) {
  if (value instanceof RegExp) return value;
  return compact(value);
}

function matchesOne(matcher, actual) {
  const text = compact(actual);
  if (matcher instanceof RegExp) return matcher.test(text);
  return compact(matcher) === text;
}

function definitionMatchers(definition) {
  const values = [];
  if (definition.control !== undefined) values.push(definition.control);
  if (Array.isArray(definition.controls)) values.push(...definition.controls);
  return values.map(normalizeControlMatcher);
}

function normalizeBacklogItem(item, index = 0) {
  return {
    index,
    route: item.route || '',
    routeLabel: item.routeLabel || '',
    reason: item.reason || '(no reason)',
    action: item.action || 'unspecified',
    tag: item.tag || '',
    control: item.control || item.text || item.placeholder || item.href || '',
    role: item.role || '',
    href: item.href || '',
  };
}

function extractBacklog(audit) {
  if (Array.isArray(audit?.scenarioBacklog)) {
    return audit.scenarioBacklog.map(normalizeBacklogItem);
  }

  if (Array.isArray(audit?.routes)) {
    const items = [];
    for (const route of audit.routes) {
      for (const group of route.groups || []) {
        for (const sample of group.samples || []) {
          items.push(normalizeBacklogItem({
            route: group.route || route.route,
            routeLabel: group.routeLabel || route.routeLabel,
            reason: group.reason,
            action: group.action,
            tag: sample.tag,
            control: sample.control || sample.text || sample.placeholder || sample.href,
            role: sample.role,
            href: sample.href,
          }, items.length));
        }
      }
    }
    return items;
  }

  throw new Error('Coverage input must include scenarioBacklog or grouped routes');
}

export function matchCoverageDefinition(definition, backlogItem) {
  const item = normalizeBacklogItem(backlogItem);
  if (definition.route && definition.route !== item.route) return false;
  if (definition.reason && definition.reason !== item.reason) return false;
  if (definition.action && definition.action !== item.action) return false;

  const tags = [
    ...(definition.tag ? [definition.tag] : []),
    ...(Array.isArray(definition.tags) ? definition.tags : []),
  ].map(compact).filter(Boolean);
  if (tags.length && !tags.includes(compact(item.tag))) return false;

  const matchers = definitionMatchers(definition);
  if (matchers.length && !matchers.some((matcher) => matchesOne(matcher, item.control))) return false;

  return true;
}

function itemGroupKey(item) {
  return JSON.stringify([item.route, item.reason, item.action]);
}

function countDefinitionsById(definitions) {
  const counts = new Map();
  for (const definition of definitions) {
    counts.set(definition.id, (counts.get(definition.id) || 0) + 1);
  }
  return counts;
}

function compareCountThenName(a, b) {
  if (b.count !== a.count) return b.count - a.count;
  return String(a.route || '').localeCompare(String(b.route || ''));
}

export function evaluateScenarioCoverage({ audit, definitions = scenarioCoverageDefinitions } = {}) {
  if (!audit) throw new Error('Missing audit input');
  assertNoStaleTarget(audit, 'audit');
  assertNoStaleTarget(definitions, 'definitions');

  const backlog = extractBacklog(audit);
  const definitionIdCounts = countDefinitionsById(definitions);
  const duplicateDefinitionIds = [...definitionIdCounts.entries()]
    .filter(([, count]) => count > 1)
    .map(([id]) => id)
    .sort();
  const duplicateIdSet = new Set(duplicateDefinitionIds);

  const implementedDefinitions = definitions.filter((definition) => (definition.status || 'implemented') === 'implemented');
  const matchesByDefinition = new Map(implementedDefinitions.map((definition) => [definition.id, []]));
  const coveredIndexes = new Set();
  const coveredGroupKeys = new Set();

  backlog.forEach((item) => {
    implementedDefinitions.forEach((definition) => {
      if (!matchCoverageDefinition(definition, item)) return;
      matchesByDefinition.get(definition.id)?.push(item);
      coveredIndexes.add(item.index);
      coveredGroupKeys.add(itemGroupKey(item));
    });
  });

  const remaining = backlog.filter((item) => !coveredIndexes.has(item.index));
  const remainingGroupKeys = new Set(remaining.map(itemGroupKey));
  const unmatchedDefinitions = implementedDefinitions
    .filter((definition) => !duplicateIdSet.has(definition.id))
    .filter((definition) => (matchesByDefinition.get(definition.id) || []).length === 0)
    .map((definition) => ({
      id: definition.id,
      route: definition.route,
      title: definition.title || '',
      reason: definition.reason || '',
      status: definition.status || 'implemented',
    }));

  const remainingRouteMap = new Map();
  for (const item of remaining) {
    const key = item.route || '(unknown route)';
    if (!remainingRouteMap.has(key)) {
      remainingRouteMap.set(key, { route: key, routeLabel: item.routeLabel || '', count: 0 });
    }
    const route = remainingRouteMap.get(key);
    route.count += 1;
    if (!route.routeLabel && item.routeLabel) route.routeLabel = item.routeLabel;
  }

  return {
    ok: duplicateDefinitionIds.length === 0 && unmatchedDefinitions.length === 0,
    source: {
      runId: audit.runId || audit.source?.runId || '',
      baseUrl: audit.baseUrl || audit.source?.baseUrl || '',
      checkedAt: audit.checkedAt || audit.source?.checkedAt || '',
    },
    generatedAt: new Date().toISOString(),
    totalBacklog: backlog.length,
    definitionCount: definitions.length,
    implementedDefinitionCount: implementedDefinitions.length,
    coveredItems: coveredIndexes.size,
    remainingItems: remaining.length,
    coveredGroups: coveredGroupKeys.size,
    remainingGroups: remainingGroupKeys.size,
    topRemainingRoutes: [...remainingRouteMap.values()].sort(compareCountThenName).slice(0, 10),
    duplicateDefinitionIds,
    unmatchedDefinitions,
    definitions: definitions.map((definition) => ({
      id: definition.id,
      title: definition.title || '',
      route: definition.route || '',
      status: definition.status || 'implemented',
      command: definition.command || '',
      matchedItems: matchesByDefinition.get(definition.id)?.length || 0,
    })),
  };
}

function formatMarkdown(report) {
  const lines = [
    '# SaaS Scenario Coverage Report',
    '',
    `- Run ID: ${report.source.runId || '(unknown)'}`,
    `- Base URL: ${report.source.baseUrl || '(unknown)'}`,
    `- Generated at: ${report.generatedAt}`,
    `- Definitions: ${report.definitionCount} (${report.implementedDefinitionCount} implemented)`,
    `- Covered backlog items: ${report.coveredItems}/${report.totalBacklog}`,
    `- Covered backlog groups: ${report.coveredGroups}`,
    `- Remaining backlog items: ${report.remainingItems}`,
    `- Remaining backlog groups: ${report.remainingGroups}`,
    '',
    '## Definitions',
    '',
    '| Status | ID | Route | Matched Items | Command |',
    '| --- | --- | --- | ---: | --- |',
    ...report.definitions.map((definition) => `| ${definition.status} | ${definition.id} | \`${definition.route}\` | ${definition.matchedItems} | \`${definition.command || '-'}\` |`),
    '',
    '## Top Remaining Routes',
    '',
  ];

  for (const route of report.topRemainingRoutes) {
    lines.push(`- ${route.route}${route.routeLabel ? ` (${route.routeLabel})` : ''}: ${route.count}`);
  }

  if (report.duplicateDefinitionIds.length) {
    lines.push('', '## Duplicate Definition IDs', '');
    for (const id of report.duplicateDefinitionIds) lines.push(`- ${id}`);
  }

  if (report.unmatchedDefinitions.length) {
    lines.push('', '## Unmatched Definitions', '');
    for (const definition of report.unmatchedDefinitions) {
      lines.push(`- ${definition.id} \`${definition.route}\`: ${definition.title || definition.reason || '-'}`);
    }
  }

  return `${lines.join('\n').trimEnd()}\n`;
}

function writeReports(report, { outputDir = resolveFromRoot(DEFAULT_OUTPUT_DIR), timestamp = portableTimestamp() } = {}) {
  const resolvedOutputDir = resolve(outputDir);
  mkdirSync(resolvedOutputDir, { recursive: true });
  const jsonPath = join(resolvedOutputDir, `scenario-coverage-${timestamp}.json`);
  const markdownPath = join(resolvedOutputDir, `scenario-coverage-${timestamp}.md`);
  writeFileSync(jsonPath, `${JSON.stringify({ ...report, outputs: { jsonPath, markdownPath } }, null, 2)}\n`, 'utf8');
  writeFileSync(markdownPath, formatMarkdown(report), 'utf8');
  return { jsonPath, markdownPath };
}

function loadAudit(inputPath) {
  const resolved = resolve(inputPath);
  if (!existsSync(resolved)) throw new Error(`Scenario coverage input not found: ${resolved}`);
  return JSON.parse(readFileSync(resolved, 'utf8'));
}

function parseArgs(args) {
  const parsed = {
    inputPath: findLatestFullChainAuditInput(),
    runCovered: false,
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
    } else if (arg === '--run-covered') {
      parsed.runCovered = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return parsed;
}

function runCoveredCommands(report) {
  const commands = [...new Set(report.definitions
    .filter((definition) => definition.status === 'implemented' && definition.matchedItems > 0 && definition.command)
    .map((definition) => definition.command))];
  for (const command of commands) {
    console.log(`RUN ${command}`);
    const result = spawnSync(command, {
      cwd: root,
      env: {
        ...process.env,
        COMPOSE_PROJECT_NAME: 'hengpintong-saas-preview',
        HRM_BASE_URL: process.env.HRM_BASE_URL || 'http://localhost:18280',
      },
      shell: true,
      stdio: 'inherit',
    });
    if (result.status !== 0) {
      throw new Error(`Covered scenario command failed: ${command}`);
    }
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('Usage: node scripts/verify-saas-scenario-coverage.mjs [--input <audit-json>] [--run-covered]');
    return 0;
  }

  const audit = loadAudit(args.inputPath);
  const report = evaluateScenarioCoverage({ audit });
  const outputs = writeReports(report);
  console.log('SaaS scenario coverage: OK');
  console.log(`Covered backlog items: ${report.coveredItems}/${report.totalBacklog}`);
  console.log(`Covered groups: ${report.coveredGroups}; remaining groups: ${report.remainingGroups}`);
  console.log('Top remaining routes:');
  for (const route of report.topRemainingRoutes.slice(0, 5)) {
    console.log(`- ${route.route}${route.routeLabel ? ` (${route.routeLabel})` : ''}: ${route.count}`);
  }
  console.log(`JSON: ${outputs.jsonPath}`);
  console.log(`Markdown: ${outputs.markdownPath}`);

  if (!report.ok) {
    if (report.duplicateDefinitionIds.length) console.error(`Duplicate definition IDs: ${report.duplicateDefinitionIds.join(', ')}`);
    if (report.unmatchedDefinitions.length) console.error(`Unmatched definitions: ${report.unmatchedDefinitions.map((item) => item.id).join(', ')}`);
    return 1;
  }

  if (args.runCovered) runCoveredCommands(report);
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
