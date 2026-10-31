// @ts-nocheck
/**
 * 我的考试（员工门户）：全部考试任务，区分待考/已通过/未通过
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

export default function P_portal_my_exams() {
  const navigate = useNavigate();
  const [exams, setExams] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    portalApi.exams().then((e: any[]) => setExams(e || []))
      .catch(err => toast.error(err.message || '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const fmtTime = (t?: string) => t ? new Date(t.includes('Z') ? t : t + 'Z').toLocaleString('zh-CN', { hour12: false }) : '不限';

  return (
    <Layout>
      <div className="max-w-4xl mx-auto p-6 space-y-4">
        <div className="flex items-center gap-3">
          <AppIcon className="fas fa-clipboard-list text-2xl text-orange-500" />
          <h1 className="text-2xl font-bold">我的考试</h1>
        </div>

        {loading ? (
          <div className="text-center text-gray-400 py-10">加载中…</div>
        ) : exams.length === 0 ? (
          <div className="text-center text-gray-400 py-10">暂无考试任务</div>
        ) : (
          <div className="space-y-3">
            {exams.map(e => {
              const canTake = e.remainingAttempts > 0 && e.inWindow;
              const passed = e.status === 'passed';
              const isRandom = e.questionMode === 'random';
              return (
                <div key={e.taskId} className={`bg-white rounded-lg shadow p-4 border-l-4 ${passed ? 'border-green-500' : canTake ? 'border-orange-500' : 'border-gray-300'}`}>
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="font-medium">{e.title}</div>
                      <div className="text-xs text-gray-500 mt-1">
                        {e.paperTitle} · 总分 {e.totalScore}/及格 {e.passScore} · {e.durationMinutes}分钟
                      </div>
                      <div className="text-xs text-gray-400 mt-1">
                        {isRandom ? `随机抽题 · 题池 ${e.poolCount || 0} 题，实际抽 ${e.questionCount || e.drawCount || 0} 题` : `固定试卷 · 共 ${e.questionCount || e.poolCount || 0} 题`}
                      </div>
                      <div className="text-xs text-gray-400 mt-1">
                        时间：{fmtTime(e.startTime)} ~ {fmtTime(e.endTime)}
                      </div>
                    </div>
                    <div className="text-right">
                      {passed ? (
                        <span className="inline-block px-2 py-0.5 rounded bg-green-100 text-green-700 text-xs">已通过</span>
                      ) : e.status === 'failed' ? (
                        <span className="inline-block px-2 py-0.5 rounded bg-red-100 text-red-600 text-xs">未通过</span>
                      ) : canTake ? (
                        <span className="inline-block px-2 py-0.5 rounded bg-orange-100 text-orange-700 text-xs">待考</span>
                      ) : (
                        <span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-500 text-xs">未开放</span>
                      )}
                      <div className="text-xs text-gray-400 mt-1">剩余 {e.remainingAttempts}/{e.maxAttempts} 次</div>
                    </div>
                  </div>
                  {canTake && (
                    <button onClick={() => navigate(`/portal/exam/${e.taskId}`)}
                      className="mt-3 w-full bg-orange-600 text-white py-2 rounded hover:bg-orange-700 text-sm">
                      {e.status === 'failed' ? '再次考试' : '开始考试'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
}
