// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 考试任务进度看板（Chunk 7/9）
 * 展示完成率/通过率/成绩单，支持发布任务
 */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import apiClient, { trainingExamApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

export default function P_exam_task_progress() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await trainingExamApi.taskProgress(id);
      setData(res);
    } catch (e: any) {
      toast.error(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const publish = async () => {
    if (!await confirm('发布后将为指派目标生成考试授权，确定？')) return;
    setPublishing(true);
    try {
      const res = await trainingExamApi.publishTask(id);
      toast.success(`已发布，授权 ${res.assignedTotal} 人（新增 ${res.newlyAssigned}）`);
      load();
    } catch (e: any) {
      toast.error(e.message || '发布失败');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) return <Layout><div className="p-10 text-center text-gray-400">加载中…</div></Layout>;
  if (!data) return <Layout><div className="p-10 text-center text-red-500">任务不存在</div></Layout>;

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/hrm/exam-tasks')} className="text-gray-500 hover:text-gray-700">
              <AppIcon className="fas fa-arrow-left" />
            </button>
            <h1 className="text-2xl font-bold">{data.title}</h1>
          </div>
          <button onClick={publish} disabled={publishing}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50">
            {publishing ? '发布中…' : '发布/刷新授权'}
          </button>
          <button onClick={async () => {
            try {
              await apiClient.downloadFile(`/hrm/export/exam-results/${id}`);
            } catch (e: any) {
              toast.error(e.message || '导出失败');
            }
          }}
            className="border border-green-600 text-green-700 px-4 py-2 rounded hover:bg-green-50">
            <AppIcon className="fas fa-file-excel" /> 导出成绩单
          </button>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <StatCard label="指派人数" value={data.total} icon="fa-users" color="text-blue-600" />
          <StatCard label="已参加" value={data.attempted} icon="fa-user-check" color="text-amber-600" />
          <StatCard label="通过" value={data.passed} icon="fa-trophy" color="text-green-600" />
          <StatCard label="及格分" value={data.passScore} icon="fa-flag-checkered" color="text-gray-600" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="bg-white rounded-lg shadow p-4">
            <div className="text-sm text-gray-500">完成率</div>
            <div className="text-2xl font-bold">{(data.completionRate * 100).toFixed(1)}%</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <div className="text-sm text-gray-500">通过率</div>
            <div className="text-2xl font-bold">{(data.passRate * 100).toFixed(1)}%</div>
          </div>
        </div>

        {/* 成绩单 */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-5 py-3 border-b font-semibold">成绩单</div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-2">员工</th>
                <th className="text-left px-4 py-2">部门</th>
                <th className="text-left px-4 py-2">已考次数</th>
                <th className="text-left px-4 py-2">最高分</th>
                <th className="text-left px-4 py-2">是否通过</th>
                <th className="text-left px-4 py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {(data.roster || []).map((r: any) => (
                <tr key={r.employeeId} className="border-t">
                  <td className="px-4 py-2">{r.employeeName}</td>
                  <td className="px-4 py-2 text-gray-500">{r.department || '-'}</td>
                  <td className="px-4 py-2">{r.attemptsUsed}</td>
                  <td className="px-4 py-2 font-medium">{r.bestScore ?? '-'}</td>
                  <td className="px-4 py-2">
                    {r.passed === true && <span className="text-green-600">通过</span>}
                    {r.passed === false && <span className="text-red-500">未通过</span>}
                    {r.passed === null && <span className="text-gray-400">未参加</span>}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{r.status}</td>
                </tr>
              ))}
              {(!data.roster || data.roster.length === 0) && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">暂无授权员工（请先发布）</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
}

function StatCard({ label, value, icon, color }: { label: string; value: any; icon: string; color: string }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">{label}</div>
        <AppIcon className={`fas ${icon} ${color}`} />
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}
