// API配置和工具函数
import { authUtils } from './auth';
import { normalizeEnterpriseApplicationListItem } from './enterpriseApplications';

// 生产环境使用相对路径，开发环境使用localhost
const API_BASE_URL = import.meta.env.VITE_API_URL || 
  (import.meta.env.PROD ? '/api' : 'http://localhost:18888/api');

// 简易 UUID（用于请求级追踪），不依赖 crypto.randomUUID 兼容性
const genRequestId = (): string => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return (crypto as any).randomUUID();
  }
  return 'r-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
};

// 自定义错误类型，附带 status / requestId，方便上层识别
export class ApiError extends Error {
  status: number;
  requestId?: string;
  code?: string;
  constructor(message: string, status: number, requestId?: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.requestId = requestId;
    this.code = code;
  }
}

const looksLikeHtml = (value: string): boolean => /<!doctype\s+html|<html[\s>]|<title>[^<]*(?:404|not found)/i.test(value);

const safeApiErrorMessage = (text: string, status: number, fallback = `请求失败 (${status})`): string => {
  if (!text || looksLikeHtml(text)) {
    return status === 404 ? '当前功能在本次发布中不可用' : '服务暂不可用，请稍后重试';
  }
  try {
    const error = JSON.parse(text);
    return error.error || error.msg || fallback;
  } catch {
    return text.slice(0, 200);
  }
};

