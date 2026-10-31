// @ts-nocheck
import React, { useCallback, useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi, miscApi, Activity } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import { isPathEnabled } from '../../utils/moduleNavigation';
import { Chart, registerables } from 'chart.js';

import AppIcon from '../../components/AppIcon';
Chart.register(...registerables);
const OperationsMetricField = React.lazy(() => import('../../components/OperationsMetricField'));

const statCards = [
  { key: 'activeEmployees', label: '员工总数', icon: 'fa-users', accent: 'ocean', trend: '在职员工', format: 'number', path: '/hrm/employees' },
  { key: 'monthOnboard', label: '本月入职', icon: 'fa-user-plus', accent: 'teal', trend: '本月新增', format: 'number', path: '/hrm/employees' },
  { key: 'monthResigned', label: '本月离职', icon: 'fa-user-minus', accent: 'amber', trend: '本月离职', format: 'number', path: '/hrm/resignations' },
  { key: 'openJobs', label: '在招岗位', icon: 'fa-briefcase', accent: 'violet', trend: '进行中', format: 'number', path: '/job-manage?status=open' },
  { key: 'interviews', label: '面试总数', icon: 'fa-calendar-check', accent: 'sea', trend: '累计面试', format: 'number', path: '/interview-manage' },
  { key: 'payrollTotal', label: '本月人力成本', icon: 'fa-wallet', accent: 'rose', trend: '本月薪资', format: 'currency', path: '/hrm/payroll-records' },
];

const quickActions = [
  { label: '发布岗位', icon: 'fa-briefcase', path: '/job-manage' },
  { label: '添加员工', icon: 'fa-user-plus', path: '/hrm/employees' },
  { label: '发起审批', icon: 'fa-clipboard-check', path: '/approval-center/my-applications' },
  { label: '培训计划', icon: 'fa-chalkboard-teacher', path: '/hrm/training-plans' },
];

type RoleHomePreset = {
  title: string;
  subtitle: string;
  primaryActions: Array<{ label: string; path: string; icon: string }>;
  focusMetrics: string[];
};

const ROLE_HOME_PRESETS: Record<string, RoleHomePreset> = {
  admin: {
    title: 'HR 运营总览',
    subtitle: '关注组织、招聘、审批、薪酬与系统运行。',
    primaryActions: [
      { label: '新建岗位', path: '/job-create', icon: 'fa-briefcase' },
      { label: '员工档案', path: '/hrm/employees', icon: 'fa-id-card' },
      { label: '审批中心', path: '/approval-center/pending', icon: 'fa-user-clock' },
    ],
    focusMetrics: ['headcount', 'openJobs', 'pendingApprovals'],
  },
  hr_admin: {
    title: 'HR 运营总览',
    subtitle: '关注组织、招聘、审批、薪酬与系统运行。',
    primaryActions: [
      { label: '新建岗位', path: '/job-create', icon: 'fa-briefcase' },
      { label: '员工档案', path: '/hrm/employees', icon: 'fa-id-card' },
      { label: '审批中心', path: '/approval-center/pending', icon: 'fa-user-clock' },
    ],
    focusMetrics: ['headcount', 'openJobs', 'pendingApprovals'],
  },
  recruiter: {
    title: '招聘工作台',
    subtitle: '聚焦岗位、简历、候选人和面试推进。',
    primaryActions: [
      { label: '岗位管理', path: '/job-manage', icon: 'fa-briefcase' },
      { label: '上传简历', path: '/resume-upload', icon: 'fa-file-arrow-up' },
      { label: '面试安排', path: '/interview-manage', icon: 'fa-users' },
    ],
    focusMetrics: ['openJobs', 'resumeCount', 'interviewsToday'],
  },
  manager: {
    title: '团队管理工作台',
    subtitle: '处理审批、绩效、培训和团队动态。',
    primaryActions: [
      { label: '待我审批', path: '/approval-center/pending', icon: 'fa-user-clock' },
      { label: '绩效评估', path: '/performance-review', icon: 'fa-star-half-alt' },
      { label: '培训进度', path: '/analytics', icon: 'fa-chart-line' },
    ],
    focusMetrics: ['pendingApprovals', 'performanceReviews', 'trainingCompletion'],
  },
  finance: {
    title: '薪酬财务工作台',
    subtitle: '关注薪资档案、工资条和异常数据。',
    primaryActions: [
      { label: '薪资档案', path: '/salary-profiles', icon: 'fa-wallet' },
      { label: '工资条', path: '/hrm/payroll-records', icon: 'fa-money-check-alt' },
      { label: '考勤统计', path: '/attendance-stats', icon: 'fa-chart-line' },
    ],
    focusMetrics: ['payrollRecords', 'attendanceExceptions', 'salaryProfiles'],
  },
};

