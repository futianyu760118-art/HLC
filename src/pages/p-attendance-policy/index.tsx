// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Page loads are intentionally scoped to the active policy view. */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { EmptyState, PageHeader, StatPill } from '../../components/PageParts';
import AppIcon from '../../components/AppIcon';
import confirm from '../../components/ConfirmDialog';
import toast from '../../utils/toast';
import { authUtils } from '../../utils/auth';
import { hrmApi } from '../../utils/api';

const TABS = [
  { key: 'shifts', label: '班次', icon: 'fa-clock' },
  { key: 'rule-sets', label: '规则', icon: 'fa-sliders' },
  { key: 'groups', label: '考勤组', icon: 'fa-users' },
  { key: 'memberships', label: '成员范围', icon: 'fa-user-check' },
  { key: 'holidays', label: '节假日', icon: 'fa-calendar-day' },
  { key: 'schedules', label: '日排班', icon: 'fa-calendar-week' },
  { key: 'daily-results', label: '考勤日报', icon: 'fa-list-check' },
];

const STATUS_LABELS = {
  active: '启用',
  inactive: '停用',
  normal: '正常',
  late: '迟到',
  early_leave: '早退',
  late_early_leave: '迟到+早退',
  missing_card: '缺卡',
  absent: '旷工',
  pending: '待打卡',
  leave: '请假覆盖',
  travel: '出差覆盖',
  out_of_office: '外出覆盖',
  makeup_card: '补卡覆盖',
  partial_coverage: '部分覆盖',
  short_hours: '工时不足',
  rest: '休息日',
  holiday: '节假日',
  unscheduled: '未排班',
};

const DAY_TYPE_LABELS = {
  workday: '工作日',
  rest: '休息日',
  holiday: '节假日',
  working_day: '调休工作日',
  company_rest: '企业休息日',
};

const SHIFT_TYPE_LABELS = { fixed: '固定班', flexible: '弹性班' };
const SCOPE_LABELS = { employee: '指定员工', department: '部门', position: '岗位' };
const inputClass = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100';
const buttonClass = 'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors';

const today = () => new Date().toISOString().slice(0, 10);

const initialForm = (kind, snapshot, employees) => {
  const firstGroup = snapshot.groups?.[0]?.id || '';
  const firstShift = snapshot.shifts?.[0]?.id || '';
  const firstRule = snapshot.ruleSets?.[0]?.id || '';
  const firstEmployee = employees?.[0]?.id || '';
  if (kind === 'shifts') return { code: '', name: '', shiftType: 'fixed', startTime: '09:00', endTime: '18:00', crossDay: false, requiredWorkHours: '8', lateGraceMinutes: 0, earlyLeaveGraceMinutes: 0, requireCheckIn: true, requireCheckOut: true, status: 'active', remark: '' };
  if (kind === 'rule-sets') return { code: '', name: '', version: 1, effectiveFrom: '', effectiveTo: '', status: 'active', absentIfNoPunch: true, missingCardIfSinglePunch: true, lateGraceMinutes: '', earlyLeaveGraceMinutes: '', remark: '' };
  if (kind === 'groups') return { code: '', name: '', defaultShiftId: firstShift, defaultRuleSetId: firstRule, priority: 0, effectiveFrom: '', effectiveTo: '', status: 'active', remark: '' };
  if (kind === 'memberships') return { groupId: firstGroup, scopeType: 'employee', employeeId: firstEmployee, departmentId: '', positionId: '', priority: 0, effectiveFrom: '', effectiveTo: '', status: 'active', remark: '' };
  if (kind === 'holidays') return { holidayDate: today(), name: '', dayType: 'holiday', status: 'active', remark: '' };
  if (kind === 'schedules') return { employeeId: firstEmployee, scheduleDate: today(), dayType: 'workday', shiftId: firstShift, source: 'manual', remark: '' };
  return {};
};

const formatDateTime = (value) => value ? String(value).replace('T', ' ').slice(0, 16) : '-';
const formatDate = (value) => value ? String(value).slice(0, 10) : '-';
const statusTone = (status) => {
  if (['normal', 'active', 'leave', 'travel', 'out_of_office', 'makeup_card', 'rest', 'holiday'].includes(status)) return 'bg-emerald-50 text-emerald-700';
  if (['late', 'early_leave', 'late_early_leave', 'partial_coverage', 'short_hours', 'pending'].includes(status)) return 'bg-amber-50 text-amber-700';
  if (['absent', 'missing_card', 'inactive'].includes(status)) return 'bg-red-50 text-red-700';
  return 'bg-gray-100 text-gray-600';
};

