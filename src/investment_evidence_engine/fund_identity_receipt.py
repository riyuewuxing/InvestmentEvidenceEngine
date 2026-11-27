"""Validate metadata-only product disclosure observations, never admit them.

Transport rehash is a reported runner observation, not receiving-side possession
of original PDF bytes or proof that the document remains the latest version.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from .official_pdf_routes import canonical_official_pdf_url

REPO = "riyuewuxing/InvestmentEvidenceEngine"
MARKER = "PUBLIC_FUND_IDENTITY"
MAX_LOG_BYTES = 64 * 1024
SELECTION = "FIXED_PUBLIC_PRODUCT_IDENTITY_CONTROLS_NOT_VENDOR_RANK"
BASE_FLAGS = ("actual_cost_verified", "actual_dealing_verified", "candidate_rank_membership_verified",
              "current_notice_chain_verified", "formal_admission", "historical_first_availability_verified")


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("DUPLICATE_JSON_KEY")
        out[key] = value
    return out


def _nonfinite(_value):
    raise ValueError("NONFINITE_JSON")


def strict_json(raw: str):
    if len(raw.encode("utf-8")) > MAX_LOG_BYTES:
        raise ValueError("OVERSIZE_IDENTITY_LOG")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)


def _date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("IDENTITY_DATE")
    return date.fromisoformat(value).isoformat()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("IDENTITY_CLOCK")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("IDENTITY_CLOCK")
    return parsed.astimezone(UTC)


def _code(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value):
        raise ValueError("IDENTITY_CODE")
    return value


def _hash(value: Any, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value):
        raise ValueError("IDENTITY_HASH")
    return value


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError("IDENTITY_TEXT")
    return value


def _rate(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,6})?", value):
        raise ValueError("IDENTITY_RATE")
    if not Decimal(0) <= Decimal(value) <= Decimal(100):
        raise ValueError("IDENTITY_RATE")
    return value


def parse_identity_receipt(log_line: str, *, expected_commit: str, now: datetime) -> dict[str, dict]:
    """Return per-share-class dated metadata; all admission flags remain false."""
    if now.utcoffset() is None or len(log_line.encode("utf-8")) > MAX_LOG_BYTES:
        raise ValueError("IDENTITY_LOG_BOUNDARY")
    stamp, sep, raw = log_line.partition(" " + MARKER + " ")
    if not sep:
        raise ValueError("IDENTITY_LOG_MARKER")
    t = _time(stamp)
    report = strict_json(raw)
    if (not isinstance(report, dict) or report.get("status") != "WARN"
            or report.get("selection") != SELECTION
            or report.get("research_only") is not True
            or any(report.get(f) is not False for f in ("formal_admission", "decision_authority", "execution_allowed"))
            or _hash(report.get("executor_commit"), 40) != _hash(expected_commit, 40)):
        raise ValueError("IDENTITY_REPORT_SCOPE")
    start, end = (_time(report[k]) for k in ("started_at", "finished_at"))
    if not start <= end <= t <= now:
        raise ValueError("IDENTITY_REPORT_CLOCK")
    records = report["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= 32:
        raise ValueError("IDENTITY_RECORD_COUNT")
    out = {}
    for r in records:
        code = _code(r["code"])
        url = r["url"]
        if (r["status"] != "OBSERVED" or r["worker_status"] != "OK"
                or r["raw_body_retained"] is not False or r["parent_rehash"] != "MATCH"
                or type(r["bytes"]) is not int or not 0 < r["bytes"] <= 2 * 1024 * 1024
                or type(r["page_count"]) is not int or not 3 <= r["page_count"] <= 8
                or canonical_official_pdf_url(url) != url):
            raise ValueError("IDENTITY_RECEIPT_SCOPE")
        a, b, capture = (_time(r[k]) for k in ("started_at", "finished_at", "retrieved_at"))
        if not start <= a <= capture <= b <= end:
            raise ValueError("IDENTITY_RECEIPT_CLOCK")
        digest = _hash(r["sha256"], 64)
        f = r["fields"]
        if f.get("code") != code or any(f.get(k) is not False for k in BASE_FLAGS):
            raise ValueError("IDENTITY_FIELD_SCOPE")
        doc = _date(f["document_day"])
        # For these dated official exchange/CNINFO paths, URL date must match
        # the document's declared dispatch day. No historical ingestion claim.
        if doc not in urlsplit(url).path.split("/") or doc > capture.date().isoformat():
            raise ValueError("IDENTITY_DOCUMENT_DAY")
        if urlsplit(url).hostname == "www.sse.com.cn" and not urlsplit(url).path.rsplit("/", 1)[-1].startswith(code + "_"):
            raise ValueError("IDENTITY_EXCHANGE_CODE")
        kind = f["product_kind"]
        manager_start = f["manager_start_reported"]
        if manager_start is None:
            if kind != "ACTIVE_ETF":
                raise ValueError("IDENTITY_MANAGER_DATE")
        else:
            manager_start = _date(manager_start)
            if manager_start > doc:
                raise ValueError("IDENTITY_MANAGER_DATE")
        classes = f["share_class_codes"]
        if not isinstance(classes, list) or not 1 <= len(classes) <= 16:
            raise ValueError("IDENTITY_CLASS_SCOPE")
        classes = [_code(c) for c in classes]
        if len(set(classes)) != len(classes) or code not in classes or set(classes) & set(out):
            raise ValueError("IDENTITY_CLASS_SCOPE")
        rates = f["estimated_operation_rate_pct"]
        if not isinstance(rates, dict) or set(rates) != set(classes):
            raise ValueError("IDENTITY_RATE_SCOPE")
        rates = {c: (None if v is None and kind == "ACTIVE_ETF" else _rate(v)) for c, v in rates.items()}
        listing_day = None
        listing_url = None
        listing_hash = None
        listing_capture = None
        basis = f["fee_basis"]
        if kind == "INDEX_ETF":
            if classes != [code] or basis != "FUND_ASSET_NAV" or f.get("listed_exchange_reported") not in {"SSE", "SZSE"}:
                raise ValueError("IDENTITY_ETF_SCOPE")
            if urlsplit(url).hostname == "www.sse.com.cn" and f["listed_exchange_reported"] != "SSE":
                raise ValueError("IDENTITY_EXCHANGE_CONFLICT")
            listing_day = _date(f["listing_day_reported"])
            if listing_day > doc or f.get("target_not_realized_tracking_error") is not True:
                raise ValueError("IDENTITY_ETF_SCOPE")
            target = _rate(f["tracking_error_target_pct"])
        elif kind == "ACTIVE_ETF":
            if (classes != [code] or basis != "FUND_ASSET_NAV"
                    or f.get("listed_exchange_reported") not in {"SSE", "SZSE"}
                    or f.get("not_index_tracking_objective") is not True
                    or "tracking_error_target_pct" in f or "listing_day_reported" in f):
                raise ValueError("IDENTITY_ACTIVE_SCOPE")
            listing = r["listing_notice"]
            listing_url = listing["url"]
            la, lb, lc = (_time(listing[k]) for k in ("started_at", "finished_at", "retrieved_at"))
            lf = listing["fields"]
            listing_day = _date(lf["listing_day_reported"])
            if (listing.get("code") != code + "_listing" or lf.get("code") != code
                    or listing["status"] != "OBSERVED" or listing["worker_status"] != "OK"
                    or listing["parent_rehash"] != "MATCH" or listing["raw_body_retained"] is not False
                    or type(listing["bytes"]) is not int or not 0 < listing["bytes"] <= 2 * 1024 * 1024
                    or type(listing["page_count"]) is not int or listing["page_count"] != 1
                    or canonical_official_pdf_url(listing_url) != listing_url
                    or not start <= la <= lc <= lb <= end
                    or lf.get("product_kind") != kind or lf.get("listed_exchange_reported") != f["listed_exchange_reported"]
                    or lf.get("actual_dealing_verified") is not False or lf.get("formal_admission") is not False
                    or _date(lf["document_day"]) != listing_day
                    or listing_day not in urlsplit(listing_url).path.split("/")
                    or not doc <= listing_day <= lc.date().isoformat()):
                raise ValueError("IDENTITY_ACTIVE_LISTING_SCOPE")
            listing_hash = _hash(listing["sha256"], 64)
            listing_capture = lc.isoformat()
            target = None
        elif kind == "ETF_FEEDER_FUND":
            if basis != "NAV_EXCLUDING_TARGET_ETF_ASSETS" or "tracking_error_target_pct" in f:
                raise ValueError("IDENTITY_FEEDER_SCOPE")
            target = None
        else:
            raise ValueError("IDENTITY_UNSUPPORTED_KIND")
        conversion = f.get("conversion_day_reported")
        if conversion is not None:
            if kind != "ETF_FEEDER_FUND" or f.get("former_kind") != "LOF" or _date(conversion) > doc:
                raise ValueError("IDENTITY_CONVERSION_SCOPE")
        for share in classes:
            out[share] = {
                "share_code": share, "product_main_code": code, "product_kind_reported": kind,
                "document_day": doc, "retrieved_at": capture.isoformat(),
                "listed_exchange_reported": f["listed_exchange_reported"] if kind in {"INDEX_ETF", "ACTIVE_ETF"} else None,
                "listing_day_reported": listing_day, "listing_source_url": listing_url,
                "listing_reported_original_sha256": listing_hash, "listing_retrieved_at": listing_capture,
                "source_url": url, "reported_original_sha256": digest, "page_count": r["page_count"],
                "manager_name_reported": _text(f["manager_name_reported"], 80),
                "manager_start_reported": manager_start, "benchmark_reported": _text(f["benchmark"], 200),
                "management_rate_pct_reported": _rate(f["management_rate_pct"]),
                "custody_rate_pct_reported": _rate(f["custody_rate_pct"]),
                "fee_basis_reported": basis, "estimated_operation_rate_pct_reported": rates[share],
                "tracking_error_target_pct_reported": target, "conversion_day_reported": conversion,
                "research_only": True, "current_notice_chain_verified": False,
                "receiver_original_bytes_verified": False, "formal_admission": False,
                "execution_allowed": False, "decision_authority": False,
                "candidate_rank_membership_verified": False,
            }
    return out