const ROLE_METRIC_LABELS: Record<string, { label: string; sourceKey?: string; format?: string }> = {
  headcount: { label: '员工总数', sourceKey: 'activeEmployees' },
  openJobs: { label: '在招岗位' },
  pendingApprovals: { label: '待处理申请', sourceKey: 'requests' },
  resumeCount: { label: '简历池', sourceKey: 'resumes' },
  interviewsToday: { label: '面试总数', sourceKey: 'interviews' },
  performanceReviews: { label: '绩效评估' },
  trainingCompletion: { label: '培训完成率' },
  payrollRecords: { label: '本月人力成本', sourceKey: 'payrollTotal', format: 'currency' },
  attendanceExceptions: { label: '考勤异常' },
  salaryProfiles: { label: '薪资档案' },
};

const getTimeAgo = (timestamp: string) => {
  const now = new Date();
  const time = new Date(timestamp);
  const diff = now.getTime() - time.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 30) return `${days}天前`;
  return time.toLocaleDateString('zh-CN');
};

const formatNum = (v: number, fmt: string) => {
  if (fmt === 'currency') return `¥${v.toLocaleString()}`;
  return v.toLocaleString();
};

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const currentUser = authUtils.getUser();
  const rolePreset = ROLE_HOME_PRESETS[currentUser?.role || ''] || ROLE_HOME_PRESETS.admin;
  const [dashboard, setDashboard] = useState<any>({ cards: {}, departmentDistribution: [], employeeStatusDistribution: [], requestDistribution: [], performanceDistribution: [] });
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [enabledModules, setEnabledModules] = useState<Set<string> | null>(null);
  const donutChartRef = useRef<HTMLCanvasElement>(null);
  const donutChartInstance = useRef<Chart | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [dashboardData, activityData, moduleRows] = await Promise.all([
        hrmApi.getDashboard(),
        miscApi.getRecentActivities(),
        currentUser?.isPlatformAdmin ? Promise.resolve(null) : hrmApi.getTenantModules(),
      ]);
      setDashboard(dashboardData);
      setActivities(activityData.activities || []);
      setEnabledModules(moduleRows ? new Set((moduleRows || []).filter((row: any) => row.enabled).map((row: any) => row.moduleKey)) : null);
    } catch (error) {
      console.error('加载驾驶舱失败', error);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [currentUser?.isPlatformAdmin]);

  useEffect(() => {
    document.title = '恒聘通HRM - 数据驾驶舱';
    loadData();
  }, [loadData]);

  // Donut chart
  useEffect(() => {
    if (loading || !donutChartRef.current) return;
    if (donutChartInstance.current) donutChartInstance.current.destroy();
    const ctx = donutChartRef.current.getContext('2d');
    if (!ctx) return;
    const empDist = dashboard.employeeStatusDistribution || [];
    const labels = empDist.length > 0 ? empDist.map((d: any) => d.name) : ['正式', '试用', '实习'];
    const values = empDist.length > 0 ? empDist.map((d: any) => d.value) : [0, 0, 0];
    const colors = ['#4b82a5', '#bc8954', '#479286', '#776b9c', '#b36d67', '#59829d'];
    donutChartInstance.current = new Chart(ctx, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: colors.slice(0, labels.length), borderWidth: 0, hoverOffset: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '68%',
        plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 6, padding: 12, font: { size: 11 } } } },
      },
    });
    return () => { donutChartInstance.current?.destroy(); };
  }, [loading, dashboard]);

  // Current operating flow: daily execution is kept separate from talent strategy.
  const pipelineData = (() => {
    const resumes = dashboard.cards?.resumes || 0;
    const interviews = dashboard.cards?.interviews || 0;
    const offers = dashboard.cards?.offers || 0;
    const onboard = dashboard.cards?.monthOnboard || 0;
    return [
      { label: '开放岗位', value: dashboard.cards?.openJobs || 0, detail: '需求入口', icon: 'fa-briefcase' },
      { label: '简历池', value: resumes, detail: '人才到达', icon: 'fa-file-alt' },
      { label: '面试中', value: interviews, detail: resumes > 0 ? `${((interviews / resumes) * 100).toFixed(0)}% 转面` : '转面待形成', icon: 'fa-users' },
      { label: 'Offer', value: offers, detail: interviews > 0 ? `${((offers / interviews) * 100).toFixed(0)}% 发放` : '发放待形成', icon: 'fa-file-signature' },
      { label: '本月入职', value: onboard, detail: offers > 0 ? `${((onboard / offers) * 100).toFixed(0)}% 到岗` : '到岗待形成', icon: 'fa-user-plus' },
    ];
  })();

  const pipelineIndicators = (() => {
    const resumes = dashboard.cards?.resumes || 0;
    const interviews = dashboard.cards?.interviews || 0;
    const offers = dashboard.cards?.offers || 0;
    const onboard = dashboard.cards?.monthOnboard || 0;
    const percent = (next: number, base: number) => base > 0 ? `${((next / base) * 100).toFixed(1)}%` : '--';
    return [
      { label: '简历转面试', value: percent(interviews, resumes) },
      { label: '面试转 Offer', value: percent(offers, interviews) },
      { label: 'Offer 到岗', value: percent(onboard, offers) },
    ];
  })();

  // Department distribution
  const deptDist = (dashboard.departmentDistribution || []).slice(0, 6);
  const deptMax = Math.max(...deptDist.map((d: any) => d.value), 1);

  const totalEmployees = dashboard.cards?.activeEmployees || 0;
  const roleFocusMetrics = rolePreset.focusMetrics.map((metricKey) => {
    const config = ROLE_METRIC_LABELS[metricKey] || { label: metricKey };
    const sourceKey = config.sourceKey || metricKey;
    const metricValue = dashboard.cards?.[sourceKey];
    return {
      key: metricKey,
      label: config.label,
      value: metricValue === undefined ? '-' : formatNum(Number(metricValue || 0), config.format || 'number'),
    };
  });
  const isEnabledPath = (path: string) => isPathEnabled(path, enabledModules);
  const visibleStatCards = statCards.filter((card) => isEnabledPath(card.path));
  const visiblePrimaryActions = rolePreset.primaryActions.filter((action) => isEnabledPath(action.path));
  const visibleQuickActions = quickActions.filter((action) => isEnabledPath(action.path));

  return (
    <Layout>
      <div className="ops-dashboard space-y-5 animate-fade-in">
        {loading ? (
          <div className="py-32 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-3xl" /><div className="mt-3 text-sm">正在加载数据驾驶舱...</div></div>
        ) : loadError ? (
          <div className="py-32 text-center">
            <AppIcon className="fas fa-exclamation-circle text-3xl text-red-400" />
            <div className="mt-3 text-sm text-gray-500">数据加载失败，请稍后重试</div>
            <button onClick={loadData} className="mt-4 px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600">重试</button>
          </div>
        ) : (
          <>
            <section className="ops-heading flex flex-col md:flex-row md:items-end md:justify-between gap-4">
              <div>
                <div className="ops-eyebrow">OPERATIONS CONTROL</div>
                <h1 className="ops-title">{rolePreset.title}</h1>
                <p className="ops-subtitle">{rolePreset.subtitle}</p>
              </div>
              <div className="ops-heading-status">
                {roleFocusMetrics.map((metric) => (
                  <div key={metric.key} className="ops-heading-metric">
                    <span>{metric.label}</span>
                    <strong>{metric.value}</strong>
                  </div>
                ))}
              </div>
            </section>

            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
              {visibleStatCards.map((card) => {
                const val = dashboard.cards?.[card.key] ?? 0;
                return (
                  <div key={card.key} data-accent={card.accent} className="stat-card ops-stat-card bg-white rounded-xl border border-gray-100 p-4 cursor-pointer" onClick={() => navigate(card.path)}>
                    <div className="flex items-start justify-between mb-3">
                      <span className="ops-stat-label">{card.label}</span>
                      <div className="ops-stat-icon flex items-center justify-center"><AppIcon className={`fas ${card.icon}`} /></div>
                    </div>
                    <div className="ops-stat-value">{formatNum(val, card.format)}</div>
                    <div className="flex items-center">
                      <span className="ops-stat-note">{card.trend}</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Daily operating flow is intentionally distinct from strategic talent planning. */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
              <section className="ops-command-panel xl:col-span-2 bg-white rounded-xl border border-gray-100 p-5">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="text-[15px] font-bold text-gray-900">招聘运营链路</h3>
                    <p className="text-xs text-gray-400 mt-1">本月人才流转通量</p>
                  </div>
                </div>
                <div className="ops-flow-viewport">
                  <div className="ops-flow-plane" />
                  <div className="ops-flow-rail">
                    {pipelineData.map((stage, index) => (
                      <React.Fragment key={stage.label}>
                        <div className="ops-flow-node">
                          <div className="ops-flow-icon"><AppIcon className={`fas ${stage.icon}`} /></div>
                          <div className="ops-flow-label">{stage.label}</div>
                          <div className="ops-flow-value">{stage.value.toLocaleString()}</div>
                          <div className="ops-flow-detail">{stage.detail}</div>
                        </div>
                        {index < pipelineData.length - 1 && (
                          <div className="ops-flow-link" aria-hidden="true">
                            <span className="ops-flow-pulse" style={{ animationDelay: `${index * 260}ms` }} />
                          </div>
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
                <div className="ops-rate-grid">
                  {pipelineIndicators.map((indicator) => (
                    <div key={indicator.label} className="ops-rate-item">
                      <span>{indicator.label}</span>
                      <strong>{indicator.value}</strong>
                    </div>
                  ))}
                  <div className="ops-rate-item">
                    <span>当前开放岗位</span>
                    <strong>{(dashboard.cards?.openJobs || 0).toLocaleString()}</strong>
                  </div>
                </div>
              </section>

              <div className="ops-quick-panel bg-white rounded-xl border border-gray-100 p-5">
                <h3 className="text-sm font-bold text-gray-800 mb-4">快捷操作</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-2 gap-3">
                  {visiblePrimaryActions.map((action) => (
                    <button key={action.label} onClick={() => navigate(action.path)} className="ops-quick-action flex flex-col items-center gap-2 p-4 rounded-xl border border-gray-100 transition-all group">
                      <div className="ops-quick-icon flex items-center justify-center">
                        <AppIcon className={`fas ${action.icon} text-sm`} />
                      </div>
                      <span className="text-xs text-gray-700 font-semibold">{action.label}</span>
                    </button>
                  ))}
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {visibleQuickActions.slice(0, 2).map((action) => (
                    <button key={action.label} onClick={() => navigate(action.path)} className="rounded-lg border border-gray-100 px-3 py-2 text-left text-xs text-gray-500 hover:border-blue-200 hover:text-blue-600 hover:bg-blue-50 transition-colors">
                      <AppIcon className={`fas ${action.icon} mr-1.5 text-[11px]`} />
                      {action.label}
                    </button>
                  ))}
                </div>
                {isEnabledPath('/system-settings') && (
                  <button onClick={() => navigate('/system-settings')} className="w-full mt-3 py-2 rounded-lg border border-dashed border-gray-200 text-xs text-gray-400 hover:text-blue-500 hover:border-blue-300 transition-colors">
                    <AppIcon className="fas fa-plus mr-1" />自定义快捷入口
                  </button>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
              <React.Suspense fallback={<div className="ops-metric-loading">正在建立运营指标视图...</div>}>
                <OperationsMetricField cards={dashboard.cards || {}} departments={dashboard.departmentDistribution || []} />
              </React.Suspense>

              <div className="ops-distribution-panel bg-white rounded-xl border border-gray-100 p-5">
                <h3 className="text-sm font-bold text-gray-800 mb-3">员工状态分布</h3>
                <div className="relative h-60">
                  <canvas ref={donutChartRef}></canvas>
                  <div className="donut-center">
                    <div className="text-2xl font-bold text-gray-900">{totalEmployees.toLocaleString()}</div>
                    <div className="text-[11px] text-gray-400">总人数</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Operating queues and organization distribution */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
              {/* Pending Tasks */}
              <div className="bg-white rounded-xl border border-gray-100 p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-gray-800">待处理事项</h3>
                </div>
                <div className="space-y-3">
                  {(dashboard.cards?.pendingOnboard || 0) > 0 && isEnabledPath('/hrm/onboarding-tasks') && (
                    <div className="flex items-start gap-3 group cursor-pointer" onClick={() => navigate('/hrm/onboarding-tasks')}>
                      <div className="w-8 h-8 rounded-lg text-green-500 bg-green-50 flex items-center justify-center flex-shrink-0"><AppIcon className="fas fa-file-import text-xs" /></div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-gray-700 group-hover:text-blue-600 transition-colors truncate">待入职员工</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{dashboard.cards.pendingOnboard} 位员工待入职</div>
                      </div>
                    </div>
                  )}
                  {(dashboard.cards?.requests || 0) > 0 && isEnabledPath('/approval-center/pending') && (
                    <div className="flex items-start gap-3 group cursor-pointer" onClick={() => navigate('/approval-center/pending')}>
                      <div className="w-8 h-8 rounded-lg text-purple-500 bg-purple-50 flex items-center justify-center flex-shrink-0"><AppIcon className="fas fa-clock text-xs" /></div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-gray-700 group-hover:text-blue-600 transition-colors truncate">待处理申请</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{dashboard.cards.requests} 条申请记录</div>
                      </div>
                    </div>
                  )}
                  {(dashboard.cards?.openJobs || 0) > 0 && isEnabledPath('/job-manage?status=open') && (
                    <div className="flex items-start gap-3 group cursor-pointer" onClick={() => navigate('/job-manage?status=open')}>
                      <div className="w-8 h-8 rounded-lg text-blue-500 bg-blue-50 flex items-center justify-center flex-shrink-0"><AppIcon className="fas fa-briefcase text-xs" /></div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-gray-700 group-hover:text-blue-600 transition-colors truncate">在招岗位</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{dashboard.cards.openJobs} 个岗位招聘中</div>
                      </div>
                    </div>
                  )}
                  {(dashboard.cards?.attendanceExceptions || 0) > 0 && isEnabledPath('/hrm/attendance-records') && (
                    <div className="flex items-start gap-3 group cursor-pointer" onClick={() => navigate('/hrm/attendance-records')}>
                      <div className="w-8 h-8 rounded-lg text-orange-500 bg-orange-50 flex items-center justify-center flex-shrink-0"><AppIcon className="fas fa-exclamation-triangle text-xs" /></div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-gray-700 group-hover:text-blue-600 transition-colors truncate">考勤异常</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{dashboard.cards.attendanceExceptions} 条异常记录</div>
                      </div>
                    </div>
                  )}
                  {!(
                    ((dashboard.cards?.pendingOnboard || 0) > 0 && isEnabledPath('/hrm/onboarding-tasks'))
                    || ((dashboard.cards?.requests || 0) > 0 && isEnabledPath('/approval-center/pending'))
                    || ((dashboard.cards?.openJobs || 0) > 0 && isEnabledPath('/job-manage?status=open'))
                    || ((dashboard.cards?.attendanceExceptions || 0) > 0 && isEnabledPath('/hrm/attendance-records'))
                  ) && (
                    <div className="text-center text-gray-400 py-6 text-xs">暂无待处理事项</div>
                  )}
                </div>
                {isEnabledPath('/approval-center/pending') && (
                  <button onClick={() => navigate('/approval-center/pending')} className="w-full mt-4 text-xs text-blue-500 hover:text-blue-700 font-medium">查看全部任务 &gt;</button>
                )}
              </div>

              {/* Announcements */}
              <div className="bg-white rounded-xl border border-gray-100 p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-gray-800">公告与通知</h3>
                </div>
                {activities.length === 0 ? (
                  <div className="text-center text-gray-400 py-8 text-xs">暂无通知</div>
                ) : (
                  <div className="space-y-3">
                    {activities.slice(0, 4).map((a, i) => (
                      <div key={i} className="group cursor-pointer">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="status-badge status-default text-[10px] py-0">{a.type === 'system' ? '系统通知' : '业务通知'}</span>
                          <span className="text-[11px] text-gray-400">{getTimeAgo(a.timestamp)}</span>
                        </div>
                        <div className="text-[13px] text-gray-700 group-hover:text-blue-600 transition-colors truncate">{a.title}</div>
                        <div className="text-[11px] text-gray-400 mt-0.5 truncate">{a.description}</div>
                      </div>
                    ))}
                  </div>
                )}
                {isEnabledPath('/notifications') && (
                  <button onClick={() => navigate('/notifications')} className="w-full mt-4 text-xs text-blue-500 hover:text-blue-700 font-medium">查看更多 &gt;</button>
                )}
              </div>

              {/* Department Distribution */}
              <div className="bg-white rounded-xl border border-gray-100 p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-gray-800">部门人数分布<span className="text-gray-400 font-normal ml-1">（Top 6）</span></h3>
                </div>
                {deptDist.length === 0 ? (
                  <div className="text-center text-gray-400 py-8 text-xs">暂无数据</div>
                ) : (
                  <div className="space-y-3">
                    {deptDist.map((dept: any) => (
                      <div key={dept.name}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-gray-500 truncate max-w-[120px]">{dept.name || '未设置'}</span>
                          <span className="font-semibold text-gray-800">{dept.value}</span>
                        </div>
                        <div className="h-[6px] bg-gray-100 rounded-full overflow-hidden">
                          <div className="ops-quiet-bar h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(6, (dept.value / deptMax) * 100)}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {isEnabledPath('/hrm/departments') && (
                  <button onClick={() => navigate('/hrm/departments')} className="w-full mt-4 text-xs text-blue-500 hover:text-blue-700 font-medium">查看全部部门 &gt;</button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
};

export default HomePage;
