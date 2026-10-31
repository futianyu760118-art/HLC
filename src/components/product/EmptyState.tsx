import type { ReactNode } from 'react';
import AppIcon from '../AppIcon';

export function ProductEmptyState({
  icon = 'fa-inbox',
  title,
  description,
  action,
  compact = false,
}: {
  icon?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`${compact ? 'py-8' : 'rounded-lg border border-slate-200 bg-white p-8'} text-center`}>
      <AppIcon className={`fas ${icon} text-2xl text-slate-300`} />
      <div className="mt-3 text-sm font-medium text-slate-700">{title}</div>
      {description && <div className="mt-1 text-sm text-slate-500">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
