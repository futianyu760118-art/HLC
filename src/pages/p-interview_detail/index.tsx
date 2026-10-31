/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { interviewsApi, jobsApi, resumesApi, Interview, Job, Resume } from '../../utils/api';
import { formatBusinessDateTime } from '../../utils/businessTime';
import { formatChinaDateTime } from '../../utils/date';
import { getStatusBadgeClass, getStatusLabel } from '../../utils/status';


import AppIcon from '../../components/AppIcon';
// 分析输入类型
type AnalysisInputType = 'text' | 'audio' | 'video';

export default function InterviewDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const interviewId = searchParams.get('interviewId');
  
  const [interview, setInterview] = useState<Interview | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  
  // AI分析相关状态
  const [activeInputType, setActiveInputType] = useState<AnalysisInputType>('text');
  const [feedbackText, setFeedbackText] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = '面试详情 - 恒聘通';
    loadInterview();
  }, [interviewId]);

  const loadInterview = async () => {
    if (!interviewId) {
      setError('缺少面试ID');
      setIsLoading(false);
      return;
    }

    try {
      const [interviews, jobs, resumes] = await Promise.all([
        interviewsApi.getAll(),
        jobsApi.getAll(),
        resumesApi.getAll()
      ]);

      const found = interviews.find(i => i.id === interviewId);
      if (found) {
        setInterview(found);
        setJob(jobs.find(j => j.id === found.jobId) || null);
        setResume(resumes.find(r => r.id === found.resumeId) || null);
      } else {
        setError('面试记录不存在');
      }
    } catch (_err) {
      setError('加载失败');
    } finally {
      setIsLoading(false);
    }
  };

  const handleUpdateStatus = async (newStatus: Interview['status']) => {
    if (!interview) return;

    try {
      const updated = await interviewsApi.update(interview.id, { status: newStatus });
      setInterview(updated);
      toast.info('状态更新成功');
    } catch (_err) {
      toast.info('更新失败');
    }
  };

  const handleDelete = async () => {
    if (!interview) return;
    const ok = await confirm({
      title: '删除面试',
      message: '确定要删除这条面试记录吗？',
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;

    try {
      await interviewsApi.delete(interview.id);
      toast.success('删除成功');
      navigate('/interview-manage');
    } catch (err: any) {
      toast.error(err?.message || '删除失败');
    }
  };

  // AI分析 - 文本分析
  const handleTextAnalyze = async () => {
    if (!interview || !feedbackText.trim()) {
      setAnalyzeError('请输入面试反馈内容');
      return;
    }
    
    if (feedbackText.trim().length < 50) {
      setAnalyzeError('面试反馈内容至少需要50字');
      return;
    }
    
    setIsAnalyzing(true);
    setAnalyzeError('');
    
    try {
      const result = await interviewsApi.analyzeText(interview.id, feedbackText);
      setInterview(result);
      setFeedbackText('');
      toast.info('AI分析完成！');
    } catch (err: any) {
      setAnalyzeError(err.message || '分析失败，请重试');
    } finally {
      setIsAnalyzing(false);
    }
  };

  // AI分析 - 媒体文件分析
  const handleMediaAnalyze = async () => {
    if (!interview || !selectedFile) {
      setAnalyzeError('请选择音频或视频文件');
      return;
    }
    
    setIsAnalyzing(true);
    setAnalyzeError('');
    
    try {
      const result = await interviewsApi.analyzeMedia(interview.id, selectedFile);
      if ('status' in result && result.status === 'file_saved') {
        // 文件已保存但功能未实现
        toast.info(result.message);
        setInterview(result.interview);
      } else {
        setInterview(result as Interview);
        toast.info('AI分析完成！');
      }
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err: any) {
      setAnalyzeError(err.message || '分析失败，请重试');
    } finally {
      setIsAnalyzing(false);
    }
  };

  // 清除分析结果
  const handleClearAnalysis = async () => {
    if (!interview) return;
    const ok = await confirm({
      title: '清除AI分析',
      message: '确定要清除AI分析结果吗？清除后需要重新分析。',
      danger: true,
      confirmText: '清除',
    });
    if (!ok) return;
    
    try {
      const result = await interviewsApi.clearAnalysis(interview.id);
      setInterview(result.interview);
      toast.success('已清除分析结果');
    } catch (err: any) {
      toast.error('清除失败: ' + (err.message || '未知错误'));
    }
  };

  // 文件选择处理
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setAnalyzeError('');
    }
  };

  // 获取维度分数颜色
  const getScoreColor = (score: number) => {
    if (score >= 85) return 'text-green-600';
    if (score >= 70) return 'text-yellow-600';
    return 'text-red-600';
  };

  // 获取推荐等级颜色
  const getRecommendationColor = (rec: string) => {
    if (rec.includes('强烈推荐') || rec === '推荐录用') return 'bg-green-100 text-green-700';
    if (rec.includes('复试')) return 'bg-yellow-100 text-yellow-700';
    return 'bg-red-100 text-red-700';
  };

  const getStatusColor = (status: string) => {
    return getStatusBadgeClass(status).replace('status-badge ', '');
  };

  const getStatusText = (status: string) => {
    return getStatusLabel(status);
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

  if (error || !interview) {
    return (
      <Layout>
        <div className="text-center py-12">
          <AppIcon className="fas fa-exclamation-circle text-5xl text-gray-400 mb-4" />
          <p className="text-gray-600">{error || '面试记录不存在'}</p>
          <button
            onClick={() => navigate('/interview-manage')}
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
              <h2 className="text-2xl font-bold text-gray-800 mb-2">面试详情</h2>
              <nav className="text-sm text-gray-600">
                <span>首页</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>面试管理</span>
                <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
                <span>面试详情</span>
              </nav>
            </div>
            <div className="flex items-center space-x-3">
              <button
                onClick={() => navigate('/interview-manage')}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                <AppIcon className="fas fa-arrow-left mr-2" />
                返回列表
              </button>
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

        {/* 面试内容 */}
        <div className="space-y-6">
          {/* 基本信息 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-start justify-between mb-4 pb-4 border-b">
              <h3 className="text-xl font-semibold text-gray-800">面试信息</h3>
              <span className={`px-4 py-2 rounded-full text-sm font-medium ${getStatusColor(interview.status)}`}>
                {getStatusText(interview.status)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <label className="text-sm font-medium text-gray-600 block mb-2">候选人</label>
                <p className="text-gray-800 font-medium">
                  {resume?.candidateName || '未知'}
                </p>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-600 block mb-2">应聘岗位</label>
                <p className="text-gray-800 font-medium">
                  {job?.title || '未知'}
                </p>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-600 block mb-2">面试时间</label>
                <p className="text-gray-800 font-medium">
                  {formatBusinessDateTime(interview.scheduledAt)}
                </p>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-600 block mb-2">面试状态</label>
                <p className="text-gray-800 font-medium">
                  {getStatusText(interview.status)}
                </p>
              </div>
              {interview.notes && (
                <div className="col-span-2">
                  <label className="text-sm font-medium text-gray-600 block mb-2">备注</label>
                  <p className="text-gray-700 whitespace-pre-wrap">{interview.notes}</p>
                </div>
              )}
            </div>
          </div>

          {/* 在线面试 */}
          {interview.roomId && (
            <div className="bg-gradient-to-r from-blue-500 to-indigo-600 rounded-xl p-6 text-white">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-semibold mb-2">
                    <AppIcon className="fas fa-video mr-2" />
                    在线面试
                  </h3>
                  <p className="text-blue-100 text-sm">
                    房间ID: {interview.roomId}
                  </p>
                  {interview.inviteToken && (
                    <p className="text-blue-100 text-sm mt-1">
                      <AppIcon className="fas fa-link mr-1" />
                      邀约链接已生成，点击“进入面试”复制发送给候选人
                    </p>
                  )}
                </div>
                <div className="flex items-center space-x-3">
                  <button
                    onClick={() => {
                      const link = `${window.location.origin}/interview-join?token=${interview.inviteToken}`;
                      navigator.clipboard.writeText(link);
                      toast.info('邀约链接已复制到剪贴板，请发送给候选人');
                    }}
                    className="px-4 py-2 bg-white/20 hover:bg-white/30 rounded-lg transition-colors"
                  >
                    <AppIcon className="fas fa-copy mr-2" />
                    复制邀约链接
                  </button>
                  <button
                    onClick={() => navigate(`/interview-room?interviewId=${interview.id}`)}
                    className="px-6 py-3 bg-white text-blue-600 font-semibold rounded-lg hover:bg-blue-50 transition-colors"
                  >
                    <AppIcon className="fas fa-video mr-2" />
                    进入面试
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* 状态操作 */}
          {interview.status !== 'completed' && interview.status !== 'cancelled' && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
                更新状态
              </h3>
              <div className="flex items-center space-x-4">
                <button
                  onClick={() => handleUpdateStatus('completed')}
                  className="flex-1 bg-green-600 text-white py-3 px-6 rounded-lg hover:bg-green-700 transition-colors"
                >
                  <AppIcon className="fas fa-check mr-2" />
                  标记为已完成
                </button>
                <button
                  onClick={() => handleUpdateStatus('cancelled')}
                  className="flex-1 bg-gray-600 text-white py-3 px-6 rounded-lg hover:bg-gray-700 transition-colors"
                >
                  <AppIcon className="fas fa-times mr-2" />
                  标记为已取消
                </button>
              </div>
            </div>
          )}

          {/* AI面试分析区域 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4 pb-3 border-b">
              <h3 className="text-lg font-semibold text-gray-800">
                <AppIcon className="fas fa-robot text-blue-500 mr-2" />
                AI面试分析
              </h3>
              {interview.aiAnalysis && (
                <button
                  onClick={handleClearAnalysis}
                  className="text-sm text-red-600 hover:text-red-700"
                >
                  <AppIcon className="fas fa-trash mr-1" />
                  清除分析
                </button>
              )}
            </div>

            {/* 已有分析结果 - 显示分析报告 */}
            {interview.aiAnalysis ? (
              <div className="space-y-6">
                {/* 综合评分卡片 */}
                <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-gray-600 mb-1">综合评分</p>
                      <div className="flex items-baseline">
                        <span className={`text-5xl font-bold ${getScoreColor(interview.aiAnalysis.overallScore)}`}>
                          {interview.aiAnalysis.overallScore}
                        </span>
                        <span className="text-gray-500 ml-1">/ 100</span>
                      </div>
                      <p className="text-sm text-gray-500 mt-1">
                        等级: <span className="font-medium">{interview.aiAnalysis.overallLevel}</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <span className={`inline-block px-4 py-2 rounded-full text-sm font-medium ${getRecommendationColor(interview.aiAnalysis.recommendation)}`}>
                        {interview.aiAnalysis.recommendation}
                      </span>
                      {interview.analyzedAt && (
                        <p className="text-xs text-gray-400 mt-2">
                          分析时间: {formatChinaDateTime(interview.analyzedAt)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                {/* 五维评分雷达 */}
                <div className="grid grid-cols-5 gap-4">
                  {[
                    { key: 'professionalScore', label: '专业能力', icon: 'fa-briefcase' },
                    { key: 'communicationScore', label: '沟通表达', icon: 'fa-comments' },
                    { key: 'teamworkScore', label: '团队协作', icon: 'fa-users' },
                    { key: 'learningScore', label: '学习能力', icon: 'fa-graduation-cap' },
                    { key: 'cultureScore', label: '文化匹配', icon: 'fa-heart' },
                  ].map(dim => {
                    const score = interview.aiAnalysis!.dimensions[dim.key as keyof typeof interview.aiAnalysis.dimensions];
                    return (
                      <div key={dim.key} className="bg-gray-50 rounded-lg p-4 text-center">
                        <AppIcon className={`fas ${dim.icon} text-xl text-gray-400 mb-2`} />
                        <p className="text-xs text-gray-500 mb-1">{dim.label}</p>
                        <p className={`text-2xl font-bold ${getScoreColor(score)}`}>{score}</p>
                      </div>
                    );
                  })}
                </div>

                {/* 综合评价 */}
                <div>
                  <h4 className="font-medium text-gray-800 mb-2">
                    <AppIcon className="fas fa-clipboard-list text-blue-500 mr-2" />
                    综合评价
                  </h4>
                  <p className="text-gray-700 bg-gray-50 p-4 rounded-lg leading-relaxed">
                    {interview.aiAnalysis.summary}
                  </p>
                </div>

                {/* 优势与不足 */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-green-50 rounded-lg p-4">
                    <h4 className="font-medium text-green-800 mb-3">
                      <AppIcon className="fas fa-thumbs-up mr-2" />
                      优势亮点
                    </h4>
                    <ul className="space-y-2">
                      {interview.aiAnalysis.strengths.map((s, i) => (
                        <li key={i} className="flex items-start text-sm text-green-700">
                          <AppIcon className="fas fa-check-circle mt-0.5 mr-2 flex-shrink-0" />
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="bg-red-50 rounded-lg p-4">
                    <h4 className="font-medium text-red-800 mb-3">
                      <AppIcon className="fas fa-exclamation-triangle mr-2" />
                      待改进项
                    </h4>
                    <ul className="space-y-2">
                      {interview.aiAnalysis.weaknesses.map((w, i) => (
                        <li key={i} className="flex items-start text-sm text-red-700">
                          <AppIcon className="fas fa-times-circle mt-0.5 mr-2 flex-shrink-0" />
                          {w}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* 录用建议 */}
                <div className="bg-blue-50 rounded-lg p-4">
                  <h4 className="font-medium text-blue-800 mb-2">
                    <AppIcon className="fas fa-lightbulb mr-2" />
                    录用建议
                  </h4>
                  <p className="text-blue-700">{interview.aiAnalysis.hiringAdvice}</p>
                </div>

                {/* 风险因素 */}
                {interview.aiAnalysis.riskFactors && interview.aiAnalysis.riskFactors.length > 0 && (
                  <div className="bg-yellow-50 rounded-lg p-4">
                    <h4 className="font-medium text-yellow-800 mb-2">
                      <AppIcon className="fas fa-exclamation-circle mr-2" />
                      风险提示
                    </h4>
                    <ul className="space-y-1">
                      {interview.aiAnalysis.riskFactors.map((r, i) => (
                        <li key={i} className="text-sm text-yellow-700">• {r}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* 后续关注事项 */}
                {interview.aiAnalysis.followUpQuestions && interview.aiAnalysis.followUpQuestions.length > 0 && (
                  <div>
                    <h4 className="font-medium text-gray-800 mb-2">
                      <AppIcon className="fas fa-question-circle text-purple-500 mr-2" />
                      后续待确认问题
                    </h4>
                    <ul className="space-y-1 text-sm text-gray-600">
                      {interview.aiAnalysis.followUpQuestions.map((q, i) => (
                        <li key={i}>• {q}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              /* 无分析结果 - 显示输入表单 */
              <div className="space-y-4">
                {/* 输入类型选择 */}
                <div className="flex border-b border-gray-200">
                  {[
                    { type: 'text' as AnalysisInputType, label: '文本输入', icon: 'fa-keyboard' },
                    { type: 'audio' as AnalysisInputType, label: '音频上传', icon: 'fa-microphone', badge: '即将上线' },
                    { type: 'video' as AnalysisInputType, label: '视频上传', icon: 'fa-video', badge: '即将上线' },
                  ].map(tab => (
                    <button
                      key={tab.type}
                      onClick={() => setActiveInputType(tab.type)}
                      className={`flex items-center px-4 py-3 border-b-2 transition-colors ${
                        activeInputType === tab.type
                          ? 'border-blue-500 text-blue-600'
                          : 'border-transparent text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      <AppIcon className={`fas ${tab.icon} mr-2`} />
                      {tab.label}
                      {tab.badge && (
                        <span className="ml-2 px-1.5 py-0.5 bg-orange-100 text-orange-600 text-xs rounded">
                          {tab.badge}
                        </span>
                      )}
                    </button>
                  ))}
                </div>

                {/* 文本输入 */}
                {activeInputType === 'text' && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        面试反馈内容
                      </label>
                      <textarea
                        value={feedbackText}
                        onChange={(e) => setFeedbackText(e.target.value)}
                        placeholder="请输入面试反馈内容，包括：候选人表现、专业能力评估、沟通表达、团队协作意愿、个人印象等..."
                        className="w-full h-48 p-4 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                      />
                      <p className="text-xs text-gray-400 mt-1">
                        已输入 {feedbackText.length} 字（至少需要50字）
                      </p>
                    </div>
                    
                    {analyzeError && (
                      <div className="p-3 bg-red-50 text-red-600 rounded-lg text-sm">
                        <AppIcon className="fas fa-exclamation-circle mr-2" />
                        {analyzeError}
                      </div>
                    )}
                    
                    <button
                      onClick={handleTextAnalyze}
                      disabled={isAnalyzing || feedbackText.length < 50}
                      className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isAnalyzing ? (
                        <>
                          <AppIcon className="fas fa-spinner fa-spin mr-2" />
                          AI分析中...
                        </>
                      ) : (
                        <>
                          <AppIcon className="fas fa-robot mr-2" />
                          开始AI分析
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* 音频上传 */}
                {activeInputType === 'audio' && (
                  <div className="space-y-4">
                    <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                      <AppIcon className="fas fa-microphone text-4xl text-gray-300 mb-4" />
                      <p className="text-gray-600 mb-2">上传面试音频文件</p>
                      <p className="text-xs text-gray-400 mb-4">支持 MP3, WAV, OGG, M4A 格式</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".mp3,.wav,.ogg,.m4a,.aac,.flac"
                        onChange={handleFileSelect}
                        className="hidden"
                        id="audio-upload"
                      />
                      <label
                        htmlFor="audio-upload"
                        className="inline-block px-4 py-2 bg-gray-100 text-gray-700 rounded-lg cursor-pointer hover:bg-gray-200"
                      >
                        选择文件
                      </label>
                      {selectedFile && activeInputType === 'audio' && (
                        <p className="mt-2 text-sm text-blue-600">
                          <AppIcon className="fas fa-file-audio mr-1" />
                          {selectedFile.name}
                        </p>
                      )}
                    </div>
                    
                    <div className="p-3 bg-orange-50 text-orange-700 rounded-lg text-sm">
                      <AppIcon className="fas fa-info-circle mr-2" />
                      音频分析功能即将上线，当前可先上传文件保存，待功能上线后自动分析
                    </div>
                    
                    {analyzeError && (
                      <div className="p-3 bg-red-50 text-red-600 rounded-lg text-sm">
                        <AppIcon className="fas fa-exclamation-circle mr-2" />
                        {analyzeError}
                      </div>
                    )}
                    
                    <button
                      onClick={handleMediaAnalyze}
                      disabled={isAnalyzing || !selectedFile}
                      className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isAnalyzing ? (
                        <>
                          <AppIcon className="fas fa-spinner fa-spin mr-2" />
                          上传中...
                        </>
                      ) : (
                        <>
                          <AppIcon className="fas fa-upload mr-2" />
                          上传音频
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* 视频上传 */}
                {activeInputType === 'video' && (
                  <div className="space-y-4">
                    <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                      <AppIcon className="fas fa-video text-4xl text-gray-300 mb-4" />
                      <p className="text-gray-600 mb-2">上传面试视频文件</p>
                      <p className="text-xs text-gray-400 mb-4">支持 MP4, AVI, MOV, MKV, WEBM 格式</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".mp4,.avi,.mov,.mkv,.webm"
                        onChange={handleFileSelect}
                        className="hidden"
                        id="video-upload"
                      />
                      <label
                        htmlFor="video-upload"
                        className="inline-block px-4 py-2 bg-gray-100 text-gray-700 rounded-lg cursor-pointer hover:bg-gray-200"
                      >
                        选择文件
                      </label>
                      {selectedFile && activeInputType === 'video' && (
                        <p className="mt-2 text-sm text-blue-600">
                          <AppIcon className="fas fa-file-video mr-1" />
                          {selectedFile.name}
                        </p>
                      )}
                    </div>
                    
                    <div className="p-3 bg-orange-50 text-orange-700 rounded-lg text-sm">
                      <AppIcon className="fas fa-info-circle mr-2" />
                      视频分析功能即将上线，当前可先上传文件保存，待功能上线后自动分析
                    </div>
                    
                    {analyzeError && (
                      <div className="p-3 bg-red-50 text-red-600 rounded-lg text-sm">
                        <AppIcon className="fas fa-exclamation-circle mr-2" />
                        {analyzeError}
                      </div>
                    )}
                    
                    <button
                      onClick={handleMediaAnalyze}
                      disabled={isAnalyzing || !selectedFile}
                      className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isAnalyzing ? (
                        <>
                          <AppIcon className="fas fa-spinner fa-spin mr-2" />
                          上传中...
                        </>
                      ) : (
                        <>
                          <AppIcon className="fas fa-upload mr-2" />
                          上传视频
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 相关信息 */}
          <div className="grid grid-cols-2 gap-6">
            {/* 候选人简历 */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
                候选人简历
              </h3>
              {resume ? (
                <div>
                  <p className="font-medium text-gray-800 mb-2">{resume.candidateName}</p>
                  <p className="text-sm text-gray-600 mb-4">
                    上传时间：{formatChinaDateTime(resume.createdAt)}
                  </p>
                  <button
                    onClick={() => navigate(`/resume-detail?resumeId=${resume.id}`)}
                    className="w-full px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
                  >
                    查看简历详情
                  </button>
                </div>
              ) : (
                <p className="text-gray-500">简历信息不可用</p>
              )}
            </div>

            {/* 岗位信息 */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
                岗位信息
              </h3>
              {job ? (
                <div>
                  <p className="font-medium text-gray-800 mb-2">{job.title}</p>
                  <p className="text-sm text-gray-600 mb-4">
                    {job.status === 'open' ? '招聘中' : '已关闭'}
                  </p>
                  <button
                    onClick={() => navigate(`/job-detail?jobId=${job.id}`)}
                    className="w-full px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
                  >
                    查看岗位详情
                  </button>
                </div>
              ) : (
                <p className="text-gray-500">岗位信息不可用</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
