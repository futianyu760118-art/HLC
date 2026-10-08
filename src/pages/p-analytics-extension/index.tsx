import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { AnalyticsFeatureKey, AnalyticsFeatureSummary, ApiError, extensionApi } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const analyticsFeatures: Array<{ key: AnalyticsFeatureKey; label: string; icon: string }> = [
  { key: 'basic_bi', label: '基础 BI', icon: 'fa-chart-pie' },
  { key: 'custom_reports', label: '自定义报表', icon: 'fa-table-list' },
  { key: 'realtime_dashboard', label: '实时仪表盘', icon: 'fa-gauge-high' },
  { key: 'benchmark', label: '对标分析', icon: 'fa-scale-balanced' },
  { key: 'visualization', label: '高级数据可视化', icon: 'fa-chart-area' },
];

const metricLabelMap: Record<string, string> = {
  employeeCount: '员工数',
  totalEmployees: '总员工',
  departmentCount: '部门数',
  kpiCount: '指标数',
  averagePerformanceScore: '绩效均分',
  reportCount: '报表数',
  exportReadyCount: '可导出',
  widgetCount: '组件数',
  refreshMode: '刷新模式',
  benchmarkCount: '对标项',
  source: '基线',
  chartCount: '图表数',
  visualLayer: '渲染层',
};

function rowsFor(payload: AnalyticsFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.kpis ||
    payload.reports ||
    payload.widgets ||
    payload.benchmarks ||
    payload.charts ||
    payload.departmentBreakdown ||
    payload.performanceDistribution ||
    payload.activityFeed ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.title ||
    row.name ||
    row.label ||
    row.departmentName ||
    row.message ||
    row.key ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const value = row.value ?? row.tenantValue ?? row.employeeCount ?? row.count;
  const unit = row.unit ? String(row.unit) : '';
  const pieces = [
    value !== undefined ? `${String(value)}${unit}` : null,
    row.status,
    row.type,
    row.dimension,
    row.metricCount !== undefined ? `${String(row.metricCount)} 项指标` : null,
    row.benchmarkValue !== undefined ? `基线 ${String(row.benchmarkValue)}${unit}` : null,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof analyticsFeatures)[number];
  payload?: AnalyticsFeatureSummary;
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
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
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
          {payload.note && <div className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">{payload.note}</div>}
        </div>
      )}
    </section>
  );
}

export default function AnalyticsExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<AnalyticsFeatureKey, AnalyticsFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<AnalyticsFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof analyticsFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<AnalyticsFeatureKey, AnalyticsFeatureSummary>> = {};
    const nextErrors: Partial<Record<AnalyticsFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'analytics', analyticsFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.analyticsFeatureSummary(feature.key);
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
    document.title = '分析与报表 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const basic = payloads.basic_bi?.summary || {};
    const reports = payloads.custom_reports?.summary || {};
    const dashboard = payloads.realtime_dashboard?.summary || {};
    const visual = payloads.visualization?.summary || {};
    return [
      { label: '员工数', value: basic.employeeCount || 0, icon: 'fa-users' },
      { label: '报表数', value: reports.reportCount || 0, icon: 'fa-table-list' },
      { label: '组件数', value: dashboard.widgetCount || 0, icon: 'fa-gauge-high' },
      { label: '图表数', value: visual.chartCount || 0, icon: 'fa-chart-area' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
                <AppIcon className="fas fa-chart-column text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">分析与报表</h1>
                <div className="mt-1 text-xs text-slate-500">基础 BI · 自定义报表 · 实时仪表盘 · 对标分析 · 高级数据可视化</div>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-cyan-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成分析快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通数据分析子功能</div>
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
