"""Bounded public SW first-level industry price recovery diagnostic; no forecasts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .bounded_worker import run_json_worker, write_worker_result
from .public_multiasset_coverage import REPO, number, session

MAX_BYTES = 2 * 1024 * 1024
ENDPOINT = "index_analysis_daily_sw"
WINDOWS = {"recent": (0, 7), "month": (30, 7), "year": (365, 7)}


def windows(day: date) -> dict:
    return {name: ((day - timedelta(days=offset + width)).isoformat(),
                   (day - timedelta(days=offset)).isoformat())
            for name, (offset, width) in WINDOWS.items()}


def normalize(rows: list[dict], start: str, end: str) -> dict:
    if not 0 < len(rows) <= 1000:
        raise ValueError("SW_EMPTY_OR_OVERSIZE")
    keyed: dict[tuple[str, str], dict] = {}
    counts: Counter = Counter()
    invalid = 0
    for row in rows:
        code = str(row.get("指数代码") or "")
        day = session(row.get("发布日期"))
        name = row.get("指数名称")
        close = number(row.get("收盘指数"))
        if not re.fullmatch(r"801[0-9]{3}(?:\.SI)?", code) or day is None or not start <= day <= end:
            invalid += 1
            continue
        key = (code[:6], day)
        counts[key] += 1
        keyed[key] = {"code": key[0], "day": day, "name": name.strip() if isinstance(name, str) else None,
                      "close": close if close is not None and close > 0 else None}
    unique = [row for key, row in sorted(keyed.items()) if counts[key] == 1]
    return {"rows": unique, "raw_count": len(rows), "invalid_count": invalid,
            "ambiguous_duplicate_rows": sum(n for n in counts.values() if n > 1),
            "normalized_sha256": hashlib.sha256(json.dumps(unique, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()}


def choose_anchor(table: dict | None) -> tuple[str | None, dict]:
    if table is None:
        return None, {}
    # Select latest date among those with the largest count of valid distinct closes.
    days: dict[str, dict] = {}
    for r in table["rows"]:
        if r["close"] is not None:
            days.setdefault(r["day"], {})[r["code"]] = r
    if not days:
        return None, {}
    selected = max(days, key=lambda d: (len(days[d]), d))
    return selected, days[selected]


def analyze(tables: dict, expected: dict) -> dict:
    anchors = {name: choose_anchor(tables.get(name)) for name in WINDOWS}
    recent_day, recent = anchors["recent"]
    month_day, month = anchors["month"]
    year_day, year = anchors["year"]
    # The only denominator is the observed recent vendor scope; no listing authority.
    eligible = sorted(set(recent) & set(month) & set(year))
    comparable = []
    identity_mismatch = 0
    for code in eligible:
        a, b, c = recent[code], month[code], year[code]
        if not a["name"] or a["name"] != b["name"] or a["name"] != c["name"]:
            identity_mismatch += 1
            continue
        short = (a["close"] / b["close"] - 1) * 100
        long = (a["close"] / c["close"] - 1) * 100
        if not all(map(lambda x: abs(x) < 1e6, (short, long))):
            continue
        comparable.append({"code": code, "industry": a["name"], "short_price_return_pct": round(short, 6),
                           "long_price_return_pct": round(long, 6), "matches": long < 0 < short})
    matches = sorted((r for r in comparable if r["matches"]),
                     key=lambda r: (r["long_price_return_pct"], -r["short_price_return_pct"], r["code"]))
    return {"status": "WARN" if comparable else "BLOCK_INCOMPLETE",
            "provider": "AKSHARE_SW_INDEX_ANALYSIS_DAILY", "scope": "SW_FIRST_LEVEL_VENDOR_OBSERVATION",
            "official_listing_verified": False, "historical_capture_verified": False,
            "windows": {name: {"requested_start": expected[name][0], "requested_end": expected[name][1],
                       "selected_day": anchors[name][0], "valid_close_count": len(anchors[name][1]),
                       "receipt": {k: v for k, v in tables[name].items() if k != "rows"}
                       if tables.get(name) is not None else None} for name in WINDOWS},
            "recent_scope_count": len(recent) if recent_day else None,
            "common_identity_complete_count": len(comparable) if all((recent_day, month_day, year_day)) else None,
            "identity_mismatch_count": identity_mismatch if all((recent_day, month_day, year_day)) else None,
            "match_count": len(matches) if comparable else None,
            "research_candidates": matches[:10],
            "rule": "COMMON_DATED_PRICE_INDEX_LONG_NEGATIVE_SHORT_POSITIVE",
            "not_total_return": True, "exact_lookback_days": False,
            "expectation_gap_verified": False, "fundamental_recovery_verified": False,
            "formal_pit": False, "research_only": True, "decision_authority": False,
            "execution_allowed": False, "raw_provider_bytes_retained": False}


def child(start: str, end: str, path: Path) -> None:
    import akshare as ak
    import pandas as pd

    before = datetime.now(UTC).isoformat()
    try:
        df = getattr(ak, ENDPOINT)(symbol="一级行业", start_date=start.replace("-", ""),
                                    end_date=end.replace("-", ""))
        if not isinstance(df, pd.DataFrame):
            raise ValueError("NOT_DATAFRAME")
        required = {"指数代码", "指数名称", "发布日期", "收盘指数"}
        if not required.issubset(df.columns) or len(set(df.columns)) != len(df.columns):
            raise ValueError("SW_SCHEMA")
        df = df.astype(object).where(pd.notna(df), None)
        payload = {"status": "OBSERVED", "table": normalize(df.to_dict(orient="records"), start, end)}
    except Exception as exc:
        payload = {"status": "BLOCK", "error_type": type(exc).__name__}
    write_worker_result(path, payload | {"start": start, "end": end,
        "started_at": before, "finished_at": datetime.now(UTC).isoformat(),
        "version": str(ak.__version__)}, max_bytes=MAX_BYTES)


def observe(item: tuple[str, tuple[str, str]]) -> tuple:
    name, (start, end) = item
    before = datetime.now(UTC)
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_industry_coverage",
                              "--child", start, end), timeout_seconds=90, max_bytes=MAX_BYTES)
    meta = {"status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    payload = worker.payload
    if worker.status != "OK" or not isinstance(payload, dict):
        return name, None, meta
    try:
        a, b = [datetime.fromisoformat(payload[k]) for k in ("started_at", "finished_at")]
        if payload["start"] != start or payload["end"] != end or a.utcoffset() is None or b.utcoffset() is None or not before <= a <= b <= datetime.now(UTC):
            raise ValueError("SCOPE_OR_CLOCK")
        meta |= {k: payload[k] for k in ("status", "started_at", "finished_at", "version")}
        if payload["status"] != "OBSERVED":
            return name, None, meta | {"error_type": payload.get("error_type")}
        return name, payload["table"], meta
    except (KeyError, TypeError, ValueError):
        return name, None, meta | {"status": "BLOCK_RECEIPT"}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    start = datetime.now(UTC)
    day = start.astimezone(ZoneInfo("Asia/Shanghai")).date()
    expected = windows(day)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(observe, expected.items()))
    report = analyze({name: table for name, table, _ in results}, expected)
    report |= {"executor_commit": os.environ["GITHUB_SHA"], "observed_day": day.isoformat(),
               "started_at": start.isoformat(), "finished_at": datetime.now(UTC).isoformat(),
               "observations": {name: meta for name, _, meta in results}}
    print("PUBLIC_INDUSTRY_COVERAGE " + json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
