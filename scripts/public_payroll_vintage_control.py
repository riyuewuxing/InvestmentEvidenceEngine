"""Fixed official BLS/ALFRED vintage control, not historical capture or forecast.

No credentials, private symbols, account, strategy or raw provider body retained.
ALFRED's graph CSV transport is an observed public endpoint, not a guaranteed API.
The exact requested header AND independently reviewed BLS revision chain matter.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from investment_evidence_engine.evidence_time_guard import source_visible
from investment_evidence_engine.sources import fetch_official_url

NY = ZoneInfo("America/New_York")
SH = ZoneInfo("Asia/Shanghai")
VINTAGES = (
    (date(2025,9,5), "09052025", "AUGUST", 22000),
    (date(2025,11,20), "11202025", "SEPTEMBER", -4000),
    (date(2025,12,16), "12162025", "NOVEMBER", -26000),
)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def bls_fields(html, release_day, report_month):
    parser = VisibleText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    identity = f"8:30 a.m. (ET) {release_day.strftime('%A, %B')} {release_day.day}, {release_day.year}"
    if identity not in text or not re.search(
            rf"THE EMPLOYMENT SITUATION\s*[-–—]+\s*{report_month} 2025", text):
        raise ValueError("BLS_RELEASE_IDENTITY")
    if report_month == "AUGUST":
        hits = re.findall(r"Total nonfarm payroll employment changed little in August \(\+([0-9,]+)\)", text)
        if not hits or len(set(hits)) != 1:
            raise ValueError("BLS_INITIAL_PRINT_AMBIGUOUS")
        value = int(hits[0].replace(",", ""))
        previous = None
    else:
        hits = re.findall(
            r"(?:The change in total nonfarm payroll employment|the change) for August was revised "
            r"(down|up) by ([0-9,]+), from ([+-][0-9,]+) to ([+-][0-9,]+)", text)
        if len(hits) != 1:
            raise ValueError("BLS_REVISION_AMBIGUOUS")
        direction, delta, old, new = hits[0]
        previous, value = int(old.replace(",","")), int(new.replace(",",""))
        amount = int(delta.replace(",","")) * (-1 if direction == "down" else 1)
        if value - previous != amount:
            raise ValueError("BLS_REVISION_ARITHMETIC_CONFLICT")
    return {"august_change_jobs": value, "previous_august_change_jobs": previous,
            "declared_release_at": datetime.combine(release_day,time(8,30),tzinfo=NY).isoformat(),
            "original_october3_schedule_observed": (
                "scheduled to be released on Friday, October 3, 2025" in text),
            "october_release_not_published_observed": (
                "will not publish an October 2025 Employment Situation news release" in text)}


def alfred_fields(csv_text, vintage_day):
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    header = f"PAYEMS_{vintage_day:%Y%m%d}"
    if len(rows) != 3 or rows[0] not in (["observation_date",header],["DATE",header]):
        raise ValueError("ALFRED_VINTAGE_HEADER_OR_COVERAGE")
    expected = ["2025-07-01","2025-08-01"]
    if any(len(row) != 2 for row in rows[1:]) or [row[0] for row in rows[1:]] != expected:
        raise ValueError("ALFRED_OBSERVATION_MONTH_MISMATCH")
    values = [Decimal(row[1]) for row in rows[1:]]
    if any(not v.is_finite() or not Decimal(100000) < v < Decimal(200000) for v in values):
        raise ValueError("ALFRED_PAYROLL_LEVEL_INVALID")
    diff = (values[1]-values[0])*1000
    if diff != diff.to_integral_value():
        raise ValueError("ALFRED_JOBS_UNIT_INVALID")
    return {"vintage_date": vintage_day.isoformat(), "column":header,
            "level_thousands": dict(zip(expected, (str(v) for v in values))),
            "august_change_jobs": int(diff)}


def receipt(url, fields, result, observed):
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"),allow_nan=False).encode()
    return fields | {"source_url":url, "source_sha256":result.content_sha256,
        "normalized_fields_sha256":hashlib.sha256(payload).hexdigest(),
        "retrieved_at":observed.isoformat(), "raw_body_retained":False,
        "actual_historical_capture_verified":False, "decision_authority":False}


def main():
    report = []
    for day, suffix, month, expected in VINTAGES:
        row = {"vintage_date":day.isoformat(), "reviewed_bls_change_jobs":expected}
        bls_url = f"https://www.bls.gov/news.release/archives/empsit_{suffix}.htm"
        alfred_url = ("https://alfred.stlouisfed.org/graph/alfredgraph.csv?"
                      f"id=PAYEMS&vintage_date={day.isoformat()}&cosd=2025-07-01&coed=2025-08-01")
        for source, url, parser in (
                ("bls",bls_url,lambda text:bls_fields(text,day,month)),
                ("alfred",alfred_url,lambda text:alfred_fields(text,day))):
            try:
                result = fetch_official_url(url,timeout=8.)
                observed = datetime.now(UTC)
                if result.url != url:
                    raise ValueError("SOURCE_ROUTE_CHANGED")
                if source == "bls" and "text/html" not in result.content_type.lower():
                    raise ValueError("BLS_CONTENT_TYPE")
                if source == "alfred" and "html" in result.content_type.lower():
                    raise ValueError("ALFRED_CONTENT_TYPE")
                fields = parser(result.text)
                if fields["august_change_jobs"] != expected:
                    raise ValueError("REVIEWED_BLS_VALUE_CONFLICT")
                row[source] = receipt(url,fields,result,observed)
                if source == "bls":
                    release = datetime.fromisoformat(fields["declared_release_at"])
                    row[source]["shanghai_declared_release_at"] = release.astimezone(SH).isoformat()
                    # A release timestamp cannot be used as actual acquisition time.
                    assert not source_visible(available_at=release,retrieved_at=observed,
                                              published_at=release,cutoff=release)
                print("PUBLIC_PAYROLL_VINTAGE " + json.dumps(
                    {"source":source,"status":"OBSERVED","data":row[source]},sort_keys=True),flush=True)
            except Exception as exc:
                row[source] = {"status":"BLOCKED","error_type":type(exc).__name__}
                print("PUBLIC_PAYROLL_SOURCE_BLOCKED " + json.dumps(
                    {"source":source,"url":url,"error_type":type(exc).__name__},sort_keys=True),flush=True)
        report.append(row)
    bls_match = all("source_sha256" in row["bls"] for row in report)
    alfred_match = all("source_sha256" in row["alfred"] for row in report)
    if bls_match:
        bls_match = (report[0]["bls"]["previous_august_change_jobs"] is None and
            report[1]["bls"]["previous_august_change_jobs"] == report[0]["bls"]["august_change_jobs"] and
            report[2]["bls"]["previous_august_change_jobs"] == report[1]["bls"]["august_change_jobs"] and
            report[0]["bls"]["original_october3_schedule_observed"] and
            report[1]["bls"]["october_release_not_published_observed"])
    status = "MATCH" if bls_match and alfred_match else "PARTIAL_OR_BLOCKED"
    print("PUBLIC_PAYROLL_VINTAGE_SUMMARY " + json.dumps({
        "status":status,"bls_archive_chain_matched":bls_match,
        "alfred_vintages_matched":alfred_match,
        "bls_alfred_share_original_upstream":True,
        "independent_measurement_sources_verified":False,
        "historical_intraday_alfred_availability_verified":False,
        "historical_capture_verified":False,"decision_authority":False,
        "execution_allowed":False},sort_keys=True),flush=True)
    return 0 if status == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
