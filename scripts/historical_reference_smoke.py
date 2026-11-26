"""Bounded provider smoke using fixed public controls, unrelated to any account.

No records are uploaded. It reports aggregate historical price statistics
and hashes of the exact normalized inputs used, not raw vendor file hashes.
This is NOT historical-vintage or exchange-calendar certification.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_evidence_engine.historical_reference import (
    DailyClose,
    HistoricalCloseSeries,
    historical_pair_reference,
)

# Fixed controls selected independently of private cases.
CONTROLS = ("600519", "510050")
SOURCES = ("eastmoney", "sina")


def child(source: str, symbol: str, start: str, end: str) -> None:
    """Isolated third-party request: stdout carries only the bounded result."""
    import akshare as ak
    import pandas as pd

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if source == "eastmoney":
            method = ak.stock_zh_a_hist if symbol == CONTROLS[0] else ak.fund_etf_hist_em
            frame = method(symbol=symbol, period="daily",
                           start_date=start.replace("-", ""), end_date=end.replace("-", ""), adjust="")
            frame = frame.rename(columns={"日期": "date", "收盘": "close"})
        elif source == "sina" and symbol == CONTROLS[0]:
            frame = ak.stock_zh_a_daily(symbol="sh"+symbol, start_date=start.replace("-", ""),
                                        end_date=end.replace("-", ""), adjust="")
        elif source == "sina" and symbol == CONTROLS[1]:
            frame = ak.fund_etf_hist_sina(symbol="sh"+symbol)
        else:
            raise ValueError("unsupported fixed control")
        if frame is None or frame.empty or not {"date", "close"}.issubset(frame.columns):
            raise ValueError("provider schema or empty data")
        # Sina ETF returns all historical rows; filter explicitly by date.
        # No deduplication, filling, sorting away duplicate conflicts, or
        # substitution of a partial current-session price.
        sessions = pd.to_datetime(frame["date"], errors="raise").dt.date
        rows = sorted(
            (str(day), float(close)) for day, close in zip(sessions, frame["close"])
            if start <= str(day) <= end
        )
    print(json.dumps(rows, allow_nan=False))


def acquire(source: str, symbol: str, start: date, end: date) -> HistoricalCloseSeries:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", source, symbol,
         start.isoformat(), end.isoformat()],
        check=True, capture_output=True, text=True, timeout=30,
    )
    rows = json.loads(proc.stdout)
    return HistoricalCloseSeries(
        subject_id=symbol, currency="CNY", price_basis="RAW_CLOSE", source_label=source,
        closes=tuple(DailyClose(session=date.fromisoformat(d), close=p) for d, p in rows),
    )


def main() -> int:
    # Explicit fixed completed session for the dated regression; not an assumed
    # "yesterday" trading session. Never add today's unfinished bar.
    end = date(2026, 11, 25)
    start = end - timedelta(days=95)
    observed = {}
    failures = []
    for source in SOURCES:
        try:
            left = acquire(source, CONTROLS[0], start, end)
            right = acquire(source, CONTROLS[1], start, end)
            ref = historical_pair_reference(left, right, last_completed_session=end)
            digests = [hashlib.sha256(s.model_dump_json().encode()).hexdigest() for s in (left, right)]
            observed[source] = (left, right, ref, digests)
        except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
            failures.append({"source": source, "error_type": type(exc).__name__})
    if not observed:
        print(json.dumps({"status": "BLOCKED", "failures": failures, "decision_authority": False}))
        return 2
    preferred = next(iter(observed))
    _, _, ref, digests = observed[preferred]
    crosscheck = "SINGLE_SOURCE"
    if len(observed) == 2:
        a, b = observed[SOURCES[0]], observed[SOURCES[1]]
        crosscheck = "MATCH" if all(
            tuple(x.session for x in l.closes) == tuple(x.session for x in r.closes)
            and all(abs(x.close-y.close) / max(x.close,y.close) <= 0.001
                    for x, y in zip(l.closes,r.closes))
            for l,r in zip(a[:2], b[:2])
        ) else "CONFLICT"
    print(json.dumps({
        "status": "OBSERVED_REFERENCE_ONLY", "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "provider_package_version": version("akshare"), "provider_count": len(observed),
        "normalized_input_sha256": digests, "crosscheck": crosscheck,
        "failures": failures, "reference": ref.model_dump(mode="json"),
        "raw_provider_bytes_retained": False,
    }, ensure_ascii=False))
    return 2 if crosscheck == "CONFLICT" else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(*sys.argv[2:])
    else:
        raise SystemExit(main())
