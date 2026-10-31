import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useEffect, lazy, Suspense } from 'react';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { Layout } from '../components/Layout';
import { authUtils } from '../utils/auth';

import P_login from '../pages/p-login';
import P_enterprise_application from '../pages/p-enterprise-application';
import P_legal_document from '../pages/p-legal-document';
import P_platform_login from '../pages/p-platform-login';
import P_change_password from '../pages/p-change-password';
import P_home from '../pages/p-home';
import P_resume_manage from '../pages/p-resume_manage';
import P_resume_detail from '../pages/p-resume_detail';
import P_job_manage from '../pages/p-job_manage';
import P_job_detail from '../pages/p-job_detail';
import P_interview_manage from '../pages/p-interview_manage';
import P_interview_detail from '../pages/p-interview_detail';
import P_interview_room from '../pages/p-interview_room';
import P_interview_join from '../pages/p-interview_join';
import P_report from '../pages/p-report';
import P_system_settings from '../pages/p-system_settings';
import P_ai_model_settings from '../pages/p-ai_model_settings';
import P_resume_upload from '../pages/p-resume_upload';
import P_job_create from '../pages/p-job_create';
import P_interview_create from '../pages/p-interview_create';
// Lazy-loaded heavy pages (improves initial load performance)
const P_hrm_module = lazy(() => import('../pages/p-hrm'));
const P_attendance_stats = lazy(() => import('../pages/p-attendance_stats'));
const P_attendance_sync = lazy(() => import('../pages/p-attendance-sync'));
const P_attendance_policy = lazy(() => import('../pages/p-attendance-policy'));
const P_performance_review = lazy(() => import('../pages/p-performance_review'));
const P_organization = lazy(() => import('../pages/p-organization'));
const P_attendance_timesheet = lazy(() => import('../pages/p-attendance-timesheet'));
const P_attendance_punches = lazy(() => import('../pages/p-attendance-punches'));
const P_performance_center = lazy(() => import('../pages/p-performance-center'));
const P_performance_indicators = lazy(() => import('../pages/p-performance-indicators'));
const P_performance_participants = lazy(() => import('../pages/p-performance-participants'));
const P_approval_center = lazy(() => import('../pages/p-approval_center'));
const P_notifications = lazy(() => import('../pages/p-notifications'));
const P_operation_logs = lazy(() => import('../pages/p-operation_logs'));
const P_salary_profiles = lazy(() => import('../pages/p-salary_profiles'));
const P_employee_requests = lazy(() => import('../pages/p-employee_requests'));
const P_feedback = lazy(() => import('../pages/p-feedback'));
const P_todos = lazy(() => import('../pages/p-todos'));
const P_talent_intelligence = lazy(() => import('../pages/p-talent_intelligence'));
const P_headcount_management = lazy(() => import('../pages/p-headcount-management'));
const P_people_analytics_extension = lazy(() => import('../pages/p-people-analytics-extension'));
const P_continuous_feedback = lazy(() => import('../pages/p-continuous-feedback'));
const P_talent_strategy_extension = lazy(() => import('../pages/p-talent-strategy-extension'));
const P_analytics_extension = lazy(() => import('../pages/p-analytics-extension'));
const P_intelligence_extension = lazy(() => import('../pages/p-intelligence-extension'));
const P_collaboration_extension = lazy(() => import('../pages/p-collaboration-extension'));
const P_workforce_extension = lazy(() => import('../pages/p-workforce-extension'));
const P_integration_extension = lazy(() => import('../pages/p-integration-extension'));
const P_mobile_extension = lazy(() => import('../pages/p-mobile-extension'));
const P_security_extension = lazy(() => import('../pages/p-security-extension'));
const P_platform_tenants = lazy(() => import('../pages/p-platform-tenants'));
// 培训+考试：管理侧专用页面
const P_learning_paths = lazy(() => import('../pages/p-learning-paths'));
const P_competency = lazy(() => import('../pages/p-competency'));
const P_pk_seasons = lazy(() => import('../pages/p-pk-seasons'));
const P_analytics = lazy(() => import('../pages/p-analytics'));
const P_training_center = lazy(() => import('../pages/p-training-center'));
const P_course_categories = lazy(() => import('../pages/p-course-categories'));
const P_exam_center = lazy(() => import('../pages/p-exam-center'));
const P_exam_papers = lazy(() => import('../pages/p-exam-papers'));
const P_exam_tasks = lazy(() => import('../pages/p-exam-tasks'));
const P_exam_attempts = lazy(() => import('../pages/p-exam-attempts'));
const P_exam_generate = lazy(() => import('../pages/p-exam-generate'));
const P_course_edit = lazy(() => import('../pages/p-course-edit'));
const P_exam_task_progress = lazy(() => import('../pages/p-exam-task-progress'));
// 培训+考试：员工门户
const P_portal_home = lazy(() => import('../pages/p-portal-home'));
const P_portal_my_courses = lazy(() => import('../pages/p-portal-my-courses'));
const P_portal_my_exams = lazy(() => import('../pages/p-portal-my-exams'));
const P_portal_my_profile = lazy(() => import('../pages/p-portal-my-profile'));
const P_portal_learning_paths = lazy(() => import('../pages/p-portal-learning-paths'));
const P_portal_wrong_questions = lazy(() => import('../pages/p-portal-wrong-questions'));
const P_portal_competency = lazy(() => import('../pages/p-portal-competency'));
const P_portal_points = lazy(() => import('../pages/p-portal-points'));
const P_portal_certificates = lazy(() => import('../pages/p-portal-certificates'));
const P_portal_pk = lazy(() => import('../pages/p-portal-pk'));
const P_portal_shop = lazy(() => import('../pages/p-portal-shop'));
const P_bigscreen = lazy(() => import('../pages/p-bigscreen'));
const P_portal_course = lazy(() => import('../pages/p-portal-course'));
const P_portal_learn = lazy(() => import('../pages/p-portal-learn'));
const P_portal_exam_intro = lazy(() => import('../pages/p-portal-exam-intro'));
const P_portal_exam_take = lazy(() => import('../pages/p-portal-exam-take'));
const P_portal_exam_result = lazy(() => import('../pages/p-portal-exam-result'));
import NotFoundPage from './NotFoundPage';
import ErrorPage from './ErrorPage';
import { preloadCommonRoutes, preloadRouteForPath } from './pagePreload';

