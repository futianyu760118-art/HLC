// @ts-nocheck
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { hrmApi } from '../../utils/api';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
const requestTypes = [
  { value: '', label: '全部', icon: 'fa-list' },
  { value: 'leave', label: '请假', icon: 'fa-calendar-minus', color: 'text-blue-500 bg-blue-50' },
  { value: 'overtime', label: '加班', icon: 'fa-clock', color: 'text-orange-500 bg-orange-50' },
  { value: 'travel', label: '出差', icon: 'fa-plane', color: 'text-cyan-500 bg-cyan-50' },
  { value: 'makeup_card', label: '补卡', icon: 'fa-id-badge', color: 'text-purple-500 bg-purple-50' },
];

const statusLabels: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'status-default' },
  pending: { label: '待审批', color: 'status-pending' },
  approved: { label: '已通过', color: 'status-active' },
  rejected: { label: '已驳回', color: 'status-inactive' },
  cancelled: { label: '已撤销', color: 'status-inactive' },
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

export default function EmployeeRequestsPage() {
  const [records, setRecords] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterEmployee, setFilterEmployee] = useState('');
  const [filterStartFrom, setFilterStartFrom] = useState('');
  const [filterStartTo, setFilterStartTo] = useState('');
  const [filterMinHours, setFilterMinHours] = useState('');
  const [filterMaxHours, setFilterMaxHours] = useState('');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({ requestType: 'leave', status: 'draft' });

  useEffect(() => {
    document.title = '请假/加班/出差/补卡 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [reqs, emps] = await Promise.all([
        hrmApi.list('employee-requests'),
        hrmApi.list('employees'),
      ]);
      setRecords(reqs || []);
      setEmployees(emps || []);
    } catch (error) {
      console.error('加载申请数据失败', error);
    } finally {
      setLoading(false);
    }
  };

  const openCreate = () => {
    setEditing(null);
    setForm({ requestType: 'leave', status: 'draft' });
    setShowModal(true);
  };

  const openEdit = (record: any) => {
    setEditing(record);
    setForm({
      employeeId: record.employeeId,
      requestType: record.requestType || 'leave',
      title: record.title || '',
      startTime: record.startTime ? String(record.startTime).slice(0, 16) : '',
      endTime: record.endTime ? String(record.endTime).slice(0, 16) : '',
      durationHours: record.durationHours || '',
      reason: record.reason || '',
      status: record.status || 'draft',
    });
    setShowModal(true);
  };

  const handleSave = async (forcedStatus?: string) => {
    if (!form.employeeId) {
      toast.info('请选择员工');
      return;
    }
    if (!form.requestType) {
      toast.info('请选择申请类型');
      return;
    }
    // 提交申请时校验时间区间
    const status = forcedStatus || form.status || 'draft';
    if (status === 'pending') {
      if (!form.startTime || !form.endTime) {
        toast.error('请填写起止时间');
        return;
      }
      if (new Date(form.endTime) <= new Date(form.startTime)) {
        toast.error('结束时间须晚于开始时间');
        return;
      }
    }
    setSaving(true);
    try {
      const payload = { ...form, status };
      if (editing) {
        await hrmApi.update('employee-requests', editing.id, payload);
      } else {
        await hrmApi.create('employee-requests', payload);
      }
      toast.success(status === 'pending' ? '已提交审批' : '已保存草稿');
      setShowModal(false);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async (record: any) => {
    try {
      await hrmApi.postAction(`employee-requests/${record.id}/submit`);
      await loadData();
      toast.info('已提交审批');
    } catch (error: any) {
      toast.error(error.message || '提交失败');
    }
  };

  const handleCancel = async (record: any) => {
    if (!confirm('确定撤销这条申请？')) return;
    try {
      await hrmApi.postAction(`employee-requests/${record.id}/cancel`);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '撤销失败');
    }
  };

  const handleDelete = async (record: any) => {
    if (!confirm('确定删除这条申请？')) return;
    try {
      await hrmApi.remove('employee-requests', record.id);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '删除失败');
    }
  };

  const filtered = records.filter((r) => {
    if (filterType && r.requestType !== filterType) return false;
    if (filterStatus && r.status !== filterStatus) return false;
    if (filterEmployee && r.employeeId !== filterEmployee) return false;
    const startDate = r.startTime ? new Date(r.startTime) : null;
    if (filterStartFrom && (!startDate || startDate < new Date(filterStartFrom))) return false;
    if (filterStartTo && (!startDate || startDate > new Date(`${filterStartTo}T23:59:59`))) return false;
    const hours = Number(r.durationHours);
    if (filterMinHours && (Number.isNaN(hours) || hours < Number(filterMinHours))) return false;
    if (filterMaxHours && (Number.isNaN(hours) || hours > Number(filterMaxHours))) return false;
    if (searchKeyword) {
      const text = `${r.employeeName || ''} ${r.title || ''} ${r.reason || ''}`.toLowerCase();
      if (!text.includes(searchKeyword.toLowerCase())) return false;
    }
    return true;
  });
  const activeFilterCount = [filterType, filterStatus, filterEmployee, filterStartFrom, filterStartTo, filterMinHours, filterMaxHours, searchKeyword].filter(Boolean).length;
  const resetFilters = () => {
    setFilterType('');
    setFilterStatus('');
    setFilterEmployee('');
    setFilterStartFrom('');
    setFilterStartTo('');
    setFilterMinHours('');
    setFilterMaxHours('');
    setSearchKeyword('');
  };

  // Stats per type
  const typeCounts = requestTypes.slice(1).map((t) => ({
    ...t,
    count: records.filter((r) => r.requestType === t.value).length,
  }));

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-calendar-plus text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">请假/加班/出差/补卡</h1>
                <p className="text-xs text-gray-400 mt-0.5">统一申请入口，支持多类型切换、时长计算、附件上传与草稿/提交/撤销状态</p>
              </div>
            </div>
            <button onClick={openCreate} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
              <AppIcon className="fas fa-plus mr-1" />新建申请
            </button>
          </div>
        </div>

        {/* Type Stat Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {typeCounts.map((t) => (
            <div key={t.value} onClick={() => setFilterType(filterType === t.value ? '' : t.value)} className={`bg-white rounded-xl border p-4 cursor-pointer transition-all ${filterType === t.value ? 'border-blue-300 shadow-md' : 'border-gray-100 hover:border-gray-200'}`}>
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs text-gray-400">{t.label}</span>
                <div className={`w-8 h-8 rounded-lg ${t.color} flex items-center justify-center`}>
                  <AppIcon className={`fas ${t.icon} text-sm`} />
                </div>
              </div>
              <div className="text-2xl font-bold text-gray-900">{t.count}</div>
            </div>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-3 border-b border-gray-100 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={searchKeyword} onChange={setSearchKeyword} placeholder="搜索员工/标题/原因..." className="w-60" />
            <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
            </button>
            <div className="flex-1" />
            <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {records.length} 条</span>
            </div>
            <div className="hpt-filter-surface p-3">
              <div className="hpt-filter-grid">
                <FilterField label="员工" type="combo" value={filterEmployee} onChange={setFilterEmployee} options={toFilterOptions(employees.map((employee: any) => ({ label: employee.name, value: employee.id })))} />
                <FilterField label="申请类型" type="segment" value={filterType} onChange={setFilterType} options={toFilterOptions(requestTypes.slice(1))} />
                <FilterField label="状态" type="select" value={filterStatus} onChange={setFilterStatus} options={toFilterOptions(Object.entries(statusLabels).map(([value, item]) => ({ value, label: item.label })))} />
                <FilterField label="开始日期" type="date-range" value={{ from: filterStartFrom, to: filterStartTo }} onChange={(next) => { setFilterStartFrom(next.from || ''); setFilterStartTo(next.to || ''); }} />
                <FilterField label="时长" type="number-range" value={{ from: filterMinHours, to: filterMaxHours }} onChange={(next) => { setFilterMinHours(next.from || ''); setFilterMaxHours(next.to || ''); }} />
              </div>
            </div>
          </div>

          {loading ? (
            <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
          ) : filtered.length === 0 ? (
            <div className="py-16 text-center">
              <AppIcon className="fas fa-calendar-times text-3xl text-gray-200 mb-3" />
              <div className="text-sm text-gray-400">暂无申请记录</div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full hrm-table">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">申请人</th>
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">类型</th>
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">标题</th>
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">时间范围</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">时长</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">状态</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => {
                    const typeMeta = requestTypes.find((t) => t.value === r.requestType);
                    const statusMeta = statusLabels[r.status] || statusLabels.draft;
                    return (
                      <tr key={r.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                        <td className="px-4 py-2.5 text-[13px] font-medium text-gray-800">{r.employeeName || '-'}</td>
                        <td className="px-4 py-2.5">
                          {typeMeta && (
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${typeMeta.color}`}>
                              <AppIcon className={`fas ${typeMeta.icon} text-[9px]`} />{typeMeta.label}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-[13px] text-gray-600 max-w-[200px] truncate" title={r.title}>{r.title || '-'}</td>
                        <td className="px-4 py-2.5 text-[12px] text-gray-500">
                          <div>{formatDateTime(r.startTime)}</div>
                          <div className="text-[11px] text-gray-400">至 {formatDateTime(r.endTime)}</div>
                        </td>
                        <td className="px-4 py-2.5 text-center text-[13px] font-medium text-blue-600">
                          {r.durationHours ? `${r.durationHours}h` : '-'}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          <span className={`status-badge ${statusMeta.color}`}>{statusMeta.label}</span>
                        </td>
                        <td className="px-4 py-2.5 text-right whitespace-nowrap">
                          {r.status === 'draft' && (
                            <button onClick={() => handleSubmit(r)} className="text-xs text-indigo-500 hover:text-indigo-700 mr-2">
                              <AppIcon className="fas fa-paper-plane text-[11px]" />提交
                            </button>
                          )}
                          {(r.status === 'draft' || r.status === 'pending') && (
                            <button onClick={() => handleCancel(r)} className="text-xs text-gray-500 hover:text-gray-700 mr-2">
                              <AppIcon className="fas fa-undo text-[11px]" />撤销
                            </button>
                          )}
                          {r.status === 'draft' && (
                            <button onClick={() => openEdit(r)} className="text-xs text-blue-500 hover:text-blue-700 mr-2">
                              <AppIcon className="fas fa-edit text-[11px]" />编辑
                            </button>
                          )}
                          {r.status === 'draft' && (
                            <button onClick={() => handleDelete(r)} className="text-xs text-red-400 hover:text-red-600">
                              <AppIcon className="fas fa-trash text-[11px]" />删除
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-base font-bold text-gray-800">{editing ? '编辑申请' : '新建申请'}</h2>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-gray-600"><AppIcon className="fas fa-times" /></button>
            </div>
            <div className="p-5 space-y-4">
              {/* Type Selector */}
              <div>
                <span className="block text-xs text-gray-500 mb-2">申请类型 <span className="text-red-500">*</span></span>
                <div className="grid grid-cols-4 gap-2">
                  {requestTypes.slice(1).map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      onClick={() => setForm({ ...form, requestType: t.value })}
                      className={`py-2 px-3 rounded-lg text-sm transition-all border ${form.requestType === t.value ? 'border-blue-500 bg-blue-50 text-blue-600 font-medium' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                    >
                      <AppIcon className={`fas ${t.icon} mr-1`} />{t.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">员工 <span className="text-red-500">*</span></span>
                  <select value={form.employeeId || ''} onChange={(e) => setForm({ ...form, employeeId: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                    <option value="">请选择员工</option>
                    {employees.map((e: any) => <option key={e.id} value={e.id}>{e.name} ({e.employeeNo})</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">标题</span>
                  <input type="text" value={form.title || ''} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="如：年假" />
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">开始时间</span>
                  <input type="datetime-local" value={form.startTime || ''} onChange={(e) => setForm({ ...form, startTime: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">结束时间</span>
                  <input type="datetime-local" value={form.endTime || ''} onChange={(e) => setForm({ ...form, endTime: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">时长（小时）</span>
                  <input type="number" min={0} step="0.5" value={form.durationHours || ''} onChange={(e) => setForm({ ...form, durationHours: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="0" />
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">状态</span>
                  <select value={form.status || 'draft'} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                    <option value="draft">草稿</option>
                    <option value="pending">待审批</option>
                  </select>
                </label>
              </div>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">申请原因</span>
                <textarea value={form.reason || ''} onChange={(e) => setForm({ ...form, reason: e.target.value })} rows={3} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-none" placeholder="请简要描述申请原因..." />
              </label>
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
              <button onClick={() => setShowModal(false)} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50">取消</button>
              <button onClick={() => handleSave('draft')} disabled={saving} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50">存为草稿</button>
              <button onClick={() => handleSave('pending')} disabled={saving} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50">{saving ? '提交中…' : '提交申请'}</button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
