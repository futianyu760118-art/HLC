// @ts-nocheck
/**
 * 员工门户首页（课程市场风格）
 * 参照网易云课堂/腾讯课堂：封面图 + 标题 + 标签 + 进度，网格卡片
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';
import { ProtectedImage } from '../../components/ProtectedFile';

const PLACEHOLDER_GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
  'linear-gradient(135deg, #30cfd0 0%, #330867 100%)',
  'linear-gradient(135deg, #5ee7df 0%, #b490ca 100%)',
];
const gradientFor = (key: string) => PLACEHOLDER_GRADIENTS[(key || '').length % PLACEHOLDER_GRADIENTS.length];

export default function P_portal_home() {
  const navigate = useNavigate();
  const [me, setMe] = useState<any>(null);
  const [courses, setCourses] = useState<any[]>([]);
  const [exams, setExams] = useState<any[]>([]);
  const [points, setPoints] = useState<any>({ totalPoints: 0, rank: null });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    Promise.all([portalApi.me(), portalApi.courses(), portalApi.exams(),
      import('../../utils/api').then(({ default: ac }) => ac.get('/portal/points/summary'))])
      .then(([m, c, e, p]) => { setMe(m); setCourses(c || []); setExams(e || []); setPoints(p || { totalPoints: 0 }); })
      .catch(err => { toast.error(err.message || '加载失败'); setLoadError(true); })
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    document.title = '学习中心';
    load();
  }, []);

  if (loading) return <Layout><div className="flex items-center justify-center min-h-[60vh]"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (loadError) return <Layout><div className="p-10 text-center"><p className="text-danger mb-3">首页数据加载失败</p><button onClick={load} className="text-sm text-primary hover:underline">重试</button></div></Layout>;

  if (me && me.bound === false) {
    return (
      <Layout>
        <div className="max-w-md mx-auto pt-24 text-center">
          <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-bg-light flex items-center justify-center">
            <AppIcon className="fas fa-user-slash text-3xl text-secondary" />
          </div>
          <h2 className="text-lg font-semibold text-text-primary mb-2">账号未绑定员工档案</h2>
          <p className="text-sm text-text-secondary">请联系管理员绑定您的员工档案后使用学习功能。</p>
        </div>
      </Layout>
    );
  }

  const learning = courses.filter(c => !c.isFinished);
  const finished = courses.filter(c => c.isFinished);
  const pendingExams = exams.filter(e => e.remainingAttempts > 0 && e.inWindow && e.status !== 'passed');
  // 临近截止的必修课（7天内未完成）
  const urgentCourses = learning.filter(c => {
    if (!c.isRequired || !c.deadline) return false;
    const days = (new Date(c.deadline).getTime() - Date.now()) / 86400000;
    return days <= 7;
  });

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-text-primary">你好，{me?.employee?.name || '同学'} 👋</h1>
            <p className="text-sm text-text-secondary mt-1">继续学习，保持成长</p>
          </div>
          {points.totalPoints > 0 && (
            <button onClick={() => navigate('/portal/points')} className="flex items-center gap-3 bg-gradient-to-br from-warning/10 to-primary/10 rounded-xl px-4 py-2.5 border border-warning/20 hover:shadow-card transition-shadow">
              <AppIcon className="fas fa-trophy text-warning text-xl" />
              <div className="text-left">
                <div className="text-lg font-bold text-warning leading-tight">{points.totalPoints}</div>
                <div className="text-xs text-text-secondary">积分{points.rank ? ` · 第${points.rank}名` : ''}</div>
              </div>
            </button>
          )}
        </div>

        {/* 快捷操作 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <QuickCard icon="fa-book-open" label="我的课程" desc={`${learning.length + finished.length} 门课程`} color="from-blue-500 to-cyan-400" onClick={() => navigate('/portal/my-courses')} />
          <QuickCard icon="fa-clipboard-check" label="我的考试" desc={`${pendingExams.length} 场待考`} color="from-orange-500 to-amber-400" onClick={() => navigate('/portal/my-exams')} />
          <QuickCard icon="fa-route" label="学习路径" desc="闯关成长" color="from-purple-500 to-pink-400" onClick={() => navigate('/portal/learning-paths')} />
          <QuickCard icon="fa-store" label="积分商城" desc={`${points.totalPoints} 积分`} color="from-green-500 to-emerald-400" onClick={() => navigate('/portal/shop')} />
        </div>

        {pendingExams.length > 0 && (
          <div className="mb-6 rounded-xl border border-warning/30 bg-warning/5 p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-warning/10 flex items-center justify-center shrink-0">
              <AppIcon className="fas fa-bell text-warning" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-text-primary text-sm">你有 {pendingExams.length} 场待完成考试</div>
              <div className="text-xs text-text-secondary truncate">{pendingExams.map(e => e.title).join('、')}</div>
            </div>
            <button onClick={() => navigate('/portal/my-exams')} className="text-sm text-warning hover:underline shrink-0">前往 →</button>
          </div>
        )}

        {/* 必修课截止提醒 */}
        {urgentCourses.length > 0 && (
          <div className="mb-6 rounded-xl border border-danger/30 bg-danger/5 p-4 flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-danger/10 flex items-center justify-center shrink-0">
              <AppIcon className="fas fa-exclamation-triangle text-danger" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-text-primary text-sm">有 {urgentCourses.length} 门必修课即将到期</div>
              <div className="text-xs text-text-secondary truncate">
                {urgentCourses.map(c => `${c.title}（${new Date(c.deadline).toLocaleDateString('zh-CN')}）`).join('、')}
              </div>
            </div>
            <button onClick={() => navigate('/portal/my-courses')} className="text-sm text-danger hover:underline shrink-0">去学习 →</button>
          </div>
        )}

        {learning.length > 0 && (
          <section className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-text-primary">继续学习</h2>
              <button onClick={() => navigate('/portal/my-courses')} className="text-sm text-primary hover:underline">全部课程</button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {learning.slice(0, 4).map(c => (
                <CourseCard key={c.id} course={c} onClick={() => navigate(`/portal/course/${c.id}`)} />
              ))}
            </div>
          </section>
        )}

        {finished.length > 0 && (
          <section className="mb-8">
            <h2 className="text-lg font-semibold text-text-primary mb-4">已完成课程</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {finished.map(c => (
                <CourseCard key={c.id} course={c} onClick={() => navigate(`/portal/course/${c.id}`)} />
              ))}
            </div>
          </section>
        )}

        {courses.length === 0 && (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-light flex items-center justify-center">
              <AppIcon className="fas fa-book-open text-2xl text-secondary" />
            </div>
            <p className="text-text-secondary">暂无可学习的课程</p>
          </div>
        )}
      </div>
    </Layout>
  );
}

