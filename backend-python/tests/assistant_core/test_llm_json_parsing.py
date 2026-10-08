"""Lightweight tests for LLM JSON extraction."""

from __future__ import annotations

from services.assistant_core import llm_client


def test_json_chat_profile_extracts_json_from_model_wrappers(monkeypatch):
    cases = [
        '```json\n{"selected_skill":"payroll.anomaly","confidence":0.9}\n```',
        '<think>我先想一下\n{"selected_skill":"approval.todo","confidence":0.77}',
        '前置说明 {不是json} {"selected_skill":"candidate.search","confidence":0.82} 后置说明 {still:not-json}',
        '好的，结果如下：\n```JSON\n{"normalized_query":"查薪酬异常","selected_skill":"payroll.anomaly"}\n```\n请确认。',
    ]
    expected = [
        'payroll.anomaly',
        'approval.todo',
        'candidate.search',
        'payroll.anomaly',
    ]

    def fake_chat(*args, **kwargs):
        return {'content': cases.pop(0)}

    monkeypatch.setattr(llm_client, 'chat', fake_chat)

    for skill_id in expected:
        payload = llm_client.json_chat_profile(
            'small',
            [{'role': 'user', 'content': '测试 JSON 解析'}],
            resource_domain='system_ai',
        )
        assert payload['selected_skill'] == skill_id


def test_json_chat_profile_records_timeout_meta(monkeypatch):
    def fake_chat(*args, **kwargs):
        llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'timeout',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'siliconflow',
            'latency_ms': 8000,
        })
        return None

    monkeypatch.setattr(llm_client, 'chat', fake_chat)

    payload = llm_client.json_chat_profile(
        'small',
        [{'role': 'user', 'content': '测试超时元信息'}],
        resource_domain='system_ai',
    )

    assert payload is None
    assert llm_client.last_call_meta()['status'] == 'timeout'


def test_chat_records_http_error_when_retry_disabled(monkeypatch):
    class FakeResponse:
        status_code = 429

        def json(self):
            return {}

    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr(llm_client, 'API_KEY', 'test-key')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    result = llm_client.chat(
        [{'role': 'user', 'content': '测试 429 诊断'}],
        retry_once=False,
        model='fake-model',
        timeout=1,
    )

    assert result is None
    assert len(calls) == 1
    meta = llm_client.last_call_meta()
    assert meta['status'] == 'http_error'
    assert meta['http_status'] == 429
    assert meta['model'] == 'fake-model'
