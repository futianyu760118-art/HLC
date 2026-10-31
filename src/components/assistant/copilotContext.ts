const MODULE_NAME_MAP: Record<string, string> = {
  '/hrm': '员工档案',
  '/job-manage': '岗位管理',
  '/resume-manage': '简历管理',
  '/interview-manage': '面试管理',
  '/attendance-stats': '考勤统计',
  '/employee-requests': '请假审批',
  '/performance-review': '绩效管理',
  '/salary-profiles': '薪资档案',
  '/hrm/employee-changes': '员工异动',
  '/notifications': '通知中心',
  '/system-settings': '系统设置',
  '/ai-model-settings': 'AI 模型设置',
  '/operation-logs': '操作日志',
};

const normalizePath = (path: string) => path.replace(/\/+$/, '') || '/';

type AssistantContextUser = {
  role?: string;
} | null | undefined;

const normalizeFilterKey = (value: string) => value
  .trim()
  .replace(/\s+/g, '-')
  .replace(/[^\w\u4e00-\u9fa5-]/g, '-')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')
  .toLowerCase();

const CANONICAL_FILTER_KEYS: Array<[RegExp, string]> = [
  [/^(search|keyword|关键词|搜索)$/i, 'search'],
  [/^(month|月份|月度|考勤月|统计月)$/i, 'month'],
  [/(员工|人员|姓名|employee)/i, 'employeeId'],
  [/(部门|department)/i, 'departmentId'],
  [/(状态|status)/i, 'status'],
  [/(申请类型|类型|type)/i, 'type'],
  [/(岗位|职位|job|position)/i, 'jobId'],
  [/(候选人|简历|candidate|resume)/i, 'candidateId'],
  [/(绩效周期|周期|cycle)/i, 'cycleId'],
  [/(开始|起始|from)/i, 'from'],
  [/(结束|截止|to)/i, 'to'],
];

const canonicalFilterKey = (rawKey: string, label?: string) => {
  const source = `${rawKey} ${label || ''}`.trim();
  const match = CANONICAL_FILTER_KEYS.find(([pattern]) => pattern.test(source));
  return match?.[1] || normalizeFilterKey(rawKey || label || 'filter');
};

const clip = (value: string, limit = 120) => value.trim().slice(0, limit);

const addFilter = (
  filters: Record<string, string>,
  rawKey: string,
  value: string,
  label?: string,
  display?: string,
) => {
  const cleanValue = clip(value);
  const cleanDisplay = clip(display || value);
  if (!cleanValue && !cleanDisplay) return;
  const key = canonicalFilterKey(rawKey, label);
  if (cleanValue && filters[key] === undefined) filters[key] = cleanValue;
  if (cleanDisplay && label) {
    const displayKey = `${key}Label`;
    if (filters[displayKey] === undefined) filters[displayKey] = cleanDisplay;
  }
};

const collectUrlFilters = () => {
  const filters: Record<string, string> = {};
  const params = new URLSearchParams(window.location.search || '');
  params.forEach((value, key) => {
    if (value) addFilter(filters, key, value);
  });
  return filters;
};

const collectDomFilters = () => {
  const filters: Record<string, string> = {};
  document.querySelectorAll<HTMLElement>('[data-hpt-filter]').forEach((node) => {
    const rawKey = node.dataset.hptFilter || '';
    const label = node.dataset.hptFilterLabel || rawKey;
    const value = node.dataset.hptFilterValue || '';
    const display = node.dataset.hptFilterDisplay || value;
    addFilter(filters, rawKey, value, label, display);
  });
  return filters;
};

const collectNativeMonthFilter = () => {
  const filters: Record<string, string> = {};
  const monthInput = document.querySelector<HTMLInputElement>('input[type="month"]');
  if (monthInput?.value) addFilter(filters, 'month', monthInput.value, '月份', monthInput.value);
  return filters;
};

export const buildAssistantClientContext = (user?: AssistantContextUser) => {
  if (typeof window === 'undefined') return {};
  const path = normalizePath(window.location.pathname || '/');
  const visibleFilters: Record<string, string> = {
    ...collectUrlFilters(),
    ...collectNativeMonthFilter(),
    ...collectDomFilters(),
  };
  const firstSegment = `/${path.split('/').filter(Boolean)[0] || ''}`;
  const moduleName = MODULE_NAME_MAP[path] || MODULE_NAME_MAP[firstSegment] || document.title || 'HRM';

  return {
    path,
    route: `${path}${window.location.search || ''}`,
    moduleId: path.split('/').filter(Boolean).join('.') || 'home',
    moduleName,
    pageTitle: document.title || moduleName,
    visibleFilters,
    selectedRecordIds: [],
    userRole: user?.role,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
    },
  };
};
