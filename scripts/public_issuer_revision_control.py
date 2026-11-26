"""One fixed public issuer accounting revision control."""
from __future__ import annotations

import json
import os

from investment_evidence_engine.issuer_revision_control import run_control


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    result = run_control()
    result["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_ISSUER_REVISION_CONTROL " + json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
