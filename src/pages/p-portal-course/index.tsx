// @ts-nocheck
/**
 * 课程详情（网课页风格）
 * 左：章节大纲（带序号/完成态/时长）；右：课程信息卡 + 学习进度 + 继续学习
 */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { fileApi, portalApi } from '../../utils/api';
import apiClient from '../../utils/api';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';
import { ProtectedImage } from '../../components/ProtectedFile';
import { MarkdownRenderer } from '../../components/MarkdownEditor';
import { StarRating, StarInput } from '../../components/StarRating';
import { CourseAssistant } from '../../components/CourseAssistant';
import { CourseDiscussion } from '../../components/CourseDiscussion';

const PLACEHOLDER_GRADIENTS = [
  'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
  'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
  'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
];
const gradientFor = (key: string) => PLACEHOLDER_GRADIENTS[(key || '').length % PLACEHOLDER_GRADIENTS.length];
const fmtDur = (sec: number) => sec ? (sec >= 3600 ? `${Math.floor(sec/3600)}小时${Math.round(sec%3600/60)}分` : `${Math.round(sec/60)}分钟`) : '';

export default function P_portal_course() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [reviews, setReviews] = useState<any>({ summary: { count: 0, avgRating: 0 }, reviews: [] });
  const [showReviewForm, setShowReviewForm] = useState(false);

  useEffect(() => {
    portalApi.courseDetail(id)
      .then(setData)
      .catch(err => toast.error(err.message || '加载失败'))
      .finally(() => setLoading(false));
    // 加载课程评价
    apiClient.get<any>(`/portal/courses/${id}/reviews`).then(setReviews).catch(() => {});
  }, [id]);

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (!data) return <Layout><div className="text-center py-20 text-danger">课程不存在或无权限</div></Layout>;

  const { course, chapters, ungroupedHours, attachments, progress, finishedCount, totalHours, isFinished } = data;
  const firstUnfinished = [...(ungroupedHours || []), ...(chapters || []).flatMap((ch: any) => ch.hours || [])].find((h: any) => !h.isFinished);

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6">
        <button onClick={() => navigate('/portal/my-courses')} className="text-sm text-text-secondary hover:text-primary mb-4 flex items-center gap-1">
          <AppIcon className="fas fa-arrow-left text-xs" /> 我的课程
        </button>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 左侧：章节大纲（占 2 列）*/}
          <div className="lg:col-span-2 space-y-5">
            {/* 课程头 */}
            <div className="flex gap-4">
              <div className="w-40 h-24 rounded-lg overflow-hidden shrink-0" style={course.coverUrl ? {} : { background: gradientFor(course.id) }}>
                {course.coverUrl ? <ProtectedImage fileUrl={course.coverUrl} className="w-full h-full object-cover" alt={course.title} /> : <div className="w-full h-full flex items-center justify-center text-white text-sm font-medium px-2 text-center line-clamp-2">{course.title}</div>}
              </div>
              <div className="flex-1 min-w-0">
                <h1 className="text-xl font-bold text-text-primary">{course.title}</h1>
                {course.shortDesc && <p className="text-sm text-text-secondary mt-1 line-clamp-2">{course.shortDesc}</p>}
                <div className="flex items-center gap-3 mt-2 text-xs text-text-secondary">
                  <span className="flex items-center gap-1"><AppIcon className="fas fa-layer-group" /> {totalHours} 课时</span>
                  <span className="flex items-center gap-1"><AppIcon className="fas fa-check-circle text-success" /> 已完成 {finishedCount}</span>
                  {course.isRequired && <span className="text-danger">必修</span>}
                </div>
              </div>
            </div>

            {course.content && (
              <section className="bg-white rounded-xl border border-border-light p-5">
                <h2 className="font-semibold text-text-primary mb-2">课程介绍</h2>
                <p className="text-sm text-text-secondary whitespace-pre-wrap leading-relaxed"><MarkdownRenderer content={course.content} /></p>
              </section>
            )}

            {/* 章节 */}
            <section className="bg-white rounded-xl border border-border-light overflow-hidden">
              <div className="px-5 py-3 border-b border-border-light font-semibold text-text-primary">课程目录</div>
              {chapters.map((ch: any, ci: number) => (
                <div key={ch.id} className="border-b border-border-light last:border-0">
                  <div className="px-5 py-3 bg-bg-light/50 flex items-center gap-2">
                    <span className="text-xs font-medium text-text-secondary">第 {ci + 1} 章</span>
                    <span className="font-medium text-text-primary text-sm">{ch.name}</span>
                  </div>
                  {ch.description && <div className="px-5 py-1.5 text-xs text-text-secondary">{ch.description}</div>}
                  {(ch.hours || []).map((h: any, hi: number) => (
                    <HourRow key={h.id} hour={h} idx={hi + 1} onClick={() => navigate(`/portal/course/${h.id}/learn`)} />
                  ))}
                  {ch.materials && ch.materials.length > 0 && (
                    <div className="px-5 py-2 border-t border-border-light/50 bg-bg-light/20">
                      <div className="text-xs text-text-secondary mb-1.5">本章资料</div>
                      <div className="space-y-1">
                        {ch.materials.map((m: any, mi: number) => (
                          <button key={mi} type="button" onClick={() => fileApi.download(m.url, `${m.title}.${m.ext}`).catch((e: any) => toast.error(e.message || '下载失败'))}
                            className="flex items-center gap-2 py-1 text-sm text-primary hover:underline">
                            <AppIcon className="fas fa-paperclip text-xs" /> {m.title}.{m.ext}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {ungroupedHours.length > 0 && (
                <div className="border-b border-border-light last:border-0">
                  <div className="px-5 py-3 bg-bg-light/50 font-medium text-text-primary text-sm">课时</div>
                  {ungroupedHours.map((h: any, hi: number) => (
                    <HourRow key={h.id} hour={h} idx={hi + 1} onClick={() => navigate(`/portal/course/${h.id}/learn`)} />
                  ))}
                </div>
              )}
              {chapters.length === 0 && ungroupedHours.length === 0 && (
                <div className="px-5 py-10 text-center text-sm text-text-secondary">暂无课时</div>
              )}
            </section>

            {/* 附件 */}
            {attachments.length > 0 && (
              <section className="bg-white rounded-xl border border-border-light p-5">
                <h2 className="font-semibold text-text-primary mb-3">课程附件</h2>
                <div className="space-y-1">
                  {attachments.map((a: any) => (
                    <button key={a.id} type="button" onClick={() => fileApi.download(a.fileUrl, `${a.title}.${a.ext}`).catch((e: any) => toast.error(e.message || '下载失败'))}
                      className="flex items-center gap-2 py-1.5 text-sm text-primary hover:underline">
                      <AppIcon className="fas fa-download text-xs" /> {a.title}.{a.ext}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>

          {/* 右侧：学习进度卡（占 1 列，sticky）*/}
          <div className="lg:col-span-1">
            <div className="lg:sticky lg:top-20 space-y-4">
              <div className="bg-white rounded-xl border border-border-light p-5">
                <div className="text-center mb-4">
                  <div className="text-3xl font-bold text-primary tabular-nums">{progress}%</div>
                  <div className="text-xs text-text-secondary mt-1">学习进度</div>
                </div>
                <div className="h-2 rounded-full bg-bg-light overflow-hidden mb-4">
                  <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${progress}%` }} />
                </div>
                <div className="flex justify-between text-sm mb-4">
                  <span className="text-text-secondary">已完成</span>
                  <span className="font-medium text-text-primary">{finishedCount} / {totalHours} 课时</span>
                </div>
                <button
                  onClick={() => {
                    const target = firstUnfinished || (ungroupedHours || [])[0] || (chapters || []).flatMap((ch: any) => ch.hours || [])[0];
                    navigate(target ? `/portal/course/${target.id}/learn` : '/portal/my-courses');
                  }}
                  className="w-full bg-primary text-white py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors flex items-center justify-center gap-2">
                  <AppIcon className="fas fa-play" /> {isFinished ? '复习课程' : (progress > 0 ? '继续学习' : '开始学习')}
                </button>
              </div>

              {/* 课程评分汇总 */}
              {reviews.summary.count > 0 && (
                <div className="bg-white rounded-xl border border-border-light p-5">
                  <h3 className="font-semibold text-text-primary mb-2">课程评分</h3>
                  <div className="flex items-center gap-3 mb-2">
                    <div className="text-3xl font-bold text-text-primary">{reviews.summary.avgRating}</div>
                    <div>
                      <StarRating rating={reviews.summary.avgRating} />
                      <div className="text-xs text-text-secondary mt-0.5">{reviews.summary.count} 人评价</div>
                    </div>
                  </div>
                  <div className="space-y-1 text-xs text-text-secondary">
                    {reviews.summary.avgContent > 0 && <div className="flex justify-between"><span>内容质量</span><span className="text-warning">{'★'.repeat(Math.round(reviews.summary.avgContent))} {reviews.summary.avgContent}</span></div>}
                    {reviews.summary.avgClarity > 0 && <div className="flex justify-between"><span>讲解清晰</span><span className="text-warning">{'★'.repeat(Math.round(reviews.summary.avgClarity))} {reviews.summary.avgClarity}</span></div>}
                    {reviews.summary.avgPracticality > 0 && <div className="flex justify-between"><span>实用性</span><span className="text-warning">{'★'.repeat(Math.round(reviews.summary.avgPracticality))} {reviews.summary.avgPracticality}</span></div>}
                  </div>
                </div>
              )}

              {/* 评价入口（学完才显示） */}
              {isFinished && (
                <button onClick={() => setShowReviewForm(true)}
                  className="w-full bg-white border border-border-light rounded-xl p-4 text-sm text-primary hover:bg-primary/5 flex items-center justify-center gap-2">
                  <AppIcon className="fas fa-star" /> {reviews.reviews.find((r: any) => r.employeeName) ? '修改我的评价' : '评价本课程'}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* 评价列表（底部） */}
        {reviews.reviews.length > 0 && (
          <section className="mt-6 bg-white rounded-xl border border-border-light p-5">
            <h2 className="font-semibold text-text-primary mb-4">学员评价（{reviews.reviews.length}）</h2>
            <div className="space-y-4">
              {reviews.reviews.slice(0, 10).map((rv: any) => (
                <div key={rv.id} className="border-b border-border-light last:border-0 pb-3 last:pb-0">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium text-primary">{(rv.employeeName || '?').charAt(0)}</div>
                      <span className="text-sm font-medium text-text-primary">{rv.employeeName}</span>
                    </div>
                    <StarRating rating={rv.rating} size="text-xs" />
                  </div>
                  {rv.comment && <p className="text-sm text-text-secondary ml-9">{rv.comment}</p>}
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {showReviewForm && <ReviewModal courseId={id} onDone={() => {
        setShowReviewForm(false);
        apiClient.get<any>(`/portal/courses/${id}/reviews`).then(setReviews).catch(() => {});
      }} />}
      <div className="mt-6"><CourseDiscussion courseId={id} /></div>
      <CourseAssistant courseId={id} />
    </Layout>
  );
}

/** 评价弹窗 */
function ReviewModal({ courseId, onDone }: { courseId: string; onDone: () => void }) {
  const [rating, setRating] = useState(5);
  const [contentQuality, setContentQuality] = useState(5);
  const [clarity, setClarity] = useState(5);
  const [practicality, setPracticality] = useState(5);
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // 回填已有评价
    apiClient.get<any>(`/portal/courses/${courseId}/review`).then((r) => {
      if (r) {
        setRating(r.rating || 5);
        setContentQuality(r.contentQuality || 5);
        setClarity(r.clarity || 5);
        setPracticality(r.practicality || 5);
        setComment(r.comment || '');
      }
    }).catch(() => {});
  }, [courseId]);

  const submit = async () => {
    setSaving(true);
    try {
      await apiClient.post(`/portal/courses/${courseId}/review`, { rating, contentQuality, clarity, practicality, comment: comment.trim() || undefined });
      toast.success('评价已提交');
      onDone();
    } catch (e) { toast.error(e.message || '提交失败'); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onDone}>
      <div className="bg-white rounded-xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">评价课程</h2>
        <div className="space-y-3">
          <StarInput value={rating} onChange={setRating} label="总体" />
          <StarInput value={contentQuality} onChange={setContentQuality} label="内容质量" />
          <StarInput value={clarity} onChange={setClarity} label="讲解清晰" />
          <StarInput value={practicality} onChange={setPracticality} label="实用性" />
          <div>
            <label className="block text-sm text-text-secondary mb-1">一句话评价（可选）</label>
            <textarea value={comment} onChange={e => setComment(e.target.value)} rows={2} placeholder="说说你的感受..."
              className="w-full px-3 py-2 border border-border-light rounded-lg outline-none resize-none text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onDone} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={submit} disabled={saving} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{saving ? '提交中…' : '提交评价'}</button>
        </div>
      </div>
    </div>
  );
}

function HourRow({ hour, idx, onClick }: { hour: any; idx: number; onClick: () => void }) {
  return (
    <div onClick={onClick} className="flex items-center gap-3 px-5 py-2.5 hover:bg-bg-light/50 cursor-pointer transition-colors">
      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 ${hour.isFinished ? 'bg-success/10 text-success' : 'bg-bg-light text-text-secondary'}`}>
        <AppIcon className={hour.isFinished ? 'fas fa-check' : 'fas fa-play'} />
      </div>
      <span className="text-xs text-text-secondary w-6 shrink-0">{String(idx).padStart(2, '0')}</span>
      <span className={`flex-1 text-sm truncate ${hour.isFinished ? 'text-text-secondary' : 'text-text-primary'}`}>{hour.title}</span>
      {hour.duration > 0 && <span className="text-xs text-text-secondary shrink-0">{fmtDur(hour.duration)}</span>}
      <span className={`text-xs shrink-0 ${hour.isFinished ? 'text-success' : 'text-primary'}`}>{hour.isFinished ? '复习' : '观看'}</span>
    </div>
  );
}
