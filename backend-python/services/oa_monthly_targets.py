"""OA 月度目标读取（只读）：部门 + 月份 → 目标值。

数据来源（泛微 OA，只读固定 SELECT）：
- uf_ndmbdr：年度目标按部门按月分解。nd=年度、bm=部门ID(HrmDepartment.id)、
  yd=月份(YYYY-MM)、mb=目标（单位：万元）。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from services.oa_employee_sync import OaReadOnlyClient

WAN = Decimal('10000')


class OaTargetClient:
    """读取 OA 月度目标；对生产库只读，不写 OA。"""

    TARGET_SELECT = """
        SELECT TOP 1 mb
        FROM FWsv.ecology.dbo.uf_ndmbdr
        WHERE bm = {department_id} AND yd = '{month}'
        ORDER BY id DESC
    """

    def __init__(self, client: OaReadOnlyClient):
        self._client = client

    @classmethod
    def from_environment(cls) -> 'OaTargetClient':
        return cls(OaReadOnlyClient.from_environment())

    def fetch_month_target(self, department_id, month: str) -> Decimal | None:
        """返回某部门某月的目标值（单位：万元）；查不到返回 None。"""
        if department_id in (None, ''):
            return None
        if not re.fullmatch(r'\d{4}-\d{2}', str(month or '')):
            return None
        statement = self.TARGET_SELECT.format(
            department_id=int(department_id), month=str(month).strip(),
        )
        rows = self._client._fetch_dicts(statement)
        if not rows:
            return None
        value = rows[0].get('mb')
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return None


def fetch_month_target(department_id, month: str, *, client=None) -> Decimal | None:
    """便捷函数：取部门月度目标（万元）。"""
    reader = client or OaTargetClient.from_environment()
    return reader.fetch_month_target(department_id, month)
