import React from 'react';
import ChatWidget from '../ChatRichWidgets';
import type { RichWidget } from '../ChatRichWidgets';
import type {
  AssistantEntity,
  AssistantMessage,
  AssistantRenderBlock,
  CopilotAction,
  CopilotContextPayload,
  CopilotEvidenceSource,
  CopilotPlanStep,
} from './types';

interface CopilotResponseProps {
  message: AssistantMessage;
  onEntityClick: (entity: AssistantEntity) => void;
  onAction: (payload: string) => void;
}

export const CopilotResponse: React.FC<CopilotResponseProps> = ({ message, onEntityClick, onAction }) => {
  if (!message || message.loading || message.role !== 'assistant') return null;
  const copilot = message.copilot || {};
  const widgets = message.widgets || [];
  const renderBlocks = message.renderBlocks || [];
  const hasRenderableBlocks = renderBlocks.some((block) => block?.payload);

  return (
    <div className="text-left">
      <RenderBlocks blocks={renderBlocks} fallbackWidgets={widgets} onEntityClick={onEntityClick} onAction={onAction} />
      <CopilotContext context={copilot.currentContext || message.clientContext} />
      <PlanTimeline plan={copilot.plan || []} />
      <EvidenceStrip evidence={copilot.evidence || []} onEntityClick={onEntityClick} />
      <CopilotActions actions={copilot.actions || []} onAction={onAction} />
      {!hasRenderableBlocks && widgets.length > 0 && null}
    </div>
  );
};

interface RenderBlocksProps {
  blocks: AssistantRenderBlock[];
  fallbackWidgets: RichWidget[];
  onEntityClick: (entity: AssistantEntity) => void;
  onAction: (payload: string) => void;
}

const RenderBlocks: React.FC<RenderBlocksProps> = ({ blocks, fallbackWidgets, onEntityClick, onAction }) => {
  const renderableBlocks = blocks.filter((block) => block?.payload);
  const widgets = renderableBlocks.length
    ? renderableBlocks.map((block) => block.payload).filter((widget): widget is RichWidget => Boolean(widget))
    : fallbackWidgets;
  if (!widgets.length) return null;
  return (
    <div className="mt-1 space-y-1 text-left">
      {widgets.map((widget, idx) => (
        <ChatWidget
          key={widget.id || widget.type || idx}
          widget={widget}
          onEntityClick={onEntityClick}
          onAction={onAction}
        />
      ))}
    </div>
  );
};

const CopilotContext: React.FC<{ context?: CopilotContextPayload }> = ({ context }) => {
  if (!context?.path && !context?.moduleName) return null;
  const filters = context.visibleFilters || {};
  const filterEntries = Object.entries(filters).filter(([, value]) => value !== undefined && value !== '');
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-gray-500">
      <span className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-slate-600">
        <i className="fas fa-location-dot text-[10px]"></i>
        {context.moduleName || context.pageTitle || context.path}
      </span>
      {filterEntries.slice(0, 3).map(([key, value]) => (
        <span key={key} className="inline-flex items-center gap-1 rounded-lg bg-white border border-gray-100 px-2 py-1">
          {key}: {String(value)}
        </span>
      ))}
    </div>
  );
};

const PlanTimeline: React.FC<{ plan: CopilotPlanStep[] }> = ({ plan }) => {
  if (!plan?.length) return null;
  return (
    <div className="mt-2 rounded-xl border border-blue-100 bg-blue-50/40 px-3 py-2 text-left">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-blue-700">
        <i className="fas fa-list-check text-[11px]"></i>
        执行过程
      </div>
      <div className="space-y-1.5">
        {plan.slice(0, 6).map((step, idx) => {
          const ok = step.status === 'ok' || step.status === 'planned';
          return (
            <div key={`${step.id || idx}`} className="flex items-center gap-2 text-[11px]">
              <span className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                ok ? 'bg-blue-100 text-blue-600' : 'bg-red-100 text-red-600'
              }`}>
                <i className={`fas ${ok ? 'fa-check' : 'fa-exclamation'} text-[9px]`}></i>
              </span>
              <span className="flex-1 min-w-0 truncate text-gray-700">{step.label || step.type || '步骤'}</span>
              {step.rowsCount !== undefined && step.rowsCount > 0 && (
                <span className="text-gray-400">{step.rowsCount} 条</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

interface EvidenceStripProps {
  evidence: CopilotEvidenceSource[];
  onEntityClick: (entity: AssistantEntity) => void;
}

const EvidenceStrip: React.FC<EvidenceStripProps> = ({ evidence, onEntityClick }) => {
  if (!evidence?.length) return null;
  return (
    <div className="mt-2 rounded-xl border border-gray-100 bg-white px-3 py-2 text-left">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-gray-700">
        <i className="fas fa-link text-[11px] text-blue-500"></i>
        证据来源
      </div>
      <div className="flex flex-wrap gap-1.5">
        {evidence.slice(0, 8).map((source, idx) => {
          const label = source.title || source.label || source.recordId || source.id || source.module || `来源 ${idx + 1}`;
          const clickable = source.url || source.href;
          return (
            <button
              key={`${label}-${idx}`}
              type="button"
              onClick={() => clickable && onEntityClick({ url: clickable })}
              disabled={!clickable}
              className={`inline-flex max-w-full items-center gap-1 rounded-lg border px-2 py-1 text-[11px] ${
                clickable
                  ? 'border-blue-100 bg-blue-50 text-blue-600 hover:bg-blue-100'
                  : 'border-gray-100 bg-gray-50 text-gray-500'
              }`}
            >
              <i className="fas fa-database text-[10px]"></i>
              <span className="truncate max-w-[160px]">{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

const CopilotActions: React.FC<{ actions: CopilotAction[]; onAction: (payload: string) => void }> = ({ actions, onAction }) => {
  if (!actions?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5 text-left">
      {actions.slice(0, 6).map((action, idx) => (
        <button
          key={`${action.payload || action.label || idx}`}
          type="button"
          onClick={() => onAction(action.payload || action.label || action.title || '')}
          className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[11px] transition-colors ${
            action.requiresConfirmation
              ? 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
              : 'border-blue-100 bg-blue-50 text-blue-600 hover:bg-blue-100'
          }`}
        >
          <i className={`fas ${action.requiresConfirmation ? 'fa-shield-halved' : 'fa-arrow-right'} text-[10px]`}></i>
          {action.label || action.title || action.payload || '继续'}
        </button>
      ))}
    </div>
  );
};

export default CopilotResponse;
