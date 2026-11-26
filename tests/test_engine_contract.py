import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
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
    from investment_evidence_engine.contracts import ArtifactRef, OperationResult

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
        return OperationResult(operation_id=operation.operation_id, status="PASS",
                               artifacts=[ArtifactRef(path=operation.operation_id + ".json", sha256="a" * 64)])

    monkeypatch.setattr(runner, "run_operation", fake_worker)
    result = execute_request(path, output_dir=tmp_path / "out",
                             executor_repo="example/public", executor_commit=COMMIT)
    assert [item.status for item in result.operations] == [upstream_status, expected, "PASS"]
    assert ("second" in called) == (expected != "BLOCK")
    assert "independent" in called
    if expected == "WARN":
        assert "UPSTREAM_WARN:first" in result.operations[1].warnings


def test_execute_workflow_shells_are_bounded_and_parse(tmp_path) -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/execute-request.yml"
    job = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["execute"]
    assert "visibility == 'public'" in job["if"]
    steps = {step.get("name"): step for step in job["steps"] if "name" in step}
    execute = steps["Execute request"]
    assert execute["env"]["REQUEST_PATH"] == '${{ steps.request.outputs.path }}'
    assert 'investment-evidence-engine "$REQUEST_PATH"' in execute["run"]
    assert '${{' not in execute["run"]
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash syntax check is performed on the public Linux runner")
    for index, step in enumerate(steps.values()):
        if "run" in step:
            assert step["timeout-minutes"] > 0
            path = tmp_path / f"step-{index}.sh"
            path.write_text(step["run"], encoding="utf-8")
            subprocess.run([bash, "-n", str(path)], check=True, timeout=3, capture_output=True)


def test_real_pit_block_is_not_factor_input(tmp_path) -> None:
    cutoff = "2026-08-24T08:00:00+08:00"
    operations = [
        ExecutionOperation(operation_id="pit", kind="PIT_REPLAY", parameters={
            "as_of": cutoff,
            "inline_records": [
                {"available_at": "2026-08-24T07:00:00+08:00",
                 "retrieved_at": "2026-08-24T07:01:00+08:00", "value": 1},
                {"available_at": "2026-08-24T07:00:00+08:00",
                 "retrieved_at": "2026-08-24T09:00:00+08:00", "value": 2},
            ],
        }),
        ExecutionOperation(operation_id="factor", kind="FACTOR_COMPUTE", parameters={
            "depends_on_operation_ids": ["pit"],
            "factor_spec": {"field": "value", "transform": "IDENTITY"},
        }),
    ]
    request = _request(operations)
    request.request_sha256 = request.compute_hash()
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    out = tmp_path / "out"
    result = execute_request(path, output_dir=out, executor_repo="example/public", executor_commit=COMMIT)
    assert result.status == "BLOCK"
    assert result.operations[0].metrics["eligible_count"] == 1
    assert result.operations[1].errors == ["UPSTREAM_NOT_USABLE:pit"]
    assert (out / "pit.json").is_file()
    assert not (out / "factor.json").exists()
