from datetime import date

import pytest

from investment_evidence_engine.historical_reference import DailyClose, HistoricalCloseSeries
from investment_evidence_engine.issuer_event_sensitivity import FIRST, LAST, event_sensitivity
from investment_evidence_engine.market_calendar import scheduled_days


def series(symbol, provider):
    days = [row.day for row in scheduled_days(FIRST, LAST) if row.is_trading_day]
    prices = [10 + i * 0.02 + (i % 3) * (0.03 if symbol == "000035" else 0.02)
              for i in range(len(days))]
    return HistoricalCloseSeries(subject_id=symbol, currency="CNY", price_basis="RAW_CLOSE",
                                 source_label=provider, closes=tuple(
                                     DailyClose(session=d, close=p) for d, p in zip(days, prices)))


def test_two_clock_sensitivity_without_selecting():
    inputs = tuple(series(code, provider) for code in ("000035", "510300")
                   for provider in ("sina", "tencent"))
    out = event_sensitivity(inputs)
    assert out["status"] == "WARN"
    assert out["event_day_conventions"] == ["2026-10-29", "2026-10-30"]
    assert len(out["variants"]) == 8
    assert [x["sessions"] for x in out["sensitivity_ranges"]] == [1, 3, 5]
    assert not out["convention_selected"] and not out["decision_authority"]
    assert not out["pit_safe"]


def test_one_source_missing_is_not_silently_accepted():
    inputs = (series("000035", "sina"), series("510300", "sina"))
    assert event_sensitivity(inputs)["status"] == "BLOCK"


def test_missing_session_fails_even_with_identical_providers():
    inputs = []
    for code in ("000035", "510300"):
        for provider in ("sina", "tencent"):
            item = series(code, provider)
            inputs.append(item.model_copy(update={"closes": tuple(x for x in item.closes
                         if x.session != date(2026, 10, 20))}))
    with pytest.raises(ValueError, match="EVENT_SESSION_COVERAGE_INCOMPLETE"):
        event_sensitivity(tuple(inputs))
