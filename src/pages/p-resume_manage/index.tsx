import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { resumesApi, jobsApi, Resume, Job } from '../../utils/api';
import { formatChinaDateTime, parseAPIDate } from '../../utils/date';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';


import AppIcon from '../../components/AppIcon';
type SortField = 'candidateName' | 'createdAt' | 'score' | 'matchDegree' | '';
type SortOrder = 'asc' | 'desc';

const ResumeManagePage: React.FC = () => {
  const navigate = useNavigate();
  
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [filteredResumes, setFilteredResumes] = useState<Resume[]>([]);
  const [sortField, setSortField] = useState<SortField>('score');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [selectedResumeIds, setSelectedResumeIds] = useState<string[]>([]);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [keywordSearch, setKeywordSearch] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [filterJobId, setFilterJobId] = useState<string>('');
  const [filterStartDate, setFilterStartDate] = useState<string>('');
  const [filterEndDate, setFilterEndDate] = useState<string>('');

  useEffect(() => {
    document.title = '简历管理 - 恒聘通';
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [resumesData, jobsData] = await Promise.all([
        resumesApi.getAll(),
        jobsApi.getAll()
      ]);
      setResumes(resumesData);
      setJobs(jobsData);
      setFilteredResumes(resumesData);
    } catch (err: any) {
      toast.error(err.message || '加载数据失败');
    } finally {
      setIsLoading(false);
    }
  };

  const loadResumes = loadData;

  useEffect(() => {
    const filtered = resumes.filter(resume => {
      // 关键词搜索
      const matchKeyword = resume.candidateName.toLowerCase().includes(keywordSearch.toLowerCase());
      
      // 岗位筛选
      const matchJob = !filterJobId || resume.jobId === filterJobId;
      
      // 日期范围筛选
      const resumeDate = parseAPIDate(resume.createdAt);
      const matchStartDate = !filterStartDate || (resumeDate && resumeDate >= new Date(filterStartDate));
      const matchEndDate = !filterEndDate || (resumeDate && resumeDate <= new Date(filterEndDate + 'T23:59:59'));
      
      return matchKeyword && matchJob && matchStartDate && matchEndDate;
    });

    if (sortField) {
      filtered.sort((a, b) => {
        let aValue: any;
        let bValue: any;

        if (sortField === 'createdAt') {
          aValue = parseAPIDate(a.createdAt)?.getTime() || 0;
          bValue = parseAPIDate(b.createdAt)?.getTime() || 0;
        } else if (sortField === 'score') {
          aValue = a.aiAnalysis?.score || 0;
          bValue = b.aiAnalysis?.score || 0;
        } else if (sortField === 'matchDegree') {
          aValue = a.aiAnalysis?.matchDegree || 0;
          bValue = b.aiAnalysis?.matchDegree || 0;
        } else {
          aValue = a[sortField];
          bValue = b[sortField];
        }

        if (sortOrder === 'asc') {
          return aValue > bValue ? 1 : -1;
        } else {
          return aValue < bValue ? 1 : -1;
        }
      });
    }

    setFilteredResumes(filtered);
    setCurrentPage(1);
  }, [keywordSearch, sortField, sortOrder, resumes, filterJobId, filterStartDate, filterEndDate]);

  const getCurrentPageResumes = () => {
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    return filteredResumes.slice(startIndex, endIndex);
  };

  const handleSortClick = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
  };

  const handleSelectAll = (checked: boolean) => {
    const currentPageResumes = getCurrentPageResumes();
    if (checked) {
      setSelectedResumeIds(currentPageResumes.map(resume => resume.id));
    } else {
      setSelectedResumeIds([]);
    }
  };

  const handleSelectResume = (resumeId: string, checked: boolean) => {
    if (checked) {
      setSelectedResumeIds([...selectedResumeIds, resumeId]);
    } else {
      setSelectedResumeIds(selectedResumeIds.filter(id => id !== resumeId));
    }
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setCurrentPage(1);
  };

  const handleBatchDelete = async () => {
    if (selectedResumeIds.length > 0 && !isDeleting) {
      const ok = await confirm({
        title: '批量删除简历',
        message: `确定要删除选中的 ${selectedResumeIds.length} 份简历吗？此操作不可撤销。`,
        danger: true,
        confirmText: '删除',
      });
      if (!ok) return;
      setIsDeleting(true);
      try {
        await Promise.all(selectedResumeIds.map(id => resumesApi.delete(id)));
        setSelectedResumeIds([]);
        toast.success('删除成功');
        loadResumes();
      } catch (err: any) {
        toast.error(err.message || '删除失败');
      } finally {
        setIsDeleting(false);
      }
    }
  };

  const handleBatchExport = () => {
    if (selectedResumeIds.length > 0) {
      const exportResumes = resumes.filter(resume => selectedResumeIds.includes(resume.id));
      const csvContent = [
        ['姓名', '上传时间', '标签'].join(','),
        ...exportResumes.map(resume => [
          resume.candidateName,
          formatChinaDateTime(resume.createdAt),
          resume.tags?.join(';') || ''
        ].join(','))
      ].join('\n');
      
      const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      
      link.setAttribute('href', url);
      link.setAttribute('download', `简历导出_${new Date().toLocaleDateString()}.csv`);
      link.style.visibility = 'hidden';
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      toast.success('导出成功');
    }
  };

  const handleUploadResume = () => {
    navigate('/resume-upload');
  };

  const handleViewDetail = (resumeId: string) => {
    navigate(`/resume-detail?resumeId=${resumeId}`);
  };

  const handleDeleteResume = async (resumeId: string) => {
    if (deletingId) return;
    const ok = await confirm({
      title: '删除简历',
      message: '确定要删除这份简历吗？',
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    setDeletingId(resumeId);
    try {
      await resumesApi.delete(resumeId);
      toast.success('删除成功');
      loadResumes();
    } catch (err: any) {
      toast.error(err.message || '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const isAllSelected = () => {
    const currentPageResumes = getCurrentPageResumes();
    return currentPageResumes.length > 0 && 
           currentPageResumes.every(resume => selectedResumeIds.includes(resume.id));
  };

  const isIndeterminate = () => {
    const currentPageResumes = getCurrentPageResumes();
    const selectedCount = currentPageResumes.filter(resume => selectedResumeIds.includes(resume.id)).length;
    return selectedCount > 0 && selectedCount < currentPageResumes.length;
  };

  const getDuplicateCount = (name: string) => {
    return resumes.filter(r => r.candidateName === name).length;
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

  const currentPageResumes = getCurrentPageResumes();
  const totalPages = Math.ceil(filteredResumes.length / pageSize);

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-file-alt text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">简历管理</h1>
                <p className="text-xs text-gray-400 mt-0.5">管理候选人简历，AI智能评分与匹配</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleBatchExport} disabled={selectedResumeIds.length === 0} className="px-3 py-[6px] text-xs border border-gray-200 rounded-lg text-gray-500 hover:text-blue-500 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                <AppIcon className="fas fa-download mr-1" />{selectedResumeIds.length > 0 ? `导出(${selectedResumeIds.length})` : '批量导出'}
              </button>
              <button onClick={handleBatchDelete} disabled={selectedResumeIds.length === 0 || isDeleting} className="px-3 py-[6px] text-xs border border-gray-200 rounded-lg text-gray-500 hover:text-red-500 hover:border-red-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                <AppIcon className="fas fa-trash mr-1" />{isDeleting ? '删除中…' : (selectedResumeIds.length > 0 ? `删除(${selectedResumeIds.length})` : '批量删除')}
              </button>
              <button onClick={handleUploadResume} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
                <AppIcon className="fas fa-upload mr-1" />上传简历
              </button>
            </div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-3 flex flex-wrap items-center gap-2">
            <div className="relative flex-shrink-0">
              <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 text-xs" />
              <input type="text" placeholder="搜索姓名..." value={keywordSearch} onChange={(e) => setKeywordSearch(e.target.value)} className="pl-9 pr-4 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-sm w-36 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all" />
            </div>
            <select value={filterJobId} onChange={(e) => setFilterJobId(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all">
              <option value="">全部岗位</option>
              {jobs.map(job => <option key={job.id} value={job.id}>{job.title} ({resumes.filter(r => r.jobId === job.id).length})</option>)}
            </select>
            <input type="date" aria-label="简历筛选开始日期" value={filterStartDate} onChange={(e) => setFilterStartDate(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all" />
            <span className="text-gray-300 text-xs">~</span>
            <input type="date" aria-label="简历筛选结束日期" value={filterEndDate} onChange={(e) => setFilterEndDate(e.target.value)} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all" />
            <select value={`${sortField}-${sortOrder}`} onChange={(e) => { const [field, order] = e.target.value.split('-') as [SortField, SortOrder]; setSortField(field); setSortOrder(order); }} className="px-3 py-[6px] border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all">
              <option value="score-desc">AI评分：高→低</option>
              <option value="score-asc">AI评分：低→高</option>
              <option value="matchDegree-desc">匹配度：高→低</option>
              <option value="matchDegree-asc">匹配度：低→高</option>
              <option value="createdAt-desc">时间：最新</option>
              <option value="createdAt-asc">时间：最早</option>
              <option value="candidateName-asc">姓名：A→Z</option>
              <option value="candidateName-desc">姓名：Z→A</option>
            </select>
            {(filterJobId || filterStartDate || filterEndDate || keywordSearch) && (
              <>
                <span className="text-xs text-blue-500 font-medium"><span className="font-bold">{filteredResumes.length}</span>/{resumes.length}</span>
                <button onClick={() => { setFilterJobId(''); setFilterStartDate(''); setFilterEndDate(''); setKeywordSearch(''); }} className="text-xs text-red-400 hover:text-red-600 transition-colors"><AppIcon className="fas fa-times-circle" /></button>
              </>
            )}
            <div className="flex-1"></div>
            <div className="text-xs text-gray-400">共 <span className="font-medium text-gray-600">{filteredResumes.length}</span> 份简历</div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full hrm-table">
              <thead>
                <tr className="border-y border-gray-100">
                  <th className="px-4 py-2.5 text-left bg-gray-50/80 w-10">
                    <input type="checkbox" aria-label="选择当前页简历" checked={isAllSelected()} ref={(input) => { if (input) input.indeterminate = isIndeterminate(); }} onChange={(e) => handleSelectAll(e.target.checked)} className="rounded border-gray-300 w-3.5 h-3.5" />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSortClick('candidateName')}>
                    姓名 <AppIcon className={`fas ${sortField === 'candidateName' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">应聘岗位</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">联系方式</th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSortClick('score')}>
                    AI评分 <AppIcon className={`fas ${sortField === 'score' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSortClick('matchDegree')}>
                    匹配度 <AppIcon className={`fas ${sortField === 'matchDegree' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSortClick('createdAt')}>
                    上传时间 <AppIcon className={`fas ${sortField === 'createdAt' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                </tr>
              </thead>
              <tbody>
                {currentPageResumes.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400">
                      <AppIcon className="fas fa-inbox text-2xl mb-2 block text-gray-300" />
                      暂无简历数据
                    </td>
                  </tr>
                ) : currentPageResumes.map((resume) => {
                  const job = jobs.find(j => j.id === resume.jobId);
                  const score = resume.aiAnalysis?.score || 0;
                  const match = resume.aiAnalysis?.matchDegree || 0;
                  return (
                    <tr key={resume.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors cursor-pointer" onClick={() => handleViewDetail(resume.id)}>
                      <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" aria-label={`选择简历 ${resume.candidateName}`} checked={selectedResumeIds.includes(resume.id)} onChange={(e) => handleSelectResume(resume.id, e.target.checked)} className="rounded border-gray-300 w-3.5 h-3.5" />
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[13px] font-medium text-gray-800">{resume.candidateName}</span>
                          {getDuplicateCount(resume.candidateName) > 1 && <span className="status-badge status-pending text-[10px] py-0">重名</span>}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-[13px] text-gray-500">{job?.title || <span className="text-gray-300 italic">已删除</span>}</td>
                      <td className="px-4 py-2.5">
                        <div className="text-[12px] text-gray-500">{resume.email || resume.phone || '-'}</div>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`text-[13px] font-bold ${score >= 85 ? 'text-green-500' : score >= 70 ? 'text-orange-500' : 'text-gray-400'}`}>{score}<span className="text-[10px] text-gray-400 font-normal ml-0.5">分</span></span>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${match >= 80 ? 'bg-green-400' : match >= 60 ? 'bg-blue-400' : 'bg-gray-300'}`} style={{ width: `${match}%` }}></div>
                          </div>
                          <span className="text-[12px] text-gray-500">{match}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-[12px] text-gray-400">{formatChinaDateTime(resume.createdAt)}</td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <button onClick={() => handleViewDetail(resume.id)} className="text-xs text-gray-500 hover:text-blue-600 mr-2 transition-colors">
                          <AppIcon className="fas fa-eye text-[11px]" />详情
                        </button>
                        <button onClick={() => handleDeleteResume(resume.id)} disabled={deletingId === resume.id} className="text-xs text-red-400 hover:text-red-600 transition-colors disabled:opacity-40">
                          <AppIcon className="fas fa-trash text-[11px]" />{deletingId === resume.id ? '删除中…' : '删除'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-5 py-3 border-t border-gray-100">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>每页</span>
                <select value={pageSize} onChange={(e) => handlePageSizeChange(parseInt(e.target.value))} className="border border-gray-200 rounded-md px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                  <option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option>
                </select>
                <span>条，共 {filteredResumes.length} 条</span>
              </div>
              <div className="flex items-center gap-1">
                <button aria-label="上一页简历" onClick={() => handlePageChange(currentPage - 1)} disabled={currentPage === 1} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
                  <AppIcon className="fas fa-chevron-left text-[10px]" />
                </button>
                {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                  const start = Math.max(1, Math.min(currentPage - 2, totalPages - 4));
                  const page = start + i;
                  if (page > totalPages) return null;
                  return <button key={page} onClick={() => handlePageChange(page)} className={`w-7 h-7 flex items-center justify-center rounded-md text-xs transition-colors ${page === currentPage ? 'bg-blue-500 text-white' : 'border border-gray-200 text-gray-600 hover:bg-gray-50'}`}>{page}</button>;
                })}
                <button aria-label="下一页简历" onClick={() => handlePageChange(currentPage + 1)} disabled={currentPage === totalPages || totalPages === 0} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
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

export default ResumeManagePage;
