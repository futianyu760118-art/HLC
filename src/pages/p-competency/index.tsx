// @ts-nocheck
/**
 * 胜任力模型管理 — 模型卡片 + 维度编辑器
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import { hrmApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

export default function P_competency() {
  const [models, setModels] = useState([]);
  const [assessments, setAssessments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [m, a] = await Promise.all([
        hrmApi.list('competency-models'),
        hrmApi.list('competency-assessments'),
      ]);
      setModels(m || []); setAssessments(a || []);
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const remove = async (m) => {
    if (!await confirm(`删除模型「${m.name}」？`)) return;
    try { await hrmApi.remove('competency-models', m.id); toast.success('已删除'); load(); }
    catch (e) { toast.error(e.message); }
  };

  if (editing) return <ModelEditor model={editing} onBack={() => { setEditing(null); load(); }} />;

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-chart-radar" title="胜任力测评" subtitle="定义岗位能力模型，测评识别短板"
          actions={<button onClick={() => setEditing({ name: '', description: '', dimensions: [{ key: 'dim1', name: '', requiredLevel: 3, description: '' }], status: 'active' })}
            className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
            <AppIcon className="fas fa-plus" /> 新建模型
          </button>} />

        <div className="grid grid-cols-3 gap-3 mb-5">
          <StatPill label="能力模型" value={models.length} icon="fa-chart-radar" />
          <StatPill label="测评记录" value={assessments.length} icon="fa-clipboard-check" tone="success" />
          <StatPill label="平均达标率" value={assessments.length ? Math.round(assessments.reduce((s, a) => s + (a.overallScore || 0), 0) / assessments.length) + '%' : '-'} icon="fa-percent" tone="neutral" />
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : models.length === 0 ? (
          <EmptyState icon="fa-chart-radar" title="还没有胜任力模型" hint="创建第一个岗位能力模型" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {models.map(m => (
              <div key={m.id} className="group bg-white rounded-xl border border-border-light p-5 hover:shadow-card transition-shadow">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-11 h-11 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <AppIcon className="fas fa-chart-radar text-primary" />
                  </div>
                  <button onClick={() => remove(m)} className="w-7 h-7 rounded text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                    <AppIcon className="fas fa-trash text-xs" />
                  </button>
                </div>
                <h3 className="font-semibold text-text-primary">{m.name}</h3>
                {m.description && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{m.description}</p>}
                <div className="mt-3 pt-3 border-t border-border-light">
                  <div className="text-xs text-text-secondary mb-2">能力维度（{m.dimensionCount}）</div>
                  <div className="flex flex-wrap gap-1">
                    {(m.dimensions || []).map(d => (
                      <span key={d.key} className="px-2 py-0.5 rounded text-xs bg-bg-light text-text-secondary">
                        {d.name} <span className="text-primary">L{d.requiredLevel}</span>
                      </span>
                    ))}
                  </div>
                </div>
                <button onClick={() => setEditing(m)} className="mt-3 w-full text-sm py-1.5 border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                  <AppIcon className="fas fa-pen text-xs" /> 编辑维度
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}

function ModelEditor({ model, onBack }) {
  const [name, setName] = useState(model.name || '');
  const [description, setDescription] = useState(model.description || '');
  const [dims, setDims] = useState(model.dimensions || []);
  const [saving, setSaving] = useState(false);

  const addDim = () => setDims([...dims, { key: `dim${dims.length + 1}_${Date.now()}`, name: '', requiredLevel: 3, description: '' }]);
  const removeDim = (i) => setDims(dims.filter((_, idx) => idx !== i));
  const updateDim = (i, field, value) => setDims(dims.map((d, idx) => idx === i ? { ...d, [field]: field === 'requiredLevel' ? Number(value) : value } : d));

  const save = async () => {
    if (!name.trim()) { toast.error('请输入岗位名称'); return; }
    const validDims = dims.filter(d => d.name.trim());
    if (validDims.length === 0) { toast.error('至少一个能力维度'); return; }
    setSaving(true);
    try {
      const data = { name: name.trim(), description, dimensions: validDims, status: 'active' };
      if (model.id) await hrmApi.update('competency-models', model.id, data);
      else await hrmApi.create('competency-models', data);
      toast.success('已保存');
      onBack();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Layout>
      <div className="max-w-3xl mx-auto px-4 md:px-6 py-6">
        <button onClick={onBack} className="text-sm text-text-secondary hover:text-primary mb-4 flex items-center gap-1">
          <AppIcon className="fas fa-arrow-left text-xs" /> 返回
        </button>
        <div className="bg-white rounded-xl border border-border-light p-5 mb-5 space-y-3">
          <h2 className="font-semibold">岗位信息</h2>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="岗位名称（如：前端工程师）" className="w-full px-3 py-2 border border-border-light rounded-lg outline-none focus:border-primary" />
          <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="岗位说明" rows={2} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none" />
        </div>
        <div className="bg-white rounded-xl border border-border-light p-5 mb-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">能力维度与要求等级</h2>
            <button onClick={addDim} className="text-sm text-primary hover:text-blue-700 flex items-center gap-1"><AppIcon className="fas fa-plus" /> 添加维度</button>
          </div>
          <div className="space-y-3">
            {dims.map((d, i) => (
              <div key={d.key || i} className="flex items-start gap-2 border border-border-light rounded-lg p-3">
                <div className="flex-1 space-y-2">
                  <input value={d.name} onChange={e => updateDim(i, 'name', e.target.value)} placeholder="维度名称（如：专业技术）" className="w-full px-2 py-1 border border-border-light rounded text-sm outline-none" />
                  <input value={d.description || ''} onChange={e => updateDim(i, 'description', e.target.value)} placeholder="说明（可选）" className="w-full px-2 py-1 border border-border-light rounded text-xs outline-none" />
                </div>
                <div className="shrink-0">
                  <label className="text-xs text-text-secondary block mb-1">要求等级</label>
                  <select value={d.requiredLevel} onChange={e => updateDim(i, 'requiredLevel', e.target.value)} className="px-2 py-1 border border-border-light rounded text-sm outline-none">
                    {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>L{n}</option>)}
                  </select>
                </div>
                <button onClick={() => removeDim(i)} className="mt-6 w-7 h-7 rounded text-text-secondary hover:text-danger flex items-center justify-center"><AppIcon className="fas fa-times text-xs" /></button>
              </div>
            ))}
          </div>
        </div>
        <button onClick={save} disabled={saving} className="w-full py-2.5 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">保存模型</button>
      </div>
    </Layout>
  );
}
