/**
 * 轻量级 Toast 提示工具，作为 alert() 的替代。
 * 不依赖 React，可在任意地方调用。
 */

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastOptions {
  duration?: number; // ms，默认 3000
}

const containerId = '__hpt_toast_container__';

const colors: Record<ToastType, { bg: string; border: string; icon: string; iconColor: string }> = {
  success: { bg: '#ecfdf5', border: '#a7f3d0', icon: 'fa-check-circle', iconColor: '#059669' },
  error: { bg: '#fef2f2', border: '#fecaca', icon: 'fa-times-circle', iconColor: '#dc2626' },
  warning: { bg: '#fffbeb', border: '#fde68a', icon: 'fa-exclamation-triangle', iconColor: '#d97706' },
  info: { bg: '#eff6ff', border: '#bfdbfe', icon: 'fa-info-circle', iconColor: '#2563eb' },
};

const ensureContainer = (): HTMLDivElement => {
  let el = document.getElementById(containerId) as HTMLDivElement | null;
  if (!el) {
    el = document.createElement('div');
    el.id = containerId;
    el.style.cssText = [
      'position:fixed',
      'top:72px',
      'right:24px',
      'z-index:9999',
      'display:flex',
      'flex-direction:column',
      'gap:8px',
      'pointer-events:none',
    ].join(';');
    document.body.appendChild(el);
  }
  return el;
};

const show = (type: ToastType, message: string, options?: ToastOptions) => {
  const c = colors[type];
  const container = ensureContainer();

  const node = document.createElement('div');
  node.style.cssText = [
    `background:${c.bg}`,
    `border:1px solid ${c.border}`,
    'border-radius:8px',
    'padding:10px 14px',
    'min-width:240px',
    'max-width:480px',
    'box-shadow:0 4px 12px rgba(0,0,0,0.08)',
    'display:flex',
    'align-items:center',
    'gap:8px',
    'font-size:13px',
    'color:#1f2937',
    'pointer-events:auto',
    'animation:hptToastIn 0.18s ease-out',
  ].join(';');

  const icon = document.createElement('i');
  icon.className = `fas ${c.icon}`;
  icon.style.color = c.iconColor;
  node.appendChild(icon);

  const text = document.createElement('span');
  text.textContent = message;
  text.style.flex = '1';
  node.appendChild(text);

  const close = document.createElement('button');
  close.innerHTML = '&times;';
  close.style.cssText = 'background:none;border:none;color:#9ca3af;font-size:18px;cursor:pointer;padding:0 4px';
  close.onclick = () => node.remove();
  node.appendChild(close);

  container.appendChild(node);

  // 注入一次性 keyframes
  if (!document.getElementById('__hpt_toast_keyframes__')) {
    const style = document.createElement('style');
    style.id = '__hpt_toast_keyframes__';
    style.textContent = '@keyframes hptToastIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:translateX(0)}}';
    document.head.appendChild(style);
  }

  const duration = options?.duration ?? 3000;
  if (duration > 0) {
    setTimeout(() => {
      node.style.transition = 'opacity 0.2s, transform 0.2s';
      node.style.opacity = '0';
      node.style.transform = 'translateX(20px)';
      setTimeout(() => node.remove(), 220);
    }, duration);
  }
};

export const toast = {
  success: (msg: string, opts?: ToastOptions) => show('success', msg, opts),
  error: (msg: string, opts?: ToastOptions) => show('error', msg, opts),
  warning: (msg: string, opts?: ToastOptions) => show('warning', msg, opts),
  info: (msg: string, opts?: ToastOptions) => show('info', msg, opts),
};

export default toast;
