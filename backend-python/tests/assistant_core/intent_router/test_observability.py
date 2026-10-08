"""Task 2.1 —— ObservabilityRecorder 与 FallbackSampleSink 单元测试。

校验目标：
- ``sha256_16`` 输出严格 16 位十六进制。
- ``ObservabilityRecorder.record`` 写入主 logger 的 caplog 中**不出现**消息原文。
- 计数器 ``inc`` / ``get`` 在多次调用、带 label / 不带 label 场景下叠加正确。
- ``FallbackSampleSink`` 在底层 logger 抛错时仍返回 ``False`` 且不向上抛。

Validates: Requirements 6.1, 6.2, 6.3, 11.4
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import pytest

from services.assistant_core.intent_router import observability as obs


# ---- 通用 fixtures ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    """每个测试前清空模块级计数器与直方图，防止用例间相互影响。"""
    obs.reset_metrics()
    yield
    obs.reset_metrics()


# ---- sha256_16 -------------------------------------------------------------


class TestSha256_16:
    def test_returns_exactly_16_hex_chars(self) -> None:
        digest = obs.sha256_16('帮我看下小王的考勤')
        assert isinstance(digest, str)
        assert len(digest) == 16
        # 必须是合法十六进制
        assert re.fullmatch(r'[0-9a-f]{16}', digest), digest

    def test_deterministic_for_same_input(self) -> None:
        assert obs.sha256_16('hello') == obs.sha256_16('hello')

    def test_different_inputs_differ(self) -> None:
        assert obs.sha256_16('a') != obs.sha256_16('b')

    def test_handles_empty_and_none(self) -> None:
        empty_digest = obs.sha256_16('')
        none_digest = obs.sha256_16(None)  # type: ignore[arg-type]
        assert len(empty_digest) == 16
        # None 与空串行为一致，方便上层无脑调用。
        assert empty_digest == none_digest

    def test_unicode_input_is_utf8_encoded(self) -> None:
        # 不报错即可；并且不同 Unicode 输入产生不同摘要
        assert obs.sha256_16('简历') != obs.sha256_16('考勤')


# ---- 计数器 -----------------------------------------------------------------


class TestCounters:
    def test_inc_default_value_one(self) -> None:
        obs.inc('router_request_total', route_path='retrieval')
        obs.inc('router_request_total', route_path='retrieval')
        assert obs.get('router_request_total', route_path='retrieval') == 2

    def test_inc_with_explicit_value(self) -> None:
        obs.inc('router_pronoun_resolved_total', value=3)
        obs.inc('router_pronoun_resolved_total', value=2)
        assert obs.get('router_pronoun_resolved_total') == 5

    def test_label_order_does_not_matter(self) -> None:
        obs.inc('m', a='1', b='2')
        obs.inc('m', b='2', a='1')
        assert obs.get('m', a='1', b='2') == 2
        assert obs.get('m', b='2', a='1') == 2

    def test_different_labels_are_isolated(self) -> None:
        obs.inc('router_request_total', route_path='retrieval')
        obs.inc('router_request_total', route_path='fast_path')
        assert obs.get('router_request_total', route_path='retrieval') == 1
        assert obs.get('router_request_total', route_path='fast_path') == 1
        # 没有传 label 时是另一个独立 series
        assert obs.get('router_request_total') == 0

    def test_get_unknown_returns_zero(self) -> None:
        assert obs.get('nonexistent_counter') == 0

    def test_negative_inc_is_clamped_to_zero(self) -> None:
        obs.inc('m', value=-5)
        assert obs.get('m') == 0


# ---- ObservabilityRecorder.record ------------------------------------------


class TestObservabilityRecorder:
    def test_log_does_not_contain_plaintext_message(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = '小王 2024-03 工资条 这是机密内容'
        recorder = obs.ObservabilityRecorder()

        with caplog.at_level(logging.INFO, logger=obs.LOGGER_NAME):
            recorder.record(
                request_id='req-1',
                user_id='u-hash-abc',
                route_path='retrieval',
                top_k_scores=[('payroll_month_summary', 0.81), ('global_search_answer', 0.42)],
                chosen_task_id='payroll_month_summary',
                confidence=0.81,
                clarification_emitted=False,
                entity_resolved_count=0,
                latency_ms=123.4,
                message_hash=obs.sha256_16(secret),
                message_length=len(secret),
            )

        # 1) 主 logger 收到了一条 record
        records = [r for r in caplog.records if r.name == obs.LOGGER_NAME]
        assert len(records) == 1
        record = records[0]

        # 2) 摘要 message + 所有结构化字段值都不能包含原文片段
        rendered = record.getMessage()
        for forbidden in ('小王', '工资条', '机密', secret):
            assert forbidden not in rendered, f'plaintext leaked into message: {forbidden!r}'
        for value in record.__dict__.values():
            value_str = str(value)
            for forbidden in ('小王', '工资条', '机密'):
                assert forbidden not in value_str, (
                    f'plaintext leaked via field value: {forbidden!r}'
                )

        # 3) 关键脱敏字段确实就位
        assert getattr(record, 'route_path') == 'retrieval'
        assert getattr(record, 'chosen_task_id') == 'payroll_month_summary'
        assert getattr(record, 'message_length') == len(secret)
        assert len(getattr(record, 'message_hash')) == 16

    def test_record_increments_counters_correctly(self) -> None:
        recorder = obs.ObservabilityRecorder()

        # 一次 retrieval 命中
        recorder.record(
            request_id='r1', user_id='u1', route_path='retrieval',
            top_k_scores=[('t1', 0.9)], chosen_task_id='t1',
            confidence=0.9, clarification_emitted=False,
            entity_resolved_count=0, latency_ms=120.0,
        )
        # 一次 fallback
        recorder.record(
            request_id='r2', user_id='u1', route_path='fallback',
            top_k_scores=[('t1', 0.4)], chosen_task_id='t1',
            confidence=0.4, clarification_emitted=False,
            entity_resolved_count=0, latency_ms=2500.0,
        )
        # 一次 clarification（含两个代词被消解）
        recorder.record(
            request_id='r3', user_id='u1', route_path='clarification',
            top_k_scores=[('t1', 0.6), ('t2', 0.55)], chosen_task_id='t1',
            confidence=0.6, clarification_emitted=True,
            entity_resolved_count=2, latency_ms=300.0,
        )
        # 一次 legacy_fallback（嵌入服务挂掉）
        recorder.record(
            request_id='r4', user_id='u1', route_path='legacy_fallback',
            top_k_scores=[], chosen_task_id='global_search_answer',
            confidence=0.0, clarification_emitted=False,
            entity_resolved_count=0, latency_ms=15.0,
        )

        # router_request_total 按 route_path 分桶
        assert obs.get(obs.COUNTER_REQUEST_TOTAL, route_path='retrieval') == 1
        assert obs.get(obs.COUNTER_REQUEST_TOTAL, route_path='fallback') == 1
        assert obs.get(obs.COUNTER_REQUEST_TOTAL, route_path='clarification') == 1
        assert obs.get(obs.COUNTER_REQUEST_TOTAL, route_path='legacy_fallback') == 1

        # fallback / legacy_fallback 都计入 router_fallback_total
        assert obs.get(obs.COUNTER_FALLBACK_TOTAL) == 2
        # 仅一次澄清
        assert obs.get(obs.COUNTER_CLARIFICATION_TOTAL) == 1
        # 代词消解累加（这里只一次 record 传了 2）
        assert obs.get(obs.COUNTER_PRONOUN_RESOLVED_TOTAL) == 2

    def test_latency_histogram_is_observed(self) -> None:
        recorder = obs.ObservabilityRecorder()
        recorder.record(
            request_id='r', user_id='u', route_path='retrieval',
            top_k_scores=[], chosen_task_id='t', confidence=0.9,
            clarification_emitted=False, entity_resolved_count=0,
            latency_ms=120.0,
        )
        snap = obs.snapshot_histograms()
        # 找到 latency 直方图（无标签）
        target_keys = [k for k in snap if k[0] == obs.HISTOGRAM_LATENCY_SECONDS]
        assert target_keys, 'latency histogram not initialized'
        buckets = snap[target_keys[0]]
        assert len(buckets) == len(obs.LATENCY_BUCKETS_MS)
        # 120ms 应当落入 ``<= 200`` 桶以及之后的所有桶（cumulative）
        for idx, upper in enumerate(obs.LATENCY_BUCKETS_MS):
            expected = 1 if 120.0 <= upper else 0
            assert buckets[idx] == expected, (
                f'bucket le={upper} expected {expected}, got {buckets[idx]}'
            )


# ---- FallbackSampleSink ----------------------------------------------------


class _ExplodingLogger:
    """logger 替身：每次 ``info()`` 都抛异常，用来证明 sink 不会把异常向上抛。"""

    def __init__(self) -> None:
        self.info_calls = 0
        self.warning_calls = 0

    def info(self, *args: Any, **kwargs: Any) -> None:
        self.info_calls += 1
        raise RuntimeError('simulated logger failure')

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.warning_calls += 1


class TestFallbackSampleSink:
    def test_write_success_path(self, caplog: pytest.LogCaptureFixture) -> None:
        sink = obs.FallbackSampleSink()
        plaintext = '测试输入'
        with caplog.at_level(logging.INFO, logger=obs.FALLBACK_SAMPLE_LOGGER_NAME):
            ok = sink.write(
                query_hash=obs.sha256_16(plaintext),
                role='hr',
                top_k_task_ids=['t1', 't2'],
                top_k_scores=[0.42, 0.31],
                chosen_task_id='t1',
                timestamp=time.time(),
            )
        assert ok is True
        records = [r for r in caplog.records
                   if r.name == obs.FALLBACK_SAMPLE_LOGGER_NAME]
        assert len(records) == 1
        rec = records[0]

        # LogRecord 自带 ``message`` 字段（其值是我们写入的静态 'router_fallback_sample'），
        # 关键检查是：所有字段值都不包含原文片段。
        for value in rec.__dict__.values():
            assert plaintext not in str(value), (
                f'plaintext leaked via field value: {value!r}'
            )
        # 期望的脱敏字段都就位
        assert getattr(rec, 'role') == 'hr'
        assert getattr(rec, 'chosen_task_id') == 't1'
        assert getattr(rec, 'top_k_task_ids') == ['t1', 't2']
        assert getattr(rec, 'query_hash') == obs.sha256_16(plaintext)

    def test_write_swallows_logger_exception_and_returns_false(self) -> None:
        exploding = _ExplodingLogger()
        warner = _ExplodingLogger()  # 即使 warning 也失败也不能向上抛
        sink = obs.FallbackSampleSink(
            sample_logger=exploding,  # type: ignore[arg-type]
            warn_logger=warner,  # type: ignore[arg-type]
        )

        # 关键：调用本身不能抛
        result = sink.write(
            query_hash='abcd' * 4,
            role='hr',
            top_k_task_ids=['t1'],
            top_k_scores=[0.1],
            chosen_task_id='t1',
            timestamp=0.0,
        )

        assert result is False
        assert exploding.info_calls == 1
        # warn_logger 也尝试了一次（即使它也抛错，sink 仍然安全返回）
        assert warner.warning_calls == 1

    def test_write_warning_path_uses_main_logger(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        exploding = _ExplodingLogger()
        sink = obs.FallbackSampleSink(
            sample_logger=exploding,  # type: ignore[arg-type]
            # warn_logger 默认 -> 主 logger，可被 caplog 捕获
        )
        with caplog.at_level(logging.WARNING, logger=obs.LOGGER_NAME):
            assert sink.write(
                query_hash='qh',
                role='hr',
                top_k_task_ids=[],
                top_k_scores=[],
                chosen_task_id='t1',
                timestamp=0.0,
            ) is False

        warnings = [r for r in caplog.records
                    if r.name == obs.LOGGER_NAME and r.levelno == logging.WARNING]
        assert warnings, 'expected at least one warning on the main logger'
        # warning 中只引用 query_hash / chosen_task_id，不包含原文
        for forbidden in ('message', 'text', 'raw_query'):
            for rec in warnings:
                assert forbidden not in str(rec.__dict__.get(forbidden, ''))

    def test_extra_fields_cannot_leak_plaintext(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        sink = obs.FallbackSampleSink()
        with caplog.at_level(logging.INFO, logger=obs.FALLBACK_SAMPLE_LOGGER_NAME):
            sink.write(
                query_hash='hh',
                role='hr',
                top_k_task_ids=[],
                top_k_scores=[],
                chosen_task_id='t1',
                timestamp=0.0,
                extra_fields={
                    'message': '机密原文',  # 必须被丢弃
                    'raw_query': '小王考勤',  # 必须被丢弃
                    'user_id': 'real-user',  # 必须被丢弃
                    'feature_flag_bucket': 10,  # 允许
                },
            )

        records = [r for r in caplog.records
                   if r.name == obs.FALLBACK_SAMPLE_LOGGER_NAME]
        assert records
        rec = records[0]
        # 受保护的字段不应被注入
        assert not hasattr(rec, 'raw_query') or getattr(rec, 'raw_query') in (None, '')
        # 任何字段值里都不能出现原文片段
        for value in rec.__dict__.values():
            assert '机密' not in str(value)
            assert '小王' not in str(value)
        # 但白名单字段被保留
        assert getattr(rec, 'feature_flag_bucket') == 10
