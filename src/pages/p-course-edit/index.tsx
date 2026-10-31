// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 课程编辑器（Chunk 7）
 * 管理课程基本信息 + 章节/课时（视频上传）+ 指派部门/员工
 */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { fileApi, hrmApi, trainingExamApi } from '../../utils/api';
import { MarkdownEditor } from '../../components/MarkdownEditor';
import { ProtectedImage } from '../../components/ProtectedFile';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

export default function P_course_edit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [course, setCourse] = useState<any>(null);
  const [chapters, setChapters] = useState<any[]>([]);
  const [hours, setHours] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [departments, setDepartments] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [assignments, setAssignments] = useState<{ deptIds: string[]; userIds: string[] }>({ deptIds: [], userIds: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingAssign, setSavingAssign] = useState(false);
  const [uploadProgressByHour, setUploadProgressByHour] = useState<Record<string, number>>({});

  const loadAll = async () => {
    setLoading(true);
    try {
      const [c, chapList, hourList, deptList, empList, assignList, catList] = await Promise.all([
        hrmApi.get('courses', id),
        hrmApi.list('course-chapters'),
        hrmApi.list('course-hours'),
        hrmApi.list('departments'),
        hrmApi.list('employees'),
        hrmApi.list('course-assignments'),
        hrmApi.list('course-categories'),
      ]);
      setCourse(c);
      setCategories(catList || []);
      setChapters((chapList || []).filter((x: any) => x.courseId === id));
      setHours((hourList || []).filter((x: any) => x.courseId === id));
      setDepartments(deptList || []);
      setEmployees(empList || []);
      const mine = (assignList || []).filter((x: any) => x.courseId === id);
      setAssignments({
        deptIds: mine.filter((x: any) => x.targetType === 'dept').map((x: any) => x.targetId),
        userIds: mine.filter((x: any) => x.targetType === 'user').map((x: any) => x.targetId),
      });
    } catch (e: any) {
      toast.error(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, [id]);

  const updateCourseField = (field: string, value: any) => {
    setCourse((prev: any) => ({ ...prev, [field]: value }));
  };

  const saveCourse = async () => {
    if (!course.title?.trim()) { toast.error('请输入课程标题'); return; }
    setSaving(true);
    try {
      await hrmApi.update('courses', id, {
        title: course.title, categoryId: course.categoryId, coverUrl: course.coverUrl,
        isRequired: course.isRequired, deadline: course.deadline, shortDesc: course.shortDesc, content: course.content,
        isShow: course.isShow, classHour: hours.length, sort: course.sort || 0,
      });
      toast.success('课程已保存');
    } catch (e: any) { toast.error(e.message || '保存失败'); }
    finally { setSaving(false); }
  };

  const addChapter = async () => {
    const name = window.prompt('章节名称');
    if (!name) return;
    try {
      await hrmApi.create('course-chapters', { courseId: id, name, sort: chapters.length });
      toast.success('已添加章节');
      loadAll();
    } catch (e: any) { toast.error(e.message || '添加失败'); }
  };

  const addHour = async (chapterId?: string) => {
    const title = window.prompt('课时标题');
    if (!title) return;
    try {
      await hrmApi.create('course-hours', { courseId: id, chapterId: chapterId || null, title, type: 'VIDEO', sort: hours.length });
      toast.success('已添加课时');
      loadAll();
    } catch (e: any) { toast.error(e.message || '添加失败'); }
  };

  const uploadVideo = async (hourId: string, file: File) => {
    setUploadProgressByHour(prev => ({ ...prev, [hourId]: 0 }));
    try {
      await trainingExamApi.uploadHourVideo(hourId, file, ({ percent }) => {
        setUploadProgressByHour(prev => ({ ...prev, [hourId]: percent }));
      });
      toast.success('视频上传成功');
      loadAll();
    } catch (e: any) { toast.error(e.message || '上传失败'); }
    finally {
      setUploadProgressByHour(prev => {
        const next = { ...prev };
        delete next[hourId];
        return next;
      });
    }
  };

  const removeHour = async (hourId: string) => {
    if (!await confirm('删除该课时？')) return;
    try {
      await hrmApi.remove('course-hours', hourId);
      toast.success('已删除');
      loadAll();
    } catch (e: any) { toast.error(e.message || '删除失败'); }
  };

  const saveAssignments = async () => {
    setSavingAssign(true);
    try {
      await trainingExamApi.assignCourse(id, assignments);
      toast.success('指派已保存');
    } catch (e: any) { toast.error(e.message || '保存失败'); }
    finally { setSavingAssign(false); }
  };

  const toggleDept = (deptId: string) => {
    setAssignments(prev => ({
      ...prev,
      deptIds: prev.deptIds.includes(deptId) ? prev.deptIds.filter(x => x !== deptId) : [...prev.deptIds, deptId],
    }));
  };
  const toggleUser = (empId: string) => {
    setAssignments(prev => ({
      ...prev,
      userIds: prev.userIds.includes(empId) ? prev.userIds.filter(x => x !== empId) : [...prev.userIds, empId],
    }));
  };

  if (loading) return <Layout><div className="p-10 text-center text-gray-400">加载中…</div></Layout>;
  if (!course) return <Layout><div className="p-10 text-center text-red-500">课程不存在</div></Layout>;

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/hrm/courses')} className="text-gray-500 hover:text-gray-700">
              <AppIcon className="fas fa-arrow-left" />
            </button>
            <h1 className="text-2xl font-bold">编辑课程</h1>
          </div>
          <button onClick={saveCourse} disabled={saving} className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">保存课程</button>
        </div>

        {/* 基本信息 */}
        <div className="bg-white rounded-lg shadow p-5 space-y-3">
          <h2 className="font-semibold">基本信息</h2>
          {/* 封面上传 */}
          <div className="flex items-center gap-4">
            <div className="w-32 h-20 rounded-lg overflow-hidden border border-gray-200 bg-gray-50 shrink-0 flex items-center justify-center">
              {course.coverUrl
                ? <ProtectedImage fileUrl={course.coverUrl} className="w-full h-full object-cover" alt="" />
                : <AppIcon className="fas fa-image text-2xl text-gray-300" />}
            </div>
            <div className="flex-1">
              <label className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded cursor-pointer hover:bg-gray-50">
                <AppIcon className="fas fa-upload text-xs" />
                {course.coverUrl ? '更换封面' : '上传封面'}
                <input type="file" accept="image/*" className="hidden" onChange={async e => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    toast.info('上传中…');
                    const res = await trainingExamApi.uploadCourseCover(course.id, f);
                    updateCourseField('coverUrl', res.coverUrl);
                    toast.success('封面已设置');
                  } catch (err) { toast.error(err.message || '上传失败'); }
                  e.target.value = '';
                }} />
              </label>
              {course.coverUrl && (
                <button onClick={async () => {
                  if (!await confirm('移除封面？')) return;
                  updateCourseField('coverUrl', '');
                  await hrmApi.update('courses', course.id, { coverUrl: '' });
                  toast.success('已移除');
                }} className="ml-2 text-sm text-red-500 hover:text-red-700">移除</button>
              )}
              <div className="text-xs text-gray-400 mt-1">建议 16:9 比例，JPG/PNG</div>
            </div>
          </div>
          <input value={course.title || ''} onChange={e => updateCourseField('title', e.target.value)}
            placeholder="课程标题" className="w-full border rounded px-3 py-2" />
          <div>
            <label className="block text-sm text-gray-700 mb-1">课程分类</label>
            <select value={course.categoryId || ''} onChange={e => updateCourseField('categoryId', e.target.value || undefined)}
              className="w-full border rounded px-3 py-2">
              <option value="">不分类</option>
              {categories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
            </select>
          </div>
          <textarea value={course.shortDesc || ''} onChange={e => updateCourseField('shortDesc', e.target.value)}
            placeholder="简介（一句话）" rows={2} className="w-full border rounded px-3 py-2" />
          <div>
            <label className="block text-sm text-gray-700 mb-1">课程介绍（支持 Markdown 富文本）</label>
            <MarkdownEditor value={course.content || ''} onChange={v => updateCourseField('content', v)}
              placeholder="用 Markdown 编写详细的课程介绍、学习目标、适合人群等…" rows={8} />
          </div>
          <div className="flex gap-4 flex-wrap items-center">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={!!course.isRequired} onChange={e => updateCourseField('isRequired', e.target.checked)} />
              必修
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={course.isShow !== false} onChange={e => updateCourseField('isShow', e.target.checked)} />
              上架
            </label>
            {course.isRequired && (
              <label className="flex items-center gap-1.5 text-sm text-gray-700">
                完成截止：
                <input type="datetime-local"
                  value={course.deadline ? new Date(new Date(course.deadline).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''}
                  onChange={e => updateCourseField('deadline', e.target.value ? new Date(e.target.value).toISOString() : null)}
                  className="border rounded px-2 py-1 text-sm" />
              </label>
            )}
          </div>
        </div>

        {/* 章节与课时 */}
        <div className="bg-white rounded-lg shadow p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">章节与课时</h2>
            <div className="flex gap-2">
              <button onClick={addChapter} className="text-sm bg-gray-100 px-3 py-1 rounded hover:bg-gray-200">+ 章节</button>
              <button onClick={() => addHour()} className="text-sm bg-gray-100 px-3 py-1 rounded hover:bg-gray-200">+ 课时</button>
            </div>
          </div>
          {chapters.length === 0 && hours.length === 0 && <div className="text-gray-400 text-sm">暂无章节/课时</div>}
          {chapters.map(ch => (
            <div key={ch.id} className="border rounded p-3">
              <input defaultValue={ch.name}
                onBlur={async e => {
                  if (e.target.value.trim() && e.target.value !== ch.name) {
                    await hrmApi.update('course-chapters', ch.id, { name: e.target.value.trim() });
                    toast.success('章节名已更新');
                    loadAll();
                  }
                }}
                className="font-medium mb-2 w-full bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-400 outline-none" />
              {ch.description && <div className="text-xs text-gray-500 mb-2">{ch.description}</div>}
              <div className="space-y-2">
                {hours.filter(h => h.chapterId === ch.id).map(h => (
                  <HourRow key={h.id} hour={h} uploadProgress={uploadProgressByHour[h.id]} onUpload={uploadVideo} onRemove={removeHour} />
                ))}
                <button onClick={() => addHour(ch.id)} className="text-xs text-blue-600">+ 添加课时到本章节</button>
              </div>
              <ChapterMaterials key={ch.id} chapter={ch} onChange={loadAll} />
            </div>
          ))}
          {hours.filter(h => !h.chapterId).length > 0 && (
            <div className="border rounded p-3">
              <div className="font-medium mb-2 text-gray-500">未分组课时</div>
              {hours.filter(h => !h.chapterId).map(h => (
                <HourRow key={h.id} hour={h} uploadProgress={uploadProgressByHour[h.id]} onUpload={uploadVideo} onRemove={removeHour} />
              ))}
            </div>
          )}
        </div>

        {/* 指派 */}
        <div className="bg-white rounded-lg shadow p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">指派（无指派 = 全员可见）</h2>
            <button onClick={saveAssignments} disabled={savingAssign} className="bg-blue-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50">保存指派</button>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">按部门</div>
            <div className="flex flex-wrap gap-2">
              {departments.map((d: any) => (
                <label key={d.id} className={`px-3 py-1 rounded border cursor-pointer text-sm ${assignments.deptIds.includes(d.id) ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white'}`}>
                  <input type="checkbox" className="hidden" checked={assignments.deptIds.includes(d.id)} onChange={() => toggleDept(d.id)} />
                  {d.name}
                </label>
              ))}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">按员工</div>
            <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
              {employees.map((emp: any) => (
                <label key={emp.id} className={`px-3 py-1 rounded border cursor-pointer text-sm ${assignments.userIds.includes(emp.id) ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white'}`}>
                  <input type="checkbox" className="hidden" checked={assignments.userIds.includes(emp.id)} onChange={() => toggleUser(emp.id)} />
                  {emp.name}
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}

function HourRow({ hour, uploadProgress, onUpload, onRemove }: { hour: any; uploadProgress?: number; onUpload: (id: string, f: File) => void; onRemove: (id: string) => void }) {
  const isUploading = typeof uploadProgress === 'number';
  return (
    <div className="flex items-center gap-2 text-sm bg-gray-50 rounded px-2 py-1.5">
      <AppIcon className="fas fa-play-circle text-gray-400" />
      <span className="flex-1">{hour.title}</span>
      {hour.duration ? <span className="text-xs text-gray-400">{Math.round(hour.duration / 60)}分钟</span> : null}
      {isUploading ? (
        <div className="w-28 shrink-0">
          <div className="text-[11px] text-blue-600 text-right">{uploadProgress}%</div>
          <div className="h-1.5 bg-blue-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-600 transition-all" style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      ) : hour.videoKey ? <span className="text-xs text-green-600">已上传</span> : <span className="text-xs text-gray-400">未上传</span>}
      <label className={`text-xs ${isUploading ? 'text-gray-400 cursor-not-allowed' : 'text-blue-600 cursor-pointer'}`}>
        上传
        <input type="file" accept="video/*" className="hidden" disabled={isUploading}
          onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(hour.id, f); e.target.value = ''; }} />
      </label>
      <button onClick={() => onRemove(hour.id)} disabled={isUploading} className={`text-xs ${isUploading ? 'text-gray-300 cursor-not-allowed' : 'text-red-500'}`}>删除</button>
    </div>
  );
}

function ChapterMaterials({ chapter, onChange }: { chapter: any; onChange: () => void }) {
  const [uploading, setUploading] = useState(false);
  const materials: Array<{ title: string; url: string; ext: string }> = chapter.materials || [];

  const onUpload = async (file: File) => {
    setUploading(true);
    try {
      await trainingExamApi.uploadChapterMaterial(chapter.id, file);
      toast.success('资料已上传');
      onChange();
    } catch (e: any) {
      toast.error(e.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const removeMaterial = async (url: string) => {
    if (!await confirm('移除该资料？')) return;
    const next = materials.filter(m => m.url !== url);
    try {
      await trainingExamApi.updateChapterMaterials(chapter.id, next);
      toast.success('已移除');
      onChange();
    } catch (e: any) { toast.error(e.message || '操作失败'); }
  };

  const fileIcon = (ext: string) => {
    const m: Record<string, string> = {
      pdf: 'fa-file-pdf text-red-500', doc: 'fa-file-word text-blue-500', docx: 'fa-file-word text-blue-500',
      ppt: 'fa-file-powerpoint text-orange-500', pptx: 'fa-file-powerpoint text-orange-500',
      xls: 'fa-file-excel text-green-600', xlsx: 'fa-file-excel text-green-600',
      txt: 'fa-file-alt text-gray-500', md: 'fa-file-alt text-gray-500',
      png: 'fa-file-image text-purple-500', jpg: 'fa-file-image text-purple-500', jpeg: 'fa-file-image text-purple-500',
    };
    return m[ext] || 'fa-file text-gray-400';
  };

  return (
    <div className="mt-3 border-t pt-2">
      <div className="text-xs text-gray-500 mb-1 flex items-center justify-between">
        <span>章节资料（员工可下载）</span>
        <label className="text-blue-600 cursor-pointer hover:text-blue-800 flex items-center gap-1">
          <AppIcon className={uploading ? 'fas fa-spinner fa-spin' : 'fas fa-upload'} />
          {uploading ? '上传中…' : '上传资料'}
          <input type="file" className="hidden" disabled={uploading}
            accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.png,.jpg,.jpeg"
            onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ''; }} />
        </label>
      </div>
      {materials.length === 0 ? (
        <div className="text-xs text-gray-400">暂无资料</div>
      ) : (
        <div className="space-y-1">
          {materials.map((m, i) => (
            <div key={i} className="flex items-center gap-2 text-sm bg-gray-50 rounded px-2 py-1.5">
              <AppIcon className={`fas ${fileIcon(m.ext)}`} />
              <span className="flex-1 truncate">{m.title}.{m.ext}</span>
              <button type="button" onClick={async () => {
                try {
                  const url = await fileApi.getBlobUrl(m.url);
                  window.open(url, '_blank', 'noopener,noreferrer');
                  setTimeout(() => URL.revokeObjectURL(url), 60_000);
                } catch (e: any) {
                  toast.error(e.message || '打开失败');
                }
              }}
                className="text-xs text-blue-600 hover:text-blue-800">查看</button>
              <button onClick={() => removeMaterial(m.url)} className="text-xs text-red-500 hover:text-red-700">移除</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
