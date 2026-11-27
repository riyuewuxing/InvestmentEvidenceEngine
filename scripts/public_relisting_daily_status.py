"""Fixed relisting status observation: daily flag is not intraday tradability."""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from investment_evidence_engine.action_reference import _rows
from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result

CODE = "sh.601975"
FIELDS = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
          "adjustflag", "tradestatus", "isST"]
LISTING = ["code", "code_name", "ipoDate", "outDate", "type", "status"]
DAYS = ["2019-01-08", "2019-01-09"]


def child(out: Path) -> None:
    import baostock as bs

    started = datetime.now(UTC).isoformat()
    if bs.login().error_code != "0":
        raise ValueError("LOGIN")
    try:
        listing = _rows(bs.query_stock_basic(code=CODE), LISTING, 2)
        rows = _rows(bs.query_history_k_data_plus(
            CODE, ",".join(FIELDS), start_date=DAYS[0], end_date=DAYS[-1],
            frequency="d", adjustflag="3"), FIELDS, 2)
    finally:
        bs.logout()
    write_worker_result(out, {"started": started, "retrieved": datetime.now(UTC).isoformat(),
                              "listing": listing, "rows": rows})


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "subject": CODE, "historical_vintage_verified": False,
              "intraday_tradability_verified": False, "actual_execution_verified": False,
              "decision_authority": False, "execution_allowed": False}
    worker = run_json_worker((sys.executable, __file__, "--child"), timeout_seconds=40,
                             max_bytes=16384)
    report["worker"] = {"status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    try:
        if worker.status != "OK" or worker.payload is None:
            raise ValueError("WORKER_BLOCK")
        p = worker.payload
        rows, listing = p["rows"], p["listing"]
        start, end = (datetime.fromisoformat(p[key]) for key in ("started", "retrieved"))
        if not start.tzinfo or not end.tzinfo or not start <= end <= datetime.now(UTC):
            raise ValueError("OBSERVATION_TIME")
        if (len(listing) != 1 or len(listing[0]) != len(LISTING) or listing[0][0] != CODE
                or [r[0] for r in rows] != DAYS):
            raise ValueError("IDENTITY_OR_COVERAGE")
        for row in rows:
            if (len(row) != len(FIELDS) or row[1] != CODE or row[8] != "3"
                    or row[9] not in ("0", "1") or row[10] not in ("0", "1")):
                raise ValueError("ROW_SCOPE")
            prices = tuple(map(Decimal, row[2:7]))
            if any(not x.is_finite() or x <= 0 for x in prices):
                raise ValueError("PRICE")
        report.update({"status": "WARN", "started": p["started"], "retrieved": p["retrieved"],
                       "listing": dict(zip(LISTING, listing[0], strict=True)),
                       "rows": [dict(zip(FIELDS, r, strict=True)) for r in rows],
                       "first_reference_matches_issuer": Decimal(rows[0][6]) == Decimal("4.31"),
                       "first_open_equals_reference": Decimal(rows[0][2]) == Decimal(rows[0][6]),
                       "next_reference_matches_prior_close": Decimal(rows[1][6]) == Decimal(rows[0][5]),
                       "official_intraday_halts": [["09:31", "10:01"], ["10:03", "14:57"]],
                       "daily_flag_does_not_prove_continuous_trading": True})
    except (ValueError, KeyError, TypeError, ArithmeticError, RuntimeError, IndexError) as exc:
        report["blocker"] = str(exc) if str(exc).isascii() and str(exc).isupper() else type(exc).__name__
    print("PUBLIC_RELISTING_DAILY_STATUS " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
