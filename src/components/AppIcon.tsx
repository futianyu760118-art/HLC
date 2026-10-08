// @ts-nocheck

import type { SVGProps } from 'react';

interface AppIconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name?: string;
}

const aliases: Record<string, string> = {
  'angles-left': 'chevron-left-double',
  'angles-right': 'chevron-right-double',
  'arrow-left': 'arrow-left',
  'bell-slash': 'bell-off',
  'calendar-alt': 'calendar',
  'calendar-days': 'calendar',
  'caret-down': 'chevron-down',
  'caret-left': 'chevron-left',
  'caret-right': 'chevron-right',
  'caret-up': 'chevron-up',
  'chart-radar': 'radar',
  'cloud-upload-alt': 'cloud-upload',
  'comment-medical': 'feedback',
  'exclamation-circle': 'alert-circle',
  'exclamation-triangle': 'alert-triangle',
  'external-link-alt': 'external-link',
  'file-alt': 'file-text',
  'file-archive': 'file-zip',
  'file-contract': 'file-contract',
  'file-import': 'file-import',
  'file-signature': 'file-signature',
  'folder-open': 'folder',
  'gauge-high': 'dashboard',
  history: 'history',
  'info-circle': 'info',
  'list-check': 'checklist',
  'money-check-alt': 'money-check',
  'question-circle': 'question',
  random: 'shuffle',
  'shield-alt': 'shield',
  'sign-out-alt': 'log-out',
  'sliders-h': 'sliders',
  'sort-down': 'sort-down',
  'sort-up': 'sort-up',
  'star-half-alt': 'star-half',
  'sync-alt': 'refresh',
  'times-circle': 'x-circle',
  'trash-alt': 'trash',
  'users-cog': 'users-cog',
  'wand-magic-sparkles': 'sparkles',
};

const extractIconName = (name?: string, className?: string) => {
  const explicit = name?.replace(/^fa-/, '');
  if (explicit) return aliases[explicit] || explicit;

  const classes = String(className || '').match(/\bfa-[a-z0-9-]+\b/g) || [];
  const raw = classes
    .map((item) => item.replace(/^fa-/, ''))
    .find((item) => !['spin', 'solid', 'regular', 'brands'].includes(item));

  if (!raw) return 'circle';
  return aliases[raw] || raw;
};

const fileIcon = (label?: string) => (
  <>
    <path d="M7 3.5h6.2L18 8.3V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1.5-1.5Z" />
    <path d="M13 3.8V8h4.2" />
    {label ? (
      <text x="12" y="16.4" textAnchor="middle" fontSize="4.1" fontWeight="800" fill="currentColor" stroke="none">
        {label}
      </text>
    ) : (
      <>
        <path d="M9 12h6" />
        <path d="M9 15h5" />
      </>
    )}
  </>
);

const userBase = () => (
  <>
    <circle cx="12" cy="8" r="3.2" />
    <path d="M5.4 20.2a6.8 6.8 0 0 1 13.2 0" />
  </>
);

const calendarBase = () => (
  <>
    <path d="M7 3.5v3" />
    <path d="M17 3.5v3" />
    <rect x="4" y="5.5" width="16" height="15" rx="2.2" />
    <path d="M4 10h16" />
  </>
);

