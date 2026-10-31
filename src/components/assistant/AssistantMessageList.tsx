import React from 'react';
import RichText from '../RichText';
import CopilotResponse from './CopilotResponse';
import type { AssistantEntity, AssistantMessage } from './types';

interface AssistantMessageListProps {
  messages: AssistantMessage[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
  assistantName: string;
  assistantAvatar: string;
  presetQuestions: string[];
  isPrivilegedUser: boolean;
  onSubmitQuestion: (question: string) => void;
  onEntityClick: (entity: AssistantEntity) => void;
  onEditUserMessage: (message: AssistantMessage) => void;
  onRetry: (message: AssistantMessage) => void;
  onRegenerate: (messageId: string) => void;
  formatTime: (timestamp: number) => string;
}

export const AssistantMessageList: React.FC<AssistantMessageListProps> = ({
  messages,
  scrollRef,
  assistantName,
  assistantAvatar,
  presetQuestions,
  isPrivilegedUser,
  onSubmitQuestion,
  onEntityClick,
  onEditUserMessage,
  onRetry,
  onRegenerate,
  formatTime,
}) => (
  <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4 sidebar-scroll bg-slate-50/70">
    {messages.length === 0 ? (
      <EmptyAssistantState
        assistantName={assistantName}
        assistantAvatar={assistantAvatar}
        presetQuestions={presetQuestions}
        onSubmitQuestion={onSubmitQuestion}
      />
    ) : (
      messages.map((message) => (
        <MessageRow
          key={message.id}
          message={message}
          assistantAvatar={assistantAvatar}
          isPrivilegedUser={isPrivilegedUser}
          onEntityClick={onEntityClick}
          onEditUserMessage={onEditUserMessage}
          onRetry={onRetry}
          onRegenerate={onRegenerate}
          onSubmitQuestion={onSubmitQuestion}
          formatTime={formatTime}
        />
      ))
    )}
  </div>
);

interface EmptyAssistantStateProps {
  assistantName: string;
  assistantAvatar: string;
  presetQuestions: string[];
  onSubmitQuestion: (question: string) => void;
}

const EmptyAssistantState: React.FC<EmptyAssistantStateProps> = ({
  assistantName,
  assistantAvatar,
  presetQuestions,
  onSubmitQuestion,
}) => (
  <div className="flex flex-col items-center text-center py-6">
    <div className="relative w-20 h-20 rounded-3xl bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center mb-4 overflow-hidden shadow-inner">
      <img src={assistantAvatar} alt={assistantName} className="w-[108px] h-[108px] object-contain" />
    </div>
    <div className="text-base font-semibold text-gray-900 mb-1">您好，我是{assistantName}</div>
    <p className="text-xs text-gray-500 mb-4 leading-relaxed">
      我可以查询系统数据、生成 HR 文案、分析候选人和帮您优化提问。
    </p>
    <div className="w-full text-left space-y-1.5">
      <div className="text-[11px] text-gray-400 mb-1">试试这些：</div>
      {presetQuestions.map((question: string) => (
        <button
          key={question}
          onClick={() => onSubmitQuestion(question)}
          className="w-full text-left px-3 py-2 text-xs text-gray-600 bg-white hover:bg-blue-50 hover:text-blue-600 rounded-xl transition-colors border border-gray-100 hover:border-blue-200"
        >
          <i className="fas fa-arrow-right text-[10px] mr-1.5 opacity-50"></i>
          {question}
        </button>
      ))}
    </div>
  </div>
);

interface MessageRowProps {
  message: AssistantMessage;
  assistantAvatar: string;
  isPrivilegedUser: boolean;
  onEntityClick: (entity: AssistantEntity) => void;
  onEditUserMessage: (message: AssistantMessage) => void;
  onRetry: (message: AssistantMessage) => void;
  onRegenerate: (messageId: string) => void;
  onSubmitQuestion: (question: string) => void;
  formatTime: (timestamp: number) => string;
}

const MessageRow = ({
  message,
  assistantAvatar,
  isPrivilegedUser,
  onEntityClick,
  onEditUserMessage,
  onRetry,
  onRegenerate,
  onSubmitQuestion,
  formatTime,
}: MessageRowProps) => (
  <div className={`flex gap-2 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}>
    <div className={`w-9 h-9 rounded-2xl flex items-center justify-center flex-shrink-0 overflow-hidden ${
      message.role === 'user' ? 'bg-gray-200 text-gray-600' : 'bg-gradient-to-br from-blue-50 to-indigo-100'
    }`}>
      {message.role === 'user' ? (
        <i className="fas fa-user text-sm"></i>
      ) : (
        <img src={assistantAvatar} alt="" className="w-[48px] h-[48px] object-contain" />
      )}
    </div>
    <div className={`flex-1 min-w-0 ${message.role === 'user' ? 'text-right' : ''}`}>
      <MessageBubble message={message} />
      <MessageToolbar
        message={message}
        onEditUserMessage={onEditUserMessage}
        onRetry={onRetry}
        onRegenerate={onRegenerate}
        formatTime={formatTime}
      />
      {message.role === 'assistant' && !message.loading && (
        <CopilotResponse
          message={message}
          onEntityClick={onEntityClick}
          onAction={(payload) => onSubmitQuestion(payload)}
        />
      )}
      <ExecutionDetails message={message} isPrivilegedUser={isPrivilegedUser} />
      <EntityLinks message={message} onEntityClick={onEntityClick} />
    </div>
  </div>
);

const MessageBubble: React.FC<{ message: AssistantMessage }> = ({ message }) => (
  <div
    className={`inline-block max-w-full px-3.5 py-2.5 rounded-2xl text-sm shadow-sm ${
      message.role === 'user'
        ? 'bg-blue-600 text-white rounded-tr-md'
        : message.error
        ? 'bg-red-50 text-red-700 border border-red-100 rounded-tl-md'
        : message.cancelled
        ? 'bg-gray-50 text-gray-500 border border-gray-100 rounded-tl-md'
        : 'bg-white text-gray-700 border border-gray-100 rounded-tl-md'
    }`}
  >
    {message.loading ? (
      <span className="flex items-center gap-2 text-gray-500">
        <i className="fas fa-circle-notch fa-spin text-blue-500"></i>
        <span>{message.content || '思考中...'}</span>
      </span>
    ) : message.role === 'user' ? (
      <span className="whitespace-pre-wrap break-words text-left block">{message.content}</span>
    ) : (
      <RichText text={message.content} className="text-left break-words" />
    )}
  </div>
);

interface MessageToolbarProps {
  message: AssistantMessage;
  onEditUserMessage: (message: AssistantMessage) => void;
  onRetry: (message: AssistantMessage) => void;
  onRegenerate: (messageId: string) => void;
  formatTime: (timestamp: number) => string;
}

const MessageToolbar: React.FC<MessageToolbarProps> = ({
  message,
  onEditUserMessage,
  onRetry,
  onRegenerate,
  formatTime,
}) => {
  if (message.loading) return null;
  return (
    <div className={`mt-1 flex items-center gap-2 text-[10px] text-gray-300 ${message.role === 'user' ? 'justify-end' : ''}`}>
      <span>{formatTime(message.timestamp)}</span>
      {message.role === 'user' && (
        <button onClick={() => onEditUserMessage(message)} className="hover:text-blue-500">
          <i className="fas fa-pen mr-0.5"></i>编辑
        </button>
      )}
      {message.role === 'assistant' && (
        <>
          {message.error && (
            <button onClick={() => onRetry(message)} className="hover:text-blue-500">
              <i className="fas fa-rotate-right mr-0.5"></i>重试
            </button>
          )}
          <button onClick={() => onRegenerate(message.id)} className="hover:text-blue-500">
            <i className="fas fa-wand-magic-sparkles mr-0.5"></i>重新生成
          </button>
        </>
      )}
    </div>
  );
};

const ExecutionDetails: React.FC<{ message: AssistantMessage; isPrivilegedUser: boolean }> = ({ message, isPrivilegedUser }) => {
  if (message.role !== 'assistant' || !message.meta || !isPrivilegedUser) return null;
  return (
    <details className="mt-1.5 text-[10px] text-gray-500 bg-gray-50 rounded-xl px-2 py-1.5 border border-gray-100">
      <summary className="cursor-pointer hover:text-blue-600 select-none">
        <i className="fas fa-cog mr-1"></i>执行详情
        {message.meta.taskTemplateId && <span className="ml-1.5 text-blue-600">{message.meta.taskTemplateId}</span>}
        {message.meta.routeTrack && <span className="ml-1.5 px-1 py-0.5 rounded bg-blue-50 text-blue-600">{message.meta.routeTrack}</span>}
        {message.meta.fallbackUsed && <span className="ml-1.5 px-1 py-0.5 rounded bg-amber-100 text-amber-600">fallback</span>}
      </summary>
      <div className="mt-1.5 space-y-0.5 pl-3">
        {(message.meta.usedSkills?.length || 0) > 0 && <div>使用 skills：{message.meta.usedSkills?.join('、')}</div>}
        {message.meta.taskType && <div>任务类型：{message.meta.taskType}</div>}
        {message.meta.modelProfile && <div>模型档位：{message.meta.modelProfile}</div>}
        {message.meta.requiresConfirmation && <div className="text-amber-600">此动作将在您点击确认后执行。</div>}
      </div>
    </details>
  );
};

const EntityLinks: React.FC<{ message: AssistantMessage; onEntityClick: (entity: AssistantEntity) => void }> = ({
  message,
  onEntityClick,
}) => {
  if (message.role !== 'assistant' || !message.entities?.length) return null;
  const hasStructuredEntityCards = (message.widgets || []).some((widget) => widget?.type === 'entity_cards')
    || (message.renderBlocks || []).some((block) => (
      block?.widgetType === 'entity_cards'
      || block?.kind === 'entity_cards'
      || block?.payload?.type === 'entity_cards'
    ));
  if (hasStructuredEntityCards) return null;
  return (
    <div className="mt-2 space-y-1.5 text-left">
      {message.entities.map((entity, idx) => (
        <button
          key={`${entity.type || 'entity'}-${entity.id || idx}`}
          onClick={() => onEntityClick(entity)}
          className="w-full flex items-center gap-2.5 px-3 py-2 bg-white rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50/30 hover:shadow-sm transition-all group text-left"
        >
          <div className="w-8 h-8 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-100">
            <i className={`fas ${entity.icon || 'fa-circle'} text-blue-500 text-xs`}></i>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-gray-800 truncate group-hover:text-blue-600">{entity.title}</span>
              {entity.typeLabel && (
                <span className="text-[10px] text-gray-400 px-1.5 py-0.5 bg-gray-100 rounded flex-shrink-0">{entity.typeLabel}</span>
              )}
            </div>
            {entity.subtitle && <div className="text-[11px] text-gray-500 truncate mt-0.5">{entity.subtitle}</div>}
            {entity.meta && <div className="text-[10px] text-gray-400 truncate mt-0.5">{entity.meta}</div>}
          </div>
          <i className="fas fa-chevron-right text-[10px] text-gray-300 group-hover:text-blue-500 flex-shrink-0"></i>
        </button>
      ))}
    </div>
  );
};

export default AssistantMessageList;
