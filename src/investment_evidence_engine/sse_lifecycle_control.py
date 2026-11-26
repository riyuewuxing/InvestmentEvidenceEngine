"""Fixed official SSE lifecycle notice controls, not a historical listing universe."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect

MAX_BYTES = 1024 * 1024
ROOT = "https://www.sse.com.cn/disclosure/announcement/listing/"
# Each notice was independently inspected on the exchange's site before the run.
# These constants are assertions, not a fallback for failed extraction.
NOTICES = {
    "ipo": ("ipo/c/c_20251023_10795665.shtml", "超颖电子电路股份有限公司", "603175",
            "2025-10-23", "2025-10-24", None, "IPO"),
    "exit": ("stock/c/c_20250714_10784844.shtml", "湖北九有投资股份有限公司", "600462",
             "2025-07-14", "2025-07-21", "2025-07-14", "DELIST"),
    "dual": ("stock/c/c_20250718_10785880.shtml", "锦州港股份有限公司", "600190",
             "2025-07-18", "2025-07-25", "2025-07-18", "DELIST"),
    "merger": ("stock/c/c_20250226_10773005.shtml", "海通证券股份有限公司", "600837",
               "2025-02-26", "2025-03-04", None, "MERGER_TERMINATION"),
}


def normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).replace("“", '"').replace("”", '"')


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def cn(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.year}年{d.month}月{d.day}日"


def parse_notice(raw: bytes, key: str) -> dict:
    if key not in NOTICES or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("SSE_LIFECYCLE_BODY_SCOPE")
    _, issuer, code, published, effective, last, kind = NOTICES[key]
    p = VisibleHTML()
    p.feed(raw.decode("utf-8-sig", errors="strict"))
    p.close()
    flat = normalized(" ".join(p.parts))
    title = "关于" + issuer + ("人民币普通股股票上市交易的公告" if kind == "IPO"
                               else "股票终止上市的公告" if kind == "MERGER_TERMINATION"
                               else "股票摘牌的公告")
    if title not in flat or published not in flat or "上海证券交易所" not in flat:
        raise ValueError("SSE_LIFECYCLE_DOCUMENT_IDENTITY")
    if kind == "IPO":
        pattern = (re.escape(issuer) + r"A股股票将在本所上市交易。[^。]{1,150}"
                   + re.escape(cn(effective)) + r"起上市交易。证券简称为[^。]{1,35},证券代码为\""
                   + code + r"\"。")
    elif kind == "MERGER_TERMINATION":
        pattern = (re.escape(issuer) + r"\(证券代码:" + code
                   + r",证券简称:[^)]{1,30}\),因被吸收合并[^。]{1,150}。[^。]{1,350}"
                   + re.escape(cn(effective)) + r"起终止其股票在本所上市交易。")
    else:
        codes = (r"A股证券简称为\"[^\"。]+\",证券代码为\"" + code
                 + r"\";B股证券简称为\"[^\"。]+\",证券代码为\"900952\""
                 if key == "dual" else r"证券简称为\"[^\"。]+\",证券代码为\"" + code + r"\"")
        pattern = (re.escape(issuer) + r"发行的股票\(" + codes
                   + r"\)已被本所决定终止上市,退市整理期于"
                   + re.escape(cn(last)) + r"届满,本所于" + re.escape(cn(effective)) + r"对其予以摘牌。")
    matches = re.findall(pattern, flat)
    if len(matches) != 1:
        raise ValueError("SSE_LIFECYCLE_EVENT_SCOPE")
    return {
        "security_id": "sh." + code, "issuer": issuer, "event_type": kind,
        "declared_notice_date": published, "announced_effective_date": effective,
        "announced_last_delisting_period_day": last,
        "related_b_share_id_excluded": "sh.900952" if key == "dual" else None,
        "notice_date_precision": "DAY_ONLY", "first_public_availability_verified": False,
        "historical_capture_verified": False, "actual_effectuation_independently_verified": False,
        "listing_universe_complete": False, "tradability_verified": False,
        "merger_consideration_verified": False,
        "normalized_event_sha256": hashlib.sha256(matches[0].encode()).hexdigest(),
    }


def scheduled_state(fields: dict, day: date) -> str:
    """Ex-post classification under the specific notice, not observed trading eligibility."""
    if type(day) is not date:
        raise ValueError("SSE_LIFECYCLE_DATE_REQUIRED")
    effective = date.fromisoformat(fields["announced_effective_date"])
    if fields["event_type"] == "IPO":
        return "PRE_ANNOUNCED_LISTING" if day < effective else "ANNOUNCED_LISTING_DATE_REACHED"
    if day >= effective:
        return "ANNOUNCED_TERMINATION_DATE_REACHED"
    last = fields["announced_last_delisting_period_day"]
    if last and day > date.fromisoformat(last):
        return "AFTER_DELISTING_PERIOD_BEFORE_REMOVAL"
    return "BEFORE_ANNOUNCED_TERMINATION_TRADABILITY_UNKNOWN"


def child(key: str, path: Path) -> None:
    url = ROOT + NOTICES[key][0]
    started = datetime.now(UTC)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            if (response.status != 200 or response.geturl() != url
                    or response.headers.get("Content-Range") is not None
                    or response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity")):
                raise ValueError("SSE_LIFECYCLE_RESPONSE_SCOPE")
            raw = response.read(MAX_BYTES + 1)
            length = response.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (length is not None and int(length) != len(raw)):
                raise ValueError("SSE_LIFECYCLE_BODY_SCOPE")
    except (OSError, ValueError) as exc:
        write_worker_result(path, {"key": key, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"key": key, "url": url, "started_at": started.isoformat(),
                               "observed_at": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe(key: str) -> dict:
    url = ROOT + NOTICES[key][0]
    out = {"key": key, "url": url, "status": "BLOCK", "raw_body_retained": False}
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.sse_lifecycle_control",
                           "--child", key), timeout_seconds=25, max_bytes=2 * MAX_BYTES)
    out |= {"worker_status": task.status, "elapsed_seconds": task.elapsed_seconds}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if p["key"] != key:
            raise ValueError("SSE_LIFECYCLE_RECEIPT_SCOPE")
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if (p["url"] != url or a.utcoffset() is None or b.utcoffset() is None
                or not a <= b <= datetime.now(UTC) or digest != p["sha256"]
                or not 0 < len(raw) <= MAX_BYTES):
            raise ValueError("SSE_LIFECYCLE_RECEIPT_SCOPE")
        out |= {"bytes": len(raw), "sha256": digest, "parent_rehash": "MATCH",
                "observed_at": b.isoformat()}
        fields = parse_notice(raw, key)
        effective = date.fromisoformat(fields["announced_effective_date"])
        days = {effective - timedelta(days=1), effective, effective + timedelta(days=1)}
        if fields["announced_last_delisting_period_day"]:
            last = date.fromisoformat(fields["announced_last_delisting_period_day"])
            days.update((last, last + timedelta(days=1)))
        return out | {"status": "OBSERVED", "fields": fields,
                      "ex_post_schedule_examples": {d.isoformat(): scheduled_state(fields, d) for d in sorted(days)}}
    except (KeyError, ValueError, TypeError, UnicodeError) as exc:
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"SSE_[A-Z_]+", code) else type(exc).__name__}


def main() -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    reports = [observe(k) for k in NOTICES]
    good = all(r["status"] == "OBSERVED" for r in reports)
    report = {"status": "WARN" if good else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "reports": reports, "pit_safe": False, "listing_universe_complete": False,
              "decision_authority": False, "execution_allowed": False, "research_only": True}
    print("SSE_LIFECYCLE_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if good else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in NOTICES:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
