#!/usr/bin/env node
/**
 * Generate reviewable Skill Card / eval patch candidates from collected
 * Skill-first failure samples.
 *
 * This script never edits production Skill Cards. It writes suggestions for
 * human review, then maintainers can merge selected examples and run evals.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const inputPath = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(repoRoot, 'artifacts', 'assistant-routing', 'skill-first-failure-samples.jsonl');
const outputPath = process.argv[3]
  ? path.resolve(process.argv[3])
  : path.join(repoRoot, 'artifacts', 'assistant-routing', 'skill-card-eval-candidate-patch.json');

const referenceProjectMechanisms = [
  {
    project: 'hermes-agent',
    mechanism: 'closed_learning_loop',
    hrm_adaptation: 'collect failure samples automatically, generate reviewable Skill Card and eval suggestions, and keep production Skill mutation human-approved only',
    evidence: [
      'artifacts/agent-reference/hermes-agent/README.md',
      'artifacts/agent-reference/hermes-agent/agent/agent_runtime_helpers.py',
    ],
  },
  {
    project: 'openclaw',
    mechanism: 'canonical_runtime_state_and_explicit_migration',
    hrm_adaptation: 'treat generated eval patches as migration/review artifacts, not runtime fallback rules or hidden compatibility shims',
    evidence: [
      'artifacts/agent-reference/openclaw/AGENTS.md',
      'artifacts/agent-reference/openclaw/src/cli/program/subcli-descriptors.ts',
    ],
  },
  {
    project: 'openclaw',
    mechanism: 'approval_and_plugin_boundary',
    hrm_adaptation: 'keep side-effect HRM Skills behind pending confirmation and execute only through registered business tools',
    evidence: [
      'artifacts/agent-reference/openclaw/AGENTS.md',
    ],
  },
];

const humanReviewChecklist = [
  'Confirm the suggested Skill is the right user-intent granularity, not just the highest lexical match.',
  'Check anti-examples for neighboring Skills before merging new colloquial examples.',
  'Verify every suggested slot hint is allowed by the Skill Card schema and registered tool schema.',
  'For side-effect Skills, confirm the action still returns a pending confirmation and never writes directly.',
  'Add or update regression cases before merging accepted Skill Card changes.',
  'Run the listed verification commands after review-approved changes are applied.',
];

const regressionVerificationCommands = [
  'python -m pytest backend-python/tests/assistant_core/test_skill_first_runtime.py -q',
  'npm run verify:assistant-kernel-nl-matrix -- --quick --no-reset-llm-health',
  'npm run verify:assistant-kernel-crud-matrix -- --quick --no-reset-llm-health',
];

function readSamples(filePath) {
  if (!fs.existsSync(filePath)) return [];
  return fs.readFileSync(filePath, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

function topCandidates(sample) {
  const top = Array.isArray(sample.top_k_skills) ? sample.top_k_skills : [];
  return top.slice(0, 5);
}

function pushUnique(list, value) {
  if (!value) return;
  if (!list.includes(value)) list.push(value);
}

function pushUniqueObject(list, value) {
  if (!value) return;
  const encoded = JSON.stringify(value);
  if (!list.some((item) => JSON.stringify(item) === encoded)) list.push(value);
}

function ensureSkillSuggestion(suggestions, skillId) {
  const key = skillId || 'unclassified';
  if (!suggestions.has(key)) {
    suggestions.set(key, {
      skill_id: key,
      suggested_colloquial_examples: [],
      suggested_anti_examples: [],
      suggested_when_to_use_notes: [],
      suggested_slot_extraction_hints: [],
      learning_event_suggestions: [],
      suggested_review_notes: [],
    });
  }
  return suggestions.get(key);
}

function inferSkillFromPendingTools(tools) {
  const toolList = Array.isArray(tools) ? tools : [];
  const mapping = {
    interview_create: 'interview.schedule_confirm_create',
    approval_decision: 'approval.confirm_action',
    notification_create: 'notification.create_confirm',
    employee_change_submit: 'employee.change_submit_confirm',
  };
  for (const tool of toolList) {
    const toolName = typeof tool === 'string' ? tool : (tool && tool.tool);
    if (mapping[toolName]) return mapping[toolName];
  }
  return null;
}

function addEvaluationCase(evaluationCases, payload) {
  if (!payload.user_text) return;
  evaluationCases.push({
    id: `skill_first_regression_${evaluationCases.length + 1}`,
    ...payload,
    review_required: true,
  });
}

function reviewEvidence(sample) {
  return {
    request_id: sample.request_id || null,
    top_k_skills: Array.isArray(sample.top_k_skills) ? sample.top_k_skills.slice(0, 8) : [],
    candidate_scores: Array.isArray(sample.candidate_scores) ? sample.candidate_scores.slice(0, 8) : [],
    matched_examples: sample.matched_examples && typeof sample.matched_examples === 'object'
      ? sample.matched_examples
      : {},
    rejected_skills: Array.isArray(sample.rejected_skills) ? sample.rejected_skills.slice(0, 8) : [],
    fallback_reason: sample.fallback_reason || null,
    permission_result: sample.permission_result || null,
    risk_result: sample.risk_result || null,
    confirmation_policy: sample.confirmation_policy || null,
    output_verification_result: sample.output_verification_result || null,
    final_executor: sample.final_executor || null,
    planner_source: sample.planner_source || null,
  };
}

function buildLearningEventSuggestions(sample, suggestions, evaluationCases) {
  const learningEvents = Array.isArray(sample.learning_events) ? sample.learning_events : [];
  const output = [];
  for (const event of learningEvents) {
    if (!event || typeof event !== 'object') continue;
    const kind = event.kind || sample.kind;
    const userText = sample.user_text;
    if (
      (kind === 'user_correction' || kind === 'clarification_changed_selection')
      && event.previous_selected_skill
      && event.current_selected_skill
    ) {
      const current = ensureSkillSuggestion(suggestions, event.current_selected_skill);
      const previous = ensureSkillSuggestion(suggestions, event.previous_selected_skill);
      pushUnique(current.suggested_colloquial_examples, userText);
      pushUnique(previous.suggested_anti_examples, userText);
      const learningSuggestion = {
        kind,
        request_id: sample.request_id,
        user_text: userText,
        previous_selected_skill: event.previous_selected_skill,
        current_selected_skill: event.current_selected_skill,
        previous_request_id: event.previous_request_id || null,
        review_required: true,
      };
      pushUniqueObject(current.learning_event_suggestions, {
        ...learningSuggestion,
        target_field: 'colloquial_examples',
      });
      pushUniqueObject(previous.learning_event_suggestions, {
        ...learningSuggestion,
        target_field: 'anti_examples',
      });
      output.push({
        ...learningSuggestion,
        suggested_patches: [
          {
            skill_id: event.current_selected_skill,
            field: 'colloquial_examples',
            value: userText,
          },
          {
            skill_id: event.previous_selected_skill,
            field: 'anti_examples',
            value: userText,
          },
        ],
        source_event: event,
      });
      addEvaluationCase(evaluationCases, {
        user_text: userText,
        expected_skill: event.current_selected_skill,
        source: 'skill_first_learning_event',
        learning_event_kind: kind,
        previous_selected_skill: event.previous_selected_skill,
        previous_request_id: event.previous_request_id || null,
        request_id: sample.request_id,
        source_event: event,
        review_evidence: reviewEvidence(sample),
      });
      continue;
    }

    if (kind === 'confirmation_cancelled') {
      const skillId = (
        inferSkillFromPendingTools(event.pending_action_tools)
        || event.current_selected_skill
        || event.previous_selected_skill
        || sample.selected_skill
        || 'unclassified'
      );
      const suggestion = ensureSkillSuggestion(suggestions, skillId);
      const reviewNote = `Review confirmation friction: user cancelled pending action for ${skillId}.`;
      pushUnique(suggestion.suggested_review_notes, reviewNote);
      const learningSuggestion = {
        kind,
        request_id: sample.request_id,
        user_text: userText,
        selected_skill: skillId,
        resolved_action_id: event.resolved_action_id || null,
        action_verb: event.action_verb || null,
        pending_action_label: event.pending_action_label || null,
        pending_action_tools: Array.isArray(event.pending_action_tools) ? event.pending_action_tools : [],
        review_required: true,
      };
      pushUniqueObject(suggestion.learning_event_suggestions, learningSuggestion);
      output.push({
        ...learningSuggestion,
        suggested_review_notes: [
          reviewNote,
          'Check whether the pending confirmation copy, risk explanation, missing evidence, or action granularity caused cancellation.',
        ],
        source_event: event,
      });
      addEvaluationCase(evaluationCases, {
        user_text: userText,
        expected_skill: skillId === 'unclassified' ? null : skillId,
        source: 'skill_first_learning_event',
        learning_event_kind: kind,
        request_id: sample.request_id,
        cancelled_action_id: event.resolved_action_id || null,
        source_event: event,
        review_evidence: reviewEvidence(sample),
      });
    }
  }
  return output;
}

function buildPatch(samples) {
  const grouped = new Map();
  for (const sample of samples) {
    if (sample.kind === 'confirmation_cancelled' || sample.selected_skill === 'execute_pending_action') {
      continue;
    }
    const key = sample.selected_skill || topCandidates(sample)[0] || 'unclassified';
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(sample);
  }

  const suggestions = new Map();
  const evaluationCases = [];
  for (const [skillId, items] of grouped.entries()) {
    const suggestion = ensureSkillSuggestion(suggestions, skillId);
    const examples = Array.from(new Set(items.map((item) => item.user_text).filter(Boolean))).slice(0, 20);
    const fallbackReasons = Array.from(new Set(items.map((item) => item.fallback_reason).filter(Boolean))).slice(0, 10);
    const antiExamples = items
      .filter((item) => item.selected_skill && item.fallback_reason === 'permission_denied')
      .map((item) => item.user_text)
      .filter(Boolean);
    for (const example of examples) {
      pushUnique(suggestion.suggested_colloquial_examples, example);
    }
    for (const antiExample of antiExamples) {
      pushUnique(suggestion.suggested_anti_examples, antiExample);
    }
    for (const reason of fallbackReasons) {
      pushUnique(suggestion.suggested_when_to_use_notes, `Review failure reason: ${reason}`);
    }
    for (const item of items.filter((entry) => entry.slot_fill_result).slice(0, 5)) {
      pushUniqueObject(suggestion.suggested_slot_extraction_hints, {
          user_text: item.user_text,
          observed_slot_fill_result: item.slot_fill_result,
          review_evidence: reviewEvidence(item),
      });
    }
    for (const text of examples) {
      const sourceSample = items.find((item) => item.user_text === text) || {};
      addEvaluationCase(evaluationCases, {
        user_text: text,
        expected_skill: skillId === 'unclassified' ? null : skillId,
        source: 'skill_first_failure_sample',
        request_id: sourceSample.request_id || null,
        review_evidence: reviewEvidence(sourceSample),
      });
    }
  }

  const learningEventSuggestions = [];
  for (const sample of samples) {
    learningEventSuggestions.push(...buildLearningEventSuggestions(sample, suggestions, evaluationCases));
  }

  const skillCardSuggestions = Array.from(suggestions.values()).map((suggestion) => ({
    ...suggestion,
    suggested_colloquial_examples: suggestion.suggested_colloquial_examples.slice(0, 20),
    suggested_anti_examples: suggestion.suggested_anti_examples.slice(0, 20),
    suggested_when_to_use_notes: suggestion.suggested_when_to_use_notes.slice(0, 20),
    suggested_slot_extraction_hints: suggestion.suggested_slot_extraction_hints.slice(0, 10),
    learning_event_suggestions: suggestion.learning_event_suggestions.slice(0, 20),
    suggested_review_notes: suggestion.suggested_review_notes.slice(0, 20),
  }));

  return {
    schema_version: 'skill-first.eval-patch.v1',
    generated_at: new Date().toISOString(),
    source: inputPath,
    sample_count: samples.length,
    production_mutation_policy: 'never_auto_mutate_skill_cards_or_routing',
    reference_project_mechanisms: referenceProjectMechanisms,
    workflow: [
      'automatic collection',
      'automatic suggestion generation',
      'human review and merge',
      'automatic regression verification',
    ],
    human_review_checklist: humanReviewChecklist,
    regression_verification_commands: regressionVerificationCommands,
    skill_card_suggestions: skillCardSuggestions,
    learning_event_suggestions: learningEventSuggestions,
    evaluation_cases: evaluationCases,
  };
}

const samples = readSamples(inputPath);
const patch = buildPatch(samples);
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(patch, null, 2), 'utf8');
console.log(JSON.stringify({
  ok: true,
  inputPath,
  outputPath,
  sampleCount: samples.length,
  suggestionCount: patch.skill_card_suggestions.length,
  evalCaseCount: patch.evaluation_cases.length,
}, null, 2));
