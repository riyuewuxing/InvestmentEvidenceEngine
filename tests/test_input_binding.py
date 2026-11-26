from datetime import UTC, datetime
from hashlib import sha256

import pytest

from investment_evidence_engine.contracts import (
    ArtifactRecordSelector,
    ArtifactRef,
    ExecutionOperation,
    ExecutionRequest,
    InputArtifactRef,
    OperationResult,
    canonical_sha256,
)
from investment_evidence_engine.runner import execute_request

DAY = "2026-11-25"
ROW = {"code": "600519", "asset": "600519", "latest_price": 10.0}
SCAN = {"candidates": [ROW], "candidate_count": 1,
        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
        "input_mode": "LIVE_MARKET_UNIVERSE", "research_only": True, "pit_safe": False,
        "decision_authority": False,
        "rule_origin": "SYSTEM_RESEARCH_FILTER",
        "rules": [{"field": "latest_price", "operator": "GE", "threshold": 1, "weight": 1.0}],
        "dependency_evidence": {"as_of": DAY, "market": "CN_A", "asset_type": "STOCK",
                                "source": "public_market_data", "status": "WARN"}}


def fixture(tmp_path, *, data=None, selected=None):
    import json

    raw = json.dumps(SCAN if data is None else data, sort_keys=True).encode()
    rel = "requests/inputs/public-control.json"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    h = "a" * 64
    ref = InputArtifactRef(
        input_id="public-scan", source_job_id="public-job", source_trace_id="public-trace",
        source_subject_repo="public/example", source_subject_commit="b" * 40,
        source_executor_repo="public/example", source_executor_commit="c" * 40,
        source_request_sha256=h, source_result_sha256=h, source_manifest_sha256=h,
        source_graph_sha256=h, source_operation_id="opportunity-scan",
        source_artifact_path="opportunity-scan.json", source_artifact_sha256=sha256(raw).hexdigest(),
        source_artifact_size_bytes=len(raw), materialized_path=rel, as_of=DAY, status="WARN",
        selector=ArtifactRecordSelector(field="code", value=selected or ROW["code"], index=0,
            record_sha256=canonical_sha256(ROW), policy="FIRST_RESEARCH_PRIORITY_RECORD_NOT_RETURN_FORECAST"),
    )
    req = ExecutionRequest(job_id="j", trace_id="t", subject_repo="public/example",
        subject_commit="d" * 40, as_of=DAY, input_refs=[ref.input_id], input_artifacts=[ref],
        operations=[ExecutionOperation(operation_id="market", kind="MARKET_DATA",
            parameters={"as_of": DAY, "subject_ids": [ref.selector.value], "input_artifact_ids": [ref.input_id]}),
            ExecutionOperation(operation_id="research", kind="RESEARCH",
            parameters={"as_of": DAY, "depends_on_operation_ids": ["market"], "input_artifact_ids": [ref.input_id]})],
        generated_at=datetime(2026, 11, 25, tzinfo=UTC))
    req.request_sha256 = req.compute_hash()
    reqfile = tmp_path / "request.json"
    reqfile.write_text(req.model_dump_json(), encoding="utf-8")
    return reqfile, path, ref


def test_exact_bytes_retained_but_research_blocked(tmp_path, monkeypatch):
    from investment_evidence_engine.dispatch import EXTRA_WORKERS

    reqfile, path, ref = fixture(tmp_path)

    def market(op, context):
        assert context.input_artifacts[ref.input_id] == ref
        body = b"synthetic output, not a real quote"
        (context.output_dir / "market.json").write_bytes(body)
        return OperationResult(operation_id=op.operation_id, status="WARN",
                               artifacts=[ArtifactRef(path="market.json", sha256=sha256(body).hexdigest(),
                                                      size_bytes=len(body))])

    monkeypatch.setitem(EXTRA_WORKERS, "MARKET_DATA", market)
    out = tmp_path / "out"
    result = execute_request(reqfile, output_dir=out, executor_repo="public/example",
                             executor_commit="e" * 40, input_root=tmp_path)
    assert result.status == "BLOCK"
    assert result.operations[1].errors == ["RESEARCH_POINT_IN_TIME_SOURCE_VINTAGE_AND_PROFILE_NOT_ADMITTED"]
    readiness = result.operations[1].metrics["research_readiness"]
    assert readiness["candidate_attachment"] == "CONTEXT_SCOPE_MATCH_TRANSPORT_ONLY"
    assert readiness["market_input"] == "UNVERIFIED"
    assert readiness["research_admitted"] is False and readiness["pit_safe"] is False
    assert result.observed_input_artifacts[0].observed_sha256 == ref.source_artifact_sha256
    assert (out / ref.materialized_path).read_bytes() == path.read_bytes()
    assert result.as_of == DAY and result.result_sha256 == result.compute_hash()


