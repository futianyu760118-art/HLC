"""任务模板加载与查询。

YAML 配置 → TaskTemplate 对象。如果未安装 PyYAML，使用内置 fallback 解析器（仅支持本项目结构）。

模块级别还提供了一个轻量的 ``reload_registry()`` 监听器机制，用于让其它子系统
（如 ``intent_router.RetrievalIndex``）在任务表刷新后同步重建自己的衍生状态。
监听器通过 :func:`register_reload_listener` 注册；任一监听器抛错都会被吞掉，
不会影响 :func:`reload_registry` 自身的成功状态，也不会影响其它监听器的执行。
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Dict, List, Optional

from .schemas import TaskTemplate, WorkflowStep

logger = logging.getLogger('hengpintong.assistant.task_registry')

YAML_FILE = os.path.join(os.path.dirname(__file__), 'task_templates.yaml')

_TASK_REGISTRY: Dict[str, TaskTemplate] = {}

#: reload 完成后会按注册顺序回调；每个回调无参（监听器自己绑定到 task_registry
#: 模块即可）。重复注册同一个 callable 会被去重，避免 import 多次后被重复回调。
_RELOAD_LISTENERS: List[Callable[[], None]] = []


def _load_yaml(path: str) -> Dict:
    """加载 YAML，优先用 PyYAML，没有则用 json 兼容回退。"""
    try:
        import yaml  # noqa
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        logger.warning('pyyaml_not_installed_using_fallback')
        # 简易回退：用纯 Python 解析子集
        return _yaml_fallback_parse(path)
    except Exception:
        logger.exception('task_yaml_load_failed')
        return {}


def _yaml_fallback_parse(path: str) -> Dict:
    """极简 YAML 解析（只支持本项目用到的结构）。
    出于稳健考虑，建议安装 PyYAML：pip install pyyaml
    """
    # 这里只导入并失败时清晰报错，因为现在生产环境一般都有 PyYAML
    # 如果实在没装也不阻塞——返回空 dict，task_registry 会在外层 fallback 到内置任务
    return {}


def _build_workflow_step(d: Dict) -> WorkflowStep:
    return WorkflowStep(
        id=d.get('id', ''),
        type=d.get('type', 'skill'),
        skill=d.get('skill'),
        input_map=d.get('input_map') or {},
        output_key=d.get('output_key', 'output'),
        required=bool(d.get('required', False)),
        on_error=d.get('on_error', 'continue'),
        description=d.get('description', ''),
        llm_purpose=d.get('llm_purpose'),
    )


def _build_task(d: Dict) -> Optional[TaskTemplate]:
    if not d.get('id'):
        return None
    return TaskTemplate(
        id=d['id'],
        name=d.get('name', d['id']),
        description=d.get('description', ''),
        trigger_examples=d.get('trigger_examples') or [],
        required_entities=d.get('required_entities') or [],
        optional_entities=d.get('optional_entities') or {},
        allowed_roles=d.get('allowed_roles') or [],
        risk_level=d.get('risk_level', 'low'),
        candidate_skills=d.get('candidate_skills') or [],
        workflow=[_build_workflow_step(s) for s in (d.get('workflow') or [])],
        output_widgets=d.get('output_widgets') or [],
        fallback_task=d.get('fallback_task'),
        requires_confirmation=bool(d.get('requires_confirmation', False)),
        keywords=d.get('keywords') or [],
        type=d.get('type', 'workflow'),
        route_track=d.get('route_track', 'A_DATA_ACTION'),
        generation=d.get('generation') or {},
    )


def _builtin_tasks() -> List[Dict]:
    """PyYAML 不可用时的最小内置任务（保证基础能力）。"""
    return [
        {
            'id': 'global_search_answer',
            'name': '全局搜索',
            'description': '兜底搜索',
            'trigger_examples': ['查一下', '找一下'],
            'required_entities': ['keyword'],
            'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'manager', 'employee',
                              'finance', 'executive', 'viewer'],
            'risk_level': 'low',
            'candidate_skills': ['global_search'],
            'workflow': [
                {'id': 'search', 'type': 'skill', 'skill': 'global_search',
                 'input_map': {'keyword': 'entities.keyword'}, 'output_key': 'result',
                 'required': True, 'on_error': 'continue'},
                {'id': 'summarize', 'type': 'llm', 'llm_purpose': 'summarizer',
                 'input_map': {'facts': 'state.result'}, 'output_key': 'summary',
                 'required': False, 'on_error': 'continue'},
            ],
            'output_widgets': ['entity_cards'],
        },
        {
            'id': 'system_dashboard',
            'name': '系统总览',
            'description': '系统总览',
            'trigger_examples': ['系统概览', '总览'],
            'allowed_roles': ['admin', 'hr_admin', 'executive', 'manager', 'recruiter',
                              'finance', 'viewer', 'employee'],
            'risk_level': 'low',
            'candidate_skills': ['dashboard_report'],
            'workflow': [
                {'id': 'dashboard', 'type': 'skill', 'skill': 'dashboard_report',
                 'input_map': {'scope': 'static:system'}, 'output_key': 'dashboard',
                 'required': True, 'on_error': 'continue'},
            ],
            'output_widgets': ['metric_cards'],
            'keywords': ['系统概览', '总览'],
        },
        {
            'id': 'forbidden_action_response',
            'name': '高风险动作拦截',
            'description': '高风险拒绝',
            'allowed_roles': ['admin', 'hr_admin', 'recruiter', 'manager', 'employee',
                              'finance', 'executive', 'viewer'],
            'risk_level': 'high',
            'requires_confirmation': True,
            'candidate_skills': [],
            'workflow': [],
            'output_widgets': ['warning'],
        },
    ]


def reload_registry() -> None:
    """从 YAML 重新加载所有任务到 registry。

    完成后按注册顺序回调 :func:`register_reload_listener` 注册的监听器；
    单个监听器抛错会被记录为异常日志但不会传播，避免一个监听器把整个
    reload 流程拖垮。
    """
    _TASK_REGISTRY.clear()
    data = _load_yaml(YAML_FILE)
    items = (data.get('tasks') or []) if isinstance(data, dict) else []
    if not items:
        logger.warning('task_yaml_empty_using_builtin')
        items = _builtin_tasks()
    for item in items:
        try:
            t = _build_task(item)
            if t:
                _TASK_REGISTRY[t.id] = t
        except Exception:
            logger.exception('task_build_failed', extra={'id': item.get('id')})
    logger.info('task_registry_loaded', extra={'count': len(_TASK_REGISTRY)})

    # 通知监听器（如 RetrievalIndex.reload）。
    # 拷贝一份避免监听器回调里调 register/unregister 时改动迭代中的列表。
    for listener in list(_RELOAD_LISTENERS):
        try:
            listener()
        except Exception:
            logger.exception(
                'task_registry_reload_listener_failed',
                extra={'listener': repr(listener)},
            )


def register_reload_listener(fn: Callable[[], None]) -> None:
    """注册一个 reload 完成后的回调（无参）。

    重复注册同一个 callable 会被去重；线程安全性与 ``reload_registry`` 一致：
    本模块没有显式锁，所有调用方应当在启动期或同一线程内串行注册。
    """
    if not callable(fn):
        raise TypeError('register_reload_listener expects a callable')
    if fn in _RELOAD_LISTENERS:
        return
    _RELOAD_LISTENERS.append(fn)


def unregister_reload_listener(fn: Callable[[], None]) -> None:
    """从监听器列表移除 ``fn``；不在列表里时静默忽略。"""
    try:
        _RELOAD_LISTENERS.remove(fn)
    except ValueError:
        pass


def _list_reload_listeners() -> List[Callable[[], None]]:
    """供测试观察当前监听器列表的拷贝；不要在生产路径调用。"""
    return list(_RELOAD_LISTENERS)


# 启动时加载（注意：此时还没有任何监听器注册过，所以不会回调）
reload_registry()


def get(task_id: str) -> Optional[TaskTemplate]:
    return _TASK_REGISTRY.get(task_id)


def all_tasks() -> List[TaskTemplate]:
    return list(_TASK_REGISTRY.values())


def list_brief(role: Optional[str] = None) -> List[Dict]:
    """给 Router 看的精简列表。可按角色过滤。"""
    out = []
    for t in _TASK_REGISTRY.values():
        if role and t.allowed_roles and role not in t.allowed_roles:
            continue
        out.append({
            'id': t.id,
            'name': t.name,
            'description': t.description,
            'trigger_examples': t.trigger_examples[:3],
            'risk_level': t.risk_level,
        })
    return out


def exists(task_id: str) -> bool:
    return task_id in _TASK_REGISTRY
