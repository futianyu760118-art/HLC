// @ts-nocheck
/**
 * 课程分类管理 — 卡片网格 + 新建/编辑/删除
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import { hrmApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const CAT_ICONS = ['fa-folder', 'fa-tag', 'fa-bookmark', 'fa-star', 'fa-flag', 'fa-circle'];

export default function P_course_categories() {
  const [cats, setCats] = useState([]);
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [c, courseList] = await Promise.all([hrmApi.list('course-categories'), hrmApi.list('courses')]);
      setCats(c || []);
      setCourses(courseList || []);
    } catch (e) { toast.error(e.message || '加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const courseCount = (catId) => courses.filter(c => c.categoryId === catId).length;

  const remove = async (cat) => {
    if (deletingId) return;
    const n = courseCount(cat.id);
    if (!await confirm(n > 0 ? `分类「${cat.name}」下有 ${n} 门课程，删除后课程将变为未分类。继续？` : `删除分类「${cat.name}」？`)) return;
    setDeletingId(cat.id);
    try { await hrmApi.remove('course-categories', cat.id); toast.success('已删除'); load(); }
    catch (e) { toast.error(e.message || '删除失败'); }
    finally { setDeletingId(null); }
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-6 py-6">
        <PageHeader icon="fa-folder-tree" title="课程分类" subtitle="组织课程内容，便于员工查找"
          actions={<button onClick={() => { setEditing(null); setShowForm(true); }}
            className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
            <AppIcon className="fas fa-plus" /> 新建分类
          </button>} />

        <div className="grid grid-cols-3 gap-3 mb-5">
          <StatPill label="分类总数" value={cats.length} icon="fa-folder-tree" />
          <StatPill label="已用分类" value={cats.filter(c => courseCount(c.id) > 0).length} icon="fa-check" tone="success" />
          <StatPill label="课程总数" value={courses.length} icon="fa-book-open" tone="neutral" />
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : cats.length === 0 ? (
          <EmptyState icon="fa-folder-tree" title="还没有分类" hint="创建第一个课程分类" />
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {cats.map((cat, i) => (
              <div key={cat.id} className="group bg-white rounded-xl border border-border-light p-4 hover:shadow-card transition-shadow">
                <div className="flex items-start justify-between">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                    style={{ background: ['#dbeafe', '#dcfce7', '#fef3c7', '#fce7f3', '#e0e7ff', '#cffafe'][i % 6] }}>
                    <AppIcon className={`fas ${CAT_ICONS[i % CAT_ICONS.length]} text-sm`} style={{ color: ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2'][i % 6] }} />
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => { setEditing(cat); setShowForm(true); }} className="w-7 h-7 rounded text-text-secondary hover:text-primary hover:bg-bg-light flex items-center justify-center">
                      <AppIcon className="fas fa-pen text-xs" />
                    </button>
                    <button onClick={() => remove(cat)} disabled={deletingId === cat.id} className="w-7 h-7 rounded text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center disabled:opacity-40">
                      <AppIcon className="fas fa-trash text-xs" />
                    </button>
                  </div>
                </div>
                <h3 className="font-medium text-text-primary mt-3">{cat.name}</h3>
                <p className="text-xs text-text-secondary mt-1">{courseCount(cat.id)} 门课程</p>
              </div>
            ))}
          </div>
        )}

        {showForm && <CategoryForm category={editing} categories={cats} onCancel={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />}
      </div>
    </Layout>
  );
}

function CategoryForm({ category, categories, onCancel, onSaved }) {
  const [name, setName] = useState(category?.name || '');
  const [parentId, setParentId] = useState(category?.parentId || '');
  const [saving, setSaving] = useState(false);

  // 计算编辑分类的所有后代 id（含自身），用于父级下拉排除，防止循环引用
  const descendantIds = (() => {
    if (!category) return new Set();
    const result = new Set([category.id]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const c of (categories || [])) {
        if (c.parentId && result.has(c.parentId) && !result.has(c.id)) {
          result.add(c.id);
          changed = true;
        }
      }
    }
    return result;
  })();

  const submit = async () => {
    if (!name.trim()) { toast.error('请输入分类名称'); return; }
    // 防止将自身或后代设为父级（形成循环）
    if (parentId && descendantIds.has(parentId)) {
      toast.error('不能将自身或子分类设为上级分类');
      return;
    }
    setSaving(true);
    try {
      if (category) await hrmApi.update('course-categories', category.id, { name: name.trim(), parentId: parentId || undefined });
      else await hrmApi.create('course-categories', { name: name.trim(), parentId: parentId || undefined, sort: 0 });
      toast.success(category ? '已更新' : '已创建');
      onSaved();
    } catch (e) { toast.error(e.message || '保存失败'); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-white rounded-xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">{category ? '编辑分类' : '新建分类'}</h2>
        <input value={name} onChange={e => setName(e.target.value)} autoFocus placeholder="分类名称"
          className="w-full px-3 py-2 border border-border-light rounded-lg outline-none focus:border-primary mb-3" />
        <div className="mb-3">
          <label className="block text-sm text-text-secondary mb-1">上级分类</label>
          <select value={parentId} onChange={e => setParentId(e.target.value)}
            className="w-full px-3 py-2 border border-border-light rounded-lg outline-none">
            <option value="">作为一级分类</option>
            {(categories || []).filter(c => !descendantIds.has(c.id)).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={submit} disabled={saving} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{saving ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>
  );
}
