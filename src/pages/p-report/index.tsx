import { useState, useEffect } from 'react';
import { Layout } from '../../components/Layout';
import { miscApi, ReportSummary } from '../../utils/api';


import AppIcon from '../../components/AppIcon';
export default function ReportPage() {
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    document.title = '数据统计 - 恒聘通';
    loadSummary();
  }, []);

  const loadSummary = async () => {
    try {
      const data = await miscApi.getReportSummary();
      setSummary(data);
    } catch (err) {
      console.error('加载统计数据失败', err);
    } finally {
      setIsLoading(false);
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
      <div>
        {/* 页面头部 */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-800 mb-2">数据统计</h2>
          <nav className="text-sm text-gray-600">
            <span>首页</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>数据统计</span>
          </nav>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 mb-1">岗位总数</p>
                <p className="text-3xl font-bold text-blue-600">
                  {summary?.totals.jobs || 0}
                </p>
              </div>
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <AppIcon className="fas fa-briefcase text-blue-600 text-xl" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 mb-1">简历总数</p>
                <p className="text-3xl font-bold text-green-600">
                  {summary?.totals.resumes || 0}
                </p>
              </div>
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <AppIcon className="fas fa-file-alt text-green-600 text-xl" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 mb-1">面试总数</p>
                <p className="text-3xl font-bold text-yellow-600">
                  {summary?.totals.interviews || 0}
                </p>
              </div>
              <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                <AppIcon className="fas fa-users text-yellow-600 text-xl" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600 mb-1">用户总数</p>
                <p className="text-3xl font-bold text-purple-600">
                  {summary?.totals.users || 0}
                </p>
              </div>
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                <AppIcon className="fas fa-user-circle text-purple-600 text-xl" />
              </div>
            </div>
          </div>
        </div>

        {/* 图表区域 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 招聘趋势 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              招聘趋势
            </h3>
            <div className="flex items-center justify-center h-64">
              <div className="text-center text-gray-400">
                <AppIcon className="fas fa-chart-line text-5xl mb-4" />
                <p>图表功能开发中...</p>
              </div>
            </div>
          </div>

          {/* 面试统计 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              面试统计
            </h3>
            <div className="flex items-center justify-center h-64">
              <div className="text-center text-gray-400">
                <AppIcon className="fas fa-chart-pie text-5xl mb-4" />
                <p>图表功能开发中...</p>
              </div>
            </div>
          </div>

          {/* 岗位分布 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              岗位分布
            </h3>
            <div className="flex items-center justify-center h-64">
              <div className="text-center text-gray-400">
                <AppIcon className="fas fa-chart-bar text-5xl mb-4" />
                <p>图表功能开发中...</p>
              </div>
            </div>
          </div>

          {/* 简历来源 */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4 pb-3 border-b">
              简历来源
            </h3>
            <div className="flex items-center justify-center h-64">
              <div className="text-center text-gray-400">
                <AppIcon className="fas fa-chart-area text-5xl mb-4" />
                <p>图表功能开发中...</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
