import { type FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AppIcon from '../../components/AppIcon';
import { authApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';

const REMEMBERED_PLATFORM_ACCOUNT_KEY = 'rememberedPlatformAdmin';

export default function PlatformLoginPage() {
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const originalTitle = document.title;
    document.title = '平台后台登录 - 恒聘通';

    const user = authUtils.getUser();
    if (authUtils.isAuthenticated() && user?.isPlatformAdmin) {
      navigate('/platform/tenants', { replace: true });
      return () => { document.title = originalTitle; };
    }
    if (authUtils.isAuthenticated() && !user?.isPlatformAdmin) {
      authUtils.logout();
    }

    const remembered = localStorage.getItem(REMEMBERED_PLATFORM_ACCOUNT_KEY);
    if (remembered) {
      try {
        const parsed = JSON.parse(remembered);
        if (parsed?.identifier) {
          setIdentifier(parsed.identifier);
          setRemember(true);
        }
      } catch {}
    }

    return () => { document.title = originalTitle; };
  }, [navigate]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const account = identifier.trim();
    if (!account) {
      setError('请输入平台管理员账号');
      return;
    }
    if (!password.trim()) {
      setError('请输入密码');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const response = await authApi.platformLogin(account, password);
      authUtils.setToken(response.token);
      authUtils.setUser(response.user);
      if (remember) {
        localStorage.setItem(REMEMBERED_PLATFORM_ACCOUNT_KEY, JSON.stringify({ identifier: account }));
      } else {
        localStorage.removeItem(REMEMBERED_PLATFORM_ACCOUNT_KEY);
      }
      if (response.user?.mustChangePassword) {
        navigate('/change-password', { replace: true });
        return;
      }
      navigate('/platform/tenants', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请检查账号和密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center px-5 py-10">
      <main className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-lg bg-blue-500 text-white flex items-center justify-center shadow-lg shadow-blue-950/30">
            <AppIcon className="fas fa-building-shield text-lg" />
          </div>
          <h1 className="text-2xl font-semibold tracking-normal">恒聘通平台后台</h1>
          <p className="mt-2 text-sm text-slate-400">SaaS 企业客户与订阅管理</p>
        </div>

        <form onSubmit={submit} className="rounded-lg border border-white/10 bg-white/[0.06] p-5 shadow-2xl shadow-black/20 space-y-4">
          {error && (
            <div className="rounded-md border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-100">
              <AppIcon className="fas fa-circle-exclamation mr-2" />
              {error}
            </div>
          )}

          <div>
            <label htmlFor="platformIdentifier" className="sr-only">平台管理员账号</label>
            <input
              id="platformIdentifier"
              type="text"
              value={identifier}
              onChange={event => setIdentifier(event.target.value)}
              className="h-11 w-full rounded-md border border-white/10 bg-slate-900/80 px-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-blue-400"
              placeholder="平台管理员邮箱 / 姓名"
              autoComplete="username"
              required
            />
          </div>

          <div className="relative">
            <label htmlFor="platformPassword" className="sr-only">密码</label>
            <input
              id="platformPassword"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={event => setPassword(event.target.value)}
              className="h-11 w-full rounded-md border border-white/10 bg-slate-900/80 px-3 pr-11 text-sm text-white outline-none placeholder:text-slate-500 focus:border-blue-400"
              placeholder="密码"
              autoComplete="current-password"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(value => !value)}
              className="absolute right-2 top-1/2 h-8 w-8 -translate-y-1/2 rounded-md text-slate-400 hover:bg-white/10 hover:text-white"
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
            >
              <AppIcon className={`fas ${showPassword ? 'fa-eye-slash' : 'fa-eye'}`} />
            </button>
          </div>

          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2 text-slate-300">
              <input
                type="checkbox"
                checked={remember}
                onChange={event => setRemember(event.target.checked)}
                className="h-4 w-4 rounded border-white/20 bg-slate-900"
              />
              记住账号
            </label>
            <Link to="/login" className="text-blue-300 hover:text-blue-200">
              企业登录
            </Link>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="h-11 w-full rounded-md bg-blue-500 text-sm font-medium text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (
              <>
                <AppIcon className="fas fa-spinner fa-spin mr-2" />
                正在登录
              </>
            ) : '进入平台后台'}
          </button>
        </form>

        <footer className="mt-5 text-center text-xs text-slate-500">
          登录即表示同意
          <a href="/legal/terms" target="_blank" rel="noreferrer" className="mx-1 text-slate-300 hover:text-blue-200">
            《服务条款》
          </a>
          和
          <a href="/legal/privacy" target="_blank" rel="noreferrer" className="ml-1 text-slate-300 hover:text-blue-200">
            《隐私政策》
          </a>
        </footer>
      </main>
    </div>
  );
}
