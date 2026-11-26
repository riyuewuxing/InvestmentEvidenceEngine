"""Public issuer disclosure metadata observation; nonempty directory sentinel."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.issuer_disclosure_index import run_control

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = run_control()
    report["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_ISSUER_INDEX_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
