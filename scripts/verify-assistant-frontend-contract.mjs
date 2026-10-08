import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();

const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

const checks = [
  {
    file: 'src/components/assistant/CopilotResponse.tsx',
    name: 'RenderBlocks renders every payload-backed block, including source=entities/action',
    patterns: [
      /renderBlocks\.some\(\(block\) => block\?\.payload\)/,
      /blocks\.filter\(\(block\) => block\?\.payload\)/,
      /renderableBlocks\.length\s*\?\s*renderableBlocks\.map\(\(block\) => block\.payload\)/,
      /filter\(\(widget\): widget is RichWidget => Boolean\(widget\)\)/,
    ],
  },
  {
    file: 'src/components/ChatRichWidgets.tsx',
    name: 'Entity cards accept backend entities, items, or data arrays',
    patterns: [
      /const ents = widget\.entities \|\| widget\.items \|\| widget\.data \|\| \[\]/,
    ],
  },
  {
    file: 'src/components/ChatRichWidgets.tsx',
    name: 'Source citations can route internal evidence links through onEntityClick',
    patterns: [
      /const external = href && String\(href\)\.startsWith\('http'\)/,
      /href && onEntityClick && !external/,
      /onEntityClick\(\{ url: href \}\)/,
    ],
  },
  {
    file: 'src/components/ChatRichWidgets.tsx',
    name: 'ECharts widgets render real chart UI instead of raw-code placeholder',
    patterns: [
      /const EChartsWidget: React\.FC/,
      /normalizeEchartsWidget/,
      /case 'echarts':\s*return <EChartsWidget widget=\{widget\} \/>;/,
      /role="img" aria-label=\{chart\.title\}/,
    ],
    forbidden: [
      /case 'echarts':\s*return <CodeFallback widget=\{widget\} label="ECharts" \/>;/,
      /暂未启用图表渲染/,
    ],
  },
  {
    file: 'src/components/assistant/AssistantMessageList.tsx',
    name: 'Legacy entity links are hidden when structured entity cards are present',
    patterns: [
      /const hasStructuredEntityCards =/,
      /block\?\.payload\?\.type === 'entity_cards'/,
      /if \(hasStructuredEntityCards\) return null/,
    ],
  },
  {
    file: 'src/components/AIAssistant.tsx',
    name: 'Assistant layout exposes compact and focus modes without persisted expanded state',
    patterns: [
      /const \[expanded, setExpanded\] = useState\(false\)/,
      /document\.body\.classList\.toggle\('hpt-assistant-expanded', open && expanded\)/,
      /new CustomEvent\('hpt-assistant-layout', \{ detail: \{ open, expanded \} \}\)/,
      /expanded \? 'is-expanded' : 'is-compact'/,
      /expanded \? '收起面板' : '展开面板'/,
    ],
    forbidden: [
      /EXPANDED_KEY/,
      /ai_assistant_expanded/,
    ],
  },
  {
    file: 'src/components/Layout.tsx',
    name: 'Layout reacts to assistant layout events and only reserves desktop side space',
    patterns: [
      /const \[assistantExpanded, setAssistantExpanded\] = useState\(false\)/,
      /CustomEvent<\{ open\?: boolean; expanded\?: boolean \}>/,
      /setAssistantExpanded\(Boolean\(detail\.expanded\)\)/,
      /width < 1180/,
      /setAssistantReserve\(428\)/,
      /setAssistantReserve\(480\)/,
      /paddingRight: assistantReserve/,
    ],
  },
  {
    file: 'src/index.css',
    name: 'Responsive assistant modes preserve module controls in compact mode and focus assistant in expanded mode',
    patterns: [
      /@media \(min-width: 840px\) and \(max-width: 1179px\)/,
      /body\.hpt-assistant-open \.hpt-ai-assistant-panel\.is-expanded/,
      /body\.hpt-assistant-expanded::before/,
      /body\.hpt-assistant-open \.hpt-ai-assistant-panel\.is-compact \.hpt-ai-assistant-content/,
      /display: none !important/,
      /body\.hpt-assistant-open \.hpt-ai-assistant-panel\.is-compact \.hpt-ai-assistant-composer textarea/,
    ],
  },
  {
    file: 'src/components/SmartFilters.tsx',
    name: 'Smart filters expose visible filter labels and values for Copilot page context',
    patterns: [
      /dataContextProps/,
      /'data-hpt-filter'/,
      /'data-hpt-filter-label'/,
      /'data-hpt-filter-value'/,
      /'data-hpt-filter-display'/,
      /dataContextProps\(label, value, value, 'search'\)/,
      /displayRangeValue/,
    ],
  },
  {
    file: 'src/components/assistant/copilotContext.ts',
    name: 'Assistant client context collects URL, native month, and SmartFilter state',
    patterns: [
      /collectUrlFilters/,
      /collectDomFilters/,
      /collectNativeMonthFilter/,
      /\[data-hpt-filter\]/,
      /CANONICAL_FILTER_KEYS/,
      /search/,
      /employeeId/,
      /departmentId/,
      /visibleFilters: Record<string, string>/,
    ],
  },
];

const failures = [];
for (const check of checks) {
  const content = read(check.file);
  for (const pattern of check.patterns) {
    if (!pattern.test(content)) {
      failures.push(`${check.name}: ${check.file} missing ${pattern}`);
    }
  }
  for (const pattern of check.forbidden || []) {
    if (pattern.test(content)) {
      failures.push(`${check.name}: ${check.file} still contains forbidden ${pattern}`);
    }
  }
}

if (failures.length) {
  console.error('Assistant frontend contract verification failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Assistant frontend contract verification passed (${checks.length} checks).`);
