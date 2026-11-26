"""Fixed public SEC filing metadata/concept control.

Acceptance is not guaranteed dissemination or historical capture. SEC's public
reuse policy covers EDGAR filing content; only the one public revenue concept
response is eligible for optional exact-byte retention, not submissions history.
"""
from __future__ import annotations

import base64
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect, decode_object
from .sources import read_official_body

CIK = "0000320193"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000320193.json"
CONCEPT = ("https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/"
           "us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json")
TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"
URLS = {"submissions": SUBMISSIONS, "concept": CONCEPT}
MAX_BYTES = 1024 * 1024
RETAIN_LIMIT = 256 * 1024
NY = ZoneInfo("America/New_York")
FILING = {
    "0000320193-25-000079": ("2025-10-31", "2025-09-27", "2025-10-31T06:01:26", "aapl-20250927.htm"),
    "0000320193-26-000026": ("2026-11-03", "2026-09-26", "2026-11-03T08:05:15", "aapl-20260926.htm"),
}
PERIOD = ("2024-09-29", "2025-09-27")
REVIEWED_REVENUE = 416_161_000_000
USER_AGENT = "InvestmentEvidenceEngine/0.1 (public research control; https://github.com/riyuewuxing/InvestmentEvidenceEngine)"


def extract_filings(raw: bytes, observed_at: datetime) -> dict:
    doc = decode_object(raw)
    if str(doc.get("cik", "")).zfill(10) != CIK or doc.get("name") != "Apple Inc.":
        raise ValueError("SEC_ENTITY_IDENTITY")
    recent = doc["filings"]["recent"]
    columns = ("accessionNumber", "form", "filingDate", "reportDate",
               "acceptanceDateTime", "primaryDocument")
    if any(not isinstance(recent.get(c), list) for c in columns):
        raise ValueError("SEC_SUBMISSIONS_SCHEMA")
    if len({len(recent[c]) for c in columns}) != 1:
        raise ValueError("SEC_SUBMISSIONS_COLUMN_LENGTH")
    found = {}
    for row in zip(*(recent[c] for c in columns), strict=True):
        accn, form, filed, report, accepted, primary = row
        if accn not in FILING:
            continue
        if accn in found or form != "10-K":
            raise ValueError("SEC_FILING_DUPLICATE_OR_FORM")
        ef, er, et, ep = FILING[accn]
        if (filed, report, primary) != (ef, er, ep):
            raise ValueError("SEC_FILING_IDENTITY")
        stamp = datetime.fromisoformat(accepted)
        if (stamp.utcoffset() is None or stamp > observed_at
                or stamp.astimezone(NY).replace(tzinfo=None).isoformat(timespec="seconds") != et):
            raise ValueError("SEC_ACCEPTANCE_CLOCK_CONFLICT")
        found[accn] = {"form": form, "filed": filed, "report_period": report,
                       "accepted_at_utc": stamp.astimezone(UTC).isoformat(),
                       "accepted_at_new_york": stamp.astimezone(NY).isoformat(),
                       "primary_document": primary,
                       "acceptance_not_publication_or_capture": True}
    if set(found) != set(FILING):
        raise ValueError("SEC_TARGET_FILINGS_MISSING")
    return found


