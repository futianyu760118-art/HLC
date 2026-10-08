import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, SecurityFeatureKey, SecurityFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const securityFeatures: Array<{ key: SecurityFeatureKey; label: string; icon: string }> = [
  { key: 'data_masking', label: '数据脱敏', icon: 'fa-user-secret' },
  { key: 'compliance_reporting', label: '合规报告', icon: 'fa-file-shield' },
  { key: 'audit_logs', label: '审计日志增强', icon: 'fa-clipboard-list' },
  { key: 'gdpr', label: 'GDPR 合规', icon: 'fa-scale-balanced' },
  { key: 'database_encryption', label: '数据库加密', icon: 'fa-database' },
  { key: 'point_in_time_recovery', label: '时间点恢复', icon: 'fa-clock-rotate-left' },
  { key: 'globalization_locale', label: '全球化语言', icon: 'fa-language' },
  { key: 'globalization_currency', label: '全球化币种', icon: 'fa-coins' },
  { key: 'globalization_timezone', label: '全球化时区', icon: 'fa-earth-asia' },
  { key: 'globalization_policy', label: '全球化规则', icon: 'fa-globe' },
  { key: 'data_lifecycle', label: '数据生命周期', icon: 'fa-recycle' },
  { key: 'mlps_evidence', label: '等保证据', icon: 'fa-shield-halved' },
];

const metricLabelMap: Record<string, string> = {
  maskedRecordCount: '脱敏记录',
  maskedFieldCount: '脱敏字段',
  maskingMode: '脱敏模式',
  controlCount: '控制项',
  implementedControlCount: '已实现',
  externalGateCount: '外部门禁',
  externalAcceptedGateCount: '已接受',
  externalGateAccepted: '外部门禁',
  operationLogCount: '操作日志',
  assistantAuditCount: 'AI 审计',
  retentionMode: '保留模式',
  dataRequestCount: '数据请求',
  exportRequestCount: '导出请求',
  deletionRequestCount: '删除请求',
  ownerEvidenceRequired: '需 Owner 证据',
  secretReferenceControl: '密钥控制',
  providerConfigCount: '供应商配置',
  databaseEncryptionStatus: '加密状态',
  restoreDrillAccepted: '恢复演练',
  restoreEvidenceStatus: '恢复证据',
  targetProject: '目标项目',
  defaultLocale: '默认语言',
  supportedLocaleCount: '语言数',
  defaultCurrency: '默认币种',
  supportedCurrencyCount: '币种数',
  defaultTimezone: '默认时区',
  supportedTimezoneCount: '时区数',
  regionCount: '区域数',
  policyCount: '规则数',
  crossBorderTransfer: '跨境传输',
  tableCount: '表数量',
  totalRows: '数据行',
  requiresOwnerApproval: 'Owner 批准',
  requiresFinalBackup: '最终备份',
  destructive: '破坏性',
  mlpsAccepted: '等保接受',
  evidenceItemCount: '证据项',
  pendingEvidenceCount: '待证据',
};

function rowsFor(payload: SecurityFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.maskedSamples ||
    payload.controls ||
    payload.externalGates ||
    payload.dataRequests ||
    payload.operationLogs ||
    payload.assistantAudits ||
    payload.requests ||
    payload.rights ||
    payload.providers ||
    payload.runbookChecks ||
    payload.locales ||
    payload.currencies ||
    payload.timezones ||
    payload.regions ||
    payload.policies ||
    payload.evidenceItems ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.label ||
    row.name ||
    row.gate ||
    row.key ||
    row.module ||
    row.action ||
    row.requestType ||
    row.providerCode ||
    row.code ||
    row.recordType ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.status,
    row.value,
    row.strategy,
    row.maskingMode,
    row.targetId,
    row.requester,
    row.scope,
    row.recordId,
    row.hasSecretRef !== undefined ? `secretRef ${String(row.hasSecretRef)}` : null,
    row.createdAt,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function displayMetric(value: unknown) {
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof securityFeatures)[number];
  payload?: SecurityFeatureSummary;
  error?: string;
}) {
  const metrics = Object.entries(payload?.summary || {})
    .filter(([key, value]) => key !== 'dataScope' && value !== undefined && value !== null)
    .slice(0, 3);
  const rows = payload ? rowsFor(payload).slice(0, 4) : [];
  const pendingOwnerEvidence = JSON.stringify(payload || {}).includes('Pending owner evidence');

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
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
          {pendingOwnerEvidence && (
            <div className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Pending owner evidence
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            {metrics.map(([key, value]) => (
              <div key={key} className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="text-[11px] text-slate-500">{metricLabelMap[key] || key}</div>
                <div className="mt-1 truncate text-lg font-bold text-slate-900">{displayMetric(value)}</div>
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

export default function SecurityExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<SecurityFeatureKey, SecurityFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<SecurityFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof securityFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<SecurityFeatureKey, SecurityFeatureSummary>> = {};
    const nextErrors: Partial<Record<SecurityFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'security', securityFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.securityFeatureSummary(feature.key);
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
    document.title = '安全与合规 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const masking = payloads.data_masking?.summary || {};
    const audit = payloads.audit_logs?.summary || {};
    const lifecycle = payloads.data_lifecycle?.summary || {};
    const compliance = payloads.compliance_reporting?.summary || {};
    return [
      { label: '脱敏字段', value: masking.maskedFieldCount || 0, icon: 'fa-user-secret' },
      { label: '审计日志', value: audit.operationLogCount || 0, icon: 'fa-clipboard-list' },
      { label: '生命周期表', value: lifecycle.tableCount || 0, icon: 'fa-recycle' },
      { label: '外部门禁已接受', value: compliance.externalAcceptedGateCount || 0, icon: 'fa-file-shield' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                <AppIcon className="fas fa-shield-halved text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">安全与合规</h1>
                <div className="mt-1 text-xs text-slate-500">数据脱敏 · 合规报告 · 审计日志增强 · GDPR 合规 · 数据库加密 · 时间点恢复 · 全球化能力 · 数据生命周期 · 等保证据</div>
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

        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Pending owner evidence：本页展示产品内安全合规能力，不改变 legal、ICP、MLPS、数据生命周期、restore drill 或 final release 的外部证据门禁状态。
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          {overview.map((item) => (
            <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs text-slate-500">{item.label}</div>
                  <div className="mt-2 text-2xl font-bold text-slate-900">{String(item.value)}</div>
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-teal-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成安全合规快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通安全合规子功能</div>
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
