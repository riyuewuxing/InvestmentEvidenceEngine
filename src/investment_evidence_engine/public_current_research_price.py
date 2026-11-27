"""Current completed-session observation for a fixed public research case.

No current private account, forecast, fee or execution. Derived hashes do
not replace raw vendor source bodies; do not claim origin independence.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from hashlib import sha256

from .historical_capture import PublicSecurity, observe_pair

FIRST, LAST = date(2026, 10, 26), date(2026, 11, 27)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    # Fixed market-wide alternative, not a selected outperformer.
    candidate = PublicSecurity(symbol="000035", asset_type="STOCK")
    alternative = PublicSecurity(symbol="510300", asset_type="ETF")
    started = datetime.now(UTC).isoformat()
    pair, series = observe_pair(candidate, alternative, FIRST, LAST, providers=("sina", "tencent"))
    terminal = []
    for s in series:
        values = [[x.session.isoformat(), x.close] for x in s.closes]
        terminal.append({"symbol": s.subject_id, "provider": s.source_label,
                         "row_count": len(values), "normalized_sha256": sha256(
                             json.dumps(values, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                         "first": values[0], "terminal": values[-1],
                         "previous": values[-2]})
    complete = pair.get("crosscheck") == "MATCH" and len(terminal) == 4 and all(
        len({tuple(r["terminal"]) for r in terminal if r["symbol"] == subject.symbol}) == 1
        for subject in (candidate, alternative)
    )
    report = {"status": "WARN" if complete else "BLOCK", "pair": pair,
              "terminal_observations": terminal, "started_at": started,
              "observed_cutoff": datetime.now(UTC).isoformat(),
              "executor_commit": os.environ["GITHUB_SHA"], "source_independence_verified": False,
              "historical_vintage_verified": False, "decision_authority": False,
              "execution_allowed": False, "raw_body_retained": False}
    print("PUBLIC_CURRENT_RESEARCH_PRICE " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
