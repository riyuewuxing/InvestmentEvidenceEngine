"""Fixed issuer disclosure revision diagnostic with actual PDF byte rehash.

A dated official static document is evidence of the currently observed version.
It is NOT proof that identical bytes were retrievable at an earlier cutoff.
No raw bodies are published; no decision authority or investment recommendation.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import sys
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .evidence_time_guard import source_visible
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape

ROOT = "https://static.cninfo.com.cn/finalpage/"
SUBJECT = "000035"
DOCS = {
    "annual_2024": ("2025-04-29/1223370914.PDF", 2, "2024年年度报告摘要"),
    "annual_2025": ("2026-04-29/1225231251.PDF", 2, "2025年年度报告摘要"),
    "policy_2026": ("2026-04-29/1225231269.PDF", 0, "关于会计政策变更的公告"),
    "half_2026": ("2026-08-29/1225528852.PDF", 1, "2026年半年度报告摘要"),
}
MAX_BYTES = 4 * 1024 * 1024
AMOUNT = r"-?[0-9]{1,3}(?:,[0-9]{3})+[.][0-9]{2}"
LABELS = {"assets": "总资产", "parent_equity": "归属于上市公司股东的净资产"}
# Page-specific table rows reviewed visually from the original publisher PDFs.
# Exact ordered values are independently checked, not used to fill missing data.
EXPECTED = {
    "annual_2024": {
        "assets": ("29,320,007,895.30", "28,112,154,208.19", "26,467,772,083.58"),
        "parent_equity": ("10,753,821,805.70", "10,650,951,399.10", "10,291,182,012.64"),
    },
    "annual_2025": {
        "assets": ("32,084,341,383.18", "29,320,007,895.30", "28,112,154,208.19"),
        "parent_equity": ("10,892,968,839.23", "10,753,821,805.70", "10,650,951,399.10"),
    },
    "half_2026": {
        "assets": ("32,925,743,186.99", "32,084,341,383.18", "32,067,826,798.82"),
        "parent_equity": ("10,828,959,345.85", "10,892,968,839.23", "10,758,535,847.11"),
    },
}


def normalize_text(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def extract_checked_rows(kind: str, text: str) -> dict:
    if kind not in EXPECTED:
        raise ValueError("ISSUER_UNKNOWN_TABLE")
    flat = normalize_text(text)
    result = {}
    for key, label in LABELS.items():
        # Anchor the row by its label and stop at the next label/non-numeric
        # token. Match every monetary cell in order, never a global substring.
        regex = (re.escape(label) + r"(?:\(元\))?(" + AMOUNT + r")(" + AMOUNT
                 + r")(?:" + r"-?[0-9]+[.][0-9]+%" + r")?(" + AMOUNT + r")")
        matches = re.findall(regex, flat)
        if len(matches) != 1 or tuple(matches[0]) != EXPECTED[kind][key]:
            raise ValueError("ISSUER_TABLE_ROW_OR_ORDER_MISMATCH")
        result[key] = tuple(str(Decimal(v.replace(",", ""))) for v in matches[0])
    return result


def parse_document(kind: str, raw: bytes) -> dict:
    from pypdf import PdfReader

    validate_pdf_shape(raw, max_bytes=MAX_BYTES)
    _, page_index, title = DOCS[kind]
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not page_index < len(reader.pages) <= 40:
        raise ValueError("ISSUER_PAGE_COUNT_OR_ENCRYPTION")
    first = normalize_text(reader.pages[0].extract_text() or "")
    page = normalize_text(reader.pages[page_index].extract_text() or "")
    if "中国天楹股份有限公司" not in first or SUBJECT not in first or title not in first:
        raise ValueError("ISSUER_DOCUMENT_IDENTITY")
    if "中国天楹股份有限公司" not in page or not page:
        raise ValueError("ISSUER_PAGE_IDENTITY")
    checks = {"page": page_index + 1, "page_count": len(reader.pages),
              "normalized_page_text_sha256": hashlib.sha256(page.encode()).hexdigest(),
              "first_page_text_sha256": hashlib.sha256(first.encode()).hexdigest()}
    if kind == "policy_2026":
        if not all(v in page for v in ("TY2026-22", "2026年1月1日", "同期报表进行追溯调整")):
            raise ValueError("ISSUER_POLICY_FIELDS")
        return checks | {"policy_effective_date": "2026-01-01",
                         "retrospective_adjustment_declared": True}
    if kind == "half_2026":
        if not all(v in page for v in ("调整前", "调整后", "TY2026-22", "保险合同")):
            raise ValueError("ISSUER_RESTATEMENT_FIELDS")
    return checks | {"table_rows_cny": extract_checked_rows(kind, page)}


def _child(kind: str, path: Path) -> None:
    started = datetime.now(UTC)
    doc = retrieve_pdf_bytes(ROOT + DOCS[kind][0], max_bytes=MAX_BYTES)
    write_worker_result(path, {"kind": kind, "url": doc.source_url, "sha256": doc.sha256,
                               "retrieved_at": doc.retrieved_at, "started_at": started.isoformat(),
                               "body": base64.b64encode(doc.data).decode("ascii")})


def observe_document(kind: str, folder: Path) -> dict:
    path_suffix, _, _ = DOCS[kind]
    url = ROOT + path_suffix
    out = {"kind": kind, "url": url, "status": "BLOCK", "decision_authority": False,
           "declared_document_date": path_suffix.split("/")[0],
           "historical_availability_verified": False, "raw_body_retained": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.issuer_revision_control",
                            "--child", kind), timeout_seconds=25, max_bytes=6 * 1024 * 1024)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if (p["kind"], p["url"]) != (kind, url):
            raise ValueError("ISSUER_RECEIPT_IDENTITY")
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("ISSUER_RECEIPT_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("ISSUER_ORIGINAL_BYTE_HASH")
        path = folder / (digest + ".pdf")
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(raw)
        reopened = path.read_bytes()
        if reopened != raw or hashlib.sha256(reopened).hexdigest() != digest:
            raise ValueError("ISSUER_MATERIALIZED_BYTE_HASH")
        out |= {"source_sha256": digest, "source_bytes": len(raw),
                "started_at": start.isoformat(), "retrieved_at": end.isoformat(),
                "original_parent_rehash": "MATCH", "temporary_file_rehash": "MATCH"}
        # Parent parsing operates on the reopened, exact original bytes. The
        # outer workflow has a hard timeout covering PDF decompression/parsing.
        out |= parse_document(kind, reopened)
    except Exception as exc:  # noqa: BLE001 - untrusted document boundary; no raw text in logs.
        code = str(exc)
        return out | {"error_code": code if re.fullmatch(r"ISSUER_[A-Z0-9_]{1,90}", code)
                      else type(exc).__name__}
    return out | {"status": "OBSERVED"}


def revision_diagnostic(receipts: list[dict]) -> dict:
    if (len(receipts) != len(DOCS) or {r["kind"] for r in receipts} != set(DOCS)
            or any(r["status"] != "OBSERVED" for r in receipts)):
        raise ValueError("ISSUER_INCOMPLETE_OBSERVATION")
    by = {r["kind"]: r for r in receipts}
    if not by["policy_2026"].get("retrospective_adjustment_declared"):
        raise ValueError("ISSUER_MISSING_POLICY_LINK")
    comparison = []
    for field in LABELS:
        previous = by["annual_2024"]["table_rows_cny"][field][0]
        before = by["annual_2025"]["table_rows_cny"][field]
        later = by["half_2026"]["table_rows_cny"][field]
        if before[1] != previous or later[1] != before[0]:
            raise ValueError("ISSUER_COMPARATIVE_LINK_MISMATCH")
        original, adjusted = Decimal(before[0]), Decimal(later[2])
        if original == adjusted or original <= 0:
            raise ValueError("ISSUER_EXPECTED_RESTATEMENT_MISSING")
        comparison.append({"field": field, "period_end": "2025-12-31",
                           "original_cny": str(original), "adjusted_cny": str(adjusted),
                           "adjustment_cny": str(adjusted-original),
                           "adjustment_pct": str(((adjusted/original-1)*100).quantize(Decimal("0.000001"))),
                           "original_document": by["annual_2025"]["url"],
                           "adjusted_document": by["half_2026"]["url"]})
    # Strictly distinguish document-path day from actual observation time.
    # A historical cutoff can screen declared document days, but the observed
    # bytes were collected now. Never convert a path date to available_at.
    checks = []
    for cutoff in ("2025-12-31", "2026-06-30", "2026-09-01"):
        local_cutoff = datetime.fromisoformat(cutoff+"T23:59:59+08:00")
        date_scope = [r["kind"] for r in receipts
                      if date.fromisoformat(r["declared_document_date"]) <= local_cutoff.date()]
        eligible = [r["kind"] for r in receipts if source_visible(
            available_at=datetime.fromisoformat(r["retrieved_at"]),
            retrieved_at=datetime.fromisoformat(r["retrieved_at"]),
            published_at=None, cutoff=local_cutoff)]
        checks.append({"cutoff": cutoff, "document_date_screen_only": date_scope,
                       "actually_observed_by_cutoff": eligible})
    if any(row["actually_observed_by_cutoff"] for row in checks):
        raise ValueError("ISSUER_HISTORICAL_OBSERVATION_BOUNDARY")
    return {"status": "OBSERVED_ACCOUNTING_REVISION_ONLY", "subject": SUBJECT,
            "comparison": comparison, "cutoff_checks": checks,
            "historical_vintage_verified": False, "historical_availability_verified": False,
            "revision_universe_complete": False, "pit_safe": False, "research_only": True,
            "execution_allowed": False, "decision_authority": False}


def run_control() -> dict:
    with TemporaryDirectory() as temp:
        receipts = [observe_document(kind, Path(temp)) for kind in DOCS]
        result = {"status": "BLOCK", "documents": receipts, "raw_body_retained": False,
                  "decision_authority": False}
        try:
            result["revision"] = revision_diagnostic(receipts)
            result["status"] = "WARN"
        except ValueError as exc:
            result["error_code"] = str(exc)
        return result


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit(2)
    _child(sys.argv[2], Path(sys.argv[3]))
