"""Quarantined continuous-feedback service.

Claude Code added routes for 1-on-1 and continuous feedback before the
corresponding ORM models and migrations existed. The routes remain unregistered;
this module is intentionally importable so repository-wide compile/import checks
do not fail while making accidental runtime use explicit.
"""

from __future__ import annotations

from typing import Any, Dict, List


FEATURE_DISABLED_REASON = (
    'Continuous feedback models are not registered. Keep routes/feedback_api.py '
    'unregistered until OneOnOneMeeting and ContinuousFeedback models, migrations, '
    'tenant tests, and browser coverage are implemented.'
)


def _raise_quarantined() -> None:
    raise RuntimeError(FEATURE_DISABLED_REASON)


class FeedbackService:
    """Explicit placeholder for the unfinished continuous-feedback feature."""

    @staticmethod
    def create_one_on_one(
        tenant_id: str,
        employee_id: str,
        manager_id: str,
        meeting_date: Any,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        _raise_quarantined()

    @staticmethod
    def get_employee_meetings(
        tenant_id: str,
        employee_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        _raise_quarantined()

    @staticmethod
    def create_feedback(
        tenant_id: str,
        employee_id: str,
        giver_id: str,
        feedback_type: str,
        category: str,
        content: str,
        is_private: bool = True,
    ) -> Dict[str, Any]:
        _raise_quarantined()

    @staticmethod
    def get_employee_feedback(
        tenant_id: str,
        employee_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        _raise_quarantined()

    @staticmethod
    def get_feedback_stats(tenant_id: str, employee_id: str) -> Dict[str, Any]:
        _raise_quarantined()
