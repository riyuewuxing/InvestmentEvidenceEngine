"""Locate issuer Q3 filing metadata without selecting or parsing a version."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.issuer_disclosure_index import OBSERVED_ORG_ID, observe

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    result, _ = observe("q3", OBSERVED_ORG_ID)
    report = {"status": "WARN" if result["status"] == "OBSERVED" and result["candidate_count"] else "BLOCK",
              "executor_commit": os.environ["GITHUB_SHA"], "index": result,
              "pit_safe": False, "decision_authority": False}
    print("PUBLIC_ISSUER_Q3_DISCOVERY " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
