// @ts-nocheck
/**
 * 题库管理 — 按课程/分类分组 + 审核 + 筛选
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import { hrmApi, trainingExamApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断' };
const TYPE_TONES = { single: 'bg-primary/10 text-primary', multiple: 'bg-success/10 text-success', judge: 'bg-warning/10 text-warning' };
const REVIEW_LABELS = { pending: '待审核', approved: '已通过', rejected: '已驳回' };
const REVIEW_DOT = { pending: 'bg-warning', approved: 'bg-success', rejected: 'bg-danger' };

const normalizeKeyword = (value) => String(value || '').trim().toLowerCase();

export default function P_exam_center() {
  const navigate = useNavigate();
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [filterCourse, setFilterCourse] = useState('all');
  const [filterCategory, setFilterCategory] = useState('all');
  const [groupBy, setGroupBy] = useState('course');
  const [keyword, setKeyword] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const q = await hrmApi.list('exam-questions');
      setQuestions(q || []);
    } catch (e) {
      toast.error(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const stats = {
    total: questions.length,
    pending: questions.filter(q => q.reviewStatus === 'pending').length,
    approved: questions.filter(q => q.reviewStatus === 'approved').length,
    byType: {
      single: questions.filter(q => q.type === 'single').length,
      multiple: questions.filter(q => q.type === 'multiple').length,
      judge: questions.filter(q => q.type === 'judge').length,
    },
  };

  const courseOptions = [];
  const categoryOptions = [];
  const courseSeen = new Set();
  const categorySeen = new Set();
  questions.forEach(question => {
    if (question.courseId && question.courseTitle && !courseSeen.has(question.courseId)) {
      courseOptions.push({ value: question.courseId, label: question.courseTitle });
      courseSeen.add(question.courseId);
    }
    if (question.category && !categorySeen.has(question.category)) {
      categoryOptions.push({ value: question.category, label: question.category });
      categorySeen.add(question.category);
    }
  });
  courseOptions.sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
  categoryOptions.sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));

  const filtered = useMemo(() => {
    const q = normalizeKeyword(keyword);
    return questions.filter(item => {
      if (filterStatus !== 'all' && item.reviewStatus !== filterStatus) return false;
      if (filterType !== 'all' && item.type !== filterType) return false;
      if (filterCourse !== 'all' && item.courseId !== filterCourse) return false;
      if (filterCategory !== 'all' && item.category !== filterCategory) return false;
      if (q) {
        const haystack = [
          item.stem,
          item.category,
          item.courseTitle,
          item.type,
          item.reviewStatus,
        ].filter(Boolean).join(' ').toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [questions, filterStatus, filterType, filterCourse, filterCategory, keyword]);

  const grouped = useMemo(() => {
    const map = new Map();
    filtered.forEach(item => {
      const key = groupBy === 'category'
        ? (item.category || '未分类')
        : (item.courseTitle || '未关联课程');
      if (!map.has(key)) {
        map.set(key, []);
      }
      map.get(key).push(item);
    });
    return Array.from(map.entries())
      .map(([label, items]) => ({
        label,
        count: items.length,
        items: items.sort((a, b) => (a.category || '').localeCompare(b.category || '', 'zh-CN') || a.stem.localeCompare(b.stem, 'zh-CN')),
      }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'zh-CN'));
  }, [filtered, groupBy]);

  const approve = async (q) => {
    try {
      await trainingExamApi.approveQuestion(q.id);
      toast.success('已通过');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const reject = async (q) => {
    if (!await confirm('驳回该题？')) return;
    try {
      await trainingExamApi.rejectQuestion(q.id);
      toast.success('已驳回');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const batchApprove = async () => {
    const ids = questions.filter(q => q.reviewStatus === 'pending').map(q => q.id);
    if (!ids.length) { toast.info('没有待审核题目'); return; }
    if (!await confirm(`批量通过 ${ids.length} 道待审核题？`)) return;
    try {
      await trainingExamApi.batchApprove(ids);
      toast.success(`已通过 ${ids.length} 题`);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <PageHeader
          icon="fa-circle-dot"
          title="题库管理"
          subtitle="按课程或分类分组查看题目，先筛选再审核"
          actions={
            <>
              {stats.pending > 0 && (
                <button onClick={batchApprove} className="px-3 py-2 text-sm bg-success text-white rounded-lg hover:bg-green-700 flex items-center gap-1.5">
                  <AppIcon className="fas fa-check-double" /> 全部通过 ({stats.pending})
                </button>
              )}
              <button onClick={() => navigate('/exam-generate')} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
                <AppIcon className="fas fa-microchip" /> 智能出题
              </button>
            </>
          }
        />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatPill label="题目总数" value={stats.total} icon="fa-circle-dot" />
          <StatPill label="已通过" value={stats.approved} icon="fa-check" tone="success" />
          <StatPill label="待审核" value={stats.pending} icon="fa-clock" tone={stats.pending ? 'warning' : 'neutral'} />
          <StatPill label="题型分布" value={`${stats.byType.single}/${stats.byType.multiple}/${stats.byType.judge}`} icon="fa-shapes" tone="neutral" />
        </div>

        <div className="bg-white rounded-xl border border-border-light p-4 mb-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
            <input
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              placeholder="搜索题干、课程、分类"
              className="md:col-span-2 text-sm border border-border-light rounded-lg px-3 py-2 outline-none focus:border-primary"
            />
            <select value={filterCourse} onChange={e => setFilterCourse(e.target.value)} className="text-sm border border-border-light rounded-lg px-3 py-2 outline-none">
              <option value="all">全部课程</option>
              {courseOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} className="text-sm border border-border-light rounded-lg px-3 py-2 outline-none">
              <option value="all">全部分类</option>
              {categoryOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </div>

          <div className="flex flex-wrap gap-2">
            <div className="flex gap-1 bg-bg-light rounded-lg p-1">
              {['all', 'pending', 'approved', 'rejected'].map(f => (
                <button key={f} onClick={() => setFilterStatus(f)}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${filterStatus === f ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
                  {f === 'all' ? '全部' : REVIEW_LABELS[f]}
                </button>
              ))}
            </div>
            <div className="flex gap-1 bg-bg-light rounded-lg p-1">
              {['all', 'single', 'multiple', 'judge'].map(f => (
                <button key={f} onClick={() => setFilterType(f)}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${filterType === f ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
                  {f === 'all' ? '全题型' : TYPE_LABELS[f]}
                </button>
              ))}
            </div>
            <div className="flex gap-1 bg-bg-light rounded-lg p-1">
              <button onClick={() => setGroupBy('course')} className={`px-3 py-1.5 rounded-md text-sm transition-colors ${groupBy === 'course' ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary hover:text-text-primary'}`}>按课程分组</button>
              <button onClick={() => setGroupBy('category')} className={`px-3 py-1.5 rounded-md text-sm transition-colors ${groupBy === 'category' ? 'bg-white shadow-sm font-medium text-primary' : 'text-text-secondary hover:text-text-primary'}`}>按分类分组</button>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="fa-circle-dot"
            title={questions.length ? '没有匹配的题目' : '题库为空'}
            hint={questions.length ? undefined : '用「智能出题」从培训资料 AI 生成题目'}
            action={!questions.length ? <button onClick={() => navigate('/exam-generate')} className="text-sm text-primary hover:underline">前往智能出题</button> : null}
          />
        ) : (
          <div className="space-y-4">
            {grouped.map(group => (
              <section key={group.label} className="bg-white rounded-xl border border-border-light overflow-hidden">
                <div className="px-4 py-3 border-b border-border-light flex items-center justify-between">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-text-primary truncate">{group.label}</h3>
                    <div className="text-xs text-text-secondary mt-0.5">{group.count} 题</div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-text-secondary shrink-0">
                    <span>{group.items.filter(item => item.reviewStatus === 'pending').length} 待审</span>
                    <span>{group.items.filter(item => item.reviewStatus === 'approved').length} 已审</span>
                  </div>
                </div>
                <div className="divide-y divide-border-light">
                  {group.items.map(q => (
                    <div key={q.id} className="p-4">
                      <div className="flex items-start gap-3">
                        <span className={`shrink-0 px-2 py-1 rounded text-xs font-medium ${TYPE_TONES[q.type] || 'bg-bg-light text-text-secondary'}`}>{TYPE_LABELS[q.type] || q.type}</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-text-primary font-medium leading-relaxed">{q.stem}</div>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-text-secondary">
                            <span><AppIcon className="fas fa-star text-xs" /> {q.score} 分</span>
                            <span>难度 {'★'.repeat(q.difficulty || 1)}</span>
                            {q.source === 'ai' && <span className="flex items-center gap-1 text-info"><AppIcon className="fas fa-microchip text-xs" /> AI 生成</span>}
                            <span className="flex items-center gap-1"><span className={`w-1.5 h-1.5 rounded-full ${REVIEW_DOT[q.reviewStatus]}`} />{REVIEW_LABELS[q.reviewStatus]}</span>
                            {q.courseTitle && <span>{q.courseTitle}</span>}
                            {q.category && <span>{q.category}</span>}
                          </div>
                          {q.explanation && <div className="mt-1.5 text-xs text-text-secondary bg-bg-light/50 rounded px-2 py-1 line-clamp-2">解析：{q.explanation}</div>}
                        </div>
                        {q.reviewStatus === 'pending' && (
                          <div className="flex gap-1.5 shrink-0">
                            <button onClick={() => approve(q)} className="px-3 py-1 text-xs text-success border border-success/30 rounded-lg hover:bg-success/5 flex items-center gap-1">
                              <AppIcon className="fas fa-check text-xs" /> 通过
                            </button>
                            <button onClick={() => reject(q)} className="px-3 py-1 text-xs text-danger border border-danger/30 rounded-lg hover:bg-danger/5 flex items-center gap-1">
                              <AppIcon className="fas fa-times text-xs" /> 驳回
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
