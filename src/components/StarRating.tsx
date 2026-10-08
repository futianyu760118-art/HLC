// @ts-nocheck
import React from 'react';
import AppIcon from './AppIcon';

/** 星级显示（只读）：rating 0-5，支持半星 */
export const StarRating: React.FC<{ rating: number; size?: string }> = ({ rating, size = 'text-sm' }) => {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return (
    <span className={`${size} text-warning inline-flex items-center`}>
      {[1, 2, 3, 4, 5].map(i => (
        <AppIcon key={i} className={i <= full ? 'fas fa-star' : (i === full + 1 && half ? 'fas fa-star-half-alt' : 'far fa-star')} />
      ))}
      {rating > 0 && <span className="ml-1 text-text-secondary tabular-nums">{rating.toFixed(1)}</span>}
    </span>
  );
};

/** 星级选择器（可交互）：value 0-5，onChange 返回 1-5 */
export const StarInput: React.FC<{ value: number; onChange: (v: number) => void; label?: string }> = ({ value, onChange, label }) => {
  const [hover, setHover] = React.useState(0);
  const display = hover || value;
  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-sm text-text-secondary w-20">{label}</span>}
      <div className="flex" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map(i => (
          <button key={i} type="button" onMouseEnter={() => setHover(i)} onClick={() => onChange(i)}
            className={`text-xl ${i <= display ? 'text-warning' : 'text-border-light'} hover:scale-110 transition-transform`}>
            <AppIcon className={i <= display ? 'fas fa-star' : 'far fa-star'} />
          </button>
        ))}
      </div>
    </div>
  );
};
