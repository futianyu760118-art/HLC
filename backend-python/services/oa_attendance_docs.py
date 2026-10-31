"""OA 考勤单据读取（只读）：请假 / 加班 / 补考勤 / 调休 / 外出 / 出差。

数据来源（泛微 OA，全部只读固定 SELECT）：
- 请假：formtable_main_17（ITEM_START_T/ITEM_LEAVE_T 起止、ITEM_LEAVE_D 小时、qjlx 类型）
- 加班：formtable_main_41 + formtable_main_41_dt1（jbkssj/jbjssj 起止、jbsc 小时、overtime_type）
- 补考勤：formtable_main_35 + formtable_main_35_dt1（bkqsj 补卡时间点）
- 调休：formtable_main_43（start_t/over_t 起止、Paidleave_time 小时）
- 外出：formtable_main_18（wcsj/fhsj 起止）
- 出差：formtable_main_15（ITEM_Travel_st/ITEM_Travel_ot 日期段）

只有流程结束（workflow_requestbase.currentnodetype = 3）且未删除的请求会被读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from services.oa_employee_sync import OaReadOnlyClient

LEAVE = 'leave'
COMPENSATORY = 'compensatory'
OVERTIME = 'overtime'
PUNCH_FIX = 'punch_fix'
OUTING = 'outing'
BUSINESS_TRIP = 'business_trip'

# 只有这四类会影响工时/缺卡判定；外出/出差当前仅标记，不参与计算（业务待定）。
AFFECTS_HOURS = {
    LEAVE: True,
    COMPENSATORY: True,
    OVERTIME: True,
    PUNCH_FIX: False,
    OUTING: False,
    BUSINESS_TRIP: False,
}

APPROVED_JOIN = """
    INNER JOIN FWsv.ecology.dbo.workflow_requestbase r ON r.requestid = {request_column}
    WHERE r.currentnodetype = 3
      AND (r.deleted IS NULL OR r.deleted = 0 OR r.deleted = '0')