function StatusTag({ status }) {
  return <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${statusTone(status)}`}>{STATUS_LABELS[status] || status || '-'}</span>;
}

function Field({ label, children, hint }) {
  return <label className="block space-y-1"><span className="block text-xs font-medium text-gray-600">{label}</span>{children}{hint && <span className="block text-[11px] text-gray-400">{hint}</span>}</label>;
}

function Toggle({ label, checked, onChange }) {
  return <label className="flex items-center gap-2 text-sm text-gray-600"><input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 rounded border-gray-300 text-blue-600" />{label}</label>;
}

export default function AttendancePolicyPage() {
  const navigate = useNavigate();
  const user = authUtils.getUser();
  const allowed = ['admin', 'hr_admin'].includes(user?.role || '');
  const [activeTab, setActiveTab] = useState('shifts');
  const [snapshot, setSnapshot] = useState({ shifts: [], ruleSets: [], groups: [], memberships: [], holidays: [], schedules: [] });
  const [employees, setEmployees] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [positions, setPositions] = useState([]);
  const [dailyResults, setDailyResults] = useState([]);
  const [dailyFilters, setDailyFilters] = useState({ startDate: today(), endDate: today(), employeeId: '', status: '' });
  const [loading, setLoading] = useState(true);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = async () => {
    if (!allowed) { setLoading(false); return; }
    setLoading(true);
    setError('');
    try {
      const [nextSnapshot, employeeRows, departmentRows, positionRows] = await Promise.all([
        hrmApi.attendancePolicySnapshot(),
        hrmApi.list('employees'),
        hrmApi.list('departments'),
        hrmApi.list('positions'),
      ]);
      setSnapshot(nextSnapshot || { shifts: [], ruleSets: [], groups: [], memberships: [], holidays: [], schedules: [] });
      setEmployees(employeeRows || []);
      setDepartments(departmentRows || []);
      setPositions(positionRows || []);
    } catch (err) {
      setError(err?.message || '加载考勤制度失败');
    } finally {
      setLoading(false);
    }
  };

  const loadResults = async () => {
    if (!allowed) return;
    setResultsLoading(true);
    try {
      const rows = await hrmApi.listAttendanceDailyResults(dailyFilters);
      setDailyResults(rows || []);
    } catch (err) {
      setError(err?.message || '加载考勤日报失败');
    } finally {
      setResultsLoading(false);
    }
  };

  useEffect(() => {
    document.title = '考勤制度 - 恒聘通HRM';
    void load();
  }, [allowed]);

  useEffect(() => {
    if (activeTab === 'daily-results') void loadResults();
  }, [activeTab]);

  const openCreate = (kind = activeTab) => {
    setDetail(null);
    setModal({ kind, row: null, form: initialForm(kind, snapshot, employees) });
  };

  const openEdit = (kind, row) => {
    const form = { ...row };
    if (kind === 'memberships') form.scopeType = row.scopeType || (row.employeeId ? 'employee' : row.departmentId ? 'department' : 'position');
    setDetail(null);
    setModal({ kind, row, form });
  };

  const updateForm = (key, value) => setModal((current) => ({ ...current, form: { ...current.form, [key]: value } }));

  const saveForm = async () => {
    if (!modal) return;
    setSaving(true);
    setError('');
    try {
      const kind = modal.kind;
      const payload = { ...modal.form };
      delete payload.id;
      delete payload.tenantId;
      delete payload.createdAt;
      delete payload.updatedAt;
      delete payload.groupName;
      delete payload.employeeName;
      delete payload.departmentName;
      delete payload.positionTitle;
      delete payload.scopeName;
      delete payload.shiftName;
      if (kind === 'memberships') {
        payload.employeeId = payload.scopeType === 'employee' ? payload.employeeId : '';
        payload.departmentId = payload.scopeType === 'department' ? payload.departmentId : '';
        payload.positionId = payload.scopeType === 'position' ? payload.positionId : '';
        delete payload.scopeType;
      }
      if (kind === 'schedules' && payload.dayType !== 'workday') payload.shiftId = '';
      if (modal.row) await hrmApi.updateAttendancePolicyRow(kind, modal.row.id, payload);
      else await hrmApi.createAttendancePolicyRow(kind, payload);
      toast.success(modal.row ? '已更新' : '已创建');
      setModal(null);
      await load();
      if (activeTab === 'daily-results') await loadResults();
    } catch (err) {
      toast.error(err?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const removeRow = async (kind, row) => {
    if (!await confirm({ title: '确认删除', message: `确定删除「${row.name || row.code || row.employeeName || row.holidayDate || '这条记录'}」？`, confirmText: '删除', danger: true })) return;
    try {
      await hrmApi.deleteAttendancePolicyRow(kind, row.id);
      toast.success('已删除');
      await load();
    } catch (err) {
      toast.error(err?.message || '删除失败');
    }
  };

  const recalculate = async () => {
    if (!dailyFilters.startDate || !dailyFilters.endDate) {
      toast.error('请选择重算日期范围');
      return;
    }
    setRecalculating(true);
    try {
      const result = await hrmApi.recalculateAttendanceDailyResults({
        startDate: dailyFilters.startDate,
        endDate: dailyFilters.endDate,
        employeeId: dailyFilters.employeeId || undefined,
      });
      toast.success(`重算完成：新增 ${result.created || 0}，更新 ${result.updated || 0}`);
      await loadResults();
    } catch (err) {
      toast.error(err?.message || '重算失败');
    } finally {
      setRecalculating(false);
    }
  };

  const activeCount = (key) => (snapshot[key] || []).filter((row) => row.status === 'active').length;
  const employeeOptions = employees.map((row) => ({ value: row.id, label: `${row.name}${row.employeeNo ? ` / ${row.employeeNo}` : ''}` }));

  if (loading) return <Layout><div className="flex justify-center py-24 text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-2xl" /></div></Layout>;
  if (!allowed) return <Layout><div className="mx-auto max-w-3xl px-6 py-12"><EmptyState icon="fa-lock" title="没有考勤制度权限" hint="请联系系统管理员或 HR 管理员。" /></div></Layout>;

  return (
    <Layout>
      <div className="mx-auto max-w-7xl space-y-5 px-4 py-5 md:px-6">
        <PageHeader
          icon="fa-calendar-check"
          title="考勤制度"
          subtitle="维护班次、规则和排班，并生成可追溯的每日结果"
          actions={<div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => navigate('/attendance-sync')} className={`${buttonClass} border border-gray-200 text-gray-600 hover:border-blue-200 hover:text-blue-600`}><AppIcon className="fas fa-sync text-xs" />考勤机同步</button>
            <button type="button" onClick={() => navigate('/hrm/attendance-records')} className={`${buttonClass} border border-gray-200 text-gray-600 hover:border-blue-200 hover:text-blue-600`}><AppIcon className="fas fa-clock text-xs" />原始考勤记录</button>
          </div>}
        />

        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <StatPill label="启用班次" value={activeCount('shifts')} icon="fa-clock" />
          <StatPill label="启用规则" value={activeCount('ruleSets')} icon="fa-sliders" tone="success" />
          <StatPill label="启用考勤组" value={activeCount('groups')} icon="fa-users" tone="warning" />
          <StatPill label="成员范围" value={snapshot.memberships.length} icon="fa-user-check" tone="neutral" />
          <StatPill label="节假日配置" value={snapshot.holidays.length} icon="fa-calendar-day" tone="neutral" />
          <StatPill label="日排班" value={snapshot.schedules.length} icon="fa-calendar-week" tone="neutral" />
          <StatPill label="日报结果" value={dailyResults.length} icon="fa-list-check" tone="primary" />
        </div>

        <div className="overflow-x-auto border-b border-gray-200">
          <div className="flex min-w-max gap-1">
            {TABS.map((tab) => (
              <button key={tab.key} type="button" onClick={() => setActiveTab(tab.key)} className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm ${activeTab === tab.key ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-800'}`}>
                <AppIcon className={`fas ${tab.icon} text-xs`} />{tab.label}{tab.key !== 'daily-results' && <span className="text-xs text-gray-400">{snapshot[tab.key === 'rule-sets' ? 'ruleSets' : tab.key]?.length || 0}</span>}
              </button>
            ))}
          </div>
        </div>

        {activeTab === 'daily-results' ? (
          <DailyResultsView
            results={dailyResults}
            filters={dailyFilters}
            setFilters={setDailyFilters}
            employees={employeeOptions}
            loading={resultsLoading}
            recalculating={recalculating}
            onSearch={() => void loadResults()}
            onRecalculate={() => void recalculate()}
            onDetail={setDetail}
          />
        ) : (
          <PolicyTable
            kind={activeTab}
            rows={snapshot[activeTab === 'rule-sets' ? 'ruleSets' : activeTab] || []}
            onCreate={() => openCreate(activeTab)}
            onEdit={openEdit}
            onDelete={removeRow}
            onDetail={setDetail}
          />
        )}

        {modal && <PolicyModal
          modal={modal}
          snapshot={snapshot}
          employees={employees}
          departments={departments}
          positions={positions}
          saving={saving}
          updateForm={updateForm}
          onCancel={() => setModal(null)}
          onSave={() => void saveForm()}
        />}
        {detail && <DetailModal result={detail} onClose={() => setDetail(null)} />}
      </div>
    </Layout>
  );
}

