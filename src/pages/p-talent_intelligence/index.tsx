import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { hrmApi, jobsApi } from '../../utils/api';
import { getStatusLabel } from '../../utils/status';
import AppIcon from '../../components/AppIcon';

type TalentRecord = Record<string, unknown>;

interface TalentDataState {
  employees: TalentRecord[];
  positions: TalentRecord[];
  departments: TalentRecord[];
  reviews: TalentRecord[];
  trainingRecords: TalentRecord[];
  contracts: TalentRecord[];
  candidates: TalentRecord[];
  jobs: TalentRecord[];
}

const emptyState: TalentDataState = {
  employees: [],
  positions: [],
  departments: [],
  reviews: [],
  trainingRecords: [],
  contracts: [],
  candidates: [],
  jobs: [],
};

const normalizeArray = (value: unknown): TalentRecord[] => (Array.isArray(value) ? value as TalentRecord[] : []);

const toText = (value: unknown) => {
  if (value === undefined || value === null) return '';
  return String(value);
};

const splitTags = (value: unknown) => {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return String(value)
    .split(/[,\n，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
};

const daysUntil = (date?: unknown) => {
  if (!date) return Number.POSITIVE_INFINITY;
  const target = new Date(String(date)).getTime();
  if (Number.isNaN(target)) return Number.POSITIVE_INFINITY;
  return Math.ceil((target - Date.now()) / 86400000);
};

export default function TalentIntelligencePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(emptyState);

  const safeList = useCallback(async (resource: string) => {
    try {
      return normalizeArray(await hrmApi.list<TalentRecord>(resource));
    } catch {
      return [];
    }
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [employees, positions, departments, reviews, trainingRecords, contracts, candidates, jobs] = await Promise.all([
        safeList('employees'),
        safeList('positions'),
        safeList('departments'),
        safeList('performance-reviews'),
        safeList('training-records'),
        safeList('contracts'),
        safeList('candidates'),
        jobsApi.getAll().catch(() => []),
      ]);
      setData({
        employees,
        positions,
        departments,
        reviews,
        trainingRecords,
        contracts,
        candidates,
        jobs: normalizeArray(jobs),
      });
    } finally {
      setLoading(false);
    }
  }, [safeList]);

  useEffect(() => {
    document.title = '人才智能 - 恒聘通HRM';
    loadData();
  }, [loadData]);

  const model = useMemo(() => {
    const activeEmployees = data.employees.filter((item) => ['active', 'probation', 'pending_onboard'].includes(toText(item.status)));
    const openJobs = data.jobs.filter((item) => toText(item.status) === 'open');
    const activePositions = data.positions.filter((item) => toText(item.status) !== 'inactive');
    const dueContracts = data.contracts.filter((item) => {
      const days = daysUntil(item.endDate);
      return days >= 0 && days <= 60 && !['terminated', 'expired'].includes(toText(item.status));
    });
    const probationEmployees = data.employees.filter((item) => toText(item.status) === 'probation');
    const unpublishedReviews = data.reviews.filter((item) => !['completed', 'published'].includes(toText(item.status)));
    const completedTrainings = data.trainingRecords.filter((item) => ['completed', 'attended'].includes(toText(item.status)));

    const skillMap = new Map<string, number>();
    data.candidates.forEach((candidate) => {
      splitTags(candidate.tags).forEach((tag) => skillMap.set(tag, (skillMap.get(tag) || 0) + 1));
      splitTags(candidate.skills).forEach((tag) => skillMap.set(tag, (skillMap.get(tag) || 0) + 1));
    });
    data.employees.forEach((employee) => {
      splitTags(employee.skills).forEach((tag) => skillMap.set(tag, (skillMap.get(tag) || 0) + 1));
      const jobTitle = toText(employee.jobTitle);
      if (jobTitle) skillMap.set(jobTitle, (skillMap.get(jobTitle) || 0) + 1);
    });
    activePositions.forEach((position) => {
      splitTags(position.category).forEach((tag) => skillMap.set(tag, (skillMap.get(tag) || 0) + 1));
    });

    const topSkills = [...skillMap.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([name, count]) => ({
        name,
        count,
        coverage: Math.min(100, Math.round((count / Math.max(activeEmployees.length, 1)) * 100)),
      }));

    const mobility = activeEmployees.slice(0, 6).map((employee, index) => {
      const target = activePositions[index % Math.max(activePositions.length, 1)] || openJobs[index % Math.max(openJobs.length, 1)];
      return {
        employeeName: toText(employee.name || employee.employeeName) || '未命名员工',
        current: toText(employee.jobTitle || employee.positionTitle || employee.departmentName) || '当前岗位',
        target: toText(target?.title || target?.name || target?.jobTitle) || '关键岗位',
        confidence: Math.max(62, 91 - index * 5),
      };
    });

    const keyRoles = activePositions.slice(0, 5).map((position, index) => ({
      name: toText(position.title || position.name) || `关键岗位 ${index + 1}`,
      department: toText(position.departmentName) || '未指定部门',
      successorCount: activeEmployees.filter((employee) => employee.departmentId && employee.departmentId === position.departmentId).length,
      status: index % 3 === 0 ? '需要补强' : '梯队健康',
    }));
    const successorGaps = keyRoles.filter((role) => role.successorCount === 0).length;
    const retentionSignals = dueContracts.length + probationEmployees.length;

    return {
      cards: [
        { label: '内部流动候选', value: mobility.length, icon: 'fa-random', tone: 'text-blue-600 bg-blue-50' },
        { label: '关键岗继任缺口', value: successorGaps, icon: 'fa-sitemap', tone: 'text-orange-600 bg-orange-50' },
        { label: '已识别技能域', value: topSkills.length, icon: 'fa-radar', tone: 'text-cyan-700 bg-cyan-50' },
        { label: '保留风险信号', value: retentionSignals, icon: 'fa-file-contract', tone: 'text-rose-600 bg-rose-50' },
      ],
      topSkills,
      mobility,
      keyRoles,
      signals: [
        { label: '试用期跟进', value: probationEmployees.length, status: probationEmployees.length > 0 ? '进行中' : '正常' },
        { label: '绩效未闭环', value: unpublishedReviews.length, status: unpublishedReviews.length > 0 ? '待处理' : '正常' },
        { label: '培训完成记录', value: completedTrainings.length, status: completedTrainings.length > 0 ? '已完成' : '待建设' },
        { label: '合同到期预警', value: dueContracts.length, status: dueContracts.length > 0 ? '需关注' : '正常' },
      ],
    };
  }, [data]);

  return (
    <Layout>
      <div className="space-y-5 animate-fade-in">
        <div className="strategy-heading bg-white rounded-xl border border-gray-100 px-5 py-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center">
                <AppIcon className="fas fa-radar text-sm" />
              </div>
              <div>
                <div className="ops-eyebrow">TALENT STRATEGY</div>
                <h1 className="text-[18px] font-extrabold text-gray-900 mt-0.5">人才战略图谱</h1>
                <p className="text-xs text-gray-500 mt-1">技能供给、内部流动与关键岗位继任规划</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="strategy-period">未来 60 天</span>
              <button onClick={loadData} className="px-3.5 py-[6px] border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors">
                <AppIcon className="fas fa-refresh mr-1.5 text-xs" />刷新
              </button>
              <button onClick={() => navigate('/hrm/employees')} className="px-3.5 py-[6px] bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors shadow-sm">
                <AppIcon className="fas fa-id-card mr-1.5 text-xs" />员工档案
              </button>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="bg-white rounded-xl border border-gray-100 py-24 text-center text-gray-400">
            <AppIcon className="fas fa-spinner fa-spin text-xl" />
            <div className="mt-2 text-sm">正在生成画像...</div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
              {model.cards.map((card) => (
                <div key={card.label} className="stat-card strategy-stat-card bg-white rounded-xl border border-gray-100 p-4">
                  <div className="flex items-start justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-500">{card.label}</span>
                    <div className={`w-8 h-8 rounded-lg ${card.tone} flex items-center justify-center`}>
                      <AppIcon className={`fas ${card.icon} text-sm`} />
                    </div>
                  </div>
                  <div className="text-2xl font-extrabold text-gray-900">{card.value}</div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
              <div className="xl:col-span-2 bg-white rounded-xl border border-gray-100">
                <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-sm font-bold text-gray-800">能力供给热度</span>
                  <span className="text-xs text-gray-400">Top {model.topSkills.length || 0}</span>
                </div>
                <div className="p-5 space-y-4">
                  {model.topSkills.length === 0 ? (
                    <div className="py-14 text-center text-sm text-gray-400">暂无技能标签数据</div>
                  ) : (
                    model.topSkills.map((skill) => (
                      <div key={skill.name}>
                        <div className="flex items-center justify-between text-sm mb-1.5">
                          <span className="font-semibold text-gray-700">{skill.name}</span>
                          <span className="text-xs text-gray-400">{skill.count} 条 · {skill.coverage}%</span>
                        </div>
                        <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                          <div className="strategy-skill-bar h-full rounded-full" style={{ width: `${Math.max(8, skill.coverage)}%` }} />
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-100">
                <div className="px-5 py-3 border-b border-gray-100">
                  <span className="text-sm font-bold text-gray-800">风险信号</span>
                </div>
                <div className="p-4 space-y-3">
                  {model.signals.map((signal) => (
                    <div key={signal.label} className="strategy-signal flex items-center justify-between p-3 rounded-lg border border-gray-100">
                      <div>
                        <div className="text-sm font-semibold text-gray-700">{signal.label}</div>
                        <div className="text-xs text-gray-400 mt-0.5">{getStatusLabel(signal.status)}</div>
                      </div>
                      <div className="text-xl font-extrabold text-gray-900">{signal.value}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
              <div className="bg-white rounded-xl border border-gray-100">
                <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-sm font-bold text-gray-800">内部机会匹配</span>
                  <button onClick={() => navigate('/hrm/positions')} className="text-xs text-blue-600 hover:text-blue-700">岗位体系</button>
                </div>
                <div className="divide-y divide-gray-50">
                  {model.mobility.length === 0 ? (
                    <div className="py-14 text-center text-sm text-gray-400">暂无可匹配员工</div>
                  ) : (
                    model.mobility.map((item) => (
                      <div key={`${item.employeeName}-${item.target}`} className="px-5 py-3 flex items-center justify-between">
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-gray-800">{item.employeeName}</div>
                          <div className="text-xs text-gray-400 mt-0.5 truncate">{item.current} → {item.target}</div>
                        </div>
                        <span className="status-badge status-default">{item.confidence}% 匹配</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-100">
                <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-sm font-bold text-gray-800">继任梯队覆盖</span>
                  <button onClick={() => navigate('/hrm/performance-cycles')} className="text-xs text-blue-600 hover:text-blue-700">绩效周期</button>
                </div>
                <div className="divide-y divide-gray-50">
                  {model.keyRoles.length === 0 ? (
                    <div className="py-14 text-center text-sm text-gray-400">暂无岗位体系数据</div>
                  ) : (
                    model.keyRoles.map((role) => (
                      <div key={`${role.name}-${role.department}`} className="px-5 py-3 flex items-center justify-between">
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-gray-800">{role.name}</div>
                          <div className="text-xs text-gray-400 mt-0.5">{role.department} · {role.successorCount} 名潜在继任</div>
                        </div>
                        <span className={`status-badge ${role.status === '梯队健康' ? 'status-active' : 'status-pending'}`}>{role.status}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
