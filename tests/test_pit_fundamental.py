from datetime import date

import pandas as pd
import pytest

from investment_evidence_engine.contracts import ExecutionOperation
from investment_evidence_engine.fundamental_worker import (
    _pit_records,
    run_fundamental_with_pit_guard,
)
from investment_evidence_engine.workers import WorkerContext


def test_historical_pit_fundamental_blocks_without_verified_pit_source(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    operation = ExecutionOperation(
        operation_id="fundamental",
        kind="FUNDAMENTAL_HISTORY",
        parameters={
            "subject_ids": ["600519"],
            "as_of": "2020-08-24",
            "pit_required": True,
        },
        evidence_domains=["FUNDAMENTAL"],
    )
    result = run_fundamental_with_pit_guard(operation, WorkerContext(output_dir=tmp_path))
    assert result.status == "BLOCK"
    assert result.errors == [
        "PIT_FINANCIAL_SOURCE_UNAVAILABLE:TUSHARE_TOKEN_NOT_CONFIGURED"
    ]


def test_vendor_ann_date_proxy_not_promoted_to_actual_availability():
    rows = _pit_records(pd.DataFrame([
        {"end_date":"20251231","f_ann_date":"20260101","available_at":"fabricated"},
        {"end_date":"20251231","f_ann_date":"20260103","available_at":"fabricated"},
    ]),endpoint="income",as_of=date(2026,1,3))
    assert len(rows) == 1
    assert "available_at" not in rows[0]
    assert "vendor_date_filter_proxy" in rows[0]


def test_vendor_notice_disagreement_is_not_backdated():
    rows = _pit_records(pd.DataFrame([{"end_date": "20251231", "ann_date": "20260101",
                                      "f_ann_date": "20260103", "report_type": "1",
                                      "ts_code": "600519.SH", "retrieved_at": "fabricated"}]),
                        endpoint="income", as_of=date(2026, 1, 3), expected_code="600519.SH")
    assert rows == []


@pytest.mark.parametrize("change", [
    {"ts_code": "000001.SZ"}, {"report_type": "2"}, {"report_type": "4"},
    {"f_ann_date": "not-a-date"}, {"ann_date": "20251230"},
])
def test_vendor_scope_conflicts_fail_closed(change):
    base = {"end_date": "20251231", "ann_date": "20260101", "f_ann_date": "20260101",
            "report_type": "1", "ts_code": "600519.SH"}
    with pytest.raises((ValueError, RuntimeError)):
        _pit_records(pd.DataFrame([{**base, **change}]), endpoint="income",
                     as_of=date(2026, 1, 4), expected_code="600519.SH")


@pytest.mark.parametrize("subjects,cutoff,request_cutoff,required,expected", [
    (["600519", "600036"], "2020-08-24", None, True, "FUNDAMENTAL_INVALID_SUBJECT_OR_CUTOFF"),
    (["510300"], "2020-08-24", None, True, "FUNDAMENTAL_INVALID_SUBJECT_OR_CUTOFF"),
    (["600519"], "2020-08-24", "2020-08-23", True, "FUNDAMENTAL_REQUEST_SCOPE_EXCEEDED_OR_INSTANT_UNSUPPORTED"),
    (["600519"], "2020-08-24", "2020-08-24T15:00:00+08:00", True, "FUNDAMENTAL_REQUEST_SCOPE_EXCEEDED_OR_INSTANT_UNSUPPORTED"),
    (["600519"], "2020-08-24", None, False, "FUNDAMENTAL_LIVE_SNAPSHOT_CANNOT_ANSWER_HISTORICAL_CUTOFF"),
])
def test_fundamental_scope_before_external_calls(tmp_path, subjects, cutoff, request_cutoff, required, expected):
    op = ExecutionOperation(operation_id="f", kind="FUNDAMENTAL_HISTORY",
                            parameters={"subject_ids": subjects, "as_of": cutoff, "pit_required": required})
    result = run_fundamental_with_pit_guard(op, WorkerContext(output_dir=tmp_path, request_as_of=request_cutoff))
    assert result.status == "BLOCK" and result.errors == [expected]
    assert not result.artifacts


def test_optional_vendor_timeout_is_explicit_and_no_secret_argv(monkeypatch):
    from investment_evidence_engine import fundamental_worker
    from investment_evidence_engine.bounded_worker import WorkerResult

    monkeypatch.setenv("TUSHARE_TOKEN", "synthetic-token-never-in-argv")
    seen = []

    def timeout(command, *, timeout_seconds, max_bytes):
        seen.append(command)
        assert timeout_seconds == 25.0
        assert max_bytes == 4 * 1024 * 1024
        return WorkerResult("WATCHDOG_TIMEOUT", elapsed_seconds=25.0)

    monkeypatch.setattr(fundamental_worker, "run_json_worker", timeout)
    rows, attempt = fundamental_worker._observe_tushare_endpoint(
        "income", "600519", date(2025, 1, 1), date(2026, 1, 3))
    assert rows == []
    assert attempt["worker_status"] == "WATCHDOG_TIMEOUT"
    assert attempt["status"] == "WARN"
    assert all("synthetic-token" not in arg for command in seen for arg in command)


def test_optional_vendor_parent_revalidates_worker_scope(monkeypatch):
    from investment_evidence_engine import fundamental_worker
    from investment_evidence_engine.bounded_worker import WorkerResult

    receipt = {"endpoint": "income", "symbol": "600519", "start": "2025-01-01", "end": "2026-01-03",
               "started_at": "2026-01-04T00:00:00+00:00", "retrieved_at": "2026-01-04T00:00:01+00:00",
               "records": [{"ts_code": "000001.SZ", "report_type": "1", "end_date": "20251231",
                            "ann_date": "20260101", "f_ann_date": "20260101", "revenue": 12}]}
    monkeypatch.setattr(fundamental_worker, "run_json_worker",
                        lambda *args, **kwargs: WorkerResult("OK", payload=receipt))
    rows, attempt = fundamental_worker._observe_tushare_endpoint(
        "income", "600519", date(2025, 1, 1), date(2026, 1, 3))
    assert rows == [] and attempt["status"] == "WARN"
    receipt["records"][0]["ts_code"] = "600519.SH"
    rows, attempt = fundamental_worker._observe_tushare_endpoint(
        "income", "600519", date(2025, 1, 1), date(2026, 1, 3))
    assert len(rows) == 1 and attempt["status"] == "PASS"
    assert rows[0]["pit_safe"] is False
    assert "available_at" not in rows[0]