function PolicyTable({ kind, rows, onCreate, onEdit, onDelete, onDetail }) {
  const titles = { shifts: '班次设置', 'rule-sets': '考勤规则', groups: '考勤组', memberships: '成员范围', holidays: '节假日与调休', schedules: '员工日排班' };
  const canCreate = kind !== 'daily-results';
  return <section className="overflow-hidden rounded-xl border border-gray-200 bg-white">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
      <div><h2 className="text-sm font-semibold text-gray-800">{titles[kind]}</h2><p className="mt-0.5 text-xs text-gray-400">共 {rows.length} 条</p></div>
      {canCreate && <button type="button" onClick={onCreate} className={`${buttonClass} bg-blue-600 text-white hover:bg-blue-700`}><AppIcon className="fas fa-plus text-xs" />新增</button>}
    </div>
    {rows.length === 0 ? <EmptyState icon="fa-calendar-plus" title="暂无配置" hint="点击右上角新增一条制度配置。" /> : <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-500"><tr>{headers(kind).map((header) => <th key={header} className="whitespace-nowrap px-3 py-2 font-medium">{header}</th>)}<th className="px-3 py-2 font-medium">操作</th></tr></thead><tbody>{rows.map((row) => <PolicyRow key={row.id} kind={kind} row={row} onEdit={onEdit} onDelete={onDelete} onDetail={onDetail} />)}</tbody></table></div>}
  </section>;
}

function headers(kind) {
  return {
    shifts: ['编码', '名称', '类型', '时间/应出勤', '宽限', '状态'],
    'rule-sets': ['编码', '名称', '版本', '生效范围', '缺卡判定', '状态'],
    groups: ['编码', '名称', '默认班次', '默认规则', '优先级', '状态'],
    memberships: ['考勤组', '范围', '对象', '生效范围', '优先级', '状态'],
    holidays: ['日期', '名称', '日期类型', '备注', '状态'],
    schedules: ['日期', '员工', '日期类型', '班次', '来源', '备注'],
  }[kind];
}

function PolicyRow({ kind, row, onEdit, onDelete, onDetail }) {
  const actions = <td className="whitespace-nowrap px-3 py-2"><div className="flex items-center gap-2"><button type="button" title="查看" onClick={() => onDetail(row)} className="text-gray-400 hover:text-blue-600"><AppIcon className="fas fa-eye text-xs" /></button><button type="button" title="编辑" onClick={() => onEdit(kind, row)} className="text-blue-600 hover:text-blue-800"><AppIcon className="fas fa-pen text-xs" /></button><button type="button" title="删除" onClick={() => void onDelete(kind, row)} className="text-gray-400 hover:text-red-600"><AppIcon className="fas fa-trash text-xs" /></button></div></td>;
  if (kind === 'shifts') return <tr className="border-t border-gray-100"><td className="px-3 py-2 font-medium text-gray-800">{row.code}</td><td className="px-3 py-2">{row.name}</td><td className="px-3 py-2">{SHIFT_TYPE_LABELS[row.shiftType] || row.shiftType}</td><td className="px-3 py-2 text-gray-600">{row.shiftType === 'fixed' ? `${row.startTime || '-'} - ${row.endTime || '-'}${row.crossDay ? '（跨日）' : ''}` : `${row.requiredWorkHours || '-'} 小时`}</td><td className="px-3 py-2 text-gray-600">迟到 {row.lateGraceMinutes || 0} 分 / 早退 {row.earlyLeaveGraceMinutes || 0} 分</td><td className="px-3 py-2"><StatusTag status={row.status} /></td>{actions}</tr>;
  if (kind === 'rule-sets') return <tr className="border-t border-gray-100"><td className="px-3 py-2 font-medium text-gray-800">{row.code}</td><td className="px-3 py-2">{row.name}</td><td className="px-3 py-2">v{row.version}</td><td className="px-3 py-2 text-gray-600">{formatDate(row.effectiveFrom)} 至 {formatDate(row.effectiveTo)}</td><td className="px-3 py-2 text-gray-600">无卡 {row.absentIfNoPunch ? '旷工' : '缺卡'} / 单卡 {row.missingCardIfSinglePunch ? '缺卡' : '按正常'}</td><td className="px-3 py-2"><StatusTag status={row.status} /></td>{actions}</tr>;
  if (kind === 'groups') return <tr className="border-t border-gray-100"><td className="px-3 py-2 font-medium text-gray-800">{row.code}</td><td className="px-3 py-2">{row.name}</td><td className="px-3 py-2 text-gray-600">{row.defaultShiftName || '-'}</td><td className="px-3 py-2 text-gray-600">{row.defaultRuleSetName || '-'}</td><td className="px-3 py-2">{row.priority || 0}</td><td className="px-3 py-2"><StatusTag status={row.status} /></td>{actions}</tr>;
  if (kind === 'memberships') return <tr className="border-t border-gray-100"><td className="px-3 py-2">{row.groupName || '-'}</td><td className="px-3 py-2">{SCOPE_LABELS[row.scopeType] || row.scopeType || '-'}</td><td className="px-3 py-2 text-gray-600">{row.scopeName || '-'}</td><td className="px-3 py-2 text-gray-600">{formatDate(row.effectiveFrom)} 至 {formatDate(row.effectiveTo)}</td><td className="px-3 py-2">{row.priority || 0}</td><td className="px-3 py-2"><StatusTag status={row.status} /></td>{actions}</tr>;
  if (kind === 'holidays') return <tr className="border-t border-gray-100"><td className="px-3 py-2">{formatDate(row.holidayDate)}</td><td className="px-3 py-2 font-medium text-gray-800">{row.name}</td><td className="px-3 py-2">{DAY_TYPE_LABELS[row.dayType] || row.dayType}</td><td className="max-w-[260px] truncate px-3 py-2 text-gray-600">{row.remark || '-'}</td><td className="px-3 py-2"><StatusTag status={row.status} /></td>{actions}</tr>;
  return <tr className="border-t border-gray-100"><td className="px-3 py-2">{formatDate(row.scheduleDate)}</td><td className="px-3 py-2 font-medium text-gray-800">{row.employeeName || '-'}</td><td className="px-3 py-2">{DAY_TYPE_LABELS[row.dayType] || row.dayType}</td><td className="px-3 py-2 text-gray-600">{row.shiftName || '-'}</td><td className="px-3 py-2 text-gray-600">{row.source || '-'}</td><td className="max-w-[220px] truncate px-3 py-2 text-gray-600">{row.remark || '-'}</td>{actions}</tr>;
}

function DailyResultsView({ results, filters, setFilters, employees, loading, recalculating, onSearch, onRecalculate, onDetail }) {
  const update = (key, value) => setFilters((current) => ({ ...current, [key]: value }));
  return <section className="overflow-hidden rounded-xl border border-gray-200 bg-white">
    <div className="border-b border-gray-100 px-4 py-3"><div className="flex flex-wrap items-end gap-2"><Field label="开始日期"><input type="date" value={filters.startDate} onChange={(event) => update('startDate', event.target.value)} className={inputClass} /></Field><Field label="结束日期"><input type="date" value={filters.endDate} onChange={(event) => update('endDate', event.target.value)} className={inputClass} /></Field><Field label="员工"><select value={filters.employeeId} onChange={(event) => update('employeeId', event.target.value)} className={inputClass}><option value="">全部员工</option>{employees.map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}</select></Field><Field label="状态"><select value={filters.status} onChange={(event) => update('status', event.target.value)} className={inputClass}><option value="">全部状态</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field><button type="button" onClick={onSearch} className={`${buttonClass} border border-gray-200 text-gray-600 hover:border-blue-200 hover:text-blue-600`}><AppIcon className="fas fa-search text-xs" />查询</button><button type="button" onClick={onRecalculate} disabled={recalculating} className={`${buttonClass} bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50`}><AppIcon className={`fas ${recalculating ? 'fa-spinner fa-spin' : 'fa-rotate' } text-xs`} />{recalculating ? '重算中' : '局部重算'}</button></div><p className="mt-2 text-xs text-gray-400">重算只写入独立日报表，不改现有考勤记录和月度统计口径。</p></div>
    {loading ? <div className="py-16 text-center text-gray-400"><AppIcon className="fas fa-spinner fa-spin text-xl" /></div> : results.length === 0 ? <EmptyState icon="fa-list-check" title="暂无日报结果" hint="先选择日期范围并执行局部重算。" /> : <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-500"><tr>{['日期', '员工', '考勤组/班次', '计划时间', '打卡', '工时', '状态', '操作'].map((header) => <th key={header} className="whitespace-nowrap px-3 py-2 font-medium">{header}</th>)}</tr></thead><tbody>{results.map((row) => <tr key={row.id} className="border-t border-gray-100"><td className="px-3 py-2">{formatDate(row.attendanceDate)}</td><td className="px-3 py-2 font-medium text-gray-800">{row.employeeName || '-'}</td><td className="px-3 py-2 text-gray-600">{row.groupName || '-'}{row.shiftName ? ` / ${row.shiftName}` : ''}</td><td className="px-3 py-2 text-gray-600">{formatDateTime(row.scheduledStart)}<br />{formatDateTime(row.scheduledEnd)}</td><td className="px-3 py-2 text-gray-600">{formatDateTime(row.checkInTime)}<br />{formatDateTime(row.checkOutTime)}</td><td className="px-3 py-2">{row.workHours == null ? '-' : `${row.workHours}h`}</td><td className="px-3 py-2"><StatusTag status={row.status} />{(row.lateMinutes || row.earlyLeaveMinutes) > 0 && <div className="mt-1 text-[11px] text-gray-400">迟 {row.lateMinutes || 0} / 早 {row.earlyLeaveMinutes || 0} 分</div>}</td><td className="px-3 py-2"><button type="button" onClick={() => onDetail(row)} className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"><AppIcon className="fas fa-eye text-[11px]" />查看原因</button></td></tr>)}</tbody></table></div>}
  </section>;
}

