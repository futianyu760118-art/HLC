"""会话记忆：复用 assistant_sessions 表，严格用户隔离。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from models import AssistantSession, User, db
from services.tenancy import assign_tenant

from .schemas import AssistantContext

logger = logging.getLogger('hengpintong.assistant.memory')

MAX_HISTORY_TURNS = 6
MAX_SESSION_MESSAGES = 40


def get_or_create_session(user_id: str, session_id: Optional[str]) -> AssistantSession:
    """获取或创建用户的会话。严格隔离 user_id。"""
    if session_id:
        sess = AssistantSession.query.filter_by(id=session_id, user_id=user_id).first()
        if sess:
            return sess
    sess = (AssistantSession.query
            .filter_by(user_id=user_id, is_active=True)
            .with_entities(
                AssistantSession.id,
                AssistantSession.message_count,
                AssistantSession.updated_at,
            )
            .order_by(AssistantSession.updated_at.desc()).first())
    if sess and (sess.message_count or 0) < MAX_SESSION_MESSAGES:
        full_sess = AssistantSession.query.filter_by(id=sess.id, user_id=user_id).first()
        if full_sess:
            return full_sess
    if sess:
        AssistantSession.query.filter_by(id=sess.id, user_id=user_id).update({'is_active': False})
    new_sess = AssistantSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=None,
        messages=[],
        is_active=True,
        message_count=0,
    )
    owner = db.session.get(User, user_id)
    assign_tenant(new_sess, owner.tenant_id if owner else None)
    db.session.add(new_sess)
    return new_sess


def trim_history_for_llm(stored_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从持久化的消息列表挑出最近 N 轮 user+assistant 用作 LLM 上下文。"""
    history: List[Dict[str, Any]] = []
    user_count = 0
    for m in reversed(stored_messages or []):
        role = m.get('role')
        if role not in ('user', 'assistant'):
            continue
        content = (m.get('content') or '').strip()
        if not content:
            continue
        item = {'role': role, 'content': content}
        # Runtime state is small and essential for follow-up understanding.
        # Keep it with assistant turns so "这个人/他/上面这些" can resolve
        # across HTTP requests, not only inside one process.
        if role == 'assistant':
            for key in (
                'meta', 'metadata', 'entities', 'widgets', 'actions', 'worksets',
                'renderBlocks', 'copilot', 'clientContext',
            ):
                if key in m:
                    item[key] = m.get(key)
        history.append(item)
        if role == 'user':
            user_count += 1
            if user_count >= MAX_HISTORY_TURNS:
                break
    history.reverse()
    return history


