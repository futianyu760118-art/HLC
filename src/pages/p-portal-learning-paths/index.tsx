// @ts-nocheck
/**
 * 我的学习路径（员工门户）— 闯关式地图
 * 阶段顺序解锁，每阶段显示课程完成状态
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

const GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
];

export default function P_portal_learning_paths() {
  const navigate = useNavigate();
  const [paths, setPaths] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    document.title = '学习路径';
    fetch('/api/portal/learning-paths', { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } })
      .then(r => r.json())
      .then(setPaths)
      .catch(err => toast.error(err.message || '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;

  if (paths.length === 0) {
    return (
      <Layout>
        <div className="max-w-3xl mx-auto px-4 md:px-6 py-6">
          <h1 className="text-2xl font-bold text-text-primary mb-4">学习路径</h1>
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-light flex items-center justify-center">
              <AppIcon className="fas fa-route text-2xl text-text-secondary" />
            </div>
            <p className="text-text-secondary">暂无学习路径</p>
            <p className="text-sm text-text-secondary mt-1">管理员可为你分配岗位成长路径</p>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto px-4 md:px-6 py-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-text-primary">学习路径</h1>
          <p className="text-sm text-text-secondary mt-1">按阶段闯关学习，完成岗位成长地图</p>
        </div>

        <div className="space-y-4">
          {paths.map((path, pi) => (
            <div key={path.pathId} className="bg-white rounded-xl border border-border-light overflow-hidden">
              {/* 路径头 */}
              <div className="p-5 cursor-pointer" onClick={() => setExpanded(expanded === path.pathId ? null : path.pathId)}>
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-xl flex items-center justify-center shrink-0" style={{ background: GRADIENTS[pi % GRADIENTS.length] }}>
                    <AppIcon className="fas fa-route text-white text-xl" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="font-semibold text-text-primary">{path.name}</h2>
                      {path.isCompleted && <span className="px-2 py-0.5 rounded-full text-xs bg-success text-white flex items-center gap-1"><AppIcon className="fas fa-check text-[10px]" /> 已完成</span>}
                    </div>
                    {path.targetPosition && <p className="text-sm text-text-secondary mt-0.5">目标：{path.targetPosition}</p>}
                    {/* 进度条 */}
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex-1 h-2 rounded-full bg-bg-light overflow-hidden">
                        <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${path.progress}%` }} />
                      </div>
                      <span className="text-xs font-medium text-primary tabular-nums">{path.progress}%</span>
                    </div>
                    <div className="text-xs text-text-secondary mt-1">
                      第 {Math.min(path.currentStage + 1, path.stageCount)} / {path.stageCount} 阶段
                    </div>
                  </div>
                  <AppIcon className={`fas fa-chevron-down text-text-secondary transition-transform ${expanded === path.pathId ? 'rotate-180' : ''}`} />
                </div>
              </div>

              {/* 阶段展开 */}
              {expanded === path.pathId && (
                <div className="border-t border-border-light bg-bg-light/30 p-5 space-y-3">
                  {path.stages.map((stage, si) => {
                    const isLocked = !stage.unlocked;
                    return (
                      <div key={si} className={`rounded-lg border ${isLocked ? 'border-border-light bg-bg-light/50 opacity-60' : 'border-border-light bg-white'} p-4`}>
                        <div className="flex items-center gap-3 mb-3">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${
                            stage.completed ? 'bg-success text-white' : isLocked ? 'bg-bg-light text-text-secondary' : 'bg-primary text-white'
                          }`}>
                            {stage.completed ? <AppIcon className="fas fa-check" /> : isLocked ? <AppIcon className="fas fa-lock text-xs" /> : si + 1}
                          </div>
                          <div className="flex-1">
                            <span className="font-medium text-text-primary text-sm">{stage.name}</span>
                            {stage.hasExam && <span className="ml-2 text-xs text-warning"><AppIcon className="fas fa-clipboard-check" /> 含考试</span>}
                          </div>
                          {stage.completed && <span className="text-xs text-success">阶段已完成</span>}
                        </div>
                        {/* 课程列表 */}
                        <div className="pl-11 space-y-1.5">
                          {stage.courses.map(c => (
                            <div key={c.id} className="flex items-center gap-2 text-sm">
                              <AppIcon className={`fas ${c.isFinished ? 'fa-check-circle text-success' : 'fa-circle text-text-secondary'} text-xs`} />
                              <button onClick={() => !isLocked && navigate(`/portal/course/${c.id}`)}
                                className={`hover:text-primary ${c.isFinished ? 'text-text-secondary line-through' : 'text-text-primary'}`}>
                                {c.title}
                              </button>
                            </div>
                          ))}
                          {stage.courses.length === 0 && <div className="text-xs text-text-secondary">本阶段无课程</div>}
                        </div>
                        {/* 阶段考试入口 */}
                        {stage.hasExam && stage.unlocked && !isLocked && (
                          <div className="pl-11 mt-2">
                            <button onClick={() => navigate('/portal/my-exams')}
                              className="text-xs text-warning hover:underline flex items-center gap-1">
                              <AppIcon className="fas fa-clipboard-check" /> 前往阶段考试
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </Layout>
  );
}
