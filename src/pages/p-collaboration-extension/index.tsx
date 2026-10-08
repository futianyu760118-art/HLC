import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { ApiError, CollaborationFeatureKey, CollaborationFeatureSummary, extensionApi } from '../../utils/api';
import { enabledExtensionFeatures, extensionMaturityLabel } from '../../utils/extensionEntitlements';

const collaborationFeatures: Array<{ key: CollaborationFeatureKey; label: string; icon: string }> = [
  { key: 'okr', label: 'OKR', icon: 'fa-bullseye' },
  { key: 'one_on_one', label: '1-on-1', icon: 'fa-handshake' },
  { key: 'survey_enps', label: '员工调研/eNPS', icon: 'fa-square-poll-vertical' },
  { key: 'employee_care', label: '员工关怀', icon: 'fa-heart-pulse' },
  { key: 'social', label: '社交功能', icon: 'fa-comments' },
  { key: 'onboarding_experience', label: '新员工体验', icon: 'fa-door-open' },
  { key: 'virtual_assistant', label: '虚拟助手', icon: 'fa-robot' },
  { key: 'feedback_experience', label: '反馈体验增强', icon: 'fa-message' },
];

const metricLabelMap: Record<string, string> = {
  objectiveCount: '目标数',
  alignedDepartmentCount: '对齐部门',
  averageProgress: '平均进度',
  employeeCount: '员工数',
  suggestedMeetingCount: '建议会议',
  monthlyCadenceCount: '月度节奏',
  surveySignalCount: '调研信号',
  openFeedbackCount: '待处理反馈',
  estimatedEnps: 'eNPS 估算',
  careSignalCount: '关怀信号',
  unreadCareCount: '未读关怀',
  postCount: '帖子数',
  replyCount: '回复数',
  engagementScore: '互动分',
  taskCount: '任务数',
  pendingTaskCount: '待办任务',
  newHireCount: '新员工',
  assistantIntentCount: '助手意图',
  knowledgeSourceCount: '知识源',
  assistantMode: '模式',
  feedbackCount: '反馈数',
  criticalCount: '严重反馈',
};

function rowsFor(payload: CollaborationFeatureSummary): Array<Record<string, unknown>> {
  return (
    payload.objectives ||
    payload.suggestions ||
    payload.signals ||
    payload.careSignals ||
    payload.posts ||
    payload.tasks ||
    payload.intents ||
    payload.feedbacks ||
    []
  );
}

function rowTitle(row: Record<string, unknown>) {
  return String(
    row.title ||
    row.employeeName ||
    row.label ||
    row.name ||
    row.intent ||
    row.taskType ||
    row.id ||
    '未命名',
  );
}

function rowDetail(row: Record<string, unknown>) {
  const pieces = [
    row.owner,
    row.departmentName,
    row.status,
    row.sentiment,
    row.suggestedCadence,
    row.riskLevel,
    row.recommendedAction,
    row.progress !== undefined ? `进度 ${String(row.progress)}` : null,
    row.value !== undefined ? `值 ${String(row.value)}` : null,
    row.replyCount !== undefined ? `回复 ${String(row.replyCount)}` : null,
    row.likeCount !== undefined ? `点赞 ${String(row.likeCount)}` : null,
    Array.isArray(row.topics) ? row.topics.join('；') : null,
    row.sample,
  ].filter(Boolean);
  return pieces.join(' · ');
}

function FeaturePanel({
  feature,
  payload,
  error,
}: {
  feature: (typeof collaborationFeatures)[number];
  payload?: CollaborationFeatureSummary;
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
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
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

export default function CollaborationExtensionPage() {
  const [payloads, setPayloads] = useState<Partial<Record<CollaborationFeatureKey, CollaborationFeatureSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<CollaborationFeatureKey, string>>>({});
  const [enabledFeatures, setEnabledFeatures] = useState<typeof collaborationFeatures>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setCatalogError('');
    const nextPayloads: Partial<Record<CollaborationFeatureKey, CollaborationFeatureSummary>> = {};
    const nextErrors: Partial<Record<CollaborationFeatureKey, string>> = {};
    try {
      const catalog = await extensionApi.catalog();
      const nextEnabledFeatures = enabledExtensionFeatures(catalog, 'collaboration', collaborationFeatures);
      setEnabledFeatures(nextEnabledFeatures);
      await Promise.all(nextEnabledFeatures.map(async (feature) => {
        try {
          nextPayloads[feature.key] = await extensionApi.collaborationFeatureSummary(feature.key);
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
    document.title = '员工体验 - 恒聘通';
    loadData();
  }, [loadData]);

  const overview = useMemo(() => {
    const okr = payloads.okr?.summary || {};
    const oneOnOne = payloads.one_on_one?.summary || {};
    const survey = payloads.survey_enps?.summary || {};
    const social = payloads.social?.summary || {};
    return [
      { label: '目标数', value: okr.objectiveCount || 0, icon: 'fa-bullseye' },
      { label: '1-on-1 建议', value: oneOnOne.suggestedMeetingCount || 0, icon: 'fa-handshake' },
      { label: '调研信号', value: survey.surveySignalCount || 0, icon: 'fa-square-poll-vertical' },
      { label: '互动内容', value: social.postCount || 0, icon: 'fa-comments' },
    ];
  }, [payloads]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                <AppIcon className="fas fa-people-group text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">员工体验</h1>
                <div className="mt-1 text-xs text-slate-500">OKR · 1-on-1 · 员工调研/eNPS · 员工关怀 · 社交功能 · 新员工体验 · 虚拟助手 · 反馈体验增强</div>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                  <AppIcon className={`fas ${item.icon} text-sm`} />
                </div>
              </div>
            </div>
          ))}
        </div>

        {catalogError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700">{catalogError}</div>
        ) : loading && Object.keys(payloads).length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-20 text-center text-emerald-600">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm text-slate-500">正在生成协同体验快照...</div>
          </div>
        ) : enabledFeatures.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-sm text-slate-500">当前未开通协同体验子功能</div>
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
