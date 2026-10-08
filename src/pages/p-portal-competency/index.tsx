// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 我的能力测评（员工门户）— 雷达图 + 自评 + 短板课程推荐
 */
import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { PageHeader, EmptyState } from '../../components/PageParts';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

export default function P_portal_competency() {
  const navigate = useNavigate();
  const [models, setModels] = useState([]);
  const [assessments, setAssessments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [assessing, setAssessing] = useState(null); // 正在测评的模型
  const [scores, setScores] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [m, a] = await Promise.all([
        apiClient.get('/portal/competency/models'),
        apiClient.get('/portal/competency/my-assessments'),
      ]);
      setModels(m || []); setAssessments(a || []);
    } catch (e) { toast.error(e.message); setLoadError(true); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const startAssess = (m) => {
    setAssessing(m);
    // 回填已有分数
    const existing = assessments.find(a => a.modelId === m.id);
    setScores(existing?.scores || {});
  };

  const submit = async () => {
    if (submitting) return;
    const dims = assessing.dimensions || [];
    const filled = dims.every(d => scores[d.key] > 0);
    if (!filled) { toast.error('请为所有维度评分'); return; }
    setSubmitting(true);
    try {
      const r = await apiClient.post(`/portal/competency/self-assess/${assessing.id}`, { scores });
      toast.success(`测评完成，达标率 ${r.overallScore}%`);
      setAssessing(null);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setSubmitting(false); }
  };

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (loadError) return <Layout><div className="p-10 text-center"><p className="text-danger mb-3">数据加载失败</p><button onClick={load} className="text-sm text-primary hover:underline">重试</button></div></Layout>;

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-chart-radar" title="能力测评" subtitle="测评识别能力短板，获取提升建议" />

        {/* 测评弹窗 */}
        {assessing && (
          <AssessModal model={assessing} scores={scores} setScores={setScores}
            onCancel={() => setAssessing(null)} onSubmit={submit} submitting={submitting} />
        )}

        {/* 已有测评结果 */}
        {assessments.length > 0 && (
          <section className="mb-6">
            <h2 className="text-lg font-semibold text-text-primary mb-4">我的测评结果</h2>
            <div className="space-y-4">
              {assessments.map(a => (
                <AssessmentResultCard key={a.id} assessment={a} navigate={navigate} />
              ))}
            </div>
          </section>
        )}

        {/* 可做的测评 */}
        <section>
          <h2 className="text-lg font-semibold text-text-primary mb-4">{assessments.length > 0 ? '其他可测评岗位' : '岗位能力测评'}</h2>
          {models.length === 0 ? (
            <EmptyState icon="fa-chart-radar" title="暂无可用的能力模型" hint="管理员可配置岗位胜任力模型" />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {models.map(m => (
                <div key={m.id} className="bg-white rounded-xl border border-border-light p-5 hover:shadow-card transition-shadow">
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <h3 className="font-semibold text-text-primary">{m.name}</h3>
                      {m.description && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{m.description}</p>}
                    </div>
                    {m.assessed && <span className="px-2 py-0.5 rounded text-xs bg-success/10 text-success">已测评</span>}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {(m.dimensions || []).map(d => (
                      <span key={d.key} className="px-2 py-0.5 rounded text-xs bg-bg-light text-text-secondary">{d.name} L{d.requiredLevel}</span>
                    ))}
                  </div>
                  {m.assessed && <div className="mt-2 text-xs text-text-secondary">上次达标率：<span className="font-medium text-primary">{m.lastOverall}%</span></div>}
                  <button onClick={() => startAssess(m)} className="mt-3 w-full text-sm py-1.5 bg-primary text-white rounded-lg hover:bg-blue-700">
                    {m.assessed ? '重新测评' : '开始测评'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </Layout>
  );
}

function AssessModal({ model, scores, setScores, onCancel, onSubmit, submitting }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onCancel}>
      <div className="bg-white rounded-xl p-6 w-full max-w-md max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-1">能力自评：{model.name}</h2>
        <p className="text-sm text-text-secondary mb-4">请根据实际能力，为每个维度评分（1=入门，5=精通）</p>
        <div className="space-y-4">
          {(model.dimensions || []).map(d => (
            <div key={d.key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium text-text-primary">{d.name}</span>
                <span className="text-xs text-text-secondary">要求 L{d.requiredLevel}</span>
              </div>
              {d.description && <p className="text-xs text-text-secondary mb-2">{d.description}</p>}
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map(n => (
                  <button key={n} onClick={() => setScores({ ...scores, [d.key]: n })}
                    className={`flex-1 py-2 rounded-lg text-sm border transition-colors ${
                      scores[d.key] === n ? 'bg-primary text-white border-primary' : 'border-border-light text-text-secondary hover:border-primary/40'
                    }`}>
                    {n}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={onSubmit} disabled={submitting} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{submitting ? '提交中…' : '提交测评'}</button>
        </div>
      </div>
    </div>
  );
}

function AssessmentResultCard({ assessment, navigate }) {
  const [recs, setRecs] = useState(null);
  const canvasRef = useRef(null);
  const dims = assessment.dimensions || [];
  const scores = assessment.scores || {};
  const required = {};
  dims.forEach(d => { required[d.key] = d.requiredLevel; });

  // 雷达图（用 canvas 手绘，避免 Chart.js 复杂引入）
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || dims.length < 3) return;
    const ctx = canvas.getContext('2d');
    const cx = 120, cy = 120, maxR = 90;
    const n = dims.length;
    ctx.clearRect(0, 0, 240, 240);
    // 网格圈
    for (let level = 1; level <= 5; level++) {
      ctx.beginPath();
      for (let i = 0; i <= n; i++) {
        const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
        const r = (level / 5) * maxR;
        const x = cx + Math.cos(angle) * r, y = cy + Math.sin(angle) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#e5e7eb'; ctx.lineWidth = 1; ctx.stroke();
    }
    // 轴线
    dims.forEach((d, i) => {
      const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(angle) * maxR, cy + Math.sin(angle) * maxR);
      ctx.strokeStyle = '#e5e7eb'; ctx.stroke();
    });
    // 要求值（虚线轮廓）
    ctx.beginPath();
    dims.forEach((d, i) => {
      const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const r = (required[d.key] / 5) * maxR;
      const x = cx + Math.cos(angle) * r, y = cy + Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath(); ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]); ctx.stroke();
    // 实际值（填充）
    ctx.beginPath();
    dims.forEach((d, i) => {
      const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const r = ((scores[d.key] || 0) / 5) * maxR;
      const x = cx + Math.cos(angle) * r, y = cy + Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = 'rgba(245, 158, 11, 0.25)'; ctx.fill();
    ctx.strokeStyle = '#d97706'; ctx.lineWidth = 2; ctx.setLineDash([]); ctx.stroke();
    // 维度标签
    ctx.fillStyle = '#6b7280'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
    dims.forEach((d, i) => {
      const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const x = cx + Math.cos(angle) * (maxR + 14), y = cy + Math.sin(angle) * (maxR + 14) + 4;
      ctx.fillText(d.name, x, y);
    });
  }, [assessment]);

  // 加载短板推荐
  useEffect(() => {
    apiClient.get(`/hrm/competency-assessments/${assessment.id}/recommendations`).then(setRecs).catch(() => {});
  }, [assessment.id]);

  const weakNames = (assessment.weakestDims || []).map(k => {
    const d = dims.find(x => x.key === k); return d ? d.name : k;
  });

  return (
    <div className="bg-white rounded-xl border border-border-light p-5">
      <div className="flex items-start gap-5">
        {/* 雷达图 */}
        <canvas ref={canvasRef} width={240} height={240} className="shrink-0" />
        {/* 结果数据 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-semibold text-text-primary">{assessment.modelName}</h3>
            <span className={`px-2 py-0.5 rounded text-xs ${assessment.overallScore >= 80 ? 'bg-success/10 text-success' : assessment.overallScore >= 60 ? 'bg-warning/10 text-warning' : 'bg-danger/10 text-danger'}`}>
              达标率 {assessment.overallScore}%
            </span>
          </div>
          <div className="space-y-1.5 mb-3">
            {dims.map(d => {
              const act = scores[d.key] || 0; const req = d.requiredLevel;
              const gap = Math.max(0, req - act);
              return (
                <div key={d.key} className="flex items-center gap-2 text-sm">
                  <span className="text-text-secondary w-20 truncate">{d.name}</span>
                  <span className={`font-medium ${gap > 0 ? 'text-danger' : 'text-success'}`}>L{act}</span>
                  <span className="text-text-secondary text-xs">/ L{req}</span>
                  {gap > 0 && <span className="text-xs text-danger">差{gap}</span>}
                </div>
              );
            })}
          </div>
          {/* 短板 + 推荐 */}
          {weakNames.length > 0 && (
            <div className="border-t border-border-light pt-3">
              <div className="text-xs text-danger mb-2 flex items-center gap-1"><AppIcon className="fas fa-exclamation-triangle" /> 能力短板：{weakNames.join('、')}</div>
              {recs && recs.recommendedCourses && recs.recommendedCourses.length > 0 && (
                <div>
                  <div className="text-xs text-text-secondary mb-1.5">推荐提升课程：</div>
                  <div className="space-y-1">
                    {recs.recommendedCourses.map(c => (
                      <button key={c.id} onClick={() => navigate(`/portal/course/${c.id}`)}
                        className="block text-left text-sm text-primary hover:underline">{c.title}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {weakNames.length === 0 && (
            <div className="border-t border-border-light pt-3 text-xs text-success flex items-center gap-1">
              <AppIcon className="fas fa-check-circle" /> 各维度均已达标，保持优秀！
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
