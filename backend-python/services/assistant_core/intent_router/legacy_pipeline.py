"""IntentRouter v2 顶层流水线（Task 12）。

把前面任务里独立实现的子组件拼成一条完整的 ``route(message, ctx)``：

::

    FastPath.match
        ├── 命中 → PermissionGate.apply → ObservabilityRecorder
        └── 未命中
            EntityMemory.resolve(message, ctx)
            Retriever.retrieve
                ├── reason='embedding_unavailable' → legacy_adapter
                │   → route_path='legacy_fallback' → Observability
                └── 正常
                    Reranker.rerank
                    ConfidenceGate.evaluate
                    PermissionGate.apply
                    Observability

该模块还负责：

* 模块加载时构造单例 ``EmbeddingClient`` 包装、``RetrievalIndex`` 与
  ``Retriever``。
* 把 ``RetrievalIndex.reload(...)`` 注册到 ``task_registry`` 的 reload
  钩子，使 task_templates.yaml 热更新后索引自动重建。
* 索引懒构建：模块加载时**不**做嵌入调用，避免启动期阻塞；首次
  ``route()`` 调用前用 ``_ensure_index_built()`` 兜底。
* ``RouterResult.candidate_skills`` 在所有路径上都要 ``⊆ skill_registry``
  （防御深度过滤）；最终 ``task_template_id`` 必须 ``∈ task_registry``，
  否则强制改写为 ``global_search_answer``。
* 异常防御：所有内部组件抛错都被吞掉，最终返回 fallback ``RouterResult``，
  不向 orchestrator 抛错。

Validates: Requirements 1.1, 1.5, 1.7, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 7.1,
7.2, 12.4
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from typing import List, Optional, Tuple

import numpy as np

from .. import skill_registry, task_registry
from ..constants import RISK_LOW
from ..schemas import AssistantContext, RouterResult
from . import (
    confidence_gate,
    embedding_client,
    fastpath,
    function_calling,
    permission_gate,
    reranker,
)
from .entity_memory import EntityMemory, EntityStore, NamedEntity
from .observability import (
    FallbackSampleSink,
    ObservabilityRecorder,
    sha256_16,
)
from .retrieval_index import RetrievalIndex
from .retriever import REASON_EMBEDDING_UNAVAILABLE, Retriever


logger = logging.getLogger('hengpintong.assistant.intent_router.pipeline')


# ---------------------------------------------------------------------------
# Embedding facade
# ---------------------------------------------------------------------------


class _EmbeddingClientFacade:
    """把 :mod:`embedding_client` 模块函数包成对象方法。

    存在意义：
    1. 让 ``Retriever`` / ``RetrievalIndex`` 这些下游通过依赖注入引用，方便
       在测试里 monkeypatch 单例（``intent_router._embedding_client_facade``）。
    2. 把模块级的 ``embed_corpus`` LRU 缓存收敛到一处，调用方不需要直接
       import ``functools``。
    """

    def embed(self, text: str) -> Optional[np.ndarray]:
        """单条查询嵌入；返回 ``None`` 表示嵌入服务不可用。"""

        return embedding_client.embed(text)

    def embed_corpus(self, text: str) -> Optional[np.ndarray]:
        """稳定语料嵌入（带 LRU 缓存）。"""

        return embedding_client.embed_corpus(text)


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------


_embedding_client_facade = _EmbeddingClientFacade()
_retrieval_index = RetrievalIndex()
_retriever = Retriever(_embedding_client_facade, _retrieval_index)
_observer = ObservabilityRecorder()
_fallback_sink = FallbackSampleSink()

#: 索引懒构建只允许触发一次的锁；构建失败也会标记一次，避免反复触发缓慢嵌入。
_index_build_lock = threading.Lock()
_index_build_attempted = False


# ---------------------------------------------------------------------------
# In-memory entity store（由 pipeline 自己维护，避免触碰 DB）
# ---------------------------------------------------------------------------


class _DictEntityStore:
    """按 ``session_id`` 分桶的内存 EntityStore。

    设计取舍：任务 12 的范围里**不**接 DB，先用内存桶把 EntityMemory 挂起来；
    任务 14（executor 短路澄清）/任务 11 升级时再切到
    ``AssistantSession.messages.entity_memory`` 子键。Process 重启会丢失
    实体，这与用户感知一致（DB 持久化是任务 11 的扩展项）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict = {}

    def load(self, session_id: str) -> List[NamedEntity]:
        with self._lock:
            return [
                NamedEntity(**dataclasses.asdict(e))
                for e in self._buckets.get(session_id, ())
            ]

    def save(self, session_id: str, entities: List[NamedEntity]) -> None:
        with self._lock:
            self._buckets[session_id] = list(entities)


