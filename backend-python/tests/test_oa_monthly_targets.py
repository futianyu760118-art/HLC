from __future__ import annotations

from decimal import Decimal

from services.oa_monthly_targets import OaTargetClient, fetch_month_target


class _FakeReader:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    def _fetch_dicts(self, statement):
        self.statements.append(statement)
        return self._rows


def test_fetch_month_target_returns_wan():
    reader = _FakeReader([{'mb': Decimal('274.00')}])
    client = OaTargetClient(reader)
    result = client.fetch_month_target(37, '2026-09')
    assert result == Decimal('274.00')
    statement = reader.statements[0]
    assert 'uf_ndmbdr' in statement
    assert 'bm = 37' in statement
    assert "yd = '2026-09'" in statement


def test_fetch_month_target_handles_empty_and_bad_input():
    reader = _FakeReader([])
    client = OaTargetClient(reader)
    assert client.fetch_month_target(37, '2026-09') is None
    assert client.fetch_month_target(None, '2026-09') is None
    assert client.fetch_month_target(37, 'bad-month') is None


def test_fetch_month_target_convenience_uses_client():
    reader = _FakeReader([{'mb': Decimal('100')}])
    client = OaTargetClient(reader)
    assert fetch_month_target(36, '2026-09', client=client) == Decimal('100')
