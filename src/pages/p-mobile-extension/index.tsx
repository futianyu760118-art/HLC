import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, MobileFeatureKey, MobileFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const mobileFeatures: Array<{ key: MobileFeatureKey; label: string; icon: string }> = [
  { key: 'self_service', label: '员工自助增强', icon: 'fa-user-check' },
  { key: 'pwa', label: '移动 Web/PWA', icon: 'fa-mobile-screen' },
  { key: 'approval', label: '移动审批', icon: 'fa-clipboard-check' },
  { key: 'attendance', label: '移动考勤', icon: 'fa-location-dot' },
  { key: 'payslip', label: '工资条', icon: 'fa-file-invoice-dollar' },
  { key: 'certificate_download', label: '证明下载', icon: 'fa-certificate' },
  { key: 'notifications', label: '通知移动体验', icon: 'fa-bell' },
  { key: 'offline_shell', label: '离线外壳', icon: 'fa-cloud-arrow-down' },
];

const metricLabelMap: Record<string, string> = {
  employeeCount: '员工数',
  portalAccountCount: '门户账号',
  selfServiceActionCount: '自助动作',
  installableCapabilityCount: 'PWA 能力',
  deliveryMode: '交付模式',
  approvalCount: '审批数',
  pendingApprovalCount: '待审批',
  mobileAttendanceRecordCount: '考勤记录',
  normalRecordCount: '正常记录',
  visiblePayslipCount: '可见工资条',
  totalNetSalary: '实发合计',
  certificateCount: '证书数',
  downloadReadyCount: '可下载',
  notificationCount: '通知数',
  unreadNotificationCount: '未读通知',
  offlineResourceCount: '离线资源',
  offlineMode: '离线模式',
};

function rowsFor(payload: MobileFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.accounts ||
    payload.actions ||
    payload.capabilities ||
    payload.approvals ||
    payload.attendanceRecords ||
    payload.payslips ||
    payload.certificates ||
    payload.notifications ||
    payload.resources ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.employeeName ||
    row.label ||
    row.title ||
    row.courseTitle ||
    row.certNo ||
    row.key ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.status,
    row.employeeNo,
    row.payrollMonth,
    row.noticeType,
    row.strategy,
    row.source,
    row.workHours !== undefined ? `工时 ${String(row.workHours)}h` : null,
    row.netSalary !== undefined ? `实发 ${String(row.netSalary)}` : null,
    row.linkUrl,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof mobileFeatures)[number];
  payload?: MobileFeatureSummary;
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
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-rose-50 text-rose-700">
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
        </div>
      )}
    </section>
  );
}

export default function MobileExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<MobileFeatureKey, MobileFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<MobileFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof mobileFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<MobileFeatureKey, MobileFeatureSummary>> = {};
    const nextErrors: Partial<Record<MobileFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'mobile', mobileFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.mobileFeatureSummary(feature.key);
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
    document.title = '员工自助与移动端 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const selfService = payloads.self_service?.summary || {};
    const approval = payloads.approval?.summary || {};
    const payslip = payloads.payslip?.summary || {};
    const offline = payloads.offline_shell?.summary || {};
    return [
      { label: '门户账号', value: selfService.portalAccountCount || 0, icon: 'fa-user-check' },
      { label: '待审批', value: approval.pendingApprovalCount || 0, icon: 'fa-clipboard-check' },
      { label: '工资条', value: payslip.visiblePayslipCount || 0, icon: 'fa-file-invoice-dollar' },
      { label: '离线资源', value: offline.offlineResourceCount || 0, icon: 'fa-cloud-arrow-down' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-50 text-rose-700">
                <AppIcon className="fas fa-mobile-screen text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">员工自助与移动端</h1>
                <div className="mt-1 text-xs text-slate-500">员工自助增强 · 移动 Web/PWA · 移动审批 · 移动考勤 · 工资条 · 证明下载 · 通知移动体验 · 离线外壳</div>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-50 text-rose-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-rose-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成移动体验快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通员工自助与移动子功能</div>
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
