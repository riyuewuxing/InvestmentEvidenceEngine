"""Actual public scan -> exact selected bytes -> sealed RESEARCH diagnostic.

The source graph here is an observed PUBLIC TRANSPORT graph, not a fabricated
private Gate1 EvidenceGraph. It never authorizes a private consumer or PIT.
All raw provider/scan artifacts exist only in the bounded runner temp folder.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.contracts import (
    ArtifactRecordSelector,
    ExecutionOperation,
    ExecutionRequest,
    InputArtifactRef,
    canonical_sha256,
)
from investment_evidence_engine.public_scan_packet import verify_public_scan_packet
from investment_evidence_engine.research_profile_evidence import COST, FACTOR, PROFILE, SPLIT
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import read_verified_artifact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SCOPE = "2026-11-26"
FIRST = date(2025, 1, 2)


def write_request(root: Path, request: ExecutionRequest) -> Path:
    request.request_sha256 = request.compute_hash()
    path = root / "request.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    return path


def build_attachment(receipt, selected, raw, *, repo, sha, request, result, root):
    art = receipt["artifacts"]["opportunity-scan.json"]
    if hashlib.sha256(raw).hexdigest() != art["sha256"] or len(raw) != art["size_bytes"]:
        raise ValueError("PUBLIC_CHAIN_SCAN_BYTES")
    graph = {"graph_type": "PUBLIC_TRANSPORT_GRAPH_NOT_PRIVATE_GATE1",
             "subject_repo": repo, "executor_commit": sha, "as_of": receipt["as_of"],
             "nodes": {"request": receipt["request_sha256"], "result": receipt["result_sha256"],
                       "manifest": receipt["manifest_sha256"],
                       "universe": receipt["artifacts"]["market-universe.json"]["sha256"],
                       "scan": art["sha256"], "candidate": receipt["candidate_record_sha256"]},
             "relations": [["result", "EXECUTED", "request"], ["result", "MANIFEST", "manifest"],
                           ["scan", "DERIVED_FROM", "universe"], ["candidate", "SELECTED_FROM", "scan"]],
             "historical_vintage_verified": False, "private_admission_verified": False,
             "decision_authority": False}
    graph_body = json.dumps(graph, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    graph_path = root / "public-transport-graph.json"
    graph_path.write_bytes(graph_body)
    digest = hashlib.sha256(graph_body).hexdigest()
    if hashlib.sha256(graph_path.read_bytes()).hexdigest() != digest:
        raise ValueError("PUBLIC_CHAIN_GRAPH_REHASH")
    relative = "requests/inputs/actual-scan.json"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    candidate = InputArtifactRef(
        input_id="public-scan", source_job_id=request.job_id, source_trace_id=request.trace_id,
        source_subject_repo=repo, source_subject_commit=sha, source_executor_repo=repo,
        source_executor_commit=sha, source_request_sha256=receipt["request_sha256"],
        source_result_sha256=receipt["result_sha256"], source_manifest_sha256=receipt["manifest_sha256"],
        source_graph_sha256=digest, source_operation_id="opportunity-scan",
        source_artifact_path="opportunity-scan.json", source_artifact_sha256=art["sha256"],
        source_artifact_size_bytes=art["size_bytes"], materialized_path=relative,
        as_of=SCOPE, status=result.operations[1].status,
        selector=ArtifactRecordSelector(field="code", value=selected["code"], index=0,
            record_sha256=receipt["candidate_record_sha256"],
            policy="FIRST_RESEARCH_PRIORITY_RECORD_NOT_RETURN_FORECAST"),
        warnings=["PUBLIC_TRANSPORT_GRAPH_NOT_PRIVATE_GATE1", "HISTORICAL_SELECTION_UNVERIFIED"],
        unknowns=["historical_vintage", "complete_listing_coverage", "private_admission"])
    return candidate, digest


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    sha = os.environ["GITHUB_SHA"]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report = {"status": "BLOCK", "executor_commit": sha, "as_of": SCOPE,
              "observed_at": now.isoformat(), "private_admission_verified": False,
              "historical_selection_verified": False, "pit_safe": False,
              "decision_authority": False, "execution_allowed": False,
              "raw_provider_bytes_retained": False}
    # Fixed after-close observation only; no claim of a historical scan if
    # queued after midnight or the source cannot establish its date.
    if now.date().isoformat() != SCOPE or not time(18) <= now.time() < time(23, 58):
        report["blocker"] = "PUBLIC_CHAIN_FIXED_CAPTURE_WINDOW_CLOSED"
    else:
        scope = {"as_of": SCOPE, "market": "CN_A", "asset_type": "STOCK"}
        scan = ExecutionRequest(job_id="public-live-scan-research-20261126",
            trace_id="public-live-scan-research-20261126", subject_repo=REPO, subject_commit=sha,
            as_of=SCOPE, operations=[
                ExecutionOperation(operation_id="market-universe", kind="MARKET_UNIVERSE",
                    parameters=scope | {"provider_scope": "SINA_ONLY", "min_universe_size": 5000}),
                ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
                    parameters=scope | {"depends_on_operation_ids": ["market-universe"], "top_n": 20,
                        "rule_origin": "SYSTEM_RESEARCH_FILTER",
                        "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                        "rules": [{"field": "amount", "operator": "GE", "threshold": 100000000},
                                  {"field": "pct_change", "operator": "LE", "threshold": -2.0}]})])
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "scan"
            a.mkdir()
            result = execute_request(write_request(a, scan), output_dir=a / "out",
                                     executor_repo=REPO, executor_commit=sha)
            report["scan_status"] = result.status
            report["scan_operations"] = [{"id": op.operation_id, "status": op.status,
                                          "metrics": op.metrics, "errors": op.errors}
                                         for op in result.operations]
            if result.status in {"PASS", "WARN"}:
                try:
                    receipt, selected, _, raw = verify_public_scan_packet(a / "out", repo=REPO, commit=sha)
                    report["scan_receipt"] = receipt
                    b = root / "research"
                    b.mkdir()
                    ref, graph_digest = build_attachment(receipt, selected, raw, repo=REPO, sha=sha,
                                                         request=scan, result=result, root=b)
                    report["public_transport_graph_sha256"] = graph_digest
                    report["public_transport_graph_type"] = "PUBLIC_TRANSPORT_GRAPH_NOT_PRIVATE_GATE1"
                    report["public_candidate"] = ref.selector.value
                    end = date.fromisoformat(SCOPE) - timedelta(days=1)
                    market = ExecutionOperation(operation_id="market", kind="MARKET_DATA",
                        parameters={"as_of": SCOPE, "subject_ids": [ref.selector.value],
                                    "input_artifact_ids": [ref.input_id], "adjust": "",
                                    "history_days": (end-FIRST).days, "history_end_offset_days": 1,
                                    "price_tolerance": 0.001}, expected_outputs=["market.json"])
                    research = ExecutionOperation(operation_id="research", kind="RESEARCH",
                        parameters=scope | {"depends_on_operation_ids": ["market"],
                            "input_artifact_ids": [ref.input_id], "profile": PROFILE, "factor": FACTOR,
                            "split": SPLIT, "cost": COST, "semantics": "RESEARCH_ONLY_NOT_ADVICE"},
                        expected_outputs=["research.json"])
                    req = ExecutionRequest(job_id="public-actual-research-20261126",
                        trace_id="public-actual-research-20261126", subject_repo=REPO,
                        subject_commit=sha, as_of=SCOPE, operations=[market, research],
                        input_refs=[ref.input_id], input_artifacts=[ref])
                    res = execute_request(write_request(b, req), output_dir=b / "out",
                                          executor_repo=REPO, executor_commit=sha, input_root=b)
                    report |= {"research_request_sha256": req.request_sha256,
                               "research_result_sha256": res.result_sha256, "research_status": res.status,
                               "research_operations": [{"id": op.operation_id, "status": op.status,
                                   "errors": op.errors, "metrics": op.metrics} for op in res.operations],
                               "observed_inputs": [x.model_dump(mode="json") for x in res.observed_input_artifacts]}
                    item = res.operations[-1]
                    if res.status == item.status == "BLOCK" and len(item.artifacts) == 1:
                        ar = item.artifacts[0]
                        body = read_verified_artifact(b / "out", ar.path, ar.sha256, ar.size_bytes)
                        diag = strict_json_loads(body)
                        if (diag["candidate_attachment_sha256"] != ref.source_artifact_sha256
                                or diag["candidate_record_sha256"] != ref.selector.record_sha256
                                or diag["symbol"] != ref.selector.value
                                or diag["formal_profile_admitted"] is not False
                                or diag["decision_authority"] is not False):
                            raise ValueError("PUBLIC_CHAIN_DIAGNOSTIC_BINDING")
                        market_art = res.operations[0].artifacts[0]
                        market_body = read_verified_artifact(b / "out", market_art.path,
                                                             market_art.sha256, market_art.size_bytes)
                        if (diag["input_market_sha256"] != market_art.sha256
                                or diag["input_bars_sha256"] != canonical_sha256(strict_json_loads(market_body)["bars"])):
                            raise ValueError("PUBLIC_CHAIN_MARKET_BINDING")
                        report |= {"status": "WARN", "research_artifact_rehash": "MATCH",
                                   "research_artifact_sha256": ar.sha256, "research_artifact_bytes": len(body),
                                   "diagnostic": diag, "production_research_worker_executed": True}
                except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
                    report["blocker"] = str(exc) if str(exc).startswith("PUBLIC_CHAIN_") else type(exc).__name__
    print("PUBLIC_ACTUAL_RESEARCH_CHAIN " + json.dumps(report, sort_keys=True, ensure_ascii=False,
                                                        allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