function PolicyModal({ modal, snapshot, employees, departments, positions, saving, updateForm, onCancel, onSave }) {
  const { kind, row, form } = modal;
  const titles = { shifts: '班次', 'rule-sets': '考勤规则', groups: '考勤组', memberships: '成员范围', holidays: '节假日', schedules: '日排班' };
  const select = (key, options, placeholder = '请选择') => <select value={form[key] || ''} onChange={(event) => updateForm(key, event.target.value)} className={inputClass}><option value="">{placeholder}</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onCancel}><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between border-b border-gray-100 px-5 py-4"><h2 className="text-base font-semibold text-gray-800">{row ? '编辑' : '新增'}{titles[kind]}</h2><button type="button" onClick={onCancel} className="text-gray-400 hover:text-gray-700"><AppIcon className="fas fa-times" /></button></div><div className="grid gap-4 px-5 py-5 md:grid-cols-2">
    {kind === 'shifts' && <><Field label="班次编码"><input value={form.code || ''} onChange={(event) => updateForm('code', event.target.value)} className={inputClass} /></Field><Field label="班次名称"><input value={form.name || ''} onChange={(event) => updateForm('name', event.target.value)} className={inputClass} /></Field><Field label="班次类型">{select('shiftType', [{ value: 'fixed', label: '固定班' }, { value: 'flexible', label: '弹性班' }])}</Field>{form.shiftType === 'fixed' ? <><Field label="上班时间"><input type="time" value={form.startTime || ''} onChange={(event) => updateForm('startTime', event.target.value)} className={inputClass} /></Field><Field label="下班时间"><input type="time" value={form.endTime || ''} onChange={(event) => updateForm('endTime', event.target.value)} className={inputClass} /></Field><div className="flex items-end pb-2"><Toggle label="跨日班次" checked={form.crossDay} onChange={(value) => updateForm('crossDay', value)} /></div></> : <Field label="应出勤小时"><input type="number" min="0.01" step="0.01" value={form.requiredWorkHours || ''} onChange={(event) => updateForm('requiredWorkHours', event.target.value)} className={inputClass} /></Field>}<Field label="允许迟到分钟"><input type="number" min="0" value={form.lateGraceMinutes ?? 0} onChange={(event) => updateForm('lateGraceMinutes', event.target.value)} className={inputClass} /></Field><Field label="允许早退分钟"><input type="number" min="0" value={form.earlyLeaveGraceMinutes ?? 0} onChange={(event) => updateForm('earlyLeaveGraceMinutes', event.target.value)} className={inputClass} /></Field><div className="flex items-end gap-4 pb-2"><Toggle label="必须上班打卡" checked={form.requireCheckIn} onChange={(value) => updateForm('requireCheckIn', value)} /><Toggle label="必须下班打卡" checked={form.requireCheckOut} onChange={(value) => updateForm('requireCheckOut', value)} /></div><Field label="状态">{select('status', [{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }])}</Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
    {kind === 'rule-sets' && <><Field label="规则编码"><input value={form.code || ''} onChange={(event) => updateForm('code', event.target.value)} className={inputClass} /></Field><Field label="规则名称"><input value={form.name || ''} onChange={(event) => updateForm('name', event.target.value)} className={inputClass} /></Field><Field label="版本"><input type="number" min="1" value={form.version ?? 1} onChange={(event) => updateForm('version', event.target.value)} className={inputClass} /></Field><Field label="生效开始"><input type="date" value={form.effectiveFrom || ''} onChange={(event) => updateForm('effectiveFrom', event.target.value)} className={inputClass} /></Field><Field label="生效结束"><input type="date" value={form.effectiveTo || ''} onChange={(event) => updateForm('effectiveTo', event.target.value)} className={inputClass} /></Field><Field label="规则允许迟到分钟"><input type="number" min="0" value={form.lateGraceMinutes ?? ''} onChange={(event) => updateForm('lateGraceMinutes', event.target.value)} className={inputClass} /></Field><Field label="规则允许早退分钟"><input type="number" min="0" value={form.earlyLeaveGraceMinutes ?? ''} onChange={(event) => updateForm('earlyLeaveGraceMinutes', event.target.value)} className={inputClass} /></Field><div className="flex flex-wrap items-end gap-4 pb-2"><Toggle label="无打卡判旷工" checked={form.absentIfNoPunch} onChange={(value) => updateForm('absentIfNoPunch', value)} /><Toggle label="单次打卡判缺卡" checked={form.missingCardIfSinglePunch} onChange={(value) => updateForm('missingCardIfSinglePunch', value)} /></div><Field label="状态">{select('status', [{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }])}</Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
    {kind === 'groups' && <><Field label="考勤组编码"><input value={form.code || ''} onChange={(event) => updateForm('code', event.target.value)} className={inputClass} /></Field><Field label="考勤组名称"><input value={form.name || ''} onChange={(event) => updateForm('name', event.target.value)} className={inputClass} /></Field><Field label="默认班次">{select('defaultShiftId', snapshot.shifts.map((item) => ({ value: item.id, label: `${item.name} / ${item.code}` })), '不设置')}</Field><Field label="默认规则">{select('defaultRuleSetId', snapshot.ruleSets.map((item) => ({ value: item.id, label: `${item.name} / v${item.version}` })), '不设置')}</Field><Field label="优先级"><input type="number" value={form.priority ?? 0} onChange={(event) => updateForm('priority', event.target.value)} className={inputClass} /></Field><Field label="生效开始"><input type="date" value={form.effectiveFrom || ''} onChange={(event) => updateForm('effectiveFrom', event.target.value)} className={inputClass} /></Field><Field label="生效结束"><input type="date" value={form.effectiveTo || ''} onChange={(event) => updateForm('effectiveTo', event.target.value)} className={inputClass} /></Field><Field label="状态">{select('status', [{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }])}</Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
    {kind === 'memberships' && <><Field label="考勤组">{select('groupId', snapshot.groups.map((item) => ({ value: item.id, label: `${item.name} / ${item.code}` })))}</Field><Field label="成员范围">{select('scopeType', Object.entries(SCOPE_LABELS).map(([value, label]) => ({ value, label })))}</Field>{form.scopeType === 'employee' && <Field label="员工">{select('employeeId', employees.map((item) => ({ value: item.id, label: `${item.name}${item.employeeNo ? ` / ${item.employeeNo}` : ''}` })))}</Field>}{form.scopeType === 'department' && <Field label="部门">{select('departmentId', departments.map((item) => ({ value: item.id, label: item.name })))}</Field>}{form.scopeType === 'position' && <Field label="岗位">{select('positionId', positions.map((item) => ({ value: item.id, label: item.title })))}</Field>}<Field label="优先级"><input type="number" value={form.priority ?? 0} onChange={(event) => updateForm('priority', event.target.value)} className={inputClass} /></Field><Field label="生效开始"><input type="date" value={form.effectiveFrom || ''} onChange={(event) => updateForm('effectiveFrom', event.target.value)} className={inputClass} /></Field><Field label="生效结束"><input type="date" value={form.effectiveTo || ''} onChange={(event) => updateForm('effectiveTo', event.target.value)} className={inputClass} /></Field><Field label="状态">{select('status', [{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }])}</Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
    {kind === 'holidays' && <><Field label="日期"><input type="date" value={form.holidayDate || ''} onChange={(event) => updateForm('holidayDate', event.target.value)} className={inputClass} /></Field><Field label="名称"><input value={form.name || ''} onChange={(event) => updateForm('name', event.target.value)} className={inputClass} /></Field><Field label="日期类型">{select('dayType', [{ value: 'holiday', label: '法定节假日' }, { value: 'working_day', label: '调休工作日' }, { value: 'company_rest', label: '企业休息日' }])}</Field><Field label="状态">{select('status', [{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }])}</Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
    {kind === 'schedules' && <><Field label="员工">{select('employeeId', employees.map((item) => ({ value: item.id, label: `${item.name}${item.employeeNo ? ` / ${item.employeeNo}` : ''}` })))}</Field><Field label="排班日期"><input type="date" value={form.scheduleDate || ''} onChange={(event) => updateForm('scheduleDate', event.target.value)} className={inputClass} /></Field><Field label="日期类型">{select('dayType', [{ value: 'workday', label: '工作日' }, { value: 'rest', label: '休息日' }, { value: 'holiday', label: '节假日' }])}</Field>{form.dayType === 'workday' && <Field label="班次">{select('shiftId', snapshot.shifts.filter((item) => item.status === 'active').map((item) => ({ value: item.id, label: `${item.name} / ${item.code}` })))}</Field>}<Field label="来源"><input value={form.source || 'manual'} onChange={(event) => updateForm('source', event.target.value)} className={inputClass} /></Field><Field label="备注"><input value={form.remark || ''} onChange={(event) => updateForm('remark', event.target.value)} className={inputClass} /></Field></>}
  </div><div className="flex justify-end gap-2 border-t border-gray-100 bg-gray-50 px-5 py-3"><button type="button" onClick={onCancel} className={`${buttonClass} border border-gray-200 bg-white text-gray-600`}>取消</button><button type="button" onClick={onSave} disabled={saving} className={`${buttonClass} bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50`}><AppIcon className={`fas ${saving ? 'fa-spinner fa-spin' : 'fa-check'} text-xs`} />{saving ? '保存中' : '保存'}</button></div></div></div>;
}

function DetailModal({ result, onClose }) {
  const explanation = result.explanation || {};
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}><div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between border-b border-gray-100 px-5 py-4"><div><h2 className="text-base font-semibold text-gray-800">{result.attendanceDate ? `${result.attendanceDate} · ${result.employeeName || '考勤日报'}` : result.name || '制度配置详情'}</h2><p className="mt-1 text-xs text-gray-400">记录依据与计算解释</p></div><button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700"><AppIcon className="fas fa-times" /></button></div><div className="space-y-4 px-5 py-5">{result.status && <div><div className="mb-1 text-xs text-gray-500">结果状态</div><StatusTag status={result.status} /></div>}<div><div className="mb-1 text-xs text-gray-500">解释</div><div className="rounded-lg bg-gray-50 px-3 py-3 text-sm leading-6 text-gray-700">{explanation.reason || '该记录没有额外解释。'}</div></div><div className="grid gap-3 text-sm md:grid-cols-2"><Info label="日期类型" value={DAY_TYPE_LABELS[result.dayType] || result.dayType} /><Info label="排班来源" value={result.scheduleSource || result.source || '-'} /><Info label="考勤组" value={result.groupName || '-'} /><Info label="班次" value={result.shiftName || '-'} /><Info label="规则" value={result.ruleSetName || '-'} /><Info label="打卡数" value={result.explanation?.punchCount ?? result.sourcePunchIds?.length ?? '-'} /><Info label="关联申请" value={result.requestIds?.length ? result.requestIds.join(', ') : '-'} /><Info label="计算版本" value={result.calculationVersion || '-'} /></div><details className="rounded-lg border border-gray-200"><summary className="cursor-pointer px-3 py-2 text-xs text-gray-500">查看结构化依据</summary><pre className="overflow-x-auto border-t border-gray-100 bg-gray-50 p-3 text-xs text-gray-600">{JSON.stringify(explanation, null, 2)}</pre></details></div></div></div>;
}

function Info({ label, value }) {
  return <div className="rounded-lg border border-gray-100 px-3 py-2"><div className="text-[11px] text-gray-400">{label}</div><div className="mt-0.5 break-words text-sm text-gray-700">{value}</div></div>;
}
