// @ts-nocheck
import React, { useEffect, useState, useMemo } from 'react';
import { Layout } from '../../components/Layout';
import { hrmApi } from '../../utils/api';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
const moduleLabels: Record<string, string> = {
  approval: '审批中心',
  employee: '员工管理',
  department: '部门管理',
  job: '岗位管理',
  resume: '简历管理',
  interview: '面试管理',
  candidate: '候选人',
  offer: 'Offer',
  attendance: '考勤管理',
  performance: '绩效管理',
  payroll: '薪酬管理',
  contract: '合同管理',
  training: '培训管理',
  user: '用户管理',
  system: '系统管理',
};

const actionLabels: Record<string, { label: string; color: string }> = {
  create: { label: '新增', color: 'text-green-600 bg-green-50' },
  update: { label: '更新', color: 'text-blue-600 bg-blue-50' },
  delete: { label: '删除', color: 'text-red-600 bg-red-50' },
  approve: { label: '通过', color: 'text-green-600 bg-green-50' },
  reject: { label: '驳回', color: 'text-red-600 bg-red-50' },
  login: { label: '登录', color: 'text-blue-600 bg-blue-50' },
  logout: { label: '退出', color: 'text-gray-600 bg-gray-50' },
  export: { label: '导出', color: 'text-purple-600 bg-purple-50' },
};

const formatDateTime = (val?: string) => {
  if (!val) return '-';
  try {
    const d = new Date(val.includes('Z') ? val : val + 'Z');
    return d.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
  } catch {
    return val;
  }
};

