import type { ButtonHTMLAttributes, ReactNode } from 'react';
import AppIcon from '../AppIcon';

type ButtonTone = 'primary' | 'secondary' | 'danger' | 'ghost';

const toneClass: Record<ButtonTone, string> = {
  primary: 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700',
  secondary: 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50',
  danger: 'bg-white text-red-600 border-red-200 hover:bg-red-50',
  ghost: 'bg-transparent text-slate-600 border-transparent hover:bg-slate-50',
};

export function ProductButton({
  children,
  icon,
  tone = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: string; tone?: ButtonTone; children: ReactNode }) {
  return (
    <button
      {...props}
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors disabled:opacity-60 ${toneClass[tone]} ${className}`}
    >
      {icon && <AppIcon className={`fas ${icon} text-[12px]`} />}
      {children}
    </button>
  );
}
