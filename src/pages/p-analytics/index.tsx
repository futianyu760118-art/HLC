// @ts-nocheck
/**
 * 学习数据看板（管理员）— 核心指标 + Chart.js 图表
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader } from '../../components/PageParts';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

export default function P_analytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get('/hrm/analytics/dashboard').then(setData)
      .catch(e => toast.error(e.message)).finally(() => setLoading(false));
  }, []);

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (!data) return <Layout><div className="text-center py-20 text-danger">加载失败</div></Layout>;

  const m = data.metrics;
  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-chart-line" title="数据看板" subtitle="培训与考试运营全局视图"
          actions={<>
            <button onClick={() => window.open('/bigscreen', '_blank')}
              className="px-3 py-2 text-sm border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center gap-1.5">
              <AppIcon className="fas fa-tv" /> 大屏展示
            </button>
            <button onClick={async () => {
              try {
                await apiClient.downloadFile('/hrm/export/points-leaderboard');
              } catch (e) {
                toast.error(e.message || '导出失败');
              }
            }}
              className="px-3 py-2 text-sm border border-border-light rounded-lg text-success hover:bg-success/5 flex items-center gap-1.5">
              <AppIcon className="fas fa-file-excel" /> 导出积分榜
            </button>
          </>} />

        {/* 核心指标 */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          <Metric label="上架课程" value={m.courseTotal} icon="fa-book-open" tone="primary" />
          <Metric label="活跃学员" value={m.learnerCount} icon="fa-users" tone="info" />
          <Metric label="考试通过率" value={m.examPassRate + '%'} icon="fa-check-circle" tone={m.examPassRate >= 60 ? 'success' : 'warning'} />
          <Metric label="人均学习" value={m.avgLearningMinutes + '分'} icon="fa-clock" tone="neutral" />
          <Metric label="考试人次" value={m.attemptCount} icon="fa-clipboard-check" tone="primary" />
          <Metric label="题库" value={m.questionCount} icon="fa-circle-dot" tone="neutral" />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* 课程完成率 */}
          <ChartCard title="课程完成率" icon="fa-chart-bar">
            <BarChart data={data.courseCompletion.map(c => ({ label: c.title.slice(0, 8), value: c.rate, raw: c }))} />
          </ChartCard>

          {/* 部门学习活跃度 */}
          <ChartCard title="部门学习时长排行" icon="fa-chart-column">
            <BarChart data={data.deptActivity.map(d => ({ label: d.name, value: d.minutes, suffix: '分' }))} />
          </ChartCard>

          {/* 热门课程 */}
          <ChartCard title="热门课程 Top5（学习人数）" icon="fa-fire">
            <div className="space-y-2 pt-2">
              {data.popularCourses.map((c, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${i < 3 ? 'bg-warning/20 text-warning' : 'bg-bg-light text-text-secondary'}`}>{i + 1}</span>
                  <span className="flex-1 text-sm text-text-primary truncate">{c.title}</span>
                  <span className="text-sm font-medium text-primary">{c.learnerCount}人</span>
                </div>
              ))}
              {data.popularCourses.length === 0 && <div className="text-center text-text-secondary text-sm py-4">暂无数据</div>}
            </div>
          </ChartCard>

          {/* 考试统计 */}
          <ChartCard title="考试通过情况" icon="fa-clipboard-check">
            <div className="space-y-2 pt-2">
              {data.examStats.map((e, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="flex-1 text-text-primary truncate">{e.title}</span>
                  <span className="text-text-secondary text-xs">{e.submissions}人次</span>
                  <div className="w-24 h-1.5 rounded-full bg-bg-light overflow-hidden">
                    <div className={`h-full rounded-full ${e.passRate >= 60 ? 'bg-success' : 'bg-warning'}`} style={{ width: e.passRate + '%' }} />
                  </div>
                  <span className={`text-xs font-medium tabular-nums w-10 ${e.passRate >= 60 ? 'text-success' : 'text-warning'}`}>{e.passRate}%</span>
                </div>
              ))}
              {data.examStats.length === 0 && <div className="text-center text-text-secondary text-sm py-4">暂无已发布考试</div>}
            </div>
          </ChartCard>
        </div>
      </div>
    </Layout>
  );
}

function Metric({ label, value, icon, tone }) {
  const tones = { primary: 'text-primary', success: 'text-success', warning: 'text-warning', danger: 'text-danger', neutral: 'text-text-secondary', info: 'text-info' };
  return (
    <div className="bg-white rounded-xl border border-border-light p-4">
      <div className="flex items-center justify-between mb-1">
        <AppIcon className={`fas ${icon} ${tones[tone]} text-sm`} />
      </div>
      <div className={`text-2xl font-bold ${tones[tone]}`}>{value}</div>
      <div className="text-xs text-text-secondary mt-0.5">{label}</div>
    </div>
  );
}

function ChartCard({ title, icon, children }) {
  return (
    <div className="bg-white rounded-xl border border-border-light p-5">
      <h2 className="font-semibold text-text-primary mb-3 flex items-center gap-2">
        <AppIcon className={`fas ${icon} text-primary text-sm`} /> {title}
      </h2>
      {children}
    </div>
  );
}

/** 纯 CSS 柱状图（避免 Chart.js 重量级依赖，横向条形） */
function BarChart({ data: items }) {
  const max = Math.max(...items.map(i => i.value || 0), 1);
  return (
    <div className="space-y-2 pt-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <span className="w-16 text-xs text-text-secondary truncate text-right" title={item.label}>{item.label}</span>
          <div className="flex-1 h-5 rounded bg-bg-light overflow-hidden relative">
            <div className="h-full bg-primary/70 rounded transition-all flex items-center justify-end px-1.5"
              style={{ width: Math.max((item.value / max) * 100, 5) + '%' }}>
              <span className="text-[10px] text-white font-medium">{item.value}{item.suffix || ''}</span>
            </div>
          </div>
        </div>
      ))}
      {items.length === 0 && <div className="text-center text-text-secondary text-sm py-4">暂无数据</div>}
    </div>
  );
}
