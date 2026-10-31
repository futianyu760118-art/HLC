// @ts-nocheck
/**
 * 轻量级富文本渲染：把 LLM 输出的简单 Markdown 渲染为美观 React 节点。
 *
 * 支持：
 * - **粗体** / __粗体__
 * - *斜体* / _斜体_（需在词内非空白处，避免误吃列表"* "前缀）
 * - `行内代码`
 * - 行首 - / * / • 的无序列表
 * - 行首 1. / 1) 的有序列表
 * - 行首 > 的引用块
 * - 数字+冒号或【标签】视为强调（不需要 markdown 也能加亮）
 *
 * 不依赖第三方库。XSS 安全：所有渲染都走 React 文本节点，不注入 HTML 字符串。
 */
import React from 'react';
import { DataTable } from './ChatRichWidgets';

interface RichTextProps {
  text: string;
  className?: string;
}

// ---------- 行内格式：粗体 / 斜体 / 行内代码 ----------
const INLINE_PATTERN = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\n\s][^*\n]*\*|_[^_\n\s][^_\n]*_)/g;

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  if (!text) return [];
  const parts = text.split(INLINE_PATTERN);
  return parts.map((part, idx) => {
    const key = `${keyPrefix}-${idx}`;
    if (!part) return null;
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('__') && part.endsWith('__')) {
      return <strong key={key} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={key} className="px-1 py-0.5 bg-gray-200/60 text-blue-700 rounded text-[12px] font-mono">
          {part.slice(1, -1)}
        </code>
      );
    }
    // 单星号/单下划线斜体（避免误吃列表前缀）
    if (
      (part.startsWith('*') && part.endsWith('*') && part.length > 2 && !part.startsWith('**')) ||
      (part.startsWith('_') && part.endsWith('_') && part.length > 2 && !part.startsWith('__'))
    ) {
      return <em key={key} className="italic">{part.slice(1, -1)}</em>;
    }
    return <span key={key}>{part}</span>;
  }).filter(Boolean);
}

// ---------- 块级解析：分组连续列表项 ----------
type Block =
  | { type: 'bullet'; items: string[] }
  | { type: 'ordered'; items: string[] }
  | { type: 'quote'; lines: string[] }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'heading'; text: string; level: number }
  | { type: 'paragraph'; text: string };

const BULLET_RE = /^\s*(?:[-*•·]|\u2022)\s+(.+)$/;
const ORDERED_RE = /^\s*(\d+)[.)、]\s*(.+)$/;
const QUOTE_RE = /^\s*>\s?(.*)$/;
const HEADING_RE = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const TABLE_ROW_RE = /^\s*\|(.+)\|\s*$/;
const TABLE_SEPARATOR_RE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/;

