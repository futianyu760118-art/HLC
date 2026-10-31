// @ts-nocheck
/**
 * 学习数据大屏 — 全屏深色科技感可视化，用于培训成果汇报展示
 * 复用 /hrm/analytics/dashboard 数据端点
 */
import React, { useEffect, useState, useRef } from 'react';
import apiClient from '../../utils/api';
import AppIcon from '../../components/AppIcon';

export default function P_bigscreen() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [time, setTime] = useState(new Date());
  const canvasRef = useRef(null);

  const fetchData = (silent = false) => {
    apiClient.get('/hrm/analytics/dashboard').then((d) => {
      setData(d);
      setLoadError(false);
    }).catch(() => {
      if (!silent) setLoadError(true);
    });
  };

  useEffect(() => {
    fetchData();
    const t1 = setInterval(() => fetchData(true), 60000);
    const t2 = setInterval(() => setTime(new Date()), 1000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, []);

  // 背景粒子动画
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let raf;
    const particles = Array(50).fill(0).map(() => ({
      x: Math.random() * canvas.width, y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 2 + 0.5,
    }));
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach((p, i) => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0, 200, 255, 0.15)'; ctx.fill();
        // 连线
        particles.slice(i + 1).forEach(p2 => {
          const d = Math.hypot(p.x - p2.x, p.y - p2.y);
          if (d < 120) {
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = `rgba(0, 200, 255, ${0.08 * (1 - d / 120)})`; ctx.lineWidth = 0.5; ctx.stroke();
          }
        });
      });
      raf = requestAnimationFrame(animate);
    };
    animate();
    return () => cancelAnimationFrame(raf);
  }, []);

  if (loadError) return (
    <div className="fixed inset-0 bg-slate-900 flex flex-col items-center justify-center text-cyan-300">
      <AppIcon className="fas fa-exclamation-triangle text-4xl mb-3" />
      <div className="text-sm mb-4">大屏数据加载失败</div>
      <button onClick={() => fetchData()} className="px-4 py-1.5 border border-cyan-400 rounded text-sm hover:bg-cyan-400/10">重试</button>
    </div>
  );

  if (!data) return (
    <div className="fixed inset-0 bg-slate-900 flex items-center justify-center">
      <AppIcon className="fas fa-spinner fa-spin text-4xl text-cyan-400" />
    </div>
  );

  const m = data.metrics || {};
  const fmtTime = (d) => d.toLocaleString('zh-CN', { hour12: false });

  return (
    <div className="fixed inset-0 bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 overflow-hidden" style={{ fontFamily: 'system-ui, sans-serif' }}>
      {/* 粒子背景 */}
      <canvas ref={canvasRef} width={window.innerWidth} height={window.innerHeight} className="absolute inset-0" />

      {/* 内容 */}
      <div className="relative h-full flex flex-col p-4 md:p-6">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-4 md:mb-6">
          <div className="flex items-center gap-3">
            <div className="w-1 h-8 bg-gradient-to-b from-cyan-400 to-blue-600 rounded-full" />
            <h1 className="text-xl md:text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 to-blue-400">
              学习发展数据大屏
            </h1>
          </div>
          <div className="text-right">
            <div className="text-cyan-300 text-sm md:text-lg font-mono tabular-nums">{fmtTime(time)}</div>
            <div className="text-slate-500 text-xs">实时数据 · 每分钟刷新</div>
          </div>
        </div>

        {/* 核心指标 */}
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3 md:gap-4 mb-4 md:mb-6">
          <BigMetric label="上架课程" value={m.courseTotal} icon="📚" color="from-cyan-400 to-blue-500" />
          <BigMetric label="活跃学员" value={m.learnerCount} icon="👥" color="from-green-400 to-emerald-500" />
          <BigMetric label="考试通过率" value={m.examPassRate + '%'} icon="✅" color="from-amber-400 to-orange-500" />
          <BigMetric label="人均学时" value={m.avgLearningMinutes + '分'} icon="⏱️" color="from-purple-400 to-pink-500" />
          <BigMetric label="考试人次" value={m.attemptCount} icon="📝" color="from-blue-400 to-indigo-500" />
          <BigMetric label="题库总量" value={m.questionCount} icon="❓" color="from-rose-400 to-red-500" />
        </div>

        {/* 图表区 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4 flex-1 min-h-0">
          {/* 课程完成率 */}
          <ChartPanel title="课程完成率 TOP">
            {(data.courseCompletion || []).slice(0, 5).map((c, i) => (
              <BarRow key={i} label={c.title} value={c.rate} suffix="%" max={100} color="cyan" />
            ))}
          </ChartPanel>

          {/* 部门学习时长 */}
          <ChartPanel title="部门学习时长">
            {(data.deptActivity || []).slice(0, 5).map((d, i) => (
              <BarRow key={i} label={d.name} value={d.minutes} suffix="分" max={Math.max(...(data.deptActivity || []).map(x => x.minutes), 1)} color="green" />
            ))}
          </ChartPanel>

          {/* 热门课程 */}
          <ChartPanel title="🔥 热门课程">
            {(data.popularCourses || []).map((c, i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                <span className={`w-5 h-5 rounded text-xs flex items-center justify-center font-bold ${i < 3 ? 'bg-amber-400/20 text-amber-300' : 'bg-slate-700 text-slate-400'}`}>{i + 1}</span>
                <span className="flex-1 text-slate-300 text-sm truncate">{c.title}</span>
                <span className="text-cyan-300 text-sm font-bold">{c.learnerCount}人</span>
              </div>
            ))}
            {(data.popularCourses || []).length === 0 && <EmptyDark text="暂无数据" />}
          </ChartPanel>

          {/* 考试通过率 */}
          <ChartPanel title="考试通过情况">
            {(data.examStats || []).map((e, i) => (
              <div key={i} className="py-1.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-slate-300 text-xs truncate flex-1">{e.title}</span>
                  <span className={`text-xs font-bold ml-2 ${e.passRate >= 60 ? 'text-green-400' : 'text-amber-400'}`}>{e.passRate}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div className={`h-full rounded-full ${e.passRate >= 60 ? 'bg-gradient-to-r from-green-400 to-emerald-500' : 'bg-gradient-to-r from-amber-400 to-orange-500'}`} style={{ width: e.passRate + '%' }} />
                </div>
              </div>
            ))}
            {(data.examStats || []).length === 0 && <EmptyDark text="暂无已发布考试" />}
          </ChartPanel>
        </div>

        {/* 底部 */}
        <div className="mt-3 text-center text-slate-600 text-xs">恒聘通 HRM · 学习发展模块 · 数据大屏</div>
      </div>
    </div>
  );
}

