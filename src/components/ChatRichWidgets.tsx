// @ts-nocheck
/**
 * 聊天富组件集合：指标卡 / 迷你柱图 / 数据表格 / 抽屉。
 * 纯 SVG + Tailwind，无第三方依赖。
 */
import React, { useEffect, useMemo, useState } from 'react';

// ============================================================
// 通用类型
// ============================================================
export interface MetricItem {
  label: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'flat';
  trendText?: string;
  color?: 'blue' | 'green' | 'amber' | 'red' | 'gray' | 'indigo' | 'purple' | 'cyan' | 'teal' | 'orange' | 'pink';
  icon?: string;  // FontAwesome 图标类名（不带 fa- 前缀），如 "users"、"briefcase"
}

export interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

// ============================================================
// 1. MetricCards：紧凑型指标卡（横向滚动，2-4 张）
// ============================================================
const colorMap: Record<string, { bg: string; text: string; border: string; iconBg: string; iconText: string }> = {
  blue:   { bg: 'bg-blue-50/70',   text: 'text-blue-600',   border: 'border-blue-100',   iconBg: 'bg-blue-100',   iconText: 'text-blue-600' },
  green:  { bg: 'bg-green-50/70',  text: 'text-green-600',  border: 'border-green-100',  iconBg: 'bg-green-100',  iconText: 'text-green-600' },
  amber:  { bg: 'bg-amber-50/70',  text: 'text-amber-600',  border: 'border-amber-100',  iconBg: 'bg-amber-100',  iconText: 'text-amber-600' },
  red:    { bg: 'bg-red-50/70',    text: 'text-red-600',    border: 'border-red-100',    iconBg: 'bg-red-100',    iconText: 'text-red-600' },
  gray:   { bg: 'bg-gray-50/70',   text: 'text-gray-700',   border: 'border-gray-100',   iconBg: 'bg-gray-100',   iconText: 'text-gray-600' },
  indigo: { bg: 'bg-indigo-50/70', text: 'text-indigo-600', border: 'border-indigo-100', iconBg: 'bg-indigo-100', iconText: 'text-indigo-600' },
  purple: { bg: 'bg-purple-50/70', text: 'text-purple-600', border: 'border-purple-100', iconBg: 'bg-purple-100', iconText: 'text-purple-600' },
  cyan:   { bg: 'bg-cyan-50/70',   text: 'text-cyan-600',   border: 'border-cyan-100',   iconBg: 'bg-cyan-100',   iconText: 'text-cyan-600' },
  teal:   { bg: 'bg-teal-50/70',   text: 'text-teal-600',   border: 'border-teal-100',   iconBg: 'bg-teal-100',   iconText: 'text-teal-600' },
  orange: { bg: 'bg-orange-50/70', text: 'text-orange-600', border: 'border-orange-100', iconBg: 'bg-orange-100', iconText: 'text-orange-600' },
  pink:   { bg: 'bg-pink-50/70',   text: 'text-pink-600',   border: 'border-pink-100',   iconBg: 'bg-pink-100',   iconText: 'text-pink-600' },
};

// 自动从 label 推测合适的图标
const guessIcon = (label: string): string => {
  const l = label.toLowerCase();
  if (l.includes('员工') || l.includes('人数') || l.includes('用户')) return 'user';
  if (l.includes('待入职') || l.includes('入职')) return 'user-plus';
  if (l.includes('离职')) return 'user-minus';
  if (l.includes('岗位') || l.includes('职位')) return 'briefcase';
  if (l.includes('候选人')) return 'user-tie';
  if (l.includes('简历')) return 'file-alt';
  if (l.includes('面试')) return 'users';
  if (l.includes('offer')) return 'envelope-open-text';
  if (l.includes('考勤') || l.includes('迟到') || l.includes('异常')) return 'calendar-alt';
  if (l.includes('反馈') || l.includes('bug')) return 'comment-dots';
  if (l.includes('审批')) return 'check-circle';
  if (l.includes('薪资') || l.includes('工资')) return 'yen-sign';
  if (l.includes('培训') || l.includes('课程')) return 'book';
  if (l.includes('绩效')) return 'chart-line';
  if (l.includes('部门')) return 'sitemap';
  return 'chart-bar';
};

// 按 index 轮转颜色（当后端未指定 color 时）
const FALLBACK_COLORS = ['blue', 'orange', 'purple', 'green', 'cyan', 'amber', 'red', 'pink'];

