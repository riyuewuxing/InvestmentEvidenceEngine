"""Single actual public control, no raw vendor rows in logs or repository."""
from __future__ import annotations

import json
import os
from datetime import date

from investment_evidence_engine.market_worker import _observe
from investment_evidence_engine.retrospective_control import (
    acquire_tencent,
    retrospective_momentum,
    same_window_comparison,
)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    first, last = date(2025, 1, 2), date(2026, 11, 25)
    symbol = "600519"  # public control, unrelated to private account selection
    left, left_info = acquire_tencent(symbol, first, last)
    right, right_info = _observe("eastmoney", symbol, first, last, "")
    report = {"executor_commit": os.environ["GITHUB_SHA"], "symbol": symbol,
              "first_requested": first.isoformat(), "last_requested": last.isoformat(),
              "providers": [left_info, right_info], "raw_provider_bytes_retained": False,
              "historical_vintage_verified": False, "source_independence_verified": False,
              "decision_authority": False, "execution_allowed": False, "status": "BLOCK"}
    frame = left if left is not None else right
    if left is not None and right is not None:
        report["comparison"] = same_window_comparison(left, right)
        if report["comparison"]["status"] != "MATCH_OBSERVED_ROWS":
            frame = None
    else:
        report["comparison"] = {"status": "SINGLE_OR_NO_SOURCE"}
    if frame is not None:
        try:
            report["diagnostic"] = retrospective_momentum(frame, first, last)
            report["status"] = "WARN"
        except (ValueError, RuntimeError) as exc:
            report["blocker"] = str(exc) if str(exc).startswith("RETROSPECTIVE_") else type(exc).__name__
    print("PUBLIC_RETROSPECTIVE_CONTROL " + json.dumps(report, ensure_ascii=False,
                                                     sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
