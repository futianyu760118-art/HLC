"""OA 排班读取（只读）：人员某天的班次与上下班时间。

数据来源（泛微 OA，全部只读固定 SELECT）：
- hrm_schedule_set_detail：field002=人员ID，field003=日期，field005=班次ID(多个用 ; 分隔，空=休息)
- hrm_schedule_worktime：field001=班次名，field002=上班时间，field003=下班时间，field007=时长
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from services.oa_employee_sync import OaReadOnlyClient


@dataclass(frozen=True)
class OaWorktime:
    worktime_id: int
    name: str
    start_time: str
    end_time: str
    hours: Decimal | None

    @property
    def crosses_midnight(self) -> bool:
        start = _minutes(self.start_time)
        end = _minutes(self.end_time)
        if start is None or end is None:
            return False
        return end <= start


@dataclass(frozen=True)
class OaScheduleDay:
    person_id: int
    schedule_date: date
    worktime_ids: tuple[int, ...]

    @property
    def is_rest(self) -> bool:
        return not self.worktime_ids


def _minutes(value: str) -> int | None:
    match = re.match(r'^(\d{1,2}):(\d{2})', (value or '').strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


class OaScheduleClient:
    """读取 OA 排班；对生产查询只读，不写 OA。"""

    SCHEDULE_SELECT = """
        SELECT
            field002 AS person_id,
            field003 AS schedule_date,
            field005 AS worktime_ids
        FROM FWsv.ecology.dbo.hrm_schedule_set_detail
        WHERE delflag = 0
          AND field003 >= '{start}'
          AND field003 <= '{end}'
        ORDER BY field003, field002
    """

    WORKTIME_SELECT = """
        SELECT
            id AS worktime_id,
            field001 AS name,
            field002 AS start_time,
            field003 AS end_time,
            field007 AS hours
        FROM FWsv.ecology.dbo.hrm_schedule_worktime
        WHERE delflag = 0
        ORDER BY id
    """

    def __init__(self, client: OaReadOnlyClient):
        self._client = client

    @classmethod
    def from_environment(cls) -> 'OaScheduleClient':
        return cls(OaReadOnlyClient.from_environment())

    def fetch_schedule(self, start: date, end: date) -> list[OaScheduleDay]:
        statement = self.SCHEDULE_SELECT.format(
            start=start.isoformat(), end=end.isoformat(),
        )
        result = []
        for row in self._client._fetch_dicts(statement):
            person_id = _to_int(row.get('person_id'))
            schedule_date = _to_date(row.get('schedule_date'))
            if person_id is None or schedule_date is None:
                continue
            result.append(OaScheduleDay(
                person_id=person_id,
                schedule_date=schedule_date,
                worktime_ids=_parse_ids(row.get('worktime_ids')),
            ))
        return result

    def fetch_worktimes(self) -> dict[int, OaWorktime]:
        result: dict[int, OaWorktime] = {}
        for row in self._client._fetch_dicts(self.WORKTIME_SELECT):
            worktime_id = _to_int(row.get('worktime_id'))
            if worktime_id is None:
                continue
            result[worktime_id] = OaWorktime(
                worktime_id=worktime_id,
                name=str(row.get('name') or '').strip(),
                start_time=str(row.get('start_time') or '').strip(),
                end_time=str(row.get('end_time') or '').strip(),
                hours=row.get('hours'),
            )
        return result


def _to_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()[:10]
    for pattern in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _parse_ids(value) -> tuple[int, ...]:
    if value is None:
        return ()
    ids = []
    for part in str(value).split(';'):
        parsed = _to_int(part)
        if parsed is not None:
            ids.append(parsed)
    return tuple(ids)
