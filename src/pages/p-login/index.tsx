// @ts-nocheck

import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import { AnimatedCharacters } from '../../components/AnimatedCharacters';

import AppIcon from '../../components/AppIcon';

const DEFAULT_TENANT_SLUG = 'HPT-00000001';
const LAST_TENANT_SLUG_KEY = 'lastTenantSlug';

const getLastTenantSlug = () => {
  if (typeof window === 'undefined') return DEFAULT_TENANT_SLUG;
  const stored = localStorage.getItem(LAST_TENANT_SLUG_KEY)?.trim();
  return stored || DEFAULT_TENANT_SLUG;
};

const getPostLoginPath = (user: any) => {
  if (user?.accountType === 'employee_portal') return '/portal';
  if (user?.isPlatformAdmin) return '/platform/tenants';
  return '/home';
};

interface LoginFormData {
  tenantSlug: string;
  email: string;
  password: string;
  rememberMe: boolean;
}

type LoginMode = 'hrm' | 'portal';

interface RememberedUser {
  email: string;
  remember: boolean;
  timestamp: number;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const initialMode = (() => {
    if (typeof window === 'undefined') return 'hrm';
    return new URLSearchParams(window.location.search).get('mode') === 'portal' ? 'portal' : 'hrm';
  })();
  const [loginMode, setLoginMode] = useState<LoginMode>(initialMode);
  const [formData, setFormData] = useState<LoginFormData>({
    tenantSlug: getLastTenantSlug(),
    email: '',
    password: '',
    rememberMe: false
  });
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [showError, setShowError] = useState(false);
  const [focusedField, setFocusedField] = useState<'tenantSlug' | 'email' | 'password' | null>(null);

  // 设置页面标题
  useEffect(() => {
    const originalTitle = document.title;
    document.title = loginMode === 'portal' ? '员工门户登录 - 恒聘通' : '管理后台登录 - 恒聘通';
    
    // 检查是否已登录；两套账号体系互相切换时先退出当前身份。
    if (authUtils.isAuthenticated()) {
      const user = authUtils.getUser();
      const isPortalAccount = user?.accountType === 'employee_portal';
      if ((loginMode === 'portal') !== isPortalAccount) {
        authUtils.logout();
        return () => { document.title = originalTitle; };
      }
      if (user?.mustChangePassword) {
        navigate('/change-password', { replace: true });
        return;
      }
      navigate(getPostLoginPath(user), { replace: true });
    }

    // 检测 token 过期跳转（由 api.ts 401 处理自动带上 ?expired=1）
    const params = new URLSearchParams(window.location.search);
    if (params.get('expired') === '1') {
      showErrorMessage('登录已过期，请重新登录');
      window.history.replaceState({}, '', `/login?mode=${loginMode}`);
    }
    
    return () => { document.title = originalTitle; };
  }, [navigate, loginMode]);

