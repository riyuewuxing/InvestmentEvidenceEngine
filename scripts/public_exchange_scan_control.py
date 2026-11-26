"""One after-close official-listing and exact public scan packet control."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.exchange_listing import SCOPES, observe_listing
from investment_evidence_engine.listing_comparison import compare_code_sets, stock_code
from investment_evidence_engine.public_scan_packet import verify_public_scan_packet
from investment_evidence_engine.runner import execute_request


def main() -> int:
    repo, commit = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if repo != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() >= 5 or now.hour < 18:
        raise SystemExit("after-close weekday only")
    day = now.date()
    reference = []
    info = []
    for scope in SCOPES:
        codes, meta = observe_listing(scope, day)
        info.append(meta)
        if codes is not None:
            reference.extend(codes)
    report = {"executor_commit": commit, "as_of": day.isoformat(), "references": info,
              "status": "BLOCK", "followup": "EXPLICIT_DATE_FORMATS_AND_HTTP_ERROR_DIAGNOSTIC",
              "raw_provider_bytes_retained": False, "decision_authority": False,
              "execution_allowed": False, "source_independence_verified": False}
    if all(item["status"] == "OBSERVED" for item in info) and len(reference) == len(set(reference)):
        # New live acquisition is conditional on real official reference.
        # The previous scan attachment was not retained and cannot be reused.
        operations = [
            ExecutionOperation(operation_id="market-universe", kind="MARKET_UNIVERSE",
                parameters={"as_of": day.isoformat(), "market": "CN_A", "asset_type": "STOCK",
                            "provider_scope": "SINA_ONLY", "min_universe_size": 5000}),
            ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
                parameters={"as_of": day.isoformat(), "market": "CN_A", "asset_type": "STOCK",
                            "depends_on_operation_ids": ["market-universe"], "top_n": 20,
                            "rule_origin": "SYSTEM_RESEARCH_FILTER",
                            "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                            "rules": [{"field": "amount", "operator": "GE", "threshold": 100000000},
                                      {"field": "pct_change", "operator": "LE", "threshold": -2.0}]}),
        ]
        request = ExecutionRequest(job_id="public-official-listing-control",
            trace_id="public-official-listing-control", subject_repo=repo, subject_commit=commit,
            as_of=day.isoformat(), operations=operations)
        request.request_sha256 = request.compute_hash()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            req = root / "request.json"
            req.write_text(request.model_dump_json(), encoding="utf-8")
            result = execute_request(req, output_dir=root / "out", executor_repo=repo, executor_commit=commit)
            report["scan_execution_status"] = result.status
            report["operations"] = [{"id": op.operation_id, "status": op.status,
                                     "metrics": op.metrics, "warnings": op.warnings, "errors": op.errors}
                                    for op in result.operations]
            if result.status in {"PASS", "WARN"}:
                receipt, selected, snapshot, _ = verify_public_scan_packet(root / "out", repo=repo, commit=commit)
                report["packet"] = receipt
                report["comparison"] = compare_code_sets(reference, snapshot)
                report["candidate_in_observed_official_scope"] = stock_code(
                    selected["code"], require_exchange=False) in set(reference)
                if report["comparison"]["status"] != "BLOCK_INCOMPLETE_OR_AMBIGUOUS":
                    report["status"] = "WARN"
    print("PUBLIC_EXCHANGE_SCAN_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                       allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
