"""Fixed issuer document control: gross cash, ex-reference and treasury cancellation.

Only three newly reviewed official documents; no raw-body redistribution, no
complete action history, no inferred historical capture time or actual payment.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .cash_entitlement import (
    CashEntitlementTerms,
    conditional_reference_price,
    reconcile_treasury_cancellation,
)
from .issuer_revision_control import normalize_text
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape

REPO = "riyuewuxing/InvestmentEvidenceEngine"
ROOT = "https://static.cninfo.com.cn/finalpage/"
DOCS = {
    "cash_2025": ("2025-07-30/1224330035.PDF", "TY2025-30", "2024年年度权益分派实施公告", (0, 2, 3)),
    "cancellation": ("2025-10-30/1224764617.PDF", "TY2025-43", "关于回购股份完成注销暨", (0,)),
    "registration": ("2025-12-05/1224850081.PDF", "TY2025-51", "关于完成注册资本工商变更登记的公告", (0,)),
}
MAX_BYTES = 1024 * 1024


def _require(text: str, markers: tuple[str, ...]) -> None:
    if not all(marker in text for marker in markers):
        raise ValueError("ENTITLEMENT_REVIEWED_FIELDS_MISMATCH")


def parse_pages(kind: str, pages: dict[int, str]) -> dict:
    suffix, code, title, wanted = DOCS[kind]
    if set(pages) != set(wanted):
        raise ValueError("ENTITLEMENT_PAGE_SCOPE")
    pages = {index: normalize_text(value) for index, value in pages.items()}
    first = pages[0]
    _require(first, ("证券代码:000035", "中国天楹股份有限公司", code, title))
    if kind == "cash_2025":
        _require(first, ("股权登记日:2025年8月5日", "除权除息日:2025年8月6日",
                         "除权前总股本:2,500,783,182股", "112,750,413股",
                         "每10股派息(含税):0.352元", "现金分红总额:84,058,753.47元",
                         "除权后总股本:2,500,783,182股", "0.336129元"))
        _require(pages[2], ("代派的A股股东现金红利将于2025年8月6日",
                            "0.0336129元/股", "84,058,753.47元", "2,500,783,182股",
                            "股权登记日收盘价-0.0336129元/股"))
        _require(pages[3], ("中国天楹股份有限公司董事会", "2025年7月30日"))
        terms = CashEntitlementTerms(symbol="000035", disclosed_date=date(2025, 7, 30),
            record_date=date(2025, 8, 5), ex_date=date(2025, 8, 6),
            source_locator=ROOT+suffix, total_shares=2500783182, excluded_shares=112750413,
            gross_per_share=Decimal("0.0352"), declared_total_cash=Decimal("84058753.47"),
            declared_reference_deduction=Decimal("0.0336129"))
        return terms.checked() | {"delegated_payment_scheduled_date": "2025-08-06",
                                  "actual_payment_verified": False}
    if kind == "cancellation":
        _require(first, ("112,750,413股", "总股本由2,500,783,182股变更为2,388,032,769股",
                         "2025年10月28日办理完成", "持有公司的股份数量不变",
                         "23.62%被动增加至24.74%"))
        return {"before": 2500783182, "cancelled": 112750413, "after": 2388032769,
                "completed": "2025-10-28", "document_path_day": "2025-10-30",
                "reported_unchanged_holder_units": True}
    _require(first, ("112,750,413股", "总股本由2,500,783,182股变更为2,388,032,769股",
                     "2025年12月4日完成了注册资本变更手续",
                     "原注册资本:250078.3182万元整", "现注册资本:238803.2769万元整",
                     "2025年12月5日"))
    return {"before": 2500783182, "cancelled": 112750413, "after": 2388032769,
            "completed": "2025-12-04", "document_date": "2025-12-05"}


def _child(kind: str, target: Path) -> None:
    started = datetime.now(UTC)
    document = retrieve_pdf_bytes(ROOT+DOCS[kind][0], max_bytes=MAX_BYTES)
    write_worker_result(target, {"kind": kind, "url": document.source_url,
        "started_at": started.isoformat(), "retrieved_at": document.retrieved_at,
        "sha256": document.sha256, "body": base64.b64encode(document.data).decode("ascii")})


def observe(kind: str, folder: Path) -> dict:
    from pypdf import PdfReader

    url = ROOT+DOCS[kind][0]
    out = {"kind": kind, "url": url, "status": "BLOCK", "raw_body_retained": False,
           "historical_availability_verified": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.issuer_entitlement_control",
                            "--child", kind), timeout_seconds=25, max_bytes=2*MAX_BYTES)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if (p["kind"], p["url"]) != (kind, url):
            raise ValueError("ENTITLEMENT_SOURCE_SCOPE")
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("ENTITLEMENT_OBSERVATION_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("ENTITLEMENT_SOURCE_DIGEST")
        path = folder/(kind+".pdf")
        with path.open("xb") as f:
            f.write(raw)
        reopened = path.read_bytes()
        if reopened != raw or hashlib.sha256(reopened).hexdigest() != digest:
            raise ValueError("ENTITLEMENT_TEMPORARY_DIGEST")
        out |= {"source_sha256": digest, "source_bytes": len(raw), "parent_rehash": "MATCH",
                "temporary_rehash": "MATCH", "started_at": start.isoformat(), "retrieved_at": end.isoformat()}
        reader = PdfReader(io.BytesIO(reopened), strict=True)
        wanted = DOCS[kind][3]
        if reader.is_encrypted or not max(wanted) < len(reader.pages) <= 12:
            raise ValueError("ENTITLEMENT_DOCUMENT_PAGE_COUNT")
        pages = {i: reader.pages[i].extract_text() or "" for i in wanted}
        out |= {"page_count": len(reader.pages),
                "page_text_sha256": {str(i+1): hashlib.sha256(normalize_text(t).encode()).hexdigest()
                                     for i, t in pages.items()}}
        fields = parse_pages(kind, pages)
    except Exception as exc:  # noqa: BLE001 - bounded external parser.
        reason = str(exc)
        return out | {"error_code": reason if re.fullmatch(r"(ENTITLEMENT|CASH_TERMS)_[A-Z_]+", reason)
                      else type(exc).__name__}
    return out | {"status": "OBSERVED", "fields": fields}


def reconcile(receipts: list[dict]) -> dict:
    if (len(receipts) != len(DOCS) or {r["kind"] for r in receipts} != set(DOCS)
            or any(r["status"] != "OBSERVED" for r in receipts)):
        raise ValueError("ENTITLEMENT_INCOMPLETE_DOCUMENTS")
    by = {r["kind"]: r["fields"] for r in receipts}
    cash, cancel, reg = by["cash_2025"], by["cancellation"], by["registration"]
    if (cancel["before"], cancel["cancelled"], cancel["after"]) != (
            reg["before"], reg["cancelled"], reg["after"]):
        raise ValueError("ENTITLEMENT_CANCELLATION_REGISTRATION_CONFLICT")
    if (cash["total_shares"], cash["excluded_shares"], cash["eligible_shares"]) != (
            cancel["before"], cancel["cancelled"], cancel["after"]):
        raise ValueError("ENTITLEMENT_SHARE_SCOPE_CONFLICT")
    event = reconcile_treasury_cancellation(before=cancel["before"], cancelled=cancel["cancelled"],
        after=cancel["after"], completed=date.fromisoformat(cancel["completed"]),
        disclosed=date.fromisoformat(cancel["document_path_day"]),
        registration_completed=date.fromisoformat(reg["completed"]),
        registration_disclosed=date.fromisoformat(reg["document_date"]))
    if date.fromisoformat(cash["ex_date"]) >= date.fromisoformat(cancel["completed"]):
        raise ValueError("ENTITLEMENT_EVENT_ORDER_CONFLICT")
    # Deliberately hypothetical prior close: isolates the cent-rounding
    # difference; never present as observed historical market price.
    prior = Decimal("5.00")
    return {"cash_terms": cash, "cancellation": event,
            "hypothetical_prior_close_cny": str(prior),
            "correct_reference_cny": str(conditional_reference_price(
                prior, Decimal(cash["reference_deduction_per_share_cny"]))),
            "incorrect_entitlement_as_reference_cny": str(conditional_reference_price(
                prior, Decimal(cash["gross_entitlement_per_share_cny"]))),
            "historical_market_reference_verified": False,
            "complete_corporate_action_history_verified": False}


def main() -> int:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise SystemExit("public repository required")
    report = {"status": "BLOCK", "executor_commit": os.environ["GITHUB_SHA"], "subject": "000035",
              "historical_availability_verified": False, "raw_body_retained": False,
              "pit_safe": False, "decision_authority": False, "execution_allowed": False}
    with TemporaryDirectory() as temp:
        report["documents"] = [observe(kind, Path(temp)) for kind in DOCS]
    try:
        report["reconciliation"] = reconcile(report["documents"])
        report["status"] = "WARN"
    except (ValueError, KeyError, TypeError) as exc:
        report["blocker"] = str(exc) if str(exc).startswith("ENTITLEMENT_") else type(exc).__name__
    print("PUBLIC_ISSUER_ENTITLEMENT_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