_entity_store: EntityStore = _DictEntityStore()
_entity_memory = EntityMemory(_entity_store)


# ---------------------------------------------------------------------------
# task_registry reload 钩子
# ---------------------------------------------------------------------------


def _on_task_registry_reload() -> None:
    """``task_registry.reload_registry()`` 完成后被调用。

    用当前 ``embedding_client_facade`` 重建索引；嵌入服务不可用时让索引保持
    空（``is_empty=True``），上层会回退到 LegacyRouter（Req 12.4）。
    """

    global _index_build_attempted
    try:
        _retrieval_index.reload(task_registry, _embedding_client_facade)
    except Exception:  # noqa: BLE001 - 索引重建失败不影响 task_registry 自己
        logger.exception('intent_router_index_reload_failed')
    finally:
        # 不论成功与否都视为已尝试构建，避免每次 route() 又触发一次重建。
        with _index_build_lock:
            _index_build_attempted = True


# 注册一次：每个进程一份。``register_reload_listener`` 内部会去重。
task_registry.register_reload_listener(_on_task_registry_reload)


def _ensure_index_built() -> None:
    """首次 ``route()`` 调用前的懒构建。

    模块加载时并不立刻 ``_retrieval_index.build(...)``，避免在启动路径触发
    嵌入调用阻塞测试与冷启动。第一次需要的时候才尝试构建：失败也记录一次，
    防止持续重试。
    """

    global _index_build_attempted
    if _index_build_attempted:
        return
    with _index_build_lock:
        if _index_build_attempted:
            return
        try:
            if _retrieval_index.is_empty():
                _retrieval_index.build(task_registry, _embedding_client_facade)
        except Exception:  # noqa: BLE001
            logger.exception('intent_router_index_lazy_build_failed')
        finally:
            _index_build_attempted = True


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _filter_skills_by_registry(skill_ids: List[str]) -> List[str]:
    """保序去重；保留存在于 ``skill_registry`` 中的 skill_id。

    防御深度：即使上游已经做过过滤，这里再过一遍可以防止 mock / 测试 / 误用
    的 candidate_skills 漏到下游。
    """

    seen: set = set()
    out: List[str] = []
    for sid in skill_ids or []:
        if not isinstance(sid, str) or sid in seen:
            continue
        if not skill_registry.exists(sid):
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _force_global_search(result: RouterResult) -> RouterResult:
    """强制改写为 ``global_search_answer``，供 task_id 不在 task_registry 时使用。

    保留 ``route_path``（不改），追加 ``intent_router:rewrote_unknown_task``
    到 ``reason``，``candidate_skills`` 至少包含 ``global_search``（在 skill
    registry 里）。``intent`` 同步置为 ``global_search``，避免下游误用。
    """

    base_reason = (result.reason or '').strip()
    note = 'intent_router:rewrote_unknown_task'
    new_reason = f'{base_reason} | {note}' if base_reason else note

    skills = _filter_skills_by_registry(result.candidate_skills or [])
    if not skills and skill_registry.exists('global_search'):
        skills = ['global_search']

    return dataclasses.replace(
        result,
        intent='global_search',
        task_template_id='global_search_answer',
        candidate_skills=skills,
        reason=new_reason,
    )


