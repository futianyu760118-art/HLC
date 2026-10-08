import { Fragment, useCallback, useEffect, useState } from 'react';
import {
  performanceCenterApi,
  type PerformanceReviewDetail,
  type PerformanceReviewRow,
} from '../../utils/api';
import { authUtils } from '../../utils/auth';

const WRITE_ROLES = new Set(['admin', 'hr_admin']);

const currentMonth = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

export default function PerformanceCenterPage() {
  const [month, setMonth] = useState(currentMonth());
  const [rows, setRows] = useState<PerformanceReviewRow[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [useAi, setUseAi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<PerformanceReviewDetail | null>(null);
  const [scoreDraft, setScoreDraft] = useState<Record<string, Record<string, number | null>>>({});
  const [detailBusy, setDetailBusy] = useState(false);

  const canWrite = WRITE_ROLES.has(authUtils.getUser()?.role || '');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await performanceCenterApi.overview(month);
      setRows(payload.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考核表失败');
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleGenerate = async () => {
    if (!canWrite) return;
    setBusy(true);
    setError(null);
    try {
      const result = await performanceCenterApi.generate(month);
      const extra = result.withoutIndicators.length
        ? `\n无匹配指标（未生成）：${result.withoutIndicators.join('、')}`
        : '';
      window.alert(`生成完成：新建 ${result.created}，已存在跳过 ${result.skipped}${extra}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const handleAutoScore = async (row: PerformanceReviewRow) => {
    if (!canWrite) return;
    setBusy(true);
    setError(null);
    try {
      const result = await performanceCenterApi.autoScore(row.id, month, useAi);
      window.alert(
        `评分完成：命中 ${result.scoredItems}/${result.totalItems} 项，总分 ${result.autoScore}` +
          (result.aiUsed ? '（含 AI 分析）' : ''),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '自动评分失败');
    } finally {
      setBusy(false);
    }
  };

  const totalWeight = (row: PerformanceReviewRow) =>
    row.items.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);

  const openDetail = async (row: PerformanceReviewRow) => {
    setDetailBusy(true);
    setError(null);
    try {
      const payload = await performanceCenterApi.detail(row.id);
      setDetail(payload);
      const draft: Record<string, Record<string, number | null>> = {};
      payload.items.forEach((item) => {
        draft[item.id] = {
          selfScore: item.selfScore ?? null,
          managerScore: item.managerScore ?? null,
          finalScore: item.finalScore ?? null,
        };
      });
      setScoreDraft(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考核表详情失败');
    } finally {
      setDetailBusy(false);
    }
  };

  const closeDetail = () => {
    setDetail(null);
    setScoreDraft({});
  };

  const setDraft = (itemId: string, field: string, raw: string) => {
    setScoreDraft((prev) => ({
      ...prev,
      [itemId]: { ...(prev[itemId] || {}), [field]: raw === '' ? null : Number(raw) },
    }));
  };

  const saveScores = async () => {
    if (!detail) return;
    const allowed = detail.permissions.allowedFields;
    const items = detail.items.map((item) => {
      const draft = scoreDraft[item.id] || {};
      const entry: { id: string; selfScore?: number | null; managerScore?: number | null; finalScore?: number | null } = { id: item.id };
      if (allowed.includes('self_score')) entry.selfScore = draft.selfScore ?? null;
      if (allowed.includes('manager_score')) entry.managerScore = draft.managerScore ?? null;
      if (allowed.includes('final_score')) entry.finalScore = draft.finalScore ?? null;
      return entry;
    });
    setDetailBusy(true);
    setError(null);
    try {
      const result = await performanceCenterApi.saveScores(detail.id, items);
      window.alert(`已保存：最终分 ${result.finalScore ?? '-'}，等级 ${result.grade ?? '-'}`);
      await openDetail({ ...detail });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存评分失败');
    } finally {
      setDetailBusy(false);
    }
  };

  const pushReview = async () => {
    if (!detail) return;
    setDetailBusy(true);
    setError(null);
    try {
      const result = await performanceCenterApi.notify(detail.id, ['self', 'manager']);
      window.alert(`已推送 ${result.sent} 人（本人/上级）`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '推送失败');
    } finally {
      setDetailBusy(false);
    }
  };

  const confirmReview = async () => {
    if (!detail) return;
    if (!window.confirm('确认该考核结果并归档？')) return;
    setDetailBusy(true);
    setError(null);
    try {
      const result = await performanceCenterApi.confirm(detail.id);
      window.alert(`已确认：最终分 ${result.finalScore ?? '-'}，等级 ${result.grade ?? '-'}`);
      await openDetail({ ...detail });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败');
    } finally {
      setDetailBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">绩效考核中心</h1>
          <p className="mt-1 text-sm text-gray-500">
            月初按岗位生成考核表，自动取数评分（可人工复核）。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <label className="flex items-center gap-1 text-sm text-gray-600">
            <input type="checkbox" checked={useAi} onChange={(event) => setUseAi(event.target.checked)} />
            启用 AI 分析
          </label>
          <button
            type="button"
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            onClick={() => void load()}
            disabled={loading}
          >
            {loading ? '加载中…' : '刷新'}
          </button>
          {canWrite && (
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              onClick={() => void handleGenerate()}
              disabled={busy}
            >
              生成考核表
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-100 px-3 py-2 text-xs text-gray-500">
          {month} · 共 {rows.length} 张考核表
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-400">
                <th className="px-3 py-2">员工</th>
                <th className="px-3 py-2">上级</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">指标数</th>
                <th className="px-3 py-2">权重合计</th>
                <th className="px-3 py-2">自动分</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.id}>
                  <tr className="border-t border-gray-100">
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="text-gray-800 hover:text-blue-600"
                        onClick={() => setExpanded({ ...expanded, [row.id]: !expanded[row.id] })}
                      >
                        {expanded[row.id] ? '▾' : '▸'} {row.employeeName || row.employeeId}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-gray-500">{row.managerName || '-'}</td>
                    <td className="px-3 py-2 text-gray-500">{row.status}</td>
                    <td className="px-3 py-2 text-gray-600">{row.items.length}</td>
                    <td className="px-3 py-2 text-gray-600">{totalWeight(row)}</td>
                    <td className="px-3 py-2 text-gray-700">{row.autoScore ?? '-'}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        className="text-blue-600 hover:underline disabled:opacity-50"
                        onClick={() => void openDetail(row)}
                        disabled={detailBusy}
                      >
                        复核
                      </button>
                      {canWrite && (
                        <button
                          type="button"
                          className="ml-3 text-blue-600 hover:underline disabled:opacity-50"
                          onClick={() => void handleAutoScore(row)}
                          disabled={busy}
                        >
                          自动评分
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded[row.id] && (
                    <tr className="bg-gray-50">
                      <td colSpan={7} className="px-3 py-2">
                        <table className="min-w-full text-xs">
                          <thead>
                            <tr className="text-left text-gray-400">
                              <th className="py-1 pr-4">指标</th>
                              <th className="py-1 pr-4">权重</th>
                              <th className="py-1 pr-4">自动分</th>
                              <th className="py-1">说明</th>
                            </tr>
                          </thead>
                          <tbody>
                            {row.items.map((item) => (
                              <tr key={item.id} className="border-t border-gray-200">
                                <td className="py-1 pr-4 text-gray-700">{item.indicatorName}</td>
                                <td className="py-1 pr-4 text-gray-500">{item.weight ?? '-'}</td>
                                <td className="py-1 pr-4 text-gray-600">{item.autoScore ?? '-'}</td>
                                <td className="py-1 text-gray-500">{item.comment || '-'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {rows.length === 0 && !loading && (
                <tr>
                  <td className="px-3 py-10 text-center text-gray-400" colSpan={7}>
                    该月暂无考核表（可点「生成考核表」）
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg bg-white p-4 shadow-lg">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">
                考核复核 · {detail.employeeName || detail.employeeId}
                {detail.managerName ? `（上级：${detail.managerName}）` : ''}
              </h2>
              <button
                type="button"
                className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-600 hover:bg-gray-50"
                onClick={closeDetail}
              >
                关闭
              </button>
            </div>
            <div className="mt-2 text-xs text-gray-500">
              状态：{detail.status}
              {detail.permissions.isHr ? ' · HR/管理员可复核最终分' : ''}
              {detail.permissions.isManager ? ' · 上级可评分' : ''}
              {detail.permissions.isSelf ? ' · 本人可自评' : ''}
            </div>

            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-gray-400">
                    <th className="px-2 py-1.5">指标</th>
                    <th className="px-2 py-1.5">权重</th>
                    <th className="px-2 py-1.5">自动分</th>
                    <th className="px-2 py-1.5">自评</th>
                    <th className="px-2 py-1.5">上级评分</th>
                    <th className="px-2 py-1.5">最终分</th>
                    <th className="px-2 py-1.5">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.items.map((item) => {
                    const draft = scoreDraft[item.id] || {};
                    const allowed = detail.permissions.allowedFields;
                    return (
                      <tr key={item.id} className="border-t border-gray-100 align-top">
                        <td className="px-2 py-1.5 text-gray-700">{item.indicatorName}</td>
                        <td className="px-2 py-1.5 text-gray-500">{item.weight ?? '-'}</td>
                        <td className="px-2 py-1.5 text-gray-600">{item.autoScore ?? '-'}</td>
                        <td className="px-2 py-1.5">
                          {allowed.includes('self_score') ? (
                            <input
                              type="number"
                              className="w-20 rounded border border-gray-300 px-1 py-0.5"
                              value={draft.selfScore ?? ''}
                              onChange={(event) => setDraft(item.id, 'selfScore', event.target.value)}
                            />
                          ) : (
                            <span className="text-gray-600">{item.selfScore ?? '-'}</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          {allowed.includes('manager_score') ? (
                            <input
                              type="number"
                              className="w-20 rounded border border-gray-300 px-1 py-0.5"
                              value={draft.managerScore ?? ''}
                              onChange={(event) => setDraft(item.id, 'managerScore', event.target.value)}
                            />
                          ) : (
                            <span className="text-gray-600">{item.managerScore ?? '-'}</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          {allowed.includes('final_score') ? (
                            <input
                              type="number"
                              className="w-20 rounded border border-gray-300 px-1 py-0.5"
                              value={draft.finalScore ?? ''}
                              onChange={(event) => setDraft(item.id, 'finalScore', event.target.value)}
                            />
                          ) : (
                            <span className="text-gray-600">{item.finalScore ?? '-'}</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-xs text-gray-500">{item.comment || '-'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
              <span className="mr-auto text-sm text-gray-500">
                自动分 {detail.autoScore ?? '-'} · 上级 {detail.managerScore ?? '-'} · 最终 {detail.finalScore ?? '-'}
                {detail.grade ? ` · 等级 ${detail.grade}` : ''}
              </span>
              <button
                type="button"
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                onClick={() => void saveScores()}
                disabled={detailBusy || detail.permissions.allowedFields.length === 0}
              >
                保存评分
              </button>
              <button
                type="button"
                className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
                onClick={() => void pushReview()}
                disabled={detailBusy}
              >
                推送本人/上级
              </button>
              {detail.permissions.isHr && (
                <button
                  type="button"
                  className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
                  onClick={() => void confirmReview()}
                  disabled={detailBusy}
                >
                  确认并归档
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
