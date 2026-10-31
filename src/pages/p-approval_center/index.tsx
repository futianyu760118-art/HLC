// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { hrmApi } from '../../utils/api';

import AppIcon from '../../components/AppIcon';
const businessTypeLabels: Record<string, string> = {
  offer: 'Offer审批',
  employee_request: '员工申请',
  probation: '转正申请',
  resignation: '离职申请',
  onboarding: '入职审批',
};

const statusLabels: Record<string, string> = {
  draft: '草稿',
  pending: '待审批',
  approved: '已通过',
  rejected: '已驳回',
  cancelled: '已撤销',
};

const statusBadgeClass = (status: string) => {
  if (status === 'approved') return 'status-badge status-active';
  if (status === 'rejected' || status === 'cancelled') return 'status-badge status-inactive';
  if (status === 'pending') return 'status-badge status-pending';
  return 'status-badge status-default';
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

export default function ApprovalCenterPage() {
  const { kind = 'my-applications' } = useParams<{ kind: string }>();
  const navigate = useNavigate();
  const [records, setRecords] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any | null>(null);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [applicantFilter, setApplicantFilter] = useState('');
  const [approverFilter, setApproverFilter] = useState('');
  const [submittedFrom, setSubmittedFrom] = useState('');
  const [submittedTo, setSubmittedTo] = useState('');
  const [comment, setComment] = useState('');
  const [actingId, setActingId] = useState<string | null>(null);

  const titleMap: Record<string, { title: string; icon: string; desc: string }> = {
    'my-applications': { title: '我的申请', icon: 'fa-inbox', desc: '查看您发起的所有审批申请，支持快速跟进、追溯查看与撤销操作' },
    pending: { title: '待我审批', icon: 'fa-user-clock', desc: '集中处理待办审批，支持快速同意/驳回与批量审批' },
    records: { title: '审批记录', icon: 'fa-history', desc: '查看历史审批操作，支持类型筛选与导出，溯源完整流程链路' },
  };

  const meta = titleMap[kind] || titleMap['my-applications'];

  useEffect(() => {
    document.title = `${meta.title} - 恒聘通HRM`;
    setSelected(null);
    loadData();
  }, [kind]);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await hrmApi.approvals(kind as any);
      setRecords(data || []);
    } catch (error: any) {
      console.error('加载审批数据失败', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (record: any, action: 'approve' | 'reject') => {
    if (!confirm(`确定${action === 'approve' ? '同意' : '驳回'}该申请？`)) return;
    setActingId(record.id);
    try {
      await hrmApi.handleApproval(record.id, action, comment || (action === 'approve' ? '同意' : '驳回'));
      setSelected(null);
      setComment('');
      await loadData();
      toast.success(action === 'approve' ? '审批通过' : '已驳回');
    } catch (error: any) {
      toast.error(error.message || '操作失败');
    } finally {
      setActingId(null);
    }
  };

  const filtered = records.filter((r) => {
    const searchable = `${r.title || r.approvalTitle || ''} ${r.applicantName || ''} ${r.approverName || ''} ${r.businessType || ''} ${r.comment || ''}`.toLowerCase();
    if (searchKeyword && !searchable.includes(searchKeyword.toLowerCase())) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    if (typeFilter && r.businessType !== typeFilter) return false;
    if (applicantFilter && r.applicantName !== applicantFilter) return false;
    if (approverFilter && r.approverName !== approverFilter) return false;
    const submittedAt = r.submittedAt || r.createdAt;
    const submittedDate = submittedAt ? new Date(submittedAt) : null;
    if (submittedFrom && (!submittedDate || submittedDate < new Date(submittedFrom))) return false;
    if (submittedTo && (!submittedDate || submittedDate > new Date(`${submittedTo}T23:59:59`))) return false;
    return true;
  });
  const applicantOptions = Array.from(new Set(records.map((r) => r.applicantName).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const approverOptions = Array.from(new Set(records.map((r) => r.approverName).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const activeFilterCount = [searchKeyword, statusFilter, typeFilter, applicantFilter, approverFilter, submittedFrom, submittedTo].filter(Boolean).length;
  const resetFilters = () => {
    setSearchKeyword('');
    setStatusFilter('');
    setTypeFilter('');
    setApplicantFilter('');
    setApproverFilter('');
    setSubmittedFrom('');
    setSubmittedTo('');
  };

  // Stats counts
  const counts = {
    total: records.length,
    pending: records.filter((r) => r.status === 'pending').length,
    approved: records.filter((r) => r.status === 'approved').length,
    rejected: records.filter((r) => r.status === 'rejected').length,
  };

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center">
              <AppIcon className={`fas ${meta.icon} text-sm`} />
            </div>
            <div>
              <h1 className="text-[15px] font-bold text-gray-900">{meta.title}</h1>
              <p className="text-xs text-gray-400 mt-0.5">{meta.desc}</p>
            </div>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: '全部', value: counts.total, icon: 'fa-list', bg: 'bg-blue-50', color: 'text-blue-500' },
            { label: '待审批', value: counts.pending, icon: 'fa-clock', bg: 'bg-orange-50', color: 'text-orange-500' },
            { label: '已通过', value: counts.approved, icon: 'fa-check-circle', bg: 'bg-green-50', color: 'text-green-500' },
            { label: '已驳回', value: counts.rejected, icon: 'fa-times-circle', bg: 'bg-red-50', color: 'text-red-500' },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs text-gray-400">{card.label}</span>
                <div className={`w-8 h-8 rounded-lg ${card.bg} ${card.color} flex items-center justify-center`}>
                  <AppIcon className={`fas ${card.icon} text-sm`} />
                </div>
              </div>
              <div className="text-2xl font-bold text-gray-900">{card.value}</div>
            </div>
          ))}
        </div>

        {/* Sub Tabs */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-2 flex items-center gap-2">
          {[
            { value: 'my-applications', label: '我的申请', icon: 'fa-inbox' },
            { value: 'pending', label: '待我审批', icon: 'fa-user-clock' },
            { value: 'records', label: '审批记录', icon: 'fa-history' },
          ].map((tab) => (
            <button
              key={tab.value}
              onClick={() => navigate(`/approval-center/${tab.value}`)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                kind === tab.value ? 'bg-blue-50 text-blue-600' : 'text-gray-500 hover:bg-gray-50'
              }`}
            >
              <AppIcon className={`fas ${tab.icon} mr-1`} />{tab.label}
            </button>
          ))}
        </div>

        {/* List + Detail */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className={`bg-white rounded-xl border border-gray-100 ${selected ? 'xl:col-span-2' : 'xl:col-span-3'}`}>
            {/* Filter Bar */}
            <div className="px-5 py-3 border-b border-gray-100 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-shrink-0">
                <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 text-xs" />
                <input
                  type="text"
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  placeholder="标题/人员/意见..."
                  className="pl-9 pr-4 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-sm w-52 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                />
              </div>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                <option value="">全部类型</option>
                {Object.entries(businessTypeLabels).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                <option value="">全部状态</option>
                {Object.entries(statusLabels).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
              <select value={applicantFilter} onChange={(e) => setApplicantFilter(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                <option value="">全部申请人</option>
                {applicantOptions.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <select value={approverFilter} onChange={(e) => setApproverFilter(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                <option value="">全部审批人</option>
                {approverOptions.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
              </button>
              <div className="flex-1" />
              <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {records.length} 条</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 max-w-xl">
                <input type="date" value={submittedFrom} onChange={(e) => setSubmittedFrom(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                <input type="date" value={submittedTo} onChange={(e) => setSubmittedTo(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
              </div>
            </div>

            {loading ? (
              <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
            ) : filtered.length === 0 ? (
              <div className="py-16 text-center">
                <AppIcon className="fas fa-inbox text-3xl text-gray-200 mb-3" />
                <div className="text-sm text-gray-400">暂无审批记录</div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full hrm-table">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">标题</th>
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">类型</th>
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">申请人</th>
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">审批人</th>
                      {kind !== 'records' && <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">提交时间</th>}
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">状态</th>
                      <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r) => (
                      <tr
                        key={r.id}
                        className={`border-b border-gray-50 hover:bg-blue-50/30 transition-colors cursor-pointer ${selected?.id === r.id ? 'bg-blue-50/40' : ''}`}
                        onClick={() => setSelected(r)}
                      >
                        <td className="px-4 py-2.5 text-[13px] font-medium text-gray-800">{r.title || r.approvalTitle || '-'}</td>
                        <td className="px-4 py-2.5 text-[13px] text-gray-500">{businessTypeLabels[r.businessType] || r.businessType || '-'}</td>
                        <td className="px-4 py-2.5 text-[13px] text-gray-500">{r.applicantName || '-'}</td>
                        <td className="px-4 py-2.5 text-[13px] text-gray-500">{r.approverName || '-'}</td>
                        {kind !== 'records' && <td className="px-4 py-2.5 text-[12px] text-gray-400">{formatDateTime(r.submittedAt || r.createdAt)}</td>}
                        <td className="px-4 py-2.5 text-center">
                          <span className={statusBadgeClass(r.status || r.action)}>
                            {statusLabels[r.status || r.action] || r.status || r.action || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right whitespace-nowrap">
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelected(r); }}
                            className="text-xs text-gray-500 hover:text-blue-600 transition-colors"
                          >
                            <AppIcon className="fas fa-eye text-[11px]" />详情
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Detail Panel */}
          {selected && (
            <div className="bg-white rounded-xl border border-gray-100 p-5">
              <div className="flex items-center justify-between mb-3 pb-3 border-b border-gray-100">
                <span className="text-sm font-bold text-gray-800">审批详情</span>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-xs">
                  <AppIcon className="fas fa-times" />
                </button>
              </div>
              <div className="space-y-3">
                <div>
                  <div className="text-xs text-gray-400 mb-1">标题</div>
                  <div className="text-[13px] text-gray-800 font-medium">{selected.title || selected.approvalTitle || '-'}</div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-gray-400 mb-1">类型</div>
                    <div className="text-[13px] text-gray-700">{businessTypeLabels[selected.businessType] || '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-1">状态</div>
                    <span className={statusBadgeClass(selected.status || selected.action)}>
                      {statusLabels[selected.status || selected.action] || selected.status || '-'}
                    </span>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-1">申请人</div>
                    <div className="text-[13px] text-gray-700">{selected.applicantName || '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-1">审批人</div>
                    <div className="text-[13px] text-gray-700">{selected.approverName || '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-1">提交时间</div>
                    <div className="text-[12px] text-gray-500">{formatDateTime(selected.submittedAt || selected.createdAt)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 mb-1">完成时间</div>
                    <div className="text-[12px] text-gray-500">{formatDateTime(selected.completedAt)}</div>
                  </div>
                </div>
                {selected.remark && (
                  <div>
                    <div className="text-xs text-gray-400 mb-1">备注</div>
                    <div className="text-[13px] text-gray-600 bg-gray-50 rounded-lg p-3">{selected.remark}</div>
                  </div>
                )}
                {selected.comment && (
                  <div>
                    <div className="text-xs text-gray-400 mb-1">审批意见</div>
                    <div className="text-[13px] text-gray-600 bg-gray-50 rounded-lg p-3">{selected.comment}</div>
                  </div>
                )}

                {/* Action Buttons for pending */}
                {kind === 'pending' && selected.status === 'pending' && (
                  <div className="pt-3 border-t border-gray-100 space-y-3">
                    <div>
                      <div className="text-xs text-gray-400 mb-1">审批意见</div>
                      <textarea
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        rows={3}
                        maxLength={500}
                        placeholder="请输入审批意见..."
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-none"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleAction(selected, 'reject')}
                        disabled={actingId === selected?.id}
                        className="flex-1 py-2 border border-red-200 text-red-500 rounded-lg text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-times mr-1" />{actingId === selected?.id ? '处理中…' : '驳回'}
                      </button>
                      <button
                        onClick={() => handleAction(selected, 'approve')}
                        disabled={actingId === selected?.id}
                        className="flex-1 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-check mr-1" />{actingId === selected?.id ? '处理中…' : '同意'}
                      </button>
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
