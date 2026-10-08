// @ts-nocheck
/**
 * 考试安排 — 考试任务卡片 + 新建/发布 + 指派
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState, StatusBadge } from '../../components/PageParts';
import { hrmApi, trainingExamApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const STATUS_MAP = {
  draft: { label: '草稿', tone: 'warning' },
  published: { label: '进行中', tone: 'success' },
  closed: { label: '已结束', tone: 'neutral' },
};

const fmtTime = (t) => {
  if (!t) return '不限';
  try { return new Date(t.includes('Z') ? t : t + 'Z').toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return t; }
};

const OPTION_LIMIT = 120;

const normalizeKeyword = (value) => String(value || '').trim().toLowerCase();

const matchesKeyword = (item, keyword, fields) => {
  if (!keyword) return true;
  return fields.some(field => String(item?.[field] || '').toLowerCase().includes(keyword));
};

const employeeMeta = (emp) => [
  emp.employeeNo,
  emp.departmentName,
  emp.jobTitle || emp.positionTitle,
].filter(Boolean).join(' · ');

export default function P_exam_tasks() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [papers, setPapers] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [t, p, d, e] = await Promise.all([
        hrmApi.list('exam-tasks'), hrmApi.list('exam-papers'),
        hrmApi.list('departments'), hrmApi.list('employees'),
      ]);
      setTasks(t || []);
      setPapers((p || []).filter(x => x.status === 'published'));
      setDepartments(d || []);
      setEmployees(e || []);
    } catch (err) { toast.error(err.message || '加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const publish = async (task) => {
    if (!await confirm(`发布「${task.title}」？将为指派目标生成考试授权。`)) return;
    try { const r = await trainingExamApi.publishTask(task.id); toast.success(`已发布，授权 ${r.assignedTotal} 人`); load(); }
    catch (e) { toast.error(e.message || '发布失败'); }
  };

  const remove = async (task) => {
    if (!await confirm(`删除考试「${task.title}」？`)) return;
    try { await hrmApi.remove('exam-tasks', task.id); toast.success('已删除'); load(); }
    catch (e) { toast.error(e.message || '删除失败'); }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <PageHeader icon="fa-calendar-check" title="考试安排" subtitle="安排考试任务，指派参加人员"
          actions={<button onClick={() => setShowForm(true)} disabled={papers.length === 0}
            className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
            <AppIcon className="fas fa-plus" /> 新建考试
          </button>} />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatPill label="考试总数" value={tasks.length} icon="fa-calendar-check" />
          <StatPill label="进行中" value={tasks.filter(t => t.status === 'published').length} icon="fa-play" tone="success" />
          <StatPill label="草稿" value={tasks.filter(t => t.status === 'draft').length} icon="fa-pen" tone="warning" />
          <StatPill label="已结束" value={tasks.filter(t => t.status === 'closed').length} icon="fa-flag-checkered" tone="neutral" />
        </div>

        {papers.length === 0 && (
          <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning flex items-center gap-2">
            <AppIcon className="fas fa-info-circle" /> 请先在「试卷组卷」创建并发布至少一份试卷，才能安排考试。
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : tasks.length === 0 ? (
          <EmptyState icon="fa-calendar-check" title="还没有考试安排" hint={papers.length ? '新建第一场考试' : '请先创建试卷'} />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {tasks.map(t => (
              <div key={t.id} className="bg-white rounded-xl border border-border-light overflow-hidden hover:shadow-card transition-shadow">
                <div className={`h-1 ${t.status === 'published' ? 'bg-success' : t.status === 'closed' ? 'bg-text-secondary' : 'bg-warning'}`} />
                <div className="p-5">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2.5">
                      <div className="w-10 h-10 rounded-lg bg-warning/10 flex items-center justify-center shrink-0">
                        <AppIcon className="fas fa-calendar-check text-warning" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-text-primary line-clamp-1">{t.title}</h3>
                        <div className="text-xs text-text-secondary mt-0.5 flex flex-wrap items-center gap-2">
                          <span>{t.paperTitle || '未关联试卷'}</span>
                          {t.questionMode === 'random' ? (
                            <span className="px-2 py-0.5 rounded bg-warning/10 text-warning">随机抽题 · 题池 {t.poolCount || 0} 抽 {t.questionCount || t.drawCount || 0}</span>
                          ) : t.paperId ? (
                            <span className="px-2 py-0.5 rounded bg-success/10 text-success">固定试卷</span>
                          ) : null}
                        </div>
                        {t.status === 'draft' && <div className="text-xs text-warning mt-1 flex items-center gap-1"><AppIcon className="fas fa-circle-exclamation" /> 草稿未发布，员工不可见</div>}
                      </div>
                    </div>
                    <StatusBadge status={t.status} map={STATUS_MAP} />
                  </div>
                  {t.description && <p className="text-sm text-text-secondary mt-2 line-clamp-2">{t.description}</p>}
                  <div className="mt-3 flex items-center gap-3 text-xs text-text-secondary">
                    <span className="flex items-center gap-1"><AppIcon className="fas fa-clock" /> {fmtTime(t.startTime)}</span>
                    <span>→</span>
                    <span>{fmtTime(t.endTime)}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-text-secondary">
                    <span><AppIcon className="fas fa-redo" /> {t.maxAttempts} 次</span>
                    <span><AppIcon className="fas fa-users" /> {t.targetType === 'dept' ? '按部门' : '按员工'} · {(t.targetIds || []).length} 个</span>
                  </div>
                  <div className="mt-4 pt-3 border-t border-border-light flex items-center gap-2">
                    <button onClick={() => navigate(`/exam-task-progress/${t.id}`)}
                      className="flex-1 text-sm py-1.5 border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                      <AppIcon className="fas fa-chart-bar text-xs" /> 查看进度
                    </button>
                    {t.status === 'draft' && (
                      <button onClick={() => publish(t)} className="px-3 py-1.5 text-sm bg-success text-white rounded-lg hover:bg-green-700 flex items-center gap-1">
                        <AppIcon className="fas fa-rocket text-xs" /> 发布
                      </button>
                    )}
                    <button onClick={() => remove(t)} className="w-8 h-8 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center">
                      <AppIcon className="fas fa-trash text-xs" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {showForm && <TaskForm papers={papers} departments={departments} employees={employees}
          onCancel={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />}
      </div>
    </Layout>
  );
}

function TaskForm({ papers, departments, employees, onCancel, onSaved }) {
  const [title, setTitle] = useState('');
  const [paperId, setPaperId] = useState(papers[0]?.id || '');
  const [description, setDescription] = useState('');
  const [maxAttempts, setMaxAttempts] = useState(1);
  const [targetType, setTargetType] = useState('dept');
  const [selectedDepts, setSelectedDepts] = useState([]);
  const [selectedEmps, setSelectedEmps] = useState([]);
  const [deptQuery, setDeptQuery] = useState('');
  const [empQuery, setEmpQuery] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [saving, setSaving] = useState(false);

  const deptKeyword = normalizeKeyword(deptQuery);
  const empKeyword = normalizeKeyword(empQuery);
  const filteredDepartments = useMemo(
    () => departments.filter(d => matchesKeyword(d, deptKeyword, ['name', 'code', 'description'])),
    [departments, deptKeyword],
  );
  const visibleDepartments = filteredDepartments.slice(0, OPTION_LIMIT);
  const filteredEmployees = useMemo(
    () => employees.filter(emp => matchesKeyword(emp, empKeyword, ['name', 'employeeNo', 'departmentName', 'positionTitle', 'jobTitle', 'email', 'phone'])),
    [employees, empKeyword],
  );
  const visibleEmployees = filteredEmployees.slice(0, OPTION_LIMIT);
  const selectedDeptItems = useMemo(
    () => departments.filter(d => selectedDepts.includes(d.id)),
    [departments, selectedDepts],
  );
  const selectedEmpItems = useMemo(
    () => employees.filter(emp => selectedEmps.includes(emp.id)),
    [employees, selectedEmps],
  );

  const submit = async () => {
    if (!title.trim()) { toast.error('请输入考试标题'); return; }
    if (!paperId) { toast.error('请选择试卷'); return; }
    const targetIds = targetType === 'dept' ? selectedDepts : selectedEmps;
    if (targetIds.length === 0) { toast.error(`请选择至少一个${targetType === 'dept' ? '部门' : '员工'}`); return; }
    if (!Number(maxAttempts) || Number(maxAttempts) <= 0) { toast.error('考试次数须大于 0'); return; }
    if (startTime && endTime && new Date(endTime) <= new Date(startTime)) { toast.error('结束时间须晚于开始时间'); return; }
    setSaving(true);
    try {
      await hrmApi.create('exam-tasks', {
        title: title.trim(), paperId, description, maxAttempts: Number(maxAttempts),
        targetType, targetIds,
        startTime: startTime ? new Date(startTime).toISOString() : null,
        endTime: endTime ? new Date(endTime).toISOString() : null,
        status: 'draft',
      });
      toast.success('考试已创建（草稿），可在列表中发布');
      onSaved();
    } catch (e) { toast.error(e.message || '创建失败'); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onCancel}>
      <div className="bg-white rounded-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">新建考试</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm text-text-secondary mb-1">考试标题 *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none focus:border-primary" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">试卷 *</label>
            <select value={paperId} onChange={e => setPaperId(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none">
              {papers.map(p => <option key={p.id} value={p.id}>{p.title}（{p.totalScore}分）</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">说明</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm text-text-secondary mb-1">开始时间</label>
              <input type="datetime-local" value={startTime} onChange={e => setStartTime(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" />
            </div>
            <div>
              <label className="block text-sm text-text-secondary mb-1">结束时间</label>
              <input type="datetime-local" value={endTime} onChange={e => setEndTime(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" />
            </div>
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">最大考试次数</label>
            <input type="number" min={1} value={maxAttempts} onChange={e => setMaxAttempts(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">指派方式</label>
            <div className="flex gap-2 mb-2">
              <button type="button" onClick={() => setTargetType('dept')} className={`px-3 py-1.5 rounded-lg text-sm ${targetType === 'dept' ? 'bg-primary text-white' : 'border border-border-light text-text-secondary'}`}>按部门</button>
              <button type="button" onClick={() => setTargetType('user')} className={`px-3 py-1.5 rounded-lg text-sm ${targetType === 'user' ? 'bg-primary text-white' : 'border border-border-light text-text-secondary'}`}>按员工</button>
            </div>
            {targetType === 'dept' ? (
              <div className="border border-border-light rounded-lg overflow-hidden">
                <div className="p-3 border-b border-border-light bg-surface-light/60 space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                    <div className="relative flex-1 min-w-0">
                      <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary text-xs" />
                      <input
                        value={deptQuery}
                        onChange={e => setDeptQuery(e.target.value)}
                        placeholder="搜索部门名称或编号"
                        className="w-full pl-8 pr-3 py-2 text-sm border border-border-light rounded-lg outline-none focus:border-primary bg-white"
                      />
                    </div>
                    {deptQuery && (
                      <button type="button" onClick={() => setDeptQuery('')} className="w-full sm:w-auto px-3 py-2 text-xs border border-border-light rounded-lg text-text-secondary hover:text-text-primary">
                        清空搜索
                      </button>
                    )}
                    {selectedDepts.length > 0 && (
                      <button type="button" onClick={() => setSelectedDepts([])} className="w-full sm:w-auto px-3 py-2 text-xs border border-border-light rounded-lg text-danger hover:bg-danger/5">
                        清空已选
                      </button>
                    )}
                  </div>
                  <div className="text-xs text-text-secondary">
                    已选 {selectedDepts.length} 个部门，当前匹配 {filteredDepartments.length} 个
                  </div>
                  {selectedDeptItems.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedDeptItems.map(d => (
                        <button
                          key={d.id}
                          type="button"
                          onClick={() => setSelectedDepts(prev => prev.filter(x => x !== d.id))}
                          className="px-2 py-1 rounded bg-primary/10 text-primary text-xs hover:bg-primary/15"
                          title="点击移除"
                        >
                          {d.name}
                          {d.code ? <span className="ml-1 text-primary/70">{d.code}</span> : null}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="max-h-56 overflow-y-auto p-2 space-y-1">
                  {visibleDepartments.length === 0 ? (
                    <div className="py-6 text-center text-sm text-text-secondary">没有匹配的部门</div>
                  ) : visibleDepartments.map(d => (
                    <label key={d.id} className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer border ${selectedDepts.includes(d.id) ? 'bg-primary/10 border-primary text-primary' : 'border-transparent hover:border-border-light hover:bg-surface-light'}`}>
                      <input type="checkbox" checked={selectedDepts.includes(d.id)} onChange={() => setSelectedDepts(prev => prev.includes(d.id) ? prev.filter(x => x !== d.id) : [...prev, d.id])} />
                      <span className="flex-1 min-w-0">
                        <span className="block truncate">{d.name}</span>
                        {d.code ? <span className="block text-xs text-text-secondary truncate">{d.code}</span> : null}
                      </span>
                    </label>
                  ))}
                  {filteredDepartments.length > OPTION_LIMIT && (
                    <div className="px-3 py-2 text-xs text-text-secondary">还有 {filteredDepartments.length - OPTION_LIMIT} 个部门未显示，请继续输入关键词缩小范围。</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="border border-border-light rounded-lg overflow-hidden">
                <div className="p-3 border-b border-border-light bg-surface-light/60 space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                    <div className="relative flex-1 min-w-0">
                      <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary text-xs" />
                      <input
                        value={empQuery}
                        onChange={e => setEmpQuery(e.target.value)}
                        placeholder="搜索姓名、工号、部门、岗位"
                        className="w-full pl-8 pr-3 py-2 text-sm border border-border-light rounded-lg outline-none focus:border-primary bg-white"
                      />
                    </div>
                    {empQuery && (
                      <button type="button" onClick={() => setEmpQuery('')} className="w-full sm:w-auto px-3 py-2 text-xs border border-border-light rounded-lg text-text-secondary hover:text-text-primary">
                        清空搜索
                      </button>
                    )}
                    {selectedEmps.length > 0 && (
                      <button type="button" onClick={() => setSelectedEmps([])} className="w-full sm:w-auto px-3 py-2 text-xs border border-border-light rounded-lg text-danger hover:bg-danger/5">
                        清空已选
                      </button>
                    )}
                  </div>
                  <div className="text-xs text-text-secondary">
                    已选 {selectedEmps.length} 人，当前匹配 {filteredEmployees.length} 人
                  </div>
                  {selectedEmpItems.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 max-h-20 overflow-y-auto">
                      {selectedEmpItems.map(emp => (
                        <button
                          key={emp.id}
                          type="button"
                          onClick={() => setSelectedEmps(prev => prev.filter(x => x !== emp.id))}
                          className="px-2 py-1 rounded bg-primary/10 text-primary text-xs hover:bg-primary/15"
                          title="点击移除"
                        >
                          {emp.name}
                          {emp.employeeNo ? <span className="ml-1 text-primary/70">{emp.employeeNo}</span> : null}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="max-h-64 overflow-y-auto p-2 space-y-1">
                  {visibleEmployees.length === 0 ? (
                    <div className="py-6 text-center text-sm text-text-secondary">没有匹配的员工</div>
                  ) : visibleEmployees.map(emp => (
                    <label key={emp.id} className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer border ${selectedEmps.includes(emp.id) ? 'bg-primary/10 border-primary text-primary' : 'border-transparent hover:border-border-light hover:bg-surface-light'}`}>
                      <input type="checkbox" checked={selectedEmps.includes(emp.id)} onChange={() => setSelectedEmps(prev => prev.includes(emp.id) ? prev.filter(x => x !== emp.id) : [...prev, emp.id])} />
                      <span className="flex-1 min-w-0">
                        <span className="block truncate">{emp.name}</span>
                        <span className="block text-xs text-text-secondary truncate">{employeeMeta(emp) || '未设置工号/部门/岗位'}</span>
                      </span>
                    </label>
                  ))}
                  {filteredEmployees.length > OPTION_LIMIT && (
                    <div className="px-3 py-2 text-xs text-text-secondary">还有 {filteredEmployees.length - OPTION_LIMIT} 人未显示，请继续输入关键词缩小范围。</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={submit} disabled={saving} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{saving ? '创建中…' : '创建（草稿）'}</button>
        </div>
      </div>
    </div>
  );
}