function splitTableCells(line: string): string[] {
  // 去掉首尾的 |，再按 | 分割
  const inner = line.trim().replace(/^\||\|$/g, '');
  return inner.split('|').map((c) => c.trim());
}

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let current: Block | null = null;
  let paragraphBuf: string[] = [];

  const flushParagraph = () => {
    if (paragraphBuf.length) {
      const merged = paragraphBuf.join(' ').trim();
      if (merged) blocks.push({ type: 'paragraph', text: merged });
      paragraphBuf = [];
    }
  };

  for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
    const raw = lines[lineIdx];
    const line = raw;
    if (!line.trim()) {
      // 空行 → 关闭当前块
      flushParagraph();
      if (current) {
        blocks.push(current);
        current = null;
      }
      continue;
    }

    const hm = line.match(HEADING_RE);
    if (hm) {
      flushParagraph();
      if (current) {
        blocks.push(current);
        current = null;
      }
      blocks.push({ type: 'heading', text: hm[2], level: hm[1].length });
      continue;
    }

    // 表格识别：当前行是表格行，且下一行是分隔符
    if (TABLE_ROW_RE.test(line)) {
      const next = lines[lineIdx + 1];
      if (next && TABLE_SEPARATOR_RE.test(next)) {
        flushParagraph();
        if (current) {
          blocks.push(current);
          current = null;
        }
        const headers = splitTableCells(line);
        const rows: string[][] = [];
        // 跳过分隔符行
        let scan = lineIdx + 2;
        while (scan < lines.length && TABLE_ROW_RE.test(lines[scan])) {
          rows.push(splitTableCells(lines[scan]));
          scan++;
        }
        blocks.push({ type: 'table', headers, rows });
        lineIdx = scan - 1;
        continue;
      }
    }

    const bm = line.match(BULLET_RE);
    const om = line.match(ORDERED_RE);
    const qm = line.match(QUOTE_RE);

    if (bm) {
      flushParagraph();
      if (!current || current.type !== 'bullet') {
        if (current) blocks.push(current);
        current = { type: 'bullet', items: [] };
      }
      (current as any).items.push(bm[1]);
      continue;
    }
    if (om) {
      flushParagraph();
      if (!current || current.type !== 'ordered') {
        if (current) blocks.push(current);
        current = { type: 'ordered', items: [] };
      }
      (current as any).items.push(om[2]);
      continue;
    }
    if (qm) {
      flushParagraph();
      if (!current || current.type !== 'quote') {
        if (current) blocks.push(current);
        current = { type: 'quote', lines: [] };
      }
      (current as any).lines.push(qm[1]);
      continue;
    }
    // 非列表/引用/表格 → 段落
    if (current) {
      blocks.push(current);
      current = null;
    }
    paragraphBuf.push(line.trim());
  }

  flushParagraph();
  if (current) blocks.push(current);
  return blocks;
}

// ---------- 渲染入口 ----------
export const RichText: React.FC<RichTextProps> = ({ text, className }) => {
  if (!text) return null;
  const blocks = parseBlocks(text);

  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.type === 'bullet') {
          return (
            <ul key={i} className="my-1 space-y-0.5 list-none">
              {block.items.map((item, j) => (
                <li key={j} className="flex gap-1.5 items-start text-sm leading-relaxed">
                  <span className="text-blue-400 mt-1.5 flex-shrink-0 w-1 h-1 rounded-full bg-blue-400" />
                  <span className="flex-1">{renderInline(item, `${i}-${j}`)}</span>
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === 'ordered') {
          return (
            <ol key={i} className="my-1 space-y-0.5 list-none">
              {block.items.map((item, j) => (
                <li key={j} className="flex gap-1.5 items-start text-sm leading-relaxed">
                  <span className="text-blue-500 font-medium flex-shrink-0 min-w-[18px]">{j + 1}.</span>
                  <span className="flex-1">{renderInline(item, `${i}-${j}`)}</span>
                </li>
              ))}
            </ol>
          );
        }
        if (block.type === 'quote') {
          return (
            <blockquote key={i} className="my-1 pl-3 border-l-2 border-blue-300 text-gray-600 text-sm">
              {block.lines.map((ln, j) => (
                <div key={j}>{renderInline(ln, `${i}-${j}`)}</div>
              ))}
            </blockquote>
          );
        }
        if (block.type === 'table') {
          // 把 Markdown 表格转成 DataTable 数据
          const columns = block.headers.map((h, idx) => ({ key: `c${idx}`, label: h || `列${idx + 1}` }));
          const rows = block.rows.map((cells) => {
            const row: Record<string, string> = {};
            block.headers.forEach((_, idx) => {
              row[`c${idx}`] = cells[idx] || '';
            });
            return row;
          });
          return <DataTable key={i} table={{ columns, rows }} />;
        }
        if (block.type === 'heading') {
          return (
            <div key={i} className={`${block.level <= 2 ? 'text-sm' : 'text-[13px]'} font-semibold text-gray-900 mt-2 mb-1 first:mt-0`}>
              {renderInline(block.text, `${i}`)}
            </div>
          );
        }
        // paragraph
        return (
          <p key={i} className="text-sm leading-relaxed my-1 first:mt-0 last:mb-0">
            {renderInline(block.text, `${i}`)}
          </p>
        );
      })}
    </div>
  );
};

export default RichText;