def _enforce_postconditions(result: RouterResult) -> RouterResult:
    """统一收尾：candidate_skills ⊆ skill_registry，task_id ∈ task_registry。

    例外：``forbidden_action_response`` / ``permission_denied_response`` 是
    pipeline 自身合成的终态响应（由 FastPath / PermissionGate 产出），即使
    没有在 ``task_templates.yaml`` 中显式声明也合法，不应被改写。
    """

    safe_skills = _filter_skills_by_registry(result.candidate_skills or [])
    if safe_skills != list(result.candidate_skills or []):
        result = dataclasses.replace(result, candidate_skills=safe_skills)

    task_id = result.task_template_id or ''
    if task_id in _SYNTHETIC_TASK_IDS:
        return result
    if not task_id or not task_registry.exists(task_id):
        # task_registry 中没有这个 id → 强制改写
        result = _force_global_search(result)

    return result


#: 合法但**不**在 ``task_registry`` 中的合成任务 id；由 pipeline 内部 / 闸门
#: 产出，不需要 yaml 显式声明就允许下游消费。
_SYNTHETIC_TASK_IDS = frozenset({
    'forbidden_action_response',
    'permission_denied_response',
    function_calling.DIRECT_SKILLS_TASK_ID,
})


def _build_fallback_router_result(
    *, route_path: str, reason: str,
) -> RouterResult:
    """异常路径下的兜底 RouterResult。"""

    skills = ['global_search'] if skill_registry.exists('global_search') else []
    return RouterResult(
        intent='global_search',
        task_template_id='global_search_answer',
        confidence=0.0,
        entities={},
        missing_fields=[],
        risk_level=RISK_LOW,
        candidate_skills=skills,
        requires_confirmation=False,
        clarification_question=None,
        reason=reason,
        rule_matched=False,
        forbidden_reason=None,
        route_path=route_path,
        top_k=[],
    )


def _record_observation(
    ctx: AssistantContext,
    message: str,
    result: RouterResult,
    entity_resolved_count: int,
    latency_ms: float,
) -> None:
    """统一调用 ObservabilityRecorder。

    所有失败都被吞掉，避免观测路径影响主请求；用户消息原文不进日志。
    """

    try:
        request_id = (getattr(ctx, 'request_id', None) or str(uuid.uuid4()))
        user_id_raw = getattr(ctx, 'user_id', '') or ''
        # 脱敏：日志里只有 user_id 的 sha256 前 16 位（Req 6.2）。
        user_id_hash = sha256_16(user_id_raw) if user_id_raw else 'anonymous'
        clarification_emitted = bool(result.clarification_options)
        message_hash = sha256_16(message or '')
        message_length = len(message or '')

        _observer.record(
            request_id=request_id,
            user_id=user_id_hash,
            route_path=result.route_path or 'unknown',
            top_k_scores=list(result.top_k or []),
            chosen_task_id=result.task_template_id or '',
            confidence=float(result.confidence),
            clarification_emitted=clarification_emitted,
            entity_resolved_count=int(entity_resolved_count),
            latency_ms=float(latency_ms),
            message_hash=message_hash,
            message_length=message_length,
        )
    except Exception:  # noqa: BLE001
        logger.exception('intent_router_observer_record_failed')