// HTTP请求工具
class ApiClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private getToken(): string | null {
    return authUtils.getToken();
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    includeAuth = true,
  ): Promise<T> {
    const token = includeAuth ? this.getToken() : null;
    const requestId = genRequestId();
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
      ...(token && { Authorization: `Bearer ${token}` }),
      ...options.headers,
    };

    const config: RequestInit = {
      ...options,
      headers,
    };

    let response: Response;
    try {
      response = await fetch(`${this.baseURL}${endpoint}`, config);
    } catch (caught: unknown) {
      if (options.signal?.aborted) throw caught;
      // 网络层错误（断网、CORS、DNS）
      throw new ApiError('网络异常，请检查连接后重试', 0, requestId);
    }

    if (!response.ok) {
      const text = await response.text();
      let message = `请求失败 (${response.status})`;
      let errorCode = '';
      try {
        const error = JSON.parse(text);
        message = error.error || error.msg || message;
        errorCode = error.code || '';
      } catch {
        message = safeApiErrorMessage(text, response.status, message);
      }

      const respRequestId = response.headers.get('X-Request-ID') || requestId;

      // 401 自动登出并回到当前认证入口，避免平台账号被踢到企业登录页。
      const isLoginEndpoint = endpoint.startsWith('/auth/login')
        || endpoint.startsWith('/portal/auth/login')
        || endpoint.startsWith('/platform/auth/login');
      if (includeAuth && response.status === 401 && !isLoginEndpoint) {
        authUtils.logout();
        if (typeof window !== 'undefined') {
          // 用 setTimeout 避免 React 渲染冲突
          setTimeout(() => {
            const isPlatformRequest = endpoint.startsWith('/platform/');
            const isPortalRequest = endpoint.startsWith('/portal/');
            const currentPath = window.location.pathname;
            if (isPlatformRequest || currentPath.startsWith('/platform')) {
              if (!currentPath.startsWith('/platform/login')) window.location.href = '/platform/login?mode=platform&expired=1';
            } else {
              const mode = isPortalRequest || currentPath.startsWith('/portal') ? 'portal' : 'hrm';
              if (currentPath !== '/login') window.location.href = `/login?mode=${mode}&expired=1`;
            }
          }, 50);
        }
      }

      if (
        includeAuth &&
        response.status === 403 &&
        errorCode === 'PASSWORD_CHANGE_REQUIRED' &&
        !endpoint.startsWith('/auth/change-password') &&
        !endpoint.startsWith('/portal/auth/change-password')
      ) {
        if (typeof window !== 'undefined' && window.location.pathname !== '/change-password') {
          setTimeout(() => {
            window.location.href = '/change-password';
          }, 50);
        }
      }

      throw new ApiError(message, response.status, respRequestId, errorCode || undefined);
    }

    // 204 / 空响应兜底
    const contentType = response.headers.get('Content-Type') || '';
    if (response.status === 204 || !contentType.includes('application/json')) {
      return undefined as unknown as T;
    }
    return response.json();
  }

  async get<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  async post<T>(endpoint: string, data?: unknown, options: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async postPublic<T>(endpoint: string, data?: unknown, options: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    }, false);
  }

  async put<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async patch<T>(endpoint: string, data?: unknown, options: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }

  async uploadFile<T>(
    endpoint: string,
    file: File,
    additionalData?: Record<string, string>,
    onProgress?: (progress: { loaded: number; total: number; percent: number }) => void,
  ): Promise<T> {
    const token = this.getToken();
    const requestId = genRequestId();
    const formData = new FormData();
    formData.append('file', file);
    
    if (additionalData) {
      Object.keys(additionalData).forEach(key => {
        formData.append(key, additionalData[key]);
      });
    }

    return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${this.baseURL}${endpoint}`);
      xhr.setRequestHeader('X-Request-ID', requestId);
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }

      if (onProgress) {
        xhr.upload.onprogress = (event) => {
          if (!event.lengthComputable) return;
          const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
          onProgress({ loaded: event.loaded, total: event.total, percent });
        };
      }

      xhr.onerror = () => reject(new ApiError('网络异常，文件上传失败', 0, requestId));
      xhr.onload = () => {
        const responseText = xhr.responseText || '';
        const responseRequestId = xhr.getResponseHeader('X-Request-ID') || requestId;

        if (xhr.status < 200 || xhr.status >= 300) {
          let message = `上传失败 (${xhr.status})`;
          try {
            const error = JSON.parse(responseText);
            message = error.error || error.msg || message;
          } catch {
            message = safeApiErrorMessage(responseText, xhr.status, message);
          }
          reject(new ApiError(message, xhr.status, responseRequestId));
          return;
        }

        if (onProgress) {
          onProgress({ loaded: file.size, total: file.size, percent: 100 });
        }

        if (!responseText.trim()) {
          resolve(undefined as unknown as T);
          return;
        }

        try {
          resolve(JSON.parse(responseText));
        } catch {
          resolve(undefined as unknown as T);
        }
      };

      xhr.send(formData);
    });
  }

  async downloadFile(endpoint: string, filename?: string): Promise<void> {
    const token = this.getToken();
    const requestId = genRequestId();
    let response: Response;
    try {
      response = await fetch(`${this.baseURL}${endpoint}`, {
        method: 'GET',
        headers: {
          'X-Request-ID': requestId,
          ...(token && { Authorization: `Bearer ${token}` }),
        },
      });
    } catch {
      throw new ApiError('网络异常，文件下载失败', 0, requestId);
    }

    if (!response.ok) {
      const text = await response.text();
      let message = `下载失败 (${response.status})`;
      try {
        const error = JSON.parse(text);
        message = error.error || error.msg || message;
      } catch {
        message = safeApiErrorMessage(text, response.status, message);
      }
      throw new ApiError(message, response.status, response.headers.get('X-Request-ID') || requestId);
    }

    const blob = await response.blob();
    const cd = response.headers.get('Content-Disposition') || '';
    const headerName = decodeURIComponent((cd.match(/filename\*=UTF-8''([^;]+)/)?.[1] || '').trim())
      || (cd.match(/filename="?([^";]+)"?/)?.[1] || '').trim();
    const downloadName = filename || headerName || 'download';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = downloadName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }
}

const apiClient = new ApiClient(API_BASE_URL);

const normalizeFileKey = (fileUrl: string): string => {
  if (!fileUrl) return '';
  let value = fileUrl.trim();
  try {
    if (/^https?:\/\//i.test(value)) {
      value = new URL(value).pathname;
    }
  } catch {}
  value = value.replace(/^\/api\/files\//, '').replace(/^\/uploads\//, '').replace(/^uploads\//, '');
  return value.split('/').filter(Boolean).map(encodeURIComponent).join('/');
};

export const fileApi = {
  endpoint(fileUrl: string, disposition: 'inline' | 'attachment' = 'inline'): string {
    const key = normalizeFileKey(fileUrl);
    const query = disposition === 'attachment' ? '?disposition=attachment' : '';
    return `/files/${key}${query}`;
  },
  async fetch(fileUrl: string, disposition: 'inline' | 'attachment' = 'inline'): Promise<Response> {
    const token = authUtils.getToken();
    const requestId = genRequestId();
    const response = await fetch(`${API_BASE_URL}${this.endpoint(fileUrl, disposition)}`, {
      headers: {
        'X-Request-ID': requestId,
        ...(token && { Authorization: `Bearer ${token}` }),
      },
    });
    if (!response.ok) {
      throw new ApiError('文件加载失败', response.status, response.headers.get('X-Request-ID') || requestId);
    }
    return response;
  },
  async getBlobUrl(fileUrl: string, disposition: 'inline' | 'attachment' = 'inline'): Promise<string> {
    const response = await this.fetch(fileUrl, disposition);
    return URL.createObjectURL(await response.blob());
  },
  async getText(fileUrl: string): Promise<string> {
    const response = await this.fetch(fileUrl, 'inline');
    return response.text();
  },
  async download(fileUrl: string, filename?: string): Promise<void> {
    await apiClient.downloadFile(this.endpoint(fileUrl, 'attachment'), filename);
  },
};

// 类型定义
export interface User {
  id: string;
  accountType?: 'hrm' | 'employee_portal';
  tenantId?: string | null;
  tenantSlug?: string | null;
  tenantName?: string | null;
  isPlatformAdmin?: boolean;
  email: string;
  name: string;
  role: 'platform_admin' | 'admin' | 'hr_admin' | 'recruiter' | 'manager' | 'employee' | 'finance' | 'executive' | 'viewer';
  avatarUrl?: string;
  employeeId?: string | null;
  employee_id?: string | null;
  employeeNo?: string | null;
  mustChangePassword?: boolean;
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface PlatformModule {
  id: string;
  tenantId: string;
  moduleKey: string;
  enabled: boolean;
  limits?: Record<string, unknown>;
}

export type ExtensionMaturity = 'workflow' | 'insight' | 'mock' | 'planned';
export type ExtensionCatalogMaturity = 'workflow' | 'summary' | 'configuration' | 'preview';

export interface ExtensionReadMarker {
  id: null;
  featureKey: string;
  persisted: false;
  metricKey?: string;
  createdAt?: string | null;
}

export interface ExtensionFeature {
  key: string;
  name: string;
  packageKey: string;
  defaultEnabled: boolean;
  maturity: ExtensionCatalogMaturity;
  supported: boolean;
  enabled?: boolean;
}

export interface ExtensionPackage {
  key: string;
  name: string;
  features: ExtensionFeature[];
}

export interface ExtensionCatalog {
  releaseCapabilityVersion: 'extension-navigation-v2';
  packages: ExtensionPackage[];
  featureCount: number;
  moduleKeys: string[];
}

export interface ExtensionProviderConfig {
  id?: string;
  providerType: string;
  providerCode: string;
  status: string;
  configJson: Record<string, unknown>;
  secretRef?: string;
  lastTestedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface ExtensionProviderStatus {
  providerType?: string;
  providerCode: string;
  configured: boolean;
  status: string;
  message: string;
  configJson?: Record<string, unknown>;
  lastTestedAt?: string | null;
}

export interface HeadcountDepartmentRow {
  departmentId: string;
  departmentName: string;
  departmentCode?: string | null;
  parentId?: string | null;
  parentName?: string | null;
  plan: number;
  actual: number;
  vacancy: number;
  usageRate: number;
  status: 'unplanned' | 'over' | 'under' | 'full';
  note?: string;
  updatedAt?: string | null;
}

export interface HeadcountExtensionSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: {
    totalPlan: number;
    totalActual: number;
    totalVacancy: number;
    usageRate: number;
    departmentCount: number;
  };
  departments: HeadcountDepartmentRow[];
}

export interface HeadcountUpdateResult {
  departmentId: string;
  departmentName: string;
  oldPlan: number;
  newPlan: number;
  actual: number;
  vacancy: number;
  usageRate: number;
  status: 'unplanned' | 'over' | 'under' | 'full';
  note?: string;
}

export interface HeadcountHistoryItem {
  id: string;
  tenantId: string;
  departmentId: string;
  departmentName?: string | null;
  oldPlan: number;
  newPlan: number;
  actual: number;
  note?: string;
  operatorId?: string | null;
  operatorName?: string | null;
  createdAt?: string | null;
}

export interface HeadcountHistoryPayload {
  items: HeadcountHistoryItem[];
  total: number;
  limit: number;
}

export interface PeopleAnalyticsDistributionRow {
  departmentId?: string;
  departmentName?: string;
  employeeCount?: number;
  label?: string;
  count?: number;
  ratio?: number;
}

export interface PeopleAnalyticsRisk {
  type: 'turnover' | 'performance' | 'headcount' | string;
  level: 'low' | 'medium' | 'high' | string;
  message: string;
}

export interface PeopleAnalyticsExtensionSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: {
    employeeCount: number;
    totalEmployees: number;
    departmentCount: number;
    highPerformerCount: number;
    highPerformerRate: number;
    turnoverRate: number;
    averageSpanOfControl: number;
    dataScope: string;
  };
  distributions: {
    byDepartment: PeopleAnalyticsDistributionRow[];
    performance: PeopleAnalyticsDistributionRow[];
  };
  risks: PeopleAnalyticsRisk[];
  snapshot?: ExtensionReadMarker;
}

export interface ContinuousFeedbackEntry {
  id: string;
  tenantId: string;
  employeeId: string;
  employeeName?: string | null;
  giverId?: string | null;
  giverName?: string | null;
  feedbackType: string;
  category?: string;
  content: string;
  visibility: string;
  sentiment: 'positive' | 'neutral' | 'negative' | string;
  status: 'open' | 'acknowledged' | 'resolved' | 'closed' | string;
  handlerId?: string | null;
  handlerName?: string | null;
  handlerReply?: string | null;
  handledAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface ContinuousFeedbackListPayload {
  featureKey: string;
  items: ContinuousFeedbackEntry[];
  total: number;
  limit: number;
}

export interface ContinuousFeedbackStatsPayload {
  featureKey: string;
  stats: {
    total: number;
    byType: Record<string, number>;
    bySentiment: Record<string, number>;
    byStatus: Record<string, number>;
  };
}

export type TalentFeatureKey =
  | 'profile'
  | 'competency_model'
  | 'succession'
  | 'review'
  | 'career_path'
  | 'idp'
  | 'internal_marketplace';

export interface TalentFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: Record<string, number | string | boolean | null | undefined>;
  profiles?: Array<Record<string, unknown>>;
  models?: Array<Record<string, unknown>>;
  weakestDimensions?: Array<Record<string, unknown>>;
  keyRoles?: Array<Record<string, unknown>>;
  nineBox?: Array<Record<string, unknown>>;
  talents?: Array<Record<string, unknown>>;
  paths?: Array<Record<string, unknown>>;
  plans?: Array<Record<string, unknown>>;
  opportunities?: Array<Record<string, unknown>>;
  snapshot?: ExtensionReadMarker;
}

export type AnalyticsFeatureKey =
  | 'basic_bi'
  | 'custom_reports'
  | 'realtime_dashboard'
  | 'benchmark'
  | 'visualization';

export interface AnalyticsFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: Record<string, number | string | boolean | null | undefined>;
  kpis?: Array<Record<string, unknown>>;
  departmentBreakdown?: Array<Record<string, unknown>>;
  performanceDistribution?: Array<Record<string, unknown>>;
  reports?: Array<Record<string, unknown>>;
  widgets?: Array<Record<string, unknown>>;
  activityFeed?: Array<Record<string, unknown>>;
  benchmarks?: Array<Record<string, unknown>>;
  charts?: Array<Record<string, unknown>>;
  note?: string;
  snapshot?: ExtensionReadMarker;
}

export type IntelligenceFeatureKey =
  | 'predictive'
  | 'turnover_risk'
  | 'ai_recruiting_assistant'
  | 'smart_compensation'
  | 'hr_bot'
  | 'smart_performance'
  | 'advanced_ai_analytics';

export interface IntelligenceFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  provider: {
    providerCode: string;
    configured: boolean;
    status: string;
    message: string;
  };
  summary: Record<string, number | string | boolean | null | undefined>;
  signals?: Array<Record<string, unknown>>;
  predictions?: Array<Record<string, unknown>>;
  riskEmployees?: Array<Record<string, unknown>>;
  candidates?: Array<Record<string, unknown>>;
  profiles?: Array<Record<string, unknown>>;
  intents?: Array<Record<string, unknown>>;
  reviews?: Array<Record<string, unknown>>;
  insights?: Array<Record<string, unknown>>;
  note?: string;
  snapshot?: ExtensionReadMarker;
}

export type CollaborationFeatureKey =
  | 'okr'
  | 'one_on_one'
  | 'survey_enps'
  | 'employee_care'
  | 'social'
  | 'onboarding_experience'
  | 'virtual_assistant'
  | 'feedback_experience';

export interface CollaborationFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  provider?: {
    providerCode: string;
    configured: boolean;
    status: string;
    message: string;
  };
  summary: Record<string, number | string | boolean | null | undefined>;
  objectives?: Array<Record<string, unknown>>;
  suggestions?: Array<Record<string, unknown>>;
  signals?: Array<Record<string, unknown>>;
  careSignals?: Array<Record<string, unknown>>;
  posts?: Array<Record<string, unknown>>;
  tasks?: Array<Record<string, unknown>>;
  intents?: Array<Record<string, unknown>>;
  feedbacks?: Array<Record<string, unknown>>;
  snapshot?: ExtensionReadMarker;
}

export type WorkforceFeatureKey =
  | 'smart_scheduling'
  | 'ai_scheduling'
  | 'planning'
  | 'leave_bank'
  | 'lifecycle_enhancement'
  | 'attendance_optimization'
  | 'shift_marketplace';

export interface WorkforceFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  provider?: {
    providerCode: string;
    configured: boolean;
    status: string;
    message: string;
  };
  summary: Record<string, number | string | boolean | null | undefined>;
  scheduleSuggestions?: Array<Record<string, unknown>>;
  simulations?: Array<Record<string, unknown>>;
  recommendations?: Array<Record<string, unknown>>;
  demandSignals?: Array<Record<string, unknown>>;
  leaveBalances?: Array<Record<string, unknown>>;
  signals?: Array<Record<string, unknown>>;
  abnormalRecords?: Array<Record<string, unknown>>;
  shiftOffers?: Array<Record<string, unknown>>;
  snapshot?: ExtensionReadMarker;
}

export type IntegrationFeatureKey =
  | 'open_api'
  | 'api_key_oauth'
  | 'webhook'
  | 'sso'
  | 'prebuilt_integrations'
  | 'realtime_sync'
  | 'app_marketplace'
  | 'video_meeting'
  | 'im_adapter'
  | 'sms_adapter';

export interface IntegrationFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  provider?: {
    providerType?: string;
    providerCode: string;
    configured: boolean;
    status: string;
    message: string;
    configJson?: Record<string, unknown>;
    lastTestedAt?: string | null;
  };
  summary: Record<string, number | string | boolean | null | undefined>;
  endpoints?: Array<Record<string, unknown>>;
  credentialFlows?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
  protocols?: Array<Record<string, unknown>>;
  providers?: Array<Record<string, unknown>>;
  syncJobs?: Array<Record<string, unknown>>;
  apps?: Array<Record<string, unknown>>;
  meetingTemplates?: Array<Record<string, unknown>>;
  messageTemplates?: Array<Record<string, unknown>>;
  smsTemplates?: Array<Record<string, unknown>>;
  snapshot?: ExtensionReadMarker;
}

export type MobileFeatureKey =
  | 'self_service'
  | 'pwa'
  | 'approval'
  | 'attendance'
  | 'payslip'
  | 'certificate_download'
  | 'notifications'
  | 'offline_shell';

export interface MobileFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: Record<string, number | string | boolean | null | undefined>;
  accounts?: Array<Record<string, unknown>>;
  actions?: Array<Record<string, unknown>>;
  capabilities?: Array<Record<string, unknown>>;
  approvals?: Array<Record<string, unknown>>;
  attendanceRecords?: Array<Record<string, unknown>>;
  payslips?: Array<Record<string, unknown>>;
  certificates?: Array<Record<string, unknown>>;
  notifications?: Array<Record<string, unknown>>;
  resources?: Array<Record<string, unknown>>;
  snapshot?: ExtensionReadMarker;
}

export type SecurityFeatureKey =
  | 'data_masking'
  | 'compliance_reporting'
  | 'audit_logs'
  | 'gdpr'
  | 'database_encryption'
  | 'point_in_time_recovery'
  | 'globalization_locale'
  | 'globalization_currency'
  | 'globalization_timezone'
  | 'globalization_policy'
  | 'data_lifecycle'
  | 'mlps_evidence';

export interface SecurityFeatureSummary {
  featureKey: string;
  status: ExtensionMaturity;
  summary: Record<string, number | string | boolean | null | undefined>;
  maskedSamples?: Array<Record<string, unknown>>;
  controls?: Array<Record<string, unknown>>;
  externalGates?: Array<Record<string, unknown>>;
  dataRequests?: Array<Record<string, unknown>>;
  operationLogs?: Array<Record<string, unknown>>;
  assistantAudits?: Array<Record<string, unknown>>;
  requests?: Array<Record<string, unknown>>;
  rights?: Array<Record<string, unknown>>;
  providers?: Array<Record<string, unknown>>;
  runbookChecks?: Array<Record<string, unknown>>;
  locales?: Array<Record<string, unknown>>;
  currencies?: Array<Record<string, unknown>>;
  timezones?: Array<Record<string, unknown>>;
  regions?: Array<Record<string, unknown>>;
  policies?: Array<Record<string, unknown>>;
  evidenceItems?: Array<Record<string, unknown>>;
  inventory?: Record<string, unknown>;
  deletionPlan?: Record<string, unknown>;
  externalGate?: Record<string, unknown>;
  snapshot?: ExtensionReadMarker;
}

export interface ExtensionFeatureStatus {
  featureKey: string;
  name: string;
  status: ExtensionMaturity;
  defaultVisible: boolean;
  acceptance: Record<string, string>;
}

export interface PlatformUsage {
  users: number;
  employees: number;
  storageMb: number;
  aiCallsThisMonth: number;
  checkedAt: string;
}

export interface PlatformOnboardingItem {
  id: string;
  tenantId: string;
  key: string;
  label?: string;
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
  note?: string | null;
  completedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface PlatformDataRequest {
  id: string;
  tenantId: string;
  requestType: 'export' | 'deletion';
  requester: string;
  scope: string;
  status: 'requested' | 'identity_verified' | 'approved' | 'export_generated' | 'delivered' | 'closed' | 'rejected';
  evidenceRef?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface PlatformSubscription {
  id?: string;
  tenantId?: string;
  planCode?: string;
  status?: string;
  startsAt?: string | null;
  endsAt?: string | null;
}

export interface PlatformTenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  planCode?: string;
  maxUsers?: number;
  maxEmployees?: number;
  maxStorageMb?: number;
  aiMonthlyQuota?: number;
  expiresAt?: string | null;
  modules?: PlatformModule[];
  admin?: User;
  admins?: User[];
  initialPassword?: string;
  usage?: PlatformUsage;
  subscription?: PlatformSubscription | null;
}

export interface ResetTenantAdminPasswordPayload {
  userId: string;
  confirmation: string;
}

export interface PlatformPlan {
  code: string;
  name: string;
  enabledModules: string[];
  limits: Record<string, unknown>;
  isActive: boolean;
}

export interface PlatformOrder {
  id: string;
  tenantId: string;
  subscriptionId?: string | null;
  orderNo: string;
  amountCents: number;
  currency: string;
  status: string;
  createdAt?: string;
  paidAt?: string | null;
}

export interface PlatformInvoice {
  id: string;
  tenantId: string;
  orderId?: string | null;
  title: string;
  taxNo?: string | null;
  amountCents: number;
  status: string;
  createdAt?: string;
  issuedAt?: string | null;
}

export interface PlatformBillingEvent {
  id: string;
  tenantId: string;
  eventType: string;
  note: string;
  operatorId?: string | null;
  operatorName?: string | null;
  createdAt?: string;
}

export interface PlatformTenantDiagnostics {
  usage?: Partial<PlatformUsage>;
  disk?: {
    totalMb?: number;
    usedMb?: number;
    freeMb?: number;
  };
  checkedAt?: string;
}

export interface PlatformOperationLog {
  id: string;
  createdAt?: string;
  action?: string;
  tenantId?: string | null;
  tenantName?: string | null;
  userId?: string | null;
  userName?: string | null;
  detail?: Record<string, unknown> | string | null;
}

export type EnterpriseApplicationStatus = 'new' | 'contacting' | 'qualified' | 'closed' | 'converted';

export interface EnterpriseApplicationCreatePayload {
  companyName: string;
  contactName: string;
  mobile: string;
  email?: string;
  region?: string;
  employeeScale?: string;
  interestedModules: string[];
  preferredContactTime?: string;
  notes?: string;
  privacyConsent: true;
  website: string;
}

export interface EnterpriseApplicationCreated {
  applicationNo: string;
  status: 'new';
}

export interface EnterpriseApplicationListItem {
  id: string;
  applicationNo: string;
  companyName: string;
  region?: string | null;
  employeeScale?: string | null;
  status: EnterpriseApplicationStatus;
  ownerUserId?: string | null;
  ownerName?: string | null;
  convertedTenantId?: string | null;
  convertedTenantName?: string | null;
  source: string;
  version: number;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface EnterpriseApplicationTimelineEvent {
  status: EnterpriseApplicationStatus;
  label: string;
  at: string;
}

export interface EnterpriseServiceApplication extends EnterpriseApplicationListItem {
  contactName: string;
  mobile: string;
  email?: string | null;
  interestedModules: string[];
  preferredContactTime?: string | null;
  notes?: string | null;
  followUpAt?: string | null;
  internalNote?: string | null;
  consentAt?: string | null;
  timeline: EnterpriseApplicationTimelineEvent[];
}

export interface EnterpriseApplicationSummary {
  todayNew: number;
  new: number;
  contacting: number;
  qualified: number;
  closed: number;
  converted: number;
}

export interface EnterpriseApplicationPage {
  items: EnterpriseApplicationListItem[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface EnterpriseApplicationUpdatePayload {
  version: number;
  status?: EnterpriseApplicationStatus;
  ownerUserId?: string | null;
  followUpAt?: string | null;
  internalNote?: string | null;
}

export interface AIProviderConfig {
  id: string;
  providerCode: string;
  displayName: string;
  baseUrl: string;
  hasApiKey: boolean;
  maskedApiKey?: string | null;
  enabled: boolean;
  settings?: Record<string, unknown>;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AIModelPolicy {
  id: string;
  resourceDomain: string;
  useCase: string;
  tier: string;
  providerCode?: string;
  modelProfile?: string;
  model?: string;
  maxTokens?: number;
  enabled: boolean;
  settings?: Record<string, unknown>;
}

export interface AIAddonPackage {
  code: string;
  name: string;
  resourceDomains: string[];
  allowedTiers: string[];
  defaultMonthlyQuota: number;
  isActive: boolean;
}

export interface TenantAIEntitlement {
  id?: string | null;
  tenantId: string;
  resourceDomain: string;
  resourceLabel?: string;
  packageCode?: string | null;
  packageName?: string | null;
  enabled: boolean;
  selectedTier?: string | null;
  allowedTiers: string[];
  monthlyQuota: number;
  usedThisMonth: number;
  remainingQuota?: number | null;
  tierLabels?: Record<string, string>;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AIUsageLedgerItem {
  id: string;
  tenantId?: string | null;
  userId?: string | null;
  userName?: string | null;
  resourceDomain: string;
  useCase?: string | null;
  tier?: string | null;
  status: string;
  units: number;
  requestId?: string | null;
  promptChars?: number;
  responseChars?: number;
  errorCode?: string | null;
  createdAt?: string | null;
  provider?: string | null;
  model?: string | null;
  assistantAuditLogId?: string | null;
  meta?: Record<string, unknown>;
}

export interface TenantAIEntitlementPayload {
  tenantId: string;
  entitlements: TenantAIEntitlement[];
}

export interface TenantAIUsagePayload {
  tenantId: string;
  periodKey: string;
  total: number;
  byDomain: Record<string, number>;
  items: AIUsageLedgerItem[];
}

export interface ScoringCriterion {
  name: string;
  weight: number;
  description: string;
}

export interface Job {
  id: string;
  title: string;
  description: string;
  status: 'open' | 'closed';
  category?: string;
  department?: string;
  departmentId?: string;
  level?: string;
  responsibilities?: string;
  requirements?: string;
  headcount?: number;
  location?: string;
  employmentType?: string;
  salaryRange?: string;
  scoringCriteria?: ScoringCriterion[];
  createdAt: string;
  updatedAt: string;
  createdBy?: string;
  createdByName?: string;
  updatedBy?: string;
  updatedByName?: string;
}

export const DEFAULT_SCORING_CRITERIA: ScoringCriterion[] = [
  { name: '基本信息完整性', weight: 10, description: '联系方式、教育背景、工作经历等是否齐全' },
  { name: '教育背景与专业匹配度', weight: 15, description: '学历、学校、专业是否符合岗位要求' },
  { name: '工作/项目经历质量', weight: 25, description: '经历相关性、成果量化、职责深度（最重要）' },
  { name: '技能与证书匹配度', weight: 15, description: '是否具备岗位所需硬技能、工具、认证' },
  { name: '成就与成果量化', weight: 15, description: '是否用数据体现贡献（如"提升30%效率"）' },
  { name: '结构与表达能力', weight: 10, description: '简历逻辑清晰、语言专业、无错别字' },
  { name: '个性化与求职动机', weight: 10, description: '自我评价、求职信、职业目标是否贴合岗位' },
];

export interface Resume {
  id: string;
  jobId: string;
  candidateName: string;
  email?: string;
  phone?: string;
  fileUrl: string;
  aiAnalysis?: {
    score: number;
    matchDegree: number;
    skills: string[];
    experience: string;
    education: string;
    summary: string;
    strengths: string[];
    weaknesses: string[];
    recommendation: string;
    interviewFocus?: string[];
    interviewQuestions?: Array<{
      question: string;
      purpose: string;
    }>;
    aiStatus?: {
      success: boolean;
      modelUsed?: string;
      fallbackUsed: boolean;
      errorMessage?: string;
      totalAttempts: number;
      usingManualFallback?: boolean;
    };
  };
  tags: string[];
  createdAt: string;
  updatedAt?: string;
  createdBy?: string;
  createdByName?: string;
  updatedBy?: string;
  updatedByName?: string;
}

// 面试AI分析结果类型
export interface InterviewAIAnalysis {
  overallScore: number;
  overallLevel: '优秀' | '良好' | '一般' | '待提升' | '不合格';
  recommendation: '强烈推荐录用' | '推荐录用' | '建议复试' | '暂不推荐' | '不推荐';
  dimensions: {
    professionalScore: number;  // 专业能力
    communicationScore: number; // 沟通表达
    teamworkScore: number;      // 团队协作
    learningScore: number;      // 学习能力
    cultureScore: number;       // 文化匹配
  };
  summary: string;
  strengths: string[];
  weaknesses: string[];
  keyObservations?: Array<{
    aspect: string;
    observation: string;
    suggestion: string;
  }>;
  riskFactors?: string[];
  hiringAdvice: string;
  followUpQuestions?: string[];
  onboardingTips?: string[];
}

export interface Interview {
  id: string;
  jobId: string;
  resumeId: string;
  scheduledAt: string;
  status: 'scheduled' | 'completed' | 'cancelled' | 'in_progress';
  notes?: string;
  // AI分析相关字段
  feedbackText?: string;
  feedbackFileUrl?: string;
  feedbackFileType?: 'text' | 'audio' | 'video';
  aiAnalysis?: InterviewAIAnalysis;
  analyzedAt?: string;
  // 在线面试相关字段
  roomId?: string;
  inviteToken?: string;
  recordingUrl?: string;
  transcript?: string;
  meetingStartedAt?: string;
  meetingEndedAt?: string;
  // 创建人和更新人
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
  createdByName?: string;
  updatedBy?: string;
  updatedByName?: string;
}

// 候选人邀约信息
export interface InterviewInvite {
  interview: {
    id: string;
    scheduledAt: string;
    status: string;
    roomId: string;
  };
  job: {
    title: string;
    department?: string;
  };
  candidate: {
    name: string;
  };
}

export interface ReportSummary {
  totals: {
    jobs: number;
    resumes: number;
    interviews: number;
    users: number;
  };
}

export interface WorkflowTransition {
  key: string;
  label: string;
  enabled: boolean;
  from: string[];
  to: string;
}

export interface DomainTimelineEvent {
  id: string;
  eventType: 'created' | 'operation' | string;
  module: string;
  action: string;
  actorId?: string | null;
  actorName?: string | null;
  at?: string | null;
  title?: string;
  detail?: Record<string, unknown>;
}

export interface DomainWorkflowPayload<TRecord = any> {
  resource: string;
  recordId: string;
  status?: string | null;
  record: TRecord;
  transitions: WorkflowTransition[];
  timeline: DomainTimelineEvent[];
}

// API方法
export const authApi = {
  login: (identifier: string, password: string, accountType: 'hrm' | 'employee_portal' = 'hrm', tenantSlug = 'HPT-00000001') =>
    accountType === 'employee_portal'
      ? apiClient.post<LoginResponse>('/portal/auth/login', { employeeNo: identifier, identifier, password, tenantSlug })
      : apiClient.post<LoginResponse>('/auth/login', { identifier, email: identifier, password, tenantSlug }),
  platformLogin: (identifier: string, password: string) =>
    apiClient.post<LoginResponse>('/platform/auth/login', { identifier, email: identifier, password }),
  changePassword: (currentPassword: string, newPassword: string, accountType: 'hrm' | 'employee_portal' = 'hrm') =>
    accountType === 'employee_portal'
      ? apiClient.post<LoginResponse>('/portal/auth/change-password', { currentPassword, newPassword })
      : apiClient.post<LoginResponse>('/auth/change-password', { currentPassword, newPassword }),
};

export const createIdempotencyKey = (): string => genRequestId();

export const publicEnterpriseApplicationApi = {
  create: (data: EnterpriseApplicationCreatePayload, idempotencyKey: string) =>
    apiClient.postPublic<EnterpriseApplicationCreated>('/public/enterprise-applications', data, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
};

export const platformApi = {
  listPlans: () => apiClient.get<PlatformPlan[]>('/platform/plans'),
  listTenants: (
    params?: { status?: string; keyword?: string; page?: number; pageSize?: number },
    options: RequestInit = {},
  ) =>
    apiClient.get<PlatformTenant[]>(`/platform/tenants${buildQuery(params || {})}`, options),
  getTenant: (id: string) => apiClient.get<PlatformTenant>(`/platform/tenants/${id}`),
  createTenant: (data: Record<string, unknown>) => apiClient.post<PlatformTenant>('/platform/tenants', data),
  updateTenant: (id: string, data: Record<string, unknown>) => apiClient.put<PlatformTenant>(`/platform/tenants/${id}`, data),
  updateTenantModules: (id: string, modules: PlatformModule[]) =>
    apiClient.put<{ modules: PlatformModule[] }>(`/platform/tenants/${id}/modules`, { modules }),
  resetAdminPassword: (id: string, data: ResetTenantAdminPasswordPayload) =>
    apiClient.post<{ user: User; initialPassword: string }>(`/platform/tenants/${id}/reset-admin-password`, data),
  listTenantOrders: (id: string) => apiClient.get<PlatformOrder[]>(`/platform/tenants/${id}/orders`),
  listTenantInvoices: (id: string) => apiClient.get<PlatformInvoice[]>(`/platform/tenants/${id}/invoices`),
  updateTenantInvoice: (tenantId: string, invoiceId: string, data: Record<string, unknown>) =>
    apiClient.put<PlatformInvoice>(`/platform/tenants/${tenantId}/invoices/${invoiceId}`, data),
  listTenantBillingEvents: (id: string) =>
    apiClient.get<PlatformBillingEvent[]>(`/platform/tenants/${id}/billing-events`),
  createTenantBillingEvent: (tenantId: string, data: { eventType: string; note: string }) =>
    apiClient.post<PlatformBillingEvent>(`/platform/tenants/${tenantId}/billing-events`, data),
  listTenantOnboardingChecklist: (id: string) =>
    apiClient.get<{ tenantId: string; items: PlatformOnboardingItem[] }>(`/platform/tenants/${id}/onboarding-checklist`),
  updateTenantOnboardingItem: (tenantId: string, key: string, data: Record<string, unknown>) =>
    apiClient.put<PlatformOnboardingItem>(`/platform/tenants/${tenantId}/onboarding-checklist/${key}`, data),
  listTenantDataRequests: (id: string) =>
    apiClient.get<PlatformDataRequest[]>(`/platform/tenants/${id}/data-requests`),
  createTenantDataRequest: (tenantId: string, data: Record<string, unknown>) =>
    apiClient.post<PlatformDataRequest>(`/platform/tenants/${tenantId}/data-requests`, data),
  updateTenantDataRequest: (tenantId: string, requestId: string, data: Record<string, unknown>) =>
    apiClient.put<PlatformDataRequest>(`/platform/tenants/${tenantId}/data-requests/${requestId}`, data),
  diagnostics: (id: string) => apiClient.get<PlatformTenantDiagnostics>(`/platform/tenants/${id}/diagnostics`),
  operationLogs: (params?: { tenantId?: string; action?: string }) =>
    apiClient.get<PlatformOperationLog[]>(`/platform/operation-logs${buildQuery(params || {})}`),
};

export const platformEnterpriseApplicationApi = {
  summary: (options: RequestInit = {}) =>
    apiClient.get<EnterpriseApplicationSummary>('/platform/enterprise-applications/summary', options),
  list: async (
    params?: { status?: EnterpriseApplicationStatus | ''; keyword?: string; page?: number; pageSize?: number },
    options: RequestInit = {},
  ) => {
    const page = await apiClient.post<EnterpriseApplicationPage>(
      '/platform/enterprise-applications/search',
      params || {},
      options,
    );
    return {
      ...page,
      items: page.items.map(item => (
        normalizeEnterpriseApplicationListItem(item as unknown as Record<string, unknown>) as unknown as EnterpriseApplicationListItem
      )),
    };
  },
  detail: (id: string, options: RequestInit = {}) =>
    apiClient.get<EnterpriseServiceApplication>(`/platform/enterprise-applications/${id}`, options),
  update: (id: string, data: EnterpriseApplicationUpdatePayload, options: RequestInit = {}) => apiClient.patch<EnterpriseServiceApplication>(
    `/platform/enterprise-applications/${id}`,
    data,
    options,
  ),
  convert: (id: string, tenantId: string, version: number, options: RequestInit = {}) =>
    apiClient.post<EnterpriseServiceApplication>(
      `/platform/enterprise-applications/${id}/convert`,
      { tenantId, version },
      options,
    ),
};

export const platformExtensionApi = {
  catalog: () => apiClient.get<ExtensionCatalog>('/platform/extensions/catalog'),
  providers: () => apiClient.get<ExtensionProviderConfig[]>('/platform/extensions/providers'),
  getProvider: (providerCode: string) =>
    apiClient.get<ExtensionProviderConfig>(`/platform/extensions/providers/${providerCode}`),
  updateProvider: (providerCode: string, data: Record<string, unknown>) =>
    apiClient.put<ExtensionProviderConfig>(`/platform/extensions/providers/${providerCode}`, data),
};

export const platformAiApi = {
  providers: () => apiClient.get<AIProviderConfig[]>('/platform/ai/providers'),
  updateProvider: (providerCode: string, data: Record<string, unknown>) =>
    apiClient.put<AIProviderConfig>(`/platform/ai/providers/${providerCode}`, data),
  modelPolicies: () => apiClient.get<AIModelPolicy[]>('/platform/ai/model-policies'),
  createModelPolicy: (data: Record<string, unknown>) =>
    apiClient.post<AIModelPolicy>('/platform/ai/model-policies', data),
  updateModelPolicy: (id: string, data: Record<string, unknown>) =>
    apiClient.put<AIModelPolicy>(`/platform/ai/model-policies/${id}`, data),
  addonPackages: () => apiClient.get<AIAddonPackage[]>('/platform/ai/addon-packages'),
  tenantEntitlements: (tenantId: string) =>
    apiClient.get<TenantAIEntitlementPayload>(`/platform/tenants/${tenantId}/ai-entitlements`),
  updateTenantEntitlements: (tenantId: string, entitlements: TenantAIEntitlement[]) =>
    apiClient.put<TenantAIEntitlementPayload>(`/platform/tenants/${tenantId}/ai-entitlements`, { entitlements }),
  tenantUsage: (tenantId: string) =>
    apiClient.get<TenantAIUsagePayload>(`/platform/tenants/${tenantId}/ai-usage`),
  runModelDiagnostic: (payload: Record<string, unknown>) =>
    apiClient.post<any>('/platform/ai/diagnostics/model-call-test', payload),
};

export const jobsApi = {
  getAll: () => apiClient.get<Job[]>('/jobs/'),
  
  create: (title: string, description: string) =>
    apiClient.post<Job>('/jobs/', { title, description }),
  
  update: (id: string, data: Partial<Pick<Job, 'title' | 'description' | 'status' | 'scoringCriteria'>>) =>
    apiClient.put<Job>(`/jobs/${id}`, data),
  
  delete: (id: string) =>
    apiClient.delete<{ removed: boolean }>(`/jobs/${id}`),
};

export const resumesApi = {
  getAll: () => apiClient.get<Resume[]>('/resumes/'),
  
  upload: (file: File, jobId: string) =>
    apiClient.uploadFile<Resume>('/resumes/upload', file, { jobId }),
  
  update: (id: string, data: Partial<Pick<Resume, 'candidateName' | 'tags'>>) =>
    apiClient.put<Resume>(`/resumes/${id}`, data),
  
  delete: (id: string) =>
    apiClient.delete<{ removed: boolean }>(`/resumes/${id}`),
  
  reanalyze: (id: string) =>
    apiClient.post<Resume>(`/resumes/${id}/reanalyze`),
};

export const interviewsApi = {
  getAll: () => apiClient.get<Interview[]>('/interviews/'),
  
  create: (jobId: string, resumeId: string, scheduledAt: string, notes?: string) =>
    apiClient.post<Interview>('/interviews/', { jobId, resumeId, scheduledAt, notes }),
  
  update: (id: string, data: Partial<Pick<Interview, 'scheduledAt' | 'status' | 'notes'>>) =>
    apiClient.put<Interview>(`/interviews/${id}`, data),
  
  delete: (id: string) =>
    apiClient.delete<{ removed: boolean }>(`/interviews/${id}`),
  
  // AI分析相关API
  analyzeText: (id: string, feedbackText: string) =>
    apiClient.post<Interview>(`/interviews/${id}/analyze/text`, { feedbackText }),
  
  analyzeMedia: (id: string, file: File) =>
    apiClient.uploadFile<Interview | { message: string; fileUrl: string; status: string; interview: Interview }>(
      `/interviews/${id}/analyze/media`, 
      file
    ),
  
  clearAnalysis: (id: string) =>
    apiClient.delete<{ cleared: boolean; interview: Interview }>(`/interviews/${id}/analyze`),
  
  // 在线面试相关API
  getInvite: (inviteToken: string) =>
    apiClient.get<InterviewInvite>(`/interviews/invite/${inviteToken}`),
  
  startMeeting: (id: string) =>
    apiClient.post<Interview>(`/interviews/${id}/meeting/start`),
  
  endMeeting: (id: string) =>
    apiClient.post<Interview>(`/interviews/${id}/meeting/end`),
  
  uploadRecording: (id: string, file: File) =>
    apiClient.uploadFile<{ success: boolean; interview: Interview; transcriptSuccess: boolean; transcriptError: string }>(
      `/interviews/${id}/recording`,
      file
    ),
  
  regenerateRoom: (id: string) =>
    apiClient.post<Interview>(`/interviews/${id}/regenerate-room`),
};

export interface Activity {
  type: string;
  icon: string;
  iconColor: string;
  title: string;
  description: string;
  detail: string;
  timestamp: string;
}

export const miscApi = {
  getReportSummary: () =>
    apiClient.get<ReportSummary>('/report/summary'),
  
  getRecentActivities: () =>
    apiClient.get<{ activities: Activity[] }>('/recent-activities'),
  
  getSettings: () =>
    apiClient.get<Record<string, unknown>>('/settings'),
  
  updateSettings: (settings: Record<string, unknown>) =>
    apiClient.post<Record<string, unknown>>('/settings', settings),
};


// HRM通用接口
const buildQuery = (params?: Record<string, string | number | boolean | undefined | null>) => {
  if (!params) return '';
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');
  return query ? `?${query}` : '';
};

export interface HrmDashboard {
  cards: Record<string, number>;
  departmentDistribution: Array<{ name: string; value: number }>;
  employeeStatusDistribution: Array<{ name: string; value: number }>;
  requestDistribution: Array<{ name: string; value: number }>;
  performanceDistribution: Array<{ name: string; value: number }>;
  aiAdvice?: string;
}

export interface HrmPageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface AccountPasswordResetResult {
  account: {
    id: string;
    accountType: 'hrm' | 'employee_portal';
    name?: string;
    email?: string;
    employeeId?: string;
    employeeNo?: string;
    mustChangePassword: boolean;
  };
  initialPassword: string;
  requestId?: string;
}

export type AccountCredentialResult = AccountPasswordResetResult;

export interface AttendanceSyncRun {
  id: string;
  trigger: string;
  status: string;
  peopleRead: number;
  peopleUpserted: number;
  punchesRead: number;
  punchesInserted: number;
  punchesDuplicate: number;
  unmatchedCount: number;
  suggestedCount: number;
  lookbackDays: number;
  cursorCheckTime?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface AttendanceSyncStatus {
  enabled: boolean;
  configured: boolean;
  tenantSlug: string;
  latestRun: AttendanceSyncRun | null;
  people: {
    unmatched: number;
    suggested: number;
    confirmed: number;
    ignored: number;
  };
  punchCount: number;
  dailyRecordCount?: number;
}

export interface AttendanceExternalPerson {
  id: string;
  externalUserId: string;
  badgeNumber?: string | null;
  name: string;
  departmentName?: string | null;
  employeeId?: string | null;
  employeeNo?: string | null;
  employeeName?: string | null;
  employeeStatus?: string | null;
  suggestedEmployeeId?: string | null;
  suggestedEmployeeNo?: string | null;
  suggestedEmployeeName?: string | null;
  mappingStatus: 'unmatched' | 'suggested' | 'confirmed' | 'ignored' | string;
  mappedAt?: string | null;
  sourceSyncedAt?: string | null;
}

export interface AttendanceShift {
  id: string;
  tenantId?: string;
  code: string;
  name: string;
  shiftType: 'fixed' | 'flexible' | string;
  startTime?: string | null;
  endTime?: string | null;
  crossDay: boolean;
  requiredWorkHours?: string | number | null;
  lateGraceMinutes: number;
  earlyLeaveGraceMinutes: number;
  requireCheckIn: boolean;
  requireCheckOut: boolean;
  status: 'active' | 'inactive' | string;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceRuleSet {
  id: string;
  tenantId?: string;
  code: string;
  name: string;
  version: number;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  status: 'active' | 'inactive' | string;
  absentIfNoPunch: boolean;
  missingCardIfSinglePunch: boolean;
  lateGraceMinutes?: number | null;
  earlyLeaveGraceMinutes?: number | null;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceGroup {
  id: string;
  tenantId?: string;
  code: string;
  name: string;
  defaultShiftId?: string | null;
  defaultShiftName?: string | null;
  defaultRuleSetId?: string | null;
  defaultRuleSetName?: string | null;
  priority: number;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  status: 'active' | 'inactive' | string;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceGroupMembership {
  id: string;
  tenantId?: string;
  groupId: string;
  groupName?: string | null;
  employeeId?: string | null;
  employeeName?: string | null;
  departmentId?: string | null;
  departmentName?: string | null;
  positionId?: string | null;
  positionTitle?: string | null;
  scopeType?: 'employee' | 'department' | 'position' | string | null;
  scopeName?: string | null;
  priority: number;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  status: 'active' | 'inactive' | string;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceHoliday {
  id: string;
  tenantId?: string;
  holidayDate: string;
  name: string;
  dayType: 'holiday' | 'working_day' | 'company_rest' | string;
  status: 'active' | 'inactive' | string;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceSchedule {
  id: string;
  tenantId?: string;
  employeeId: string;
  employeeName?: string | null;
  scheduleDate: string;
  dayType: 'workday' | 'rest' | 'holiday' | string;
  shiftId?: string | null;
  shiftName?: string | null;
  source: string;
  remark?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendanceDailyResult {
  id: string;
  tenantId?: string;
  employeeId: string;
  employeeName?: string | null;
  attendanceDate: string;
  dayType: string;
  scheduleSource?: string | null;
  groupId?: string | null;
  groupName?: string | null;
  shiftId?: string | null;
  shiftName?: string | null;
  ruleSetId?: string | null;
  ruleSetName?: string | null;
  scheduledStart?: string | null;
  scheduledEnd?: string | null;
  checkInTime?: string | null;
  checkOutTime?: string | null;
  workHours?: string | number | null;
  status: string;
  lateMinutes: number;
  earlyLeaveMinutes: number;
  sourcePunchIds: string[];
  requestIds: string[];
  explanation: Record<string, unknown>;
  calculationVersion: string;
  calculatedAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AttendancePolicySnapshot {
  shifts: AttendanceShift[];
  ruleSets: AttendanceRuleSet[];
  groups: AttendanceGroup[];
  memberships: AttendanceGroupMembership[];
  holidays: AttendanceHoliday[];
  schedules: AttendanceSchedule[];
  generatedAt?: string;
}

export type AttendancePolicyKind = 'shifts' | 'rule-sets' | 'groups' | 'memberships' | 'holidays' | 'schedules';

export const hrmApi = {
  getDashboard: () => apiClient.get<HrmDashboard>('/hrm/dashboard'),
  getMeta: () => apiClient.get<Record<string, unknown>>('/hrm/meta'),
  getTenantModules: () => apiClient.get<PlatformModule[]>('/hrm/tenant/modules'),
  list: <T = any>(resource: string, params?: Record<string, string | number | boolean | undefined | null>) =>
    apiClient.get<T[]>(`/hrm/${resource}${buildQuery(params)}`),
  listPage: <T = any>(resource: string, params: Record<string, string | number | boolean | undefined | null>) =>
    apiClient.get<HrmPageResult<T>>(`/hrm/${resource}${buildQuery(params)}`),
  get: <T = any>(resource: string, id: string) =>
    apiClient.get<T>(`/hrm/${resource}/${id}`),
  create: <T = any>(resource: string, data: Record<string, unknown>) =>
    apiClient.post<T>(`/hrm/${resource}`, data),
  createUser: (data: Record<string, unknown>) =>
    apiClient.post<AccountCredentialResult>('/hrm/users/create', data),
  update: <T = any>(resource: string, id: string, data: Record<string, unknown>) =>
    apiClient.put<T>(`/hrm/${resource}/${id}`, data),
  remove: (resource: string, id: string) =>
    apiClient.delete<{ removed: boolean }>(`/hrm/${resource}/${id}`),
  resetUserPassword: (userId: string) =>
    apiClient.post<AccountPasswordResetResult>(`/hrm/users/${userId}/reset-password`, {}),
  resetEmployeePortalPassword: (employeeId: string) =>
    apiClient.post<AccountPasswordResetResult>(`/hrm/employees/${employeeId}/reset-portal-password`, {}),
  getWorkflow: <T = any>(resource: string, id: string) =>
    apiClient.get<DomainWorkflowPayload<T>>(`/hrm/${resource}/${id}/workflow`),
  runWorkflowTransition: <T = any>(resource: string, id: string, transition: string, data?: Record<string, unknown>) =>
    apiClient.post<{ record: T; workflow: DomainWorkflowPayload<T> }>(`/hrm/${resource}/${id}/workflow/${transition}`, data || {}),
  postAction: <T = any>(path: string, data?: Record<string, unknown>) =>
    apiClient.post<T>(`/hrm/${path}`, data || {}),
  approvals: (kind: 'my-applications' | 'pending' | 'records') =>
    apiClient.get<any[]>(`/hrm/approvals/${kind}`),
  handleApproval: (id: string, action: 'approve' | 'reject', comment?: string) =>
    apiClient.post<any>(`/hrm/approvals/${id}/${action}`, { comment }),
  attendanceMonthly: (month: string) =>
    apiClient.get<{ month: string; records: any[] }>(`/hrm/attendance/monthly${buildQuery({ month })}`),
  attendanceSyncStatus: () =>
    apiClient.get<AttendanceSyncStatus>('/hrm/attendance-sync/status'),
  runAttendanceSync: () =>
    apiClient.post<AttendanceSyncRun & { runId?: string }>('/hrm/attendance-sync/run', {}),
  listAttendanceSyncPeople: (status?: string) =>
    apiClient.get<AttendanceExternalPerson[]>(`/hrm/attendance-sync/people${buildQuery({ status })}`),
  confirmAttendanceSyncPerson: (personId: string, employeeId: string) =>
    apiClient.post<AttendanceExternalPerson>(`/hrm/attendance-sync/people/${personId}/confirm`, { employeeId }),
  ignoreAttendanceSyncPerson: (personId: string) =>
    apiClient.post<AttendanceExternalPerson>(`/hrm/attendance-sync/people/${personId}/ignore`, {}),
  attendancePolicySnapshot: () =>
    apiClient.get<AttendancePolicySnapshot>('/hrm/attendance-policy/snapshot'),
  listAttendanceDailyResults: (params?: Record<string, string | number | undefined | null>) =>
    apiClient.get<AttendanceDailyResult[]>(`/hrm/attendance-policy/daily-results${buildQuery(params)}`),
  recalculateAttendanceDailyResults: (data: { startDate: string; endDate: string; employeeId?: string }) =>
    apiClient.post<Record<string, unknown>>('/hrm/attendance-policy/recalculate', data),
  createAttendancePolicyRow: <T = Record<string, unknown>>(kind: AttendancePolicyKind, data: Record<string, unknown>) =>
    apiClient.post<T>(`/hrm/attendance-policy/${kind}`, data),
  updateAttendancePolicyRow: <T = Record<string, unknown>>(kind: AttendancePolicyKind, id: string, data: Record<string, unknown>) =>
    apiClient.put<T>(`/hrm/attendance-policy/${kind}/${id}`, data),
  deleteAttendancePolicyRow: (kind: AttendancePolicyKind, id: string) =>
    apiClient.delete<{ deleted: boolean; id: string }>(`/hrm/attendance-policy/${kind}/${id}`),
  ai: (scene: string, payload: Record<string, unknown>) =>
    apiClient.post<{ scene: string; summary: string; suggestions: string[]; generatedAt: string }>(`/hrm/ai/${scene}`, payload),
  aiEntitlements: () =>
    apiClient.get<TenantAIEntitlementPayload>('/hrm/ai/entitlements'),
  aiUsage: () =>
    apiClient.get<TenantAIUsagePayload>('/hrm/ai/usage'),
  selectAiTier: (resourceDomain: string, tier: string) =>
    apiClient.post<{ entitlement: TenantAIEntitlement }>(`/hrm/ai/entitlements/${resourceDomain}/select-tier`, { tier }),
  uploadFeedbackAttachment: (file: File) =>
    apiClient.uploadFile<{ name: string; url: string; size: number; type: 'image' | 'document'; ext: string }>(
      '/hrm/feedback-attachments',
      file
    ),
  assistantQuery: (question: string, sessionId?: string, options?: { signal?: AbortSignal; clientContext?: any }) =>
    apiClient.post<{
      schemaVersion?: string;
      question: string;
      summary: string;
      answer?: { content?: string; format?: string };
      entities: Array<{
        type: string;
        typeLabel: string;
        icon: string;
        id: string;
        title: string;
        subtitle: string;
        meta: string;
        url: string;
      }>;
      widgets?: Array<{
        type: 'metrics' | 'metric_cards' | 'bar' | 'bar_chart' | 'donut' | 'doughnut_chart' | 'table' | 'data_table' | 'entity_cards' | 'warning' | 'markdown' | 'workset_summary' | 'confirmation_card' | 'follow_up_actions' | 'source_citations' | 'mermaid_diagram' | 'echarts' | 'clarification';
        title?: string;
        centerLabel?: string;
        data?: any;
        metrics?: any[];
        table?: any;
        cards?: any[];
        entities?: any[];
        workset?: any;
        content?: string;
        question?: string;
        options?: Array<{ label: string; payload?: string }>;
        sources?: any[];
        actions?: any[];
        level?: 'info' | 'warning' | 'danger';
        message?: string;
      }>;
      actions?: any[];
      worksets?: any[];
      renderBlocks?: any[];
      copilot?: any;
      clientContext?: any;
      sessionId: string | null;
      generatedAt: string;
      meta?: any;
    }>('/hrm/assistant/query', { question, sessionId, clientContext: options?.clientContext }, { signal: options?.signal }),
  assistantQueryStream: async (
    question: string,
    sessionId?: string,
    options?: {
      signal?: AbortSignal;
      clientContext?: any;
      onStatus?: (message: string) => void;
      onDelta?: (content: string) => void;
      onFinal?: (payload: any) => void;
    },
  ) => {
    const token = authUtils.getToken();
    const requestId = genRequestId();
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream, application/json',
      'X-Request-ID': requestId,
      ...(token && { Authorization: `Bearer ${token}` }),
    };

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/hrm/assistant/query`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ question, sessionId, stream: true, clientContext: options?.clientContext }),
        signal: options?.signal,
      });
    } catch (e: any) {
      if (e?.name === 'AbortError') throw e;
      throw new ApiError('网络异常，请检查连接后重试', 0, requestId);
    }

    if (!response.ok) {
      const text = await response.text();
      let message = `请求失败 (${response.status})`;
      try {
        const error = JSON.parse(text);
        message = error.error || error.msg || message;
      } catch {
        message = safeApiErrorMessage(text, response.status, message);
      }
      throw new ApiError(message, response.status, response.headers.get('X-Request-ID') || requestId);
    }

    const contentType = response.headers.get('Content-Type') || '';
    if (!contentType.includes('text/event-stream') || !response.body) {
      const payload = await response.json();
      options?.onFinal?.(payload);
      return payload;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalPayload: any = null;
    let streamError: any = null;

    const dispatchEvent = (raw: string) => {
      const lines = raw.split('\n');
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      let payload: any = null;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        payload = { content: dataLines.join('\n') };
      }
      if (event === 'status') {
        options?.onStatus?.(payload.message || payload.content || '');
      } else if (event === 'delta') {
        options?.onDelta?.(payload.content || payload.text || '');
      } else if (event === 'error') {
        streamError = payload;
      } else if (event === 'final') {
        finalPayload = payload;
        options?.onFinal?.(payload);
      } else if (payload?.summary || payload?.answer) {
        finalPayload = payload;
        options?.onFinal?.(payload);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      parts.forEach(dispatchEvent);
    }
    if (buffer.trim()) dispatchEvent(buffer);
    if (streamError) {
      throw new ApiError(streamError.error || '助手请求失败', response.status || 500, requestId);
    }
    return finalPayload || {};
  },
  assistantSkills: () =>
    apiClient.get<Array<{
      id: string;
      name: string;
      icon: string;
      description: string;
      category: string;
      color: string;
      task_template_id: string;
      fields: Array<{
        key: string;
        label: string;
        type: 'text' | 'number' | 'select' | 'month' | 'date';
        required?: boolean;
        default?: any;
        placeholder?: string;
        min?: number;
        max?: number;
        options?: Array<{ value: string; label: string }>;
      }>; 
    }>>('/hrm/assistant/skills'),
  assistantOptimizePrompt: (prompt: string, sessionId?: string) =>
    apiClient.post<{
      original: string;
      optimized: string;
      routeTrack: string;
      intent: string;
      modelProfile: string;
      model?: string | null;
    }>('/hrm/assistant/optimize-prompt', { prompt, sessionId }),
  assistantTranscribeAudio: (file: File) =>
    apiClient.uploadFile<{ text: string; provider: string }>('/hrm/assistant/transcribe', file),
  assistantModelSettings: () =>
    apiClient.get<{
      provider: string;
      smallModel: string;
      standardModel: string;
      strongModel: string;
      useCases: Record<string, 'small' | 'standard' | 'strong'>;
      features: Record<string, boolean>;
      effectiveModels?: Record<string, string>;
    }>('/hrm/assistant/model-settings'),
  assistantUpdateModelSettings: (settings: Record<string, unknown>) =>
    apiClient.post<any>('/hrm/assistant/model-settings', settings),
  assistantModelCallTest: (payload: {
    prompt?: string;
    modelProfile?: 'small' | 'standard' | 'strong';
    sessionId?: string;
    clientContext?: any;
  }) =>
    apiClient.post<{
      ok: boolean;
      marker: string;
      requestId: string;
      sessionId: string | null;
      modelProfile: string;
      model: string;
      useCase: string;
      response?: string;
      error?: string | null;
    }>('/hrm/assistant/model-call-test', payload),
  assistantModelStreamTest: async (
    payload: {
      prompt?: string;
      modelProfile?: 'small' | 'standard' | 'strong';
      sessionId?: string;
      clientContext?: any;
    },
    options?: {
      signal?: AbortSignal;
      onStatus?: (message: string) => void;
      onDelta?: (content: string) => void;
    },
  ) => {
    const token = authUtils.getToken();
    const requestId = genRequestId();
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream, application/json',
      'X-Request-ID': requestId,
      ...(token && { Authorization: `Bearer ${token}` }),
    };
    const response = await fetch(`${API_BASE_URL}/hrm/assistant/model-stream-test`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: options?.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      let message = `请求失败 (${response.status})`;
      try {
        const error = JSON.parse(text);
        message = error.error || error.msg || message;
      } catch {
        message = safeApiErrorMessage(text, response.status, message);
      }
      throw new ApiError(message, response.status, response.headers.get('X-Request-ID') || requestId);
    }
    if (!response.body) return {};
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalPayload: any = null;
    let streamError: any = null;
    const dispatchEvent = (raw: string) => {
      const lines = raw.split('\n');
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      let data: any = null;
      try {
        data = JSON.parse(dataLines.join('\n'));
      } catch {
        data = { content: dataLines.join('\n') };
      }
      if (event === 'status') options?.onStatus?.(data.message || data.content || '');
      if (event === 'delta') options?.onDelta?.(data.content || data.text || '');
      if (event === 'error') streamError = data;
      if (event === 'final') finalPayload = data;
    };
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      parts.forEach(dispatchEvent);
    }
    if (buffer.trim()) dispatchEvent(buffer);
    if (streamError) throw new ApiError(streamError.error || '流式模型调用测试失败', response.status || 500, requestId);
    return finalPayload || {};
  },
  assistantEvaluationCases: () =>
    apiClient.get<{
      version: string;
      failure_taxonomy: string[];
      cases: any[];
    }>('/hrm/assistant/evaluation-cases'),
  assistantEvaluationRuns: (params?: Record<string, string | number | boolean | undefined | null>) =>
    apiClient.get<any[]>(`/hrm/assistant/evaluation-runs${buildQuery(params)}`),
  assistantEvaluationRun: (id: string) =>
    apiClient.get<any>(`/hrm/assistant/evaluation-runs/${id}`),
  assistantRunEvaluation: (payload: {
    caseId?: string;
    caseIds?: string[];
    limit?: number;
    retestOf?: string;
    clientContext?: any;
  }) =>
    apiClient.post<any>('/hrm/assistant/evaluation-runs', payload),
  assistantAuditLogs: (params?: Record<string, string | number | boolean | undefined | null>) =>
    apiClient.get<any[]>(`/hrm/assistant/audit-logs${buildQuery(params)}`),
  assistantAuditSummary: (params?: Record<string, string | number | boolean | undefined | null>) =>
    apiClient.get<any>(`/hrm/assistant/audit-summary${buildQuery(params)}`),
  assistantAuditLog: (id: string) =>
    apiClient.get<any>(`/hrm/assistant/audit-logs/${id}`),
  employeeLifecycle: (id: string) =>
    apiClient.get<any>(`/hrm/employees/${id}/lifecycle`),
  assistantSkillInvoke: (skillId: string, params: Record<string, any>, sessionId?: string, options?: { signal?: AbortSignal; clientContext?: any }) =>
    apiClient.post<{
      summary: string;
      entities: any[];
      widgets?: any[];
      renderBlocks?: any[];
      copilot?: any;
      clientContext?: any;
      sessionId: string | null;
      meta?: any;
    }>('/hrm/assistant/query', { skillId, params, sessionId, clientContext: options?.clientContext }, { signal: options?.signal }),
  assistantNewSession: () =>
    apiClient.post<{ id: string; title: string | null; messageCount: number }>(
      '/hrm/assistant/sessions/new'
    ),
  assistantListSessions: () =>
    apiClient.get<Array<{ id: string; title: string | null; messageCount: number; createdAt: string; updatedAt: string }>>(
      '/hrm/assistant/sessions'
    ),
  assistantGetSession: (id: string) =>
    apiClient.get<{ id: string; messages: any[]; title: string | null }>(
      `/hrm/assistant/sessions/${id}`
    ),
  assistantDeleteSession: (id: string) =>
    apiClient.delete<{ removed: boolean }>(`/hrm/assistant/sessions/${id}`),
};

