import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import AppIcon from './AppIcon';

export type FilterOption = {
  label: string;
  value: string;
  meta?: string;
};

type RawFilterOption =
  | string
  | number
  | {
      label?: unknown;
      name?: unknown;
      title?: unknown;
      value?: unknown;
      id?: unknown;
      meta?: unknown;
    };

type RangeValue = {
  from?: string;
  to?: string;
};

export type FilterFieldType =
  | 'select'
  | 'combo'
  | 'segment'
  | 'text'
  | 'date'
  | 'month'
  | 'date-range'
  | 'datetime-range'
  | 'number-range';

type TextFilterFieldProps = {
  label: string;
  type?: Exclude<FilterFieldType, 'date-range' | 'datetime-range' | 'number-range'>;
  value: string | number | null | undefined;
  onChange: (value: string) => void;
  options?: FilterOption[];
  placeholder?: string;
  searchable?: boolean;
  inputType?: string;
  allLabel?: string;
  className?: string;
};

type RangeFilterFieldProps = {
  label: string;
  type: 'date-range' | 'datetime-range' | 'number-range';
  value: RangeValue | null | undefined;
  onChange: (value: RangeValue) => void;
  options?: FilterOption[];
  placeholder?: string;
  searchable?: boolean;
  inputType?: string;
  allLabel?: string;
  className?: string;
};

type FilterFieldProps = TextFilterFieldProps | RangeFilterFieldProps;

const normalize = (value: unknown) => String(value ?? '').trim().toLowerCase();

const normalizeContextKey = (value: string) => value
  .trim()
  .replace(/\s+/g, '-')
  .replace(/[^\w\u4e00-\u9fa5-]/g, '-')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')
  .toLowerCase();

const displayRangeValue = (value: RangeValue | null | undefined) => {
  const from = String(value?.from || '').trim();
  const to = String(value?.to || '').trim();
  if (from && to) return `${from} 至 ${to}`;
  return from || to;
};

const dataContextProps = (
  label: string,
  value: string | number | null | undefined,
  display?: string,
  contextKey = label,
) => {
  const rawValue = String(value ?? '').trim();
  const displayValue = String(display ?? rawValue).trim();
  return {
    'data-hpt-filter': normalizeContextKey(contextKey) || contextKey,
    'data-hpt-filter-label': label,
    'data-hpt-filter-value': rawValue,
    'data-hpt-filter-display': displayValue,
  };
};

const fuzzyScore = (option: FilterOption, query: string) => {
  const label = normalize(option.label);
  const value = normalize(option.value);
  const meta = normalize(option.meta);
  const text = `${label} ${value} ${meta}`;
  if (!query) return 1;
  if (label === query || value === query) return 120;
  if (label.includes(query)) return 100 - label.indexOf(query);
  if (value.includes(query)) return 88 - value.indexOf(query);
  if (meta.includes(query)) return 72 - meta.indexOf(query);

  let cursor = 0;
  let hits = 0;
  for (const char of query) {
    const next = text.indexOf(char, cursor);
    if (next === -1) return 0;
    hits += 1;
    cursor = next + 1;
  }
  return hits >= Math.min(query.length, 2) ? 38 + hits : 0;
};

export const toFilterOptions = (items: RawFilterOption[] = []): FilterOption[] => items.map((item) => {
  if (typeof item === 'string' || typeof item === 'number') {
    return { label: String(item), value: String(item) };
  }
  return {
    label: String(item.label ?? item.name ?? item.title ?? item.value ?? ''),
    value: String(item.value ?? item.id ?? item.label ?? ''),
    meta: item.meta === undefined || item.meta === null ? undefined : String(item.meta),
  };
}).filter((item) => item.label && item.value);

export function SearchInput({
  value,
  onChange,
  placeholder = '搜索...',
  className = '',
  contextLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  contextLabel?: string;
}) {
  const label = contextLabel || placeholder.replace(/^搜索/, '').replace(/[.。…]+$/g, '') || '搜索';
  return (
    <div className={`hpt-search-box ${className}`} {...dataContextProps(label, value, value, 'search')}>
      <AppIcon className="fas fa-search hpt-search-icon" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="hpt-control hpt-search-input"
      />
    </div>
  );
}

