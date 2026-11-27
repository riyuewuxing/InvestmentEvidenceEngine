"""One fixed public candidate; current-vintage historical rows only."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from investment_evidence_engine.action_reference import _rows
from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.cash_execution_math import ReferenceDay, reference_chain
from investment_evidence_engine.market_calendar import scheduled_days
from investment_evidence_engine.retrospective_control import acquire_tencent

REPO = "riyuewuxing/InvestmentEvidenceEngine"
FIRST, LAST = date(2026, 7, 1), date(2026, 8, 31)
CODE = "sz.000001"
FIELDS = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
          "adjustflag", "tradestatus", "isST"]
LISTING = ["code", "code_name", "ipoDate", "outDate", "type", "status"]


def child(out: Path) -> None:
    import baostock as bs

    started = datetime.now(UTC).isoformat()
    if bs.login().error_code != "0":
        raise ValueError("LOGIN")
    try:
        listing = _rows(bs.query_stock_basic(code=CODE), LISTING, 2)
        rows = _rows(bs.query_history_k_data_plus(
            CODE, ",".join(FIELDS), start_date=FIRST.isoformat(),
            end_date=LAST.isoformat(), frequency="d", adjustflag="3"), FIELDS, 756)
    finally:
        bs.logout()
    write_worker_result(out, {"started": started, "retrieved": datetime.now(UTC).isoformat(),
                              "listing": listing, "rows": rows})


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "subject": CODE, "first": FIRST.isoformat(), "last": LAST.isoformat(),
              "historical_vintage_verified": False, "actual_execution_verified": False,
              "decision_authority": False, "execution_allowed": False}
    worker = run_json_worker((sys.executable, __file__, "--child"), timeout_seconds=40,
                             max_bytes=256*1024)
    report["baostock_worker"] = {"status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    try:
        if worker.status != "OK" or worker.payload is None:
            raise ValueError("BAOSTOCK_WORKER_BLOCK")
        p = worker.payload
        started, retrieved = (datetime.fromisoformat(p[key]) for key in ("started", "retrieved"))
        if not started.tzinfo or not retrieved.tzinfo or not started <= retrieved <= datetime.now(UTC):
            raise ValueError("OBSERVATION_TIME")
        listing = p["listing"]
        if (len(listing) != 1 or len(listing[0]) != 6 or listing[0][0] != CODE
                or listing[0][3:] != ["", "1", "1"]
                or (FIRST - date.fromisoformat(listing[0][2])).days < 365):
            raise ValueError("CURRENT_LISTING_SCOPE")
        rows = p["rows"]
        report["listing_observed"] = {"ipo_date": listing[0][2], "out_date": listing[0][3],
            "type": listing[0][4], "status": listing[0][5], "historical_identity_verified": False}
        report["baostock_observation"] = {"rows": len(rows), "started": p["started"],
            "retrieved": p["retrieved"], "normalized_rows_sha256": hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
            "trading_status_counts": {k: sum(r[9] == k for r in rows) for k in ("0", "1")},
            "st_flag_counts": {k: sum(r[10] == k for r in rows) for k in ("0", "1")}}
        sessions = tuple(r.day for r in scheduled_days(FIRST, LAST) if r.is_trading_day)
        if tuple(date.fromisoformat(r[0]) for r in rows) != sessions:
            raise ValueError("BAOSTOCK_COVERAGE")
        if any(r[1] != CODE or r[8] != "3" or r[9] not in ("0", "1") for r in rows):
            raise ValueError("ROW_IDENTITY_OR_STATUS")
        diagnostic = reference_chain(tuple(ReferenceDay(date.fromisoformat(r[0]),
            Decimal(r[5]), Decimal(r[6]) if r[6] else None, r[9] == "0",
            Decimal(r[7]) if r[7] else None) for r in rows))
        report["reference_chain"] = diagnostic
        report["reference_break_cells"] = [
            {"session": row[0], "prior_close": rows[i-1][5], "reference": row[6], "close": row[5]}
            for i, row in enumerate(rows) if i and
            any(v["session"] == row[0] for v in diagnostic["blockers"])]
        other, info = acquire_tencent(CODE[3:], FIRST, LAST)
        report["tencent"] = info
        if other is None or tuple(other["date"].dt.date) != sessions:
            raise ValueError("TENCENT_COVERAGE")
        for left, right in zip(rows, other.itertuples(index=False), strict=True):
            if tuple(map(Decimal, left[2:6])) != tuple(
                    Decimal(str(getattr(right, k))) for k in ("open", "high", "low", "close")):
                raise ValueError("EXACT_OHLC_MISMATCH")
        report["exact_ohlc_crosscheck"] = "MATCH"
        report["status"] = "WARN" if diagnostic["status"] != "BLOCK" else "BLOCK"
        report["diagnostic_completed"] = True
    except (ValueError, KeyError, TypeError, ArithmeticError, RuntimeError, IndexError) as exc:
        report["blocker"] = str(exc) if str(exc).isascii() and str(exc).isupper() else type(exc).__name__
    print("PUBLIC_STRICT_REFERENCE_CHAIN " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
