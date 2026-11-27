"""Retrospective secondary-price crosscheck for two fixed ETF dealing notices."""
from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal

from .historical_capture import PublicSecurity, observe_pair

FIRST = date(2026, 8, 24)
LAST = date(2026, 9, 24)
SUBJECTS = ("159607", "159696")
TARGETS = {
    "159607": ("2026-09-07", "2026-09-08"),
    "159696": ("2026-08-27", "2026-08-28"),
}


def run_control() -> dict:
    subjects = tuple(PublicSecurity(symbol=s, asset_type="ETF") for s in SUBJECTS)
    pair, series = observe_pair(*subjects, FIRST, LAST, providers=("sina", "tencent"))
    rows = []
    for symbol in SUBJECTS:
        group = [s for s in series if s.subject_id == symbol]
        for session in TARGETS[symbol]:
            prices = {
                s.source_label: str(Decimal(str(bar.close)))
                for s in group for bar in s.closes if bar.session.isoformat() == session
            }
            exact = set(prices) == {"sina", "tencent"} and len(set(prices.values())) == 1
            row = {"symbol": symbol, "session": session, "close_by_source": prices,
                   "exact_two_provider_match": exact}
            if symbol == "159696" and session == "2026-08-27":
                row["issuer_reported_close_cny"] = "2.044"
                row["matches_issuer_reported_close"] = exact and Decimal(next(iter(prices.values()))) == Decimal("2.044")
            rows.append(row)
    complete = all(r["exact_two_provider_match"] for r in rows) and all(
        r.get("matches_issuer_reported_close", True) for r in rows
    )
    return {
        "status": "WARN" if complete else "BLOCK", "observations": rows,
        "source_pair_crosscheck": pair, "first": FIRST.isoformat(), "last": LAST.isoformat(),
        "source_independence_verified": False, "historical_vintage_verified": False,
        "daily_close_does_not_prove_intraday_resume_or_fill": True,
        "raw_provider_body_retained": False, "decision_authority": False, "execution_allowed": False,
    }


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    result = run_control() | {"executor_commit": os.environ["GITHUB_SHA"]}
    print("PUBLIC_ETF_DEALING_CLOSE " + json.dumps(result, ensure_ascii=False, sort_keys=True,
                                                   allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
