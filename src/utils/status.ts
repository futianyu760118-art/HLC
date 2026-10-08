export const STATUS_LABELS: Record<string, string> = {
  active: '启用/在职',
  inactive: '停用',
  open: '招聘中',
  closed: '已关闭',
  new: '新候选人',
  screening: '筛选中',
  interview: '面试中',
  scheduled: '已安排',
  in_progress: '进行中',
  processing: '处理中',
  offer: 'Offer中',
  offer_accepted: '已接受Offer',
  offer_rejected: '已拒绝Offer',
  converted: '已转员工',
  draft: '草稿',
  pending: '待审批',
  sent: '已发送',
  accepted: '已接受',
  rejected: '已拒绝',
  approved: '已通过',
  cancelled: '已取消',
  canceled: '已取消',
  pending_onboard: '待入职',
  probation: '试用期',
  resigned: '已离职',
  effective: '已生效',
  planned: '计划中',
  completed: '已完成',
  published: '已发布',
  normal: '正常',
  late: '迟到',
  early_leave: '早退',
  missing_card: '缺卡',
  leave: '请假',
  overtime: '加班',
  travel: '出差',
  makeup_card: '补卡',
  registered: '已报名',
  attended: '已参加',
  unread: '未读',
  read: '已读',
  paid: '已发放',
  calculated: '已核算',
  expired: '已过期',
  terminated: '已终止',
  file_saved: '文件已保存',
  resolved: '已处理',
};

const STATUS_TONES: Record<string, 'active' | 'inactive' | 'pending' | 'default'> = {
  active: 'active',
  open: 'active',
  completed: 'active',
  published: 'active',
  approved: 'active',
  accepted: 'active',
  offer_accepted: 'active',
  converted: 'active',
  effective: 'active',
  normal: 'active',
  registered: 'active',
  attended: 'active',
  paid: 'active',
  calculated: 'active',
  resolved: 'active',

  inactive: 'inactive',
  closed: 'inactive',
  cancelled: 'inactive',
  canceled: 'inactive',
  rejected: 'inactive',
  offer_rejected: 'inactive',
  resigned: 'inactive',
  expired: 'inactive',
  terminated: 'inactive',
  late: 'inactive',
  early_leave: 'inactive',
  missing_card: 'inactive',

  draft: 'pending',
  pending: 'pending',
  in_progress: 'pending',
  processing: 'pending',
  scheduled: 'default',
  screening: 'pending',
  interview: 'pending',
  offer: 'pending',
  pending_onboard: 'pending',
  probation: 'pending',
  planned: 'pending',
  sent: 'default',
  unread: 'pending',
  file_saved: 'default',
};

const ACTIVE_TEXT = ['启用', '在职', '正常', '已通过', '已完成', '已接受', '已生效', '已发布', '已发放', '已核算', '已参加', '已处理'];
const INACTIVE_TEXT = ['停用', '已关闭', '已取消', '已撤销', '已拒绝', '已离职', '已过期', '已终止', '迟到', '早退', '缺卡'];
const PENDING_TEXT = ['待审批', '草稿', '试用期', '待入职', '计划中', '筛选中', '面试中', 'Offer中', '进行中', '处理中', '未读'];

export const getStatusLabel = (value?: unknown, fallback = '-') => {
  if (value === undefined || value === null || value === '') return fallback;
  const raw = String(value);
  return STATUS_LABELS[raw] || STATUS_LABELS[raw.toLowerCase()] || raw;
};

export const getStatusTone = (value?: unknown): 'active' | 'inactive' | 'pending' | 'default' => {
  if (value === undefined || value === null || value === '') return 'default';
  const raw = String(value);
  const lower = raw.toLowerCase();
  const label = getStatusLabel(raw, raw);

  if (STATUS_TONES[raw]) return STATUS_TONES[raw];
  if (STATUS_TONES[lower]) return STATUS_TONES[lower];
  if (ACTIVE_TEXT.some((item) => label.includes(item) || raw.includes(item))) return 'active';
  if (INACTIVE_TEXT.some((item) => label.includes(item) || raw.includes(item))) return 'inactive';
  if (PENDING_TEXT.some((item) => label.includes(item) || raw.includes(item))) return 'pending';
  return 'default';
};

export const getStatusBadgeClass = (value?: unknown) => `status-badge status-${getStatusTone(value)}`;
