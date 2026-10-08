"""智能助手服务兼容入口。

真实 Copilot 主流程在 ``services.assistant_core.copilot_orchestrator``。
本文件只保留旧 API 名称，避免路由和历史调用点一次性改动。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .assistant_core import copilot_orchestrator


def handle_assistant_query(
    user_id: str,
    message: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return copilot_orchestrator.query(
        user_id=user_id,
        message=message,
        session_id=session_id,
        request_id=request_id,
        client_context=client_context,
    )


def assistant_skill_invoke(
    skill_id: str,
    params: Dict[str, Any],
    user_id: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return copilot_orchestrator.invoke_skill(
        skill_id=skill_id,
        params=params,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        client_context=client_context,
    )


def assistant_query(
    question: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not user_id:
        return {
            'summary': '未识别到用户身份，无法启动助手。',
            'entities': [],
            'widgets': [],
            'sessionId': session_id,
            'meta': {'taskTemplateId': None, 'errorCode': 'no_user'},
        }
    return handle_assistant_query(
        user_id=user_id,
        message=question,
        session_id=session_id,
        request_id=request_id,
        client_context=client_context,
    )


def assistant_stream_grounded_response(
    question: str,
    result_payload: Dict[str, Any],
    *,
    user_id: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_context: Optional[Dict[str, Any]] = None,
):
    return copilot_orchestrator.stream_grounded_response(
        user_id=user_id,
        message=question,
        result_payload=result_payload,
        session_id=session_id,
        request_id=request_id,
        client_context=client_context,
    )


def assistant_apply_streamed_answer(
    result_payload: Dict[str, Any],
    streamed_text: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    return copilot_orchestrator.apply_streamed_answer(
        result_payload,
        streamed_text,
        user_id=user_id,
    )