@pytest.mark.parametrize("mode", ["tamper", "missing", "selector", "private", "future", "duplicate", "private_rule"])
def test_bad_input_rejected_before_dispatch(tmp_path, monkeypatch, mode):
    data = None
    if mode == "private":
        data = {**SCAN, "candidates": [{**ROW, "account": "forbidden"}]}
    elif mode == "future":
        data = {**SCAN, "dependency_evidence": {**SCAN["dependency_evidence"], "as_of": "2026-11-26"}}
    elif mode == "duplicate":
        data = {**SCAN, "candidates": [ROW, ROW], "candidate_count": 2}
    elif mode == "private_rule":
        data = {**SCAN, "rule_origin": "USER_PROVIDED"}
    reqfile, path, _ = fixture(tmp_path, data=data, selected="000001" if mode == "selector" else None)
    if mode == "tamper":
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b"10.0", b"11.0"))
    elif mode == "missing":
        path.unlink()
    monkeypatch.setattr("investment_evidence_engine.runner.run_operation",
                        lambda *a: pytest.fail("must not dispatch"))
    with pytest.raises(ValueError):
        execute_request(reqfile, output_dir=tmp_path / "out", executor_repo="public/example",
                        executor_commit="e" * 40, input_root=tmp_path)


def test_legacy_hash_payload_omits_empty_input_fields():
    req = ExecutionRequest(job_id="j", trace_id="t", subject_repo="public/example",
        subject_commit="d" * 40, as_of=DAY,
        operations=[ExecutionOperation(operation_id="market", kind="MARKET_DATA")])
    assert "input_artifacts" not in req.payload()


def test_retained_input_cannot_be_changed_by_worker(tmp_path, monkeypatch):
    from investment_evidence_engine.dispatch import EXTRA_WORKERS

    reqfile, _, ref = fixture(tmp_path)

    def tamper(op, context):
        target = context.output_dir / ref.materialized_path
        target.write_bytes(target.read_bytes().replace(b"10.0", b"11.0"))
        return OperationResult(operation_id=op.operation_id, status="WARN")

    monkeypatch.setitem(EXTRA_WORKERS, "MARKET_DATA", tamper)
    with pytest.raises(ValueError, match="RETAINED_INPUT_ARTIFACT_CHANGED"):
        execute_request(reqfile, output_dir=tmp_path / "out", executor_repo="public/example",
                        executor_commit="e" * 40, input_root=tmp_path)


def test_observe_actual_scan_worker_output_on_synthetic_fixture(tmp_path):
    from investment_evidence_engine.input_binding import observe_scan_input
    from investment_evidence_engine.research_compute import run_opportunity_scan
    from investment_evidence_engine.workers import WorkerContext

    ctx = WorkerContext(output_dir=tmp_path, request_as_of=DAY)
    ctx.completed_operations["universe"] = {"kind": "MARKET_UNIVERSE", "status": "WARN",
        "market": "CN_A", "asset_type": "STOCK", "as_of": DAY}
    ctx.payloads["universe"] = {"source": "public_market_data", "public_data_only": True,
        "decision_authority": False, "market": "CN_A", "asset_type": "STOCK",
        "as_of": DAY, "records": [ROW]}
    op = ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
        parameters={"as_of": DAY, "depends_on_operation_ids": ["universe"], "market": "CN_A",
                    "asset_type": "STOCK", "rule_origin": "SYSTEM_RESEARCH_FILTER",
                    "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                    "rules": [{"field": "latest_price", "operator": "GE", "threshold": 1}]})
    result = run_opportunity_scan(op, ctx)
    assert result.status == "WARN"
    scan = ctx.payloads["opportunity-scan"]
    _, path, ref = fixture(tmp_path, data=scan)
    ref = ref.model_copy(update={"selector": ref.selector.model_copy(
        update={"record_sha256": canonical_sha256(scan["candidates"][0])})})
    receipt, raw = observe_scan_input(tmp_path, ref)
    assert receipt.status == "MATCH" and raw == path.read_bytes()


def test_research_readiness_never_promotes_context_claims(tmp_path, monkeypatch):
    import pandas as pd

    from investment_evidence_engine.dispatch import EXTRA_WORKERS

    reqfile, _, ref = fixture(tmp_path)

    def market(op, context):
        context.frames[op.operation_id] = pd.DataFrame([{"close": 10.0}])
        context.payloads[op.operation_id] = {"symbol": ref.selector.value, "as_of": DAY,
                                             "pit_safe": True, "historical_vintage_verified": True}
        body = b"synthetic scope fixture"
        (context.output_dir / "market.json").write_bytes(body)
        return OperationResult(operation_id=op.operation_id, status="PASS",
                               artifacts=[ArtifactRef(path="market.json", sha256=sha256(body).hexdigest(),
                                                      size_bytes=len(body))])

    monkeypatch.setitem(EXTRA_WORKERS, "MARKET_DATA", market)
    result = execute_request(reqfile, output_dir=tmp_path / "out", executor_repo="public/example",
                             executor_commit="e" * 40, input_root=tmp_path)
    readiness = result.operations[1].metrics["research_readiness"]
    assert result.status == "BLOCK"
    assert readiness["market_input"] == "OBSERVED_SCOPE_MATCH_ONLY"
    assert readiness["historical_source_vintage"] == "NOT_ADMITTED"
    assert readiness["formal_profile"] == "NOT_ADMITTED"
    assert readiness["research_admitted"] is False
    assert readiness["decision_authority"] is False
