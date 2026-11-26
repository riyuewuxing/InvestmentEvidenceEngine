from datetime import UTC, date, datetime, timedelta

import pytest

from investment_evidence_engine import historical_capture as capture
from investment_evidence_engine.historical_capture import (
    PublicSecurity,
    _from_rows,
    observe_pair,
    sources_agree,
    summarize_observed_pair,
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
        validate_window(START, END, datetime(2026,11,25,6,tzinfo=UTC))
    validate_window(START, END, datetime(2026,11,25,8,tzinfo=UTC))


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
    summary, found = observe_pair(A, B, START, END, providers=("sina", "tencent"))
    assert len(found) == 3 and summary["crosscheck"] == "CONFLICT"
    assert {"provider": "tencent", "asset_type": "ETF", "error_code": "WATCHDOG_TIMEOUT"} in summary["failures"]
    assert summary["status"] == "BLOCKED" and "reference" not in summary
    assert not sources_agree(found[0], found[2])


def test_mixed_source_observation_is_not_dual_source_verification(monkeypatch):
    def fetch(source, subject, start, end):
        if (source == "sina" and subject == A) or source == "tencent":
            raise ValueError("WATCHDOG_TIMEOUT")
        return series(subject, source)
    monkeypatch.setattr(capture, "acquire_series", fetch)
    summary, found = observe_pair(A, B, START, END, providers=("sina", "baostock", "tencent"))
    assert len(found) == 2
    assert summary["status"] == "OBSERVED_REFERENCE_ONLY"
    assert summary["crosscheck"] == "SINGLE_SOURCE_PER_ASSET"
    assert summary["candidate_providers"] == ["baostock"]
    assert summary["alternative_providers"] == ["sina"]
    assert not summary["reference"]["decision_authority"]
    assert not summary["reference"]["historical_vintage_verified"]


def test_conflicting_or_wrong_date_source_not_silently_dropped():
    left = series(A, "baostock")
    right = series(B, "sina")
    shifted = _from_rows([[d.isoformat(), 100.] for d in DAYS[1:]], B, "tencent", START, END)
    assert summarize_observed_pair(A, B, (left, right, shifted), START, END)["error_code"] == "SOURCE_CONFLICT"
    with pytest.raises(ValueError):
        summarize_observed_pair(A, B, (left, right, right), START, END)


def test_all_provider_failures_do_not_emit_prices(monkeypatch):
    def fail(*args):
        raise ValueError("WATCHDOG_TIMEOUT")
    monkeypatch.setattr(capture, "acquire_series", fail)
    summary, found = observe_pair(A, B, START, END)
    assert summary["status"] == "BLOCKED" and found == ()
    assert len(summary["failures"]) == 7 and "reference" not in summary


def test_crosscheck_requires_every_pair_not_only_first_provider():
    # Each outer source matches the middle source at 0.09%, but the outer
    # pair conflicts at about 0.18%. The result cannot depend on input order.
    middle, low, high = (series(A, "sina"), series(A, "baostock", .9991),
                         series(A, "tencent", 1.0009))
    etf = series(B, "sina")
    assert sources_agree(middle, low) and sources_agree(middle, high)
    assert not sources_agree(low, high)
    for ordered in ((middle, low, high, etf), (low, middle, high, etf),
                    (high, middle, low, etf)):
        result = summarize_observed_pair(A, B, ordered, START, END)
        assert result["status"] == "BLOCKED" and result["error_code"] == "SOURCE_CONFLICT"
