import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const BASE_URL = (process.env.HRM_BASE_URL || 'http://localhost:18280').replace(/\/+$/, '');
const FORBIDDEN_LOCAL_BASE = ['localhost:', '18080'].join('');
if (BASE_URL.includes(FORBIDDEN_LOCAL_BASE)) {
  throw new Error('Refusing to verify against 18080 from HRM-saas');
}
const EMAIL = process.env.HRM_TEST_EMAIL || 'admin@hengpintong.demo';
const PASSWORD = process.env.HRM_TEST_PASSWORD || 'Demo@123456';
const ARTIFACT_DIR = process.env.HRM_BROWSER_ARTIFACT_DIR || path.resolve('artifacts', 'browser-verification');
const REQUEST_TIMEOUT_MS = Number(process.env.HRM_ASSISTANT_OPERATIONAL_ROUTING_TIMEOUT_MS || 60000);

const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
const runId = process.env.HRM_ASSISTANT_OPERATIONAL_ROUTING_RUN_ID
  || `assistant-operational-routing-${stamp}`;
const sessionId = `${runId}-session`;

const CASES = [
  {
    id: 'candidate_focus_setup',
    question: '分析一下候选人吴明华怎么样，并说明依据',
    expectedIntent: 'recruitment.person.assess',
    expectedSkills: ['candidate_evidence_bundle'],
    forbiddenSkills: ['performance_analysis', 'training_analysis', 'payroll_analysis'],
    expectedModules: ['candidates', 'resumes', 'jobs'],
    minFieldEvidenceCount: 8,
  },
  {
    id: 'performance_after_candidate_focus',
    question: '绩效评估分布怎么样',
    expectedIntent: 'performance.distribution',
    expectedSkills: ['performance_analysis'],
    forbiddenSkills: ['candidate_evidence_bundle'],
    expectedModules: ['performance_reviews', 'employees'],
    minFieldEvidenceCount: 6,
    expectedRiskLevel: 'low',
  },
  {
    id: 'training_after_candidate_focus',
    question: '培训完成率是多少',
    expectedIntent: 'training.completion',
    expectedSkills: ['training_analysis'],
    forbiddenSkills: ['candidate_evidence_bundle'],
    expectedModules: ['training_courses', 'training_plans', 'training_records', 'employees'],
    minFieldEvidenceCount: 8,
    expectedRiskLevel: 'low',
  },
  {
    id: 'payroll_after_candidate_focus',
    question: '2026-05 工资条汇总',
    expectedIntent: 'payroll.summary',
    expectedSkills: ['payroll_analysis'],
    forbiddenSkills: ['candidate_evidence_bundle', 'payroll_performance_link'],
    expectedModules: ['payroll_records', 'employees'],
    minFieldEvidenceCount: 6,
    expectedRiskLevel: 'high',
    expectedToolCachePolicy: 'none',
  },
  {
    id: 'candidate_assessment_still_available',
    question: '分析一下候选人吴明华怎么样，并说明依据',
    expectedIntent: 'recruitment.person.assess',
    expectedSkills: ['candidate_evidence_bundle'],
    forbiddenSkills: ['performance_analysis', 'training_analysis', 'payroll_analysis'],
    expectedModules: ['candidates', 'resumes', 'jobs'],
    minFieldEvidenceCount: 8,
  },
];

const fail = (message, details) => {
  if (details) console.error(JSON.stringify(details, null, 2));
  throw new Error(message);
};

const assertIsolatedBaseUrl = () => {
  const url = new URL(BASE_URL);
  if (url.port === '8080' || url.port === '8443') {
    fail('Refusing to run assistant operational routing smoke against old production ports', {
      baseUrl: BASE_URL,
    });
  }
};

const asJson = async (response, label = response.url) => {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    fail(`${label} did not return JSON`, text.slice(0, 1000));
  }
};

const requestJson = async (method, pathName, payload, token, requestId) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${BASE_URL}${pathName}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(requestId ? { 'X-Request-ID': requestId } : {}),
      },
      body: method === 'GET' ? undefined : JSON.stringify(payload || {}),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') {
      fail(`${method} ${pathName} exceeded ${REQUEST_TIMEOUT_MS}ms`, { requestId });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const text = await response.text();
    fail(`${method} ${pathName} failed with HTTP ${response.status}`, text.slice(0, 1200));
  }
  return asJson(response, pathName);
};

const login = async () => {
  const payload = await requestJson(
    'POST',
    '/api/auth/login',
    { email: EMAIL, password: PASSWORD },
    null,
    `${runId}-login`,
  );
  if (!payload.token || !payload.user) fail('Login succeeded but token/user is missing', payload);
  return payload;
};

const collectSourceWidgets = (payload) => {
  const widgets = Array.isArray(payload?.widgets) ? payload.widgets : [];
  const blocks = Array.isArray(payload?.renderBlocks) ? payload.renderBlocks : [];
  return [
    ...widgets.filter((widget) => widget?.type === 'source_citations'),
    ...blocks
      .map((block) => block?.payload || block?.data)
      .filter((widget) => widget?.type === 'source_citations' || Array.isArray(widget?.sources)),
  ];
};

const collectSources = (payload) => {
  const sourceWidgets = collectSourceWidgets(payload);
  const widgetSources = sourceWidgets.flatMap((widget) => widget?.sources || widget?.data || []);
  const evidenceSources = Array.isArray(payload?.copilot?.evidence) ? payload.copilot.evidence : [];
  return [...widgetSources, ...evidenceSources].filter(Boolean);
};