export function SmartSelect({
  value,
  onChange,
  options = [],
  placeholder = '请选择',
  searchable = false,
  clearable = true,
  disabled = false,
  emptyText = '没有匹配选项',
  className = '',
}: {
  value?: string;
  onChange: (value: string) => void;
  options: FilterOption[];
  placeholder?: string;
  searchable?: boolean;
  clearable?: boolean;
  disabled?: boolean;
  emptyText?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const selected = options.find((option) => String(option.value) === String(value));

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, []);

  useEffect(() => {
    if (open && searchable) {
      setTimeout(() => searchRef.current?.focus(), 30);
    }
    if (!open) setQuery('');
  }, [open, searchable]);

  const visibleOptions = useMemo(() => {
    const q = normalize(query);
    if (!q) return options;
    return options
      .map((option) => ({ option, score: fuzzyScore(option, q) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.option.label.localeCompare(b.option.label, 'zh-CN'))
      .map((item) => item.option);
  }, [options, query]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={`hpt-smart-select-wrap ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
        }}
        className={`hpt-control hpt-smart-select ${open ? 'is-open' : ''} ${!selected ? 'is-empty' : ''}`}
      >
        <span className="hpt-smart-select-value">{selected?.label || placeholder}</span>
        <span className="hpt-smart-select-tools">
          {clearable && value && (
            <span
              role="button"
              aria-label="清除选择"
              tabIndex={-1}
              onClick={(event) => {
                event.stopPropagation();
                onChange('');
              }}
              className="hpt-smart-select-clear"
            >
              <AppIcon className="fas fa-xmark" />
            </span>
          )}
          <AppIcon className={`fas fa-chevron-down hpt-smart-select-arrow ${open ? 'is-open' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="hpt-select-menu">
          {searchable && (
            <div className="hpt-select-search">
              <AppIcon className="fas fa-magnifying-glass" />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="输入关键词筛选"
              />
            </div>
          )}
          <div className="hpt-select-options">
            {visibleOptions.length === 0 ? (
              <div className="hpt-select-empty">{emptyText}</div>
            ) : visibleOptions.map((option) => {
              const active = String(option.value) === String(value);
              return (
                <button
                  type="button"
                  key={option.value}
                  onClick={() => choose(String(option.value))}
                  className={`hpt-select-option ${active ? 'is-active' : ''}`}
                >
                  <span className="min-w-0">
                    <span className="hpt-select-option-label">{option.label}</span>
                    {option.meta && <span className="hpt-select-option-meta">{option.meta}</span>}
                  </span>
                  {active && <AppIcon className="fas fa-check hpt-select-check" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function FilterField(props: RangeFilterFieldProps): ReactElement;
export function FilterField(props: TextFilterFieldProps): ReactElement;
export function FilterField(props: FilterFieldProps): ReactElement {
  const {
    label,
    type = 'select',
    options = [],
    placeholder,
    searchable,
    inputType,
    allLabel = '全部',
    className = '',
  } = props;
  const rangeType = type === 'number-range' ? 'number' : type === 'datetime-range' ? 'datetime-local' : 'date';

  if (type === 'segment') {
    const { value, onChange } = props as TextFilterFieldProps;
    const items = [{ label: allLabel, value: '' }, ...options];
    const selected = items.find((option) => String(option.value) === String(value || ''));
    return (
      <div className={`hpt-filter-field ${className}`} {...dataContextProps(label, value, selected?.label)}>
        <span className="hpt-filter-label">{label}</span>
        <div className="hpt-segmented-filter">
          {items.map((option) => (
            <button
              key={option.value || '__all'}
              type="button"
              onClick={() => onChange(option.value)}
              className={String(value || '') === String(option.value) ? 'is-active' : ''}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (type === 'date-range' || type === 'datetime-range' || type === 'number-range') {
    const { value, onChange } = props as RangeFilterFieldProps;
    const rangeValue: RangeValue = value || {};
    const displayValue = displayRangeValue(rangeValue);
    return (
      <div className={`hpt-filter-field ${className}`} {...dataContextProps(label, displayValue, displayValue)}>
        <span className="hpt-filter-label">{label}</span>
        <div className="hpt-range-control">
          <input
            type={rangeType}
            value={rangeValue.from || ''}
            onChange={(event) => onChange({ ...rangeValue, from: event.target.value })}
            placeholder="起"
            className="hpt-control"
          />
          <span>至</span>
          <input
            type={rangeType}
            value={rangeValue.to || ''}
            onChange={(event) => onChange({ ...rangeValue, to: event.target.value })}
            placeholder="止"
            className="hpt-control"
          />
        </div>
      </div>
    );
  }

  if (type === 'text' || type === 'date' || type === 'month') {
    const { value, onChange } = props as TextFilterFieldProps;
    return (
      <label className={`hpt-filter-field ${className}`} {...dataContextProps(label, value)}>
        <span className="hpt-filter-label">{label}</span>
        <input
          type={inputType || (type === 'text' ? 'text' : type)}
          value={String(value || '')}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder || `输入${label}`}
          className="hpt-control"
        />
      </label>
    );
  }

  const { value, onChange } = props as TextFilterFieldProps;
  const selected = options.find((option) => String(option.value) === String(value || ''));
  return (
    <div className={`hpt-filter-field ${className}`} {...dataContextProps(label, value, selected?.label)}>
      <span className="hpt-filter-label">{label}</span>
      <SmartSelect
        value={String(value || '')}
        onChange={onChange}
        options={options}
        searchable={type === 'combo' || searchable}
        placeholder={placeholder || `全部${label}`}
      />
    </div>
  );
}
