import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import {
  ApiError,
  ContinuousFeedbackEntry,
  ContinuousFeedbackStatsPayload,
  extensionApi,
  hrmApi,
} from '../../utils/api';

type EmployeeOption = {
  id: string;
  name?: string;
  employeeNo?: string;
  departmentName?: string;
};

const feedbackTypes = [
  { value: 'praise', label: '认可' },
  { value: 'coaching', label: '辅导' },
  { value: 'concern', label: '关怀' },
  { value: 'suggestion', label: '建议' },
];

const visibilityOptions = [
  { value: 'manager', label: '直属管理者' },
  { value: 'hr', label: 'HR 可见' },
  { value: 'private', label: '仅记录人可见' },
];

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'open', label: '待处理' },
  { value: 'acknowledged', label: '已确认' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
];

const statusLabels: Record<string, string> = {
  open: '待处理',
  acknowledged: '已确认',
  resolved: '已解决',
  closed: '已关闭',
};

const typeLabels = Object.fromEntries(feedbackTypes.map((item) => [item.value, item.label]));

const sentimentTone: Record<string, string> = {
  positive: 'bg-emerald-50 text-emerald-700',
  neutral: 'bg-slate-100 text-slate-700',
  negative: 'bg-rose-50 text-rose-700',
};

const normalizeEmployees = (value: unknown): EmployeeOption[] => {
  if (!Array.isArray(value)) return [];
  return value
    .map((item: any) => ({
      id: String(item.id || ''),
      name: item.name || item.employeeName,
      employeeNo: item.employeeNo || item.employee_no,
      departmentName: item.departmentName,
    }))
    .filter((item) => item.id);
};

function StatCard({ label, value, icon }: { label: string; value: number; icon: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs text-slate-500">{label}</div>
          <div className="mt-2 text-2xl font-bold text-slate-900">{value}</div>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
          <AppIcon className={`fas ${icon} text-sm`} />
        </div>
      </div>
    </div>
  );
}

