/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import { interviewsApi, jobsApi, resumesApi, Job, Resume } from '../../utils/api';

import AppIcon from '../../components/AppIcon';
export default function InterviewCreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [allResumes, setAllResumes] = useState<Resume[]>([]);
  const [formData, setFormData] = useState({
    jobId: '',
    resumeId: '',
    scheduledAt: '',
    notes: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  // 搜索相关状态
  const [jobSearch, setJobSearch] = useState('');
  const [resumeSearch, setResumeSearch] = useState('');
  const [showJobDropdown, setShowJobDropdown] = useState(false);
  const [showResumeDropdown, setShowResumeDropdown] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedResume, setSelectedResume] = useState<Resume | null>(null);

  const jobDropdownRef = useRef<HTMLDivElement>(null);
  const resumeDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = '新建面试 - 恒聘通';
    loadData();

    // 点击外部关闭下拉框
    const handleClickOutside = (e: MouseEvent) => {
      if (jobDropdownRef.current && !jobDropdownRef.current.contains(e.target as Node)) {
        setShowJobDropdown(false);
      }
      if (resumeDropdownRef.current && !resumeDropdownRef.current.contains(e.target as Node)) {
        setShowResumeDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadData = async () => {
    try {
      const [jobsData, resumesData] = await Promise.all([
        jobsApi.getAll(),
        resumesApi.getAll()
      ]);
      setJobs(jobsData.filter(j => j.status === 'open'));
      setAllResumes(resumesData);
      
      // 从 URL 参数自动填充岗位和候选人
      const urlJobId = searchParams.get('jobId');
      const urlResumeId = searchParams.get('resumeId');
      
      if (urlJobId) {
        const job = jobsData.find(j => j.id === urlJobId);
        // 只有open状态的岗位才能创建面试
        if (job && job.status === 'open') {
          setSelectedJob(job);
          setJobSearch(job.title);
          setFormData(prev => ({ ...prev, jobId: urlJobId }));
        }
      }
      
      if (urlResumeId) {
        const resume = resumesData.find(r => r.id === urlResumeId);
        if (resume) {
          setSelectedResume(resume);
          setResumeSearch(resume.candidateName);
          setFormData(prev => ({ ...prev, resumeId: urlResumeId }));
        }
      }
    } catch (_err) {
      setError('加载数据失败');
    } finally {
      setIsLoading(false);
    }
  };

  // 根据岗位筛选候选人
  const filteredResumes = formData.jobId
    ? allResumes.filter(r => r.jobId === formData.jobId)
    : allResumes;

  // 搜索过滤后的岗位
  const searchedJobs = jobs.filter(j =>
    j.title.toLowerCase().includes(jobSearch.toLowerCase())
  );

  // 搜索过滤后的候选人
  const searchedResumes = filteredResumes.filter(r =>
    r.candidateName.toLowerCase().includes(resumeSearch.toLowerCase())
  );

  // 选择岗位
  const handleSelectJob = (job: Job) => {
    setSelectedJob(job);
    setFormData(prev => ({ ...prev, jobId: job.id, resumeId: '' }));
    setJobSearch(job.title);
    setShowJobDropdown(false);
    // 清空候选人选择，因为岗位变了
    setSelectedResume(null);
    setResumeSearch('');
  };

  // 选择候选人
  const handleSelectResume = (resume: Resume) => {
    setSelectedResume(resume);
    setFormData(prev => ({ ...prev, resumeId: resume.id }));
    setResumeSearch(resume.candidateName);
    setShowResumeDropdown(false);
  };

  const handleInputChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!formData.jobId) {
      setError('请选择岗位');
      return;
    }

    if (!formData.resumeId) {
      setError('请选择候选人');
      return;
    }

    if (!formData.scheduledAt) {
      setError('请选择面试时间');
      return;
    }

    // 允许创建历史面试记录，不限制时间
    // const scheduledDate = new Date(formData.scheduledAt);
    // if (scheduledDate < new Date()) {
    //   setError('面试时间不能早于当前时间');
    //   return;
    // }

    setIsSubmitting(true);

    try {
      await interviewsApi.create(
        formData.jobId,
        formData.resumeId,
        formData.scheduledAt,
        formData.notes
      );
      
      toast.info('面试安排成功！');
      navigate('/interview-manage');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '创建失败，请重试';
      setError(errorMessage);
    } finally {
      setIsSubmitting(false);
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

  return (
    <Layout>
      <div className="max-w-3xl mx-auto">
        {/* 页面头部 */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-800 mb-2">新建面试</h2>
          <nav className="text-sm text-gray-600">
            <span>首页</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>面试管理</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>新建面试</span>
          </nav>
        </div>

        {/* 表单 */}
        <div className="bg-white rounded-xl border border-gray-200 p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* 选择岗位 - 可搜索 */}
            <div ref={jobDropdownRef} className="relative">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                岗位 <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={jobSearch}
                  onChange={(e) => {
                    setJobSearch(e.target.value);
                    setShowJobDropdown(true);
                    if (!e.target.value) {
                      setFormData(prev => ({ ...prev, jobId: '', resumeId: '' }));
                      setSelectedJob(null);
                      setSelectedResume(null);
                      setResumeSearch('');
                    }
                  }}
                  onFocus={() => setShowJobDropdown(true)}
                  placeholder="搜索岗位名称..."
                  className="w-full px-4 py-3 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <AppIcon className="fas fa-search absolute right-3 top-1/2 -translate-y-1/2 text-gray-400" />
                {selectedJob && (
                  <button
                    type="button"
                    onClick={() => {
                      setJobSearch('');
                      setFormData(prev => ({ ...prev, jobId: '', resumeId: '' }));
                      setSelectedJob(null);
                      setSelectedResume(null);
                      setResumeSearch('');
                    }}
                    className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <AppIcon className="fas fa-times" />
                  </button>
                )}
              </div>
              {showJobDropdown && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-auto">
                  {searchedJobs.length > 0 ? (
                    searchedJobs.map(job => (
                      <div
                        key={job.id}
                        onClick={() => handleSelectJob(job)}
                        className={`px-4 py-3 cursor-pointer hover:bg-blue-50 ${
                          formData.jobId === job.id ? 'bg-blue-50 text-blue-600' : ''
                        }`}
                      >
                        <p className="font-medium">{job.title}</p>
                        <p className="text-sm text-gray-500">{job.status === 'open' ? '招聘中' : '已关闭'}</p>
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-gray-500 text-center">
                      {jobs.length === 0 ? (
                        <span>
                          暂无开放岗位，
                          <button
                            type="button"
                            onClick={() => navigate('/job-create')}
                            className="text-blue-600 hover:underline"
                          >
                            立即创建
                          </button>
                        </span>
                      ) : (
                        '未找到匹配的岗位'
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 选择候选人 - 可搜索，根据岗位筛选 */}
            <div ref={resumeDropdownRef} className="relative">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                候选人 <span className="text-red-500">*</span>
                {formData.jobId && (
                  <span className="text-xs text-blue-600 ml-2">
                    (已筛选该岗位的候选人，共 {filteredResumes.length} 人)
                  </span>
                )}
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={resumeSearch}
                  onChange={(e) => {
                    setResumeSearch(e.target.value);
                    setShowResumeDropdown(true);
                    if (!e.target.value) {
                      setFormData(prev => ({ ...prev, resumeId: '' }));
                      setSelectedResume(null);
                    }
                  }}
                  onFocus={() => setShowResumeDropdown(true)}
                  placeholder={formData.jobId ? '搜索候选人姓名...' : '请先选择岗位'}
                  disabled={!formData.jobId}
                  className="w-full px-4 py-3 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
                />
                <AppIcon className="fas fa-search absolute right-3 top-1/2 -translate-y-1/2 text-gray-400" />
                {selectedResume && (
                  <button
                    type="button"
                    onClick={() => {
                      setResumeSearch('');
                      setFormData(prev => ({ ...prev, resumeId: '' }));
                      setSelectedResume(null);
                    }}
                    className="absolute right-8 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <AppIcon className="fas fa-times" />
                  </button>
                )}
              </div>
              {showResumeDropdown && formData.jobId && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-auto">
                  {searchedResumes.length > 0 ? (
                    searchedResumes.map(resume => (
                      <div
                        key={resume.id}
                        onClick={() => handleSelectResume(resume)}
                        className={`px-4 py-3 cursor-pointer hover:bg-blue-50 ${
                          formData.resumeId === resume.id ? 'bg-blue-50 text-blue-600' : ''
                        }`}
                      >
                        <p className="font-medium">{resume.candidateName}</p>
                        <p className="text-sm text-gray-500">
                          匹配度: {resume.aiAnalysis?.matchDegree || '-'}
                          {resume.aiAnalysis?.score && ` | 评分: ${resume.aiAnalysis.score}`}
                        </p>
                      </div>
                    ))
                  ) : (
                    <div className="px-4 py-3 text-gray-500 text-center">
                      {filteredResumes.length === 0 ? (
                        <span>
                          该岗位暂无候选人，
                          <button
                            type="button"
                            onClick={() => navigate('/resume-upload')}
                            className="text-blue-600 hover:underline"
                          >
                            上传简历
                          </button>
                        </span>
                      ) : (
                        '未找到匹配的候选人'
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 面试时间 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                面试时间 <span className="text-red-500">*</span>
              </label>
              <input
                type="datetime-local"
                name="scheduledAt"
                value={formData.scheduledAt}
                onChange={handleInputChange}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>

            {/* 备注 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                备注
              </label>
              <textarea
                name="notes"
                value={formData.notes}
                onChange={handleInputChange}
                rows={4}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="可以填写面试地点、注意事项等..."
              />
            </div>

            {/* 错误信息 */}
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                <AppIcon className="fas fa-exclamation-circle mr-2" />
                {error}
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex items-center space-x-4">
              <button
                type="submit"
                disabled={isSubmitting || jobs.length === 0 || allResumes.length === 0}
                className="flex-1 bg-blue-600 text-white py-3 px-6 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <AppIcon className="fas fa-spinner fa-spin mr-2" />
                    创建中...
                  </>
                ) : (
                  <>
                    <AppIcon className="fas fa-calendar-plus mr-2" />
                    创建面试
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => navigate('/interview-manage')}
                disabled={isSubmitting}
                className="flex-1 bg-white border border-gray-300 text-gray-700 py-3 px-6 rounded-lg hover:bg-gray-50 transition-colors"
              >
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </Layout>
  );
}
