"""Fixed public merger consideration control, not an actual holding or total return."""
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

from pypdf import PdfReader

from .bounded_worker import run_json_worker, write_worker_result
from .market_worker import _observe
from .official_pdf_transport import retrieve_pdf_bytes, validate_pdf_shape
from .sse_lifecycle_control import normalized

DOCS = {
    "halt": "https://static.cninfo.com.cn/finalpage/2025-02-05/1222455977.PDF",
    "conversion": "https://static.cninfo.com.cn/finalpage/2025-03-14/1222789432.PDF",
}
MAX_BYTES = 2 * 1024 * 1024
OLD = "600837"
NEW = "601211"
LAST_TRADE = date(2025, 2, 5)
HALT = date(2025, 2, 6)
RECORD = date(2025, 3, 3)
TERMINATION = date(2025, 3, 4)
REGISTERED = date(2025, 3, 13)
NEW_LISTING = date(2025, 3, 17)
RATIO = Decimal("0.62")


def required(text: str, markers: tuple[str, ...]) -> None:
    if not all(marker in text for marker in markers):
        raise ValueError("MERGER_DOCUMENT_FIELDS_MISSING")


def one(pattern: str, text: str) -> re.Match:
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("MERGER_DOCUMENT_FIELD_SCOPE")
    return matches[0]


def share_count(value: str) -> int:
    if not re.fullmatch(r"(?:[0-9]{1,15}|[0-9]{1,3}(?:,[0-9]{3}){1,4})", value):
        raise ValueError("MERGER_SHARE_COUNT_SCHEMA")
    n = int(value.replace(",", ""))
    if not 0 < n <= 10**14:
        raise ValueError("MERGER_SHARE_COUNT_BOUNDS")
    return n


def parse_halt(pages: list[str]) -> dict:
    if len(pages) != 2:
        raise ValueError("MERGER_HALT_PAGE_SCOPE")
    p1, p2 = [normalized(p) for p in pages]
    required(p1, ("证券代码:600837", "临2025-019", "海通证券股份有限公司关于公司",
                  "股票连续停牌直至终止上市、实施换股吸收合并的提示性公告",
                  "2025年2月6日(即异议股东现金选择权申报日)开市起连续停牌,不再交易。",
                  "2025年2月5日为公司股票最后一个交易日"))
    required(p2, ("公司股东换股取得的国泰君安股票应当为整数",
                  "小数点后尾数大小排序", "随机发放", "海通证券股份有限公司董事会2025年2月4日"))
    return {"old_security": "sh." + OLD, "declared_signature_date": "2025-02-04",
            "source_path_date": "2025-02-05", "last_announced_trading_date": LAST_TRADE.isoformat(),
            "announced_continuous_halt_start": HALT.isoformat(),
            "fractional_allocation_depends_on_all_eligible_holders": True,
            "cash_option_eligibility_verified": False}


def parse_conversion(pages: list[str]) -> dict:
    if not 4 <= len(pages) <= 12:
        raise ValueError("MERGER_CONVERSION_PAGE_SCOPE")
    texts = [normalized(p) for p in pages]
    p1, p3p4 = texts[0], "".join(texts[2:4])
    required(p1, ("证券代码:601211", "公告编号:2025-028",
                  "A股换股实施结果、股份变动暨新增A股股份上市公告",
                  "本次股票上市流通日期为2025年3月17日",
                  "2025年3月4日海通证券A股股票终止上市后",
                  "股票市值无法在投资者账户总市值中体现",
                  "本次募集配套资金新增A股股份数量为626,174,076股"))
    required(texts[-1], ("国泰君安证券股份有限公司董事会2025年3月14日",))
    required(p3p4, ("A股换股实施股权登记日为2025年3月3日",
                    "2025年3月13日收到中国证券登记结算有限责任公司上海分公司出具的《证券变更登记证明》",
                    "按照1:0.62的比例转换为本公司A股股票",
                    "每1股海通证券A股股票可换取0.62股国泰君安A股股票"))
    n = r"([0-9,]{1,25})"
    values = one(r"截至2025年3月13日止,国泰君安本次实际发行" + n
                 + r"股A股股票,原海通证券的A股换股股东以其于换股实施股权登记日持有的"
                 + n + r"股海通证券A股股票和海通证券持有的库存股" + n
                 + r"股按照1:0\.62换股比例换取国泰君安发行的" + n + r"股A股股票", p3p4)
    issued, outstanding, treasury, repeated = map(share_count, values.groups())
    if issued != repeated or (issued, outstanding, treasury) != (5985871332, 9577556713, 77074467):
        raise ValueError("MERGER_FIXED_SHARE_VALUES_MISMATCH")
    exact = Decimal(outstanding + treasury) * RATIO
    residual = Decimal(issued) - exact
    if abs(residual) >= 1:
        raise ValueError("MERGER_AGGREGATE_ROUNDING_CONFLICT")
    return {
        "old_security": "sh." + OLD, "new_security": "sh." + NEW,
        "declared_notice_date": "2025-03-14", "record_date": RECORD.isoformat(),
        "termination_date": TERMINATION.isoformat(), "issuer_reported_registration_date": REGISTERED.isoformat(),
        "new_share_listing_date": NEW_LISTING.isoformat(), "new_shares_per_old_share": str(RATIO),
        "old_eligible_shares": outstanding, "old_treasury_shares": treasury,
        "new_conversion_shares_issued": issued, "separate_financing_shares_not_conversion": 626174076,
        "theoretical_aggregate_conversion_shares": str(exact), "actual_minus_theoretical_shares": str(residual),
        "aggregate_reconciles_within_one_share": True, "individual_allocation_verified": False,
        "account_display_gap_not_wealth_zero": True, "registration_record_independently_observed": False,
    }