export default function OperationLogsPage() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any | null>(null);
  const [filterModule, setFilterModule] = useState('');
  const [filterAction, setFilterAction] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [filterTargetId, setFilterTargetId] = useState('');
  const [filterCreatedFrom, setFilterCreatedFrom] = useState('');
  const [filterCreatedTo, setFilterCreatedTo] = useState('');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    document.title = '操作日志 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await hrmApi.list('operation-logs');
      setLogs(data || []);
    } catch (error) {
      console.error('加载日志失败', error);
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(() => logs.filter((log) => {
    if (filterModule && log.module !== filterModule) return false;
    if (filterAction && log.action !== filterAction) return false;
    if (filterUser && !(log.userName || '').toLowerCase().includes(filterUser.toLowerCase())) return false;
    if (filterTargetId && !(log.targetId || '').toLowerCase().includes(filterTargetId.toLowerCase())) return false;
    const createdDate = log.createdAt ? new Date(log.createdAt) : null;
    if (filterCreatedFrom && (!createdDate || createdDate < new Date(filterCreatedFrom))) return false;
    if (filterCreatedTo && (!createdDate || createdDate > new Date(`${filterCreatedTo}T23:59:59`))) return false;
    if (searchKeyword) {
      const keyword = searchKeyword.toLowerCase();
      const text = `${log.userName || ''} ${log.module || ''} ${log.action || ''} ${log.targetId || ''} ${log.ip || ''}`.toLowerCase();
      if (!text.includes(keyword)) return false;
    }
    return true;
  }), [logs, filterModule, filterAction, filterUser, filterTargetId, filterCreatedFrom, filterCreatedTo, searchKeyword]);
  // 任一筛选条件变化时重置到第 1 页（避免在深层页码应用筛选后看到空列表）
  useEffect(() => { setCurrentPage(1); }, [filterModule, filterAction, filterUser, filterTargetId, filterCreatedFrom, filterCreatedTo, searchKeyword]);
  const moduleOptions = useMemo(() => Array.from(new Set(logs.map((log) => log.module).filter(Boolean))).sort(), [logs]);
  const actionOptions = useMemo(() => Array.from(new Set(logs.map((log) => log.action).filter(Boolean))).sort(), [logs]);
  const activeFilterCount = [filterModule, filterAction, filterUser, filterTargetId, filterCreatedFrom, filterCreatedTo, searchKeyword].filter(Boolean).length;
  const resetFilters = () => {
    setFilterUser('');
    setFilterModule('');
    setFilterAction('');
    setFilterTargetId('');
    setFilterCreatedFrom('');
    setFilterCreatedTo('');
    setSearchKeyword('');
  };

  const totalPages = Math.ceil(filtered.length / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const pageLogs = filtered.slice(startIndex, startIndex + pageSize);

  // CSV Export
  const handleExport = () => {
    const headers = ['操作时间', '操作人', '所属模块', '操作类型', '操作内容', 'IP地址'];
    const rows = filtered.map((log) => [
      formatDateTime(log.createdAt),
      log.userName || '-',
      moduleLabels[log.module] || log.module || '-',
      actionLabels[log.action]?.label || log.action || '-',
      log.targetId || '-',
      log.ip || '-',
    ]);
    const csv = [headers, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `操作日志_${new Date().toLocaleDateString()}.csv`;
    link.click();
  };

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-clipboard-list text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">操作日志</h1>
                <p className="text-xs text-gray-400 mt-0.5">日志查询 · 操作追踪 · 导出 · 变更对比</p>
              </div>
            </div>
            <button onClick={handleExport} className="px-3.5 py-[6px] bg-gray-800 text-white rounded-lg text-xs font-medium hover:bg-gray-900 transition-colors">
              <AppIcon className="fas fa-download mr-1" />导出CSV
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={searchKeyword} onChange={setSearchKeyword} placeholder="人/模块/对象/IP..." className="w-60" />
          <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
          </button>
          <div className="flex-1" />
          <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {logs.length} 条</span>
          </div>
          <div className="hpt-filter-surface p-3">
            <div className="hpt-filter-grid">
              <FilterField label="操作人" type="text" value={filterUser} onChange={setFilterUser} placeholder="输入操作人" />
              <FilterField label="对象ID" type="text" value={filterTargetId} onChange={setFilterTargetId} placeholder="输入对象ID" />
              <FilterField label="所属模块" type="combo" value={filterModule} onChange={setFilterModule} options={toFilterOptions(moduleOptions.map((value) => ({ value, label: moduleLabels[value] || value })))} />
              <FilterField label="操作类型" type="combo" value={filterAction} onChange={setFilterAction} options={toFilterOptions(actionOptions.map((value) => ({ value, label: actionLabels[value]?.label || value })))} />
              <FilterField label="操作时间" type="date-range" value={{ from: filterCreatedFrom, to: filterCreatedTo }} onChange={(next) => { setFilterCreatedFrom(next.from || ''); setFilterCreatedTo(next.to || ''); }} />
            </div>
          </div>
        </div>

        {/* Table + Detail */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className={`bg-white rounded-xl border border-gray-100 ${selected ? 'xl:col-span-2' : 'xl:col-span-3'}`}>
            {loading ? (
              <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
            ) : pageLogs.length === 0 ? (
              <div className="py-16 text-center">
                <AppIcon className="fas fa-folder-open text-3xl text-gray-200 mb-3" />
                <div className="text-sm text-gray-400">暂无操作日志</div>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full hrm-table">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作时间</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作人</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">所属模块</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作类型</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">影响对象</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">IP 地址</th>
                        <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageLogs.map((log) => {
                        const actionMeta = actionLabels[log.action] || { label: log.action, color: 'text-gray-600 bg-gray-50' };
                        return (
                          <tr key={log.id} className={`border-b border-gray-50 hover:bg-blue-50/30 transition-colors cursor-pointer ${selected?.id === log.id ? 'bg-blue-50/40' : ''}`} onClick={() => setSelected(log)}>
                            <td className="px-4 py-2.5 text-[12px] text-gray-500">{formatDateTime(log.createdAt)}</td>
                            <td className="px-4 py-2.5 text-[13px] text-gray-700">{log.userName || '-'}</td>
                            <td className="px-4 py-2.5 text-[13px] text-gray-500">{moduleLabels[log.module] || log.module || '-'}</td>
                            <td className="px-4 py-2.5">
                              <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium ${actionMeta.color}`}>{actionMeta.label}</span>
                            </td>
                            <td className="px-4 py-2.5 text-[12px] text-gray-500 max-w-[140px] truncate" title={log.targetId}>{log.targetId || '-'}</td>
                            <td className="px-4 py-2.5 text-[12px] text-gray-400">{log.ip || '-'}</td>
                            <td className="px-4 py-2.5 text-right">
                              <button onClick={(e) => { e.stopPropagation(); setSelected(log); }} className="text-xs text-blue-500 hover:text-blue-700">
                                <AppIcon className="fas fa-eye text-[11px]" />详情
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {/* Pagination */}
                <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <span>每页</span>
                    <select value={pageSize} onChange={(e) => { setPageSize(parseInt(e.target.value)); setCurrentPage(1); }} className="border border-gray-200 rounded px-1.5 py-0.5 text-xs">
                      <option value="20">20</option><option value="50">50</option><option value="100">100</option>
                    </select>
                    <span>条，共 {filtered.length} 条</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setCurrentPage(currentPage - 1)} disabled={currentPage === 1} className="w-7 h-7 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 text-xs">
                      <AppIcon className="fas fa-chevron-left text-[10px]" />
                    </button>
                    <span className="px-3 text-xs text-gray-500">{currentPage} / {totalPages || 1}</span>
                    <button onClick={() => setCurrentPage(currentPage + 1)} disabled={currentPage >= totalPages} className="w-7 h-7 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 text-xs">
                      <AppIcon className="fas fa-chevron-right text-[10px]" />
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Detail Panel */}
          {selected && (
            <div className="bg-white rounded-xl border border-gray-100 p-5">
              <div className="flex items-center justify-between mb-3 pb-3 border-b border-gray-100">
                <span className="text-sm font-bold text-gray-800">变更详情</span>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-xs"><AppIcon className="fas fa-times" /></button>
              </div>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 text-[12px]">
                  <div><span className="text-gray-400">操作人：</span><span className="text-gray-700 font-medium">{selected.userName || '-'}</span></div>
                  <div><span className="text-gray-400">操作时间：</span><span className="text-gray-700">{formatDateTime(selected.createdAt)}</span></div>
                  <div><span className="text-gray-400">所属模块：</span><span className="text-gray-700">{moduleLabels[selected.module] || selected.module}</span></div>
                  <div><span className="text-gray-400">操作类型：</span>
                    {(() => {
                      const am = actionLabels[selected.action] || { label: selected.action, color: 'text-gray-600 bg-gray-50' };
                      return <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium ${am.color}`}>{am.label}</span>;
                    })()}
                  </div>
                  <div><span className="text-gray-400">对象ID：</span><span className="text-gray-700 break-all">{selected.targetId || '-'}</span></div>
                  <div><span className="text-gray-400">IP 地址：</span><span className="text-gray-700">{selected.ip || '-'}</span></div>
                </div>
                {selected.detail && Object.keys(selected.detail).length > 0 && (
                  <div>
                    <div className="text-xs text-gray-400 mb-2">变更详情</div>
                    <div className="bg-gray-50 rounded-lg p-3 text-[12px] text-gray-700 font-mono whitespace-pre-wrap overflow-x-auto">
                      {JSON.stringify(selected.detail, null, 2)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
