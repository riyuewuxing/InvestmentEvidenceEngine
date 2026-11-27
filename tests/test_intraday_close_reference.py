from datetime import UTC, date, datetime

import pytest

from investment_evidence_engine.intraday_close_reference import (
    expected_endpoints,
    normalized_closes,
    retrospective_t_close_sensitivity,
)

DAY = date(2026, 11, 27)
NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)


def rows():
    return [{"time": f"2026-11-27 {t}:00", "open": "10", "high": "10.2", "low": "9.8",
             "close": "10.1" if t == "14:30" else "10", "volume": "100",
             "code": "sz.000001", "adjustflag": "3"} for t in expected_endpoints(DAY)]


def norm(data, source="baostock"):
    return normalized_closes(data, session=DAY, source=source, symbol="000001")


def daily():
    return dict(date=DAY.isoformat(), code="sz.000001", preclose="10", close="10", high="10.2",
                low="9.8", open="10", adjustflag="3", tradestatus="1", isST="0", calendar_open=True)


def test_fixed_session_and_zero_spread_retrospective_is_not_execution():
    a, b = norm(rows()), norm(rows(), "sina")
    assert a["count"] == 48 and a["complete"]
    out = retrospective_t_close_sensitivity(a, b, daily(), session=DAY, evaluated_at=NOW)
    assert out["status"] == "RETROSPECTIVE_CLOSE_SENSITIVITY_ONLY"
    assert out["close_crosscheck"] == "MATCH"
    assert out["close_change_10_to_1430_pct"] == 1
    assert out["conditional_results"]["positive_t"]["matched_net_cash_delta_cny"] == "-0.53"
    assert out["actual_fills_verified"] is False and out["bid_ask_observed"] is False


def test_source_conflict_and_missing_primary_bar_block():
    data = rows()
    data[0]["close"] = "10.01"
    out = retrospective_t_close_sensitivity(norm(rows()), norm(data, "sina"), daily(), session=DAY, evaluated_at=NOW)
    assert out["reason"] == "MINUTE_SOURCE_CLOSE_CONFLICT"
    out = retrospective_t_close_sensitivity(norm(rows()[1:]), None, daily(), session=DAY, evaluated_at=NOW)
    assert out["reason"] == "PRIMARY_COMPLETE_SESSION_REQUIRED"


def test_daily_reference_conflict_and_same_day_before_close_block():
    out = retrospective_t_close_sensitivity(norm(rows()), None, daily() | {"close": "10.01"}, session=DAY, evaluated_at=NOW)
    assert out["reason"] == "MINUTE_DAILY_OHLC_CONFLICT"
    with pytest.raises(ValueError):
        retrospective_t_close_sensitivity(norm(rows()), None, daily(), session=DAY,
                                           evaluated_at=datetime(2026, 11, 27, 6, tzinfo=UTC))


def test_duplicates_bad_adjustment_and_lunch_bar_fail_closed():
    data = rows()
    with pytest.raises(ValueError):
        norm(data + [data[0]])
    data[0]["adjustflag"] = "2"
    with pytest.raises(ValueError):
        norm(data)
    data = rows()
    data[0]["time"] = "2026-11-27 12:00:00"
    with pytest.raises(ValueError):
        norm(data)
