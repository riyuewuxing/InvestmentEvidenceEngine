"""Bounded direct official SSE/SZSE listing observations, no historical claim."""
from __future__ import annotations

import base64
import hashlib
import io
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .listing_comparison import normalize_codes, stock_code
from .snapshot_integrity import strict_json_loads

MAX_BODY = 4 * 1024 * 1024
SCOPES = ("sse_main", "sse_star", "szse_a")


def endpoint(scope: str) -> tuple[str, str]:
    if scope in {"sse_main", "sse_star"}:
        params = {"STOCK_TYPE": "1" if scope == "sse_main" else "8",
                  "REG_PROVINCE": "", "CSRC_CODE": "", "STOCK_CODE": "",
                  "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
                  "COMPANY_STATUS": "2,4,5,7,8", "type": "inParams", "isPagination": "true",
                  "pageHelp.cacheSize": "1", "pageHelp.beginPage": "1",
                  "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1", "pageHelp.endPage": "1"}
        return ("https://query.sse.com.cn/sseQuery/commonQuery.do?" + urllib.parse.urlencode(params),
                "https://www.sse.com.cn/assortment/stock/list/share/")
    if scope == "szse_a":
        return ("https://www.szse.cn/api/report/ShowReport?"
                + urllib.parse.urlencode({"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1",
                                          "random": "0.6935816432433362"}),
                "https://www.szse.cn/market/product/stock/list/")
    raise ValueError("UNKNOWN_EXCHANGE_LISTING_SCOPE")


def _listing_day(value: object) -> date:
    if isinstance(value, datetime):
        if value.utcoffset() is not None or value.time() != datetime.min.time():
            raise ValueError("LISTING_DATE_PRECISION_INVALID")
        return value.date()
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("LISTING_DATE_INVALID")


def _code(value: object, scope: str) -> str:
    if type(value) is int and 0 <= value <= 999999 and scope == "szse_a":
        # A named A股代码 spreadsheet cell can be numeric. Restore the
        # six-character identifier, not an inferred market from the number.
        value = f"{value:06d}"
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{6}", value) is None:
        raise ValueError("OFFICIAL_LISTING_CODE_INVALID")
    exchange = "sz" if scope == "szse_a" else "sh"
    code = stock_code(exchange + "." + value, require_exchange=True)
    if code is None or (scope == "sse_star" and not value.startswith(("688", "689"))) or (
            scope == "sse_main" and value.startswith(("688", "689"))):
        raise ValueError("OFFICIAL_LISTING_BOARD_MISMATCH")
    return code


def parse_listing(raw: bytes, scope: str, day: date) -> tuple[list[str], dict]:
    if scope not in SCOPES or type(day) is not date or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY:
        raise ValueError("OFFICIAL_LISTING_INPUT_INVALID")
    declared_total = None
    if scope.startswith("sse_"):
        data = strict_json_loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise ValueError("SSE_RESULT_INVALID")
        records = data["result"]
        if not records or len(records) > 10000 or not all(isinstance(r, dict) for r in records):
            raise ValueError("SSE_RESULT_SIZE_INVALID")
        page = data.get("pageHelp")
        if isinstance(page, dict) and "total" in page:
            total = page["total"]
            if type(total) is int or (isinstance(total, str) and re.fullmatch(r"[0-9]+", total)):
                declared_total = int(total)
            else:
                raise ValueError("SSE_DECLARED_TOTAL_INVALID")
            if declared_total != len(records):
                raise ValueError("SSE_DECLARED_TOTAL_MISMATCH")
        pairs = [(r["A_STOCK_CODE"], r["LIST_DATE"]) for r in records]
    else:
        # Verify bounded uncompressed archive before parsing untrusted XLSX.
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (len(members) > 100 or sum(x.file_size for x in members) > 32 * 1024 * 1024
                    or any(x.filename.startswith("/") or ".." in x.filename.split("/") for x in members)):
                raise ValueError("SZSE_ARCHIVE_LIMIT")
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        try:
            if len(book.worksheets) != 1:
                raise ValueError("SZSE_WORKSHEET_COUNT_INVALID")
            sheet = book.worksheets[0]
            if sheet.max_row is None or sheet.max_row > 10001 or sheet.max_column is None or sheet.max_column > 64:
                raise ValueError("SZSE_WORKSHEET_SIZE_INVALID")
            rows = iter(sheet.values)
            headers = next(rows)
            if headers.count("A股代码") != 1 or headers.count("A股上市日期") != 1:
                raise ValueError("SZSE_HEADER_INVALID")
            code_idx, day_idx = headers.index("A股代码"), headers.index("A股上市日期")
            pairs = [(row[code_idx], row[day_idx]) for row in rows if any(v is not None for v in row)]
        finally:
            book.close()
    if not pairs:
        raise ValueError("OFFICIAL_LISTING_EMPTY")
    codes = []
    seen = set()
    future = 0
    for value, listed in pairs:
        code = _code(value, scope)
        if code in seen:
            raise ValueError("OFFICIAL_LISTING_DUPLICATE")
        seen.add(code)
        if _listing_day(listed) > day:
            future += 1
        else:
            codes.append(code)
    _, stats = normalize_codes(codes, require_exchange=True)
    minimum = {"sse_main": 1000, "sse_star": 200, "szse_a": 1000}[scope]
    if stats["unique_in_scope"] < minimum or stats["invalid_count"] or stats["duplicate_count"]:
        raise ValueError("OFFICIAL_LISTING_COVERAGE_TOO_SMALL")
    return codes, {"declared_total": declared_total, "returned_rows": len(pairs),
                   "future_listing_dates_excluded": future, "code_stats": stats,
                   "declared_total_match": declared_total is not None,
                   "complete_listing_verified": False}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _child(scope: str, day: str, path: Path) -> None:
    url, referer = endpoint(scope)
    started = datetime.now(UTC)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer,
                                                   "Accept-Encoding": "identity"})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=12) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("OFFICIAL_LISTING_HTTP_IDENTITY")
        raw = response.read(MAX_BODY + 1)
    if not 0 < len(raw) <= MAX_BODY:
        raise ValueError("OFFICIAL_LISTING_BODY_SIZE")
    write_worker_result(path, {"scope": scope, "day": day, "url": url,
                               "started_at": started.isoformat(), "observed_at": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe_listing(scope: str, day: date) -> tuple[list[str] | None, dict]:
    url, _ = endpoint(scope)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.exchange_listing",
                            "--child", scope, day.isoformat()), timeout_seconds=25,
                           max_bytes=6 * 1024 * 1024)
    info = {"scope": scope, "url": url, "status": "BLOCK",
            "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return None, info
    p = task.payload
    try:
        if (p["scope"], p["day"], p["url"]) != (scope, day.isoformat(), url):
            raise ValueError("OFFICIAL_LISTING_RECEIPT_SCOPE")
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("OFFICIAL_LISTING_RECEIPT_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("OFFICIAL_LISTING_BODY_HASH")
        codes, meta = parse_listing(raw, scope, day)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, StopIteration, zipfile.BadZipFile) as exc:
        code = str(exc)
        return None, info | {"worker_status": "PAYLOAD_INVALID",
                             "error_code": code if re.fullmatch(r"[A-Z0-9_]{3,80}", code) else type(exc).__name__}
    return codes, info | {"status": "OBSERVED", "started_at": start.isoformat(), "observed_at": end.isoformat(),
                          "raw_body_sha256": digest, "raw_body_bytes": len(raw),
                          "raw_body_parent_rehash": "MATCH", **meta}


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], sys.argv[3], Path(sys.argv[4]))
