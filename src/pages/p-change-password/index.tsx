// @ts-nocheck

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import AppIcon from '../../components/AppIcon';

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const user = authUtils.getUser();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const nextPath = (nextUser: any) => nextUser?.accountType === 'employee_portal' ? '/portal' : '/home';

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!currentPassword || !newPassword || !confirmPassword) {
      setError('请完整填写当前密码和新密码');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }
    if (newPassword.length < 8) {
      setError('新密码长度至少 8 位');
      return;
    }

    setSubmitting(true);
    try {
      const response = await authApi.changePassword(
        currentPassword,
        newPassword,
        user?.accountType === 'employee_portal' ? 'employee_portal' : 'hrm'
      );
      authUtils.setToken(response.token);
      authUtils.setUser(response.user);
      navigate(nextPath(response.user), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '修改密码失败，请重试');
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-5 py-10">
      <main className="w-full max-w-md bg-white border border-gray-100 rounded-lg shadow-sm p-8">
        <div className="w-12 h-12 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center mb-5">
          <AppIcon className="fas fa-key text-lg" />
        </div>
        <h1 className="text-xl font-bold text-gray-950">首次登录修改密码</h1>
        <p className="mt-2 text-sm text-gray-500 leading-6">
          {user?.name ? `${user.name}，` : ''}为了账号安全，请先设置一个新的登录密码。
        </p>

        {error && (
          <div className="mt-5 px-4 py-3 rounded-lg bg-red-50 text-red-600 text-sm flex items-start gap-2">
            <AppIcon className="fas fa-circle-exclamation mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="currentPassword" className="block text-sm font-medium text-gray-700 mb-1.5">当前密码</label>
            <input
              id="currentPassword"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400"
              autoComplete="current-password"
              required
            />
          </div>
          <div>
            <label htmlFor="newPassword" className="block text-sm font-medium text-gray-700 mb-1.5">新密码</label>
            <input
              id="newPassword"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400"
              autoComplete="new-password"
              required
            />
          </div>
          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-1.5">确认新密码</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400"
              autoComplete="new-password"
              required
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full h-11 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-60 transition-colors"
          >
            {submitting ? '提交中...' : '确认修改'}
          </button>
        </form>
      </main>
    </div>
  );
}