def _legacy_route(message: str, ctx: AssistantContext) -> RouterResult:
    """嵌入服务不可用时回退到显式 legacy router。

    旧关键词/LLM router 已迁入 ``services.assistant_core.legacy_router``。
    这里必须显式引用 legacy 文件，不能再通过 ``router.py`` 公共名字回到
    旧 route-file 主链路。
    """

    from .. import legacy_router as legacy_module  # 局部 import 避免循环依赖

    try:
        result = legacy_module.route(message, ctx)
    except Exception:  # noqa: BLE001 - 防御：legacy 内部异常也不能逃出
        logger.exception('intent_router_legacy_failed')
        return _build_fallback_router_result(
            route_path='legacy_fallback',
            reason='intent_router:legacy_exception',
        )
    if result is None:
        return _build_fallback_router_result(
            route_path='legacy_fallback',
            reason='intent_router:legacy_returned_none',
        )
    # 不论 legacy 标的是什么 route_path，统一改为 legacy_fallback。
    return dataclasses.replace(result, route_path='legacy_fallback')


# ---------------------------------------------------------------------------
# Fallback sample sink wiring (Task 15)
# ---------------------------------------------------------------------------


#: 触发 Fallback 采样的 ``route_path`` 集合。
#:
#: ``fallback`` —— ConfidenceGate 判定 confidence < low_threshold，或者
#: pipeline 内部异常兜底；``legacy_fallback`` —— 嵌入服务不可用走 LegacyRouter
#: 的 v2 内部 fallback；``legacy`` —— FeatureFlag 关闭时整体走 LegacyAdapter
#: 的对照采样路径。这三类样本都要进入离线分析管道。
_FALLBACK_ROUTE_PATHS = frozenset({'fallback', 'legacy_fallback', 'legacy'})