export const extensionApi = {
  catalog: () => apiClient.get<ExtensionCatalog>('/extensions/catalog'),
  featureStatus: (domain: string, feature: string) =>
    apiClient.get<ExtensionFeatureStatus>(`/extensions/${domain}/${feature}/status`),
  peopleAnalyticsSummary: () =>
    apiClient.get<PeopleAnalyticsExtensionSummary>('/extensions/analytics/people/summary'),
  headcountSummary: () =>
    apiClient.get<HeadcountExtensionSummary>('/extensions/foundation/headcount/summary'),
  updateHeadcountPlan: (departmentId: string, data: { plan: number; note?: string }) =>
    apiClient.put<HeadcountUpdateResult>(`/extensions/foundation/headcount/departments/${departmentId}`, data),
  headcountHistory: (params?: { departmentId?: string; limit?: number }) =>
    apiClient.get<HeadcountHistoryPayload>(`/extensions/foundation/headcount/history${buildQuery(params)}`),
  continuousFeedbackEntries: (params?: { employeeId?: string; status?: string; limit?: number }) =>
    apiClient.get<ContinuousFeedbackListPayload>(
      `/extensions/foundation/continuous_feedback/entries${buildQuery(params)}`,
    ),
  createContinuousFeedback: (data: {
    employeeId: string;
    feedbackType?: string;
    category?: string;
    content: string;
    visibility?: string;
  }) =>
    apiClient.post<{ featureKey: string; item: ContinuousFeedbackEntry }>(
      '/extensions/foundation/continuous_feedback/entries',
      data,
    ),
  continuousFeedbackStats: (params?: { employeeId?: string }) =>
    apiClient.get<ContinuousFeedbackStatsPayload>(
      `/extensions/foundation/continuous_feedback/stats${buildQuery(params)}`,
    ),
  updateContinuousFeedbackStatus: (entryId: string, data: { status: string; handlerReply?: string }) =>
    apiClient.put<{ featureKey: string; item: ContinuousFeedbackEntry }>(
      `/extensions/foundation/continuous_feedback/entries/${entryId}/status`,
      data,
    ),
  talentFeatureSummary: (feature: TalentFeatureKey) =>
    apiClient.get<TalentFeatureSummary>(`/extensions/talent/${feature}/summary`),
  analyticsFeatureSummary: (feature: AnalyticsFeatureKey) =>
    apiClient.get<AnalyticsFeatureSummary>(`/extensions/analytics/${feature}/summary`),
  intelligenceFeatureSummary: (feature: IntelligenceFeatureKey) =>
    apiClient.get<IntelligenceFeatureSummary>(`/extensions/intelligence/${feature}/summary`),
  collaborationFeatureSummary: (feature: CollaborationFeatureKey) =>
    apiClient.get<CollaborationFeatureSummary>(`/extensions/collaboration/${feature}/summary`),
  workforceFeatureSummary: (feature: WorkforceFeatureKey) =>
    apiClient.get<WorkforceFeatureSummary>(`/extensions/workforce/${feature}/summary`),
  integrationFeatureSummary: (feature: IntegrationFeatureKey) =>
    apiClient.get<IntegrationFeatureSummary>(`/extensions/integration/${feature}/summary`),
  mobileFeatureSummary: (feature: MobileFeatureKey) =>
    apiClient.get<MobileFeatureSummary>(`/extensions/mobile/${feature}/summary`),
  securityFeatureSummary: (feature: SecurityFeatureKey) =>
    apiClient.get<SecurityFeatureSummary>(`/extensions/security/${feature}/summary`),
  providerStatus: (providerCode: string) =>
    apiClient.get<ExtensionProviderStatus>(`/extensions/integration/provider-status/${providerCode}`),
};

