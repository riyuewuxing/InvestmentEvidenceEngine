import json
from datetime import date

import pandas as pd
import pytest

from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.retrospective_control import (
    _metrics,
    parse_tencent_raw,
    retrospective_momentum,
    same_window_comparison,
)

FIRST = date(2025, 1, 2)
LAST = date(2026, 11, 25)


def raw(rows, *, key="day", symbol="sh600519"):
    return json.dumps({"code": 0, "data": {symbol: {key: rows}}}).encode()


def test_explicit_raw_order_and_outside_window_count():
    body = raw([["2024-12-31", "10", "11", "12", "9", "20"],
                ["2025-01-02", "20", "21", "22", "19", "40"]])
    frame, excluded = parse_tencent_raw(body, "600519", FIRST, LAST)
    assert excluded == 1
    assert frame.iloc[0][["open", "close", "high", "low", "volume"]].tolist() == [20, 21, 22, 19, 40]


@pytest.mark.parametrize("body", [
    raw([["2025-01-02", "20", "21", "22", "19", "40"]], key="qfqday"),
    raw([["2025-01-02", "20", "21", "22", "19", "40"]], symbol="sz000001"),
    raw([["2025-01-02", True, "21", "22", "19", "40"]]),
    raw([["2025-01-02", "20", "21", "18", "19", "40"]]),
    raw([["2025-01-02", "20", "21", "22", "19", "40"]] * 2),
    b'{"code":0,"code":1,"data":{}}',
])
def test_invalid_raw_blocks(body):
    with pytest.raises((ValueError, RuntimeError)):
        parse_tencent_raw(body, "600519", FIRST, LAST)


def bars():
    days = [item.day.isoformat() for item in scheduled_days(FIRST, LAST) if item.is_trading_day]
    return pd.DataFrame([{"date": d, "open": 100 + i / 10, "high": 102 + i / 10,
                          "low": 99 + i / 10, "close": 101 + i / 10,
                          "volume": 1000} for i, d in enumerate(days)])


def test_fixed_segments_and_price_only_boundary():
    result = retrospective_momentum(bars(), FIRST, LAST)
    assert result["pit_safe"] is False and result["execution_allowed"] is False
    assert result["test_segment_evaluations"] == 1
    seg = result["segments"]
    assert len(seg) == 3 and seg[0]["terminal_open"] < seg[1]["first_entry_open"]
    assert seg[1]["terminal_open"] < seg[2]["first_entry_open"]
    assert sum(s["intervals"] for s in seg) + 4 == result["eligible_intervals_before_split"]
    for s in seg:
        for stress in s["stress"]:
            assert stress["signal_rule"] == stress["constant_invested"]
            assert stress["flat_cash_assumed_zero_interest"]["net_price_change_pct"] == 0
        assert s["stress"][0]["signal_rule"]["net_price_change_pct"] > s["stress"][2]["signal_rule"]["net_price_change_pct"]


def test_missing_session_and_zero_volume_block():
    frame = bars()
    with pytest.raises(ValueError, match="SCHEDULE_COVERAGE_MISMATCH"):
        retrospective_momentum(frame.drop(index=30), FIRST, LAST)
    frame.loc[30, "volume"] = 0
    with pytest.raises(ValueError, match="ZERO_VOLUME_SESSION"):
        retrospective_momentum(frame, FIRST, LAST)


def test_entry_exit_cost_and_no_same_open_signal():
    result = _metrics([1.1, 0.9], [0, 1], 10)
    assert result["net_price_change_pct"] == pytest.approx((0.9 * 0.999 ** 2 - 1) * 100)
    assert result["unit_weight_turnover"] == 2
    frame = bars()
    baseline = retrospective_momentum(frame, FIRST, LAST)
    # A change in the very last close cannot enter any signal: the last
    # evaluated label ends at that day's open.
    frame.loc[len(frame) - 1, "close"] = frame.loc[len(frame) - 1, "low"]
    assert retrospective_momentum(frame, FIRST, LAST) == baseline


def test_comparison_does_not_silently_intersect_or_verify_volume():
    frame = bars()
    right = frame.copy()
    right["volume"] *= 100
    assert same_window_comparison(frame, right)["status"] == "MATCH_OBSERVED_ROWS"
    assert same_window_comparison(frame, right)["source_independence_verified"] is False
    assert same_window_comparison(frame, right.iloc[1:])["status"] == "DATE_COVERAGE_MISMATCH"
