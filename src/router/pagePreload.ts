type PageLoader = () => Promise<unknown>;

const routeLoaders: Array<[RegExp, PageLoader]> = [
  [/^\/hrm\//, () => import('../pages/p-hrm')],
  [/^\/talent-intelligence$/, () => import('../pages/p-talent_intelligence')],
  [/^\/headcount-management$/, () => import('../pages/p-headcount-management')],
  [/^\/organization$/, () => import('../pages/p-organization')],
  [/^\/attendance-timesheet$/, () => import('../pages/p-attendance-timesheet')],
  [/^\/attendance-punches$/, () => import('../pages/p-attendance-punches')],
  [/^\/performance-center$/, () => import('../pages/p-performance-center')],
  [/^\/performance-indicators$/, () => import('../pages/p-performance-indicators')],
  [/^\/performance-participants$/, () => import('../pages/p-performance-participants')],
  [/^\/people-analytics$/, () => import('../pages/p-people-analytics-extension')],
  [/^\/continuous-feedback$/, () => import('../pages/p-continuous-feedback')],
  [/^\/talent-strategy$/, () => import('../pages/p-talent-strategy-extension')],
  [/^\/analytics-suite$/, () => import('../pages/p-analytics-extension')],
  [/^\/intelligence-suite$/, () => import('../pages/p-intelligence-extension')],
  [/^\/collaboration-suite$/, () => import('../pages/p-collaboration-extension')],
  [/^\/workforce-suite$/, () => import('../pages/p-workforce-extension')],
  [/^\/integration-suite$/, () => import('../pages/p-integration-extension')],
  [/^\/mobile-suite$/, () => import('../pages/p-mobile-extension')],
  [/^\/security-suite$/, () => import('../pages/p-security-extension')],
  [/^\/attendance-stats$/, () => import('../pages/p-attendance_stats')],
  [/^\/attendance-sync$/, () => import('../pages/p-attendance-sync')],
  [/^\/attendance-policy$/, () => import('../pages/p-attendance-policy')],
  [/^\/performance-review$/, () => import('../pages/p-performance_review')],
  [/^\/approval-center/, () => import('../pages/p-approval_center')],
  [/^\/notifications$/, () => import('../pages/p-notifications')],
  [/^\/operation-logs$/, () => import('../pages/p-operation_logs')],
  [/^\/salary-profiles$/, () => import('../pages/p-salary_profiles')],
  [/^\/employee-requests$/, () => import('../pages/p-employee_requests')],
  [/^\/feedback$/, () => import('../pages/p-feedback')],
  [/^\/analytics$/, () => import('../pages/p-analytics')],
  [/^\/training-center$/, () => import('../pages/p-training-center')],
  [/^\/learning-paths$/, () => import('../pages/p-learning-paths')],
  [/^\/exam-/, () => import('../pages/p-exam-center')],
  [/^\/platform\/tenants$/, () => import('../pages/p-platform-tenants')],
];

const loadedPaths = new Set<string>();

const scheduleIdle = (task: () => void) => {
  if (typeof window === 'undefined') return;
  const run = () => task();
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(run, { timeout: 1800 });
  } else {
    globalThis.setTimeout(run, 240);
  }
};

export const preloadRouteForPath = (path: string) => {
  if (!path || loadedPaths.has(path)) return;
  const match = routeLoaders.find(([pattern]) => pattern.test(path));
  if (!match) return;
  loadedPaths.add(path);
  scheduleIdle(() => {
    void match[1]().catch(() => {
      loadedPaths.delete(path);
    });
  });
};

export const preloadCommonRoutes = () => {
  [
    '/hrm/employees',
    '/hrm/contracts',
    '/hrm/probations',
    '/hrm/resignations',
    '/approval-center/pending',
    '/operation-logs',
  ].forEach(preloadRouteForPath);
};
