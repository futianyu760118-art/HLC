/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { resumesApi, jobsApi, Resume, Job, fileApi } from '../../utils/api';
import { formatChinaDateTime } from '../../utils/date';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';


import AppIcon from '../../components/AppIcon';
export default function ResumeDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const resumeId = searchParams.get('resumeId');
  
  const [resume, setResume] = useState<Resume | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    candidateName: '',
    email: '',
    phone: '',
  });
  const [isReanalyzing, setIsReanalyzing] = useState(false);

  useEffect(() => {
    document.title = '简历详情 - 恒聘通';
    loadResume();
  }, [resumeId]);

  const loadResume = async () => {
    if (!resumeId) {
      setError('缺少简历ID');
      setIsLoading(false);
      return;
    }

    try {
      const [resumes, jobs] = await Promise.all([
        resumesApi.getAll(),
        jobsApi.getAll()
      ]);
      
      const found = resumes.find(r => r.id === resumeId);
      if (found) {
        setResume(found);
        setJob(jobs.find(j => j.id === found.jobId) || null);
        setEditForm({
          candidateName: found.candidateName,
          email: found.email || '',
          phone: found.phone || '',
        });
      } else {
        setError('简历不存在');
      }
    } catch (_err) {
      setError('加载失败');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!resume) return;
    const ok = await confirm({
      title: '删除简历',
      message: '确定要删除这份简历吗？此操作不可撤销。',
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;

    try {
      await resumesApi.delete(resume.id);
      toast.success('删除成功');
      navigate('/resume-manage');
    } catch (err: any) {
      toast.error(err?.message || '删除失败');
    }
  };

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    if (resume) {
      setEditForm({
        candidateName: resume.candidateName,
        email: resume.email || '',
        phone: resume.phone || '',
      });
    }
    setIsEditing(false);
  };

  const handleSaveEdit = async () => {
    if (!resume) return;
    
    try {
      await resumesApi.update(resume.id, {
        candidateName: editForm.candidateName,
      });
      
      // 更新本地状态
      setResume({
        ...resume,
        candidateName: editForm.candidateName,
        email: editForm.email,
        phone: editForm.phone,
      });
      
      setIsEditing(false);
      toast.success('保存成功');
    } catch (err: any) {
      toast.error(err?.message || '保存失败');
    }
  };

  const handleReanalyze = async () => {
    if (!resume) return;
    const ok = await confirm({
      title: '重新分析简历',
      message: 'AI 将使用最新评估标准重新分析这份简历，原有评分会被覆盖。确定继续？',
      confirmText: '重新分析',
    });
    if (!ok) return;

    try {
      setIsReanalyzing(true);
      const updatedResume = await resumesApi.reanalyze(resume.id);
      setResume(updatedResume);
      toast.success('重新分析完成');
      
      // 刷新页面数据
      await loadResume();
    } catch (err: any) {
      toast.error(err?.message || '重新分析失败');
    } finally {
      setIsReanalyzing(false);
    }
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

  if (error || !resume) {
    return (
      <Layout>
        <div className="text-center py-12">
          <AppIcon className="fas fa-exclamation-circle text-5xl text-gray-400 mb-4" />
          <p className="text-gray-600">{error || '简历不存在'}</p>
          <button
            onClick={() => navigate('/resume-manage')}
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
              <h2 className="text-2xl font-bold text-gray-800 mb-2">简历详情</h2>
              <nav className="text-sm text-gray-600">
                <span>首页</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>简历管理</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>简历详情</span>
              </nav>
            </div>
            <div className="flex items-center space-x-3">
              <button
                onClick={() => navigate('/resume-manage')}
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
                    onClick={handleReanalyze}
                    disabled={isReanalyzing}
                    className="px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isReanalyzing ? (
                      <>
                        <AppIcon className="fas fa-spinner fa-spin mr-2" />
                        分析中...
                      </>
                    ) : (
                      <>
                        <AppIcon className="fas fa-sync-alt mr-2" />
                        重新分析
                      </>
                    )}
                  </button>
                </>
              )}
              <button
                onClick={handleDelete}
                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
              >
                <AppIcon className="fas fa-trash mr-2" />
                删除
              </button>
            </div>
          </div>
        </div>

        {/* 简历内容 */}
        <div className="space-y-6">
          {/* AI评分概览 */}
          {resume.aiAnalysis && (
            <div className="grid grid-cols-2 gap-6">
              <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl p-6 text-white">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-blue-100 text-sm mb-1">AI综合评分</p>
                    <p className="text-5xl font-bold">{resume.aiAnalysis.score}</p>
                    <p className="text-blue-100 text-sm mt-2">满分100分</p>
                  </div>
                  <div className="w-16 h-16 bg-white bg-opacity-20 rounded-full flex items-center justify-center">
                    <AppIcon className="fas fa-star text-3xl" />
                  </div>
                </div>
              </div>

              <div className="bg-gradient-to-br from-green-500 to-green-600 rounded-xl p-6 text-white">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-green-100 text-sm mb-1">岗位匹配度</p>
                    <p className="text-5xl font-bold">{resume.aiAnalysis.matchDegree}%</p>
                    <p className="text-green-100 text-sm mt-2">{resume.aiAnalysis.recommendation}</p>
                  </div>
                  <div className="w-16 h-16 bg-white bg-opacity-20 rounded-full flex items-center justify-center">
                    <AppIcon className="fas fa-chart-line text-3xl" />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 基本信息 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4 pb-3 border-b">
              <h3 className="text-lg font-semibold text-gray-800">
                基本信息
              </h3>
              {isEditing && (
                <div className="flex items-center space-x-2">
                  <button
                    onClick={handleSaveEdit}
                    className="px-3 py-1 bg-green-500 text-white text-sm rounded hover:bg-green-600"
                  >
                    <AppIcon className="fas fa-save mr-1" />
                    保存
                  </button>
                  <button
                    onClick={handleCancelEdit}
                    className="px-3 py-1 bg-gray-300 text-gray-700 text-sm rounded hover:bg-gray-400"
                  >
                    <AppIcon className="fas fa-times mr-1" />
                    取消
                  </button>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-gray-600">候选人姓名</label>
                {isEditing ? (
                  <input
                    type="text"
                    value={editForm.candidateName}
                    onChange={(e) => setEditForm({ ...editForm, candidateName: e.target.value })}
                    className="w-full mt-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                ) : (
                  <p className="text-gray-800 font-medium mt-1">{resume.candidateName}</p>
                )}
              </div>
              <div>
                <label className="text-sm text-gray-600">应聘岗位</label>
                <p className="text-gray-800 font-medium mt-1">{job?.title || '未知岗位'}</p>
              </div>
              <div>
                <label className="text-sm text-gray-600">邮箱</label>
                {isEditing ? (
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full mt-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="请输入邮箱"
                  />
                ) : (
                  <p className="text-gray-800 font-medium mt-1">{resume.email || '未填写'}</p>
                )}
              </div>
              <div>
                <label className="text-sm text-gray-600">电话</label>
                {isEditing ? (
                  <input
                    type="tel"
                    value={editForm.phone}
                    onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                    className="w-full mt-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="请输入电话"
                  />
                ) : (
                  <p className="text-gray-800 font-medium mt-1">{resume.phone || '未填写'}</p>
                )}
              </div>
              {resume.aiAnalysis && (
                <>
                  <div>
                    <label className="text-sm text-gray-600">工作经验</label>
                    <p className="text-gray-800 font-medium mt-1">{resume.aiAnalysis.experience}</p>
                  </div>
                  <div>
                    <label className="text-sm text-gray-600">学历</label>
                    <p className="text-gray-800 font-medium mt-1">{resume.aiAnalysis.education}</p>
                  </div>
                </>
              )}
              <div>
                <label className="text-sm text-gray-600">上传时间</label>
                <p className="text-gray-800 font-medium mt-1">
                  {formatChinaDateTime(resume.createdAt)}
                </p>
              </div>
            </div>
          </div>

          {/* AI分析结果 */}
          {resume.aiAnalysis && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b flex items-center justify-between">
                <div className="flex items-center">
                  <AppIcon className="fas fa-robot text-blue-600 mr-2" />
                  AI分析结果
                </div>
                {/* AI调用状态标签 */}
                {resume.aiAnalysis.aiStatus && (
                  <div className="flex items-center space-x-2">
                    {resume.aiAnalysis.aiStatus.success ? (
                      resume.aiAnalysis.aiStatus.fallbackUsed ? (
                        <span className="px-3 py-1 bg-yellow-100 text-yellow-800 text-xs rounded-full flex items-center">
                          <AppIcon className="fas fa-exclamation-triangle mr-1" />
                          使用备用模型
                        </span>
                      ) : (
                        <span className="px-3 py-1 bg-green-100 text-green-800 text-xs rounded-full flex items-center">
                          <AppIcon className="fas fa-check-circle mr-1" />
                          AI分析成功
                        </span>
                      )
                    ) : (
                      <span className="px-3 py-1 bg-red-100 text-red-800 text-xs rounded-full flex items-center">
                        <AppIcon className="fas fa-times-circle mr-1" />
                        AI分析失败
                      </span>
                    )}
                  </div>
                )}
              </h3>

              {/* AI状态详情（如果有错误或使用了备用） */}
              {resume.aiAnalysis.aiStatus && (resume.aiAnalysis.aiStatus.fallbackUsed || !resume.aiAnalysis.aiStatus.success) && (
                <div className={`mb-4 p-4 rounded-lg border ${
                  resume.aiAnalysis.aiStatus.success 
                    ? 'bg-yellow-50 border-yellow-200' 
                    : 'bg-red-50 border-red-200'
                }`}>
                  <div className="flex items-start">
                    <AppIcon className={`fas ${
                      resume.aiAnalysis.aiStatus.success 
                        ? 'fa-info-circle text-yellow-600' 
                        : 'fa-exclamation-circle text-red-600'
                    } mr-3 mt-0.5`} />
                    <div className="flex-1">
                      <p className={`text-sm font-medium mb-2 ${
                        resume.aiAnalysis.aiStatus.success 
                          ? 'text-yellow-800' 
                          : 'text-red-800'
                      }`}>
                        {resume.aiAnalysis.aiStatus.success 
                          ? '主模型调用失败，已自动切换到备用模型' 
                          : 'AI模型调用失败'}
                      </p>
                      {resume.aiAnalysis.aiStatus.modelUsed && (
                        <p className="text-xs text-gray-600 mb-1">
                          <strong>使用模型：</strong>{resume.aiAnalysis.aiStatus.modelUsed}
                        </p>
                      )}
                      {resume.aiAnalysis.aiStatus.errorMessage && (
                        <p className="text-xs text-gray-600 mb-1">
                          <strong>错误信息：</strong>{resume.aiAnalysis.aiStatus.errorMessage}
                        </p>
                      )}
                      {resume.aiAnalysis.aiStatus.totalAttempts > 0 && (
                        <p className="text-xs text-gray-600">
                          <strong>尝试次数：</strong>{resume.aiAnalysis.aiStatus.totalAttempts}
                        </p>
                      )}
                      {resume.aiAnalysis.aiStatus.usingManualFallback && (
                        <p className="text-xs text-gray-600 mt-2 italic">
                          * 所有AI模型均不可用，当前显示的是基于规则的备用分析结果，建议稍后重新分析。
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}
              
              {/* AI总结 */}
              <div className="mb-6">
                <label className="text-sm font-medium text-gray-700 block mb-3">综合评价</label>
                <div className="space-y-3">
                  {resume.aiAnalysis.summary.split('\n').filter(p => p.trim()).map((paragraph, index) => (
                    <div 
                      key={index} 
                      className="bg-gradient-to-r from-gray-50 to-white border-l-4 border-blue-500 p-4 rounded-r-lg shadow-sm hover:shadow-md transition-shadow"
                    >
                      <p className="text-gray-800 leading-relaxed">
                        {paragraph}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              {/* 技能 */}
              <div className="mb-6">
                <label className="text-sm font-medium text-gray-700 block mb-2">技能清单</label>
                <div className="flex flex-wrap gap-2">
                  {resume.aiAnalysis.skills.map((skill, index) => (
                    <span
                      key={index}
                      className="px-3 py-1 bg-blue-100 text-blue-700 text-sm rounded-lg"
                    >
                      <AppIcon className="fas fa-check mr-1" />
                      {skill}
                    </span>
                  ))}
                </div>
              </div>

              {/* 优势与不足 */}
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <label className="text-sm font-medium text-green-700 block mb-2">
                    <AppIcon className="fas fa-thumbs-up mr-1" />
                    优势
                  </label>
                  <ul className="space-y-2">
                    {resume.aiAnalysis.strengths.map((strength, index) => (
                      <li key={index} className="text-sm text-gray-700 flex items-start">
                        <AppIcon className="fas fa-plus-circle text-green-600 mr-2 mt-0.5" />
                        {strength}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <label className="text-sm font-medium text-yellow-700 block mb-2">
                    <AppIcon className="fas fa-exclamation-triangle mr-1" />
                    待提升
                  </label>
                  <ul className="space-y-2">
                    {resume.aiAnalysis.weaknesses.map((weakness, index) => (
                      <li key={index} className="text-sm text-gray-700 flex items-start">
                        <AppIcon className="fas fa-minus-circle text-yellow-600 mr-2 mt-0.5" />
                        {weakness}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* 面试建议 */}
          {resume.aiAnalysis && (resume.aiAnalysis.interviewFocus || resume.aiAnalysis.interviewQuestions) && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b flex items-center">
                <AppIcon className="fas fa-clipboard-list text-purple-600 mr-2" />
                AI面试建议
              </h3>
              
              {/* 面试侧重点 */}
              {resume.aiAnalysis.interviewFocus && resume.aiAnalysis.interviewFocus.length > 0 && (
                <div className="mb-6">
                  <label className="text-sm font-medium text-gray-700 block mb-3">
                    <AppIcon className="fas fa-bullseye text-orange-500 mr-2" />
                    面试侧重点
                  </label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {resume.aiAnalysis.interviewFocus.map((focus, index) => (
                      <div
                        key={index}
                        className="bg-gradient-to-r from-orange-50 to-yellow-50 border border-orange-200 rounded-lg p-3"
                      >
                        <div className="flex items-center">
                          <div className="flex-shrink-0 w-8 h-8 bg-orange-500 text-white rounded-full flex items-center justify-center font-bold mr-3">
                            {index + 1}
                          </div>
                          <p className="text-sm text-gray-800 font-medium">{focus}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 推荐面试题 */}
              {resume.aiAnalysis.interviewQuestions && resume.aiAnalysis.interviewQuestions.length > 0 && (
                <div>
                  <label className="text-sm font-medium text-gray-700 block mb-3">
                    <AppIcon className="fas fa-question-circle text-purple-500 mr-2" />
                    推荐面试题目
                  </label>
                  <div className="space-y-4">
                    {resume.aiAnalysis.interviewQuestions.map((item, index) => (
                      <div
                        key={index}
                        className="bg-purple-50 border border-purple-200 rounded-lg p-4"
                      >
                        <div className="flex items-start">
                          <div className="flex-shrink-0 w-8 h-8 bg-purple-600 text-white rounded-full flex items-center justify-center font-bold mr-3 mt-1">
                            Q{index + 1}
                          </div>
                          <div className="flex-1">
                            <p className="text-gray-800 font-medium mb-2 leading-relaxed">
                              {item.question}
                            </p>
                            <div className="flex items-start text-xs text-purple-700 bg-white bg-opacity-60 rounded px-3 py-2">
                              <AppIcon className="fas fa-lightbulb mr-2 mt-0.5" />
                              <span className="flex-1">{item.purpose}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 提示信息 */}
              <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <p className="text-sm text-blue-800 flex items-start">
                  <AppIcon className="fas fa-info-circle mr-2 mt-0.5" />
                  <span>以上面试建议由AI根据候选人简历和岗位要求生成，仅供参考。实际面试时请结合公司文化、团队需求等因素综合考虑。</span>
                </p>
              </div>
            </div>
          )}

          {/* 快捷操作 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              快捷操作
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={() => {
                  if (resume.jobId && job?.status === 'open') {
                    navigate(`/interview-create?resumeId=${resume.id}&jobId=${resume.jobId}`);
                  }
                }}
                disabled={!job || job.status !== 'open'}
                className={`px-4 py-3 rounded-lg transition-colors ${
                  job?.status === 'open' 
                    ? 'bg-blue-600 text-white hover:bg-blue-700' 
                    : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                }`}
                title={job?.status !== 'open' ? '岗位已关闭，无法安排面试' : ''}
              >
                <AppIcon className="fas fa-calendar-plus mr-2" />
                {job?.status === 'open' ? '安排面试' : '岗位已关闭'}
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await fileApi.download(resume.fileUrl, `${resume.candidateName || 'resume'}.pdf`);
                  } catch (e: any) {
                    toast.error(e.message || '下载失败');
                  }
                }}
                className="px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-center"
              >
                <AppIcon className="fas fa-download mr-2" />
                下载简历
              </button>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
