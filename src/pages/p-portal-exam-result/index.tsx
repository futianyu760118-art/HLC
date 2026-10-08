// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 考试结果页（Chunk 8）：总分/通过 + 逐题回顾（正确答案/解析）
 */
import React, { useEffect, useState } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS: Record<string, string> = { single: '单选', multiple: '多选', judge: '判断' };

export default function P_portal_exam_result() {
  const { attemptId } = useParams();
  const location = useLocation() as any;
  const navigate = useNavigate();
  const [result, setResult] = useState<any>(location.state || null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!result) {
      portalApi.examResult(attemptId).then(setResult).catch(() => setLoadError(true));
    }
  }, [attemptId]);

  if (loadError) return <Layout><div className="p-10 text-center"><p className="text-red-500 mb-3">加载考试结果失败</p><button onClick={() => navigate('/portal/my-exams')} className="text-sm text-primary hover:underline">返回考试列表 →</button></div></Layout>;
  if (!result) return <Layout><div className="p-10 text-center text-gray-400">加载中…</div></Layout>;

  const passRate = result.totalScore ? (result.score / result.totalScore * 100).toFixed(1) : '0';

  return (
    <Layout>
      <div className="max-w-3xl mx-auto p-6 space-y-4">
        <button onClick={() => navigate('/portal')} className="text-gray-500 hover:text-gray-700 text-sm">← 返回学习中心</button>

        {/* 成绩头部 */}
        <div className={`rounded-lg shadow p-6 text-center ${result.passed ? 'bg-green-50' : 'bg-red-50'}`}>
          <AppIcon className={`fas ${result.passed ? 'fa-trophy text-green-500' : 'fa-times-circle text-red-500'} text-5xl mb-2`} />
          <div className={`text-3xl font-bold ${result.passed ? 'text-green-700' : 'text-red-700'}`}>
            {result.passed ? '恭喜通过' : '未通过'}
          </div>
          <div className="mt-2 text-gray-600">
            得分 <span className="font-bold text-2xl">{result.score}</span> / {result.totalScore}（{passRate}%）· 及格分 {result.passScore}
          </div>
        </div>

        {/* 答题回顾 */}
        <div className="bg-white rounded-lg shadow p-5">
          <h2 className="font-semibold mb-3">答题回顾</h2>
          {(result.questions || []).map((q, i) => {
            const userAns = (q.userAnswer || []).map((idx: number) => String.fromCharCode(65 + idx));
            const correctAns = (q.answer || []).map((idx: number) => String.fromCharCode(65 + idx));
            const correct = q.correct;
            return (
              <div key={q.id || i} className={`border rounded p-3 mb-3 ${correct ? 'border-green-200' : 'border-red-200'}`}>
                <div className="flex items-start gap-2 mb-2">
                  <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{TYPE_LABELS[q.type] || q.type}</span>
                  <span className={`text-xs ${correct ? 'text-green-600' : 'text-red-500'}`}>
                    {correct ? `✓ +${q.awarded}分` : `✗ ${q.awarded || 0}分`}
                  </span>
                  <div className="flex-1 font-medium">{i + 1}. {q.stem}</div>
                </div>
                <div className="space-y-1 text-sm">
                  {(q.options || []).map((opt: string, oi: number) => {
                    const isUser = (q.userAnswer || []).includes(oi);
                    const isCorrect = (q.answer || []).includes(oi);
                    return (
                      <div key={oi} className={`px-2 py-1 rounded ${isCorrect ? 'bg-green-100' : isUser ? 'bg-red-100' : ''}`}>
                        <span className="font-medium">{String.fromCharCode(65 + oi)}.</span> {opt}
                        {isCorrect && <span className="text-green-600 ml-2">✓ 正确答案</span>}
                        {isUser && !isCorrect && <span className="text-red-500 ml-2">你的选择</span>}
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 text-xs text-gray-500">
                  你的答案：{userAns.length ? userAns.join('、') : '未作答'} · 正确答案：{correctAns.join('、')}
                </div>
                {q.explanation && <div className="mt-1 text-xs text-gray-600 bg-gray-50 p-2 rounded">解析：{q.explanation}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </Layout>
  );
}
