import { type CSSProperties, useEffect, useMemo, useState } from 'react';

type ViewMode = 'business' | 'department';

interface MetricDatum {
  label: string;
  value: number;
  accent: string;
  tint: string;
  hint: string;
}

interface OperationsMetricFieldProps {
  cards: Record<string, number>;
  departments: Array<{ name: string; value: number }>;
}

const PALETTE = [
  { accent: '#2a78dc', tint: '#ebf3ff' },
  { accent: '#14a293', tint: '#e8faf6' },
  { accent: '#6477dd', tint: '#eef0ff' },
  { accent: '#ea9335', tint: '#fff4e6' },
  { accent: '#18a286', tint: '#e8faf4' },
  { accent: '#8064d5', tint: '#f2eeff' },
  { accent: '#db6376', tint: '#fff0f3' },
  { accent: '#3689c6', tint: '#ebf6ff' },
  { accent: '#23a572', tint: '#ebfaf2' },
  { accent: '#d78c36', tint: '#fff5e9' },
];

const formatNumber = (value: number) => value.toLocaleString('zh-CN');
const formatMoney = (value: number) => `¥${Math.round(value || 0).toLocaleString('zh-CN')}`;

const OperationsMetricField = ({ cards, departments }: OperationsMetricFieldProps) => {
  const [mode, setMode] = useState<ViewMode>('business');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const businessData = useMemo<MetricDatum[]>(() => ([
    { label: '员工总数', value: cards.activeEmployees || 0, ...PALETTE[0], hint: '在职' },
    { label: '在招岗位', value: cards.openJobs || 0, ...PALETTE[1], hint: '开放' },
    { label: '简历池', value: cards.resumes || 0, ...PALETTE[2], hint: '累计' },
    { label: '面试', value: cards.interviews || 0, ...PALETTE[3], hint: '累计' },
    { label: 'Offer', value: cards.offers || 0, ...PALETTE[4], hint: '累计' },
    { label: '待入职', value: cards.pendingOnboard || 0, ...PALETTE[5], hint: '队列' },
    { label: '本月入职', value: cards.monthOnboard || 0, ...PALETTE[6], hint: '新增' },
    { label: '本月离职', value: cards.monthResigned || 0, ...PALETTE[7], hint: '变动' },
    { label: '待审批', value: cards.requests || 0, ...PALETTE[8], hint: '申请' },
    { label: '考勤异常', value: cards.attendanceExceptions || 0, ...PALETTE[9], hint: '关注' },
  ]), [cards]);

  const departmentData = useMemo<MetricDatum[]>(() => {
    const entries = departments.slice(0, 10);
    if (entries.length === 0) return [];
    return entries.map((department, index) => ({
      label: department.name || '未设置',
      value: department.value || 0,
      ...PALETTE[index % PALETTE.length],
      hint: '人数',
    }));
  }, [departments]);

  const data = mode === 'business' ? businessData : departmentData;
  const maximum = Math.max(...data.map((datum) => datum.value), 1);
  const highestIndex = data.length > 0 ? data.reduce((best, datum, index, entries) => datum.value > entries[best].value ? index : best, 0) : null;
  const focusedIndex = hoveredIndex === null ? highestIndex : hoveredIndex;
  const focused = focusedIndex === null ? null : data[focusedIndex];

  useEffect(() => setHoveredIndex(null), [mode]);

  return (
    <section className="ops-metric-panel" aria-label="运营指标视图">
      <header className="ops-volume-head">
        <div>
          <h3>运营指标视图</h3>
          <p>完整业务量级与组织分布，悬停查看关键值</p>
        </div>
        <div className="ops-volume-controls" role="tablist" aria-label="数据视角">
          <button type="button" role="tab" aria-selected={mode === 'business'} className={mode === 'business' ? 'is-selected' : ''} onClick={() => setMode('business')}>业务全量</button>
          <button type="button" role="tab" aria-selected={mode === 'department'} className={mode === 'department' ? 'is-selected' : ''} onClick={() => setMode('department')}>部门结构</button>
        </div>
      </header>

      <div className="ops-volume-brief">
        <div><span>本月人力成本</span><strong>{formatMoney(cards.payrollTotal)}</strong></div>
        <div><span>人员净流入</span><strong>{(cards.monthOnboard || 0) - (cards.monthResigned || 0) >= 0 ? '+' : ''}{formatNumber((cards.monthOnboard || 0) - (cards.monthResigned || 0))}</strong></div>
        <div><span>当前聚焦</span><strong>{focused ? focused.label : '暂无部门人数数据'}</strong></div>
      </div>

      {data.length === 0 ? (
        <div className="ops-metric-empty">
          <strong>尚无部门人数数据</strong>
          <span>录入员工部门归属后，这里将自动形成结构对比。</span>
        </div>
      ) : (
        <>
          <div className="ops-metric-stage" data-testid="operations-metric-field">
            <div className="ops-metric-plane" aria-hidden="true" />
            <div className="ops-metric-bars" style={{ gridTemplateColumns: `repeat(${data.length}, minmax(64px, 1fr))` }} role="img" aria-label={`${mode === 'business' ? '业务全量' : '部门结构'}指标对比`}>
              {data.map((datum, index) => {
                const proportion = datum.value === 0 ? 0.04 : Math.max(0.12, datum.value / maximum);
                const properties = {
                  '--metric-height': `${proportion * 100}%`,
                  '--metric-accent': datum.accent,
                  '--metric-tint': datum.tint,
                  '--metric-delay': `${index * 32}ms`,
                } as CSSProperties;
                return (
                  <button
                    key={`${datum.label}-${index}`}
                    type="button"
                    className={`ops-metric-column ${focusedIndex === index ? 'is-active' : ''}`}
                    style={properties}
                    onMouseEnter={() => setHoveredIndex(index)}
                    onFocus={() => setHoveredIndex(index)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    onBlur={() => setHoveredIndex(null)}
                    aria-label={`${datum.label} ${formatNumber(datum.value)}`}
                  >
                    <span className="ops-metric-number">{formatNumber(datum.value)}</span>
                    <span className="ops-metric-track">
                      <span className="ops-metric-prism" />
                    </span>
                    <span className="ops-metric-label">{datum.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className={`ops-volume-legend ${mode === 'department' ? 'is-department' : ''}`}>
            {data.map((datum, index) => (
              <button
                key={`legend-${datum.label}-${index}`}
                type="button"
                className={focusedIndex === index ? 'is-active' : ''}
                style={{ '--metric-tint': datum.tint } as CSSProperties}
                onMouseEnter={() => setHoveredIndex(index)}
                onFocus={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                onBlur={() => setHoveredIndex(null)}
              >
                <i style={{ background: datum.accent }} />
                <span>{datum.label}</span>
                <strong>{formatNumber(datum.value)}</strong>
                <small>{datum.hint}</small>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
};

export default OperationsMetricField;
