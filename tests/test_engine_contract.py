from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.runner import execute_request
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


@pytest.mark.parametrize("operation_id", ["../escape", "a/b", "a\\b", "execution_result", "run_manifest", "a\n", ""])
def test_operation_id_cannot_escape_artifact_directory(operation_id) -> None:
    with pytest.raises(ValidationError):
        ExecutionOperation(operation_id=operation_id, kind="MARKET_DATA")


def _request(operations):
    return ExecutionRequest(
        job_id="test-job", trace_id="test-trace", subject_repo="example/public",
        subject_commit=COMMIT, as_of="2026-08-24", operations=operations,
    )


@pytest.mark.parametrize("dependencies", [["later"], ["first", "first"], "first", [1]])
def test_dependency_requires_unique_earlier_operations(dependencies) -> None:
    with pytest.raises(ValidationError):
        _request([
            ExecutionOperation(operation_id="first", kind="MARKET_DATA"),
            ExecutionOperation(operation_id="second", kind="PRICE_ANALYTICS",
                               parameters={"depends_on_operation_ids": dependencies}),
        ])


@pytest.mark.parametrize("upstream_status,expected", [
    ("BLOCK", "BLOCK"), ("ERROR", "BLOCK"), ("PENDING", "BLOCK"), ("WARN", "WARN"), ("PASS", "PASS"),
])
def test_runner_propagates_dependency_status(tmp_path, monkeypatch, upstream_status, expected) -> None:
    from investment_evidence_engine import runner
    from investment_evidence_engine.contracts import OperationResult

    operations = [
        ExecutionOperation(operation_id="first", kind="MARKET_DATA"),
        ExecutionOperation(operation_id="second", kind="PRICE_ANALYTICS",
                           parameters={"depends_on_operation_ids": ["first"]}),
        ExecutionOperation(operation_id="independent", kind="MARKET_DATA"),
    ]
    request = _request(operations)
    request.request_sha256 = request.compute_hash()
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    called = []

    def fake_worker(operation, context):
        called.append(operation.operation_id)
        if operation.operation_id == "first":
            context.payloads["first"] = {"diagnostic": True}
            return OperationResult(operation_id="first", status=upstream_status)
        return OperationResult(operation_id=operation.operation_id, status="PASS")

    monkeypatch.setattr(runner, "run_operation", fake_worker)
    result = execute_request(path, output_dir=tmp_path / "out",
                             executor_repo="example/public", executor_commit=COMMIT)
    assert [item.status for item in result.operations] == [upstream_status, expected, "PASS"]
    assert ("second" in called) == (expected != "BLOCK")
    assert "independent" in called
    if expected == "WARN":
        assert "UPSTREAM_WARN:first" in result.operations[1].warnings
