"""Regression for the actual price/K-line dependency boundary (synthetic rows)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.market_worker import _bounded_frame
from investment_evidence_engine.workers import WorkerContext, _jsonable_records

STAMP = "2026-11-26T14:00:00+08:00"


def rows():
    return [{"date": day, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100}
            for day in ("2026-11-24", "2026-11-25")]


def context(tmp_path):
    return WorkerContext(output_dir=tmp_path, request_as_of=STAMP,
                         clock=lambda: datetime(2026, 11, 26, 16, tzinfo=ZoneInfo("Asia/Shanghai")))


def attach(ctx):
    f = pd.DataFrame(rows())
    f["date"] = pd.to_datetime(f["date"])
    ctx.frames["market"] = f
    ctx.payloads["market"] = {"symbol": "600519", "as_of": STAMP, "start": "2026-10-01",
                              "end": "2026-11-25", "adjust": "", "bars": _jsonable_records(f)}
    ctx.completed_operations["market"] = {"kind": "MARKET_DATA", "status": "WARN", "as_of": STAMP}


def op(kind, **kwargs):
    return ExecutionOperation(operation_id="price", kind=kind,
                              parameters={"subject_ids": ["600519"], "as_of": STAMP, **kwargs})


@pytest.mark.parametrize("kind", ["PRICE_ANALYTICS", "KLINE_RENDER"])
@pytest.mark.parametrize("failure", ["missing", "wrong_symbol", "wrong_clock", "wrong_kind",
                                     "wrong_rows", "inline_conflict", "late_window", "wrong_basis"])
def test_bad_dependencies_never_fetch(tmp_path, monkeypatch, kind, failure):
    ctx = context(tmp_path)
    attach(ctx)
    params = {"depends_on_operation_ids": ["market"]}
    if failure == "missing":
        ctx.frames.clear()
    elif failure == "wrong_symbol":
        ctx.payloads["market"]["symbol"] = "000001"
    elif failure == "wrong_clock":
        ctx.payloads["market"]["as_of"] = "2026-11-26"
    elif failure == "wrong_kind":
        ctx.completed_operations["market"]["kind"] = "PRICE_ANALYTICS"
    elif failure == "wrong_rows":
        ctx.frames["market"]["close"] = 10
    elif failure == "inline_conflict":
        params["inline_ohlcv"] = rows()
    elif failure == "late_window":
        ctx.payloads["market"]["end"] = "2026-11-26"
    elif failure == "wrong_basis":
        params["adjust"] = "qfq"
    monkeypatch.setattr("investment_evidence_engine.market_worker._observe",
                        lambda *a: pytest.fail("implicit network fetch forbidden"))
    result = run_operation(op(kind, **params), ctx)
    assert result.status == "BLOCK"
    assert not result.artifacts


def test_real_consumers_share_identity_and_dates(tmp_path):
    ctx = context(tmp_path)
    attach(ctx)
    result = run_operation(op("PRICE_ANALYTICS", depends_on_operation_ids=["market"]), ctx)
    assert result.status == "WARN"
    assert ctx.payloads["price"]["price_input"]["source_operation_id"] == "market"
    assert result.metrics["last_date"] == "2026-11-25"
    assert ctx.payloads["price"]["pit_safe"] is False
    chart = op("KLINE_RENDER", depends_on_operation_ids=["market"]).model_copy(update={"operation_id": "chart"})
    result = run_operation(chart, ctx)
    assert result.status == "WARN" and len(result.artifacts) == 2
    assert ctx.payloads["chart"]["last_rendered_date"] == "2026-11-25"


@pytest.mark.parametrize("kind", ["PRICE_ANALYTICS", "KLINE_RENDER"])
@pytest.mark.parametrize("bad", ["future", "duplicate", "empty"])
def test_inline_scope_fail_closed(tmp_path, kind, bad):
    r = rows()
    if bad == "future":
        r[1]["date"] = "2026-11-26"
    elif bad == "duplicate":
        r[1]["date"] = r[0]["date"]
    else:
        r = []
    assert run_operation(op(kind, inline_ohlcv=r), context(tmp_path)).status == "BLOCK"


def test_standalone_uses_bounded_market_adapter(tmp_path, monkeypatch):
    from datetime import date

    f = _bounded_frame(pd.DataFrame(rows()), date(2026, 11, 1), date(2026, 11, 25))
    calls = []

    def observe(source, symbol, first, end, adjust):
        calls.append((source, symbol, end, adjust))
        return f.copy(), {"provider": source, "status": "OBSERVED"}

    monkeypatch.setattr("investment_evidence_engine.market_worker._observe", observe)
    ctx = context(tmp_path)
    result = run_operation(op("PRICE_ANALYTICS", adjust=""), ctx)
    assert result.status == "WARN"
    assert calls == [("eastmoney", "600519", date(2026, 11, 25), ""),
                     ("tencent", "600519", date(2026, 11, 25), "")]
    assert ctx.payloads["price"]["price_input"]["kind"] == "BOUNDED_IMPLICIT_MARKET"
