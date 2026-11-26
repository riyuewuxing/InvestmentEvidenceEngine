"""Fixed ALFRED daily vintage crosscheck against already retained BLS releases.

Source: BLS via ALFRED, Federal Reserve Bank of St. Louis.
A provider's vintage date is not a system capture time or intraday release clock.
No API credentials, no current-vintage fallback, no raw vendor archive.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect

SERIES = "PAYEMS"
JULY = date(2025, 7, 1)
AUGUST = date(2025, 8, 1)
VINTAGES = (date(2025, 9, 4), date(2025, 9, 5), date(2025, 11, 20), date(2025, 12, 16))
MAX_BYTES = 256 * 1024


def vintage_url(vintage: date) -> str:
    if vintage not in VINTAGES:
        raise ValueError("ALFRED_UNREGISTERED_VINTAGE")
    return "https://alfred.stlouisfed.org/graph/alfredgraph.csv?" + urlencode({
        "id": SERIES, "vintage_date": vintage.isoformat(),
        "cosd": JULY.isoformat(), "coed": AUGUST.isoformat(),
    })


def parse_vintage(raw: bytes, vintage: date) -> dict:
    """Strict series/vintage header, ordered monthly rows and no future observations."""
    vintage_url(vintage)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("ALFRED_BODY_SIZE")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="strict")), strict=True)
    header = next(reader, [])
    expected = SERIES + "_" + vintage.strftime("%Y%m%d")
    if len(header) != 2 or header[0] not in {"observation_date", "DATE"} or header[1] != expected:
        raise ValueError("ALFRED_VINTAGE_HEADER")
    selected = {}
    previous = None
    count = 0
    for row in reader:
        count += 1
        if count > 1500 or len(row) != 2:
            raise ValueError("ALFRED_ROW_LIMIT_OR_SCHEMA")
        day = date.fromisoformat(row[0])
        if day.isoformat() != row[0] or day.day != 1 or (previous is not None and day <= previous):
            raise ValueError("ALFRED_MONTHLY_ORDER")
        previous = day
        if row[1] in {"", "."}:
            level = None
        else:
            if not re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]{1,6})?", row[1]):
                raise ValueError("ALFRED_LEVEL_SCHEMA")
            level = Decimal(row[1])
            if not 0 < level < 1_000_000 or level != level.to_integral_value():
                raise ValueError("ALFRED_LEVEL_UNIT")
        if day > vintage and level is not None:
            raise ValueError("ALFRED_FUTURE_MEASUREMENT")
        if day in {JULY, AUGUST}:
            selected[day] = level
    if selected.get(JULY) is None:
        raise ValueError("ALFRED_JULY_BASE_MISSING")
    july, august = selected[JULY], selected.get(AUGUST)
    if vintage >= VINTAGES[1] and august is None:
        raise ValueError("ALFRED_AUGUST_MISSING_AFTER_RELEASE")
    change = None if august is None else int((august - july) * 1000)
    return {"provider_vintage_date": vintage.isoformat(), "series_id": SERIES,
            "level_unit": "THOUSANDS_OF_PERSONS", "frequency": "MONTHLY",
            "seasonal_adjustment": "SEASONALLY_ADJUSTED",
            "july_level_thousands": str(july),
            "august_level_thousands": None if august is None else str(august),
            "august_change_jobs": change, "response_rows": count,
            "date_precision": "DAY_ONLY", "historical_capture_verified": False}


def _child(vintage: date, path: Path) -> None:
    url = vintage_url(vintage)
    start = datetime.now(UTC)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("ALFRED_RESPONSE_SCOPE")
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("ALFRED_CONTENT_ENCODING")
            if response.headers.get("Content-Range") is not None:
                raise ValueError("ALFRED_PARTIAL_RESPONSE")
            raw = response.read(MAX_BYTES + 1)
            length = response.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (length is not None and int(length) != len(raw)):
                raise ValueError("ALFRED_BODY_SIZE")
    except (OSError, ValueError) as exc:
        write_worker_result(path, {"vintage": vintage.isoformat(), "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"vintage": vintage.isoformat(), "url": url,
                              "started_at": start.isoformat(), "retrieved_at": datetime.now(UTC).isoformat(),
                              "body_sha256": hashlib.sha256(raw).hexdigest(),
                              "body_base64": base64.b64encode(raw).decode("ascii")})


def observe(vintage: date) -> dict:
    out = {"requested_vintage": vintage.isoformat(), "url": vintage_url(vintage),
           "status": "BLOCK", "raw_body_retained": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.alfred_vintage_control",
                            "--child", vintage.isoformat()), timeout_seconds=20, max_bytes=512 * 1024)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if p["vintage"] != vintage.isoformat():
            raise ValueError("ALFRED_RECEIPT_VINTAGE")
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if (p["url"] != vintage_url(vintage) or start.utcoffset() is None or end.utcoffset() is None
                or not start <= end <= datetime.now(UTC)):
            raise ValueError("ALFRED_RECEIPT_SCOPE")
        raw = base64.b64decode(p["body_base64"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if not 0 < len(raw) <= MAX_BYTES or digest != p["body_sha256"]:
            raise ValueError("ALFRED_BODY_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "retrieved_at": end.isoformat(),
                "parent_rehash": "MATCH"}
        fields = parse_vintage(raw, vintage)
        return out | {"status": "OBSERVED", "fields": fields}
    except (KeyError, ValueError, TypeError, csv.Error) as exc:
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"ALFRED_[A-Z_]+", code) else type(exc).__name__}


def compare_vintages(receipts: list[dict], original_changes: tuple[int, ...]) -> dict:
    if len(receipts) != 4 or len(original_changes) != 3:
        raise ValueError("ALFRED_COMPARISON_SCOPE")
    if [r.get("requested_vintage") for r in receipts] != [d.isoformat() for d in VINTAGES]:
        raise ValueError("ALFRED_COMPARISON_SCOPE")
    if any(r.get("status") != "OBSERVED" for r in receipts):
        return {"status": "BLOCK", "comparison": "INCOMPLETE"}
    changes = []
    for receipt in receipts:
        fields = receipt["fields"]
        if (fields.get("provider_vintage_date") != receipt["requested_vintage"]
                or fields.get("series_id") != SERIES):
            raise ValueError("ALFRED_COMPARISON_IDENTITY")
        change = fields["august_change_jobs"]
        if change is not None and type(change) is not int:
            raise ValueError("ALFRED_COMPARISON_VALUE")
        changes.append(change)
    matches = [actual == expected for actual, expected in zip(changes, (None, *original_changes), strict=True)]
    return {"status": "WARN" if all(matches) else "BLOCK",
            "comparison": "MATCH" if all(matches) else "CONFLICT",
            "august_changes_jobs": changes, "original_changes_jobs": [None, *original_changes],
            "per_vintage_match": matches, "source_date_vintage_consistency": all(matches),
            "source_independence_verified": False, "intraday_availability_verified": False,
            "historical_system_capture_verified": False, "complete_vintage_universe_verified": False,
            "pit_safe": False, "decision_authority": False, "execution_allowed": False}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(date.fromisoformat(sys.argv[2]), Path(sys.argv[3]))
