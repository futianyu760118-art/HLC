// @ts-nocheck
/**
 * 学习 PK 赛（员工门户）— 看活跃赛季 + 自己部门排名
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, EmptyState } from '../../components/PageParts';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

export default function P_portal_pk() {
  const [seasons, setSeasons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    apiClient.get('/portal/pk-seasons/active').then(setSeasons)
      .catch(e => { toast.error(e.message); setLoadError(true); }).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (loadError) return <Layout><div className="max-w-4xl mx-auto px-4 md:px-6 py-6"><PageHeader icon="fa-trophy" title="学习 PK 赛" subtitle="部门间学习竞技" /><div className="text-center py-16"><p className="text-danger mb-3">数据加载失败</p><button onClick={load} className="text-sm text-primary hover:underline">重试</button></div></div></Layout>;

  if (seasons.length === 0) {
    return (
      <Layout>
        <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
          <PageHeader icon="fa-trophy" title="学习 PK 赛" subtitle="部门间学习竞技" />
          <EmptyState icon="fa-trophy" title="暂无进行中的赛季" hint="管理员可创建 PK 赛季" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-trophy" title="学习 PK 赛" subtitle="为团队荣誉而战！" />
        <div className="space-y-6">
          {seasons.map(s => (
            <div key={s.seasonId} className="bg-white rounded-xl border border-border-light overflow-hidden">
              <div className="p-5 bg-gradient-to-r from-warning/10 to-transparent">
                <h2 className="text-lg font-bold text-text-primary">{s.name}</h2>
                {s.description && <p className="text-sm text-text-secondary mt-1">{s.description}</p>}
                <div className="mt-2 flex items-center gap-4 text-xs text-text-secondary">
                  <span><AppIcon className="fas fa-calendar" /> {(s.startDate||'').slice(0,10)} ~ {(s.endDate||'').slice(0,10)}</span>
                  {s.myDeptRank && <span className="text-warning font-medium">我的部门排名：第{s.myDeptRank}名</span>}
                  <span>我的贡献：{s.myPoints}积分</span>
                </div>
              </div>
              {/* 团队排行 */}
              <div className="p-5">
                <h3 className="font-medium text-text-primary mb-3">团队排行</h3>
                <div className="space-y-2">
                  {s.teamBoard.filter(t => t.score > 0 || t.rank <= 5).map(t => (
                    <div key={t.deptId} className={`flex items-center gap-3 px-3 py-2.5 rounded-lg ${t.deptId === s.myDeptId ? 'bg-primary/5 border border-primary/20' : ''}`}>
                      <span className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${t.rank === 1 ? 'bg-warning text-white' : t.rank === 2 ? 'bg-text-secondary text-white' : t.rank === 3 ? 'bg-orange-400 text-white' : 'bg-bg-light text-text-secondary'}`}>
                        {t.rank <= 3 ? <AppIcon className="fas fa-medal" /> : t.rank}
                      </span>
                      <div className="flex-1">
                        <span className="font-medium text-text-primary">{t.deptName}</span>
                        {t.deptId === s.myDeptId && <span className="ml-2 text-xs text-primary">（我的部门）</span>}
                      </div>
                      <span className="text-xs text-text-secondary">{t.memberCount}人</span>
                      <span className="text-lg font-bold text-warning tabular-nums">{s.metric === 'avg_points' ? t.avgPoints : t.totalPoints}</span>
                    </div>
                  ))}
                  {s.teamBoard.every(t => t.score === 0) && <div className="text-center text-text-secondary text-sm py-4">暂无积分数据，快来为部门争光！</div>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Layout>
  );
}