  // 检查记住的用户信息
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const rememberedUser = localStorage.getItem(`rememberedUser:${loginMode}`);
      if (rememberedUser) {
        try {
          const userData: RememberedUser = JSON.parse(rememberedUser);
          if (userData.remember && userData.email) {
            setFormData(prev => ({
              ...prev,
              email: userData.email,
              rememberMe: true
            }));
          }
        } catch (e) {
          console.error('解析记住的用户信息失败:', e);
        }
      } else {
        setFormData(prev => ({
          ...prev,
          email: '',
          password: '',
          rememberMe: false
        }));
      }
    }
  }, [loginMode]);

  const showErrorMessage = (message: string) => {
    setErrorMessage(message);
    setShowError(true);
    setTimeout(() => setShowError(false), 5000);
  };

  const hideErrorMessage = () => {
    setShowError(false);
  };

  const handleTogglePassword = () => {
    setShowPassword(!showPassword);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const { email, password, rememberMe } = formData;
    const tenantSlug = formData.tenantSlug.trim();

    if (!tenantSlug) {
      showErrorMessage('请输入企业编码');
      return;
    }
    if (tenantSlug.toLowerCase() === 'platform') {
      showErrorMessage('平台管理员请使用独立的平台登录入口');
      return;
    }

    if (!email.trim()) {
      showErrorMessage(loginMode === 'portal' ? '请输入员工编号 / OA登录名 / OA人员ID' : '请输入管理账号');
      return;
    }

    if (!password.trim()) {
      showErrorMessage('请输入密码');
      return;
    }

    hideErrorMessage();
    setIsLoading(true);

    try {
      const response = await authApi.login(email, password, loginMode === 'portal' ? 'employee_portal' : 'hrm', tenantSlug);
      
      authUtils.setToken(response.token);
      authUtils.setUser(response.user);

      if (typeof window !== 'undefined') {
        localStorage.setItem(LAST_TENANT_SLUG_KEY, tenantSlug);
        if (rememberMe) {
          localStorage.setItem(`rememberedUser:${loginMode}`, JSON.stringify({
            email: email,
            remember: true,
            timestamp: new Date().getTime()
          }));
        }
      }

      if (response.user?.mustChangePassword) {
        setTimeout(() => navigate('/change-password'), 1200);
        return;
      }
      setTimeout(() => navigate(getPostLoginPath(response.user)), 1200);
    } catch (error) {
      setIsLoading(false);
      const errorMessage = error instanceof Error ? error.message : '登录失败，请检查账号和密码';
      showErrorMessage(errorMessage);
    }
  };

  const handleForgotPassword = () => {
    showErrorMessage(loginMode === 'portal' ? '请联系 HR 重置员工门户密码' : '请联系管理员重置后台密码');
  };

  const switchMode = (mode: LoginMode) => {
    hideErrorMessage();
    setLoginMode(mode);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSubmit(e as any);
    }
    if (e.key === 'Escape' && showError) {
      hideErrorMessage();
    }
  };

  const handleEmailFocus = () => {
    hideErrorMessage();
    setFocusedField('email');
  };

  const handleTenantSlugFocus = () => {
    hideErrorMessage();
    setFocusedField('tenantSlug');
  };

  const handlePasswordFocus = () => {
    hideErrorMessage();
    setFocusedField('password');
  };

  const handleInputBlur = () => {
    setFocusedField(null);
  };

  return (
    <div className="hpt-auth auth-minimal min-h-screen bg-white flex items-center justify-center px-5 py-10">
      <main className="auth-composition">
        <aside className="auth-character-stage" aria-hidden="true">
          <div className="auth-character-canvas">
            <AnimatedCharacters
              isTyping={focusedField === 'password'}
              showPassword={showPassword}
              passwordLength={formData.password.length}
            />
          </div>
          <div className="auth-character-floor" />
        </aside>

        <section className="auth-form-panel">
          <header className="mb-9 text-center">
            <h1 className="auth-title text-gray-950">欢迎回来</h1>
            <p className="auth-subtitle mt-3">
              {loginMode === 'portal' ? '进入学习与考试门户' : '进入 HRM 管理后台'}
            </p>
          </header>

          <div className="grid grid-cols-2 gap-2 rounded-lg bg-gray-100 p-1 mb-5">
            <button
              type="button"
              onClick={() => switchMode('hrm')}
              className={`h-10 rounded-md text-sm font-medium transition-colors ${loginMode === 'hrm' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
            >
              管理后台
            </button>
            <button
              type="button"
              onClick={() => switchMode('portal')}
              className={`h-10 rounded-md text-sm font-medium transition-colors ${loginMode === 'portal' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
            >
              员工门户
            </button>
          </div>
          
          <div aria-live="polite" className={`${showError ? 'opacity-100 max-h-20 mb-5' : 'opacity-0 max-h-0 overflow-hidden'} auth-alert flex items-center px-4 py-3 transition-all duration-300 text-sm`}>
            <AppIcon className="fas fa-exclamation-circle mr-2" />
            <span>{errorMessage}</span>
          </div>
            
          <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} className="space-y-3.5">
            <div>
              <label htmlFor="tenantSlug" className="sr-only">企业编码</label>
              <input
                type="text"
                id="tenantSlug"
                name="tenantSlug"
                value={formData.tenantSlug}
                onChange={handleInputChange}
                onFocus={handleTenantSlugFocus}
                onBlur={handleInputBlur}
                className="auth-input w-full"
                placeholder="企业编码，例如 HPT-00000001"
                autoComplete="organization"
                autoCapitalize="none"
                spellCheck={false}
                required
              />
            </div>

            <div>
              <label htmlFor="email" className="sr-only">{loginMode === 'portal' ? '员工编号 / OA登录名 / OA人员ID' : '管理账号'}</label>
              <input
                type="text"
                id="email"
                name="email"
                value={formData.email}
                onChange={handleInputChange}
                onFocus={handleEmailFocus}
                onBlur={handleInputBlur}
                className="auth-input w-full"
                placeholder={loginMode === 'portal' ? '员工编号 / OA登录名 / OA人员ID' : '邮箱 / 姓名'}
                autoComplete="username"
                required
              />
            </div>
            
            <div className="relative">
              <label htmlFor="password" className="sr-only">密码</label>
              <input
                type={showPassword ? 'text' : 'password'}
                id="password"
                name="password"
                value={formData.password}
                onChange={handleInputChange}
                onFocus={handlePasswordFocus}
                onBlur={handleInputBlur}
                className="auth-input w-full pr-12"
                placeholder="密码"
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                onClick={handleTogglePassword}
                className="auth-eye absolute right-3 top-1/2 -translate-y-1/2"
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
              >
                <AppIcon className={`fas ${showPassword ? 'fa-eye-slash' : 'fa-eye'} text-sm`} />
              </button>
            </div>
            
            <div className="flex items-center justify-between pt-1 pb-3">
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  name="rememberMe"
                  checked={formData.rememberMe}
                  onChange={handleInputChange}
                  className="auth-checkbox"
                />
                <span className="text-sm text-gray-600">记住登录 30 天</span>
              </label>
              <button
                type="button"
                onClick={handleForgotPassword}
                className="auth-link text-sm"
              >
                忘记密码？
              </button>
            </div>
              
            <button
              type="submit"
              disabled={isLoading}
              className="auth-submit w-full"
            >
              {isLoading ? <><AppIcon className="fas fa-spinner fa-spin mr-2" />正在登录</> : (loginMode === 'portal' ? '登录员工门户' : '登录管理后台')}
            </button>
          </form>

          <div className="mt-5 rounded-lg border border-blue-100 bg-blue-50/70 px-4 py-3 text-center text-sm text-slate-600">
            还没有企业账号？
            <Link to="/enterprise-application" className="ml-1 font-medium text-blue-600 hover:text-blue-700">
              申请企业服务
            </Link>
          </div>
            
          <footer className="mt-16 text-center text-[12px] text-gray-400">
            <div>
              登录即表示同意
              <a href="/legal/terms" target="_blank" rel="noreferrer" className="mx-1 text-gray-500 hover:text-blue-600">
                《服务条款》
              </a>
              和
              <a href="/legal/privacy" target="_blank" rel="noreferrer" className="ml-1 text-gray-500 hover:text-blue-600">
                《隐私政策》
              </a>
            </div>
            <div className="mt-2">
              <span>恒聘通 HRM</span>
              <span className="mx-2">·</span>
              <Link to="/platform/login" className="text-gray-500 hover:text-blue-600">
                平台后台
              </Link>
            </div>
          </footer>
        </section>
      </main>
    </div>
  );
}