import AppIcon from '../components/AppIcon';
const PageLoading = () => (
  <div className="min-h-[240px] rounded-lg border border-gray-100 bg-white px-6 py-8">
    <div className="flex items-center gap-3 text-sm text-gray-500">
      <AppIcon className="fas fa-spinner fa-spin text-base text-blue-400" />
      <span>正在加载模块...</span>
    </div>
    <div className="mt-6 space-y-3">
      <div className="h-4 w-44 rounded bg-gray-100" />
      <div className="h-3 w-full max-w-3xl rounded bg-gray-100" />
      <div className="h-3 w-2/3 rounded bg-gray-100" />
    </div>
  </div>
);

const wrapLazy = (Component: React.ComponentType) => (
  <Suspense fallback={<PageLoading />}>
    <Component />
  </Suspense>
);

const shelllessRoutePatterns = [
  /^\/$/,
  /^\/(?:login|register|change-password|enterprise-application|interview-join|bigscreen)(?:\/|$)/,
  /^\/legal(?:\/|$)/,
  /^\/platform(?:\/|$)/,
];

const shouldUsePersistentShell = (pathname: string) => (
  authUtils.isAuthenticated()
  && !shelllessRoutePatterns.some((pattern) => pattern.test(pathname))
);

function Listener() {
  const location = useLocation();
  useEffect(() => {
    const pageId = 'P-' + location.pathname.replace('/', '').toUpperCase();
    preloadRouteForPath(location.pathname);
    if (typeof window === 'object' && window.parent && window.parent.postMessage) {
      window.parent.postMessage({
        type: 'chux-path-change',
        pageId: pageId,
        pathname: location.pathname,
        search: location.search,
      }, '*');
    }
  }, [location]);

  useEffect(() => {
    preloadCommonRoutes();
  }, []);

  return shouldUsePersistentShell(location.pathname)
    ? <Layout><Outlet /></Layout>
    : <Outlet />;
}

function CanonicalRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search || ''}`} replace={true} />;
}

// 使用 createBrowserRouter 创建路由实例
const router = createBrowserRouter([
  {
    path: '/',
    element: <Listener />,
    children: [
      {
    path: '/',
    element: <Navigate to='/login' replace={true} />,
  },
      {
    path: '/login',
    element: (
      <ErrorBoundary>
        <P_login />
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/enterprise-application',
    element: (
      <ErrorBoundary>
        <P_enterprise_application />
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/legal/terms',
    element: <P_legal_document type="terms" />,
    errorElement: <ErrorPage />,
  },
      {
    path: '/legal/privacy',
    element: <P_legal_document type="privacy" />,
    errorElement: <ErrorPage />,
  },
      {
    path: '/platform/login',
    element: (
      <ErrorBoundary>
        <P_platform_login />
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/change-password',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_change_password />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/platform/tenants',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_platform_tenants)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/register',
    element: <Navigate to='/login?mode=hrm' replace={true} />,
    errorElement: <ErrorPage />,
  },
      {
    path: '/home',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_home />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/resume-manage',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_resume_manage />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/resume-detail',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_resume_detail />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/job-manage',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_job_manage />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/job-detail',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_job_detail />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/interview-manage',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_interview_manage />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/interview-detail',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_interview_detail />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/interview-room',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_interview_room />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/interview-join',
    element: (
      <ErrorBoundary>
        <P_interview_join />
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/report',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_report />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/system-settings',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_system_settings />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/ai-model-settings',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_ai_model_settings />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/resume-upload',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_resume_upload />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/job-create',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_job_create />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/interview-create',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          <P_interview_create />
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },

      {
    path: '/talent-intelligence',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_talent_intelligence)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/headcount-management',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_headcount_management)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/organization',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_organization)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/attendance-timesheet',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_attendance_timesheet)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/attendance-punches',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_attendance_punches)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/performance-center',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_performance_center)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/performance-participants',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_performance_participants)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/performance-indicators',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_performance_indicators)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/people-analytics',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_people_analytics_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/continuous-feedback',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_continuous_feedback)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/talent-strategy',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_talent_strategy_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/analytics-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_analytics_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/intelligence-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_intelligence_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/collaboration-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_collaboration_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/workforce-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_workforce_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/integration-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_integration_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/mobile-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_mobile_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/security-suite',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_security_extension)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/hrm/attendance-stats',
    element: <CanonicalRedirect to='/attendance-stats' />,
  },
      {
    path: '/hrm/employee-requests',
    element: <CanonicalRedirect to='/employee-requests' />,
  },
      {
    path: '/hrm/performance-reviews',
    element: <CanonicalRedirect to='/performance-review' />,
  },
      {
    path: '/hrm/salary-profiles',
    element: <CanonicalRedirect to='/salary-profiles' />,
  },
      {
    path: '/hrm/notifications',
    element: <CanonicalRedirect to='/notifications' />,
  },
      {
    path: '/hrm/operation-logs',
    element: <CanonicalRedirect to='/operation-logs' />,
  },
      {
    path: '/hrm/my-applications',
    element: <CanonicalRedirect to='/approval-center/my-applications' />,
  },
      {
    path: '/hrm/pending-approvals',
    element: <CanonicalRedirect to='/approval-center/pending' />,
  },
      {
    path: '/hrm/approval-records',
    element: <CanonicalRedirect to='/approval-center/records' />,
  },
      {
    path: '/hrm/:module',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_hrm_module)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/attendance-stats',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_attendance_stats)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
  {
    path: '/attendance-sync',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_attendance_sync)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/attendance-policy',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_attendance_policy)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/performance-review',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_performance_review)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/approval-center/:kind',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_approval_center)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/approval-center',
    element: <Navigate to='/approval-center/my-applications' replace={true} />,
  },
      {
    path: '/todos',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_todos)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/notifications',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_notifications)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/operation-logs',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_operation_logs)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/salary-profiles',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_salary_profiles)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/employee-requests',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_employee_requests)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
      {
    path: '/feedback',
    element: (
      <ErrorBoundary>
        <ProtectedRoute>
          {wrapLazy(P_feedback)}
        </ProtectedRoute>
      </ErrorBoundary>
    ),
    errorElement: <ErrorPage />,
  },
  // 培训+考试：管理侧专用页面
  {
    path: '/pk-seasons',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_pk_seasons)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/analytics',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_analytics)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/competency',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_competency)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/learning-paths',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_learning_paths)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/training-center',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_training_center)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/course-categories',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_course_categories)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/bigscreen',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_bigscreen)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-center',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_center)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-papers',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_papers)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-tasks',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_tasks)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-attempts',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_attempts)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-generate',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_generate)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/course-edit/:id',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_course_edit)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/exam-task-progress/:id',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_exam_task_progress)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  // 培训+考试：员工门户
  {
    path: '/portal',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_home)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/my-courses',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_my_courses)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/my-exams',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_my_exams)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/my-profile',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_my_profile)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/learning-paths',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_learning_paths)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/wrong-questions',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_wrong_questions)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/competency',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_competency)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/points',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_points)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/certificates',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_certificates)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/pk',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_pk)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/shop',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_shop)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/course/:id',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_course)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/course/:hourId/learn',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_learn)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/exam/:taskId',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_exam_intro)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/exam/take/:attemptId',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_exam_take)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
  {
    path: '/portal/exam/result/:attemptId',
    element: (<ErrorBoundary><ProtectedRoute>{wrapLazy(P_portal_exam_result)}</ProtectedRoute></ErrorBoundary>),
    errorElement: <ErrorPage />,
  },
      {
    path: '*',
    element: <NotFoundPage />,
  },
    ]
  }
]);

export default router;

