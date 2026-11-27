"""One fixed public full-market observation, not a private strategy or investment signal."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.public_scan_packet import verify_public_scan_packet
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import observe_artifact_file

SHANGHAI = ZoneInfo("Asia/Shanghai")


def main():
    now = datetime.now(SHANGHAI)
    day = now.date().isoformat()
    if now.weekday() >= 5:
        raise SystemExit("No weekend snapshot control")
    repo, commit = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if repo != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("Public control repository mismatch")
    operations = [
        ExecutionOperation(operation_id="market-universe", kind="MARKET_UNIVERSE",
                           parameters={"as_of": day, "market": "CN_A", "asset_type": "STOCK",
                                       "min_universe_size": 5000, "provider_scope": "SINA_ONLY"}),
        ExecutionOperation(operation_id="opportunity-scan", kind="OPPORTUNITY_SCAN",
                           parameters={"as_of": day, "market": "CN_A", "asset_type": "STOCK",
                                       "depends_on_operation_ids": ["market-universe"], "top_n": 20,
                                       "rule_origin": "SYSTEM_RESEARCH_FILTER",
                                       "ranking_semantics": "RESEARCH_PRIORITY_NOT_RETURN_FORECAST",
                                       "rules": [
                                           {"field": "amount", "operator": "GE", "threshold": 100_000_000},
                                           {"field": "pct_change", "operator": "LE", "threshold": -2.0},
                                       ]}),
    ]
    request = ExecutionRequest(job_id="public-universe-control", trace_id="public-control-v1",
                               subject_repo=repo, subject_commit=commit, as_of=day,
                               operations=operations)
    request.request_sha256 = request.compute_hash()
    with tempfile.TemporaryDirectory(prefix="public-universe-control-") as tmp:
        path = Path(tmp) / "request.json"
        out = Path(tmp) / "output"
        path.write_text(request.model_dump_json(), encoding="utf-8")
        result = execute_request(path, output_dir=out, executor_repo=repo, executor_commit=commit)
        summary = {"as_of": day, "executor_commit": commit,
                   "request_sha256": request.request_sha256,
                   "result_sha256": result.result_sha256,
                   "status": result.status, "operations": [],
                   "raw_provider_bytes_retained": False, "source_independence_verified": False,
                   "actual_historical_capture_verified": False, "decision_authority": False,
                   "execution_allowed": False}
        for item in result.operations:
            record = {"operation_id": item.operation_id, "status": item.status,
                      "metrics": item.metrics, "warnings": item.warnings, "errors": item.errors,
                      "observed_artifacts": []}
            for artifact in item.artifacts:
                digest, size = observe_artifact_file(out, artifact.path, artifact.size_bytes)
                if digest != artifact.sha256:
                    raise ValueError("observed digest mismatch")
                record["observed_artifacts"].append({"path": artifact.path, "sha256": digest,
                                                     "size_bytes": size})
                payload = strict_json_loads((out / artifact.path).read_bytes())
                if item.operation_id == "market-universe":
                    record["capture"] = {key: payload.get(key) for key in (
                        "capture_started_at", "retrieved_at", "primary_provider",
                        "quote_trade_date", "quote_trade_date_status", "listing_crosscheck",
                        "provider_history", "row_count", "raw_row_count", "invalid_row_count",
                        "duplicate_row_count", "full_listing_coverage_verified", "pit_safe")}
                    # Do not export any actual securities, prices or provider rows.
                    if isinstance(record["capture"].get("listing_crosscheck"), dict):
                        record["capture"]["listing_crosscheck"].pop("name_mismatch_sample", None)
                elif item.operation_id == "opportunity-scan":
                    record["scan"] = {key: payload.get(key) for key in (
                        "screened_count", "candidate_count", "ranking_semantics",
                        "rule_origin", "pit_safe", "research_only")}
            summary["operations"].append(record)
        if result.status in {"PASS", "WARN"}:
            try:
                receipt, _, codes, _ = verify_public_scan_packet(out, repo=repo, commit=commit)
                summary["packet_verification"] = receipt
                summary["normalized_universe_rows_verified"] = len(codes)
                summary["independent_rank_derivation_verified"] = True
            except (ValueError, TypeError, KeyError, OSError) as exc:
                summary["status"] = "BLOCK"
                summary["packet_verification_error"] = str(exc)
                summary["independent_rank_derivation_verified"] = False
        # Same-day snapshot, never assume closing quote or exact observation time.
        summary["closing_snapshot_verified"] = False
        summary["quote_timestamp_independently_verified"] = False
        print("PUBLIC_UNIVERSE_CONTROL " + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if summary["status"] in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
