// @ts-nocheck
/**
 * AI 学习助手浮窗（嵌在课程详情页右下角）
 * 员工可针对课程内容提问，AI 基于 RAG 回答
 */
import React, { useState, useRef, useEffect } from 'react';
import apiClient from '../utils/api';
import AppIcon from './AppIcon';

const SUGGESTIONS = ['这门课的核心要点是什么？', '帮我总结一下学习重点', '有哪些需要特别注意的地方？'];

export const CourseAssistant: React.FC<{ courseId: string }> = ({ courseId }) => {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'ai', content: string }>>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const ask = async (q: string) => {
    if (!q.trim() || loading) return;
    const question = q.trim();
    setMessages(prev => [...prev, { role: 'user', content: question }].slice(-50));
    setInput('');
    setLoading(true);
    try {
      const r = await apiClient.post<{ answer: string; error?: string }>(`/portal/courses/${courseId}/ask`, { question });
      setMessages(prev => [...prev, { role: 'ai', content: r.answer || r.error || '抱歉，未能回答。' }].slice(-50));
    } catch (e) {
      setMessages(prev => [...prev, { role: 'ai', content: 'AI 助手暂时不可用：' + (e.message || '未知错误') }].slice(-50));
    } finally { setLoading(false); }
  };

  return (
    <>
      {/* 悬浮按钮 */}
      {!open && (
        <button onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-primary text-white shadow-lg hover:bg-blue-700 hover:scale-105 transition-all flex items-center justify-center z-40">
          <AppIcon className="fas fa-comment-dots text-xl" />
          <span className="absolute -top-1 -right-1 w-3 h-3 bg-success rounded-full border-2 border-white" />
        </button>
      )}

      {/* 对话窗 */}
      {open && (
        <div className="fixed bottom-6 right-6 w-80 max-w-[calc(100vw-3rem)] bg-white rounded-2xl shadow-2xl border border-border-light z-40 flex flex-col" style={{ maxHeight: '70vh' }}>
          {/* 头部 */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border-light bg-primary text-white rounded-t-2xl">
            <div className="flex items-center gap-2">
              <AppIcon className="fas fa-robot" />
              <span className="font-medium text-sm">AI 学习助手</span>
            </div>
            <button onClick={() => setOpen(false)} className="text-white/80 hover:text-white">
              <AppIcon className="fas fa-times" />
            </button>
          </div>

          {/* 消息区 */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3" style={{ minHeight: '200px' }}>
            {messages.length === 0 && (
              <div className="text-center py-4">
                <AppIcon className="fas fa-graduation-cap text-3xl text-primary/30 mb-2" />
                <p className="text-sm text-text-secondary">有任何关于课程的问题，随时问我！</p>
                <div className="mt-3 space-y-1.5">
                  {SUGGESTIONS.map(s => (
                    <button key={s} onClick={() => ask(s)}
                      className="block w-full text-left text-xs px-3 py-2 rounded-lg bg-bg-light text-text-secondary hover:bg-primary/5 hover:text-primary transition-colors">
                      💡 {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${m.role === 'user' ? 'bg-primary text-white rounded-br-sm' : 'bg-bg-light text-text-primary rounded-bl-sm'}`}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-bg-light px-3 py-2 rounded-2xl rounded-bl-sm">
                  <AppIcon className="fas fa-spinner fa-spin text-text-secondary text-sm" />
                </div>
              </div>
            )}
          </div>

          {/* 输入区 */}
          <div className="p-3 border-t border-border-light">
            <div className="flex gap-2">
              <input value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input); } }}
                placeholder="输入你的问题…" disabled={loading}
                className="flex-1 px-3 py-2 text-sm border border-border-light rounded-lg outline-none focus:border-primary disabled:bg-bg-light" />
              <button onClick={() => ask(input)} disabled={loading || !input.trim()}
                className="px-3 py-2 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                <AppIcon className="fas fa-paper-plane text-sm" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
