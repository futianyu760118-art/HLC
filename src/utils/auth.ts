// 用户认证和状态管理工具
import type { AuthUser, UserRole } from '../types/auth';

export const AUTH_STORAGE_MODE = 'localStorage-bearer-first-cohort' as const;
export const AUTH_TOKEN_STORAGE_KEY = 'token' as const;
export const AUTH_USER_STORAGE_KEY = 'user' as const;

const notifyAuthChanged = () => {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(new Event('hpt-auth-changed'));
  } catch {}
};

export const authUtils = {
  // 保存token
  setToken(token: string): void {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    notifyAuthChanged();
  },

  // 获取token
  getToken(): string | null {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  },

  // 删除token
  removeToken(): void {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    notifyAuthChanged();
  },

  // 保存用户信息
  setUser(user: AuthUser): void {
    localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify(user));
    notifyAuthChanged();
  },

  // 获取用户信息
  getUser(): AuthUser | null {
    const userStr = localStorage.getItem(AUTH_USER_STORAGE_KEY);
    if (!userStr) return null;
    try {
      return JSON.parse(userStr) as AuthUser;
    } catch {
      return null;
    }
  },

  getSessionScopeKey(): string {
    const user = this.getUser();
    const token = this.getToken();
    if (!token && !user) return 'anonymous';
    return [
      user?.tenantId || 'no-tenant',
      user?.id || user?.employeeId || user?.employee_id || 'no-user',
      user?.accountType || 'hrm',
      user?.role || 'unknown-role',
      token ? 'authenticated' : 'no-token',
    ].join(':');
  },

  // 删除用户信息
  removeUser(): void {
    localStorage.removeItem(AUTH_USER_STORAGE_KEY);
    notifyAuthChanged();
  },

  // 检查是否已登录
  isAuthenticated(): boolean {
    return !!this.getToken();
  },

  // 登出
  logout(): void {
    this.removeToken();
    this.removeUser();
  },

  // 检查用户权限
  hasRole(requiredRole: UserRole): boolean {
    const user = this.getUser();
    if (!user) return false;

    const roleHierarchy: Record<UserRole, number> = {
      platform_admin: 8,
      admin: 7,
      executive: 6,
      hr_admin: 5,
      manager: 4,
      finance: 3,
      recruiter: 2,
      employee: 1,
      viewer: 0,
    };

    return user.role ? roleHierarchy[user.role] >= roleHierarchy[requiredRole] : false;
  },
};
