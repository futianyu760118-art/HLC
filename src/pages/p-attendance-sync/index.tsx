import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { authUtils } from '../../utils/auth';
import {
  AttendanceExternalPerson,
  AttendanceSyncStatus,
  hrmApi,
} from '../../utils/api';

type MappingTab = 'suggested' | 'unmatched' | 'confirmed' | 'ignored';

const TAB_LABELS: Record<MappingTab, string> = {
  suggested: '待确认建议',
  unmatched: '未匹配',
  confirmed: '已确认',
  ignored: '已忽略',
};

interface EmployeeOption {
  id: string;
  name: string;
  employeeNo?: string | null;
  status?: string | null;
  departmentName?: string | null;
}

export default function AttendanceSyncPage() {
  const navigate = useNavigate();
  const user = authUtils.getUser();
  const allowed = user?.tenantSlug === 'HPT-00000001' && ['admin', 'hr_admin'].includes(user?.role || '');
  const [status, setStatus] = useState<AttendanceSyncStatus | null>(null);
  const [tab, setTab] = useState<MappingTab>('suggested');
  const [people, setPeople] = useState<AttendanceExternalPerson[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployee, setSelectedEmployee] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const [nextStatus, nextPeople, employeeRows] = await Promise.all([
        hrmApi.attendanceSyncStatus(),
        hrmApi.listAttendanceSyncPeople(tab),
        hrmApi.list<EmployeeOption>('employees'),
      ]);
      setStatus(nextStatus);
      setPeople(nextPeople);
      setEmployees(Array.isArray(employeeRows) ? employeeRows : []);
      const defaults: Record<string, string> = {};
      nextPeople.forEach((person) => {
        defaults[person.id] = person.employeeId || person.suggestedEmployeeId || '';
      });
      setSelectedEmployee(defaults);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载考勤机同步状态失败');
    } finally {
      setLoading(false);
    }
  }, [allowed, tab]);

  useEffect(() => {
    document.title = '考勤机同步 - 恒聘通HRM';
    void load();
  }, [load]);

  const runSync = async () => {
    setSyncing(true);
    setError('');
    try {
      await hrmApi.runAttendanceSync();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  const confirmPerson = async (person: AttendanceExternalPerson) => {
    const employeeId = selectedEmployee[person.id];
    if (!employeeId) {
      setError('请选择要绑定的员工');
      return;
    }
    setError('');
    try {
      await hrmApi.confirmAttendanceSyncPerson(person.id, employeeId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认绑定失败');
    }
  };

  const ignorePerson = async (person: AttendanceExternalPerson) => {
    setError('');
    try {
      await hrmApi.ignoreAttendanceSyncPerson(person.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '忽略失败');
    }
  };

  const latest = status?.latestRun;
  const employeeOptions = useMemo(
    () => employees.map((employee) => ({
      value: employee.id,
      label: `${employee.name}${employee.employeeNo ? ` / ${employee.employeeNo}` : ''}${employee.departmentName ? ` / ${employee.departmentName}` : ''}`,
    })),
    [employees],
  );

  return (
    <Layout>
      <div className="p-4 md:p-6 space-y-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">考勤机同步</h1>
            <p className="mt-1 text-sm text-gray-500">
              只读接入考勤机人员和打卡。同名唯一匹配会自动绑定；绑定后以考勤机数字编号作为员工工号，并生成按员工按日的考勤记录。
            </p>
          </div>
          {allowed && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => navigate('/hrm/attendance-records')}
                className="px-4 py-2 rounded-lg border border-gray-200 text-sm text-gray-700"
              >
                查看考勤记录
              </button>
              <button
                type="button"
                onClick={() => void runSync()}
                disabled={syncing || !status?.configured}
                className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:bg-gray-300"
              >
                {syncing ? '同步中…' : '立即同步'}
              </button>
            </div>
          )}
        </header>

        {!allowed && (
          <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-600">
            当前企业没有考勤机同步入口。
          </div>
        )}

        {allowed && error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        {allowed && (
          <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <Stat label="最近状态" value={latest?.status || '尚未同步'} />
            <Stat label="原始打卡" value={String(status?.punchCount ?? 0)} />
            <Stat label="已绑定" value={String(status?.people.confirmed ?? 0)} />
            <Stat label="日考勤" value={String(status?.dailyRecordCount ?? 0)} />
            <Stat label="待确认建议" value={String(status?.people.suggested ?? 0)} />
            <Stat label="未匹配" value={String(status?.people.unmatched ?? 0)} />
          </section>
        )}

        {allowed && latest && (
          <p className="text-xs text-gray-500">
            最近批次 {latest.trigger} · 人员 {latest.peopleRead} · 新增打卡 {latest.punchesInserted} · 重复 {latest.punchesDuplicate}
            {latest.completedAt ? ` · 完成于 ${latest.completedAt.replace('T', ' ').slice(0, 19)}` : ''}
            {latest.errorMessage ? ` · ${latest.errorMessage}` : ''}
          </p>
        )}

        {allowed && (
          <div className="flex flex-wrap gap-2">
            {(Object.keys(TAB_LABELS) as MappingTab[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${tab === key ? 'bg-blue-50 border-blue-300 text-blue-700' : 'border-gray-200 text-gray-600'}`}
              >
                {TAB_LABELS[key]}
                {status ? ` ${status.people[key]}` : ''}
              </button>
            ))}
          </div>
        )}

        {allowed && (
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  <th className="px-3 py-2 font-medium">考勤机人员</th>
                  <th className="px-3 py-2 font-medium">考勤工号</th>
                  <th className="px-3 py-2 font-medium">部门</th>
                  <th className="px-3 py-2 font-medium">HRM 员工</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-gray-400">加载中…</td>
                  </tr>
                )}
                {!loading && people.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-gray-400">暂无记录</td>
                  </tr>
                )}
                {!loading && people.map((person) => (
                  <tr key={person.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">{person.name || '（空姓名）'}</td>
                    <td className="px-3 py-2 text-gray-500">{person.badgeNumber || '—'}</td>
                    <td className="px-3 py-2 text-gray-500">{person.departmentName || '—'}</td>
                    <td className="px-3 py-2">
                      {tab === 'confirmed' ? (
                        <span>{person.employeeName} {person.employeeNo ? `/ ${person.employeeNo}` : ''}</span>
                      ) : (
                        <select
                          value={selectedEmployee[person.id] || ''}
                          onChange={(event) => setSelectedEmployee((current) => ({ ...current, [person.id]: event.target.value }))}
                          className="w-full min-w-[180px] rounded-md border border-gray-200 px-2 py-1"
                        >
                          <option value="">选择员工</option>
                          {employeeOptions.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-2">
                        {tab !== 'confirmed' && (
                          <button type="button" className="text-blue-600" onClick={() => void confirmPerson(person)}>确认绑定</button>
                        )}
                        {tab !== 'ignored' && tab !== 'confirmed' && (
                          <button type="button" className="text-gray-500" onClick={() => void ignorePerson(person)}>忽略</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-medium text-gray-900">{value}</div>
    </div>
  );
}
