// @ts-nocheck
/**
 * 问题反馈对话框：支持缺陷、需求、其他类型的问题收集，可上传图片/文档附件。
 * 当前页面 URL 和 UserAgent 自动捕获，便于后续定位。
 */
import React, { useEffect, useRef, useState } from 'react';
import { hrmApi } from '../utils/api';
import toast from '../utils/toast';

import AppIcon from './AppIcon';
import { ProtectedImage } from './ProtectedFile';
interface FeedbackDialogProps {
  open: boolean;
  onClose: () => void;
}

type FeedbackType = 'bug' | 'feature' | 'other';
type Severity = 'low' | 'medium' | 'high' | 'critical';

interface Attachment {
  name: string;
  url: string;
  size: number;
  type: 'image' | 'document';
  ext: string;
  uploading?: boolean;
  error?: string;
}

const typeOptions: Array<{ value: FeedbackType; label: string; icon: string; color: string; desc: string }> = [
  { value: 'bug', label: '缺陷反馈', icon: 'fa-bug', color: 'text-red-500 bg-red-50 border-red-200', desc: '页面错误、功能异常等问题' },
  { value: 'feature', label: '需求建议', icon: 'fa-lightbulb', color: 'text-amber-500 bg-amber-50 border-amber-200', desc: '功能改进、新增需求等建议' },
  { value: 'other', label: '其他反馈', icon: 'fa-comment-dots', color: 'text-blue-500 bg-blue-50 border-blue-200', desc: '使用体验、咨询等其他问题' },
];

const severityOptions: Array<{ value: Severity; label: string; color: string }> = [
  { value: 'low', label: '低', color: 'border-gray-300 text-gray-600 hover:bg-gray-50' },
  { value: 'medium', label: '中', color: 'border-amber-300 text-amber-600 hover:bg-amber-50' },
  { value: 'high', label: '高', color: 'border-orange-300 text-orange-600 hover:bg-orange-50' },
  { value: 'critical', label: '紧急', color: 'border-red-300 text-red-600 hover:bg-red-50' },
];

const MAX_ATTACHMENTS = 5;
const MAX_SIZE_MB = 10;
const ACCEPT_EXTENSIONS = '.jpg,.jpeg,.png,.gif,.bmp,.webp,.tiff,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.log,.md,.json,.zip';

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const getFileIcon = (ext: string, type: string) => {
  if (type === 'image') return 'fa-image';
  const map: Record<string, string> = {
    pdf: 'fa-file-pdf',
    doc: 'fa-file-word',
    docx: 'fa-file-word',
    xls: 'fa-file-excel',
    xlsx: 'fa-file-excel',
    ppt: 'fa-file-powerpoint',
    pptx: 'fa-file-powerpoint',
    txt: 'fa-file-alt',
    csv: 'fa-file-csv',
    zip: 'fa-file-archive',
    log: 'fa-file-alt',
    md: 'fa-file-alt',
    json: 'fa-file-code',
  };
  return map[ext] || 'fa-file';
};

