import hashlib
import json
from pathlib import Path

import pytest

from investment_evidence_engine.contracts import (
    ArtifactRef,
    ExecutionOperation,
    ExecutionRequest,
    ExecutionResult,
    OperationResult,
)
from investment_evidence_engine.dispatch import run_operation
from investment_evidence_engine.public_scan_packet import verify_public_scan_packet
from investment_evidence_engine.runner import execute_request

REPO = "public/example"
COMMIT = "a" * 40
DAY = "2026-11-26"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def artifact(path):
    body = path.read_bytes()
    return ArtifactRef(path=path.name, sha256=hashlib.sha256(body).hexdigest(),
                       size_bytes=len(body), media_type="application/json")


@pytest.fixture
def packet(tmp_path, monkeypatch):
    def dispatch(op, context):
        if op.kind != "MARKET_UNIVERSE":
            return run_operation(op, context)
        payload = {"source": "public_market_data", "public_data_only": True, "decision_authority": False,
                   "market": "CN_A", "asset_type": "STOCK", "as_of": DAY, "provider": "synthetic",
                   "records": [{"asset": "600001", "code": "600001", "latest_price": 20.0},
                               {"asset": "600002", "code": "600002", "latest_price": 5.0}]}
        context.payloads[op.operation_id] = payload
        context.completed_operations[op.operation_id] = {
            "kind": "MARKET_UNIVERSE", "status": "WARN", "as_of": DAY,
            "market": "CN_A", "asset_type": "STOCK"}
        path = context.output_dir / "market-universe.json"
        write(path, payload)
        return OperationResult(operation_id=op.operation_id, status="WARN", artifacts=[artifact(path)])

    monkeypatch.setattr("investment_evidence_engine.runner.run_operation", dispatch)
    scope = {"as_of": DAY, "market": "CN_A", "asset_type": "STOCK"}
    req = ExecutionRequest(job_id="j", trace_id="t", subject_repo=REPO, subject_commit=COMMIT,
                           as_of=DAY, operations=[
        ExecutionOperation(operation_id="market-universe", kind="MARKET_UNIVERSE", parameters=scope),
        ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
            parameters={**scope, "depends_on_operation_ids": ["market-universe"],
                        "rule_origin": "SYSTEM_RESEARCH_FILTER",
                        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                        "rules": [{"field": "latest_price", "operator": "GE", "threshold": 10}]})])
    req.request_sha256 = req.compute_hash()
    path = tmp_path / "request.json"
    path.write_text(req.model_dump_json(), encoding="utf-8")
    root = tmp_path / "out"
    assert execute_request(path, output_dir=root, executor_repo=REPO, executor_commit=COMMIT).status == "WARN"
    return root


def test_packet_replays_exact_saved_bytes(packet):
    receipt, selected, codes, raw = verify_public_scan_packet(packet, repo=REPO, commit=COMMIT)
    assert selected["code"] == codes[0] == "600001"
    assert receipt["deterministic_scan_replay"] == receipt["materialized_attachment_rehash"] == "MATCH"
    assert receipt["source_graph_verified"] is False and receipt["private_admission_verified"] is False
    assert raw == (packet / "opportunity-scan.json").read_bytes()


@pytest.mark.parametrize("fault", ["tamper", "manifest", "extra", "wrong_commit", "reseal"])
def test_packet_rejects_changes(packet, fault):
    commit = COMMIT
    path = packet / "opportunity-scan.json"
    manifest_path = packet / "run_manifest.json"
    if fault == "tamper":
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "manifest":
        manifest = json.loads(manifest_path.read_bytes())
        manifest["decision_authority"] = True
        write(manifest_path, manifest)
    elif fault == "extra":
        (packet / "unexpected.txt").write_text("fixture")
    elif fault == "wrong_commit":
        commit = "b" * 40
    else:
        body = json.loads(path.read_bytes())
        body["candidates"].reverse()
        write(path, body)
        result_path = packet / "execution_result.json"
        result = ExecutionResult.model_validate_json(result_path.read_bytes())
        result.operations[1].artifacts = [artifact(path)]
        result.seal()
        result_path.write_text(result.model_dump_json(), encoding="utf-8")
        manifest = json.loads(manifest_path.read_bytes())
        manifest["result_sha256"] = result.result_sha256
        manifest["artifacts"] = [ref.model_dump(mode="json") for op in result.operations for ref in op.artifacts]
        write(manifest_path, manifest)
    with pytest.raises(ValueError):
        verify_public_scan_packet(Path(packet), repo=REPO, commit=commit)
