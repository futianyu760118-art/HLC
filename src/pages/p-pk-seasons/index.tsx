// @ts-nocheck
/**
 * 团队 PK 竞赛管理 — 赛季卡片 + 创建 + 排行榜查看
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import { hrmApi } from '../../utils/api';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

export default function P_pk_seasons() {
  const [seasons, setSeasons] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [leaderboard, setLeaderboard] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [s, d] = await Promise.all([hrmApi.list('pk-seasons'), hrmApi.list('departments')]);
      setSeasons(s || []); setDepartments(d || []);
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const viewLeaderboard = async (id) => {
    try { const r = await apiClient.get(`/hrm/pk-seasons/${id}/leaderboard`); setLeaderboard(r); }
    catch (e) { toast.error(e.message); }
  };

  const remove = async (s) => {
    if (!await confirm(`删除赛季「${s.name}」？`)) return;
    try { await hrmApi.remove('pk-seasons', s.id); toast.success('已删除'); load(); }
    catch (e) { toast.error(e.message); }
  };

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <PageHeader icon="fa-trophy" title="团队 PK 竞赛" subtitle="部门间学习竞技，激发团队活力"
          actions={<button onClick={() => setShowForm(true)} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
            <AppIcon className="fas fa-plus" /> 创建赛季
          </button>} />

        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
          <StatPill label="赛季总数" value={seasons.length} icon="fa-trophy" />
          <StatPill label="进行中" value={seasons.filter(s => s.status === 'active').length} icon="fa-play" tone="success" />
          <StatPill label="部门数" value={departments.length} icon="fa-building" tone="neutral" />
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : seasons.length === 0 ? (
          <EmptyState icon="fa-trophy" title="还没有赛季" hint="创建第一个 PK 赛季，点燃团队学习热情" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {seasons.map(s => (
              <div key={s.id} className="bg-white rounded-xl border border-border-light p-5 hover:shadow-card transition-shadow">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-11 h-11 rounded-lg bg-warning/10 flex items-center justify-center shrink-0">
                    <AppIcon className="fas fa-trophy text-warning" />
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${s.status === 'active' ? 'bg-success/10 text-success' : 'bg-bg-light text-text-secondary'}`}>
                    {s.status === 'active' ? '进行中' : '已结束'}
                  </span>
                </div>
                <h3 className="font-semibold text-text-primary">{s.name}</h3>
                {s.description && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{s.description}</p>}
                <div className="mt-3 pt-3 border-t border-border-light text-xs text-text-secondary space-y-1">
                  <div><AppIcon className="fas fa-calendar" /> {(s.startDate||'').slice(0,10)} ~ {(s.endDate||'').slice(0,10)}</div>
                  <div><AppIcon className="fas fa-chart-bar" /> {s.metric === 'avg_points' ? '人均积分' : '总积分'} · {s.participantDeptIds?.length || '全'}个部门</div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button onClick={() => viewLeaderboard(s.id)} className="flex-1 text-sm py-1.5 border border-border-light rounded-lg text-primary hover:bg-primary/5 flex items-center justify-center gap-1">
                    <AppIcon className="fas fa-ranking-star" /> 排行榜
                  </button>
                  <button onClick={() => remove(s)} className="w-8 h-8 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/5 flex items-center justify-center">
                    <AppIcon className="fas fa-trash text-xs" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {showForm && <SeasonForm departments={departments} onCancel={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); }} />}
        {leaderboard && <LeaderboardModal data={leaderboard} onClose={() => setLeaderboard(null)} />}
      </div>
    </Layout>
  );
}

function SeasonForm({ departments, onCancel, onSaved }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [metric, setMetric] = useState('total_points');
  const [selectedDepts, setSelectedDepts] = useState([]);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name.trim() || !startDate || !endDate) { toast.error('请填写名称和起止时间'); return; }
    if (new Date(endDate) <= new Date(startDate)) { toast.error('结束日期须晚于开始日期'); return; }
    if (selectedDepts.length === 0) { toast.error('请选择至少一个参赛部门'); return; }
    setSaving(true);
    try {
      await hrmApi.create('pk-seasons', {
        name: name.trim(), description, metric,
        startDate: new Date(startDate).toISOString(), endDate: new Date(endDate).toISOString(),
        participantDeptIds: selectedDepts, status: 'active',
      });
      toast.success('赛季已创建');
      onSaved();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onCancel}>
      <div className="bg-white rounded-xl p-6 w-full max-w-md max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">创建 PK 赛季</h2>
        <div className="space-y-3">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="赛季名称（如：2026Q2 学习挑战赛）" className="w-full px-3 py-2 border border-border-light rounded-lg outline-none" />
          <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="说明" rows={2} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none" />
          <div className="grid grid-cols-2 gap-3">
            <div><label className="text-xs text-text-secondary">开始日期</label><input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" /></div>
            <div><label className="text-xs text-text-secondary">结束日期</label><input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm" /></div>
          </div>
          <div>
            <label className="text-xs text-text-secondary">排名指标</label>
            <select value={metric} onChange={e => setMetric(e.target.value)} className="w-full px-3 py-2 border border-border-light rounded-lg outline-none text-sm">
              <option value="total_points">部门总积分</option>
              <option value="avg_points">部门人均积分</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-text-secondary mb-1 block">参赛部门（空=全部）</label>
            <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto p-2 border border-border-light rounded-lg">
              {departments.map(d => (
                <label key={d.id} className={`px-2 py-1 rounded text-xs cursor-pointer border ${selectedDepts.includes(d.id) ? 'bg-primary/10 border-primary text-primary' : 'border-border-light text-text-secondary'}`}>
                  <input type="checkbox" className="hidden" checked={selectedDepts.includes(d.id)} onChange={() => setSelectedDepts(prev => prev.includes(d.id) ? prev.filter(x => x !== d.id) : [...prev, d.id])} />
                  {d.name}
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary">取消</button>
          <button onClick={submit} disabled={saving} className="px-4 py-2 text-sm bg-primary text-white rounded-lg disabled:opacity-50">{saving ? '创建中…' : '创建赛季'}</button>
        </div>
      </div>
    </div>
  );
}

function LeaderboardModal({ data, onClose }) {
  const s = data.season;
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl p-6 w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{s.name} - 排行榜</h2>
          <button onClick={onClose}><AppIcon className="fas fa-times text-text-secondary" /></button>
        </div>
        {/* 团队榜 */}
        <h3 className="font-medium text-text-primary mb-2">团队排行（{s.metric === 'avg_points' ? '人均积分' : '总积分'}）</h3>
        <div className="space-y-2 mb-5">
          {data.teamBoard.map(t => (
            <div key={t.deptId} className={`flex items-center gap-3 px-3 py-2 rounded-lg ${t.rank <= 3 ? 'bg-warning/5' : ''}`}>
              <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${t.rank === 1 ? 'bg-warning text-white' : t.rank === 2 ? 'bg-text-secondary text-white' : t.rank === 3 ? 'bg-orange-400 text-white' : 'bg-bg-light text-text-secondary'}`}>{t.rank}</span>
              <span className="flex-1 font-medium text-text-primary">{t.deptName}</span>
              <span className="text-xs text-text-secondary">{t.memberCount}人</span>
              <span className="text-sm font-bold text-warning">{s.metric === 'avg_points' ? t.avgPoints : t.totalPoints}</span>
            </div>
          ))}
        </div>
        {/* 个人贡献榜 */}
        <h3 className="font-medium text-text-primary mb-2">个人贡献榜 Top{Math.min(10, data.individualBoard.length)}</h3>
        <div className="space-y-1">
          {data.individualBoard.slice(0, 10).map(p => (
            <div key={p.employeeId} className="flex items-center gap-3 px-3 py-1.5 text-sm">
              <span className="w-6 text-text-secondary text-xs">#{p.rank}</span>
              <span className="flex-1 text-text-primary">{p.employeeName}</span>
              <span className="text-text-secondary text-xs">{p.deptName}</span>
              <span className="font-medium text-warning">{p.points}</span>
            </div>
          ))}
          {data.individualBoard.length === 0 && <div className="text-center text-text-secondary text-sm py-3">暂无积分数据</div>}
        </div>
      </div>
    </div>
  );
}
