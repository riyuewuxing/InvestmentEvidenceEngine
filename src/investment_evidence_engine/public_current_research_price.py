"""Current completed-session observation for a fixed public research case.

No current private account, forecast, fee or execution. Derived hashes do
not replace raw vendor source bodies; do not claim origin independence.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from hashlib import sha256

from .historical_capture import PublicSecurity, acquire_series, observe_pair
from .market_calendar import acquire_calendar, check_calendar

FIRST, LAST = date(2026, 10, 26), date(2026, 11, 27)


# Exact prior Tencent normalized series, not an asserted fresh response.
PRIOR_ETF_HASH = "46328c8f782c0bea606517583c7195747ab752a1571541ac55536fb85a7dcb38"


def summarize_supplement(series, sessions: tuple[date, ...] | None) -> dict:
    if series.subject_id != "510300" or series.source_label != "eastmoney" or series.price_basis != "RAW_CLOSE":
        raise ValueError("CURRENT_ETF_SUPPLEMENT_SCOPE")
    rows = [[x.session.isoformat(), x.close] for x in series.closes]
    digest = sha256(json.dumps(rows, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    match = digest == PRIOR_ETF_HASH
    calendar_match = sessions is not None and tuple(x.session for x in series.closes) == sessions
    return {"row_count": len(rows), "first": rows[0], "terminal": rows[-1], "previous": rows[-2],
            "normalized_sha256": digest, "prior_tencent_normalized_sha256": PRIOR_ETF_HASH,
            "exact_prior_tencent_projection_match": match,
            "observed_calendar_sessions_match": calendar_match,
            "status": "WARN" if match and calendar_match else "BLOCK"}


def supplement() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    started = datetime.now(UTC).isoformat()
    report = {"status": "BLOCK", "started_at": started, "prior_price_job": 140425520748,
              "alternative": "510300", "provider": "eastmoney",
              "source_independence_verified": False, "historical_vintage_verified": False,
              "raw_body_retained": False, "decision_authority": False, "execution_allowed": False}
    sessions = None
    try:
        cal = acquire_calendar(FIRST, LAST)
        sessions = check_calendar(cal, first=FIRST, last=LAST, cutoff=datetime.now(UTC))
        report |= {"calendar_status": "MATCH_SCHEDULE_AND_VENDOR", "calendar_session_count": len(sessions),
                   "calendar_observed_at": cal.observed_at.isoformat(),
                   "calendar_sha256": sha256(cal.model_dump_json().encode()).hexdigest()}
    except (OSError, ValueError) as exc:
        report |= {"calendar_status": "BLOCK", "calendar_error": str(exc)[:120]}
    try:
        series = acquire_series("eastmoney", PublicSecurity(symbol="510300", asset_type="ETF"), FIRST, LAST)
        report |= summarize_supplement(series, sessions)
    except (OSError, ValueError) as exc:
        report["alternative_error"] = str(exc)[:120]
    print("PUBLIC_CURRENT_ETF_SUPPLEMENT " + json.dumps(report | {"executor_commit": os.environ["GITHUB_SHA"],
          "observed_cutoff": datetime.now(UTC).isoformat()}, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


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
    if sys.argv[1:] == ["--alternative-supplement"]:
        raise SystemExit(supplement())
    if len(sys.argv) == 1:
        raise SystemExit(main())
    raise SystemExit(2)