def _sanitize_client_context(client_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(client_context, dict):
        return {}

    allowed = {
        'path', 'route', 'moduleId', 'moduleName', 'pageTitle', 'visibleFilters',
        'selectedRecordIds', 'selectedRecords', 'search', 'userRole', 'viewport',
    }
    sanitized: Dict[str, Any] = {}
    for key in allowed:
        if key not in client_context:
            continue
        value = client_context.get(key)
        if isinstance(value, str):
            sanitized[key] = value[:300]
        elif isinstance(value, (int, float, bool)) or value is None:
            sanitized[key] = value
        elif isinstance(value, list):
            sanitized[key] = value[:20]
        elif isinstance(value, dict):
            sanitized[key] = {
                str(k)[:80]: v
                for k, v in list(value.items())[:30]
                if isinstance(v, (str, int, float, bool)) or v is None
            }
    return sanitized


def build_context(user_id: str, session_id: Optional[str] = None,
                  request_id: Optional[str] = None,
                  client_context: Optional[Dict[str, Any]] = None) -> AssistantContext:
    """从 DB 装配 AssistantContext。"""
    user = User.query.get(user_id)
    role = (user.role if user else 'viewer') or 'viewer'
    history: List[Dict[str, Any]] = []
    real_session_id: Optional[str] = None
    try:
        sess = get_or_create_session(user_id, session_id)
        history = trim_history_for_llm(sess.messages or [])
        real_session_id = sess.id
    except Exception:
        logger.exception('memory_build_context_failed')
        # session 加载失败不阻塞主流程

    return AssistantContext(
        user_id=user_id,
        role=role,
        session_id=real_session_id,
        history=history,
        request_id=request_id,
        user_name=user.name if user else None,
        user_department_id=user.department_id if user else None,
        user_employee_id=user.employee_id if user else None,
        audit_user_id=user_id,
        audit_session_id=real_session_id,
        client_context=_sanitize_client_context(client_context),
    )


def save_turn(user_id: str, session_id: Optional[str], question: str,
              summary: str, entity_count: int = 0,
              metadata: Optional[Dict[str, Any]] = None,
              *,
              request_id: Optional[str] = None,
              entities: Optional[List[Dict[str, Any]]] = None,
              widgets: Optional[List[Dict[str, Any]]] = None,
              actions: Optional[List[Dict[str, Any]]] = None,
              worksets: Optional[List[Dict[str, Any]]] = None,
              answer: Optional[Dict[str, Any]] = None,
              schema_version: Optional[str] = None,
              render_blocks: Optional[List[Dict[str, Any]]] = None,
              copilot: Optional[Dict[str, Any]] = None,
              client_context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """把一轮对话写入会话。返回 session_id。"""
    try:
        sess = get_or_create_session(user_id, session_id)
        stored = list(sess.messages or [])
        now_iso = datetime.utcnow().isoformat()
        stored.append({'role': 'user', 'content': question, 'ts': now_iso})
        assistant_msg: Dict[str, Any] = {
            'role': 'assistant',
            'content': summary,
            'entityCount': entity_count,
            'ts': now_iso,
        }
        if metadata:
            assistant_msg['meta'] = metadata
        if entities:
            assistant_msg['entities'] = entities
        if widgets:
            assistant_msg['widgets'] = widgets
        if actions:
            assistant_msg['actions'] = actions
        if worksets:
            assistant_msg['worksets'] = worksets
        if answer:
            assistant_msg['answer'] = answer
        if schema_version:
            assistant_msg['schemaVersion'] = schema_version
        if render_blocks:
            assistant_msg['renderBlocks'] = render_blocks
        if copilot:
            assistant_msg['copilot'] = copilot
        if client_context:
            assistant_msg['clientContext'] = client_context
        stored.append(assistant_msg)
        sess.messages = stored
        sess.message_count = len(stored)
        if not sess.title:
            sess.title = (question or '')[:80]
        committed_session_id = sess.id
        db.session.commit()
        committed_tenant_id = sess.tenant_id
        if request_id:
            try:
                from .audit import link_audits_to_session

                link_audits_to_session(
                    tenant_id=committed_tenant_id,
                    request_id=request_id,
                    user_id=user_id,
                    session_id=committed_session_id,
                )
            except Exception:
                logger.exception('memory_audit_session_link_failed')
        return committed_session_id
    except Exception:
        logger.exception('memory_save_turn_failed')
        db.session.rollback()
        return session_id


def update_latest_assistant_answer(
    *,
    user_id: str,
    session_id: str,
    summary: str,
    answer: Optional[Dict[str, Any]] = None,
    render_blocks: Optional[List[Dict[str, Any]]] = None,
    copilot: Optional[Dict[str, Any]] = None,
) -> bool:
    """Replace the latest assistant turn content after a streamed expression."""
    try:
        sess = AssistantSession.query.filter_by(id=session_id, user_id=user_id).first()
        if not sess:
            return False
        stored = list(sess.messages or [])
        for entry in reversed(stored):
            if not isinstance(entry, dict) or entry.get('role') != 'assistant':
                continue
            entry['content'] = summary
            if answer is not None:
                entry['answer'] = answer
            if render_blocks is not None:
                entry['renderBlocks'] = render_blocks
            if copilot is not None:
                entry['copilot'] = copilot
            meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
            meta['streamedAnswer'] = True
            entry['meta'] = meta
            sess.messages = stored
            sess.updated_at = datetime.utcnow()
            db.session.commit()
            return True
        return False
    except Exception:
        logger.exception('memory_update_latest_assistant_answer_failed')
        db.session.rollback()
        return False


def get_pending_action(
    user_id: str,
    session_id: Optional[str],
    action_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Restore the latest unconsumed chat-confirmed action from session state."""
    if not session_id:
        return None
    try:
        sess = AssistantSession.query.filter_by(id=session_id, user_id=user_id).first()
        if not sess:
            return None
        resolved_ids = set()
        for entry in reversed(sess.messages or []):
            if not isinstance(entry, dict) or entry.get('role') != 'assistant':
                continue
            meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
            resolved = meta.get('resolvedActionId')
            if resolved:
                resolved_ids.add(resolved)
            pending = meta.get('pendingAction')
            if not isinstance(pending, dict):
                continue
            pending_id = pending.get('id')
            if pending_id in resolved_ids:
                continue
            if action_id and pending_id != action_id:
                continue
            return pending
    except Exception:
        logger.exception('memory_pending_action_failed')
    return None
