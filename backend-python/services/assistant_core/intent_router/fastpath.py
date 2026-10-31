"""FastPath：高风险域关键词直通 + 写意图直通。

只承担两件事：

1. 写动作直通：消息命中 :func:`guardrails.detect_write_intent` 时，立刻返回
   ``forbidden_action_response``，跳过 Retriever / Reranker / EntityMemory。
2. 高风险域关键词直通：消息命中外部 yaml 中登记的薪酬域关键词时，直接返回
   对应路由结果，跳过 Retriever / Reranker。

设计原则与边界：

- 关键词集合通过 *外部* yaml 配置维护（默认：本模块同目录下的
  ``fastpath_keywords.yaml``），运行时变更不需要改 ``router.py`` 源码；
  路径可由环境变量 ``ASSISTANT_INTENT_ROUTER_FASTPATH_KEYWORDS_PATH`` 覆盖。
- 启动加载 + ``mtime`` 监听做 *热加载*：每次 :meth:`FastPath.match` 调用都会
  做一次 ``os.path.getmtime`` 检查；mtime 变化时在 ``threading.Lock`` 下重新
  解析 yaml，保证并发请求看到一致快照。
- *不* 与 ``task_registry`` / ``skill_registry`` 耦合；FastPath 命中产生的
  ``RouterResult`` 仍然要经过上层 ``PermissionGate`` 校验。
- 自检：加载时若发现 yaml 中存在中等 / 低风险域条目，立即抛 ``ValueError``，
  避免静默扩大快速通道的覆盖面。``task_template_id`` 仅允许：
  - 精确等于 ``forbidden_action_response``，或
  - 以 ``payroll_`` 为前缀。

Validates: Requirements 2.1, 2.2, 2.3, 2.4
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from config import IntentRouterConfig

from ..constants import RISK_HIGH
from ..guardrails import detect_write_intent
from ..schemas import AssistantContext, RouterResult

logger = logging.getLogger('hengpintong.assistant.intent_router.fastpath')


#: 环境变量名：自定义 fastpath yaml 路径（在 ``config.IntentRouterConfig`` 集中登记）。
ENV_FASTPATH_KEYWORDS_PATH = IntentRouterConfig.ENV_FASTPATH_KEYWORDS_PATH

#: 默认 yaml 路径：本模块同目录下的 ``fastpath_keywords.yaml``。
_DEFAULT_KEYWORDS_PATH = str(
    Path(__file__).resolve().parent
    / IntentRouterConfig.DEFAULT_FASTPATH_KEYWORDS_FILENAME,
)

#: yaml 中允许的 ``task_template_id``（精确名白名单）。
_ALLOWED_EXACT_TASK_IDS = frozenset({'forbidden_action_response'})

#: yaml 中允许的 ``task_template_id`` 前缀（仅高风险薪酬域）。
_ALLOWED_TASK_ID_PREFIXES: Tuple[str, ...] = ('payroll_',)


# ---------------------------------------------------------------------------
# 内部数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DomainEntry:
    """yaml 中单个高风险域配置的内存表示。"""

    domain: str
    keywords: Tuple[str, ...]
    task_template_id: str
    candidate_skills: Tuple[str, ...]
    risk_level: str


def _is_allowed_task_id(task_id: str) -> bool:
    """``task_id`` 是否在 FastPath 白名单中。"""
    if task_id in _ALLOWED_EXACT_TASK_IDS:
        return True
    return any(task_id.startswith(prefix) for prefix in _ALLOWED_TASK_ID_PREFIXES)


# ---------------------------------------------------------------------------
# FastPath 主体
# ---------------------------------------------------------------------------


class FastPath:
    """读取外部 yaml + 运行时热加载 + ``match()`` 接口。

    线程安全：``_load()`` 与 ``match()`` 通过 ``self._lock`` 串行化对内部
    状态（``_entries`` / ``_mtime``）的写入；并发读取在重新加载完成后看到
    的是一致的快照。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        """初始化并立刻加载 yaml。

        Args:
            path: 显式覆盖 yaml 路径；为 ``None`` 时按 ``ENV → 默认值`` 顺序解析。

        Raises:
            FileNotFoundError: yaml 文件不存在。
            ValueError: yaml 结构非法或包含未授权的 ``task_template_id``。
        """
        resolved = (
            path
            or os.environ.get(ENV_FASTPATH_KEYWORDS_PATH)
            or _DEFAULT_KEYWORDS_PATH
        )
        self._path = str(resolved)
        self._lock = threading.Lock()
        self._entries: List[_DomainEntry] = []
        self._mtime: float = 0.0
        # 启动期立刻加载并校验；任何错误都直接向上抛，避免“静默通过”。
        self._load()

    # -- 公开属性 ---------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def entries(self) -> Tuple[_DomainEntry, ...]:
        """当前已加载的域条目快照（只读）。"""
        return tuple(self._entries)

    # -- 加载 / 热加载 ----------------------------------------------------

    def _load(self) -> None:
        """同步加载并校验 yaml。失败时抛错，状态不变。"""
        path = Path(self._path)
        if not path.exists():
            raise FileNotFoundError(
                f'fastpath keywords yaml not found: {self._path}'
            )
        with open(path, 'r', encoding='utf-8') as fp:
            raw = yaml.safe_load(fp)
        # 空 yaml 也视为合法（没有任何 fastpath 关键词）。
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(
                f'fastpath yaml root must be a mapping, got '
                f'{type(raw).__name__}'
            )

        entries: List[_DomainEntry] = []
        for domain, cfg in raw.items():
            entries.append(self._validate_entry(str(domain), cfg))

        self._entries = entries
        self._mtime = path.stat().st_mtime

    @staticmethod
    def _validate_entry(domain: str, cfg: object) -> _DomainEntry:
        """校验单条 yaml 域配置；不通过则抛 ``ValueError``。"""
        if not isinstance(cfg, dict):
            raise ValueError(
                f'fastpath domain {domain!r} must be a mapping, got '
                f'{type(cfg).__name__}'
            )

        task_id = cfg.get('task_template_id')
        keywords = cfg.get('keywords') or []
        candidate_skills = cfg.get('candidate_skills') or []
        risk_level = cfg.get('risk_level', RISK_HIGH)

        if not isinstance(task_id, str) or not task_id:
            raise ValueError(
                f'fastpath entry {domain!r} missing string task_template_id'
            )
        if not _is_allowed_task_id(task_id):
            raise ValueError(
                f'fastpath entry {domain!r} disallowed task_template_id='
                f'{task_id!r}; only {sorted(_ALLOWED_EXACT_TASK_IDS)!r} or '
                f'prefixes {list(_ALLOWED_TASK_ID_PREFIXES)!r} are allowed '
                'in fastpath'
            )
        if risk_level != RISK_HIGH:
            raise ValueError(
                f'fastpath entry {domain!r} must declare risk_level='
                f'{RISK_HIGH!r}, got {risk_level!r}'
            )
        if not isinstance(keywords, list) or not all(
            isinstance(k, str) and k for k in keywords
        ):
            raise ValueError(
                f'fastpath entry {domain!r} keywords must be a non-empty '
                'list of strings'
            )
        if not isinstance(candidate_skills, list) or not all(
            isinstance(s, str) for s in candidate_skills
        ):
            raise ValueError(
                f'fastpath entry {domain!r} candidate_skills must be a list '
                'of strings'
            )

        return _DomainEntry(
            domain=domain,
            keywords=tuple(keywords),
            task_template_id=task_id,
            candidate_skills=tuple(candidate_skills),
            risk_level=risk_level,
        )

    def reload(self) -> None:
        """显式重新加载（线程安全）。"""
        with self._lock:
            self._load()

    def _maybe_reload(self) -> None:
        """检查文件 mtime；如有变化则在锁下重新加载。

        快速路径：mtime 与缓存一致时不取锁，零额外开销。
        慢速路径：mtime 变化时取锁、再次确认 mtime（防止竞态）后重新加载。
        重新加载抛出的异常会向上传播，避免在脏配置下继续服务。
        """
        try:
            current_mtime = os.path.getmtime(self._path)
        except OSError as exc:
            logger.warning('fastpath_mtime_unavailable: %s', exc)
            return
        if current_mtime == self._mtime:
            return
        with self._lock:
            try:
                latest_mtime = os.path.getmtime(self._path)
            except OSError as exc:
                logger.warning('fastpath_mtime_unavailable: %s', exc)
                return
            if latest_mtime != self._mtime:
                self._load()

    # -- 主入口 -----------------------------------------------------------

    def match(
        self, message: str, ctx: Optional[AssistantContext] = None,
    ) -> Optional[RouterResult]:
        """尝试用快速通道路由 ``message``。

        优先级：写动作直通 > 高风险域关键词命中 > 未命中（``None``）。

        Args:
            message: 用户原始消息。
            ctx: ``AssistantContext``；FastPath 当前不依赖 ctx 字段，但保留
                参数以便上层统一调用约定与未来扩展（按 ``ctx.role`` 调整提示
                等）。

        Returns:
            命中时返回 ``RouterResult``（``route_path='fast_path'``）；
            未命中或消息为空时返回 ``None``，由上层走 Retriever。
        """
        del ctx  # 当前未使用，保留参数签名以兼容上层调用方。
        self._maybe_reload()
        if not message:
            return None

        # 1) 写动作直通（最高优先级，绕过 yaml）。
        forbidden = detect_write_intent(message)
        if forbidden:
            return RouterResult(
                intent='forbidden_action',
                task_template_id='forbidden_action_response',
                confidence=0.99,
                entities={'forbidden_reason': forbidden},
                missing_fields=[],
                risk_level=RISK_HIGH,
                candidate_skills=[],
                requires_confirmation=True,
                clarification_question=None,
                reason='fastpath:write_intent_detected',
                rule_matched=True,
                forbidden_reason=forbidden,
                route_path='fast_path',
            )

        # 2) 高风险域关键词命中（按 yaml 中的声明顺序）。
        text_lower = message.lower()
        for entry in self._entries:
            # ``forbidden_action_response`` 通过 detect_write_intent 处理，
            # 不参与关键词匹配（即使 yaml 误配也不会误伤）。
            if entry.task_template_id == 'forbidden_action_response':
                continue
            for kw in entry.keywords:
                if kw in message or kw.lower() in text_lower:
                    return RouterResult(
                        intent=entry.task_template_id,
                        task_template_id=entry.task_template_id,
                        confidence=0.95,
                        entities={'matched_keyword': kw},
                        missing_fields=[],
                        risk_level=entry.risk_level,
                        candidate_skills=list(entry.candidate_skills),
                        requires_confirmation=False,
                        clarification_question=None,
                        reason=f'fastpath:{entry.domain}:{kw}',
                        rule_matched=True,
                        forbidden_reason=None,
                        route_path='fast_path',
                    )

        return None


# ---------------------------------------------------------------------------
# 模块级单例 + 函数式包装
# ---------------------------------------------------------------------------


_default_fastpath: Optional[FastPath] = None
_default_lock = threading.Lock()


def _get_default() -> FastPath:
    """惰性构造模块级单例。"""
    global _default_fastpath
    if _default_fastpath is None:
        with _default_lock:
            if _default_fastpath is None:
                _default_fastpath = FastPath()
    return _default_fastpath


def match(
    message: str, ctx: Optional[AssistantContext] = None,
) -> Optional[RouterResult]:
    """模块级 ``match`` 包装（使用默认单例）。"""
    return _get_default().match(message, ctx)


def reload() -> None:
    """重置默认单例：下一次 ``match`` 会重新读取 env / yaml。

    显式 ``reload()`` 与 ``match()`` 内部的 mtime 热加载是两条独立通道：
    本函数主要用于环境变量切换或测试隔离场景。
    """
    global _default_fastpath
    with _default_lock:
        _default_fastpath = None


__all__ = [
    'ENV_FASTPATH_KEYWORDS_PATH',
    'FastPath',
    'match',
    'reload',
]
