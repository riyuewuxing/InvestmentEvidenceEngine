"""Current official delisting-directory coverage, not historical membership admission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .exchange_listing import _listing_day
from .listing_comparison import stock_code
from .snapshot_integrity import strict_json_loads

MAX_BYTES = 4 * 1024 * 1024
SCOPES = ("sse_delisted", "szse_delisted")
ANCHORS = {
    "sse_delisted": {"600462": "2025-07-21", "600190": "2025-07-25", "600837": "2025-03-04"},
    "szse_delisted": {"000016": "2026-10-23"},
}
CUTS = ("2024-12-31", "2025-12-31", "2026-10-31")


def endpoint(scope: str) -> tuple[str, str]:
    # Fixed routes supported by the published AKShare stock_info.py reference;
    # no adapter fallback or guessed alternative path after a failure.
    if scope == "sse_delisted":
        params = {"sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "isPagination": "true",
                  "STOCK_CODE": "", "CSRC_CODE": "", "REG_PROVINCE": "", "STOCK_TYPE": "1,2,8",
                  "COMPANY_STATUS": "3", "type": "inParams", "pageHelp.cacheSize": "1",
                  "pageHelp.beginPage": "1", "pageHelp.pageSize": "500",
                  "pageHelp.pageNo": "1", "pageHelp.endPage": "1"}
        return ("https://query.sse.com.cn/commonQuery.do?" + urllib.parse.urlencode(params),
                "https://www.sse.com.cn/assortment/stock/list/delisting/")
    if scope == "szse_delisted":
        return ("https://www.szse.cn/api/report/ShowReport?" + urllib.parse.urlencode({
            "SHOWTYPE": "xlsx", "CATALOGID": "1793_ssgs", "TABKEY": "tab2",
            "random": "0.6935816432433362"}),
            "https://www.szse.cn/market/stock/suspend/index.html")
    raise ValueError("DELIST_UNKNOWN_SCOPE")


def code_value(value: object, *, numeric: bool = False) -> str:
    if numeric and type(value) is int and 0 <= value <= 999999:
        value = f"{value:06d}"
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{6}", value) is None:
        raise ValueError("DELIST_CODE_SCHEMA")
    return value


def integer(value: object) -> int:
    if type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        result = int(value)
        if 0 <= result <= 10000:
            return result
    raise ValueError("DELIST_TOTAL_SCHEMA")


def pairs_from_body(raw: bytes, scope: str) -> tuple[list[tuple], dict]:
    if scope not in SCOPES or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("DELIST_BODY_SCOPE")
    if scope == "sse_delisted":
        data = strict_json_loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise ValueError("DELIST_SSE_RESULT")
        rows = data["result"]
        if not 0 < len(rows) <= 500 or not all(isinstance(r, dict) for r in rows):
            raise ValueError("DELIST_SSE_ROWS")
        page = data.get("pageHelp")
        total = integer(page["total"]) if isinstance(page, dict) and "total" in page else None
        if total is not None and total != len(rows):
            raise ValueError("DELIST_SSE_TRUNCATED")
        # COMPANY_CODE is a company-directory key, not unconditionally A_STOCK_CODE.
        return [(r["COMPANY_CODE"], r["LIST_DATE"], r["DELIST_DATE"], r.get("A_STOCK_CODE"))
                for r in rows], {"declared_total": total, "returned_rows": len(rows),
                                 "date_field": "DELIST_DATE",
                                 "identity_field": "COMPANY_CODE_AND_A_STOCK_CODE_IF_PRESENT"}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = z.infolist()
        if (len(members) > 100 or sum(m.file_size for m in members) > 32 * 1024 * 1024
                or any(m.filename.startswith("/") or ".." in m.filename.split("/") for m in members)):
            raise ValueError("DELIST_XLSX_ARCHIVE_LIMIT")
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    try:
        if len(book.worksheets) != 1:
            raise ValueError("DELIST_XLSX_SHEET")
        sheet = book.worksheets[0]
        if sheet.max_row is None or not 2 <= sheet.max_row <= 10001 or sheet.max_column is None or sheet.max_column > 64:
            raise ValueError("DELIST_XLSX_SIZE")
        rows = iter(sheet.values)
        header = next(rows)
        names = ("证券代码", "上市日期", "终止上市日期")
        if any(header.count(name) != 1 for name in names):
            raise ValueError("DELIST_XLSX_HEADER")
        indices = [header.index(name) for name in names]
        pairs = [tuple(row[i] for i in indices) + (None,) for row in rows if any(v is not None for v in row)]
    finally:
        book.close()
    if not pairs:
        raise ValueError("DELIST_XLSX_EMPTY")
    return pairs, {"declared_total": None, "returned_rows": len(pairs), "date_field": "终止上市日期",
                   "identity_field": "证券代码"}


def summarize(raw: bytes, scope: str, observed_day: date) -> dict:
    pairs, meta = pairs_from_body(raw, scope)
    exchange = "sh" if scope == "sse_delisted" else "sz"
    seen = set()
    valid = {}
    excluded = Counter()
    years = Counter()
    anchors = {}
    for value, listed, removed, a_code in pairs:
        try:
            code = code_value(value, numeric=scope == "szse_delisted")
        except ValueError:
            excluded["invalid_code"] += 1
            continue
        if code in seen:
            raise ValueError("DELIST_DUPLICATE_DIRECTORY_KEY")
        seen.add(code)
        if stock_code(exchange + "." + code, require_exchange=True) is None:
            excluded["non_a_prefix_or_unknown"] += 1
            continue
        if scope == "sse_delisted" and a_code not in (None, "", "-") and a_code != code:
            excluded["company_a_identity_conflict"] += 1
            continue
        try:
            first, last = _listing_day(listed), _listing_day(removed)
            if not first <= last <= observed_day:
                raise ValueError("DELIST_DATE_ORDER")
        except (ValueError, TypeError, OverflowError):
            excluded["missing_or_invalid_interval"] += 1
            if code in ANCHORS[scope]:
                anchors[code] = {"status": "INVALID_INTERVAL"}
            continue
        valid[code] = (first, last)
        years[str(last.year)] += 1
    for code, expected in ANCHORS[scope].items():
        if code in valid:
            actual = valid[code][1].isoformat()
            anchors[code] = {"directory_end_date": actual, "announced_removal": expected,
                             "status": "MATCH" if actual == expected else "DIFFERENT_DATE_SEMANTICS"}
        elif code not in anchors:
            anchors[code] = {"status": "ABSENT_OR_EXCLUDED", "announced_removal": expected}
    if not valid:
        raise ValueError("DELIST_NO_VALID_INTERVALS")
    return meta | {"valid_a_prefix_intervals": len(valid), "excluded": dict(excluded),
                   "observed_directory_end_year_counts": dict(sorted(years.items())),
                   "retrospective_interval_membership_counts": {
                       cut: sum(first <= date.fromisoformat(cut) < last for first, last in valid.values())
                       for cut in CUTS},
                   "anchors": anchors, "complete_historical_universe_verified": False,
                   "interval_semantics_independently_verified_for_every_row": False,
                   "historical_first_availability_verified": False,
                   "tradability_verified": False, "pit_safe": False}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def child(scope: str, path: Path) -> None:
    url, referer = endpoint(scope)
    started = datetime.now(UTC)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer,
                                                   "Accept-Encoding": "identity"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            if (response.status != 200 or response.geturl() != url
                    or response.headers.get("Content-Range") is not None
                    or response.headers.get("Content-Encoding", "identity").lower() not in ("identity", "")):
                raise ValueError("DELIST_HTTP_SCOPE")
            raw = response.read(MAX_BYTES + 1)
            length = response.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or length is not None and int(length) != len(raw):
                raise ValueError("DELIST_BODY_LENGTH")
    except (OSError, ValueError) as exc:
        write_worker_result(path, {"scope": scope, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None})
        return
    write_worker_result(path, {"scope": scope, "url": url, "started": started.isoformat(),
                               "observed": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe(scope: str) -> dict:
    url, _ = endpoint(scope)
    out = {"scope": scope, "url": url, "status": "BLOCK", "raw_body_retained": False}
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.delisting_directory",
                              "--child", scope), timeout_seconds=30, max_bytes=6 * 1024 * 1024)
    out |= {"worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        if p["scope"] != scope:
            raise ValueError("DELIST_RECEIPT_SCOPE")
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        a, b = datetime.fromisoformat(p["started"]), datetime.fromisoformat(p["observed"])
        raw = base64.b64decode(p["body"], validate=True)
        if (p["url"] != url or a.utcoffset() is None or b.utcoffset() is None
                or not a <= b <= datetime.now(UTC) or hashlib.sha256(raw).hexdigest() != p["sha256"]
                or not 0 < len(raw) <= MAX_BYTES):
            raise ValueError("DELIST_RECEIPT_SCOPE")
        out |= {"observed_at": b.isoformat(), "sha256": p["sha256"], "bytes": len(raw),
                "parent_rehash": "MATCH"}
        from zoneinfo import ZoneInfo

        out["summary"] = summarize(raw, scope, b.astimezone(ZoneInfo("Asia/Shanghai")).date())
        return out | {"status": "WARN"}
    except Exception as exc:
        return out | {"error": str(exc) if re.fullmatch(r"DELIST_[A-Z_]+", str(exc)) else type(exc).__name__}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    results = [observe(s) for s in SCOPES]
    report = {"executor_commit": os.environ["GITHUB_SHA"], "status": "WARN" if all(
        r["status"] == "WARN" for r in results) else "BLOCK", "observations": results,
        "historical_universe_admitted": False, "decision_authority": False, "execution_allowed": False,
        "pit_safe": False}
    print("PUBLIC_DELIST_DIRECTORY " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in SCOPES:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
