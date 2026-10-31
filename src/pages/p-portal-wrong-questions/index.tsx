// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 错题本（员工门户）— 错题回顾 + 收藏 + 重练掌握
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';
import apiClient from '../../utils/api';

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断' };
const TYPE_TONES = { single: 'bg-primary/10 text-primary', multiple: 'bg-success/10 text-success', judge: 'bg-warning/10 text-warning' };

export default function P_portal_wrong_questions() {
  const [data, setData] = useState({ items: [], stats: { total: 0, wrong: 0, mastered: 0, favorited: 0 } });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'wrong' | 'mastered' | 'all'>('wrong');
  const [onlyFav, setOnlyFav] = useState(false);
  const [practicing, setPracticing] = useState(false);
  const [practiceAnswers, setPracticeAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ mastery: filter });
      if (onlyFav) params.set('favorited', '1');
      const r = await apiClient.get(`/portal/wrong-questions?${params}`);
      setData(r);
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [filter, onlyFav]);

  const toggleFav = async (id) => {
    if (busyId) return;
    setBusyId(id);
    try { await apiClient.post(`/portal/wrong-questions/${id}/favorite`, {}); load(); }
    catch (e) { toast.error(e.message); }
    finally { setBusyId(null); }
  };
  const toggleMaster = async (id) => {
    if (busyId) return;
    setBusyId(id);
    try { await apiClient.post(`/portal/wrong-questions/${id}/master`, {}); load(); }
    catch (e) { toast.error(e.message); }
    finally { setBusyId(null); }
  };

  const startPractice = () => {
    setPracticing(true);
    setPracticeAnswers({});
  };
  const exitPractice = () => {
    setPracticing(false);
    setPracticeAnswers({});
  };
  const submitPractice = async () => {
    const answered = Object.keys(practiceAnswers).filter(k => practiceAnswers[k]?.length > 0).length;
    if (answered === 0) { toast.error('请至少作答一题'); return; }
    if (submitting) return;
    setSubmitting(true);
    try {
      const r = await apiClient.post('/portal/wrong-questions/practice', { answers: practiceAnswers });
      toast.success(`重练完成，${r.mastered?.length || 0} 题已掌握`);
      setPracticing(false);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSubmitting(false); }
  };

  const toggleAnswer = (qid, idx, multi) => {
    setPracticeAnswers(prev => {
      const cur = prev[qid] || [];
      if (multi) return { ...prev, [qid]: cur.includes(idx) ? cur.filter(i => i !== idx) : [...cur, idx] };
      return { ...prev, [qid]: [idx] };
    });
  };

  const items = data.items || [];
  const stats = data.stats || {};

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-bookmark" title="错题本" subtitle="回顾错题，针对性重练掌握"
          actions={!practicing && items.length > 0 ? (
            <button onClick={startPractice} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
              <AppIcon className="fas fa-redo" /> 开始重练
            </button>
          ) : practicing ? (
            <div className="flex items-center gap-2">
              <button onClick={exitPractice} className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 flex items-center gap-1.5">
                <AppIcon className="fas fa-times" /> 退出重练
              </button>
              <button onClick={submitPractice} disabled={submitting} className="px-4 py-2 text-sm bg-success text-white rounded-lg hover:bg-green-700 flex items-center gap-1.5 disabled:opacity-50">
                <AppIcon className="fas fa-check" /> {submitting ? '提交中…' : '提交重练'}
              </button>
            </div>
          ) : null} />

        <div className="grid grid-cols-4 gap-3 mb-5">
          <StatPill label="错题总数" value={stats.total} icon="fa-bookmark" />
          <StatPill label="待掌握" value={stats.wrong} icon="fa-circle-exclamation" tone="warning" />
          <StatPill label="已掌握" value={stats.mastered} icon="fa-check" tone="success" />
          <StatPill label="已收藏" value={stats.favorited} icon="fa-star" tone="neutral" />
        </div>

        {/* 筛选 */}
        {!practicing && (
          <div className="flex items-center gap-3 mb-4">
            <div className="flex gap-1 bg-bg-light rounded-lg p-1">
              {(['wrong', 'mastered', 'all'] as const).map(f => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${filter === f ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
                  {f === 'wrong' ? '待掌握' : f === 'mastered' ? '已掌握' : '全部'}
                </button>
              ))}
            </div>
            <button onClick={() => setOnlyFav(!onlyFav)}
              className={`px-3 py-1.5 rounded-lg text-sm border flex items-center gap-1 ${onlyFav ? 'border-warning bg-warning/10 text-warning' : 'border-border-light text-text-secondary'}`}>
              <AppIcon className="fas fa-star" /> 仅看收藏
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : items.length === 0 ? (
          <EmptyState icon="fa-bookmark" title={filter === 'wrong' ? '没有待掌握的错题' : '暂无错题'}
            hint={filter === 'wrong' ? '继续保持！' : '参加考试后，做错的题目会自动收录到这里'} />
        ) : practicing ? (
          /* 重练模式 */
          <div className="space-y-3">
            {items.map((q, i) => {
              const multi = q.type === 'multiple';
              const sel = practiceAnswers[q.id] || [];
              return (
                <div key={q.id} className="bg-white rounded-xl border border-border-light p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${TYPE_TONES[q.type]}`}>{TYPE_LABELS[q.type]}</span>
                    <span className="text-xs text-text-secondary">第 {i + 1} 题</span>
                    <span className="text-xs text-danger">错 {q.wrongCount} 次</span>
                  </div>
                  <div className="text-sm text-text-primary mb-3">{q.stem}</div>
                  <div className="space-y-1.5">
                    {(q.options || []).map((opt, oi) => {
                      const checked = sel.includes(oi);
                      return (
                        <label key={oi} className={`flex items-center gap-2 border rounded px-3 py-2 cursor-pointer text-sm ${checked ? 'border-primary bg-primary/5' : 'border-border-light hover:bg-bg-light'}`}>
                          <input type={multi ? 'checkbox' : 'radio'} name={`wq-${q.id}`} checked={checked} onChange={() => toggleAnswer(q.id, oi, multi)} />
                          <span className="font-medium text-text-secondary">{String.fromCharCode(65 + oi)}.</span>
                          <span>{opt}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          /* 浏览模式：显示错题 + 正确答案 + 解析 */
          <div className="space-y-3">
            {items.map((q) => (
              <div key={q.id} className="bg-white rounded-xl border border-border-light p-4">
                <div className="flex items-start gap-3">
                  <span className={`shrink-0 px-2 py-1 rounded text-xs ${TYPE_TONES[q.type]}`}>{TYPE_LABELS[q.type]}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-text-primary font-medium leading-relaxed">{q.stem}</div>
                    {/* 选项 + 标注对错 */}
                    <div className="mt-2 space-y-1">
                      {(q.options || []).map((opt, oi) => {
                        const isCorrect = (q.answer || []).includes(oi);
                        const isUserWrong = (q.userAnswer || []).includes(oi) && !isCorrect;
                        return (
                          <div key={oi} className={`text-sm px-2 py-1 rounded ${isCorrect ? 'bg-success/10 text-success' : isUserWrong ? 'bg-danger/10 text-danger' : 'text-text-secondary'}`}>
                            <span className="font-medium">{String.fromCharCode(65 + oi)}.</span> {opt}
                            {isCorrect && <span className="ml-2">✓ 正确答案</span>}
                            {isUserWrong && <span className="ml-2">✗ 你的选择</span>}
                          </div>
                        );
                      })}
                    </div>
                    {q.explanation && (
                      <div className="mt-2 text-xs text-text-secondary bg-bg-light/50 rounded px-2 py-1.5">解析：{q.explanation}</div>
                    )}
                    <div className="mt-2 flex items-center gap-3">
                      <span className="text-xs text-text-secondary">累计错 {q.wrongCount} 次</span>
                      {q.category && <span className="text-xs text-text-secondary">{q.category}</span>}
                    </div>
                  </div>
                  {/* 操作 */}
                  <div className="flex flex-col gap-1 shrink-0">
                    <button onClick={() => toggleFav(q.id)} disabled={busyId === q.id} title="收藏"
                      className={`w-7 h-7 rounded flex items-center justify-center disabled:opacity-40 ${q.isFavorited ? 'text-warning' : 'text-text-secondary hover:text-warning'}`}>
                      <AppIcon className={`fas fa-star text-xs`} />
                    </button>
                    <button onClick={() => toggleMaster(q.id)} disabled={busyId === q.id} title={q.mastery === 'wrong' ? '标记已掌握' : '取消掌握'}
                      className={`w-7 h-7 rounded flex items-center justify-center disabled:opacity-40 ${q.mastery === 'mastered' ? 'text-success' : 'text-text-secondary hover:text-success'}`}>
                      <AppIcon className="fas fa-check text-xs" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
