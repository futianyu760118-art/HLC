import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  performanceParticipantApi,
  type PerformanceParticipantRow,
} from '../../utils/api';
import { authUtils } from '../../utils/auth';

const WRITE_ROLES = new Set(['admin', 'hr_admin']);

export default function PerformanceParticipantsPage() {
  const [rows, setRows] = useState<PerformanceParticipantRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [keyword, setKeyword] = useState('');
  const [departmentName, setDepartmentName] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canWrite = WRITE_ROLES.has(authUtils.getUser()?.role || '');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await performanceParticipantApi.list({
        keyword: keyword.trim() || undefined,
        departmentName: departmentName.trim() || undefined,
      });
      setRows(payload.items || []);
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载员工失败');
    } finally {
      setLoading(false);
    }
  }, [keyword, departmentName]);

  useEffect(() => {
    void load();
  }, [load]);

  const participantCount = useMemo(
    () => rows.filter((row) => row.participant).length,
    [rows],
  );

  const allSelected = rows.length > 0 && selected.size === rows.length;

  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(rows.map((row) => row.id)));
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const apply = async (participant: boolean) => {
    if (!canWrite || selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await performanceParticipantApi.save(Array.from(selected), participant);
      window.alert(`已${participant ? '标记' : '取消'} ${result.updated} 人参与考核`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">参与考核人员</h1>
          <p className="mt-1 text-sm text-gray-500">
            勾选员工标记「参与考核」后，生成考核表时才会为其按岗位生成。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="w-40 rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={departmentName}
            onChange={(event) => setDepartmentName(event.target.value)}
            placeholder="按部门筛选"
          />
          <input
            className="w-40 rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索姓名或工号"
          />
          <button
            type="button"
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            onClick={() => void load()}
            disabled={loading}
          >
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
        <span className="text-gray-600">
          共 {rows.length} 人，已参与 <span className="font-medium text-blue-700">{participantCount}</span> 人，已选 {selected.size} 人
        </span>
        {canWrite && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              onClick={() => void apply(true)}
              disabled={busy || selected.size === 0}
            >
              标记参与考核
            </button>
            <button
              type="button"
              className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
              onClick={() => void apply(false)}
              disabled={busy || selected.size === 0}
            >
              取消参与考核
            </button>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-400">
                {canWrite && (
                  <th className="px-3 py-2">
                    <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="全选" />
                  </th>
                )}
                <th className="px-3 py-2">姓名</th>
                <th className="px-3 py-2">工号</th>
                <th className="px-3 py-2">部门</th>
                <th className="px-3 py-2">岗位</th>
                <th className="px-3 py-2">人员类型</th>
                <th className="px-3 py-2">参与考核</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  {canWrite && (
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggleOne(row.id)}
                        aria-label={`选择 ${row.name}`}
                      />
                    </td>
                  )}
                  <td className="px-3 py-2 text-gray-800">{row.name}</td>
                  <td className="px-3 py-2 text-gray-500">{row.employeeNo || '-'}</td>
                  <td className="px-3 py-2 text-gray-500">{row.departmentName || '-'}</td>
                  <td className="px-3 py-2 text-gray-500">{row.positionName || '-'}</td>
                  <td className="px-3 py-2 text-gray-500">{row.employeeType || '-'}</td>
                  <td className="px-3 py-2">
                    {row.participant ? (
                      <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">参与</span>
                    ) : (
                      <span className="text-xs text-gray-400">未参与</span>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && !loading && (
                <tr>
                  <td className="px-3 py-10 text-center text-gray-400" colSpan={canWrite ? 7 : 6}>
                    暂无员工
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
