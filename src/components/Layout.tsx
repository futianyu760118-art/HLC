import React, { ReactNode, useState, useMemo, useEffect, useCallback } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { authUtils } from '../utils/auth';
import { extensionApi, hrmApi } from '../utils/api';
import FeedbackDialog from './FeedbackDialog';
import { NotificationBell } from './NotificationBell';
import AIAssistant from './AIAssistant';
import confirm from './ConfirmDialog';

import AppIcon from './AppIcon';
import UserAvatar from './UserAvatar';
import { isPathEnabled } from '../utils/moduleNavigation';
import { managementCapabilitiesForGroup } from '../config/capabilityNavigation';
interface LayoutProps {
  children: ReactNode;
}

const LayoutNestingContext = React.createContext(false);

type MenuItem = {
  path: string;
  icon: string;
  label: string;
};

type MenuGroup = {
  title: string;
  items: MenuItem[];
};

const roleLabels: Record<string, string> = {
  platform_admin: '平台管理员', admin: '系统管理员', hr_admin: 'HR管理员', recruiter: '招聘专员', manager: '部门负责人', employee: '普通员工', finance: '财务人员', executive: '高管/老板', viewer: '查看者',
};

const menuGroups: MenuGroup[] = [
  { title: '首页', items: [{ path: '/home', icon: 'fa-gauge-high', label: '数据驾驶舱' }] },
  { title: '人才战略', items: [{ path: '/talent-intelligence', icon: 'fa-radar', label: '人才智能' }, ...managementCapabilitiesForGroup('人才战略')] },
  { title: '招聘管理', items: [
    { path: '/job-manage', icon: 'fa-briefcase', label: '岗位管理' },
    { path: '/resume-manage', icon: 'fa-file-alt', label: '简历管理' },
    { path: '/hrm/candidates', icon: 'fa-user-tie', label: '候选人管理' },
    { path: '/interview-manage', icon: 'fa-users', label: '面试管理' },
    { path: '/hrm/offers', icon: 'fa-file-signature', label: 'Offer管理' },
  ] },
  { title: '组织管理', items: [
    { path: '/organization', icon: 'fa-sitemap', label: '组织架构' },
    { path: '/hrm/departments', icon: 'fa-sitemap', label: '部门管理' },
    { path: '/hrm/positions', icon: 'fa-layer-group', label: '岗位体系' },
    ...managementCapabilitiesForGroup('组织管理'),
  ] },
  { title: '员工管理', items: [
    { path: '/hrm/employees', icon: 'fa-id-card', label: '员工档案' },
    { path: '/hrm/onboarding-tasks', icon: 'fa-clipboard-check', label: '入职管理' },
    { path: '/hrm/probations', icon: 'fa-user-check', label: '转正管理' },
    { path: '/hrm/employee-changes', icon: 'fa-random', label: '人事异动' },
    { path: '/hrm/resignations', icon: 'fa-user-minus', label: '离职管理' },
    { path: '/hrm/contracts', icon: 'fa-file-contract', label: '合同管理' },
    ...managementCapabilitiesForGroup('员工管理'),
  ] },
  { title: '考勤与申请', items: [
    { path: '/attendance-timesheet', icon: 'fa-clock', label: '考勤明细（工时）' },
    { path: '/attendance-punches', icon: 'fa-fingerprint', label: '原始打卡记录' },
    { path: '/attendance-stats', icon: 'fa-chart-line', label: '考勤统计' },
    { path: '/attendance-policy', icon: 'fa-calendar-check', label: '考勤制度' },
    { path: '/attendance-sync', icon: 'fa-sync', label: '考勤机同步' },
    { path: '/employee-requests', icon: 'fa-calendar-plus', label: '请假/加班/出差/补卡' },
    ...managementCapabilitiesForGroup('考勤与申请'),
  ] },
  { title: '审批中心', items: [
    { path: '/approval-center/my-applications', icon: 'fa-inbox', label: '我的申请' },
    { path: '/approval-center/pending', icon: 'fa-user-clock', label: '待我审批' },
    { path: '/approval-center/records', icon: 'fa-history', label: '审批记录' },
  ] },
  { title: '绩效管理', items: [
    { path: '/performance-center', icon: 'fa-clipboard-check', label: '绩效考核中心' },
      { path: '/performance-indicators', icon: 'fa-list-check', label: '考核指标' },
      { path: '/performance-participants', icon: 'fa-user-check', label: '参与考核人员' },
    { path: '/hrm/performance-cycles', icon: 'fa-bullseye', label: '绩效周期' },
    { path: '/hrm/performance-templates', icon: 'fa-list-check', label: '绩效模板' },
    { path: '/performance-review', icon: 'fa-star-half-alt', label: '绩效评估' },
    ...managementCapabilitiesForGroup('绩效管理'),
  ] },
  { title: '薪酬管理', items: [
    { path: '/salary-profiles', icon: 'fa-wallet', label: '薪资档案' },
    { path: '/hrm/payroll-records', icon: 'fa-money-check-alt', label: '工资条' },
  ] },
  { title: '学习发展', items: [
    { path: '/analytics', icon: 'fa-chart-line', label: '数据看板' },
    { path: '/pk-seasons', icon: 'fa-trophy', label: '团队PK竞赛' },
    { path: '/training-center', icon: 'fa-book-open-reader', label: '课程目录' },
    { path: '/learning-paths', icon: 'fa-route', label: '学习路径' },
    { path: '/competency', icon: 'fa-chart-radar', label: '胜任力测评' },
    { path: '/course-categories', icon: 'fa-folder-tree', label: '课程分类' },
    { path: '/exam-generate', icon: 'fa-microchip', label: '智能出题' },
  ] },
  { title: '考试中心', items: [
    { path: '/exam-center', icon: 'fa-circle-dot', label: '题库管理' },
    { path: '/exam-papers', icon: 'fa-file-lines', label: '试卷组卷' },
    { path: '/exam-tasks', icon: 'fa-calendar-check', label: '考试安排' },
    { path: '/exam-attempts', icon: 'fa-chart-line', label: '成绩管理' },
  ] },
  { title: '系统管理', items: [
    { path: '/hrm/users', icon: 'fa-users-cog', label: '用户管理' },
    { path: '/hrm/roles', icon: 'fa-user-shield', label: '角色权限' },
    { path: '/todos', icon: 'fa-clipboard-check', label: '待办事项' },
    { path: '/notifications', icon: 'fa-bell', label: '通知提醒' },
    { path: '/feedback', icon: 'fa-comment-medical', label: '问题反馈' },
    { path: '/operation-logs', icon: 'fa-clipboard-list', label: '操作日志' },
    { path: '/ai-model-settings', icon: 'fa-brain', label: 'AI 模型管理' },
    { path: '/system-settings', icon: 'fa-cog', label: '系统设置' },
    ...managementCapabilitiesForGroup('系统管理'),
  ] },
];

