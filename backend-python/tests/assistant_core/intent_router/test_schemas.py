"""Task 1.1 —— RouterResult v2 字段、序列化 round-trip、widget 形状测试。

校验目标：
- v2 新增字段全部带默认值，老调用点（仅传 v1 必填字段）仍可构造。
- ``to_dict()`` 输出的字段集合是 v1 字段的**超集**（驼峰命名）。
- ``from_dict(to_dict(r)) == r`` 在合法 RouterResult 上恒成立。
- ``from_dict`` 容忍未知键、不丢已知键。
- ``confidence`` 不可解析为 ``[0,1]`` 的 float 时置 0.0 并把原始字符串写入 ``reason``。
- ``widgets.clarification`` 返回的字段形状与 Requirement 3.3 对齐，
  ``options`` 长度上限 4。

Validates: Requirements 1.4, 3.3, 9.1, 9.2, 9.3, 9.4, 9.5, 10.7
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pytest

from services.assistant_core.schemas import RouterResult
from services.assistant_core.widgets import (
    MAX_CLARIFICATION_OPTIONS,
    clarification,
)


# ---- v1 字段集合（从 to_dict 视角）------------------------------------------
# Requirement 8.2 要求 v2 的 to_dict 是 v1 的超集；这里固定 v1 的键集合，
# 让回归测试一旦少导出就立刻报红。
_LEGACY_KEYS = {
    'intent',
    'taskTemplateId',
    'confidence',
    'entities',
    'missingFields',
    'riskLevel',
    'candidateSkills',
    'requiresConfirmation',
    'clarificationQuestion',
    'reason',
}

_V2_NEW_KEYS = {
    'routePath',
    'topK',
    'clarificationOptions',
    'lowConfidenceWarning',
    'entityResolved',
}


# =============================================================================
# RouterResult 默认值
# =============================================================================


class TestRouterResultDefaults:
    def test_minimal_construction_uses_defaults(self) -> None:
        """只传 v1 必填字段，所有 v2 字段都应回落到默认值。"""
        r = RouterResult(intent='x', task_template_id=None, confidence=0.0)

        # v1 默认值不变
        assert r.entities == {}
        assert r.missing_fields == []
        assert r.risk_level == 'low'
        assert r.candidate_skills == []
        assert r.requires_confirmation is False
        assert r.clarification_question is None
        assert r.reason == ''
        assert r.rule_matched is False
        assert r.forbidden_reason is None

        # v2 新增字段默认值
        assert r.route_path == 'unknown'
        assert r.top_k == []
        assert r.clarification_options == []
        assert r.low_confidence_warning is False
        assert r.entity_resolved == {}

    def test_mutable_defaults_are_isolated_between_instances(self) -> None:
        """field(default_factory=...) 必须保证两个实例不会共享同一引用。"""
        r1 = RouterResult(intent='a', task_template_id=None, confidence=0.0)
        r2 = RouterResult(intent='b', task_template_id=None, confidence=0.0)
        r1.top_k.append(('t', 0.5))
        r1.clarification_options.append({'label': 'x', 'payload': 'x'})
        r1.entity_resolved['k'] = 'v'

        assert r2.top_k == []
        assert r2.clarification_options == []
        assert r2.entity_resolved == {}


# =============================================================================
# to_dict 行为
# =============================================================================


class TestToDict:
    def test_to_dict_contains_legacy_keys(self) -> None:
        r = RouterResult(intent='x', task_template_id='global_search_answer', confidence=0.5)
        d = r.to_dict()
        missing = _LEGACY_KEYS - set(d.keys())
        assert missing == set(), f'legacy keys missing: {missing}'

    def test_to_dict_is_superset_of_legacy(self) -> None:
        r = RouterResult(intent='x', task_template_id=None, confidence=0.5)
        d = r.to_dict()
        # 既包含全部 v1 键，也包含全部 v2 新键
        assert _LEGACY_KEYS <= set(d.keys())
        assert _V2_NEW_KEYS <= set(d.keys())

    def test_to_dict_camel_case_for_new_fields(self) -> None:
        r = RouterResult(
            intent='x', task_template_id='t', confidence=0.7,
            route_path='retrieval',
            top_k=[('t', 0.7), ('u', 0.5)],
            clarification_options=[{'label': 'L', 'payload': 'P'}],
            low_confidence_warning=True,
            entity_resolved={'employee': '小王'},
        )
        d = r.to_dict()
        assert d['routePath'] == 'retrieval'
        # top_k 序列化为 [[task_id, score], ...]，更适合 JSON 跨语言传输
        assert d['topK'] == [['t', 0.7], ['u', 0.5]]
        assert d['clarificationOptions'] == [{'label': 'L', 'payload': 'P'}]
        assert d['lowConfidenceWarning'] is True
        assert d['entityResolved'] == {'employee': '小王'}
        # 不应有 snake_case 漏出
        for snake in ('route_path', 'top_k', 'clarification_options',
                      'low_confidence_warning', 'entity_resolved'):
            assert snake not in d

    def test_confidence_is_rounded_to_three_decimals(self) -> None:
        r = RouterResult(intent='x', task_template_id=None, confidence=0.123456)
        assert r.to_dict()['confidence'] == pytest.approx(0.123)


# =============================================================================
# from_dict round-trip 与未知字段容忍
# =============================================================================


def _make_full_router_result() -> RouterResult:
    """构造一个把所有字段都填上的 RouterResult，便于测 round-trip。"""
    return RouterResult(
        intent='payroll_month_summary',
        task_template_id='payroll_month_summary',
        confidence=0.812,
        entities={'employee_name': '小王', 'month': '2024-03'},
        missing_fields=['department'],
        risk_level='high',
        candidate_skills=['payroll_analysis'],
        requires_confirmation=True,
        clarification_question='你想查哪个月？',
        reason='规则命中：薪酬',
        rule_matched=True,
        forbidden_reason=None,
        route_path='fast_path',
        top_k=[('payroll_month_summary', 0.81), ('global_search_answer', 0.32)],
        clarification_options=[
            {'label': '本月', 'payload': '2024-03'},
            {'label': '上月', 'payload': '2024-02'},
        ],
        low_confidence_warning=False,
        entity_resolved={'employee': '小王'},
    )


class TestFromDictRoundTrip:
    def test_round_trip_full_instance(self) -> None:
        r = _make_full_router_result()
        restored = RouterResult.from_dict(r.to_dict())
        assert restored == r

    def test_round_trip_minimal_instance(self) -> None:
        r = RouterResult(intent='x', task_template_id=None, confidence=0.0)
        restored = RouterResult.from_dict(r.to_dict())
        assert restored == r

    @pytest.mark.parametrize('confidence', [0.0, 0.5, 0.999, 1.0, 0.78])
    def test_round_trip_confidence_values(self, confidence: float) -> None:
        r = RouterResult(intent='x', task_template_id='t', confidence=confidence)
        assert RouterResult.from_dict(r.to_dict()) == r

    def test_unknown_keys_are_ignored(self) -> None:
        d = _make_full_router_result().to_dict()
        d['__unknown__'] = '应被忽略'
        d['weirdField'] = {'nested': 1}
        d['llmRawResponse'] = 'whatever'

        restored = RouterResult.from_dict(d)
        # 已知字段不丢
        assert restored.task_template_id == 'payroll_month_summary'
        assert restored.route_path == 'fast_path'
        # 实例上不会冒出未知字段
        assert not hasattr(restored, '__unknown__')
        assert not hasattr(restored, 'weirdField')

    def test_from_dict_accepts_snake_case_aliases(self) -> None:
        """便于直接吃 LLM 返回的 snake_case JSON，不需要外层做翻译。"""
        d = {
            'intent': 'recent_resume_analysis',
            'task_template_id': 'recent_resume_analysis',
            'confidence': 0.9,
            'route_path': 'retrieval',
            'top_k': [['recent_resume_analysis', 0.9]],
            'clarification_options': [{'label': '高分', 'payload': 'high'}],
            'low_confidence_warning': False,
            'entity_resolved': {'time_window': 'last_7d'},
            'requires_confirmation': True,
        }
        r = RouterResult.from_dict(d)
        assert r.task_template_id == 'recent_resume_analysis'
        assert r.route_path == 'retrieval'
        assert r.top_k == [('recent_resume_analysis', 0.9)]
        assert r.requires_confirmation is True
        assert r.entity_resolved == {'time_window': 'last_7d'}

    def test_from_dict_handles_none(self) -> None:
        r = RouterResult.from_dict(None)
        # 全部回到默认值
        assert r.intent == ''
        assert r.task_template_id is None
        assert r.confidence == 0.0
        assert r.route_path == 'unknown'
        assert r.top_k == []

    def test_from_dict_returns_independent_collections(self) -> None:
        d = _make_full_router_result().to_dict()
        r1 = RouterResult.from_dict(d)
        r2 = RouterResult.from_dict(d)
        r1.entities['mutated'] = True
        r1.candidate_skills.append('x')
        r1.entity_resolved['k'] = 'v'
        assert 'mutated' not in r2.entities
        assert 'x' not in r2.candidate_skills
        assert 'k' not in r2.entity_resolved


# =============================================================================
# confidence 越界归零 + 原始字符串写入 reason
# =============================================================================


class TestConfidenceSanitization:
    @pytest.mark.parametrize('bad_value', [
        '不是数字',
        'NaN',
        '1.5',          # 超过 1
        '-0.1',         # 低于 0
        None,
        [],
        {},
        object(),
    ])
    def test_invalid_confidence_clamped_to_zero(self, bad_value: Any) -> None:
        r = RouterResult.from_dict({
            'intent': 'x',
            'taskTemplateId': 't',
            'confidence': bad_value,
            'reason': '',
        })
        assert r.confidence == 0.0
        # 原始字符串被写入 reason，便于后续 fallback 排查
        assert 'invalid_confidence=' in r.reason
        assert repr(bad_value) in r.reason

    @pytest.mark.parametrize('value,expected', [
        (1.2, 0.0),
        (-0.5, 0.0),
        (math.inf, 0.0),
        (-math.inf, 0.0),
        (math.nan, 0.0),
    ])
    def test_out_of_range_floats_clamped_to_zero(
        self, value: float, expected: float,
    ) -> None:
        r = RouterResult.from_dict({
            'intent': 'x', 'taskTemplateId': 't', 'confidence': value,
        })
        assert r.confidence == expected
        assert 'invalid_confidence=' in r.reason

    def test_invalid_confidence_preserves_existing_reason(self) -> None:
        r = RouterResult.from_dict({
            'intent': 'x',
            'taskTemplateId': 't',
            'confidence': 'abc',
            'reason': '原始原因',
        })
        assert r.confidence == 0.0
        assert '原始原因' in r.reason
        assert 'invalid_confidence=' in r.reason

    def test_valid_confidence_does_not_taint_reason(self) -> None:
        r = RouterResult.from_dict({
            'intent': 'x', 'taskTemplateId': 't',
            'confidence': 0.42, 'reason': 'ok',
        })
        assert r.confidence == 0.42
        assert r.reason == 'ok'

    def test_string_number_is_accepted(self) -> None:
        # JSON 来源偶尔会把数字当字符串传来；保持容忍度
        r = RouterResult.from_dict({
            'intent': 'x', 'taskTemplateId': 't', 'confidence': '0.73',
        })
        assert r.confidence == 0.73
        assert 'invalid_confidence' not in r.reason

    def test_bool_is_treated_as_invalid(self) -> None:
        # bool 是 int 的子类，True == 1.0 但语义上不应被当成置信度
        r = RouterResult.from_dict({
            'intent': 'x', 'taskTemplateId': 't', 'confidence': True,
        })
        assert r.confidence == 0.0
        assert 'invalid_confidence=True' in r.reason


# =============================================================================
# widgets.clarification 形状
# =============================================================================


class TestClarificationWidget:
    def test_basic_shape(self) -> None:
        w = clarification(
            question='你要查谁？',
            options=[
                {'label': '小王', 'payload': '小王'},
                {'label': '小李', 'payload': '小李'},
            ],
            origin_message='看看 TA 的考勤',
        )
        assert w == {
            'type': 'clarification',
            'question': '你要查谁？',
            'options': [
                {'label': '小王', 'payload': '小王'},
                {'label': '小李', 'payload': '小李'},
            ],
            'origin_message': '看看 TA 的考勤',
        }

    def test_options_truncated_to_max_four(self) -> None:
        opts = [{'label': f'opt{i}', 'payload': f'p{i}'} for i in range(10)]
        w = clarification('q', opts, 'm')
        assert MAX_CLARIFICATION_OPTIONS == 4
        assert len(w['options']) == 4
        # 保留的是前 4 个，不是末尾 4 个
        assert [o['label'] for o in w['options']] == ['opt0', 'opt1', 'opt2', 'opt3']

    def test_payload_defaults_to_label(self) -> None:
        w = clarification('q', [{'label': '小王'}], 'm')
        assert w['options'] == [{'label': '小王', 'payload': '小王'}]

    def test_drops_invalid_option_entries(self) -> None:
        # 缺 label / 非 dict / label 非字符串 → 全部跳过，不会让前端拿到空按钮
        w = clarification('q', [
            {'label': '可见', 'payload': 'p'},
            {'payload': '只有 payload'},  # drop
            'not a dict',  # type: ignore[list-item]  # drop
            {'label': '', 'payload': 'empty'},  # drop
            {'label': 123, 'payload': 'num'},  # drop
        ], 'm')
        assert w['options'] == [{'label': '可见', 'payload': 'p'}]

    def test_empty_options_yields_empty_list(self) -> None:
        w = clarification('q', [], 'm')
        assert w['options'] == []
        assert w['type'] == 'clarification'

    def test_handles_none_origin_message_and_question(self) -> None:
        w = clarification(None, None, None)  # type: ignore[arg-type]
        assert w['question'] == ''
        assert w['origin_message'] == ''
        assert w['options'] == []
        assert w['type'] == 'clarification'

    def test_extra_keys_in_option_are_dropped(self) -> None:
        # 防止泄漏调试字段（比如内部 trace id）到前端
        w = clarification('q', [
            {'label': 'X', 'payload': 'x', 'internal_trace_id': 'leak-me'},
        ], 'm')
        assert w['options'] == [{'label': 'X', 'payload': 'x'}]
