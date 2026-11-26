"""Fixed public FOMC source and retrospective mainland price diagnostic.

No private subjects, credentials, portfolio, model or strategy inputs. Actual
retrieval now does not prove historic availability, a blind replay or alpha.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from investment_evidence_engine.evidence_time_guard import event_cutoff_status, market_event_reference
from investment_evidence_engine.historical_capture import PublicSecurity, observe_pair
from investment_evidence_engine.historical_reference import event_price_window_reference
from investment_evidence_engine.market_calendar import acquire_calendar, check_calendar
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
    a = PublicSecurity(symbol="600519", asset_type="STOCK")
    b = PublicSecurity(symbol="510050", asset_type="ETF")
    summary, observed = observe_pair(a,b,FIRST,LAST,providers=("sina","baostock","tencent"))
    print("PUBLIC_EVENT_PRICE_OBSERVATION " + json.dumps(summary, sort_keys=True), flush=True)
    if summary.get("status") != "OBSERVED_REFERENCE_ONLY" or summary.get("crosscheck") != "MATCH":
        return 2
    try:
        calendar = acquire_calendar(FIRST,LAST)
        sessions = check_calendar(calendar,first=FIRST,last=LAST,cutoff=datetime.now(SH))
        selected = tuple(next(s for s in observed if s.subject_id == subject.symbol) for subject in (a,b))
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
                warnings=warnings+["RAW_PRICE_ONLY; NO CAUSAL OR EXECUTION INFERENCE"])
            print("PUBLIC_EVENT_DIAGNOSTIC " + json.dumps(diagnostic,sort_keys=True,allow_nan=False),flush=True)
    except Exception as exc:
        print("PUBLIC_EVENT_DIAGNOSTIC_BLOCKED " + json.dumps({"error_type":type(exc).__name__,
            "decision_authority":False}),flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
