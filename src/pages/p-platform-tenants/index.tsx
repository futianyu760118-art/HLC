import { type Dispatch, type FormEvent, type SetStateAction, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppIcon from '../../components/AppIcon';
import EnterpriseApplicationsPanel from '../../components/platform/EnterpriseApplicationsPanel';
import {
  ProductButton,
  ProductEmptyState,
  ProductMetricCard,
  ProductPageHeader,
  ProductStatusBadge,
} from '../../components/product';
import { authUtils } from '../../utils/auth';
import {
  platformApi,
  platformAiApi,
  platformExtensionApi,
  type AIAddonPackage,
  type AIProviderConfig,
  type AIUsageLedgerItem,
  type ExtensionCatalog,
  type PlatformBillingEvent,
  type PlatformDataRequest,
  type PlatformInvoice,
  type PlatformModule,
  type PlatformOnboardingItem,
  type PlatformOperationLog,
  type PlatformOrder,
  type PlatformPlan,
  type PlatformSubscription,
  type PlatformTenant,
  type PlatformTenantDiagnostics,
  type TenantAIEntitlement,
  type TenantAIUsagePayload,
} from '../../utils/api';

type PlatformTabKey = 'tenants' | 'enterpriseApplications' | 'capabilities' | 'aiResources' | 'onboarding' | 'dataRequests' | 'plans' | 'subscriptions' | 'diagnostics' | 'logs';

type CreateTenantForm = {
  name: string;
  slug: string;
  adminEmail: string;
  adminName: string;
  planCode: string;
  enabledModules: string[];
  maxUsers: number | string;
  maxEmployees: number | string;
  maxStorageMb: number | string;
  aiMonthlyQuota: number | string;
  expiresAt: string;
};

type DataRequestForm = {
  requestType: PlatformDataRequest['requestType'];
  requester: string;
  scope: string;
};

type BillingEventForm = {
  eventType: string;
  note: string;
};

type ResetCredentialReceipt = {
  password: string;
  administrator: string;
};

type TenantCustomerPanelProps = {
  selected: PlatformTenant | null;
  modules: PlatformModule[];
  moduleLabels: Record<string, string>;
  saving: boolean;
  resetOpen: boolean;
  resetAdminUserId: string;
  resetConfirmation: string;
  resetCredential: ResetCredentialReceipt | null;
  onOpenResetPassword: () => void;
  onCloseResetPassword: () => void;
  onCopyResetCredential: () => void;
  onDismissResetCredential: () => void;
  onResetAdminUserIdChange: (userId: string) => void;
  onResetConfirmationChange: (confirmation: string) => void;
  onResetAdminPassword: () => void;
  onSaveModules: () => void;
  onUpdateTenantStatus: (nextStatus: string) => void;
  onModulesChange: Dispatch<SetStateAction<PlatformModule[]>>;
};

const MODULE_LABELS: Record<string, string> = {
  recruitment: '招聘',
  organization: '组织员工',
  attendance: '考勤',
  approval: '审批',
  performance: '绩效',
  payroll: '薪酬',
  training_exam: '培训考试',
  assistant: 'AI 助手',
  feedback: '问题反馈',
  system: '系统',
};

const ALL_MODULE_KEYS = Object.keys(MODULE_LABELS);

const DEFAULT_CREATE_FORM: CreateTenantForm = {
  name: '',
  slug: '',
  adminEmail: '',
  adminName: '企业管理员',
  planCode: 'enterprise',
  enabledModules: [...ALL_MODULE_KEYS],
  maxUsers: 50,
  maxEmployees: 500,
  maxStorageMb: 10240,
  aiMonthlyQuota: 1000,
  expiresAt: '',
};

const DEFAULT_DATA_REQUEST_FORM: DataRequestForm = {
  requestType: 'export',
  requester: '',
  scope: 'tenant structured export',
};

const DEFAULT_BILLING_EVENT_FORM: BillingEventForm = {
  eventType: 'renewal_reminder_sent',
  note: '',
};

const DEFAULT_PROVIDER_FORM = {
  providerCode: 'siliconflow',
  displayName: '',
  baseUrl: '',
  apiKey: '',
  enabled: true,
};

const PLATFORM_TABS = [
  { key: 'tenants', label: '企业客户' },
  { key: 'enterpriseApplications', label: '企业申请' },
  { key: 'capabilities', label: '应用与能力' },
  { key: 'aiResources', label: 'AI 资源管理' },
  { key: 'onboarding', label: '开通清单' },
  { key: 'dataRequests', label: '数据请求' },
  { key: 'plans', label: '套餐管理' },
  { key: 'subscriptions', label: '订阅管理' },
  { key: 'diagnostics', label: '运行诊断' },
  { key: 'logs', label: '平台操作日志' },
] as const;

export default function PlatformTenantsPage() {
  const navigate = useNavigate();
  const user = authUtils.getUser();
  const [plans, setPlans] = useState<PlatformPlan[]>([]);
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [selected, setSelected] = useState<PlatformTenant | null>(null);
  const [modules, setModules] = useState<PlatformModule[]>([]);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateTenantForm>(DEFAULT_CREATE_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [resetOpen, setResetOpen] = useState(false);
  const [resetAdminUserId, setResetAdminUserId] = useState('');
  const [resetConfirmation, setResetConfirmation] = useState('');
  const [resetCredential, setResetCredential] = useState<ResetCredentialReceipt | null>(null);
  const [activeTab, setActiveTab] = useState<PlatformTabKey>('tenants');
  const [diagnostics, setDiagnostics] = useState<PlatformTenantDiagnostics | null>(null);
  const [operationLogs, setOperationLogs] = useState<PlatformOperationLog[]>([]);
  const [orders, setOrders] = useState<PlatformOrder[]>([]);
  const [invoices, setInvoices] = useState<PlatformInvoice[]>([]);
  const [billingEvents, setBillingEvents] = useState<PlatformBillingEvent[]>([]);
  const [billingEventForm, setBillingEventForm] = useState<BillingEventForm>(DEFAULT_BILLING_EVENT_FORM);
  const [onboardingItems, setOnboardingItems] = useState<PlatformOnboardingItem[]>([]);
  const [dataRequests, setDataRequests] = useState<PlatformDataRequest[]>([]);
  const [dataRequestForm, setDataRequestForm] = useState<DataRequestForm>(DEFAULT_DATA_REQUEST_FORM);
  const [dataRequestEvidence, setDataRequestEvidence] = useState('');
  const [aiProviders, setAiProviders] = useState<AIProviderConfig[]>([]);
  const [aiPackages, setAiPackages] = useState<AIAddonPackage[]>([]);
  const [aiEntitlements, setAiEntitlements] = useState<TenantAIEntitlement[]>([]);
  const [aiUsage, setAiUsage] = useState<TenantAIUsagePayload | null>(null);
  const [providerForm, setProviderForm] = useState(DEFAULT_PROVIDER_FORM);
  const [editingProviderSecret, setEditingProviderSecret] = useState(false);
  const [aiDiagnosticPrompt, setAiDiagnosticPrompt] = useState('平台 AI 连通性诊断');
  const [aiDiagnosticResult, setAiDiagnosticResult] = useState<any>(null);
  const [extensionCatalog, setExtensionCatalog] = useState<ExtensionCatalog | null>(null);
  const moduleLabels = useMemo(() => {
    const labels = { ...MODULE_LABELS };
    extensionCatalog?.packages.forEach(extensionPackage => {
      extensionPackage.features.forEach(feature => {
        labels[feature.key] = feature.name;
      });
    });
    return labels;
  }, [extensionCatalog]);

  const planOptions = useMemo(() => plans.filter(plan => plan.isActive !== false), [plans]);
  const modulesForPlan = (planCode: string) => {
    const plan = planOptions.find(item => item.code === planCode);
    return plan?.enabledModules?.length ? plan.enabledModules : [...ALL_MODULE_KEYS];
  };

  const loadTenant = useCallback(async (id: string) => {
    setError('');
    try {
      const detail = await platformApi.getTenant(id);
      setSelected(detail);
      setModules(detail.modules || []);
      setResetOpen(false);
      setResetAdminUserId('');
      setResetConfirmation('');
      setResetCredential(null);
      setDiagnostics(null);
      setOnboardingItems([]);
      setDataRequests([]);
      setBillingEvents([]);
      setAiEntitlements([]);
      setAiUsage(null);
      setAiDiagnosticResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载企业详情失败');
    }
  }, []);

  const refreshTenants = useCallback(async (filters: { keyword?: string; status?: string; selectFirst?: boolean } = {}) => {
    setLoading(true);
    setError('');
    try {
      const data = await platformApi.listTenants({
        keyword: filters.keyword?.trim() || undefined,
        status: filters.status || undefined,
      });
      setTenants(data || []);
      if (filters.selectFirst && data?.length) {
        await loadTenant(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载企业客户失败');
    } finally {
      setLoading(false);
    }
  }, [loadTenant]);

  useEffect(() => {
    platformApi.listPlans().then(setPlans).catch(() => {});
    refreshTenants({ selectFirst: true });
  }, [refreshTenants]);

  useEffect(() => {
    if (!resetCredential) return undefined;
    const timer = window.setTimeout(() => setResetCredential(null), 60_000);
    return () => window.clearTimeout(timer);
  }, [resetCredential]);

  useEffect(() => {
    let alive = true;
    platformExtensionApi.catalog()
      .then(catalog => { if (alive) setExtensionCatalog(catalog); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载应用能力失败'); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (activeTab !== 'onboarding') return;
    if (!selected?.id) {
      setOnboardingItems([]);
      return;
    }
    let alive = true;
    platformApi.listTenantOnboardingChecklist(selected.id)
      .then(data => { if (alive) setOnboardingItems(data.items || []); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载开通清单失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  useEffect(() => {
    if (activeTab !== 'diagnostics') return;
    if (!selected?.id) {
      setDiagnostics(null);
      return;
    }
    let alive = true;
    platformApi.diagnostics(selected.id)
      .then(data => { if (alive) setDiagnostics(data); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载运行诊断失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  useEffect(() => {
    if (activeTab !== 'dataRequests') return;
    if (!selected?.id) {
      setDataRequests([]);
      return;
    }
    let alive = true;
    platformApi.listTenantDataRequests(selected.id)
      .then(rows => { if (alive) setDataRequests(rows || []); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载数据请求失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  useEffect(() => {
    if (activeTab !== 'logs') return;
    let alive = true;
    platformApi.operationLogs(selected?.id ? { tenantId: selected.id } : {})
      .then(rows => { if (alive) setOperationLogs(rows || []); })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载平台操作日志失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  useEffect(() => {
    if (activeTab !== 'subscriptions') return;
    if (!selected?.id) {
      setOrders([]);
      setInvoices([]);
      setBillingEvents([]);
      return;
    }
    let alive = true;
    Promise.all([
      platformApi.listTenantOrders(selected.id),
      platformApi.listTenantInvoices(selected.id),
      platformApi.listTenantBillingEvents(selected.id),
    ])
      .then(([orderRows, invoiceRows, eventRows]) => {
        if (!alive) return;
        setOrders(orderRows || []);
        setInvoices(invoiceRows || []);
        setBillingEvents(eventRows || []);
      })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载订阅订单失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  useEffect(() => {
    if (activeTab !== 'aiResources') return;
    setError('');
    let alive = true;
    Promise.all([
      platformAiApi.providers(),
      platformAiApi.addonPackages(),
      selected?.id ? platformAiApi.tenantEntitlements(selected.id) : Promise.resolve({ tenantId: '', entitlements: [] }),
      selected?.id ? platformAiApi.tenantUsage(selected.id) : Promise.resolve(null),
    ])
      .then(([providers, packages, entitlementPayload, usagePayload]) => {
        if (!alive) return;
        setError('');
        setAiProviders(providers || []);
        setAiPackages(packages || []);
        setAiEntitlements(entitlementPayload?.entitlements || []);
        setAiUsage(usagePayload || null);
        const primary = (providers || [])[0];
        if (primary) {
          setProviderForm({
            providerCode: primary.providerCode,
            displayName: primary.displayName || primary.providerCode,
            baseUrl: primary.baseUrl || '',
            apiKey: '',
            enabled: primary.enabled,
          });
          setEditingProviderSecret(false);
        }
      })
      .catch(err => { if (alive) setError(err instanceof Error ? err.message : '加载 AI 资源配置失败'); });
    return () => { alive = false; };
  }, [activeTab, selected?.id]);

  if (!user?.isPlatformAdmin) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <AppIcon className="fas fa-lock text-4xl text-gray-300 mb-3" />
          <h2 className="text-lg font-bold text-gray-800 mb-1">无权访问平台后台</h2>
          <ProductButton className="mt-4" tone="primary" onClick={() => navigate('/login')}>
            返回登录
          </ProductButton>
        </div>
      </div>
    );
  }

  const createTenant = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const created = await platformApi.createTenant({
        ...createForm,
        enabledModules: createForm.enabledModules,
        maxUsers: Number(createForm.maxUsers),
        maxEmployees: Number(createForm.maxEmployees),
        maxStorageMb: Number(createForm.maxStorageMb),
        aiMonthlyQuota: Number(createForm.aiMonthlyQuota),
        expiresAt: createForm.expiresAt || null,
      });
      setCreateForm(DEFAULT_CREATE_FORM);
      setCreateOpen(false);
      setMessage(`已开通企业 ${created.name}`);
      await refreshTenants({ keyword, status });
      await loadTenant(created.id);
      if (created.initialPassword) {
        setResetCredential({
          password: created.initialPassword,
          administrator: `${created.admin?.name || '企业管理员'} · ${created.admin?.email || ''}`,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建企业失败');
    } finally {
      setSaving(false);
    }
  };

  const openCreateTenantForm = () => {
    if (!createOpen) {
      setCreateForm({
        ...DEFAULT_CREATE_FORM,
        enabledModules: modulesForPlan(DEFAULT_CREATE_FORM.planCode),
      });
    }
    setCreateOpen(value => !value);
  };

  const saveModules = async () => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const result = await platformApi.updateTenantModules(selected.id, modules);
      setModules(result.modules || []);
      setMessage('模块配置已保存');
      await loadTenant(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存模块配置失败');
    } finally {
      setSaving(false);
    }
  };

  const updateTenantStatus = async (nextStatus: string) => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const updated = await platformApi.updateTenant(selected.id, { status: nextStatus });
      setSelected(updated);
      setMessage(nextStatus === 'active' ? '企业已启用' : '企业已停用');
      await refreshTenants({ keyword, status });
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新企业状态失败');
    } finally {
      setSaving(false);
    }
  };

  const closeResetAdminPassword = () => {
    setResetOpen(false);
    setResetAdminUserId('');
    setResetConfirmation('');
  };

  const openResetAdminPassword = () => {
    setResetCredential(null);
    setResetAdminUserId('');
    setResetConfirmation('');
    setResetOpen(true);
  };

  const copyResetCredential = async () => {
    if (!resetCredential) return;
    try {
      await navigator.clipboard.writeText(resetCredential.password);
      setError('');
      setMessage('一次性密码已复制到剪贴板');
    } catch {
      setError('复制失败，请手动复制一次性密码');
    }
  };

  const resetAdminPassword = async () => {
    if (!selected) return;
    if (!resetAdminUserId) {
      setError('请选择要重置的管理员');
      return;
    }
    if (resetConfirmation !== `RESET ${selected.slug}`) {
      setError(`请输入完整确认短语：RESET ${selected.slug}`);
      return;
    }
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const result = await platformApi.resetAdminPassword(selected.id, {
        userId: resetAdminUserId,
        confirmation: resetConfirmation,
      });
      setResetCredential({
        password: result.initialPassword,
        administrator: `${result.user.name} · ${result.user.email}`,
      });
      closeResetAdminPassword();
    } catch (err) {
      setError(err instanceof Error ? err.message : '重置管理员密码失败');
    } finally {
      setSaving(false);
    }
  };

  const updateInvoiceStatus = async (invoiceId: string, status: string) => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const updated = await platformApi.updateTenantInvoice(selected.id, invoiceId, { status });
      setInvoices(prev => prev.map(item => item.id === invoiceId ? updated : item));
      setMessage(status === 'issued' ? '发票已标记为已开票' : '发票状态已更新');
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新发票状态失败');
    } finally {
      setSaving(false);
    }
  };

  const createBillingEvent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const created = await platformApi.createTenantBillingEvent(selected.id, {
        eventType: billingEventForm.eventType,
        note: billingEventForm.note,
      });
      setBillingEvents(prev => [created, ...prev]);
      setBillingEventForm(DEFAULT_BILLING_EVENT_FORM);
      setMessage('商业跟进记录已添加');
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加商业跟进记录失败');
    } finally {
      setSaving(false);
    }
  };

  const updateOnboardingStatus = async (itemKey: string, nextStatus: PlatformOnboardingItem['status']) => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const updated = await platformApi.updateTenantOnboardingItem(selected.id, itemKey, { status: nextStatus });
      setOnboardingItems(prev => prev.map(item => item.key === itemKey ? updated : item));
      setMessage('开通清单已更新');
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新开通清单失败');
    } finally {
      setSaving(false);
    }
  };

  const createDataRequest = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const created = await platformApi.createTenantDataRequest(selected.id, {
        requestType: dataRequestForm.requestType,
        requester: dataRequestForm.requester,
        scope: dataRequestForm.scope,
      });
      setDataRequests(prev => [created, ...prev]);
      setDataRequestForm(DEFAULT_DATA_REQUEST_FORM);
      setMessage('数据请求已创建');
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建数据请求失败');
    } finally {
      setSaving(false);
    }
  };

  const updateDataRequestStatus = async (requestId: string, nextStatus: PlatformDataRequest['status']) => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const payload: { status: PlatformDataRequest['status']; evidenceRef?: string } = { status: nextStatus };
      const evidenceRef = dataRequestEvidence.trim();
      if (evidenceRef) {
        payload.evidenceRef = evidenceRef;
      }
      const updated = await platformApi.updateTenantDataRequest(selected.id, requestId, payload);
      setDataRequests(prev => prev.map(item => item.id === requestId ? updated : item));
      setDataRequestEvidence('');
      setMessage('数据请求状态已更新');
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新数据请求失败');
    } finally {
      setSaving(false);
    }
  };

  const saveAiProvider = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const saved = await platformAiApi.updateProvider(providerForm.providerCode, {
        displayName: providerForm.displayName,
        baseUrl: providerForm.baseUrl,
        apiKey: editingProviderSecret ? providerForm.apiKey.trim() || undefined : undefined,
        enabled: providerForm.enabled,
      });
      setAiProviders(prev => {
        const exists = prev.some(item => item.providerCode === saved.providerCode);
        return exists ? prev.map(item => item.providerCode === saved.providerCode ? saved : item) : [saved, ...prev];
      });
      setProviderForm(prev => ({ ...prev, apiKey: '' }));
      setEditingProviderSecret(false);
      setMessage('AI 供应商配置已保存');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 AI 供应商失败');
    } finally {
      setSaving(false);
    }
  };

  const saveAiEntitlements = async () => {
    if (!selected) return;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const result = await platformAiApi.updateTenantEntitlements(selected.id, aiEntitlements);
      setAiEntitlements(result.entitlements || []);
      const usagePayload = await platformAiApi.tenantUsage(selected.id);
      setAiUsage(usagePayload || null);
      setMessage('客户 AI 权益已保存');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存客户 AI 权益失败');
    } finally {
      setSaving(false);
    }
  };

  const runAiDiagnostic = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    setAiDiagnosticResult(null);
    try {
      const result = await platformAiApi.runModelDiagnostic({
        prompt: aiDiagnosticPrompt,
        modelProfile: 'standard',
      });
      setAiDiagnosticResult(result);
      setMessage(result?.ok ? '平台 AI 诊断已完成' : '平台 AI 诊断返回异常，请查看结果');
    } catch (err) {
      setError(err instanceof Error ? err.message : '平台 AI 诊断失败');
    } finally {
      setSaving(false);
    }
  };

  const logout = () => {
    authUtils.logout();
    navigate('/platform/login');
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="h-16 border-b border-slate-200 bg-white flex items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-md bg-blue-600 text-white flex items-center justify-center">
            <AppIcon className="fas fa-building-shield" />
          </div>
          <div>
            <div className="font-semibold leading-tight">恒聘通平台后台</div>
            <div className="text-xs text-slate-500">企业客户与 SaaS 开通管理</div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <a className="text-blue-600 hover:text-blue-700" href="/docs/customer-onboarding.md">
            开通清单
          </a>
          <a className="text-blue-600 hover:text-blue-700" href="/docs/support-sla.md">
            支持 SLA
          </a>
          <span className="text-slate-500">{user.name}</span>
          <ProductButton icon="fa-right-from-bracket" onClick={logout}>退出</ProductButton>
        </div>
      </header>

      <div className="px-6 py-4 border-b border-slate-200 bg-white">
        <nav className="flex items-center gap-2 text-sm">
          {PLATFORM_TABS.map(tab => (
            <button
              key={tab.key}
              className={`h-9 px-3 rounded-md ${activeTab === tab.key ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50'}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <main className={activeTab === 'enterpriseApplications' ? 'p-6' : 'grid grid-cols-[360px_1fr] gap-5 p-6'}>
        {activeTab !== 'enterpriseApplications' && <section className="bg-white border border-slate-200 rounded-lg min-h-[calc(100vh-160px)]">
          <div className="p-4 border-b border-slate-200">
            <div className="flex items-center justify-between mb-3">
              <h1 className="text-base font-semibold">企业客户</h1>
              <ProductButton tone="primary" icon="fa-plus" onClick={openCreateTenantForm}>新建</ProductButton>
            </div>
            <div className="flex gap-2">
              <input
                value={keyword}
                onChange={event => setKeyword(event.target.value)}
                className="h-9 min-w-0 flex-1 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
                placeholder="搜索名称或编码"
                aria-label="搜索企业客户"
              />
              <select
                value={status}
                onChange={event => setStatus(event.target.value)}
                className="h-9 rounded-md border border-slate-200 px-2 text-sm outline-none"
                aria-label="筛选企业状态"
              >
                <option value="">全部</option>
                <option value="active">启用</option>
                <option value="inactive">停用</option>
                <option value="expired">到期</option>
              </select>
              <button className="h-9 w-9 rounded-md border border-slate-200 hover:bg-slate-50" onClick={() => refreshTenants({ keyword, status })} aria-label="刷新企业客户">
                <AppIcon className={`fas ${loading ? 'fa-spinner fa-spin' : 'fa-rotate-right'}`} />
              </button>
            </div>
          </div>

          {createOpen && (
            <form className="p-4 border-b border-slate-200 bg-slate-50 space-y-3" onSubmit={createTenant}>
              <div className="grid grid-cols-2 gap-3">
                <input required placeholder="企业名称" className="h-9 rounded-md border border-slate-200 px-3 text-sm" value={createForm.name} onChange={e => setCreateForm({ ...createForm, name: e.target.value })} />
                <input placeholder="企业编码，留空自动生成" className="h-9 rounded-md border border-slate-200 px-3 text-sm" value={createForm.slug} onChange={e => setCreateForm({ ...createForm, slug: e.target.value })} />
                <input required placeholder="管理员邮箱" className="h-9 rounded-md border border-slate-200 px-3 text-sm col-span-2" value={createForm.adminEmail} onChange={e => setCreateForm({ ...createForm, adminEmail: e.target.value })} />
                <input placeholder="管理员姓名" className="h-9 rounded-md border border-slate-200 px-3 text-sm" value={createForm.adminName} onChange={e => setCreateForm({ ...createForm, adminName: e.target.value })} />
                <select
                  className="h-9 rounded-md border border-slate-200 px-2 text-sm"
                  value={createForm.planCode}
                  onChange={e => {
                    const planCode = e.target.value;
                    setCreateForm({ ...createForm, planCode, enabledModules: modulesForPlan(planCode) });
                  }}
                >
                  {(planOptions.length ? planOptions : [{ code: 'enterprise', name: '企业全功能版', enabledModules: [], limits: {}, isActive: true }]).map(plan => (
                    <option key={plan.code} value={plan.code}>{plan.name}</option>
                  ))}
                </select>
                <input type="number" min="1" className="h-9 rounded-md border border-slate-200 px-3 text-sm" value={createForm.maxUsers} onChange={e => setCreateForm({ ...createForm, maxUsers: e.target.value })} />
                <input type="number" min="1" className="h-9 rounded-md border border-slate-200 px-3 text-sm" value={createForm.maxEmployees} onChange={e => setCreateForm({ ...createForm, maxEmployees: e.target.value })} />
              </div>
              <div className="rounded-md border border-slate-200 bg-white p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-700">开通模块</span>
                  <span className="text-xs text-slate-500">{createForm.enabledModules.length}/{ALL_MODULE_KEYS.length}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {ALL_MODULE_KEYS.map(moduleKey => {
                    const module = { key: moduleKey, label: MODULE_LABELS[moduleKey] || moduleKey };
                    const checked = createForm.enabledModules.includes(module.key);
                    return (
                      <label key={module.key} className="flex items-center gap-2 rounded-md border border-slate-100 px-2 py-2 text-sm text-slate-700 hover:bg-slate-50">
                        <input
                          type="checkbox"
                          checked={checked}
                          aria-label={`新建企业开放${module.label}模块`}
                          onChange={event => {
                            setCreateForm(prev => {
                              const enabled = new Set(prev.enabledModules);
                              if (event.target.checked) {
                                enabled.add(module.key);
                              } else {
                                enabled.delete(module.key);
                              }
                              return { ...prev, enabledModules: ALL_MODULE_KEYS.filter(key => enabled.has(key)) };
                            });
                          }}
                          className="h-4 w-4"
                        />
                        <span>{module.label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <ProductButton disabled={saving} tone="primary" className="w-full bg-slate-900 border-slate-900 hover:bg-slate-800">
                {saving ? '正在开通' : '开通企业'}
              </ProductButton>
            </form>
          )}

          <div className="divide-y divide-slate-100">
            {tenants.map(tenant => (
              <button
                key={tenant.id}
                className={`w-full text-left p-4 hover:bg-slate-50 ${selected?.id === tenant.id ? 'bg-blue-50' : ''}`}
                onClick={() => loadTenant(tenant.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-sm">{tenant.name}</div>
                  <ProductStatusBadge tone={tenant.status === 'active' ? 'success' : 'neutral'}>{tenant.status}</ProductStatusBadge>
                </div>
                <div className="mt-1 text-xs text-slate-500">{tenant.slug} · {tenant.planCode || '未设置套餐'}</div>
              </button>
            ))}
            {!tenants.length && (
              <ProductEmptyState compact title="暂无企业客户" description="调整筛选条件或新建企业客户。" />
            )}
          </div>
        </section>}

        <section className={activeTab === 'enterpriseApplications' ? '' : 'space-y-5'}>
          {(message || error) && (
            <div className={`rounded-md border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
              {error || message}
            </div>
          )}

          {activeTab === 'tenants' && (
            <TenantCustomerPanel
              selected={selected}
              modules={modules}
              moduleLabels={moduleLabels}
              saving={saving}
              resetOpen={resetOpen}
              resetAdminUserId={resetAdminUserId}
              resetConfirmation={resetConfirmation}
              resetCredential={resetCredential}
              onOpenResetPassword={openResetAdminPassword}
              onCloseResetPassword={closeResetAdminPassword}
              onCopyResetCredential={copyResetCredential}
              onDismissResetCredential={() => setResetCredential(null)}
              onResetAdminUserIdChange={setResetAdminUserId}
              onResetConfirmationChange={setResetConfirmation}
              onResetAdminPassword={resetAdminPassword}
              onSaveModules={saveModules}
              onUpdateTenantStatus={updateTenantStatus}
              onModulesChange={setModules}
            />
          )}
          {activeTab === 'enterpriseApplications' && (
            <EnterpriseApplicationsPanel
              currentUserId={user?.id || ''}
            />
          )}
          {activeTab === 'capabilities' && <ApplicationCapabilitiesPanel catalog={extensionCatalog} />}
          {activeTab === 'aiResources' && (
            <AiResourcesPanel
              selected={selected}
              providers={aiProviders}
              packages={aiPackages}
              entitlements={aiEntitlements}
              usage={aiUsage}
              providerForm={providerForm}
              editingProviderSecret={editingProviderSecret}
              diagnosticPrompt={aiDiagnosticPrompt}
              diagnosticResult={aiDiagnosticResult}
              saving={saving}
              onProviderFormChange={setProviderForm}
              onEditingProviderSecretChange={setEditingProviderSecret}
              onEntitlementsChange={setAiEntitlements}
              onDiagnosticPromptChange={setAiDiagnosticPrompt}
              onSaveProvider={saveAiProvider}
              onSaveEntitlements={saveAiEntitlements}
              onRunDiagnostic={runAiDiagnostic}
            />
          )}
          {activeTab === 'onboarding' && (
            <OnboardingPanel
              selected={selected}
              items={onboardingItems}
              saving={saving}
              onUpdateStatus={updateOnboardingStatus}
            />
          )}
          {activeTab === 'dataRequests' && (
            <DataRequestsPanel
              selected={selected}
              requests={dataRequests}
              form={dataRequestForm}
              evidenceRef={dataRequestEvidence}
              saving={saving}
              onFormChange={setDataRequestForm}
              onEvidenceChange={setDataRequestEvidence}
              onCreate={createDataRequest}
              onUpdateStatus={updateDataRequestStatus}
            />
          )}
          {activeTab === 'plans' && <PlansPanel plans={plans} />}
          {activeTab === 'subscriptions' && (
            <SubscriptionsPanel
              selected={selected}
              tenants={tenants}
              orders={orders}
              invoices={invoices}
              billingEvents={billingEvents}
              billingEventForm={billingEventForm}
              onBillingEventFormChange={setBillingEventForm}
              saving={saving}
              onUpdateInvoiceStatus={updateInvoiceStatus}
              onCreateBillingEvent={createBillingEvent}
            />
          )}
          {activeTab === 'diagnostics' && <DiagnosticsPanel selected={selected} diagnostics={diagnostics} />}
          {activeTab === 'logs' && <OperationLogsPanel logs={operationLogs} selected={selected} />}
        </section>
      </main>
    </div>
  );
}

const ONBOARDING_STATUS_LABELS: Record<PlatformOnboardingItem['status'], string> = {
  pending: '待处理',
  in_progress: '进行中',
  done: '已完成',
  blocked: '受阻',
};

const DATA_REQUEST_TYPE_LABELS: Record<PlatformDataRequest['requestType'], string> = {
  export: '导出',
  deletion: '删除/匿名化',
};

const DATA_REQUEST_STATUS_LABELS: Record<PlatformDataRequest['status'], string> = {
  requested: '已请求',
  identity_verified: '身份已核验',
  approved: '已批准',
  export_generated: '导出已生成',
  delivered: '已交付',
  closed: '已关闭',
  rejected: '已拒绝',
};

const DATA_REQUEST_STATUS_OPTIONS: PlatformDataRequest['status'][] = [
  'identity_verified',
  'approved',
  'export_generated',
  'delivered',
  'closed',
  'rejected',
];

function OnboardingPanel({
  selected,
  items,
  saving,
  onUpdateStatus,
}: {
  selected: PlatformTenant | null;
  items: PlatformOnboardingItem[];
  saving: boolean;
  onUpdateStatus: (itemKey: string, nextStatus: PlatformOnboardingItem['status']) => void;
}) {
  if (!selected) {
    return (
      <section className="bg-white border border-slate-200 rounded-lg p-5">
        <ProductPageHeader title="开通清单" subtitle="选择企业后跟进入驻准备事项。" icon="fa-list-check" />
        <div className="mt-4">
          <ProductEmptyState compact title="请选择左侧企业查看开通清单" />
        </div>
      </section>
    );
  }

  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <ProductPageHeader
        title="开通清单"
        subtitle={`${selected.name} 的首次开通、资料确认和交付准备事项。`}
        icon="fa-list-check"
      />
      <div className="mt-5 divide-y divide-slate-100 rounded-md border border-slate-200 overflow-hidden">
        {items.map(item => (
          <div key={item.key} className="grid grid-cols-[1fr_100px_240px] items-center gap-3 px-4 py-3">
            <div>
              <div className="text-sm font-medium text-slate-800">{item.label || item.key}</div>
              <div className="mt-1 text-xs text-slate-500">{item.note || '暂无备注'}</div>
            </div>
            <ProductStatusBadge tone={item.status === 'done' ? 'success' : item.status === 'blocked' ? 'danger' : item.status === 'in_progress' ? 'primary' : 'neutral'}>
              {ONBOARDING_STATUS_LABELS[item.status] || item.status}
            </ProductStatusBadge>
            <div className="flex justify-end gap-2">
              <ProductButton tone="ghost" disabled={saving || item.status === 'in_progress'} onClick={() => onUpdateStatus(item.key, 'in_progress')}>进行中</ProductButton>
              <ProductButton tone="primary" disabled={saving || item.status === 'done'} onClick={() => onUpdateStatus(item.key, 'done')}>完成</ProductButton>
            </div>
          </div>
        ))}
        {!items.length && <ProductEmptyState compact title="正在加载或暂无开通清单" />}
      </div>
    </section>
  );
}

function DataRequestsPanel({
  selected,
  requests,
  form,
  evidenceRef,
  saving,
  onFormChange,
  onEvidenceChange,
  onCreate,
  onUpdateStatus,
}: {
  selected: PlatformTenant | null;
  requests: PlatformDataRequest[];
  form: DataRequestForm;
  evidenceRef: string;
  saving: boolean;
  onFormChange: Dispatch<SetStateAction<DataRequestForm>>;
  onEvidenceChange: (value: string) => void;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onUpdateStatus: (requestId: string, nextStatus: PlatformDataRequest['status']) => void;
}) {
  if (!selected) {
    return (
      <section className="bg-white border border-slate-200 rounded-lg p-5">
        <ProductPageHeader title="数据请求" subtitle="选择企业后跟进导出、删除和匿名化请求。" icon="fa-file-export" />
        <div className="mt-4">
          <ProductEmptyState compact title="请选择左侧企业查看数据请求" />
        </div>
      </section>
    );
  }

  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <ProductPageHeader
        title="数据请求"
        subtitle={`${selected.name} 的客户数据导出、删除和匿名化请求跟踪。`}
        icon="fa-file-export"
      />

      <form className="mt-5 grid grid-cols-[150px_180px_1fr_110px] gap-3 rounded-md border border-slate-200 bg-slate-50 p-3" onSubmit={onCreate}>
        <select
          value={form.requestType}
          onChange={event => onFormChange(prev => ({ ...prev, requestType: event.target.value as PlatformDataRequest['requestType'] }))}
          className="h-9 rounded-md border border-slate-200 px-2 text-sm outline-none"
        >
          <option value="export">导出</option>
          <option value="deletion">删除/匿名化</option>
        </select>
        <input
          required
          value={form.requester}
          onChange={event => onFormChange(prev => ({ ...prev, requester: event.target.value }))}
          className="h-9 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
          placeholder="请求人"
        />
        <input
          required
          value={form.scope}
          onChange={event => onFormChange(prev => ({ ...prev, scope: event.target.value }))}
          className="h-9 min-w-0 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
          placeholder="请求范围"
        />
        <ProductButton tone="primary" disabled={saving} icon="fa-plus">创建请求</ProductButton>
      </form>

      <div className="mt-4 flex items-center gap-3">
        <label className="text-sm font-medium text-slate-600" htmlFor="dataRequestEvidenceRef">证据引用</label>
        <input
          id="dataRequestEvidenceRef"
          value={evidenceRef}
          onChange={event => onEvidenceChange(event.target.value)}
          className="h-9 min-w-0 flex-1 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
          placeholder="例如 ticket HPT-DATA-1"
        />
      </div>

      <div className="mt-4 rounded-md border border-slate-200 overflow-hidden">
        <div className="grid grid-cols-[110px_140px_1fr_150px_300px] bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
          <span>类型</span>
          <span>请求人</span>
          <span>范围 / 证据</span>
          <span>状态</span>
          <span>推进</span>
        </div>
        {requests.map(row => (
          <div key={row.id} className="grid grid-cols-[110px_140px_1fr_150px_300px] items-center gap-2 border-t border-slate-100 px-3 py-3 text-sm text-slate-700">
            <span>{DATA_REQUEST_TYPE_LABELS[row.requestType] || row.requestType}</span>
            <span className="truncate">{row.requester}</span>
            <span className="min-w-0">
              <span className="block truncate">{row.scope}</span>
              <span className="block truncate text-xs text-slate-500">{row.evidenceRef || '暂无证据引用'}</span>
            </span>
            <ProductStatusBadge tone={row.status === 'closed' ? 'success' : row.status === 'rejected' ? 'danger' : row.status === 'requested' ? 'neutral' : 'primary'}>
              {DATA_REQUEST_STATUS_LABELS[row.status] || row.status}
            </ProductStatusBadge>
            <div className="flex flex-wrap justify-end gap-2">
              {DATA_REQUEST_STATUS_OPTIONS.map(status => (
                <button
                  key={status}
                  className="text-xs text-blue-600 hover:text-blue-700 disabled:text-slate-300"
                  disabled={saving || row.status === status}
                  onClick={() => onUpdateStatus(row.id, status)}
                >
                  {DATA_REQUEST_STATUS_LABELS[status]}
                </button>
              ))}
            </div>
          </div>
        ))}
        {!requests.length && <ProductEmptyState compact title="暂无数据请求" description="创建客户导出或删除/匿名化请求后在这里推进状态。" />}
      </div>
    </section>
  );
}

function TenantCustomerPanel({
  selected,
  modules,
  moduleLabels,
  saving,
  resetOpen,
  resetAdminUserId,
  resetConfirmation,
  resetCredential,
  onOpenResetPassword,
  onCloseResetPassword,
  onCopyResetCredential,
  onDismissResetCredential,
  onResetAdminUserIdChange,
  onResetConfirmationChange,
  onResetAdminPassword,
  onSaveModules,
  onUpdateTenantStatus,
  onModulesChange,
}: TenantCustomerPanelProps) {
  if (!selected) {
    return <ProductEmptyState title="请选择一个企业客户" description="从左侧列表选择企业后查看模块、额度和管理员操作。" />;
  }

  return (
    <>
      <div className="bg-white border border-slate-200 rounded-lg p-5">
        <ProductPageHeader
          title="企业客户"
          subtitle={`${selected.name} · 企业编码：${selected.slug}`}
          icon="fa-building"
          actions={(
            <>
              <ProductButton icon="fa-key" onClick={onOpenResetPassword} disabled={saving}>重置管理员密码</ProductButton>
              <ProductButton
                tone={selected.status === 'active' ? 'secondary' : 'primary'}
                onClick={() => onUpdateTenantStatus(selected.status === 'active' ? 'inactive' : 'active')}
                disabled={saving}
              >
              {selected.status === 'active' ? '停用企业' : '启用企业'}
              </ProductButton>
            </>
          )}
        />
        {resetCredential && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-credential-title"
          >
            <div className="w-full max-w-lg rounded-xl border border-emerald-200 bg-white p-5 shadow-2xl">
              <div id="reset-credential-title" className="text-base font-semibold text-emerald-900">一次性密码已生成</div>
              <p className="mt-2 text-sm text-slate-600">
                {resetCredential.administrator} · 该密码只显示一次，并将在 60 秒后从页面清除。
              </p>
              <code className="mt-4 block overflow-x-auto rounded-md bg-slate-100 px-3 py-3 font-mono text-sm text-slate-900">
                {resetCredential.password}
              </code>
              <div className="mt-5 flex flex-wrap justify-end gap-3">
                <ProductButton onClick={onCopyResetCredential}>复制密码</ProductButton>
                <ProductButton tone="secondary" onClick={onDismissResetCredential}>我已保存，关闭</ProductButton>
              </div>
            </div>
          </div>
        )}
        {resetOpen && (
          <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4">
            <div className="text-sm font-medium text-amber-900">确认重置管理员一次性密码</div>
            <p className="mt-1 text-xs text-amber-800">
              选择要重置的管理员，并输入确认短语 <code className="font-mono">{`RESET ${selected.slug}`}</code>。
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <select
                className="h-9 rounded-md border border-amber-300 bg-white px-3 text-sm"
                value={resetAdminUserId}
                onChange={event => onResetAdminUserIdChange(event.target.value)}
                disabled={saving}
              >
                <option value="">选择要重置的管理员</option>
                {(selected.admins || []).map(admin => (
                  <option key={admin.id} value={admin.id}>{admin.name} · {admin.email}</option>
                ))}
              </select>
              <input
                className="h-9 rounded-md border border-amber-300 bg-white px-3 text-sm"
                value={resetConfirmation}
                onChange={event => onResetConfirmationChange(event.target.value)}
                placeholder={`RESET ${selected.slug}`}
                autoComplete="off"
                disabled={saving}
              />
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <ProductButton tone="secondary" onClick={onCloseResetPassword} disabled={saving}>取消</ProductButton>
              <ProductButton
                icon="fa-key"
                onClick={onResetAdminPassword}
                disabled={saving || !resetAdminUserId || resetConfirmation !== `RESET ${selected.slug}`}
              >
                确认重置
              </ProductButton>
            </div>
          </div>
        )}
        <div className="mt-5 grid grid-cols-4 gap-3">
          <ProductMetricCard label="后台用户" value={`${selected.usage?.users ?? 0}/${selected.maxUsers ?? '-'}`} />
          <ProductMetricCard label="员工档案" value={`${selected.usage?.employees ?? 0}/${selected.maxEmployees ?? '-'}`} />
          <ProductMetricCard label="存储用量" value={`${selected.usage?.storageMb ?? 0}/${selected.maxStorageMb ?? '-'} MB`} />
          <ProductMetricCard label="AI 月额度" value={`${selected.usage?.aiCallsThisMonth ?? 0}/${selected.aiMonthlyQuota ?? '-'}`} />
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">模块开关</h3>
          <ProductButton tone="primary" icon="fa-floppy-disk" onClick={onSaveModules} disabled={saving}>保存配置</ProductButton>
        </div>
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
          {modules.map(module => (
            <label key={module.moduleKey} className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-3 hover:bg-slate-50">
              <span>
                <span className="block text-sm font-medium">{moduleLabels[module.moduleKey] || module.moduleKey}</span>
                <span className="block text-xs text-slate-500">{module.moduleKey}</span>
              </span>
              <input
                type="checkbox"
                checked={module.enabled}
                aria-label={`切换${moduleLabels[module.moduleKey] || module.moduleKey}模块`}
                onChange={event => onModulesChange(prev => prev.map(item => item.moduleKey === module.moduleKey ? { ...item, enabled: event.target.checked } : item))}
                className="h-5 w-5"
              />
            </label>
          ))}
        </div>
      </div>
    </>
  );
}

function PlansPanel({ plans }: { plans: PlatformPlan[] }) {
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">套餐管理</h2>
        <span className="text-sm text-slate-500">共 {plans.length} 个套餐</span>
      </div>
      <div className="divide-y divide-slate-100">
        {plans.map(plan => (
          <div key={plan.code} className="py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{plan.name}</div>
                <div className="mt-1 text-xs text-slate-500">{plan.code}</div>
              </div>
              <ProductStatusBadge tone={plan.isActive ? 'success' : 'neutral'}>{plan.isActive ? '启用' : '停用'}</ProductStatusBadge>
            </div>
            <div className="mt-2 text-sm text-slate-600">
              可用模块 {plan.enabledModules?.length ?? 0} 个
            </div>
          </div>
        ))}
        {!plans.length && <ProductEmptyState compact title="暂无套餐配置" />}
      </div>
    </section>
  );
}

function ApplicationCapabilitiesPanel({ catalog }: { catalog: ExtensionCatalog | null }) {
  const maturityLabels = {
    workflow: '完整流程',
    summary: '数据概览',
    configuration: '配置与适配',
    preview: '规划预览',
  } as const;
  const features = catalog?.packages.flatMap(extensionPackage => extensionPackage.features) || [];
  const supportedCount = features.filter(feature => feature.supported).length;

  return (
    <section className="space-y-4">
      <ProductPageHeader
        title="应用与能力"
        subtitle="查看当前发布包实际支持的业务能力、成熟度和租户默认可见策略。"
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <ProductMetricCard label="发布能力版本" value={catalog?.releaseCapabilityVersion || '加载中'} />
        <ProductMetricCard label="已支持" value={`${supportedCount}/${features.length || 0}`} />
        <ProductMetricCard label="默认策略" value="租户显式开通" />
      </div>
      {!catalog ? (
        <div className="rounded-lg border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">正在加载应用能力...</div>
      ) : (
        <div className="space-y-4">
          {catalog.packages.map(extensionPackage => (
            <div key={extensionPackage.key} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-semibold text-slate-800">{extensionPackage.name}</h3>
                <span className="text-xs text-slate-400">{extensionPackage.features.filter(feature => feature.supported).length}/{extensionPackage.features.length} 已支持</span>
              </div>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {extensionPackage.features.map(feature => (
                  <div key={feature.key} className="rounded-md border border-slate-100 px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-700">{feature.name}</span>
                      <ProductStatusBadge tone={feature.supported ? 'success' : 'neutral'}>
                        {feature.supported ? '当前支持' : '暂不展示'}
                      </ProductStatusBadge>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">{maturityLabels[feature.maturity]}</div>
                    <div className="mt-1 truncate font-mono text-[10px] text-slate-400" title={feature.key}>{feature.key}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AiResourcesPanel({
  selected,
  providers,
  packages,
  entitlements,
  usage,
  providerForm,
  editingProviderSecret,
  diagnosticPrompt,
  diagnosticResult,
  saving,
  onProviderFormChange,
  onEditingProviderSecretChange,
  onEntitlementsChange,
  onDiagnosticPromptChange,
  onSaveProvider,
  onSaveEntitlements,
  onRunDiagnostic,
}: {
  selected: PlatformTenant | null;
  providers: AIProviderConfig[];
  packages: AIAddonPackage[];
  entitlements: TenantAIEntitlement[];
  usage: TenantAIUsagePayload | null;
  providerForm: typeof DEFAULT_PROVIDER_FORM;
  editingProviderSecret: boolean;
  diagnosticPrompt: string;
  diagnosticResult: any;
  saving: boolean;
  onProviderFormChange: Dispatch<SetStateAction<typeof DEFAULT_PROVIDER_FORM>>;
  onEditingProviderSecretChange: (value: boolean) => void;
  onEntitlementsChange: Dispatch<SetStateAction<TenantAIEntitlement[]>>;
  onDiagnosticPromptChange: (value: string) => void;
  onSaveProvider: () => void;
  onSaveEntitlements: () => void;
  onRunDiagnostic: () => void;
}) {
  const tierLabels: Record<string, string> = {
    basic: '经济档',
    standard: '标准档',
    professional: '专业档',
  };
  const usageRows = usage?.items || [];
  const enabledCount = entitlements.filter(item => item.enabled).length;
  const totalQuota = entitlements.reduce((sum, item) => sum + (item.enabled ? Number(item.monthlyQuota || 0) : 0), 0);
  const updateEntitlement = (domain: string, patch: Partial<TenantAIEntitlement>) => {
    onEntitlementsChange(prev => prev.map(item => item.resourceDomain === domain ? { ...item, ...patch } : item));
  };
  const packageForDomain = (domain: string) => (
    packages.find(item => item.resourceDomains.includes(domain))
    || packages.find(item => item.code === 'enterprise_ai')
    || packages[0]
  );

  return (
    <section className="space-y-5">
      <div className="bg-white border border-slate-200 rounded-lg p-5">
        <ProductPageHeader
          title="AI 资源管理"
          subtitle="平台统一配置供应商、模型策略、客户加购包权益和真实诊断。"
          icon="fa-brain"
        />
        <div className="mt-5 grid grid-cols-4 gap-3">
          <ProductMetricCard label="供应商" value={String(providers.length)} />
          <ProductMetricCard label="加购包" value={String(packages.length)} />
          <ProductMetricCard label="客户已开通域" value={selected ? String(enabledCount) : '-'} />
          <ProductMetricCard label="客户月额度" value={selected ? String(totalQuota) : '-'} />
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-5">
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold">供应商配置</h3>
            <ProductStatusBadge tone={providerForm.enabled ? 'success' : 'neutral'}>
              {providerForm.enabled ? '启用' : '停用'}
            </ProductStatusBadge>
          </div>
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">供应商编码</span>
              <input
                value={providerForm.providerCode}
                onChange={event => onProviderFormChange(prev => ({ ...prev, providerCode: event.target.value }))}
                className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">显示名称</span>
              <input
                value={providerForm.displayName}
                onChange={event => onProviderFormChange(prev => ({ ...prev, displayName: event.target.value }))}
                className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">接口地址</span>
              <input
                value={providerForm.baseUrl}
                onChange={event => onProviderFormChange(prev => ({ ...prev, baseUrl: event.target.value }))}
                className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
              />
            </label>
            {editingProviderSecret ? (
              <div className="space-y-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">输入新密钥</span>
                  <input
                    name="ai-provider-api-key-replacement"
                    autoComplete="new-password"
                    value={providerForm.apiKey}
                    onChange={event => onProviderFormChange(prev => ({ ...prev, apiKey: event.target.value }))}
                    className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
                    placeholder="仅在更换密钥时填写"
                    type="password"
                  />
                </label>
                <button
                  type="button"
                  className="text-xs text-slate-500 hover:text-slate-700"
                  onClick={() => {
                    onProviderFormChange(prev => ({ ...prev, apiKey: '' }));
                    onEditingProviderSecretChange(false);
                  }}
                >取消更换</button>
              </div>
            ) : (
              <div className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2">
                <span className="text-xs text-slate-500">
                  {providers[0]?.hasApiKey ? `密钥已保存：${providers[0].maskedApiKey || '已脱敏'}` : '尚未保存密钥'}
                </span>
                <button
                  type="button"
                  className="text-xs font-medium text-blue-600 hover:text-blue-700"
                  onClick={() => onEditingProviderSecretChange(true)}
                >更换密钥</button>
              </div>
            )}
            <label className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm">
              <span>启用供应商</span>
              <input
                type="checkbox"
                checked={providerForm.enabled}
                onChange={event => onProviderFormChange(prev => ({ ...prev, enabled: event.target.checked }))}
                className="h-4 w-4"
              />
            </label>
            <ProductButton tone="primary" icon="fa-floppy-disk" disabled={saving} onClick={onSaveProvider}>
              保存供应商
            </ProductButton>
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold">平台诊断</h3>
              <p className="mt-1 text-xs text-slate-500">诊断只允许平台后台触发，不占用客户权益。</p>
            </div>
            <ProductButton icon="fa-vial" disabled={saving} onClick={onRunDiagnostic}>运行诊断</ProductButton>
          </div>
          <textarea
            value={diagnosticPrompt}
            onChange={event => onDiagnosticPromptChange(event.target.value)}
            className="mt-4 min-h-[90px] w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400"
            maxLength={800}
          />
          {diagnosticResult && (
            <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
              <div>状态：{diagnosticResult.ok ? '成功' : '异常'}</div>
              <div>请求：{diagnosticResult.requestId || '-'}</div>
              <div className="mt-1 line-clamp-3">{diagnosticResult.response || diagnosticResult.error || '-'}</div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold">客户 AI 加购包权益</h3>
            <p className="mt-1 text-xs text-slate-500">{selected ? `${selected.name} 的资源域、档位和月额度。` : '请选择左侧企业客户。'}</p>
          </div>
          <ProductButton tone="primary" icon="fa-floppy-disk" disabled={!selected || saving} onClick={onSaveEntitlements}>
            保存权益
          </ProductButton>
        </div>

        {!selected ? (
          <ProductEmptyState compact title="请选择企业客户后配置 AI 权益" />
        ) : (
          <div className="mt-4 rounded-md border border-slate-200 overflow-hidden">
            <div className="grid grid-cols-[140px_100px_170px_220px_140px_120px] bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
              <span>资源域</span>
              <span>开通</span>
              <span>加购包</span>
              <span>允许档位</span>
              <span>默认档位</span>
              <span>月额度</span>
            </div>
            {entitlements.map(item => {
              const pkg = packageForDomain(item.resourceDomain);
              return (
                <div key={item.resourceDomain} className="grid grid-cols-[140px_100px_170px_220px_140px_120px] items-center gap-2 border-t border-slate-100 px-3 py-3 text-sm text-slate-700">
                  <span>
                    <span className="block font-medium">{item.resourceLabel || item.resourceDomain}</span>
                    <span className="block text-xs text-slate-400">{item.resourceDomain}</span>
                  </span>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={item.enabled}
                      onChange={event => updateEntitlement(item.resourceDomain, {
                        enabled: event.target.checked,
                        packageCode: item.packageCode || pkg?.code || 'enterprise_ai',
                        allowedTiers: item.allowedTiers.length ? item.allowedTiers : (pkg?.allowedTiers || ['standard']),
                        selectedTier: item.selectedTier || (pkg?.allowedTiers?.[0] || 'standard'),
                        monthlyQuota: item.monthlyQuota || pkg?.defaultMonthlyQuota || 1000,
                      })}
                      className="h-4 w-4"
                    />
                    <span>{item.enabled ? '已开' : '未开'}</span>
                  </label>
                  <select
                    value={item.packageCode || pkg?.code || 'enterprise_ai'}
                    onChange={event => {
                      const nextPackage = packages.find(row => row.code === event.target.value);
                      updateEntitlement(item.resourceDomain, {
                        packageCode: event.target.value,
                        allowedTiers: nextPackage?.allowedTiers || item.allowedTiers,
                        selectedTier: nextPackage?.allowedTiers?.[0] || item.selectedTier || 'standard',
                        monthlyQuota: item.monthlyQuota || nextPackage?.defaultMonthlyQuota || 1000,
                      });
                    }}
                    className="h-9 rounded-md border border-slate-200 px-2 text-sm"
                  >
                    {packages.map(row => (
                      <option key={row.code} value={row.code}>{row.name}</option>
                    ))}
                  </select>
                  <div className="flex flex-wrap gap-2">
                    {['basic', 'standard', 'professional'].map(tier => (
                      <label key={tier} className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={item.allowedTiers.includes(tier)}
                          onChange={event => {
                            const next = event.target.checked
                              ? Array.from(new Set([...item.allowedTiers, tier]))
                              : item.allowedTiers.filter(value => value !== tier);
                            updateEntitlement(item.resourceDomain, {
                              allowedTiers: next,
                              selectedTier: next.includes(item.selectedTier || '') ? item.selectedTier : (next[0] || ''),
                            });
                          }}
                        />
                        <span>{tierLabels[tier]}</span>
                      </label>
                    ))}
                  </div>
                  <select
                    value={item.selectedTier || ''}
                    onChange={event => updateEntitlement(item.resourceDomain, { selectedTier: event.target.value })}
                    className="h-9 rounded-md border border-slate-200 px-2 text-sm"
                  >
                    {(item.allowedTiers.length ? item.allowedTiers : ['standard']).map(tier => (
                      <option key={tier} value={tier}>{tierLabels[tier] || tier}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min="0"
                    value={item.monthlyQuota || 0}
                    onChange={event => updateEntitlement(item.resourceDomain, { monthlyQuota: Number(event.target.value || 0) })}
                    className="h-9 rounded-md border border-slate-200 px-2 text-sm"
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="bg-white border border-slate-200 rounded-lg p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-semibold">客户 AI 用量</h3>
          <span className="text-xs text-slate-500">{usage?.periodKey || '-'}</span>
        </div>
        <div className="rounded-md border border-slate-200 overflow-hidden">
          <div className="grid grid-cols-[160px_120px_120px_100px_1fr] bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
            <span>时间</span>
            <span>资源域</span>
            <span>场景</span>
            <span>状态</span>
            <span>请求</span>
          </div>
          {usageRows.slice(0, 80).map((row: AIUsageLedgerItem) => (
            <div key={row.id} className="grid grid-cols-[160px_120px_120px_100px_1fr] border-t border-slate-100 px-3 py-2 text-sm text-slate-700">
              <span className="truncate">{row.createdAt || '-'}</span>
              <span className="truncate">{row.resourceDomain}</span>
              <span className="truncate">{row.useCase || '-'}</span>
              <span className="truncate">{row.status}</span>
              <span className="truncate text-slate-500">{row.requestId || '-'}</span>
            </div>
          ))}
          {!usageRows.length && <ProductEmptyState compact title="暂无 AI 用量记录" />}
        </div>
      </div>
    </section>
  );
}

function SubscriptionsPanel({
  selected,
  tenants,
  orders,
  invoices,
  billingEvents,
  billingEventForm,
  onBillingEventFormChange,
  saving,
  onUpdateInvoiceStatus,
  onCreateBillingEvent,
}: {
  selected: PlatformTenant | null;
  tenants: PlatformTenant[];
  orders: PlatformOrder[];
  invoices: PlatformInvoice[];
  billingEvents: PlatformBillingEvent[];
  billingEventForm: BillingEventForm;
  onBillingEventFormChange: Dispatch<SetStateAction<BillingEventForm>>;
  saving: boolean;
  onUpdateInvoiceStatus: (invoiceId: string, status: string) => void;
  onCreateBillingEvent: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const subscription: PlatformSubscription | null | undefined = selected?.subscription;
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">订阅管理</h2>
        <span className="text-sm text-slate-500">企业客户 {tenants.length} 家</span>
      </div>
      {!selected ? (
        <ProductEmptyState compact title="请选择左侧企业查看订阅状态" />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3">
            <ProductMetricCard label="企业" value={selected.name} />
            <ProductMetricCard label="套餐" value={selected.planCode || '-'} />
            <ProductMetricCard label="状态" value={subscription?.status || selected.status || '-'} />
            <ProductMetricCard label="到期" value={selected.expiresAt || subscription?.endsAt || '-'} />
          </div>
          <div className="rounded-md border border-slate-200 overflow-hidden">
            <div className="grid grid-cols-4 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
              <span>订阅 ID</span>
              <span>套餐</span>
              <span>开始时间</span>
              <span>结束时间</span>
            </div>
            <div className="grid grid-cols-4 px-3 py-3 text-sm text-slate-700">
              <span>{subscription?.id || '-'}</span>
              <span>{subscription?.planCode || selected.planCode || '-'}</span>
              <span>{subscription?.startsAt || '-'}</span>
              <span>{subscription?.endsAt || selected.expiresAt || '-'}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-md border border-slate-200 overflow-hidden">
              <div className="bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">订单记录</div>
              <div className="grid grid-cols-[1fr_110px_90px] px-3 py-2 text-xs font-medium text-slate-500">
                <span>订单号</span>
                <span>金额</span>
                <span>状态</span>
              </div>
              {orders.map(order => (
                <div key={order.id} className="grid grid-cols-[1fr_110px_90px] border-t border-slate-100 px-3 py-2 text-sm text-slate-700">
                  <span className="truncate">{order.orderNo}</span>
                  <span>{formatCents(order.amountCents, order.currency)}</span>
                  <span>{order.status}</span>
                </div>
              ))}
              {!orders.length && <div className="px-3 py-8 text-center text-sm text-slate-400">暂无订单记录</div>}
            </div>
            <div className="rounded-md border border-slate-200 overflow-hidden">
              <div className="bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">发票记录</div>
              <div className="grid grid-cols-[1fr_100px_90px_90px] px-3 py-2 text-xs font-medium text-slate-500">
                <span>抬头</span>
                <span>金额</span>
                <span>状态</span>
                <span>操作</span>
              </div>
              {invoices.map(invoice => (
                <div key={invoice.id} className="grid grid-cols-[1fr_100px_90px_90px] border-t border-slate-100 px-3 py-2 text-sm text-slate-700">
                  <span className="truncate">{invoice.title}</span>
                  <span>{formatCents(invoice.amountCents)}</span>
                  <span>{invoice.status}</span>
                  <span>
                    {invoice.status !== 'issued' ? (
                      <button
                        className="text-blue-600 hover:text-blue-700 disabled:text-slate-300"
                        disabled={saving}
                        onClick={() => onUpdateInvoiceStatus(invoice.id, 'issued')}
                      >
                        开票
                      </button>
                    ) : '已开'}
                  </span>
                </div>
              ))}
              {!invoices.length && <div className="px-3 py-8 text-center text-sm text-slate-400">暂无发票记录</div>}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between bg-slate-50 px-3 py-2">
              <h3 className="text-sm font-medium text-slate-700">商业跟进记录</h3>
              <span className="text-xs text-slate-500">{billingEvents.length} 条</span>
            </div>
            <form className="grid grid-cols-[180px_1fr_auto] gap-2 border-t border-slate-100 p-3" onSubmit={onCreateBillingEvent}>
              <select
                className="h-9 rounded-md border border-slate-200 px-3 text-sm"
                value={billingEventForm.eventType}
                onChange={event => onBillingEventFormChange(prev => ({ ...prev, eventType: event.target.value }))}
              >
                <option value="renewal_reminder_sent">续费提醒</option>
                <option value="payment_follow_up">回款跟进</option>
                <option value="invoice_follow_up">发票跟进</option>
                <option value="contract_review">合同确认</option>
                <option value="customer_success_check">客户成功回访</option>
              </select>
              <input
                required
                maxLength={1000}
                className="h-9 rounded-md border border-slate-200 px-3 text-sm"
                placeholder="记录跟进要点"
                value={billingEventForm.note}
                onChange={event => onBillingEventFormChange(prev => ({ ...prev, note: event.target.value }))}
              />
              <ProductButton tone="primary" disabled={saving} icon="fa-plus">添加</ProductButton>
            </form>
            <div className="grid grid-cols-[160px_1fr_150px_120px] px-3 py-2 text-xs font-medium text-slate-500">
              <span>类型</span>
              <span>记录</span>
              <span>操作人</span>
              <span>时间</span>
            </div>
            {billingEvents.map(event => (
              <div key={event.id} className="grid grid-cols-[160px_1fr_150px_120px] border-t border-slate-100 px-3 py-2 text-sm text-slate-700">
                <span className="truncate">{event.eventType}</span>
                <span className="truncate">{event.note || '-'}</span>
                <span className="truncate">{event.operatorName || event.operatorId || '-'}</span>
                <span className="truncate">{event.createdAt || '-'}</span>
              </div>
            ))}
            {!billingEvents.length && <div className="px-3 py-8 text-center text-sm text-slate-400">暂无商业跟进记录</div>}
          </div>
        </div>
      )}
    </section>
  );
}

function DiagnosticsPanel({ selected, diagnostics }: { selected: PlatformTenant | null; diagnostics: PlatformTenantDiagnostics | null }) {
  if (!selected) {
    return (
      <section className="bg-white border border-slate-200 rounded-lg p-5">
        <h2 className="text-xl font-semibold">运行诊断</h2>
        <ProductEmptyState compact title="请选择左侧企业查看运行诊断" />
      </section>
    );
  }

  const usage = diagnostics?.usage || selected.usage || {};
  const disk = diagnostics?.disk || {};
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">运行诊断</h2>
        <span className="text-sm text-slate-500">{diagnostics?.checkedAt || '正在加载诊断'}</span>
      </div>
      <div className="grid grid-cols-4 gap-3">
        <ProductMetricCard label="后台用户" value={String(usage.users ?? 0)} />
        <ProductMetricCard label="员工档案" value={String(usage.employees ?? 0)} />
        <ProductMetricCard label="存储 MB" value={String(usage.storageMb ?? 0)} />
        <ProductMetricCard label="AI 本月调用" value={String(usage.aiCallsThisMonth ?? 0)} />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <ProductMetricCard label="磁盘总量 MB" value={String(disk.totalMb ?? '-')} />
        <ProductMetricCard label="已用 MB" value={String(disk.usedMb ?? '-')} />
        <ProductMetricCard label="可用 MB" value={String(disk.freeMb ?? '-')} />
      </div>
    </section>
  );
}

function OperationLogsPanel({ logs, selected }: { logs: PlatformOperationLog[]; selected: PlatformTenant | null }) {
  return (
    <section className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">平台操作日志</h2>
        <span className="text-sm text-slate-500">{selected ? selected.name : '全部企业'} · {logs.length} 条</span>
      </div>
      <div className="rounded-md border border-slate-200 overflow-hidden">
        <div className="grid grid-cols-[150px_1fr_160px_160px] bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
          <span>时间</span>
          <span>动作</span>
          <span>企业</span>
          <span>操作人</span>
        </div>
        {logs.map(log => (
          <div key={log.id} className="grid grid-cols-[150px_1fr_160px_160px] px-3 py-3 text-sm text-slate-700 border-t border-slate-100">
            <span className="truncate">{log.createdAt || '-'}</span>
            <span className="truncate">{log.action || '-'}</span>
            <span className="truncate">{log.tenantName || '-'}</span>
            <span className="truncate">{log.userName || '-'}</span>
          </div>
        ))}
        {!logs.length && <div className="p-8 text-center text-sm text-slate-400">暂无平台操作日志</div>}
      </div>
    </section>
  );
}

function formatCents(value?: number, currency = 'CNY') {
  const amount = Number(value || 0) / 100;
  return `${currency} ${amount.toFixed(2)}`;
}
