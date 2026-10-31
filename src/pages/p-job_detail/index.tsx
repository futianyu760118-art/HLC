/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { jobsApi, resumesApi, interviewsApi, Job, DEFAULT_SCORING_CRITERIA, ScoringCriterion } from '../../utils/api';


import AppIcon from '../../components/AppIcon';
export default function JobDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get('jobId');
  
  const [job, setJob] = useState<Job | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    title: '',
    description: '',
  });
  const [editCriteria, setEditCriteria] = useState<ScoringCriterion[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isToggling, setIsToggling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [funnel, setFunnel] = useState({ resumes: 0, pendingInterview: 0, interviewing: 0, hired: 0 });

  useEffect(() => {
    document.title = '岗位详情 - 恒聘通';
    loadJob();
  }, [jobId]);

  const loadFunnel = async (jid: string) => {
    try {
      const [resumes, interviews] = await Promise.all([
        resumesApi.getAll().catch(() => []),
        interviewsApi.getAll().catch(() => []),
      ]);
      const jobResumes = (resumes || []).filter((r: any) => r.jobId === jid);
      const jobInterviews = (interviews || []).filter((i: any) => i.jobId === jid);
      setFunnel({
        resumes: jobResumes.length,
        pendingInterview: jobInterviews.filter((i: any) => ['pending', 'scheduled'].includes(i.status)).length,
        interviewing: jobInterviews.filter((i: any) => ['in_progress', 'completed'].includes(i.status)).length,
        // 录用：有 offer 或简历状态为 hired/employed
        hired: jobResumes.filter((r: any) => ['hired', 'employed', 'offered'].includes(r.status)).length
                 + jobInterviews.filter((i: any) => i.status === 'hired').length,
      });
    } catch {
      // 漏斗统计失败不影响主页面
    }
  };

  const loadJob = async () => {
    if (!jobId) {
      setError('缺少岗位ID');
      setIsLoading(false);
      return;
    }

    try {
      const jobs = await jobsApi.getAll();
      const found = jobs.find(j => j.id === jobId);
      if (found) {
        setJob(found);
        setEditForm({
          title: found.title,
          description: found.description,
        });
        setEditCriteria(
          found.scoringCriteria 
            ? JSON.parse(JSON.stringify(found.scoringCriteria))
            : JSON.parse(JSON.stringify(DEFAULT_SCORING_CRITERIA))
        );
        loadFunnel(found.id);
      } else {
        setError('岗位不存在');
      }
    } catch (_err) {
      setError('加载失败');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleStatus = async () => {
    if (!job || isToggling) return;

    const newStatus = job.status === 'open' ? 'closed' : 'open';
    const ok = await confirm({
      title: newStatus === 'closed' ? '关闭岗位' : '重新开启岗位',
      message: newStatus === 'closed' ? '关闭后将不再接收新简历，确定继续？' : '确定要重新开启这个岗位吗？',
      confirmText: newStatus === 'closed' ? '关闭' : '开启',
      danger: newStatus === 'closed',
    });
    if (!ok) return;
    setIsToggling(true);
    try {
      const updated = await jobsApi.update(job.id, { status: newStatus });
      setJob(updated);
      toast.success('状态更新成功');
    } catch (err: any) {
      toast.error(err?.message || '更新失败');
    } finally {
      setIsToggling(false);
    }
  };

  const handleDelete = async () => {
    if (!job || isDeleting) return;
    const ok = await confirm({
      title: '删除岗位',
      message: '确定要删除这个岗位吗？关联的简历和面试数据也会被删除。',
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    setIsDeleting(true);
    try {
      await jobsApi.delete(job.id);
      toast.success('删除成功');
      navigate('/job-manage');
    } catch (err: any) {
      toast.error(err?.message || '删除失败');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    if (job) {
      setEditForm({
        title: job.title,
        description: job.description,
      });
      setEditCriteria(
        job.scoringCriteria 
          ? JSON.parse(JSON.stringify(job.scoringCriteria))
          : JSON.parse(JSON.stringify(DEFAULT_SCORING_CRITERIA))
      );
    }
    setIsEditing(false);
  };

  const handleSaveEdit = async () => {
    if (!job) return;
    if (!editForm.title?.trim()) { toast.warning('请输入岗位名称'); return; }
    if (!editForm.description?.trim()) { toast.warning('请输入岗位描述'); return; }

    const totalWeight = editCriteria.reduce((sum, c) => sum + c.weight, 0);
    if (totalWeight !== 100) {
      toast.warning(`评分权重总和必须为100%，当前为${totalWeight}%`);
      return;
    }
    if (isSaving) return;
    setIsSaving(true);
    try {
      const updated = await jobsApi.update(job.id, {
        title: editForm.title,
        description: editForm.description,
        scoringCriteria: editCriteria,
      });
      setJob(updated);
      setIsEditing(false);
      toast.info('保存成功');
    } catch (_err) {
      toast.info('保存失败');
    } finally {
      setIsSaving(false);
    }
  };

  const handleWeightChange = (index: number, value: number) => {
    const newCriteria = [...editCriteria];
    newCriteria[index].weight = Math.max(0, Math.min(100, value));
    setEditCriteria(newCriteria);
  };

  const getTotalWeight = () => {
    return editCriteria.reduce((sum, c) => sum + c.weight, 0);
  };

  const resetWeights = () => {
    setEditCriteria(JSON.parse(JSON.stringify(DEFAULT_SCORING_CRITERIA)));
  };

  if (isLoading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64">
          <AppIcon className="fas fa-spinner fa-spin text-3xl text-blue-500" />
        </div>
      </Layout>
    );
  }

  if (error || !job) {
    return (
      <Layout>
        <div className="text-center py-12">
          <AppIcon className="fas fa-exclamation-circle text-5xl text-gray-400 mb-4" />
          <p className="text-gray-600">{error || '岗位不存在'}</p>
          <button
            onClick={() => navigate('/job-manage')}
            className="mt-4 text-blue-600 hover:underline"
          >
            返回列表
          </button>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-5xl mx-auto">
        {/* 页面头部 */}
        <div className="mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-800 mb-2">岗位详情</h2>
              <nav className="text-sm text-gray-600">
                <span>首页</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>岗位管理</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>岗位详情</span>
              </nav>
            </div>
            <div className="flex items-center space-x-3">
              <button
                onClick={() => navigate('/job-manage')}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                <AppIcon className="fas fa-arrow-left mr-2" />
                返回列表
              </button>
              {!isEditing && (
                <>
                  <button
                    onClick={handleEdit}
                    className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                  >
                    <AppIcon className="fas fa-edit mr-2" />
                    编辑
                  </button>
                  <button
                    onClick={handleToggleStatus}
                    disabled={isToggling}
                    className={`px-4 py-2 text-white rounded-lg disabled:opacity-50 ${
                      job.status === 'open'
                        ? 'bg-yellow-500 hover:bg-yellow-600'
                        : 'bg-green-500 hover:bg-green-600'
                    }`}
                  >
                    <AppIcon className={`fas fa-${job.status === 'open' ? 'pause' : 'play'} mr-2`} />
                    {isToggling ? '处理中…' : (job.status === 'open' ? '关闭岗位' : '重新开启')}
                  </button>
                </>
              )}
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50"
              >
                <AppIcon className="fas fa-trash mr-2" />
                {isDeleting ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        </div>

        {/* 岗位内容 */}
        <div className="space-y-6">
          {/* 基本信息 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-start justify-between mb-4 pb-4 border-b">
              <div className="flex-1">
                {isEditing ? (
                  <input
                    type="text"
                    value={editForm.title}
                    onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                    className="text-2xl font-bold text-gray-800 w-full border-b-2 border-blue-500 focus:outline-none pb-1"
                  />
                ) : (
                  <h3 className="text-2xl font-bold text-gray-800">{job.title}</h3>
                )}
                <p className="text-sm text-gray-500 mt-2">
                  创建时间：{new Date(job.createdAt).toLocaleString('zh-CN')}
                </p>
              </div>
              {isEditing ? (
                <div className="flex items-center space-x-2 ml-4">
                  <button
                    onClick={handleSaveEdit}
                    disabled={isSaving}
                    className="px-3 py-1 bg-green-500 text-white text-sm rounded hover:bg-green-600 disabled:opacity-50"
                  >
                    <AppIcon className="fas fa-save mr-1" />
                    {isSaving ? '保存中…' : '保存'}
                  </button>
                  <button
                    onClick={handleCancelEdit}
                    className="px-3 py-1 bg-gray-300 text-gray-700 text-sm rounded hover:bg-gray-400"
                  >
                    <AppIcon className="fas fa-times mr-1" />
                    取消
                  </button>
                </div>
              ) : (
                <span className={`px-4 py-2 rounded-full text-sm font-medium ${
                  job.status === 'open'
                    ? 'bg-green-100 text-green-700'
                    : 'bg-gray-100 text-gray-700'
                }`}>
                  {job.status === 'open' ? '招聘中' : '已关闭'}
                </span>
              )}
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-2">岗位描述</label>
                {isEditing ? (
                  <textarea
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    rows={10}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                ) : (
                  <div className="prose max-w-none">
                    <pre className="whitespace-pre-wrap text-gray-700 font-sans">{job.description}</pre>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4 pt-4 border-t">
                <div>
                  <label className="text-sm text-gray-600">创建时间</label>
                  <p className="text-gray-800 font-medium mt-1">
                    {new Date(job.createdAt).toLocaleString('zh-CN')}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-gray-600">更新时间</label>
                  <p className="text-gray-800 font-medium mt-1">
                    {new Date(job.updatedAt).toLocaleString('zh-CN')}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* AI评分权重 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4 pb-3 border-b">
              <h3 className="text-lg font-semibold text-gray-800">
                <AppIcon className="fas fa-sliders-h text-blue-600 mr-2" />
                AI评分权重配置
              </h3>
              {isEditing && (
                <div className="flex items-center space-x-3">
                  <span className={`text-sm font-medium ${getTotalWeight() === 100 ? 'text-green-600' : 'text-red-600'}`}>
                    总权重: {getTotalWeight()}%
                  </span>
                  <button
                    type="button"
                    onClick={resetWeights}
                    className="text-sm text-blue-600 hover:text-blue-700"
                  >
                    <AppIcon className="fas fa-undo mr-1" />
                    恢复默认
                  </button>
                </div>
              )}
            </div>

            {editCriteria.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <AppIcon className="fas fa-info-circle text-3xl mb-2" />
                <p>该岗位使用默认评分权重</p>
              </div>
            ) : (
              <div className="space-y-3">
                {editCriteria.map((criterion, index) => (
                  <div key={index} className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex-1">
                        <p className="text-sm font-medium text-gray-800">{criterion.name}</p>
                        <p className="text-xs text-gray-500 mt-1">{criterion.description}</p>
                      </div>
                      <div className="flex items-center space-x-3 ml-4">
                        {isEditing ? (
                          <>
                            <input
                              type="range"
                              min="0"
                              max="50"
                              value={criterion.weight}
                              onChange={(e) => handleWeightChange(index, parseInt(e.target.value))}
                              className="w-32"
                            />
                            <input
                              type="number"
                              min="0"
                              max="100"
                              value={criterion.weight}
                              onChange={(e) => handleWeightChange(index, parseInt(e.target.value) || 0)}
                              className="w-16 px-2 py-1 border border-gray-300 rounded text-center text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </>
                        ) : (
                          <span className="text-lg font-bold text-blue-600 w-16 text-right">
                            {criterion.weight}
                          </span>
                        )}
                        <span className="text-sm text-gray-600 w-4">%</span>
                      </div>
                    </div>
                    <div className="mt-2 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 transition-all"
                        style={{ width: `${criterion.weight}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {isEditing && getTotalWeight() !== 100 && (
              <div className="mt-4 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                <AppIcon className="fas fa-exclamation-triangle mr-2" />
                权重总和必须为100%！当前总和：{getTotalWeight()}%
              </div>
            )}
          </div>

          {/* 统计信息 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              招聘统计
            </h3>
            <div className="grid grid-cols-4 gap-6">
              <div className="text-center">
                <p className="text-3xl font-bold text-blue-600">{funnel.resumes}</p>
                <p className="text-sm text-gray-600 mt-2">投递简历</p>
              </div>
              <div className="text-center">
                <p className="text-3xl font-bold text-green-600">{funnel.pendingInterview}</p>
                <p className="text-sm text-gray-600 mt-2">待面试</p>
              </div>
              <div className="text-center">
                <p className="text-3xl font-bold text-yellow-600">{funnel.interviewing}</p>
                <p className="text-sm text-gray-600 mt-2">面试中</p>
              </div>
              <div className="text-center">
                <p className="text-3xl font-bold text-purple-600">{funnel.hired}</p>
                <p className="text-sm text-gray-600 mt-2">已录用</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
