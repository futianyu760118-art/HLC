// @ts-nocheck
/**
 * 成绩管理 — 答题记录列表 + 筛选 + 详情查看
 */
import React, { useEffect, useState } from 'react';
import { Layout } from '../../components/Layout';
import { PageHeader, StatPill, EmptyState } from '../../components/PageParts';
import apiClient, { hrmApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

const fmtTime = (t) => {
  if (!t) return '-';
  try { return new Date(t.includes('Z') ? t : t + 'Z').toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return t; }
};

export default function P_exam_attempts() {
  const [attempts, setAttempts] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterTask, setFilterTask] = useState('all');
  const [filterResult, setFilterResult] = useState('all');
  const [detail, setDetail] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [a, t] = await Promise.all([hrmApi.list('exam-attempts'), hrmApi.list('exam-tasks')]);
      setAttempts((a || []).filter(x => x.status === 'submitted'));
      setTasks(t || []);
    } catch (e) { toast.error(e.message || '加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const filtered = attempts.filter(a => {
    if (filterTask !== 'all' && a.taskId !== filterTask) return false;
    if (filterResult === 'passed' && !a.passed) return false;
    if (filterResult === 'failed' && a.passed) return false;
    return true;
  });

  const passRate = attempts.length ? Math.round(attempts.filter(a => a.passed).length / attempts.length * 100) : 0;
  const avgScore = attempts.length ? (attempts.reduce((s, a) => s + Number(a.score || 0), 0) / attempts.length).toFixed(1) : 0;

  const detailAttempt = detail ? attempts.find(a => a.id === detail) : null;

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <PageHeader icon="fa-chart-line" title="成绩管理" subtitle="查看考试成绩与答题详情"
          actions={<button onClick={async () => {
            if (!filterTask || filterTask === 'all') { toast.error('请先选择一场考试再导出'); return; }
            try {
              await apiClient.downloadFile(`/hrm/export/exam-results/${filterTask}`);
            } catch (e) {
              toast.error(e.message || '导出失败');
            }
          }} className="px-3 py-2 text-sm border border-border-light rounded-lg text-success hover:bg-success/5 flex items-center gap-1.5">
            <AppIcon className="fas fa-file-excel" /> 导出成绩单
          </button>} />

        <div className="grid grid-cols-4 gap-3 mb-5">
          <StatPill label="参考人次" value={attempts.length} icon="fa-users" />
          <StatPill label="通过人次" value={attempts.filter(a => a.passed).length} icon="fa-check" tone="success" />
          <StatPill label="通过率" value={`${passRate}%`} icon="fa-percent" tone={passRate >= 60 ? 'success' : 'warning'} />
          <StatPill label="平均分" value={avgScore} icon="fa-star-half-alt" tone="neutral" />
        </div>

        {/* 筛选 */}
        <div className="flex items-center gap-3 mb-4">
          <select value={filterTask} onChange={e => setFilterTask(e.target.value)} className="px-3 py-1.5 text-sm border border-border-light rounded-lg outline-none">
            <option value="all">全部考试</option>
            {tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
          <div className="flex gap-1 bg-bg-light rounded-lg p-1">
            {(['all', 'passed', 'failed'] as const).map(f => (
              <button key={f} onClick={() => setFilterResult(f)}
                className={`px-3 py-1 rounded-md text-sm transition-colors ${filterResult === f ? 'bg-white shadow-sm font-medium' : 'text-text-secondary'} ${f === 'passed' ? 'text-success' : f === 'failed' ? 'text-danger' : 'text-text-primary'}`}>
                {f === 'all' ? '全部' : f === 'passed' ? '通过' : '未通过'}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : filtered.length === 0 ? (
          <EmptyState icon="fa-chart-line" title="暂无成绩记录" hint="员工提交考试后，成绩将显示在这里" />
        ) : (
          <div className="bg-white rounded-xl border border-border-light overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-bg-light/50 text-text-secondary">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">员工</th>
                  <th className="text-left px-4 py-3 font-medium">考试</th>
                  <th className="text-left px-4 py-3 font-medium">得分</th>
                  <th className="text-left px-4 py-3 font-medium">结果</th>
                  <th className="text-left px-4 py-3 font-medium">提交时间</th>
                  <th className="text-right px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {filtered.map(a => {
                  const task = tasks.find(t => t.id === a.taskId);
                  return (
                    <tr key={a.id} className="hover:bg-bg-light/30">
                      <td className="px-4 py-3">
                        <div className="font-medium text-text-primary">{a.employeeName}</div>
                      </td>
                      <td className="px-4 py-3 text-text-secondary">{a.taskTitle || task?.title || '-'}</td>
                      <td className="px-4 py-3">
                        <span className="font-bold text-text-primary">{a.score}</span>
                        <span className="text-text-secondary text-xs"> / {a.totalScore}</span>
                        <div className="text-[11px] text-text-secondary mt-0.5">及格 {a.passScore ?? task?.passScore ?? '-'}</div>
                      </td>
                      <td className="px-4 py-3">
                        {a.passed
                          ? <span className="inline-flex items-center gap-1 text-success text-xs"><AppIcon className="fas fa-check-circle" /> 通过</span>
                          : <span className="inline-flex items-center gap-1 text-danger text-xs"><AppIcon className="fas fa-times-circle" /> 未通过</span>}
                      </td>
                      <td className="px-4 py-3 text-text-secondary text-xs">{fmtTime(a.submittedAt)}</td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => setDetail(a.id)} className="text-xs text-primary hover:text-blue-700">详情</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {detailAttempt && (
          <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
            <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="font-semibold text-text-primary">成绩详情</h3>
                  <p className="text-xs text-text-secondary mt-1">
                    {detailAttempt.employeeName} · {detailAttempt.taskTitle || tasks.find(t => t.id === detailAttempt.taskId)?.title || '-'}
                  </p>
                </div>
                <button onClick={() => setDetail(null)} className="w-8 h-8 rounded-lg hover:bg-bg-light text-text-secondary">
                  <AppIcon className="fas fa-times" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-bg-light p-3">
                  <div className="text-xs text-text-secondary">得分</div>
                  <div className="font-semibold text-text-primary">{detailAttempt.score} / {detailAttempt.totalScore}</div>
                </div>
                <div className="rounded-lg bg-bg-light p-3">
                  <div className="text-xs text-text-secondary">及格分</div>
                  <div className="font-semibold text-text-primary">{detailAttempt.passScore ?? '-'}</div>
                </div>
                <div className="rounded-lg bg-bg-light p-3">
                  <div className="text-xs text-text-secondary">结果</div>
                  <div className={detailAttempt.passed ? 'font-semibold text-success' : 'font-semibold text-danger'}>{detailAttempt.passed ? '通过' : '未通过'}</div>
                </div>
                <div className="rounded-lg bg-bg-light p-3">
                  <div className="text-xs text-text-secondary">提交时间</div>
                  <div className="font-semibold text-text-primary">{fmtTime(detailAttempt.submittedAt)}</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
