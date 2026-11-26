from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.market_worker import (
    _bounded_frame,
    _crosscheck,
    _window,
    run_market_data_resilient,
)
from investment_evidence_engine.providers import ProviderError
from investment_evidence_engine.workers import WorkerContext


@pytest.fixture
def ctx(tmp_path):
    return WorkerContext(output_dir=tmp_path, request_as_of="2026-11-26",
                         clock=lambda: datetime(2026, 11, 26, 16, tzinfo=ZoneInfo("Asia/Shanghai")))


def op(**kwargs):
    return ExecutionOperation(operation_id="market", kind="MARKET_DATA",
                              parameters={"as_of": "2026-11-26", "subject_ids": ["600519"], **kwargs})


def frame(days=("2026-11-24", "2026-11-25")):
    return pd.DataFrame([{"date": d, "open": 10, "high": 12, "low": 9, "close": 11,
                          "volume": 100} for d in days])


def test_calendar_offset_honored(ctx):
    start, end, offset = _window(op(history_end_offset_days=1).parameters, ctx)
    assert (end, offset) == (date(2026, 11, 25), 1)
    assert (end - start).days == 450


@pytest.mark.parametrize(("stamp", "expected"), [
    ("2026-11-26T06:00:00+00:00", date(2026, 11, 25)),
    ("2026-11-26T07:30:00+00:00", date(2026, 11, 26)),
    ("2026-11-25T17:00:00-05:00", date(2026, 11, 25)),
])
def test_precise_market_timezone(ctx, stamp, expected):
    ctx.request_as_of = stamp
    assert _window(op(as_of=stamp).parameters, ctx)[1] == expected


@pytest.mark.parametrize("extra", [
    {"as_of": "2026-11-25"}, {"history_days": True}, {"history_end_offset_days": -1},
    {"history_end_offset_days": True}, {"price_tolerance": float("inf")},
    {"subject_ids": ["600519", "000001"]}, {"adjust": "unknown"},
    {"input_artifact_ids": ["unverified"]},
])
def test_invalid_request_blocks_before_network(ctx, monkeypatch, extra):
    monkeypatch.setattr("investment_evidence_engine.market_worker._observe",
                        lambda *a: pytest.fail("network must not be reached"))
    result = run_market_data_resilient(op(**extra), ctx)
    assert result.status == "BLOCK"


@pytest.mark.parametrize("days", [
    ("2026-11-25", "2026-11-26"), ("2026-11-25", "2026-11-25"),
    ("2026-11-25T12:00:00", "2026-11-24"), ("2026-11-25T00:00:00+08:00",),
])
def test_future_duplicate_intraday_dates_rejected(days):
    with pytest.raises((ProviderError, ValueError)):
        _bounded_frame(frame(days), date(2026, 11, 1), date(2026, 11, 25))


@pytest.mark.parametrize(("column", "value"), [
    ("close", float("inf")), ("volume", -1), ("high", 8), ("open", True),
])
def test_nonphysical_bars_rejected(column, value):
    data = frame()
    data[column] = value
    with pytest.raises(ProviderError):
        _bounded_frame(data, date(2026, 11, 1), date(2026, 11, 25))


def test_same_overlap_is_not_same_coverage():
    left = _bounded_frame(frame(), date(2026, 11, 1), date(2026, 11, 25))
    right = left.iloc[1:]
    assert _crosscheck(left, right, 0.005)["status"] == "DATE_COVERAGE_MISMATCH"


def test_observed_match_warns_and_raw_adjust_survives(ctx, monkeypatch):
    calls = []
    data = _bounded_frame(frame(), date(2026, 11, 1), date(2026, 11, 25))

    def observed(source, symbol, start, end, adjust):
        calls.append((source, end, adjust))
        return data, {"provider": source, "status": "OBSERVED"}

    monkeypatch.setattr("investment_evidence_engine.market_worker._observe", observed)
    result = run_market_data_resilient(op(history_end_offset_days=1, adjust=""), ctx)
    assert result.status == "WARN"
    assert calls == [("eastmoney", date(2026, 11, 25), ""), ("tencent", date(2026, 11, 25), "")]
    payload = ctx.payloads["market"]
    assert payload["crosscheck"]["status"] == "MATCH_OBSERVED_ROWS"
    assert payload["pit_safe"] is False
    assert payload["historical_vintage_verified"] is False


def test_all_providers_fail_closed(ctx, monkeypatch):
    monkeypatch.setattr("investment_evidence_engine.market_worker._observe",
                        lambda *a: (None, {"status": "BLOCK", "worker_status": "WATCHDOG_TIMEOUT"}))
    result = run_market_data_resilient(op(), ctx)
    assert result.status == "BLOCK"
    assert result.metrics["provider_count"] == 3
    assert "market" not in ctx.payloads


def test_raw_secondary_never_becomes_primary_and_falls_back(ctx, monkeypatch):
    calls = []
    data = _bounded_frame(frame(), date(2026, 11, 1), date(2026, 11, 25))

    def observed(source, symbol, start, end, adjust):
        calls.append(source)
        return ((data, {"provider": source, "status": "OBSERVED"}) if source == "baostock"
                else (None, {"provider": source, "status": "BLOCK"}))

    monkeypatch.setattr("investment_evidence_engine.market_worker._observe", observed)
    result = run_market_data_resilient(op(history_end_offset_days=1, adjust=""), ctx)
    assert calls == ["eastmoney", "sina", "baostock", "tencent"]
    assert result.status == "WARN"
    assert ctx.payloads["market"]["primary_upstream"] == "baostock"


def test_adjusted_history_does_not_use_raw_tencent(ctx, monkeypatch):
    calls = []
    data = _bounded_frame(frame(), date(2026, 11, 1), date(2026, 11, 25))

    def observed(source, symbol, start, end, adjust):
        calls.append(source)
        assert adjust == "qfq"
        return data, {"provider": source, "status": "OBSERVED"}

    monkeypatch.setattr("investment_evidence_engine.market_worker._observe", observed)
    assert run_market_data_resilient(op(history_end_offset_days=1), ctx).status == "WARN"
    assert calls == ["eastmoney", "baostock"]


def test_conflicting_raw_prices_are_not_research_inputs(ctx, monkeypatch):
    data = _bounded_frame(frame(), date(2026, 11, 1), date(2026, 11, 25))

    def observed(source, symbol, start, end, adjust):
        other = data.copy()
        if source == "tencent":
            other["close"] *= 1.02
        return other, {"provider": source, "status": "OBSERVED"}

    monkeypatch.setattr("investment_evidence_engine.market_worker._observe", observed)
    result = run_market_data_resilient(op(history_end_offset_days=1, adjust=""), ctx)
    assert result.status == "BLOCK"
    assert result.errors == ["MARKET_PRICE_CONFLICT"]
    assert "market" not in ctx.frames and "market" not in ctx.payloads
    assert len(result.artifacts) == 1
