import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import AppIcon from '../AppIcon';
import confirm from '../ConfirmDialog';
import {
  ProductButton,
  ProductEmptyState,
  ProductMetricCard,
  ProductStatusBadge,
} from '../product';
import {
  ApiError,
  platformApi,
  platformEnterpriseApplicationApi,
  type EnterpriseApplicationStatus,
  type EnterpriseApplicationListItem,
  type EnterpriseApplicationSummary,
  type EnterpriseServiceApplication,
  type PlatformTenant,
} from '../../utils/api';
import {
  LatestRequestGate,
  localInputToUtcIso,
  runConfirmedEnterpriseConversion,
  utcIsoToLocalInput,
} from '../../utils/enterpriseApplications';

const EMPTY_SUMMARY: EnterpriseApplicationSummary = {
  todayNew: 0,
  new: 0,
  contacting: 0,
  qualified: 0,
  closed: 0,
  converted: 0,
};

const TENANT_OPTION_PAGE_SIZE = 500;

const STATUS_META: Record<EnterpriseApplicationStatus, { label: string; tone: 'primary' | 'warning' | 'success' | 'neutral' }> = {
  new: { label: '待联系', tone: 'primary' },
  contacting: { label: '跟进中', tone: 'warning' },
  qualified: { label: '有效意向', tone: 'success' },
  closed: { label: '已关闭', tone: 'neutral' },
  converted: { label: '已转企业', tone: 'success' },
};

const MODULE_LABELS: Record<string, string> = {
  organization: '组织与员工',
  recruitment: '招聘管理',
  attendance: '考勤排班',
  approval: '流程审批',
  performance: '绩效管理',
  payroll: '薪酬核算',
  training_exam: '培训考试',
  assistant: 'AI 助手',
};

const CONTACT_TIME_LABELS: Record<string, string> = {
  weekday_morning: '工作日上午',
  weekday_afternoon: '工作日下午',
  weekday_evening: '工作日傍晚',
  anytime: '工作日均可',
};

const formatDateTime = (value?: string | null) => {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
};

