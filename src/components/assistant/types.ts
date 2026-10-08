import type { RichWidget } from '../ChatRichWidgets';

export interface AssistantEntity {
  type?: string;
  typeLabel?: string;
  icon?: string;
  id?: string;
  title?: string;
  subtitle?: string;
  meta?: string;
  url?: string;
  href?: string;
}

export interface AssistantRenderBlock {
  id?: string | number;
  kind?: string;
  widgetType?: string;
  payload?: RichWidget | null;
}

export interface CopilotContextPayload {
  path?: string;
  route?: string;
  moduleId?: string;
  moduleName?: string;
  pageTitle?: string;
  visibleFilters?: Record<string, unknown>;
}

export interface CopilotPlanStep {
  id?: string | number;
  type?: string;
  label?: string;
  status?: string;
  rowsCount?: number;
}

export interface CopilotEvidenceSource {
  id?: string | number;
  title?: string;
  label?: string;
  recordId?: string | number;
  module?: string;
  url?: string;
  href?: string;
}

export interface CopilotAction {
  label?: string;
  title?: string;
  payload?: string;
  requiresConfirmation?: boolean;
  description?: string;
  icon?: string;
  intent?: string;
  variant?: string;
}

export interface AssistantMeta {
  taskTemplateId?: string | null;
  usedSkills?: string[];
  riskLevel?: 'low' | 'medium' | 'high';
  requiresConfirmation?: boolean;
  fallbackUsed?: boolean;
  routeTrack?: string;
  taskType?: string;
  modelProfile?: string;
}

export interface AssistantRequest {
  kind: 'query' | 'skill';
  question?: string;
  skillId?: string;
  params?: Record<string, string>;
  displayText: string;
  loadingText: string;
}

export interface CopilotPayload {
  currentContext?: CopilotContextPayload;
  plan?: CopilotPlanStep[];
  evidence?: CopilotEvidenceSource[];
  actions?: CopilotAction[];
}

export interface AssistantMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  entities?: AssistantEntity[];
  widgets?: RichWidget[];
  renderBlocks?: AssistantRenderBlock[];
  copilot?: CopilotPayload;
  clientContext?: CopilotContextPayload;
  meta?: AssistantMeta;
  loading?: boolean;
  error?: boolean;
  cancelled?: boolean;
  timestamp: number;
  retry?: AssistantRequest;
}

export interface AssistantSessionMessageRow {
  role?: 'user' | 'assistant';
  content?: string;
  entities?: AssistantEntity[];
  widgets?: RichWidget[];
  renderBlocks?: AssistantRenderBlock[];
  copilot?: CopilotPayload;
  clientContext?: CopilotContextPayload;
  meta?: AssistantMeta;
  ts?: string | number;
}

export interface AssistantQueryResult {
  schemaVersion?: string;
  question?: string;
  summary?: string;
  answer?: { content?: string; format?: string };
  entities?: AssistantEntity[];
  widgets?: RichWidget[];
  renderBlocks?: AssistantRenderBlock[];
  copilot?: CopilotPayload;
  clientContext?: CopilotContextPayload;
  sessionId?: string | null;
  generatedAt?: string;
  meta?: AssistantMeta;
}