def parse_pdf(raw: bytes, key: str) -> dict:
    validate_pdf_shape(raw, max_bytes=MAX_BYTES)
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 12:
        raise ValueError("MERGER_PDF_PAGE_SCOPE")
    pages = [p.extract_text() or "" for p in reader.pages]
    fields = parse_halt(pages) if key == "halt" else parse_conversion(pages)
    return fields | {"pages": len(pages), "normalized_page_sha256": [
        hashlib.sha256(normalized(p).encode()).hexdigest() for p in pages]}


def exact_entitlement(old_shares: int, ratio: Decimal) -> int:
    """Only an exactly integral hypothetical entitlement; never guess a fractional allocation."""
    if (type(old_shares) is not int or not 0 < old_shares <= 10**9
            or not isinstance(ratio, Decimal) or not ratio.is_finite() or not 0 < ratio <= 100):
        raise ValueError("MERGER_ENTITLEMENT_INPUT")
    new = Decimal(old_shares) * ratio
    if new != new.to_integral_value():
        raise ValueError("MERGER_INDIVIDUAL_FRACTIONAL_ALLOCATION_UNVERIFIED")
    return int(new)


def interval_state(day: date) -> str:
    if type(day) is not date:
        raise ValueError("MERGER_DATE_REQUIRED")
    if day < HALT:
        return "BEFORE_ANNOUNCED_HALT_NOT_TRADE_PROOF"
    if day < TERMINATION:
        return "ANNOUNCED_HALT_NO_EXECUTION"
    if day < REGISTERED:
        return "DELISTED_PENDING_CONVERSION_UNPRICED"
    if day < NEW_LISTING:
        return "ISSUER_REPORTED_REGISTERED_NOT_NEW_SHARE_LISTING"
    return "ANNOUNCED_NEW_SHARE_LISTING_DATE_REACHED_NOT_TRADE_PROOF"


def mark_bridge(old_close: Decimal, new_close: Decimal) -> dict:
    if any(not isinstance(v, Decimal) or not v.is_finite() or not 0 < v <= 100000
           for v in (old_close, new_close)):
        raise ValueError("MERGER_PRICE_INVALID")
    old_units = 100  # Fixed public hypothetical, never an account input.
    new_units = exact_entitlement(old_units, RATIO)
    before = old_close * old_units
    after = new_close * new_units
    return {"hypothetical_old_shares": old_units, "theoretical_new_shares": new_units,
            "old_last_session_close_cny": str(old_close), "new_listing_day_close_cny": str(new_close),
            "old_mark_cny": str(before), "new_mark_cny": str(after),
            "gross_endpoint_mark_change_pct": str(((after/before-1)*100).quantize(Decimal("0.000001"))),
            "interim_value": None, "interim_return": None, "total_return_verified": False,
            "trade_execution_verified": False, "cash_option_and_other_flows_included": False}


def child(key: str, target: Path) -> None:
    start = datetime.now(UTC)
    try:
        doc = retrieve_pdf_bytes(DOCS[key], max_bytes=MAX_BYTES)
        write_worker_result(target, {"key": key, "url": doc.source_url, "started_at": start.isoformat(),
                                     "retrieved_at": doc.retrieved_at, "sha256": doc.sha256,
                                     "body": base64.b64encode(doc.data).decode("ascii")})
    except Exception as exc:  # noqa: BLE001 - source boundary, no raw exception content.
        write_worker_result(target, {"key": key, "error": type(exc).__name__})


