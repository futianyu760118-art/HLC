// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 问题反馈管理页面。
 * - 普通用户：查看自己提交的反馈
 * - 管理员（admin/hr_admin/manager）：查看所有反馈，可处理、回复、变更状态
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AttachmentPreview from '../../components/AttachmentPreview';
import { ProtectedImage } from '../../components/ProtectedFile';

import AppIcon from '../../components/AppIcon';
const typeMap: Record<string, { label: string; icon: string; color: string; resolvedLabel: string }> = {
  bug: { label: '缺陷', icon: 'fa-bug', color: 'bg-red-50 text-red-600 border-red-200', resolvedLabel: '已修复' },
  feature: { label: '需求', icon: 'fa-lightbulb', color: 'bg-amber-50 text-amber-600 border-amber-200', resolvedLabel: '已采纳' },
  other: { label: '其他', icon: 'fa-comment-dots', color: 'bg-blue-50 text-blue-600 border-blue-200', resolvedLabel: '已处理' },
};

const severityMap: Record<string, { label: string; color: string }> = {
  low: { label: '低', color: 'text-gray-500 bg-gray-50' },
  medium: { label: '中', color: 'text-amber-600 bg-amber-50' },
  high: { label: '高', color: 'text-orange-600 bg-orange-50' },
  critical: { label: '紧急', color: 'text-red-600 bg-red-50' },
};

