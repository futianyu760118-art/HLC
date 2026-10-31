// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { hrmApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
const noticeTypeLabels: Record<string, { label: string; icon: string; color: string }> = {
  system: { label: '系统通知', icon: 'fa-bell', color: 'bg-blue-50 text-blue-500' },
  approval: { label: '审批提醒', icon: 'fa-clipboard-check', color: 'bg-purple-50 text-purple-500' },
  hr: { label: '人事提醒', icon: 'fa-user-tie', color: 'bg-orange-50 text-orange-500' },
  performance: { label: '绩效提醒', icon: 'fa-star', color: 'bg-green-50 text-green-500' },
  contract: { label: '合同提醒', icon: 'fa-file-contract', color: 'bg-cyan-50 text-cyan-500' },
  feedback: { label: '反馈通知', icon: 'fa-bug', color: 'bg-emerald-50 text-emerald-600' },
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

const getTimeAgo = (timestamp: string) => {
  if (!timestamp) return '';
  const now = new Date();
  const time = new Date(timestamp.includes('Z') ? timestamp : timestamp + 'Z');
  const diff = now.getTime() - time.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 30) return `${days}天前`;
  return time.toLocaleDateString('zh-CN');
};

export default function NotificationsPage() {
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any | null>(null);
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [filterCreatedFrom, setFilterCreatedFrom] = useState('');
  const [filterCreatedTo, setFilterCreatedTo] = useState('');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [creatingNew, setCreatingNew] = useState(false);
  const [sending, setSending] = useState(false);
  const [form, setForm] = useState({ title: '', content: '', noticeType: 'system', userId: '', linkUrl: '' });

  const currentUser = authUtils.getUser();
  const isAdmin = ['admin', 'hr_admin', 'manager'].includes(currentUser?.role);
  const notifyNotificationChange = () => window.dispatchEvent(new Event('hrm:notifications-changed'));

  useEffect(() => {
    document.title = '通知提醒 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await hrmApi.list('notifications');
      setNotifications(data || []);
      if (isAdmin) {
        const userData = await hrmApi.list('users');
        setUsers(userData || []);
      }
    } catch (error) {
      console.error('加载通知失败', error);
    } finally {
      setLoading(false);
    }
  };

  const handleMarkRead = async (record: any) => {
    if (record.status === 'read') return;
    try {
      await hrmApi.update('notifications', record.id, { status: 'read' });
      notifyNotificationChange();
      await loadData();
      if (selected?.id === record.id) {
        setSelected({ ...selected, status: 'read' });
      }
    } catch (error: any) {
      console.error('标记已读失败', error);
    }
  };

  const handleMarkAllRead = async () => {
    const unread = notifications.filter((n) => n.status === 'unread');
    if (unread.length === 0) return;
    if (!(await confirm({ title: '全部标记已读', message: `确定将 ${unread.length} 条通知全部标记为已读？`, confirmText: '标记已读' }))) return;
    try {
      await Promise.all(unread.map((n) => hrmApi.update('notifications', n.id, { status: 'read' })));
      notifyNotificationChange();
      await loadData();
      toast.info('已全部标记为已读');
    } catch (error: any) {
      toast.error(error.message || '操作失败');
    }
  };

  const handleDelete = async (record: any) => {
    if (!(await confirm({ title: '删除通知', message: '确定删除这条通知？', confirmText: '删除', danger: true }))) return;
    try {
      await hrmApi.remove('notifications', record.id);
      notifyNotificationChange();
      setSelected(null);
      await loadData();
    } catch (error: any) {
      toast.error(error.message || '删除失败');
    }
  };

  const handleCreate = async () => {
    if (!form.title) {
      toast.info('请输入标题');
      return;
    }
    if (sending) return;
    setSending(true);
    try {
      await hrmApi.create('notifications', form);
      notifyNotificationChange();
      setCreatingNew(false);
      setForm({ title: '', content: '', noticeType: 'system', userId: '', linkUrl: '' });
      await loadData();
      toast.success('通知已发送');
    } catch (error: any) {
      toast.error(error.message || '创建失败');
    } finally {
      setSending(false);
    }
  };

  const filtered = notifications.filter((n) => {
    if (searchKeyword) {
      const text = `${n.title || ''} ${n.content || ''} ${n.userName || ''}`.toLowerCase();
      if (!text.includes(searchKeyword.toLowerCase())) return false;
    }
    if (filterType && n.noticeType !== filterType) return false;
    if (filterStatus && n.status !== filterStatus) return false;
    if (filterUser && n.userId !== filterUser) return false;
    const createdDate = n.createdAt ? new Date(n.createdAt) : null;
    if (filterCreatedFrom && (!createdDate || createdDate < new Date(filterCreatedFrom))) return false;
    if (filterCreatedTo && (!createdDate || createdDate > new Date(`${filterCreatedTo}T23:59:59`))) return false;
    return true;
  });
  const activeFilterCount = [searchKeyword, filterType, filterStatus, filterUser, filterCreatedFrom, filterCreatedTo].filter(Boolean).length;
  const resetFilters = () => {
    setSearchKeyword('');
    setFilterType('');
    setFilterStatus('');
    setFilterUser('');
    setFilterCreatedFrom('');
    setFilterCreatedTo('');
  };

  const unreadCount = notifications.filter((n) => n.status === 'unread').length;

  const handleOpenLink = async (record: any) => {
    if (!record.linkUrl) return;
    await handleMarkRead(record);
    navigate(record.linkUrl);
  };

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-bell text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">通知提醒 {unreadCount > 0 && <span className="ml-2 px-2 py-0.5 bg-red-500 text-white text-[10px] rounded-full">{unreadCount}</span>}</h1>
                <p className="text-xs text-gray-400 mt-0.5">消息中心 · 接收系统、人事、审批和问题反馈处理提醒</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {unreadCount > 0 && (
                <button onClick={handleMarkAllRead} className="px-3 py-[6px] text-xs border border-gray-200 rounded-lg text-gray-500 hover:text-blue-500 hover:border-blue-200 transition-colors">
                  <AppIcon className="fas fa-check-double mr-1" />全部已读
                </button>
              )}
              {isAdmin && (
                <button onClick={() => setCreatingNew(true)} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
                  <AppIcon className="fas fa-plus mr-1" />发送通知
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={searchKeyword} onChange={setSearchKeyword} placeholder="标题/内容/接收人..." className="w-60" />
          <div className="flex items-center bg-gray-50 rounded-lg p-0.5">
            {[
              { label: '全部', value: '', count: notifications.length },
              { label: '未读', value: 'unread', count: unreadCount },
              { label: '已读', value: 'read', count: notifications.length - unreadCount },
            ].map((tab) => (
              <button key={tab.value} onClick={() => setFilterStatus(tab.value)} className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${filterStatus === tab.value ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                {tab.label} <span className="text-gray-400 ml-0.5">({tab.count})</span>
              </button>
            ))}
          </div>
          <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
          </button>
          <div className="flex-1" />
          <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filtered.length}</span> / {notifications.length} 条</span>
          </div>
          <div className="hpt-filter-surface p-3">
            <div className="hpt-filter-grid">
              <FilterField label="通知类型" type="select" value={filterType} onChange={setFilterType} options={toFilterOptions(Object.entries(noticeTypeLabels).map(([value, item]) => ({ value, label: item.label })))} />
              {isAdmin && (
                <FilterField label="接收人" type="combo" value={filterUser} onChange={setFilterUser} options={toFilterOptions(users.map((user: any) => ({ label: user.name || user.email || user.id, value: user.id })))} />
              )}
              <FilterField label="创建时间" type="date-range" value={{ from: filterCreatedFrom, to: filterCreatedTo }} onChange={(next) => { setFilterCreatedFrom(next.from || ''); setFilterCreatedTo(next.to || ''); }} />
            </div>
          </div>
        </div>

        {/* List + Detail */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className={`bg-white rounded-xl border border-gray-100 ${selected ? 'xl:col-span-2' : 'xl:col-span-3'}`}>
            {loading ? (
              <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
            ) : filtered.length === 0 ? (
              <div className="py-16 text-center">
                <AppIcon className="fas fa-bell-slash text-3xl text-gray-200 mb-3" />
                <div className="text-sm text-gray-400">暂无通知</div>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {filtered.map((n) => {
                  const typeMeta = noticeTypeLabels[n.noticeType] || noticeTypeLabels.system;
                  const isUnread = n.status === 'unread';
                  return (
                    <div
                      key={n.id}
                      onClick={() => { setSelected(n); handleMarkRead(n); }}
                      className={`px-5 py-3 cursor-pointer transition-colors hover:bg-blue-50/30 ${selected?.id === n.id ? 'bg-blue-50/40' : ''}`}
                    >
                      <div className="flex items-start gap-3">
                        <div className={`w-8 h-8 rounded-lg ${typeMeta.color} flex items-center justify-center flex-shrink-0 mt-0.5`}>
                          <AppIcon className={`fas ${typeMeta.icon} text-xs`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`text-[13px] truncate ${isUnread ? 'font-bold text-gray-800' : 'font-medium text-gray-600'}`}>{n.title}</span>
                            {isUnread && <span className="w-1.5 h-1.5 bg-red-500 rounded-full flex-shrink-0"></span>}
                          </div>
                          <div className="text-[12px] text-gray-400 mt-0.5 truncate">{n.content || '无内容'}</div>
                          <div className="flex items-center gap-2 mt-1">
                            <span className={`text-[10px] px-1.5 py-0 rounded ${typeMeta.color}`}>{typeMeta.label}</span>
                            <span className="text-[10px] text-gray-400">{getTimeAgo(n.createdAt)}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Detail Panel */}
          {selected && (
            <div className="bg-white rounded-xl border border-gray-100 p-5">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
                <div className="flex items-center gap-2">
                  {(() => {
                    const typeMeta = noticeTypeLabels[selected.noticeType] || noticeTypeLabels.system;
                    return (
                      <>
                        <div className={`w-8 h-8 rounded-lg ${typeMeta.color} flex items-center justify-center`}>
                          <AppIcon className={`fas ${typeMeta.icon} text-xs`} />
                        </div>
                        <span className="text-sm font-bold text-gray-800">{typeMeta.label}</span>
                      </>
                    );
                  })()}
                </div>
                <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-xs">
                  <AppIcon className="fas fa-times" />
                </button>
              </div>
              <div className="space-y-3">
                <div>
                  <div className="text-base font-bold text-gray-800 mb-1">{selected.title}</div>
                  <div className="text-xs text-gray-400">{formatDateTime(selected.createdAt)}</div>
                </div>
                {selected.content && (
                  <div className="text-[13px] text-gray-600 bg-gray-50 rounded-lg p-3 leading-relaxed whitespace-pre-wrap">{selected.content}</div>
                )}
                {selected.userName && (
                  <div className="text-xs text-gray-400">接收人：{selected.userName}</div>
                )}
                {selected.linkUrl && (
                  <button onClick={() => handleOpenLink(selected)} className="inline-flex items-center gap-1 text-xs text-blue-500 hover:text-blue-700">
                    <AppIcon className="fas fa-external-link-alt" />查看详情
                  </button>
                )}
                <div className="pt-3 border-t border-gray-100 flex gap-2">
                  <button onClick={() => handleDelete(selected)} className="px-3 py-1.5 border border-red-200 text-red-500 rounded-lg text-xs hover:bg-red-50 transition-colors">
                    <AppIcon className="fas fa-trash mr-1" />删除
                  </button>
                  <button onClick={() => setSelected(null)} className="px-3 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-xs hover:bg-gray-50 transition-colors">
                    关闭
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Create Modal */}
      {creatingNew && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setCreatingNew(false)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-base font-bold text-gray-800">发送通知</h2>
              <button onClick={() => setCreatingNew(false)} className="text-gray-400 hover:text-gray-600"><AppIcon className="fas fa-times" /></button>
            </div>
            <div className="p-5 space-y-3">
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">类型</span>
                <select value={form.noticeType} onChange={(e) => setForm({ ...form, noticeType: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  {Object.entries(noticeTypeLabels).map(([v, l]) => <option key={v} value={v}>{l.label}</option>)}
                </select>
              </label>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">接收人</span>
                <select value={form.userId} onChange={(e) => setForm({ ...form, userId: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                  <option value="">全员通知</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.name || u.email || u.id}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">标题 <span className="text-red-500">*</span></span>
                <input type="text" maxLength={100} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="请输入通知标题" />
              </label>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">内容</span>
                <textarea maxLength={2000} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} rows={5} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-none" placeholder="请输入通知内容..." />
              </label>
              <label className="block">
                <span className="block text-xs text-gray-500 mb-1">详情链接</span>
                <input type="text" maxLength={500} value={form.linkUrl} onChange={(e) => setForm({ ...form, linkUrl: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="/feedback?id=..." />
              </label>
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
              <button onClick={() => setCreatingNew(false)} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50">取消</button>
              <button onClick={handleCreate} disabled={sending} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50">{sending ? '发送中…' : '发送'}</button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