def observe_doc(key: str) -> dict:
    out = {"key": key, "source_url": DOCS[key], "status": "BLOCK", "raw_body_retained": False}
    result = run_json_worker((sys.executable, "-m", "investment_evidence_engine.merger_consideration_control",
                              "--child", key), timeout_seconds=28, max_bytes=3*MAX_BYTES)
    out |= {"worker_status": result.status, "elapsed_seconds": result.elapsed_seconds}
    if result.status != "OK" or result.payload is None:
        return out
    try:
        p = result.payload
        if p["key"] != key:
            raise ValueError("MERGER_RECEIPT_KEY")
        if "error" in p:
            return out | {"error": p["error"]}
        a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        raw = base64.b64decode(p["body"], validate=True)
        if (p["url"] != DOCS[key] or a.utcoffset() is None or b.utcoffset() is None
                or not a <= b <= datetime.now(UTC) or hashlib.sha256(raw).hexdigest() != p["sha256"]):
            raise ValueError("MERGER_RECEIPT_SCOPE")
        out |= {"bytes": len(raw), "sha256": p["sha256"], "parent_rehash": "MATCH",
                "retrieved_at": b.isoformat()}
        return out | {"status": "OBSERVED", "fields": parse_pdf(raw, key)}
    except Exception as exc:  # noqa: BLE001 - parser boundary.
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"MERGER_[A-Z_]+", code) else type(exc).__name__}


def price_control() -> dict:
    # Request a finite interval containing the event and adjacent dates, not
    # just the last observed bar. Missing data never implies a zero close.
    specs = [(OLD, date(2025, 1, 20), date(2025, 3, 18), LAST_TRADE),
             (NEW, date(2025, 3, 13), date(2025, 3, 19), NEW_LISTING)]
    reports = []
    endpoints = {}
    for symbol, first, last, target in specs:
        values = []
        for provider in ("sina", "tencent"):
            frame, info = _observe(provider, symbol, first, last, "")
            receipt = {"security": "sh." + symbol, "provider_route": provider, **info,
                       "target_date": target.isoformat(), "requested_first": first.isoformat(),
                       "requested_last": last.isoformat(), "target_close": None}
            if frame is not None:
                days = list(frame["date"].dt.date)
                rows = frame.loc[frame["date"].dt.date == target, "close"]
                receipt |= {"observed_first": days[0].isoformat(), "observed_last": days[-1].isoformat(),
                            "post_announced_last_trade_rows": (
                                sum(day > LAST_TRADE for day in days) if symbol == OLD else None)}
                if len(rows) == 1:
                    v = Decimal(str(rows.iloc[0]))
                    if v.is_finite() and v > 0 and (symbol != OLD or not any(day > LAST_TRADE for day in days)):
                        receipt["target_close"] = str(v)
                        values.append(v)
            reports.append(receipt)
        if len(values) == 2 and values[0] == values[1]:
            endpoints[symbol] = values[0]
    if set(endpoints) != {OLD, NEW}:
        return {"status": "BLOCK", "observations": reports,
                "blocker": "TWO_EXACT_MATCHING_POSITIVE_ENDPOINTS_AND_OLD_DATE_SCOPE_REQUIRED"}
    return {"status": "WARN", "observations": reports, "bridge": mark_bridge(endpoints[OLD], endpoints[NEW])}


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    docs = [observe_doc(k) for k in DOCS]
    good = all(d["status"] == "OBSERVED" for d in docs)
    report = {"status": "WARN" if good else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "documents": docs, "pit_safe": False, "historical_capture_verified": False,
              "historical_first_availability_verified": False, "source_independence_verified": False,
              "corporate_action_universe_verified": False, "decision_authority": False,
              "execution_allowed": False, "research_only": True}
    if good:
        report["historical_schedule_examples"] = {
            day.isoformat(): interval_state(day) for day in (LAST_TRADE, HALT, RECORD, TERMINATION, REGISTERED, NEW_LISTING)}
        report["prices"] = price_control()
    else:
        report["prices"] = {"status": "NOT_RUN", "reason": "SOURCE_DOCUMENTS_REQUIRED"}
    print("MERGER_CONSIDERATION_CONTROL " + json.dumps(report, sort_keys=True, ensure_ascii=False), flush=True)
    return 0 if good and report["prices"]["status"] == "WARN" else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in DOCS:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