export const FeedbackDialog: React.FC<FeedbackDialogProps> = ({ open, onClose }) => {
  const [feedbackType, setFeedbackType] = useState<FeedbackType>('bug');
  const [severity, setSeverity] = useState<Severity>('medium');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setFeedbackType('bug');
      setSeverity('medium');
      setTitle('');
      setContent('');
      setAttachments([]);
    }
  }, [open]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const uploadingCount = attachments.filter((a) => a.uploading).length;

  const handleFiles = async (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (attachments.length + arr.length > MAX_ATTACHMENTS) {
      toast.warning(`最多上传 ${MAX_ATTACHMENTS} 个附件`);
      return;
    }

    for (const file of arr) {
      if (file.size > MAX_SIZE_MB * 1024 * 1024) {
        toast.error(`${file.name} 超过 ${MAX_SIZE_MB}MB 限制`);
        continue;
      }

      // 占位（uploading 状态）
      const placeholder: Attachment = {
        name: file.name,
        url: '',
        size: file.size,
        type: file.type.startsWith('image/') ? 'image' : 'document',
        ext: (file.name.split('.').pop() || '').toLowerCase(),
        uploading: true,
      };
      setAttachments((prev) => [...prev, placeholder]);

      try {
        const result = await hrmApi.uploadFeedbackAttachment(file);
        setAttachments((prev) => {
          const idx = prev.findIndex((a) => a === placeholder);
          if (idx === -1) return prev;
          const next = [...prev];
          next[idx] = { ...result, uploading: false };
          return next;
        });
      } catch (e: any) {
        setAttachments((prev) => {
          const idx = prev.findIndex((a) => a === placeholder);
          if (idx === -1) return prev;
          const next = [...prev];
          next[idx] = { ...placeholder, uploading: false, error: e?.message || '上传失败' };
          return next;
        });
        toast.error(`${file.name}: ${e?.message || '上传失败'}`);
      }
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
      e.target.value = ''; // 允许重复选择同一文件
    }
  };

  const handleRemoveAttachment = (idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  // 拖拽上传
  const [dragOver, setDragOver] = useState(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleSubmit = async () => {
    if (!title.trim()) {
      toast.warning('请填写反馈标题');
      return;
    }
    if (!content.trim()) {
      toast.warning('请填写问题描述');
      return;
    }
    if (content.trim().length < 5) {
      toast.warning('问题描述太短，请详细说明');
      return;
    }
    if (uploadingCount > 0) {
      toast.warning('附件还在上传，请稍候');
      return;
    }

    // 只把上传成功的附件提交
    const validAttachments = attachments
      .filter((a) => !a.uploading && !a.error && a.url)
      .map(({ uploading: _uploading, error: _error, ...rest }) => rest);

    setSubmitting(true);
    try {
      await hrmApi.create('feedbacks', {
        feedbackType,
        severity: feedbackType === 'bug' ? severity : 'medium',
        title: title.trim(),
        content: content.trim(),
        pageUrl: typeof window !== 'undefined' ? window.location.href : '',
        userAgent: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 500) : '',
        attachments: validAttachments,
      });
      toast.success('反馈已提交，感谢您的反馈！');
      onClose();
    } catch (e: any) {
      toast.error(e?.message || '提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  const currentType = typeOptions.find((t) => t.value === feedbackType)!;

  return (
    <>
      {/* 遮罩 */}
      <div className="fixed inset-0 bg-black/40 z-[60] animate-fade-in" onClick={onClose} />
      {/* 对话框 */}
      <div className="fixed inset-0 z-[61] flex items-center justify-center p-4 pointer-events-none">
        <div
          className="bg-white rounded-2xl shadow-2xl w-full max-w-lg pointer-events-auto animate-fade-in overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 头部 */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center">
                <AppIcon className="fas fa-comment-medical text-blue-600 text-sm" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-gray-900">问题反馈</h3>
                <p className="text-xs text-gray-400 mt-0.5">您的反馈是我们改进的动力</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
            >
              <AppIcon className="fas fa-times text-sm" />
            </button>
          </div>

          {/* 内容区 */}
          <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
            {/* 反馈类型 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">反馈类型</label>
              <div className="grid grid-cols-3 gap-2">
                {typeOptions.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setFeedbackType(opt.value)}
                    className={`flex flex-col items-center justify-center px-2 py-3 rounded-lg border text-xs transition-all ${
                      feedbackType === opt.value
                        ? `${opt.color} border-current font-semibold ring-2 ring-offset-1 ring-current/30`
                        : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <AppIcon className={`fas ${opt.icon} text-base mb-1`} />
                    <span>{opt.label}</span>
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-gray-400 mt-1.5">{currentType.desc}</p>
            </div>

            {/* 严重程度（仅缺陷） */}
            {feedbackType === 'bug' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">严重程度</label>
                <div className="grid grid-cols-4 gap-2">
                  {severityOptions.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setSeverity(opt.value)}
                      className={`px-3 py-1.5 rounded-lg border text-xs transition-all ${
                        severity === opt.value
                          ? `${opt.color} font-semibold ring-2 ring-offset-1 ring-current/30`
                          : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 标题 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                标题 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={100}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 outline-none transition-all bg-gray-50 focus:bg-white"
                placeholder="一句话概括问题"
              />
              <div className="text-[11px] text-gray-400 text-right mt-0.5">{title.length}/100</div>
            </div>

            {/* 详细描述 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                详细描述 <span className="text-red-500">*</span>
              </label>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                maxLength={2000}
                rows={5}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 outline-none transition-all bg-gray-50 focus:bg-white resize-none"
                placeholder={
                  feedbackType === 'bug'
                    ? '请描述：1) 操作步骤  2) 期望结果  3) 实际现象'
                    : feedbackType === 'feature'
                    ? '请描述：1) 您希望增加的功能  2) 使用场景  3) 预期效果'
                    : '请详细描述您的问题或建议'
                }
              />
              <div className="text-[11px] text-gray-400 text-right mt-0.5">{content.length}/2000</div>
            </div>

            {/* 附件上传 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                附件
                <span className="text-[11px] text-gray-400 ml-1.5 font-normal">
                  （图片或文档，最多 {MAX_ATTACHMENTS} 个，单个 ≤ {MAX_SIZE_MB}MB）
                </span>
              </label>

              {/* 拖拽上传区 */}
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`relative border-2 border-dashed rounded-lg px-4 py-3 cursor-pointer transition-all ${
                  dragOver
                    ? 'border-blue-400 bg-blue-50'
                    : 'border-gray-200 hover:border-blue-300 hover:bg-blue-50/30'
                } ${attachments.length >= MAX_ATTACHMENTS ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
                  <AppIcon className="fas fa-cloud-upload-alt text-blue-500" />
                  <span>点击或拖拽文件到此处上传</span>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={ACCEPT_EXTENSIONS}
                  onChange={handleFileInput}
                  className="hidden"
                />
              </div>

              {/* 附件列表 */}
              {attachments.length > 0 && (
                <ul className="mt-2 space-y-1.5">
                  {attachments.map((att, idx) => (
                    <li
                      key={idx}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${
                        att.error
                          ? 'border-red-200 bg-red-50'
                          : att.uploading
                          ? 'border-blue-200 bg-blue-50'
                          : 'border-gray-200 bg-gray-50'
                      }`}
                    >
                      {/* 缩略图或图标 */}
                      {att.type === 'image' && att.url && !att.uploading ? (
                        <ProtectedImage
                          fileUrl={att.url}
                          alt={att.name}
                          className="w-8 h-8 rounded object-cover flex-shrink-0 border border-gray-200"
                        />
                      ) : (
                        <div className="w-8 h-8 rounded bg-white border border-gray-200 flex items-center justify-center flex-shrink-0">
                          {att.uploading ? (
                            <AppIcon className="fas fa-spinner fa-spin text-blue-500 text-xs" />
                          ) : att.error ? (
                            <AppIcon className="fas fa-exclamation-triangle text-red-500 text-xs" />
                          ) : (
                            <AppIcon className={`fas ${getFileIcon(att.ext, att.type)} text-blue-500 text-sm`} />
                          )}
                        </div>
                      )}

                      {/* 名称和大小 */}
                      <div className="flex-1 min-w-0">
                        <div className="text-gray-800 truncate" title={att.name}>
                          {att.name}
                        </div>
                        <div className="text-[10px] text-gray-400">
                          {att.uploading ? '上传中...' : att.error ? att.error : formatSize(att.size)}
                        </div>
                      </div>

                      {/* 删除按钮 */}
                      <button
                        type="button"
                        onClick={() => handleRemoveAttachment(idx)}
                        className="w-6 h-6 rounded flex items-center justify-center text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors flex-shrink-0"
                        title="移除"
                      >
                        <AppIcon className="fas fa-times text-xs" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 自动捕获信息 */}
            <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
              <div className="flex items-start gap-2 text-[11px] text-gray-500">
                <AppIcon className="fas fa-info-circle text-gray-400 mt-0.5" />
                <div className="flex-1">
                  <div className="text-gray-600 font-medium mb-1">将自动附带以下信息以协助定位</div>
                  <div className="truncate">
                    页面：{typeof window !== 'undefined' ? window.location.pathname + window.location.search : ''}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 底部按钮 */}
          <div className="flex items-center justify-end gap-2 px-6 py-3 bg-gray-50 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting || uploadingCount > 0}
              className="px-4 py-1.5 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 shadow-sm"
            >
              {submitting ? (
                <>
                  <AppIcon className="fas fa-spinner fa-spin mr-1.5" />提交中...
                </>
              ) : uploadingCount > 0 ? (
                <>
                  <AppIcon className="fas fa-spinner fa-spin mr-1.5" />等待上传完成...
                </>
              ) : (
                <>
                  <AppIcon className="fas fa-paper-plane mr-1.5" />提交反馈
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default FeedbackDialog;
