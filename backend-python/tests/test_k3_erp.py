from __future__ import annotations

from decimal import Decimal

import pytest

from services.k3_erp import (
    fetch_order_amount,
    fetch_outbound_margin,
    fetch_new_product_order_amount,
)


class _FakeReader:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    def _fetch_dicts(self, statement):
        self.statements.append(statement)
        return self._rows


def test_fetch_order_amount_parses_month_total():
    reader = _FakeReader([
        {'order_count': 34, 'amount': Decimal('583051.26'), 'tax_amount': Decimal('2024.70')},
    ])
    result = fetch_order_amount('2026-09', client=reader)

    assert result['month'] == '2026-09'
    assert result['orderCount'] == 34
    assert result['amount'] == 583051.26
    assert result['taxAmount'] == 2024.7

    statement = reader.statements[0]
    assert 'SEOrder' in statement and 'SEOrderEntry' in statement
    assert "2026-09-01" in statement and "2026-10-01" in statement
    assert statement.lstrip().upper().startswith('SELECT')


def test_fetch_order_amount_handles_empty():
    reader = _FakeReader([])
    result = fetch_order_amount('2026-09', client=reader)
    assert result['orderCount'] == 0
    assert result['amount'] == 0.0


def test_fetch_outbound_margin_computes_ratio():
    reader = _FakeReader([
        {'outbound_count': 45, 'sales_amount': Decimal('2698191.14'), 'cost_amount': Decimal('737534.77')},
    ])
    result = fetch_outbound_margin('2026-09', client=reader)

    assert result['month'] == '2026-09'
    assert result['outboundCount'] == 45
    assert result['salesAmount'] == 2698191.14
    assert result['costAmount'] == 737534.77
    assert result['grossProfit'] == 1960656.37
    assert result['grossMargin'] == 0.7267

    statement = reader.statements[0]
    assert 'ICStockBill' in statement and 'ICStockBillEntry' in statement
    assert 'b.FTranType = 21' in statement
    assert "2026-09-01" in statement and "2026-10-01" in statement


def test_fetch_outbound_margin_handles_empty():
    reader = _FakeReader([])
    result = fetch_outbound_margin('2026-09', client=reader)
    assert result['salesAmount'] == 0.0
    assert result['grossProfit'] == 0.0
    assert result['grossMargin'] == 0.0


def test_fetch_new_product_order_amount_parses_result():
    reader = _FakeReader([
        {'new_item_count': 17, 'amount': Decimal('191901.84')},
    ])
    result = fetch_new_product_order_amount('2026-09', client=reader)

    assert result['month'] == '2026-09'
    assert result['newProductCount'] == 17
    assert result['amount'] == 191901.84

    statement = reader.statements[0]
    assert 'SEOrder' in statement and 'MIN(o2.FDate)' in statement
    assert "2026-09-01" in statement and "2026-10-01" in statement


def test_fetch_new_product_order_amount_handles_empty():
    reader = _FakeReader([])
    result = fetch_new_product_order_amount('2026-09', client=reader)
    assert result['newProductCount'] == 0
    assert result['amount'] == 0.0


class _RoutedReader:
    def __init__(self):
        self.statements = []

    def _fetch_dicts(self, statement):
        self.statements.append(statement)
        if 't_Department' in statement:
            return [{'FItemID': 34790, 'FName': '销售一部'}]
        return [{'order_count': 10, 'amount': Decimal('726357.69'), 'tax_amount': Decimal('0')}]


def test_fetch_order_amount_filters_by_department():
    reader = _RoutedReader()
    result = fetch_order_amount('2026-09', dept_name='销售一部', client=reader)
    assert result['amount'] == 726357.69
    assert result['departmentId'] == 34790
    assert 'FDeptID = 34790' in reader.statements[-1]


def test_fetch_order_amount_unknown_department_raises():
    class _Empty(_RoutedReader):
        def _fetch_dicts(self, statement):
            self.statements.append(statement)
            return []

    with pytest.raises(ValueError):
        fetch_order_amount('2026-09', dept_name='不存在的部门', client=_Empty())
