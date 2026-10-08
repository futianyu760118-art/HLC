import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, WorkforceFeatureKey, WorkforceFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const workforceFeatures: Array<{ key: WorkforceFeatureKey; label: string; icon: string }> = [
  { key: 'smart_scheduling', label: '智能排班', icon: 'fa-calendar-days' },
  { key: 'ai_scheduling', label: 'AI 排班增强', icon: 'fa-wand-magic-sparkles' },
  { key: 'planning', label: '劳动力规划', icon: 'fa-people-line' },
  { key: 'leave_bank', label: '假期银行', icon: 'fa-umbrella-beach' },
  { key: 'lifecycle_enhancement', label: '生命周期增强', icon: 'fa-arrows-spin' },
  { key: 'attendance_optimization', label: '考勤优化', icon: 'fa-clock' },
  { key: 'shift_marketplace', label: '班次市场', icon: 'fa-right-left' },
];

const metricLabelMap: Record<string, string> = {
  employeeCount: '员工数',
  scheduleSuggestionCount: '排班建议',
  highLoadCount: '高负荷',
  simulationCount: '模拟数',
  assistantMode: '模式',
  departmentCount: '部门数',
  demandSignalCount: '需求信号',
  leaveRequestCount: '休假申请',
  usedLeaveHours: '已用小时',
  estimatedRemainingHours: '剩余额度',
  lifecycleSignalCount: '生命周期信号',
  probationCount: '转正事项',
  contractRenewalCount: '合同续签',
  attendanceRecordCount: '考勤记录',
  abnormalAttendanceCount: '异常考勤',
  averageWorkHours: '平均工时',
  abnormalRate: '异常率',
  shiftOfferCount: '班次机会',
  swapEligibleCount: '可交换',
  highLoadOfferCount: '高负荷',
};

function rowsFor(payload: WorkforceFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.scheduleSuggestions ||
    payload.simulations ||
    payload.recommendations ||
    payload.demandSignals ||
    payload.leaveBalances ||
    payload.signals ||
    payload.abnormalRecords ||
    payload.shiftOffers ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.employeeName ||
    row.departmentName ||
    row.name ||
    row.label ||
    row.type ||
    row.shiftType ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.status,
    row.demandLevel,
    row.recommendedShift,
    row.loadScore !== undefined ? `负荷 ${String(row.loadScore)}` : null,
    row.overtimeHours !== undefined ? `加班 ${String(row.overtimeHours)}h` : null,
    row.usedHours !== undefined ? `已用 ${String(row.usedHours)}h` : null,
    row.workHours !== undefined ? `工时 ${String(row.workHours)}h` : null,
    row.dueDate,
    row.message,
    row.recommendedAction,
    Array.isArray(row.reasons) ? row.reasons.join('；') : null,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof workforceFeatures)[number];
  payload?: WorkforceFeatureSummary;
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
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-orange-50 text-orange-700">
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
          {payload.provider?.message && (
            <div className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {payload.provider.message}
            </div>
          )}
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
        </div>
      )}
    </section>
  );
}

export default function WorkforceExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<WorkforceFeatureKey, WorkforceFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<WorkforceFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof workforceFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<WorkforceFeatureKey, WorkforceFeatureSummary>> = {};
    const nextErrors: Partial<Record<WorkforceFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'workforce', workforceFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.workforceFeatureSummary(feature.key);
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
    document.title = '排班与劳动力 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const scheduling = payloads.smart_scheduling?.summary || {};
    const planning = payloads.planning?.summary || {};
    const attendance = payloads.attendance_optimization?.summary || {};
    const marketplace = payloads.shift_marketplace?.summary || {};
    return [
      { label: '排班建议', value: scheduling.scheduleSuggestionCount || 0, icon: 'fa-calendar-days' },
      { label: '需求信号', value: planning.demandSignalCount || 0, icon: 'fa-people-line' },
      { label: '异常考勤', value: attendance.abnormalAttendanceCount || 0, icon: 'fa-clock' },
      { label: '班次机会', value: marketplace.shiftOfferCount || 0, icon: 'fa-right-left' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-50 text-orange-700">
                <AppIcon className="fas fa-calendar-days text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">排班与劳动力</h1>
                <div className="mt-1 text-xs text-slate-500">智能排班 · AI 排班增强 · 劳动力规划 · 假期银行 · 生命周期增强 · 考勤优化 · 班次市场</div>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-50 text-orange-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-orange-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成劳动力快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通排班与劳动力子功能</div>
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
