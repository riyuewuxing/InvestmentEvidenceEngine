"""One additional-page observation of the already established Q3 version."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_evidence_engine.issuer_q3_control import observe_pdf

if __name__ == "__main__":
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    with TemporaryDirectory() as temp:
        report = observe_pdf("https://static.cninfo.com.cn/finalpage/2026-10-29/1225635059.PDF",
                             Path(temp), pressure=True)
    report["executor_commit"] = os.environ["GITHUB_SHA"]
    print("PUBLIC_Q3_PRESSURE " + json.dumps(report, sort_keys=True), flush=True)
    raise SystemExit(0 if report["status"] == "OBSERVED" else 2)
