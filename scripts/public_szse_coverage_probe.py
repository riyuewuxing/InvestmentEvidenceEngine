"""One bounded public official aggregate and alternative first-page observation."""
import json
import os

from investment_evidence_engine.szse_coverage_probe import observe

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = {"monthly": observe("monthly"), "page": observe("page"),
              "executor_commit": os.environ["GITHUB_SHA"],
              "complete_listing_verified": False, "decision_authority": False}
    print("PUBLIC_SZSE_COVERAGE " + json.dumps(report, sort_keys=True), flush=True)
    raise SystemExit(0 if report["monthly"]["status"] == "OBSERVED" else 2)
