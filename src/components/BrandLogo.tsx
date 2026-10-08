import { useId } from 'react';

type BrandLogoSize = 'sm' | 'md' | 'lg';

interface BrandLogoProps {
  size?: BrandLogoSize;
  showText?: boolean;
  stacked?: boolean;
  className?: string;
}

const sizeMap: Record<BrandLogoSize, { mark: string; title: string; subtitle: string }> = {
  sm: { mark: 'w-8 h-8', title: 'text-[15px]', subtitle: 'text-[10px]' },
  md: { mark: 'w-11 h-11', title: 'text-xl', subtitle: 'text-xs' },
  lg: { mark: 'w-16 h-16', title: 'text-2xl', subtitle: 'text-sm' },
};

function LogoMark({ size = 'sm' }: { size?: BrandLogoSize }) {
  const id = useId().replace(/:/g, '');
  const grad = `hpt-logo-grad-${id}`;
  const soft = `hpt-logo-soft-${id}`;

  return (
    <svg viewBox="0 0 64 64" className={`${sizeMap[size].mark} flex-shrink-0`} aria-hidden="true">
      <defs>
        <linearGradient id={grad} x1="12" x2="52" y1="10" y2="54" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1d4ed8" />
          <stop offset="1" stopColor="#0f766e" />
        </linearGradient>
        <linearGradient id={soft} x1="14" x2="50" y1="12" y2="50" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffffff" stopOpacity="0.98" />
          <stop offset="1" stopColor="#dff7ff" stopOpacity="0.92" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="56" height="56" rx="15" fill="white" />
      <rect x="5.5" y="5.5" width="53" height="53" rx="13.5" fill="url(#soft)" stroke="#d8e6f7" />
      <path d="M18 42V22c0-2.2 1.8-4 4-4h20c2.2 0 4 1.8 4 4v20c0 2.2-1.8 4-4 4H22c-2.2 0-4-1.8-4-4Z" fill="url(#grad)" opacity="0.94" />
      <path d="M26 40V24M38 40V24M26 32h12" stroke="white" strokeWidth="4.2" strokeLinecap="round" />
      <path d="M43.5 21.5 48 17M43.5 42.5 48 47" stroke="#0f766e" strokeWidth="3.2" strokeLinecap="round" />
      <circle cx="48.5" cy="16.5" r="3" fill="#0f766e" />
      <circle cx="48.5" cy="47.5" r="3" fill="#1d4ed8" />
    </svg>
  );
}

export default function BrandLogo({ size = 'sm', showText = true, stacked = false, className = '' }: BrandLogoProps) {
  const classes = sizeMap[size];

  return (
    <div className={`inline-flex ${stacked ? 'flex-col text-center' : 'items-center'} gap-2 ${className}`.trim()}>
      <LogoMark size={size} />
      {showText && (
        <div className={stacked ? '' : 'leading-tight'}>
          <div className={`${classes.title} font-extrabold text-slate-900 whitespace-nowrap`}>恒聘通 HRM</div>
          {size !== 'sm' && <div className={`${classes.subtitle} font-medium text-slate-500 mt-1`}>一体化人才管理系统</div>}
        </div>
      )}
    </div>
  );
}
