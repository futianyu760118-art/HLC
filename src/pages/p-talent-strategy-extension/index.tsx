import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, extensionApi, TalentFeatureKey, TalentFeatureSummary } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const talentFeatures: Array<{ key: TalentFeatureKey; label: string; icon: string; description: string }> = [
  { key: 'profile', label: '人才画像', icon: 'fa-id-badge', description: '员工多维画像、九宫格和人才标签' },
  { key: 'competency_model', label: '能力模型', icon: 'fa-chart-radar', description: '岗位能力模型、测评覆盖和短板维度' },
  { key: 'succession', label: '继任计划', icon: 'fa-sitemap', description: '关键角色、继任候选和缺口识别' },
  { key: 'review', label: '人才盘点', icon: 'fa-table-cells', description: '九宫格盘点和核心人才分布' },
  { key: 'career_path', label: '职业发展路径', icon: 'fa-route', description: '员工下一岗位和成长步骤建议' },
  { key: 'idp', label: '个人发展计划', icon: 'fa-list-check', description: 'IDP 关注领域和复盘节奏' },
  { key: 'internal_marketplace', label: '内部人才市场', icon: 'fa-briefcase', description: '内部机会和匹配人才' },
];

const metricLabelMap: Record<string, string> = {
  employeeCount: '员工数',
  coreTalentCount: '核心人才',
  highPotentialCount: '高潜人才',
  modelCount: '模型数',
  assessmentCount: '测评数',
  averageScore: '平均分',
  keyRoleCount: '关键角色',
  readyRoleCount: '有继任',
  gapCount: '缺口',
  nineBoxCount: '盘点人数',
  observationCount: '待观察',
  pathCount: '路径数',
  planCount: '计划数',
  monthlyReviewCount: '月度复盘',
  openOpportunityCount: '开放机会',
  matchCount: '匹配人数',
};

function firstList(payload: TalentFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.profiles ||
    payload.models ||
    payload.keyRoles ||
    payload.nineBox ||
    payload.paths ||
    payload.plans ||
    payload.opportunities ||
    payload.weakestDimensions ||
    []
  );
}

function displayName(row: Record<string, unknown>) {
  return String(
    row.employeeName ||
    row.name ||
    row.roleName ||
    row.label ||
    row.currentPosition ||
    row.title ||
    row.dimensionKey ||
    '未命名',
  );
}

function displayDetail(row: Record<string, unknown>) {
  const parts = [
    row.departmentName,
    row.positionTitle,
    row.targetPosition,
    row.readiness,
    row.matchCount !== undefined ? `${row.matchCount} 个匹配` : null,
    row.count !== undefined ? `${row.count} 人` : null,
  ].filter(Boolean);
  return parts.join(' · ');
}

function FeatureCard({
  feature,
  payload,
  error,
}: {
  feature: (typeof talentFeatures)[number];
  payload?: TalentFeatureSummary;
  error?: string;
}) {
  const metrics = Object.entries(payload?.summary || {})
    .filter(([key, value]) => key !== 'dataScope' && value !== undefined && value !== null && typeof value !== 'boolean')
    .slice(0, 3);
  const rows = payload ? firstList(payload).slice(0, 3) : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            <AppIcon className={`fas ${feature.icon} text-sm`} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-900">{feature.label}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">{feature.description}</p>
          </div>
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
                <div className="mt-1 text-lg font-bold text-slate-900">{String(value)}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-2">
            {rows.length === 0 ? (
              <div className="py-6 text-center text-xs text-slate-400">暂无可展示明细</div>
            ) : rows.map((row, index) => (
              <div key={`${feature.key}-${index}`} className="rounded-lg border border-slate-100 px-3 py-2">
                <div className="truncate text-sm font-semibold text-slate-800">{displayName(row)}</div>
                <div className="mt-1 truncate text-xs text-slate-500">{displayDetail(row) || feature.label}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export default function TalentStrategyExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<TalentFeatureKey, TalentFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<TalentFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof talentFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<TalentFeatureKey, TalentFeatureSummary>> = {};
    const nextErrors: Partial<Record<TalentFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'talent', talentFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.talentFeatureSummary(feature.key);
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
    document.title = '人才盘点与发展 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const profile = payloads.profile?.summary || {};
    const succession = payloads.succession?.summary || {};
    const marketplace = payloads.internal_marketplace?.summary || {};
    return [
      { label: '人才画像人数', value: profile.employeeCount || 0, icon: 'fa-id-badge' },
      { label: '核心人才', value: profile.coreTalentCount || 0, icon: 'fa-star' },
      { label: '继任缺口', value: succession.gapCount || 0, icon: 'fa-sitemap' },
      { label: '内部机会', value: marketplace.openOpportunityCount || 0, icon: 'fa-briefcase' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <AppIcon className="fas fa-people-arrows text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">人才盘点与发展</h1>
                <p className="mt-1 text-xs text-slate-500">人才画像、能力模型、继任、盘点、发展路径、IDP 与内部机会的统一能力工作台</p>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-blue-500">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成人才战略快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通人才战略子功能</div>
        ) : (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            {enabledFeatures.map((feature) => (
              <FeatureCard
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
