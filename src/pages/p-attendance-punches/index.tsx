import { useCallback, useEffect, useState } from 'react';
import { attendanceTimesheetApi } from '../../utils/api';

interface PunchRow {
  id: string;
  employeeId?: string | null;
  employeeName: string;
  employeeNo?: string | null;
  checkDate: string;
  checkTimeOnly: string;
  checkType?: string | null;
}

type FilterMode = 'date' | 'month';

const today = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};

const currentMonth = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

export default function AttendancePunchesPage() {
  const [filterMode, setFilterMode] = useState<FilterMode>('date');
  const [date, setDate] = useState(today());
  const [month, setMonth] = useState(currentMonth());
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<PunchRow[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = { page, size: 50 };
      if (filterMode === 'date' && date) {
        params.date = date;
      } else if (filterMode === 'month' && month) {
        params.month = month;
      }
      if (keyword.trim()) {
        params.keyword = keyword.trim();
      }
      const payload = await attendanceTimesheetApi.punches(params);
      setRows(payload.items || []);
      setTotal(payload.total || 0);
      setPages(payload.pages || 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载原始打卡失败');
    } finally {
      setLoading(false);
    }
  }, [filterMode, date, month, page, keyword]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [filterMode, date, month]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [keyword]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">原始打卡记录</h1>
          <p className="mt-1 text-sm text-gray-500">
            考勤机每次刷卡的流水记录（不汇总、不计算工时）。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded border border-gray-300">
            <button
              type="button"
              className={`px-3 py-1.5 text-sm ${filterMode === 'date' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              onClick={() => setFilterMode('date')}
            >
              按天
            </button>
            <button
              type="button"
              className={`px-3 py-1.5 text-sm ${filterMode === 'month' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              onClick={() => setFilterMode('month')}
            >
              按月
            </button>
          </div>
          {filterMode === 'date' ? (
            <input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          ) : (
            <input
              type="month"
              value={month}
              onChange={(event) => setMonth(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            />
          )}
          <input
            type="text"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索姓名或工号"
            className="rounded border border-gray-300 px-2 py-1.5 text-sm w-40"
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

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-100 px-3 py-2 text-xs text-gray-500">
          {filterMode === 'date' ? `日期：${date}` : `月份：${month}`} · 共 {total} 条打卡记录
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-gray-400">
                <th className="px-3 py-2">日期</th>
                <th className="px-3 py-2">打卡时间</th>
                <th className="px-3 py-2">员工</th>
                <th className="px-3 py-2">工号</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 text-gray-500">
                    {row.checkDate}
                    {filterMode === 'month' && (
                      <span className="ml-1 text-xs text-gray-400">
                        周{['日', '一', '二', '三', '四', '五', '六'][new Date(row.checkDate).getDay()]}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-medium text-gray-800">{row.checkTimeOnly}</td>
                  <td className="px-3 py-2 text-gray-700">{row.employeeName}</td>
                  <td className="px-3 py-2 text-gray-500">{row.employeeNo || '-'}</td>
                </tr>
              ))}
              {rows.length === 0 && !loading && (
                <tr>
                  <td className="px-3 py-10 text-center text-gray-400" colSpan={4}>
                    {filterMode === 'date' ? '当天暂无打卡记录' : '当月暂无打卡记录'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-gray-100 px-3 py-2 text-sm text-gray-500">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              disabled={page <= 1}
              onClick={() => setPage((v) => Math.max(1, v - 1))}
            >
              上一页
            </button>
            <span>
              {page} / {pages}
            </span>
            <button
              type="button"
              className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              disabled={page >= pages}
              onClick={() => setPage((v) => v + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
