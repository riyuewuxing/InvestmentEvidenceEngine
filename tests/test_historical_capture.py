from datetime import date, datetime, timedelta, timezone

import pytest

from investment_evidence_engine import historical_capture as capture
from investment_evidence_engine.historical_capture import (
    PublicSecurity,
    _from_rows,
    observe_pair,
    sources_agree,
    validate_window,
)

END = date(2026, 11, 25)
START = END - timedelta(days=40)
DAYS = [START + timedelta(days=i) for i in range(41)
        if (START + timedelta(days=i)).weekday() < 5]
A = PublicSecurity(symbol="600519", asset_type="STOCK")
B = PublicSecurity(symbol="510050", asset_type="ETF")


def series(subject, source, multiplier=1):
    return _from_rows([[d.isoformat(), (100+i)*multiplier] for i,d in enumerate(DAYS)],
        subject, source, START, END)


def test_asset_type_routing_and_window():
    assert A.prefixed == "sh600519" and B.prefixed == "sh510050"
    assert PublicSecurity(symbol="159915", asset_type="ETF").prefixed == "sz159915"
    with pytest.raises(ValueError):
        PublicSecurity(symbol="510050", asset_type="STOCK").prefixed
    with pytest.raises(ValueError):
        validate_window(START, END, datetime(2026,11,25,6,tzinfo=timezone.utc))
    validate_window(START, END, datetime(2026,11,25,8,tzinfo=timezone.utc))


@pytest.mark.parametrize("fault", ["duplicate", "future", "nonfinite", "bool", "missing_end"])
def test_normalized_rows_fail_closed(fault):
    rows = [[d.isoformat(), 100.] for d in DAYS]
    if fault == "duplicate":
        rows.append(rows[-1])
    elif fault == "future":
        rows.append(["2026-11-26", 100.])
    elif fault == "nonfinite":
        rows[-1][1] = float("inf")
    elif fault == "bool":
        rows[-1][1] = True
    elif fault == "missing_end":
        rows.pop()
    with pytest.raises(ValueError):
        _from_rows(rows, A, "sina", START, END)


def test_source_conflict_retained_and_failed_asset_reported(monkeypatch):
    def fetch(source, subject, start, end):
        if source == "tencent" and subject == B:
            raise ValueError("WATCHDOG_TIMEOUT")
        return series(subject, source, 1.02 if source == "sina" else 1)
    monkeypatch.setattr(capture, "acquire_series", fetch)
    summary, found = observe_pair(A, B, START, END)
    assert len(found) == 2 and summary["crosscheck"] == "CONFLICT"
    assert {"provider": "tencent", "asset_type": "ETF", "error_code": "WATCHDOG_TIMEOUT"} in summary["failures"]
    assert not summary["reference"]["decision_authority"]
    assert not sources_agree(found[0][1], found[1][1])


def test_all_provider_failures_do_not_emit_prices(monkeypatch):
    def fail(*args):
        raise ValueError("WATCHDOG_TIMEOUT")
    monkeypatch.setattr(capture, "acquire_series", fail)
    summary, found = observe_pair(A,B,START,END)
    assert summary["status"] == "BLOCKED" and found == ()
    assert len(summary["failures"]) == 6 and "reference" not in summary
