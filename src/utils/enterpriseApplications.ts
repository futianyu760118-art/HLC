export type RequestTicket = Readonly<{ sequence: number; target: string }>;

export class LatestRequestGate {
  private sequence = 0;

  begin(target: string): RequestTicket {
    return { sequence: ++this.sequence, target };
  }

  isCurrent(ticket: RequestTicket, target: string): boolean {
    return ticket.sequence === this.sequence && ticket.target === target;
  }

  invalidate(): void {
    this.sequence += 1;
  }
}

export class SubmissionIdempotencyKey {
  private value: string | null = null;

  getOrCreate(factory: () => string): string {
    if (!this.value) this.value = factory();
    return this.value;
  }

  invalidate(): void {
    this.value = null;
  }
}

const pad = (value: number): string => String(value).padStart(2, '0');

export function utcIsoToLocalInput(
  value?: string | null,
  timezoneOffsetMinutes?: number,
): string {
  if (!value) return '';
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return '';
  if (timezoneOffsetMinutes !== undefined) {
    const local = new Date(instant.getTime() - timezoneOffsetMinutes * 60_000);
    return `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}`
      + `T${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`;
  }
  return `${instant.getFullYear()}-${pad(instant.getMonth() + 1)}-${pad(instant.getDate())}`
    + `T${pad(instant.getHours())}:${pad(instant.getMinutes())}`;
}

export function localInputToUtcIso(
  value?: string | null,
  timezoneOffsetMinutes?: number,
): string | null {
  if (!value) return null;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number);
  const instant = timezoneOffsetMinutes === undefined
    ? new Date(year, month - 1, day, hour, minute)
    : new Date(Date.UTC(year, month - 1, day, hour, minute) + timezoneOffsetMinutes * 60_000);
  return Number.isNaN(instant.getTime()) ? null : instant.toISOString();
}

const LIST_KEYS = [
  'id',
  'applicationNo',
  'companyName',
  'region',
  'employeeScale',
  'status',
  'ownerUserId',
  'ownerName',
  'convertedTenantId',
  'convertedTenantName',
  'source',
  'version',
  'createdAt',
  'updatedAt',
] as const;

export function normalizeEnterpriseApplicationListItem(
  value: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of LIST_KEYS) {
    if (Object.hasOwn(value, key)) result[key] = value[key];
  }
  return result;
}

type ConfirmOptions = {
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  danger: boolean;
  icon: string;
};

export async function runConfirmedEnterpriseConversion<T>({
  applicationCompany,
  targetTenantName,
  confirm,
  convert,
}: {
  applicationCompany: string;
  targetTenantName: string;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  convert: () => Promise<T>;
}): Promise<T | undefined> {
  const approved = await confirm({
    title: '确认关联企业客户？',
    message: `申请企业：${applicationCompany}\n目标企业：${targetTenantName}\n关联后申请将进入“已转企业”终态，不能再修改状态。该操作不会自动开通账号、订阅或发送消息。`,
    confirmText: '确认关联并进入终态',
    cancelText: '取消',
    danger: true,
    icon: 'fa-link',
  });
  if (!approved) return undefined;
  return convert();
}
