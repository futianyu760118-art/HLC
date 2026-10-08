// @ts-nocheck
/**
 * 我的积分（员工门户）— 积分总数 + 排行榜 + 明细
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader } from '../../components/PageParts';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

export default function P_portal_points() {
  const [data, setData] = useState<any>({ totalPoints: 0, rank: null, logs: [], leaderboard: [] });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    apiClient.get('/portal/points/summary').then(setData)
      .catch(e => { toast.error(e.message); setLoadError(true); }).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (loadError) return <Layout><div className="p-10 text-center"><p className="text-danger mb-3">积分数据加载失败</p><button onClick={load} className="text-sm text-primary hover:underline">重试</button></div></Layout>;

  const ACTION_ICONS: Record<string, string> = {
    course_hour_finished: 'fa-play-circle', course_completed: 'fa-check-circle',
    exam_passed: 'fa-trophy', exam_attempted: 'fa-clipboard-check',
    competency_assessed: 'fa-chart-radar',
    review_submitted: 'fa-star',
    reward_exchange: 'fa-gift',
  };

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-trophy" title="学习积分" subtitle="学习越多，积分越高" />

        {/* 积分总览 */}
        <div className="rounded-lg border border-border-light bg-white p-5 mb-6">
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className="text-4xl font-bold text-warning">{data.totalPoints}</div>
              <div className="text-xs text-text-secondary mt-1">总积分</div>
            </div>
            {data.rank && (
              <div className="text-center border-l border-border-light pl-6">
                <div className="text-4xl font-bold text-primary">#{data.rank}</div>
                <div className="text-xs text-text-secondary mt-1">排名（共{data.totalLearners}人）</div>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* 排行榜 */}
          <div className="bg-white rounded-lg border border-border-light p-5">
            <h2 className="font-semibold text-text-primary mb-4 flex items-center gap-2">
              <AppIcon className="fas fa-medal text-warning" /> 学习排行榜
            </h2>
            <div className="space-y-2">
              {(data.leaderboard || []).map((u, i) => (
                <div key={u.employeeId} className={`flex items-center gap-3 px-3 py-2 rounded-lg ${u.employeeId === data.employeeId ? 'bg-primary/5' : ''}`}>
                  <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    i === 0 ? 'bg-warning text-white' : i === 1 ? 'bg-text-secondary text-white' : i === 2 ? 'bg-orange-400 text-white' : 'bg-bg-light text-text-secondary'
                  }`}>{u.rank}</span>
                  <span className="flex-1 text-sm font-medium text-text-primary">{u.employeeName}</span>
                  {u.department && <span className="text-xs text-text-secondary">{u.department}</span>}
                  <span className="text-sm font-bold text-warning">{u.totalPoints}</span>
                </div>
              ))}
              {(!data.leaderboard || data.leaderboard.length === 0) && <div className="text-center text-text-secondary text-sm py-4">暂无排行数据</div>}
            </div>
          </div>

          {/* 积分明细 */}
          <div className="bg-white rounded-lg border border-border-light p-5">
            <h2 className="font-semibold text-text-primary mb-4 flex items-center gap-2">
              <AppIcon className="fas fa-list text-primary" /> 积分明细
            </h2>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {(data.logs || []).map((log) => (
                <div key={log.id} className="flex items-center gap-3 py-2 border-b border-border-light last:border-0">
                  <AppIcon className={`fas ${ACTION_ICONS[log.action] || 'fa-circle'} text-primary text-xs w-4`} />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-text-primary">{log.actionLabel || log.action}</div>
                    {log.detail && <div className="mt-0.5 truncate text-xs text-text-secondary">{log.detail}</div>}
                  </div>
                  <span className={`text-sm font-semibold ${log.points >= 0 ? 'text-success' : 'text-danger'}`}>
                    {log.points > 0 ? '+' : ''}{log.points}
                  </span>
                </div>
              ))}
              {(!data.logs || data.logs.length === 0) && <div className="text-center text-text-secondary text-sm py-4">完成学习任务即可获得积分</div>}
            </div>
          </div>
        </div>

        {/* 积分规则说明 */}
        <div className="mt-5 rounded-lg border border-border-light bg-white p-4 text-xs text-text-secondary">
          <div className="font-medium text-text-primary mb-2">积分规则</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <span>完成课时 +5</span><span>完成课程 +20</span>
            <span>参加考试 +10</span><span>考试通过 +50</span>
            <span>能力测评 +15</span><span>课程评价 +5</span>
          </div>
        </div>
      </div>
    </Layout>
  );
}
