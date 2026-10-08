// @ts-nocheck
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { hrmApi } from '../../utils/api';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
const formatMoney = (val: any) => {
  const num = parseFloat(val);
  if (isNaN(num) || !num) return '-';
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export default function SalaryProfilesPage() {
  const [profiles, setProfiles] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterEmployee, setFilterEmployee] = useState('');
  const [filterCurrency, setFilterCurrency] = useState('');
  const [filterMinTotal, setFilterMinTotal] = useState('');
  const [filterMaxTotal, setFilterMaxTotal] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});

  useEffect(() => {
    document.title = '薪资档案 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [profilesData, employeesData] = await Promise.all([
        hrmApi.list('salary-profiles'),
        hrmApi.list('employees'),
      ]);
      setProfiles(profilesData || []);
      setEmployees(employeesData || []);
    } catch (error) {
      console.error('加载薪资档案失败', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!form.employeeId) {
      toast.info('请选择员工');
      return;
    }
    if (form.baseSalary === '' || form.baseSalary === undefined || Number(form.baseSalary) <= 0) {
      toast.error('基本工资须大于 0');
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await hrmApi.update('salary-profiles', editing.id, form);
      } else {
        await hrmApi.create('salary-profiles', form);
      }
      toast.success('已保存');
      setShowModal(false);
      setEditing(null);
      setForm({});
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (record?: any) => {
    if (record) {
      setEditing(record);
      setForm({
        employeeId: record.employeeId,
        baseSalary: record.baseSalary || '',
        positionSalary: record.positionSalary || '',
        performanceSalary: record.performanceSalary || '',
        bonus: record.bonus || '',
        allowance: record.allowance || '',
        deduction: record.deduction || '',
        currency: record.currency || 'CNY',
        status: record.status || 'active',
        remark: record.remark || '',
      });
    } else {
      setEditing(null);
      setForm({ currency: 'CNY', status: 'active' });
    }
    setShowModal(true);
  };

  const handleDelete = async (record: any) => {
    if (!confirm(`确定删除 ${record.employeeName} 的薪资档案？`)) return;
    try {
      await hrmApi.remove('salary-profiles', record.id);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '删除失败');
    }
  };

  const filtered = profiles.filter((p) => {
    if (filterStatus && p.status !== filterStatus) return false;
    if (filterEmployee && p.employeeId !== filterEmployee) return false;
    if (filterCurrency && p.currency !== filterCurrency) return false;
    const total = Number(p.totalSalary);
    if (filterMinTotal && (Number.isNaN(total) || total < Number(filterMinTotal))) return false;
    if (filterMaxTotal && (Number.isNaN(total) || total > Number(filterMaxTotal))) return false;
    if (searchKeyword) {
      const text = `${p.employeeName || ''} ${p.currency || ''} ${p.remark || ''}`.toLowerCase();
      if (!text.includes(searchKeyword.toLowerCase())) return false;
    }
    return true;
  });
  const currencyOptions = Array.from(new Set(profiles.map((p) => p.currency).filter(Boolean))).sort();
  const activeFilterCount = [searchKeyword, filterStatus, filterEmployee, filterCurrency, filterMinTotal, filterMaxTotal].filter(Boolean).length;
  const resetFilters = () => {
    setSearchKeyword('');
    setFilterStatus('');
    setFilterEmployee('');
    setFilterCurrency('');
    setFilterMinTotal('');
    setFilterMaxTotal('');
  };

  // Stats
  const totalProfiles = profiles.length;
  const activeProfiles = profiles.filter((p) => p.status === 'active').length;
  const totalCost = profiles
    .filter((p) => p.status === 'active')
    .reduce((sum, p) => sum + (parseFloat(p.totalSalary) || 0), 0);
  const avgSalary = activeProfiles > 0 ? totalCost / activeProfiles : 0;

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-wallet text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">薪资档案</h1>
                <p className="text-xs text-gray-400 mt-0.5">集中维护薪资结构、历史变更可追溯</p>
              </div>
            </div>
            <button onClick={() => openEdit()} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
              <AppIcon className="fas fa-plus mr-1" />新建薪资档案
            </button>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: '档案总数', value: totalProfiles, icon: 'fa-id-card', bg: 'bg-blue-50', color: 'text-blue-500' },
            { label: '生效档案', value: activeProfiles, icon: 'fa-check-circle', bg: 'bg-green-50', color: 'text-green-500' },
            { label: '总人力成本', value: `¥${totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`, icon: 'fa-money-bill-wave', bg: 'bg-orange-50', color: 'text-orange-500' },
            { label: '平均薪资', value: `¥${avgSalary.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`, icon: 'fa-chart-line', bg: 'bg-purple-50', color: 'text-purple-500' },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs text-gray-400">{card.label}</span>
                <div className={`w-8 h-8 rounded-lg ${card.bg} ${card.color} flex items-center justify-center`}>
                  <AppIcon className={`fas ${card.icon} text-sm`} />
                </div>
              </div>
              <div className="text-xl font-bold text-gray-900">{card.value}</div>
            </div>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-3 border-b border-gray-100 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={searchKeyword} onChange={setSearchKeyword} placeholder="员工/币种/备注..." className="w-56" />
            <div className="flex items-center bg-gray-50 rounded-lg p-0.5">
              {[
                { label: '全部', value: '' },
                { label: '生效', value: 'active' },
                { label: '停用', value: 'inactive' },
              ].map((tab) => (
                <button key={tab.value} onClick={() => setFilterStatus(tab.value)} className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${filterStatus === tab.value ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                  {tab.label}
                </button>
              ))}
            </div>
            <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
            </button>
            <div className="flex-1" />
            <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {profiles.length} 条</span>
            </div>
            <div className="hpt-filter-surface p-3">
              <div className="hpt-filter-grid">
                <FilterField label="员工" type="combo" value={filterEmployee} onChange={setFilterEmployee} options={toFilterOptions(employees.map((employee: any) => ({ label: employee.name, value: employee.id })))} />
                <FilterField label="币种" type="select" value={filterCurrency} onChange={setFilterCurrency} options={toFilterOptions(currencyOptions)} />
                <FilterField label="薪资合计" type="number-range" value={{ from: filterMinTotal, to: filterMaxTotal }} onChange={(next) => { setFilterMinTotal(next.from || ''); setFilterMaxTotal(next.to || ''); }} />
              </div>
            </div>
          </div>

          {loading ? (
            <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
          ) : filtered.length === 0 ? (
            <div className="py-16 text-center text-gray-400 text-sm">暂无薪资档案</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full hrm-table">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">员工</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">基本工资</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">岗位工资</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">绩效工资</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">奖金</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">补贴</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">扣款</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">合计</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">状态</th>
                    <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p) => (
                    <tr key={p.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                      <td className="px-4 py-2.5 text-[13px] font-medium text-gray-800">{p.employeeName || '-'}</td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-600 text-right">{formatMoney(p.baseSalary)}</td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-600 text-right">{formatMoney(p.positionSalary)}</td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-600 text-right">{formatMoney(p.performanceSalary)}</td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-600 text-right">{formatMoney(p.bonus)}</td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-600 text-right">{formatMoney(p.allowance)}</td>
                      <td className="px-4 py-2.5 text-[12px] text-red-500 text-right">{p.deduction ? `-${formatMoney(p.deduction)}` : '-'}</td>
                      <td className="px-4 py-2.5 text-[13px] font-bold text-blue-600 text-right">{formatMoney(p.totalSalary)}</td>
                      <td className="px-4 py-2.5 text-center">
                        <span className={`status-badge ${p.status === 'active' ? 'status-active' : 'status-inactive'}`}>
                          {p.status === 'active' ? '生效' : '停用'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        <button onClick={() => openEdit(p)} className="text-xs text-blue-500 hover:text-blue-700 mr-2">
                          <AppIcon className="fas fa-edit text-[11px]" />编辑
                        </button>
                        <button onClick={() => handleDelete(p)} className="text-xs text-red-400 hover:text-red-600">
                          <AppIcon className="fas fa-trash text-[11px]" />删除
                        </button>
                      </td>
                    </tr>
                  ))}
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
              <h2 className="text-base font-bold text-gray-800">{editing ? '编辑薪资档案' : '新建薪资档案'}</h2>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-gray-600"><AppIcon className="fas fa-times" /></button>
            </div>
            <div className="p-5 grid grid-cols-2 gap-4">
              <label className="col-span-2">
                <span className="block text-xs text-gray-500 mb-1">员工 <span className="text-red-500">*</span></span>
                <select value={form.employeeId || ''} onChange={(e) => setForm({ ...form, employeeId: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" disabled={!!editing}>
                  <option value="">请选择员工</option>
                  {employees.map((e: any) => <option key={e.id} value={e.id}>{e.name} ({e.employeeNo})</option>)}
                </select>
              </label>
              {[
                { name: 'baseSalary', label: '基本工资' },
                { name: 'positionSalary', label: '岗位工资' },
                { name: 'performanceSalary', label: '绩效工资' },
                { name: 'bonus', label: '奖金' },
                { name: 'allowance', label: '补贴' },
                { name: 'deduction', label: '扣款' },
              ].map((f) => (
                <label key={f.name}>
                  <span className="block text-xs text-gray-500 mb-1">{f.label}</span>
                  <input type="number" min={0} step="0.01" value={form[f.name] || ''} onChange={(e) => setForm({ ...form, [f.name]: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="0.00" />
                </label>
              ))}
              <label>
                <span className="block text-xs text-gray-500 mb-1">币种</span>
                <select value={form.currency || 'CNY'} onChange={(e) => setForm({ ...form, currency: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  <option value="CNY">人民币 (CNY)</option>
                  <option value="USD">美元 (USD)</option>
                  <option value="HKD">港币 (HKD)</option>
                </select>
              </label>
              <label>
                <span className="block text-xs text-gray-500 mb-1">状态</span>
                <select value={form.status || 'active'} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  <option value="active">生效</option>
                  <option value="inactive">停用</option>
                </select>
              </label>
              <label className="col-span-2">
                <span className="block text-xs text-gray-500 mb-1">备注</span>
                <textarea value={form.remark || ''} onChange={(e) => setForm({ ...form, remark: e.target.value })} rows={3} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-none" />
              </label>
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
              <button onClick={() => setShowModal(false)} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50">取消</button>
              <button onClick={handleSave} disabled={saving} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50">{saving ? '保存中…' : '保存'}</button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
