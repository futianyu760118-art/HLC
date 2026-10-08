// @ts-nocheck
/**
 * 课程讨论区组件（嵌在课程详情页底部）
 */
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '../utils/api';
import toast from '../utils/toast';
import AppIcon from './AppIcon';

export const CourseDiscussion: React.FC<{ courseId: string }> = ({ courseId }) => {
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [expandedPost, setExpandedPost] = useState<string | null>(null);
  const [replies, setReplies] = useState<Record<string, any[]>>({});
  const [replyText, setReplyText] = useState<Record<string, string>>({});
  const [loadingReplies, setLoadingReplies] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiClient.get(`/portal/courses/${courseId}/discussions`).then((r: any[]) => {
      setPosts(r || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [courseId]);
  useEffect(() => { load(); }, [load]);

  const submitPost = async () => {
    if (!newTitle.trim() || !newContent.trim()) { toast.error('标题和内容不能为空'); return; }
    try {
      await apiClient.post(`/portal/courses/${courseId}/discussions`, { title: newTitle.trim(), content: newContent.trim() });
      setNewTitle(''); setNewContent(''); setShowForm(false);
      toast.success('发帖成功');
      load();
    } catch (e) { toast.error(e.message); }
  };

  const toggleExpand = async (postId: string) => {
    if (expandedPost === postId) { setExpandedPost(null); return; }
    setExpandedPost(postId);
    if (!replies[postId]) {
      setLoadingReplies(postId);
      try {
        const r = await apiClient.get(`/portal/discussions/${postId}`);
        setReplies({ ...replies, [postId]: r.replies || [] });
      } catch { toast.error('加载回复失败'); } finally { setLoadingReplies(null); }
    }
  };

  const submitReply = async (postId: string) => {
    const text = (replyText[postId] || '').trim();
    if (!text) return;
    try {
      const r = await apiClient.post(`/portal/discussions/${postId}/replies`, { content: text });
      setReplies({ ...replies, [postId]: [...(replies[postId] || []), r] });
      setReplyText({ ...replyText, [postId]: '' });
      load(); // 刷新回复数
    } catch (e) { toast.error(e.message); }
  };

  const like = async (targetType: string, targetId: string, cb?: () => void) => {
    try {
      await apiClient.post('/portal/discussions/like', { targetType, targetId });
      cb?.();
      load();
      if (expandedPost) toggleExpand(expandedPost);
    } catch {}
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
    <div className="bg-white rounded-xl border border-border-light overflow-hidden">
      <div className="px-5 py-3 border-b border-border-light flex items-center justify-between">
        <h2 className="font-semibold text-text-primary flex items-center gap-2">
          <AppIcon className="fas fa-comments text-primary" /> 课程讨论区
          {posts.length > 0 && <span className="text-xs text-text-secondary font-normal">({posts.length})</span>}
        </h2>
        <button onClick={() => setShowForm(!showForm)} className="text-sm text-primary hover:text-blue-700 flex items-center gap-1">
          <AppIcon className="fas fa-pen text-xs" /> {showForm ? '取消' : '发帖'}
        </button>
      </div>

      {/* 发帖表单 */}
      {showForm && (
        <div className="p-4 border-b border-border-light space-y-2">
          <input value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="帖子标题"
            className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" />
          <textarea value={newContent} onChange={e => setNewContent(e.target.value)} placeholder="说说你的想法、疑问或心得…" rows={3}
            className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm resize-none" />
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-text-secondary">取消</button>
            <button onClick={submitPost} className="px-4 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-blue-700">发布</button>
          </div>
        </div>
      )}

      {/* 帖子列表 */}
      <div className="divide-y divide-border-light">
        {loading ? (
          <div className="p-8 text-center text-text-secondary text-sm">加载中…</div>
        ) : posts.length === 0 ? (
          <div className="p-8 text-center">
            <AppIcon className="fas fa-comments text-3xl text-text-secondary/30 mb-2" />
            <p className="text-text-secondary text-sm">还没有讨论，发第一个帖子吧！</p>
          </div>
        ) : posts.map(p => (
          <div key={p.id} className="p-4 hover:bg-bg-light/30 transition-colors">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium text-primary shrink-0">
                {(p.employeeName || '?').charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-sm font-medium text-text-primary">{p.employeeName}</span>
                  <span className="text-xs text-text-secondary">{fmtTime(p.createdAt)}</span>
                  {p.isPinned && <span className="text-xs text-warning"><AppIcon className="fas fa-thumbtack" /> 置顶</span>}
                </div>
                <h3 className="text-sm font-medium text-text-primary mb-1">{p.title}</h3>
                <p className="text-sm text-text-secondary line-clamp-3 whitespace-pre-wrap">{p.content}</p>
                <div className="mt-2 flex items-center gap-4 text-xs text-text-secondary">
                  <button onClick={() => like('post', p.id)} className="flex items-center gap-1 hover:text-primary transition-colors">
                    <AppIcon className="fas fa-thumbs-up" /> {p.likeCount || 0}
                  </button>
                  <button onClick={() => toggleExpand(p.id)} className="flex items-center gap-1 hover:text-primary transition-colors">
                    <AppIcon className="fas fa-comment" /> {p.replyCount || 0} 回复
                  </button>
                </div>

                {/* 回复展开 */}
                {expandedPost === p.id && (
                  <div className="mt-3 pl-4 border-l-2 border-border-light space-y-2">
                    {loadingReplies === p.id && <div className="text-xs text-text-secondary py-1">加载回复中…</div>}
                    {loadingReplies !== p.id && (!replies[p.id] || replies[p.id].length === 0) && <div className="text-xs text-text-secondary py-1">暂无回复</div>}
                    {(replies[p.id] || []).map(r => (
                      <div key={r.id} className="flex items-start gap-2">
                        <div className="w-6 h-6 rounded-full bg-bg-light flex items-center justify-center text-[10px] font-medium text-text-secondary shrink-0">
                          {(r.employeeName || '?').charAt(0)}
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-text-primary">{r.employeeName}</span>
                            <span className="text-[10px] text-text-secondary">{fmtTime(r.createdAt)}</span>
                          </div>
                          <p className="text-sm text-text-primary mt-0.5">{r.content}</p>
                          <button onClick={() => like('reply', r.id)} className="text-[10px] text-text-secondary hover:text-primary mt-0.5">
                            <AppIcon className="fas fa-thumbs-up" /> {r.likeCount || 0}
                          </button>
                        </div>
                      </div>
                    ))}
                    {/* 回复输入 */}
                    <div className="flex gap-2 mt-2">
                      <input value={replyText[p.id] || ''} onChange={e => setReplyText({ ...replyText, [p.id]: e.target.value })}
                        onKeyDown={e => { if (e.key === 'Enter') submitReply(p.id); }}
                        placeholder="写回复…" className="flex-1 px-2 py-1 text-sm border border-border-light rounded outline-none" />
                      <button onClick={() => submitReply(p.id)} className="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-blue-700">回复</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
