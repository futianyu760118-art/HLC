// @ts-nocheck
/**
 * 培训中心（管理侧）— 网课平台网格风格
 * 顶部统计 + 分类筛选 + 课程卡片网格 + 新建/编辑入口
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi } from '../../utils/api';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';
import { ProtectedImage } from '../../components/ProtectedFile';

const PLACEHOLDER_GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
  'linear-gradient(135deg, #30cfd0 0%, #330867 100%)',
];
const gradientFor = (key) => PLACEHOLDER_GRADIENTS[(key || '').length % PLACEHOLDER_GRADIENTS.length];

export default function P_training_center() {
  const navigate = useNavigate();
  const [courses, setCourses] = useState([]);
  const [categories, setCategories] = useState([]);
  const [reviewSummary, setReviewSummary] = useState({});
  const [learnStats, setLearnStats] = useState({});
  const [filterCat, setFilterCat] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [progressCourse, setProgressCourse] = useState(null); // 正在查看学员进度的课程

  const openProgress = (course) => setProgressCourse(course);

  const load = async () => {
    setLoading(true);
    try {
      const [c, cat] = await Promise.all([hrmApi.list('courses'), hrmApi.list('course-categories')]);
      setCourses(c || []);
      setCategories(cat || []);
      // 加载评分汇总
      apiClient.get<any>('/hrm/courses/reviews-summary').then((rows: any[]) => {
        const map = {};
        (rows || []).forEach(r => { map[r.courseId] = r; });
        setReviewSummary(map);
      }).catch(() => {});
      // 加载学习统计（学习人数/完成人数/平均进度）
      apiClient.get<any>('/hrm/courses/learning-stats').then((rows: any[]) => {
        const map = {};
        (rows || []).forEach(r => { map[r.courseId] = r; });
        setLearnStats(map);
      }).catch(() => {});
    } catch (e) { toast.error(e.message || '加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const filtered = courses.filter(c => {
    if (filterCat !== 'all' && c.categoryId !== filterCat) return false;
    if (keyword && !(c.title || '').toLowerCase().includes(keyword.toLowerCase())) return false;
    return true;
  });

  const stats = {
    total: courses.length,
    published: courses.filter(c => c.isShow).length,
    required: courses.filter(c => c.isRequired).length,
    learners: Object.values(learnStats).reduce((s: number, r: any) => s + (r.learnerCount || 0), 0),
  };

  const createCourse = async (data) => {
    setCreating(true);
    try {
      const r = await hrmApi.create('courses', data);
      toast.success('课程已创建');
      setShowCreate(false);
      navigate(`/course-edit/${r.id}`);
    } catch (e) { toast.error(e.message || '创建失败'); }
    finally { setCreating(false); }
  };

  const togglePublish = async (c) => {
    try {
      await hrmApi.update('courses', c.id, { isShow: !c.isShow });
      toast.success(c.isShow ? '已下架' : '已上架');
      load();
    } catch (e) { toast.error(e.message || '操作失败'); }
  };

  const removeCourse = async (c) => {
    if (!await confirm(`删除课程「${c.title}」？相关章节/课时将一并删除。`)) return;
    try {
      await hrmApi.remove('courses', c.id);
      toast.success('已删除');
      load();
    } catch (e) { toast.error(e.message || '删除失败'); }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        {/* 顶部 */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-text-primary">培训中心</h1>
            <p className="text-sm text-text-secondary mt-1">管理课程内容、章节资料与指派</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => navigate('/hrm/course-categories')} className="px-3 py-2 text-sm border border-border-light rounded-lg text-text-secondary hover:bg-bg-light flex items-center gap-1.5">
              <AppIcon className="fas fa-folder-tree" /> 分类管理
            </button>
            <button onClick={() => navigate('/exam-generate')} className="px-3 py-2 text-sm border border-border-light rounded-lg text-text-secondary hover:bg-bg-light flex items-center gap-1.5">
              <AppIcon className="fas fa-wand-magic-sparkles" /> AI 出题
            </button>
            <button onClick={() => setShowCreate(true)} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
              <AppIcon className="fas fa-plus" /> 新建课程
            </button>
          </div>
        </div>

        {/* 统计条 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatCard label="课程总数" value={stats.total} icon="fa-book-open" />
          <StatCard label="已上架" value={stats.published} icon="fa-eye" tone="success" />
          <StatCard label="必修课" value={stats.required} icon="fa-exclamation-circle" tone="danger" />
          <StatCard label="学习中人数" value={stats.learners} icon="fa-user-graduate" tone="primary" />
        </div>

        {/* 筛选 */}
        <div className="flex items-center gap-3 mb-5">
          <div className="flex gap-1 bg-bg-light rounded-lg p-1 overflow-x-auto">
            <button onClick={() => setFilterCat('all')}
              className={`px-3 py-1.5 rounded-md text-sm whitespace-nowrap transition-colors ${filterCat === 'all' ? 'bg-white text-primary shadow-sm font-medium' : 'text-text-secondary hover:text-text-primary'}`}>
              全部
            </button>
            {categories.map(cat => (
              <button key={cat.id} onClick={() => setFilterCat(cat.id)}
                className={`px-3 py-1.5 rounded-md text-sm whitespace-nowrap transition-colors ${filterCat === cat.id ? 'bg-white text-primary shadow-sm font-medium' : 'text-text-secondary hover:text-text-primary'}`}>
                {cat.name}
              </button>
            ))}
          </div>
          <div className="relative flex-1 max-w-xs ml-auto">
            <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-xs text-text-secondary" />
            <input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="搜索课程"
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-border-light rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none" />
          </div>
        </div>

        {/* 课程网格 */}
        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-light flex items-center justify-center">
              <AppIcon className="fas fa-book-open text-2xl text-text-secondary" />
            </div>
            <p className="text-text-secondary mb-3">{keyword || filterCat !== 'all' ? '没有匹配的课程' : '还没有课程，创建第一门吧'}</p>
            {!keyword && filterCat === 'all' && (
              <button onClick={() => setShowCreate(true)} className="text-sm text-primary hover:underline">+ 新建课程</button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {filtered.map(c => (
              <AdminCourseCard key={c.id} course={c} categories={categories} review={reviewSummary[c.id]} learn={learnStats[c.id]}
                onEdit={() => navigate(`/course-edit/${c.id}`)}
                onTogglePublish={() => togglePublish(c)}
                onRemove={() => removeCourse(c)}
                onProgress={() => openProgress(c)} />
            ))}
          </div>
        )}

        {showCreate && <CreateCourseModal categories={categories} saving={creating} onCancel={() => setShowCreate(false)} onCreate={createCourse} />}
        {progressCourse && <ProgressModal course={progressCourse} onClose={() => setProgressCourse(null)} />}
      </div>
    </Layout>
  );
}

