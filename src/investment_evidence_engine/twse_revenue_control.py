"""Fixed TSMC revenue check, using an open TWSE dataset and dated issuer PDF.

The source table's report date is a snapshot date, not a filing timestamp.
Source: Securities and Futures Bureau / Taiwan Stock Exchange, dataset 18420,
Open Government Data License v1.0 (https://data.gov.tw/license).
No raw documents or vendor body publication, no A-share linkage or decision.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import sys
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect
from .issuer_revision_control import normalize_text
from .official_pdf_transport import validate_pdf_shape

URLS = {
    "exchange": "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv",
    "issuer": ("https://pr.tsmc.com/system/files/newspdf/attachment/"
               "382be7eb993b44afd73aa6fbcf92ac792433c7d1/October%202026%20%28E%29_final_wmn.pdf"),
}
MAX_BYTES = 2 * 1024 * 1024
MONTH = date(2026, 10, 1)
DECLARED_DAY = date(2026, 11, 10)
TAIPEI = ZoneInfo("Asia/Taipei")
AMOUNTS = ("營業收入-當月營收", "營業收入-上月營收", "營業收入-去年當月營收",
           "累計營業收入-當月累計營收", "累計營業收入-去年累計營收")
PERCENTS = ("營業收入-上月比較增減(%)", "營業收入-去年同月增減(%)",
            "累計營業收入-前期比較增減(%)")
REQUIRED = {"出表日期", "資料年月", "公司代號", "公司名稱", "產業別", *AMOUNTS, *PERCENTS, "備註"}
# Values are reviewed against the original one-page issuer table. Only used
# to check extracted cells, never to fill a missing response.
PDF_ROW = ("586,890", "511,857", "14.7", "367,473", "59.7", "4,485,617", "3,130,437", "43.3")


def roc_date(value: str, *, month: bool = False) -> date:
    if not re.fullmatch(r"[0-9]{5}" if month else r"[0-9]{7}", value):
        raise ValueError("TWSE_ROC_DATE_SCHEMA")
    return date(int(value[:3]) + 1911, int(value[3:5]), 1 if month else int(value[5:7]))


def amount(value: str) -> int:
    if not re.fullmatch(r"(?:[0-9]{1,15}|[0-9]{1,3}(?:,[0-9]{3}){1,4})", value):
        raise ValueError("TWSE_AMOUNT_SCHEMA")
    number = int(value.replace(",", ""))
    if number <= 0:
        raise ValueError("TWSE_NONPOSITIVE_AMOUNT")
    return number


def percent(value: str) -> Decimal:
    if not re.fullmatch(r"-?[0-9]{1,5}(?:\.[0-9]{1,6})?", value):
        raise ValueError("TWSE_PERCENT_SCHEMA")
    return Decimal(value)


def pct(new: int, old: int) -> Decimal:
    return (Decimal(new) / Decimal(old) - 1) * 100


def round_to(value: Decimal, precision: str) -> Decimal:
    return value.quantize(Decimal(precision), rounding=ROUND_HALF_UP)


def parse_exchange(raw: bytes, observed: datetime) -> dict:
    if not 0 < len(raw) <= MAX_BYTES or observed.utcoffset() is None:
        raise ValueError("TWSE_BODY_OR_CLOCK")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="strict")), strict=True)
    headers = next(reader, [])
    if set(headers) != REQUIRED or len(headers) != len(REQUIRED):
        raise ValueError("TWSE_HEADER_SCHEMA")
    rows, matches = 0, []
    for values in reader:
        rows += 1
        if rows > 5000 or len(values) != len(headers):
            raise ValueError("TWSE_ROW_SCHEMA")
        row = dict(zip(headers, values, strict=True))
        if row["公司代號"] == "2330":
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("TWSE_TARGET_MISSING_OR_DUPLICATE")
    row = matches[0]
    if row["公司名稱"] not in {"台積電", "台灣積體電路製造股份有限公司", "台灣積體電路製造"}:
        raise ValueError("TWSE_TARGET_IDENTITY")
    period = roc_date(row["資料年月"], month=True)
    snapshot = roc_date(row["出表日期"])
    if period != MONTH or not DECLARED_DAY <= snapshot <= observed.astimezone(TAIPEI).date():
        raise ValueError("TWSE_PERIOD_OR_SNAPSHOT_MISMATCH")
    levels = [amount(row[k]) for k in AMOUNTS]
    rates = [percent(row[k]) for k in PERCENTS]
    current, prior, year_ago, ytd, ytd_ago = levels
    if ytd < current or ytd_ago < year_ago:
        raise ValueError("TWSE_CUMULATIVE_AMOUNT")
    calculated = [pct(current, prior), pct(current, year_ago), pct(ytd, ytd_ago)]
    # Independently recompute rates to within 0.011 pp (published rounding).
    if any(abs(a - b) > Decimal("0.011") for a, b in zip(rates, calculated, strict=True)):
        raise ValueError("TWSE_RATE_RECONCILIATION")
    return {"symbol": "2330", "market": "TWSE", "period": period.isoformat(),
            "snapshot_date": snapshot.isoformat(), "source_rows_observed": rows,
            "source_rowset_completeness_verified": False,
            "unit": "TWD_THOUSANDS", "amounts": levels,
            "reported_rates_pct": [str(v) for v in rates],
            "recomputed_rates_pct": [str(round_to(v, "0.000001")) for v in calculated],
            "snapshot_not_publication_clock": True, "historical_vintage_verified": False}


def parse_issuer(raw: bytes) -> dict:
    from pypdf import PdfReader

    validate_pdf_shape(raw, max_bytes=MAX_BYTES)
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) != 1:
        raise ValueError("TSMC_PDF_PAGE_SCOPE")
    flat = normalize_text(reader.pages[0].extract_text() or "")
    required = ("TSMCOctober2026RevenueReport", "November10,2026",
                "TWSE:2330,NYSE:TSM", "TSMCOctoberRevenueReport(Consolidated)",
                "Unit:NT$million")
    if not all(marker in flat for marker in required):
        raise ValueError("TSMC_PDF_IDENTITY")
    target = "NetRevenue" + "".join(PDF_ROW)
    if flat.count(target) != 1:
        raise ValueError("TSMC_PDF_ROW_MISMATCH")
    return {"symbol": "2330", "period": MONTH.isoformat(),
            "declared_release_date": DECLARED_DAY.isoformat(),
            "declared_date_precision": "DAY_ONLY", "first_availability_verified": False,
            "unit": "TWD_MILLIONS",
            "amounts": [amount(PDF_ROW[i]) for i in (0, 1, 3, 5, 6)],
            "reported_rates_pct": [PDF_ROW[i] for i in (2, 4, 7)],
            "normalized_page_sha256": hashlib.sha256(flat.encode()).hexdigest()}


def compare(exchange: dict, issuer: dict) -> dict:
    if any(r.get("symbol") != "2330" or r.get("period") != MONTH.isoformat()
           for r in (exchange, issuer)) or (exchange.get("unit"), issuer.get("unit")) != (
               "TWD_THOUSANDS", "TWD_MILLIONS"):
        raise ValueError("TWSE_COMPARISON_SCOPE")
    exact = exchange["amounts"]
    rounded = issuer["amounts"]
    if len(exact) != 5 or len(rounded) != 5 or any(type(v) is not int or v <= 0 for v in exact + rounded):
        raise ValueError("TWSE_COMPARISON_AMOUNT_SCHEMA")
    # The issuer PDF is in millions; source precision differs by 1,000.
    differences = [str(Decimal(a) / 1000 - Decimal(b)) for a, b in zip(exact, rounded, strict=True)]
    matches = [abs(Decimal(d)) <= Decimal("0.5") for d in differences]
    a_rates, b_rates = exchange["reported_rates_pct"], issuer["reported_rates_pct"]
    if len(a_rates) != 3 or len(b_rates) != 3:
        raise ValueError("TWSE_COMPARISON_RATE_SCHEMA")
    # Direct unrounded ratios, not rounding already rounded exchange rates.
    current, prior, year_ago, ytd, ytd_ago = exact
    rates = [pct(current, prior), pct(current, year_ago), pct(ytd, ytd_ago)]
    rate_match = [round_to(a, "0.1") == percent(b) for a, b in zip(rates, b_rates, strict=True)]
    good = all(matches) and all(rate_match)
    return {"status": "WARN" if good else "BLOCK",
            "comparison": "MATCH_WITH_DECLARED_ROUNDING" if good else "CONFLICT",
            "amount_differences_twd_millions": differences, "amount_matches": matches,
            "rate_matches": rate_match, "same_issuer_upstream": True,
            "historical_vintage_verified": False, "historical_capture_verified": False,
            "first_availability_verified": False, "cross_market_causal_link_verified": False,
            "pit_safe": False, "decision_authority": False, "execution_allowed": False}


def _child(kind: str, target: Path) -> None:
    url = URLS[kind]
    start = datetime.now(UTC)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=12) as res:
            if res.status != 200 or res.geturl() != url:
                raise ValueError("TWSE_RESPONSE_SCOPE")
            if res.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("TWSE_ENCODING")
            if res.headers.get("Content-Range") is not None:
                raise ValueError("TWSE_PARTIAL_RESPONSE")
            raw = res.read(MAX_BYTES + 1)
            declared = res.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (declared is not None and int(declared) != len(raw)):
                raise ValueError("TWSE_BODY_SIZE")
    except (OSError, ValueError) as exc:
        write_worker_result(target, {"kind": kind, "error": type(exc).__name__,
                                     "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(target, {"kind": kind, "url": url,
                                 "started_at": start.isoformat(), "retrieved_at": datetime.now(UTC).isoformat(),
                                 "sha256": hashlib.sha256(raw).hexdigest(),
                                 "body": base64.b64encode(raw).decode("ascii")})


def observe(kind: str) -> dict:
    out = {"kind": kind, "url": URLS[kind], "status": "BLOCK", "raw_body_retained": False}
    result = run_json_worker((sys.executable, "-m", "investment_evidence_engine.twse_revenue_control",
                              "--child", kind), timeout_seconds=25, max_bytes=3 * MAX_BYTES)
    out |= {"worker_status": result.status, "elapsed_seconds": result.elapsed_seconds}
    if result.status != "OK" or result.payload is None:
        return out
    try:
        p = result.payload
        if p["kind"] != kind:
            raise ValueError("TWSE_RECEIPT_KIND")
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if (p["url"] != URLS[kind] or start.utcoffset() is None or end.utcoffset() is None
                or not start <= end <= datetime.now(UTC)):
            raise ValueError("TWSE_RECEIPT_SCOPE")
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if not 0 < len(raw) <= MAX_BYTES or digest != p["sha256"]:
            raise ValueError("TWSE_RECEIPT_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "parent_rehash": "MATCH",
                "retrieved_at": end.isoformat()}
        fields = parse_exchange(raw, end) if kind == "exchange" else parse_issuer(raw)
        return out | {"status": "OBSERVED", "fields": fields}
    except (KeyError, ValueError, TypeError, csv.Error) as exc:
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"(?:TWSE|TSMC)_[A-Z_]+", code) else type(exc).__name__}
    except Exception as exc:  # noqa: BLE001 - parser boundary.
        return out | {"error": type(exc).__name__}


def main() -> int:
    import os

    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    receipts = [observe(kind) for kind in URLS]
    comparison = (compare(receipts[0]["fields"], receipts[1]["fields"])
                  if all(r["status"] == "OBSERVED" for r in receipts)
                  else {"status": "BLOCK", "comparison": "INCOMPLETE"})
    report = comparison | {"executor_commit": os.environ["GITHUB_SHA"], "receipts": receipts,
        "dataset": "https://data.gov.tw/dataset/18420",
        "source_attribution": "金融監督管理委員會證券期貨局、臺灣證券交易所：上市公司每月營業收入彙總表",
        "license": "政府資料開放授權條款-第1版 https://data.gov.tw/license",
        "issuer_source_attribution": "TSMC October 2026 Revenue Report, TSMC",
        "pit_safe": False, "decision_authority": False, "execution_allowed": False,
        "research_only": True, "raw_body_retained": False}
    print("PUBLIC_TWSE_REVENUE_CONTROL " + json.dumps(report, sort_keys=True, ensure_ascii=False,
                                                     allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in URLS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
