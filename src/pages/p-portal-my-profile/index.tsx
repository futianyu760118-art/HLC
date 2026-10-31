import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import apiClient, { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

interface LearningStats {
  coursesFinished: number;
  coursesInProgress: number;
  coursesTotal: number;
  courseCompletionRate: number;
  totalWatchedMinutes: number;
  examsTaken: number;
  examsPassed: number;
  examPassRate: number;
  certificatesEarned: number;
  totalPoints: number;
  learningPaths: number;
  learningPathsCompleted: number;
}

interface CourseRecord {
  courseId: string;
  courseTitle?: string;
  progress: number;
  finishedCount: number;
  hourCount: number;
  isFinished: boolean;
  finishedAt?: string;
  updatedAt?: string;
}

interface ExamRecord {
  latestAttemptId: string;
  taskId?: string;
  taskTitle?: string;
  paperTitle?: string;
  latestScore?: number;
  totalScore?: number;
  bestScore?: number;
  passed: boolean;
  attemptCount: number;
  submittedAt?: string;
}

interface CertificateRecord {
  id: string;
  courseTitle?: string;
  certNo: string;
  issuedAt?: string;
}

interface LearningPathRecord {
  id: string;
  pathName?: string;
  progress: number;
  isCompleted: boolean;
}

interface ProfilePayload {
  employee: {
    name?: string;
    employeeNo?: string;
    email?: string;
    departmentName?: string;
    positionTitle?: string;
    jobTitle?: string;
    hireDate?: string;
  };
  stats: LearningStats;
  recentCourses: CourseRecord[];
  recentExams: ExamRecord[];
  certificates: CertificateRecord[];
  learningPaths: LearningPathRecord[];
}

const EMPTY_STATS: LearningStats = {
  coursesFinished: 0,
  coursesInProgress: 0,
  coursesTotal: 0,
  courseCompletionRate: 0,
  totalWatchedMinutes: 0,
  examsTaken: 0,
  examsPassed: 0,
  examPassRate: 0,
  certificatesEarned: 0,
  totalPoints: 0,
  learningPaths: 0,
  learningPathsCompleted: 0,
};

const formatDate = (value?: string, includeTime = false) => {
  if (!value) return '-';
  const normalized = value.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', includeTime
    ? { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { year: 'numeric', month: '2-digit', day: '2-digit' });
};

const formatDuration = (minutes: number) => {
  const safeMinutes = Math.max(0, Number(minutes) || 0);
  const hours = Math.floor(safeMinutes / 60);
  const rest = safeMinutes % 60;
  if (!hours) return `${rest} 分钟`;
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
};

export default function P_portal_my_profile() {
  const navigate = useNavigate();
  const [data, setData] = useState<ProfilePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [exporting, setExporting] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    portalApi.myProfile()
      .then((payload) => setData(payload as ProfilePayload))
      .catch((error: Error) => {
        toast.error(error.message || '学习档案加载失败');
        setLoadError(true);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    document.title = '学习档案';
    load();
  }, []);

  const stats = data?.stats || EMPTY_STATS;
  const profileCompletion = useMemo(() => {
    if (!stats.coursesTotal && !stats.examsTaken) return 0;
    const courseWeight = stats.coursesTotal ? stats.courseCompletionRate : 0;
    const examWeight = stats.examsTaken ? stats.examPassRate : 0;
    const divisor = Number(stats.coursesTotal > 0) + Number(stats.examsTaken > 0);
    return Math.round((courseWeight + examWeight) / Math.max(divisor, 1));
  }, [stats]);

  const exportReport = async () => {
    setExporting(true);
    try {
      await apiClient.downloadFile('/portal/export/my-report');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return <Layout><div className="flex justify-center py-24"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  }

  if (loadError || !data) {
    return (
      <Layout>
        <div className="py-24 text-center">
          <AppIcon className="fas fa-circle-exclamation text-2xl text-danger" />
          <p className="mt-3 text-sm text-text-secondary">学习档案加载失败</p>
          <button type="button" onClick={load} className="mt-4 text-sm font-medium text-primary hover:underline">重新加载</button>
        </div>
      </Layout>
    );
  }

  const { employee, recentCourses = [], recentExams = [], certificates = [], learningPaths = [] } = data;
  const roleLabel = employee.positionTitle || employee.jobTitle || '员工';
  const initials = (employee.name || '员').slice(-2);

  return (
    <Layout>
      <div className="mx-auto max-w-6xl px-4 py-6 md:px-6">
        <header className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-bold text-text-primary">学习档案</h1>
            <p className="mt-1 text-sm text-text-secondary">课程、考试、证书与成长记录</p>
          </div>
          <button
            type="button"
            onClick={exportReport}
            disabled={exporting}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-border-light bg-white px-3 text-sm font-medium text-text-primary hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
          >
            <AppIcon className={`fas ${exporting ? 'fa-spinner fa-spin' : 'fa-file-pdf'}`} />
            {exporting ? '正在导出' : '导出学习报告'}
          </button>
        </header>

        <section className="mb-5 rounded-lg border border-border-light bg-white px-5 py-5">
          <div className="flex flex-col gap-5 md:flex-row md:items-center">
            <div className="flex min-w-0 flex-1 items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-primary text-base font-bold text-white">
                {initials}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-lg font-semibold text-text-primary">{employee.name || '-'}</h2>
                  <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{roleLabel}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-secondary">
                  <span>{employee.departmentName || '未分配部门'}</span>
                  <span>工号 {employee.employeeNo || '-'}</span>
                  <span>入职 {formatDate(employee.hireDate)}</span>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 border-t border-border-light pt-4 md:border-l md:border-t-0 md:pl-6 md:pt-0">
              <CompactMetric label="学习时长" value={formatDuration(stats.totalWatchedMinutes)} />
              <CompactMetric label="当前积分" value={`${stats.totalPoints} 分`} />
              <CompactMetric label="成长路径" value={`${stats.learningPathsCompleted}/${stats.learningPaths}`} />
              <CompactMetric label="综合完成度" value={`${profileCompletion}%`} />
            </div>
          </div>
        </section>

        <section className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <OverviewMetric icon="fa-book-open" label="已完成课程" value={stats.coursesFinished} note={`共 ${stats.coursesTotal} 门`} tone="primary" />
          <OverviewMetric icon="fa-chart-line" label="学习中课程" value={stats.coursesInProgress} note={`${stats.courseCompletionRate}% 课程完成率`} tone="info" />
          <OverviewMetric icon="fa-clipboard-check" label="参加考试" value={stats.examsTaken} note="已按考试去重" tone="warning" />
          <OverviewMetric icon="fa-award" label="通过考试" value={stats.examsPassed} note={`${stats.examPassRate}% 通过率`} tone="success" />
        </section>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-5">
            <section className="rounded-lg border border-border-light bg-white">
              <SectionHeader
                icon="fa-book-open"
                title="课程记录"
                meta={`${recentCourses.length} 门有学习记录`}
                actionLabel="全部课程"
                onAction={() => navigate('/portal/my-courses')}
              />
              {recentCourses.length === 0 ? (
                <EmptyRow icon="fa-book-open" text="暂无课程学习记录" />
              ) : (
                <div className="divide-y divide-border-light">
                  {recentCourses.map((course) => (
                    <button
                      type="button"
                      key={course.courseId}
                      onClick={() => navigate(`/portal/course/${course.courseId}`)}
                      className="flex w-full items-center gap-4 px-4 py-3.5 text-left hover:bg-bg-light/60"
                    >
                      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${course.isFinished ? 'bg-success/10 text-success' : 'bg-primary/10 text-primary'}`}>
                        <AppIcon className={`fas ${course.isFinished ? 'fa-check' : 'fa-play'}`} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-3">
                          <span className="truncate text-sm font-medium text-text-primary">{course.courseTitle || '未命名课程'}</span>
                          <span className={`shrink-0 text-xs font-medium ${course.isFinished ? 'text-success' : 'text-primary'}`}>
                            {course.isFinished ? '已完成' : `${course.progress}%`}
                          </span>
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded bg-bg-light">
                          <div className={`h-full rounded ${course.isFinished ? 'bg-success' : 'bg-primary'}`} style={{ width: `${Math.min(100, Math.max(0, course.progress))}%` }} />
                        </div>
                        <div className="mt-1.5 flex justify-between text-xs text-text-secondary">
                          <span>{course.finishedCount}/{course.hourCount || 0} 课时</span>
                          <span>{course.isFinished ? `完成于 ${formatDate(course.finishedAt)}` : `更新于 ${formatDate(course.updatedAt)}`}</span>
                        </div>
                      </div>
                      <AppIcon className="fas fa-chevron-right shrink-0 text-xs text-text-secondary" />
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-lg border border-border-light bg-white">
              <SectionHeader
                icon="fa-clipboard-check"
                title="考试记录"
                meta={`${recentExams.length} 场考试，重复作答已合并`}
                actionLabel="我的考试"
                onAction={() => navigate('/portal/my-exams')}
              />
              {recentExams.length === 0 ? (
                <EmptyRow icon="fa-clipboard-list" text="暂无考试记录" />
              ) : (
                <div className="divide-y divide-border-light">
                  {recentExams.map((exam) => (
                    <button
                      type="button"
                      key={exam.taskId || exam.latestAttemptId}
                      onClick={() => navigate(`/portal/exam/result/${exam.latestAttemptId}`)}
                      className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-4 py-4 text-left hover:bg-bg-light/60 sm:grid-cols-[minmax(0,1fr)_90px_90px_110px_auto]"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-text-primary">{exam.taskTitle || '未命名考试'}</div>
                        <div className="mt-1 truncate text-xs text-text-secondary">{exam.paperTitle || '考试试卷'} · 最近作答 {formatDate(exam.submittedAt, true)}</div>
                      </div>
                      <ExamMetric className="hidden sm:block" label="最佳成绩" value={exam.bestScore ?? '-'} />
                      <ExamMetric className="hidden sm:block" label="作答次数" value={`${exam.attemptCount} 次`} />
                      <div className="text-right">
                        <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ${exam.passed ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                          {exam.passed ? '已通过' : '未通过'}
                        </span>
                        <div className="mt-1 text-xs text-text-secondary sm:hidden">最高 {exam.bestScore ?? '-'} · {exam.attemptCount} 次</div>
                      </div>
                      <AppIcon className="fas fa-chevron-right hidden text-xs text-text-secondary sm:block" />
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="space-y-5">
            <section className="rounded-lg border border-border-light bg-white p-4">
              <h2 className="text-sm font-semibold text-text-primary">学习达成</h2>
              <div className="mt-4 space-y-4">
                <ProgressRow label="课程完成率" value={stats.courseCompletionRate} color="bg-primary" />
                <ProgressRow label="考试通过率" value={stats.examPassRate} color="bg-success" />
                <ProgressRow label="综合完成度" value={profileCompletion} color="bg-warning" />
              </div>
            </section>

            <section className="rounded-lg border border-border-light bg-white">
              <SectionHeader
                icon="fa-certificate"
                title="学习证书"
                meta={`共 ${stats.certificatesEarned} 张`}
                actionLabel="全部证书"
                onAction={() => navigate('/portal/certificates')}
              />
              {certificates.length === 0 ? (
                <EmptyRow icon="fa-certificate" text="暂无学习证书" compact />
              ) : (
                <div className="divide-y divide-border-light">
                  {certificates.slice(0, 4).map((certificate) => (
                    <button
                      type="button"
                      key={certificate.id}
                      onClick={() => navigate('/portal/certificates')}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-bg-light/60"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning/10 text-warning">
                        <AppIcon className="fas fa-award" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-text-primary">{certificate.courseTitle || '学习证书'}</div>
                        <div className="mt-0.5 text-xs text-text-secondary">{formatDate(certificate.issuedAt)} · {certificate.certNo}</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-lg border border-border-light bg-white p-4">
              <h2 className="text-sm font-semibold text-text-primary">成长入口</h2>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <QuickLink icon="fa-route" label="学习路径" value={`${stats.learningPathsCompleted}/${stats.learningPaths}`} onClick={() => navigate('/portal/learning-paths')} />
                <QuickLink icon="fa-trophy" label="学习积分" value={`${stats.totalPoints}`} onClick={() => navigate('/portal/points')} />
                <QuickLink icon="fa-bookmark" label="错题本" value="复习" onClick={() => navigate('/portal/wrong-questions')} />
                <QuickLink icon="fa-chart-radar" label="能力测评" value="查看" onClick={() => navigate('/portal/competency')} />
              </div>
              {learningPaths.length > 0 && (
                <div className="mt-4 border-t border-border-light pt-3">
                  <div className="mb-2 text-xs text-text-secondary">最近学习路径</div>
                  {learningPaths.slice(0, 2).map((path) => (
                    <div key={path.id} className="mb-2 last:mb-0">
                      <div className="flex items-center justify-between gap-3 text-xs">
                        <span className="truncate text-text-primary">{path.pathName || '学习路径'}</span>
                        <span className={path.isCompleted ? 'text-success' : 'text-primary'}>{path.isCompleted ? '已完成' : `${path.progress}%`}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </aside>
        </div>
      </div>
    </Layout>
  );
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}

function OverviewMetric({ icon, label, value, note, tone }: { icon: string; label: string; value: number; note: string; tone: 'primary' | 'info' | 'warning' | 'success' }) {
  const tones = {
    primary: 'bg-primary/10 text-primary',
    info: 'bg-info/10 text-info',
    warning: 'bg-warning/10 text-warning',
    success: 'bg-success/10 text-success',
  };
  return (
    <div className="rounded-lg border border-border-light bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs text-text-secondary">{label}</div>
          <div className="mt-1 text-2xl font-bold text-text-primary">{value}</div>
        </div>
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${tones[tone]}`}>
          <AppIcon className={`fas ${icon}`} />
        </div>
      </div>
      <div className="mt-2 text-xs text-text-secondary">{note}</div>
    </div>
  );
}

function SectionHeader({ icon, title, meta, actionLabel, onAction }: { icon: string; title: string; meta: string; actionLabel: string; onAction: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border-light px-4 py-3.5">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <AppIcon className={`fas ${icon} text-primary`} />
          {title}
        </h2>
        <div className="mt-0.5 truncate text-xs text-text-secondary">{meta}</div>
      </div>
      <button type="button" onClick={onAction} className="shrink-0 text-xs font-medium text-primary hover:underline">{actionLabel}</button>
    </div>
  );
}

function ExamMetric({ label, value, className = '' }: { label: string; value: string | number; className?: string }) {
  return (
    <div className={className}>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}

function ProgressRow({ label, value, color }: { label: string; value: number; color: string }) {
  const safeValue = Math.min(100, Math.max(0, Number(value) || 0));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="font-semibold text-text-primary">{safeValue}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-bg-light">
        <div className={`h-full rounded ${color}`} style={{ width: `${safeValue}%` }} />
      </div>
    </div>
  );
}

function QuickLink({ icon, label, value, onClick }: { icon: string; label: string; value: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="rounded-lg border border-border-light p-3 text-left hover:border-primary/30 hover:bg-primary/5">
      <div className="flex items-center justify-between gap-2">
        <AppIcon className={`fas ${icon} text-primary`} />
        <span className="text-xs font-semibold text-text-primary">{value}</span>
      </div>
      <div className="mt-2 text-xs text-text-secondary">{label}</div>
    </button>
  );
}

function EmptyRow({ icon, text, compact = false }: { icon: string; text: string; compact?: boolean }) {
  return (
    <div className={`text-center text-sm text-text-secondary ${compact ? 'py-8' : 'py-12'}`}>
      <AppIcon className={`fas ${icon} mb-2 text-xl text-secondary`} />
      <div>{text}</div>
    </div>
  );
}
