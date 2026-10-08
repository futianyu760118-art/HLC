import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, PeopleAnalyticsExtensionSummary, PeopleAnalyticsRisk } from '../../utils/api';

const emptySummary: PeopleAnalyticsExtensionSummary['summary'] = {
  employeeCount: 0,
  totalEmployees: 0,
  departmentCount: 0,
  highPerformerCount: 0,
  highPerformerRate: 0,
  turnoverRate: 0,
  averageSpanOfControl: 0,
  dataScope: 'currentTenant',
};

const riskTone: Record<string, string> = {
  high: 'bg-rose-50 text-rose-700 border-rose-100',
  medium: 'bg-amber-50 text-amber-700 border-amber-100',
  low: 'bg-emerald-50 text-emerald-700 border-emerald-100',
};

function MetricCard({ label, value, icon, tone }: { label: string; value: string | number; icon: string; tone: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">{label}</div>
          <div className="mt-2 text-2xl font-bold text-slate-900">{value}</div>
        </div>
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${tone}`}>
          <AppIcon className={`fas ${icon} text-sm`} />
        </div>
      </div>
    </div>
  );
}

function RiskItem({ risk }: { risk: PeopleAnalyticsRisk }) {
  const className = riskTone[risk.level] || 'bg-slate-50 text-slate-700 border-slate-100';
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${className}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold">{risk.type}</span>
        <span className="text-xs uppercase">{risk.level}</span>
      </div>
      <p className="mt-1 leading-6">{risk.message}</p>
    </div>
  );
}

export default function PeopleAnalyticsExtensionPage() {
  const [data, setData] = useState<PeopleAnalyticsExtensionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await extensionApi.peopleAnalyticsSummary());
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('当前企业未开通人力分析，请联系平台管理员。');
      } else {
        setError(err instanceof Error ? err.message : '人力分析数据加载失败');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = '人力分析 - 恒聘通';
    loadData();
  }, [loadData]);

  const summary = data?.summary || emptySummary;
  const departmentRows = useMemo(
    () => data?.distributions.byDepartment.slice(0, 8) || [],
    [data],
  );
  const performanceRows = useMemo(
    () => data?.distributions.performance.slice(0, 6) || [],
    [data],
  );

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <AppIcon className="fas fa-chart-simple text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">人力分析</h1>
                <p className="mt-1 text-xs text-slate-500">基于当前租户员工、绩效和离职数据生成人才洞察快照</p>
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

        {loading ? (
          <div className="rounded-lg border border-slate-200 bg-white py-24 text-center text-blue-500">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成人才分析快照...</div>
          </div>
        ) : error ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800">
            <AppIcon className="fas fa-triangle-exclamation mr-2" />
            {error}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="在职员工" value={summary.employeeCount} icon="fa-id-card" tone="bg-blue-50 text-blue-600" />
              <MetricCard label="部门覆盖" value={summary.departmentCount} icon="fa-sitemap" tone="bg-cyan-50 text-cyan-700" />
              <MetricCard label="高绩效占比" value={`${summary.highPerformerRate}%`} icon="fa-star" tone="bg-emerald-50 text-emerald-700" />
              <MetricCard label="近 12 月离职率" value={`${summary.turnoverRate}%`} icon="fa-arrow-trend-down" tone="bg-rose-50 text-rose-600" />
            </div>

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
              <section className="rounded-lg border border-slate-200 bg-white xl:col-span-2">
                <div className="border-b border-slate-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-slate-900">部门人数分布</h2>
                </div>
                <div className="space-y-4 p-5">
                  {departmentRows.length === 0 ? (
                    <div className="py-12 text-center text-sm text-slate-400">暂无部门员工数据</div>
                  ) : departmentRows.map((row) => {
                    const percent = Math.round((row.ratio || 0) * 100);
                    return (
                      <div key={row.departmentId || row.departmentName}>
                        <div className="mb-1.5 flex items-center justify-between text-sm">
                          <span className="font-medium text-slate-700">{row.departmentName || '未分配部门'}</span>
                          <span className="text-xs text-slate-500">{row.employeeCount || 0} 人 · {percent}%</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.max(5, percent)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 bg-white">
                <div className="border-b border-slate-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-slate-900">风险信号</h2>
                </div>
                <div className="space-y-3 p-4">
                  {(data?.risks || []).length === 0 ? (
                    <div className="py-12 text-center text-sm text-slate-400">暂无风险信号</div>
                  ) : data?.risks.map((risk, index) => (
                    <RiskItem key={`${risk.type}-${index}`} risk={risk} />
                  ))}
                </div>
              </section>
            </div>

            <section className="rounded-lg border border-slate-200 bg-white">
              <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold text-slate-900">绩效分布</h2>
                <span className="text-xs text-slate-400">快照 {data?.snapshot?.createdAt || '刚刚生成'}</span>
              </div>
              <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2 xl:grid-cols-3">
                {performanceRows.length === 0 ? (
                  <div className="py-10 text-sm text-slate-400">暂无绩效评分数据</div>
                ) : performanceRows.map((row) => (
                  <div key={row.label} className="rounded-lg border border-slate-100 px-4 py-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-slate-800">{row.label}</span>
                      <span className="text-lg font-bold text-slate-900">{row.count || 0}</span>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">{Math.round((row.ratio || 0) * 100)}% 员工</div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </Layout>
  );
}
