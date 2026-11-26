"""Fixed Philadelphia Fed release-table control; no historical capture assertion."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from replay_bls_archive import retained_revisions

from investment_evidence_engine.bounded_worker import run_json_worker, write_worker_result
from investment_evidence_engine.issuer_disclosure_index import NoRedirect

URL = ("https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/"
       "data-files/xlsx/employ_level_first_second_third.xlsx?hash=038598EEF20022DF3CAE6801113BDF87&sc_lang=en")
SOURCE = "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/employ"
MAX_BYTES = 1024 * 1024


def row_fields(rows) -> dict:
    """Only accept documented release headers, explicit series/unit, and one August row."""
    headers = ("date", "first", "second", "third", "most_recent")
    metadata = []
    matches = []
    header = False
    for i, cells in enumerate(rows):
        if i > 2000 or len(cells) != 5:
            raise ValueError("PHILLY_ROW_LIMIT")
        if not header:
            if tuple(str(c).strip().lower() for c in cells) == headers:
                header = True
            else:
                metadata.extend(str(c) for c in cells if c is not None)
                if i >= 12:
                    raise ValueError("PHILLY_HEADER")
            continue
        if isinstance(cells[0], str) and re.fullmatch(r"2025:M0?8", cells[0].strip()):
            matches.append(cells)
    caption = " ".join(metadata).lower()
    if not header or "employ" not in caption or "thousand" not in caption or "change" not in caption:
        raise ValueError("PHILLY_SERIES_UNIT")
    if len(matches) != 1:
        raise ValueError("PHILLY_TARGET_SCOPE")
    values = []
    for value in matches[0][1:4]:
        if value is None or value == ".":
            values.append(None)
        elif type(value) in (int, float) and -100000 <= value <= 100000 and int(value) == value:
            values.append(int(value) * 1000)
        else:
            raise ValueError("PHILLY_VALUE_SCHEMA")
    return {"period": "2025-08", "series": "EMPLOY", "unit": "JOBS",
            "release_values": values, "latest_revision_not_used": True}


def parse(raw: bytes) -> dict:
    import openpyxl

    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("PHILLY_BODY_SIZE")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = z.infolist()
        if len(files) > 100 or sum(x.file_size for x in files) > 8 * MAX_BYTES:
            raise ValueError("PHILLY_XLSX_BOUNDS")
        if any(x.filename.startswith("xl/externalLinks/") or x.filename.endswith("vbaProject.bin") for x in files):
            raise ValueError("PHILLY_XLSX_EXTERNAL")
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    try:
        if len(wb.worksheets) != 1:
            raise ValueError("PHILLY_SHEET_SCOPE")
        sheet = wb.worksheets[0]
        if sheet.max_row is None or sheet.max_row > 2000 or sheet.max_column != 5:
            raise ValueError("PHILLY_SHEET_BOUNDS")
        return row_fields(sheet.iter_rows(min_col=1, max_col=5, values_only=True)) | {
            "openpyxl_version": openpyxl.__version__, "source_rows_observed": sheet.max_row}
    finally:
        wb.close()


def child(path: Path) -> None:
    start = datetime.now(UTC)
    try:
        req = Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
        with build_opener(NoRedirect()).open(req, timeout=12) as res:
            if (res.status != 200 or res.geturl() != URL or res.headers.get("Content-Range")
                    or res.headers.get("Content-Encoding", "identity").lower() not in ("", "identity")):
                raise ValueError("PHILLY_RESPONSE_SCOPE")
            raw = res.read(MAX_BYTES + 1)
            length = res.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (length is not None and int(length) != len(raw)):
                raise ValueError("PHILLY_BODY_SIZE")
    except (OSError, ValueError) as exc:
        write_worker_result(path, {"error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"url": URL, "started_at": start.isoformat(),
                              "retrieved_at": datetime.now(UTC).isoformat(),
                              "sha256": hashlib.sha256(raw).hexdigest(),
                              "body": base64.b64encode(raw).decode("ascii")})


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    originals = retained_revisions()
    expected = [int(r.value) for r in originals]
    task = run_json_worker((sys.executable, str(Path(__file__).resolve()), "--child"),
                           timeout_seconds=25, max_bytes=2 * MAX_BYTES)
    result = {"status": "BLOCK", "source": SOURCE, "url": URL,
              "executor_commit": os.environ["GITHUB_SHA"], "worker_status": task.status,
              "elapsed_seconds": task.elapsed_seconds, "original_values_jobs": expected,
              "original_source_sha256": [r.raw_sha256 for r in originals],
              "raw_body_retained": False, "historical_capture_verified": False,
              "source_independence_verified": False, "intraday_availability_verified": False,
              "pit_safe": False, "decision_authority": False, "execution_allowed": False}
    if task.status == "OK" and task.payload is not None:
        p = task.payload
        try:
            if "error" in p:
                result |= {"error": p["error"], "http_status": p.get("http_status")}
            else:
                a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
                raw = base64.b64decode(p["body"], validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                if (p["url"] != URL or not a.utcoffset() == b.utcoffset()
                        or a.utcoffset() is None or not a <= b <= datetime.now(UTC)
                        or digest != p["sha256"] or not 0 < len(raw) <= MAX_BYTES):
                    raise ValueError("PHILLY_RECEIPT")
                result |= {"sha256": digest, "bytes": len(raw), "parent_rehash": "MATCH",
                           "retrieved_at": b.isoformat()}
                fields = parse(raw)
                values = fields["release_values"]
                matches = [None if x is None else x == y for x, y in zip(values, expected, strict=True)]
                result |= {"fields": fields, "matches": matches,
                           "comparison": "MATCH" if all(x is True for x in matches) else (
                               "CONFLICT" if any(x is False for x in matches) else "INCOMPLETE")}
                # Missing values are never substituted by later revisions.
                if result["comparison"] == "MATCH":
                    result["status"] = "WARN"
        except Exception as exc:
            result["error"] = str(exc) if re.fullmatch(r"PHILLY_[A-Z_]+", str(exc)) else type(exc).__name__
    print("PHILLY_EMPLOY_CONTROL " + json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
