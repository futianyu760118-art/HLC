// @ts-nocheck
import React from 'react';
import AppIcon from './AppIcon';

/** 管理侧页面标准头部：图标 + 标题 + 副标题 + 右侧操作区 */
export const PageHeader: React.FC<{
  icon: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}> = ({ icon, title, subtitle, actions }) => (
  <div className="flex items-center justify-between mb-6">
    <div className="flex items-center gap-3">
      <div className="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
        <AppIcon className={`fas ${icon} text-primary text-lg`} />
      </div>
      <div>
        <h1 className="text-xl font-bold text-text-primary leading-tight">{title}</h1>
        {subtitle && <p className="text-sm text-text-secondary mt-0.5">{subtitle}</p>}
      </div>
    </div>
    {actions && <div className="flex items-center gap-2">{actions}</div>}
  </div>
);

/** 统计小卡片 */
export const StatPill: React.FC<{
  label: string;
  value: React.ReactNode;
  icon: string;
  tone?: 'primary' | 'success' | 'warning' | 'danger' | 'neutral';
}> = ({ label, value, icon, tone = 'primary' }) => {
  const tones: Record<string, string> = {
    primary: 'text-primary', success: 'text-success', warning: 'text-warning',
    danger: 'text-danger', neutral: 'text-text-secondary',
  };
  return (
    <div className="bg-white rounded-xl border border-border-light px-4 py-3 flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-bg-light flex items-center justify-center shrink-0">
        <AppIcon className={`fas ${icon} ${tones[tone]} text-sm`} />
      </div>
      <div>
        <div className={`text-lg font-bold leading-tight ${tones[tone]}`}>{value}</div>
        <div className="text-xs text-text-secondary">{label}</div>
      </div>
    </div>
  );
};

/** 空状态 */
export const EmptyState: React.FC<{ icon: string; title: string; hint?: string; action?: React.ReactNode }> = ({ icon, title, hint, action }) => (
  <div className="text-center py-20">
    <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-light flex items-center justify-center">
      <AppIcon className={`fas ${icon} text-2xl text-text-secondary`} />
    </div>
    <p className="text-text-primary font-medium">{title}</p>
    {hint && <p className="text-sm text-text-secondary mt-1">{hint}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

/** 状态标签 */
export const StatusBadge: React.FC<{ status?: string; map: Record<string, { label: string; tone: string }> }> = ({ status, map }) => {
  if (!status || !map[status]) return null;
  const { label, tone } = map[status];
  const tones: Record<string, string> = {
    success: 'bg-success/10 text-success', warning: 'bg-warning/10 text-warning',
    danger: 'bg-danger/10 text-danger', neutral: 'bg-bg-light text-text-secondary',
    primary: 'bg-primary/10 text-primary',
  };
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${tones[tone] || tones.neutral}`}>{label}</span>;
};
