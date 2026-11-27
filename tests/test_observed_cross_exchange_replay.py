"""Actual public-run derived receipt regression; no raw source or historical admission."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.cross_exchange_release_control import reconcile
from investment_evidence_engine.runner import execute_request

FIXTURE = Path(__file__).parent / "fixtures" / "byd_cross_exchange_2024h1_observed.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]


def test_actual_cross_exchange_observations_reconcile():
    rows = load()
    assert all(row["status"] == "OBSERVED" and row["parent_rehash"] == "MATCH" for row in rows.values())
    result = reconcile(rows["index"]["parsed"], rows["hk"]["parsed"], rows["sz"]["parsed"],
                       observed_at=max(datetime.fromisoformat(v["observed_at"]) for v in rows.values()))
    assert result["status"] == "WARN"
    assert result["exact_field_and_comparative_match"]
    assert not result["historical_first_availability_verified"]
    assert not result["independent_audit_of_issuer_figures"]
    assert not result["pit_safe"] and not result["decision_authority"]


@pytest.mark.parametrize(("cutoff", "status", "count"), [
    ("2024-06-30T23:59:59+08:00", "BLOCK", 0),
    ("2024-08-28T15:00:00+08:00", "BLOCK", 0),
    ("2024-08-28T17:55:59+08:00", "BLOCK", 0),
    ("2024-08-29T09:30:00+08:00", "BLOCK", 0),
    ("2026-11-27T05:06:06+00:00", "BLOCK", 2),
    ("2026-11-27T05:06:08+00:00", "WARN", 3),
])
def test_sealed_runner_observed_clock_not_report_or_release_day(tmp_path, cutoff, status, count):
    observations = load()
    # Use the actual observation as a conservative availability proxy only.
    # This is NOT a witness of the initial public release or durable admission time.
    records = [
        {"source_kind": kind, "source_sha256": row["source_sha256"],
         "source_run_id": row["run_id"], "available_at": row["observed_at"],
         "retrieved_at": row["observed_at"],
         "clock_role": "OBSERVATION_PROXY_NOT_FIRST_AVAILABILITY"}
        for kind, row in observations.items()
    ]
    op = ExecutionOperation(operation_id="pit", kind="PIT_REPLAY",
                            parameters={"as_of": cutoff, "inline_records": records})
    request = ExecutionRequest(job_id="observed-byd", trace_id="byd-clock-regression",
                               subject_repo="riyuewuxing/InvestmentEvidenceEngine",
                               subject_commit="6306b7152893a9844818a1cc84402b74475f29d2",
                               as_of=cutoff, operations=[op])
    request.request_sha256 = request.compute_hash()
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    out = tmp_path / "out"
    result = execute_request(request_path, output_dir=out,
                             executor_repo=request.subject_repo, executor_commit=request.subject_commit)
    assert result.status == status and not result.decision_authority
    artifact = result.operations[0].artifacts[0]
    raw = (out / artifact.path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == artifact.sha256
    payload = json.loads(raw)
    assert payload["eligible_count"] == count
    assert payload["future_rejected_count"] == 3 - count
    assert not payload["historical_vintage_verified"] and not payload["pit_safe"]
    assert not payload["decision_authority"]
