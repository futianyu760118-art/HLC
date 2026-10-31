import type { ReactNode } from 'react';
import AppIcon from '../AppIcon';

export function ProductMetricCard({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: ReactNode;
  icon?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-slate-500">{label}</div>
        {icon && <AppIcon className={`fas ${icon} text-[12px] text-slate-400`} />}
      </div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
