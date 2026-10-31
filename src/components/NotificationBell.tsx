// @ts-nocheck
/**
 * 通知铃铛（门户顶部）— 未读数 + 下拉列表 + 全部已读
 */
import React, { useEffect, useState, useRef } from 'react';
import apiClient from '../utils/api';
import AppIcon from './AppIcon';

const TYPE_ICONS: Record<string, string> = {
  exam: 'fa-clipboard-check', course: 'fa-book-open',
  learning_path: 'fa-route', discussion: 'fa-comments',
  training: 'fa-bell', system: 'fa-info-circle',
};

export const NotificationBell: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const load = () => {
    apiClient.get('/portal/notifications').then((r: any) => {
      setItems(r.items || []);
      setUnread(r.unreadCount || 0);
    }).catch(() => {});
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);  // 30秒刷新
    return () => clearInterval(t);
  }, []);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const markRead = async (id: string, linkUrl?: string) => {
    await apiClient.post(`/portal/notifications/${id}/read`, {});
    load();
    if (linkUrl) window.location.href = linkUrl;
  };

  const readAll = async () => {
    await apiClient.post('/portal/notifications/read-all', {});
    load();
  };

  const fmtTime = (t: string) => {
    if (!t) return '';
    const d = new Date(t.includes('Z') ? t : t + 'Z');
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
    return d.toLocaleDateString('zh-CN');
  };

  return (
    <div ref={ref} className="relative">
      <button onClick={() => { setOpen(!open); if (!open) load(); }}
        className="relative w-9 h-9 rounded-lg hover:bg-bg-light flex items-center justify-center transition-colors">
        <AppIcon className={`fas fa-bell ${unread > 0 ? 'text-primary' : 'text-text-secondary'}`} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 bg-danger text-white text-[10px] font-bold rounded-full flex items-center justify-center">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 w-80 max-w-[calc(100vw-2rem)] bg-white rounded-xl shadow-xl border border-border-light z-50 flex flex-col" style={{ maxHeight: '70vh' }}>
          <div className="flex items-center justify-between px-4 py-3 border-b border-border-light">
            <span className="font-medium text-sm text-text-primary">通知</span>
            {unread > 0 && (
              <button onClick={readAll} className="text-xs text-primary hover:text-blue-700">全部已读</button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-border-light">
            {items.length === 0 ? (
              <div className="p-8 text-center text-text-secondary text-sm">
                <AppIcon className="fas fa-bell-slash text-2xl text-text-secondary/30 mb-2" />
                <p>暂无通知</p>
              </div>
            ) : items.map(n => (
              <div key={n.id}
                onClick={() => markRead(n.id, n.linkUrl)}
                className={`px-4 py-3 cursor-pointer hover:bg-bg-light/50 transition-colors ${n.status === 'unread' ? 'bg-primary/5' : ''}`}>
                <div className="flex items-start gap-2.5">
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${n.status === 'unread' ? 'bg-primary/10' : 'bg-bg-light'}`}>
                    <AppIcon className={`fas ${TYPE_ICONS[n.noticeType] || 'fa-bell'} text-xs ${n.status === 'unread' ? 'text-primary' : 'text-text-secondary'}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-text-primary truncate">{n.title}</span>
                      {n.status === 'unread' && <span className="w-2 h-2 rounded-full bg-danger shrink-0" />}
                    </div>
                    <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{n.content}</p>
                    <span className="text-[10px] text-text-secondary/70">{fmtTime(n.createdAt)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
