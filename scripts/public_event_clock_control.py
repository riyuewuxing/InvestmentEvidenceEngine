"""Fixed public FOMC source and retrospective mainland price diagnostic.

No private subjects, credentials, portfolio, model or strategy inputs. Actual
retrieval now does not prove historic availability, a blind replay or alpha.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from datetime import UTC, date, datetime, time
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from investment_evidence_engine.evidence_time_guard import (
    event_cutoff_status,
    market_event_reference,
)
from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair
from investment_evidence_engine.historical_receipt import (
    HistoricalCaptureFailure,
    HistoricalReceipt,
    load_receipt,
    persist_receipt,
)
from investment_evidence_engine.historical_reference import event_price_window_reference
from investment_evidence_engine.holding_risk import CashDistribution, CashDistributionInputs
from investment_evidence_engine.market_calendar import acquire_calendar, check_calendar
from investment_evidence_engine.official_pdf_transport import retrieve_pdf_bytes
from investment_evidence_engine.sources import fetch_official_url

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
FIRST, LAST = date(2025, 7, 1), date(2025, 12, 19)
EVENTS = (
    ("https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm",
     date(2025, 9, 17), "EDT"),
    ("https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm",
     date(2025, 12, 10), "EST"),
)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read_statement(url, day, expected_zone):
    result = fetch_official_url(url, timeout=8.0)
    observed = datetime.now(UTC)
    if result.url != url or "text/html" not in result.content_type.lower():
        raise ValueError("FED_STATEMENT_IDENTITY")
    parser = VisibleText()
    parser.feed(result.text)
    text = " ".join(" ".join(parser.parts).split())
    label = f"{day.strftime('%B')} {day.day}, {day.year}"
    markers = re.findall(r"For release at ([0-9]+:[0-9]+) p\.m\. (EDT|EST)", text)
    if (label not in text or "Federal Reserve issues FOMC statement" not in text
            or markers != [("2:00", expected_zone)]):
        raise ValueError("FED_RELEASE_IDENTITY_OR_CLOCK")
    declared = datetime.combine(day, time(14), tzinfo=NY)
    if declared.tzname() != expected_zone:
        raise ValueError("FED_RELEASE_ZONE_MISMATCH")
    # Deliberately not a source-available_at claim: the current response was
    # captured now. A 2025 cutoff cannot admit the 2026 acquisition.
    before = declared.replace(microsecond=0)
    assert event_cutoff_status(declared.isoformat(), observed.isoformat(), before.isoformat()) == "AFTER_CUTOFF"
    return {"source_url": url, "source_sha256": result.content_sha256,
        "source_content_type": result.content_type, "declared_release_at": declared.isoformat(),
        "shanghai_release_at": declared.astimezone(SH).isoformat(), "retrieved_at": observed.isoformat(),
        "actual_historical_availability_verified": False, "historical_retrieval_verified": False,
        "raw_body_retained": False, "decision_authority": False}



DIVIDEND_URL = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-12-10/510050_20251210_C3NC.pdf"


def read_benchmark_dividend():
    doc = retrieve_pdf_bytes(DIVIDEND_URL)
    reader = PdfReader(io.BytesIO(doc.data), strict=True)
    if reader.is_encrypted or len(reader.pages) != 2:
        raise ValueError("DIVIDEND_FIXED_DOCUMENT_STRUCTURE")
    first = "".join(unicodedata.normalize("NFKC", reader.pages[0].extract_text() or "").split())
    markers = (
        r"基金主代码[:：]?510050(?!\d)",
        r"公告送出日期[:：]?2025年12月10日",
        r"本次分红方案\(单位[:：]元/10份基金份额\)0\.80(?!\d)",
        r"权益登记日[:：]?2025年12月16日",
        r"除息日[:：]?2025年12月17日",
        r"现金红利发放日[:：]?2025年12月22日",
    )
    if not all(re.search(marker, first) for marker in markers):
        raise ValueError("DIVIDEND_FIXED_DOCUMENT_FIELDS")
    return {"source_url": DIVIDEND_URL, "source_sha256": doc.sha256,
        "source_bytes": len(doc.data), "retrieved_at": doc.retrieved_at,
        "parser": "pypdf", "parser_version": version("pypdf"), "page_count": len(reader.pages),
        "subject_id": "510050", "announcement_date": "2025-12-10",
        "record_date": "2025-12-16", "ex_date": "2025-12-17",
        "scheduled_pay_date": "2025-12-22", "gross_cash_per_unit_cny": 0.08,
        "payment_verified": False, "historical_availability_verified": False,
        "corporate_action_universe_verified": False, "raw_body_retained": False,
        "decision_authority": False}


def add_dividend_sensitivity(diagnostic, benchmark, dividend):
    closes = {row.session.isoformat(): row.close for row in benchmark.closes}
    ex = dividend["ex_date"]
    prior_ex = dividend["record_date"]
    for row in diagnostic["windows"]:
        included = diagnostic["prior_close_session"] <= prior_ex < ex <= row["end_session"]
        row["listed_benchmark_ex_date_in_window"] = included
        if included:
            cash = dividend["gross_cash_per_unit_cny"]
            entry_close = closes[diagnostic["prior_close_session"]]
            prior_ex_close = closes[prior_ex]
            exit_close = closes[row["end_session"]]
            gross = ((exit_close+cash)/entry_close-1)*100
            row["conditional_benchmark_gross_receivable_return_pct"] = gross
            row["conditional_benchmark_receivable_increment_pp"] = cash/entry_close*100
            row["conditional_car_with_listed_ex_date_only_pct"] = (
                row["market_model_arithmetic_car_pct"] - diagnostic["beta"]*cash/prior_ex_close*100)
            row["cash_receivable_basis"] = (
                "FIXED_UNITS_GROSS_LISTED_ENTITLEMENT_NOT_PAYMENT_OR_EXHAUSTIVE_TOTAL_RETURN")
    diagnostic["listed_dividend_source_sha256"] = dividend["source_sha256"]
    diagnostic["listed_dividend_payment_verified"] = False


def main():
    receipts = []
    for url, day, zone in EVENTS:
        try:
            receipt = read_statement(url, day, zone)
            print("PUBLIC_FED_CLOCK_RECEIPT " + json.dumps(receipt, sort_keys=True), flush=True)
            receipts.append(receipt)
        except Exception as exc:
            print("PUBLIC_FED_CLOCK_BLOCKED " + json.dumps({"source_url": url,
                "error_type": type(exc).__name__, "decision_authority": False}), flush=True)
    if len(receipts) != len(EVENTS):
        return 2
    try:
        dividend = read_benchmark_dividend()
        print("PUBLIC_EVENT_DIVIDEND_RECEIPT " + json.dumps(dividend, sort_keys=True), flush=True)
    except Exception as exc:
        print("PUBLIC_EVENT_DIVIDEND_BLOCKED " + json.dumps({"error_type": type(exc).__name__}), flush=True)
        return 2
    a = PublicSecurity(symbol="600519", asset_type="STOCK")
    b = PublicSecurity(symbol="510050", asset_type="ETF")
    summary, observed = observe_pair(a,b,FIRST,LAST,providers=("sina","baostock","tencent"))
    print("PUBLIC_EVENT_PRICE_OBSERVATION " + json.dumps(summary, sort_keys=True), flush=True)
    if summary.get("status") != "OBSERVED_REFERENCE_ONLY" or summary.get("crosscheck") != "MATCH":
        return 2
    try:
        calendar = acquire_calendar(FIRST,LAST)
        sessions = check_calendar(calendar,first=FIRST,last=LAST,cutoff=datetime.now(SH))
        actual = HistoricalReceipt(schema_version="2",candidate=a,alternative=b,
            first_requested=FIRST,last_completed=LAST,observed_at=datetime.now(SH),
            akshare_version=version("akshare"),attempted_providers=tuple(summary["attempted_providers"]),
            failures=tuple(HistoricalCaptureFailure.model_validate(f) for f in summary["failures"]),
            series=observed,calendar=calendar,distributions=CashDistributionInputs(events=(
                CashDistribution(subject_id="510050",disclosed_date=date(2025,12,10),
                    ex_date=date(2025,12,17),gross_cash_per_unit_cny=dividend["gross_cash_per_unit_cny"],
                    source_locator=DIVIDEND_URL+"#page=1"),)))
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            digest, computed = persist_receipt(folder,actual)
            loaded = load_receipt(folder,a,b,LAST,now=datetime.now(SH))
            raw = (folder/(digest+".json")).read_bytes()
            if (hashlib.sha256(raw).hexdigest() != digest
                    or loaded["normalized_observation_sha256"] != digest
                    or loaded["reference"] != computed["reference"]
                    or loaded["holding_reference"]["status"] != "HISTORICAL_HOLDING_REFERENCE_ONLY"):
                raise ValueError("PUBLIC_EVENT_RECEIPT_REHASH_OR_COVERAGE")
            actual = HistoricalReceipt.model_validate_json(raw)
            print("PUBLIC_EVENT_NORMALIZED_RECEIPT " + json.dumps({
                "sha256":digest,"bytes":len(raw),"rehash":True,"session_count":len(sessions),
                "provider_count":len(actual.series),"akshare_version":actual.akshare_version,
                "series_sha256":{x.subject_id+":"+x.source_label:
                    hashlib.sha256(x.model_dump_json().encode()).hexdigest() for x in actual.series},
                "calendar_sha256":hashlib.sha256(actual.calendar.model_dump_json().encode()).hexdigest(),
                "raw_provider_bytes_retained":False,"durable_raw_archive":False,
                "decision_authority":False}, sort_keys=True),flush=True)
        selected = tuple(next(s for s in actual.series if s.subject_id == subject.symbol) for subject in (a,b))
        for receipt in receipts:
            published = receipt["declared_release_at"]
            ref, rule, warnings = market_event_reference(published,sessions)
            if ref is None or rule != "PRE_CLOSE_SAME_TRADING_DAY":
                raise ValueError("FED_MAINLAND_CLOCK_REFERENCE")
            release_local = datetime.fromisoformat(ref)
            if release_local.time() >= time(9,15):
                raise ValueError("FED_NOT_BEFORE_AUCTION")
            diagnostic = event_price_window_reference(*selected,sessions=sessions,
                                                       event_session=release_local.date())
            diagnostic.update(source_url=receipt["source_url"],source_sha256=receipt["source_sha256"],
                declared_release_at=published,calendar_observed_at=calendar.observed_at.isoformat(),
                calendar_match="BAOSTOCK_VS_REVIEWED_SSE_SZSE_ANNUAL_SCHEDULE",
                provider_crosscheck="MATCH_WITHIN_EXISTING_TOLERANCE",
                corporate_actions_not_exhaustive=True, before_auction_reference=True,
                historical_retrieval_verified=False, historical_blind_replay=False,
                normalized_receipt_sha256=digest,
                warnings=warnings+["RAW_PRICE_ONLY; NO CAUSAL OR EXECUTION INFERENCE"])
            add_dividend_sensitivity(diagnostic, selected[1], dividend)
            print("PUBLIC_EVENT_DIAGNOSTIC " + json.dumps(diagnostic,sort_keys=True,allow_nan=False),flush=True)
    except Exception as exc:
        print("PUBLIC_EVENT_DIAGNOSTIC_BLOCKED " + json.dumps({"error_type":type(exc).__name__,
            "decision_authority":False}),flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
