"""Copilot response contract helpers.

This layer keeps the legacy ``widgets`` contract working while exposing a
single HRM Copilot surface for plan, evidence, render blocks and controlled
actions. It is intentionally deterministic so failures can be attributed to
the pipeline instead of patched one prompt at a time.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .schemas import AssistantContext, ExecutionResult


RENDER_SCHEMA_VERSION = 'assistant.render.v1'

WIDGET_BLOCK_MAP = {
    'metrics': 'kpi',
    'metric_cards': 'kpi',
    'bar': 'chart',
    'bar_chart': 'chart',
    'donut': 'chart',
    'doughnut_chart': 'chart',
    'table': 'table',
    'data_table': 'table',
    'entity_cards': 'entity_cards',
    'warning': 'notice',
    'markdown': 'markdown',
    'workset_summary': 'workset',
    'confirmation_card': 'confirmation',
    'follow_up_actions': 'actions',
    'source_citations': 'sources',
    'mermaid_diagram': 'diagram',
    'echarts': 'chart',
    'clarification': 'clarification',
    'timeline': 'timeline',
    'comparison_matrix': 'matrix',
    'status_badges': 'status',
    'media_preview': 'media',
}


def apply_response_contract(
    result: ExecutionResult,
    ctx: AssistantContext,
    *,
    message: Optional[str] = None,
) -> ExecutionResult:
    """Attach Copilot v2 metadata and render blocks to an execution result."""
    if result.render_blocks and result.copilot:
        return result

    widgets = [w for w in (result.widgets or []) if isinstance(w, dict)]
    render_blocks = _build_render_blocks(result, widgets)
    result.render_blocks = render_blocks
    result.client_context = getattr(ctx, 'client_context', {}) or {}
    existing_copilot = dict(result.copilot or {})
    result.copilot = {
        **existing_copilot,
        'schema': RENDER_SCHEMA_VERSION,
        'mode': _infer_mode(result),
        'intent': result.router.intent if result.router else None,
        'confidence': result.router.confidence if result.router else None,
        'riskLevel': result.router.risk_level if result.router else 'low',
        'requiresConfirmation': bool(result.requires_confirmation),
        'taskType': result.route_decision.task_type if result.route_decision else None,
        'routeTrack': result.route_decision.route_track if result.route_decision else None,
        'currentContext': _compact_client_context(result.client_context),
        'plan': _build_plan(result),
        'evidence': _build_evidence(result, widgets),
        'actions': _normalize_actions(result, widgets),
        'evaluationHints': _build_evaluation_hints(result, widgets, message),
    }
    return result


def _build_render_blocks(
    result: ExecutionResult,
    widgets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    content = ''
    if isinstance(result.answer, dict):
        content = str(result.answer.get('content') or '').strip()
    if not content:
        content = str(result.summary or '').strip()
    if content:
        blocks.append({
            'id': 'answer',
            'kind': 'markdown',
            'title': '结论',
            'content': content,
            'source': 'answer',
        })
    if result.entities and not any(str(w.get('type')) == 'entity_cards' for w in widgets):
        entity_items = result.entities[:12]
        blocks.append({
            'id': 'entities',
            'kind': 'entity_cards',
            'widgetType': 'entity_cards',
            'title': '关联记录',
            'payload': {
                'type': 'entity_cards',
                'title': '关联记录',
                'items': entity_items,
                'entities': entity_items,
            },
            'source': 'entities',
        })
    for idx, widget in enumerate(widgets):
        widget_type = str(widget.get('type') or 'unknown')
        kind = WIDGET_BLOCK_MAP.get(widget_type, 'widget')
        blocks.append({
            'id': f'widget-{idx + 1}',
            'kind': kind,
            'widgetType': widget_type,
            'title': widget.get('title'),
            'payload': widget,
            'source': 'widget',
        })
    if result.worksets and not any(block.get('kind') == 'workset' for block in blocks):
        blocks.append({
            'id': 'worksets',
            'kind': 'workset',
            'widgetType': 'workset_summary',
            'title': '可继续追问的结果集',
            'payload': {
                'type': 'workset_summary',
                'title': '可继续追问的结果集',
                'worksets': result.worksets[:3],
            },
            'source': 'worksets',
        })
    for idx, action in enumerate(result.actions or []):
        if not isinstance(action, dict):
            continue
        blocks.append({
            'id': f'action-{idx + 1}',
            'kind': 'confirmation' if result.requires_confirmation else 'actions',
            'title': action.get('label') or action.get('title') or '待处理动作',
            'payload': action,
            'source': 'action',
        })
    evidence = _build_evidence(result, widgets)
    if evidence and not any(block.get('kind') == 'sources' for block in blocks):
        blocks.append({
            'id': 'sources',
            'kind': 'sources',
            'widgetType': 'source_citations',
            'title': '证据来源',
            'payload': {
                'type': 'source_citations',
                'title': '证据来源',
                'sources': evidence,
            },
            'source': 'evidence',
        })
    return blocks


def _infer_mode(result: ExecutionResult) -> str:
    if result.requires_confirmation:
        return 'confirm_action'
    if any((w or {}).get('type') == 'clarification' for w in result.widgets or []):
        return 'clarify'
    if result.entities:
        return 'grounded_answer'
    if result.widgets:
        return 'structured_answer'
    return 'plain_answer'


def _build_plan(result: ExecutionResult) -> List[Dict[str, Any]]:
    if result.trace:
        return [{
            'id': step.step_id,
            'label': step.skill or step.type,
            'type': step.type,
            'status': step.status,
            'rowsCount': step.rows_count,
            'durationMs': round(step.duration_ms, 1),
            'riskLevel': step.risk_level,
        } for step in result.trace]
    decision = result.route_decision
    if decision and decision.tool_plan:
        plan = []
        for idx, tool in enumerate(decision.tool_plan):
            label = getattr(tool, 'skill', None) or getattr(tool, 'tool', None) or tool.purpose
            plan.append({
                'id': f'tool-{idx + 1}',
                'label': label,
                'type': 'tool',
                'status': 'planned',
                'riskLevel': tool.risk_level,
            })
        return plan
    if decision:
        return [{
            'id': 'route',
            'label': decision.intent or decision.task_type or '识别任务',
            'type': 'route',
            'status': 'ok',
            'riskLevel': decision.risk_level,
        }]
    return []


def _build_evidence(
    result: ExecutionResult,
    widgets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for widget in widgets:
        if widget.get('type') != 'source_citations':
            continue
        raw_sources = widget.get('sources') or widget.get('data') or []
        if isinstance(raw_sources, list):
            sources.extend(s for s in raw_sources if isinstance(s, dict))
    if sources:
        return _dedupe_evidence(sources)

    for ent in result.entities or []:
        if not isinstance(ent, dict):
            continue
        sources.append({
            'module': ent.get('type'),
            'recordId': ent.get('id'),
            'title': ent.get('title'),
            'url': ent.get('url'),
        })
    return _dedupe_evidence(sources)


def _dedupe_evidence(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    evidence: List[Dict[str, Any]] = []
    for item in items:
        key = (
            item.get('module') or item.get('recordType') or item.get('type'),
            item.get('recordId') or item.get('id') or item.get('title'),
        )
        if key in seen:
            continue
        seen.add(key)
        evidence.append(item)
        if len(evidence) >= 20:
            break
    return evidence


def _normalize_actions(
    result: ExecutionResult,
    widgets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for action in result.actions or []:
        if isinstance(action, dict):
            actions.append({**action, 'requiresConfirmation': bool(result.requires_confirmation)})
    for widget in widgets:
        if widget.get('type') not in ('confirmation_card', 'follow_up_actions'):
            continue
        for action in widget.get('actions') or []:
            if isinstance(action, dict):
                actions.append({
                    **action,
                    'requiresConfirmation': (
                        widget.get('type') == 'confirmation_card'
                        or bool(action.get('requiresConfirmation'))
                    ),
                    'sourceWidget': widget.get('type'),
                })
    return actions[:12]


def _compact_client_context(client_context: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(client_context, dict):
        return {}
    return {
        'path': client_context.get('path') or client_context.get('route'),
        'moduleId': client_context.get('moduleId'),
        'moduleName': client_context.get('moduleName'),
        'pageTitle': client_context.get('pageTitle'),
        'visibleFilters': client_context.get('visibleFilters') or {},
        'selectedRecordIds': client_context.get('selectedRecordIds') or [],
    }


def _build_evaluation_hints(
    result: ExecutionResult,
    widgets: List[Dict[str, Any]],
    message: Optional[str],
) -> Dict[str, Any]:
    widget_types = [w.get('type') for w in widgets if isinstance(w, dict)]
    evidence_count = len(_build_evidence(result, widgets))
    failure_categories: List[str] = []
    expected_business_errors = {'permission_denied'}
    if result.error_code and result.error_code not in expected_business_errors:
        failure_categories.append('tool_calling')
    if result.fallback_used:
        failure_categories.append('intent_or_retrieval_fallback')
    if result.router and result.router.confidence < 0.55:
        failure_categories.append('intent_confidence')
    if result.requires_confirmation and not _normalize_actions(result, widgets):
        failure_categories.append('confirmation_contract')
    if result.entities and evidence_count == 0:
        failure_categories.append('evidence_linking')

    return {
        'question': (message or '')[:300],
        'widgetTypes': widget_types,
        'entityCount': len(result.entities or []),
        'evidenceCount': evidence_count,
        'fieldEvidenceCount': _field_evidence_count(widgets),
        'failureCategories': failure_categories,
        'needsRootCauseReview': bool(failure_categories),
    }


def _field_evidence_count(widgets: List[Dict[str, Any]]) -> int:
    total = 0
    for widget in widgets:
        if not isinstance(widget, dict) or widget.get('type') != 'source_citations':
            continue
        raw_sources = widget.get('sources') or widget.get('data') or []
        if not isinstance(raw_sources, list):
            continue
        for source in raw_sources:
            if isinstance(source, dict) and isinstance(source.get('fields'), list):
                total += len(source.get('fields') or [])
    return total
