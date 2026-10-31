// @ts-nocheck
/**
 * 学习路径管理 — 路径卡片 + 编辑器（阶段→课程→考试）
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState, StatusBadge } from '../../components/PageParts';
import { hrmApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const STATUS_MAP = {
  draft: { label: '草稿', tone: 'warning' },
  published: { label: '已发布', tone: 'success' },
  archived: { label: '已归档', tone: 'neutral' },
};

export default function P_learning_paths() {
  const [paths, setPaths] = useState([]);
  const [courses, setCourses] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [p, c, t, d] = await Promise.all([
        hrmApi.list('learning-paths'), hrmApi.list('courses'),
        hrmApi.list('exam-tasks'), hrmApi.list('departments'),
      ]);
      setPaths(p || []); setCourses(c || []); setTasks((t || [])); setDepartments(d || []);
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const publish = async (path) => {
    if (!await confirm(`发布「${path.name}」？将为目标员工生成学习授权。`)) return;
    try {
      const r = await apiPost(path.id, 'publish');
      toast.success(`已发布，授权 ${r.assignedTotal} 人`);
      load();
    } catch (e) { toast.error(e.message); }
  };
  const apiPost = (id, action) => fetch(`/api/hrm/learning-paths/${id}/${action}`, {
    method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
  }).then(r => r.json());

  const remove = async (path) => {
    if (!await confirm(`删除路径「${path.name}」？`)) return;
    try { await hrmApi.remove('learning-paths', path.id); toast.success('已删除'); load(); }
    catch (e) { toast.error(e.message); }
  };

  if (editing) {
    return <PathEditor path={editing} courses={courses} tasks={tasks} departments={departments}
      onBack={() => { setEditing(null); load(); }} />;
  }

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-route" title="学习路径" subtitle="按岗位串联课程，构建成长地图"
          actions={<button onClick={() => setEditing({ name: '', description: '', stages: [{ name: '第一阶段', courseIds: [] }], status: 'draft', targetPosition: '', targetDepartmentId: '' })}
            className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
            <AppIcon className="fas fa-plus" /> 新建路径
          </button>} />

        <div className="grid grid-cols-3 gap-3 mb-5">
          <StatPill label="路径总数" value={paths.length} icon="fa-route" />
          <StatPill label="已发布" value={paths.filter(p => p.status === 'published').length} icon="fa-check" tone="success" />
          <StatPill label="草稿" value={paths.filter(p => p.status === 'draft').length} icon="fa-pen" tone="warning" />
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : paths.length === 0 ? (
          <EmptyState icon="fa-route" title="还没有学习路径" hint="创建第一条路径，把课程串成岗位成长地图" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {paths.map(p => (
              <div key={p.id} className="group bg-white rounded-xl border border-border-light p-5 hover:shadow-card transition-shadow">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-11 h-11 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <AppIcon className="fas fa-route text-primary" />
                  </div>
                  <StatusBadge status={p.status} map={STATUS_MAP} />
                </div>
                <h3 className="font-semibold text-text-primary line-clamp-1">{p.name}</h3>
                {p.targetPosition && <p className="text-sm text-text-secondary mt-1">目标岗位：{p.targetPosition}</p>}
                <div className="mt-3 pt-3 border-t border-border-light flex items-center gap-3 text-xs text-text-secondary">
                  <span className="flex items-center gap-1"><AppIcon className="fas fa-layer-group" /> {p.stageCount} 阶段</span>
                  <span className="flex items-center gap-1"><AppIcon className="fas fa-book-open" /> {p.courseCount} 课程</span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <button onClick={() => setEditing(p)} className="flex-1 text-sm py-1.5 border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                    <AppIcon className="fas fa-pen text-xs" /> 编辑
                  </button>
                  {p.status === 'draft' && (
                    <button onClick={() => publish(p)} className="px-3 py-1.5 text-sm bg-success text-white rounded-lg hover:bg-green-700 flex items-center gap-1">
                      <AppIcon className="fas fa-rocket text-xs" /> 发布
                    </button>
                  )}
                  <button onClick={() => remove(p)} className="w-8 h-8 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center">
                    <AppIcon className="fas fa-trash text-xs" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}

function PathEditor({ path, courses, tasks, departments, onBack }) {
  const [name, setName] = useState(path.name || '');
  const [description, setDescription] = useState(path.description || '');
  const [targetPosition, setTargetPosition] = useState(path.targetPosition || '');
  const [targetDept, setTargetDept] = useState(path.targetDepartmentId || '');
  const [stages, setStages] = useState(path.stages || [{ name: '第一阶段', courseIds: [] }]);
  const [saving, setSaving] = useState(false);

  const addStage = () => setStages([...stages, { name: `第${stages.length + 1}阶段`, courseIds: [] }]);
  const removeStage = (i) => setStages(stages.filter((_, idx) => idx !== i));
  const moveStage = (i, dir) => {
    const j = i + dir;
    if (j < 0 || j >= stages.length) return;
    const next = [...stages];
    [next[i], next[j]] = [next[j], next[i]];
    setStages(next);
  };
  const updateStage = (i, field, value) => setStages(stages.map((s, idx) => idx === i ? { ...s, [field]: value } : s));
  const toggleCourse = (i, cid) => {
    setStages(stages.map((s, idx) => {
      if (idx !== i) return s;
      const ids = s.courseIds || [];
      return { ...s, courseIds: ids.includes(cid) ? ids.filter(x => x !== cid) : [...ids, cid] };
    }));
  };

  const save = async (status) => {
    if (!name.trim()) { toast.error('请输入路径名称'); return; }
    if (stages.length === 0) { toast.error('至少一个阶段'); return; }
    if (stages.some(s => !s.name?.trim())) { toast.error('每个阶段需要名称'); return; }
    setSaving(true);
    try {
      const data = { name: name.trim(), description, targetPosition, targetDepartmentId: targetDept || undefined, stages, status };
      if (path.id) await hrmApi.update('learning-paths', path.id, data);
      else await hrmApi.create('learning-paths', data);
      toast.success('已保存');
      onBack();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-6">
        <button onClick={onBack} className="text-sm text-text-secondary hover:text-primary mb-4 flex items-center gap-1">
          <AppIcon className="fas fa-arrow-left text-xs" /> 返回路径列表
        </button>

        {/* 基本信息 */}
        <div className="bg-white rounded-xl border border-border-light p-5 mb-5 space-y-3">
          <h2 className="font-semibold text-text-primary">路径信息</h2>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="路径名称（如：前端工程师成长路径）"
            className="w-full px-3 py-2 border border-border-light rounded-lg outline-none focus:border-primary" />
          <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="路径说明" rows={2}
            className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none" />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-text-secondary">目标岗位</label>
              <input value={targetPosition} onChange={e => setTargetPosition(e.target.value)} placeholder="如：前端工程师"
                className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" />
            </div>
            <div>
              <label className="text-xs text-text-secondary">目标部门（限定指派范围）</label>
              <select value={targetDept} onChange={e => setTargetDept(e.target.value)}
                className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm">
                <option value="">全员</option>
                {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
          </div>
        </div>

        {/* 阶段编辑 */}
        <div className="bg-white rounded-xl border border-border-light p-5 mb-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-text-primary">学习阶段（闯关顺序）</h2>
            <button onClick={addStage} className="text-sm text-primary hover:text-blue-700 flex items-center gap-1">
              <AppIcon className="fas fa-plus" /> 添加阶段
            </button>
          </div>
          <div className="space-y-3">
            {stages.map((stage, i) => (
              <div key={i} className="border border-border-light rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-7 h-7 rounded-full bg-primary text-white flex items-center justify-center text-xs font-bold shrink-0">{i + 1}</div>
                  <input value={stage.name} onChange={e => updateStage(i, 'name', e.target.value)}
                    className="flex-1 px-2 py-1 border border-border-light rounded outline-none text-sm font-medium" />
                  <div className="flex gap-1">
                    <button onClick={() => moveStage(i, -1)} disabled={i === 0} className="w-6 h-6 rounded text-text-secondary hover:text-primary disabled:opacity-30 flex items-center justify-center"><AppIcon className="fas fa-arrow-up text-xs" /></button>
                    <button onClick={() => moveStage(i, 1)} disabled={i === stages.length - 1} className="w-6 h-6 rounded text-text-secondary hover:text-primary disabled:opacity-30 flex items-center justify-center"><AppIcon className="fas fa-arrow-down text-xs" /></button>
                    <button onClick={() => removeStage(i)} className="w-6 h-6 rounded text-text-secondary hover:text-danger flex items-center justify-center"><AppIcon className="fas fa-times text-xs" /></button>
                  </div>
                </div>
                {/* 选课程 */}
                <div className="mb-2">
                  <div className="text-xs text-text-secondary mb-1.5">本阶段课程（全部学完解锁下一阶段）</div>
                  <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                    {courses.map(c => {
                      const checked = (stage.courseIds || []).includes(c.id);
                      return (
                        <label key={c.id} className={`px-2 py-1 rounded text-xs cursor-pointer border ${checked ? 'bg-primary/10 border-primary text-primary' : 'border-border-light text-text-secondary hover:border-primary/40'}`}>
                          <input type="checkbox" className="hidden" checked={checked} onChange={() => toggleCourse(i, c.id)} />
                          {c.title}
                        </label>
                      );
                    })}
                  </div>
                </div>
                {/* 选考试（可选）*/}
                <div>
                  <div className="text-xs text-text-secondary mb-1">阶段考试（可选，通过后解锁）</div>
                  <select value={stage.examTaskId || ''} onChange={e => updateStage(i, 'examTaskId', e.target.value || undefined)}
                    className="text-sm border border-border-light rounded px-2 py-1 outline-none">
                    <option value="">无考试</option>
                    {tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                  </select>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex gap-2">
          <button onClick={() => save('draft')} disabled={saving} className="flex-1 py-2.5 text-sm border border-border-light rounded-lg text-text-secondary hover:bg-bg-light">存草稿</button>
          <button onClick={() => save('published')} disabled={saving} className="flex-1 py-2.5 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">保存并发布</button>
        </div>
      </div>
    </Layout>
  );
}
