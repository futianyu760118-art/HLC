// @ts-nocheck
/* eslint-disable react-hooks/exhaustive-deps -- Legacy page-level one-shot data loads; keep scoped to this file. */
/**
 * 答题页（Chunk 8）：逐题作答 + 倒计时 + 暂存 localStorage + 提交
 */
import React, { useEffect, useRef, useState } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { Layout } from '../../components/Layout';
import { portalApi } from '../../utils/api';
import toast from '../../utils/toast';
import confirm from '../../components/ConfirmDialog';
import AppIcon from '../../components/AppIcon';

const TYPE_LABELS: Record<string, string> = { single: '单选', multiple: '多选', judge: '判断' };

export default function P_portal_exam_take() {
  const { attemptId } = useParams();
  const location = useLocation() as any;
  const navigate = useNavigate();
  const [meta, setMeta] = useState<any>(location.state || null);
  const [loadError, setLoadError] = useState<string>('');
  const [answers, setAnswers] = useState<Record<string, number[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  // 从 localStorage 恢复暂存
  useEffect(() => {
    const saved = localStorage.getItem(`exam-answers-${attemptId}`);
    if (saved) {
      try { setAnswers(JSON.parse(saved)); } catch {}
    }
  }, [attemptId]);

  // 无 location.state（刷新/直链）时，通过 API 恢复进行中的作答信息
  useEffect(() => {
    if (meta) return;
    let cancelled = false;
    portalApi.getAttempt(attemptId).then((res: any) => {
      if (!cancelled) setMeta(res);
    }).catch((e: any) => {
      if (!cancelled) {
        // 已提交（410）→ 跳结果页；其他错误展示
        if (e?.status === 410) {
          navigate(`/portal/exam/result/${attemptId}`, { replace: true });
        } else {
          setLoadError(e?.message || '恢复考试信息失败');
        }
      }
    });
    return () => { cancelled = true; };
  }, [attemptId, meta, navigate]);

  // 暂存
  useEffect(() => {
    localStorage.setItem(`exam-answers-${attemptId}`, JSON.stringify(answers));
  }, [answers, attemptId]);

  // 用 ref 保存 answers 的最新值，解决 effect 闭包陈旧问题
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const doSubmitRef = useRef(null);
  doSubmitRef.current = doSubmit;

  // 倒计时
  useEffect(() => {
    if (!meta?.durationMinutes) return;
    const total = meta.durationMinutes * 60;
    const startedKey = `exam-start-${attemptId}`;
    let startedAt = Number(localStorage.getItem(startedKey) || 0);
    if (!startedAt) { startedAt = Date.now(); localStorage.setItem(startedKey, String(startedAt)); }
    const update = () => {
      const left = total - Math.floor((Date.now() - startedAt) / 1000);
      setSecondsLeft(left);
      if (left <= 0) { doSubmitRef.current?.(true); }
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [meta]);

  // 切屏检测（防作弊基础）：visibilitychange 切走计数，超阈值自动提交
  const [leaveCount, setLeaveCount] = useState(0);
  const MAX_LEAVES = 3;
  useEffect(() => {
    const handler = () => {
      if (document.hidden) {
        setLeaveCount(prev => {
          const next = prev + 1;
          if (next >= MAX_LEAVES) {
            toast.error(`检测到 ${MAX_LEAVES} 次切屏，考试自动提交`);
            doSubmitRef.current?.(true);
          } else {
            toast.warning(`检测到切屏（第 ${next} 次），${MAX_LEAVES} 次将自动交卷`);
          }
          return next;
        });
      }
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

  if (!meta) {
    return (
      <Layout>
        <div className="p-10 text-center">
          {loadError ? (
            <div className="text-red-500">{loadError}</div>
          ) : (
            <>
              <div className="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-3"></div>
              <div className="text-gray-500">正在恢复考试…</div>
            </>
          )}
        </div>
      </Layout>
    );
  }

  const questions = meta.questions || [];

  const toggleAnswer = (qid: string, idx: number, multi: boolean) => {
    setAnswers(prev => {
      const cur = prev[qid] || [];
      if (multi) {
        return { ...prev, [qid]: cur.includes(idx) ? cur.filter(i => i !== idx) : [...cur, idx] };
      }
      return { ...prev, [qid]: [idx] };
    });
  };

  const answeredCount = Object.values(answers).filter(v => v && v.length > 0).length;
  // 未答完的题：题目存在于快照，但没有非空答案
  const unansweredCount = questions.length - answeredCount;

  async function doSubmit(auto = false) {
    // 从 ref 读取最新答案（防闭包陈旧）
    const currentAnswers = answersRef.current;
    if (!auto) {
      if (unansweredCount > 0) {
        // 有未答题：必须明确确认“仍要交卷”，避免误操作
        const ok = await confirm(
          `还有 ${unansweredCount} 道题未作答（共 ${questions.length} 题），未答的题将按 0 分计入。确定要交卷吗？提交后不可修改。`,
          { confirmText: '确认交卷' },
        );
        if (!ok) return;
      } else {
        if (!await confirm(`全部题目已作答（${questions.length} 题），确定提交？提交后不可修改。`)) return;
      }
    } else {
      toast.info('时间到，自动提交');
    }
    setSubmitting(true);
    try {
      const res = await portalApi.submitExam(attemptId, currentAnswers);
      localStorage.removeItem(`exam-answers-${attemptId}`);
      localStorage.removeItem(`exam-start-${attemptId}`);
      navigate(`/portal/exam/result/${attemptId}`, { state: res, replace: true });
    } catch (e: any) {
      toast.error(e.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  }

  const fmtTime = (s: number) => {
    if (s < 0) s = 0;
    const m = Math.floor(s / 60), sec = s % 60;
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  };

  return (
    <Layout>
      <div className="max-w-3xl mx-auto p-6 space-y-4">
        <div className="flex items-center justify-between sticky top-0 bg-white py-2 z-10 border-b">
          <h1 className="text-lg font-bold">{meta.title}</h1>
          <div className="flex items-center gap-3">
            {secondsLeft !== null && (
              <span className={`font-mono font-bold ${secondsLeft < 60 ? 'text-red-500' : 'text-gray-700'}`}>
                <AppIcon className="fas fa-clock" /> {fmtTime(secondsLeft)}
              </span>
            )}
            <span className="text-sm text-gray-500">{answeredCount}/{questions.length}</span>
            {leaveCount > 0 && (
              <span className={`text-xs px-2 py-0.5 rounded ${leaveCount >= 2 ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-700'}`}>
                切屏 {leaveCount}/{MAX_LEAVES}
              </span>
            )}
            <button onClick={() => doSubmit(false)} disabled={submitting}
              className="bg-green-600 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50">
              {submitting ? '提交中…' : '交卷'}
            </button>
          </div>
        </div>

        {questions.map((q, i) => {
          const multi = q.type === 'multiple';
          const selected = answers[q.id] || [];
          return (
            <div key={q.id} className="bg-white rounded-lg shadow p-4">
              <div className="flex items-start gap-2 mb-3">
                <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{TYPE_LABELS[q.type] || q.type}</span>
                <span className="text-xs text-gray-400">{q.score} 分</span>
                <div className="flex-1 font-medium">{i + 1}. {q.stem}</div>
              </div>
              <div className="space-y-2">
                {(q.options || []).map((opt: string, oi: number) => {
                  const checked = selected.includes(oi);
                  return (
                    <label key={oi} className={`flex items-center gap-2 border rounded px-3 py-2 cursor-pointer ${checked ? 'border-blue-400 bg-blue-50' : 'hover:bg-gray-50'}`}>
                      <input type={multi ? 'checkbox' : 'radio'} name={`q-${q.id}`} checked={checked}
                        onChange={() => toggleAnswer(q.id, oi, multi)} />
                      <span className="font-medium text-gray-500">{String.fromCharCode(65 + oi)}.</span>
                      <span>{opt}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}

        <button onClick={() => doSubmit(false)} disabled={submitting}
          className="w-full bg-green-600 text-white py-3 rounded-lg font-medium disabled:opacity-50">
          {submitting ? '提交中…' : '提交试卷'}
        </button>
      </div>
    </Layout>
  );
}