export const MetricCards: React.FC<{ metrics: MetricItem[] }> = ({ metrics }) => {
  if (!metrics?.length) return null;
  return (
    <div className={`grid gap-2.5 my-2 ${metrics.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
      {metrics.map((m, i) => {
        const color = m.color || (FALLBACK_COLORS[i % FALLBACK_COLORS.length] as MetricItem['color']);
        const c = colorMap[color || 'blue'] || colorMap.blue;
        const icon = m.icon || guessIcon(m.label || '');
        return (
          <div key={i} className={`${c.bg} ${c.border} border rounded-2xl px-3 py-3 flex items-center gap-3`}>
            {/* 圆角图标块 */}
            <div className={`w-10 h-10 rounded-xl ${c.iconBg} flex items-center justify-center flex-shrink-0`}>
              <i className={`fas fa-${icon} ${c.iconText} text-base`}></i>
            </div>
            {/* 文本区 */}
            <div className="flex-1 min-w-0">
              <div className="text-[11px] text-gray-500 mb-0.5 truncate">{m.label}</div>
              <div className="flex items-baseline gap-1">
                <span className={`text-xl font-bold leading-none ${c.text}`}>{m.value}</span>
                {m.unit && <span className="text-[11px] text-gray-500">{m.unit}</span>}
              </div>
              {m.trendText && (
                <div className={`text-[10px] mt-0.5 ${
                  m.trend === 'up' ? 'text-green-600' : m.trend === 'down' ? 'text-red-500' : 'text-gray-400'
                }`}>
                  {m.trend === 'up' && <i className="fas fa-arrow-up mr-0.5"></i>}
                  {m.trend === 'down' && <i className="fas fa-arrow-down mr-0.5"></i>}
                  {m.trendText}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ============================================================
// 2. MiniBarChart：水平迷你柱图
// ============================================================
export const MiniBarChart: React.FC<{
  data: ChartDataPoint[];
  title?: string;
  maxItems?: number;
}> = ({ data, title, maxItems = 8 }) => {
  if (!data?.length) return null;
  const visible = data.slice(0, maxItems);
  const max = Math.max(...visible.map((d) => d.value), 1);
  const palette = ['#3b82f6', '#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];

  return (
    <div className="my-2 bg-gradient-to-br from-gray-50 to-blue-50/30 border border-gray-100 rounded-lg p-3">
      {title && <div className="text-xs font-medium text-gray-700 mb-2">{title}</div>}
      <div className="space-y-1.5">
        {visible.map((d, i) => {
          const pct = (d.value / max) * 100;
          const color = d.color || palette[i % palette.length];
          return (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="text-gray-600 truncate w-20 flex-shrink-0" title={d.label}>{d.label}</span>
              <div className="flex-1 h-5 bg-white rounded relative overflow-hidden border border-gray-100">
                <div
                  className="h-full rounded transition-all duration-500"
                  style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.85 }}
                />
                <span className="absolute inset-0 flex items-center px-2 text-[10px] font-medium text-gray-700">
                  {d.value}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {data.length > maxItems && (
        <div className="text-[10px] text-gray-400 text-right mt-1.5">
          仅显示前 {maxItems} 项，共 {data.length} 项
        </div>
      )}
    </div>
  );
};

// ============================================================
// 3. DonutChart：迷你环形图（适合占比）
// ============================================================
export const MiniDonut: React.FC<{
  data: ChartDataPoint[];
  title?: string;
  centerLabel?: string;
}> = ({ data, title, centerLabel }) => {
  if (!data?.length) return null;
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;
  const palette = ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899'];
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="my-2 bg-gradient-to-br from-gray-50 to-blue-50/30 border border-gray-100 rounded-lg p-3">
      {title && <div className="text-xs font-medium text-gray-700 mb-2">{title}</div>}
      <div className="flex items-center gap-4">
        <div className="relative flex-shrink-0">
          <svg width="100" height="100" viewBox="0 0 100 100">
            {data.map((d, i) => {
              const pct = d.value / total;
              const dash = pct * circumference;
              const color = d.color || palette[i % palette.length];
              const seg = (
                <circle
                  key={i}
                  cx="50" cy="50" r={radius}
                  fill="none"
                  stroke={color}
                  strokeWidth="14"
                  strokeDasharray={`${dash} ${circumference - dash}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 50 50)"
                />
              );
              offset += dash;
              return seg;
            })}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className="text-base font-semibold text-gray-800">{total}</div>
            {centerLabel && <div className="text-[9px] text-gray-500">{centerLabel}</div>}
          </div>
        </div>
        <div className="flex-1 space-y-1 min-w-0">
          {data.slice(0, 6).map((d, i) => {
            const color = d.color || palette[i % palette.length];
            const pct = ((d.value / total) * 100).toFixed(1);
            return (
              <div key={i} className="flex items-center gap-1.5 text-[11px]">
                <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ backgroundColor: color }} />
                <span className="text-gray-700 truncate flex-1" title={d.label}>{d.label}</span>
                <span className="text-gray-500 flex-shrink-0">{d.value}</span>
                <span className="text-gray-400 flex-shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// ============================================================
// 4. DataTable：紧凑表格（>5 行/>4 列时折叠 + 抽屉查看全部）
// ============================================================
export interface TableColumn {
  key: string;
  label: string;
  width?: string;
  align?: 'left' | 'center' | 'right';
}

export interface TableData {
  columns: TableColumn[];
  rows: Array<Record<string, any>>;
  title?: string;
}

const TableDrawer: React.FC<{ table: TableData; onClose: () => void }> = ({ table, onClose }) => {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const exportCsv = () => {
    const headers = table.columns.map((c) => c.label).join(',');
    const lines = table.rows.map((r) =>
      table.columns.map((c) => {
        const val = r[c.key];
        const s = val === null || val === undefined ? '' : String(val);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      }).join(',')
    );
    const csv = '\uFEFF' + [headers, ...lines].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${table.title || 'table'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-[70] animate-fade-in" onClick={onClose} />
      <div className="fixed top-0 right-0 bottom-0 z-[71] bg-white shadow-2xl w-full max-w-3xl flex flex-col animate-fade-in">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-indigo-50">
          <div>
            <div className="text-base font-semibold text-gray-900">{table.title || '数据表'}</div>
            <div className="text-xs text-gray-500 mt-0.5">{table.rows.length} 行 · {table.columns.length} 列</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={exportCsv}
              className="px-3 py-1.5 text-xs text-blue-600 bg-white border border-blue-200 rounded-lg hover:bg-blue-50"
            >
              <i className="fas fa-download mr-1"></i>导出 CSV
            </button>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-white hover:text-gray-600"
            >
              <i className="fas fa-times"></i>
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 z-10">
              <tr>
                {table.columns.map((col) => (
                  <th
                    key={col.key}
                    className={`px-4 py-2.5 text-xs font-medium text-gray-600 ${
                      col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                    }`}
                    style={col.width ? { width: col.width } : undefined}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i} className="border-b border-gray-100 hover:bg-blue-50/30">
                  {table.columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-2 text-gray-700 ${
                        col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                      }`}
                    >
                      {row[col.key] ?? '-'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
};

export const DataTable: React.FC<{ table: TableData }> = ({ table }) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  if (!table?.rows?.length || !table?.columns?.length) return null;

  const PREVIEW_ROWS = 5;
  const PREVIEW_COLS = 4;
  const tooManyRows = table.rows.length > PREVIEW_ROWS;
  const tooManyCols = table.columns.length > PREVIEW_COLS;
  const columns = tooManyCols ? table.columns.slice(0, PREVIEW_COLS) : table.columns;
  const rows = tooManyRows ? table.rows.slice(0, PREVIEW_ROWS) : table.rows;

  return (
    <>
      <div className="my-2 bg-white border border-gray-200 rounded-lg overflow-hidden">
        {table.title && (
          <div className="px-3 py-2 bg-gray-50 border-b border-gray-100 text-xs font-medium text-gray-700 flex items-center justify-between">
            <span>{table.title}</span>
            {(tooManyRows || tooManyCols) && (
              <button
                onClick={() => setDrawerOpen(true)}
                className="text-blue-600 hover:text-blue-700 text-[11px] font-normal"
              >
                查看全部 <i className="fas fa-external-link-alt text-[9px] ml-0.5"></i>
              </button>
            )}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="bg-gray-50/50 border-b border-gray-100">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className={`px-2.5 py-1.5 text-[11px] font-medium text-gray-600 ${
                      col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                    }`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-gray-50 last:border-0 hover:bg-blue-50/20">
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-2.5 py-1.5 text-gray-700 ${
                        col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                      }`}
                    >
                      <span className="block truncate max-w-[120px]" title={String(row[col.key] ?? '')}>
                        {row[col.key] ?? '-'}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!table.title && (tooManyRows || tooManyCols) && (
          <div className="px-3 py-1.5 bg-gray-50/50 border-t border-gray-100 text-[10px] text-gray-500 flex items-center justify-between">
            <span>
              {tooManyRows && `仅显示前 ${PREVIEW_ROWS} 行，`}
              {tooManyCols && `仅显示前 ${PREVIEW_COLS} 列，`}
              共 {table.rows.length} 行 · {table.columns.length} 列
            </span>
            <button
              onClick={() => setDrawerOpen(true)}
              className="text-blue-600 hover:text-blue-700"
            >
              查看全部 <i className="fas fa-external-link-alt text-[9px]"></i>
            </button>
          </div>
        )}
      </div>

      {drawerOpen && <TableDrawer table={table} onClose={() => setDrawerOpen(false)} />}
    </>
  );
};

// ============================================================
// 富 widget 入口：根据数据类型分发
// ============================================================
export interface WarningWidget {
  type: 'warning';
  level?: 'info' | 'warning' | 'danger';
  message: string;
}

export interface EntityCardsWidget {
  type: 'entity_cards';
  title?: string;
  entities: Array<{
    type: string;
    typeLabel?: string;
    icon?: string;
    id: string;
    title: string;
    subtitle?: string;
    meta?: string;
    url?: string;
  }>;
}

export interface RichWidget {
  // 兼容多种命名（前端历史 + 新版后端）
  id?: string | number;
  type: 'metrics' | 'metric_cards' | 'bar' | 'bar_chart' | 'donut' | 'doughnut_chart'
       | 'table' | 'data_table' | 'entity_cards' | 'warning'
       | 'markdown' | 'workset_summary' | 'confirmation_card' | 'follow_up_actions'
       | 'source_citations' | 'mermaid_diagram' | 'echarts' | 'clarification'
       | 'timeline' | 'comparison_matrix' | 'status_badges' | 'media_preview';
  title?: string;
  centerLabel?: string;
  data?: any;
  metrics?: MetricItem[];
  table?: TableData;
  cards?: any[];
  entities?: any[];
  workset?: any;
  content?: string;
  question?: string;
  options?: Array<{ label: string; payload?: string }>;
  sources?: any[];
  actions?: any[];
  level?: 'info' | 'warning' | 'danger';
  message?: string;
  items?: any[];
  columns?: any[];
  rows?: any[];
}

const Warning: React.FC<{ widget: any }> = ({ widget }) => {
  const level = widget.level || 'info';
  const styles: Record<string, string> = {
    info: 'bg-blue-50 border-blue-200 text-blue-700',
    warning: 'bg-amber-50 border-amber-200 text-amber-700',
    danger: 'bg-red-50 border-red-200 text-red-700',
  };
  const icons: Record<string, string> = {
    info: 'fa-info-circle',
    warning: 'fa-exclamation-triangle',
    danger: 'fa-circle-exclamation',
  };
  return (
    <div className={`my-2 px-3 py-2 rounded-lg border text-xs flex items-start gap-2 ${styles[level]}`}>
      <i className={`fas ${icons[level]} mt-0.5`}></i>
      <span className="break-words flex-1">{widget.message}</span>
    </div>
  );
};

const EntityCardsList: React.FC<{ widget: any; onPick?: (entity: any) => void }> = ({ widget, onPick }) => {
  const ents = widget.entities || widget.items || widget.data || [];
  if (!ents.length) return null;
  return (
    <div className="my-2">
      {widget.title && <div className="text-xs font-medium text-gray-700 mb-1">{widget.title}</div>}
      <div className="space-y-1.5">
        {ents.slice(0, 12).map((e: any, i: number) => (
          <button
            key={`${e.type}-${e.id}-${i}`}
            onClick={() => onPick && onPick(e)}
            className="w-full flex items-center gap-2 px-2.5 py-2 bg-white rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50/30 transition-all text-left group"
          >
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-100">
              <i className={`fas ${e.icon || 'fa-circle'} text-blue-500 text-xs`}></i>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-gray-800 truncate group-hover:text-blue-600">
                  {e.title}
                </span>
                {e.typeLabel && (
                  <span className="text-[10px] text-gray-400 px-1.5 py-0.5 bg-gray-100 rounded flex-shrink-0">
                    {e.typeLabel}
                  </span>
                )}
              </div>
              {e.subtitle && <div className="text-[11px] text-gray-500 truncate mt-0.5">{e.subtitle}</div>}
              {e.meta && <div className="text-[10px] text-gray-400 truncate mt-0.5">{e.meta}</div>}
            </div>
            {e.url && <i className="fas fa-chevron-right text-[10px] text-gray-300 flex-shrink-0"></i>}
          </button>
        ))}
      </div>
    </div>
  );
};

const MarkdownWidget: React.FC<{ widget: any }> = ({ widget }) => {
  const content = widget.content || widget.markdown || widget.text || '';
  if (!content) return null;
  return (
    <div className="my-2 bg-white border border-gray-100 rounded-xl px-3 py-2 text-xs text-gray-700 whitespace-pre-wrap leading-relaxed">
      {widget.title && <div className="text-xs font-semibold text-gray-800 mb-1">{widget.title}</div>}
      {content}
    </div>
  );
};

const WorksetSummary: React.FC<{ widget: any }> = ({ widget }) => {
  const ws = widget.workset || widget.data || {};
  const items = ws.items || [];
  if (!items.length) return null;
  return (
    <div className="my-2 bg-indigo-50/60 border border-indigo-100 rounded-xl px-3 py-2">
      <div className="text-xs font-semibold text-indigo-700 mb-1">
        {widget.title || ws.label || '已记录结果集'}
      </div>
      <div className="text-[11px] text-indigo-600 mb-1">
        后续可说“这几个人 / 第二个 / 上面这些候选人”继续追问。
      </div>
      <div className="flex flex-wrap gap-1">
        {items.slice(0, 6).map((item: any, idx: number) => (
          <span key={`${item.entity_id || idx}`} className="px-2 py-0.5 rounded-full bg-white border border-indigo-100 text-[10px] text-gray-600">
            {item.rank}. {item.title || item.entity_id}
          </span>
        ))}
      </div>
    </div>
  );
};

const ConfirmationCard: React.FC<{ widget: any; onAction?: (payload: string) => void }> = ({ widget, onAction }) => (
  <div className="my-2 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 text-xs text-amber-800">
    <div className="font-semibold mb-1">
      <i className="fas fa-shield-alt mr-1"></i>
      {widget.title || '需要确认'}
    </div>
    <div>{widget.message || widget.content || '该动作将在您确认后由助手执行。'}</div>
    {!!widget.actions?.length && (
      <div className="mt-2 flex gap-2">
        {widget.actions.map((action: any, idx: number) => (
          <button
            key={`${action.payload || action.label}-${idx}`}
            type="button"
            onClick={() => onAction?.(action.payload || action.label)}
            className={action.variant === 'primary'
              ? 'px-3 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700'
              : 'px-3 py-1.5 rounded-lg bg-white border border-amber-200 text-amber-700 hover:bg-amber-100'}
          >
            {action.label}
          </button>
        ))}
      </div>
    )}
  </div>
);

const FollowUpActions: React.FC<{ widget: any; onAction?: (payload: string) => void }> = ({ widget, onAction }) => {
  const actions = widget.actions || widget.data || [];
  if (!actions.length) return null;
  return (
    <div className="my-2 rounded-xl border border-blue-100 bg-white px-3 py-2">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-gray-700">
        <i className="fas fa-wand-magic-sparkles text-[11px] text-blue-500"></i>
        {widget.title || '推荐下一步'}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {actions.map((a: any, idx: number) => {
          const confirmation = !!a.requiresConfirmation;
          return (
            <button
              type="button"
              onClick={() => onAction?.(a.payload || a.label || a.title)}
              key={`${a.payload || a.label || idx}`}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors ${
                confirmation
                  ? 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                  : 'border-blue-100 bg-blue-50 text-blue-600 hover:bg-blue-100'
              }`}
              title={a.description || a.payload || a.label}
            >
              <i className={`fas ${a.icon || (confirmation ? 'fa-shield-halved' : 'fa-arrow-right')} text-[10px]`}></i>
              {a.label || a.title || String(a)}
            </button>
          );
        })}
      </div>
    </div>
  );
};

const SourceCitations: React.FC<{ widget: any; onEntityClick?: (entity: any) => void }> = ({ widget, onEntityClick }) => {
  const sources = widget.sources || widget.data || [];
  if (!sources.length) return null;
  return (
    <div className="my-2 bg-gray-50 border border-gray-100 rounded-xl px-3 py-2">
      <div className="text-xs font-semibold text-gray-700 mb-1">{widget.title || '来源'}</div>
      <ul className="space-y-0.5">
        {sources.slice(0, 6).map((s: any, idx: number) => {
          const label = s.title || s.label || s.recordId || s.id || String(s);
          const href = s.url || s.href;
          const external = href && String(href).startsWith('http');
          const fields = Array.isArray(s.fields) ? s.fields : [];
          return (
            <li key={idx} className="text-[11px] text-gray-500">
              <div>
                {href && onEntityClick && !external ? (
                  <button type="button" onClick={() => onEntityClick({ url: href })} className="inline-flex max-w-full items-center gap-1 text-blue-600 hover:text-blue-700">
                    <span className="truncate">{label}</span>
                    <i className="fas fa-arrow-right text-[9px]"></i>
                  </button>
                ) : href ? (
                  <a href={href} className="inline-flex max-w-full items-center gap-1 text-blue-600 hover:text-blue-700" target={external ? '_blank' : undefined} rel="noreferrer">
                    <span className="truncate">{label}</span>
                    <i className="fas fa-arrow-up-right-from-square text-[9px]"></i>
                  </a>
                ) : label}
              </div>
              {fields.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {fields.slice(0, 4).map((field: any, fieldIdx: number) => (
                    <span key={`${field.key || field.label || fieldIdx}`} className="max-w-full rounded-md border border-gray-200 bg-white px-1.5 py-0.5 text-[10px] leading-4 text-gray-600">
                      <span className="font-medium text-gray-700">{field.label || field.key}</span>
                      <span className="mx-1 text-gray-300">·</span>
                      <span className="break-words">{String(field.value ?? '-')}</span>
                    </span>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

const CodeFallback: React.FC<{ widget: any; label: string }> = ({ widget, label }) => {
  const code = widget.code || widget.content || JSON.stringify(widget.data || {}, null, 2);
  return (
    <div className="my-2 bg-gray-900 text-gray-100 rounded-xl overflow-hidden text-xs">
      <div className="px-3 py-1.5 bg-gray-800 text-gray-300 flex items-center justify-between">
        <span>{label}</span>
        <span className="text-[10px] text-gray-400">结构化预览</span>
      </div>
      <pre className="p-3 overflow-x-auto whitespace-pre-wrap">{code}</pre>
    </div>
  );
};

const CHART_PALETTE = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#7c3aed', '#0891b2', '#db2777', '#64748b'];

const toFiniteNumber = (value: any): number => {
  const number = typeof value === 'number' ? value : Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(number) ? number : 0;
};

const truncateLabel = (value: any, max = 6): string => {
  const text = String(value ?? '');
  return text.length > max ? `${text.slice(0, max)}…` : text;
};

const normalizeChartPoint = (raw: any, index: number, categories: any[] = []): ChartDataPoint => {
  if (Array.isArray(raw)) {
    return {
      label: String(raw[0] ?? categories[index] ?? `项${index + 1}`),
      value: toFiniteNumber(raw[1]),
      color: raw[2],
    };
  }
  if (raw && typeof raw === 'object') {
    return {
      label: String(raw.name ?? raw.label ?? categories[index] ?? `项${index + 1}`),
      value: toFiniteNumber(raw.value ?? raw.count ?? raw.total),
      color: raw.color || raw.itemStyle?.color,
    };
  }
  return {
    label: String(categories[index] ?? `项${index + 1}`),
    value: toFiniteNumber(raw),
  };
};

const asArray = (value: any): any[] => {
  if (Array.isArray(value)) return value;
  if (value === undefined || value === null) return [];
  return [value];
};

const axisCategories = (option: any): any[] => {
  const xAxis = Array.isArray(option?.xAxis) ? option.xAxis[0] : option?.xAxis;
  const yAxis = Array.isArray(option?.yAxis) ? option.yAxis[0] : option?.yAxis;
  if (Array.isArray(xAxis?.data)) return xAxis.data;
  if (Array.isArray(yAxis?.data)) return yAxis.data;
  return [];
};

const normalizeEchartsWidget = (widget: any) => {
  const raw = widget.option || widget.options || widget.data || widget;
  if (Array.isArray(raw)) {
    const points = raw.map((item, index) => normalizeChartPoint(item, index));
    return {
      title: widget.title || '图表',
      type: widget.chartType || 'bar',
      series: [{ name: widget.title || '数据', type: widget.chartType || 'bar', points }],
      centerLabel: widget.centerLabel,
    };
  }

  const categories = axisCategories(raw);
  const rawSeries = asArray(raw?.series?.length ? raw.series : raw?.series);
  const fallbackData = raw?.data || widget.data || [];
  const series = (rawSeries.length ? rawSeries : [{ name: raw?.name || widget.title || '数据', type: raw?.type || widget.chartType || 'bar', data: fallbackData }])
    .map((item: any, seriesIndex: number) => {
      const data = asArray(item?.data || item?.values || fallbackData);
      return {
        name: item?.name || raw?.legend?.data?.[seriesIndex] || widget.title || `系列${seriesIndex + 1}`,
        type: item?.type || raw?.type || widget.chartType || 'bar',
        points: data.map((point, index) => normalizeChartPoint(point, index, categories)),
      };
    })
    .filter((item) => item.points.length > 0);
  const type = String(widget.chartType || series[0]?.type || raw?.type || 'bar').toLowerCase();
  const title = widget.title || raw?.title?.text || raw?.title || series[0]?.name || '图表';
  return {
    title,
    type,
    series,
    centerLabel: widget.centerLabel || raw?.centerLabel || raw?.title?.subtext,
  };
};

const EChartsWidget: React.FC<{ widget: any }> = ({ widget }) => {
  const chart = useMemo(() => normalizeEchartsWidget(widget), [widget]);
  const type = chart.type === 'doughnut' ? 'donut' : chart.type;
  const firstSeries = chart.series[0];
  if (!firstSeries?.points?.length) return <CodeFallback widget={widget} label="ECharts" />;
  if (type === 'pie' || type === 'donut') {
    return <MiniDonut data={firstSeries.points} title={chart.title} centerLabel={chart.centerLabel || '合计'} />;
  }

  const visibleSeries = chart.series.slice(0, 3).map((series, seriesIndex) => ({
    ...series,
    points: series.points.slice(0, 8),
    color: CHART_PALETTE[seriesIndex % CHART_PALETTE.length],
  }));
  const labels = visibleSeries[0].points.map((point) => point.label);
  const values = visibleSeries.flatMap((series) => series.points.map((point) => point.value));
  const rawMax = Math.max(...values, 0);
  const rawMin = Math.min(...values, 0);
  const max = rawMax === rawMin ? rawMax + 1 : rawMax;
  const min = rawMax === rawMin ? rawMin - 1 : rawMin;
  const range = max - min || 1;
  const width = 340;
  const height = 190;
  const left = 38;
  const right = 14;
  const top = 18;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const y = (value: number) => top + ((max - value) / range) * plotHeight;
  const zeroY = Math.max(top, Math.min(top + plotHeight, y(0)));
  const lineMode = type === 'line';
  const total = values.reduce((sum, value) => sum + value, 0);
  const peak = Math.max(...values);

  return (
    <div className="my-2 rounded-2xl border border-gray-100 bg-white overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-gray-100 bg-slate-50/70">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-gray-800 truncate">{chart.title}</div>
          <div className="text-[11px] text-gray-400">{lineMode ? '趋势图' : '分布图'} · {labels.length} 项</div>
        </div>
        <div className="flex flex-wrap justify-end gap-1">
          <span className="rounded-lg bg-blue-50 px-2 py-1 text-[11px] text-blue-700">峰值 {peak}</span>
          <span className="rounded-lg bg-slate-100 px-2 py-1 text-[11px] text-slate-600">合计 {total}</span>
        </div>
      </div>
      <div className="px-2.5 py-2">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-48 w-full" role="img" aria-label={chart.title}>
          {[0, 0.5, 1].map((ratio) => {
            const gridY = top + ratio * plotHeight;
            const value = Math.round(max - ratio * range);
            return (
              <g key={ratio}>
                <line x1={left} y1={gridY} x2={width - right} y2={gridY} stroke="#e5e7eb" strokeWidth="1" />
                <text x={left - 8} y={gridY + 4} textAnchor="end" fontSize="10" fill="#94a3b8">{value}</text>
              </g>
            );
          })}
          <line x1={left} y1={zeroY} x2={width - right} y2={zeroY} stroke="#cbd5e1" strokeWidth="1.2" />
          {lineMode ? (
            visibleSeries.map((series, seriesIndex) => {
              const step = series.points.length > 1 ? plotWidth / (series.points.length - 1) : plotWidth;
              const points = series.points.map((point, index) => ({
                x: left + (series.points.length > 1 ? index * step : plotWidth / 2),
                y: y(point.value),
                value: point.value,
                label: point.label,
              }));
              const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
              const area = `${path} L ${points[points.length - 1].x} ${zeroY} L ${points[0].x} ${zeroY} Z`;
              return (
                <g key={series.name || seriesIndex}>
                  {seriesIndex === 0 && <path d={area} fill={series.color} opacity="0.08" />}
                  <path d={path} fill="none" stroke={series.color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                  {points.map((point, index) => (
                    <g key={`${series.name}-${index}`}>
                      <circle cx={point.x} cy={point.y} r="4" fill="#fff" stroke={series.color} strokeWidth="2" />
                      {index === points.length - 1 && <text x={point.x + 7} y={point.y + 4} fontSize="10" fill={series.color}>{point.value}</text>}
                    </g>
                  ))}
                </g>
              );
            })
          ) : (
            visibleSeries.map((series, seriesIndex) => {
              const step = plotWidth / Math.max(series.points.length, 1);
              const groupWidth = Math.min(30, step * 0.68);
              const barWidth = Math.max(5, groupWidth / visibleSeries.length);
              return (
                <g key={series.name || seriesIndex}>
                  {series.points.map((point, index) => {
                    const barHeight = Math.abs(zeroY - y(point.value));
                    const x = left + index * step + (step - groupWidth) / 2 + seriesIndex * barWidth;
                    const barY = Math.min(zeroY, y(point.value));
                    return (
                      <g key={`${series.name}-${point.label}-${index}`}>
                        <rect x={x} y={barY} width={barWidth - 1} height={Math.max(2, barHeight)} rx="3" fill={point.color || series.color} opacity="0.9" />
                        {visibleSeries.length === 1 && <text x={x + barWidth / 2} y={barY - 4} textAnchor="middle" fontSize="10" fill="#475569">{point.value}</text>}
                      </g>
                    );
                  })}
                </g>
              );
            })
          )}
          {labels.map((label, index) => {
            const step = plotWidth / Math.max(labels.length, 1);
            const x = lineMode && labels.length > 1 ? left + index * (plotWidth / (labels.length - 1)) : left + index * step + step / 2;
            return (
              <text key={`${label}-${index}`} x={x} y={height - 18} textAnchor="middle" fontSize="10" fill="#64748b">
                {truncateLabel(label)}
              </text>
            );
          })}
        </svg>
        {visibleSeries.length > 1 && (
          <div className="flex flex-wrap gap-1.5 px-1 pb-1">
            {visibleSeries.map((series) => (
              <span key={series.name} className="inline-flex items-center gap-1 rounded-lg bg-gray-50 px-2 py-1 text-[11px] text-gray-600">
                <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: series.color }} />
                {series.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const ClarificationWidget: React.FC<{ widget: any; onAction?: (payload: string) => void }> = ({ widget, onAction }) => {
  const options = widget.options || [];
  return (
    <div className="my-2 bg-blue-50 border border-blue-100 rounded-xl px-3 py-2 text-xs text-blue-700">
      <div className="font-semibold mb-1">{widget.question || widget.message || '请进一步确认'}</div>
      {options.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {options.map((o: any, idx: number) => (
            <button type="button" onClick={() => onAction?.(o.payload || o.label)} key={idx} className="px-2 py-1 rounded-lg bg-white border border-blue-100 text-blue-600 hover:bg-blue-100">
              {o.label || o.payload}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const TimelineWidget: React.FC<{ widget: any; onEntityClick?: (entity: any) => void }> = ({ widget, onEntityClick }) => {
  const items = widget.items || widget.data || [];
  if (!items.length) return null;
  const statusStyle: Record<string, string> = {
    done: 'bg-green-100 text-green-600',
    success: 'bg-green-100 text-green-600',
    warning: 'bg-amber-100 text-amber-600',
    danger: 'bg-red-100 text-red-600',
    active: 'bg-blue-100 text-blue-600',
    pending: 'bg-gray-100 text-gray-500',
    default: 'bg-slate-100 text-slate-500',
  };
  return (
    <div className="my-2 rounded-xl border border-gray-100 bg-white px-3 py-2">
      {widget.title && <div className="text-xs font-semibold text-gray-800 mb-2">{widget.title}</div>}
      <div className="space-y-2">
        {items.slice(0, 10).map((item: any, idx: number) => {
          const style = statusStyle[item.status] || statusStyle.default;
          return (
            <button
              key={`${item.title || idx}`}
              type="button"
              onClick={() => item.url && onEntityClick?.({ url: item.url })}
              className="w-full grid grid-cols-[auto_1fr] gap-2 text-left group"
            >
              <div className="flex flex-col items-center">
                <span className={`w-7 h-7 rounded-full flex items-center justify-center ${style}`}>
                  <i className={`fas ${item.icon || 'fa-circle'} text-[10px]`}></i>
                </span>
                {idx < Math.min(items.length, 10) - 1 && <span className="w-px flex-1 bg-gray-100 mt-1"></span>}
              </div>
              <div className="min-w-0 pb-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-medium text-gray-800 truncate group-hover:text-blue-600">{item.title || item.label || '-'}</span>
                  {item.time && <span className="text-[10px] text-gray-400 flex-shrink-0">{item.time}</span>}
                </div>
                {item.description && <div className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">{item.description}</div>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};

const ComparisonMatrix: React.FC<{ widget: any }> = ({ widget }) => {
  const columns = widget.columns || [];
  const rows = widget.rows || widget.data || [];
  if (!columns.length || !rows.length) return null;
  return (
    <div className="my-2 rounded-xl border border-gray-100 bg-white overflow-hidden">
      {widget.title && <div className="px-3 py-2 text-xs font-semibold text-gray-800 border-b border-gray-100">{widget.title}</div>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50">
            <tr>
              {columns.slice(0, 6).map((col: any) => (
                <th key={col.key || col.label} className="px-2.5 py-2 text-left font-medium text-gray-600 whitespace-nowrap">
                  {col.label || col.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 8).map((row: any, idx: number) => (
              <tr key={idx} className="border-t border-gray-50 hover:bg-blue-50/20">
                {columns.slice(0, 6).map((col: any) => (
                  <td key={col.key || col.label} className="px-2.5 py-2 text-gray-700 whitespace-nowrap">
                    {row[col.key] ?? row[col.label] ?? '-'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const StatusBadges: React.FC<{ widget: any }> = ({ widget }) => {
  const items = widget.items || widget.data || [];
  if (!items.length) return null;
  const styles: Record<string, string> = {
    success: 'bg-green-50 border-green-100 text-green-700',
    normal: 'bg-green-50 border-green-100 text-green-700',
    warning: 'bg-amber-50 border-amber-100 text-amber-700',
    danger: 'bg-red-50 border-red-100 text-red-700',
    risk: 'bg-red-50 border-red-100 text-red-700',
    active: 'bg-blue-50 border-blue-100 text-blue-700',
    neutral: 'bg-gray-50 border-gray-100 text-gray-600',
  };
  return (
    <div className="my-2 rounded-xl border border-gray-100 bg-white px-3 py-2">
      {widget.title && <div className="text-xs font-semibold text-gray-800 mb-2">{widget.title}</div>}
      <div className="flex flex-wrap gap-1.5">
        {items.slice(0, 12).map((item: any, idx: number) => {
          const cls = styles[item.status] || styles.neutral;
          return (
            <span key={`${item.label || idx}`} className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] ${cls}`} title={item.hint || ''}>
              <i className={`fas ${item.icon || 'fa-circle'} text-[9px]`}></i>
              {item.label}
              {item.value !== undefined && <strong className="font-semibold">{item.value}</strong>}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const MediaPreview: React.FC<{ widget: any }> = ({ widget }) => {
  const items = widget.items || widget.data || [];
  if (!items.length) return null;
  return (
    <div className="my-2 rounded-xl border border-gray-100 bg-white px-3 py-2">
      {widget.title && <div className="text-xs font-semibold text-gray-800 mb-2">{widget.title}</div>}
      <div className="grid grid-cols-2 gap-2">
        {items.slice(0, 4).map((item: any, idx: number) => {
          const isImage = /image|png|jpg|jpeg|webp|gif/i.test(item.mimeType || item.url || '');
          return (
            <a key={`${item.url || idx}`} href={item.url} target="_blank" rel="noreferrer" className="rounded-xl border border-gray-100 overflow-hidden hover:border-blue-200 hover:shadow-sm transition-all bg-gray-50">
              {isImage ? (
                <img src={item.thumbnail || item.url} alt={item.title || ''} className="h-24 w-full object-cover bg-gray-100" />
              ) : (
                <div className="h-24 flex items-center justify-center bg-blue-50 text-blue-500">
                  <i className="fas fa-file-lines text-2xl"></i>
                </div>
              )}
              <div className="px-2 py-1.5">
                <div className="text-[11px] font-medium text-gray-700 truncate">{item.title || '附件'}</div>
                {item.description && <div className="text-[10px] text-gray-400 truncate">{item.description}</div>}
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
};

export const ChatWidget: React.FC<{
  widget: RichWidget;
  onEntityClick?: (entity: any) => void;
  onAction?: (payload: string) => void;
}> = ({ widget, onEntityClick, onAction }) => {
  if (!widget) return null;
  switch (widget.type) {
    case 'metrics':
    case 'metric_cards': {
      const metrics = (widget.metrics || (widget as any).cards || []) as MetricItem[];
      const title = widget.title;
      if (!title) {
        return <MetricCards metrics={metrics} />;
      }
      // 带标题：包裹一个圆角容器，顶部带"标题 + 副标题 + 装饰图标"的头部
      return (
        <div className="my-2 bg-white border border-gray-100 rounded-2xl overflow-hidden">
          <div className="relative flex items-center gap-2.5 px-4 py-3 border-b border-gray-100">
            <div className="w-9 h-9 rounded-xl bg-blue-100 flex items-center justify-center flex-shrink-0">
              <i className="fas fa-chart-bar text-blue-600 text-base"></i>
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-gray-800">{title}</div>
              <div className="text-[11px] text-gray-500 mt-0.5">关键指标实时汇总</div>
            </div>
            {/* 装饰背景图标（淡） */}
            <div className="absolute right-3 top-1/2 -translate-y-1/2 flex gap-1 opacity-40 pointer-events-none">
              <i className="fas fa-chart-pie text-purple-300 text-2xl"></i>
              <i className="fas fa-chart-line text-blue-300 text-2xl"></i>
            </div>
          </div>
          <div className="px-3 pb-3 pt-2">
            <MetricCards metrics={metrics} />
          </div>
        </div>
      );
    }
    case 'bar':
    case 'bar_chart':
      return <MiniBarChart data={widget.data || []} title={widget.title} />;
    case 'donut':
    case 'doughnut_chart':
      return <MiniDonut data={widget.data || []} title={widget.title} centerLabel={widget.centerLabel} />;
    case 'table':
    case 'data_table':
      return <DataTable table={widget.table || { columns: [], rows: [] }} />;
    case 'entity_cards':
      return <EntityCardsList widget={widget} onPick={onEntityClick} />;
    case 'warning':
      return <Warning widget={widget} />;
    case 'markdown':
      return <MarkdownWidget widget={widget} />;
    case 'workset_summary':
      return <WorksetSummary widget={widget} />;
    case 'confirmation_card':
      return <ConfirmationCard widget={widget} onAction={onAction} />;
    case 'follow_up_actions':
      return <FollowUpActions widget={widget} onAction={onAction} />;
    case 'source_citations':
      return <SourceCitations widget={widget} onEntityClick={onEntityClick} />;
    case 'mermaid_diagram':
      return <CodeFallback widget={widget} label="Mermaid" />;
    case 'echarts':
      return <EChartsWidget widget={widget} />;
    case 'clarification':
      return <ClarificationWidget widget={widget} onAction={onAction} />;
    case 'timeline':
      return <TimelineWidget widget={widget} onEntityClick={onEntityClick} />;
    case 'comparison_matrix':
      return <ComparisonMatrix widget={widget} />;
    case 'status_badges':
      return <StatusBadges widget={widget} />;
    case 'media_preview':
      return <MediaPreview widget={widget} />;
    default:
      return null;
  }
};

export default ChatWidget;
