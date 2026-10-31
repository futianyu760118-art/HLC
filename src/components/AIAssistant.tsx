import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { hrmApi } from '../utils/api';
import { authUtils } from '../utils/auth';
import AssistantMessageList from './assistant/AssistantMessageList';
import { buildAssistantClientContext } from './assistant/copilotContext';
import type {
  AssistantEntity,
  AssistantMessage,
  AssistantQueryResult,
  AssistantRequest,
  AssistantSessionMessageRow,
} from './assistant/types';

type SkillParams = Record<string, string>;

interface SpeechRecognitionResultLike {
  isFinal?: boolean;
  0?: { transcript?: string };
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionErrorEventLike {
  error?: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

interface WindowWithSpeechRecognition extends Window {
  SpeechRecognition?: SpeechRecognitionCtor;
  webkitSpeechRecognition?: SpeechRecognitionCtor;
}

interface SkillField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'month' | 'date';
  required?: boolean;
  default?: string | number | boolean | null;
  placeholder?: string;
  min?: number;
  max?: number;
  options?: Array<{ value: string; label: string }>;
}

interface SkillCard {
  id: string;
  name: string;
  icon: string;
  description: string;
  category: string;
  color: string;
  task_template_id: string;
  fields: SkillField[];
}

interface AssistantSessionSummary {
  id: string;
  title: string | null;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

const COLOR_MAP: Record<string, { bg: string; text: string; border: string; hoverBg: string }> = {
  blue: { bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-200', hoverBg: 'hover:bg-blue-100' },
  indigo: { bg: 'bg-indigo-50', text: 'text-indigo-600', border: 'border-indigo-200', hoverBg: 'hover:bg-indigo-100' },
  green: { bg: 'bg-green-50', text: 'text-green-600', border: 'border-green-200', hoverBg: 'hover:bg-green-100' },
  purple: { bg: 'bg-purple-50', text: 'text-purple-600', border: 'border-purple-200', hoverBg: 'hover:bg-purple-100' },
  cyan: { bg: 'bg-cyan-50', text: 'text-cyan-600', border: 'border-cyan-200', hoverBg: 'hover:bg-cyan-100' },
  teal: { bg: 'bg-teal-50', text: 'text-teal-600', border: 'border-teal-200', hoverBg: 'hover:bg-teal-100' },
  amber: { bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200', hoverBg: 'hover:bg-amber-100' },
  orange: { bg: 'bg-orange-50', text: 'text-orange-600', border: 'border-orange-200', hoverBg: 'hover:bg-orange-100' },
  red: { bg: 'bg-red-50', text: 'text-red-600', border: 'border-red-200', hoverBg: 'hover:bg-red-100' },
  lime: { bg: 'bg-lime-50', text: 'text-lime-600', border: 'border-lime-200', hoverBg: 'hover:bg-lime-100' },
  sky: { bg: 'bg-sky-50', text: 'text-sky-600', border: 'border-sky-200', hoverBg: 'hover:bg-sky-100' },
  pink: { bg: 'bg-pink-50', text: 'text-pink-600', border: 'border-pink-200', hoverBg: 'hover:bg-pink-100' },
  violet: { bg: 'bg-violet-50', text: 'text-violet-600', border: 'border-violet-200', hoverBg: 'hover:bg-violet-100' },
  gray: { bg: 'bg-gray-50', text: 'text-gray-600', border: 'border-gray-200', hoverBg: 'hover:bg-gray-100' },
};

const ASSISTANT_NAME = '聘小犀';
const HISTORY_KEY_PREFIX = 'ai_assistant_history:';
const OPEN_KEY = 'ai_assistant_open';
const PANEL_KEY = 'ai_assistant_panel';
const TOGGLE_POS_KEY = 'ai_assistant_toggle_pos';
const SESSION_KEY_PREFIX = 'ai_assistant_session:';
const MAX_HISTORY = 60;
const ASSISTANT_AVATAR = '/ai-assistant.png';
const INPUT_MAX_HEIGHT = 144;
const INPUT_MIN_HEIGHT = 40;

const presetQuestions = [
  '你能做什么？',
  '分析最近收到的简历',
  '找出最近 5 个 Java 候选人，并帮我设计面试题',
  '帮我润色：请你明天下午三点来公司面试',
  '查看本月考勤异常情况',
];

const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const getAssistantContent = (result?: AssistantQueryResult | null) =>
  result?.answer?.content || result?.summary || '（无返回内容）';

const getAssistantUserKey = () => {
  try {
    const user = authUtils.getUser();
    if (user?.id) return `user:${user.id}`;
    const token = localStorage.getItem('token') || '';
    if (token) return `token:${token.slice(-16)}`;
  } catch {}
  return 'anon';
};

const getHistoryStorageKey = (scopeKey = getAssistantUserKey()) => `${HISTORY_KEY_PREFIX}${scopeKey}`;

const getSessionStorageKey = (scopeKey = getAssistantUserKey()) => {
  try {
    return SESSION_KEY_PREFIX + scopeKey;
  } catch {
    return SESSION_KEY_PREFIX + 'anon';
  }
};

const formatTime = (ts: number) => {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
};

const getErrorMessage = (error: unknown, fallback = '请求失败，请稍后重试') => {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  return fallback;
};

const getErrorName = (error: unknown) => {
  if (error instanceof Error && error.name) return error.name;
  if (typeof error === 'object' && error !== null && 'name' in error) {
    const name = (error as { name?: unknown }).name;
    if (typeof name === 'string') return name;
  }
  return '';
};

const isAbortError = (error: unknown) => getErrorName(error) === 'AbortError'
  || getErrorMessage(error, '').includes('aborted');

const getSpeechRecognitionCtor = () => {
  if (typeof window === 'undefined') return null;
  const win = window as WindowWithSpeechRecognition;
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
};

const pickAudioMimeType = () => {
  if (typeof MediaRecorder === 'undefined') return '';
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return options.find((type) => MediaRecorder.isTypeSupported(type)) || '';
};

const audioExtensionFromMime = (mimeType: string) => {
  if (mimeType.includes('mp4')) return 'mp4';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
};

const isLocalhostHost = () => {
  if (typeof window === 'undefined') return false;
  return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
};

const voiceUnavailableText = () => {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    if (isLocalhostHost()) {
      return '当前页面不是安全上下文，请改用 https://localhost:18445 打开后再使用语音输入。';
    }
    return '浏览器要求 HTTPS 才能开启麦克风，请使用 https://localhost:18445 或受信任域名访问。';
  }
  return '当前浏览器不支持语音输入。';
};

const isAssistantSessionMessage = (
  row: AssistantSessionMessageRow | null | undefined,
): row is AssistantSessionMessageRow & { role: 'user' | 'assistant' } => (
  Boolean(row && (row.role === 'user' || row.role === 'assistant'))
);

const parseMessageTimestamp = (value: string | number | undefined) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return Date.parse(value) || Date.now();
  return Date.now();
};

const sessionMessagesToLocal = (rows: AssistantSessionMessageRow[]): AssistantMessage[] =>
  (rows || [])
    .filter(isAssistantSessionMessage)
    .map((m) => ({
      id: genId(),
      role: m.role,
      content: m.content || '',
      entities: m.entities || [],
      widgets: m.widgets || [],
      renderBlocks: m.renderBlocks || [],
      copilot: m.copilot || undefined,
      clientContext: m.clientContext || undefined,
      meta: m.meta,
      timestamp: parseMessageTimestamp(m.ts),
    }));

const buildPromptSuggestion = (raw: string, skills: SkillCard[]) => {
  const text = raw.trim();
  const skillHint = skills.slice(0, 6).map((s) => s.name).join('、');
  if (!text) {
    return `帮我查询或处理一个 HR 场景：请先根据我的需求判断要查员工、候选人、简历、岗位、考勤、绩效、审批还是薪酬，并给出清晰结果。可用能力：${skillHint || '招聘、员工、考勤、绩效、审批、薪酬权限控制'}`;
  }
  if (/最近|近\d+天|本周|本月/.test(text) && /(应聘|投递|简历|候选人|哪些人|名单)/.test(text)) {
    return text
      .replace('都有哪些人', '候选人名单')
      .replace('有哪些人', '候选人名单')
      .replace('几位候选人', '候选人名单');
  }
  if (/面试题|出题|面试重点/.test(text)) {
    return `${text}。请分别结合每位候选人的个人经历、项目经验、技能、优势、不足和面试侧重点，生成差异化面试题，不要输出重复模板。`;
  }
  if (/对比|谁更适合|哪个更适合|推荐谁|排序|排名/.test(text)) {
    return `${text}。请按岗位匹配度、核心优势、风险点、证据来源和优先级给出结论。`;
  }
  if (/邮件|邀约|通知|文案|JD|招聘文案/.test(text)) {
    return `${text}。请生成一版 HR 可直接审核的文案，明确受众、语气、关键信息和待补充字段，不要自动发送。`;
  }
  if (/分析|总结|报告|建议|方案/.test(text)) {
    return `${text}。请输出结论、关键证据、风险点和建议动作。`;
  }
  return text;
};

export const AIAssistant: React.FC = () => {
  const navigate = useNavigate();
  const [open, setOpen] = useState(() => sessionStorage.getItem(OPEN_KEY) === '1');
  const [togglePos, setTogglePos] = useState<{ x: number; y: number } | null>(() => {
    try {
      const raw = localStorage.getItem(TOGGLE_POS_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as { x?: unknown; y?: unknown };
      if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
        return { x: parsed.x, y: parsed.y };
      }
    } catch {
      /* ignore */
    }
    return null;
  });
  const togglePosRef = useRef(togglePos);
  const dragStateRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);
  const dragMovedRef = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [activePanel, setActivePanel] = useState<'chat' | 'skills' | 'history'>(() => {
    const saved = sessionStorage.getItem(PANEL_KEY);
    return saved === 'skills' || saved === 'history' ? saved : 'chat';
  });
  const [messages, setMessages] = useState<AssistantMessage[]>(() => {
    try {
      const saved = sessionStorage.getItem(getHistoryStorageKey());
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [sessionId, setSessionId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(getSessionStorageKey());
    } catch {
      return null;
    }
  });
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [optimizingPrompt, setOptimizingPrompt] = useState(false);
  const [promptOptimizationInfo, setPromptOptimizationInfo] = useState<string | null>(null);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [recordingSupported, setRecordingSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribingVoice, setTranscribingVoice] = useState(false);
  const [voiceInfo, setVoiceInfo] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [skills, setSkills] = useState<SkillCard[]>([]);
  const [skillsLoaded, setSkillsLoaded] = useState(false);
  const [activeSkill, setActiveSkill] = useState<SkillCard | null>(null);
  const [formValues, setFormValues] = useState<SkillParams>({});
  const [sessions, setSessions] = useState<AssistantSessionSummary[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState(() => authUtils.getUser());
  const [assistantScopeKey, setAssistantScopeKey] = useState(() => getAssistantUserKey());
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const hydratingSessionRef = useRef<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const voiceBaseInputRef = useRef('');
  const voiceFinalRef = useRef('');
  const voiceCancelledRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const isPrivilegedUser = useMemo(
    () => currentUser && (currentUser.role === 'admin' || currentUser.role === 'hr_admin'),
    [currentUser],
  );

  const groupedSkills = useMemo(() => {
    return skills.reduce<Record<string, SkillCard[]>>((acc, s) => {
      (acc[s.category] = acc[s.category] || []).push(s);
      return acc;
    }, {});
  }, [skills]);

  useEffect(() => {
    sessionStorage.setItem(OPEN_KEY, open ? '1' : '0');
  }, [open]);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.body.classList.toggle('hpt-assistant-open', open);
    document.body.classList.toggle('hpt-assistant-expanded', open && expanded);
    window.dispatchEvent(new CustomEvent('hpt-assistant-layout', { detail: { open, expanded } }));
    return () => {
      document.body.classList.remove('hpt-assistant-open');
      document.body.classList.remove('hpt-assistant-expanded');
    };
  }, [open, expanded]);

