import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, IntegrationFeatureKey, IntegrationFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const integrationFeatures: Array<{ key: IntegrationFeatureKey; label: string; icon: string }> = [
  { key: 'open_api', label: '开放 API', icon: 'fa-code' },
  { key: 'api_key_oauth', label: 'API Key/OAuth', icon: 'fa-key' },
  { key: 'webhook', label: 'Webhook', icon: 'fa-share-nodes' },
  { key: 'sso', label: 'SSO', icon: 'fa-user-lock' },
  { key: 'prebuilt_integrations', label: '预集成', icon: 'fa-plug-circle-check' },
  { key: 'realtime_sync', label: '实时同步', icon: 'fa-rotate' },
  { key: 'app_marketplace', label: '应用市场', icon: 'fa-store' },
  { key: 'video_meeting', label: '视频会议适配', icon: 'fa-video' },
  { key: 'im_adapter', label: 'IM 适配', icon: 'fa-comment-dots' },
  { key: 'sms_adapter', label: '短信适配', icon: 'fa-message' },
];

const metricLabelMap: Record<string, string> = {
  endpointCount: '端点数',
  scopeCount: '权限域',
  version: '版本',
  credentialFlowCount: '凭据流程',
  secretLeakGuard: '凭据保护',
  eventCount: '事件数',
  retryPolicy: '重试策略',
  protocolCount: '协议数',
  configuredProviderCount: '已配置',
  providerCount: '供应商',
  syncJobCount: '同步任务',
  eventDrivenCount: '事件驱动',
  appCount: '应用数',
  configuredAppCount: '已配置应用',
  templateCount: '模板数',
  messageTemplateCount: '消息模板',
  smsTemplateCount: '短信模板',
};

function rowsFor(payload: IntegrationFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.endpoints ||
    payload.credentialFlows ||
    payload.events ||
    payload.protocols ||
    payload.providers ||
    payload.syncJobs ||
    payload.apps ||
    payload.meetingTemplates ||
    payload.messageTemplates ||
    payload.smsTemplates ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.name ||
    row.path ||
    row.event ||
    row.providerCode ||
    row.key ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.method,
    row.scope,
    row.status,
    row.category,
    row.deliveryMode,
    row.cadence,
    row.auditAction,
    row.secretStorage,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof integrationFeatures)[number];
  payload?: IntegrationFeatureSummary;
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
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-700">
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
            <div className={`mb-4 rounded-lg px-3 py-2 text-xs ${payload.provider.configured ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
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

export default function IntegrationExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<IntegrationFeatureKey, IntegrationFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<IntegrationFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof integrationFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<IntegrationFeatureKey, IntegrationFeatureSummary>> = {};
    const nextErrors: Partial<Record<IntegrationFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'integration', integrationFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.integrationFeatureSummary(feature.key);
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
    document.title = '集成管理 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const openApi = payloads.open_api?.summary || {};
    const webhook = payloads.webhook?.summary || {};
    const marketplace = payloads.app_marketplace?.summary || {};
    const prebuilt = payloads.prebuilt_integrations?.summary || {};
    return [
      { label: 'API 端点', value: openApi.endpointCount || 0, icon: 'fa-code' },
      { label: 'Webhook 事件', value: webhook.eventCount || 0, icon: 'fa-share-nodes' },
      { label: '市场应用', value: marketplace.appCount || 0, icon: 'fa-store' },
      { label: '已配置供应商', value: prebuilt.configuredProviderCount || 0, icon: 'fa-plug-circle-check' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-50 text-sky-700">
                <AppIcon className="fas fa-plug text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">集成管理</h1>
                <div className="mt-1 text-xs text-slate-500">开放 API · API Key/OAuth · Webhook · SSO · 预集成 · 实时同步 · 应用市场 · 视频会议 · IM · 短信</div>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-50 text-sky-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-sky-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成生态集成快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通生态集成子功能</div>
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