function BigMetric({ label, value, icon, color }) {
  return (
    <div className="relative rounded-xl border border-slate-700/50 bg-slate-800/40 backdrop-blur-sm p-3 md:p-4 overflow-hidden">
      <div className={`absolute inset-0 bg-gradient-to-br ${color} opacity-5`} />
      <div className="relative">
        <div className="text-2xl md:text-3xl mb-1">{icon}</div>
        <div className={`text-2xl md:text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r ${color} tabular-nums`}>{value}</div>
        <div className="text-slate-400 text-xs md:text-sm mt-0.5">{label}</div>
      </div>
    </div>
  );
}

function ChartPanel({ title, children }) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 backdrop-blur-sm p-3 md:p-4 flex flex-col">
      <h3 className="text-cyan-300 text-sm font-medium mb-2 md:mb-3 border-b border-slate-700/50 pb-2">{title}</h3>
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

function BarRow({ label, value, suffix, max, color }) {
  const colors = { cyan: 'from-cyan-400 to-blue-500', green: 'from-green-400 to-emerald-500' };
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-slate-300 text-xs w-16 truncate text-right" title={label}>{label.length > 6 ? label.slice(0, 6) + '…' : label}</span>
      <div className="flex-1 h-4 rounded bg-slate-700/50 overflow-hidden">
        <div className={`h-full rounded bg-gradient-to-r ${colors[color] || colors.cyan} flex items-center justify-end px-1.5 transition-all duration-1000`} style={{ width: Math.max(value / max * 100, 3) + '%' }}>
          <span className="text-[9px] text-white font-medium">{value}{suffix}</span>
        </div>
      </div>
    </div>
  );
}

function EmptyDark({ text }) {
  return <div className="text-slate-600 text-sm text-center py-6">{text}</div>;
}