  useEffect(() => {
    sessionStorage.setItem(PANEL_KEY, activePanel);
  }, [activePanel]);

  useEffect(() => {
    try {
      sessionStorage.setItem(getHistoryStorageKey(assistantScopeKey), JSON.stringify(messages.slice(-MAX_HISTORY)));
    } catch {}
  }, [assistantScopeKey, messages]);

  useEffect(() => {
    try {
      const key = getSessionStorageKey(assistantScopeKey);
      if (sessionId) localStorage.setItem(key, sessionId);
      else localStorage.removeItem(key);
    } catch {}
  }, [assistantScopeKey, sessionId]);

  useEffect(() => {
    const refreshUser = () => {
      const nextUser = authUtils.getUser();
      const nextScope = getAssistantUserKey();
      setCurrentUser(nextUser);
      if (assistantScopeKey !== nextScope) {
        try {
          const saved = sessionStorage.getItem(getHistoryStorageKey(nextScope));
          setMessages(saved ? JSON.parse(saved) : []);
          setSessionId(localStorage.getItem(getSessionStorageKey(nextScope)));
        } catch {
          setMessages([]);
          setSessionId(null);
        }
        setSessions([]);
        setHistoryLoaded(false);
        setEditingMessageId(null);
        setActiveSkill(null);
        setAssistantScopeKey(nextScope);
      }
    };
    window.addEventListener('storage', refreshUser);
    window.addEventListener('focus', refreshUser);
    window.addEventListener('hpt-auth-changed', refreshUser);
    return () => {
      window.removeEventListener('storage', refreshUser);
      window.removeEventListener('focus', refreshUser);
      window.removeEventListener('hpt-auth-changed', refreshUser);
    };
  }, [assistantScopeKey]);