const renderIcon = (name: string) => {
  switch (name) {
    case 'dashboard':
      return (
        <>
          <path d="M4.5 15.5a7.5 7.5 0 1 1 15 0" />
          <path d="M12 15.5l4-4.2" />
          <path d="M8 18.5h8" />
        </>
      );
    case 'brain':
      return (
        <>
          <path d="M9.2 5.2a3 3 0 0 0-4.1 3.4A3.6 3.6 0 0 0 5.8 15a3.3 3.3 0 0 0 3.4 4.1" />
          <path d="M14.8 5.2a3 3 0 0 1 4.1 3.4A3.6 3.6 0 0 1 18.2 15a3.3 3.3 0 0 1-3.4 4.1" />
          <path d="M12 4.5v15" />
          <path d="M8.7 9.2H12" />
          <path d="M12 13.8h3.4" />
        </>
      );
    case 'briefcase':
      return (
        <>
          <rect x="3.7" y="7" width="16.6" height="12" rx="2" />
          <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
          <path d="M3.7 11.5h16.6" />
          <path d="M10.4 12h3.2" />
        </>
      );
    case 'search':
      return (
        <>
          <circle cx="10.8" cy="10.8" r="5.8" />
          <path d="M15.2 15.2 20 20" />
        </>
      );
    case 'bars':
      return (
        <>
          <path d="M4 7h16" />
          <path d="M4 12h16" />
          <path d="M4 17h16" />
        </>
      );
    case 'home':
      return (
        <>
          <path d="M4 11 12 4l8 7" />
          <path d="M6 10v9.5A1.5 1.5 0 0 0 7.5 21h9a1.5 1.5 0 0 0 1.5-1.5V10" />
          <path d="M10 21v-5.5h4V21" />
        </>
      );
    case 'bell':
      return (
        <>
          <path d="M18 10.6a6 6 0 0 0-12 0c0 4-1.7 5.3-2.4 6h16.8c-.7-.7-2.4-2-2.4-6Z" />
          <path d="M9.5 19a2.7 2.7 0 0 0 5 0" />
        </>
      );
    case 'bell-off':
      return (
        <>
          <path d="m4 4 16 16" />
          <path d="M9.2 5.2A6 6 0 0 1 18 10.6c0 1.7.3 3 .8 4" />
          <path d="M6 10.6c0 4-1.7 5.3-2.4 6h12.2" />
          <path d="M9.5 19a2.7 2.7 0 0 0 5 0" />
        </>
      );
    case 'calendar':
      return calendarBase();
    case 'calendar-check':
      return (
        <>
          {calendarBase()}
          <path d="m9 15 2 2 4.3-4.5" />
        </>
      );
    case 'calendar-plus':
      return (
        <>
          {calendarBase()}
          <path d="M12 13.2v5" />
          <path d="M9.5 15.7h5" />
        </>
      );
    case 'calendar-minus':
      return (
        <>
          {calendarBase()}
          <path d="M9.5 15.7h5" />
        </>
      );
    case 'calendar-times':
      return (
        <>
          {calendarBase()}
          <path d="m9.8 13.7 4.4 4.4" />
          <path d="m14.2 13.7-4.4 4.4" />
        </>
      );
    case 'clock':
    case 'user-clock':
      return (
        <>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 7.5V12l3 2" />
        </>
      );
    case 'chart-line':
      return (
        <>
          <path d="M4 19h16" />
          <path d="M5 16.5 9 12l3 2.5L18.5 7" />
          <path d="M16 7h2.5v2.5" />
        </>
      );
    case 'chart-bar':
      return (
        <>
          <path d="M4 20h16" />
          <rect x="6" y="11" width="2.6" height="6" rx=".7" />
          <rect x="11" y="7" width="2.6" height="10" rx=".7" />
          <rect x="16" y="4.5" width="2.6" height="12.5" rx=".7" />
        </>
      );
    case 'chart-area':
      return (
        <>
          <path d="M4 19h16" />
          <path d="M5 16.8 9.5 11l3.7 3.1L19 7.2v9.6H5Z" />
        </>
      );
    case 'chart-pie':
      return (
        <>
          <path d="M12 4.2v8h8A8 8 0 1 1 12 4.2Z" />
          <path d="M14.5 3.8A8 8 0 0 1 20.2 9.5h-5.7Z" />
        </>
      );
    case 'circle-dot':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="12" cy="12" r="3" fill="currentColor" stroke="none" />
        </>
      );
    case 'radar':
      return (
        <>
          <path d="m12 3 7.5 5v8L12 21l-7.5-5V8Z" />
          <path d="m12 7 4 2.7v4.6L12 17l-4-2.7V9.7Z" />
          <path d="M12 3v18M4.5 8l15 8M19.5 8l-15 8" />
        </>
      );
    case 'sitemap':
      return (
        <>
          <rect x="8.5" y="3.5" width="7" height="4.5" rx="1.2" />
          <rect x="3.5" y="16" width="6" height="4.5" rx="1.2" />
          <rect x="14.5" y="16" width="6" height="4.5" rx="1.2" />
          <path d="M12 8v4H6.5v4" />
          <path d="M12 12h5.5v4" />
        </>
      );
    case 'layer-group':
      return (
        <>
          <path d="m12 3.5 8 4.2-8 4.2-8-4.2Z" />
          <path d="m4 12 8 4.2 8-4.2" />
          <path d="m4 16.2 8 4.3 8-4.3" />
        </>
      );
    case 'users':
      return (
        <>
          <path d="M9.5 12.5a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8Z" />
          <path d="M3.5 20a6.1 6.1 0 0 1 12 0" />
          <path d="M16 8a2.8 2.8 0 0 1 0 5.1" />
          <path d="M17.5 15.5A5 5 0 0 1 21 20" />
        </>
      );
    case 'user':
    case 'user-circle':
    case 'user-tie':
    case 'id-card':
    case 'id-badge':
      return userBase();
    case 'user-plus':
      return (
        <>
          {userBase()}
          <path d="M18 6v5" />
          <path d="M15.5 8.5h5" />
        </>
      );
    case 'user-minus':
      return (
        <>
          {userBase()}
          <path d="M15.5 8.5h5" />
        </>
      );
    case 'user-check':
      return (
        <>
          {userBase()}
          <path d="m16 8.5 1.7 1.8 3.2-3.7" />
        </>
      );
    case 'user-shield':
      return (
        <>
          {userBase()}
          <path d="M18 12.5 21 14v2.2a4.2 4.2 0 0 1-3 4 4.2 4.2 0 0 1-3-4V14Z" />
        </>
      );
    case 'users-cog':
      return (
        <>
          {renderIcon('users')}
          <circle cx="18.2" cy="6.5" r="1.8" />
          <path d="M18.2 3.2v1" />
          <path d="M18.2 8.8v1" />
          <path d="M15 6.5h1" />
          <path d="M20.4 6.5h1" />
        </>
      );
    case 'file':
    case 'file-text':
      return fileIcon();
    case 'file-lines':
      return (
        <>
          {fileIcon()}
          <path d="M9 11h6" />
          <path d="M9 14h6" />
        </>
      );
    case 'file-pdf':
      return fileIcon('PDF');
    case 'file-word':
      return fileIcon('DOC');
    case 'file-image':
      return fileIcon('IMG');
    case 'file-excel':
    case 'file-csv':
      return fileIcon('XLS');
    case 'file-powerpoint':
      return fileIcon('PPT');
    case 'file-video':
      return fileIcon('VID');
    case 'file-audio':
      return fileIcon('AUD');
    case 'file-code':
      return fileIcon('</>');
    case 'file-zip':
      return fileIcon('ZIP');
    case 'file-contract':
    case 'file-signature':
    case 'file-import':
      return (
        <>
          {fileIcon()}
          <path d="m10 18 2.2-2.2 1.8 1.8 3-3" />
        </>
      );
    case 'folder':
      return (
        <>
          <path d="M3.8 7.2A1.8 1.8 0 0 1 5.6 5.5h4.1l2 2.2h6.7a1.8 1.8 0 0 1 1.8 1.8v8.3a1.8 1.8 0 0 1-1.8 1.8H5.6a1.8 1.8 0 0 1-1.8-1.8Z" />
          <path d="M4 10h16" />
        </>
      );
    case 'folder-tree':
      return (
        <>
          <path d="M3 5h6l1.5 1.8h10" />
          <rect x="3" y="5" width="7.5" height="4.2" rx="1" />
          <rect x="13" y="10.5" width="7.5" height="4.2" rx="1" />
          <rect x="3" y="15.5" width="7.5" height="4.2" rx="1" />
          <path d="M6.8 9.2v3h9" />
          <path d="M16 12.5v3" />
        </>
      );
    case 'download':
      return (
        <>
          <path d="M12 4v10" />
          <path d="m8 10 4 4 4-4" />
          <path d="M5 19h14" />
        </>
      );
    case 'upload':
    case 'cloud-upload':
      return (
        <>
          <path d="M7.5 18.5h9.2a4 4 0 0 0 .5-8 5.6 5.6 0 0 0-10.8 1.6 3.2 3.2 0 0 0 1.1 6.4Z" />
          <path d="M12 17V9" />
          <path d="m8.8 12.2 3.2-3.2 3.2 3.2" />
        </>
      );
    case 'edit':
      return (
        <>
          <path d="M5 19h4.2L19 9.2 14.8 5 5 14.8Z" />
          <path d="m13.8 6 4.2 4.2" />
        </>
      );
    case 'trash':
      return (
        <>
          <path d="M5 7h14" />
          <path d="M9 7V5h6v2" />
          <path d="M7 7.5 8 20h8l1-12.5" />
          <path d="M10.5 11v5" />
          <path d="M13.5 11v5" />
        </>
      );
    case 'save':
      return (
        <>
          <path d="M5 4h11l3 3v13H5Z" />
          <path d="M8 4v6h7V4" />
          <path d="M8 20v-6h8v6" />
        </>
      );
    case 'copy':
      return (
        <>
          <rect x="8" y="8" width="11" height="11" rx="2" />
          <path d="M5 15.5V6a1 1 0 0 1 1-1h9.5" />
        </>
      );
    case 'link':
      return (
        <>
          <path d="M10.5 13.5a4 4 0 0 0 5.7 0l2-2a4 4 0 0 0-5.7-5.7l-1.1 1.1" />
          <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2 2a4 4 0 1 0 5.7 5.7l1.1-1.1" />
        </>
      );
    case 'external-link':
      return (
        <>
          <path d="M14 5h5v5" />
          <path d="m19 5-8 8" />
          <path d="M10 6H6.5A1.5 1.5 0 0 0 5 7.5v10A1.5 1.5 0 0 0 6.5 19h10A1.5 1.5 0 0 0 18 17.5V14" />
        </>
      );
    case 'check':
      return <path d="m5 12.5 4.2 4.2L19 6.8" />;
    case 'check-circle':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="m8.2 12.3 2.5 2.5 5.2-5.6" />
        </>
      );
    case 'check-double':
      return (
        <>
          <path d="m3.8 12.5 3.2 3.2 6.2-7" />
          <path d="m10.8 12.5 3.2 3.2 6.2-7" />
        </>
      );
    case 'x':
    case 'times':
      return (
        <>
          <path d="M6.5 6.5 17.5 17.5" />
          <path d="M17.5 6.5 6.5 17.5" />
        </>
      );
    case 'x-circle':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="m9 9 6 6" />
          <path d="m15 9-6 6" />
        </>
      );
    case 'plus':
      return (
        <>
          <path d="M12 5v14" />
          <path d="M5 12h14" />
        </>
      );
    case 'plus-circle':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 8v8" />
          <path d="M8 12h8" />
        </>
      );
    case 'minus-circle':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M8 12h8" />
        </>
      );
    case 'alert-circle':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7.5v5.5" />
          <path d="M12 16.5h.01" />
        </>
      );
    case 'alert-triangle':
      return (
        <>
          <path d="M10.4 4.7 3.5 17.2A1.7 1.7 0 0 0 5 19.8h14a1.7 1.7 0 0 0 1.5-2.6L13.6 4.7a1.8 1.8 0 0 0-3.2 0Z" />
          <path d="M12 9v4.5" />
          <path d="M12 16.7h.01" />
        </>
      );
    case 'info':
    case 'question':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          {name === 'question' ? <path d="M9.7 9a2.6 2.6 0 1 1 4.2 2.1c-.9.7-1.9 1.3-1.9 2.6" /> : <path d="M12 11v5" />}
          <path d="M12 7.7h.01" />
        </>
      );
    case 'chevron-left':
      return <path d="m14.5 6-6 6 6 6" />;
    case 'chevron-right':
      return <path d="m9.5 6 6 6-6 6" />;
    case 'chevron-down':
      return <path d="m6 9.5 6 6 6-6" />;
    case 'chevron-up':
      return <path d="m6 14.5 6-6 6 6" />;
    case 'chevron-left-double':
      return (
        <>
          <path d="m12.5 6-6 6 6 6" />
          <path d="m18 6-6 6 6 6" />
        </>
      );
    case 'chevron-right-double':
      return (
        <>
          <path d="m11.5 6 6 6-6 6" />
          <path d="m6 6 6 6-6 6" />
        </>
      );
    case 'sort':
      return (
        <>
          <path d="m8 9 4-4 4 4" />
          <path d="m16 15-4 4-4-4" />
        </>
      );
    case 'sort-up':
      return <path d="m8 14 4-5 4 5Z" />;
    case 'sort-down':
      return <path d="m8 10 4 5 4-5Z" />;
    case 'spinner':
      return (
        <>
          <path d="M12 3.5a8.5 8.5 0 1 1-8.5 8.5" />
          <path d="M3.5 7.5V3.5h4" />
        </>
      );
    case 'cog':
      return (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3.5v2" />
          <path d="M12 18.5v2" />
          <path d="M4.6 7.2l1.7 1" />
          <path d="M17.7 15.8l1.7 1" />
          <path d="M4.6 16.8l1.7-1" />
          <path d="M17.7 8.2l1.7-1" />
          <path d="M3.5 12h2" />
          <path d="M18.5 12h2" />
        </>
      );
    case 'sliders':
      return (
        <>
          <path d="M4 7h16" />
          <circle cx="9" cy="7" r="2" />
          <path d="M4 17h16" />
          <circle cx="15" cy="17" r="2" />
        </>
      );
    case 'refresh':
    case 'undo':
      return (
        <>
          <path d="M6.2 8.8A7 7 0 1 1 6 15" />
          <path d="M6.2 4.8v4h4" />
        </>
      );
    case 'play':
      return <path d="M8 5.5 18 12 8 18.5Z" />;
    case 'pause':
      return (
        <>
          <path d="M8.5 5.5v13" />
          <path d="M15.5 5.5v13" />
        </>
      );
    case 'stop':
      return <rect x="7" y="7" width="10" height="10" rx="1.5" />;
    case 'video':
      return (
        <>
          <rect x="4" y="7" width="11" height="10" rx="2" />
          <path d="m15 10 5-3v10l-5-3" />
        </>
      );
    case 'microphone':
      return (
        <>
          <rect x="9" y="4" width="6" height="10" rx="3" />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
          <path d="M12 17.5V21" />
        </>
      );
    case 'music':
      return (
        <>
          <path d="M15 5v10.5a2.5 2.5 0 1 1-1.5-2.3V7l5-1.5v8.5a2.5 2.5 0 1 1-1.5-2.3V5.5Z" />
        </>
      );
    case 'image':
      return (
        <>
          <rect x="4" y="5" width="16" height="14" rx="2" />
          <circle cx="9" cy="10" r="1.5" />
          <path d="m5 17 4.5-4.5 3.3 3.2 2.4-2.4L19 17" />
        </>
      );
    case 'paperclip':
      return <path d="M8 12.2 13.9 6.3a3 3 0 1 1 4.2 4.2l-7.4 7.4a4.5 4.5 0 0 1-6.4-6.4L11.7 4" />;
    case 'paper-plane':
      return (
        <>
          <path d="M21 4 10 21l-2-7-6-3Z" />
          <path d="m10 14 11-10" />
        </>
      );
    case 'feedback':
    case 'comment-dots':
    case 'comments':
      return (
        <>
          <path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v4A3.5 3.5 0 0 1 15.5 14H11l-4.5 4v-4A3.5 3.5 0 0 1 5 10.5Z" />
          <path d="M9 8.5h.01" />
          <path d="M12 8.5h.01" />
          <path d="M15 8.5h.01" />
        </>
      );
    case 'inbox':
      return (
        <>
          <path d="M5 5h14l2 8v5.5A1.5 1.5 0 0 1 19.5 20h-15A1.5 1.5 0 0 1 3 18.5V13Z" />
          <path d="M3 13h5l1.5 3h5l1.5-3h5" />
        </>
      );
    case 'clipboard-list':
    case 'clipboard-check':
    case 'checklist':
      return (
        <>
          <rect x="6" y="4.5" width="12" height="16" rx="2" />
          <path d="M9.5 4.5A2.5 2.5 0 0 1 12 2a2.5 2.5 0 0 1 2.5 2.5" />
          <path d="M9 11h6" />
          <path d="M9 15h4.5" />
          {name === 'clipboard-check' || name === 'checklist' ? <path d="m8.5 17.8 1.4 1.4 3-3.2" /> : null}
        </>
      );
    case 'bullseye':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="12" cy="12" r="5" />
          <circle cx="12" cy="12" r="1.6" />
        </>
      );
    case 'star':
    case 'star-half':
      return (
        <>
          <path d="m12 3.5 2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8Z" />
          {name === 'star-half' ? <path d="M12 3.5v13" /> : null}
        </>
      );
    case 'trophy':
      return (
        <>
          <path d="M8 5h8v5a4 4 0 0 1-8 0Z" />
          <path d="M8 6.5H5.5a2 2 0 0 0 2 3.5" />
          <path d="M16 6.5h2.5a2 2 0 0 1-2 3.5" />
          <path d="M12 14v3.5" />
          <path d="M8.5 20h7" />
          <path d="M9.5 20a2.5 2.5 0 0 1 5 0Z" />
        </>
      );
    case 'route':
      return (
        <>
          <circle cx="6.5" cy="5.5" r="2.5" />
          <circle cx="17.5" cy="18.5" r="2.5" />
          <path d="M6.5 8v4.5a3.5 3.5 0 0 0 3.5 3.5h4a3.5 3.5 0 0 1 3.5 3.5" />
          <path d="M6.5 8.5v.5" />
        </>
      );
    case 'graduation-cap':
      return (
        <>
          <path d="m3 9 9-4 9 4-9 4Z" />
          <path d="M7 11.2v4.2c2.8 2.1 7.2 2.1 10 0v-4.2" />
          <path d="M21 9v6" />
        </>
      );
    case 'book-open':
      return (
        <>
          <path d="M12 6.5C10.5 5.2 8.3 5 5.8 5H4v12h1.8c2.5 0 4.7.2 6.2 1.5" />
          <path d="M12 6.5C13.5 5.2 15.7 5 18.2 5H20v12h-1.8c-2.5 0-4.7.2-6.2 1.5" />
          <path d="M12 6.5v12" />
        </>
      );
    case 'book-open-reader':
      return (
        <>
          <path d="M12 4.5C10.6 3.4 8.5 3.2 6 3.2H4.5v8.5H6c2.5 0 4.6.2 6 1.3" />
          <path d="M12 4.5c1.4-1.1 3.5-1.3 6-1.3h1.5v8.5H18c-2.5 0-4.6.2-6 1.3" />
          <path d="M12 4.5V13" />
          <path d="M9.5 18.5 12 21l2.5-2.5" />
          <path d="M12 16v5" />
        </>
      );
    case 'bookmark':
      return (
        <>
          <path d="M6.5 4.5h11A1.5 1.5 0 0 1 19 6v15l-7-4-7 4V6a1.5 1.5 0 0 1 1.5-1.5Z" />
        </>
      );
    case 'chalkboard-teacher':
      return (
        <>
          <rect x="4" y="5" width="16" height="10" rx="1.5" />
          <path d="M8 20h8" />
          <path d="M12 15v5" />
          <path d="M8 9h5" />
        </>
      );
    case 'wallet':
      return (
        <>
          <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h11A1.5 1.5 0 0 1 19 6.5V9" />
          <rect x="4" y="8" width="17" height="11" rx="2" />
          <path d="M16 13.5h5" />
        </>
      );
    case 'store':
      return (
        <>
          <path d="M5 9 6 4h12l1 5" />
          <path d="M4 9h16l-.8 2a2.5 2.5 0 0 1-4.4 0 2.5 2.5 0 0 1-4.4 0 2.5 2.5 0 0 1-4.4 0Z" />
          <rect x="6" y="13" width="12" height="7" rx="1" />
          <path d="M10 20v-3.5h4V20" />
        </>
      );
    case 'certificate':
      return (
        <>
          <rect x="4" y="4" width="16" height="12" rx="1.5" />
          <path d="M8 8h8" />
          <path d="M8 11h5" />
          <circle cx="12" cy="18.5" r="2.5" />
          <path d="m10.4 20-1 2.3 2.6-1.2 2.6 1.2-1-2.3" />
        </>
      );
    case 'microchip':
    case 'chip':
      return (
        <>
          <rect x="7" y="7" width="10" height="10" rx="1.5" />
          <rect x="9.8" y="9.8" width="4.4" height="4.4" rx=".6" />
          <path d="M9.8 4.5v2.5M14.2 4.5v2.5M9.8 17v2.5M14.2 17v2.5M4.5 9.8h2.5M4.5 14.2h2.5M17 9.8h2.5M17 14.2h2.5" />
        </>
      );
    case 'money-check':
    case 'money-bill-wave':
      return (
        <>
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <path d="M7.5 10h4" />
          <path d="M7.5 14h7" />
          <circle cx="16.5" cy="11" r="1.5" />
        </>
      );
    case 'plane':
      return (
        <>
          <path d="M21 4 3 11.5l7 2.2L12.5 21Z" />
          <path d="m10 13.7 4.8-5.8" />
        </>
      );
    case 'shield':
      return (
        <>
          <path d="M12 3.5 19 6v5.5c0 4.5-2.8 7.7-7 9-4.2-1.3-7-4.5-7-9V6Z" />
          <path d="m8.5 12 2.2 2.2 4.8-5" />
        </>
      );
    case 'lock':
      return (
        <>
          <rect x="5" y="10" width="14" height="10" rx="2" />
          <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
        </>
      );
    case 'eye':
      return (
        <>
          <path d="M3.5 12s3-6 8.5-6 8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6Z" />
          <circle cx="12" cy="12" r="2.6" />
        </>
      );
    case 'eye-slash':
      return (
        <>
          <path d="m4 4 16 16" />
          <path d="M9.8 6.4A8.8 8.8 0 0 1 12 6c5.5 0 8.5 6 8.5 6a14 14 0 0 1-2.2 3" />
          <path d="M6.4 8.1A14.4 14.4 0 0 0 3.5 12s3 6 8.5 6c1.2 0 2.3-.3 3.2-.7" />
        </>
      );
    case 'envelope':
      return (
        <>
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <path d="m5 7.5 7 5 7-5" />
        </>
      );
    case 'keyboard':
      return (
        <>
          <rect x="3.5" y="7" width="17" height="10" rx="2" />
          <path d="M7 10h.01M10 10h.01M13 10h.01M16 10h.01M8 14h8" />
        </>
      );
    case 'plug':
      return (
        <>
          <path d="M8 3.5v5" />
          <path d="M16 3.5v5" />
          <path d="M6 8.5h12v2.2a6 6 0 0 1-5 5.9V21" />
          <path d="M9 21h8" />
        </>
      );
    case 'mobile':
      return (
        <>
          <rect x="7" y="2.8" width="10" height="18.4" rx="2.2" />
          <path d="M10 5.7h4" />
          <path d="M11.9 18.1h.2" />
        </>
      );
    case 'table':
      return (
        <>
          <rect x="4" y="5" width="16" height="14" rx="2" />
          <path d="M4 10h16" />
          <path d="M9 5v14" />
          <path d="M15 5v14" />
        </>
      );
    case 'list':
      return (
        <>
          <path d="M8 7h12" />
          <path d="M8 12h12" />
          <path d="M8 17h12" />
          <path d="M4 7h.01" />
          <path d="M4 12h.01" />
          <path d="M4 17h.01" />
        </>
      );
    case 'heart':
      return <path d="M20 8.8c0 5.4-8 10.2-8 10.2S4 14.2 4 8.8A4.2 4.2 0 0 1 11.5 6 4.2 4.2 0 0 1 20 8.8Z" />;
    case 'thumbs-up':
      return (
        <>
          <path d="M7 10v10H4.5A1.5 1.5 0 0 1 3 18.5v-7A1.5 1.5 0 0 1 4.5 10Z" />
          <path d="M7 10h2.5L12 4.5a2 2 0 0 1 3 2L14 10h4.5a2 2 0 0 1 1.9 2.6L18.8 18a3 3 0 0 1-2.9 2H7" />
        </>
      );
    case 'lightbulb':
      return (
        <>
          <path d="M9 18h6" />
          <path d="M10 21h4" />
          <path d="M8.5 14.5a5.5 5.5 0 1 1 7 0c-.8.7-1.2 1.5-1.3 2.5H9.8c-.1-1-.5-1.8-1.3-2.5Z" />
        </>
      );
    case 'bug':
      return (
        <>
          <rect x="7.5" y="7" width="9" height="12" rx="4.5" />
          <path d="M9 5.5 7 3.5" />
          <path d="m15 5.5 2-2" />
          <path d="M4 12h3.5" />
          <path d="M16.5 12H20" />
          <path d="M5 17l3-1" />
          <path d="m19 17-3-1" />
        </>
      );
    case 'building':
      return (
        <>
          <rect x="5" y="4" width="10" height="16" rx="1.5" />
          <path d="M15 9h4v11h-4" />
          <path d="M8 8h.01M12 8h.01M8 12h.01M12 12h.01M8 16h.01M12 16h.01" />
        </>
      );
    case 'bullhorn':
      return (
        <>
          <path d="M5 13H3.5A1.5 1.5 0 0 1 2 11.5v-3A1.5 1.5 0 0 1 3.5 7H5l12-3v12Z" />
          <path d="M7 13l2 6" />
          <path d="M19 8.5v3" />
        </>
      );
    case 'ban':
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="m6 6 12 12" />
        </>
      );
    case 'toggle-on':
      return (
        <>
          <rect x="3" y="7" width="18" height="10" rx="5" />
          <circle cx="16" cy="12" r="3" />
        </>
      );
    case 'shuffle':
      return (
        <>
          <path d="M4 7h3.5c2.8 0 3.5 10 6.5 10H20" />
          <path d="M17 14l3 3-3 3" />
          <path d="M4 17h3.5c1.2 0 2-1.5 2.7-3.3" />
          <path d="M17 4l3 3-3 3" />
        </>
      );
    case 'log-out':
      return (
        <>
          <path d="M9 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3" />
          <path d="M15 7l5 5-5 5" />
          <path d="M20 12H9" />
        </>
      );
    case 'robot':
      return (
        <>
          <rect x="5" y="8" width="14" height="10" rx="3" />
          <path d="M12 5v3" />
          <circle cx="9.5" cy="13" r=".8" fill="currentColor" stroke="none" />
          <circle cx="14.5" cy="13" r=".8" fill="currentColor" stroke="none" />
          <path d="M9.5 16h5" />
        </>
      );
    case 'sparkles':
      return (
        <>
          <path d="M12 3.5 13.6 8l4.4 1.6-4.4 1.6L12 15.7l-1.6-4.5L6 9.6 10.4 8Z" />
          <path d="M5.5 14.5 6.4 17l2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9Z" />
          <path d="M18 15.5 18.8 18l2.2.8-2.2.8-.8 2.4-.8-2.4-2.2-.8 2.2-.8Z" />
        </>
      );
    default:
      return (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 8v4.5" />
          <path d="M12 16.5h.01" />
        </>
      );
  }
};

export default function AppIcon({ name, className = '', ...props }: AppIconProps) {
  const iconName = extractIconName(name, className);
  const isSpin = String(className).includes('fa-spin') || iconName === 'spinner';

  return (
    <svg
      viewBox="0 0 24 24"
      className={`app-icon ${isSpin ? 'is-spin' : ''} ${className}`.trim()}
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.85"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {renderIcon(iconName)}
    </svg>
  );
}