const summarizeResponse = (payload) => {
  const routeDecision = payload?.meta?.routeDecision || payload?.routeDecision || {};
  const usedSkills = Array.isArray(payload?.meta?.usedSkills)
    ? payload.meta.usedSkills
    : Array.isArray(payload?.copilot?.plan)
      ? payload.copilot.plan.map((step) => step?.id || step?.label).filter(Boolean)
      : [];
  const sources = collectSources(payload);
  const sourceModules = Array.from(new Set(sources.map((source) => source?.module).filter(Boolean)));
  const fieldEvidenceCount = sources.reduce(
    (sum, source) => sum + (Array.isArray(source?.fields) ? source.fields.length : 0),
    0,
  );
  return {
    summary: payload?.summary || payload?.answer?.content || '',
    intent: routeDecision.intent || payload?.copilot?.intent || '',
    reason: routeDecision.reason || '',
    riskLevel: routeDecision.riskLevel || payload?.meta?.riskLevel || payload?.copilot?.riskLevel || '',
    usedSkills,
    toolPlan: Array.isArray(routeDecision.toolPlan) ? routeDecision.toolPlan : [],
    sourceModules,
    fieldEvidenceCount,
    widgetTypes: Array.from(new Set((payload?.widgets || []).map((widget) => widget?.type).filter(Boolean))),
  };
};

const assertIncludesAll = (actual, expected, label, details) => {
  const missing = expected.filter((item) => !actual.includes(item));
  if (missing.length) fail(`${label} missing expected values`, { missing, actual, ...details });
};

const verifyCase = (caseSpec, actual) => {
  if (actual.intent !== caseSpec.expectedIntent) {
    fail('Assistant routing intent mismatch', {
      caseId: caseSpec.id,
      expectedIntent: caseSpec.expectedIntent,
      actualIntent: actual.intent,
      summary: actual.summary,
    });
  }
  assertIncludesAll(actual.usedSkills, caseSpec.expectedSkills, 'usedSkills', {
    caseId: caseSpec.id,
    expectedSkills: caseSpec.expectedSkills,
  });
  const forbidden = (caseSpec.forbiddenSkills || []).filter((skill) => actual.usedSkills.includes(skill));
  if (forbidden.length) {
    fail('Assistant routing used a forbidden skill', {
      caseId: caseSpec.id,
      forbidden,
      usedSkills: actual.usedSkills,
    });
  }
  assertIncludesAll(actual.sourceModules, caseSpec.expectedModules, 'sourceModules', {
    caseId: caseSpec.id,
    expectedModules: caseSpec.expectedModules,
  });
  if (actual.fieldEvidenceCount < caseSpec.minFieldEvidenceCount) {
    fail('Assistant response has too little field-level evidence', {
      caseId: caseSpec.id,
      minFieldEvidenceCount: caseSpec.minFieldEvidenceCount,
      fieldEvidenceCount: actual.fieldEvidenceCount,
      sourceModules: actual.sourceModules,
    });
  }
  if (caseSpec.expectedRiskLevel && actual.riskLevel !== caseSpec.expectedRiskLevel) {
    fail('Assistant routing risk level mismatch', {
      caseId: caseSpec.id,
      expectedRiskLevel: caseSpec.expectedRiskLevel,
      actualRiskLevel: actual.riskLevel,
    });
  }
  if (caseSpec.expectedToolCachePolicy) {
    const tool = actual.toolPlan.find((plan) => caseSpec.expectedSkills.includes(plan?.tool));
    if (!tool || tool.cachePolicy !== caseSpec.expectedToolCachePolicy) {
      fail('Assistant tool cache policy mismatch', {
        caseId: caseSpec.id,
        expectedToolCachePolicy: caseSpec.expectedToolCachePolicy,
        toolPlan: actual.toolPlan,
      });
    }
  }
};

const main = async () => {
  assertIsolatedBaseUrl();
  await mkdir(ARTIFACT_DIR, { recursive: true });

  const health = await requestJson('GET', '/api/health', null, null, `${runId}-health`);
  const ready = await requestJson('GET', '/api/ready', null, null, `${runId}-ready`);
  if (health.ok !== true) fail('/api/health did not return ok=true', health);
  if (ready.ok !== true || ready.db !== 'up') fail('/api/ready did not return ok=true, db=up', ready);

  const { token } = await login();
  const results = [];
  for (const caseSpec of CASES) {
    const requestId = `${runId}-${caseSpec.id}`;
    const payload = await requestJson(
      'POST',
      '/api/hrm/assistant/query',
      {
        question: caseSpec.question,
        sessionId,
        clientContext: {
          smokeTest: 'assistant_operational_routing',
          runId,
          caseId: caseSpec.id,
        },
      },
      token,
      requestId,
    );
    const actual = summarizeResponse(payload);
    verifyCase(caseSpec, actual);
    results.push({
      caseId: caseSpec.id,
      requestId,
      question: caseSpec.question,
      ...actual,
    });
  }

  const reportPath = path.join(ARTIFACT_DIR, `${runId}.json`);
  const report = {
    ok: true,
    runId,
    baseUrl: BASE_URL,
    sessionId,
    health,
    ready,
    caseCount: results.length,
    results,
    reportPath,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf-8');
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
