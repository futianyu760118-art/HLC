/**
 * 全局确认弹窗组件 + 命令式 confirm() API。
 * 用法：const ok = await confirm({ title: '确定删除？', danger: true });
 */
import React, { useEffect, useState } from 'react';
import { createRoot, Root } from 'react-dom/client';

import AppIcon from './AppIcon';
export interface ConfirmOptions {
  title?: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  icon?: string;
}

interface DialogProps extends ConfirmOptions {
  onConfirm: () => void;
  onCancel: () => void;
}

const Dialog: React.FC<DialogProps> = ({ title, message, confirmText, cancelText, danger, icon, onConfirm, onCancel }) => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter') onConfirm();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel, onConfirm]);

  const accent = danger ? 'red' : 'blue';
  return (
    <div
      role="dialog"
      aria-modal="true"
      className={`fixed inset-0 z-[10000] bg-black/30 flex items-center justify-center p-4 transition-opacity duration-150 ${visible ? 'opacity-100' : 'opacity-0'}`}
      onClick={onCancel}
    >
      <div
        className={`bg-white rounded-xl shadow-2xl w-full max-w-md transition-transform duration-150 ${visible ? 'scale-100' : 'scale-95'}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 bg-${accent}-50 text-${accent}-500`}>
              <AppIcon className={`fas ${icon || (danger ? 'fa-exclamation-triangle' : 'fa-question-circle')} text-lg`} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-bold text-gray-800 mb-1">{title || '确认操作'}</h3>
              {message && <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line">{message}</p>}
            </div>
          </div>
        </div>
        <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 flex justify-end gap-2 rounded-b-xl">
          <button
            onClick={onCancel}
            className="px-4 py-1.5 border border-gray-200 bg-white text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors"
          >
            {cancelText || '取消'}
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className={`px-4 py-1.5 text-white rounded-lg text-sm font-medium transition-colors ${
              danger ? 'bg-red-500 hover:bg-red-600' : 'bg-blue-500 hover:bg-blue-600'
            }`}
          >
            {confirmText || '确定'}
          </button>
        </div>
      </div>
    </div>
  );
};

let mountId = 0;
const mounted = new Map<number, { root: Root; el: HTMLDivElement }>();

const teardown = (id: number) => {
  const entry = mounted.get(id);
  if (!entry) return;
  // 延迟 unmount 让动画跑完
  setTimeout(() => {
    entry.root.unmount();
    entry.el.remove();
    mounted.delete(id);
  }, 200);
};

export const confirm = (options: ConfirmOptions = {}): Promise<boolean> => {
  return new Promise((resolve) => {
    const id = ++mountId;
    const el = document.createElement('div');
    document.body.appendChild(el);
    const root = createRoot(el);
    mounted.set(id, { root, el });

    const finish = (ok: boolean) => {
      teardown(id);
      resolve(ok);
    };

    root.render(
      <Dialog
        {...options}
        onConfirm={() => finish(true)}
        onCancel={() => finish(false)}
      />
    );
  });
};

export default confirm;
