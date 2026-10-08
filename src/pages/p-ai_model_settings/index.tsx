import { useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { hrmApi, type AIUsageLedgerItem, type TenantAIEntitlement, type TenantAIUsagePayload } from '../../utils/api';

type Notice = {
  ok: boolean;
  text: string;
};

const formatDateTime = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const percentOf = (used?: number, quota?: number | null) => {
  if (!quota || quota <= 0) return 0;
  return Math.min(100, Math.round(((used || 0) / quota) * 100));
};

const tierLabel = (entitlement: TenantAIEntitlement, tier?: string | null) => (
  (tier && entitlement.tierLabels?.[tier]) || tier || '未选择'
);

const statusClass = (status?: string | null) => {
  if (status === 'success') return 'bg-emerald-50 text-emerald-700';
  if (status) return 'bg-rose-50 text-rose-700';
  return 'bg-slate-50 text-slate-500';
};

const usageStatusText = (row: AIUsageLedgerItem) => {
  if (row.status === 'success') return '成功';
  if (row.errorCode) return row.errorCode;
  return row.status || '-';
};

export default function AIModelSettingsPage() {
  const [entitlements, setEntitlements] = useState<TenantAIEntitlement[]>([]);
  const [usage, setUsage] = useState<TenantAIUsagePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingDomain, setSavingDomain] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);

  const enabledCount = useMemo(
    () => entitlements.filter(item => item.enabled).length,
    [entitlements],
  );
  const totalQuota = useMemo(
    () => entitlements.reduce((sum, item) => sum + (item.enabled ? Math.max(Number(item.monthlyQuota || 0), 0) : 0), 0),
    [entitlements],
  );
  const usedTotal = usage?.total || entitlements.reduce((sum, item) => sum + (item.usedThisMonth || 0), 0);
  const remainingTotal = entitlements.reduce((sum, item) => sum + (item.enabled ? Math.max(Number(item.remainingQuota ?? 0), 0) : 0), 0);

  const loadData = async () => {
    setLoading(true);
    setNotice(null);
    try {
      const [entitlementPayload, usagePayload] = await Promise.all([
        hrmApi.aiEntitlements(),
        hrmApi.aiUsage(),
      ]);
      setEntitlements(entitlementPayload.entitlements || []);
      setUsage(usagePayload || null);
    } catch (error) {
      setNotice({ ok: false, text: error instanceof Error ? error.message : '加载 AI 权益失败' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    document.title = 'AI 权益与用量 - 恒聘通';
    loadData();
  }, []);

  const selectTier = async (resourceDomain: string, tier: string) => {
    setSavingDomain(resourceDomain);
    setNotice(null);
    try {
      const result = await hrmApi.selectAiTier(resourceDomain, tier);
      setEntitlements(prev => prev.map(item => (
        item.resourceDomain === resourceDomain
          ? { ...item, ...result.entitlement, tierLabels: item.tierLabels }
          : item
      )));
      setNotice({ ok: true, text: 'AI 档位已更新，后续请求将按新档位计入权益。' });
    } catch (error) {
      setNotice({ ok: false, text: error instanceof Error ? error.message : '更新 AI 档位失败' });
    } finally {
      setSavingDomain('');
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex h-64 items-center justify-center text-blue-500">
          <AppIcon className="fas fa-spinner fa-spin text-xl" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
              <AppIcon className="fas fa-layer-group text-base" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900">AI 权益与用量</h1>
              <p className="mt-1 text-xs text-slate-500">查看已购 AI 能力、月度额度和可选档位。</p>
            </div>
          </div>
          <button
            type="button"
            onClick={loadData}
            className="h-9 rounded-md border border-slate-200 px-3 text-sm text-slate-600 hover:bg-slate-50"
          >
            <AppIcon className="fas fa-rotate-right mr-1" />刷新
          </button>
        </div>

        {notice && (
          <div className={`rounded-md border px-4 py-3 text-sm ${notice.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
            {notice.text}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Metric label="已开通资源" value={`${enabledCount}/${entitlements.length}`} icon="fa-toggle-on" />
          <Metric label="本月已用" value={String(usedTotal)} icon="fa-chart-line" />
          <Metric label="剩余额度" value={String(remainingTotal)} icon="fa-battery-three-quarters" />
          <Metric label="月度额度" value={String(totalQuota)} icon="fa-gauge-high" />
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {entitlements.map(item => {
            const used = item.usedThisMonth || usage?.byDomain?.[item.resourceDomain] || 0;
            const pct = percentOf(used, item.monthlyQuota);
            const disabled = !item.enabled;
            return (
              <section key={item.resourceDomain} className={`rounded-lg border bg-white p-4 ${disabled ? 'border-slate-200 opacity-75' : 'border-blue-100'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-bold text-slate-900">{item.resourceLabel || item.resourceDomain}</h2>
                      <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${item.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                        {item.enabled ? '已开通' : '未开通'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{item.packageName || item.packageCode || '未绑定加购包'}</p>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-slate-900">{used}/{item.monthlyQuota || 0}</div>
                    <div className="text-[11px] text-slate-400">本月用量</div>
                  </div>
                </div>

                <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${pct >= 90 ? 'bg-rose-500' : pct >= 70 ? 'bg-amber-500' : 'bg-blue-600'}`} style={{ width: `${pct}%` }} />
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                  <span>剩余 {item.remainingQuota ?? 0}</span>
                  <span>{pct}%</span>
                </div>

                <div className="mt-4">
                  <div className="mb-2 text-xs font-semibold text-slate-500">当前档位</div>
                  {item.allowedTiers.length ? (
                    <div className="flex flex-wrap gap-2">
                      {item.allowedTiers.map(tier => (
                        <button
                          key={tier}
                          type="button"
                          disabled={disabled || savingDomain === item.resourceDomain}
                          onClick={() => selectTier(item.resourceDomain, tier)}
                          className={`h-8 rounded-md border px-3 text-xs font-medium ${
                            item.selectedTier === tier
                              ? 'border-blue-600 bg-blue-50 text-blue-700'
                              : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                          } disabled:cursor-not-allowed disabled:opacity-50`}
                        >
                          {tierLabel(item, tier)}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-md border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-500">
                      该能力尚未购买，请联系平台管理员开通对应 AI 加购包。
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>

        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">近期 AI 用量</h2>
              <p className="mt-1 text-xs text-slate-500">仅展示业务域、档位、状态和计量信息。</p>
            </div>
            <span className="text-xs text-slate-400">{usage?.periodKey || '-'}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  {['时间', '资源', '场景', '档位', '状态', '单位', '请求'].map(label => (
                    <th key={label} className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(usage?.items || []).length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-sm text-slate-400">暂无 AI 用量记录</td>
                  </tr>
                ) : (
                  (usage?.items || []).slice(0, 80).map(row => {
                    const entitlement = entitlements.find(item => item.resourceDomain === row.resourceDomain);
                    return (
                      <tr key={row.id} className="border-b border-slate-50 hover:bg-blue-50/30">
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-600">{formatDateTime(row.createdAt)}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs font-medium text-slate-800">{entitlement?.resourceLabel || row.resourceDomain}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-600">{row.useCase || '-'}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-600">{tierLabel(entitlement || ({ tierLabels: {} } as TenantAIEntitlement), row.tier)}</td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs">
                          <span className={`rounded-md px-2 py-1 text-[11px] ${statusClass(row.status)}`}>{usageStatusText(row)}</span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-600">{row.units || 1}</td>
                        <td className="max-w-[180px] truncate px-4 py-2.5 text-xs text-slate-400">{row.requestId || '-'}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </Layout>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-slate-500">{label}</span>
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
          <AppIcon className={`fas ${icon} text-xs`} />
        </span>
      </div>
      <div className="mt-2 text-xl font-bold text-slate-900">{value}</div>
    </div>
  );
}
