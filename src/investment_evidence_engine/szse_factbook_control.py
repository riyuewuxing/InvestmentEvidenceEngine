"""Fixed historical SZSE fact-book observation, not a contemporaneous universe.

Copyrighted yearbook is transient only. No complete table, text or raw PDF
is published. Record counts, fingerprints, and a few code-only anchors.
A later-published yearbook cannot be backdated to the statistical year end.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_revision_control import normalize_text
from .official_pdf_transport import read_bounded_pdf

REPO = "riyuewuxing/InvestmentEvidenceEngine"
URL = "https://docs.static.szse.cn/www/market/periodical/year/W020250912366937867370.pdf"
# The web document resolver reported this exact content length before execution.
# This narrowly bounded fixed-source exception does not change the generic
# official PDF limit or allow caller-supplied URLs.
MAX_BYTES = 18 * 1024 * 1024
EXPECTED_LENGTH = 17220384
TABLES = {"main": (120, 30, 1521, ("000", "001", "002", "003", "200")),
          "chinext": (214, 27, 1365, ("300", "301"))}
MONEY = r"(?:[0-9]{1,3}(?:[ ,]+[0-9]{3})+|[0-9]+)\.[0-9]{2}"
PCT = r"[0-9]{1,3}\.[0-9]{4}"
ROW = re.compile(
    r"^\s*(?P<rank>[0-9]{1,4})\s+(?P<left>[0-9]{6})\s+.{1,40}?\s+(?P<value>"
    + MONEY + r")\s+" + PCT + r"\s+" + PCT
    + r"\s+(?P<right>[0-9]{6})\s+.{1,40}?\s+(?P<negotiable>"
    + MONEY + r")\s+" + PCT + r"\s+" + PCT + r"\s*$"
)


def parse_rows(text: str) -> tuple[list[tuple], int]:
    rows = []
    malformed = 0
    for line in text.splitlines():
        if not re.match(r"^\s*[0-9]{1,4}\s+[0-9]{6}(?:\s|$)", line):
            continue
        match = ROW.fullmatch(line)
        if match is None:
            malformed += 1
            continue
        d = match.groupdict()
        value, negotiable = (Decimal(re.sub(r"[ ,]", "", d[k])) for k in ("value", "negotiable"))
        rows.append((int(d["rank"]), d["left"], d["right"], str(value), str(negotiable)))
    return rows, malformed


def summarize_rows(rows: list[tuple], board: str, malformed: int) -> dict:
    _, _, reference_count, prefixes = TABLES[board]
    left, right = [{r[i] for r in rows} for i in (1, 2)]
    rank_ok = [r[0] for r in rows] == list(range(1, len(rows)+1))
    unique = len(left) == len(right) == len(rows)
    allowed = all(code.startswith(prefixes) for code in left | right)
    same = left == right
    counts = {prefix: sum(code.startswith(prefix) for code in left) for prefix in prefixes}
    # Market value order, not security-level liquidity or trading eligibility.
    order = all(Decimal(a[3]) >= Decimal(b[3]) and Decimal(a[4]) >= Decimal(b[4])
                for a, b in zip(rows[:-1], rows[1:], strict=True))
    # A ranking is not automatically a listing roster. Do not coerce an
    # over/under-count, duplicate, or mismatch into a complete universe.
    valid = bool(rows and not malformed and rank_ok and unique and allowed and same and order)
    return {"status": "RANKING_RECONCILED_ONLY" if valid else "BLOCK",
            "rows": len(rows), "malformed_candidate_rows": malformed, "rank_sequence_match": rank_ok,
            "unique_codes_both_columns": unique, "prefix_scope_match": allowed, "same_code_sets": same,
            "descending_value_order": order, "left_prefix_counts": counts,
            "left_only_count": len(left-right), "right_only_count": len(right-left),
            "reported_year_end_listed_count_reference": reference_count,
            "count_difference": len(left)-reference_count,
            "year_end_listing_count_match": len(left)==reference_count,
            "ranked_code_projection_sha256": hashlib.sha256(
                json.dumps([[r[0], r[1], r[2]] for r in rows], separators=(",", ":")).encode()).hexdigest(),
            "sorted_left_code_set_sha256": hashlib.sha256(
                json.dumps(sorted(left), separators=(",", ":")).encode()).hexdigest(),
            "first_last_left_codes": [rows[0][1], rows[-1][1]] if rows else [],
            "anchor_codes_present": {c: c in left for c in ("000035", "000858", "200028", "300750")},
            "sum_market_value_million_cny": str(sum((Decimal(r[3]) for r in rows), Decimal(0))),
            "historical_universe_complete": False, "tradability_verified": False}


def download(target: Path, receipt: Path) -> None:
    import httpx

    started = datetime.now(UTC)
    with httpx.Client(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        with client.stream("GET", URL, headers={"Accept": "application/pdf", "Accept-Encoding": "identity"}) as response:
            if str(response.url) != URL:
                raise ValueError("YEARBOOK_SOURCE_SCOPE")
            body = read_bounded_pdf(response, time.monotonic()+35, max_bytes=MAX_BYTES)
    if len(body) != EXPECTED_LENGTH:
        # Preserve version change as an observation; do not parse a different
        # edition under the fixed source assumption.
        write_worker_result(receipt, {"status": "BLOCK", "reason": "YEARBOOK_LENGTH_CHANGED",
            "source_bytes": len(body), "source_sha256": hashlib.sha256(body).hexdigest()})
        return
    with target.open("xb") as handle:
        handle.write(body)
    write_worker_result(receipt, {"status": "OBSERVED", "url": URL, "source_bytes": len(body),
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "started_at": started.isoformat(), "observed_at": datetime.now(UTC).isoformat()})


def parse(target: Path, receipt: Path) -> None:
    from pypdf import PdfReader

    raw = target.read_bytes()
    reader = PdfReader(target, strict=True)
    report = {"status": "BLOCK", "source_sha256": hashlib.sha256(raw).hexdigest(),
              "page_count": len(reader.pages)}
    if reader.is_encrypted or not 240 <= len(reader.pages) <= 1900:
        write_worker_result(receipt, report | {"reason": "YEARBOOK_PAGE_SCOPE"})
        return
    opening = [normalize_text(reader.pages[i].extract_text() or "") for i in range(12)]
    joined = "".join(opening)
    report["edition_identity"] = ("深圳证券交易所市场统计年鉴" in joined
                                 and "2024" in joined and "2025年10月" in joined)
    report["statistical_period_identity"] = ("2024年1月1日至2024年12月31日" in joined)
    report["publisher_year_later"] = "2025年10月" in joined
    # Search near the TOC page rather than assuming PDF index equals page label.
    tables = {}
    for name, (printed, pages, _, _) in TABLES.items():
        candidates = []
        for i in range(printed-1, min(printed+22, len(reader.pages))):
            txt = normalize_text(reader.pages[i].extract_text() or "")
            if ("各股市价总值排名表" in txt or "RANKBYSTOCKMARKETVALUE" in txt):
                candidates.append(i)
        item = {"start_candidates_zero_based": candidates}
        if len(candidates) != 1:
            tables[name] = item | {"status": "BLOCK", "reason": "YEARBOOK_TABLE_START_AMBIGUOUS"}
            continue
        start = candidates[0]
        rows = []
        malformed = 0
        page_counts = []
        page_hashes = []
        for i in range(start, start+pages):
            text = reader.pages[i].extract_text(extraction_mode="layout") or ""
            parsed, bad = parse_rows(text)
            page_counts.append({"page_index": i, "rows": len(parsed), "malformed": bad})
            page_hashes.append(hashlib.sha256(text.encode()).hexdigest())
            rows.extend(parsed)
            malformed += bad
        result = summarize_rows(rows, name, malformed)
        tables[name] = item | result | {"page_counts": page_counts,
            "layout_page_text_hashes": page_hashes}
    report["tables"] = tables
    report["status"] = "WARN" if (report["edition_identity"] and report["statistical_period_identity"]
        and all(v["status"] == "RANKING_RECONCILED_ONLY" for v in tables.values())) else "BLOCK"
    write_worker_result(receipt, report)


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "url": URL, "statistical_as_of": "2024-12-31", "publication_year": 2025,
              "available_at_year_end_verified": False, "historical_vintage_verified": False,
              "complete_historical_universe_verified": False, "raw_pdf_retained": False,
              "decision_authority": False, "execution_allowed": False, "pit_safe": False}
    with TemporaryDirectory() as folder:
        target = Path(folder)/"factbook.pdf"
        task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.szse_factbook_control",
                                "--download", str(target)), timeout_seconds=55, max_bytes=65536)
        report["download_worker"] = {"status": task.status, "elapsed_seconds": task.elapsed_seconds}
        if task.status == "OK" and task.payload is not None:
            report["download"] = task.payload
            if task.payload.get("status") == "OBSERVED" and target.is_file():
                raw = target.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if len(raw)==EXPECTED_LENGTH and digest==task.payload.get("source_sha256"):
                    report["parent_rehash"] = "MATCH"
                    parsed = run_json_worker((sys.executable, "-m", "investment_evidence_engine.szse_factbook_control",
                        "--parse", str(target)), timeout_seconds=85, max_bytes=128*1024)
                    report["parser_worker"] = {"status": parsed.status, "elapsed_seconds": parsed.elapsed_seconds}
                    if parsed.status=="OK" and parsed.payload is not None:
                        report["parser"] = parsed.payload
                        if parsed.payload.get("source_sha256")==digest:
                            report["parser_input_rehash"]="MATCH"
                            report["status"]=parsed.payload["status"]
    print("PUBLIC_SZSE_FACTBOOK " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"]=="WARN" else 2


if __name__ == "__main__":
    if len(sys.argv)==4 and sys.argv[1]=="--download":
        download(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv)==4 and sys.argv[1]=="--parse":
        parse(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv)==1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
