"""Widgets 构建器：把 skill 输出转成前端可渲染的结构化组件。

兼容现有 ChatRichWidgets.tsx 的类型：
- metric_cards / metrics
- bar_chart / bar
- doughnut_chart / donut
- data_table / table
- entity_cards
- warning（新增）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


MAX_TABLE_ROWS = 20


def metric_cards(cards: List[Dict[str, Any]], title: str = '') -> Dict[str, Any]:
    return {
        'type': 'metrics',
        'title': title or None,
        'metrics': [{
            'label': c.get('label', ''),
            'value': c.get('value', '-'),
            'unit': c.get('unit'),
            'color': c.get('color', 'blue'),
            'trend': c.get('trend'),
            'trendText': c.get('trendText') or c.get('hint') or c.get('delta'),
        } for c in cards if c],
    }


def bar_chart(data: List[Dict[str, Any]], title: str = '', max_items: int = 8) -> Dict[str, Any]:
    return {
        'type': 'bar',
        'title': title or None,
        'data': [{'label': d.get('label', ''), 'value': d.get('value', 0)} for d in (data or [])][:max_items],
    }


def doughnut_chart(data: List[Dict[str, Any]], title: str = '', center_label: str = '总数') -> Dict[str, Any]:
    return {
        'type': 'donut',
        'title': title or None,
        'centerLabel': center_label,
        'data': [{'label': d.get('label', ''), 'value': d.get('value', 0)} for d in (data or [])],
    }


def echarts(option: Dict[str, Any], title: str = '', chart_type: str = '') -> Dict[str, Any]:
    return {
        'type': 'echarts',
        'title': title or None,
        'chartType': chart_type or None,
        'option': option or {},
    }


def data_table(columns: List[Dict[str, Any]], rows: List[Dict[str, Any]],
               title: str = '', exportable: bool = True) -> Dict[str, Any]:
    truncated = len(rows) > MAX_TABLE_ROWS
    visible_rows = rows[:MAX_TABLE_ROWS]
    full_title = title
    if truncated:
        full_title = f'{title}（仅展示前 {MAX_TABLE_ROWS} 条，共 {len(rows)} 条）'
    return {
        'type': 'table',
        'table': {
            'title': full_title or None,
            'columns': columns,
            'rows': visible_rows,
            'exportable': exportable,
        },
    }


def entity_cards(entities: List[Dict[str, Any]], title: str = '相关结果') -> Dict[str, Any]:
    return {
        'type': 'entity_cards',
        'title': title or None,
        'entities': entities[:20],
    }


def warning(message: str, level: str = 'warning') -> Dict[str, Any]:
    if level not in ('info', 'warning', 'danger'):
        level = 'warning'
    return {
        'type': 'warning',
        'level': level,
        'message': message,
    }


def empty_state(message: str = '没有找到相关数据') -> Dict[str, Any]:
    return warning(message, level='info')


def confirmation_card(action: str, summary: str, action_id: Optional[str] = None) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []
    if action_id:
        actions = [
            {'label': '确认执行', 'payload': f'确认执行动作：{action_id}', 'variant': 'primary'},
            {'label': '取消', 'payload': f'取消动作：{action_id}', 'variant': 'secondary'},
        ]
    return {
        'type': 'confirmation_card',
        'title': action,
        'message': summary,
        'actionId': action_id,
        'actions': actions,
    }


def follow_up_actions(actions: List[Dict[str, Any]], title: str = '推荐下一步') -> Dict[str, Any]:
    safe_actions: List[Dict[str, Any]] = []
    for raw in (actions or [])[:6]:
        if not isinstance(raw, dict):
            continue
        label = raw.get('label') or raw.get('title')
        if not isinstance(label, str) or not label.strip():
            continue
        payload = raw.get('payload') or label
        item = {
            'label': label.strip(),
            'payload': str(payload).strip(),
            'variant': raw.get('variant') or 'secondary',
        }
        for key in ('description', 'icon', 'url', 'href', 'intent', 'requiresConfirmation'):
            value = raw.get(key)
            if value not in (None, '', []):
                item[key] = value
        safe_actions.append(item)
    return {
        'type': 'follow_up_actions',
        'title': title or '推荐下一步',
        'actions': safe_actions,
    }


def timeline(items: List[Dict[str, Any]], title: str = '') -> Dict[str, Any]:
    return {
        'type': 'timeline',
        'title': title or None,
        'items': [{
            'time': item.get('time') or item.get('date') or '',
            'title': item.get('title') or item.get('label') or '',
            'description': item.get('description') or item.get('content') or '',
            'status': item.get('status') or 'default',
            'icon': item.get('icon'),
            'url': item.get('url'),
        } for item in (items or [])[:20] if item],
    }


def comparison_matrix(columns: List[Dict[str, Any]], rows: List[Dict[str, Any]],
                      title: str = '') -> Dict[str, Any]:
    return {
        'type': 'comparison_matrix',
        'title': title or None,
        'columns': columns[:8],
        'rows': rows[:12],
    }


def status_badges(items: List[Dict[str, Any]], title: str = '') -> Dict[str, Any]:
    return {
        'type': 'status_badges',
        'title': title or None,
        'items': [{
            'label': item.get('label') or item.get('title') or '',
            'value': item.get('value'),
            'status': item.get('status') or item.get('level') or 'neutral',
            'icon': item.get('icon'),
            'hint': item.get('hint') or item.get('description'),
        } for item in (items or [])[:16] if item],
    }


def media_preview(items: List[Dict[str, Any]], title: str = '') -> Dict[str, Any]:
    return {
        'type': 'media_preview',
        'title': title or None,
        'items': [{
            'title': item.get('title') or item.get('name') or '',
            'url': item.get('url') or item.get('href') or '',
            'thumbnail': item.get('thumbnail') or item.get('thumb') or item.get('url') or '',
            'mimeType': item.get('mimeType') or item.get('type') or '',
            'description': item.get('description') or item.get('meta') or '',
        } for item in (items or [])[:8] if item],
    }


#: 澄清组件中可呈现的最大候选回复数量。超过会被截断。
MAX_CLARIFICATION_OPTIONS = 4


def clarification(question: str,
                  options: List[Dict[str, Any]],
                  origin_message: str) -> Dict[str, Any]:
    """构造澄清轮组件。

    与 Requirement 3.3 对齐：返回 ``{type:'clarification', question, options, origin_message}``。
    每个 option 形如 ``{label, payload}``；多余字段会被丢弃以避免泄漏内部状态。
    ``options`` 长度上限为 :data:`MAX_CLARIFICATION_OPTIONS` (=4)，超出部分截断。

    Args:
        question: 澄清问题，前端直接展示给用户。
        options: 候选回复列表；每项至少需要 ``label`` 字段，``payload``
            缺省时回退到 ``label``，方便上层最简调用。
        origin_message: 上一轮用户原始消息，下一轮路由会与回答合并。

    Returns:
        一个 dict，可直接放进 ``ExecutionResult.widgets`` 列表。
    """
    safe_options: List[Dict[str, Any]] = []
    for raw in (options or [])[:MAX_CLARIFICATION_OPTIONS]:
        if not isinstance(raw, dict):
            continue
        label = raw.get('label')
        if not isinstance(label, str) or not label:
            # 缺少可显示文本的项直接丢弃；不要让前端显示空按钮。
            continue
        payload = raw.get('payload', label)
        safe_options.append({'label': label, 'payload': payload})

    return {
        'type': 'clarification',
        'question': question or '',
        'options': safe_options,
        'origin_message': origin_message or '',
    }
