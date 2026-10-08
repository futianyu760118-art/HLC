"""Continuous feedback MVP service for the governed extension API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from models import ContinuousFeedbackEntry, Employee, db


VALID_FEEDBACK_TYPES = {'praise', 'coaching', 'concern', 'goal', 'other'}
VALID_STATUSES = {'open', 'acknowledged', 'resolved', 'closed'}
POSITIVE_TYPES = {'praise', 'goal'}
NEGATIVE_TYPES = {'concern'}


def _new_id() -> str:
    return str(uuid.uuid4())


def _sentiment_for(feedback_type: str, content: str) -> str:
    lowered = (content or '').lower()
    if feedback_type in POSITIVE_TYPES:
        return 'positive'
    if feedback_type in NEGATIVE_TYPES:
        return 'negative'
    if any(token in lowered for token in ('great', 'excellent', 'thanks', 'appreciate', 'good')):
        return 'positive'
    if any(token in lowered for token in ('risk', 'issue', 'problem', 'concern', 'late')):
        return 'negative'
    return 'neutral'


class ContinuousFeedbackService:
    @staticmethod
    def create_entry(
        tenant_id: str,
        employee_id: str,
        giver_id: str,
        data: Dict[str, Any],
    ) -> ContinuousFeedbackEntry:
        employee = Employee.query.filter_by(id=employee_id, tenant_id=tenant_id).first()
        if not employee:
            raise LookupError('员工不存在或无权访问')

        content = (data.get('content') or '').strip()
        if not content:
            raise ValueError('反馈内容不能为空')

        feedback_type = (data.get('feedbackType') or data.get('feedback_type') or 'coaching').strip()
        if feedback_type not in VALID_FEEDBACK_TYPES:
            feedback_type = 'other'

        entry = ContinuousFeedbackEntry(
            id=_new_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            giver_id=giver_id,
            feedback_type=feedback_type,
            category=(data.get('category') or '').strip(),
            content=content,
            visibility=(data.get('visibility') or 'manager').strip() or 'manager',
            sentiment=_sentiment_for(feedback_type, content),
            status='open',
        )
        db.session.add(entry)
        return entry

    @staticmethod
    def list_entries(
        tenant_id: str,
        *,
        employee_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        query = ContinuousFeedbackEntry.query.filter_by(tenant_id=tenant_id)
        if employee_id:
            query = query.filter_by(employee_id=employee_id)
        if status:
            query = query.filter_by(status=status)
        limit = max(1, min(int(limit or 100), 200))
        rows = query.order_by(ContinuousFeedbackEntry.created_at.desc()).limit(limit).all()
        return {
            'featureKey': 'extension.foundation.continuous_feedback',
            'items': [row.to_dict() for row in rows],
            'total': len(rows),
            'limit': limit,
        }

    @staticmethod
    def stats(tenant_id: str, employee_id: Optional[str] = None) -> Dict[str, Any]:
        query = ContinuousFeedbackEntry.query.filter_by(tenant_id=tenant_id)
        if employee_id:
            query = query.filter_by(employee_id=employee_id)

        rows = query.all()
        by_type = {key: 0 for key in VALID_FEEDBACK_TYPES}
        by_sentiment = {'positive': 0, 'neutral': 0, 'negative': 0}
        by_status = {key: 0 for key in VALID_STATUSES}
        for row in rows:
            by_type[row.feedback_type] = by_type.get(row.feedback_type, 0) + 1
            by_sentiment[row.sentiment] = by_sentiment.get(row.sentiment, 0) + 1
            by_status[row.status] = by_status.get(row.status, 0) + 1

        return {
            'featureKey': 'extension.foundation.continuous_feedback',
            'stats': {
                'total': len(rows),
                'byType': by_type,
                'bySentiment': by_sentiment,
                'byStatus': by_status,
            },
        }

    @staticmethod
    def update_status(
        tenant_id: str,
        entry_id: str,
        status: str,
        handler_id: str,
        handler_reply: str = '',
    ) -> ContinuousFeedbackEntry:
        if status not in VALID_STATUSES:
            raise ValueError('反馈状态无效')
        entry = ContinuousFeedbackEntry.query.filter_by(id=entry_id, tenant_id=tenant_id).first()
        if not entry:
            raise LookupError('反馈不存在或无权访问')
        entry.status = status
        entry.handler_id = handler_id
        entry.handler_reply = handler_reply
        entry.handled_at = datetime.utcnow()
        return entry
