import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import AppIcon from '../../components/AppIcon';
import apiClient, { ApiError } from '../../utils/api';

interface Todo {
  id: string;
  type: string;
  type_label: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  created_at: string;
  deadline: string | null;
  link: string;
  meta: Record<string, any>;
}

interface TodoSummary {
  count: number;
  highCount: number;
  urgentCount: number;
}

interface TodoResponse {
  todos?: Todo[];
  count?: number;
}

const priorityColors = {
  high: 'bg-rose-500',
  medium: 'bg-amber-500',
  low: 'bg-slate-400',
};

const typeIcons: Record<string, string> = {
  approval_pending: 'fa-clipboard-check',
  onboarding_task: 'fa-user-plus',
  performance_review: 'fa-star',
  training_course: 'fa-graduation-cap',
  attendance_anomaly: 'fa-clock',
};

const formatTime = (isoString: string) => {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} 天前`;

  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
};

const formatDate = (dateString: string) => {
  if (!dateString) return '';
  const date = new Date(dateString);
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
};

function StatCard({ icon, label, value, color = 'blue' }: {
  icon: string;
  label: string;
  value: number;
  color?: string;
}) {
  const colorClasses: Record<string, { bg: string; text: string }> = {
    blue: { bg: 'bg-blue-50', text: 'text-blue-600' },
    rose: { bg: 'bg-rose-50', text: 'text-rose-600' },
    amber: { bg: 'bg-amber-50', text: 'text-amber-600' },
  };

  const colors = colorClasses[color] || colorClasses.blue;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-slate-500">{label}</span>
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${colors.bg} ${colors.text}`}>
          <AppIcon className={`fas ${icon} text-xs`} />
        </span>
      </div>
      <div className="mt-2 text-2xl font-bold text-slate-900">{value}</div>
    </div>
  );
}

export default function TodosPage() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<'all' | 'high' | 'urgent'>('all');
  const [summary, setSummary] = useState<TodoSummary>({
    count: 0,
    highCount: 0,
    urgentCount: 0,
  });
  const navigate = useNavigate();

  useEffect(() => {
    document.title = '待办事项 - 恒聘通';
    loadTodos();
  }, []);

  const loadTodos = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiClient.get<TodoResponse>('/todos');
      const nextTodos = Array.isArray(data?.todos) ? data.todos : [];
      setTodos(nextTodos);

      // 计算统计数据
      const highCount = nextTodos.filter((t) => t.priority === 'high').length;
      const now = new Date();
      const urgentCount = nextTodos.filter((t) => {
        if (!t.deadline) return false;
        const deadline = new Date(t.deadline);
        const daysUntil = Math.ceil((deadline.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
        return daysUntil <= 3 && daysUntil >= 0;
      }).length;

      setSummary({
        count: data.count || nextTodos.length,
        highCount,
        urgentCount,
      });
    } catch (loadError) {
      const message = loadError instanceof ApiError && loadError.status === 403
        ? '当前账号无权查看待办事项'
        : loadError instanceof Error ? loadError.message : '待办事项加载失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleTodoClick = (todo: Todo) => {
    navigate(todo.link);
  };

  const filteredTodos = todos.filter(todo => {
    if (filter === 'high') return todo.priority === 'high';
    if (filter === 'urgent') {
      if (!todo.deadline) return false;
      const now = new Date();
      const deadline = new Date(todo.deadline);
      const daysUntil = Math.ceil((deadline.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
      return daysUntil <= 3 && daysUntil >= 0;
    }
    return true;
  });

  if (loading) {
    return (
      <Layout>
        <div className="flex h-64 items-center justify-center text-blue-500">
          <AppIcon className="fas fa-spinner fa-spin text-xl" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="space-y-4 animate-fade-in">
        {error && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            <span><AppIcon className="fas fa-circle-exclamation mr-2" />{error}</span>
            <button type="button" onClick={() => { void loadTodos(); }} className="font-medium underline">重试</button>
          </div>
        )}
        {/* 页面头部 */}
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <AppIcon className="fas fa-clipboard-check text-base" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-900">待办事项</h1>
                <p className="mt-1 text-xs text-slate-500">查看并处理您的所有待办任务</p>
              </div>
            </div>
            <button
              onClick={loadTodos}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <AppIcon className="fas fa-sync-alt mr-2" />
              刷新
            </button>
          </div>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            icon="fa-clipboard-check"
            label="全部待办"
            value={summary.count}
            color="blue"
          />
          <StatCard
            icon="fa-exclamation-circle"
            label="高优先级"
            value={summary.highCount}
            color="rose"
          />
          <StatCard
            icon="fa-clock"
            label="即将到期"
            value={summary.urgentCount}
            color="amber"
          />
        </div>

        {/* 筛选标签 */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setFilter('all')}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              filter === 'all'
                ? 'bg-blue-600 text-white'
                : 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50'
            }`}
          >
            全部 ({summary.count})
          </button>
          <button
            onClick={() => setFilter('high')}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              filter === 'high'
                ? 'bg-rose-600 text-white'
                : 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50'
            }`}
          >
            高优先级 ({summary.highCount})
          </button>
          <button
            onClick={() => setFilter('urgent')}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              filter === 'urgent'
                ? 'bg-amber-600 text-white'
                : 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50'
            }`}
          >
            即将到期 ({summary.urgentCount})
          </button>
        </div>

        {/* 待办列表 */}
        {filteredTodos.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white p-12 text-center">
            <AppIcon className="fas fa-check-circle text-4xl text-emerald-500" />
            <p className="mt-4 text-sm text-slate-500">
              {filter === 'all' ? '太棒了！您已完成所有待办事项' : '此类别下暂无待办事项'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredTodos.map(todo => (
              <div
                key={todo.id}
                onClick={() => handleTodoClick(todo)}
                className="rounded-lg border border-slate-200 bg-white p-4 hover:border-blue-300 transition-colors cursor-pointer"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3 flex-1">
                    {/* 优先级指示器 */}
                    <div className={`mt-2 h-2 w-2 rounded-full flex-shrink-0 ${priorityColors[todo.priority]}`} />

                    {/* 图标 */}
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                      <AppIcon className={`fas ${typeIcons[todo.type] || 'fa-tasks'} text-sm`} />
                    </div>

                    {/* 内容 */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-medium text-slate-900">{todo.title}</h3>
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600 whitespace-nowrap">
                          {todo.type_label}
                        </span>
                        {todo.priority === 'high' && (
                          <span className="rounded-md bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">
                            高优先级
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-slate-600 line-clamp-2">{todo.description}</p>
                      <div className="mt-2 flex items-center gap-4 text-xs text-slate-500">
                        <span>
                          <AppIcon className="far fa-clock mr-1" />
                          {formatTime(todo.created_at)}
                        </span>
                        {todo.deadline && (
                          <span className="text-amber-600">
                            <AppIcon className="far fa-calendar mr-1" />
                            截止 {formatDate(todo.deadline)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 右侧箭头 */}
                  <AppIcon className="fas fa-chevron-right text-slate-400 ml-2 flex-shrink-0" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