// 组织架构 API（/api/org/*）
export interface OrgTreeNode {
  id: string;
  name: string;
  shortName?: string | null;
  code?: string | null;
  parentId?: string | null;
  managerId?: string | null;
  managerName?: string | null;
  status: string;
  employeeCount: number;
  totalEmployeeCount?: number;
  children: OrgTreeNode[];
}

export interface OrgChartDepartment {
  id: string;
  name: string;
  parentId?: string | null;
  managerId?: string | null;
  status: string;
}

export interface OrgChartEmployee {
  id: string;
  employeeNo?: string | null;
  name: string;
  departmentId?: string | null;
  positionId?: string | null;
  jobTitle?: string | null;
  managerId?: string | null;
  status: string;
}

export interface OrgChartPayload {
  departments: OrgChartDepartment[];
  employees: OrgChartEmployee[];
  reportingLines: Array<{ employeeId: string; managerId: string }>;
}

export const orgApi = {
  tree: (includeInactive = false) =>
    apiClient.get<{ tree: OrgTreeNode[] }>(
      `/org/tree${buildQuery({ includeInactive: includeInactive ? 1 : undefined })}`,
    ),
  chart: (includeInactive = false) =>
    apiClient.get<OrgChartPayload>(
      `/org/chart${buildQuery({ includeInactive: includeInactive ? 1 : undefined })}`,
    ),
  setEmployeeManager: (employeeId: string, managerId: string | null) =>
    apiClient.put<{ employee: OrgChartEmployee; manager: OrgChartEmployee | null }>(
      `/org/employees/${employeeId}/manager`,
      { managerId },
    ),
  setDepartmentManager: (departmentId: string, managerId: string | null) =>
    apiClient.put<{ department: OrgChartDepartment; manager: OrgChartEmployee | null }>(
      `/org/departments/${departmentId}/manager`,
      { managerId },
    ),
};

