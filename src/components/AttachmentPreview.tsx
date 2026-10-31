// @ts-nocheck
/**
 * 附件预览模态框：支持图片/PDF/视频/音频在线预览，文档/压缩包提供下载。
 */
import React, { useEffect, useState } from 'react';
import { fileApi } from '../utils/api';

import AppIcon from './AppIcon';
interface Attachment {
  name: string;
  url: string;
  size: number;
  type: 'image' | 'document';
  ext: string;
}

interface AttachmentPreviewProps {
  attachments: Attachment[];
  initialIndex?: number;
  onClose: () => void;
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const isImage = (ext: string) => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff'].includes(ext);
const isPdf = (ext: string) => ext === 'pdf';
const isVideo = (ext: string) => ['mp4', 'webm', 'mov'].includes(ext);
const isAudio = (ext: string) => ['mp3', 'wav', 'ogg', 'm4a'].includes(ext);
const isText = (ext: string) => ['txt', 'log', 'md', 'json', 'csv'].includes(ext);
// Office 文档使用 Office Online Viewer
const isOffice = (ext: string) => ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(ext);

const getIcon = (ext: string) => {
  const map: Record<string, string> = {
    pdf: 'fa-file-pdf', doc: 'fa-file-word', docx: 'fa-file-word',
    xls: 'fa-file-excel', xlsx: 'fa-file-excel',
    ppt: 'fa-file-powerpoint', pptx: 'fa-file-powerpoint',
    txt: 'fa-file-alt', csv: 'fa-file-csv', zip: 'fa-file-archive',
    json: 'fa-file-code', md: 'fa-file-alt', log: 'fa-file-alt',
  };
  return map[ext] || 'fa-file';
};

export const AttachmentPreview: React.FC<AttachmentPreviewProps> = ({
  attachments,
  initialIndex = 0,
  onClose,
}) => {
  const [index, setIndex] = useState(initialIndex);
  const [textContent, setTextContent] = useState<string>('');
  const [textLoading, setTextLoading] = useState(false);
  const [fullUrl, setFullUrl] = useState('');

  const current = attachments[index];
  const currentExt = current?.ext;
  const currentUrl = current?.url;

  useEffect(() => {
    setIndex(initialIndex);
  }, [initialIndex]);

  // 加载文本类文件内容
  useEffect(() => {
    if (!currentUrl || !currentExt) return;
    if (isText(currentExt)) {
      setTextLoading(true);
      setTextContent('');
      fileApi.getText(currentUrl)
        .then((t) => setTextContent(t.slice(0, 200000))) // 最多展示 200KB
        .catch(() => setTextContent('（加载失败）'))
        .finally(() => setTextLoading(false));
    }
  }, [currentExt, currentUrl]);

  useEffect(() => {
    if (!currentUrl) return;
    let alive = true;
    let objectUrl = '';
    setFullUrl('');
    fileApi.getBlobUrl(currentUrl)
      .then((url) => {
        objectUrl = url;
        if (alive) setFullUrl(url);
        else URL.revokeObjectURL(url);
      })
      .catch(() => setFullUrl(''));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [currentUrl]);

  // 键盘导航
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft') setIndex((i) => Math.max(0, i - 1));
      else if (e.key === 'ArrowRight') setIndex((i) => Math.min(attachments.length - 1, i + 1));
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [attachments.length, onClose]);

  if (!current) return null;

  // 对于 office 文档，使用绝对地址（如果是相对路径需要拼当前 origin）
  const absoluteUrl = fullUrl.startsWith('http')
    ? fullUrl
    : (typeof window !== 'undefined' ? window.location.origin + fullUrl : fullUrl);
  const officeViewerUrl = `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(absoluteUrl)}`;

  const renderContent = () => {
    if (isImage(current.ext)) {
      if (!fullUrl) return <div className="text-white text-sm">加载中…</div>;
      return (
        <img
          src={fullUrl}
          alt={current.name}
          className="max-w-full max-h-full object-contain"
          style={{ maxHeight: '80vh' }}
        />
      );
    }
    if (isPdf(current.ext)) {
      if (!fullUrl) return <div className="text-white text-sm">加载中…</div>;
      return (
        <iframe
          src={fullUrl}
          title={current.name}
          className="w-full bg-white rounded-lg"
          style={{ height: '80vh' }}
        />
      );
    }
    if (isVideo(current.ext)) {
      if (!fullUrl) return <div className="text-white text-sm">加载中…</div>;
      return (
        <video
          src={fullUrl}
          controls
          className="max-w-full max-h-full bg-black rounded-lg"
          style={{ maxHeight: '80vh' }}
        />
      );
    }
    if (isAudio(current.ext)) {
      if (!fullUrl) return <div className="text-white text-sm">加载中…</div>;
      return (
        <div className="bg-white rounded-lg p-8 flex flex-col items-center gap-4">
          <AppIcon className="fas fa-music text-6xl text-blue-500" />
          <div className="text-gray-700 font-medium">{current.name}</div>
          <audio src={fullUrl} controls className="w-full max-w-md" />
        </div>
      );
    }
    if (isText(current.ext)) {
      return (
        <div className="bg-white rounded-lg p-4 w-full overflow-auto" style={{ maxHeight: '80vh' }}>
          {textLoading ? (
            <div className="flex items-center justify-center py-12">
              <AppIcon className="fas fa-spinner fa-spin text-2xl text-blue-400" />
            </div>
          ) : (
            <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words font-mono">
              {textContent}
            </pre>
          )}
        </div>
      );
    }
    if (isOffice(current.ext)) {
      // 检测是否为局域网/内网地址，office viewer 需要公网可访问
      const isPublicUrl = absoluteUrl.startsWith('https://') &&
        !/192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|localhost|127\.0\.0\.1/.test(absoluteUrl);
      if (isPublicUrl) {
        return (
          <iframe
            src={officeViewerUrl}
            title={current.name}
            className="w-full bg-white rounded-lg"
            style={{ height: '80vh' }}
          />
        );
      }
      // 内网无法用 Office Viewer，提供下载
      return (
        <div className="bg-white rounded-lg p-12 flex flex-col items-center gap-4 max-w-md">
          <AppIcon className={`fas ${getIcon(current.ext)} text-6xl text-blue-500`} />
          <div className="text-center">
            <div className="text-base font-medium text-gray-800">{current.name}</div>
            <div className="text-xs text-gray-500 mt-1">{formatSize(current.size)}</div>
          </div>
          <p className="text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg text-center">
            <AppIcon className="fas fa-info-circle mr-1" />
            Office 文档在内网环境下不支持在线预览，请下载后查看
          </p>
          <button
            type="button"
            onClick={() => fileApi.download(current.url, current.name)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
          >
            <AppIcon className="fas fa-download mr-1.5" />下载文件
          </button>
        </div>
      );
    }
    // 其他类型（zip 等）
    return (
      <div className="bg-white rounded-lg p-12 flex flex-col items-center gap-4 max-w-md">
        <AppIcon className={`fas ${getIcon(current.ext)} text-6xl text-blue-500`} />
        <div className="text-center">
          <div className="text-base font-medium text-gray-800">{current.name}</div>
          <div className="text-xs text-gray-500 mt-1">{formatSize(current.size)}</div>
        </div>
        <p className="text-xs text-gray-500 text-center">该文件类型不支持在线预览</p>
        <button
          type="button"
          onClick={() => fileApi.download(current.url, current.name)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
        >
          <AppIcon className="fas fa-download mr-1.5" />下载文件
        </button>
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 bg-black/85 z-[80] flex flex-col animate-fade-in"
      onClick={onClose}
    >
      {/* 顶部工具栏 */}
      <div
        className="flex items-center gap-3 px-4 py-3 text-white"
        onClick={(e) => e.stopPropagation()}
      >
        <AppIcon className={`fas ${isImage(current.ext) ? 'fa-image' : getIcon(current.ext)} text-blue-300`} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{current.name}</div>
          <div className="text-xs text-gray-400">
            {formatSize(current.size)}
            {attachments.length > 1 && <span className="ml-2">· {index + 1} / {attachments.length}</span>}
          </div>
        </div>
        <button
          type="button"
          onClick={() => fileApi.download(current.url, current.name)}
          className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs transition-colors"
          title="下载"
        >
          <AppIcon className="fas fa-download mr-1" />下载
        </button>
        <button
          type="button"
          onClick={() => fullUrl && window.open(fullUrl, '_blank', 'noopener,noreferrer')}
          disabled={!fullUrl}
          className="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs transition-colors"
          title="新窗口打开"
        >
          <AppIcon className="fas fa-external-link-alt mr-1" />新窗口
        </button>
        <button
          onClick={onClose}
          className="w-9 h-9 rounded-lg flex items-center justify-center bg-white/10 hover:bg-white/20 transition-colors"
          title="关闭 (ESC)"
        >
          <AppIcon className="fas fa-times" />
        </button>
      </div>

      {/* 内容区 */}
      <div
        className="flex-1 flex items-center justify-center px-4 pb-4 relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 上一张 */}
        {attachments.length > 1 && (
          <button
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
            className="absolute left-4 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors z-10"
            title="上一个 (←)"
          >
            <AppIcon className="fas fa-chevron-left" />
          </button>
        )}

        <div className="max-w-5xl w-full flex items-center justify-center">{renderContent()}</div>

        {/* 下一张 */}
        {attachments.length > 1 && (
          <button
            onClick={() => setIndex((i) => Math.min(attachments.length - 1, i + 1))}
            disabled={index === attachments.length - 1}
            className="absolute right-4 w-10 h-10 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors z-10"
            title="下一个 (→)"
          >
            <AppIcon className="fas fa-chevron-right" />
          </button>
        )}
      </div>
    </div>
  );
};

export default AttachmentPreview;
