import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import AppIcon from '../../components/AppIcon';
import {
  createIdempotencyKey,
  publicEnterpriseApplicationApi,
  type EnterpriseApplicationCreatePayload,
} from '../../utils/api';
import {
  validateEnterpriseApplicationForm,
  type EnterpriseApplicationFieldErrors,
} from './form';
import { SubmissionIdempotencyKey } from '../../utils/enterpriseApplications';

type ApplicationForm = Omit<EnterpriseApplicationCreatePayload, 'privacyConsent' | 'email' | 'region' | 'employeeScale' | 'preferredContactTime' | 'notes'> & {
  email: string;
  region: string;
  employeeScale: string;
  preferredContactTime: string;
  notes: string;
  privacyConsent: boolean;
};

const MODULE_OPTIONS = [
  { key: 'organization', label: '组织与员工' },
  { key: 'recruitment', label: '招聘管理' },
  { key: 'attendance', label: '考勤排班' },
  { key: 'approval', label: '流程审批' },
  { key: 'performance', label: '绩效管理' },
  { key: 'payroll', label: '薪酬核算' },
  { key: 'training_exam', label: '培训考试' },
  { key: 'assistant', label: 'AI 助手' },
] as const;

const EMPTY_FORM: ApplicationForm = {
  companyName: '',
  contactName: '',
  mobile: '',
  email: '',
  region: '',
  employeeScale: '',
  interestedModules: [],
  preferredContactTime: '',
  notes: '',
  privacyConsent: false,
  website: '',
};