function StatCard({ label, value, icon, tone = 'primary' }) {
  const tones = { primary: 'text-primary', success: 'text-success', danger: 'text-danger' };
  return (
    <div className="bg-white rounded-xl border border-border-light p-4 flex items-center gap-3">
      <div className="w-10 h-10 rounded-lg bg-bg-light flex items-center justify-center">
        <AppIcon className={`fas ${icon} ${tones[tone]}`} />
      </div>
      <div>
        <div className={`text-xl font-bold ${tones[tone]}`}>{value}</div>
        <div className="text-xs text-text-secondary">{label}</div>
      </div>
    </div>
  );
}

function AdminCourseCard({ course, categories, review, learn, onEdit, onTogglePublish, onRemove, onProgress }) {
  const catName = categories.find(c => c.id === course.categoryId)?.name;
  const learner = learn?.learnerCount || 0;
  const finished = learn?.finishedCount || 0;
  const avgProgress = learn?.avgProgress || 0;
  const assigned = learn?.assignedCount || 0;
  // 完成率：已完成 / 分配总人数（无分配时按学习人数算）
  const finishRate = assigned > 0 ? Math.round(finished / assigned * 100) : (learner > 0 ? Math.round(finished / learner * 100) : 0);
  return (
    <div className="group bg-white rounded-xl overflow-hidden border border-border-light shadow-card hover:shadow-card-hover transition-all duration-200 cursor-pointer" onClick={onEdit}>
      {/* 封面区：占卡片主体，底部叠课程名，悬停浮出管理操作 */}
      <div className="aspect-[4/3] relative overflow-hidden" style={course.coverUrl ? {} : { background: gradientFor(course.id) }}>
        {course.coverUrl ? (
          <ProtectedImage fileUrl={course.coverUrl} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" alt="" />
        ) : null}
        {/* 底部渐变遮罩 + 课程名（无论有无封面都叠，保证标题清晰）*/}
        <div className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/70 via-black/20 to-transparent flex items-end p-3">
          <h3 className="text-white font-semibold text-base leading-snug line-clamp-2 drop-shadow">{course.title}</h3>
        </div>
        {/* 左上角状态标 */}
        <div className="absolute top-2.5 left-2.5 flex gap-1.5">
          {course.isRequired && <span className="px-2 py-0.5 rounded text-xs text-white bg-danger/90 font-medium">必修</span>}
          {!course.isShow && <span className="px-2 py-0.5 rounded text-xs text-white bg-black/60">未上架</span>}
        </div>
        {/* 右上分类标 */}
        {catName && (
          <span className="absolute top-2.5 right-2.5 px-2 py-0.5 rounded text-xs text-white bg-black/40 backdrop-blur-sm">{catName}</span>
        )}
        {/* 悬停浮层：管理操作 */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/45 transition-colors duration-200 flex items-center justify-center opacity-0 group-hover:opacity-100">
          <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
            <button onClick={onEdit} title="编辑课程"
              className="w-10 h-10 rounded-full bg-white/95 text-text-primary hover:bg-white flex items-center justify-center transition-colors">
              <AppIcon className="fas fa-pen text-sm" />
            </button>
            <button onClick={onProgress} title="学员进度"
              className="w-10 h-10 rounded-full bg-white/95 text-primary hover:bg-primary hover:text-white flex items-center justify-center transition-colors">
              <AppIcon className="fas fa-chart-line text-sm" />
            </button>
            <button onClick={onTogglePublish} title={course.isShow ? '下架' : '上架'}
              className="w-10 h-10 rounded-full bg-white/95 text-text-primary hover:bg-white flex items-center justify-center transition-colors">
              <AppIcon className={`text-sm ${course.isShow ? 'fas fa-eye-slash' : 'fas fa-eye'}`} />
            </button>
            <button onClick={onRemove} title="删除课程"
              className="w-10 h-10 rounded-full bg-white/95 text-danger hover:bg-danger hover:text-white flex items-center justify-center transition-colors">
              <AppIcon className="fas fa-trash text-sm" />
            </button>
          </div>
        </div>
      </div>
      {/* 信息区：学习人数 + 进度 + 评分 */}
      <div className="px-3 py-2.5 space-y-1.5">
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span className="flex items-center gap-1">
            <AppIcon className="fas fa-layer-group text-xs" /> {course.classHour || 0} 课时
          </span>
          {review && review.reviewCount > 0 && (
            <span className="flex items-center gap-0.5">
              <AppIcon className="fas fa-star text-warning text-xs" />
              <span className="text-warning font-medium">{review.avgRating}</span>
              <span className="text-text-secondary">({review.reviewCount})</span>
            </span>
          )}
        </div>
        {/* 学习统计：学习人数 / 完成率 / 平均进度 */}
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1 text-text-secondary" title="学习人数 / 分配人数">
            <AppIcon className="fas fa-user-graduate text-xs text-primary" />
            <span className="text-text-primary font-medium">{learner}</span>
            {assigned > 0 && <span className="text-text-secondary">/{assigned}</span>}
            <span className="text-text-secondary ml-0.5">人在学</span>
          </span>
          <span className={`flex items-center gap-0.5 ${finishRate >= 80 ? 'text-success' : finishRate > 0 ? 'text-warning' : 'text-text-secondary'}`} title="完成率">
            <AppIcon className="fas fa-check-circle text-xs" />
            {finishRate}%
          </span>
        </div>
        {/* 平均进度条 */}
        {learner > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-bg-light rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all ${avgProgress >= 100 ? 'bg-success' : 'bg-primary'}`} style={{ width: `${Math.min(avgProgress, 100)}%` }} />
            </div>
            <span className="text-xs text-text-secondary tabular-nums shrink-0">均{avgProgress}%</span>
          </div>
        )}
      </div>
      <div className="px-3 pb-2.5 flex items-center justify-end text-xs">
        <span className="flex items-center gap-1 text-primary opacity-0 group-hover:opacity-100 transition-opacity">
          点击编辑 <AppIcon className="fas fa-arrow-right text-[10px]" />
        </span>
      </div>
    </div>
  );
}

function CreateCourseModal({ categories, saving, onCancel, onCreate }) {
  const [title, setTitle] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [shortDesc, setShortDesc] = useState('');
  const [isRequired, setIsRequired] = useState(false);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-white rounded-xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-text-primary mb-4">新建课程</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm text-text-secondary mb-1">课程标题 *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} autoFocus
              className="w-full px-3 py-2 border border-border-light rounded-lg focus:border-primary focus:ring-1 focus:ring-primary outline-none" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">分类</label>
            <select value={categoryId} onChange={e => setCategoryId(e.target.value)}
              className="w-full px-3 py-2 border border-border-light rounded-lg outline-none">
              <option value="">不分类</option>
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">简介</label>
            <textarea value={shortDesc} onChange={e => setShortDesc(e.target.value)} rows={2}
              className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none" />
          </div>
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={isRequired} onChange={e => setIsRequired(e.target.checked)} />
            必修课
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={() => title.trim() && onCreate({ title: title.trim(), categoryId: categoryId || undefined, shortDesc: shortDesc.trim() || undefined, isRequired, isShow: true })}
            disabled={!title.trim() || saving}
            className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{saving ? '创建中…' : '创建并编辑'}</button>
        </div>
      </div>
    </div>
  );
}

function ProgressModal({ course, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    apiClient.get<any>(`/hrm/courses/${course.id}/progress`)
      .then((r) => setData(r))
      .catch((e) => setError(e.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [course.id]);

  const fmtTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <div>
            <h2 className="text-base font-semibold text-text-primary">{course.title} · 学员进度</h2>
            {!loading && !error && data && (
              <p className="text-xs text-text-secondary mt-0.5">
                共 {data.assigned} 人 · 已完成 {data.finished} 人 · 完成率 {Math.round((data.completionRate || 0) * 100)}%
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary p-1">
            <AppIcon className="fas fa-times" />
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-16"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
          ) : error ? (
            <div className="p-10 text-center text-danger text-sm">{error}</div>
          ) : !data || !data.roster || data.roster.length === 0 ? (
            <div className="p-10 text-center text-text-secondary text-sm">暂无学员</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-bg-light text-text-secondary text-xs">
                <tr>
                  <th className="text-left font-medium px-5 py-2.5">学员</th>
                  <th className="text-left font-medium px-3 py-2.5">部门</th>
                  <th className="text-left font-medium px-3 py-2.5 w-40">学习进度</th>
                  <th className="text-center font-medium px-3 py-2.5">完成课时</th>
                  <th className="text-center font-medium px-3 py-2.5">观看时长</th>
                  <th className="text-center font-medium px-3 py-2.5">最后学习</th>
                  <th className="text-center font-medium px-5 py-2.5">状态</th>
                </tr>
              </thead>
              <tbody>
                {data.roster
                  .slice()
                  .sort((a, b) => (b.progress || 0) - (a.progress || 0))
                  .map((r) => (
                    <tr key={r.employeeId} className="border-t border-border-light hover:bg-bg-light/50">
                      <td className="px-5 py-2.5 text-text-primary font-medium">{r.employeeName || '—'}</td>
                      <td className="px-3 py-2.5 text-text-secondary">{r.department || '—'}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-bg-light rounded-full overflow-hidden min-w-[60px]">
                            <div className={`h-full rounded-full ${(r.progress || 0) >= 100 ? 'bg-success' : 'bg-primary'}`} style={{ width: `${Math.min(r.progress || 0, 100)}%` }} />
                          </div>
                          <span className="text-xs text-text-secondary tabular-nums shrink-0">{r.progress || 0}%</span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-center text-text-secondary tabular-nums">{r.finishedCount || 0}/{r.totalHours || 0}</td>
                      <td className="px-3 py-2.5 text-center text-text-secondary tabular-nums">{r.watchedMinutes || 0}分</td>
                      <td className="px-3 py-2.5 text-center text-text-secondary text-xs">{fmtTime(r.lastWatchedAt)}</td>
                      <td className="px-5 py-2.5 text-center">
                        {r.isFinished ? (
                          <span className="inline-flex items-center gap-1 text-success text-xs"><AppIcon className="fas fa-check-circle" /> 已完成</span>
                        ) : (r.progress || 0) > 0 ? (
                          <span className="text-warning text-xs">学习中</span>
                        ) : (
                          <span className="text-text-secondary text-xs">未开始</span>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
