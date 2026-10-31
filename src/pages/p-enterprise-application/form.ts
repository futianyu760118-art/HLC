export type EnterpriseApplicationValidationField =
  | 'companyName'
  | 'contactName'
  | 'mobile'
  | 'email'
  | 'privacyConsent';

export type EnterpriseApplicationFieldErrors = Partial<
  Record<EnterpriseApplicationValidationField, string>
>;

export function validateEnterpriseApplicationForm(form: {
  companyName: string;
  contactName: string;
  mobile: string;
  email: string;
  privacyConsent: boolean;
}): EnterpriseApplicationFieldErrors {
  const errors: EnterpriseApplicationFieldErrors = {};
  if (form.companyName.trim().length < 2) errors.companyName = '请填写完整的企业名称';
  if (!form.contactName.trim()) errors.contactName = '请填写联系人姓名';
  const mobile = form.mobile.replace(/[\s()-]/g, '').replace(/^(?:\+86|0086)/, '');
  if (!/^1[3-9]\d{9}$/.test(mobile)) errors.mobile = '请填写有效的手机号码';
  if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    errors.email = '请填写有效的邮箱地址';
  }
  if (!form.privacyConsent) errors.privacyConsent = '请阅读并同意隐私政策后提交';
  return errors;
}
