import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { interviewsApi, jobsApi, resumesApi, Interview, Job, Resume } from '../../utils/api';
import { formatBusinessDateTime } from '../../utils/businessTime';
import { getStatusBadgeClass, getStatusLabel } from '../../utils/status';


import AppIcon from '../../components/AppIcon';
const InterviewManagePage: React.FC = () => {
  const navigate = useNavigate();
  
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [filteredInterviews, setFilteredInterviews] = useState<Interview[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [jobFilter, setJobFilter] = useState('');
  const [resumeFilter, setResumeFilter] = useState('');
  const [creatorFilter, setCreatorFilter] = useState('');
  const [scheduledFrom, setScheduledFrom] = useState('');
  const [scheduledTo, setScheduledTo] = useState('');
  const [analysisFilter, setAnalysisFilter] = useState('');
  const [selectedInterviews, setSelectedInterviews] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    document.title = '面试管理 - 恒聘通';
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [interviewsData, jobsData, resumesData] = await Promise.all([
        interviewsApi.getAll(),
        jobsApi.getAll(),
        resumesApi.getAll()
      ]);
      setInterviews(interviewsData);
      setJobs(jobsData);
      setResumes(resumesData);
      setFilteredInterviews(interviewsData);
      setLoadError(false);
    } catch (err) {
      console.error('加载数据失败', err);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const filtered = interviews.filter(interview => {
      const resume = resumes.find(r => r.id === interview.resumeId);
      const job = jobs.find(j => j.id === interview.jobId);
      const scheduledDate = interview.scheduledAt ? new Date(interview.scheduledAt) : null;
      
      const matchesSearch = !searchTerm || 
        resume?.candidateName.toLowerCase().includes(searchTerm.toLowerCase()) ||
        job?.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        interview.notes?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        interview.createdByName?.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchesStatus = !statusFilter || interview.status === statusFilter;
      const matchesJob = !jobFilter || interview.jobId === jobFilter;
      const matchesResume = !resumeFilter || interview.resumeId === resumeFilter;
      const matchesCreator = !creatorFilter || interview.createdByName === creatorFilter;
      const matchesFrom = !scheduledFrom || (scheduledDate && scheduledDate >= new Date(`${scheduledFrom}T00:00:00`));
      const matchesTo = !scheduledTo || (scheduledDate && scheduledDate <= new Date(`${scheduledTo}T23:59:59`));
      const matchesAnalysis = !analysisFilter
        || (analysisFilter === 'analyzed' && !!interview.aiAnalysis)
        || (analysisFilter === 'not_analyzed' && !interview.aiAnalysis)
        || (analysisFilter === 'has_room' && !!interview.roomId);
      
      return matchesSearch && matchesStatus && matchesJob && matchesResume && matchesCreator && matchesFrom && matchesTo && matchesAnalysis;
    });

    setFilteredInterviews(filtered);
    setCurrentPage(1);
  }, [searchTerm, statusFilter, jobFilter, resumeFilter, creatorFilter, scheduledFrom, scheduledTo, analysisFilter, interviews, jobs, resumes]);

  const totalItems = filteredInterviews.length;
  const totalPages = Math.ceil(totalItems / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const currentInterviews = filteredInterviews.slice(startIndex, endIndex);

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedInterviews(currentInterviews.map(i => i.id));
    } else {
      setSelectedInterviews([]);
    }
  };

  const handleSelectInterview = (id: string, checked: boolean) => {
    if (checked) {
      setSelectedInterviews(prev => [...prev, id]);
    } else {
      setSelectedInterviews(prev => prev.filter(i => i !== id));
    }
  };

  const handleBatchDelete = async () => {
    if (selectedInterviews.length === 0) {
      toast.warning('请先选择要删除的面试记录');
      return;
    }
    if (isDeleting) return;

    const ok = await confirm({
      title: '批量删除面试',
      message: `确定要删除选中的 ${selectedInterviews.length} 条面试记录吗？`,
      danger: true,
      confirmText: '删除',
    });
    if (ok) {
      setIsDeleting(true);
      try {
        await Promise.all(selectedInterviews.map(id => interviewsApi.delete(id)));
        toast.success('删除成功');
        setSelectedInterviews([]);
        loadData();
      } catch (err: any) {
        toast.error(err?.message || '删除失败');
      } finally {
        setIsDeleting(false);
      }
    }
  };

  const handleDeleteInterview = async (id: string) => {
    if (deletingId) return;
    const ok = await confirm({
      title: '删除面试',
      message: '确定要删除这条面试记录吗？',
      danger: true,
      confirmText: '删除',
    });
    if (ok) {
      setDeletingId(id);
      try {
        await interviewsApi.delete(id);
        toast.success('删除成功');
        loadData();
      } catch (err: any) {
        toast.error(err?.message || '删除失败');
      } finally {
        setDeletingId(null);
      }
    }
  };

  const getJobName = (jobId: string | null | undefined) => {
    if (!jobId) return '岗位已删除';
    return jobs.find(j => j.id === jobId)?.title || '岗位已删除';
  };

  const getCandidateName = (resumeId: string | null | undefined) => {
    if (!resumeId) return '简历已删除';
    return resumes.find(r => r.id === resumeId)?.candidateName || '简历已删除';
  };

  const generatePageNumbers = () => {
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    const endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

    if (endPage - startPage + 1 < maxVisiblePages) {
      startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    const pages = [];
    for (let i = startPage; i <= endPage; i++) {
      pages.push(i);
    }
    return pages;
  };

  const isAllSelected = currentInterviews.length > 0 && selectedInterviews.length === currentInterviews.length;
  const isIndeterminate = selectedInterviews.length > 0 && selectedInterviews.length < currentInterviews.length;

  const scheduledCount = interviews.filter(i => i.status === 'scheduled').length;
  const inProgressCount = interviews.filter(i => i.status === 'in_progress').length;
  const completedCount = interviews.filter(i => i.status === 'completed').length;
  const cancelledCount = interviews.filter(i => i.status === 'cancelled').length;
  const creatorOptions = Array.from(new Set(interviews.map(i => i.createdByName || '').filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const activeFilterCount = [searchTerm, statusFilter, jobFilter, resumeFilter, creatorFilter, scheduledFrom, scheduledTo, analysisFilter].filter(Boolean).length;
  const resetFilters = () => {
    setSearchTerm('');
    setStatusFilter('');
    setJobFilter('');
    setResumeFilter('');
    setCreatorFilter('');
    setScheduledFrom('');
    setScheduledTo('');
    setAnalysisFilter('');
  };

  if (isLoading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64">
          <AppIcon className="fas fa-spinner fa-spin text-2xl text-blue-400" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Stat Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {[
            { label: '面试总数', value: interviews.length, icon: 'fa-users', bg: 'bg-blue-50', color: 'text-blue-500' },
            { label: '已安排', value: scheduledCount, icon: 'fa-calendar-check', bg: 'bg-cyan-50', color: 'text-cyan-500' },
            { label: '进行中', value: inProgressCount, icon: 'fa-spinner', bg: 'bg-indigo-50', color: 'text-indigo-500' },
            { label: '已完成', value: completedCount, icon: 'fa-check-circle', bg: 'bg-green-50', color: 'text-green-500' },
            { label: '已取消', value: cancelledCount, icon: 'fa-times-circle', bg: 'bg-gray-100', color: 'text-gray-500' },
          ].map((card) => (
            <div key={card.label} className="stat-card bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs text-gray-400">{card.label}</span>
                <div className={`w-8 h-8 rounded-lg ${card.bg} ${card.color} flex items-center justify-center`}><AppIcon className={`fas ${card.icon} text-sm`} /></div>
              </div>
              <div className="text-2xl font-bold text-gray-900">{card.value}</div>
            </div>
          ))}
        </div>

        {/* Table Card */}
        <div className="bg-white rounded-xl border border-gray-100">
          {/* Toolbar */}
          <div className="px-5 py-3 border-b border-gray-100 space-y-3">
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
              <div className="flex items-center gap-2">
                <div className="flex items-center bg-gray-50 rounded-lg p-0.5">
                  {[
                    { label: '全部', value: '', count: interviews.length },
                    { label: '已安排', value: 'scheduled', count: scheduledCount },
                    { label: '进行中', value: 'in_progress', count: inProgressCount },
                    { label: '已完成', value: 'completed', count: completedCount },
                    { label: '已取消', value: 'cancelled', count: cancelledCount },
                  ].map((tab) => (
                    <button key={tab.value} onClick={() => setStatusFilter(tab.value)} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${statusFilter === tab.value ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                      {tab.label} <span className="text-gray-400 ml-0.5">({tab.count})</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="relative">
                  <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 text-xs" />
                  <input type="text" placeholder="候选人/岗位/备注..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="pl-9 pr-4 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-sm w-52 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all" />
                </div>
                <button onClick={handleBatchDelete} disabled={selectedInterviews.length === 0 || isDeleting} className="px-3 py-[6px] text-xs border border-gray-200 rounded-lg text-gray-500 hover:text-red-500 hover:border-red-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                  <AppIcon className="fas fa-trash mr-1" />{isDeleting ? '删除中…' : (selectedInterviews.length > 0 ? `删除(${selectedInterviews.length})` : '批量删除')}
                </button>
                <button onClick={() => navigate('/interview-create')} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
                  <AppIcon className="fas fa-plus mr-1" />新建面试
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2">
              <select value={jobFilter} onChange={(e) => setJobFilter(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all">
                <option value="">全部岗位</option>
                {jobs.map(job => <option key={job.id} value={job.id}>{job.title}</option>)}
              </select>
              <select value={resumeFilter} onChange={(e) => setResumeFilter(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all">
                <option value="">全部候选人</option>
                {resumes.map(resume => <option key={resume.id} value={resume.id}>{resume.candidateName}</option>)}
              </select>
              <select value={creatorFilter} onChange={(e) => setCreatorFilter(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all">
                <option value="">全部创建人</option>
                {creatorOptions.map(name => <option key={name} value={name}>{name}</option>)}
              </select>
              <select value={analysisFilter} onChange={(e) => setAnalysisFilter(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all">
                <option value="">全部分析状态</option>
                <option value="analyzed">已AI分析</option>
                <option value="not_analyzed">未AI分析</option>
                <option value="has_room">有面试房间</option>
              </select>
              <input type="date" value={scheduledFrom} onChange={(e) => setScheduledFrom(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all" />
              <input type="date" value={scheduledTo} onChange={(e) => setScheduledTo(e.target.value)} className="px-2.5 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all" />
              <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-2.5 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
              </button>
            </div>
            <div className="text-[11px] text-gray-400">
              当前筛选 <span className="font-medium text-gray-600">{filteredInterviews.length}</span> / {interviews.length} 场面试
            </div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full hrm-table">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="px-4 py-2.5 text-left bg-gray-50/80 w-10">
                    <input type="checkbox" checked={isAllSelected} ref={(input) => { if (input) input.indeterminate = isIndeterminate; }} onChange={(e) => handleSelectAll(e.target.checked)} className="rounded border-gray-300 focus:ring-blue-500 w-3.5 h-3.5" />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">候选人</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">应聘岗位</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">面试时间</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">状态</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作人</th>
                  <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                </tr>
              </thead>
              <tbody>
                {currentInterviews.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400">
                      <AppIcon className="fas fa-calendar-times text-2xl mb-2 block text-gray-300" />
                      {loadError ? '数据加载失败' : '暂无面试记录'}
                      {loadError && <button onClick={loadData} className="ml-2 text-blue-500 hover:underline">重试</button>}
                    </td>
                  </tr>
                ) : currentInterviews.map(interview => (
                  <tr key={interview.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                    <td className="px-4 py-2.5">
                      <input type="checkbox" checked={selectedInterviews.includes(interview.id)} onChange={(e) => handleSelectInterview(interview.id, e.target.checked)} className="rounded border-gray-300 focus:ring-blue-500 w-3.5 h-3.5" />
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="text-[13px] font-medium text-gray-800">{getCandidateName(interview.resumeId)}</span>
                    </td>
                    <td className="px-4 py-2.5 text-[13px] text-gray-500">{getJobName(interview.jobId)}</td>
                    <td className="px-4 py-2.5 text-[13px] text-gray-500">{formatBusinessDateTime(interview.scheduledAt)}</td>
                    <td className="px-4 py-2.5">
                      <span className={getStatusBadgeClass(interview.status)}>{getStatusLabel(interview.status)}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-[12px] text-gray-500">{interview.createdByName || '-'}</div>
                    </td>
                    <td className="px-4 py-2.5 text-right whitespace-nowrap">
                      <button onClick={() => navigate(`/interview-detail?interviewId=${interview.id}`)} className="text-xs text-gray-500 hover:text-blue-600 mr-2 transition-colors">
                        <AppIcon className="fas fa-eye text-[11px]" />详情
                      </button>
                      <button onClick={() => handleDeleteInterview(interview.id)} disabled={deletingId === interview.id} className="text-xs text-red-400 hover:text-red-600 transition-colors disabled:opacity-40">
                        <AppIcon className="fas fa-trash text-[11px]" />{deletingId === interview.id ? '删除中…' : '删除'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-5 py-3 border-t border-gray-100">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>每页</span>
                <select value={pageSize} onChange={(e) => { setPageSize(parseInt(e.target.value)); setCurrentPage(1); }} className="border border-gray-200 rounded-md px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                  <option value="10">10</option><option value="20">20</option><option value="50">50</option>
                </select>
                <span>条，共 {totalItems} 条</span>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => setCurrentPage(currentPage - 1)} disabled={currentPage === 1} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
                  <AppIcon className="fas fa-chevron-left text-[10px]" />
                </button>
                {generatePageNumbers().map(page => (
                  <button key={page} onClick={() => setCurrentPage(page)} className={`w-7 h-7 flex items-center justify-center rounded-md text-xs transition-colors ${page === currentPage ? 'bg-blue-500 text-white' : 'border border-gray-200 text-gray-600 hover:bg-gray-50'}`}>{page}</button>
                ))}
                <button onClick={() => setCurrentPage(currentPage + 1)} disabled={currentPage === totalPages || totalPages === 0} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
                  <AppIcon className="fas fa-chevron-right text-[10px]" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default InterviewManagePage;
