const BUSINESS_TIME_ZONE = 'Asia/Shanghai';

const toBusinessInstant = (value: string) => {
  const text = String(value || '').trim();
  if (!text) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const date = new Date(hasZone ? text : `${text}+08:00`);
  return Number.isNaN(date.getTime()) ? null : date;
};

export const formatBusinessDateTime = (
  value: string,
  options: Intl.DateTimeFormatOptions = {},
) => {
  const date = toBusinessInstant(value);
  if (!date) return value || '-';
  return date.toLocaleString('zh-CN', {
    timeZone: BUSINESS_TIME_ZONE,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...options,
  });
};

