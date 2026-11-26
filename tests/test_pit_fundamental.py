from datetime import date

import pandas as pd

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
        {"f_ann_date":"20260101","available_at":"fabricated"},
        {"f_ann_date":"20260103","available_at":"fabricated"},
    ]),endpoint="income",as_of=date(2026,1,3))
    assert len(rows) == 1
    assert "available_at" not in rows[0]
    assert "vendor_date_filter_proxy" in rows[0]
