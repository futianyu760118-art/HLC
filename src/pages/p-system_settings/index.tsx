// @ts-nocheck
import { useState, useEffect } from 'react';
import { Layout } from '../../components/Layout';
import confirm from '../../components/ConfirmDialog';
import { miscApi } from '../../utils/api';
import { authUtils } from '../../utils/auth';
import { getConfiguredAvatarUrl, setConfiguredAvatarUrl } from '../../utils/profile';

import AppIcon from '../../components/AppIcon';
import UserAvatar from '../../components/UserAvatar';
const roleLabels: Record<string, string> = {
  admin: '系统管理员', hr_admin: 'HR管理员', recruiter: '招聘专员',
  manager: '部门负责人', employee: '普通员工', finance: '财务人员',
  executive: '高管/老板', viewer: '查看者',
};

const tabs = [
  { id: 'account', label: '账户与公司', icon: 'fa-building' },
  { id: 'function', label: '功能设置', icon: 'fa-toggle-on' },
  { id: 'notification', label: '通知设置', icon: 'fa-bell' },
  { id: 'security', label: '安全设置', icon: 'fa-shield-alt' },
];

const Toggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void; label: string; desc?: string }> = ({ checked, onChange, label, desc }) => (
  <div className="flex items-center justify-between py-3">
    <div>
      <div className="text-[13px] font-medium text-gray-700">{label}</div>
      {desc && <div className="text-xs text-gray-400 mt-0.5">{desc}</div>}
    </div>
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-label={`切换${label}`}
      aria-pressed={checked}
      className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${checked ? 'bg-blue-500' : 'bg-gray-200'}`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </button>
  </div>
);

export default function SystemSettingsPage() {
  const user = authUtils.getUser();
  const [activeTab, setActiveTab] = useState('account');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);
  const [settings, setSettings] = useState({
    // Company info
    companyName: '',
    companySize: '500-1000人',
    companyIndustry: '',
    contactEmail: '',
    contactPhone: '',
    companyAddress: '',
    companyWebsite: '',
    // Function settings
    autoResumeAnalysis: true,
    enableMultiDeptAttendance: true,
    enableOnboardingTasks: true,
    enableProbationReminder: true,
    enableContractReminder: true,
    enableSalaryEncryption: true,
    // Notification settings
    emailNotification: true,
    inSystemNotification: true,
    approvalReminder: true,
    onboardingReminder: true,
    contractExpireReminder: true,
    performanceReminder: true,
    // Locale
    systemLanguage: 'zh-CN',
    timezone: 'Asia/Shanghai',
    dateFormat: 'YYYY-MM-DD',
    timeFormat: '24h',
    // Security
    passwordExpiry: '90',
    enableTwoFactor: false,
    sessionTimeout: '30',
    enableLoginAudit: true,
  });
  const [avatarUrl, setAvatarUrl] = useState(getConfiguredAvatarUrl());

  useEffect(() => {
    document.title = '系统设置 - 恒聘通';
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const data = await miscApi.getSettings();
      if (data) setSettings((prev) => ({ ...prev, ...data }));
    } catch (err) {
      console.error('加载设置失败', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    // 校验：公司名称必填
    if (!settings.companyName?.trim()) {
      setToast({ type: 'error', msg: '请输入公司名称' });
      setTimeout(() => setToast(null), 3000);
      return;
    }
    // 联系邮箱格式（填写时校验）
    if (settings.contactEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(settings.contactEmail)) {
      setToast({ type: 'error', msg: '联系邮箱格式不正确' });
      setTimeout(() => setToast(null), 3000);
      return;
    }
    setSaving(true);
    try {
      setConfiguredAvatarUrl(avatarUrl);
      await miscApi.updateSettings(settings);
      setToast({ type: 'success', msg: '设置已保存成功' });
      setTimeout(() => setToast(null), 3000);
    } catch (err: any) {
      setToast({ type: 'error', msg: err.message || '保存失败' });
      setTimeout(() => setToast(null), 3000);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    const ok = await confirm({
      title: '重置设置',
      message: '确定重置当前设置？未保存的修改会丢失。',
      confirmText: '重置',
    });
    if (ok) {
      setAvatarUrl(getConfiguredAvatarUrl());
      loadSettings();
    }
  };

  const update = (key: string, value: any) => setSettings((prev) => ({ ...prev, [key]: value }));

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64">
          <AppIcon className="fas fa-spinner fa-spin text-2xl text-blue-400" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {/* Header */}
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center"><AppIcon className="fas fa-cog text-sm" /></div>
            <div>
              <h1 className="text-[15px] font-bold text-gray-900">系统设置</h1>
              <p className="text-xs text-gray-400 mt-0.5">账户与公司信息、功能开关、语言与通知、安全设置</p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white rounded-xl border border-gray-100 px-5">
          <div className="flex items-center gap-1 border-b border-gray-100">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
                  activeTab === tab.id
                    ? 'text-blue-600 border-blue-500'
                    : 'text-gray-500 border-transparent hover:text-gray-700'
                }`}
              >
                <AppIcon className={`fas ${tab.icon} mr-1.5`} />{tab.label}
              </button>
            ))}
          </div>

          <div className="py-5">
            {/* Account & Company */}
            {activeTab === 'account' && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                  <h3 className="text-[13px] font-bold text-gray-700 mb-3">账户信息</h3>
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                      <UserAvatar user={{ ...(user || {}), avatarUrl }} size="lg" />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-gray-800">{user?.name}</div>
                        <div className="text-xs text-gray-500">{user?.email}</div>
                        <div className="text-xs text-blue-500 mt-0.5">{roleLabels[user?.role || ''] || user?.role}</div>
                      </div>
                      <button className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-white">修改密码</button>
                    </div>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">头像图片 URL</span>
                      <input
                        type="url"
                        value={avatarUrl}
                        onChange={(e) => setAvatarUrl(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                        placeholder="https://example.com/avatar.png"
                      />
                      <span className="block text-[11px] text-gray-400 mt-1">保存后右上角头像会立即更新；留空则使用姓名首字母。</span>
                    </label>
                  </div>
                </div>

                <div>
                  <h3 className="text-[13px] font-bold text-gray-700 mb-3">公司信息</h3>
                  <div className="space-y-3">
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">公司名称</span>
                      <input type="text" value={settings.companyName} onChange={(e) => update('companyName', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="请输入公司名称" />
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="block">
                        <span className="block text-xs text-gray-500 mb-1">公司规模</span>
                        <select value={settings.companySize} onChange={(e) => update('companySize', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                          {['1-10人', '10-50人', '50-100人', '100-500人', '500-1000人', '1000+人'].map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </label>
                      <label className="block">
                        <span className="block text-xs text-gray-500 mb-1">所属行业</span>
                        <input type="text" value={settings.companyIndustry} onChange={(e) => update('companyIndustry', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="如：互联网/IT" />
                      </label>
                    </div>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">公司网站</span>
                      <input type="url" value={settings.companyWebsite} onChange={(e) => update('companyWebsite', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="https://example.com" />
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="block">
                        <span className="block text-xs text-gray-500 mb-1">联系邮箱</span>
                        <input type="email" value={settings.contactEmail} onChange={(e) => update('contactEmail', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="contact@example.com" />
                      </label>
                      <label className="block">
                        <span className="block text-xs text-gray-500 mb-1">联系电话</span>
                        <input type="tel" value={settings.contactPhone} onChange={(e) => update('contactPhone', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="010-12345678" />
                      </label>
                    </div>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">公司地址</span>
                      <input type="text" value={settings.companyAddress} onChange={(e) => update('companyAddress', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" placeholder="请输入详细地址" />
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* Function Settings */}
            {activeTab === 'function' && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-1 max-w-4xl">
                <Toggle checked={settings.autoResumeAnalysis} onChange={(v) => update('autoResumeAnalysis', v)} label="开启简历自动AI评分" desc="上传简历后自动使用AI进行评分和匹配分析" />
                <Toggle checked={settings.enableMultiDeptAttendance} onChange={(v) => update('enableMultiDeptAttendance', v)} label="启用部门考勤差异化设置" desc="不同部门可设置独立的考勤规则" />
                <Toggle checked={settings.enableOnboardingTasks} onChange={(v) => update('enableOnboardingTasks', v)} label="启用入职任务自动生成" desc="新员工创建后自动生成默认入职任务清单" />
                <Toggle checked={settings.enableProbationReminder} onChange={(v) => update('enableProbationReminder', v)} label="启用试用期到期提醒" desc="试用期临近结束时自动通知HR与上级" />
                <Toggle checked={settings.enableContractReminder} onChange={(v) => update('enableContractReminder', v)} label="启用合同到期提醒" desc="合同到期前30天自动提醒HR" />
                <Toggle checked={settings.enableSalaryEncryption} onChange={(v) => update('enableSalaryEncryption', v)} label="启用薪资数据加密查看" desc="非HR/管理员查看薪资数据需二次确认" />
              </div>
            )}

            {/* Notification */}
            {activeTab === 'notification' && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-1 max-w-4xl">
                <Toggle checked={settings.inSystemNotification} onChange={(v) => update('inSystemNotification', v)} label="站内通知" desc="在系统内接收推送提醒" />
                <Toggle checked={settings.emailNotification} onChange={(v) => update('emailNotification', v)} label="邮件通知" desc="接收系统通知和提醒邮件" />
                <Toggle checked={settings.approvalReminder} onChange={(v) => update('approvalReminder', v)} label="审批提醒" desc="收到待审批事项时通知" />
                <Toggle checked={settings.onboardingReminder} onChange={(v) => update('onboardingReminder', v)} label="入职提醒" desc="新员工入职任务、待入职提醒" />
                <Toggle checked={settings.contractExpireReminder} onChange={(v) => update('contractExpireReminder', v)} label="合同到期提醒" desc="合同到期前自动提醒" />
                <Toggle checked={settings.performanceReminder} onChange={(v) => update('performanceReminder', v)} label="绩效提醒" desc="绩效周期、自评、上级评分提醒" />

                <div className="col-span-full mt-4 pt-4 border-t border-gray-100">
                  <h3 className="text-[13px] font-bold text-gray-700 mb-3">语言与区域</h3>
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">系统语言</span>
                      <select value={settings.systemLanguage} onChange={(e) => update('systemLanguage', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                        <option value="zh-CN">简体中文</option>
                        <option value="zh-TW">繁體中文</option>
                        <option value="en-US">English</option>
                      </select>
                    </label>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">时区</span>
                      <select value={settings.timezone} onChange={(e) => update('timezone', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                        <option value="Asia/Shanghai">(GMT+08:00) 北京、上海</option>
                        <option value="Asia/Hong_Kong">(GMT+08:00) 香港</option>
                        <option value="Asia/Tokyo">(GMT+09:00) 东京</option>
                        <option value="UTC">UTC (GMT+00:00)</option>
                      </select>
                    </label>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">日期格式</span>
                      <select value={settings.dateFormat} onChange={(e) => update('dateFormat', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                        <option value="YYYY-MM-DD">2025-05-20</option>
                        <option value="YYYY/MM/DD">2025/05/20</option>
                        <option value="DD-MM-YYYY">20-05-2025</option>
                      </select>
                    </label>
                    <label className="block">
                      <span className="block text-xs text-gray-500 mb-1">时间格式</span>
                      <select value={settings.timeFormat} onChange={(e) => update('timeFormat', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40">
                        <option value="24h">24小时制 (HH:mm:ss)</option>
                        <option value="12h">12小时制 (hh:mm:ss A)</option>
                      </select>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* Security */}
            {activeTab === 'security' && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-3 max-w-4xl">
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">密码有效期（天）</span>
                  <input type="number" min={0} max={3650} step={1} value={settings.passwordExpiry} onChange={(e) => update('passwordExpiry', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                  <span className="block text-[11px] text-gray-400 mt-1">设置为 0 表示永不过期</span>
                </label>
                <label className="block">
                  <span className="block text-xs text-gray-500 mb-1">会话超时（分钟）</span>
                  <input type="number" min={1} max={1440} step={1} value={settings.sessionTimeout} onChange={(e) => update('sessionTimeout', e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40" />
                  <span className="block text-[11px] text-gray-400 mt-1">无操作超过此时长后自动登出</span>
                </label>
                <div className="col-span-full mt-2">
                  <Toggle checked={settings.enableTwoFactor} onChange={(v) => update('enableTwoFactor', v)} label="启用双因子认证（2FA）" desc="登录时除密码外需输入手机/邮箱验证码" />
                  <Toggle checked={settings.enableLoginAudit} onChange={(v) => update('enableLoginAudit', v)} label="登录审计" desc="记录所有用户登录、登出、异常事件" />
                </div>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="px-1 py-3 border-t border-gray-100 flex justify-end gap-2">
            <button onClick={handleReset} className="px-4 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors">重置</button>
            <button onClick={handleSave} disabled={saving} className="px-4 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-60">
              {saving ? <><AppIcon className="fas fa-spinner fa-spin mr-1" />保存中...</> : <><AppIcon className="fas fa-save mr-1" />保存设置</>}
            </button>
          </div>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed top-20 right-6 z-50 animate-fade-in">
          <div className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 ${toast.type === 'success' ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-red-50 border border-red-200 text-red-700'}`}>
            <AppIcon className={`fas ${toast.type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}`} />
            <span className="text-sm">{toast.msg}</span>
          </div>
        </div>
      )}
    </Layout>
  );
}
