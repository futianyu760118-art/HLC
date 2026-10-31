"""Business wall-clock handling for HR schedules.

HR events are entered and displayed as local business times. Store these
values as naive datetimes in the existing schema, but normalize any zoned
input to the configured business timezone before persistence.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 local test runtime
    ZoneInfo = None


BUSINESS_TIMEZONE = os.getenv('BUSINESS_TIMEZONE', 'Asia/Shanghai')


def _timezone():
    try:
        if ZoneInfo is not None:
            return ZoneInfo(BUSINESS_TIMEZONE)
    except Exception:
        pass
    return timezone(timedelta(hours=8), name='Asia/Shanghai')


def business_now() -> datetime:
    """Return current local business time without tzinfo for DB comparisons."""
    return datetime.now(_timezone()).replace(tzinfo=None)


def parse_business_datetime(value) -> Optional[datetime]:
    """Normalize local/offset ISO input into a naive local business datetime."""
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_timezone()).replace(tzinfo=None)
    return parsed
