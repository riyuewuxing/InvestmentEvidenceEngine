from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.workers import WorkerContext, run_operation

COMMIT = "a" * 40


def test_contract_rejects_private_account_parameters() -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(
            operation_id="bad",
            kind="MARKET_DATA",
            parameters={"positions": [{"symbol": "600519", "weight": 0.8}]},
        )


def test_request_hash_is_deterministically_verifiable() -> None:
    request = ExecutionRequest(
        job_id="job-1",
        trace_id="trace-1",
        subject_repo="riyuewuxing/touzizhuanjia",
        subject_commit=COMMIT,
        as_of="2026-08-24",
        operations=[
            ExecutionOperation(
                operation_id="market",
                kind="MARKET_DATA",
                parameters={"subject_ids": ["600519"], "as_of": "2026-08-24"},
            )
        ],
    )
    request.request_sha256 = request.compute_hash()
    assert request.verify()


def test_price_analytics_runs_without_network_when_public_ohlcv_is_supplied(tmp_path) -> None:
    start = date(2026, 7, 1)
    bars = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100.5 + index,
            "volume": 100000 + index * 100,
        }
        for index in range(45)
    ]
    operation = ExecutionOperation(
        operation_id="price",
        kind="PRICE_ANALYTICS",
        parameters={
            "subject_ids": ["600519"],
            "as_of": "2026-08-24",
            "inline_ohlcv": bars,
        },
        evidence_domains=["PRICE_STRUCTURE"],
    )
    result = run_operation(operation, WorkerContext(output_dir=tmp_path))
    assert result.status == "PASS"
    assert result.artifacts[0].path == "price.json"
    assert (tmp_path / "price.json").exists()
    assert result.metrics["rows"] == 45


def test_unimplemented_worker_blocks_instead_of_guessing(tmp_path) -> None:
    operation = ExecutionOperation(
        operation_id="factor",
        kind="FACTOR_COMPUTE",
        parameters={"subject_ids": ["600519"], "as_of": "2026-08-24"},
    )
    result = run_operation(operation, WorkerContext(output_dir=tmp_path))
    assert result.status == "BLOCK"
    assert result.errors == ["UNIMPLEMENTED_OPERATION:FACTOR_COMPUTE"]
