import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(scriptPath), '..');
const DEFAULT_REQUIREMENTS_PATH = 'backend-python/requirements.txt';
const DEFAULT_EVIDENCE_PATH = 'docs/backend-dependency-audit-evidence.md';

function commandOutput(result) {
  return [result?.stdout, result?.stderr, result?.error?.message]
    .filter(Boolean)
    .join('\n');
}

function isToolUnavailable(result) {
  if (result?.error?.code === 'ENOENT') return true;
  const output = commandOutput(result);
  return /not recognized|not found|No module named pip_audit|ERR_MODULE_NOT_FOUND/i.test(output);
}

function auditCommandOptions() {
  return {
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONDONTWRITEBYTECODE: '1',
      HTTP_PROXY: '',
      HTTPS_PROXY: '',
      ALL_PROXY: '',
      http_proxy: '',
      https_proxy: '',
      all_proxy: '',
    },
  };
}

function defaultRunCommand(command, args, options = auditCommandOptions()) {
  return spawnSync(command, args, {
    encoding: 'utf8',
    ...options,
  });
}

const auditArgs = (requirementsPath) => [
  '-r',
  requirementsPath,
  '--progress-spinner',
  'off',
];

function normalizeResult(result) {
  return {
    status: result?.status ?? (result?.error ? 1 : 0),
    stdout: result?.stdout || '',
    stderr: result?.stderr || '',
    error: result?.error || null,
  };
}

function parseEvidenceRows(markdown) {
  const lines = markdown.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => {
    const normalized = line.replace(/\s+/g, ' ').trim();
    return normalized === '| Date | Owner | Evidence | Decision |';
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
      date: cells[0],
      owner: cells[1],
      evidence: cells[2],
      decision: cells[3],
    });
  }
  return rows;
}

function isConcreteOwnerEvidence(row) {
  if (!row || row.decision !== 'Accepted') return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date)) return false;

  const text = [row.owner, row.evidence].join(' ').trim();
  if (!text) return false;
  if (/<[^>]+>/.test(text)) return false;
  if (!/backend-python\/requirements\.txt/i.test(row.evidence)) return false;
  if (!/\b(audit|scanner|scan|exception|pip-audit)\b/i.test(row.evidence)) return false;

  return !/\b(TBD|TODO|pending|not attached|owner role|owner name|artifact name|ticket link)\b/i.test(text);
}

function acceptedOwnerEvidence({ evidenceText, evidencePath }) {
  const text = evidenceText ?? (
    evidencePath && existsSync(evidencePath)
      ? readFileSync(evidencePath, 'utf8')
      : ''
  );
  const rows = parseEvidenceRows(text);
  return rows.find(isConcreteOwnerEvidence) || null;
}

function auditFailure(tool, result, requirementsPath) {
  return {
    ok: false,
    reason: 'audit-failed',
    tool,
    requirementsPath,
    status: result.status,
    output: commandOutput(result),
  };
}

function parsePinnedRequirements(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+#.*$/, '').trim())
    .filter((line) => line && !line.startsWith('#') && !line.startsWith('-'))
    .map((line) => {
      const match = line.match(/^([A-Za-z0-9_.-]+)==([^;\s]+)(?:\s*;.*)?$/);
      if (!match) return null;
      return {
        name: match[1],
        version: match[2],
      };
    })
    .filter(Boolean);
}

async function defaultFetchPackageInfo(name, version) {
  const url = `https://pypi.org/pypi/${encodeURIComponent(name)}/${encodeURIComponent(version)}/json`;
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: {
          'User-Agent': 'HRM-saas-backend-dependency-audit/1.0',
        },
      });
      if (!response.ok) {
        throw new Error(`PyPI returned HTTP ${response.status} for ${name}==${version}`);
      }
      return await response.json();
    } catch (error) {
      lastError = error;
      if (attempt === 3) break;
    } finally {
      clearTimeout(timeout);
    }
  }
  throw lastError;
}

async function evaluatePypiJsonAudit({
  requirementsPath,
  requirementsText,
  fetchPackageInfo = defaultFetchPackageInfo,
}) {
  const text = requirementsText ?? readFileSync(requirementsPath, 'utf8');
  const requirements = parsePinnedRequirements(text);
  const findings = [];
  const errors = [];

  for (const requirement of requirements) {
    try {
      let info = null;
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          info = await fetchPackageInfo(requirement.name, requirement.version);
          break;
        } catch (error) {
          if (attempt === 3) throw error;
        }
      }
      const vulnerabilities = Array.isArray(info?.vulnerabilities) ? info.vulnerabilities : [];
      for (const vuln of vulnerabilities) {
        findings.push({
          packageName: requirement.name,
          version: requirement.version,
          id: vuln.id || 'UNKNOWN',
          fixVersions: Array.isArray(vuln.fix_versions) ? vuln.fix_versions : [],
        });
      }
    } catch (error) {
      errors.push(`${requirement.name}==${requirement.version}: ${error.message}`);
    }
  }

  if (errors.length) {
    return {
      ok: false,
      reason: 'tool-unavailable',
      tool: 'PyPI JSON API',
      requirementsPath,
      output: errors.join('\n'),
    };
  }

  if (findings.length) {
    return {
      ok: false,
      reason: 'audit-failed',
      tool: 'PyPI JSON API',
      requirementsPath,
      status: 1,
      output: [
        `Found ${findings.length} known vulnerabilities via PyPI JSON API`,
        ...findings.map((finding) => `${finding.packageName} ${finding.version} ${finding.id}${finding.fixVersions.length ? ` fix: ${finding.fixVersions.join(', ')}` : ''}`),
      ].join('\n'),
    };
  }

  return {
    ok: true,
    reason: 'passed',
    tool: 'PyPI JSON API',
    requirementsPath,
    output: `No known vulnerabilities found via PyPI JSON API for ${requirements.length} pinned packages`,
  };
}

