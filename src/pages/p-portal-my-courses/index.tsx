// @ts-nocheck
/**
 * 我的课程（网格视图，复用首页 CourseCard）
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';
import { CourseCard } from '../p-portal-home';

export default function P_portal_my_courses() {
  const navigate = useNavigate();
  const [courses, setCourses] = useState<any[]>([]);
  const [filter, setFilter] = useState<'all' | 'learning' | 'finished'>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    portalApi.courses(filter).then((c: any[]) => setCourses(c || []))
      .catch(err => toast.error(err.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-2xl font-bold text-text-primary">我的课程</h1>
          <div className="flex gap-1 bg-bg-light rounded-lg p-1">
            {(['all', 'learning', 'finished'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${filter === f ? 'bg-white text-primary shadow-sm font-medium' : 'text-text-secondary hover:text-text-primary'}`}>
                {f === 'all' ? '全部' : f === 'learning' ? '学习中' : '已完成'}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div>
        ) : courses.length === 0 ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-light flex items-center justify-center">
              <AppIcon className="fas fa-book-open text-2xl text-text-secondary" />
            </div>
            <p className="text-text-secondary">
              {filter === 'finished' ? '还没有已完成的课程' : filter === 'learning' ? '没有进行中的课程' : '暂无课程'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {courses.map(c => (
              <CourseCard key={c.id} course={c} onClick={() => navigate(`/portal/course/${c.id}`)} />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
