import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import { DEFAULT_SCORING_CRITERIA, ScoringCriterion, jobsApi } from '../../utils/api';


import AppIcon from '../../components/AppIcon';
export default function JobCreatePage() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    requirements: '',
    salary: '',
    location: '',
    type: 'full-time'
  });
  const [scoringCriteria, setScoringCriteria] = useState<ScoringCriterion[]>(
    JSON.parse(JSON.stringify(DEFAULT_SCORING_CRITERIA))
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    document.title = '新建岗位 - 恒聘通';
  }, []);

  const handleInputChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleWeightChange = (index: number, value: number) => {
    const newCriteria = [...scoringCriteria];
    newCriteria[index].weight = Math.max(0, Math.min(100, value));
    setScoringCriteria(newCriteria);
  };

  const getTotalWeight = () => {
    return scoringCriteria.reduce((sum, c) => sum + c.weight, 0);
  };

  const resetWeights = () => {
    setScoringCriteria(JSON.parse(JSON.stringify(DEFAULT_SCORING_CRITERIA)));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!formData.title.trim()) {
      setError('请输入岗位名称');
      return;
    }

    if (!formData.description.trim()) {
      setError('请输入岗位描述');
      return;
    }

    const totalWeight = getTotalWeight();
    if (totalWeight !== 100) {
      setError(`评分权重总和必须为100%，当前为${totalWeight}%`);
      return;
    }

    setIsSubmitting(true);

    try {
      const description = `
${formData.description}

**岗位要求：**
${formData.requirements}

**薪资范围：** ${formData.salary || '面议'}
**工作地点：** ${formData.location || '待定'}
**工作类型：** ${formData.type === 'full-time' ? '全职' : formData.type === 'part-time' ? '兼职' : '实习'}
      `.trim();

      // 使用 apiClient 创建岗位（自动带 token、X-Request-ID、401 处理）
      await jobsApi.create(formData.title, description);
      
      toast.success('岗位创建成功');
      navigate('/job-manage');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '创建失败，请重试';
      setError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Layout>
      <div className="max-w-4xl mx-auto">
        {/* 页面头部 */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-800 mb-2">新建岗位</h2>
          <nav className="text-sm text-gray-600">
            <span>首页</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>岗位管理</span>
            <AppIcon className="fas fa-chevron-right mx-2 text-xs" />
            <span>新建岗位</span>
          </nav>
        </div>

        {/* 表单 */}
        <div className="bg-white rounded-xl border border-gray-200 p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* 岗位名称 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                岗位名称 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                name="title"
                value={formData.title}
                onChange={handleInputChange}
                aria-label="岗位名称"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="例如：高级前端开发工程师"
                required
              />
            </div>

            {/* 岗位描述 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                岗位描述 <span className="text-red-500">*</span>
              </label>
              <textarea
                name="description"
                value={formData.description}
                onChange={handleInputChange}
                aria-label="岗位描述"
                rows={6}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="请详细描述岗位职责和工作内容..."
                required
              />
            </div>

            {/* 任职要求 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                任职要求
              </label>
              <textarea
                name="requirements"
                value={formData.requirements}
                onChange={handleInputChange}
                aria-label="任职要求"
                rows={6}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="请列出岗位的任职要求..."
              />
            </div>

            {/* 两列布局 */}
            <div className="grid grid-cols-2 gap-6">
              {/* 薪资范围 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  薪资范围
                </label>
                <input
                  type="text"
                  name="salary"
                  value={formData.salary}
                  onChange={handleInputChange}
                  aria-label="薪资范围"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：15K-25K"
                />
              </div>

              {/* 工作地点 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  工作地点
                </label>
                <input
                  type="text"
                  name="location"
                  value={formData.location}
                  onChange={handleInputChange}
                  aria-label="工作地点"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：北京·朝阳区"
                />
              </div>
            </div>

            {/* 工作类型 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                工作类型
              </label>
              <select
                name="type"
                value={formData.type}
                onChange={handleInputChange}
                aria-label="工作类型"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="full-time">全职</option>
                <option value="part-time">兼职</option>
                <option value="internship">实习</option>
              </select>
            </div>

            {/* AI评分权重设置 */}
            <div className="border-t border-gray-200 pt-6">
              <div className="flex items-center justify-between mb-4">
                <label className="block text-sm font-medium text-gray-700">
                  <AppIcon className="fas fa-sliders-h text-blue-600 mr-2" />
                  AI评分权重设置
                </label>
                <div className="flex items-center space-x-3">
                  <span className={`text-sm font-medium ${getTotalWeight() === 100 ? 'text-green-600' : 'text-red-600'}`}>
                    总权重: {getTotalWeight()}%
                  </span>
                  <button
                    type="button"
                    onClick={resetWeights}
                    className="text-sm text-blue-600 hover:text-blue-700"
                  >
                    <AppIcon className="fas fa-undo mr-1" />
                    恢复默认
                  </button>
                </div>
              </div>
              
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                <p className="text-sm text-blue-800">
                  <AppIcon className="fas fa-info-circle mr-2" />
                  AI将根据以下权重对简历进行评分。权重总和必须为100%。调整权重可以让AI更关注你认为重要的方面。
                </p>
              </div>

              <div className="space-y-3">
                {scoringCriteria.map((criterion, index) => (
                  <div key={index} className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex-1">
                        <p className="text-sm font-medium text-gray-800">{criterion.name}</p>
                        <p className="text-xs text-gray-500 mt-1">{criterion.description}</p>
                      </div>
                      <div className="flex items-center space-x-3 ml-4">
                        <input
                          type="range"
                          min="0"
                          max="50"
                          value={criterion.weight}
                          aria-label={`${criterion.name}权重滑块`}
                          onChange={(e) => handleWeightChange(index, parseInt(e.target.value))}
                          className="w-32"
                        />
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={criterion.weight}
                          aria-label={`${criterion.name}权重数值`}
                          onChange={(e) => handleWeightChange(index, parseInt(e.target.value) || 0)}
                          className="w-16 px-2 py-1 border border-gray-300 rounded text-center text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        <span className="text-sm text-gray-600 w-4">%</span>
                      </div>
                    </div>
                    {/* 权重进度条 */}
                    <div className="mt-2 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 transition-all"
                        style={{ width: `${criterion.weight}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>

              {getTotalWeight() !== 100 && (
                <div className="mt-4 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                  <AppIcon className="fas fa-exclamation-triangle mr-2" />
                  权重总和必须为100%，请调整各项权重！当前总和：{getTotalWeight()}%
                </div>
              )}
            </div>

            {/* 错误信息 */}
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                <AppIcon className="fas fa-exclamation-circle mr-2" />
                {error}
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex items-center space-x-4">
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex-1 bg-blue-600 text-white py-3 px-6 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <>
                    <AppIcon className="fas fa-spinner fa-spin mr-2" />
                    创建中...
                  </>
                ) : (
                  <>
                    <AppIcon className="fas fa-plus mr-2" />
                    创建岗位
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => navigate('/job-manage')}
                disabled={isSubmitting}
                className="flex-1 bg-white border border-gray-300 text-gray-700 py-3 px-6 rounded-lg hover:bg-gray-50 transition-colors"
              >
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </Layout>
  );
}
