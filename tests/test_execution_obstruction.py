from datetime import date
from decimal import Decimal

import pytest

from investment_evidence_engine.execution_obstruction import (
    inspect_status_rows,
    ordinary_limits,
    tick_price,
)
from investment_evidence_engine.market_calendar import scheduled_days


def fixture():
    dates = tuple(r.day for r in scheduled_days(date(2025, 1, 2), date(2026, 11, 25)) if r.is_trading_day)
    rows = [[d.isoformat(), "sz.000035", "4.00", "4.00", "4.00", "4.00", "4.00",
             "100", "3", "1", "0"] for d in dates]
    return dates, rows


def test_tick_rounding():
    assert ordinary_limits(Decimal("4.35")) == (Decimal("3.92"), Decimal("4.79"))
    assert ordinary_limits(Decimal("0.04")) == (Decimal("0.03"), Decimal("0.05"))
    assert ordinary_limits(Decimal("0.01")) == (Decimal("0.01"), Decimal("0.02"))
    with pytest.raises(ValueError):
        tick_price("4.351")


def test_constant_profile_no_intents():
    dates, rows = fixture()
    report = inspect_status_rows(rows, identity="sz.000035", sessions=dates, event_references={})
    assert sum(r["intended_transitions"] for r in report["segments"]) == 0
    assert not report["actual_order_fills_verified"]


@pytest.mark.parametrize("index,value", [(0,"2024-01-01"), (1,"sz.000001"), (8,"2"),
                                        (9,"0"), (10,"1"), (10,""), (6,"4.01"), (3,"4.41")])
def test_invalid_rows_block(index, value):
    dates, rows = fixture()
    rows[50][index] = value
    with pytest.raises(ValueError):
        inspect_status_rows(rows, identity="sz.000035", sessions=dates, event_references={})


def test_intended_buy_at_limit_is_not_fill():
    dates, rows = fixture()
    rows[20][2:6] = ["4.01"] * 4
    rows[21][2:7] = ["4.41", "4.41", "4.41", "4.41", "4.01"]
    rows[22][6] = "4.41"
    report = inspect_status_rows(rows, identity="sz.000035", sessions=dates, event_references={})
    first = report["segments"][0]
    assert first["open_adverse_limit_count"] == 1
    assert first["full_day_adverse_one_price_count"] == 1
    assert first["flagged_intents"][0]["day"] == dates[21].isoformat()