export default function EnterpriseApplicationPage() {
  const [form, setForm] = useState<ApplicationForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<EnterpriseApplicationFieldErrors>({});
  const [applicationNo, setApplicationNo] = useState('');
  const idempotencyKey = useRef(new SubmissionIdempotencyKey());

  useEffect(() => {
    const originalTitle = document.title;
    document.title = '申请企业服务 - 恒聘通 HRM';
    return () => { document.title = originalTitle; };
  }, []);

  const updateText = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    idempotencyKey.current.invalidate();
    setForm(current => ({ ...current, [name]: value }));
    setFieldErrors({});
    setError('');
  };

  const toggleModule = (key: string) => {
    idempotencyKey.current.invalidate();
    setForm(current => ({
      ...current,
      interestedModules: current.interestedModules.includes(key)
        ? current.interestedModules.filter(item => item !== key)
        : [...current.interestedModules, key],
    }));
    setError('');
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validationErrors = validateEnterpriseApplicationForm(form);
    if (Object.keys(validationErrors).length) {
      setFieldErrors(validationErrors);
      setError('请检查标红字段后重新提交');
      return;
    }
    setSubmitting(true);
    setError('');
    setFieldErrors({});
    try {
      const result = await publicEnterpriseApplicationApi.create({
        ...form,
        companyName: form.companyName.trim(),
        contactName: form.contactName.trim(),
        mobile: form.mobile.trim(),
        email: form.email.trim() || undefined,
        region: form.region.trim() || undefined,
        notes: form.notes.trim() || undefined,
        privacyConsent: true,
      }, idempotencyKey.current.getOrCreate(createIdempotencyKey));
      setApplicationNo(result.applicationNo);
    } catch {
      setError('申请暂未提交成功，请稍后重试；如仍失败，请联系平台服务人员。');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link to="/login" className="flex items-center gap-3" aria-label="返回恒聘通登录页">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white">
              <AppIcon className="fas fa-building" />
            </span>
            <span>
              <span className="block text-sm font-semibold text-slate-900">恒聘通 HRM</span>
              <span className="block text-xs text-slate-500">企业人力资源数字化平台</span>
            </span>
          </Link>
          <Link to="/login" className="text-sm font-medium text-blue-600 hover:text-blue-700">
            已有企业账号，返回登录
          </Link>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-8 px-5 py-10 sm:px-8 lg:grid-cols-[0.82fr_1.18fr] lg:py-14">
        <section className="rounded-2xl bg-gradient-to-br from-blue-700 to-blue-500 p-8 text-white shadow-sm lg:p-10">
          <span className="inline-flex rounded-full bg-white/15 px-3 py-1 text-xs font-medium">企业服务申请</span>
          <h1 className="mt-6 text-3xl font-semibold leading-tight">让 HR 事务在线协同，让组织数据真正可用</h1>
          <p className="mt-4 text-sm leading-7 text-blue-50">
            提交基本信息后，企业顾问将在 1 个工作日内联系您，了解组织规模、业务场景与上线计划，再提供匹配的产品方案。
          </p>
          <div className="mt-10 space-y-5">
            {[
              ['fa-layer-group', '一体化 HR 工作台', '覆盖组织员工、招聘、考勤、薪酬、绩效与培训。'],
              ['fa-shield-halved', '企业级数据边界', '独立企业空间、权限控制与平台审计。'],
              ['fa-headset', '人工顾问跟进', '不自动开通账号，由顾问确认需求后安排后续服务。'],
            ].map(([icon, title, description]) => (
              <div key={title} className="flex gap-4">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15">
                  <AppIcon className={`fas ${icon}`} />
                </span>
                <span>
                  <span className="block text-sm font-semibold">{title}</span>
                  <span className="mt-1 block text-xs leading-5 text-blue-100">{description}</span>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {applicationNo ? (
            <div className="flex min-h-[560px] flex-col items-center justify-center text-center" aria-live="polite">
              <span className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-50 text-2xl text-emerald-600">
                <AppIcon className="fas fa-check" />
              </span>
              <h2 className="mt-6 text-2xl font-semibold">申请已提交</h2>
              <p className="mt-3 max-w-md text-sm leading-6 text-slate-500">
                企业顾问将在 1 个工作日内通过您填写的联系方式与您沟通，请留意来电或邮件。
              </p>
              <div className="mt-6 rounded-lg border border-slate-200 bg-slate-50 px-6 py-4">
                <span className="block text-xs text-slate-500">申请编号</span>
                <strong className="mt-1 block font-mono text-base tracking-wide text-slate-800">{applicationNo}</strong>
              </div>
              <Link to="/login" className="mt-8 text-sm font-medium text-blue-600 hover:text-blue-700">
                返回登录页
              </Link>
            </div>
          ) : (
            <>
              <div>
                <h2 className="text-2xl font-semibold">申请企业服务</h2>
                <p className="mt-2 text-sm text-slate-500">请留下企业信息，带 * 的字段为必填项。</p>
              </div>

              <div aria-live="polite" className={`mt-5 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'hidden'}`}>
                <AppIcon className="fas fa-circle-exclamation mr-2" />
                {error}
              </div>

              <form className="mt-6" onSubmit={handleSubmit} noValidate>
                <fieldset disabled={submitting} className="min-w-0 space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="sm:col-span-2">
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">企业名称 *</span>
                    <input name="companyName" value={form.companyName} onChange={updateText} maxLength={120} aria-invalid={Boolean(fieldErrors.companyName)} aria-describedby={fieldErrors.companyName ? 'companyName-error' : undefined} className={`h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2 ${fieldErrors.companyName ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-500 focus:ring-blue-100'}`} autoComplete="organization" />
                    {fieldErrors.companyName && <span id="companyName-error" className="mt-1 block text-xs text-red-600">{fieldErrors.companyName}</span>}
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">联系人 *</span>
                    <input name="contactName" value={form.contactName} onChange={updateText} maxLength={60} aria-invalid={Boolean(fieldErrors.contactName)} aria-describedby={fieldErrors.contactName ? 'contactName-error' : undefined} className={`h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2 ${fieldErrors.contactName ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-500 focus:ring-blue-100'}`} autoComplete="name" />
                    {fieldErrors.contactName && <span id="contactName-error" className="mt-1 block text-xs text-red-600">{fieldErrors.contactName}</span>}
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">手机号 *</span>
                    <input name="mobile" value={form.mobile} onChange={updateText} maxLength={30} inputMode="tel" aria-invalid={Boolean(fieldErrors.mobile)} aria-describedby={fieldErrors.mobile ? 'mobile-error' : undefined} className={`h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2 ${fieldErrors.mobile ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-500 focus:ring-blue-100'}`} autoComplete="tel" />
                    {fieldErrors.mobile && <span id="mobile-error" className="mt-1 block text-xs text-red-600">{fieldErrors.mobile}</span>}
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">工作邮箱</span>
                    <input name="email" value={form.email} onChange={updateText} maxLength={255} inputMode="email" aria-invalid={Boolean(fieldErrors.email)} aria-describedby={fieldErrors.email ? 'email-error' : undefined} className={`h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2 ${fieldErrors.email ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-500 focus:ring-blue-100'}`} autoComplete="email" />
                    {fieldErrors.email && <span id="email-error" className="mt-1 block text-xs text-red-600">{fieldErrors.email}</span>}
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">所在地区</span>
                    <input name="region" value={form.region} onChange={updateText} maxLength={80} placeholder="例如：上海市" className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" autoComplete="address-level1" />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">员工规模</span>
                    <select name="employeeScale" value={form.employeeScale} onChange={updateText} className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100">
                      <option value="">请选择</option>
                      <option value="1-49">1-49 人</option>
                      <option value="50-99">50-99 人</option>
                      <option value="100-499">100-499 人</option>
                      <option value="500-999">500-999 人</option>
                      <option value="1000-4999">1000-4999 人</option>
                      <option value="5000+">5000 人以上</option>
                    </select>
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-medium text-slate-700">期望联系时间</span>
                    <select name="preferredContactTime" value={form.preferredContactTime} onChange={updateText} className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100">
                      <option value="">请选择</option>
                      <option value="weekday_morning">工作日上午</option>
                      <option value="weekday_afternoon">工作日下午</option>
                      <option value="weekday_evening">工作日傍晚</option>
                      <option value="anytime">工作日均可</option>
                    </select>
                  </label>
                </div>

                <fieldset>
                  <legend className="text-sm font-medium text-slate-700">关注功能</legend>
                  <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {MODULE_OPTIONS.map(option => {
                      const selected = form.interestedModules.includes(option.key);
                      return (
                        <button key={option.key} type="button" aria-pressed={selected} onClick={() => toggleModule(option.key)} className={`h-10 rounded-lg border px-2 text-xs font-medium transition-colors ${selected ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600 hover:border-slate-300'}`}>
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>

                <label>
                  <span className="mb-1.5 block text-sm font-medium text-slate-700">补充需求</span>
                  <textarea name="notes" value={form.notes} onChange={updateText} maxLength={1000} rows={4} placeholder="例如：希望解决的业务问题、计划上线时间等" className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                  <span className="mt-1 block text-right text-xs text-slate-400">{form.notes.length}/1000</span>
                </label>

                <label className="flex items-start gap-3 text-sm text-slate-600">
                  <input type="checkbox" name="privacyConsent" checked={form.privacyConsent} onChange={event => { idempotencyKey.current.invalidate(); setForm(current => ({ ...current, privacyConsent: event.target.checked })); setFieldErrors({}); setError(''); }} aria-invalid={Boolean(fieldErrors.privacyConsent)} aria-describedby={fieldErrors.privacyConsent ? 'privacyConsent-error' : undefined} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600" />
                  <span>
                    我已阅读并同意
                    <a href="/legal/privacy" target="_blank" rel="noreferrer" className="mx-1 text-blue-600 hover:text-blue-700">《隐私政策》</a>
                    ，同意恒聘通为本次企业服务联系处理上述信息。
                    {fieldErrors.privacyConsent && <span id="privacyConsent-error" className="mt-1 block text-xs text-red-600">{fieldErrors.privacyConsent}</span>}
                  </span>
                </label>

                <label className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">
                  网址
                  <input name="website" value={form.website} onChange={updateText} tabIndex={-1} autoComplete="off" />
                </label>

                <button type="submit" disabled={submitting} className="flex h-11 w-full items-center justify-center rounded-lg bg-blue-600 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300">
                  {submitting ? <><AppIcon className="fas fa-spinner fa-spin mr-2" />正在提交</> : '提交申请'}
                </button>
                </fieldset>
              </form>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
