/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import React, { useState, useEffect, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { jobsApi, Job as ApiJob } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';


import AppIcon from '../../components/AppIcon';
const JobManagePage: React.FC = () => {
  const [searchParams] = useSearchParams();
  
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [jobs, setJobs] = useState<ApiJob[]>([]);
  const [filteredJobs, setFilteredJobs] = useState<ApiJob[]>([]);
  const [sortField, setSortField] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [selectedJobs, setSelectedJobs] = useState<string[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState(() => searchParams.get('status') || '');
  const [departmentFilter, setDepartmentFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [levelFilter, setLevelFilter] = useState('');
  const [locationFilter, setLocationFilter] = useState('');
  const [employmentTypeFilter, setEmploymentTypeFilter] = useState('');
  const [createdFrom, setCreatedFrom] = useState('');
  const [createdTo, setCreatedTo] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const getUniqueOptions = (field: keyof ApiJob) => Array.from(new Set(
    jobs.map(job => String(job[field] || '').trim()).filter(Boolean)
  )).sort((a, b) => a.localeCompare(b, 'zh-CN'));

  const filterOptions = useMemo(() => ({
    departments: getUniqueOptions('department'),
    categories: getUniqueOptions('category'),
    levels: getUniqueOptions('level'),
    locations: getUniqueOptions('location'),
    employmentTypes: getUniqueOptions('employmentType'),
  }), [jobs]);

  const activeFilterCount = [
    searchTerm,
    statusFilter,
    departmentFilter,
    categoryFilter,
    levelFilter,
    locationFilter,
    employmentTypeFilter,
    createdFrom,
    createdTo,
  ].filter(Boolean).length;

  useEffect(() => {
    document.title = '岗位管理 - 恒聘通';
    loadJobs();
  }, []);

  const loadJobs = async () => {
    try {
      const data = await jobsApi.getAll();
      setJobs(data);
      setFilteredJobs(data);
    } catch (err: any) {
      toast.error(err.message || '加载岗位失败');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const filtered = jobs.filter(job => {
      const keyword = searchTerm.trim().toLowerCase();
      const searchable = [
        job.title,
        job.department,
        job.category,
        job.level,
        job.location,
        job.employmentType,
        job.salaryRange,
        job.description,
        job.createdByName,
      ].filter(Boolean).join(' ').toLowerCase();
      const createdDate = job.createdAt ? new Date(job.createdAt) : null;
      const matchesSearch = !keyword || searchable.includes(keyword);
      const matchesStatus = !statusFilter || job.status === statusFilter;
      const matchesDepartment = !departmentFilter || job.department === departmentFilter;
      const matchesCategory = !categoryFilter || job.category === categoryFilter;
      const matchesLevel = !levelFilter || job.level === levelFilter;
      const matchesLocation = !locationFilter || job.location === locationFilter;
      const matchesEmploymentType = !employmentTypeFilter || job.employmentType === employmentTypeFilter;
      const matchesCreatedFrom = !createdFrom || (createdDate && createdDate >= new Date(`${createdFrom}T00:00:00`));
      const matchesCreatedTo = !createdTo || (createdDate && createdDate <= new Date(`${createdTo}T23:59:59`));
      return matchesSearch && matchesStatus && matchesDepartment && matchesCategory && matchesLevel && matchesLocation && matchesEmploymentType && matchesCreatedFrom && matchesCreatedTo;
    });

    if (sortField) {
      filtered.sort((a, b) => {
        let aValue: any = a[sortField as keyof ApiJob];
        let bValue: any = b[sortField as keyof ApiJob];

        if (sortField === 'createdAt') {
          aValue = new Date(a.createdAt);
          bValue = new Date(b.createdAt);
        }

        const left = aValue ?? '';
        const right = bValue ?? '';
        if (sortOrder === 'asc') return left > right ? 1 : -1;
        return left < right ? 1 : -1;
      });
    }

    setFilteredJobs(filtered);
    setCurrentPage(1);
  }, [searchTerm, statusFilter, departmentFilter, categoryFilter, levelFilter, locationFilter, employmentTypeFilter, createdFrom, createdTo, sortField, sortOrder, jobs]);

  const resetFilters = () => {
    setSearchTerm('');
    setStatusFilter('');
    setDepartmentFilter('');
    setCategoryFilter('');
    setLevelFilter('');
    setLocationFilter('');
    setEmploymentTypeFilter('');
    setCreatedFrom('');
    setCreatedTo('');
  };

  const totalItems = filteredJobs.length;
  const totalPages = Math.ceil(totalItems / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = startIndex + pageSize;
  const currentJobs = filteredJobs.slice(startIndex, endIndex);

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedJobs(currentJobs.map(job => job.id));
    } else {
      setSelectedJobs([]);
    }
  };

  const handleSelectJob = (jobId: string, checked: boolean) => {
    if (checked) {
      setSelectedJobs(prev => [...prev, jobId]);
    } else {
      setSelectedJobs(prev => prev.filter(id => id !== jobId));
    }
  };

  const handleSort = (field: string) => {
    if (sortField === field) {
      setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const handleBatchDelete = async () => {
    if (selectedJobs.length === 0) {
      toast.warning('请先选择要删除的岗位');
      return;
    }
    
    const ok = await confirm({
      title: '批量删除岗位',
      message: `确定要删除选中的 ${selectedJobs.length} 个岗位吗？此操作不可撤销。`,
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    
    try {
      await Promise.all(selectedJobs.map(id => jobsApi.delete(id)));
      toast.success('删除成功');
      setSelectedJobs([]);
      loadJobs();
    } catch (err: any) {
      toast.error(err.message || '删除失败');
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    const ok = await confirm({
      title: '删除岗位',
      message: '确定要删除这个岗位吗？关联的简历和面试数据也会被删除。',
      danger: true,
      confirmText: '删除',
    });
    if (!ok) return;
    
    try {
      await jobsApi.delete(jobId);
      toast.success('删除成功');
      loadJobs();
    } catch (err: any) {
      toast.error(err.message || '删除失败');
    }
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

  const isAllSelected = currentJobs.length > 0 && selectedJobs.length === currentJobs.length;
  const isIndeterminate = selectedJobs.length > 0 && selectedJobs.length < currentJobs.length;

  const openCount = jobs.filter(j => j.status === 'open').length;
  const closedCount = jobs.filter(j => j.status === 'closed').length;

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
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: '岗位总数', value: jobs.length, icon: 'fa-briefcase', bg: 'bg-blue-50', color: 'text-blue-500' },
            { label: '在招岗位', value: openCount, icon: 'fa-bullhorn', bg: 'bg-green-50', color: 'text-green-500' },
            { label: '已关闭', value: closedCount, icon: 'fa-ban', bg: 'bg-gray-100', color: 'text-gray-500' },
            { label: '本周新增', value: jobs.filter(j => { const d = new Date(j.createdAt); const now = new Date(); return (now.getTime() - d.getTime()) < 7 * 86400000; }).length, icon: 'fa-chart-line', bg: 'bg-purple-50', color: 'text-purple-500' },
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
                {/* Status Tabs */}
                <div className="flex items-center bg-gray-50 rounded-lg p-0.5">
                  {[
                    { label: '全部', value: '', count: jobs.length },
                    { label: '在招', value: 'open', count: openCount },
                    { label: '已关闭', value: 'closed', count: closedCount },
                  ].map((tab) => (
                    <button key={tab.value} onClick={() => setStatusFilter(tab.value)} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${statusFilter === tab.value ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                      {tab.label} <span className="text-gray-400 ml-0.5">({tab.count})</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <SearchInput value={searchTerm} onChange={setSearchTerm} placeholder="岗位/部门/地点..." className="w-60" />
                <button onClick={handleBatchDelete} disabled={selectedJobs.length === 0} className="px-3 py-[6px] text-xs border border-gray-200 rounded-lg text-gray-500 hover:text-red-500 hover:border-red-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                  <AppIcon className="fas fa-trash mr-1" />{selectedJobs.length > 0 ? `删除(${selectedJobs.length})` : '批量删除'}
                </button>
                <Link to="/job-create" className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 transition-colors shadow-sm">
                  <AppIcon className="fas fa-plus mr-1" />新建岗位
                </Link>
              </div>
            </div>
            <div className="hpt-filter-surface p-3">
              <div className="hpt-filter-grid">
                <FilterField label="部门" type="combo" value={departmentFilter} onChange={setDepartmentFilter} options={toFilterOptions(filterOptions.departments)} />
                <FilterField label="分类" type="combo" value={categoryFilter} onChange={setCategoryFilter} options={toFilterOptions(filterOptions.categories)} />
                <FilterField label="职级" type="select" value={levelFilter} onChange={setLevelFilter} options={toFilterOptions(filterOptions.levels)} />
                <FilterField label="地点" type="combo" value={locationFilter} onChange={setLocationFilter} options={toFilterOptions(filterOptions.locations)} />
                <FilterField label="用工" type="select" value={employmentTypeFilter} onChange={setEmploymentTypeFilter} options={toFilterOptions(filterOptions.employmentTypes)} />
                <FilterField label="创建时间" type="date-range" value={{ from: createdFrom, to: createdTo }} onChange={(next) => { setCreatedFrom(next.from || ''); setCreatedTo(next.to || ''); }} />
                <div className="hpt-filter-field flex items-end">
                  <button onClick={resetFilters} disabled={activeFilterCount === 0} className="hpt-control px-3 text-gray-500 hover:text-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                    <AppIcon className="fas fa-rotate-left mr-1.5" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
                  </button>
                </div>
              </div>
            </div>
            <div className="text-[11px] text-gray-400">
              当前筛选 <span className="font-medium text-gray-600">{filteredJobs.length}</span> / {jobs.length} 个岗位
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
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('title')}>
                    岗位名称 <AppIcon className={`fas ${sortField === 'title' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('department')}>
                    部门 <AppIcon className={`fas ${sortField === 'department' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('category')}>
                    分类/职级 <AppIcon className={`fas ${sortField === 'category' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('location')}>
                    地点/用工 <AppIcon className={`fas ${sortField === 'location' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('status')}>
                    状态 <AppIcon className={`fas ${sortField === 'status' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80 cursor-pointer hover:text-gray-600" onClick={() => handleSort('createdAt')}>
                    创建时间 <AppIcon className={`fas ${sortField === 'createdAt' ? (sortOrder === 'asc' ? 'fa-sort-up' : 'fa-sort-down') : 'fa-sort'} ml-0.5 text-gray-300`} />
                  </th>
                  <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作人</th>
                  <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">操作</th>
                </tr>
              </thead>
              <tbody>
                {currentJobs.map(job => (
                  <tr key={job.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                    <td className="px-4 py-2.5">
                      <input type="checkbox" checked={selectedJobs.includes(job.id)} onChange={(e) => handleSelectJob(job.id, e.target.checked)} className="rounded border-gray-300 focus:ring-blue-500 w-3.5 h-3.5" />
                    </td>
                    <td className="px-4 py-2.5">
                      <Link to={`/job-detail?jobId=${job.id}`} className="text-[13px] font-medium text-gray-800 hover:text-blue-600 transition-colors">{job.title}</Link>
                      {job.salaryRange && <div className="text-[11px] text-gray-400 mt-0.5">{job.salaryRange}</div>}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-[13px] text-gray-600">{job.department || '-'}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-[13px] text-gray-600">{job.category || '-'}</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">{job.level || '-'}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-[13px] text-gray-600">{job.location || '-'}</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">{job.employmentType || '-'}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`status-badge ${job.status === 'open' ? 'status-active' : 'status-inactive'}`}>
                        {job.status === 'open' ? '招聘中' : '已关闭'}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[13px] text-gray-500">
                      {new Date(job.createdAt).toLocaleDateString('zh-CN')}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="text-[12px] text-gray-500">{job.createdByName || '-'}</div>
                    </td>
                    <td className="px-4 py-2.5 text-right whitespace-nowrap">
                      <Link to={`/job-detail?jobId=${job.id}`} className="text-xs text-gray-500 hover:text-blue-600 mr-2 transition-colors">
                        <AppIcon className="fas fa-eye text-[11px]" />详情
                      </Link>
                      <button onClick={() => handleDeleteJob(job.id)} className="text-xs text-red-400 hover:text-red-600 transition-colors">
                        <AppIcon className="fas fa-trash text-[11px]" />删除
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
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                </select>
                <span>条，共 {totalItems} 条</span>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => handlePageChange(currentPage - 1)} disabled={currentPage === 1} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
                  <AppIcon className="fas fa-chevron-left text-[10px]" />
                </button>
                {generatePageNumbers().map(page => (
                  <button key={page} onClick={() => handlePageChange(page)} className={`w-7 h-7 flex items-center justify-center rounded-md text-xs transition-colors ${page === currentPage ? 'bg-blue-500 text-white' : 'border border-gray-200 text-gray-600 hover:bg-gray-50'}`}>{page}</button>
                ))}
                <button onClick={() => handlePageChange(currentPage + 1)} disabled={currentPage === totalPages || totalPages === 0} className="w-7 h-7 flex items-center justify-center border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs text-gray-500">
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

export default JobManagePage;