menuGroups[0].items.push(...managementCapabilitiesForGroup('首页'));

// 个人学习门户专用菜单（普通员工只看这些；其他绑定员工档案的角色可切换进入）
const portalMenuGroups: MenuGroup[] = [
  { title: '学习中心', items: [
    { path: '/portal', icon: 'fa-home', label: '我的首页' },
    { path: '/portal/my-courses', icon: 'fa-book-open', label: '我的课程' },
    { path: '/portal/learning-paths', icon: 'fa-route', label: '学习路径' },
    { path: '/portal/pk', icon: 'fa-trophy', label: 'PK竞赛' },
    { path: '/portal/wrong-questions', icon: 'fa-bookmark', label: '错题本' },
  ] },
  { title: '考试中心', items: [
    { path: '/portal/my-exams', icon: 'fa-clipboard-list', label: '我的考试' },
  ] },
  { title: '我的', items: [
    { path: '/portal/my-profile', icon: 'fa-id-card', label: '学习档案' },
    { path: '/portal/competency', icon: 'fa-chart-radar', label: '能力测评' },
    { path: '/portal/points', icon: 'fa-trophy', label: '学习积分' },
    { path: '/portal/shop', icon: 'fa-store', label: '积分商城' },
    { path: '/portal/certificates', icon: 'fa-certificate', label: '我的证书' },
  ] },
];

