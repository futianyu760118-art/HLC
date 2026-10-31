import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, IntelligenceFeatureKey, IntelligenceFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const intelligenceFeatures: Array<{ key: IntelligenceFeatureKey; label: string; icon: string }> = [
  { key: 'predictive', label: '预测性分析', icon: 'fa-chart-line' },
  { key: 'turnover_risk', label: '离职风险', icon: 'fa-user-shield' },
  { key: 'ai_recruiting_assistant', label: 'AI 招聘助手', icon: 'fa-user-tie' },
  { key: 'smart_compensation', label: '智能薪酬', icon: 'fa-sack-dollar' },
  { key: 'hr_bot', label: 'HR Bot', icon: 'fa-robot' },
  { key: 'smart_performance', label: '智能绩效', icon: 'fa-star-half-stroke' },
  { key: 'advanced_ai_analytics', label: '高级 AI 分析', icon: 'fa-brain' },
];

const metricLabelMap: Record<string, string> = {
  employeeCount: '员工数',
  signalCount: '信号数',
  riskEmployeeCount: '风险员工',
  highRiskCount: '高风险',
  candidateCount: '候选人',
  openJobCount: '开放岗位',
  recommendedCount: '推荐数',
  profileCount: '薪酬档案',
  averageTotalSalary: '平均薪酬',
  belowBandCount: '低于区间',
  intentCount: '意图数',
  knowledgeSourceCount: '知识源',
  assistantMode: '模式',
  reviewCount: '绩效记录',
  highPerformerCount: '高绩效',
  coachingCount: '待辅导',
  insightCount: '洞察数',
};

function rowsFor(payload: IntelligenceFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.signals ||
    payload.predictions ||
    payload.riskEmployees ||
    payload.candidates ||
    payload.profiles ||
    payload.intents ||
    payload.reviews ||
    payload.insights ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.employeeName ||
    row.candidateName ||
    row.title ||
    row.label ||
    row.intent ||
    row.key ||
    row.resumeId ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.departmentName,
    row.riskLevel,
    row.recommendation,
    row.recommendedAction,
    row.matchScore !== undefined ? `匹配 ${String(row.matchScore)}` : null,
    row.totalSalary !== undefined ? `薪酬 ${String(row.totalSalary)}` : null,
    row.score !== undefined ? `得分 ${String(row.score)}` : null,
    row.message,
    Array.isArray(row.reasons) ? row.reasons.join('；') : null,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof intelligenceFeatures)[number];
  payload?: IntelligenceFeatureSummary;
  error?: string;
}) {
  const metrics = Object.entries(payload?.summary || {})
    .filter(([key, value]) => key !== 'dataScope' && value !== undefined && value !== null && typeof value !== 'boolean')
    .slice(0, 3);
  const rows = payload ? rowsFor(payload).slice(0, 4) : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
            <AppIcon className={`fas ${feature.icon} text-sm`} />
          </div>
          <h2 className="text-sm font-bold text-slate-900">{feature.label}</h2>
        </div>
        {payload && <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">{extensionMaturityLabel(payload.status)}</span>}
      </div>

      {error ? (
        <div className="px-5 py-5 text-sm text-amber-700">
          <AppIcon className="fas fa-triangle-exclamation mr-2" />
          {error}
        </div>
      ) : !payload ? (
        <div className="px-5 py-10 text-center text-sm text-slate-400">
          <AppIcon className="fas fa-spinner fa-spin mr-2" />
          正在生成快照
        </div>
      ) : (
        <div className="p-5">
          <div className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {payload.provider?.message || '未配置真实供应商'}
          </div>
          <div className="grid grid-cols-3 gap-3">
            {metrics.map(([key, value]) => (
              <div key={key} className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="text-[11px] text-slate-500">{metricLabelMap[key] || key}</div>
                <div className="mt-1 truncate text-lg font-bold text-slate-900">{String(value)}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-2">
            {rows.length === 0 ? (
              <div className="py-6 text-center text-xs text-slate-400">暂无可展示明细</div>
            ) : rows.map((row, index) => (
              <div key={`${feature.key}-${index}`} className="rounded-lg border border-slate-100 px-3 py-2">
                <div className="truncate text-sm font-semibold text-slate-800">{rowTitle(row)}</div>
                <div className="mt-1 truncate text-xs text-slate-500">{rowDetail(row) || feature.label}</div>
              </div>
            ))}
          </div>
          {payload.note && <div className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{payload.note}</div>}
        </div>
      )}
    </section>
  );
}

export default function IntelligenceExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<IntelligenceFeatureKey, IntelligenceFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<IntelligenceFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof intelligenceFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<IntelligenceFeatureKey, IntelligenceFeatureSummary>> = {};
    const nextErrors: Partial<Record<IntelligenceFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'intelligence', intelligenceFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.intelligenceFeatureSummary(feature.key);
        } catch (err) {
          if (err instanceof ApiError && err.status === 403) {
            nextErrors[feature.key] = `${feature.label} 未开通`;
          } else {
            nextErrors[feature.key] = err instanceof Error ? err.message : `${feature.label} 加载失败`;
          }
        }
      }));
    } catch (err) {
      setEnabledFeatures([]);
      setCatalogError(err instanceof Error ? err.message : '功能授权加载失败');
    }
    setPayloads(nextPayloads);
    setErrors(nextErrors);
    setLoading(false);
  }, []);

  useEffect(() => {
    document.title = '智能助手与预测 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const predictive = payloads.predictive?.summary || {};
    const turnover = payloads.turnover_risk?.summary || {};
    const recruiting = payloads.ai_recruiting_assistant?.summary || {};
    const ai = payloads.advanced_ai_analytics?.summary || {};
    return [
      { label: '预测信号', value: predictive.signalCount || 0, icon: 'fa-chart-line' },
      { label: '风险员工', value: turnover.riskEmployeeCount || 0, icon: 'fa-user-shield' },
      { label: '候选人', value: recruiting.candidateCount || 0, icon: 'fa-user-tie' },
      { label: '综合洞察', value: ai.insightCount || 0, icon: 'fa-brain' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
                <AppIcon className="fas fa-brain text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">智能助手与预测</h1>
                <div className="mt-1 text-xs text-slate-500">预测性分析 · 离职风险 · AI 招聘助手 · 智能薪酬 · HR Bot · 智能绩效 · 高级 AI 分析</div>
              </div>
            </div>
            <button
              type="button"
              onClick={loadData}
              className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <AppIcon className="fas fa-refresh mr-2 text-xs" />
              刷新快照
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          {overview.map((item) => (
            <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs text-slate-500">{item.label}</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">{String(item.value)}</div>
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-violet-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成智能化快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通智能化子功能</div>
        ) : (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            {enabledFeatures.map((feature) => (
              <FeaturePanel
                key={feature.key}
                feature={feature}
                payload={payloads[feature.key]}
                error={errors[feature.key]}
              />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
