import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  attendanceEventApi,
  attendanceTimesheetApi,
  type AttendanceEventRow,
  type AttendanceSummaryRow,
  type AttendanceTimesheetRow,
} from '../../utils/api';
import { authUtils } from '../../utils/auth';

const WRITE_ROLES = new Set(['admin', 'hr_admin']);

const ColumnFilter: React.FC<{
  label: string;
  active: boolean;
  children: (close: () => void) => React.ReactNode;
}> = ({ label, active, children }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect) {
      setPos({
        top: rect.bottom + 4,
        left: Math.min(rect.left, Math.max(8, window.innerWidth - 224)),
      });
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return undefined;
    const handler = (event: MouseEvent) => {
      if (btnRef.current && !btnRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        title={`筛选：${label}`}
        className="ml-1 align-middle"
      >
        <i className={`fas fa-filter text-[10px] ${active ? 'text-blue-600' : 'text-gray-300 hover:text-gray-500'}`} />
      </button>
      {open &&
        createPortal(
          <div
            style={{ position: 'fixed', top: pos.top, left: pos.left }}
            className="z-[70] w-52 rounded-lg border border-gray-200 bg-white p-2 text-xs font-normal normal-case text-gray-700 shadow-xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            {children(() => setOpen(false))}
          </div>,
          document.body,
        )}
    </>
  );
};

const FilterRadio: React.FC<{
  name: string;
  label: string;
  checked: boolean;
  onSelect: () => void;
}> = ({ name, label, checked, onSelect }) => (
  <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-gray-50">
    <input type="radio" name={name} checked={checked} onChange={onSelect} />
    <span>{label}</span>
  </label>
);


const STATUS_LABELS: Record<string, string> = {
  normal: '正常',
  missing_card: '缺卡',
  absent: '旷工',
  rest: '休息',
  leave: '请假',
  other: '其他',
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  leave: '请假',
  compensatory: '调休',
  overtime: '加班',
  punch_fix: '补卡',
  outing: '外出',
  business_trip: '出差',
};

const toTimeOnly = (value?: string | null): string => (value ? value.slice(11, 16) : '');

const currentMonth = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

export default function AttendanceTimesheetPage() {
  const [month, setMonth] = useState(currentMonth());
  const [tab, setTab] = useState<'detail' | 'summary' | 'events'>('detail');
  const [status, setStatus] = useState('');
  const [eventType, setEventType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [filterDate, setFilterDate] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterOvertime, setFilterOvertime] = useState('');
  const [filterLeave, setFilterLeave] = useState('');
  const [filterEvent, setFilterEvent] = useState('');
  const [filterMinHours, setFilterMinHours] = useState('');
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<AttendanceTimesheetRow[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [summary, setSummary] = useState<AttendanceSummaryRow[]>([]);
  const [events, setEvents] = useState<AttendanceEventRow[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventPages, setEventPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eventDetail, setEventDetail] = useState<{
    open: boolean;
    loading: boolean;
    title: string;
    rows: AttendanceEventRow[];
    error: string | null;
  }>({ open: false, loading: false, title: '', rows: [], error: null });

  const canWrite = WRITE_ROLES.has(authUtils.getUser()?.role || '');

  const openEventDetail = async (row: AttendanceTimesheetRow) => {
    if (!row.eventSummary) return;
    setEventDetail({
      open: true,
      loading: true,
      title: `${row.employeeName || ''} ${row.workDate}`,
      rows: [],
      error: null,
    });
    try {
      const payload = await attendanceEventApi.list({
        employeeId: row.employeeId,
        startDate: row.workDate,
        endDate: row.workDate,
        size: 50,
      });
      setEventDetail((prev) => ({ ...prev, loading: false, rows: payload.items || [] }));
    } catch (err) {
      setEventDetail((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : '加载单据失败',
      }));
    }
  };

  const closeEventDetail = () => setEventDetail((prev) => ({ ...prev, open: false }));

  const loadDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await attendanceTimesheetApi.list({
        month,
        page,
        size: 20,
        status: status || undefined,
        keyword: keyword.trim() || undefined,
        date: filterDate || undefined,
        employeeType: filterType || undefined,
        hasOvertime: filterOvertime === '' ? undefined : filterOvertime === '1',
        hasLeave: filterLeave === '' ? undefined : filterLeave === '1',
        hasEvent: filterEvent === '' ? undefined : filterEvent === '1',
        minWorkHours: filterMinHours.trim() === '' ? undefined : Number(filterMinHours),
      });
      setRows(payload.items || []);
      setTotal(payload.total || 0);
      setPages(payload.pages || 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考勤明细失败');
    } finally {
      setLoading(false);
    }
  }, [month, page, status, keyword, filterDate, filterType, filterOvertime, filterLeave, filterEvent, filterMinHours]);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await attendanceTimesheetApi.summary(month, { keyword: keyword.trim() || undefined });
      setSummary(payload.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载月度汇总失败');
    } finally {
      setLoading(false);
    }
  }, [month, keyword]);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await attendanceEventApi.list({
        month,
        eventType: eventType || undefined,
        keyword: keyword.trim() || undefined,
        page,
        size: 20,
      });
      setEvents(payload.items || []);
      setEventTotal(payload.total || 0);
      setEventPages(payload.pages || 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考勤单据失败');
    } finally {
      setLoading(false);
    }
  }, [month, eventType, keyword, page]);

  useEffect(() => {
    if (tab === 'detail') void loadDetail();
    else if (tab === 'summary') void loadSummary();
    else void loadEvents();
  }, [tab, loadDetail, loadSummary, loadEvents]);

  useEffect(() => {
    setPage(1);
  }, [month, status, eventType, keyword, filterDate, filterType, filterOvertime, filterLeave, filterEvent, filterMinHours]);

  const handleSyncEvents = async () => {
    if (!canWrite) return;
    setBusy(true);
    setError(null);
    try {
      const result = await attendanceEventApi.sync(12);
      window.alert(`同步完成：读取 ${result.fetched}，新建 ${result.created}，更新 ${result.updated}，未匹配 ${result.unmatched}`);
      await loadEvents();
    } catch (err) {
      setError(err instanceof Error ? err.message : '同步失败');
    } finally {
      setBusy(false);
    }
  };

  const handleNotifySummary = async () => {
    if (!canWrite) return;
    setBusy(true);
    setError(null);
    try {
      const result = await attendanceTimesheetApi.notifySummary(month);
      window.alert(`已推送 ${result.pushed} 位部门负责人`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '推送失败');
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('month', month);
      if (status) params.set('status', status);
      if (keyword.trim()) params.set('keyword', keyword.trim());
      if (filterDate) params.set('date', filterDate);
      if (filterType) params.set('employeeType', filterType);
      if (filterOvertime !== '') params.set('hasOvertime', filterOvertime);
      if (filterLeave !== '') params.set('hasLeave', filterLeave);
      if (filterEvent !== '') params.set('hasEvent', filterEvent);
      if (filterMinHours.trim() !== '') params.set('minWorkHours', filterMinHours.trim());
      const token = authUtils.getToken();
      const res = await fetch(`/api/hrm/attendance-timesheet/export?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error('导出失败');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `考勤明细_${month}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败');
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = async () => {
    if (!canWrite) return;
    setBusy(true);
    setError(null);
    try {
      const result = await attendanceTimesheetApi.generate(month);
      window.alert(`生成完成：新建 ${result.created}，更新 ${result.updated}，保留人工校对 ${result.skippedManual}`);
      await loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const summaryTotals = useMemo(() => {
    const totals = { expectedDays: 0, presentDays: 0, absentDays: 0, workHours: 0, overtimeHours: 0 };
    summary.forEach((row) => {
      totals.expectedDays += row.expectedDays;
      totals.presentDays += row.presentDays;
      totals.absentDays += row.absentDays;
      totals.workHours += row.workHours;
      totals.overtimeHours += row.overtimeHours || 0;
    });
    return totals;
  }, [summary]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">考勤明细与校对</h1>
          <p className="mt-1 text-sm text-gray-500">
            依据 OA 排班、考勤机打卡与 OA 单据自动归属；按上方所选月份重算（切换月份仅查看，需点「生成」才刷新）。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value)}
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          {tab === 'events' && (
            <select
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            >
              <option value="">全部单据</option>
              <option value="leave">请假</option>
              <option value="compensatory">调休</option>
              <option value="overtime">加班</option>
              <option value="punch_fix">补卡</option>
              <option value="outing">外出</option>
              <option value="business_trip">出差</option>
            </select>
          )}
          <button
            type="button"
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
            onClick={() => {
              if (tab === 'detail') void loadDetail();
              else if (tab === 'summary') void loadSummary();
              else void loadEvents();
            }}
            disabled={loading}
          >
            {loading ? '加载中…' : '刷新'}
          </button>
          {canWrite && tab === 'detail' && (
            <button
              type="button"
              title="按上方所选月份重算，不会重算其它月份"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              onClick={() => void handleGenerate()}
              disabled={busy}
            >
              生成 {month} 明细
            </button>
          )}
          {canWrite && tab === 'events' && (
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              onClick={() => void handleSyncEvents()}
              disabled={busy}
            >
              同步 OA 单据
            </button>
          )}
          {canWrite && tab === 'summary' && (
            <button
              type="button"
              title="把当月部门工时推送（站内通知）给各部门负责人"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              onClick={() => void handleNotifySummary()}
              disabled={busy}
            >
              推送部门负责人
            </button>
          )}
          {tab === 'detail' && (
            <button
              type="button"
              title="按当前筛选导出 Excel"
              className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
              onClick={() => void handleExport()}
              disabled={busy}
            >
              导出 Excel
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-2 border-b border-gray-200">
        {([
          ['detail', '日明细'],
          ['summary', '月度汇总'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`px-3 py-2 text-sm ${tab === key ? 'border-b-2 border-blue-600 font-medium text-blue-700' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      {tab === 'detail' ? (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-400">
                  <th className="px-3 py-2">
                    员工
                    <ColumnFilter label="员工" active={!!keyword.trim()}>
                      {(close) => (
                        <div className="space-y-2">
                          <input
                            autoFocus
                            className="w-full rounded border border-gray-300 px-2 py-1"
                            value={keyword}
                            onChange={(event) => setKeyword(event.target.value)}
                            placeholder="姓名或工号"
                          />
                          <button type="button" className="text-blue-600 hover:underline" onClick={() => { setKeyword(''); close(); }}>
                            清除
                          </button>
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">
                    日期
                    <ColumnFilter label="日期" active={!!filterDate}>
                      {(close) => (
                        <div className="space-y-2">
                          <input
                            type="date"
                            className="w-full rounded border border-gray-300 px-2 py-1"
                            value={filterDate}
                            onChange={(event) => setFilterDate(event.target.value)}
                          />
                          <button type="button" className="text-blue-600 hover:underline" onClick={() => { setFilterDate(''); close(); }}>
                            清除
                          </button>
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">
                    类型
                    <ColumnFilter label="类型" active={!!filterType}>
                      {(close) => (
                        <div>
                          <FilterRadio name="f-type" label="全部" checked={!filterType} onSelect={() => { setFilterType(''); close(); }} />
                          <FilterRadio name="f-type" label="后勤" checked={filterType === '后勤'} onSelect={() => { setFilterType('后勤'); close(); }} />
                          <FilterRadio name="f-type" label="车间" checked={filterType === '车间'} onSelect={() => { setFilterType('车间'); close(); }} />
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">上班</th>
                  <th className="px-3 py-2">下班</th>
                  <th className="px-3 py-2">当天打卡</th>
                  <th className="px-3 py-2">
                    正常工时
                    <ColumnFilter label="正常工时" active={filterMinHours.trim() !== ''}>
                      {(close) => (
                        <div className="space-y-2">
                          <div className="flex items-center gap-1">
                            <span>≥</span>
                            <input
                              type="number"
                              className="w-full rounded border border-gray-300 px-2 py-1"
                              value={filterMinHours}
                              onChange={(event) => setFilterMinHours(event.target.value)}
                              placeholder="小时"
                            />
                          </div>
                          <button type="button" className="text-blue-600 hover:underline" onClick={() => { setFilterMinHours(''); close(); }}>
                            清除
                          </button>
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">
                    加班
                    <ColumnFilter label="加班" active={filterOvertime !== ''}>
                      {(close) => (
                        <div>
                          <FilterRadio name="f-ot" label="全部" checked={filterOvertime === ''} onSelect={() => { setFilterOvertime(''); close(); }} />
                          <FilterRadio name="f-ot" label="有加班" checked={filterOvertime === '1'} onSelect={() => { setFilterOvertime('1'); close(); }} />
                          <FilterRadio name="f-ot" label="无加班" checked={filterOvertime === '0'} onSelect={() => { setFilterOvertime('0'); close(); }} />
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">
                    请假
                    <ColumnFilter label="请假" active={filterLeave !== ''}>
                      {(close) => (
                        <div>
                          <FilterRadio name="f-lv" label="全部" checked={filterLeave === ''} onSelect={() => { setFilterLeave(''); close(); }} />
                          <FilterRadio name="f-lv" label="有请假" checked={filterLeave === '1'} onSelect={() => { setFilterLeave('1'); close(); }} />
                          <FilterRadio name="f-lv" label="无请假" checked={filterLeave === '0'} onSelect={() => { setFilterLeave('0'); close(); }} />
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">应/实打卡</th>
                  <th className="px-3 py-2">
                    状态
                    <ColumnFilter label="状态" active={!!status}>
                      {(close) => (
                        <div>
                          <FilterRadio name="f-st" label="全部" checked={!status} onSelect={() => { setStatus(''); close(); }} />
                          <FilterRadio name="f-st" label="正常" checked={status === 'normal'} onSelect={() => { setStatus('normal'); close(); }} />
                          <FilterRadio name="f-st" label="缺卡" checked={status === 'missing_card'} onSelect={() => { setStatus('missing_card'); close(); }} />
                          <FilterRadio name="f-st" label="旷工" checked={status === 'absent'} onSelect={() => { setStatus('absent'); close(); }} />
                          <FilterRadio name="f-st" label="请假" checked={status === 'leave'} onSelect={() => { setStatus('leave'); close(); }} />
                          <FilterRadio name="f-st" label="休息" checked={status === 'rest'} onSelect={() => { setStatus('rest'); close(); }} />
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">
                    单据
                    <ColumnFilter label="单据" active={filterEvent !== ''}>
                      {(close) => (
                        <div>
                          <FilterRadio name="f-ev" label="全部" checked={filterEvent === ''} onSelect={() => { setFilterEvent(''); close(); }} />
                          <FilterRadio name="f-ev" label="有单据" checked={filterEvent === '1'} onSelect={() => { setFilterEvent('1'); close(); }} />
                          <FilterRadio name="f-ev" label="无单据" checked={filterEvent === '0'} onSelect={() => { setFilterEvent('0'); close(); }} />
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-gray-100">
                    <td className="px-3 py-2 text-gray-800">{row.employeeName || row.employeeId}</td>
                    <td className="px-3 py-2 text-gray-500">{row.workDate}</td>
                    <td className="px-3 py-2 text-gray-500">{row.employeeType || '-'}</td>
                    <td className="px-3 py-2 text-gray-600">
                      {toTimeOnly(row.checkIn) || '-'}
                      {row.checkInFixed && (
                        <span
                          title="来自 OA 补卡单"
                          className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700"
                        >
                          补
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-600">
                      {toTimeOnly(row.checkOut) || '-'}
                      {row.checkOutFixed && (
                        <span
                          title="来自 OA 补卡单"
                          className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700"
                        >
                          补
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {row.punchTimes && row.punchTimes.length > 0 ? (
                        <span className="flex flex-wrap gap-1">
                          {row.punchTimes.map((punch) => (
                            <span key={punch.t} className="rounded bg-gray-100 px-1">
                              {punch.t.slice(11, 16)}
                              {punch.fix && <span className="ml-0.5 text-amber-600">补</span>}
                            </span>
                          ))}
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-700">{row.workHours}</td>
                    <td className="px-3 py-2 text-orange-600">{row.overtimeHours ? row.overtimeHours : '-'}</td>
                    <td className="px-3 py-2 text-indigo-600">{row.leaveHours ? row.leaveHours : '-'}</td>
                    <td className="px-3 py-2 text-gray-500">
                      {row.expectedPunches}/{row.actualPunches}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-gray-700">{STATUS_LABELS[row.status] || row.status}</span>
                      {row.manualCorrected && <span className="ml-1 text-xs text-amber-600">已校对</span>}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.eventSummary ? (
                        <button
                          type="button"
                          onClick={() => void openEventDetail(row)}
                          className="rounded border border-gray-200 px-1.5 py-0.5 text-gray-600 hover:bg-gray-50 hover:text-blue-600"
                        >
                          {row.eventSummary}
                        </button>
                      ) : (
                        <span className="text-gray-500">-</span>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && !loading && (
                  <tr>
                    <td className="px-3 py-10 text-center text-gray-400" colSpan={11}>
                      暂无数据
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
                onClick={() => setPage((value) => Math.max(1, value - 1))}
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
                onClick={() => setPage((value) => value + 1)}
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      ) : tab === 'summary' ? (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="flex flex-wrap gap-4 border-b border-gray-100 px-3 py-2 text-xs text-gray-500">
            <span>员工 {summary.length} 人</span>
            <span>应出勤 {summaryTotals.expectedDays} 天</span>
            <span>出勤 {summaryTotals.presentDays} 天</span>
            <span>旷工 {summaryTotals.absentDays} 天</span>
            <span>合计工时 {summaryTotals.workHours.toFixed(1)}h</span>
            <span className="text-orange-600">合计加班 {summaryTotals.overtimeHours.toFixed(1)}h</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-400">
                  <th className="px-3 py-2">
                    员工
                    <ColumnFilter label="员工" active={!!keyword.trim()}>
                      {(close) => (
                        <div className="space-y-2">
                          <input
                            autoFocus
                            className="w-full rounded border border-gray-300 px-2 py-1"
                            value={keyword}
                            onChange={(event) => setKeyword(event.target.value)}
                            placeholder="姓名或工号"
                          />
                          <button type="button" className="text-blue-600 hover:underline" onClick={() => { setKeyword(''); close(); }}>
                            清除
                          </button>
                        </div>
                      )}
                    </ColumnFilter>
                  </th>
                  <th className="px-3 py-2">部门</th>
                  <th className="px-3 py-2">应出勤</th>
                  <th className="px-3 py-2">出勤</th>
                  <th className="px-3 py-2">正常</th>
                  <th className="px-3 py-2">缺卡</th>
                  <th className="px-3 py-2">旷工</th>
                  <th className="px-3 py-2">正常工时</th>
                  <th className="px-3 py-2">加班</th>
                  <th className="px-3 py-2">出勤率</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((row) => (
                  <tr key={row.employeeId} className="border-t border-gray-100">
                    <td className="px-3 py-2 text-gray-800">{row.employeeName || row.employeeId}</td>
                    <td className="px-3 py-2 text-gray-500">{row.departmentName || '-'}</td>
                    <td className="px-3 py-2 text-gray-600">{row.expectedDays}</td>
                    <td className="px-3 py-2 text-gray-600">{row.presentDays}</td>
                    <td className="px-3 py-2 text-gray-600">{row.normalDays}</td>
                    <td className="px-3 py-2 text-gray-600">{row.missingCardDays}</td>
                    <td className="px-3 py-2 text-gray-600">{row.absentDays}</td>
                    <td className="px-3 py-2 text-gray-700">{row.workHours}</td>
                    <td className="px-3 py-2 text-orange-600">{row.overtimeHours ? row.overtimeHours : '-'}</td>
                    <td className="px-3 py-2 text-gray-600">
                      {row.attendanceRate == null ? '-' : `${(row.attendanceRate * 100).toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
                {summary.length === 0 && !loading && (
                  <tr>
                    <td className="px-3 py-10 text-center text-gray-400" colSpan={9}>
                      暂无汇总数据
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-400">
                  <th className="px-3 py-2">员工</th>
                  <th className="px-3 py-2">工号</th>
                  <th className="px-3 py-2">单据类型</th>
                  <th className="px-3 py-2">开始</th>
                  <th className="px-3 py-2">结束</th>
                  <th className="px-3 py-2">时长</th>
                  <th className="px-3 py-2">事由</th>
                  <th className="px-3 py-2">单据号</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="border-t border-gray-100">
                    <td className="px-3 py-2 text-gray-800">
                      {event.employeeName || (event.employeeId ? event.employeeId : '未匹配员工')}
                    </td>
                    <td className="px-3 py-2 text-gray-500">{event.employeeNo || '-'}</td>
                    <td className="px-3 py-2 text-gray-600">{EVENT_TYPE_LABELS[event.eventType] || event.eventType}</td>
                    <td className="px-3 py-2 text-gray-500">{event.startAt ? event.startAt.slice(0, 16).replace('T', ' ') : '-'}</td>
                    <td className="px-3 py-2 text-gray-500">{event.endAt ? event.endAt.slice(0, 16).replace('T', ' ') : '-'}</td>
                    <td className="px-3 py-2 text-gray-700">{event.hours != null ? `${event.hours}h` : '-'}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">{event.reason || '-'}</td>
                    <td className="px-3 py-2 text-xs text-gray-400">{event.oaMainId || '-'}</td>
                  </tr>
                ))}
                {events.length === 0 && !loading && (
                  <tr>
                    <td className="px-3 py-10 text-center text-gray-400" colSpan={8}>
                      暂无单据，可点击「同步 OA 单据」拉取近 12 个月数据
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-gray-100 px-3 py-2 text-sm text-gray-500">
            <span>共 {eventTotal} 条</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                上一页
              </button>
              <span>
                {page} / {eventPages}
              </span>
              <button
                type="button"
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
                disabled={page >= eventPages}
                onClick={() => setPage((value) => value + 1)}
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      )}

      {eventDetail.open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={closeEventDetail}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-lg bg-white p-4 shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">
                原单明细 · {eventDetail.title}
              </h2>
              <button
                type="button"
                onClick={closeEventDetail}
                className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-600 hover:bg-gray-50"
              >
                关闭
              </button>
            </div>
            {eventDetail.loading && <p className="mt-3 text-sm text-gray-500">加载中…</p>}
            {eventDetail.error && <p className="mt-3 text-sm text-red-600">{eventDetail.error}</p>}
            {!eventDetail.loading && !eventDetail.error && eventDetail.rows.length === 0 && (
              <p className="mt-3 text-sm text-gray-500">未找到当天对应的单据记录</p>
            )}
            {eventDetail.rows.length > 0 && (
              <table className="mt-3 min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-gray-400">
                    <th className="px-2 py-1.5">类型</th>
                    <th className="px-2 py-1.5">开始</th>
                    <th className="px-2 py-1.5">结束</th>
                    <th className="px-2 py-1.5">时长</th>
                    <th className="px-2 py-1.5">事由</th>
                    <th className="px-2 py-1.5">单据号</th>
                  </tr>
                </thead>
                <tbody>
                  {eventDetail.rows.map((event) => (
                    <tr key={event.id} className="border-t border-gray-100">
                      <td className="px-2 py-1.5 text-gray-700">
                        {EVENT_TYPE_LABELS[event.eventType] || event.eventType}
                      </td>
                      <td className="px-2 py-1.5 text-gray-500">
                        {event.startAt ? event.startAt.slice(0, 16).replace('T', ' ') : '-'}
                      </td>
                      <td className="px-2 py-1.5 text-gray-500">
                        {event.endAt ? event.endAt.slice(0, 16).replace('T', ' ') : '-'}
                      </td>
                      <td className="px-2 py-1.5 text-gray-700">
                        {event.hours != null ? `${event.hours}h` : '-'}
                      </td>
                      <td className="px-2 py-1.5 text-xs text-gray-500">{event.reason || '-'}</td>
                      <td className="px-2 py-1.5 text-xs text-gray-400">{event.oaMainId || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