const statusMap: Record<string, { label: string; color: string; icon: string }> = {
  pending: { label: '待处理', color: 'bg-gray-100 text-gray-700', icon: 'fa-clock' },
  in_progress: { label: '处理中', color: 'bg-blue-50 text-blue-600', icon: 'fa-spinner' },
  resolved: { label: '已解决', color: 'bg-green-50 text-green-600', icon: 'fa-check-circle' },
  closed: { label: '已关闭', color: 'bg-gray-50 text-gray-500', icon: 'fa-times-circle' },
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

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const fileIconMap: Record<string, string> = {
  pdf: 'fa-file-pdf', doc: 'fa-file-word', docx: 'fa-file-word',
  xls: 'fa-file-excel', xlsx: 'fa-file-excel',
  ppt: 'fa-file-powerpoint', pptx: 'fa-file-powerpoint',
  txt: 'fa-file-alt', csv: 'fa-file-csv', zip: 'fa-file-archive',
  json: 'fa-file-code', md: 'fa-file-alt', log: 'fa-file-alt',
};

export default function FeedbackPage() {
  const [list, setList] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [filterCreatedFrom, setFilterCreatedFrom] = useState('');
  const [filterCreatedTo, setFilterCreatedTo] = useState('');
  const [filterAttachment, setFilterAttachment] = useState('');
  const [keyword, setKeyword] = useState('');
  const [reply, setReply] = useState('');
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [reopenModalOpen, setReopenModalOpen] = useState(false);
  const [reopenForm, setReopenForm] = useState({ reason: '', currentState: '' });
  const [searchParams] = useSearchParams();

  const currentUser = authUtils.getUser();
  const isAdmin = ['admin', 'hr_admin', 'manager'].includes(currentUser?.role);

  useEffect(() => {
    document.title = '问题反馈 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await hrmApi.list('feedbacks');
      setList(data || []);
      const selectedId = searchParams.get('id');
      if (selectedId) {
        const match = (data || []).find((x: any) => x.id === selectedId);
        if (match) {
          setSelected(match);
          setReply(match.handlerReply || '');
        }
      }
      // 列表刷新后，更新当前选中项的最新数据
      setSelected((prev: any) => {
        if (!prev) return prev;
        const fresh = (data || []).find((x: any) => x.id === prev.id);
        return fresh || prev;
      });
    } catch (e: any) {
      toast.error(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(() => {
    return list.filter((item) => {
      if (filterType && item.feedbackType !== filterType) return false;
      if (filterStatus && item.status !== filterStatus) return false;
      if (filterSeverity && item.severity !== filterSeverity) return false;
      if (filterUser && item.userName !== filterUser) return false;
      if (filterAttachment === 'with' && !(item.attachments || []).length) return false;
      if (filterAttachment === 'without' && (item.attachments || []).length) return false;
      const createdDate = item.createdAt ? new Date(item.createdAt) : null;
      if (filterCreatedFrom && (!createdDate || createdDate < new Date(filterCreatedFrom))) return false;
      if (filterCreatedTo && (!createdDate || createdDate > new Date(`${filterCreatedTo}T23:59:59`))) return false;
      if (keyword) {
        const k = keyword.toLowerCase();
        if (
          !item.title?.toLowerCase().includes(k) &&
          !item.content?.toLowerCase().includes(k) &&
          !item.userName?.toLowerCase().includes(k)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [list, filterType, filterStatus, filterSeverity, filterUser, filterCreatedFrom, filterCreatedTo, filterAttachment, keyword]);

  const userOptions = useMemo(() => Array.from(new Set(list.map((item) => item.userName).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN')), [list]);
  const activeFilterCount = [filterType, filterStatus, filterSeverity, filterUser, filterCreatedFrom, filterCreatedTo, filterAttachment, keyword].filter(Boolean).length;
  const resetFilters = () => {
    setFilterType('');
    setFilterStatus('');
    setFilterSeverity('');
    setFilterUser('');
    setFilterCreatedFrom('');
    setFilterCreatedTo('');
    setFilterAttachment('');
    setKeyword('');
  };

  const stats = useMemo(() => {
    const total = list.length;
    const pending = list.filter((x) => x.status === 'pending').length;
    const inProgress = list.filter((x) => x.status === 'in_progress').length;
    const resolved = list.filter((x) => x.status === 'resolved').length;
    return { total, pending, inProgress, resolved };
  }, [list]);

  const handleSelect = (item: any) => {
    setSelected(item);
    setReply(item.handlerReply || '');
    setReopenModalOpen(false);
    setReopenForm({ reason: '', currentState: '' });
  };

  const handleUpdateStatus = async (status: string) => {
    if (!selected || pendingAction) return;
    setPendingAction(status);
    try {
      const updated = await hrmApi.update('feedbacks', selected.id, {
        status,
        handlerReply: reply,
      });
      toast.success(`已更新状态为「${statusMap[status]?.label || status}」`);
      setSelected(updated);
      setReply(updated.handlerReply || '');
      await loadData();
    } catch (e: any) {
      console.error('更新状态失败', e);
      toast.error(e?.message || '更新失败，请检查权限或网络');
    } finally {
      setPendingAction(null);
    }
  };

  const handleSaveReply = async () => {
    if (!selected || pendingAction) return;
    if (!reply.trim()) {
      toast.warning('请填写回复内容');
      return;
    }
    setPendingAction('save_reply');
    try {
      const updated = await hrmApi.update('feedbacks', selected.id, {
        handlerReply: reply,
        status: selected.status === 'pending' ? 'in_progress' : selected.status,
      });
      toast.success('回复已保存');
      setSelected(updated);
      setReply(updated.handlerReply || '');
      await loadData();
    } catch (e: any) {
      console.error('保存回复失败', e);
      toast.error(e?.message || '保存失败');
    } finally {
      setPendingAction(null);
    }
  };

  const openReopenModal = () => {
    setReopenForm({ reason: '', currentState: '' });
    setReopenModalOpen(true);
  };

  const handleReopen = async () => {
    if (!selected || pendingAction) return;
    const reason = reopenForm.reason.trim();
    const currentState = reopenForm.currentState.trim();
    if (!reason || !currentState) {
      toast.warning('请填写重新打开原因和当前情况描述');
      return;
    }
    setPendingAction('reopen');
    try {
      const updated = await hrmApi.update('feedbacks', selected.id, {
        status: 'pending',
        reopenReason: reason,
        reopenCurrentState: currentState,
      });
      toast.success('已重新打开反馈');
      setSelected(updated);
      setReply(updated.handlerReply || '');
      setReopenModalOpen(false);
      setReopenForm({ reason: '', currentState: '' });
      await loadData();
    } catch (e: any) {
      toast.error(e?.message || '重新打开失败');
    } finally {
      setPendingAction(null);
    }
  };

  const handleDelete = async (item: any) => {
    if (!(await confirm({ title: '删除反馈', message: `确定删除"${item.title}"？此操作不可撤销。`, confirmText: '删除' }))) return;
    try {
      await hrmApi.remove('feedbacks', item.id);
      toast.success('已删除');
      if (selected?.id === item.id) setSelected(null);
      await loadData();
    } catch (e: any) {
      toast.error(e?.message || '删除失败');
    }
  };

  const resolvedLabel = selected ? (typeMap[selected.feedbackType]?.resolvedLabel || '已解决') : '已解决';
  const canReopenSelected = selected
    && (selected.status === 'resolved' || selected.status === 'closed')
    && (isAdmin || selected.userId === currentUser?.id);

  return (
    <Layout>
      <div className="animate-fade-in">
        {/* 头部 */}
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-gray-900">问题反馈</h1>
          <p className="text-sm text-gray-500 mt-1">
            {isAdmin ? '查看并处理用户提交的所有问题反馈' : '查看您提交的反馈及处理进度'}
          </p>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {[
            { label: '全部反馈', value: stats.total, icon: 'fa-inbox', color: 'text-gray-600 bg-gray-50' },
            { label: '待处理', value: stats.pending, icon: 'fa-clock', color: 'text-amber-600 bg-amber-50' },
            { label: '处理中', value: stats.inProgress, icon: 'fa-spinner', color: 'text-blue-600 bg-blue-50' },
            { label: '已解决', value: stats.resolved, icon: 'fa-check-circle', color: 'text-green-600 bg-green-50' },
          ].map((s) => (
            <div key={s.label} className="bg-white rounded-lg border border-gray-100 p-4 flex items-center justify-between">
              <div>
                <div className="text-xs text-gray-500">{s.label}</div>
                <div className="text-2xl font-semibold text-gray-900 mt-1">{s.value}</div>
              </div>
              <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${s.color}`}>
                <AppIcon className={`fas ${s.icon}`} />
              </div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* 列表 */}
          <div className="lg:col-span-7 bg-white rounded-lg border border-gray-100 overflow-hidden flex flex-col" style={{ minHeight: '560px' }}>
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/50 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative flex-1 min-w-[200px]">
                  <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 text-xs" />
                  <input
                    type="text"
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    placeholder="搜索标题、内容或提交人..."
                    className="w-full pl-9 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 outline-none"
                  />
                </div>
                {isAdmin && (
                  <select value={filterUser} onChange={(e) => setFilterUser(e.target.value)} className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                    <option value="">全部提交人</option>
                    {userOptions.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                )}
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  <option value="">全部类型</option>
                  <option value="bug">缺陷</option>
                  <option value="feature">需求</option>
                  <option value="other">其他</option>
                </select>
                <select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  <option value="">全部状态</option>
                  <option value="pending">待处理</option>
                  <option value="in_progress">处理中</option>
                  <option value="resolved">已解决</option>
                  <option value="closed">已关闭</option>
                </select>
                <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)} className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  <option value="">全部优先级</option>
                  {Object.entries(severityMap).map(([value, meta]) => <option key={value} value={value}>{meta.label}</option>)}
                </select>
                <select value={filterAttachment} onChange={(e) => setFilterAttachment(e.target.value)} className="px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  <option value="">全部附件</option>
                  <option value="with">有附件</option>
                  <option value="without">无附件</option>
                </select>
                <button
                  onClick={loadData}
                  className="px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                >
                  <AppIcon className="fas fa-sync-alt mr-1.5 text-xs" />刷新
                </button>
                <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-1.5 text-xs text-gray-500 bg-white border border-gray-200 rounded-lg hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed">
                  <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input type="date" value={filterCreatedFrom} onChange={(e) => setFilterCreatedFrom(e.target.value)} className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                <input type="date" value={filterCreatedTo} onChange={(e) => setFilterCreatedTo(e.target.value)} className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {list.length} 条</span>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-20">
                  <AppIcon className="fas fa-spinner fa-spin text-2xl text-blue-400" />
                </div>
              ) : filtered.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                  <AppIcon className="fas fa-inbox text-4xl mb-3" />
                  <p className="text-sm">{list.length === 0 ? '暂无反馈记录' : '没有符合条件的反馈'}</p>
                </div>
              ) : (
                <ul className="divide-y divide-gray-100">
                  {filtered.map((item) => {
                    const t = typeMap[item.feedbackType] || typeMap.other;
                    const s = statusMap[item.status] || statusMap.pending;
                    return (
                      <li
                        key={item.id}
                        onClick={() => handleSelect(item)}
                        className={`px-4 py-3 cursor-pointer transition-colors ${
                          selected?.id === item.id ? 'bg-blue-50/50' : 'hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${t.color} border`}>
                            <AppIcon className={`fas ${t.icon} text-xs`} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-sm font-medium text-gray-900 truncate">{item.title}</span>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.color} flex-shrink-0`}>
                                {item.status === 'resolved' ? (typeMap[item.feedbackType]?.resolvedLabel || s.label) : s.label}
                              </span>
                              {item.feedbackType === 'bug' && item.severity && (
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${severityMap[item.severity]?.color || ''} flex-shrink-0`}>
                                  {severityMap[item.severity]?.label}
                                </span>
                              )}
                              {item.attachments && item.attachments.length > 0 && (
                                <span className="text-[10px] text-gray-400 flex-shrink-0">
                                  <AppIcon className="fas fa-paperclip mr-0.5" />{item.attachments.length}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 line-clamp-2 mb-1.5">{item.content}</p>
                            <div className="flex items-center gap-3 text-[11px] text-gray-400">
                              <span><AppIcon className="fas fa-user mr-1" />{item.userName || '匿名'}</span>
                              <span><AppIcon className="fas fa-clock mr-1" />{formatDateTime(item.createdAt)}</span>
                            </div>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          {/* 详情 */}
          <div className="lg:col-span-5 bg-white rounded-lg border border-gray-100 overflow-hidden flex flex-col" style={{ minHeight: '560px' }}>
            {!selected ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-400 py-20">
                <AppIcon className="fas fa-arrow-left text-2xl mb-3" />
                <p className="text-sm">请从左侧选择一条反馈查看详情</p>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                <div className="px-5 py-4 border-b border-gray-100">
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <h3 className="text-base font-semibold text-gray-900 flex-1">{selected.title}</h3>
                    {(isAdmin || selected.userId === currentUser?.id) && (
                      <button
                        onClick={() => handleDelete(selected)}
                        className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                        title="删除"
                      >
                        <AppIcon className="fas fa-trash" />
                      </button>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {(() => {
                      const t = typeMap[selected.feedbackType] || typeMap.other;
                      return (
                        <span className={`px-2 py-0.5 rounded border ${t.color}`}>
                          <AppIcon className={`fas ${t.icon} mr-1`} />{t.label}
                        </span>
                      );
                    })()}
                    {selected.feedbackType === 'bug' && (
                      <span className={`px-2 py-0.5 rounded ${severityMap[selected.severity]?.color || ''}`}>
                        严重程度：{severityMap[selected.severity]?.label || '中'}
                      </span>
                    )}
                    <span className={`px-2 py-0.5 rounded ${statusMap[selected.status]?.color || ''}`}>
                      {selected.status === 'resolved'
                        ? (typeMap[selected.feedbackType]?.resolvedLabel || '已解决')
                        : (statusMap[selected.status]?.label || '待处理')}
                    </span>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1.5">问题描述</div>
                    <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap break-words">
                      {selected.content}
                    </div>
                  </div>

                  {/* 附件 */}
                  {selected.attachments && selected.attachments.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1.5">
                        附件 <span className="text-gray-400 font-normal">({selected.attachments.length})</span>
                        <span className="text-gray-400 font-normal ml-1">· 点击预览</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {selected.attachments.map((att: any, idx: number) => {
                          const isImage = att.type === 'image';
                          return (
                            <button
                              key={idx}
                              type="button"
                              onClick={() => setPreviewIndex(idx)}
                              className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg border border-gray-100 hover:border-blue-300 hover:bg-blue-50/50 transition-all group text-left"
                              title={`点击预览：${att.name}`}
                            >
                              {isImage ? (
                                <ProtectedImage
                                  fileUrl={att.url}
                                  alt={att.name}
                                  className="w-10 h-10 object-cover rounded flex-shrink-0 border border-gray-200"
                                />
                              ) : (
                                <div className="w-10 h-10 bg-white rounded border border-gray-200 flex items-center justify-center flex-shrink-0">
                                  <AppIcon className={`fas ${fileIconMap[att.ext] || 'fa-file'} text-blue-500 text-lg`} />
                                </div>
                              )}
                              <div className="flex-1 min-w-0">
                                <div className="text-xs text-gray-700 truncate group-hover:text-blue-600">{att.name}</div>
                                <div className="text-[10px] text-gray-400 mt-0.5">{formatSize(att.size)}</div>
                              </div>
                              <AppIcon className="fas fa-eye text-gray-300 group-hover:text-blue-500 text-xs" />
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <div className="text-gray-500 mb-1">提交人</div>
                      <div className="text-gray-800">{selected.userName || '匿名'}</div>
                    </div>
                    <div>
                      <div className="text-gray-500 mb-1">提交时间</div>
                      <div className="text-gray-800">{formatDateTime(selected.createdAt)}</div>
                    </div>
                    {selected.handlerName && (
                      <>
                        <div>
                          <div className="text-gray-500 mb-1">处理人</div>
                          <div className="text-gray-800">{selected.handlerName}</div>
                        </div>
                        <div>
                          <div className="text-gray-500 mb-1">处理时间</div>
                          <div className="text-gray-800">{formatDateTime(selected.handledAt)}</div>
                        </div>
                      </>
                    )}
                    {selected.reopenReason && (
                      <div className="col-span-2">
                        <div className="text-gray-500 mb-1">最近重新打开</div>
                        <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 text-amber-800 space-y-2">
                          <div>
                            <span className="font-medium">原因：</span>
                            <span className="whitespace-pre-wrap break-words">{selected.reopenReason}</span>
                          </div>
                          <div>
                            <span className="font-medium">当前情况：</span>
                            <span className="whitespace-pre-wrap break-words">{selected.reopenCurrentState || '-'}</span>
                          </div>
                        </div>
                      </div>
                    )}
                    {selected.reopenHistory?.length > 0 && (
                      <div className="col-span-2">
                        <div className="text-gray-500 mb-1">重新打开记录</div>
                        <div className="space-y-2">
                          {[...selected.reopenHistory].slice().reverse().map((item: any, idx: number) => (
                            <div key={`${item.reopenedAt || idx}-${idx}`} className="bg-gray-50 border border-gray-100 rounded-lg p-2.5 text-gray-700">
                              <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-400 mb-1">
                                <span>{formatDateTime(item.reopenedAt)}</span>
                                <span>{statusMap[item.fromStatus]?.label || item.fromStatus} → 待处理</span>
                              </div>
                              <div className="whitespace-pre-wrap break-words">原因：{item.reason}</div>
                              <div className="whitespace-pre-wrap break-words mt-1">现状：{item.currentState}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {selected.pageUrl && (
                      <div className="col-span-2">
                        <div className="text-gray-500 mb-1">页面 URL</div>
                        <div className="text-gray-700 break-all bg-gray-50 rounded px-2 py-1">{selected.pageUrl}</div>
                      </div>
                    )}
                  </div>

                  {/* 处理回复 */}
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1.5">
                      处理回复
                      {selected.handlerName && (
                        <span className="text-gray-400 ml-1">（{selected.handlerName}）</span>
                      )}
                    </div>
                    {isAdmin ? (
                      <textarea
                        value={reply}
                        onChange={(e) => setReply(e.target.value)}
                        rows={4}
                        maxLength={1000}
                        placeholder="填写处理意见或回复..."
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 outline-none bg-gray-50 focus:bg-white resize-none"
                      />
                    ) : (
                      <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 whitespace-pre-wrap break-words min-h-[60px]">
                        {selected.handlerReply || <span className="text-gray-400">暂无回复</span>}
                      </div>
                    )}
                  </div>
                </div>

                {/* 操作栏（仅管理员可见） */}
                {isAdmin && (
                  <div className="px-5 py-3 border-t border-gray-100 bg-gray-50/50 flex flex-wrap items-center gap-2">
                    <button
                      onClick={handleSaveReply}
                      disabled={!!pendingAction}
                      className="px-3 py-1.5 text-xs text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                    >
                      <AppIcon className="fas fa-save mr-1.5" />{pendingAction === 'save_reply' ? '保存中…' : '保存回复'}
                    </button>
                    <div className="flex-1" />
                    {selected.status !== 'in_progress' && (
                      <button
                        onClick={() => handleUpdateStatus('in_progress')}
                        disabled={!!pendingAction}
                        className="px-3 py-1.5 text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-play mr-1" />{pendingAction === 'in_progress' ? '处理中…' : '处理中'}
                      </button>
                    )}
                    {selected.status !== 'resolved' && (
                      <button
                        onClick={() => handleUpdateStatus('resolved')}
                        disabled={!!pendingAction}
                        className="px-3 py-1.5 text-xs text-green-600 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-check mr-1" />{resolvedLabel}
                      </button>
                    )}
                    {selected.status !== 'closed' && (
                      <button
                        onClick={() => handleUpdateStatus('closed')}
                        disabled={!!pendingAction}
                        className="px-3 py-1.5 text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-times mr-1" />关闭
                      </button>
                    )}
                    {(selected.status === 'resolved' || selected.status === 'closed') && (
                      <button
                        onClick={openReopenModal}
                        disabled={!!pendingAction}
                        className="px-3 py-1.5 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 disabled:opacity-50"
                      >
                        <AppIcon className="fas fa-undo mr-1" />重新打开
                      </button>
                    )}
                  </div>
                )}
                {!isAdmin && canReopenSelected && (
                  <div className="px-5 py-3 border-t border-gray-100 bg-gray-50/50 flex justify-end">
                    <button
                      onClick={openReopenModal}
                      className="px-3 py-1.5 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100"
                    >
                      <AppIcon className="fas fa-undo mr-1" />重新打开
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 附件预览 */}
      {previewIndex !== null && selected?.attachments && (
        <AttachmentPreview
          attachments={selected.attachments}
          initialIndex={previewIndex}
          onClose={() => setPreviewIndex(null)}
        />
      )}

      {reopenModalOpen && selected && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setReopenModalOpen(false)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-base font-bold text-gray-800">重新打开反馈</h2>
              <button onClick={() => setReopenModalOpen(false)} className="text-gray-400 hover:text-gray-600"><AppIcon className="fas fa-times" /></button>
            </div>
            <div className="p-5 space-y-3">
              <div className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3">
                <div className="font-medium text-gray-800 mb-1">{selected.title}</div>
                <div className="text-xs text-gray-500">已修复内容重新出现时，请补充原因和当前复现情况，便于处理人继续定位。</div>
              </div>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">重新打开原因 <span className="text-red-500">*</span></span>
                <textarea
                  value={reopenForm.reason}
                  onChange={(e) => setReopenForm({ ...reopenForm, reason: e.target.value })}
                  rows={3}
                  maxLength={500}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 outline-none resize-none"
                  placeholder="例如：修复后仍然出现同样错误，或出现了新的失败现象"
                />
              </label>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">当前情况描述 <span className="text-red-500">*</span></span>
                <textarea
                  value={reopenForm.currentState}
                  onChange={(e) => setReopenForm({ ...reopenForm, currentState: e.target.value })}
                  rows={4}
                  maxLength={1000}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 outline-none resize-none"
                  placeholder="请描述现在如何复现、看到什么结果、期望是什么"
                />
              </label>
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
              <button onClick={() => setReopenModalOpen(false)} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50">取消</button>
              <button onClick={handleReopen} className="px-4 py-1.5 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600">
                提交并重新打开
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
