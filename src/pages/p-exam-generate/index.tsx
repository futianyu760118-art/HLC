// @ts-nocheck
/**
 * AI 出题页（Chunk 7）
 * 选课程或粘贴资料 → AI 生成题目 → 逐题审核 → 批量入库
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { hrmApi, trainingExamApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS: Record<string, string> = { single: '单选', multiple: '多选', judge: '判断' };

export default function P_exam_generate() {
  const [courses, setCourses] = useState<any[]>([]);
  const [courseId, setCourseId] = useState('');
  const [sourceText, setSourceText] = useState('');
  const [count, setCount] = useState(5);
  const [types, setTypes] = useState<string[]>(['single', 'multiple', 'judge']);
  const [loading, setLoading] = useState(false);
  const [generated, setGenerated] = useState<any[]>([]);

  useEffect(() => {
    hrmApi.list('courses').then((rows: any[]) => setCourses(rows || [])).catch(() => {});
  }, []);

  const toggleType = (t: string) => {
    setTypes(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  };

  const handleGenerate = async () => {
    if (types.length === 0) { toast.error('至少选一种题型'); return; }
    if (!sourceText.trim() && !courseId) { toast.error('请选择课程或粘贴资料'); return; }
    setLoading(true);
    try {
      const res = await trainingExamApi.generateQuestions({
        courseId: courseId || undefined,
        sourceText: sourceText.trim() || undefined,
        count, types,
      });
      setGenerated(res.questions || []);
      toast.success(`生成 ${res.count} 道题，请审核`);
    } catch (e: any) {
      toast.error(e.message || '生成失败');
    } finally {
      setLoading(false);
    }
  };

  const editField = (idx: number, field: string, value: any) => {
    setGenerated(prev => prev.map((q, i) => i === idx ? { ...q, [field]: value } : q));
  };

  const approveOne = async (q: any) => {
    if (!q.stem?.trim()) { toast.error('题干不能为空'); return; }
    if (!q.answer?.length) { toast.error('请选择正确答案'); return; }
    try {
      await trainingExamApi.approveQuestion(q.id);
      toast.success('已通过');
      setGenerated(prev => prev.map(x => x.id === q.id ? { ...x, reviewStatus: 'approved' } : x));
    } catch (e: any) { toast.error(e.message || '操作失败'); }
  };

  const rejectOne = async (q: any) => {
    try {
      await trainingExamApi.rejectQuestion(q.id);
      setGenerated(prev => prev.filter(x => x.id !== q.id));
      toast.success('已驳回');
    } catch (e: any) { toast.error(e.message || '操作失败'); }
  };

  const batchApprove = async () => {
    const pending = generated.filter(q => q.reviewStatus === 'pending');
    if (!pending.length) { toast.info('没有待审核题目'); return; }
    // 逐题校验完整性，剔除不合格的
    const valid = pending.filter(q => q.stem?.trim() && q.answer?.length);
    const invalid = pending.length - valid.length;
    if (!valid.length) { toast.error('待审核题目均不完整（题干/答案缺失），无法批量通过'); return; }
    const ids = valid.map(q => q.id);
    try {
      await trainingExamApi.batchApprove(ids);
      toast.success(`批量通过 ${ids.length} 题${invalid ? `，跳过 ${invalid} 题不完整` : ''}`);
      setGenerated(prev => prev.map(q => ids.includes(q.id) ? { ...q, reviewStatus: 'approved' } : q));
    } catch (e: any) { toast.error(e.message || '操作失败'); }
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex items-center gap-3">
          <AppIcon className="fas fa-wand-magic-sparkles text-2xl text-purple-500" />
          <h1 className="text-2xl font-bold">AI 出题</h1>
        </div>

        {/* 配置区 */}
        <div className="bg-white rounded-lg shadow p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">关联课程（可选，自动取课程资料）</label>
            <select value={courseId} onChange={e => setCourseId(e.target.value)}
              className="w-full border rounded px-3 py-2">
              <option value="">不关联课程</option>
              {courses.map((c: any) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">或粘贴培训资料（与课程二选一或补充）</label>
            <textarea value={sourceText} onChange={e => setSourceText(e.target.value)} rows={6}
              placeholder="粘贴培训文档、规范、讲义文本……AI 会据此出题"
              className="w-full border rounded px-3 py-2 font-mono text-sm" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">题目数量</label>
              <input type="number" min={1} max={20} value={count}
                aria-label="题目数量"
                onChange={e => setCount(Math.max(1, Math.min(20, +e.target.value || 5)))}
                className="w-full border rounded px-3 py-2" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">题型</label>
              <div className="flex gap-3 pt-2">
                {(['single', 'multiple', 'judge'] as const).map(t => (
                  <label key={t} className="flex items-center gap-1">
                    <input type="checkbox" aria-label={`选择${TYPE_LABELS[t]}题型`} checked={types.includes(t)} onChange={() => toggleType(t)} />
                    {TYPE_LABELS[t]}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <button onClick={handleGenerate} disabled={loading}
            className="bg-purple-600 text-white px-5 py-2 rounded hover:bg-purple-700 disabled:opacity-50 flex items-center gap-2">
            {loading ? <><AppIcon className="fas fa-spinner fa-spin" /> 生成中…</> : <><AppIcon className="fas fa-magic" /> 生成题目</>}
          </button>
        </div>

        {/* 生成结果 */}
        {generated.length > 0 && (
          <div className="bg-white rounded-lg shadow p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">生成结果（{generated.length} 题）</h2>
              <button onClick={batchApprove}
                className="bg-green-600 text-white px-4 py-1.5 rounded text-sm hover:bg-green-700">
                全部通过
              </button>
            </div>
            {generated.map((q, idx) => (
              <div key={q.id || idx} className="border rounded p-4 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{TYPE_LABELS[q.type] || q.type}</span>
                  <select value={q.difficulty} onChange={e => editField(idx, 'difficulty', +e.target.value)}
                    className="text-xs border rounded px-1 py-0.5">
                    {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>难度 {n}</option>)}
                  </select>
                  {q.reviewStatus === 'approved' && <span className="text-xs text-green-600">已通过</span>}
                </div>
                <textarea value={q.stem} onChange={e => editField(idx, 'stem', e.target.value)} rows={2}
                  className="w-full border rounded px-2 py-1 text-sm" />
                {q.type !== 'judge' && (
                  <div className="space-y-1">
                    {(q.options || []).map((opt: string, oi: number) => (
                      <div key={oi} className="flex items-center gap-2 text-sm">
                        <label className="flex items-center gap-1 cursor-pointer">
                          <input type={q.type === 'multiple' ? 'checkbox' : 'radio'} name={`ans-${idx}`}
                            checked={(q.answer || []).includes(oi)}
                            onChange={() => {
                              if (q.type === 'multiple') {
                                const next = (q.answer || []).includes(oi) ? (q.answer || []).filter((x: number) => x !== oi) : [...(q.answer || []), oi];
                                editField(idx, 'answer', next);
                              } else {
                                editField(idx, 'answer', [oi]);
                              }
                            }} />
                          <span className="w-6 text-gray-400">{String.fromCharCode(65 + oi)}.</span>
                        </label>
                        <input value={opt} onChange={e => {
                          const next = [...q.options]; next[oi] = e.target.value;
                          editField(idx, 'options', next);
                        }} className="flex-1 border rounded px-2 py-1" />
                      </div>
                    ))}
                  </div>
                )}
                {q.type === 'judge' && (
                  <div className="flex items-center gap-4 text-sm">
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input type="radio" name={`ans-${idx}`} checked={(q.answer || [])[0] === 0}
                        onChange={() => editField(idx, 'answer', [0])} /> 正确
                    </label>
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input type="radio" name={`ans-${idx}`} checked={(q.answer || [])[0] === 1}
                        onChange={() => editField(idx, 'answer', [1])} /> 错误
                    </label>
                  </div>
                )}
                <textarea value={q.explanation || ''} onChange={e => editField(idx, 'explanation', e.target.value)} rows={1}
                  placeholder="解析（可选）" className="w-full border rounded px-2 py-1 text-xs" />
                {q.reviewStatus === 'pending' && (
                  <div className="flex gap-2 pt-1">
                    <button onClick={() => approveOne(q)} className="bg-green-600 text-white px-3 py-1 rounded text-xs">通过</button>
                    <button onClick={() => rejectOne(q)} className="bg-red-500 text-white px-3 py-1 rounded text-xs">驳回</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
