"""Actual scan-packet byte control with a separate disclosure-directory reference.

This does not run or pass the official exchange listing gate. No raw vendor
records are persisted or published. No fabricated source graph or admission.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.disclosure_directory import observe_directory
from investment_evidence_engine.listing_comparison import compare_code_sets, stock_code
from investment_evidence_engine.public_scan_packet import verify_public_scan_packet
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.selected_price_diagnostic import SCOPE, run_selected_price_diagnostic


def main() -> int:
    repo, commit = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if repo != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.date() != SCOPE or now.hour < 18:
        raise SystemExit("after-close weekday only")
    day = now.date().isoformat()
    reference, meta = observe_directory()
    report = {"executor_commit": commit, "as_of": day, "directory": meta,
              "status": "BLOCK", "official_listing_gate": "NOT_RUN_PRIOR_SZSE_BLOCK",
              "full_listing_coverage_verified": False, "source_independence_verified": False,
              "raw_provider_bytes_retained": False, "decision_authority": False,
              "execution_allowed": False, "private_admission_verified": False}
    if reference is not None:
        scope = {"as_of": day, "market": "CN_A", "asset_type": "STOCK"}
        request = ExecutionRequest(job_id="public-disclosure-scan-packet", trace_id="public-disclosure-scan-packet",
            subject_repo=repo, subject_commit=commit, as_of=day, operations=[
            ExecutionOperation(operation_id="market-universe", kind="MARKET_UNIVERSE",
                parameters={**scope, "provider_scope": "SINA_ONLY", "min_universe_size": 5000}),
            ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
                parameters={**scope, "depends_on_operation_ids": ["market-universe"], "top_n": 20,
                            "rule_origin": "SYSTEM_RESEARCH_FILTER",
                            "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                            "rules": [{"field": "amount", "operator": "GE", "threshold": 100000000},
                                      {"field": "pct_change", "operator": "LE", "threshold": -2.0}]})])
        request.request_sha256 = request.compute_hash()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            req = root / "request.json"
            req.write_text(request.model_dump_json(), encoding="utf-8")
            result = execute_request(req, output_dir=root / "out", executor_repo=repo, executor_commit=commit)
            report["scan_execution_status"] = result.status
            report["operations"] = [{"id": item.operation_id, "status": item.status,
                                     "metrics": item.metrics, "warnings": item.warnings, "errors": item.errors}
                                    for item in result.operations]
            if result.status in {"PASS", "WARN"}:
                try:
                    receipt, selected, snapshot, raw = verify_public_scan_packet(root / "out", repo=repo, commit=commit)
                    report["packet"] = receipt
                    report["comparison"] = compare_code_sets(reference, snapshot) | {
                        "reference_kind": "CNINFO_DISCLOSURE_DIRECTORY_NOT_EXCHANGE_LISTING"}
                    report["first_record_present_in_reference"] = stock_code(
                        selected["code"], require_exchange=False) in set(reference)
                    report["status"] = "WARN"
                    report["actual_packet_bytes_observed_in_runner"] = True
                    report["actual_packet_bytes_durably_retained"] = False
                    report["selected_price_diagnostic"] = run_selected_price_diagnostic(
                        raw, receipt, reference, root=root / "selected-diagnostic", repo=repo, commit=commit)
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    report["packet_blocker"] = (str(exc) if str(exc).startswith(("PUBLIC_SCAN_", "INPUT_ARTIFACT_"))
                                                else type(exc).__name__)
    print("PUBLIC_DISCLOSURE_SCAN_PACKET " + json.dumps(report, sort_keys=True, ensure_ascii=False,
                                                        allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
