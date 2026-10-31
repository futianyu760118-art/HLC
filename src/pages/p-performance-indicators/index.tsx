import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  performanceIndicatorApi,
  performanceMetricOptions,
  type PerformanceIndicatorPayload,
  type PerformanceIndicatorRow,
} from '../../utils/api';
import { authUtils } from '../../utils/auth';

const WRITE_ROLES = new Set(['admin', 'hr_admin']);

const EMPTY_FORM: PerformanceIndicatorPayload & {
  departmentName: string;
  positionName: string;
  name: string;
} = {
  departmentName: '',
  positionName: '',
  seq: null,
  name: '',
  targetValue: '',
  scoringRule: '',
  weight: 10,
  evaluatorDepartment: '',
  linkedToSalary: true,
  metric: '',
  operator: '>=',
  threshold: null,
  score: null,
  dataSource: 'system',
  targetSource: 'fixed',
  targetOaDepartmentId: '',
  scoringMode: 'threshold',
};

export default function PerformanceIndicatorsPage() {
  const [rows, setRows] = useState<PerformanceIndicatorRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<typeof EMPTY_FORM | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const canWrite = WRITE_ROLES.has(authUtils.getUser()?.role || '');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await performanceIndicatorApi.list();
      setRows(payload || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考核指标失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    const map = new Map<string, PerformanceIndicatorRow[]>();
    rows.forEach((row) => {
      const key = `${row.departmentName || '-'} / ${row.positionName || '-'}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(row);
    });
    return Array.from(map.entries());
  }, [rows]);

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
  };

  const openEdit = (row: PerformanceIndicatorRow) => {
    setEditingId(row.id);
    setForm({
      departmentName: row.departmentName || '',
      positionName: row.positionName || '',
      seq: row.seq ?? null,
      name: row.name,
      targetValue: row.targetValue || '',
      scoringRule: row.scoringRule || '',
      weight: row.weight ?? 10,
      evaluatorDepartment: row.evaluatorDepartment || '',
      linkedToSalary: row.linkedToSalary !== false,
      metric: row.rule?.metric || '',
      operator: row.rule?.operator || '>=',
      threshold: row.rule?.threshold ?? null,
      score: row.rule?.score ?? null,
      dataSource: row.rule?.dataSource || 'system',
      targetSource: row.rule?.targetSource || 'fixed',
      targetOaDepartmentId: row.rule?.targetOaDepartmentId || '',
      scoringMode: row.rule?.scoringMode || 'threshold',
    });
  };

  const submit = async () => {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      if (editingId) await performanceIndicatorApi.update(editingId, form);
      else await performanceIndicatorApi.create(form);
      setForm(null);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: PerformanceIndicatorRow) => {
    if (!window.confirm(`确认删除指标「${row.name}」？`)) return;
    setBusy(true);
    setError(null);
    try {
      await performanceIndicatorApi.remove(row.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">考核指标基础资料</h1>
          <p className="mt-1 text-sm text-gray-500">
            按「部门 + 岗位」维护考核指标、目标值与自动取数规则。
          </p>
        </div>
        <div className="flex items-center gap-2">
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
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
              onClick={openCreate}
            >
              新增指标
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      {grouped.length === 0 && !loading && (
        <div className="rounded-lg border border-dashed border-gray-200 py-16 text-center text-sm text-gray-400">
          暂无考核指标（可点「新增指标」）
        </div>
      )}

      {grouped.map(([key, items]) => (
        <div key={key} className="rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <span className="text-sm font-medium text-gray-800">{key}</span>
            <span className="text-xs text-gray-400">
              合计权重 {items.reduce((sum, item) => sum + (Number(item.weight) || 0), 0)}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-400">
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">考核指标</th>
                  <th className="px-3 py-2">目标值</th>
                  <th className="px-3 py-2">权重</th>
                  <th className="px-3 py-2">评分标准</th>
                  <th className="px-3 py-2">数据来源（说明）</th>
                  <th className="px-3 py-2">评价部门</th>
                  {canWrite && <th className="px-3 py-2">操作</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-t border-gray-100 align-top">
                    <td className="px-3 py-2 text-gray-500">{item.seq}</td>
                    <td className="px-3 py-2 text-gray-800">
                      {item.name}
                      {item.linkedToSalary === false && (
                        <span className="ml-1 text-xs text-gray-400">（不挂钩工资）</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{item.targetValue || '-'}</td>
                    <td className="px-3 py-2 text-gray-600">{item.weight ?? '-'}</td>
                    <td className="px-3 py-2 text-gray-500 whitespace-pre-line">{item.scoringRule || '-'}</td>
                    <td className="px-3 py-2">
                      {item.scoringRuleConfigured ? (
                        <span className="text-xs text-green-700">
                          {item.dataSourceNote}
                          {item.rule?.scoringMode === 'achievement' ? '；按达成率评分' : ''}
                          {item.rule?.targetSource === 'oa_monthly'
                            ? `；目标来自 OA 月度目标（部门${item.rule?.targetOaDepartmentId || '?'}）`
                            : item.rule?.operator
                              ? `；判定 ${item.rule.operator} ${item.rule.threshold}`
                              : ''}
                        </span>
                      ) : (
                        <span className="text-xs text-amber-600">未配置取数规则（需人工录入）</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-500">{item.evaluatorDepartment || '-'}</td>
                    {canWrite && (
                      <td className="px-3 py-2">
                        <button type="button" className="text-blue-600 hover:underline" onClick={() => openEdit(item)}>
                          编辑
                        </button>
                        <button
                          type="button"
                          className="ml-3 text-red-500 hover:underline"
                          onClick={() => void remove(item)}
                        >
                          删除
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {form && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-4 shadow-lg">
            <h2 className="text-base font-semibold text-gray-900">
              {editingId ? '编辑考核指标' : '新增考核指标'}
            </h2>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="text-sm">
                <span className="text-gray-600">部门</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.departmentName}
                  onChange={(event) => setForm({ ...form, departmentName: event.target.value })}
                  placeholder="如：销售中心"
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">岗位</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.positionName}
                  onChange={(event) => setForm({ ...form, positionName: event.target.value })}
                  placeholder="如：副总"
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">序号</span>
                <input
                  type="number"
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.seq ?? ''}
                  onChange={(event) =>
                    setForm({ ...form, seq: event.target.value === '' ? null : Number(event.target.value) })
                  }
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">指标名称</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">目标值</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.targetValue ?? ''}
                  onChange={(event) => setForm({ ...form, targetValue: event.target.value })}
                  placeholder="如：500000"
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">权重分</span>
                <input
                  type="number"
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.weight ?? ''}
                  onChange={(event) =>
                    setForm({ ...form, weight: event.target.value === '' ? null : Number(event.target.value) })
                  }
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">评价部门</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.evaluatorDepartment ?? ''}
                  onChange={(event) => setForm({ ...form, evaluatorDepartment: event.target.value })}
                />
              </label>
              <label className="text-sm">
                <span className="text-gray-600">是否挂钩工资</span>
                <select
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.linkedToSalary ? '1' : '0'}
                  onChange={(event) => setForm({ ...form, linkedToSalary: event.target.value === '1' })}
                >
                  <option value="1">挂钩</option>
                  <option value="0">不挂钩</option>
                </select>
              </label>
              <label className="text-sm md:col-span-2">
                <span className="text-gray-600">评分标准</span>
                <textarea
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  rows={2}
                  value={form.scoringRule ?? ''}
                  onChange={(event) => setForm({ ...form, scoringRule: event.target.value })}
                />
              </label>
              <label className="text-sm md:col-span-2">
                <span className="text-gray-600">自动取数指标（数据来源）</span>
                <select
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                  value={form.metric ?? ''}
                  onChange={(event) => setForm({ ...form, metric: event.target.value })}
                >
                  {performanceMetricOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              {form.metric && (
                <>
                  <label className="text-sm">
                    <span className="text-gray-600">评分方式</span>
                    <select
                      className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                      value={form.scoringMode ?? 'threshold'}
                      onChange={(event) => setForm({ ...form, scoringMode: event.target.value })}
                    >
                      <option value="threshold">达标/不达标（满分或 0）</option>
                      <option value="achievement">达成率（实际/目标×权重，&lt;60%为0，封顶+10）</option>
                    </select>
                  </label>
                  <label className="text-sm">
                    <span className="text-gray-600">目标来源</span>
                    <select
                      className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                      value={form.targetSource ?? 'fixed'}
                      onChange={(event) => setForm({ ...form, targetSource: event.target.value })}
                    >
                      <option value="fixed">固定值（用下方阈值）</option>
                      <option value="oa_monthly">OA 月度目标（部门月度分解）</option>
                    </select>
                  </label>
                  {form.targetSource === 'oa_monthly' ? (
                    <label className="text-sm">
                      <span className="text-gray-600">OA 部门ID（uf_ndmbdr.bm）</span>
                      <input
                        className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                        value={form.targetOaDepartmentId ?? ''}
                        onChange={(event) => setForm({ ...form, targetOaDepartmentId: event.target.value })}
                        placeholder="如：37（销售一部）"
                      />
                    </label>
                  ) : (
                    <label className="text-sm">
                      <span className="text-gray-600">阈值</span>
                      <input
                        type="number"
                        className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                        value={form.threshold ?? ''}
                        onChange={(event) =>
                          setForm({ ...form, threshold: event.target.value === '' ? null : Number(event.target.value) })
                        }
                        placeholder="如：500000"
                      />
                    </label>
                  )}
                  {form.scoringMode === 'threshold' && (
                    <label className="text-sm">
                      <span className="text-gray-600">比较符</span>
                      <select
                        className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5"
                        value={form.operator ?? '>='}
                        onChange={(event) => setForm({ ...form, operator: event.target.value })}
                      >
                        <option value=">=">≥ 大于等于</option>
                        <option value="<=">≤ 小于等于</option>
                        <option value=">">&gt; 大于</option>
                        <option value="<">&lt; 小于</option>
                      </select>
                    </label>
                  )}
                </>
              )}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-3 py-1.5 text-sm"
                onClick={() => {
                  setForm(null);
                  setEditingId(null);
                }}
              >
                取消
              </button>
              <button
                type="button"
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                onClick={() => void submit()}
                disabled={busy}
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
