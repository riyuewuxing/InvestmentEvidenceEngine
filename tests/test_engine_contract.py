from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.workers import WorkerContext

COMMIT = "a" * 40


def test_contract_rejects_private_account_parameters() -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(
            operation_id="bad",
            kind="MARKET_DATA",
            parameters={"positions": [{"symbol": "600519", "weight": 0.8}]},
        )


@pytest.mark.parametrize("operation_id", [".", "..", "../escape", "nested/id", r"nested\id"])
def test_operation_id_is_safe_for_artifact_paths(operation_id: str) -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(operation_id=operation_id, kind="MARKET_DATA")


def test_operation_id_allows_normal_artifact_name() -> None:
    operation = ExecutionOperation(operation_id="market.v2-test_1", kind="MARKET_DATA")
    assert operation.operation_id == "market.v2-test_1"


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


def test_dispatcher_routes_factor_compute_without_input_to_structured_block(tmp_path) -> None:
    operation = ExecutionOperation(
        operation_id="factor",
        kind="FACTOR_COMPUTE",
        parameters={"subject_ids": ["600519"], "as_of": "2026-08-24"},
    )
    result = run_operation(operation, WorkerContext(output_dir=tmp_path))
    assert result.status == "BLOCK"
    assert result.errors == ["NO_FACTOR_INPUT_RECORDS"]


def test_execution_request_rejects_scan_dependency_that_is_not_prior_market_universe() -> None:
    universe = ExecutionOperation(
        operation_id="universe",
        kind="MARKET_DATA",
        parameters={"as_of": "2026-09-02"},
    )
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": "2026-09-02",
            "depends_on_operation_ids": ["universe"],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )
    with pytest.raises(ValidationError):
        ExecutionRequest(
            job_id="job-1",
            trace_id="trace-1",
            subject_repo="public/engine",
            subject_commit=COMMIT,
            as_of="2026-09-02",
            operations=[universe, scan],
        )


@pytest.mark.parametrize(
    "operations",
    [
        [
            ExecutionOperation(
                operation_id="scan",
                kind="OPPORTUNITY_SCAN",
                parameters={
                    "as_of": "2026-09-02",
                    "depends_on_operation_ids": ["missing"],
                    "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
                },
            )
        ],
        [
            ExecutionOperation(
                operation_id="scan",
                kind="OPPORTUNITY_SCAN",
                parameters={
                    "as_of": "2026-09-02",
                    "depends_on_operation_ids": ["universe"],
                    "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
                },
            ),
            ExecutionOperation(
                operation_id="universe",
                kind="MARKET_UNIVERSE",
                parameters={"as_of": "2026-09-02"},
            ),
        ],
    ],
)
def test_execution_request_rejects_missing_or_late_scan_dependency(operations) -> None:
    with pytest.raises(ValidationError):
        ExecutionRequest(
            job_id="job-1",
            trace_id="trace-1",
            subject_repo="public/engine",
            subject_commit=COMMIT,
            as_of="2026-09-02",
            operations=operations,
        )


def test_execution_request_rejects_scan_inline_and_dependency_conflict() -> None:
    universe = ExecutionOperation(
        operation_id="universe",
        kind="MARKET_UNIVERSE",
        parameters={"as_of": "2026-09-02"},
    )
    scan = ExecutionOperation(
        operation_id="scan",
        kind="OPPORTUNITY_SCAN",
        parameters={
            "as_of": "2026-09-02",
            "depends_on_operation_ids": ["universe"],
            "inline_records": [{"asset": "A", "pct_change": 1}],
            "rules": [{"field": "pct_change", "operator": "GE", "threshold": 0}],
        },
    )
    with pytest.raises(ValidationError):
        ExecutionRequest(
            job_id="job-1",
            trace_id="trace-1",
            subject_repo="public/engine",
            subject_commit=COMMIT,
            as_of="2026-09-02",
            operations=[universe, scan],
        )


@pytest.mark.parametrize(
    "kind, parameters",
    [
        ("MARKET_UNIVERSE", {"as_of": "2026-09-02", "unexpected": True}),
        ("OPPORTUNITY_SCAN", {"inline_records": [], "rules": [], "unexpected": True}),
    ],
)
def test_operation_specific_public_allowlists_reject_extra_parameters(kind, parameters) -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(operation_id="guard", kind=kind, parameters=parameters)


@pytest.mark.parametrize(
    "parameters",
    [
        {"account_id": "abc"},
        {"cash": 1},
        {"cost": 1},
        {"holding": 1},
        {"position": 1},
        {"transaction": 1},
        {"nested": [{"ref": "private://account:abc"}]},
        {"nested": [{"ref": "portfolio:abc"}]},
    ],
)
def test_public_operation_rejects_private_keys_and_nested_references(parameters) -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(operation_id="guard", kind="MARKET_DATA", parameters=parameters)


def test_public_operation_does_not_misclassify_numeric_cost_bps() -> None:
    operation = ExecutionOperation(
        operation_id="guard",
        kind="MARKET_DATA",
        parameters={"cost_bps": 10},
    )
    assert operation.parameters["cost_bps"] == 10
