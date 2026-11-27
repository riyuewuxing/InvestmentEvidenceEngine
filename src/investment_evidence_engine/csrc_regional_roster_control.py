"""Fixed-source CSRC regional roster; no historical availability admission."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from .bounded_worker import run_json_worker, write_worker_result

REPO = "riyuewuxing/InvestmentEvidenceEngine"
URL = "https://www.csrc.gov.cn/chongqing/c104815/c7531127/content.shtml"
MODULE = "investment_evidence_engine.csrc_regional_roster_control"
MAX_BYTES = 4 * 1024 * 1024
EXPECTED = {"SZ": 37, "SH": 35, "BJ": 6}
DATE_MS = "1736096898000"
TITLE = "重庆辖区上市公司名录（截至2024年12月）"
CODE = re.compile(r"([0-9]{6})\.(SZ|SH|BJ)")


class RosterParser(HTMLParser):
    """Collect rows only; exclude name, phone, and address from receipts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
            self.cell = None
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None


def extract_roster(html: str) -> tuple[list[tuple[int, str]], int]:
    parser = RosterParser()
    parser.feed(html)
    rows = []
    rejected = 0
    for row in parser.rows:
        if not row or not re.fullmatch(r"[0-9]{1,3}", row[0]):
            continue
        if len(row) < 3:
            rejected += 1
            continue
        code = CODE.fullmatch(re.sub(r"\s+", "", row[2]))
        if not code:
            rejected += 1
            continue
        rows.append((int(row[0]), code[0]))
    return rows, rejected


def summarize(html: str) -> dict:
    rows, rejected = extract_roster(html)
    codes = [code for _, code in rows]
    counts = Counter(code.rsplit(".", 1)[1] for code in codes)
    unique = len(set(codes)) == len(codes)
    sequence = [n for n, _ in rows] == list(range(1, sum(EXPECTED.values()) + 1))
    marker = TITLE in html
    date_marker = DATE_MS in html
    exact = marker and date_marker and unique and sequence and counts == EXPECTED and not rejected
    return {"status": "WARN" if exact else "BLOCK",
            "title_marker": marker, "publication_metadata_marker": date_marker,
            "publisher_reported_publication_utc": datetime.fromtimestamp(int(DATE_MS)/1000, UTC).isoformat() if date_marker else None,
            "count_by_exchange": dict(counts), "expected_count_by_exchange": EXPECTED,
            "rows": len(rows), "rejected_numeric_rows": rejected,
            "unique_codes": unique, "sequential_rows": sequence,
            "code_set_sha256": hashlib.sha256(json.dumps(sorted(set(codes)), separators=(",", ":")).encode()).hexdigest(),
            "bse_legacy_codes": sorted(code for code in codes if code.endswith(".BJ")),
            "regional_company_roster_only": True,
            "complete_historical_universe_verified": False, "pit_safe": False}


def retrieve() -> bytes:
    import httpx

    deadline = time.monotonic() + 35
    with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as client:
        with client.stream("GET", URL, headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if str(response.url) != URL:
                raise ValueError("unexpected source")
            data = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(data) + len(chunk) > MAX_BYTES:
                    raise ValueError("bounded transport limit")
                data.extend(chunk)
            if not data:
                raise ValueError("empty document")
            return bytes(data)


def worker(result: Path) -> None:
    started = datetime.now(UTC).isoformat()
    try:
        raw = retrieve()
        observed = datetime.now(UTC).isoformat()
        data = raw.decode("utf-8", errors="strict")
        report = summarize(data)
        report.update(source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest(),
                      started_at=started, observed_at=observed)
    except Exception as exc:
        report = {"status": "BLOCK", "error_type": type(exc).__name__, "started_at": started}
    write_worker_result(result, report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    task = run_json_worker((sys.executable, "-m", MODULE, "--observe"),
                           timeout_seconds=50, max_bytes=65536)
    report = {"status": "BLOCK", "url": URL, "as_of": "2024-12-31",
              "executor_commit": os.environ["GITHUB_SHA"], "worker_status": task.status,
              "worker_elapsed_seconds": task.elapsed_seconds, "raw_html_retained": False,
              "available_at_verified": False, "decision_authority": False,
              "execution_allowed": False, "pit_safe": False}
    if task.payload:
        report["observation"] = task.payload
        report["status"] = task.payload["status"]
    print("PUBLIC_CSRC_REGIONAL_ROSTER " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--observe":
        worker(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
