import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import confirm from '../../components/ConfirmDialog';
import { jobsApi, Job } from '../../utils/api';


import AppIcon from '../../components/AppIcon';
export default function ResumeUploadPage() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [isLoadingJobs, setIsLoadingJobs] = useState(true);
  const [uploadResults, setUploadResults] = useState<{
    success: number; 
    failed: number;
    replaced: number;
    replacedInfo?: Array<{name: string; count: number}>;
  } | null>(null);

  useEffect(() => {
    document.title = '上传简历 - 恒聘通';
    loadJobs();
  }, []);

  const loadJobs = async () => {
    try {
      const data = await jobsApi.getAll();
      const openJobs = data.filter(j => j.status === 'open');
      setJobs(openJobs);
      if (openJobs.length > 0) {
        setSelectedJobId(openJobs[0].id);
      }
    } catch (_err) {
      setError('加载岗位列表失败');
    } finally {
      setIsLoadingJobs(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    
    const allowedTypes = [
      'application/pdf',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain',
      'image/jpeg',
      'image/jpg',
      'image/png',
      'image/bmp',
      'image/tiff',
      'image/webp'
    ];
    
    const newValidFiles: File[] = [];
    const errors: string[] = [];
    
    // 验证所有新选择的文件
    Array.from(fileList).forEach((file) => {
      // 检查是否已存在
      const isDuplicate = selectedFiles.some(f => f.name === file.name && f.size === file.size);
      if (isDuplicate) {
        errors.push(`${file.name}: 文件已存在`);
      } else if (!allowedTypes.includes(file.type)) {
        errors.push(`${file.name}: 不支持的文件类型`);
      } else if (file.size > 5 * 1024 * 1024) {
        errors.push(`${file.name}: 文件超过5MB`);
      } else {
        newValidFiles.push(file);
      }
    });
    
    if (errors.length > 0) {
      setError(errors.join('; '));
      setTimeout(() => setError(''), 5000); // 5秒后自动清除错误
    }
    
    // 追加到现有文件列表
    if (newValidFiles.length > 0) {
      setSelectedFiles(prev => [...prev, ...newValidFiles]);
      setError(''); // 清除之前的错误
    }
    
    // 重置input，允许重复选择相同文件
    e.target.value = '';
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (selectedFiles.length === 0) {
      setError('请选择要上传的简历文件');
      return;
    }

    if (!selectedJobId) {
      setError('请选择应聘岗位');
      return;
    }

    setIsUploading(true);
    setError('');
    setUploadProgress(0);
    setUploadResults(null);

    try {
      // 模拟上传进度
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 200);

      // 批量上传
      const formData = new FormData();
      selectedFiles.forEach(file => {
        formData.append('file', file);
      });
      formData.append('jobId', selectedJobId);

      const response = await fetch('/api/resumes/upload', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: formData,
      });

      if (!response.ok) {
        throw new Error('上传失败');
      }

      const result = await response.json();

      clearInterval(progressInterval);
      setUploadProgress(100);
      setSuccess(true);
      setUploadResults({ 
        success: result.success, 
        failed: result.failed,
        replaced: result.replaced || 0,
        replacedInfo: result.replacedInfo
      });

      setTimeout(() => {
        navigate('/resume-manage');
      }, 3000);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '上传失败，请重试';
      setError(errorMessage);
      setUploadProgress(0);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      // 创建一个临时的DataTransfer对象来模拟input的files
      const dt = new DataTransfer();
      Array.from(files).forEach(file => dt.items.add(file));
      
      const fakeEvent = {
        target: { 
          files: dt.files,
          value: '' // 模拟清空
        }
      } as React.ChangeEvent<HTMLInputElement>;
      handleFileChange(fakeEvent);
    }
  };
  
  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };
  
  const handleClearAll = async () => {
    const ok = await confirm({
      title: '清空文件',
      message: `确定要清空所有已选择的 ${selectedFiles.length} 个文件吗？`,
      danger: true,
      confirmText: '清空',
    });
    if (ok) {
      setSelectedFiles([]);
      setError('');
    }
  };

  if (isLoadingJobs) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64">
          <AppIcon className="fas fa-spinner fa-spin text-3xl text-blue-500" />
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-3xl mx-auto">
        {/* 页面头部 */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-800 mb-2">上传简历</h2>
          <nav className="text-sm text-gray-600">
            <span>首页</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>简历管理</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>上传简历</span>
          </nav>
        </div>

        {jobs.length === 0 ? (
          <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-8 text-center">
            <AppIcon className="fas fa-exclamation-triangle text-4xl text-yellow-600 mb-4" />
            <h3 className="text-lg font-semibold text-gray-800 mb-2">暂无开放岗位</h3>
            <p className="text-gray-600 mb-4">请先创建岗位后再上传简历</p>
            <button
              onClick={() => navigate('/job-create')}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <AppIcon className="fas fa-plus mr-2" />
              创建岗位
            </button>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 p-8">
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* 选择岗位 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  应聘岗位 <span className="text-red-500">*</span>
                </label>
                <select
                  value={selectedJobId}
                  onChange={(e) => setSelectedJobId(e.target.value)}
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={isUploading}
                  required
                >
                  {jobs.map(job => (
                    <option key={job.id} value={job.id}>
                      {job.title}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-sm text-gray-500">
                  <AppIcon className="fas fa-info-circle mr-1" />
                  AI将根据所选岗位要求自动分析简历匹配度
                </p>
              </div>

            {/* 文件上传区域 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                简历文件 <span className="text-red-500">*</span>
              </label>
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                className="border-2 border-dashed rounded-lg p-6 text-center border-gray-300 hover:border-blue-400 transition-colors"
              >
                <input
                  type="file"
                  id="file-upload"
                  onChange={handleFileChange}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png,.bmp,.tiff,.webp"
                  disabled={isUploading}
                  multiple
                />
                <label
                  htmlFor="file-upload"
                  className="cursor-pointer block"
                >
                  <AppIcon className="fas fa-cloud-upload-alt text-4xl text-gray-400 mb-3" />
                  <p className="text-gray-600 font-medium">
                    点击选择文件或拖拽到此处
                  </p>
                  <p className="text-sm text-gray-500 mt-2">
                    支持 PDF、Word、TXT、图片(JPG/PNG等)，单个文件不超过 5MB
                  </p>
                  {selectedFiles.length > 0 && (
                    <p className="text-sm text-blue-600 mt-2">
                      已选择 {selectedFiles.length} 个文件，可继续添加
                    </p>
                  )}
                </label>
              </div>
              
              {/* 文件列表 - 类似通义千问风格 */}
              {selectedFiles.length > 0 && (
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-sm font-medium text-gray-700">
                      已选择的文件 ({selectedFiles.length})
                    </p>
                    <button
                      type="button"
                      onClick={handleClearAll}
                      disabled={isUploading}
                      className="text-xs text-red-600 hover:text-red-700 disabled:opacity-50 flex items-center"
                    >
                      <AppIcon className="fas fa-trash-alt mr-1" />
                      清空全部
                    </button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {selectedFiles.map((file, index) => (
                      <div
                        key={`${file.name}-${index}`}
                        className="group relative bg-gradient-to-br from-white to-gray-50 border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-md transition-all cursor-default"
                      >
                        {/* 删除按钮 - 悬停时显示 */}
                        <button
                          type="button"
                          onClick={() => removeFile(index)}
                          disabled={isUploading}
                          className="absolute -top-2 -right-2 w-7 h-7 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50 flex items-center justify-center hover:bg-red-600 hover:scale-110 shadow-lg z-10"
                          title="删除文件"
                        >
                          <AppIcon className="fas fa-times text-xs" />
                        </button>
                        
                        <div className="flex items-center space-x-3">
                          {/* 文件图标 */}
                          <div className="flex-shrink-0 w-12 h-12 flex items-center justify-center rounded-lg bg-white shadow-sm">
                            {file.name.endsWith('.pdf') ? (
                              <AppIcon className="fas fa-file-pdf text-2xl text-red-500" />
                            ) : file.name.endsWith('.doc') || file.name.endsWith('.docx') ? (
                              <AppIcon className="fas fa-file-word text-2xl text-blue-500" />
                            ) : file.name.match(/\.(jpg|jpeg|png|bmp|tiff|webp)$/i) ? (
                              <AppIcon className="fas fa-file-image text-2xl text-green-500" />
                            ) : (
                              <AppIcon className="fas fa-file-alt text-2xl text-gray-500" />
                            )}
                          </div>
                          
                          {/* 文件信息 */}
                          <div className="flex-1 min-w-0">
                            <p 
                              className="text-sm font-medium text-gray-800 truncate leading-tight" 
                              title={file.name}
                            >
                              {file.name}
                            </p>
                            <div className="flex items-center mt-1.5 space-x-2">
                              <p className="text-xs text-gray-500">
                                {(file.size / 1024).toFixed(1)} KB
                              </p>
                              <span className="w-1 h-1 bg-gray-300 rounded-full"></span>
                              <p className="text-xs text-green-600 flex items-center">
                                <AppIcon className="fas fa-check-circle mr-1" />
                                就绪
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 上传进度 */}
            {isUploading && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-gray-600">
                    {uploadProgress < 90 ? '正在上传简历...' : '正在AI解析简历...'}
                  </span>
                  <span className="text-sm text-gray-600">{uploadProgress}%</span>
                </div>
                <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  ></div>
                </div>
                {uploadProgress >= 90 && (
                  <p className="text-sm text-blue-600 mt-2 flex items-center">
                    <AppIcon className="fas fa-robot mr-2" />
                    AI正在分析简历内容，提取关键信息...
                  </p>
                )}
              </div>
            )}

            {/* 错误信息 */}
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                <AppIcon className="fas fa-exclamation-circle mr-2" />
                {error}
              </div>
            )}

            {/* 成功信息 */}
            {success && uploadResults && (
              <div className="space-y-3">
                <div className="bg-green-50 border border-green-200 text-green-600 px-4 py-3 rounded-lg">
                  <AppIcon className="fas fa-check-circle mr-2" />
                  上传完成！成功 {uploadResults.success} 个
                  {uploadResults.failed > 0 && `，失败 ${uploadResults.failed} 个`}
                  {uploadResults.replaced > 0 && `，自动替换 ${uploadResults.replaced} 个重复简历`}
                  。AI已完成简历解析，正在跳转...
                </div>
                
                {/* 显示替换详情 */}
                {uploadResults.replaced > 0 && uploadResults.replacedInfo && (
                  <div className="bg-orange-50 border border-orange-200 text-orange-700 px-4 py-3 rounded-lg">
                    <div className="flex items-start">
                      <AppIcon className="fas fa-info-circle mr-2 mt-0.5" />
                      <div className="flex-1">
                        <p className="font-medium mb-2">检测到重复简历，已自动替换为最新版本：</p>
                        <ul className="text-sm space-y-1">
                          {uploadResults.replacedInfo.map((info, idx) => (
                            <li key={idx}>
                              • {info.name} - 替换了 {info.count} 条旧记录
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex items-center space-x-4">
              <button
                type="submit"
                disabled={isUploading || success || selectedFiles.length === 0}
                className="flex-1 bg-blue-600 text-white py-3 px-6 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isUploading ? (
                  <>
                    <AppIcon className="fas fa-spinner fa-spin mr-2" />
                    正在上传 {selectedFiles.length} 个文件...
                  </>
                ) : (
                  <>
                    <AppIcon className="fas fa-upload mr-2" />
                    {selectedFiles.length > 0 
                      ? `上传 ${selectedFiles.length} 个简历` 
                      : '上传简历'}
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => navigate('/resume-manage')}
                disabled={isUploading}
                className="flex-1 bg-white border border-gray-300 text-gray-700 py-3 px-6 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                取消
              </button>
            </div>
          </form>

          {/* 温馨提示 */}
          <div className="mt-8 p-4 bg-blue-50 rounded-lg">
            <h4 className="text-sm font-medium text-blue-800 mb-2">
              <AppIcon className="fas fa-robot mr-2" />
              AI智能解析说明
            </h4>
            <ul className="text-sm text-blue-700 space-y-1 ml-6">
              <li>• 支持上传 PDF、Word (doc/docx)、TXT 和图片格式的简历文件</li>
              <li>• <strong className="text-green-600">OCR识别：</strong>支持扫描版PDF和图片简历，自动OCR识别文字</li>
              <li>• 支持同时选择多个文件批量上传</li>
              <li>• 单个文件大小不能超过 5MB</li>
              <li>• 上传后AI将自动解析简历内容，提取关键信息</li>
              <li>• AI会根据岗位要求计算匹配度和评分，生成面试建议</li>
              <li>• 自动提取姓名、联系方式、技能、经验等信息</li>
              <li>• <strong className="text-orange-600">智能去重：</strong>如果检测到同名同岗位或同名同联系方式，将自动替换为最新版本</li>
            </ul>
          </div>
        </div>
        )}
      </div>
    </Layout>
  );
}