def _maybe_write_fallback_sample(
    message: str,
    ctx: AssistantContext,
    result: RouterResult,
) -> None:
    """若属于低置信度 / fallback / legacy 路径，写一条脱敏样本。

    采样规则（Req 11.1 / 11.2）：

    * ``RouterResult.route_path`` ∈ ``{'fallback', 'legacy_fallback',
      'legacy'}`` —— v2 内部兜底路径与 FeatureFlag 关闭时的对照样本。
    * ``RouterResult.confidence < low_threshold`` —— 即便上游闸门没把
      ``route_path`` 改写为 ``fallback``（例如 FastPath 命中后强制确认但
      置信度恰好低于阈值），仍记录一条便于事后训练。

    脱敏规则（Req 11.3）：

    * 只写 ``query_hash``（``sha256_16(message)``）、``role``、Top-K 的
      ``task_id`` / ``score`` 序列、最终 ``chosen_task_id`` 与 ``timestamp``。
    * 绝不写消息原文 / ``user_id`` / ``session_id`` / 实体值。

    防御深度（Req 11.4）：

    * 任何异常（取阈值 / 取字段 / sink.write 内部异常）都被吞掉，仅
      :func:`logging.Logger.warning` 一条诊断；FallbackSampleSink 自身已经
      做过一层 try/except，这里再加一道兜底，保证主路径不受影响。
    """

    try:
        # 1) 阈值：优先复用 confidence_gate 的当前生效值（与 evaluate 同口径），
        #    任何异常回落到默认 0.50，避免 sink 因配置故障而漏写。
        try:
            low_threshold, _high = confidence_gate.get_thresholds()
        except Exception:  # noqa: BLE001
            low_threshold = confidence_gate.DEFAULT_LOW_THRESHOLD

        # 2) 触发判定：路径命中或低置信度。
        route_path = (result.route_path or '').strip()
        try:
            confidence = float(result.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        triggered = (
            route_path in _FALLBACK_ROUTE_PATHS
            or confidence < float(low_threshold)
        )
        if not triggered:
            return

        # 3) 抽取 Top-K 的 task_ids 与 scores（保序，分别成两列）。
        top_k_task_ids: List[str] = []
        top_k_scores: List[float] = []
        for item in (result.top_k or ()):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    top_k_task_ids.append(str(item[0]))
                    top_k_scores.append(float(item[1]))
                except (TypeError, ValueError):
                    # 单条解析失败：跳过而不破坏整列；与 RouterResult.from_dict 同款语义。
                    continue

        role_raw = getattr(ctx, 'role', '') or ''
        role = str(role_raw)

        # 4) 写 sink；FallbackSampleSink.write 自己也会 try/except，这里再裹一层。
        _fallback_sink.write(
            query_hash=sha256_16(message or ''),
            role=role,
            top_k_task_ids=top_k_task_ids,
            top_k_scores=top_k_scores,
            chosen_task_id=result.task_template_id or '',
            timestamp=time.time(),
        )
    except Exception:  # noqa: BLE001
        # 主路径必须永远不感知 sink 的故障。
        logger.warning(
            'intent_router_fallback_sample_failed',
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def route(message: str, ctx: AssistantContext) -> RouterResult:
    """``IntentRouter`` v2 完整流水线。

    永不抛错：所有内部组件异常都被吞掉，最终返回兜底 ``RouterResult``。
    """

    start_perf = time.perf_counter()
    entity_resolved_count = 0
    result: Optional[RouterResult] = None

    try:
        _ensure_index_built()

        # 1) FastPath 直通：写动作 / 高风险薪酬域。
        try:
            fp_hit = fastpath.match(message, ctx)
        except Exception:  # noqa: BLE001
            logger.exception('intent_router_fastpath_failed')
            fp_hit = None

        if fp_hit is not None:
            try:
                gated = permission_gate.apply(fp_hit, ctx)
            except Exception:  # noqa: BLE001
                logger.exception('intent_router_permission_failed_fastpath')
                gated = fp_hit
            result = _enforce_postconditions(gated)
        else:
            # 2) EntityMemory 消解（不强依赖：失败 → 用原始 message）。
            resolved_query = message
            entity_trace: dict = {}
            session_id = getattr(ctx, 'session_id', None) or ''
            if session_id:
                try:
                    resolved_query, entity_trace = _entity_memory.resolve(
                        message, session_id, ctx,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception('intent_router_entity_memory_failed')
                    resolved_query = message
                    entity_trace = {}
            entity_resolved_count = len(
                entity_trace.get('pronouns_found', []) or []
            )

            # 3) Retriever 召回。
            try:
                candidates = _retriever.retrieve(resolved_query)
            except Exception:  # noqa: BLE001
                logger.exception('intent_router_retriever_failed')
                from .retriever import RetrievalCandidates
                candidates = RetrievalCandidates(items=[], reason='retrieval_failed')

            # 4) 嵌入服务不可用 → legacy_fallback。
            if candidates.reason == REASON_EMBEDDING_UNAVAILABLE:
                legacy_result = _legacy_route(message, ctx)
                # legacy 路径同样要做角色过滤 + task 校验。
                try:
                    legacy_gated = permission_gate.apply(legacy_result, ctx)
                except Exception:  # noqa: BLE001
                    logger.exception('intent_router_permission_failed_legacy')
                    legacy_gated = legacy_result
                # legacy_gated 可能被改写为 permission_denied_response，需要
                # 重新回退 route_path 为 legacy_fallback（PermissionGate 在
                # 拒绝路径上会保留入参 route_path，已经是 legacy_fallback）。
                result = _enforce_postconditions(legacy_gated)
                # 强制把 route_path 标为 legacy_fallback（防止 _force_global_search
                # 没改它，但 PermissionGate 已经把它降级）。
                if result.route_path != 'legacy_fallback':
                    result = dataclasses.replace(
                        result, route_path='legacy_fallback',
                    )
            else:
                # 5) Reranker 重排。
                try:
                    reranked = reranker.rerank(resolved_query, candidates, ctx)
                except Exception:  # noqa: BLE001
                    logger.exception('intent_router_reranker_failed')
                    reranked = _build_fallback_router_result(
                        route_path='fallback',
                        reason='intent_router:reranker_exception',
                    )

                # 把 entity_resolved trace 挂到 RouterResult 上，方便观测复盘。
                if entity_trace:
                    reranked = dataclasses.replace(
                        reranked, entity_resolved=dict(entity_trace),
                    )

                # 6) ConfidenceGate 二次着色。
                try:
                    after_gate = confidence_gate.evaluate(reranked, ctx)
                except Exception:  # noqa: BLE001
                    logger.exception('intent_router_confidence_failed')
                    after_gate = reranked

                # 6.5) Function Calling 兜底：embedding 路径未命中时，
                #      把可用 skill 列表交给 LLM 自主选择工具和参数。
                if after_gate.route_path == 'fallback':
                    try:
                        fc_result = function_calling.try_function_calling(
                            message, ctx,
                        )
                        if fc_result is not None:
                            after_gate = fc_result
                    except Exception:  # noqa: BLE001
                        logger.exception('intent_router_function_calling_failed')

                # 7) PermissionGate 收尾。
                try:
                    after_perm = permission_gate.apply(after_gate, ctx)
                except Exception:  # noqa: BLE001
                    logger.exception('intent_router_permission_failed_retrieval')
                    after_perm = after_gate

                result = _enforce_postconditions(after_perm)

    except Exception:  # noqa: BLE001 - 顶层防御，确保永不抛错给 orchestrator
        logger.exception('intent_router_route_failed')
        exc_type = 'unknown'
        try:
            import sys as _sys
            exc = _sys.exc_info()[0]
            exc_type = exc.__name__ if exc is not None else 'unknown'
        except Exception:
            pass
        result = _build_fallback_router_result(
            route_path='fallback',
            reason=f'intent_router:exception:{exc_type}',
        )

    if result is None:
        # 防御性路径：任何分支都没有给 result 赋值。
        result = _build_fallback_router_result(
            route_path='fallback',
            reason='intent_router:no_result',
        )

    latency_ms = (time.perf_counter() - start_perf) * 1000.0

    # 7.5) 实体记忆写入：把本轮路由结果中的实体存入 EntityMemory，
    #      供下一轮的代词消解使用（如 "他" → "朱亮"）。
    session_id = getattr(ctx, 'session_id', None) or ''
    if session_id and result.entities:
        try:
            import time as _time
            import re as _re
            new_entities = _entity_memory.extract(
                message or '',
                router_entities=result.entities,
                source_turn_index=int(_time.time()),
            )
            # 如果 keyword 看起来像中文人名（2-4 个汉字），同时存为 CANDIDATE
            kw = result.entities.get('keyword', '')
            if isinstance(kw, str) and _re.fullmatch(r'[\u4e00-\u9fa5·]{2,4}', kw):
                from .entity_memory import NamedEntity, CANDIDATE, ttl_minutes_for
                now_ts = _time.time()
                new_entities.append(NamedEntity(
                    type=CANDIDATE,
                    value=kw,
                    canonical_id=None,
                    source_turn_index=int(now_ts),
                    expires_at=now_ts + ttl_minutes_for(CANDIDATE) * 60.0,
                ))
            for ent in new_entities:
                _entity_memory.set(session_id, ent)
        except Exception:  # noqa: BLE001
            logger.exception('intent_router_entity_store_failed')

    # 8) 始终上报观测。
    _record_observation(
        ctx=ctx,
        message=message or '',
        result=result,
        entity_resolved_count=entity_resolved_count,
        latency_ms=latency_ms,
    )

    # 9) 离线对照采样：低置信度 / fallback / legacy_fallback 都要进 sink。
    #    所有异常已在 helper 内被吞掉；这里再加 try 是 *防御深度*，避免任何
    #    未来重构改动顺手把异常带出来阻塞主请求（Req 11.4）。
    try:
        _maybe_write_fallback_sample(message or '', ctx, result)
    except Exception:  # noqa: BLE001
        logger.warning(
            'intent_router_fallback_sample_outer_failed',
            exc_info=True,
        )

    return result


__all__ = [
    'route',
    '_ensure_index_built',
    '_on_task_registry_reload',
    '_EmbeddingClientFacade',
    '_maybe_write_fallback_sample',
]
