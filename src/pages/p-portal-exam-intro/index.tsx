// @ts-nocheck
/**
 * 考试介绍页（Chunk 8）：规则展示 + 开始按钮
 */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

export default function P_portal_exam_intro() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [exams, setExams] = useState<any[]>([]);
  const [starting, setStarting] = useState(false);

  useEffect(() => { portalApi.exams().then(setExams).catch(() => {}); }, []);

  const exam = exams.find(e => e.taskId === taskId);

  const start = async () => {
    if (!exam) return;
    if (exam.remainingAttempts <= 0) { toast.error('考试次数已用完'); return; }
    if (!exam.inWindow) { toast.error('不在考试时间窗内'); return; }
    if (!await confirm(`开始考试？本次为第 ${exam.attemptsUsed + 1} 次作答，共 ${exam.maxAttempts} 次机会。`)) return;
    setStarting(true);
    try {
      const res = await portalApi.startExam(taskId);
      navigate(`/portal/exam/take/${res.attemptId}`, { state: res });
    } catch (e: any) {
      toast.error(e.message || '开始失败');
    } finally {
      setStarting(false);
    }
  };

  if (!exam) return <Layout><div className="p-10 text-center text-gray-400">考试不存在或未指派给您</div></Layout>;

  return (
    <Layout>
      <div className="max-w-2xl mx-auto p-6 space-y-4">
        <button onClick={() => navigate('/portal')} className="text-gray-500 hover:text-gray-700 text-sm">← 返回</button>
        <h1 className="text-2xl font-bold">{exam.title}</h1>
        {exam.description && <p className="text-gray-600">{exam.description}</p>}
        <div className="bg-white rounded-lg shadow p-5 space-y-2">
          <Row label="试卷" value={exam.paperTitle} />
          <Row label="出题方式" value={exam.questionMode === 'random' ? `随机抽题（题池 ${exam.poolCount || 0} 题，抽 ${exam.questionCount || exam.drawCount || 0} 题）` : `固定试卷（${exam.questionCount || exam.poolCount || 0} 题）`} />
          <Row label="总分 / 及格分" value={`${exam.totalScore} / ${exam.passScore}`} />
          <Row label="答题时长" value={`${exam.durationMinutes} 分钟`} />
          <Row label="时间窗" value={`${exam.startTime ? new Date(exam.startTime).toLocaleString('zh-CN') : '不限'} ~ ${exam.endTime ? new Date(exam.endTime).toLocaleString('zh-CN') : '不限'}`} />
          <Row label="剩余次数" value={`${exam.remainingAttempts} / ${exam.maxAttempts}`} />
          <Row label="状态" value={exam.status === 'passed' ? '已通过' : exam.status === 'failed' ? '未通过' : '未参加'} />
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
          <AppIcon className="fas fa-exclamation-triangle" /> 注意：请尽量一次性完成；中途刷新页面会保留已作答内容。
        </div>
        {exam.questionMode === 'random' && (
          <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm text-blue-700">
            <AppIcon className="fas fa-shuffle" /> 随机题会在点击“开始考试”后为当前作答人生成，并在本次作答内保持不变。
          </div>
        )}
        <button onClick={start} disabled={starting || exam.remainingAttempts <= 0 || !exam.inWindow}
          className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50">
          {starting ? '准备试卷中…' : exam.remainingAttempts <= 0 ? '次数已用完' : !exam.inWindow ? '不在时间窗' : '开始考试'}
        </button>
      </div>
    </Layout>
  );
}

function Row({ label, value }: { label: string; value: any }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium">{value ?? '-'}</span>
    </div>
  );
}