"""


@dataclass(frozen=True)
class OaAttendanceDoc:
    event_type: str
    source_key: str
    oa_form_table: str
    oa_main_id: str
    employee_no: str | None = None
    oa_person_id: str | None = None
    oa_department_id: str | None = None
    oa_request_id: str | None = None
    oa_workflow_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    hours: Decimal | None = None
    subtype: str | None = None
    reason: str | None = None

    @property
    def affects_hours(self) -> bool:
        return AFFECTS_HOURS.get(self.event_type, False)


class OaAttendanceDocClient:
    """读取 OA 考勤单据；对生产库只读，不写 OA。"""

    LEAVE_SELECT = """
        SELECT
            f.id AS main_id,
            f.requestId AS request_id,
            f.ITEM_APPLICANTID AS oa_person_id,
            f.ITEM_EMPCODE AS employee_no,
            f.ITEM_DEPT AS department_id,
            f.ITEM_START_T AS start_time,
            f.ITEM_LEAVE_T AS end_time,
            f.ITEM_LEAVE_D AS hours,
            f.qjlx AS subtype,
            f.ITEM_LEAVE_R AS reason
        FROM FWsv.ecology.dbo.formtable_main_17 f
    """ + APPROVED_JOIN.format(request_column='f.requestId') + """
          AND f.ITEM_START_T >= '{start}'
          AND f.ITEM_START_T < '{end}'
        ORDER BY f.id
    """

    OVERTIME_SELECT = """
        SELECT
            m.id AS main_id,
            m.requestId AS request_id,
            m.applicant AS oa_person_id,
            m.empcode AS employee_no,
            m.dept AS department_id,
            m.overtime_type AS subtype,
            m.overtime_r AS reason,
            d.id AS detail_id,
            d.jbkssj AS start_time,
            d.jbjssj AS end_time,
            d.jbsc AS hours,
            d.jbyy AS detail_reason
        FROM FWsv.ecology.dbo.formtable_main_41 m
        INNER JOIN FWsv.ecology.dbo.formtable_main_41_dt1 d ON d.mainid = m.id
        INNER JOIN FWsv.ecology.dbo.workflow_requestbase r ON r.requestid = m.requestId
        WHERE r.currentnodetype = 3
          AND (r.deleted IS NULL OR r.deleted = 0 OR r.deleted = '0')
          AND d.jbkssj >= '{start}'
          AND d.jbkssj < '{end}'
        ORDER BY d.id
    """

    PUNCH_FIX_SELECT = """
        SELECT
            m.id AS main_id,
            m.requestId AS request_id,
            m.ITEM_applicantid AS oa_person_id,
            m.ITEM_empcode AS employee_no,
            m.ITEM_dept AS department_id,
            m.ITEM_attendance_r AS reason,
            d.id AS detail_id,
            d.bkqsj AS start_time
        FROM FWsv.ecology.dbo.formtable_main_35 m
        INNER JOIN FWsv.ecology.dbo.formtable_main_35_dt1 d ON d.mainid = m.id
        INNER JOIN FWsv.ecology.dbo.workflow_requestbase r ON r.requestid = m.requestId
        WHERE r.currentnodetype = 3
          AND (r.deleted IS NULL OR r.deleted = 0 OR r.deleted = '0')
          AND d.bkqsj >= '{start}'
          AND d.bkqsj < '{end}'
        ORDER BY d.id
    """

    COMPENSATORY_SELECT = """
        SELECT
            m.id AS main_id,
            m.requestId AS request_id,
            m.applicant AS oa_person_id,
            m.empcode AS employee_no,
            m.dept AS department_id,
            m.start_t AS start_time,
            m.over_t AS end_time,
            m.Paidleave_time AS hours,
            m.Paidleave_reason AS reason
        FROM FWsv.ecology.dbo.formtable_main_43 m
    """ + APPROVED_JOIN.format(request_column='m.requestId') + """
          AND m.start_t >= '{start}'
          AND m.start_t < '{end}'
        ORDER BY m.id
    """

    OUTING_SELECT = """
        SELECT
            m.id AS main_id,
            m.requestId AS request_id,
            m.sqr AS oa_person_id,
            m.gh AS employee_no,
            m.sqbm AS department_id,
            m.wcsj AS start_time,
            m.fhsj AS end_time,
            m.wcsy AS reason
        FROM FWsv.ecology.dbo.formtable_main_18 m
    """ + APPROVED_JOIN.format(request_column='m.requestId') + """
          AND m.wcsj >= '{start}'
          AND m.wcsj < '{end}'
        ORDER BY m.id
    """

    BUSINESS_TRIP_SELECT = """
        SELECT
            m.id AS main_id,
            m.requestId AS request_id,
            m.ITEM_applicant AS oa_person_id,
            m.ITEM_empcode AS employee_no,
            m.ITEM_dept AS department_id,
            m.ITEM_Travel_st AS start_time,
            m.ITEM_Travel_ot AS end_time,
            m.ITEM_Travel_r AS reason
        FROM FWsv.ecology.dbo.formtable_main_15 m
    """ + APPROVED_JOIN.format(request_column='m.requestId') + """
          AND m.ITEM_Travel_st >= '{start}'
          AND m.ITEM_Travel_st < '{end}'
        ORDER BY m.id
    """

    def __init__(self, client: OaReadOnlyClient):
        self._client = client

    @classmethod
    def from_environment(cls) -> 'OaAttendanceDocClient':
        return cls(OaReadOnlyClient.from_environment())

    def fetch_documents(self, start: date, end: date) -> list[OaAttendanceDoc]:
        """读取 [start, end) 内的已审批考勤单据。"""
        start_str = start.isoformat()
        end_str = end.isoformat()
        documents: list[OaAttendanceDoc] = []
        documents.extend(self._fetch(self.LEAVE_SELECT, start_str, end_str, self._map_leave, LEAVE))
        documents.extend(self._fetch(self.OVERTIME_SELECT, start_str, end_str, self._map_overtime, OVERTIME))
        documents.extend(self._fetch(self.PUNCH_FIX_SELECT, start_str, end_str, self._map_punch_fix, PUNCH_FIX))
        documents.extend(self._fetch(
            self.COMPENSATORY_SELECT, start_str, end_str, self._map_compensatory, COMPENSATORY,
        ))
        documents.extend(self._fetch(self.OUTING_SELECT, start_str, end_str, self._map_outing, OUTING))
        documents.extend(self._fetch(
            self.BUSINESS_TRIP_SELECT, start_str, end_str, self._map_business_trip, BUSINESS_TRIP,
        ))
        return documents

    def _fetch(self, template, start, end, mapper, event_type):
        statement = template.format(start=start, end=end)
        result = []
        for row in self._client._fetch_dicts(statement):
            mapped = mapper(row)
            if mapped is not None:
                result.append(mapped)
        return result

    def _map_leave(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        if not main_id:
            return None
        return OaAttendanceDoc(
            event_type=LEAVE,
            source_key=f'{LEAVE}:{main_id}',
            oa_form_table='formtable_main_17',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=_to_datetime(row.get('start_time')),
            end_at=_to_datetime(row.get('end_time')),
            hours=_to_decimal(row.get('hours')),
            subtype=_to_str(row.get('subtype')),
            reason=_clean(row.get('reason')),
        )

    def _map_overtime(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        detail_id = _to_str(row.get('detail_id'))
        if not main_id or not detail_id:
            return None
        return OaAttendanceDoc(
            event_type=OVERTIME,
            source_key=f'{OVERTIME}:{detail_id}',
            oa_form_table='formtable_main_41',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=_to_datetime(row.get('start_time')),
            end_at=_to_datetime(row.get('end_time')),
            hours=_to_decimal(row.get('hours')),
            subtype=_to_str(row.get('subtype')),
            reason=_clean(row.get('detail_reason')) or _clean(row.get('reason')),
        )

    def _map_punch_fix(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        detail_id = _to_str(row.get('detail_id'))
        if not main_id or not detail_id:
            return None
        return OaAttendanceDoc(
            event_type=PUNCH_FIX,
            source_key=f'{PUNCH_FIX}:{detail_id}',
            oa_form_table='formtable_main_35',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=_to_datetime(row.get('start_time')),
            end_at=_to_datetime(row.get('start_time')),
            subtype=None,
            reason=_clean(row.get('reason')),
        )

    def _map_compensatory(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        if not main_id:
            return None
        return OaAttendanceDoc(
            event_type=COMPENSATORY,
            source_key=f'{COMPENSATORY}:{main_id}',
            oa_form_table='formtable_main_43',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=_to_datetime(row.get('start_time')),
            end_at=_to_datetime(row.get('end_time')),
            hours=_to_decimal(row.get('hours')),
            subtype=None,
            reason=_clean(row.get('reason')),
        )

    def _map_outing(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        if not main_id:
            return None
        return OaAttendanceDoc(
            event_type=OUTING,
            source_key=f'{OUTING}:{main_id}',
            oa_form_table='formtable_main_18',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=_to_datetime(row.get('start_time')),
            end_at=_to_datetime(row.get('end_time')),
            subtype=None,
            reason=_clean(row.get('reason')),
        )

    def _map_business_trip(self, row) -> OaAttendanceDoc | None:
        main_id = _to_str(row.get('main_id'))
        if not main_id:
            return None
        start_at = _to_datetime(row.get('start_time'))
        end_at = _to_datetime(row.get('end_time'))
        if start_at is not None:
            start_at = datetime.combine(start_at.date(), time(0, 0))
        if end_at is not None:
            end_at = datetime.combine(end_at.date(), time(23, 59, 59))
        return OaAttendanceDoc(
            event_type=BUSINESS_TRIP,
            source_key=f'{BUSINESS_TRIP}:{main_id}',
            oa_form_table='formtable_main_15',
            oa_main_id=main_id,
            employee_no=_clean(row.get('employee_no')),
            oa_person_id=_to_str(row.get('oa_person_id')),
            oa_department_id=_to_str(row.get('department_id')),
            oa_request_id=_to_str(row.get('request_id')),
            start_at=start_at,
            end_at=end_at,
            subtype=None,
            reason=_clean(row.get('reason')),
        )


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _to_datetime(value) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0))
    text = str(value).strip()
    for pattern in (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y/%m/%d %H:%M:%S',
        '%Y/%m/%d %H:%M',
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%Y%m%d',
    ):
        try:
            return datetime.strptime(text[:19], pattern)
        except ValueError:
            continue
    return None
