// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi } from '../../utils/api';
import { Chart, registerables } from 'chart.js';
import { FilterField, SearchInput, toFilterOptions } from '../../components/SmartFilters';

import AppIcon from '../../components/AppIcon';
Chart.register(...registerables);

export default function AttendanceStatsPage() {
  const navigate = useNavigate();
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [records, setRecords] = useState<any[]>([]);
  const [sourceCounts, setSourceCounts] = useState({ attendanceRecords: 0, approvedRequests: 0 });
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [employeeFilter, setEmployeeFilter] = useState('');
  const [exceptionFilter, setExceptionFilter] = useState('');
  const [minExceptions, setMinExceptions] = useState('');
  const [maxExceptions, setMaxExceptions] = useState('');
  const barChartRef = useRef<HTMLCanvasElement>(null);
  const pieChartRef = useRef<HTMLCanvasElement>(null);
  const barChartInstance = useRef<Chart | null>(null);
  const pieChartInstance = useRef<Chart | null>(null);

  useEffect(() => {
    document.title = '考勤统计 - 恒聘通HRM';
    loadData();
  }, [month]);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await hrmApi.attendanceMonthly(month);
      setRecords(data.records || []);
      setSourceCounts(data.sourceCounts || { attendanceRecords: 0, approvedRequests: 0 });
    } catch (error) {
      console.error('加载考勤统计失败', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredRecords = records.filter((record) => {
    if (keyword && !(record.employeeName || '').toLowerCase().includes(keyword.toLowerCase())) return false;
    if (employeeFilter && record.employeeId !== employeeFilter) return false;
    if (exceptionFilter === 'has_exception' && Number(record.exceptions || 0) <= 0) return false;
    if (exceptionFilter === 'no_exception' && Number(record.exceptions || 0) > 0) return false;
    if (exceptionFilter === 'has_request' && Number(record.approvedRequests || 0) <= 0) return false;
    if (exceptionFilter === 'no_request' && Number(record.approvedRequests || 0) > 0) return false;
    if (minExceptions && Number(record.exceptions || 0) < Number(minExceptions)) return false;
    if (maxExceptions && Number(record.exceptions || 0) > Number(maxExceptions)) return false;
    return true;
  });
  const activeFilterCount = [keyword, employeeFilter, exceptionFilter, minExceptions, maxExceptions].filter(Boolean).length;
  const resetFilters = () => {
    setKeyword('');
    setEmployeeFilter('');
    setExceptionFilter('');
    setMinExceptions('');
    setMaxExceptions('');
  };

  // Summary stats
  const totalNormal = filteredRecords.reduce((sum, r) => sum + (r.normal || 0), 0);
  const totalLate = filteredRecords.reduce((sum, r) => sum + (r.late || 0), 0);
  const totalEarlyLeave = filteredRecords.reduce((sum, r) => sum + (r.earlyLeave || 0), 0);
  const totalMissingCard = filteredRecords.reduce((sum, r) => sum + (r.missingCard || 0), 0);
  const totalLeave = filteredRecords.reduce((sum, r) => sum + (r.leave || 0), 0);
  const totalOvertime = filteredRecords.reduce((sum, r) => sum + (r.overtime || 0), 0);
  const totalTravel = filteredRecords.reduce((sum, r) => sum + (r.travel || 0), 0);
  const totalMakeupCard = filteredRecords.reduce((sum, r) => sum + (r.makeupCard || 0), 0);
  const totalApprovedRequests = filteredRecords.reduce((sum, r) => sum + (r.approvedRequests || 0), 0);
  const totalAll = totalNormal + totalLate + totalEarlyLeave + totalMissingCard + totalLeave + totalOvertime + totalTravel + totalMakeupCard;

  // Bar chart - department attendance
  useEffect(() => {
    if (loading || !barChartRef.current) return;
    if (barChartInstance.current) barChartInstance.current.destroy();
    const ctx = barChartRef.current.getContext('2d');
    if (!ctx) return;
    const names = filteredRecords.slice(0, 10).map(r => r.employeeName || '未知');
    const normals = filteredRecords.slice(0, 10).map(r => r.normal || 0);
    const exceptions = filteredRecords.slice(0, 10).map(r => (r.late || 0) + (r.earlyLeave || 0) + (r.missingCard || 0));
    barChartInstance.current = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: names,
        datasets: [
          { label: '正常', data: normals, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 3 },
          { label: '异常', data: exceptions, backgroundColor: 'rgba(239,68,68,0.7)', borderRadius: 3 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'top', align: 'end', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 6, font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 45 } },
          y: {
            grid: { color: '#f3f4f6' },
            beginAtZero: true,
            ticks: {
              font: { size: 11 },
              stepSize: 1,
              precision: 0,
              callback: (value) => Number.isInteger(Number(value)) ? String(value) : '',
            },
          },
        },
      },
    });
    return () => { barChartInstance.current?.destroy(); };
  }, [loading, filteredRecords]);

  // Pie chart - status distribution
  useEffect(() => {
    if (loading || !pieChartRef.current) return;
    if (pieChartInstance.current) pieChartInstance.current.destroy();
    const ctx = pieChartRef.current.getContext('2d');
    if (!ctx) return;
    const values = [totalNormal, totalLate, totalEarlyLeave, totalMissingCard, totalLeave, totalOvertime, totalTravel, totalMakeupCard];
    const data = values.filter(v => v > 0);
    const labels = ['正常', '迟到', '早退', '缺卡', '请假', '加班', '出差', '补卡'].filter((_, i) => values[i] > 0);
    const colors = ['#3b82f6', '#ef4444', '#f59e0b', '#8b5cf6', '#10b981', '#06b6d4', '#14b8a6', '#64748b'];
    pieChartInstance.current = new Chart(ctx, {
      type: 'doughnut',
      data: { labels, datasets: [{ data, backgroundColor: colors.slice(0, data.length), borderWidth: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '60%',
        plugins: { legend: { position: 'right', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 6, font: { size: 11 }, padding: 12 } } },
      },
    });
    return () => { pieChartInstance.current?.destroy(); };
  }, [loading, filteredRecords]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-chart-line text-sm" /></div>
              <div>
                <h1 className="text-[15px] font-bold text-gray-900">考勤统计</h1>
                <p className="text-xs text-gray-400 mt-0.5">按员工汇总当月正常、缺卡等日记录。点员工姓名可查看该月每日打卡。</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => navigate(`/hrm/attendance-records?month=${encodeURIComponent(month)}`)}
                className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:text-blue-600 hover:border-blue-200"
              >
                按天查看
              </button>
              <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 px-5 py-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput value={keyword} onChange={setKeyword} placeholder="搜索员工..." className="w-56" />
            <button onClick={resetFilters} disabled={activeFilterCount === 0} className="px-3 py-[6px] border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-blue-600 hover:border-blue-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              <AppIcon className="fas fa-rotate-left mr-1" />重置{activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
            </button>
            <div className="flex-1" />
            <span className="text-xs text-gray-400">显示 <span className="font-medium text-gray-600">{filteredRecords.length}</span> / {records.length} 人</span>
          </div>
          <div className="hpt-filter-surface p-3">
            <div className="hpt-filter-grid">
              <FilterField
                label="员工"
                type="combo"
                value={employeeFilter}
                onChange={setEmployeeFilter}
                options={toFilterOptions(records.map((record) => ({ label: record.employeeName, value: record.employeeId })))}
              />
              <FilterField
                label="异常情况"
                type="select"
                value={exceptionFilter}
                onChange={setExceptionFilter}
                options={toFilterOptions([
                  { label: '有异常', value: 'has_exception' },
                  { label: '无异常', value: 'no_exception' },
                  { label: '有已批申请', value: 'has_request' },
                  { label: '无已批申请', value: 'no_request' },
                ])}
              />
              <FilterField
                label="异常次数"
                type="number-range"
                value={{ from: minExceptions, to: maxExceptions }}
                onChange={(next) => {
                  setMinExceptions(next.from || '');
                  setMaxExceptions(next.to || '');
                }}
              />
            </div>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-4">
          {[
            { label: '出勤人次', value: totalAll, icon: 'fa-users', bg: 'bg-blue-50', color: 'text-blue-500' },
            { label: '正常', value: totalNormal, icon: 'fa-check-circle', bg: 'bg-green-50', color: 'text-green-500' },
            { label: '迟到', value: totalLate, icon: 'fa-clock', bg: 'bg-red-50', color: 'text-red-500' },
            { label: '早退', value: totalEarlyLeave, icon: 'fa-sign-out-alt', bg: 'bg-orange-50', color: 'text-orange-500' },
            { label: '缺卡', value: totalMissingCard, icon: 'fa-exclamation-circle', bg: 'bg-purple-50', color: 'text-purple-500' },
            { label: '请假', value: totalLeave, icon: 'fa-calendar-minus', bg: 'bg-cyan-50', color: 'text-cyan-500' },
            { label: '加班', value: totalOvertime, icon: 'fa-moon', bg: 'bg-indigo-50', color: 'text-indigo-500' },
            { label: '已批申请', value: totalApprovedRequests, icon: 'fa-clipboard-check', bg: 'bg-slate-50', color: 'text-slate-500' },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-start justify-between mb-2">
                <span className="text-xs text-gray-400">{card.label}</span>
                <div className={`w-7 h-7 rounded-lg ${card.bg} ${card.color} flex items-center justify-center`}><AppIcon className={`fas ${card.icon} text-xs`} /></div>
              </div>
              <div className="text-xl font-bold text-gray-900">{card.value}</div>
            </div>
          ))}
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <div className="bg-white rounded-xl border border-gray-100 p-5">
            <h3 className="text-sm font-bold text-gray-800 mb-3">考勤趋势（天）</h3>
            <div className="h-64"><canvas ref={barChartRef}></canvas></div>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-5">
            <h3 className="text-sm font-bold text-gray-800 mb-3">考勤状态分布</h3>
            <div className="h-64 relative">
              <canvas ref={pieChartRef}></canvas>
              <div className="donut-center">
                <div className="text-lg font-bold text-gray-900">{totalAll}</div>
                <div className="text-[10px] text-gray-400">总人次</div>
              </div>
            </div>
          </div>
        </div>

        {/* Detail Table */}
        <div className="bg-white rounded-xl border border-gray-100">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-bold text-gray-800">员工考勤明细</h3>
            <span className="text-xs text-gray-400">
              打卡 {sourceCounts.attendanceRecords || 0} 条 · 已批申请 {sourceCounts.approvedRequests || 0} 条 · 显示 {filteredRecords.length}/{records.length} 人
            </span>
          </div>
          {loading ? (
            <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div>
          ) : filteredRecords.length === 0 ? (
            <div className="py-16 text-center text-gray-400 text-sm">本月暂无考勤数据</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full hrm-table">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">员工</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">正常</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">迟到</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">早退</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">缺卡</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">请假</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">加班</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">出差</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">补卡</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">已批申请</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">异常合计</th>
                    <th className="px-4 py-2.5 text-center text-[11px] font-semibold text-gray-400 uppercase bg-gray-50/80">日报</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRecords.map((r, i) => (
                    <tr key={r.employeeId || i} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                      <td className="px-4 py-2.5 text-[13px] font-medium text-gray-800">
                        <button
                          type="button"
                          className="text-left text-blue-600 hover:underline"
                          onClick={() => navigate(`/hrm/attendance-records?employeeId=${encodeURIComponent(r.employeeId || '')}&month=${encodeURIComponent(month)}`)}
                        >
                          {r.employeeName || '-'}
                        </button>
                      </td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-green-600 font-medium">{r.normal || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-red-500">{r.late || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-orange-500">{r.earlyLeave || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-purple-500">{r.missingCard || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-cyan-500">{r.leave || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-blue-500">{r.overtime || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-teal-600">{r.travel || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-slate-500">{r.makeupCard || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] text-gray-600">{r.approvedRequests || 0}</td>
                      <td className="px-4 py-2.5 text-center text-[13px] font-bold text-red-600">{r.exceptions || 0}</td>
                      <td className="px-4 py-2.5 text-center">
                        <button
                          type="button"
                          className="text-xs text-blue-600 hover:underline"
                          onClick={() => navigate(`/hrm/attendance-records?employeeId=${encodeURIComponent(r.employeeId || '')}&month=${encodeURIComponent(month)}`)}
                        >
                          查看日报
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
