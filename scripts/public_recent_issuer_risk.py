"""One fixed issuer risk index observation; no original-body admission."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.issuer_disclosure_index import OBSERVED_ORG_ID, observe

if __name__ == "__main__":
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    result, _ = observe("recent-risk", OBSERVED_ORG_ID)
    result |= {"executor_commit": os.environ["GITHUB_SHA"], "historical_pit": False,
               "decision_authority": False, "execution_allowed": False}
    print("PUBLIC_RECENT_ISSUER_RISK " + json.dumps(result, ensure_ascii=False, sort_keys=True,
                                                       allow_nan=False), flush=True)
    raise SystemExit(0 if result["status"] == "OBSERVED" else 2)
