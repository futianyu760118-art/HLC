// @ts-nocheck
import React, { useEffect, useState, useRef } from 'react';
import { Layout } from '../../components/Layout';
import { hrmApi } from '../../utils/api';
import { getStatusBadgeClass, getStatusLabel } from '../../utils/status';
import { Chart, registerables } from 'chart.js';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
Chart.register(...registerables);

const gradeColors: Record<string, string> = {
  S: 'text-purple-600 bg-purple-50',
  A: 'text-blue-600 bg-blue-50',
  B: 'text-green-600 bg-green-50',
  C: 'text-orange-600 bg-orange-50',
  D: 'text-red-600 bg-red-50',
};

export default function PerformanceReviewPage() {
  const [reviews, setReviews] = useState<any[]>([]);
  const [cycles, setCycles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedReview, setSelectedReview] = useState<any | null>(null);
  const [keyword, setKeyword] = useState('');
  const [filterEmployee, setFilterEmployee] = useState('');
  const [filterCycle, setFilterCycle] = useState('');
  const [filterGrade, setFilterGrade] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [minScore, setMinScore] = useState('');
  const [maxScore, setMaxScore] = useState('');
  const radarRef = useRef<HTMLCanvasElement>(null);
  const radarInstance = useRef<Chart | null>(null);

  useEffect(() => {
    document.title = '绩效评估 - 恒聘通HRM';
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [reviewsData, cyclesData] = await Promise.all([
        hrmApi.list('performance-reviews'),
        hrmApi.list('performance-cycles'),
      ]);
      setReviews(reviewsData);
      setCycles(cyclesData);
    } catch (error) {
      console.error('加载绩效数据失败', error);
    } finally {
      setLoading(false);
    }
  };

  // Radar chart for selected review
  useEffect(() => {
    if (!selectedReview || !radarRef.current) return;
    if (radarInstance.current) radarInstance.current.destroy();
    const ctx = radarRef.current.getContext('2d');
    if (!ctx) return;
    const selfScore = selectedReview.selfScore || 0;
    const managerScore = selectedReview.managerScore || 0;
    const finalScore = selectedReview.finalScore || 0;
    // Simulate dimension scores based on available data
    const dims = [
      Math.min(100, selfScore * 1.1),
      Math.min(100, managerScore * 1.05),
      Math.min(100, finalScore),
      Math.min(100, (selfScore + managerScore) / 2),
      Math.min(100, finalScore * 0.95),
    ];
    radarInstance.current = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: ['目标达成', '专业能力', '团队协作', '学习成长', '文化匹配'],
        datasets: [{
          label: '评估得分',
          data: dims,
          backgroundColor: 'rgba(59,130,246,0.15)',
          borderColor: '#3b82f6',
          borderWidth: 2,
          pointBackgroundColor: '#3b82f6',
          pointRadius: 4,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: { r: { beginAtZero: true, max: 100, ticks: { stepSize: 20, font: { size: 10 } }, grid: { color: '#e5e7eb' }, pointLabels: { font: { size: 11 } } } },
        plugins: { legend: { display: false } },
      },
    });
    return () => { radarInstance.current?.destroy(); };
  }, [selectedReview]);

  const filteredReviews = reviews.filter(r => {
    if (keyword) {
      const text = `${r.employeeName || ''} ${r.cycleName || ''} ${r.result || ''} ${r.remark || ''}`.toLowerCase();
      if (!text.includes(keyword.toLowerCase())) return false;
    }
    if (filterEmployee && r.employeeId !== filterEmployee) return false;
    if (filterCycle && r.cycleId !== filterCycle) return false;
    if (filterGrade && r.grade !== filterGrade) return false;
    if (filterStatus && r.status !== filterStatus) return false;
    const score = Number(r.finalScore);
    if (minScore && (Number.isNaN(score) || score < Number(minScore))) return false;
    if (maxScore && (Number.isNaN(score) || score > Number(maxScore))) return false;
    return true;
  });
  const employeeOptions = Array.from(new Map(reviews.filter((r) => r.employeeId).map((r) => [r.employeeId, r.employeeName || r.employeeId])).entries());
  const activeFilterCount = [keyword, filterEmployee, filterCycle, filterGrade, filterStatus, minScore, maxScore].filter(Boolean).length;
  const resetFilters = () => {
    setKeyword('');
    setFilterEmployee('');
    setFilterCycle('');
    setFilterGrade('');
    setFilterStatus('');
    setMinScore('');
    setMaxScore('');
  };

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-star-half-alt text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">绩效评估</h1>
                <p className="text-xs text-gray-400 mt-0.5">在线评估打分，过程留痕可追溯</p>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 px-5 py-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={keyword} onChange={setKeyword} placeholder="员工/周期/结果..." className="w-60" />
            <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
            </button>
            <div className="flex-1" />
            <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filteredReviews.length}</span> / {reviews.length} 条</span>
          </div>
          <div className="hpt-filter-surface p-3">
            <div className="hpt-filter-grid">
              <FilterField label="员工" type="combo" value={filterEmployee} onChange={setFilterEmployee} options={toFilterOptions(employeeOptions.map(([id, name]) => ({ value: id, label: name })))} />
              <FilterField label="绩效周期" type="combo" value={filterCycle} onChange={setFilterCycle} options={toFilterOptions(cycles.map((c) => ({ value: c.id, label: c.name })))} />
              <FilterField label="等级" type="segment" value={filterGrade} onChange={setFilterGrade} options={toFilterOptions(['S', 'A', 'B', 'C', 'D'])} />
              <FilterField label="状态" type="segment" value={filterStatus} onChange={setFilterStatus} options={toFilterOptions([
                { label: '草稿', value: 'draft' },
                { label: '完成', value: 'completed' },
                { label: '发布', value: 'published' },
              ])} />
              <FilterField label="最终得分" type="number-range" value={{ from: minScore, to: maxScore }} onChange={(next) => { setMinScore(next.from || ''); setMaxScore(next.to || ''); }} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          {/* Review List */}
          <div className="xl:col-span-2 bg-white rounded-xl border border-gray-100">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <span className="text-sm font-bold text-gray-800">评估列表</span>
              <span className="text-xs text-gray-400">显示 {filteredReviews.length}/{reviews.length} 条</span>
            </div>
            {loading ? (
              <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
            ) : filteredReviews.length === 0 ? (
              <div className="py-16 text-center text-gray-400 text-sm">暂无绩效评估数据</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full hrm-table">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">员工</th>
                      <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">周期</th>
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">自评分</th>
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">上级评分</th>
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">最终得分</th>
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">等级</th>
                      <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredReviews.map((r) => (
                      <tr key={r.id} className={`border-b border-gray-50 hover:bg-blue-50/30 transition-colors cursor-pointer ${selectedReview?.id === r.id ? 'bg-blue-50/50' : ''}`} onClick={() => setSelectedReview(r)}>
                        <td className="px-4 py-2.5 text-[13px] font-medium text-gray-800">{r.employeeName || '-'}</td>
                        <td className="px-4 py-2.5 text-[13px] text-gray-500">{r.cycleName || '-'}</td>
                        <td className="px-4 py-2.5 text-center text-[13px] text-gray-600">{r.selfScore || '-'}</td>
                        <td className="px-4 py-2.5 text-center text-[13px] text-gray-600">{r.managerScore || '-'}</td>
                        <td className="px-4 py-2.5 text-center text-[13px] font-bold text-blue-600">{r.finalScore || '-'}</td>
                        <td className="px-4 py-2.5 text-center">
                          {r.grade ? <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${gradeColors[r.grade] || 'text-gray-500 bg-gray-100'}`}>{r.grade}</span> : '-'}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          <span className={getStatusBadgeClass(r.status)}>
                            {getStatusLabel(r.status)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Detail Panel */}
          <div className="bg-white rounded-xl border border-gray-100 p-5">
            {selectedReview ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
                  <div className="w-10 h-10 bg-blue-500 rounded-full flex items-center justify-center text-white font-bold text-sm">{(selectedReview.employeeName || '?')[0]}</div>
                  <div>
                    <div className="text-sm font-bold text-gray-800">{selectedReview.employeeName || '未知'}</div>
                    <div className="text-xs text-gray-400">{selectedReview.cycleName || '未指定周期'}</div>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="p-3 bg-gray-50 rounded-lg">
                    <div className="text-lg font-bold text-gray-800">{selectedReview.selfScore || '-'}</div>
                    <div className="text-[10px] text-gray-400">自评分</div>
                  </div>
                  <div className="p-3 bg-gray-50 rounded-lg">
                    <div className="text-lg font-bold text-gray-800">{selectedReview.managerScore || '-'}</div>
                    <div className="text-[10px] text-gray-400">上级评分</div>
                  </div>
                  <div className="p-3 bg-blue-50 rounded-lg">
                    <div className="text-lg font-bold text-blue-600">{selectedReview.finalScore || '-'}</div>
                    <div className="text-[10px] text-blue-400">最终得分</div>
                  </div>
                </div>
                {selectedReview.grade && (
                  <div className="text-center py-2">
                    <span className={`inline-flex items-center justify-center w-12 h-12 rounded-full text-xl font-bold ${gradeColors[selectedReview.grade] || 'text-gray-500 bg-gray-100'}`}>{selectedReview.grade}</span>
                    <div className="text-xs text-gray-400 mt-1">绩效等级</div>
                  </div>
                )}
                <div className="h-48"><canvas ref={radarRef}></canvas></div>
                {selectedReview.selfReview && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500 mb-1">自评</div>
                    <div className="text-[13px] text-gray-600 bg-gray-50 rounded-lg p-3">{selectedReview.selfReview}</div>
                  </div>
                )}
                {selectedReview.result && (
                  <div>
                    <div className="text-xs font-semibold text-gray-500 mb-1">绩效结果</div>
                    <div className="text-[13px] text-gray-600 bg-gray-50 rounded-lg p-3">{selectedReview.result}</div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-gray-400 py-16">
                <AppIcon className="fas fa-chart-radar text-3xl mb-3 text-gray-200" />
                <div className="text-sm">点击左侧列表查看评估详情</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
