"""Same issuer second official host and full report cash-flow evidence."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.issuer_cashflow_control import main

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = main()
    report["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_ISSUER_CASHFLOW_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