export default function EnterpriseApplicationsPanel({
  currentUserId,
}: {
  currentUserId: string;
}) {
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [items, setItems] = useState<EnterpriseApplicationListItem[]>([]);
  const [status, setStatus] = useState<EnterpriseApplicationStatus | ''>('');
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [writeError, setWriteError] = useState('');
  const [message, setMessage] = useState('');
  const [selected, setSelected] = useState<EnterpriseServiceApplication | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [internalNote, setInternalNote] = useState('');
  const [followUpAt, setFollowUpAt] = useState('');
  const [convertTenantId, setConvertTenantId] = useState('');
  const [tenantOptions, setTenantOptions] = useState<PlatformTenant[]>([]);
  const [tenantOptionsLoading, setTenantOptionsLoading] = useState(true);
  const [tenantOptionsError, setTenantOptionsError] = useState('');
  const listGate = useRef(new LatestRequestGate());
  const detailGate = useRef(new LatestRequestGate());
  const writeGate = useRef(new LatestRequestGate());
  const listAbort = useRef<AbortController | null>(null);
  const detailAbort = useRef<AbortController | null>(null);
  const writeAbort = useRef<AbortController | null>(null);
  const tenantOptionsAbort = useRef<AbortController | null>(null);
  const selectedId = useRef('');

  const loadList = useCallback(async () => {
    const target = JSON.stringify({ status, keyword, page });
    const ticket = listGate.current.begin(target);
    listAbort.current?.abort();
    const controller = new AbortController();
    listAbort.current = controller;
    setLoading(true);
    setListError('');
    try {
      const [nextSummary, result] = await Promise.all([
        platformEnterpriseApplicationApi.summary({ signal: controller.signal }),
        platformEnterpriseApplicationApi.list(
          { status, keyword: keyword || undefined, page, pageSize: 20 },
          { signal: controller.signal },
        ),
      ]);
      if (!listGate.current.isCurrent(ticket, target)) return;
      setSummary(nextSummary);
      setItems(result.items || []);
      setTotal(result.total || 0);
      setTotalPages(result.totalPages || 0);
    } catch (caught) {
      if (controller.signal.aborted || !listGate.current.isCurrent(ticket, target)) return;
      setListError(caught instanceof Error ? caught.message : '加载企业申请失败');
    } finally {
      if (listGate.current.isCurrent(ticket, target)) setLoading(false);
    }
  }, [keyword, page, status]);

  useEffect(() => {
    const gate = listGate.current;
    void loadList();
    return () => {
      listAbort.current?.abort();
      gate.invalidate();
    };
  }, [loadList]);

  useEffect(() => {
    tenantOptionsAbort.current?.abort();
    const controller = new AbortController();
    tenantOptionsAbort.current = controller;
    setTenantOptionsLoading(true);
    setTenantOptionsError('');
    const loadAllTenantOptions = async () => {
      const rows: PlatformTenant[] = [];
      for (let page = 1; ; page += 1) {
        const batch = await platformApi.listTenants(
          { page, pageSize: TENANT_OPTION_PAGE_SIZE },
          { signal: controller.signal },
        );
        rows.push(...batch);
        if (batch.length < TENANT_OPTION_PAGE_SIZE) return rows;
      }
    };
    void loadAllTenantOptions()
      .then(rows => {
        if (!controller.signal.aborted) setTenantOptions(rows || []);
      })
      .catch(caught => {
        if (!controller.signal.aborted) {
          setTenantOptionsError(caught instanceof Error ? caught.message : '加载企业客户选项失败');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setTenantOptionsLoading(false);
      });
    return () => {
      tenantOptionsAbort.current?.abort();
      tenantOptionsAbort.current = null;
    };
  }, []);

  useEffect(() => () => {
    listAbort.current?.abort();
    detailAbort.current?.abort();
    writeAbort.current?.abort();
    tenantOptionsAbort.current?.abort();
    listGate.current.invalidate();
    detailGate.current.invalidate();
    writeGate.current.invalidate();
    selectedId.current = '';
  }, []);

  const openDetail = async (id: string) => {
    detailAbort.current?.abort();
    writeAbort.current?.abort();
    writeGate.current.invalidate();
    const controller = new AbortController();
    detailAbort.current = controller;
    const ticket = detailGate.current.begin(id);
    selectedId.current = id;
    setSelected(null);
    setDetailLoading(true);
    setMessage('');
    setDetailError('');
    setWriteError('');
    try {
      const detail = await platformEnterpriseApplicationApi.detail(id, { signal: controller.signal });
      if (!detailGate.current.isCurrent(ticket, selectedId.current)) return;
      setSelected(detail);
      setInternalNote(detail.internalNote || '');
      setFollowUpAt(utcIsoToLocalInput(detail.followUpAt));
      setConvertTenantId(detail.convertedTenantId || '');
    } catch (caught) {
      if (!controller.signal.aborted && detailGate.current.isCurrent(ticket, selectedId.current)) {
        setDetailError(caught instanceof Error ? caught.message : '加载申请详情失败');
      }
    } finally {
      if (detailGate.current.isCurrent(ticket, selectedId.current)) setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    detailAbort.current?.abort();
    writeAbort.current?.abort();
    detailGate.current.invalidate();
    writeGate.current.invalidate();
    selectedId.current = '';
    setSelected(null);
    setDetailError('');
    setWriteError('');
    setDetailLoading(false);
    setSaving(false);
    setMessage('');
  };

  const refreshAfterConflict = async (
    target: string,
    ticket: ReturnType<LatestRequestGate['begin']>,
  ) => {
    const controller = new AbortController();
    writeAbort.current = controller;
    try {
      const latest = await platformEnterpriseApplicationApi.detail(target, { signal: controller.signal });
      if (!writeGate.current.isCurrent(ticket, selectedId.current)) return;
      setSelected(latest);
      setInternalNote(latest.internalNote || '');
      setFollowUpAt(utcIsoToLocalInput(latest.followUpAt));
      setConvertTenantId(latest.convertedTenantId || '');
      await loadList();
      if (writeGate.current.isCurrent(ticket, selectedId.current)) {
        setWriteError('申请已被其他管理员更新，已刷新最新详情，请核对后重试');
      }
    } catch {
      if (controller.signal.aborted || !writeGate.current.isCurrent(ticket, selectedId.current)) return;
      setWriteError('申请已被其他管理员更新，但刷新最新详情失败，请关闭后重新打开');
    }
  };

  const applyUpdate = async (
    data: Omit<Parameters<typeof platformEnterpriseApplicationApi.update>[1], 'version'>,
    successMessage: string,
  ) => {
    if (!selected) return;
    const target = selected.id;
    writeAbort.current?.abort();
    const controller = new AbortController();
    writeAbort.current = controller;
    const ticket = writeGate.current.begin(target);
    setSaving(true);
    setWriteError('');
    setMessage('');
    try {
      const updated = await platformEnterpriseApplicationApi.update(
        target,
        { ...data, version: selected.version },
        { signal: controller.signal },
      );
      if (!writeGate.current.isCurrent(ticket, selectedId.current)) return;
      setSelected(updated);
      setInternalNote(updated.internalNote || '');
      setFollowUpAt(utcIsoToLocalInput(updated.followUpAt));
      setMessage(successMessage);
      await loadList();
    } catch (caught) {
      if (controller.signal.aborted || !writeGate.current.isCurrent(ticket, selectedId.current)) return;
      if (caught instanceof ApiError && caught.status === 409 && caught.code === 'APPLICATION_CONFLICT') {
        await refreshAfterConflict(target, ticket);
        return;
      }
      setWriteError(caught instanceof Error ? caught.message : '保存申请失败');
    } finally {
      if (writeGate.current.isCurrent(ticket, selectedId.current)) setSaving(false);
    }
  };

  const convertApplication = async () => {
    if (!selected || !convertTenantId) {
      setWriteError('请先选择已创建的企业客户');
      return;
    }
    const target = selected.id;
    const tenant = tenantOptions.find(item => item.id === convertTenantId);
    let ticket: ReturnType<LatestRequestGate['begin']> | null = null;
    const controller = new AbortController();
    try {
      const updated = await runConfirmedEnterpriseConversion({
        applicationCompany: selected.companyName,
        targetTenantName: tenant?.name || convertTenantId,
        confirm,
        convert: async () => {
          if (selectedId.current !== target) throw new DOMException('stale target', 'AbortError');
          writeAbort.current?.abort();
          writeAbort.current = controller;
          ticket = writeGate.current.begin(target);
          setSaving(true);
          setWriteError('');
          setMessage('');
          return platformEnterpriseApplicationApi.convert(
            target,
            convertTenantId,
            selected.version,
            { signal: controller.signal },
          );
        },
      });
      if (!updated || !ticket || !writeGate.current.isCurrent(ticket, selectedId.current)) return;
      setSelected(updated);
      setMessage('已关联企业客户，申请状态已更新为已转企业');
      await loadList();
    } catch (caught) {
      if (
        controller?.signal.aborted
        || selectedId.current !== target
        || (ticket && !writeGate.current.isCurrent(ticket, selectedId.current))
      ) return;
      if (
        ticket
        && caught instanceof ApiError
        && caught.status === 409
        && caught.code === 'APPLICATION_CONFLICT'
      ) {
        await refreshAfterConflict(target, ticket);
        return;
      }
      setWriteError(caught instanceof Error ? caught.message : '关联企业失败');
    } finally {
      if (ticket && writeGate.current.isCurrent(ticket, selectedId.current)) setSaving(false);
    }
  };

  const submitFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(1);
    setKeyword(keywordInput.trim());
  };

  const selectedStatus = selected ? STATUS_META[selected.status] : null;
  const sourceLabel = selected?.source === 'login_home' ? '登录页' : '企业服务申请页';
  return (
    <section className="space-y-5" aria-label="企业申请工作台">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">企业申请</h1>
          <p className="mt-1 text-sm text-slate-500">统一查看官网申请，人工联系、判断意向并关联已创建企业。</p>
        </div>
        <ProductButton icon="fa-rotate" disabled={loading} onClick={() => void loadList()}>刷新</ProductButton>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ProductMetricCard label="今日新增" value={summary.todayNew} icon="fa-calendar-day" hint="今天提交的全部申请" />
        <ProductMetricCard label="待联系" value={summary.new} icon="fa-phone" hint="尚未开始跟进" />
        <ProductMetricCard label="跟进中" value={summary.contacting} icon="fa-comments" hint="正在联系和确认需求" />
        <ProductMetricCard label="有效意向" value={summary.qualified} icon="fa-bullseye" hint="可关联已创建企业" />
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <form className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4" onSubmit={submitFilters}>
          <label className="min-w-[220px] flex-1">
            <span className="sr-only">关键词</span>
            <div className="relative">
              <AppIcon className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-xs text-slate-400" />
              <input value={keywordInput} onChange={event => setKeywordInput(event.target.value)} maxLength={100} placeholder="关键词：企业、联系人、手机号或申请编号" className="h-9 w-full rounded-md border border-slate-200 pl-9 pr-3 text-sm outline-none focus:border-blue-400" />
            </div>
          </label>
          <label>
            <span className="sr-only">状态</span>
            <select value={status} onChange={event => { setStatus(event.target.value as EnterpriseApplicationStatus | ''); setPage(1); }} className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400">
              <option value="">全部状态</option>
              <option value="new">待联系</option>
              <option value="contacting">跟进中</option>
              <option value="qualified">有效意向</option>
              <option value="converted">已转企业</option>
              <option value="closed">已关闭</option>
            </select>
          </label>
          <ProductButton tone="primary" icon="fa-search">查询</ProductButton>
        </form>

        {listError && (
          <div className="m-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {listError}
          </div>
        )}

        <div className="overflow-x-auto">
          <div className="min-w-[920px]">
            <div className="grid grid-cols-[150px_1.6fr_110px_140px_150px_80px] bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500">
              <span>申请编号</span><span>企业</span><span>状态</span><span>负责人</span><span>申请时间</span><span>操作</span>
            </div>
            {items.map(item => {
              const meta = STATUS_META[item.status];
              return (
                <div key={item.id} className="grid grid-cols-[150px_1.6fr_110px_140px_150px_80px] items-center border-t border-slate-100 px-4 py-3 text-sm text-slate-700">
                  <span className="truncate font-mono text-xs text-slate-500" title={item.applicationNo}>{item.applicationNo}</span>
                  <span className="min-w-0"><strong className="block truncate font-medium text-slate-800">{item.companyName}</strong><span className="block truncate text-xs text-slate-400">{item.region || '地区未填写'} · {item.employeeScale || '规模未填写'}</span></span>
                  <span><ProductStatusBadge tone={meta.tone}>{meta.label}</ProductStatusBadge></span>
                  <span className="truncate">{item.ownerName || '待接手'}</span>
                  <span className="text-xs text-slate-500">{formatDateTime(item.createdAt)}</span>
                  <button type="button" onClick={() => void openDetail(item.id)} className="text-sm font-medium text-blue-600 hover:text-blue-700">详情</button>
                </div>
              );
            })}
          </div>
        </div>

        {loading && <div className="flex items-center justify-center gap-2 p-10 text-sm text-slate-500"><AppIcon className="fas fa-spinner fa-spin" />正在加载申请</div>}
        {!loading && !items.length && <ProductEmptyState compact title="暂无符合条件的企业申请" description="新申请提交后会自动出现在这里。" />}

        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm text-slate-500">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-2">
            <ProductButton disabled={page <= 1 || loading} onClick={() => setPage(current => Math.max(1, current - 1))}>上一页</ProductButton>
            <span>第 {page} / {Math.max(totalPages, 1)} 页</span>
            <ProductButton disabled={page >= totalPages || loading} onClick={() => setPage(current => current + 1)}>下一页</ProductButton>
          </div>
        </div>
      </div>

      {(selected || detailLoading || detailError) && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" role="dialog" aria-modal="true" aria-label="企业申请详情">
          <button type="button" className="min-w-0 flex-1 cursor-default" aria-label="关闭详情" onClick={closeDetail} />
          <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
            {detailLoading && !selected ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><AppIcon className="fas fa-spinner fa-spin" />正在加载详情</div>
            ) : detailError && !selected ? (
              <div className="m-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
                <p>{detailError}</p>
                <ProductButton className="mt-3" onClick={closeDetail}>关闭</ProductButton>
              </div>
            ) : selected && selectedStatus ? (
              <>
                <header className="sticky top-0 z-10 flex items-start justify-between border-b border-slate-200 bg-white px-6 py-5">
                  <div>
                    <div className="flex items-center gap-3"><h2 className="text-lg font-semibold">{selected.companyName}</h2><ProductStatusBadge tone={selectedStatus.tone}>{selectedStatus.label}</ProductStatusBadge></div>
                    <p className="mt-1 font-mono text-xs text-slate-400">{selected.applicationNo}</p>
                  </div>
                  <button type="button" aria-label="关闭详情" onClick={closeDetail} className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600"><AppIcon className="fas fa-xmark" /></button>
                </header>

                <div className="space-y-6 p-6">
                  {(writeError || message) && <div aria-live="polite" className={`rounded-md border px-4 py-3 text-sm ${writeError ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{writeError || message}</div>}

                  <section>
                    <h3 className="text-sm font-semibold text-slate-800">申请信息</h3>
                    <dl className="mt-3 grid gap-x-5 gap-y-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-2">
                      {[
                        ['联系人', selected.contactName],
                        ['手机号', selected.mobile],
                        ['工作邮箱', selected.email || '-'],
                        ['所在地区', selected.region || '-'],
                        ['员工规模', selected.employeeScale || '-'],
                        ['期望联系时间', CONTACT_TIME_LABELS[selected.preferredContactTime || ''] || '-'],
                        ['来源', sourceLabel],
                        ['申请时间', formatDateTime(selected.createdAt)],
                      ].map(([label, value]) => <div key={label}><dt className="text-xs text-slate-400">{label}</dt><dd className="mt-1 text-sm text-slate-700">{value}</dd></div>)}
                    </dl>
                    <div className="mt-4"><span className="text-xs text-slate-400">关注功能</span><div className="mt-2 flex flex-wrap gap-2">{selected.interestedModules.length ? selected.interestedModules.map(key => <span key={key} className="rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-700">{MODULE_LABELS[key] || key}</span>) : <span className="text-sm text-slate-400">未选择</span>}</div></div>
                    <div className="mt-4"><span className="text-xs text-slate-400">补充需求</span><p className="mt-2 whitespace-pre-wrap rounded-md border border-slate-200 p-3 text-sm leading-6 text-slate-700">{selected.notes || '未填写'}</p></div>
                  </section>

                  <section className="border-t border-slate-100 pt-5">
                    <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-slate-800">跟进操作</h3><span className="text-xs text-slate-400">负责人：{selected.ownerName || '待接手'}</span></div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {selected.ownerUserId !== currentUserId && <ProductButton icon="fa-user-check" disabled={saving} onClick={() => void applyUpdate({ ownerUserId: currentUserId }, '已接手该申请')}>接手</ProductButton>}
                      {selected.status === 'new' && <ProductButton tone="primary" icon="fa-phone" disabled={saving} onClick={() => void applyUpdate({ status: 'contacting' }, '已标记为跟进中')}>标记已联系</ProductButton>}
                      {selected.status === 'contacting' && <ProductButton tone="primary" icon="fa-bullseye" disabled={saving} onClick={() => void applyUpdate({ status: 'qualified' }, '已标记为有效意向')}>标记有效意向</ProductButton>}
                      {['contacting', 'qualified'].includes(selected.status) && <ProductButton tone="danger" icon="fa-ban" disabled={saving} onClick={() => void applyUpdate({ status: 'closed' }, '申请已关闭')}>关闭</ProductButton>}
                      {selected.status === 'closed' && <ProductButton icon="fa-rotate-left" disabled={saving} onClick={() => void applyUpdate({ status: 'contacting' }, '申请已重新进入跟进')}>重新跟进</ProductButton>}
                    </div>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      <label><span className="mb-1.5 block text-xs text-slate-500">下次跟进</span><input type="datetime-local" value={followUpAt} onChange={event => setFollowUpAt(event.target.value)} className="h-10 w-full rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400" /></label>
                      <div className="flex items-end"><ProductButton icon="fa-calendar-check" disabled={saving} onClick={() => void applyUpdate({ followUpAt: localInputToUtcIso(followUpAt) }, '下次跟进时间已保存')}>保存跟进时间</ProductButton></div>
                    </div>
                    <label className="mt-4 block"><span className="mb-1.5 block text-xs text-slate-500">内部备注</span><textarea value={internalNote} onChange={event => setInternalNote(event.target.value)} maxLength={2000} rows={4} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" placeholder="仅平台管理员可见，不要记录无关个人信息" /></label>
                    <ProductButton className="mt-2" icon="fa-floppy-disk" disabled={saving} onClick={() => void applyUpdate({ internalNote }, '内部备注已保存')}>保存内部备注</ProductButton>
                  </section>

                  {selected.status === 'qualified' && (
                    <section className="rounded-lg border border-blue-100 bg-blue-50/60 p-4">
                      <h3 className="text-sm font-semibold text-slate-800">关联已创建企业</h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500">这里只建立关联，不会自动创建企业、管理员、试用账号或订阅。</p>
                      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                        <select value={convertTenantId} onChange={event => setConvertTenantId(event.target.value)} disabled={saving || tenantOptionsLoading || Boolean(tenantOptionsError)} className="h-9 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 disabled:bg-slate-100">
                          <option value="">{tenantOptionsLoading ? '正在加载企业客户' : tenantOptionsError ? '企业客户选项加载失败' : '请选择已创建企业'}</option>
                          {tenantOptions.map(tenant => <option key={tenant.id} value={tenant.id}>{tenant.name} · {tenant.slug}</option>)}
                        </select>
                        <ProductButton tone="primary" icon="fa-link" disabled={saving || !convertTenantId} onClick={() => void convertApplication()}>确认关联</ProductButton>
                      </div>
                      {tenantOptionsError && <p className="mt-2 text-xs text-red-600" role="alert">{tenantOptionsError}</p>}
                    </section>
                  )}

                  {selected.status === 'converted' && <section className="rounded-lg border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-700"><AppIcon className="fas fa-circle-check mr-2" />已关联：{selected.convertedTenantName || selected.convertedTenantId}</section>}

                  <section className="border-t border-slate-100 pt-5">
                    <h3 className="text-sm font-semibold text-slate-800">状态时间线</h3>
                    <ol className="mt-3 space-y-3">{selected.timeline.map((entry, index) => <li key={`${entry.status}-${entry.at}-${index}`} className="flex gap-3"><span className="mt-1.5 h-2 w-2 rounded-full bg-blue-500" /><span><span className="block text-sm text-slate-700">{entry.label}</span><span className="block text-xs text-slate-400">{formatDateTime(entry.at)}</span></span></li>)}</ol>
                  </section>
                </div>
              </>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  );
}