export function evaluateBackendDependencyAudit({
  runCommand = defaultRunCommand,
  requirementsPath = resolve(root, DEFAULT_REQUIREMENTS_PATH),
  evidencePath = resolve(root, DEFAULT_EVIDENCE_PATH),
  evidenceText = null,
  requirementsText = null,
  fetchPackageInfo = defaultFetchPackageInfo,
} = {}) {
  const args = auditArgs(requirementsPath);
  const commandOptions = auditCommandOptions();
  const primary = normalizeResult(runCommand('pip-audit', args, commandOptions));
  if (primary.status === 0) {
    return {
      ok: true,
      reason: 'passed',
      tool: 'pip-audit',
      requirementsPath,
      output: commandOutput(primary),
    };
  }

  if (!isToolUnavailable(primary)) {
    return auditFailure('pip-audit', primary, requirementsPath);
  }

  const fallback = normalizeResult(runCommand('python', ['-m', 'pip_audit', ...args], commandOptions));
  if (fallback.status === 0) {
    return {
      ok: true,
      reason: 'passed',
      tool: 'python -m pip_audit',
      requirementsPath,
      output: commandOutput(fallback),
    };
  }

  if (!isToolUnavailable(fallback)) {
    return auditFailure('python -m pip_audit', fallback, requirementsPath);
  }

  return evaluatePypiJsonAudit({
    requirementsPath,
    requirementsText,
    fetchPackageInfo,
  }).then((pypiResult) => {
    if (pypiResult.ok || pypiResult.reason === 'audit-failed') {
      return pypiResult;
    }

    const ownerEvidence = acceptedOwnerEvidence({ evidenceText, evidencePath });
    if (ownerEvidence) {
      return {
        ok: true,
        reason: 'owner-evidence',
        tool: 'security owner evidence',
        requirementsPath,
        evidencePath,
        evidence: ownerEvidence,
        output: pypiResult.output || commandOutput(fallback) || commandOutput(primary),
      };
    }

    return {
      ok: false,
      reason: 'tool-unavailable',
      tool: null,
      requirementsPath,
      evidencePath,
      output: pypiResult.output || commandOutput(fallback) || commandOutput(primary),
    };
  });
}

export function formatBackendDependencyAuditReport(result) {
  if (result.ok) {
    if (result.reason === 'owner-evidence') {
      return [
        'Backend dependency audit: OWNER_EVIDENCE',
        `Requirements: ${result.requirementsPath}`,
        `Evidence: ${result.evidencePath}`,
        `Owner: ${result.evidence.owner}`,
        `Date: ${result.evidence.date}`,
        result.evidence.evidence,
      ].filter(Boolean).join('\n');
    }

    return [
      'Backend dependency audit: OK',
      `Tool: ${result.tool}`,
      `Requirements: ${result.requirementsPath}`,
      result.output.trim(),
    ].filter(Boolean).join('\n');
  }

  if (result.reason === 'tool-unavailable') {
    return [
      'Backend dependency audit: TOOL_UNAVAILABLE',
      `Requirements: ${result.requirementsPath}`,
      `Evidence: ${result.evidencePath}`,
      'No accepted owner evidence found.',
      'Install pip-audit, run an approved equivalent scanner, or attach a security owner approved exception before final release.',
      result.output.trim(),
    ].filter(Boolean).join('\n');
  }

  return [
    'Backend dependency audit: FAILED',
    `Tool: ${result.tool}`,
    `Requirements: ${result.requirementsPath}`,
    result.output.trim(),
  ].filter(Boolean).join('\n');
}

function readArgValue(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return null;
  return args[index + 1] || null;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('Usage: node scripts/check-backend-dependency-audit.mjs [--requirements backend-python/requirements.txt] [--evidence docs/backend-dependency-audit-evidence.md]');
    return 0;
  }

  const requirementsArg = readArgValue(args, '--requirements');
  const evidenceArg = readArgValue(args, '--evidence');
  const result = await evaluateBackendDependencyAudit({
    requirementsPath: resolve(root, requirementsArg || DEFAULT_REQUIREMENTS_PATH),
    evidencePath: resolve(root, evidenceArg || DEFAULT_EVIDENCE_PATH),
  });
  console.log(formatBackendDependencyAuditReport(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  process.exitCode = await main();
}
