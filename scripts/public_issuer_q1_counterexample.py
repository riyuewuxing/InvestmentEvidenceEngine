"""Observe only the newly identified Q1 document, with matching parent route."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.issuer_cashflow_control import observe

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    with TemporaryDirectory() as temp:
        result = observe("q1_2026", Path(temp))
    report = {"status": "WARN" if result["status"] == "OBSERVED" else "BLOCK",
              "executor_commit": os.environ["GITHUB_SHA"], "document": result,
              "pit_safe": False, "decision_authority": False}
    print("PUBLIC_ISSUER_Q1_COUNTEREXAMPLE " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if report["status"] == "WARN" else 2)