export default function ContinuousFeedbackPage() {
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [items, setItems] = useState<ContinuousFeedbackEntry[]>([]);
  const [stats, setStats] = useState<ContinuousFeedbackStatsPayload['stats']>({
    total: 0,
    byType: {},
    bySentiment: {},
    byStatus: {},
  });
  const [statusFilter, setStatusFilter] = useState('');
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('');
  const [feedbackType, setFeedbackType] = useState('praise');
  const [visibility, setVisibility] = useState('manager');
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [handlerReply, setHandlerReply] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const selectedEmployeeName = useMemo(() => {
    const employee = employees.find((item) => item.id === selectedEmployeeId);
    return employee?.name || employee?.employeeNo || '';
  }, [employees, selectedEmployeeId]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [employeeRows, listPayload, statsPayload] = await Promise.all([
        hrmApi.list('employees').catch(() => []),
        extensionApi.continuousFeedbackEntries({ status: statusFilter, limit: 100 }),
        extensionApi.continuousFeedbackStats(),
      ]);
      const normalized = normalizeEmployees(employeeRows);
      setEmployees(normalized);
      setItems(listPayload.items || []);
      setStats(statsPayload.stats);
      if (!selectedEmployeeId && normalized[0]) {
        setSelectedEmployeeId(normalized[0].id);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('当前企业未开通持续反馈，请联系平台管理员。');
      } else {
        setError(err instanceof Error ? err.message : '持续反馈数据加载失败');
      }
    } finally {
      setLoading(false);
    }
  }, [selectedEmployeeId, statusFilter]);

  useEffect(() => {
    document.title = '持续反馈 - 恒聘通';
    loadData();
  }, [loadData]);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    setError('');
    if (!selectedEmployeeId) {
      setError('请先选择反馈对象。');
      return;
    }
    if (!content.trim()) {
      setError('请输入反馈内容。');
      return;
    }
    setSaving(true);
    try {
      await extensionApi.createContinuousFeedback({
        employeeId: selectedEmployeeId,
        feedbackType,
        visibility,
        category: category.trim(),
        content: content.trim(),
      });
      setContent('');
      setCategory('');
      setMessage(`${selectedEmployeeName || '员工'} 的反馈已记录。`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈创建失败');
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (entryId: string, status: 'acknowledged' | 'resolved') => {
    setMessage('');
    setError('');
    try {
      await extensionApi.updateContinuousFeedbackStatus(entryId, {
        status,
        handlerReply: handlerReply.trim(),
      });
      setHandlerReply('');
      setMessage(status === 'acknowledged' ? '反馈已确认。' : '反馈已解决。');
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈状态更新失败');
    }
  };

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <AppIcon className="fas fa-comments text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">持续反馈</h1>
                <p className="mt-1 text-xs text-slate-500">记录认可、辅导和关怀反馈，并跟踪处理闭环</p>
              </div>
            </div>
            <button
              type="button"
              onClick={loadData}
              className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <AppIcon className="fas fa-refresh mr-2 text-xs" />
              刷新
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-800">
            <AppIcon className="fas fa-triangle-exclamation mr-2" />
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-3 text-sm text-emerald-800">
            <AppIcon className="fas fa-circle-check mr-2" />
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <StatCard label="反馈总数" value={stats.total || 0} icon="fa-comments" />
          <StatCard label="待处理" value={stats.byStatus.open || 0} icon="fa-inbox" />
          <StatCard label="正向反馈" value={stats.bySentiment.positive || 0} icon="fa-thumbs-up" />
          <StatCard label="关怀信号" value={stats.bySentiment.negative || 0} icon="fa-heart-pulse" />
        </div>

        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <form onSubmit={handleCreate} className="rounded-lg border border-slate-200 bg-white p-5 xl:col-span-1">
            <h2 className="text-sm font-semibold text-slate-900">记录反馈</h2>
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-500">反馈对象</label>
                <select
                  value={selectedEmployeeId}
                  onChange={(event) => setSelectedEmployeeId(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  {employees.length === 0 && <option value="">暂无员工</option>}
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.name || employee.employeeNo || employee.id}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-500">类型</label>
                  <select
                    value={feedbackType}
                    onChange={(event) => setFeedbackType(event.target.value)}
                    className="mt-1 h-9 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  >
                    {feedbackTypes.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500">可见范围</label>
                  <select
                    value={visibility}
                    onChange={(event) => setVisibility(event.target.value)}
                    className="mt-1 h-9 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  >
                    {visibilityOptions.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500">主题</label>
                <input
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="协作、成长、关怀..."
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500">反馈内容</label>
                <textarea
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                  className="mt-1 min-h-28 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="记录可行动、可追踪的反馈内容"
                />
              </div>
              <button
                type="submit"
                disabled={saving || loading}
                className="inline-flex h-9 w-full items-center justify-center rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              >
                {saving ? <AppIcon className="fas fa-spinner fa-spin mr-2 text-xs" /> : <AppIcon className="fas fa-plus mr-2 text-xs" />}
                提交反馈
              </button>
            </div>
          </form>

          <section className="rounded-lg border border-slate-200 bg-white xl:col-span-2">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-3 md:flex-row md:items-center md:justify-between">
              <h2 className="text-sm font-semibold text-slate-900">反馈列表</h2>
              <div className="flex items-center gap-2">
                <input
                  value={handlerReply}
                  onChange={(event) => setHandlerReply(event.target.value)}
                  className="h-9 w-56 rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="处理备注"
                />
                <select
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  {statusOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </div>
            </div>
            {loading ? (
              <div className="py-20 text-center text-blue-500">
                <AppIcon className="fas fa-spinner fa-spin text-xl" />
                <div className="mt-2 text-sm text-slate-500">正在加载反馈...</div>
              </div>
            ) : items.length === 0 ? (
              <div className="py-20 text-center text-sm text-slate-400">暂无反馈记录</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {items.map((item) => (
                  <div key={item.id} className="px-5 py-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">{item.employeeName || item.employeeId}</span>
                          <span className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                            {typeLabels[item.feedbackType] || item.feedbackType}
                          </span>
                          <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${sentimentTone[item.sentiment] || sentimentTone.neutral}`}>
                            {item.sentiment}
                          </span>
                          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                            {statusLabels[item.status] || item.status}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-700">{item.content}</p>
                        {item.handlerReply && (
                          <p className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                            处理备注：{item.handlerReply}
                          </p>
                        )}
                        <div className="mt-2 text-xs text-slate-400">
                          {item.category || '未分类'} · {item.createdAt || '刚刚'}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <button
                          type="button"
                          onClick={() => updateStatus(item.id, 'acknowledged')}
                          disabled={item.status === 'acknowledged' || item.status === 'resolved'}
                          className="h-8 rounded-md border border-slate-300 px-3 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
                        >
                          确认
                        </button>
                        <button
                          type="button"
                          onClick={() => updateStatus(item.id, 'resolved')}
                          disabled={item.status === 'resolved'}
                          className="h-8 rounded-md bg-blue-600 px-3 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                        >
                          解决
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </Layout>
  );
}
