"""Aggregate current vendor coverage, never a formal market or PIT admission.

Only generic public vendor endpoints. Normalized rows remain in the runner;
stdout contains coverage statistics and aggregate research-priority diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result

REPO = "riyuewuxing/InvestmentEvidenceEngine"
SPECS = {
    "fund_catalog": ("fund_name_em", "基金代码", {"name": "基金简称", "category": "基金类型"}),
    "fund_rank": ("fund_open_fund_rank_em", "基金代码", {"day": "日期", "nav": "单位净值",
                    "month": "近1月", "year": "近1年"}),
    "etf_catalog": ("fund_etf_spot_ths", "基金代码", {"name": "基金名称", "category": "基金类型",
                    "nav": "最新-单位净值", "day": "最新-交易日"}),
    "etf_rank": ("fund_exchange_rank_em", "基金代码", {"day": "日期", "month": "近1月", "year": "近1年"}),
    "etf_quote": ("fund_etf_category_sina", "代码", {"name": "名称", "price": "最新价", "amount": "成交额"}),
}
NUMERIC = {"nav", "month", "year", "price", "amount"}
MAX_ROWS = 100000
MAX_BYTES = 12 * 1024 * 1024


def code6(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:(?:sh|sz|bj))?([0-9]{6})", value.strip().lower())
    return match[1] if match else None


def number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(str(value).strip().removesuffix("%"))
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def session(value: object) -> str | None:
    try:
        text = str(value)
        if isinstance(value, datetime):
            return value.date().isoformat() if value.utcoffset() is None and value.time() == datetime.min.time() else None
        return date.fromisoformat(text).isoformat() if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text) else None
    except ValueError:
        return None


def normalize(key: str, columns: list[str], raw: list[dict]) -> dict:
    _, code_col, fields = SPECS[key]
    if len(columns) != len(set(columns)) or code_col not in columns or not 0 < len(raw) <= MAX_ROWS:
        raise ValueError("COVERAGE_SCHEMA_OR_EMPTY")
    counts: Counter = Counter()
    records = {}
    invalid = 0
    for row in raw:
        code = code6(row.get(code_col))
        if code is None:
            invalid += 1
            continue
        counts[code] += 1
        record = {}
        for field, col in fields.items():
            value = row.get(col)
            if field in NUMERIC:
                val = number(value)
                if field in {"nav", "price"} and val is not None and val <= 0:
                    val = None
                if field == "amount" and val is not None and val < 0:
                    val = None
            elif field == "day":
                val = session(value)
            else:
                val = value.strip() if isinstance(value, str) and value.strip() else None
            record[field] = val
        records[code] = record
    # Every row of an ambiguous identity is excluded, not arbitrarily first/last.
    for code, count in counts.items():
        if count > 1:
            records.pop(code, None)
    duplicate_rows = sum(v for v in counts.values() if v > 1)
    return {"records": records, "raw_count": len(raw), "invalid_rows": invalid,
            "ambiguous_duplicate_rows": duplicate_rows, "missing_columns": sorted(
                col for col in fields.values() if col not in columns)}


def summary(table: dict | None) -> dict:
    if table is None:
        return {"status": "UNAVAILABLE", "usable_count": None}
    rows = table["records"]
    return {"status": "OBSERVED" if rows else "NO_USABLE_ROWS",
            "raw_count": table["raw_count"], "usable_count": len(rows),
            "invalid_rows": table["invalid_rows"],
            "ambiguous_duplicate_rows": table["ambiguous_duplicate_rows"],
            "missing_columns": table["missing_columns"],
            "normalized_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True,
                ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()}


def overlap(left: set[str] | None, right: set[str] | None) -> dict:
    if left is None or right is None or not left:
        return {"denominator": len(left) if left is not None else None, "numerator": None,
                "coverage": None, "extra": None}
    n = len(left & right)
    return {"denominator": len(left), "numerator": n, "coverage": n / len(left),
            "extra": len(right - left)}


def recovery_lens(codes: set[str] | None, rank: dict | None, *, observed_day: str) -> dict:
    # Explicit public diagnostic: negative one-year return and positive one-month return.
    # No forecast, expected return, sector, or manager-quality inference.
    empty = {"status": "UNAVAILABLE", "denominator": len(codes) if codes is not None else None,
             "eligible": None, "matches": None, "latest_vendor_nav_day": None}
    if codes is None or rank is None or not codes:
        return empty
    rows = rank["records"]
    days = Counter(row["day"] for code, row in rows.items() if code in codes and row["day"] is not None
                   and row["day"] <= observed_day)
    if not days:
        return empty
    latest = max(days)
    by_day: dict[str, dict] = {}
    complete = {code: rows[code] for code in codes & rows.keys()
                if rows[code]["day"] in days and rows[code]["month"] is not None
                and rows[code]["year"] is not None}
    for day in sorted(days):
        eligible = {code: r for code, r in complete.items() if r["day"] == day}
        matches = sorted((code for code, r in eligible.items() if r["year"] < 0 < r["month"]),
                         key=lambda code: (eligible[code]["year"], -eligible[code]["month"], code))
        by_day[day] = {"dated_rows": days[day], "eligible": len(eligible), "matches": len(matches),
                       "top20_count": min(20, len(matches)),
                       "top20_order_sha256": hashlib.sha256(json.dumps(matches[:20]).encode()).hexdigest()}
    dominant = max(by_day, key=lambda d: (by_day[d]["eligible"], d))
    selected = by_day[dominant]
    return {"status": "OBSERVED_VENDOR_NAV_RETURN_DIAGNOSTIC", "denominator": len(codes),
            "eligible": selected["eligible"], "matches": selected["matches"],
            "latest_vendor_nav_day": latest, "dominant_eligible_day": dominant,
            "observed_day": observed_day, "observed_day_cohort": by_day.get(observed_day),
            "date_cohorts": by_day,
            "nav_day_counts": dict(sorted(days.items())),
            "missing_or_other_day": len(codes) - selected["eligible"],
            "top20_order_sha256": selected["top20_order_sha256"],
            "rule": "year_return_lt_0_and_month_return_gt_0",
            "order": "year_ascending_month_descending_code_ascending",
            "selection": "MAX_COMPLETE_ROWS_THEN_LATEST_DATE_NO_MIXED_DATE_RANK",
            "formal_pit": False, "expected_return_verified": False}


def analyze(tables: dict, *, observed_day: str) -> dict:
    def records(key):
        value = tables.get(key)
        return value["records"] if value is not None else None

    master = records("fund_catalog")
    etfs = records("etf_catalog")
    quote = records("etf_quote")
    # A vendor ETF directory is not a listing authority; ambiguous feeder names
    # must not leak into the listed ETF diagnostic.
    def etf_scope(rows):
        if not rows:
            return None
        return {c for c, r in rows.items() if r.get("name") and "联接" not in r["name"]}

    ths_codes, sina_codes = etf_scope(etfs), etf_scope(quote)
    # Use the observed ETF quote directory as primary, not an official registry.
    # THS is a distinct vendor scope; do not silently turn its absence into zero.
    etf_codes = sina_codes if sina_codes else ths_codes if ths_codes else None
    excluded = (ths_codes or set()) | (sina_codes or set())
    fund_codes = ({c for c, r in master.items() if c not in excluded and r.get("name")
                   and ("ETF" not in r["name"].upper() or "联接" in r["name"])}
                  if master and etf_codes is not None else None)
    # Vendor category labels are diagnostic, not authenticated product metadata.
    fund_rank = records("fund_rank")
    etf_rank = records("etf_rank")
    return {"tables": {key: summary(tables.get(key)) for key in SPECS},
            "fund_vendor_catalog_scope": {"code_count": len(fund_codes) if fund_codes is not None else None,
                "share_class_not_product_count": True, "official_universe_verified": False,
                "category_counts": dict(Counter(master[c].get("category") or "UNKNOWN" for c in fund_codes))
                if fund_codes is not None else None,
                "rank_coverage": overlap(fund_codes, set(fund_rank) if fund_rank is not None else None),
                "recovery_lens": recovery_lens(fund_codes, tables.get("fund_rank"), observed_day=observed_day),
                "category_recovery_lenses": {category: recovery_lens(
                    {c for c in fund_codes if (master[c].get("category") or "UNKNOWN") == category},
                    tables.get("fund_rank"), observed_day=observed_day)
                    for category in sorted({master[c].get("category") or "UNKNOWN" for c in fund_codes})}
                    if fund_codes is not None else None},
            "etf_vendor_catalog_scope": {"code_count": len(etf_codes) if etf_codes is not None else None,
                "denominator_source": "SINA_ETF_CATEGORY" if sina_codes else "THS_ETF_CATEGORY" if ths_codes else None,
                "independent_vendor_directory_overlap": overlap(sina_codes, ths_codes),
                "nav_coverage": overlap(etf_codes, {c for c, row in etfs.items()
                    if row.get("nav") is not None and row.get("day") is not None and row["day"] <= observed_day}
                    if etfs is not None else None),
                "official_universe_verified": False,
                "subtype_verified_count": 0 if etf_codes is not None else None,
                "subtype_unknown_count": len(etf_codes) if etf_codes is not None else None,
                "rank_coverage": overlap(etf_codes, set(etf_rank) if etf_rank is not None else None),
                "secondary_quote_coverage": overlap(etf_codes, set(quote) if quote is not None else None),
                "positive_secondary_price_coverage": overlap(etf_codes,
                    {c for c, row in quote.items() if row.get("price") is not None} if quote is not None else None),
                "recovery_lens": recovery_lens(etf_codes, tables.get("etf_rank"), observed_day=observed_day)},
            "industry_coverage": "NOT_ESTABLISHED", "industry_reversal": "UNKNOWN",
            "research_only": True, "decision_authority": False, "execution_allowed": False,
            "formal_pit": False, "raw_provider_bytes_retained": False}


def child(key: str, path: Path) -> None:
    import akshare as ak
    import pandas as pd

    start = datetime.now(UTC).isoformat()
    try:
        endpoint, _, _ = SPECS[key]
        kwargs = {"symbol": "全部"} if key == "fund_rank" else {"symbol": "ETF基金"} if key == "etf_quote" else {}
        df = getattr(ak, endpoint)(**kwargs)
        if not isinstance(df, pd.DataFrame):
            raise ValueError("NOT_DATAFRAME")
        # Preserve true missing values; never coerce into zero or an open status.
        df = df.astype(object).where(pd.notna(df), None)
        result = normalize(key, list(df.columns), df.to_dict(orient="records"))
        payload = {"status": "OBSERVED", "table": result}
    except Exception as exc:
        payload = {"status": "BLOCK", "error_type": type(exc).__name__}
    write_worker_result(path, payload | {"key": key, "started_at": start,
        "finished_at": datetime.now(UTC).isoformat(), "akshare_version": str(ak.__version__)},
        max_bytes=MAX_BYTES)


def observe(key: str) -> tuple[str, dict | None, dict]:
    before = datetime.now(UTC)
    result = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_multiasset_coverage", "--child", key),
                             timeout_seconds=65, max_bytes=MAX_BYTES)
    meta = {"worker_status": result.status, "elapsed_seconds": result.elapsed_seconds,
            "endpoint": SPECS[key][0]}
    if result.status != "OK" or result.payload is None:
        return key, None, meta
    payload = result.payload
    try:
        a, b = (datetime.fromisoformat(payload[k]) for k in ("started_at", "finished_at"))
        if payload["key"] != key or a.utcoffset() is None or b.utcoffset() is None or not before <= a <= b <= datetime.now(UTC):
            raise ValueError("CLOCK_OR_SCOPE")
        meta |= {k: payload[k] for k in ("started_at", "finished_at", "akshare_version", "status")}
        if payload["status"] != "OBSERVED":
            return key, None, meta | {"error_type": payload.get("error_type")}
        return key, payload["table"], meta
    except (ValueError, KeyError, TypeError):
        return key, None, meta | {"status": "BLOCK_RECEIPT"}


def main() -> int:
    from zoneinfo import ZoneInfo

    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    start = datetime.now(UTC)
    day = start.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(observe, SPECS))
    report = analyze({key: table for key, table, _ in results}, observed_day=day)
    report |= {"executor_commit": os.environ["GITHUB_SHA"], "observed_day": day,
               "started_at": start.isoformat(), "finished_at": datetime.now(UTC).isoformat(),
               "observations": {key: meta for key, _, meta in results},
               "status": "WARN" if all(table is not None and table["records"] for _, table, _ in results) else "BLOCK_PARTIAL"}
    print("PUBLIC_MULTIASSET_COVERAGE " + json.dumps(report, ensure_ascii=False, sort_keys=True,
                                                      allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in SPECS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
