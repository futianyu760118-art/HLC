type StatusTone = 'success' | 'warning' | 'danger' | 'neutral' | 'primary';

const toneClass: Record<StatusTone, string> = {
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  danger: 'bg-red-50 text-red-700',
  neutral: 'bg-slate-100 text-slate-500',
  primary: 'bg-blue-50 text-blue-700',
};

export function ProductStatusBadge({
  children,
  tone = 'neutral',
}: {
  children: string;
  tone?: StatusTone;
}) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${toneClass[tone]}`}>
      {children}
    </span>
  );
}
