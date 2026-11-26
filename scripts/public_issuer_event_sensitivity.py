"""Fixed two-clock, two-source-per-asset retrospective research control."""
import json
import os

from investment_evidence_engine.historical_capture import observe_pair
from investment_evidence_engine.issuer_event_sensitivity import (
    BENCHMARK,
    FIRST,
    ISSUER,
    LAST,
    event_sensitivity,
)

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    summary, series = observe_pair(ISSUER, BENCHMARK, FIRST, LAST, providers=("sina", "tencent"))
    result = event_sensitivity(series)
    result["actual_attempts"] = summary
    result["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_ISSUER_EVENT_SENSITIVITY " + json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    raise SystemExit(0 if result["status"] == "WARN" else 2)