  const resizeInputTextarea = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const nextHeight = Math.max(INPUT_MIN_HEIGHT, Math.min(el.scrollHeight, INPUT_MAX_HEIGHT));
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > INPUT_MAX_HEIGHT ? 'auto' : 'hidden';
  }, []);

  useEffect(() => {
    const secure = typeof window === 'undefined' ? false : window.isSecureContext;
    setSpeechSupported(Boolean(getSpeechRecognitionCtor()));
    setRecordingSupported(
      secure
      && typeof navigator !== 'undefined'
      && Boolean(navigator.mediaDevices?.getUserMedia)
      && typeof MediaRecorder !== 'undefined',
    );
    if (!secure) {
      setVoiceInfo(null);
    }
    return () => {
      recognitionRef.current?.stop?.();
      mediaRecorderRef.current?.stop?.();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setTimeout(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
      inputRef.current?.focus();
      resizeInputTextarea();
    }, 80);
  }, [open, activePanel, resizeInputTextarea]);

  useEffect(() => {
    resizeInputTextarea();
  }, [input, open, activePanel, resizeInputTextarea]);

  useEffect(() => {
    if (open && activePanel === 'chat') {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [messages.length, open, activePanel]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]);

  const updateAssistantMessage = useCallback((id: string, patch: Partial<AssistantMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  const loadSkills = useCallback(async (force = false) => {
    if (skillsLoaded && !force) return;
    try {
      const data = await hrmApi.assistantSkills();
      setSkills(data || []);
      setSkillsLoaded(true);
    } catch {
      setSkillsLoaded(true);
    }
  }, [skillsLoaded]);

  const loadSessions = useCallback(async (force = false) => {
    if (historyLoaded && !force) return;
    setHistoryLoading(true);
    try {
      const data = await hrmApi.assistantListSessions();
      setSessions(data || []);
      setHistoryLoaded(true);
    } finally {
      setHistoryLoading(false);
    }
  }, [historyLoaded]);

  useEffect(() => {
    if (!open || activePanel !== 'chat' || !sessionId || messages.length > 0 || busy) return;
    if (hydratingSessionRef.current === sessionId) return;
    let cancelled = false;
    hydratingSessionRef.current = sessionId;
    hrmApi.assistantGetSession(sessionId)
      .then((detail) => {
        if (cancelled || sessionId !== hydratingSessionRef.current) return;
        const restored = sessionMessagesToLocal(detail.messages || []);
        if (restored.length) setMessages(restored);
      })
      .catch(() => {
        if (!cancelled) hydratingSessionRef.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [activePanel, busy, messages.length, open, sessionId]);

  const runAssistantRequest = useCallback(async (
    request: AssistantRequest,
    options: { appendUser?: boolean; replaceAssistantId?: string } = {},
  ) => {
    if (busy) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    const assistantId = options.replaceAssistantId || genId();

    if (options.replaceAssistantId) {
      updateAssistantMessage(assistantId, {
        content: request.loadingText,
        loading: true,
        error: false,
        cancelled: false,
        entities: [],
        widgets: [],
        renderBlocks: [],
        copilot: undefined,
        clientContext: undefined,
        retry: request,
      });
    } else {
      const nextMessages: AssistantMessage[] = [];
      if (options.appendUser !== false) {
        nextMessages.push({
          id: genId(),
          role: 'user',
          content: request.displayText,
          timestamp: Date.now(),
        });
      }
      nextMessages.push({
        id: assistantId,
        role: 'assistant',
        content: request.loadingText,
        loading: true,
        timestamp: Date.now(),
        retry: request,
      });
      setMessages((prev) => [...prev, ...nextMessages]);
    }

    try {
      let result: AssistantQueryResult;
      const clientContext = buildAssistantClientContext(currentUser);
      if (request.kind === 'skill') {
        result = await hrmApi.assistantSkillInvoke(
          request.skillId!,
          request.params || {},
          sessionId || undefined,
          { signal: controller.signal, clientContext },
        );
      } else {
        let streamed = '';
        result = await hrmApi.assistantQueryStream(request.question!, sessionId || undefined, {
          signal: controller.signal,
          clientContext,
          onStatus: (message) => {
            if (message) updateAssistantMessage(assistantId, { content: message, loading: true });
          },
          onDelta: (content) => {
            streamed += content || '';
            if (streamed) updateAssistantMessage(assistantId, { content: streamed, loading: true });
          },
        });
        if (!result?.summary && !result?.answer) {
          result = await hrmApi.assistantQuery(request.question!, sessionId || undefined, {
            signal: controller.signal,
            clientContext,
          });
        }
      }

      if (result?.sessionId && result.sessionId !== sessionId) {
        setSessionId(result.sessionId);
      }
      updateAssistantMessage(assistantId, {
        content: getAssistantContent(result),
        entities: result?.entities || [],
        widgets: result?.widgets || [],
        renderBlocks: result?.renderBlocks || [],
        copilot: result?.copilot || undefined,
        clientContext: result?.clientContext || undefined,
        meta: result?.meta || undefined,
        loading: false,
        error: false,
        cancelled: false,
        timestamp: Date.now(),
        retry: request,
      });
      setHistoryLoaded(false);
    } catch (error: unknown) {
      const aborted = isAbortError(error);
      updateAssistantMessage(assistantId, {
        content: aborted ? '已中断本次请求。' : getErrorMessage(error),
        loading: false,
        error: !aborted,
        cancelled: aborted,
        timestamp: Date.now(),
        retry: request,
      });
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      setBusy(false);
    }
  }, [busy, currentUser, sessionId, updateAssistantMessage]);

  const submitQuestion = useCallback((question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    if (listening) {
      voiceCancelledRef.current = true;
      recognitionRef.current?.stop?.();
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== 'inactive') recorder.stop();
    }
    const request: AssistantRequest = {
      kind: 'query',
      question: q,
      displayText: q,
      loadingText: `${ASSISTANT_NAME} 正在理解问题...`,
    };
    setInput('');
    setPromptOptimizationInfo(null);
    setVoiceInfo(null);
    if (editingMessageId) {
      const editId = editingMessageId;
      setEditingMessageId(null);
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === editId);
        return idx >= 0 ? prev.slice(0, idx) : prev;
      });
      setTimeout(() => runAssistantRequest(request), 0);
      return;
    }
    runAssistantRequest(request);
  }, [busy, editingMessageId, listening, runAssistantRequest]);

  const cancelRequest = useCallback(() => {
    requestRef.current?.abort();
  }, []);

  const stopServerRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    } else {
      setListening(false);
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
      if (voiceCancelledRef.current) {
        voiceCancelledRef.current = false;
      }
    }
  }, []);

  const startServerVoiceInput = useCallback(async () => {
    if (!recordingSupported || busy || listening || transcribingVoice) return;
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setVoiceInfo(voiceUnavailableText());
      return;
    }
    try {
      setVoiceInfo('正在听写...');
      voiceCancelledRef.current = false;
      audioChunksRef.current = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const mimeType = pickAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setListening(false);
        setTranscribingVoice(false);
        setVoiceInfo('语音录制失败，请重试。');
      };
      recorder.onstop = async () => {
        setListening(false);
        setTranscribingVoice(true);
        stream.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
        if (voiceCancelledRef.current) {
          voiceCancelledRef.current = false;
          setTranscribingVoice(false);
          audioChunksRef.current = [];
          return;
        }
        try {
          const effectiveType = mimeType || audioChunksRef.current[0]?.type || 'audio/webm';
          const blob = new Blob(audioChunksRef.current, { type: effectiveType });
          if (!blob.size) {
            setVoiceInfo('没有识别到语音。');
            return;
          }
          const ext = audioExtensionFromMime(effectiveType);
          const file = new File([blob], `assistant-voice-${Date.now()}.${ext}`, { type: effectiveType });
          const result = await hrmApi.assistantTranscribeAudio(file);
          const text = (result?.text || '').trim();
          if (text) {
            setInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
            setVoiceInfo('已转成文字，可继续编辑。');
          } else {
            setVoiceInfo('没有识别到文字。');
          }
        } catch (error: unknown) {
          setVoiceInfo(getErrorMessage(error, '语音识别失败，请重试。'));
        } finally {
          setTranscribingVoice(false);
          audioChunksRef.current = [];
          setTimeout(() => inputRef.current?.focus(), 30);
        }
      };
      recorder.start();
      setListening(true);
    } catch (error: unknown) {
      setListening(false);
      setTranscribingVoice(false);
      setVoiceInfo(getErrorName(error) === 'NotAllowedError' ? '麦克风权限被拒绝，请在地址栏允许麦克风权限。' : '无法启动麦克风。');
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  }, [busy, listening, recordingSupported, transcribingVoice]);

  const toggleVoiceInput = useCallback(() => {
    if (busy || transcribingVoice) return;
    if (listening) {
      voiceCancelledRef.current = false;
      recognitionRef.current?.stop?.();
      stopServerRecording();
      return;
    }

    setVoiceInfo(null);
    if (recordingSupported) {
      startServerVoiceInput();
      return;
    }

    const Recognition = getSpeechRecognitionCtor();
    if (!Recognition) {
      setVoiceInfo(voiceUnavailableText());
      return;
    }

    try {
      const recognition = new Recognition();
      recognitionRef.current = recognition;
      voiceBaseInputRef.current = input.trim();
      voiceFinalRef.current = '';
      voiceCancelledRef.current = false;
      recognition.lang = 'zh-CN';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        setListening(true);
        setVoiceInfo('正在听写...');
      };
      recognition.onresult = (event: SpeechRecognitionEventLike) => {
        let interim = '';
        let finalText = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const transcript = event.results[i]?.[0]?.transcript || '';
          if (event.results[i]?.isFinal) finalText += transcript;
          else interim += transcript;
        }
        if (finalText) {
          voiceFinalRef.current = `${voiceFinalRef.current}${finalText}`;
        }
        const pieces = [voiceBaseInputRef.current, voiceFinalRef.current, interim]
          .map((value) => value.trim())
          .filter(Boolean);
        setInput(pieces.join(' '));
      };
      recognition.onerror = (event: SpeechRecognitionErrorEventLike) => {
        setVoiceInfo(event?.error === 'not-allowed' ? '麦克风权限被拒绝。' : '语音识别中断，可再试一次。');
      };
      recognition.onend = () => {
        setListening(false);
        if (voiceCancelledRef.current) {
          voiceCancelledRef.current = false;
          return;
        }
        const currentValue = inputRef.current?.value?.trim() || '';
        if (voiceFinalRef.current.trim() || (currentValue && currentValue !== voiceBaseInputRef.current)) {
          setVoiceInfo('已转成文字，可继续编辑。');
        }
        setTimeout(() => inputRef.current?.focus(), 30);
      };
      recognition.start();
    } catch {
      setVoiceInfo('无法启动语音输入。');
    }
  }, [busy, input, listening, recordingSupported, startServerVoiceInput, stopServerRecording, transcribingVoice]);

  const handleRetry = (msg: AssistantMessage) => {
    if (!msg.retry || busy) return;
    runAssistantRequest(msg.retry, { appendUser: false, replaceAssistantId: msg.id });
  };

  const handleRegenerate = (assistantMessageId: string) => {
    if (busy) return;
    const idx = messages.findIndex((m) => m.id === assistantMessageId);
    if (idx <= 0) return;
    let userIdx = -1;
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        userIdx = i;
        break;
      }
    }
    if (userIdx < 0) return;
    const q = messages[userIdx].content;
    const request: AssistantRequest = {
      kind: 'query',
      question: q,
      displayText: q,
      loadingText: `${ASSISTANT_NAME} 正在重新生成...`,
    };
    setMessages((prev) => prev.slice(0, userIdx + 1));
    setTimeout(() => runAssistantRequest(request, { appendUser: false }), 0);
  };

  const handleEditUserMessage = (msg: AssistantMessage) => {
    if (busy) return;
    setInput(msg.content);
    setEditingMessageId(msg.id);
    setTimeout(() => inputRef.current?.focus(), 30);
  };

  const handleNewChat = async () => {
    if (busy) cancelRequest();
    if (messages.length > 0) {
      try {
        const sess = await hrmApi.assistantNewSession();
        setSessionId(sess.id);
      } catch {
        setSessionId(null);
      }
    } else {
      setSessionId(null);
    }
    setMessages([]);
    setInput('');
    setPromptOptimizationInfo(null);
    setEditingMessageId(null);
    setActivePanel('chat');
    setHistoryLoaded(false);
  };

  const openSkillsPanel = () => {
    setActivePanel((prev) => (prev === 'skills' ? 'chat' : 'skills'));
    setActiveSkill(null);
    loadSkills();
  };

  const openHistoryPanel = () => {
    setActivePanel((prev) => (prev === 'history' ? 'chat' : 'history'));
    loadSessions();
  };

  const handleEntityClick = (entity: AssistantEntity) => {
    const targetUrl = entity?.url || entity?.href;
    if (!targetUrl) return;
    const canonicalMap: Record<string, string> = {
      '/hrm/attendance-stats': '/attendance-stats',
      '/hrm/employee-requests': '/employee-requests',
      '/hrm/performance-reviews': '/performance-review',
      '/hrm/salary-profiles': '/salary-profiles',
      '/hrm/notifications': '/notifications',
      '/hrm/operation-logs': '/operation-logs',
      '/hrm/my-applications': '/approval-center/my-applications',
      '/hrm/pending-approvals': '/approval-center/pending',
      '/hrm/approval-records': '/approval-center/records',
    };
    const [path, query = ''] = targetUrl.split('?');
    navigate(`${canonicalMap[path] || path}${query ? `?${query}` : ''}`);
  };

  const handleSkillClick = (skill: SkillCard) => {
    if (!skill.fields?.length) {
      invokeSkill(skill, {});
      return;
    }
    const defaults: SkillParams = {};
    skill.fields.forEach((f) => {
      defaults[f.key] = f.default !== undefined && f.default !== null ? String(f.default) : '';
    });
    setFormValues(defaults);
    setActiveSkill(skill);
  };

  const skillDisplayText = (skill: SkillCard, params: SkillParams) => {
    const paramDesc = Object.entries(params)
      .filter(([, v]) => v !== '' && v !== undefined && v !== null)
      .map(([k, v]) => {
        const field = skill.fields.find((f) => f.key === k);
        const label = field?.label || k;
        if (field?.options) {
          const opt = field.options.find((o) => o.value === String(v));
          return `${label}: ${opt?.label || v}`;
        }
        return `${label}: ${v}`;
      })
      .join('，');
    return paramDesc ? `${skill.name}（${paramDesc}）` : skill.name;
  };

  const invokeSkill = (skill: SkillCard, params: SkillParams) => {
    if (busy) return;
    setActivePanel('chat');
    setActiveSkill(null);
    runAssistantRequest({
      kind: 'skill',
      skillId: skill.id,
      params,
      displayText: skillDisplayText(skill, params),
      loadingText: `${ASSISTANT_NAME} 正在执行「${skill.name}」...`,
    });
  };

  const handleSkillFormSubmit = () => {
    if (!activeSkill) return;
    for (const f of activeSkill.fields) {
      if (f.required && !String(formValues[f.key] || '').trim()) return;
    }
    invokeSkill(activeSkill, formValues);
  };

  const optimizePrompt = async () => {
    if (busy || optimizingPrompt) return;
    setOptimizingPrompt(true);
    setPromptOptimizationInfo('正在结合系统能力规划更清晰的提问...');
    try {
      const result = await hrmApi.assistantOptimizePrompt(input, sessionId || undefined);
      setInput(result.optimized || input);
      const source = result.model
        ? `强模型已按 ${result.routeTrack} / ${result.intent} 规划`
        : `已按 ${result.routeTrack} / ${result.intent} 规则规划`;
      setPromptOptimizationInfo(`${source}，可继续编辑后发送。`);
    } catch {
      if (!skillsLoaded) await loadSkills();
      setInput(buildPromptSuggestion(input, skills));
      setPromptOptimizationInfo('模型优化暂不可用，已按系统能力模板补充执行要求。');
    } finally {
      setOptimizingPrompt(false);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  };

  const selectSession = async (id: string) => {
    if (busy) return;
    const detail = await hrmApi.assistantGetSession(id);
    setSessionId(id);
    setMessages(sessionMessagesToLocal(detail.messages || []));
    setActivePanel('chat');
  };

  const deleteSession = async (id: string) => {
    if (busy) return;
    await hrmApi.assistantDeleteSession(id);
    if (sessionId === id) {
      setSessionId(null);
      setMessages([]);
    }
    setSessions((prev) => prev.filter((s) => s.id !== id));
  };

  const renderToolbarButton = (
    title: string,
    icon: string,
    onClick: () => void,
    active = false,
  ) => (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
      title={title}
      aria-label={title}
      className={`w-9 h-9 rounded-xl flex items-center justify-center transition-colors ${
        active ? 'bg-blue-100 text-blue-600' : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700'
      }`}
    >
      <i className={`fas ${icon} text-sm`}></i>
    </button>
  );

  const renderSkillPanel = () => (
    <div className="flex-1 overflow-y-auto px-4 py-4 sidebar-scroll bg-gray-50/40">
      {activeSkill ? (
        <div>
          <button
            onClick={() => setActiveSkill(null)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-blue-600 mb-3 transition-colors"
          >
            <i className="fas fa-arrow-left text-[10px]"></i>
            返回技能列表
          </button>
          <div className="rounded-2xl bg-white border border-gray-100 p-4 shadow-sm">
            <div className="flex items-center gap-3 mb-4">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${(COLOR_MAP[activeSkill.color] || COLOR_MAP.gray).bg}`}>
                <i className={`fas ${activeSkill.icon} ${(COLOR_MAP[activeSkill.color] || COLOR_MAP.gray).text}`}></i>
              </div>
              <div>
                <div className="text-sm font-semibold text-gray-900">{activeSkill.name}</div>
                <div className="text-xs text-gray-500">{activeSkill.description}</div>
              </div>
            </div>
            <div className="space-y-3">
              {activeSkill.fields.map((field) => (
                <div key={field.key}>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    {field.label}{field.required && <span className="text-red-500 ml-0.5">*</span>}
                  </label>
                  {field.type === 'select' ? (
                    <select
                      value={formValues[field.key] || ''}
                      onChange={(e) => setFormValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
                      className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 outline-none"
                    >
                      <option value="">请选择</option>
                      {(field.options || []).map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={field.type === 'number' ? 'number' : field.type}
                      value={formValues[field.key] || ''}
                      min={field.min}
                      max={field.max}
                      onChange={(e) => setFormValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
                      placeholder={field.placeholder}
                      className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 outline-none"
                    />
                  )}
                </div>
              ))}
            </div>
            <button
              onClick={handleSkillFormSubmit}
              disabled={busy}
              className="w-full mt-4 px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <i className="fas fa-play mr-2"></i>
              执行技能
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="mb-4 rounded-2xl bg-white border border-blue-100 p-3 text-xs text-gray-600 shadow-sm">
            <i className="fas fa-layer-group text-blue-500 mr-1.5"></i>
            技能面板会按您的角色展示可用能力，执行前仍会走权限和脱敏。
          </div>
          {Object.entries(groupedSkills).map(([category, cards]) => (
            <div key={category} className="mb-5">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-1 h-3.5 bg-blue-500 rounded-full"></span>
                <span className="text-sm font-semibold text-gray-700">{category}</span>
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                {cards.map((skill) => {
                  const c = COLOR_MAP[skill.color] || COLOR_MAP.gray;
                  return (
                    <button
                      key={skill.id}
                      onClick={() => handleSkillClick(skill)}
                      disabled={busy}
                      className={`relative text-left rounded-2xl border p-3.5 transition-all hover:shadow-md hover:-translate-y-0.5 disabled:opacity-50 overflow-hidden ${c.bg} ${c.border}`}
                    >
                      <i className={`fas ${skill.icon} ${c.text} absolute -bottom-2 -right-1 text-5xl opacity-10`}></i>
                      <div className="flex items-start gap-2.5">
                        <div className={`w-9 h-9 rounded-xl bg-white/80 flex items-center justify-center ${c.text}`}>
                          <i className={`fas ${skill.icon}`}></i>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold text-gray-800 truncate">{skill.name}</div>
                          <div className="text-xs text-gray-500 mt-1 line-clamp-2">{skill.description}</div>
                          {!!skill.fields?.length && (
                            <div className="mt-2 text-[10px] text-gray-500">
                              <i className="fas fa-sliders-h mr-1"></i>{skill.fields.length} 参数
                            </div>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          {!skillsLoaded && (
            <div className="text-center py-10 text-gray-400 text-xs">
              <i className="fas fa-spinner fa-spin text-lg mb-2 block"></i>
              加载技能列表...
            </div>
          )}
        </div>
      )}
    </div>
  );

  const renderHistoryPanel = () => (
    <div className="flex-1 overflow-y-auto px-4 py-4 sidebar-scroll bg-gray-50/40">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-gray-800">历史聊天记录</div>
        <button
          onClick={() => loadSessions(true)}
          className="text-xs text-blue-600 hover:text-blue-700"
        >
          <i className="fas fa-rotate mr-1"></i>刷新
        </button>
      </div>
      {historyLoading ? (
        <div className="text-center py-10 text-gray-400 text-xs">
          <i className="fas fa-spinner fa-spin text-lg mb-2 block"></i>
          加载历史会话...
        </div>
      ) : sessions.length ? (
        <div className="space-y-2">
          {sessions.map((s) => (
            <div key={s.id} className="group bg-white border border-gray-100 rounded-2xl p-3 shadow-sm hover:border-blue-200 transition-colors">
              <button onClick={() => selectSession(s.id)} className="w-full text-left">
                <div className="text-sm font-medium text-gray-800 truncate">{s.title || '未命名对话'}</div>
                <div className="text-[11px] text-gray-400 mt-1">
                  {s.messageCount || 0} 条消息 · {s.updatedAt ? new Date(s.updatedAt).toLocaleString() : ''}
                </div>
              </button>
              <button
                onClick={() => deleteSession(s.id)}
                className="mt-2 hidden group-hover:inline-flex text-[11px] text-red-500 hover:text-red-600"
              >
                <i className="fas fa-trash mr-1"></i>删除
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-10 text-gray-400 text-xs">
          <i className="far fa-clock text-2xl mb-2 block"></i>
          暂无历史会话
        </div>
      )}
    </div>
  );

  const renderMessages = () => (
    <AssistantMessageList
      messages={messages}
      scrollRef={scrollRef}
      assistantName={ASSISTANT_NAME}
      assistantAvatar={ASSISTANT_AVATAR}
      presetQuestions={presetQuestions}
      isPrivilegedUser={Boolean(isPrivilegedUser)}
      onSubmitQuestion={submitQuestion}
      onEntityClick={handleEntityClick}
      onEditUserMessage={handleEditUserMessage}
      onRetry={handleRetry}
      onRegenerate={handleRegenerate}
      formatTime={formatTime}
    />
  );

  useEffect(() => {
    togglePosRef.current = togglePos;
  }, [togglePos]);

  const clampTogglePos = (x: number, y: number) => {
    const size = 64;
    const maxX = Math.max(8, window.innerWidth - size - 8);
    const maxY = Math.max(8, window.innerHeight - size - 8);
    return { x: Math.min(Math.max(8, x), maxX), y: Math.min(Math.max(8, y), maxY) };
  };

  const handleTogglePointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    dragMovedRef.current = false;
    dragStateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: rect.left,
      originY: rect.top,
    };
    setDragging(true);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
  };

  const handleTogglePointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragStateRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!dragMovedRef.current && Math.abs(dx) + Math.abs(dy) < 5) return;
    dragMovedRef.current = true;
    setTogglePos(clampTogglePos(drag.originX + dx, drag.originY + dy));
  };

  const handleTogglePointerUp = () => {
    dragStateRef.current = null;
    setDragging(false);
    if (dragMovedRef.current && togglePosRef.current) {
      try {
        localStorage.setItem(TOGGLE_POS_KEY, JSON.stringify(togglePosRef.current));
      } catch {
        /* ignore */
      }
    }
  };

  const handleToggleClick = () => {
    if (dragMovedRef.current) {
      dragMovedRef.current = false;
      return;
    }
    setOpen((prev) => !prev);
  };

  const toggleStyle = togglePos
    ? { left: togglePos.x, top: togglePos.y, right: 'auto' as const, bottom: 'auto' as const }
    : undefined;

  const panelStyle: React.CSSProperties = togglePos
    ? {
        height: 'min(720px, calc(100vh - 8rem))',
        right: Math.min(
          Math.max(8, window.innerWidth - (togglePos.x + 64)),
          Math.max(8, window.innerWidth - 440 - 8),
        ),
        bottom: Math.min(Math.max(8, window.innerHeight - togglePos.y + 8), Math.max(8, window.innerHeight - 120)),
        left: 'auto',
        top: 'auto',
      }
    : { height: 'min(720px, calc(100vh - 8rem))' };

  return (
    <>
      <button
        type="button"
        onPointerDown={handleTogglePointerDown}
        onPointerMove={handleTogglePointerMove}
        onPointerUp={handleTogglePointerUp}
        onClick={handleToggleClick}
        title={`${ASSISTANT_NAME}（可拖动）`}
        aria-label={ASSISTANT_NAME}
        style={toggleStyle}
        className={`hpt-ai-assistant-toggle ${open ? 'is-open' : ''} fixed bottom-6 right-6 z-[55] w-16 h-16 rounded-3xl flex items-center justify-center ${dragging ? '' : 'transition-all duration-300'} shadow-xl border overflow-hidden cursor-move touch-none select-none ${
          open ? 'bg-slate-800 border-slate-700 scale-95' : 'bg-white border-blue-100 hover:shadow-2xl hover:scale-105'
        }`}
      >
        {open ? (
          <i className="fas fa-xmark text-white text-xl"></i>
        ) : (
          <>
            <img src={ASSISTANT_AVATAR} alt={ASSISTANT_NAME} className="w-[88px] h-[88px] object-contain pointer-events-none" />
            <span className="absolute -top-1 -right-1 px-1.5 py-0.5 rounded-full bg-blue-600 text-white text-[9px] font-bold shadow">
              AI
            </span>
          </>
        )}
      </button>

      {open && (
        <div
          className={`hpt-ai-assistant-panel ${expanded ? 'is-expanded' : 'is-compact'} fixed bottom-24 right-6 z-[55] w-[440px] max-w-[calc(100vw-3rem)] bg-white rounded-[28px] shadow-2xl border border-gray-100 flex flex-col animate-fade-in overflow-hidden`}
          style={panelStyle}
        >
          <div className="hpt-ai-assistant-header flex items-center justify-between px-5 py-4 border-b border-gray-100 bg-white">
            <div className="flex items-center gap-3 min-w-0">
              <div className="hpt-ai-assistant-avatar w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center flex-shrink-0 overflow-hidden shadow-inner">
                <img src={ASSISTANT_AVATAR} alt="" className="w-[64px] h-[64px] object-contain" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-base font-semibold text-gray-900">{ASSISTANT_NAME}</span>
                  <span className="px-1.5 py-0.5 text-[10px] font-bold bg-blue-600 text-white rounded">Copilot</span>
                </div>
                <div className="hpt-ai-assistant-subtitle text-xs text-gray-500 mt-0.5">
                  查询、生成、分析与提示词优化
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              {renderToolbarButton('当前聊天', 'fa-comments', () => setActivePanel('chat'), activePanel === 'chat')}
              {renderToolbarButton('技能面板', 'fa-layer-group', openSkillsPanel, activePanel === 'skills')}
              {renderToolbarButton('新建聊天', 'fa-pen-to-square', handleNewChat)}
              {renderToolbarButton('历史聊天记录', 'fa-clock-rotate-left', openHistoryPanel, activePanel === 'history')}
              {renderToolbarButton(expanded ? '收起面板' : '展开面板', expanded ? 'fa-compress' : 'fa-expand', () => setExpanded((prev) => !prev), expanded)}
              {renderToolbarButton('关闭', 'fa-xmark', () => setOpen(false))}
            </div>
          </div>

          <div className="hpt-ai-assistant-content flex-1 min-h-0 flex flex-col">
            {activePanel === 'skills' ? renderSkillPanel() : activePanel === 'history' ? renderHistoryPanel() : renderMessages()}
          </div>

          <div className="hpt-ai-assistant-composer px-4 py-3 border-t border-gray-100 bg-white">
            {editingMessageId && (
              <div className="hpt-ai-assistant-tip mb-2 flex items-center justify-between rounded-xl bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-blue-700">
                <span><i className="fas fa-pen mr-1"></i>正在编辑上一条消息，发送后会从该处重新生成</span>
                <button onClick={() => setEditingMessageId(null)} className="text-blue-600 hover:text-blue-800">取消</button>
              </div>
            )}
            {promptOptimizationInfo && (
              <div className="hpt-ai-assistant-tip mb-2 flex items-start justify-between gap-2 rounded-xl border border-indigo-100 bg-indigo-50 px-3 py-2 text-[11px] text-indigo-700">
                <span><i className="fas fa-wand-magic-sparkles mr-1"></i>{promptOptimizationInfo}</span>
                <button type="button" onClick={() => setPromptOptimizationInfo(null)} className="text-indigo-400 hover:text-indigo-700">关闭</button>
              </div>
            )}
            <div className="flex items-end gap-2">
              <button
                type="button"
                onClick={optimizePrompt}
                disabled={busy || optimizingPrompt}
                title={optimizingPrompt ? '正在优化提示词' : '优化提示词'}
                className="w-11 h-11 rounded-2xl flex items-center justify-center bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-100 disabled:opacity-50 transition-colors flex-shrink-0"
              >
                <i className={`fas ${optimizingPrompt ? 'fa-spinner fa-spin' : 'fa-wand-magic-sparkles'} text-sm`}></i>
              </button>
              <div className="flex-1 min-w-0 flex items-end gap-2 px-3 py-2 bg-gray-50 border border-gray-200 rounded-2xl focus-within:ring-2 focus-within:ring-blue-500/30 focus-within:border-blue-400 transition-all">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    setVoiceInfo(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      submitQuestion(input);
                    }
                  }}
                  rows={1}
                  maxLength={800}
                  placeholder={`问 ${ASSISTANT_NAME}，或先点左侧魔法棒优化提示词`}
                  disabled={busy}
                  className="flex-1 min-w-0 bg-transparent text-sm outline-none resize-none disabled:opacity-50 placeholder-gray-400 sidebar-scroll py-2"
                  style={{ maxHeight: `${INPUT_MAX_HEIGHT}px`, minHeight: `${INPUT_MIN_HEIGHT}px`, lineHeight: '20px' }}
                />
                <button
                  type="button"
                  onClick={toggleVoiceInput}
                  disabled={busy || transcribingVoice}
                  title={
                    listening
                      ? '停止听写'
                      : transcribingVoice
                        ? '正在识别语音'
                        : (!speechSupported && !recordingSupported)
                          ? voiceUnavailableText()
                          : '语音输入（优先使用服务端开源 ASR）'
                  }
                  className={`w-9 h-9 rounded-xl flex items-center justify-center transition-colors flex-shrink-0 ${
                    listening
                      ? 'bg-red-50 text-red-600 border border-red-100'
                      : 'bg-white text-gray-500 hover:text-blue-600 hover:bg-blue-50 border border-gray-100'
                  } disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  <i className={`fas ${transcribingVoice ? 'fa-spinner fa-spin' : listening ? 'fa-stop' : 'fa-microphone'} text-sm`}></i>
                </button>
              </div>
              <button
                type="button"
                onClick={busy ? cancelRequest : () => submitQuestion(input)}
                disabled={!busy && !input.trim()}
                className={`w-11 h-11 rounded-2xl flex items-center justify-center text-white shadow-md hover:shadow-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none flex-shrink-0 ${
                  busy ? 'bg-red-500 hover:bg-red-600' : 'bg-blue-600 hover:bg-blue-700'
                }`}
                title={busy ? '中断请求' : '发送'}
              >
                <i className={`fas ${busy ? 'fa-stop' : 'fa-paper-plane'} text-sm`}></i>
              </button>
            </div>
            {voiceInfo && (
              <div className="hpt-ai-assistant-voice mt-2 flex items-center justify-center gap-1.5 text-[11px] text-blue-500">
                <i className={`fas ${listening ? 'fa-wave-square' : transcribingVoice ? 'fa-spinner fa-spin' : 'fa-microphone-lines'}`}></i>
                <span>{voiceInfo}</span>
              </div>
            )}
            <div className="hpt-ai-assistant-footnote text-[11px] text-gray-400 mt-2 text-center flex items-center justify-center gap-1.5">
              <i className="fas fa-shield-alt text-gray-400"></i>
              <span>有权限校验与脱敏；可连续追问、编辑、重试和重新生成</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default AIAssistant;
