// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 视频学习页：播放器 + 防拖动（网课）+ 周期上报进度 + 章节大纲（同课程页结构）
 */
import React, { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import apiClient, { portalApi } from '../../utils/api';
import { useProtectedFileUrl } from '../../components/ProtectedFile';
import toast from '../../utils/toast';
import AppIcon from '../../components/AppIcon';

function fmtDur(s: number) {
  if (!s) return '';
  const m = Math.floor(s / 60), sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

const nowMs = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

export default function P_portal_learn() {
  const { hourId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const lastReportRef = useRef(0);
  const resumeAppliedRef = useRef(false);

  useEffect(() => {
    setLoading(true);
    apiClient.get(`/portal/hours/${hourId}`)
      .then((r) => setData(r))
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }, [hourId]);

  // 用已记录的观看时长初始化最远可拖动位置（从上次进度继续，但不能跳过未看部分）
  const maxWatchedRef = useRef(0);
  const courseFinishedShownRef = useRef(false);
  useEffect(() => {
    const watched = data?.hour?.watchedDuration || 0;
    maxWatchedRef.current = watched;
    lastPosRef.current = watched;
    lastReportRef.current = watched;
    seekingRef.current = false;
    seekGuardUntilRef.current = 0;
    resumeAppliedRef.current = false;
    courseFinishedShownRef.current = false; // 切换课时重置完成提示
  }, [data?.hour?.id]);

  const { url: playableVideoUrl, error: videoLoadError, loading: videoLoading } = useProtectedFileUrl(data?.hour?.videoUrl);

  const reportFailCount = useRef(0);
  // 周期上报（每 10 秒 + 暂停/结束）
  const report = async (force = false) => {
    const v = videoRef.current;
    if (!v) return;
    // 用 maxWatchedRef（真实连续观看到达的最远点）而非 v.currentTime，
    // 防止用户点击进度条末尾的瞬间位置污染完成判定（拖动会被 seeked 拉回，
    // 但那一瞬间的 currentTime 不应算作已观看）。
    const watched = Math.floor(maxWatchedRef.current || 0);
    if (!force && watched - lastReportRef.current < 10) return;
    lastReportRef.current = watched;
    const total = data?.hour?.duration || Math.floor(v.duration || 0);
    const isFinished = total > 0 && watched >= total * 0.9; // 真实观看达到 90% 视为完成
    try {
      const res = await portalApi.reportProgress(hourId, { watchedDuration: watched, isFinished, totalDuration: total });
      reportFailCount.current = 0;
      setData((prev: any) => {
        if (!prev) return prev;
        const hourFinished = Boolean(prev.hour?.isFinished || res.hourFinished);
        const markHour = (h: any) => h.id === hourId ? { ...h, isFinished: hourFinished } : h;
        const chapters = (prev.course?.chapters || []).map((ch: any) => ({
          ...ch,
          hours: (ch.hours || []).map(markHour),
        }));
        const ungroupedHours = (prev.course?.ungroupedHours || []).map(markHour);
        const allHours = [...chapters.flatMap((ch: any) => ch.hours || []), ...ungroupedHours];
        const finishedCount = allHours.filter((h: any) => h.isFinished).length;
        return {
          ...prev,
          hour: {
            ...prev.hour,
            watchedDuration: Math.max(prev.hour?.watchedDuration || 0, watched),
            isFinished: hourFinished,
          },
          course: {
            ...prev.course,
            progress: res.courseProgress ?? prev.course?.progress,
            finishedCount: Number.isFinite(finishedCount) ? finishedCount : prev.course?.finishedCount,
            chapters,
            ungroupedHours,
          },
        };
      });
      if (res.courseFinished && !courseFinishedShownRef.current) {
        courseFinishedShownRef.current = true;
        toast.success('恭喜，课程已全部完成！');
      } else if (res.hourFinished && isFinished && !courseFinishedShownRef.current) {
        toast.success('本课时已完成');
      }
    } catch {
      reportFailCount.current += 1;
      if (reportFailCount.current === 3) {
        toast.error('学习进度保存失败，请检查网络连接');
      }
    }
  };

  useEffect(() => {
    const timer = setInterval(() => report(false), 10000);
    return () => clearInterval(timer);
  }, [data]);

  // —— 防拖动（网课逻辑）——
  // maxWatchedRef 只由正常播放推进；任何 seeking/seeked 期间都不提升它。
  // 这样快速多次点击进度条也不会把“最远已观看点”一点点抬高。
  const lastPosRef = useRef(0);
  const seekingRef = useRef(false);
  const seekGuardUntilRef = useRef(0);
  const seekTolerance = 0.5;

  const clampForwardSeek = () => {
    const v = videoRef.current;
    if (!v) return false;
    if (v.currentTime > maxWatchedRef.current + seekTolerance) {
      v.currentTime = maxWatchedRef.current;
      lastPosRef.current = maxWatchedRef.current;
      seekGuardUntilRef.current = nowMs() + 500;
      return true;
    }
    return false;
  };

  const handleTimeUpdate = () => {
    const v = videoRef.current;
    if (!v) return;
    const cur = v.currentTime;
    if (v.seeking || seekingRef.current || nowMs() < seekGuardUntilRef.current) {
      lastPosRef.current = Math.min(cur, maxWatchedRef.current);
      return;
    }
    // 正常播放：相邻 timeupdate 间隔通常 ≤1s，允许 ≤2s 的推进（含轻微卡顿）
    if (cur > lastPosRef.current && cur - lastPosRef.current <= 2) {
      if (cur > maxWatchedRef.current) {
        maxWatchedRef.current = cur;
      }
    }
    lastPosRef.current = cur;
  };

  const handleSeeking = () => {
    seekingRef.current = true;
    clampForwardSeek();
  };

  const handleSeeked = () => {
    const clamped = clampForwardSeek();
    seekingRef.current = false;
    seekGuardUntilRef.current = nowMs() + 300;
    if (!clamped && videoRef.current) {
      lastPosRef.current = videoRef.current.currentTime;
    }
  };

  const handleLoadedMetadata = () => {
    const v = videoRef.current;
    if (!v || resumeAppliedRef.current) return;
    resumeAppliedRef.current = true;
    const watched = data?.hour?.watchedDuration || 0;
    if (watched <= 1) return;
    const duration = Number.isFinite(v.duration) && v.duration > 0 ? v.duration : data?.hour?.duration || 0;
    const resumeAt = duration > 0 ? Math.min(watched, Math.max(0, duration - 1)) : watched;
    if (resumeAt > 0) {
      v.currentTime = resumeAt;
      lastPosRef.current = resumeAt;
      maxWatchedRef.current = Math.max(maxWatchedRef.current, resumeAt);
    }
  };

  const reload = () => {
    setLoading(true);
    setLoadError(false);
    apiClient.get(`/portal/hours/${hourId}`)
      .then((r) => setData(r))
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  };

  if (loading) return <Layout><div className="flex justify-center py-20"><AppIcon className="fas fa-spinner fa-spin text-2xl text-primary" /></div></Layout>;
  if (loadError) return <Layout><div className="p-10 text-center"><p className="text-danger mb-3">加载课时失败</p><div className="flex items-center justify-center gap-3"><button onClick={reload} className="text-sm text-primary hover:underline">重试</button><span className="text-gray-300">·</span><button onClick={() => navigate('/portal/my-courses')} className="text-sm text-primary hover:underline">返回课程列表 →</button></div></div></Layout>;
  if (!data) return <Layout><div className="p-10 text-center text-danger">课时不存在</div></Layout>;

  const { hour, course } = data;
  // 切换到指定课时
  const goHour = async (hid: string) => {
    if (hid === hour.id) return;
    await report(true);
    navigate(`/portal/course/${hid}/learn`, { replace: true });
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-6 space-y-4">
        <button onClick={() => navigate(`/portal/course/${course.id}`)} className="text-gray-500 hover:text-gray-700 text-sm">
          ← 返回课程
        </button>
        <h1 className="text-xl font-bold">{hour.title}</h1>
        <div className="bg-black rounded-lg overflow-hidden">
          {hour.videoUrl ? (
            videoLoading ? (
              <div className="text-center text-gray-300 py-20">
                <AppIcon className="fas fa-spinner fa-spin text-2xl mb-3" />
                <div className="text-sm">正在准备视频…</div>
              </div>
            ) : playableVideoUrl ? (
              <video ref={videoRef} src={playableVideoUrl} controls className="w-full" style={{ maxHeight: '70vh' }}
                onEnded={() => report(true)} onPause={() => report(true)}
                onLoadedMetadata={handleLoadedMetadata}
                onTimeUpdate={handleTimeUpdate} onSeeking={handleSeeking} onSeeked={handleSeeked} />
            ) : (
              <div className="text-center text-red-300 py-20 text-sm">
                {videoLoadError ? '视频加载失败，请稍后重试' : '视频暂时不可播放'}
              </div>
            )
          ) : (
            <div className="text-center text-gray-400 py-20">该课时尚未上传视频</div>
          )}
        </div>
        <div className="text-sm text-gray-500">
          <AppIcon className="fas fa-info-circle" /> 观看进度会自动保存。课程视频需按顺序观看，无法拖动跳过未观看部分。
        </div>

        {/* 课程整体进度 */}
        {course && course.totalHours > 0 && (
          <div className="bg-white border border-gray-100 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-text-primary">{course.title}</span>
                <span className="text-xs text-text-secondary">已完成 {course.finishedCount} / {course.totalHours} 课时</span>
              </div>
              <span className="text-sm font-bold text-primary tabular-nums">{course.progress}%</span>
            </div>
            <div className="h-1.5 bg-bg-light rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${course.progress}%` }} />
            </div>
          </div>
        )}

        {/* 章节大纲（同课程页结构） */}
        {course && (
          <div className="bg-white border border-gray-100 rounded-lg p-4 space-y-4">
            <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <AppIcon className="fas fa-list-ul text-primary" /> 课程目录
            </h3>
            {/* 按章节分组 */}
            {(course.chapters || []).map((ch: any) => (
              <div key={ch.id} className="space-y-1">
                <div className="text-xs font-medium text-text-secondary px-1 py-1">{ch.name}</div>
                {(ch.hours || []).map((h: any) => (
                  <button key={h.id} onClick={() => goHour(h.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                      h.id === hour.id ? 'bg-primary/10' : 'hover:bg-bg-light'
                    }`}>
                    <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 ${h.isFinished ? 'bg-success/10 text-success' : h.id === hour.id ? 'bg-primary text-white' : 'bg-bg-light text-text-secondary'}`}>
                      <AppIcon className={h.isFinished ? 'fas fa-check' : 'fas fa-play'} />
                    </span>
                    <span className={`flex-1 text-sm truncate ${h.id === hour.id ? 'text-primary font-medium' : h.isFinished ? 'text-text-secondary' : 'text-text-primary'}`}>{h.title}</span>
                    {h.duration > 0 && <span className="text-xs text-text-secondary shrink-0">{fmtDur(h.duration)}</span>}
                    <span className={`text-xs shrink-0 ${h.isFinished ? 'text-success' : h.id === hour.id ? 'text-primary' : 'text-text-secondary'}`}>{h.isFinished ? '已完成' : h.id === hour.id ? '学习中' : '观看'}</span>
                  </button>
                ))}
              </div>
            ))}
            {/* 未分章节的课时 */}
            {(course.ungroupedHours || []).length > 0 && (
              <div className="space-y-1">
                {(course.ungroupedHours || []).map((h: any) => (
                  <button key={h.id} onClick={() => goHour(h.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                      h.id === hour.id ? 'bg-primary/10' : 'hover:bg-bg-light'
                    }`}>
                    <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 ${h.isFinished ? 'bg-success/10 text-success' : h.id === hour.id ? 'bg-primary text-white' : 'bg-bg-light text-text-secondary'}`}>
                      <AppIcon className={h.isFinished ? 'fas fa-check' : 'fas fa-play'} />
                    </span>
                    <span className={`flex-1 text-sm truncate ${h.id === hour.id ? 'text-primary font-medium' : h.isFinished ? 'text-text-secondary' : 'text-text-primary'}`}>{h.title}</span>
                    {h.duration > 0 && <span className="text-xs text-text-secondary shrink-0">{fmtDur(h.duration)}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}
