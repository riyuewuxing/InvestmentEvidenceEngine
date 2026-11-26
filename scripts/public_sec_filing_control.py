"""Bounded fixed Apple SEC disclosure source control."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.sec_filing_control import emit_retention_candidate, run_control

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report, raw = run_control()
    report["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_SEC_FILING_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    if raw is not None:
        emit_retention_candidate(raw)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
