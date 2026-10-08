"""助手核心数据结构（dataclass）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class AssistantContext:
    """单次请求的执行上下文。"""
    user_id: str
    role: str
    session_id: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    request_id: Optional[str] = None
    locale: str = 'zh-CN'
    user_name: Optional[str] = None
    user_department_id: Optional[str] = None
    user_employee_id: Optional[str] = None
    audit_user_id: Optional[str] = None
    audit_session_id: Optional[str] = None
    client_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterResult:
    """Router 输出的任务路由决策。

    字段集合保持向后兼容：所有 v2 新增字段都附带默认值，存量调用点
    无需感知。``to_dict`` 输出的是 v1 字段集合的**超集**（驼峰命名），
    ``from_dict`` 容忍未知键并对 ``confidence`` 做范围/类型清洗。
    """
    intent: str
    task_template_id: Optional[str]
    confidence: float
    entities: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[str] = field(default_factory=list)
    risk_level: str = 'low'
    candidate_skills: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    clarification_question: Optional[str] = None
    reason: str = ''
    rule_matched: bool = False  # 规则命中即不调 LLM
    forbidden_reason: Optional[str] = None  # 被 guardrail 拒绝时的原因

    # ---- v2 新增字段（默认值确保 v1 调用点零改造） ---------------------
    route_path: str = 'unknown'
    """路由分流标识：``fast_path`` / ``retrieval`` / ``clarification`` /
    ``fallback`` / ``legacy_fallback`` / ``legacy`` / ``unknown`` 等。"""

    top_k: List[Tuple[str, float]] = field(default_factory=list)
    """Retriever 召回的 Top-K 候选 ``(task_template_id, score)``，按相似度降序。"""

    clarification_options: List[Dict[str, Any]] = field(default_factory=list)
    """澄清组件的快捷回复列表，最多 4 项；每项形如 ``{label, payload}``。"""

    low_confidence_warning: bool = False
    """连续两轮低置信度时的强制 Top-1 标记，提醒下游 UI 提示用户。"""

    entity_resolved: Dict[str, Any] = field(default_factory=dict)
    """EntityMemory 把代词/省略消解为具体实体的映射结果，便于 trace 复盘。"""

    # ------------------------------------------------------------------
    # 规范化 / 序列化 / 反序列化
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        """规范化字段，使 ``from_dict(to_dict(r)) == r`` 在任意合法 r 上恒成立。

        - ``confidence`` 截断到 3 位小数，与 ``to_dict`` 输出口径一致；
          这样无论 r 来自构造、还是来自反序列化，比较都不会因浮点尾差失败。
        - ``top_k`` 元素一律统一成 ``(str, float)`` 的 tuple，避免调用方
          传入 list 与反序列化输出 tuple 之间出现 ``[] != ()`` 的尴尬。
        """
        try:
            self.confidence = round(float(self.confidence), 3)
        except (TypeError, ValueError):
            # 构造期不再抛错；落到 0.0 让上层显式处理（``from_dict`` 走清洗路径）。
            self.confidence = 0.0
        normalized: List[Tuple[str, float]] = []
        for item in self.top_k or []:
            if isinstance(item, tuple) and len(item) >= 2:
                normalized.append((str(item[0]), float(item[1])))
            elif isinstance(item, list) and len(item) >= 2:
                normalized.append((str(item[0]), float(item[1])))
        self.top_k = normalized

    def to_dict(self) -> Dict[str, Any]:
        """输出驼峰键的 dict；字段集合是 v1 的超集。"""
        return {
            # ---- v1 字段（保持原命名，老下游不感知 v2） ----
            'intent': self.intent,
            'taskTemplateId': self.task_template_id,
            'confidence': round(self.confidence, 3),
            'entities': self.entities,
            'missingFields': self.missing_fields,
            'riskLevel': self.risk_level,
            'candidateSkills': self.candidate_skills,
            'requiresConfirmation': self.requires_confirmation,
            'clarificationQuestion': self.clarification_question,
            'reason': self.reason,
            'ruleMatched': self.rule_matched,
            'forbiddenReason': self.forbidden_reason,
            # ---- v2 新增字段 ----
            'routePath': self.route_path,
            'topK': [[task_id, float(score)] for task_id, score in self.top_k],
            'clarificationOptions': list(self.clarification_options),
            'lowConfidenceWarning': self.low_confidence_warning,
            'entityResolved': dict(self.entity_resolved),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'RouterResult':
        """从 dict 反序列化为 ``RouterResult``。

        - 容忍未知键：不在字段表里的键被静默忽略，不抛异常。
        - 同时识别驼峰（``to_dict`` 的输出）与下划线（容错）。
        - ``confidence`` 不可解析为 ``[0, 1]`` 区间内的 float 时置为
          ``0.0``，并把原始字符串追加到 ``reason`` 末尾，满足 Req 9.5。
        """
        if not data:
            return cls(intent='', task_template_id=None, confidence=0.0)

        def pick(*keys: str, default: Any = None) -> Any:
            for k in keys:
                if k in data:
                    return data[k]
            return default

        # ---- confidence 清洗 ------------------------------------------------
        raw_conf = pick('confidence', default=None)
        base_reason = pick('reason', default='') or ''
        if not isinstance(base_reason, str):
            base_reason = str(base_reason)
        confidence, reason = _sanitize_confidence(raw_conf, base_reason)

        # ---- top_k 容错 -----------------------------------------------------
        raw_top_k = pick('topK', 'top_k', default=None)
        top_k: List[Tuple[str, float]] = []
        if isinstance(raw_top_k, list):
            for item in raw_top_k:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        top_k.append((str(item[0]), float(item[1])))
                    except (TypeError, ValueError):
                        # 单条解析失败：跳过而不是丢弃整个列表，最大化恢复有效信息
                        continue

        # ---- 集合 / 字典字段（拷贝以避免别名共享） ---------------------------
        entities = pick('entities', default=None)
        entities = dict(entities) if isinstance(entities, dict) else {}

        missing_fields = pick('missingFields', 'missing_fields', default=None)
        missing_fields = (
            [str(x) for x in missing_fields]
            if isinstance(missing_fields, list)
            else []
        )

        candidate_skills = pick('candidateSkills', 'candidate_skills', default=None)
        candidate_skills = (
            [str(x) for x in candidate_skills]
            if isinstance(candidate_skills, list)
            else []
        )

        clarification_options = pick(
            'clarificationOptions', 'clarification_options', default=None,
        )
        clarification_options = (
            [dict(o) for o in clarification_options if isinstance(o, dict)]
            if isinstance(clarification_options, list)
            else []
        )

        entity_resolved = pick('entityResolved', 'entity_resolved', default=None)
        entity_resolved = (
            dict(entity_resolved) if isinstance(entity_resolved, dict) else {}
        )

        # ---- 标量字段 -------------------------------------------------------
        intent = pick('intent', default='') or ''
        task_template_id = pick('taskTemplateId', 'task_template_id', default=None)
        risk_level = pick('riskLevel', 'risk_level', default='low') or 'low'
        clarification_question = pick(
            'clarificationQuestion', 'clarification_question', default=None,
        )
        rule_matched = bool(pick('ruleMatched', 'rule_matched', default=False))
        forbidden_reason = pick('forbiddenReason', 'forbidden_reason', default=None)
        route_path = pick('routePath', 'route_path', default='unknown') or 'unknown'
        low_confidence_warning = bool(pick(
            'lowConfidenceWarning', 'low_confidence_warning', default=False,
        ))
        requires_confirmation = bool(pick(
            'requiresConfirmation', 'requires_confirmation', default=False,
        ))

        return cls(
            intent=str(intent),
            task_template_id=task_template_id,
            confidence=confidence,
            entities=entities,
            missing_fields=missing_fields,
            risk_level=str(risk_level),
            candidate_skills=candidate_skills,
            requires_confirmation=requires_confirmation,
            clarification_question=clarification_question,
            reason=reason,
            rule_matched=rule_matched,
            forbidden_reason=forbidden_reason,
            route_path=str(route_path),
            top_k=top_k,
            clarification_options=clarification_options,
            low_confidence_warning=low_confidence_warning,
            entity_resolved=entity_resolved,
        )


def _sanitize_confidence(raw: Any, base_reason: str) -> Tuple[float, str]:
    """把任意输入清洗为 ``[0, 1]`` 内的 float。

    返回 ``(confidence, reason)``。当输入不可解析或越界时，
    ``confidence`` 置为 ``0.0`` 并把原始字符串拼到 ``reason`` 末尾。

    设计上不抛任何异常，便于在反序列化路径上无脑调用。
    """
    # bool 是 int 的子类，但语义上不应被当成置信度
    if isinstance(raw, bool):
        return _record_bad_conf(raw, base_reason)
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _record_bad_conf(raw, base_reason)
    # NaN / inf / 越界
    if value != value or value in (float('inf'), float('-inf')):
        return _record_bad_conf(raw, base_reason)
    if value < 0.0 or value > 1.0:
        return _record_bad_conf(raw, base_reason)
    return value, base_reason


def _record_bad_conf(raw: Any, base_reason: str) -> Tuple[float, str]:
    note = f'invalid_confidence={raw!r}'
    if base_reason:
        return 0.0, f'{base_reason} | {note}'
    return 0.0, note


@dataclass
class GenerationPlan:
    """LLM 直出类任务的生成计划。

    该结构只描述“如何生成”，不允许 LLM 直接访问数据库。需要私有数据时，
    上游必须先通过 ToolCallPlan/skill 加载脱敏上下文。
    """
    template_id: str
    prompt_template: str = ''
    output_format: str = 'markdown'  # text | markdown | json | mermaid | echarts
    model_profile: str = 'standard'  # small | standard | strong
    max_tokens: int = 1200
    temperature: float = 0.5
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'templateId': self.template_id,
            'promptTemplate': self.prompt_template,
            'outputFormat': self.output_format,
            'modelProfile': self.model_profile,
            'maxTokens': self.max_tokens,
            'temperature': self.temperature,
            'constraints': self.constraints,
        }


@dataclass
class ToolCallPlan:
    """Skill/tool 调用计划。

    只用于编排层描述工具调用，不改变旧 workflow executor 的执行协议。
    """
    step_id: str
    tool: str
    purpose: str = 'query'  # query | load_context | side_effect | render
    input: Dict[str, Any] = field(default_factory=dict)
    iterate_over: Optional[str] = None
    required: bool = True
    risk_level: str = 'low'
    cache_policy: str = 'default'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stepId': self.step_id,
            'tool': self.tool,
            'purpose': self.purpose,
            'input': self.input,
            'iterateOver': self.iterate_over,
            'required': self.required,
            'riskLevel': self.risk_level,
            'cachePolicy': self.cache_policy,
        }


@dataclass
class RouteDecision:
    """三轨混合架构的统一路由决策。"""
    task_type: str  # data_query | action | generation | dialogue | knowledge | composite | clarification | forbidden
    route_track: str  # A_DATA_ACTION | B_GENERATION | C_DIALOGUE_KNOWLEDGE | COMPOSITE
    intent: str
    confidence: float
    risk_level: str = 'low'
    task_template_id: Optional[str] = None
    required_context: List[str] = field(default_factory=list)
    tool_plan: List[ToolCallPlan] = field(default_factory=list)
    generation_plan: Optional[GenerationPlan] = None
    clarification_question: Optional[str] = None
    clarification_options: List[Dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    safety_flags: List[str] = field(default_factory=list)
    fallback_policy: str = 'friendly'
    reason: str = ''
    router_result: Optional[RouterResult] = None

    def __post_init__(self) -> None:
        try:
            self.confidence = round(float(self.confidence), 3)
        except (TypeError, ValueError):
            self.confidence = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'taskType': self.task_type,
            'routeTrack': self.route_track,
            'intent': self.intent,
            'confidence': round(self.confidence, 3),
            'riskLevel': self.risk_level,
            'taskTemplateId': self.task_template_id,
            'requiredContext': list(self.required_context),
            'toolPlan': [p.to_dict() for p in self.tool_plan],
            'generationPlan': self.generation_plan.to_dict() if self.generation_plan else None,
            'clarificationQuestion': self.clarification_question,
            'clarificationOptions': list(self.clarification_options),
            'requiresConfirmation': self.requires_confirmation,
            'safetyFlags': list(self.safety_flags),
            'fallbackPolicy': self.fallback_policy,
            'reason': self.reason,
        }


def router_result_to_route_decision(
    result: RouterResult,
    *,
    route_track: str = 'A_DATA_ACTION',
    task_type: str = 'data_query',
) -> RouteDecision:
    """Wrap a legacy RouterResult in a RouteDecision without losing fields."""
    safety_flags = [result.forbidden_reason] if result.forbidden_reason else []
    resolved_task_type = task_type
    if result.task_template_id == 'permission_denied_response':
        resolved_task_type = 'forbidden'
        if 'permission_denied' not in safety_flags:
            safety_flags.append('permission_denied')
    elif result.task_template_id == 'forbidden_action_response':
        resolved_task_type = 'forbidden'
    if result.reason and 'permission_gate:role_not_allowed' in result.reason and 'permission_denied' not in safety_flags:
        safety_flags.append('permission_denied')
    return RouteDecision(
        task_type=resolved_task_type,
        route_track=route_track,
        intent=result.intent,
        confidence=result.confidence,
        risk_level=result.risk_level,
        task_template_id=result.task_template_id,
        clarification_question=result.clarification_question,
        clarification_options=list(result.clarification_options or []),
        requires_confirmation=result.requires_confirmation,
        safety_flags=safety_flags,
        fallback_policy='legacy',
        reason=result.reason,
        router_result=result,
    )


def route_decision_to_router_result(decision: RouteDecision) -> RouterResult:
    """Convert RouteDecision back to RouterResult for the old executor path."""
    if decision.router_result is not None:
        return decision.router_result
    candidate_skills = [p.tool for p in decision.tool_plan if p.tool]
    return RouterResult(
        intent=decision.intent,
        task_template_id=decision.task_template_id,
        confidence=decision.confidence,
        entities={},
        risk_level=decision.risk_level,
        candidate_skills=candidate_skills,
        requires_confirmation=decision.requires_confirmation,
        clarification_question=decision.clarification_question,
        reason=decision.reason,
        forbidden_reason=(decision.safety_flags[0] if decision.task_type == 'forbidden'
                          and decision.safety_flags else None),
        route_path=('clarification' if decision.task_type == 'clarification'
                    else decision.route_track),
        clarification_options=list(decision.clarification_options or []),
    )


@dataclass
class WorkflowStep:
    """Task Template 中的单个步骤。"""
    id: str
    type: str  # skill | llm | branch | permission_check | widget
    skill: Optional[str] = None
    input_map: Dict[str, Any] = field(default_factory=dict)
    output_key: str = 'output'
    required: bool = True
    on_error: str = 'continue'  # continue | fallback | stop
    description: str = ''
    # llm 类型独有
    llm_purpose: Optional[str] = None  # summarizer | comparison | polish


@dataclass
class TaskTemplate:
    """业务任务模板。"""
    id: str
    name: str
    description: str
    trigger_examples: List[str] = field(default_factory=list)
    required_entities: List[str] = field(default_factory=list)
    optional_entities: Dict[str, Any] = field(default_factory=dict)
    allowed_roles: List[str] = field(default_factory=list)
    risk_level: str = 'low'
    candidate_skills: List[str] = field(default_factory=list)
    workflow: List[WorkflowStep] = field(default_factory=list)
    output_widgets: List[str] = field(default_factory=list)
    fallback_task: Optional[str] = None
    requires_confirmation: bool = False
    keywords: List[str] = field(default_factory=list)  # 规则匹配关键词
    type: str = 'workflow'
    route_track: str = 'A_DATA_ACTION'
    generation: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillSpec:
    """通用 Skill 注册项。"""
    id: str
    name: str
    domain: str  # recruitment | employee | attendance | performance | payroll | ...
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    allowed_roles: List[str] = field(default_factory=list)
    risk_level: str = 'low'
    side_effect: bool = False
    action_type: str = 'READ_PUBLIC'
    handler: Optional[Callable] = None


@dataclass
class ExecutionStep:
    """一步执行的轨迹记录。"""
    step_id: str
    type: str
    skill: Optional[str] = None
    status: str = 'pending'  # ok | error | skipped
    duration_ms: float = 0.0
    rows_count: int = 0
    error: Optional[str] = None
    risk_level: str = 'low'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stepId': self.step_id,
            'type': self.type,
            'skill': self.skill,
            'status': self.status,
            'durationMs': round(self.duration_ms, 1),
            'rowsCount': self.rows_count,
            'error': self.error,
            'riskLevel': self.risk_level,
        }


@dataclass
class ExecutionResult:
    """Executor 最终输出。"""
    summary: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    widgets: List[Dict[str, Any]] = field(default_factory=list)
    session_id: Optional[str] = None
    trace: List[ExecutionStep] = field(default_factory=list)
    router: Optional[RouterResult] = None
    route_decision: Optional[RouteDecision] = None
    requires_confirmation: bool = False
    fallback_used: bool = False
    error_code: Optional[str] = None
    answer: Optional[Dict[str, Any]] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    worksets: List[Dict[str, Any]] = field(default_factory=list)
    schema_version: str = 'assistant.response.v2'
    model_profile: Optional[str] = None
    model_name: Optional[str] = None
    render_blocks: List[Dict[str, Any]] = field(default_factory=list)
    copilot: Dict[str, Any] = field(default_factory=dict)
    client_context: Dict[str, Any] = field(default_factory=dict)

    def to_response(self, include_meta: bool = False, include_full_trace: bool = False) -> Dict[str, Any]:
        """转成兼容现有 API 的响应。"""
        used_skills = [s.skill for s in self.trace if s.skill]
        resp = {
            'schemaVersion': self.schema_version,
            'summary': self.summary,
            'entities': self.entities,
            'widgets': self.widgets,
            'sessionId': self.session_id,
        }
        if self.answer:
            resp['answer'] = self.answer
        if self.actions:
            resp['actions'] = self.actions
        if self.worksets:
            resp['worksets'] = self.worksets
        if self.render_blocks:
            resp['renderBlocks'] = self.render_blocks
        if self.copilot:
            resp['copilot'] = self.copilot
        if self.client_context:
            resp['clientContext'] = self.client_context
        if include_meta:
            decision = self.route_decision
            model_profile = (
                decision.generation_plan.model_profile
                if decision and decision.generation_plan else None
            ) or self.model_profile
            meta = {
                'taskTemplateId': self.router.task_template_id if self.router else None,
                'usedSkills': list(dict.fromkeys(used_skills)),  # 去重保序
                'riskLevel': self.router.risk_level if self.router else 'low',
                'requiresConfirmation': self.requires_confirmation,
                'fallbackUsed': self.fallback_used,
                'routeTrack': decision.route_track if decision else None,
                'taskType': decision.task_type if decision else None,
                'modelProfile': model_profile,
                'modelName': self.model_name,
                'errorCode': self.error_code,
                'traceSummary': [s.to_dict() for s in self.trace] if include_full_trace else [
                    {'skill': s.skill, 'status': s.status} for s in self.trace if s.skill
                ],
            }
            if decision:
                meta['routeDecision'] = decision.to_dict()
            resp['meta'] = meta
        return resp
