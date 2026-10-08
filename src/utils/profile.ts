const AVATAR_KEY = 'hpt:userAvatarUrl';

export const getConfiguredAvatarUrl = () => {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(AVATAR_KEY) || '';
};

export const setConfiguredAvatarUrl = (url: string) => {
  if (typeof window === 'undefined') return;
  const cleaned = url.trim();
  if (cleaned) localStorage.setItem(AVATAR_KEY, cleaned);
  else localStorage.removeItem(AVATAR_KEY);
  window.dispatchEvent(new Event('hpt-profile-updated'));
};

export const getUserAvatarUrl = (user?: { avatarUrl?: string } | null) => {
  return user?.avatarUrl || getConfiguredAvatarUrl();
};
