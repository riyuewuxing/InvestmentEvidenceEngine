"""Exercise the production research arithmetic on a real sealed market artifact.

Fixed public control subject, not a selected candidate or private Gate2 graph.
No synthetic source hashes, no private input, no claim of PIT or actual fills.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.research_profile import evaluate_market_profile
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import read_verified_artifact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SUBJECT = "600519"
SCOPE = "2026-11-26"
FIRST = date(2025, 1, 2)
LAST = date(2026, 11, 25)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    sha = os.environ["GITHUB_SHA"]
    op = ExecutionOperation(operation_id="market", kind="MARKET_DATA",
        parameters={"subject_ids": [SUBJECT], "as_of": SCOPE,
                    "history_days": (LAST-FIRST).days, "history_end_offset_days": 1,
                    "adjust": "", "price_tolerance": 0.001},
        expected_outputs=["market.json"], evidence_domains=["MARKET"])
    req = ExecutionRequest(job_id="public-research-profile-control",
        trace_id="public-research-profile-20261127", subject_repo=REPO,
        subject_commit=sha, as_of=SCOPE, operations=[op])
    req.request_sha256 = req.compute_hash()
    report = {"status": "BLOCK", "executor_commit": sha, "scope": SCOPE, "subject": SUBJECT,
              "fixed_public_control_not_gate1_candidate": True, "source_graph_verified": False,
              "formal_profile_admitted": False, "pit_safe": False, "decision_authority": False,
              "execution_allowed": False, "raw_body_retained": False}
    with TemporaryDirectory() as temp:
        root = Path(temp)
        path = root / "request.json"
        path.write_text(req.model_dump_json(), encoding="utf-8")
        output = root / "out"
        result = execute_request(path, output_dir=output, executor_repo=REPO, executor_commit=sha)
        assert result.result_sha256 == result.compute_hash()
        item = result.operations[0]
        report |= {"market_status": item.status, "market_errors": item.errors,
                   "market_metrics": item.metrics, "market_warnings": item.warnings,
                   "request_sha256": req.request_sha256, "result_sha256": result.result_sha256}
        if item.status in {"PASS", "WARN"} and len(item.artifacts) == 1:
            art = item.artifacts[0]
            try:
                raw = read_verified_artifact(output, art.path, art.sha256, art.size_bytes)
                data = strict_json_loads(raw)
                if (data["start"], data["end"]) != (FIRST.isoformat(), LAST.isoformat()):
                    raise ValueError("RESEARCH_CONTROL_EXACT_WINDOW_REQUIRED")
                report |= {"market_artifact_rehash": "MATCH", "market_artifact_sha256": art.sha256,
                           "market_artifact_size": len(raw), "crosscheck": data["crosscheck"],
                           "providers": data["providers"]}
                report["profile_diagnostic"] = evaluate_market_profile(raw, symbol=SUBJECT, as_of=SCOPE)
                report["status"] = "WARN"
            except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
                reason = str(exc)
                report["blocker"] = reason if reason.startswith(("RESEARCH_", "RETROSPECTIVE_")) else type(exc).__name__
    print("PUBLIC_RESEARCH_PROFILE_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                           allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
