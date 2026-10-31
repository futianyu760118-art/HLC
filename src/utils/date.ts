const hasTimezoneInfo = (value: string) => /Z|[+-]\d{2}:\d{2}$/.test(value);

const normalizeToUTC = (value?: string | null) => {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return hasTimezoneInfo(trimmed) ? trimmed : `${trimmed}Z`;
};

export const parseAPIDate = (value?: string | null): Date | null => {
  const normalized = normalizeToUTC(value);
  if (!normalized) return null;
  const timestamp = Date.parse(normalized);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Date(timestamp);
};

const defaultDisplayOptions: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
};

export const formatChinaDateTime = (
  value?: string | null,
  options?: Intl.DateTimeFormatOptions
): string => {
  const date = parseAPIDate(value);
  if (!date) return '';
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    ...defaultDisplayOptions,
    ...options,
    timeZone: 'Asia/Shanghai',
  });
  return formatter.format(date);
};


