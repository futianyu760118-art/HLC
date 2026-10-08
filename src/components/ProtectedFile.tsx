// @ts-nocheck
import React, { useEffect, useState } from 'react';
import { fileApi } from '../utils/api';

const canUseDirectUrl = (fileUrl?: string | null) => {
  const value = String(fileUrl || '').trim();
  if (!value) return false;
  if (/^(blob:|data:)/i.test(value)) return true;
  // 后端短期签名媒体 URL（/api/media/<key>?exp=&sig=）：无 Authorization 即可播放，
  // 支持流式/Range，<video>/<img> 可直接使用，无需转 blob。
  if (/^\/api\/media\//i.test(value)) return true;
  if (!/^https?:\/\//i.test(value)) return false;
  try {
    const parsed = new URL(value);
    if (typeof window !== 'undefined' && parsed.origin === window.location.origin) {
      return !/^\/(uploads|api\/files)\//.test(parsed.pathname);
    }
  } catch {}
  return true;
};

export function useProtectedFileUrl(fileUrl?: string | null) {
  const [url, setUrl] = useState<string>('');
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    let objectUrl = '';
    setUrl('');
    setError(false);
    if (!fileUrl) return () => {};
    if (canUseDirectUrl(fileUrl)) {
      setUrl(String(fileUrl));
      return () => {};
    }
    fileApi.getBlobUrl(fileUrl)
      .then((next) => {
        objectUrl = next;
        if (alive) setUrl(next);
        else URL.revokeObjectURL(next);
      })
      .catch(() => {
        if (alive) setError(true);
      });
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [fileUrl]);

  return { url, error, loading: Boolean(fileUrl && !url && !error) };
}

export function ProtectedImage({ fileUrl, alt = '', className = '', style, fallback = null, ...props }) {
  const { url, error, loading } = useProtectedFileUrl(fileUrl);
  if (!fileUrl || error) return fallback;
  if (loading) return fallback || <div className={className} style={style} />;
  return <img src={url} alt={alt} className={className} style={style} {...props} />;
}