/** 课程卡片（市场网格风格）— 导出供 my-courses 复用 */
export function CourseCard({ course, onClick }: { course: any; onClick: () => void }) {
  const progress = course.progress || 0;
  return (
    <div onClick={onClick}
      className="group bg-white rounded-xl overflow-hidden border border-border-light shadow-card hover:shadow-card-hover transition-all duration-200 cursor-pointer">
      {/* 封面为主角（4:3），底部叠标题，进度条叠最底 */}
      <div className="aspect-[4/3] relative overflow-hidden" style={course.coverUrl ? {} : { background: gradientFor(course.id) }}>
        {course.coverUrl ? (
          <ProtectedImage fileUrl={course.coverUrl} alt={course.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
        ) : null}
        {/* 底部渐变遮罩 + 课程名 */}
        <div className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/70 via-black/20 to-transparent flex items-end p-3">
          <h3 className="text-white font-semibold text-base leading-snug line-clamp-2 drop-shadow">{course.title}</h3>
        </div>
        {/* 左上状态标 */}
        <div className="absolute top-2.5 left-2.5 flex gap-1.5">
          {course.isRequired && <span className="px-2 py-0.5 rounded text-xs text-white bg-danger/90 font-medium">必修</span>}
        </div>
        {/* 右上完成徽章 */}
        {course.isFinished && (
          <div className="absolute top-2.5 right-2.5">
            <span className="px-2 py-0.5 rounded-full text-xs text-white bg-success/90 flex items-center gap-1 backdrop-blur-sm">
              <AppIcon className="fas fa-check text-[10px]" /> 已完成
            </span>
          </div>
        )}
        {/* 底部进度细条 */}
        {progress > 0 && !course.isFinished && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/30">
            <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
      {/* 信息区极简：只有状态一行 */}
      <div className="px-3 py-2 flex items-center gap-1.5 text-xs text-text-secondary">
        <AppIcon className={`fas ${course.isFinished ? 'fa-check-circle text-success' : progress > 0 ? 'fa-play-circle text-primary' : 'fa-circle-notch'}`} />
        {course.isFinished ? '已完成' : progress > 0 ? `学习中 ${progress}%` : '未开始'}
      </div>
    </div>
  );
}

/** 快捷操作卡片 */
function QuickCard({ icon, label, desc, color, onClick }) {
  return (
    <button onClick={onClick}
      className="group relative overflow-hidden rounded-xl border border-border-light bg-white p-4 hover:shadow-card-hover transition-all text-left">
      <div className={`absolute top-0 right-0 w-20 h-20 rounded-full bg-gradient-to-br ${color} opacity-10 group-hover:opacity-20 group-hover:scale-150 transition-all`} />
      <div className={`relative w-10 h-10 rounded-lg bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <AppIcon className={`fas ${icon} text-white text-lg`} />
      </div>
      <div className="relative font-medium text-text-primary text-sm">{label}</div>
      <div className="relative text-xs text-text-secondary mt-0.5">{desc}</div>
    </button>
  );
}