def extract_concept(raw: bytes) -> dict:
    doc = decode_object(raw)
    if (str(doc.get("cik", "")).zfill(10) != CIK or doc.get("entityName") != "Apple Inc."
            or doc.get("taxonomy") != "us-gaap" or doc.get("tag") != TAG):
        raise ValueError("SEC_CONCEPT_IDENTITY")
    rows = doc["units"]["USD"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("SEC_CONCEPT_ROWS")
    facts = {}
    for row in rows:
        if (row.get("start"), row.get("end")) != PERIOD or row.get("accn") not in FILING:
            continue
        accn = row["accn"]
        if row.get("form") != "10-K" or row.get("filed") != FILING[accn][0]:
            raise ValueError("SEC_CONCEPT_FILING_CONFLICT")
        value = row.get("val")
        if type(value) is not int or value <= 0 or accn in facts:
            raise ValueError("SEC_CONCEPT_AMBIGUOUS")
        facts[accn] = value
    if set(facts) != set(FILING) or facts["0000320193-25-000079"] != REVIEWED_REVENUE:
        raise ValueError("SEC_CONCEPT_TARGET_MISMATCH")
    return {"period_start": PERIOD[0], "period_end": PERIOD[1], "unit": "USD",
            "values_by_accession": facts, "original_matches_reviewed_10k": True,
            "comparison_equal": len(set(facts.values())) == 1}


def _child(kind: str, path: Path) -> None:
    url = URLS[kind]
    started = datetime.now(UTC)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                    "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            if response.geturl() != url or "json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("SEC_RESPONSE_SCOPE")
            raw = read_official_body(response, limit=MAX_BYTES)
    except Exception as exc:  # noqa: BLE001 - bounded public source observation
        write_worker_result(path, {"kind": kind, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"kind": kind, "url": url,
                               "started_at": started.isoformat(),
                               "retrieved_at": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe(kind: str) -> tuple[dict, bytes | None]:
    started = datetime.now(UTC)
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.sec_filing_control",
                            "--child", kind), timeout_seconds=25, max_bytes=2*1024*1024)
    out = {"kind": kind, "url": URLS[kind], "status": "BLOCK", "worker_status": task.status,
           "elapsed_seconds": task.elapsed_seconds, "decision_authority": False}
    if task.status != "OK" or task.payload is None:
        return out, None
    try:
        p = task.payload
        if p["kind"] != kind:
            raise ValueError("SEC_RECEIPT_KIND")
        if p.get("error"):
            return out | {"error": p["error"], "http_status": p.get("http_status")}, None
        end = datetime.fromisoformat(p["retrieved_at"])
        begin = datetime.fromisoformat(p["started_at"])
        if (p["url"] != URLS[kind] or begin.utcoffset() is None or end.utcoffset() is None
                or not started <= begin <= end <= datetime.now(UTC)):
            raise ValueError("SEC_RECEIPT_SCOPE")
        raw = base64.b64decode(p["body"], validate=True)
        if not 0 < len(raw) <= MAX_BYTES or hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise ValueError("SEC_RECEIPT_HASH")
        out |= {"sha256": p["sha256"], "bytes": len(raw), "retrieved_at": end.isoformat(),
                "parent_rehash": "MATCH", "historical_capture_verified": False}
        out["fields"] = extract_filings(raw, end) if kind == "submissions" else extract_concept(raw)
        return out | {"status": "OBSERVED"}, raw
    except Exception as exc:  # noqa: BLE001 - never log raw external error text
        code = str(exc)
        return out | {"error": code if code.startswith("SEC_") else type(exc).__name__}, None


def run_control() -> tuple[dict, bytes | None]:
    submissions, _ = observe("submissions")
    # Do not repeat or try alternate endpoints after a rate limit/access denial.
    if submissions["status"] != "OBSERVED":
        return {"status": "BLOCK", "submissions": submissions, "decision_authority": False}, None
    concept, raw = observe("concept")
    report = {"status": "WARN" if concept["status"] == "OBSERVED" else "BLOCK",
              "submissions": submissions, "concept": concept,
              "historical_capture_verified": False, "first_public_availability_verified": False,
              "pit_safe": False, "decision_authority": False, "revision_universe_complete": False,
              "raw_retention_candidate": raw is not None and len(raw) <= RETAIN_LIMIT}
    return report, raw if report["raw_retention_candidate"] else None


def emit_retention_candidate(raw: bytes) -> None:
    """Bounded exact public financial concept bytes, not general provider logs."""
    if not 0 < len(raw) <= RETAIN_LIMIT:
        raise ValueError("SEC_RETENTION_SIZE")
    extract_concept(raw)
    encoded = base64.b64encode(raw).decode("ascii")
    for i in range(0, len(encoded), 4096):
        print(f"PUBLIC_SEC_CONCEPT_BYTES {i//4096:04d} {encoded[i:i+4096]}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], Path(sys.argv[3]))
