import { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { authUtils } from '../utils/auth';
import { User } from '../utils/api';

import AppIcon from './AppIcon';
interface ProtectedRouteProps {
  children: ReactNode;
  requiredRole?: User['role'];
}

/**
 * 鉴权守卫。
 * - 未登录直接跳登录页（用 Navigate，避免渲染闪烁）
 * - 权限不足显示 403（不弹 alert，UX 更友好）
 */
export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRole,
}) => {
  const location = useLocation();
  const isPortalRoute = location.pathname.startsWith('/portal');
  const isPlatformRoute = location.pathname.startsWith('/platform');

  if (!authUtils.isAuthenticated()) {
    // 把当前 url 带在 state 里，登录后可跳回
    const loginPath = isPlatformRoute ? '/platform/login' : `/login?mode=${isPortalRoute ? 'portal' : 'hrm'}`;
    return <Navigate to={loginPath} replace state={{ from: location.pathname + location.search }} />;
  }

  const user = authUtils.getUser();
  const isPortalAccount = user?.accountType === 'employee_portal';
  if (user?.mustChangePassword && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  if (isPortalAccount && !isPortalRoute && location.pathname !== '/change-password') {
    return <Navigate to="/login?mode=hrm" replace />;
  }

  if (user?.isPlatformAdmin && !isPlatformRoute && location.pathname !== '/change-password') {
    return <Navigate to="/platform/tenants" replace />;
  }

  if (!user?.isPlatformAdmin && isPlatformRoute) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <AppIcon className="fas fa-lock text-4xl text-gray-300 mb-3" />
          <h2 className="text-lg font-bold text-gray-800 mb-1">无权访问平台后台</h2>
          <p className="text-sm text-gray-500">请使用平台管理员账号登录。</p>
        </div>
      </div>
    );
  }

  if (!isPortalAccount && isPortalRoute) {
    return <Navigate to="/login?mode=portal" replace />;
  }

  if (requiredRole && !authUtils.hasRole(requiredRole)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <AppIcon className="fas fa-lock text-4xl text-gray-300 mb-3" />
          <h2 className="text-lg font-bold text-gray-800 mb-1">无权访问</h2>
          <p className="text-sm text-gray-500">您的角色无权查看此页面，请联系管理员申请权限。</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
