import { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import { extensionApi } from '../../utils/api';

interface Department {
  departmentId: string;
  departmentName: string;
  plan: number;
  actual: number;
  vacancy: number;
  usageRate: number;
  status: 'unplanned' | 'over' | 'under' | 'full';
  parentName?: string | null;
}

interface Summary {
  totalPlan: number;
  totalActual: number;
  totalVacancy: number;
  usageRate: number;
}

const statusColors = {
  unplanned: 'bg-slate-100 text-slate-600',
  over: 'bg-rose-50 text-rose-700',
  under: 'bg-amber-50 text-amber-700',
  full: 'bg-emerald-50 text-emerald-700',
};

const statusLabels = {
  unplanned: '未设置',
  over: '超编',
  under: '缺编',
  full: '满编',
};

function MetricCard({ icon, label, value, color = 'blue' }: {
  icon: string;
  label: string;
  value: number | string;
  color?: string;
}) {
  const colorClasses: Record<string, { bg: string; text: string }> = {
    blue: { bg: 'bg-blue-50', text: 'text-blue-600' },
    emerald: { bg: 'bg-emerald-50', text: 'text-emerald-600' },
    amber: { bg: 'bg-amber-50', text: 'text-amber-600' },
  };

  const colors = colorClasses[color] || colorClasses.blue;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs text-slate-500">{label}</div>
          <div className="mt-2 text-2xl font-bold text-slate-900">{value}</div>
        </div>
        <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${colors.bg} ${colors.text}`}>
          <AppIcon className={`fas ${icon} text-lg`} />
        </div>
      </div>
    </div>
  );
}

export default function HeadcountManagementPage() {
  const [summary, setSummary] = useState<Summary>({
    totalPlan: 0,
    totalActual: 0,
    totalVacancy: 0,
    usageRate: 0,
  });
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingDept, setEditingDept] = useState<Department | null>(null);
  const [editValue, setEditValue] = useState('');

  useEffect(() => {
    document.title = '编制管理 - 恒聘通';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await extensionApi.headcountSummary();
      setSummary(data.summary);
      setDepartments(data.departments);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '编制数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleEditHeadcount = (dept: Department) => {
    setEditingDept(dept);
    setEditValue(String(dept.plan));
  };

  const handleSaveHeadcount = async () => {
    if (!editingDept) return;

    try {
      const plan = Number.parseInt(editValue, 10);
      if (Number.isNaN(plan) || plan < 0) {
        alert('请输入有效的编制人数');
        return;
      }
      await extensionApi.updateHeadcountPlan(editingDept.departmentId, { plan });

      setEditingDept(null);
      await loadData();
    } catch (error) {
      setError(error instanceof Error ? error.message : '更新失败');
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex h-64 items-center justify-center text-blue-500">
          <AppIcon className="fas fa-spinner fa-spin text-xl" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* 页面头部 */}
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <AppIcon className="fas fa-users text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">编制管理</h1>
                <p className="mt-1 text-xs text-slate-500">管理部门和岗位编制，跟踪使用情况</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => { void loadData(); }}
              aria-label="刷新编制数据"
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <AppIcon className="fas fa-sync-alt mr-2" />
              刷新
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            <span><AppIcon className="fas fa-circle-exclamation mr-2" />{error}</span>
            <button type="button" onClick={() => { void loadData(); }} className="font-medium underline">重试</button>
          </div>
        )}

        {/* 编制汇总卡片 */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <MetricCard
            icon="fa-users"
            label="编制总数"
            value={summary.totalPlan}
            color="blue"
          />
          <MetricCard
            icon="fa-user-check"
            label="实际人数"
            value={summary.totalActual}
            color="emerald"
          />
          <MetricCard
            icon="fa-user-plus"
            label="空缺人数"
            value={summary.totalVacancy}
            color="amber"
          />
          <MetricCard
            icon="fa-chart-pie"
            label="编制使用率"
            value={`${summary.usageRate}%`}
            color="blue"
          />
        </div>

        {/* 部门编制列表 */}
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-5 py-4">
            <h2 className="font-semibold text-slate-900">部门编制详情</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">部门</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">编制人数</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">实际人数</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">空缺</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">使用率</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">状态</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-slate-500">操作</th>
                </tr>
              </thead>
              <tbody>
                {departments.map(dept => (
                  <tr key={dept.departmentId} className="border-b border-slate-50 hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <div className="text-sm font-medium text-slate-900">{dept.departmentName}</div>
                      {dept.parentName && (
                        <div className="text-xs text-slate-500">{dept.parentName}</div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-slate-700">{dept.plan}</td>
                    <td className="px-4 py-2.5 text-sm text-slate-700">{dept.actual}</td>
                    <td className="px-4 py-2.5 text-sm">
                      <span className={dept.vacancy > 0 ? 'text-amber-600' : 'text-slate-700'}>
                        {dept.vacancy}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={`h-full ${dept.usageRate > 100 ? 'bg-rose-500' : 'bg-blue-600'}`}
                            style={{ width: `${Math.min(dept.usageRate, 100)}%` }}
                          />
                        </div>
                        <span className="text-xs text-slate-700">{dept.usageRate}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${statusColors[dept.status]}`}>
                        {statusLabels[dept.status]}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => handleEditHeadcount(dept)}
                        aria-label={`设置${dept.departmentName}编制`}
                        className="text-sm text-blue-600 hover:text-blue-700"
                      >
                        设置编制
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 编辑对话框 */}
        {editingDept && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
            <div className="w-full max-w-md rounded-lg bg-white p-6">
              <h3 className="text-lg font-semibold text-slate-900">设置编制 - {editingDept.departmentName}</h3>
              <div className="mt-4">
                <label className="block text-sm font-medium text-slate-700">编制人数</label>
                <input
                  type="number"
                  aria-label="编制人数"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  min="0"
                />
                <div className="mt-2 text-xs text-slate-500">
                  当前实际人数: {editingDept.actual} 人
                </div>
              </div>
              <div className="mt-6 flex gap-3">
                <button
                  type="button"
                  onClick={handleSaveHeadcount}
                  className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  保存
                </button>
                <button
                  type="button"
                  onClick={() => setEditingDept(null)}
                  className="flex-1 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
