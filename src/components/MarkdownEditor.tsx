// @ts-nocheck
/**
 * Markdown 编辑器组件 — 左编辑右预览 + 工具栏
 */
import React, { useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import AppIcon from './AppIcon';

/** 兼容旧调用：不再返回 HTML，避免调用方误用未消毒字符串。 */
export function renderMarkdown(md: string): string {
  return md || '';
}

/** Markdown 渲染组件（只读展示） */
export const MarkdownRenderer: React.FC<{ content: string; className?: string }> = ({ content, className }) => (
  <div className={`md-render ${className || ''}`}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        h1: ({ children }) => <h1 className="md-h1">{children}</h1>,
        h2: ({ children }) => <h2 className="md-h2">{children}</h2>,
        h3: ({ children }) => <h3 className="md-h3">{children}</h3>,
        p: ({ children }) => <p className="md-p">{children}</p>,
        a: ({ href, children }) => (
          <a href={href || '#'} target="_blank" rel="noreferrer" className="md-link">{children}</a>
        ),
        img: ({ src, alt }) => <img src={src || ''} alt={alt || ''} className="md-img" />,
        code: ({ children, className: codeClassName }) => (
          <code className={codeClassName ? `md-code ${codeClassName}` : 'md-inline-code'}>{children}</code>
        ),
        pre: ({ children }) => <pre className="md-code">{children}</pre>,
        blockquote: ({ children }) => <blockquote className="md-quote">{children}</blockquote>,
        ul: ({ children }) => <ul className="md-ul">{children}</ul>,
        hr: () => <hr className="md-hr" />,
      }}
    >
      {content || ''}
    </ReactMarkdown>
  </div>
);

/** Markdown 编辑器（左编辑右预览 + 工具栏） */
export const MarkdownEditor: React.FC<{
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}> = ({ value, onChange, placeholder, rows = 6 }) => {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const [showPreview, setShowPreview] = useState(false);

  const insert = (before: string, after: string = '', placeholderText = '') => {
    const ta = taRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = value.substring(start, end) || placeholderText;
    const newValue = value.substring(0, start) + before + selected + after + value.substring(end);
    onChange(newValue);
    setTimeout(() => {
      ta.focus();
      ta.selectionStart = start + before.length;
      ta.selectionEnd = start + before.length + selected.length;
    }, 0);
  };

  const insertLine = (prefix: string) => {
    const ta = taRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const lineStart = value.lastIndexOf('\n', start - 1) + 1;
    const newValue = value.substring(0, lineStart) + prefix + value.substring(lineStart);
    onChange(newValue);
    setTimeout(() => ta.focus(), 0);
  };

  const tools = [
    { icon: 'fa-heading', title: '标题', action: () => insertLine('### ') },
    { icon: 'fa-bold', title: '加粗', action: () => insert('**', '**', '加粗文字') },
    { icon: 'fa-italic', title: '斜体', action: () => insert('*', '*', '斜体') },
    { icon: 'fa-list-ul', title: '无序列表', action: () => insertLine('- ') },
    { icon: 'fa-list-ol', title: '有序列表', action: () => insertLine('1. ') },
    { icon: 'fa-quote-right', title: '引用', action: () => insertLine('> ') },
    { icon: 'fa-link', title: '链接', action: () => insert('[', '](https://)', '链接文字') },
    { icon: 'fa-image', title: '图片', action: () => insert('![', '](https://)', '图片描述') },
    { icon: 'fa-code', title: '代码', action: () => insert('`', '`', 'code') },
  ];

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* 工具栏 */}
      <div className="flex items-center gap-1 px-2 py-1.5 bg-gray-50 border-b border-gray-200">
        {tools.map(t => (
          <button key={t.icon} type="button" onClick={t.action} title={t.title}
            className="w-7 h-7 rounded hover:bg-gray-200 flex items-center justify-center text-gray-500 hover:text-gray-700 transition-colors">
            <AppIcon className={`fas ${t.icon} text-xs`} />
          </button>
        ))}
        <div className="flex-1" />
        <button type="button" onClick={() => setShowPreview(!showPreview)}
          className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${showPreview ? 'bg-primary text-white' : 'text-gray-500 hover:bg-gray-200'}`}>
          <AppIcon className="fas fa-eye text-[10px]" /> {showPreview ? '编辑' : '预览'}
        </button>
      </div>
      {/* 编辑/预览 */}
      {showPreview ? (
        <div className="p-3 bg-white min-h-[80px]" style={{ minHeight: `${rows * 24}px` }}>
          <MarkdownRenderer content={value} />
          {!value && <span className="text-gray-400 text-sm">暂无内容</span>}
        </div>
      ) : (
        <textarea
          ref={taRef}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || '支持 Markdown 格式，可用工具栏排版'}
          rows={rows}
          className="w-full px-3 py-2 outline-none resize-y text-sm font-mono"
          style={{ minHeight: `${rows * 24}px` }}
        />
      )}
    </div>
  );
};
