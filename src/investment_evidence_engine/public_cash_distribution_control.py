"""Fixed public-document cash entitlement sensitivity, never total-return admission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from .bounded_worker import run_json_worker, write_worker_result
from .historical_capture import PublicSecurity, observe_pair, summarize_observed_pair
from .historical_reference import HistoricalCloseSeries
from .issuer_revision_control import normalize_text
from .market_calendar import SCHEDULE_VERSION, scheduled_days
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape

FIRST = date(2026, 1, 5)
LAST = date(2026, 8, 31)
STOCK = PublicSecurity(symbol="000035", asset_type="STOCK")
ETF = PublicSecurity(symbol="510300", asset_type="ETF")
MAX_BYTES = 1024 * 1024
DOCS = {
    "stock": {
        "symbol": STOCK.symbol, "page": 1,
        "url": "https://static.cninfo.com.cn/finalpage/2026-08-14/1225471266.PDF",
        "declared_day": "2026-08-14", "record_day": "2026-08-19",
        "ex_day": "2026-08-20", "payment_day": "2026-08-20",
        "cash_per_10": "0.36",
    },
    "etf": {
        "symbol": ETF.symbol, "page": 2,
        "url": "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-01-12/510300_20260112_VTCZ.pdf",
        "declared_day": "2026-01-12", "record_day": "2026-01-16",
        "ex_day": "2026-01-19", "payment_day": "2026-01-27",
        "cash_per_10": "1.2300",
    },
}


def checked_fields(kind: str, first_text: str, selected_text: str) -> dict:
    """Check the exact reviewed identity, amount and dated rows in the actual PDF."""
    doc = DOCS[kind]
    first, text = normalize_text(first_text), normalize_text(selected_text)
    if kind == "stock":
        if not all(x in first for x in ("证券代码:000035", "中国天楹股份有限公司",
                                        "2025年年度权益分派实施公告", "TY2026-37")):
            raise ValueError("DISTRIBUTION_DOCUMENT_IDENTITY")
        markers = ("股权登记日:2026年8月19日", "除权除息日:2026年8月20日",
                   "每10股派息(含税):0.36元", "除权前总股本:2,388,032,769股",
                   "除权后总股本:2,388,032,769股")
    else:
        if not all(x in first for x in ("华泰柏瑞沪深300交易型开放式指数证券投资基金分红公告",
                                        "2026年1月12日")):
            raise ValueError("DISTRIBUTION_DOCUMENT_IDENTITY")
        markers = ("基金主代码510300", "权益登记日2026年1月16日",
                   "除息日2026年1月19日", "现金红利发放日2026年1月27日",
                   "本次分红方案(单位:元/10份基金份额)1.2300",
                   "2026年第一次分红")
    if not all(marker in text for marker in markers):
        raise ValueError("DISTRIBUTION_REVIEWED_FIELDS_MISMATCH")
    return {k: doc[k] for k in ("symbol", "declared_day", "record_day", "ex_day", "payment_day")} | {
        "gross_cash_per_unit_cny": str(Decimal(doc["cash_per_10"]) / Decimal(10)),
        "declared_day_not_verified_publication_clock": True,
    }


def _child(kind: str, target: Path) -> None:
    started = datetime.now(UTC)
    doc = retrieve_pdf_bytes(DOCS[kind]["url"], max_bytes=MAX_BYTES)
    write_worker_result(target, {"kind": kind, "url": doc.source_url, "sha256": doc.sha256,
                                "started_at": started.isoformat(), "retrieved_at": doc.retrieved_at,
                                "body": base64.b64encode(doc.data).decode("ascii")})


def observe_document(kind: str, folder: Path) -> dict:
    from pypdf import PdfReader

    doc = DOCS[kind]
    out = {"kind": kind, "url": doc["url"], "status": "BLOCK",
           "historical_availability_verified": False, "raw_body_retained": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.public_cash_distribution_control",
                            "--child", kind), timeout_seconds=25, max_bytes=2 * MAX_BYTES)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if (p["kind"], p["url"]) != (kind, doc["url"]):
            raise ValueError("DISTRIBUTION_RECEIPT_SCOPE")
        start, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if start.utcoffset() is None or end.utcoffset() is None or not start <= end <= datetime.now(UTC):
            raise ValueError("DISTRIBUTION_RECEIPT_TIME")
        raw = base64.b64decode(p["body"], validate=True)
        validate_pdf_shape(raw, max_bytes=MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != p["sha256"]:
            raise ValueError("DISTRIBUTION_BODY_HASH")
        target = folder / (digest + ".pdf")
        with target.open("xb") as handle:
            handle.write(raw)
        reopened = target.read_bytes()
        if reopened != raw or hashlib.sha256(reopened).hexdigest() != digest:
            raise ValueError("DISTRIBUTION_REOPEN_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "parent_rehash": "MATCH",
                "temporary_rehash": "MATCH", "retrieved_at": end.isoformat(),
                "parser_version": version("pypdf")}
        reader = PdfReader(io.BytesIO(reopened), strict=True)
        if reader.is_encrypted or not doc["page"] <= len(reader.pages) <= 10:
            raise ValueError("DISTRIBUTION_PAGE_SCOPE")
        first = reader.pages[0].extract_text() or ""
        selected = reader.pages[doc["page"] - 1].extract_text() or ""
        out |= {"page": doc["page"], "page_count": len(reader.pages),
                "page_text_sha256": hashlib.sha256(normalize_text(selected).encode()).hexdigest()}
        fields = checked_fields(kind, first, selected)
    except Exception as exc:  # noqa: BLE001 - external parser boundary.
        code = str(exc)
        return out | {"error_code": code if re.fullmatch(r"DISTRIBUTION_[A-Z_]+", code)
                      else type(exc).__name__}
    return out | {"status": "OBSERVED", "fields": fields}


def cash_sensitivity(series: HistoricalCloseSeries, *, ex_date: date, cash: Decimal,
                     sessions: tuple[date, ...]) -> dict:
    """Exactly one reviewed event; hypothetical gross entitlement at ex-close."""
    series = HistoricalCloseSeries.model_validate(series.model_dump())
    if (series.currency != "CNY" or series.price_basis != "RAW_CLOSE"
            or tuple(row.session for row in series.closes) != sessions):
        raise ValueError("DISTRIBUTION_RAW_SESSION_SCOPE")
    if not cash.is_finite() or cash <= 0 or ex_date not in sessions[1:]:
        raise ValueError("DISTRIBUTION_EVENT_SCOPE")
    index = sessions.index(ex_date)
    prices = [row.close for row in series.closes]
    amount = float(cash)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("DISTRIBUTION_EVENT_SCOPE")
    previous, ex_close = prices[index - 1], prices[index]
    daily_raw = (ex_close / previous - 1) * 100
    daily_cash = ((ex_close + amount) / previous - 1) * 100
    full_raw = (prices[-1] / prices[0] - 1) * 100
    full_cash = ((prices[-1] / prices[0]) * (1 + amount / ex_close) - 1) * 100
    result = {"event_price_return_pct": daily_raw, "event_gross_entitlement_return_pct": daily_cash,
              "event_difference_pp": daily_cash - daily_raw, "full_price_return_pct": full_raw,
              "full_one_event_reinvested_return_pct": full_cash, "full_difference_pp": full_cash - full_raw}
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError("DISTRIBUTION_NONFINITE_RESULT")
    return result | {"symbol": series.subject_id, "provider": series.source_label,
                     "ex_date": ex_date.isoformat(), "previous_session": sessions[index - 1].isoformat(),
                     "normalized_series_sha256": hashlib.sha256(series.model_dump_json().encode()).hexdigest()}


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    with TemporaryDirectory() as temp:
        receipts = [observe_document(kind, Path(temp)) for kind in DOCS]
    report = {"status": "BLOCK", "documents": receipts, "executor_commit": os.environ["GITHUB_SHA"],
              "calendar_version": SCHEDULE_VERSION, "calendar_coverage_verified": False,
              "corporate_action_coverage_verified": False, "historical_vintage_verified": False,
              "decision_authority": False, "execution_allowed": False, "research_only": True,
              "pit_safe": False, "raw_provider_bytes_retained": False,
              "cash_convention": "ONE_KNOWN_GROSS_ENTITLEMENT_REINVESTED_AT_EX_CLOSE_NOT_PAYMENT_DATE",
              "taxes_fees_splits_other_events_verified": False}
    if all(r["status"] == "OBSERVED" for r in receipts):
        summary, series = observe_pair(STOCK, ETF, FIRST, LAST, providers=("sina", "tencent"))
        report["actual_attempts"] = summary
        pair = summarize_observed_pair(STOCK, ETF, series, FIRST, LAST)
        if pair["status"] == "OBSERVED_REFERENCE_ONLY" and pair["crosscheck"] == "MATCH":
            sessions = tuple(row.day for row in scheduled_days(FIRST, LAST) if row.is_trading_day)
            fields = {r["fields"]["symbol"]: r["fields"] for r in receipts}
            try:
                report["scenarios"] = [cash_sensitivity(s,
                    ex_date=date.fromisoformat(fields[s.subject_id]["ex_day"]),
                    cash=Decimal(fields[s.subject_id]["gross_cash_per_unit_cny"]),
                    sessions=sessions) for s in series]
            except ValueError as exc:
                report["blocker"] = str(exc)
            else:
                report |= {"status": "WARN", "scheduled_session_count": len(sessions),
                           "scheduled_session_labels_match": True, "observed_event_list_exhaustive": False}
        else:
            report["blocker"] = "TWO_SOURCE_PER_ASSET_REQUIRED"
    print("PUBLIC_CASH_DISTRIBUTION_CONTROL " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return 0 if report["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        _child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