// 考勤日明细 / 月度汇总 API（/api/hrm/attendance-timesheet|attendance-summary）
export interface AttendanceTimesheetRow {
  id: string;
  employeeId: string;
  employeeName?: string | null;
  departmentId?: string | null;
  workDate: string;
  employeeType?: string | null;
  worktimeIds?: string | null;
  checkIn?: string | null;
  checkOut?: string | null;
  checkInFixed?: boolean;
  checkOutFixed?: boolean;
  punchTimes?: Array<{ t: string; fix?: boolean }>;
  workHours: number;
  overtimeHours?: number;
  leaveHours?: number;
  eventSummary?: string | null;
  expectedPunches: number;
  actualPunches: number;
  missingCount: number;
  status: string;
  source?: string;
  manualCorrected: boolean;
  remark?: string | null;
}

export interface AttendanceTimesheetPage {
  items: AttendanceTimesheetRow[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface AttendanceSummaryRow {
  employeeId: string;
  employeeName?: string | null;
  employeeNo?: string | null;
  employeeType?: string | null;
  departmentId?: string | null;
  departmentName?: string | null;
  totalDays: number;
  expectedDays: number;
  presentDays: number;
  normalDays: number;
  missingCardDays: number;
  absentDays: number;
  restDays: number;
  otherDays: number;
  workHours: number;
  overtimeHours: number;
  attendanceRate?: number | null;
}

export const attendanceTimesheetApi = {
  punches: (params: {
    month?: string;
    date?: string;
    startDate?: string;
    endDate?: string;
    employeeId?: string;
    keyword?: string;
    page?: number;
    size?: number;
  }) => apiClient.get<{
    items: Array<{
      id: string;
      employeeId?: string | null;
      employeeName: string;
      employeeNo?: string | null;
      checkTime: string;
      checkDate: string;
      checkTimeOnly: string;
      checkType?: string | null;
      sensorId?: string | null;
    }>;
    total: number;
    page: number;
    size: number;
    pages: number;
  }>(`/hrm/attendance-punches${buildQuery(params)}`),
  list: (params: {
    month?: string;
    employeeId?: string;
    keyword?: string;
    departmentId?: string;
    status?: string;
    date?: string;
    employeeType?: string;
    hasOvertime?: boolean;
    hasLeave?: boolean;
    hasEvent?: boolean;
    minWorkHours?: number;
    page?: number;
    size?: number;
  }) => apiClient.get<AttendanceTimesheetPage>(`/hrm/attendance-timesheet${buildQuery(params)}`),
  generate: (month: string, overwriteManual = false) =>
    apiClient.post<{ month: string; created: number; updated: number; skippedManual: number }>(
      '/hrm/attendance-timesheet/generate',
      { month, overwriteManual },
    ),
  correct: (
    detailId: string,
    data: { checkIn?: string; checkOut?: string; status?: string; workHours?: number; remark?: string },
  ) => apiClient.post<AttendanceTimesheetRow>(`/hrm/attendance-timesheet/${detailId}/correct`, data),
  summary: (month: string, params?: { departmentId?: string; employeeId?: string; keyword?: string }) =>
    apiClient.get<{ month: string; items: AttendanceSummaryRow[] }>(
      `/hrm/attendance-summary${buildQuery({ month, ...(params || {}) })}`,
    ),
  notifySummary: (month: string) =>
    apiClient.post<{ month: string; pushed: number }>('/hrm/attendance-summary/notify', { month }),
};

// 考勤单据（OA 请假/加班/补卡/调休/外出/出差）
export interface AttendanceEventRow {
  id: string;
  eventType: string;
  employeeId?: string | null;
  employeeName?: string | null;
  employeeNo?: string | null;
  oaPersonId?: string | null;
  oaDepartmentId?: string | null;
  startAt?: string | null;
  endAt?: string | null;
  hours?: number | null;
  subtype?: string | null;
  reason?: string | null;
  status: string;
  affectsHours: boolean;
  oaRequestId?: string | null;
  oaFormTable?: string | null;
  oaMainId?: string | null;
  source?: string;
  syncedAt?: string | null;
}

export interface AttendanceEventPage {
  items: AttendanceEventRow[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export const attendanceEventApi = {
  list: (params: {
    month?: string;
    eventType?: string;
    keyword?: string;
    employeeId?: string;
    startDate?: string;
    endDate?: string;
    page?: number;
    size?: number;
  }) => apiClient.get<AttendanceEventPage>(`/hrm/attendance-events${buildQuery(params)}`),
  sync: (months = 12) =>
    apiClient.post<{
      start: string;
      end: string;
      months: number;
      fetched: number;
      created: number;
      updated: number;
      unmatched: number;
      byType: Record<string, number>;
    }>('/hrm/attendance-events/sync', { months }),
};

// 绩效考核中心 API（生成考核表 / 自动评分）
export interface PerformanceReviewItemPayload {
  id: string;
  indicatorCode?: string | null;
  indicatorName?: string | null;
  weight?: number | null;
  dataSource?: string | null;
  metric?: string | null;
  autoScore?: number | null;
  selfScore?: number | null;
  managerScore?: number | null;
  finalScore?: number | null;
  comment?: string | null;
  sortOrder?: number;
}

export interface PerformanceReviewRow {
  id: string;
  employeeId: string;
  employeeName?: string | null;
  cycleId?: string | null;
  cycleName?: string | null;
  managerId?: string | null;
  managerName?: string | null;
  autoScore?: number | null;
  selfScore?: number | null;
  managerScore?: number | null;
  finalScore?: number | null;
  grade?: string | null;
  status: string;
  items: PerformanceReviewItemPayload[];
}

export interface PerformanceReviewPermissions {
  allowedFields: string[];
  isHr: boolean;
  isSelf: boolean;
  isManager: boolean;
}

export interface PerformanceReviewDetail extends PerformanceReviewRow {
  employeeName?: string | null;
  managerName?: string | null;
  remark?: string | null;
  permissions: PerformanceReviewPermissions;
}

export interface PerformanceOverview {
  month: string;
  cycleId: string | null;
  items: PerformanceReviewRow[];
}

export interface PerformanceIndicatorRow {
  id: string;
  departmentName?: string | null;
  positionName?: string | null;
  seq?: number;
  name: string;
  targetValue?: string | null;
  definition?: string | null;
  scoringRule?: string | null;
  weight?: number | null;
  evaluatorDepartment?: string | null;
  linkedToSalary?: boolean;
  scoringRuleConfigured: boolean;
  dataSourceNote?: string | null;
  metricLabel?: string | null;
  rule?: {
    metric?: string | null;
    operator?: string | null;
    threshold?: number | null;
    score?: number | null;
    dataSource?: string | null;
    targetSource?: string | null;
    targetOaDepartmentId?: string | null;
    scoringMode?: string | null;
  } | null;
}

export interface PerformanceIndicatorPayload {
  departmentName?: string | null;
  positionName?: string | null;
  seq?: number | null;
  name: string;
  targetValue?: string | null;
  definition?: string | null;
  scoringRule?: string | null;
  weight?: number | null;
  evaluatorDepartment?: string | null;
  linkedToSalary?: boolean;
  metric?: string | null;
  operator?: string | null;
  threshold?: number | null;
  score?: number | null;
  dataSource?: string | null;
  targetSource?: string | null;
  targetOaDepartmentId?: string | null;
  scoringMode?: string | null;
}

export interface PerformanceParticipantRow {
  id: string;
  name: string;
  employeeNo?: string | null;
  departmentId?: string | null;
  departmentName?: string | null;
  positionName?: string | null;
  employeeType?: string | null;
  participant: boolean;
}

export const performanceParticipantApi = {
  list: (params?: { departmentName?: string; keyword?: string }) =>
    apiClient.get<{ items: PerformanceParticipantRow[] }>(
      `/hrm/performance-participants${buildQuery(params)}`,
    ),
  save: (employeeIds: string[], participant: boolean) =>
    apiClient.post<{ updated: number; participant: boolean }>(
      '/hrm/performance-participants',
      { employeeIds, participant },
    ),
};

export const performanceIndicatorApi = {
  list: (params?: { departmentName?: string; positionName?: string }) =>
    apiClient.get<PerformanceIndicatorRow[]>(`/hrm/performance-indicators${buildQuery(params)}`),
  create: (data: PerformanceIndicatorPayload) =>
    apiClient.post<PerformanceIndicatorRow>('/hrm/performance-indicators', data),
  update: (id: string, data: PerformanceIndicatorPayload) =>
    apiClient.put<PerformanceIndicatorRow>(`/hrm/performance-indicators/${id}`, data),
  remove: (id: string) => apiClient.delete<{ removed: boolean; id: string }>(`/hrm/performance-indicators/${id}`),
};

export const performanceMetricOptions = [
  { value: '', label: '不自动取数（人工录入）' },
  { value: 'orderAmount', label: '接单金额（金蝶ERP）' },
  { value: 'orderCount', label: '订单数（金蝶ERP）' },
  { value: 'grossMargin', label: '销售毛利率（金蝶ERP出库）' },
  { value: 'grossProfit', label: '销售毛利额（金蝶ERP出库）' },
  { value: 'salesAmount', label: '销售出库金额（金蝶ERP）' },
  { value: 'costAmount', label: '销售出库成本（金蝶ERP）' },
  { value: 'newProductAmount', label: '新产品接单金额（金蝶ERP）' },
  { value: 'newProductCount', label: '新产品数（金蝶ERP）' },
  { value: 'workHours', label: '月工时（考勤）' },
  { value: 'presentDays', label: '出勤天数（考勤）' },
  { value: 'absentDays', label: '旷工天数（考勤）' },
  { value: 'missingCardDays', label: '缺卡天数（考勤）' },
  { value: 'attendanceRate', label: '出勤率（考勤）' },
];

export const performanceCenterApi = {
  overview: (month: string) =>
    apiClient.get<PerformanceOverview>(`/hrm/performance-reviews/overview${buildQuery({ month })}`),
  generate: (month: string) =>
    apiClient.post<{
      cycleId: string;
      month: string;
      created: number;
      skipped: number;
      withoutIndicators: string[];
    }>('/hrm/performance-reviews/generate', { month }),
  autoScore: (reviewId: string, month: string, useAi = false) =>
    apiClient.post<{
      reviewId: string;
      month: string;
      scoredItems: number;
      totalItems: number;
      autoScore: number;
      aiUsed: boolean;
    }>(`/hrm/performance-reviews/${reviewId}/auto-score`, { month, useAi }),
  detail: (reviewId: string) =>
    apiClient.get<PerformanceReviewDetail>(`/hrm/performance-reviews/${reviewId}`),
  saveScores: (
    reviewId: string,
    items: Array<{ id: string; selfScore?: number | null; managerScore?: number | null; finalScore?: number | null }>,
  ) =>
    apiClient.post<{
      reviewId: string;
      changes: unknown[];
      autoScore?: number | null;
      managerScore?: number | null;
      finalScore?: number | null;
      grade?: string | null;
    }>(`/hrm/performance-reviews/${reviewId}/scores`, { items }),
  confirm: (reviewId: string, data?: { finalScore?: number | null; remark?: string }) =>
    apiClient.post<{ reviewId: string; finalScore?: number | null; grade?: string | null; status: string }>(
      `/hrm/performance-reviews/${reviewId}/confirm`,
      data || {},
    ),
  notify: (reviewId: string, targets: string[] = ['self', 'manager']) =>
    apiClient.post<{ reviewId: string; targets: string[]; sent: number }>(
      `/hrm/performance-reviews/${reviewId}/notify`,
      { targets },
    ),
};

// 个人学习门户 API（/api/portal/*）—— 只要账号绑定员工档案即可学习/考试
export const portalApi = {
  me: () => apiClient.get<{ employee: any; bound: boolean }>('/portal/me'),
  courses: (status?: 'all' | 'learning' | 'finished') =>
    apiClient.get<any[]>(`/portal/courses${buildQuery({ status })}`),
  courseDetail: (id: string) =>
    apiClient.get<any>(`/portal/courses/${id}`),
  reportProgress: (hourId: string, data: { watchedDuration: number; isFinished: boolean; totalDuration?: number }) =>
    apiClient.post<any>(`/portal/courses/${hourId}/progress`, data),
  exams: () => apiClient.get<any[]>('/portal/exams'),
  startExam: (taskId: string) => apiClient.post<any>(`/portal/exams/${taskId}/start`, {}),
  getAttempt: (attemptId: string) => apiClient.get<any>(`/portal/exams/${attemptId}/attempt`),
  submitExam: (attemptId: string, answers: Record<string, number[]>) =>
    apiClient.post<any>(`/portal/exams/${attemptId}/submit`, { answers }),
  examResult: (attemptId: string) => apiClient.get<any>(`/portal/exams/${attemptId}/result`),
  myProfile: () => apiClient.get<any>('/portal/my-profile'),
};

// 培训+考试：管理侧 bespoke API
export const trainingExamApi = {
  assignCourse: (courseId: string, data: { deptIds?: string[]; userIds?: string[] }) =>
    apiClient.post<any>(`/hrm/courses/${courseId}/assign`, data),
  uploadHourVideo: (hourId: string, file: File, onProgress?: (progress: { loaded: number; total: number; percent: number }) => void) =>
    apiClient.uploadFile<any>(`/hrm/course-hours/${hourId}/upload-video`, file, undefined, onProgress),
  uploadCourseCover: (courseId: string, file: File) =>
    apiClient.uploadFile<any>(`/hrm/courses/${courseId}/upload-cover`, file),
  uploadChapterMaterial: (chapterId: string, file: File, title?: string) =>
    apiClient.uploadFile<any>(`/hrm/course-chapters/${chapterId}/upload-material`, file, title ? { title } : undefined),
  updateChapterMaterials: (chapterId: string, materials: Array<{ title: string; url: string; ext: string }>) =>
    apiClient.put<any>(`/hrm/course-chapters/${chapterId}/materials`, { materials }),
  generateQuestions: (data: { courseId?: string; sourceText?: string; count?: number; types?: string[] }) =>
    apiClient.post<{ questions: any[]; count: number }>('/hrm/exam-questions/generate', data),
  approveQuestion: (id: string) => apiClient.post<any>(`/hrm/exam-questions/${id}/approve`, {}),
  rejectQuestion: (id: string) => apiClient.post<any>(`/hrm/exam-questions/${id}/reject`, {}),
  batchApprove: (ids: string[]) => apiClient.post<{ approved: number }>('/hrm/exam-questions/batch-approve', { ids }),
  publishTask: (taskId: string) => apiClient.post<any>(`/hrm/exam-tasks/${taskId}/publish`, {}),
  taskProgress: (taskId: string) => apiClient.get<any>(`/hrm/exam-tasks/${taskId}/progress`),
};

export default apiClient;
