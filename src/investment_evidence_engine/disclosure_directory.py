"""Observed CNINFO disclosure-search directory, not an exchange listing.

Fixed HTTPS source, bounded body and process, no persistence or redistribution
of raw records. Prefix coverage only; no active-listing or quote-date claim.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result
from .exchange_listing import _NoRedirect
from .listing_comparison import normalize_codes, stock_code
from .snapshot_integrity import strict_json_loads

URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
MAX_BODY = 4 * 1024 * 1024


def parse_directory(raw: bytes) -> tuple[list[str], dict]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY:
        raise ValueError("DIRECTORY_BODY_SIZE")
    body = strict_json_loads(raw)
    rows = body.get("stockList") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not 0 < len(rows) <= 12000:
        raise ValueError("DIRECTORY_SCHEMA")
    codes = []
    seen = set()
    categories = Counter()
    outside = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("DIRECTORY_ROW_SCHEMA")
        raw_code, category, org = row.get("code"), row.get("category"), row.get("orgId")
        if not isinstance(raw_code, str):
            raise ValueError("DIRECTORY_CODE_SCHEMA")
        code = stock_code(raw_code, require_exchange=False)
        if code is None:
            outside += 1
            continue
        if (not isinstance(org, str) or not org.strip()
                or not isinstance(category, str) or not category.strip()):
            raise ValueError("DIRECTORY_IN_SCOPE_IDENTITY_MISSING")
        if code in seen:
            raise ValueError("DIRECTORY_IN_SCOPE_DUPLICATE")
        seen.add(code)
        codes.append(code)
        categories[category] += 1
    _, stats = normalize_codes(codes, require_exchange=True)
    if min(stats["sh_count"], stats["sz_count"]) < 1000:
        raise ValueError("DIRECTORY_PREFIX_COVERAGE_TOO_SMALL")
    return codes, {"raw_count": len(rows), "out_of_scope": outside, "code_stats": stats,
                   "distinct_in_scope_categories": len(categories),
                   "scope": "CNINFO_DISCLOSURE_SEARCH_SH_SZ_PREFIX_OBSERVATION",
                   "active_listing_verified": False, "listing_date_verified": False,
                   "listing_completeness_verified": False, "source_independence_verified": False,
                   "quote_trade_date_verified": False, "pit_safe": False, "decision_authority": False}


def _child(out: Path) -> None:
    started = datetime.now(UTC)
    request = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/search"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=15) as response:
            if response.status != 200 or response.geturl() != URL:
                raise ValueError("DIRECTORY_HTTP_IDENTITY")
            raw = response.read(MAX_BODY + 1)
        if not 0 < len(raw) <= MAX_BODY:
            raise ValueError("DIRECTORY_BODY_SIZE")
    except urllib.error.HTTPError as exc:
        write_worker_result(out, {"error_type": "HTTPError", "http_status": exc.code})
        return
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        write_worker_result(out, {"error_type": type(exc).__name__})
        return
    write_worker_result(out, {"url": URL, "started_at": started.isoformat(),
                              "observed_at": datetime.now(UTC).isoformat(),
                              "body_sha256": hashlib.sha256(raw).hexdigest(),
                              "body_base64": base64.b64encode(raw).decode("ascii")})


def observe_directory() -> tuple[list[str] | None, dict]:
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.disclosure_directory",
                            "--child"), timeout_seconds=25, max_bytes=6 * 1024 * 1024)
    info = {"url": URL, "status": "BLOCK", "worker_status": task.status,
            "elapsed_seconds": task.elapsed_seconds, "active_listing_verified": False,
            "raw_provider_bytes_retained": False}
    if task.status != "OK" or task.payload is None:
        return None, info
    p = task.payload
    if p.get("error_type"):
        return None, info | {"error_type": p["error_type"], "http_status": p.get("http_status")}
    try:
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        if p["url"] != URL or start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("DIRECTORY_RECEIPT_IDENTITY")
        raw = base64.b64decode(p["body_base64"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["body_sha256"]:
            raise ValueError("DIRECTORY_RECEIPT_DIGEST")
        info |= {"started_at": start.isoformat(), "observed_at": end.isoformat(),
                 "body_sha256": digest, "body_bytes": len(raw), "body_parent_rehash": "MATCH"}
        codes, metadata = parse_directory(raw)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        # No record values or response contents in the receipt.
        return None, info | {"worker_status": "PAYLOAD_INVALID",
                             "error_code": str(exc) if str(exc).startswith("DIRECTORY_") else type(exc).__name__}
    return codes, info | metadata | {"status": "OBSERVED"}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(Path(sys.argv[2]))
