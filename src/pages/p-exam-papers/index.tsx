// @ts-nocheck
/**
 * 试卷组卷 — 支持固定题与题池随机抽题
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState, StatusBadge } from '../../components/PageParts';
import { hrmApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断' };
const STATUS_MAP = {
  draft: { label: '草稿', tone: 'neutral' },
  published: { label: '已发布', tone: 'success' },
  archived: { label: '已归档', tone: 'neutral' },
};
const QUESTION_MODE_LABELS = { fixed: '固定试卷', random: '随机抽题' };

const normalizeKeyword = (value) => String(value || '').trim().toLowerCase();

const questionMeta = (question) => {
  const parts = [];
  if (question.courseTitle) parts.push(question.courseTitle);
  if (question.category) parts.push(question.category);
  return parts.join(' / ');
};

export default function P_exam_papers() {
  const [papers, setPapers] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [p, q] = await Promise.all([hrmApi.list('exam-papers'), hrmApi.list('exam-questions')]);
      setPapers(p || []);
      setQuestions((q || []).filter(item => item.reviewStatus === 'approved'));
    } catch (e) {
      toast.error(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const remove = async (paper) => {
    if (!await confirm(`删除试卷「${paper.title}」？`)) return;
    try {
      await hrmApi.remove('exam-papers', paper.id);
      toast.success('已删除');
      load();
    } catch (e) {
      toast.error(e.message || '删除失败');
    }
  };

  if (editing) {
    return <PaperEditor paper={editing} questions={questions} onBack={() => { setEditing(null); load(); }} />;
  }

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <PageHeader
          icon="fa-file-lines"
          title="试卷组卷"
          subtitle="先建立题池，再决定是固定出题还是随机抽题"
          actions={
            <button
              onClick={() => setEditing({
                title: '',
                description: '',
                questionIds: [],
                questionMode: 'fixed',
                drawCount: null,
                totalScore: 0,
                passScore: 60,
                durationMinutes: 30,
                status: 'draft',
                shuffle: false,
              })}
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5"
            >
              <AppIcon className="fas fa-plus" /> 新建试卷
            </button>
          }
        />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatPill label="试卷总数" value={papers.length} icon="fa-file-lines" />
          <StatPill label="已发布" value={papers.filter(p => p.status === 'published').length} icon="fa-check" tone="success" />
          <StatPill label="草稿" value={papers.filter(p => p.status === 'draft').length} icon="fa-pen" tone="warning" />
          <StatPill label="可用题目" value={questions.length} icon="fa-circle-dot" tone="neutral" />
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : papers.length === 0 ? (
          <EmptyState icon="fa-file-lines" title="还没有试卷" hint="新建第一份试卷，从题库中选题组卷" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {papers.map(paper => {
              const poolCount = (paper.questionIds || []).length;
              const questionMode = paper.questionMode || 'fixed';
              const drawCount = Number(paper.drawCount || 0);
              const examCount = questionMode === 'random' ? drawCount : poolCount;
              return (
                <div key={paper.id} className="group bg-white rounded-xl border border-border-light p-5 hover:shadow-card transition-shadow">
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-11 h-11 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                      <AppIcon className={`fas ${questionMode === 'random' ? 'fa-shuffle' : 'fa-file-lines'} text-primary`} />
                    </div>
                    <StatusBadge status={paper.status} map={STATUS_MAP} />
                  </div>
                  <h3 className="font-semibold text-text-primary line-clamp-1">{paper.title}</h3>
                  {paper.description && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{paper.description}</p>}
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-1 rounded bg-bg-light text-text-secondary">{QUESTION_MODE_LABELS[questionMode] || '固定试卷'}</span>
                    {questionMode === 'random' ? (
                      <span className="px-2 py-1 rounded bg-warning/10 text-warning">题池 {poolCount} 抽 {examCount}</span>
                    ) : (
                      <span className="px-2 py-1 rounded bg-success/10 text-success">固定 {examCount} 题</span>
                    )}
                    {paper.shuffle && <span className="px-2 py-1 rounded bg-primary/10 text-primary">题序乱序</span>}
                  </div>
                  <div className="mt-3 pt-3 border-t border-border-light flex flex-wrap items-center gap-3 text-xs text-text-secondary">
                    <span className="flex items-center gap-1"><AppIcon className="fas fa-list-ol" /> 出题 {examCount} 题</span>
                    <span className="flex items-center gap-1"><AppIcon className="fas fa-layer-group" /> 题池 {poolCount} 题</span>
                    <span className="flex items-center gap-1"><AppIcon className="fas fa-star" /> {paper.totalScore} 分</span>
                    <span>及格 {paper.passScore}</span>
                    {paper.durationMinutes && <span>{paper.durationMinutes} 分钟</span>}
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <button onClick={() => setEditing(paper)} className="flex-1 text-sm py-1.5 border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                      <AppIcon className="fas fa-pen text-xs" /> 组卷
                    </button>
                    <button onClick={() => remove(paper)} className="w-8 h-8 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center">
                      <AppIcon className="fas fa-trash text-xs" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
}

function PaperEditor({ paper, questions, onBack }) {
  const [title, setTitle] = useState(paper.title || '');
  const [description, setDescription] = useState(paper.description || '');
  const [questionMode, setQuestionMode] = useState(paper.questionMode || 'fixed');
  const [passScore, setPassScore] = useState(paper.passScore || 60);
  const [duration, setDuration] = useState(paper.durationMinutes || 30);
  const [shuffle, setShuffle] = useState(paper.shuffle || false);
  const [selectedIds, setSelectedIds] = useState(paper.questionIds || []);
  const [drawCount, setDrawCount] = useState(paper.drawCount || '');
  const [randomTotalScore, setRandomTotalScore] = useState(paper.totalScore || '');
  const [filterType, setFilterType] = useState('all');
  const [filterCourse, setFilterCourse] = useState('all');
  const [filterCategory, setFilterCategory] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [saving, setSaving] = useState(false);

  const selectedSet = new Set(selectedIds);
  const selectedQuestions = questions.filter(question => selectedSet.has(question.id));
  const fixedTotalScore = selectedQuestions.reduce((sum, question) => sum + Number(question.score || 0), 0);
  const effectiveTotalScore = questionMode === 'random' ? Number(randomTotalScore || 0) : fixedTotalScore;
  const effectiveQuestionCount = questionMode === 'random' ? Number(drawCount || 0) : selectedIds.length;
  const avgRandomScore = questionMode === 'random' && Number(drawCount || 0) > 0
    ? (Number(randomTotalScore || 0) / Number(drawCount || 0))
    : 0;
  const normalizedKeyword = normalizeKeyword(keyword);

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

  const availableQuestions = questions.filter(question => {
    if (filterType !== 'all' && question.type !== filterType) return false;
    if (filterCourse !== 'all' && question.courseId !== filterCourse) return false;
    if (filterCategory !== 'all' && question.category !== filterCategory) return false;
    if (normalizedKeyword) {
      const haystack = [
        question.stem,
        question.category,
        question.courseTitle,
        TYPE_LABELS[question.type],
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(normalizedKeyword)) return false;
    }
    return true;
  });

  const toggle = (questionId) => {
    setSelectedIds(prev => prev.includes(questionId) ? prev.filter(item => item !== questionId) : [...prev, questionId]);
  };

  const switchMode = (nextMode) => {
    setQuestionMode(nextMode);
    if (nextMode === 'random') {
      if (!drawCount) setDrawCount(selectedIds.length || '');
      if (!randomTotalScore && fixedTotalScore > 0) setRandomTotalScore(fixedTotalScore);
    }
  };

  const save = async (status) => {
    if (!title.trim()) { toast.error('请输入试卷名称'); return; }
    if (selectedIds.length === 0) { toast.error('请至少选择一道题'); return; }
    if (!Number(duration) || Number(duration) <= 0) { toast.error('答题时长须大于 0'); return; }
    if (!Number(passScore) || Number(passScore) <= 0) { toast.error('及格分须大于 0'); return; }

    if (questionMode === 'random') {
      if (!Number(drawCount) || Number(drawCount) <= 0) { toast.error('请设置随机抽题数量'); return; }
      if (Number(drawCount) > selectedIds.length) { toast.error('抽题数量不能超过题池数量'); return; }
      if (!Number(randomTotalScore) || Number(randomTotalScore) <= 0) { toast.error('随机试卷请填写总分'); return; }
      if (Number(passScore) > Number(randomTotalScore)) { toast.error('及格分不能超过总分'); return; }
    } else if (Number(passScore) > fixedTotalScore) {
      toast.error('及格分不能超过总分');
      return;
    }

    setSaving(true);
    try {
      const data = {
        title: title.trim(),
        description,
        questionIds: selectedIds,
        questionMode,
        drawCount: questionMode === 'random' ? Number(drawCount) : null,
        totalScore: questionMode === 'random' ? Number(randomTotalScore) : fixedTotalScore,
        passScore: Number(passScore),
        durationMinutes: Number(duration),
        shuffle,
        status,
      };
      if (paper.id) await hrmApi.update('exam-papers', paper.id, data);
      else await hrmApi.create('exam-papers', data);
      toast.success('已保存');
      onBack();
    } catch (e) {
      toast.error(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <button onClick={onBack} className="text-sm text-text-secondary hover:text-primary mb-4 flex items-center gap-1">
          <AppIcon className="fas fa-arrow-left text-xs" /> 返回试卷列表
        </button>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          <div className="lg:col-span-3">
            <div className="bg-white rounded-xl border border-border-light overflow-hidden">
              <div className="px-4 py-3 border-b border-border-light space-y-3">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                  <div>
                    <h2 className="font-semibold text-text-primary">题库选题</h2>
                    <div className="text-xs text-text-secondary mt-1">先缩小范围，再把合适的题加入题池</div>
                  </div>
                  <div className="text-xs text-text-secondary">当前筛到 {availableQuestions.length} 题，已入池 {selectedIds.length} 题</div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                  <input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="搜索题干 / 分类 / 课程" className="md:col-span-2 text-sm border border-border-light rounded-lg px-3 py-2 outline-none focus:border-primary" />
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
                  {['all', 'single', 'multiple', 'judge'].map(type => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setFilterType(type)}
                      className={`px-3 py-1.5 rounded-lg text-sm ${filterType === type ? 'bg-primary text-white' : 'border border-border-light text-text-secondary hover:text-text-primary'}`}
                    >
                      {type === 'all' ? '全部题型' : TYPE_LABELS[type]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="max-h-[62vh] overflow-y-auto divide-y divide-border-light">
                {availableQuestions.length === 0 ? (
                  <div className="text-center py-10 text-text-secondary text-sm">当前筛选条件下没有题目</div>
                ) : availableQuestions.map(question => {
                  const checked = selectedSet.has(question.id);
                  return (
                    <label key={question.id} className={`flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors ${checked ? 'bg-primary/5' : 'hover:bg-bg-light'}`}>
                      <input type="checkbox" checked={checked} onChange={() => toggle(question.id)} className="mt-1" />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <span className="text-xs px-1.5 py-0.5 rounded bg-bg-light text-text-secondary">{TYPE_LABELS[question.type]}</span>
                          <span className="text-xs text-text-secondary">{question.score} 分</span>
                          {question.category ? <span className="text-xs text-text-secondary">{question.category}</span> : null}
                        </div>
                        <div className="text-sm text-text-primary line-clamp-2">{question.stem}</div>
                        <div className="mt-1 text-xs text-text-secondary line-clamp-1">{questionMeta(question) || '未分类题目'}</div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-xl border border-border-light p-4 space-y-3">
              <h2 className="font-semibold text-text-primary">试卷信息</h2>
              <input value={title} onChange={e => setTitle(e.target.value)} placeholder="试卷名称" className="w-full px-3 py-2 border border-border-light rounded-lg outline-none focus:border-primary text-sm" />
              <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="试卷说明（可选）" rows={2} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm resize-none" />

              <div>
                <label className="block text-xs text-text-secondary mb-1">出题方式</label>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => switchMode('fixed')} className={`px-3 py-2 rounded-lg text-sm ${questionMode === 'fixed' ? 'bg-primary text-white' : 'border border-border-light text-text-secondary'}`}>
                    固定试卷
                  </button>
                  <button type="button" onClick={() => switchMode('random')} className={`px-3 py-2 rounded-lg text-sm ${questionMode === 'random' ? 'bg-primary text-white' : 'border border-border-light text-text-secondary'}`}>
                    随机抽题
                  </button>
                </div>
              </div>

              {questionMode === 'random' && (
                <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-warning">
                  员工开始考试时，系统会从当前题池里随机抽题并冻结成个人试卷。
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                {questionMode === 'random' ? (
                  <>
                    <div>
                      <label className="text-xs text-text-secondary">题池抽题数</label>
                      <input type="number" min={1} max={selectedIds.length || undefined} step={1} value={drawCount} onChange={e => setDrawCount(e.target.value)} className="w-full px-2 py-1.5 border border-border-light rounded-lg outline-none text-sm" />
                    </div>
                    <div>
                      <label className="text-xs text-text-secondary">试卷总分</label>
                      <input type="number" min={1} step={1} value={randomTotalScore} onChange={e => setRandomTotalScore(e.target.value)} className="w-full px-2 py-1.5 border border-border-light rounded-lg outline-none text-sm" />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="text-xs text-text-secondary">固定题数</label>
                      <div className="w-full px-2 py-1.5 border border-border-light rounded-lg text-sm bg-bg-light text-text-primary">{selectedIds.length}</div>
                    </div>
                    <div>
                      <label className="text-xs text-text-secondary">试卷总分</label>
                      <div className="w-full px-2 py-1.5 border border-border-light rounded-lg text-sm bg-bg-light text-text-primary">{fixedTotalScore}</div>
                    </div>
                  </>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-text-secondary">及格分</label>
                  <input type="number" min={1} max={effectiveTotalScore || undefined} step={1} value={passScore} onChange={e => setPassScore(e.target.value)} className="w-full px-2 py-1.5 border border-border-light rounded-lg outline-none text-sm" />
                </div>
                <div>
                  <label className="text-xs text-text-secondary">时长(分钟)</label>
                  <input type="number" min={1} step={1} value={duration} onChange={e => setDuration(e.target.value)} className="w-full px-2 py-1.5 border border-border-light rounded-lg outline-none text-sm" />
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-text-primary">
                <input type="checkbox" checked={shuffle} onChange={e => setShuffle(e.target.checked)} /> 题目展示顺序乱序
              </label>

              <div className="pt-3 border-t border-border-light space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">题池</span>
                  <span className="text-text-primary">{selectedIds.length} 题</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">实际出题</span>
                  <span className="text-text-primary">{effectiveQuestionCount || 0} 题</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">试卷总分</span>
                  <span className="text-text-primary">{effectiveTotalScore || 0} 分</span>
                </div>
                {questionMode === 'random' && Number(drawCount || 0) > 0 && Number(randomTotalScore || 0) > 0 && (
                  <div className="text-xs text-text-secondary">每道抽中题约 {avgRandomScore.toFixed(2)} 分</div>
                )}
              </div>

              {selectedQuestions.length > 0 && (
                <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                  {selectedQuestions.slice(0, 12).map(question => (
                    <span key={question.id} className="px-2 py-1 rounded bg-primary/10 text-primary text-xs line-clamp-1">
                      {question.stem}
                    </span>
                  ))}
                  {selectedQuestions.length > 12 && <span className="px-2 py-1 rounded bg-bg-light text-text-secondary text-xs">还有 {selectedQuestions.length - 12} 题</span>}
                </div>
              )}

              <div className="flex gap-2">
                <button onClick={() => save('draft')} disabled={saving} className="flex-1 py-2 text-sm border border-border-light rounded-lg text-text-secondary hover:bg-bg-light">存草稿</button>
                <button onClick={() => save('published')} disabled={saving} className="flex-1 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">保存并发布</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
