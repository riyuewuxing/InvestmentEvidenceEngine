from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from investment_evidence_engine.public_prediction_pilot import (
    SYMBOL,
    calendar_rows_expected,
    freeze,
    input_sessions,
    preregistration,
    verify_frozen,
)

CLOCK = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)


def rows(close="10.10"):
    return [[d, "sh." + SYMBOL, "10.00", close, "100", "3", "1"] for d in input_sessions()]


def test_fixed_control_receipt_and_tamper():
    result = freeze(calendar_rows_expected(), rows(), started=CLOCK, observed=CLOCK)
    assert result["direction"] == "UP"
    assert result["outcome"] is None
    assert result["execution_allowed"] is False
    assert preregistration()["first_target"] == "2026-11-27"
    verify_frozen(result)
    bad = deepcopy(result)
    bad["observation"]["daily_rows"][0][3] = "9"
    with pytest.raises(ValueError):
        verify_frozen(bad)


@pytest.mark.parametrize(("close", "direction"), [("10.01", "FLAT"), ("9.99", "FLAT"), ("9.98", "DOWN")])
def test_threshold(close, direction):
    assert freeze(calendar_rows_expected(), rows(close), started=CLOCK, observed=CLOCK)["direction"] == direction


@pytest.mark.parametrize("mutation", ["calendar", "future", "missing", "duplicate", "halt", "adjusted", "nan", "symbol"])
def test_fail_closed(mutation):
    cal, data = calendar_rows_expected(), rows()
    if mutation == "calendar":
        cal.pop()
    elif mutation == "future":
        data[-1][0] = "2026-11-26"
    elif mutation == "missing":
        data.pop()
    elif mutation == "duplicate":
        data[-1] = data[-2]
    elif mutation == "halt":
        data[0][-1] = "0"
    elif mutation == "adjusted":
        data[0][-2] = "2"
    elif mutation == "nan":
        data[0][2] = "NaN"
    else:
        data[0][1] = "sh.600000"
    with pytest.raises(ValueError):
        freeze(cal, data, started=CLOCK, observed=CLOCK)


def test_clock_and_no_backfill():
    for t in (CLOCK.replace(tzinfo=None), CLOCK + timedelta(days=1), CLOCK - timedelta(days=1),
              CLOCK + timedelta(seconds=121)):
        with pytest.raises(ValueError):
            freeze(calendar_rows_expected(), rows(), started=CLOCK, observed=t)
