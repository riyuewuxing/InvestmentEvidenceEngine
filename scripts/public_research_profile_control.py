"""Exercise the production research arithmetic on a real sealed market artifact.

Fixed public control subject, not a selected candidate or private Gate2 graph.
No synthetic source hashes, no private input, no claim of PIT or actual fills.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.contracts import ExecutionOperation, ExecutionRequest
from investment_evidence_engine.research_profile_evidence import (
    canonical_sha256,
    evaluate_market_profile,
)
from investment_evidence_engine.runner import execute_request
from investment_evidence_engine.snapshot_integrity import strict_json_loads
from investment_evidence_engine.transport_integrity import read_verified_artifact

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SUBJECT = "600519"
SCOPE = "2026-11-26"
FIRST = date(2025, 1, 2)
LAST = date(2026, 11, 25)


EXPECTED_BARS_SHA256 = "aeb60bb14f900b396ac0abb4ec3db32c90ef6d59e2c1dce8f44fceb6bef8cd88"
PRIOR_RUN = 45853666093
PRIOR_JOB = 140026299369
PRIOR_EXECUTOR = "53020c1b280042e4999ebfe1831d58b00cd3a04d"
PRIOR_DIAGNOSTIC = Path(__file__).resolve().parents[1] / "fixtures/research_profile/observed_20261126_000035_diagnostic.json"


def main(*, same_version: bool = False, fresh_recompute: bool = False) -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    sha = os.environ["GITHUB_SHA"]
    subject = "000035" if same_version or fresh_recompute else SUBJECT
    op = ExecutionOperation(operation_id="market", kind="MARKET_DATA",
        parameters={"subject_ids": [subject], "as_of": SCOPE,
                    "history_days": (LAST-FIRST).days, "history_end_offset_days": 1,
                    "adjust": "", "price_tolerance": 0.001},
        expected_outputs=["market.json"], evidence_domains=["MARKET"])
    req = ExecutionRequest(job_id="public-research-profile-control",
        trace_id="public-research-profile-20261127-recompute" if same_version else "public-research-profile-20261127", subject_repo=REPO,
        subject_commit=sha, as_of=SCOPE, operations=[op])
    req.request_sha256 = req.compute_hash()
    report = {"status": "BLOCK", "executor_commit": sha, "scope": SCOPE, "subject": subject,
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
                if same_version:
                    actual_digest = canonical_sha256(data["bars"])
                    report |= {"prior_run": PRIOR_RUN, "prior_job": PRIOR_JOB,
                               "prior_executor_commit": PRIOR_EXECUTOR,
                               "expected_prior_bars_sha256": EXPECTED_BARS_SHA256,
                               "observed_bars_sha256": actual_digest,
                               "normalized_bar_version_match": actual_digest == EXPECTED_BARS_SHA256}
                    if actual_digest != EXPECTED_BARS_SHA256:
                        raise ValueError("RESEARCH_PRIOR_NORMALIZED_BAR_VERSION_MISMATCH")
                    prior = strict_json_loads(PRIOR_DIAGNOSTIC.read_bytes())
                    current = evaluate_market_profile(raw, symbol=subject, as_of=SCOPE)
                    report |= {"prior_diagnostic_sha256": canonical_sha256(prior),
                               "current_diagnostic_sha256": canonical_sha256(current["raw_price_diagnostic"]),
                               "prior_exact_diagnostic_recompute": "MATCH" if canonical_sha256(prior)
                                   == canonical_sha256(current["raw_price_diagnostic"]) else "MISMATCH"}
                    if report["prior_exact_diagnostic_recompute"] != "MATCH":
                        raise ValueError("RESEARCH_PRIOR_DIAGNOSTIC_RECOMPUTE_MISMATCH")
                    report["profile_diagnostic"] = current
                else:
                    report["profile_diagnostic"] = evaluate_market_profile(raw, symbol=subject, as_of=SCOPE)
                    if fresh_recompute:
                        import pandas as pd

                        from investment_evidence_engine.retrospective_control import (
                            retrospective_momentum,
                        )

                        first_pass = report["profile_diagnostic"]
                        reopened = read_verified_artifact(output, art.path, art.sha256, art.size_bytes)
                        second_pass = evaluate_market_profile(reopened, symbol=subject, as_of=SCOPE)
                        wrapper = retrospective_momentum(pd.DataFrame(data["bars"]), FIRST, LAST)
                        if (canonical_sha256(first_pass) != canonical_sha256(second_pass)
                                or canonical_sha256(wrapper) != canonical_sha256(first_pass["raw_price_diagnostic"])):
                            raise ValueError("RESEARCH_FRESH_ARITHMETIC_RECOMPUTE_MISMATCH")
                        report |= {"fresh_observed_version_only": True, "prior_version_match_claimed": False,
                                   "same_artifact_reopen_and_recompute": "MATCH",
                                   "existing_wrapper_recompute": "MATCH",
                                   "prior_normalized_bar_version_mismatch_preserved": True}
                report["status"] = "WARN"
            except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
                reason = str(exc)
                report["blocker"] = reason if reason.startswith(("RESEARCH_", "RETROSPECTIVE_")) else type(exc).__name__
    print("PUBLIC_RESEARCH_PROFILE_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                           allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 1:
        raise SystemExit(main())
    if sys.argv[1:] == ["--same-version"]:
        raise SystemExit(main(same_version=True))
    if sys.argv[1:] == ["--fresh-recompute"]:
        raise SystemExit(main(fresh_recompute=True))
    raise SystemExit(2)