const LayoutShell: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const user = authUtils.getUser();
  const isPortalRoute = location.pathname.startsWith('/portal');
  const isPortalAccount = user?.accountType === 'employee_portal';
  // 员工门户账号只看门户菜单；管理后台账号不直接复用门户权限。
  const isEmployeeOnly = isPortalAccount;
  const portalGroups = (!isEmployeeOnly && isPortalRoute)
    ? [
        { title: '工作台', items: [{ path: '/home', icon: 'fa-arrow-left', label: '返回管理后台' }] },
        ...portalMenuGroups,
      ]
    : portalMenuGroups;
  const groups = (isEmployeeOnly || isPortalRoute) ? portalGroups : menuGroups;
  const [enabledModules, setEnabledModules] = useState<Set<string> | null>(null);
  const [supportedCapabilities, setSupportedCapabilities] = useState<Set<string> | null>(null);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return sessionStorage.getItem('layout:collapsed') === '1';
  });
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    if (typeof window === 'undefined') return {};
    try {
      return JSON.parse(sessionStorage.getItem('layout:collapsedGroups') || '{}');
    } catch {
      return {};
    }
  });
  const [unreadCount, setUnreadCount] = useState(0);
  const [showFeedback, setShowFeedback] = useState(false);
  const [navSearch, setNavSearch] = useState('');
  const [profileRevision, setProfileRevision] = useState(0);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);  // 移动端侧边栏抽屉
  const [assistantOpen, setAssistantOpen] = useState(() => {
    if (typeof window === 'undefined') return false;
    return sessionStorage.getItem('ai_assistant_open') === '1';
  });
  const [assistantExpanded, setAssistantExpanded] = useState(false);
  const [assistantReserve, setAssistantReserve] = useState(0);
  const sidebarRef = React.useRef<HTMLElement>(null);

  useEffect(() => {
    if (isPortalRoute || user?.isPlatformAdmin) {
      setEnabledModules(null);
      setSupportedCapabilities(null);
      return;
    }
    let cancelled = false;
    Promise.allSettled([hrmApi.getTenantModules(), extensionApi.catalog()])
      .then(([modulesResult, catalogResult]) => {
        if (cancelled) return;
        const rows = modulesResult.status === 'fulfilled' ? modulesResult.value : [];
        setEnabledModules(new Set((rows || []).filter((row: any) => row.enabled).map((row: any) => row.moduleKey)));
        if (catalogResult.status !== 'fulfilled' || catalogResult.value.releaseCapabilityVersion !== 'extension-navigation-v2') {
          setSupportedCapabilities(new Set());
          return;
        }
        setSupportedCapabilities(new Set(catalogResult.value.packages.flatMap((extensionPackage) => (
          extensionPackage.features.filter((feature) => feature.supported).map((feature) => feature.key)
        ))));
      });
    return () => { cancelled = true; };
  }, [isPortalRoute, user?.tenantId, user?.isPlatformAdmin]);

  const visibleGroups = useMemo(() => {
    if (isPortalRoute) return groups;
    if (!enabledModules || !supportedCapabilities) return [];
    return groups
      .map(group => ({
        ...group,
        items: group.items.filter((item) => {
          if (item.path === '/attendance-sync') {
            return user?.tenantSlug === 'HPT-00000001'
              && ['admin', 'hr_admin'].includes(user?.role || '')
              && isPathEnabled(item.path, enabledModules, supportedCapabilities);
          }
          if (item.path === '/attendance-policy') {
            return ['admin', 'hr_admin'].includes(user?.role || '')
              && isPathEnabled(item.path, enabledModules, supportedCapabilities);
          }
          return isPathEnabled(item.path, enabledModules, supportedCapabilities);
        }),
      }))
      .filter(group => group.items.length > 0);
  }, [enabledModules, supportedCapabilities, groups, isPortalRoute, user?.tenantSlug, user?.role]);

  const navSearchResults = useMemo(() => {
    const keyword = navSearch.trim().toLowerCase();
    if (!keyword) return [];
    return visibleGroups
      .flatMap((group) => group.items.map((item) => ({ ...item, group: group.title })))
      .filter((item) => `${item.label} ${item.group} ${item.path}`.toLowerCase().includes(keyword))
      .slice(0, 8);
  }, [navSearch, visibleGroups]);

  const openNavSearchResult = useCallback((path: string) => {
    navigate(path);
    setNavSearch('');
    setMobileSidebarOpen(false);
  }, [navigate]);

  // 持久化 sidebar 滚动位置（修复切换页面后菜单回到顶部的问题）
  useEffect(() => {
    const el = sidebarRef.current;
    if (!el) return;
    // 恢复滚动位置
    const saved = sessionStorage.getItem('layout:sidebarScroll');
    if (saved) {
      el.scrollTop = parseInt(saved, 10) || 0;
    }
    // 监听滚动并保存
    let raf: number | null = null;
    const onScroll = () => {
      if (raf !== null) return;
      raf = requestAnimationFrame(() => {
        sessionStorage.setItem('layout:sidebarScroll', String(el.scrollTop));
        raf = null;
      });
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      el.removeEventListener('scroll', onScroll);
      if (raf !== null) cancelAnimationFrame(raf);
    };
  }, []);

  // 持久化折叠状态
  useEffect(() => {
    sessionStorage.setItem('layout:collapsed', collapsed ? '1' : '0');
  }, [collapsed]);

  useEffect(() => {
    sessionStorage.setItem('layout:collapsedGroups', JSON.stringify(collapsedGroups));
  }, [collapsedGroups]);

  useEffect(() => {
    const refreshProfile = () => setProfileRevision((value) => value + 1);
    window.addEventListener('hpt-profile-updated', refreshProfile);
    return () => window.removeEventListener('hpt-profile-updated', refreshProfile);
  }, []);
  useEffect(() => {
    const computeReserve = () => {
      const width = window.innerWidth || 0;
      if (!assistantOpen || width < 1180) {
        setAssistantReserve(0);
      } else if (width <= 1380) {
        setAssistantReserve(428);
      } else {
        setAssistantReserve(480);
      }
    };
    computeReserve();
    window.addEventListener('resize', computeReserve);
    return () => window.removeEventListener('resize', computeReserve);
  }, [assistantOpen, assistantExpanded]);

  useEffect(() => {
    const handleAssistantLayout = (event: Event) => {
      const detail = (event as CustomEvent<{ open?: boolean; expanded?: boolean }>).detail || {};
      setAssistantOpen(Boolean(detail.open));
      setAssistantExpanded(Boolean(detail.expanded));
    };
    window.addEventListener('hpt-assistant-layout', handleAssistantLayout as EventListener);
    return () => window.removeEventListener('hpt-assistant-layout', handleAssistantLayout as EventListener);
  }, []);

  const refreshUnreadCount = useCallback(() => {
    if (isPortalAccount || isPortalRoute || user?.isPlatformAdmin) {
      setUnreadCount(0);
      return;
    }
    hrmApi.list('notifications', { status: 'unread' })
      .then((data: any[]) => setUnreadCount(data?.length || 0))
      .catch(() => {});
  }, [isPortalAccount, isPortalRoute, user?.isPlatformAdmin]);

  // 获取真实未读通知数，并在通知页面写入后立即同步。
  useEffect(() => {
    refreshUnreadCount();
    const timer = window.setInterval(refreshUnreadCount, 60000);
    const handleNotificationChange = () => refreshUnreadCount();
    window.addEventListener('hrm:notifications-changed', handleNotificationChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('hrm:notifications-changed', handleNotificationChange);
    };
  }, [refreshUnreadCount]);

  const handleLogout = async () => {
    const ok = await confirm({ title: '退出登录', message: '确定要退出登录吗？', confirmText: '退出' });
    if (ok) {
      authUtils.logout();
      navigate(user?.isPlatformAdmin ? '/platform/login' : (isPortalAccount || isPortalRoute ? '/login?mode=portal' : '/login?mode=hrm'));
    }
  };

  const isActive = useCallback((path: string) => {
    // Exact match
    if (location.pathname === path) return true;
    // For approval-center sub-routes
    if (path.startsWith('/approval-center/') && location.pathname.startsWith(path)) return true;
    return false;
  }, [location.pathname]);

  const breadcrumb = useMemo(() => {
    const crumbs: Array<{ label: string; path?: string }> = isPortalRoute
      ? [{ label: '学习门户', path: '/portal' }]
      : [{ label: '首页', path: '/home' }];
    for (const group of visibleGroups) {
      for (const item of group.items) {
        if (isActive(item.path)) {
          if (group.title !== '首页' && group.title !== '学习中心' && group.title !== '工作台') crumbs.push({ label: group.title });
          crumbs.push({ label: item.label });
          return crumbs;
        }
      }
    }
    return crumbs;
  }, [visibleGroups, isActive, isPortalRoute]);

  const sidebarW = collapsed ? 'w-[68px]' : 'w-60';
  const mainMl = collapsed ? 'ml-0 md:ml-[68px]' : 'ml-0 md:ml-60';
  const showWorkspaceSwitch = false;
  const workspaceSwitchTarget = isPortalRoute ? '/login?mode=hrm' : '/login?mode=portal';
  const workspaceSwitchLabel = isPortalRoute ? '管理后台' : '员工门户';
  const workspaceSwitchIcon = isPortalRoute ? 'fa-gauge-high' : 'fa-graduation-cap';

  return (
    <>
      {/* 移动端遮罩 */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 bg-black/40 z-30 md:hidden" onClick={() => setMobileSidebarOpen(false)} />
      )}
      {/* 移动端顶部汉堡按钮 */}
      <button onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
        aria-label={mobileSidebarOpen ? '关闭菜单' : '打开菜单'}
        className="fixed top-2 left-2 z-50 md:hidden w-10 h-10 rounded-lg bg-white border border-gray-200 flex items-center justify-center shadow-sm">
        <AppIcon className={`fas ${mobileSidebarOpen ? 'fa-times' : 'fa-bars'} text-gray-600`} />
      </button>
    <div className="hpt-shell min-h-screen bg-white">
      <header className="fixed top-0 left-0 right-0 bg-white border-b border-gray-200 h-14 z-50 shadow-sm">
        <div className="flex items-center h-full px-4">
          <button onClick={() => setCollapsed(!collapsed)} className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg mr-3 flex-shrink-0 transition-colors" aria-label={collapsed ? '展开菜单' : '收起菜单'}>
            <AppIcon className="fas fa-bars text-sm" />
          </button>

          <div className="hidden md:flex items-center text-sm text-gray-400 mr-4 flex-shrink-0">
            {breadcrumb.map((crumb, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span className="mx-1.5">/</span>}
                {crumb.path ? (
                  <Link to={crumb.path} className="hover:text-blue-600 transition-colors">{crumb.label}</Link>
                ) : (
                  <span className={i === breadcrumb.length - 1 ? 'text-gray-700 font-medium' : ''}>{crumb.label}</span>
                )}
              </React.Fragment>
            ))}
          </div>

          <div className="flex-1 max-w-md mx-2 hidden lg:block">
            <div className="relative">
              <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-300 text-xs" />
              <input
                type="text"
                aria-label="导航搜索"
                value={navSearch}
                onChange={(event) => setNavSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && navSearchResults[0]) {
                    openNavSearchResult(navSearchResults[0].path);
                  }
                  if (event.key === 'Escape') setNavSearch('');
                }}
                placeholder={isPortalRoute ? '搜索课程、考试、证书...' : '搜索员工、部门、岗位...'}
                className="w-full pl-9 pr-4 py-[6px] bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 focus:bg-white transition-all"
              />
              {navSearchResults.length > 0 && (
                <div className="absolute left-0 right-0 top-full mt-2 rounded-lg border border-gray-200 bg-white shadow-lg z-50 overflow-hidden">
                  {navSearchResults.map((item) => (
                    <button
                      key={item.path}
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 focus:outline-none focus:bg-gray-50"
                      onClick={() => openNavSearchResult(item.path)}
                    >
                      <span className="font-medium text-gray-800">{item.label}</span>
                      <span className="ml-2 text-xs text-gray-400">{item.group}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex-1" />

          <div className="flex items-center space-x-1">
            {showWorkspaceSwitch && (
              <button
                type="button"
                onClick={() => navigate(workspaceSwitchTarget)}
                title={workspaceSwitchLabel}
                aria-label={workspaceSwitchLabel}
                className="hidden sm:flex h-8 items-center gap-1.5 px-3 rounded-lg text-xs font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
              >
                <AppIcon className={`fas ${workspaceSwitchIcon} text-[12px]`} />
                <span>{workspaceSwitchLabel}</span>
              </button>
            )}
            {isPortalAccount && <NotificationBell />}
            <button
              type="button"
              onClick={() => setShowFeedback(true)}
              title="问题反馈"
              aria-label="问题反馈"
              className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-blue-600 transition-colors"
            >
              <AppIcon className="fas fa-comment-medical text-[13px]" />
            </button>
            {!isPortalAccount && (
              <Link to="/notifications" className="relative w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors" aria-label="通知">
                <AppIcon className="fas fa-bell text-[13px]" />
                {unreadCount > 0 && <span className="absolute top-0.5 right-0.5 w-[14px] h-[14px] bg-red-500 text-white text-[9px] rounded-full flex items-center justify-center leading-none font-medium">{unreadCount > 99 ? '99+' : unreadCount}</span>}
              </Link>
            )}
            <button className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors" aria-label="日程">
              <AppIcon className="fas fa-calendar-check text-[13px]" />
            </button>
            {!isPortalAccount && !isPortalRoute && (
              <button onClick={() => navigate('/system-settings')} className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors" aria-label="系统设置">
                <AppIcon className="fas fa-cog text-[13px]" />
              </button>
            )}

            <div className="relative ml-2">
              <button onClick={() => setShowUserMenu(!showUserMenu)} className="flex items-center space-x-2 py-1 px-2 rounded-lg hover:bg-gray-50 transition-colors">
                <UserAvatar key={profileRevision} user={user} size="sm" />
                <div className="hidden sm:block text-left">
                  <div className="text-sm text-gray-800 font-medium leading-tight">{user?.name || '用户'}</div>
                  <div className="text-[10px] text-blue-500 leading-tight">{roleLabels[user?.role || ''] || '用户'}</div>
                </div>
                <AppIcon className="fas fa-chevron-down text-[10px] text-gray-300 hidden sm:inline" />
              </button>
              {showUserMenu && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowUserMenu(false)} />
                  <div className="absolute right-0 mt-2 w-56 bg-white rounded-xl shadow-lg py-1 z-20 border border-gray-100">
                    <div className="px-4 py-3 border-b border-gray-100">
                      <p className="text-sm font-medium text-gray-800">{user?.name}</p>
                      <p className="text-xs text-gray-500">{user?.email}</p>
                      <p className="text-xs text-blue-600 mt-1">{roleLabels[user?.role || ''] || user?.role || '未设置角色'}</p>
                    </div>
                    {showWorkspaceSwitch && (
                      <Link to={workspaceSwitchTarget} className="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors" onClick={() => setShowUserMenu(false)}><AppIcon className={`fas ${workspaceSwitchIcon} mr-2 text-gray-400`} />{workspaceSwitchLabel}</Link>
                    )}
                    {!isPortalAccount && !isPortalRoute && (
                      <Link to="/system-settings" className="block px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors" onClick={() => setShowUserMenu(false)}><AppIcon className="fas fa-cog mr-2 text-gray-400" />系统设置</Link>
                    )}
                    <button onClick={handleLogout} className="w-full text-left px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 transition-colors"><AppIcon className="fas fa-sign-out-alt mr-2" />退出登录</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      <aside className={`fixed left-0 top-14 bottom-0 ${sidebarW} bg-white border-r border-gray-200 z-40 flex flex-col overflow-hidden transition-all duration-200
        ${mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}>
        <nav ref={sidebarRef} className={`${collapsed ? 'px-1.5' : 'px-3'} py-2 flex-1 min-h-0 overflow-y-auto overflow-x-hidden sidebar-scroll`}>
          {visibleGroups.map((group) => (
            <div key={group.title} className="mb-0.5">
              {!collapsed && (
                <button onClick={() => setCollapsedGroups({ ...collapsedGroups, [group.title]: !collapsedGroups[group.title] })} className="w-full flex items-center justify-between px-2 py-2 text-[11px] font-semibold text-gray-400 uppercase tracking-wider hover:text-gray-500 transition-colors">
                  <span>{group.title}</span><AppIcon className={`fas fa-chevron-${collapsedGroups[group.title] ? 'right' : 'down'} text-[9px]`} />
                </button>
              )}
              {collapsed && <div className="h-px bg-gray-100 my-1.5 mx-1"></div>}
              {(collapsed || !collapsedGroups[group.title]) && <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      title={collapsed ? item.label : undefined}
                      onClick={() => setMobileSidebarOpen(false)}
                      className={`hpt-nav-link flex items-center ${collapsed ? 'justify-center px-1.5' : 'px-3 gap-3'} py-2 rounded-lg transition-all group ${isActive(item.path) ? 'hpt-nav-active text-blue-600 font-semibold' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'}`}
                    >
                      <AppIcon className={`hpt-nav-icon fas ${item.icon} ${collapsed ? 'is-collapsed' : ''}`} />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </Link>
                  </li>
                ))}
              </ul>}
            </div>
          ))}
        </nav>
        <div className={`hpt-sidebar-footer flex-shrink-0 border-t border-gray-100 bg-white ${collapsed ? 'px-1.5' : 'px-3'} py-2`}>
          <button onClick={() => setCollapsed(!collapsed)} className={`hpt-collapse-button w-full flex items-center ${collapsed ? 'justify-center' : 'px-3 space-x-2'} py-2 rounded-lg text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors`} aria-label={collapsed ? '展开菜单' : '收起菜单'}>
            <AppIcon className={`fas fa-angles-${collapsed ? 'right' : 'left'} text-xs`} />
            {!collapsed && <span className="text-xs">收起菜单</span>}
          </button>
        </div>
      </aside>

      <main
        className={`hpt-main ${mainMl} mt-14 p-3 md:p-5 min-h-screen transition-all duration-200 md:translate-x-0`}
        style={{
          ...(assistantReserve ? { paddingRight: assistantReserve } : {}),
        }}
      >
        {children}
      </main>

      <FeedbackDialog open={showFeedback} onClose={() => setShowFeedback(false)} />

    </div>
    <AIAssistant />
    </>
  );
};

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const insidePersistentShell = React.useContext(LayoutNestingContext);
  if (insidePersistentShell) return <>{children}</>;

  return (
    <LayoutNestingContext.Provider value={true}>
      <LayoutShell>{children}</LayoutShell>
    </LayoutNestingContext.Provider>
  );
};
