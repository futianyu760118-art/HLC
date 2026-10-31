"""K3 ERP 只读取数（销售订单金额）。

通过 OA 的链接服务器 `k3sv` 访问金蝶 K3 数据库，仅执行固定只读 SELECT。
"""

from __future__ import annotations

from datetime import date, timedelta

from services.oa_employee_sync import OaReadOnlyClient

K3_DATABASE = 'AIS20161019115614'

ORDER_AMOUNT_SELECT = """
    SELECT
        COUNT(DISTINCT o.FInterID) AS order_count,
        ISNULL(SUM(e.FAmount), 0) AS amount,
        ISNULL(SUM(e.FTaxAmount), 0) AS tax_amount
    FROM k3sv.{database}.dbo.SEOrder o
    JOIN k3sv.{database}.dbo.SEOrderEntry e ON e.FInterID = o.FInterID
    WHERE o.FDate >= '{start}' AND o.FDate < '{end}'
      AND o.FStatus >= 1
      {dept_filter}
"""

DEPARTMENT_SELECT = """
    SELECT FItemID, FName
    FROM k3sv.{database}.dbo.t_Department
    WHERE ISNULL(FDeleted, 0) = 0
"""

# 销售出库毛利率：销售额取 FConsignAmount，成本取 FAmount（K3 出库成本）。
OUTBOUND_MARGIN_SELECT = """
    SELECT
        COUNT(DISTINCT b.FInterID) AS outbound_count,
        ISNULL(SUM(e.FConsignAmount), 0) AS sales_amount,
        ISNULL(SUM(e.FAmount), 0) AS cost_amount
    FROM k3sv.{database}.dbo.ICStockBill b
    JOIN k3sv.{database}.dbo.ICStockBillEntry e ON e.FInterID = b.FInterID
    WHERE b.FTranType = 21
      AND b.FDate >= '{start}' AND b.FDate < '{end}'
      AND b.FStatus >= 1
"""

# 新产品接单金额：当月「首次接单」的产品在本月的订单金额合计。
NEW_PRODUCT_SELECT = """
    SELECT
        COUNT(DISTINCT e.FItemID) AS new_item_count,
        ISNULL(SUM(e.FAmount), 0) AS amount
    FROM k3sv.{database}.dbo.SEOrder o
    JOIN k3sv.{database}.dbo.SEOrderEntry e ON e.FInterID = o.FInterID
    JOIN (
        SELECT e2.FItemID AS item_id, MIN(o2.FDate) AS first_date
        FROM k3sv.{database}.dbo.SEOrder o2
        JOIN k3sv.{database}.dbo.SEOrderEntry e2 ON e2.FInterID = o2.FInterID
        WHERE o2.FStatus >= 1
        GROUP BY e2.FItemID
    ) f ON f.item_id = e.FItemID
    WHERE o.FStatus >= 1
      AND o.FDate >= '{start}' AND o.FDate < '{end}'
      AND f.first_date >= '{start}' AND f.first_date < '{end}'
      {dept_filter}
"""


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(part) for part in month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    return start, end


def resolve_department_id(dept_name: str, *, client: OaReadOnlyClient | None = None) -> int | None:
    """按名称解析 K3 部门 ID（名称在 Python 侧比对，避免查询串编码问题）。"""
    name = (dept_name or '').strip()
    if not name:
        return None
    reader = client or OaReadOnlyClient.from_environment()
    rows = reader._fetch_dicts(DEPARTMENT_SELECT.format(database=K3_DATABASE))
    for row in rows:
        if str(row.get('FName') or '').strip() == name:
            try:
                return int(row.get('FItemID'))
            except (TypeError, ValueError):
                return None
    return None


def _dept_filter(reader, dept_name: str | None, alias: str) -> tuple[str, int | None]:
    """返回 (SQL 片段, K3 部门ID)。未指定部门返回 ('', None)。"""
    if not dept_name:
        return '', None
    dept_id = resolve_department_id(dept_name, client=reader)
    if dept_id is None:
        raise ValueError(f'K3 未找到部门：{dept_name}')
    return f'AND {alias}.FDeptID = {dept_id}', dept_id


def fetch_order_amount(
    month: str,
    *,
    dept_name: str | None = None,
    client: OaReadOnlyClient | None = None,
) -> dict:
    """取某月「接单金额」（销售订单金额合计，仅统计已审核 FStatus>=1）。

    dept_name 指定时按 K3 销售部门过滤（如「销售一部」）。
    """
    start, end = _month_bounds(month)
    reader = client or OaReadOnlyClient.from_environment()
    dept_filter, dept_id = _dept_filter(reader, dept_name, 'o')
    statement = ORDER_AMOUNT_SELECT.format(
        database=K3_DATABASE, start=start.isoformat(), end=end.isoformat(),
        dept_filter=dept_filter,
    )
    rows = reader._fetch_dicts(statement)
    row = rows[0] if rows else {}
    return {
        'month': month,
        'departmentId': dept_id,
        'orderCount': int(row.get('order_count') or 0),
        'amount': float(row.get('amount') or 0),
        'taxAmount': float(row.get('tax_amount') or 0),
    }


def fetch_outbound_margin(month: str, *, client: OaReadOnlyClient | None = None) -> dict:
    """取某月「销售出库毛利率」。

    - 销售额 = 销售出库单 FConsignAmount 合计（仅已审核 FStatus>=1）
    - 成本额 = 销售出库单 FAmount 合计（K3 出库成本）
    - 毛利率 = (销售额 - 成本额) / 销售额

    注意：口径为「出库」而非「接单」；成本依赖 K3 出库成本数据是否已生成。
    """
    start, end = _month_bounds(month)
    reader = client or OaReadOnlyClient.from_environment()
    statement = OUTBOUND_MARGIN_SELECT.format(
        database=K3_DATABASE, start=start.isoformat(), end=end.isoformat(),
    )
    rows = reader._fetch_dicts(statement)
    row = rows[0] if rows else {}
    sales = float(row.get('sales_amount') or 0)
    cost = float(row.get('cost_amount') or 0)
    profit = sales - cost
    margin = (profit / sales) if sales else 0.0
    return {
        'month': month,
        'outboundCount': int(row.get('outbound_count') or 0),
        'salesAmount': round(sales, 2),
        'costAmount': round(cost, 2),
        'grossProfit': round(profit, 2),
        'grossMargin': round(margin, 4),
    }


def fetch_new_product_order_amount(
    month: str,
    *,
    dept_name: str | None = None,
    client: OaReadOnlyClient | None = None,
) -> dict:
    """取某月「新产品接单金额」：当月首次接单的产品在本月的销售订单金额合计。

    「新产品」判定 = 该产品在全部历史销售订单中的首次下单日期落在本月。
    dept_name 指定时按 K3 销售部门过滤。
    """
    start, end = _month_bounds(month)
    reader = client or OaReadOnlyClient.from_environment()
    dept_filter, dept_id = _dept_filter(reader, dept_name, 'o')
    statement = NEW_PRODUCT_SELECT.format(
        database=K3_DATABASE, start=start.isoformat(), end=end.isoformat(),
        dept_filter=dept_filter,
    )
    rows = reader._fetch_dicts(statement)
    row = rows[0] if rows else {}
    return {
        'month': month,
        'departmentId': dept_id,
        'newProductCount': int(row.get('new_item_count') or 0),
        'amount': float(row.get('amount') or 0),
    }
