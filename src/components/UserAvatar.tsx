import { useState } from 'react';
import { getUserAvatarUrl } from '../utils/profile';

interface UserAvatarProps {
  user?: { name?: string; email?: string; avatarUrl?: string } | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizeMap = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-10 h-10 text-sm',
  lg: 'w-12 h-12 text-base',
};

const getInitial = (user?: UserAvatarProps['user']) => {
  const source = user?.name || user?.email || 'U';
  return source.trim().charAt(0).toUpperCase() || 'U';
};

export default function UserAvatar({ user, size = 'sm', className = '' }: UserAvatarProps) {
  const [imageOk, setImageOk] = useState(true);
  const avatarUrl = getUserAvatarUrl(user);

  if (avatarUrl && imageOk) {
    return (
      <img
        src={avatarUrl}
        alt={user?.name || '用户头像'}
        className={`${sizeMap[size]} rounded-full object-cover ring-1 ring-slate-200 bg-white ${className}`.trim()}
        onError={() => setImageOk(false)}
      />
    );
  }

  return (
    <div className={`${sizeMap[size]} rounded-full bg-[linear-gradient(135deg,#f8fbff,#e9f2ff)] border border-slate-200 text-slate-700 flex items-center justify-center font-bold shadow-sm ${className}`.trim()}>
      {getInitial(user)}
    </div>
  );
}
