"""Fixed public transfer-event evidence; no portfolio or trading admission."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from pypdf import PdfReader

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect
from .official_pdf_transport import validate_pdf_shape
from .sse_lifecycle_control import VisibleHTML, normalized

MAX_BYTES = 4 * 1024 * 1024
PDF_MAX_BYTES = 8 * 1024 * 1024
PDF_KEYS = ("sponsor", "risk")
SOURCES = {
    "broker_a": "https://www.citics.com/newsite/tzgg/ywgg/202508/t20250807_1200880.html",
    "broker_b": "https://www.citics.com/newsite/tzgg/ywgg/202508/t20250807_1200881.html",
    "sponsor": "https://www.nesc.cn/plat_files/upload/png_upload/20250807/202508071754544960221.pdf",
    "risk": ("https://notice.10jqka.com.cn/api/pdf/6ae242bad6e56642_1758072001/"
             "%E9%94%A6%E5%B7%9E%E6%B8%AFA3%3A%E6%8A%95%E8%B5%84%E9%A3%8E%E9%99%A9"
             "%E5%88%86%E6%9E%90%E6%8A%A5%E5%91%8A.pdf"),
    "annual": ("https://vip.stock.finance.sina.com.cn/corp/view/"
               "vCB_AllBulletinDetail.php?id=12260296&stockid=600190"),
}
MAPPING = {"A": ("600190", "400280"), "B": ("900952", "420280")}
REMOVAL = "2025-07-25"
LAST = "2025-07-18"
ENTRY = "2025-09-17"
EXPECTED = "2025-09-26"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def parse_text(key: str, value: str) -> dict:
    text = normalized(value)
    require("锦州港股份有限公司" in text, "TRANSFER_WRONG_ISSUER")
    if key in ("broker_a", "broker_b"):
        share_class = key[-1].upper()
        old, new = MAPPING[share_class]
        pattern = (rf"锦州港股份有限公司{share_class}股\(证券简称:[^,()]+,证券代码:{old},"
                   rf"确权证券代码:{new}\)于2025年7月25日在上交所摘牌并终止上市,"
                   r"预计将于2025年9月26日前在退市板块挂牌转让。")
        require(len(re.findall(pattern, text)) == 1, "TRANSFER_BROKER_MAPPING")
        require("2025-08-07" in text and "2025年8月15日" in text,
                "TRANSFER_BROKER_DATE")
        return {"share_class": share_class, "former_code": old, "confirmation_code": new,
                "reported_removal": REMOVAL, "expected_entry_by": EXPECTED,
                "displayed_notice_day": "2025-08-07",
                "actual_board_entry": None, "account_confirmation_verified": False}
    if key == "sponsor":
        require("股份确权公告" in text and "山西证券" in text
                and all(code in text for pair in MAPPING.values() for code in pair),
                "TRANSFER_SPONSOR_IDENTITY")
        require(re.search(r"退出登记[^。]{0,100}2025年7月28日办理完毕", text) is not None,
                "TRANSFER_EXIT_REGISTRATION")
        require("2025年9月26日前" in text, "TRANSFER_SPONSOR_EXPECTED_DATE")
        return {"reported_market_exit_registration": "2025-07-28",
                "expected_entry_by": EXPECTED, "account_confirmation_verified": False}
    if key == "risk":
        require("投资风险分析" in text and "山西证券" in text
                and re.search(r"2025年9月17日起[^。]{0,230}挂牌转让", text) is not None,
                "TRANSFER_RISK_ENTRY_ANNOUNCEMENT")
        shares = {}
        a_start = "截至2025年9月3日,公司A股股本结构如下"
        b_start = "截至2025年9月3日,公司B股股本结构如下"
        require(text.count(a_start) == text.count(b_start) == 1
                and text.index(a_start) < text.index(b_start), "TRANSFER_RISK_CLASS_SCOPE")
        a_section, b_section = text.split(a_start, 1)[1].split(b_start, 1)
        b_section = b_section.split("挂牌前的前十名股东持股情况", 1)[0]
        for share_class, section in (("A", a_section), ("B", b_section)):
            matches = re.findall(r"退市板块待确认股份([\d,]+)总股本([\d,]+)", section[:1800])
            require(len(matches) == 1, "TRANSFER_RISK_PENDING_SHARES")
            pending, total = (int(v.replace(",", "")) for v in matches[0])
            require(0 < pending <= total, "TRANSFER_RISK_INVALID_COUNTS")
            shares[share_class] = {"pending_confirmation": pending, "total": total}
        return {"announced_entry_from": ENTRY, "share_counts_as_of": "2025-09-03",
                "share_counts": shares, "account_confirmation_verified": False}
    if key == "annual":
        require("2025年年度报告" in text
                and "锦州港A3/锦州港B3证券代码400280/420280" in text
                and "进入退市板块时间2025年9月17日" in text,
                "TRANSFER_ANNUAL_ENTRY")
        require("每周交易三次" in text and "集合竞价交易" in text,
                "TRANSFER_ANNUAL_MARKET_MODE")
        return {"issuer_retrospective_entry": ENTRY, "report_period": "2025",
                "codes": ["400280", "420280"], "reported_weekly_frequency": 3,
                "reported_market_mode": "CALL_AUCTION",
                "historical_availability_verified": False}
    raise ValueError("TRANSFER_UNKNOWN_SOURCE")


def event_state(day: date, *, entry_verified: bool) -> str:
    """Retrospective venue classification, never an account/price inference."""
    if day <= date.fromisoformat(LAST):
        return "BEFORE_END_OF_DELISTING_PERIOD"
    if day < date.fromisoformat(REMOVAL):
        return "AFTER_DELISTING_PERIOD_BEFORE_REMOVAL"
    if not entry_verified:
        return "OLD_VENUE_REMOVED_NEW_VENUE_UNVERIFIED"
    if day < date.fromisoformat(ENTRY):
        return "OLD_VENUE_REMOVED_BEFORE_REPORTED_NEW_ENTRY"
    return "NEW_VENUE_REPORTED_ACCOUNT_TRADABILITY_UNVERIFIED"


def parse_body(key: str, body: bytes) -> dict:
    limit = PDF_MAX_BYTES if key in PDF_KEYS else MAX_BYTES
    require(0 < len(body) <= limit, "TRANSFER_BODY_LIMIT")
    if key in PDF_KEYS:
        validate_pdf_shape(body, max_bytes=limit)
        pdf = PdfReader(io.BytesIO(body), strict=True)
        require(not pdf.is_encrypted and 1 <= len(pdf.pages) <= 250,
                "TRANSFER_PDF_PAGE_LIMIT")
        value = "\n".join(page.extract_text() or "" for page in pdf.pages[:4])
    else:
        parser = VisibleHTML()
        try:
            decoded = body.decode("utf-8-sig", errors="strict")
        except UnicodeError:
            if key != "annual":
                raise
            decoded = body.decode("gb18030", errors="strict")
        parser.feed(decoded)
        parser.close()
        value = " ".join(parser.parts)
    return parse_text(key, value)


def pdf_declared_length(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal() or len(value) > 12:
        return None
    n = int(value)
    # Only new evidence of the previous 4 MiB limit being insufficient
    # authorizes a single bounded GET; ambiguous metadata does not.
    return n if MAX_BYTES < n <= PDF_MAX_BYTES else None


def child(key: str, path: Path, *, size_probe: bool = False) -> None:
    url = SOURCES[key]
    started = datetime.now(UTC)
    metadata = {}
    limit = MAX_BYTES
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
        opener = build_opener(NoRedirect())
        if size_probe:
            require(key in PDF_KEYS, "TRANSFER_PDF_PROBE_SCOPE")
            with opener.open(Request(url, headers=headers, method="HEAD"), timeout=8) as head:
                length = head.headers.get("Content-Length")
                scope_ok = (head.status == 200 and head.geturl() == url
                            and head.headers.get("Content-Range") is None
                            and head.headers.get("Content-Encoding", "identity").lower() in ("", "identity"))
                declared = pdf_declared_length(length) if scope_ok else None
                metadata = {"head_status": head.status,
                            "head_content_length": length if length is not None and length.isdecimal()
                            and len(length) <= 12 else None,
                            "head_observed_at": datetime.now(UTC).isoformat(),
                            "larger_get_authorized": declared is not None}
            if declared is None:
                write_worker_result(path, {"key": key, "error": "TRANSFER_NO_NEW_SIZE_EVIDENCE", **metadata})
                return
            limit = declared
        request = Request(url, headers=headers)
        with opener.open(request, timeout=12) as response:
            require(response.status == 200 and response.geturl() == url
                    and response.headers.get("Content-Range") is None
                    and response.headers.get("Content-Encoding", "identity").lower() in ("", "identity"),
                    "TRANSFER_HTTP_SCOPE")
            length = response.headers.get("Content-Length")
            if size_probe:
                require(length is not None and pdf_declared_length(length) == limit,
                        "TRANSFER_GET_LENGTH_CHANGED")
            body = response.read(limit + 1)
            require(0 < len(body) <= limit and (length is None or int(length) == len(body))
                    and (not size_probe or len(body) == limit), "TRANSFER_BODY_LIMIT")
        result = {"key": key, "url": url, "started_at": started.isoformat(), **metadata,
                  "observed_at": datetime.now(UTC).isoformat(),
                  "sha256": hashlib.sha256(body).hexdigest(),
                  "body": base64.b64encode(body).decode("ascii")}
        try:
            result["fields"] = parse_body(key, body)
        except Exception as exc:
            reason = str(exc)
            result["parse_error"] = (reason if re.fullmatch(r"TRANSFER_[A-Z_]+", reason)
                                     else type(exc).__name__)
    except Exception as exc:
        reason = str(exc)
        result = {"key": key, "error": reason if re.fullmatch(r"TRANSFER_[A-Z_]+", reason)
                  else type(exc).__name__, **metadata,
                  "http_status": exc.code if isinstance(exc, HTTPError) else None}
    write_worker_result(path, result)


def observe(key: str, *, size_probe: bool = False) -> dict:
    url = SOURCES[key]
    out = {"key": key, "url": url, "status": "BLOCK", "raw_body_retained": False}
    worker = run_json_worker((sys.executable, "-m", "investment_evidence_engine.transfer_control",
                              "--pdf-child" if size_probe else "--child", key),
                             timeout_seconds=40 if size_probe else 25,
                             max_bytes=(12 if size_probe else 6) * 1024 * 1024)
    out |= {"worker_status": worker.status, "elapsed_seconds": worker.elapsed_seconds}
    if worker.status != "OK" or worker.payload is None:
        return out
    try:
        p = worker.payload
        require(p["key"] == key, "TRANSFER_RECEIPT_KEY")
        if size_probe:
            out |= {k: p[k] for k in ("head_status", "head_content_length", "head_observed_at",
                                     "larger_get_authorized") if k in p}
        if "error" in p:
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        a, b = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["observed_at"])
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        limit = PDF_MAX_BYTES if size_probe else MAX_BYTES
        require(p["url"] == url and a.utcoffset() is not None and b.utcoffset() is not None
                and a <= b <= datetime.now(UTC) and digest == p["sha256"]
                and 0 < len(raw) <= limit, "TRANSFER_RECEIPT_SCOPE")
        if size_probe:
            require(p.get("larger_get_authorized") is True
                    and pdf_declared_length(p.get("head_content_length")) == len(raw),
                    "TRANSFER_RECEIPT_HEAD_SCOPE")
        evidence = out | {"bytes": len(raw), "sha256": digest,
                          "parent_rehash": "MATCH", "observed_at": b.isoformat()}
        if "parse_error" in p:
            return evidence | {"parse_error": p["parse_error"]}
        require(isinstance(p.get("fields"), dict), "TRANSFER_RECEIPT_FIELDS")
        return evidence | {"status": "OBSERVED", "fields": p["fields"]}
    except (KeyError, TypeError, ValueError) as exc:
        reason = str(exc)
        return out | {"error": reason if re.fullmatch(r"TRANSFER_[A-Z_]+", reason)
                      else type(exc).__name__}


def main(*, size_probe: bool = False) -> int:
    if os.environ["GITHUB_REPOSITORY"] != "riyuewuxing/InvestmentEvidenceEngine":
        raise SystemExit("public repository required")
    if size_probe:
        reports = [observe(key, size_probe=True) for key in PDF_KEYS]
        complete = all(r["status"] == "OBSERVED" for r in reports)
        report = {"status": "WARN" if complete else "BLOCK",
                  "executor_commit": os.environ["GITHUB_SHA"], "reports": reports,
                  "pit_safe": False, "decision_authority": False, "execution_allowed": False,
                  "research_only": True}
        print("TRANSFER_PDF_SIZE_PROBE " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        return 0 if complete else 2
    reports = [observe(key) for key in SOURCES]
    observed = {row["key"] for row in reports if row["status"] == "OBSERVED"}
    complete = observed == set(SOURCES)
    entry_verified = "annual" in observed
    days = (LAST, "2025-07-19", REMOVAL, "2025-07-28", "2025-09-16", ENTRY, EXPECTED)
    report = {"status": "WARN" if complete else "BLOCK", "executor_commit": os.environ["GITHUB_SHA"],
              "reports": reports, "retrospective_states": {
                  day: event_state(date.fromisoformat(day), entry_verified=entry_verified) for day in days},
              "pit_safe": False, "listing_universe_complete": False,
              "account_tradability_verified": False, "share_conversion_ratio_verified": False,
              "mark_to_market_verified": False, "decision_authority": False,
              "execution_allowed": False, "research_only": True}
    print("TRANSFER_CONTROL " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if complete else 2


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child" and sys.argv[2] in SOURCES:
        child(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--pdf-child" and sys.argv[2] in PDF_KEYS:
        child(sys.argv[2], Path(sys.argv[3]), size_probe=True)
    elif len(sys.argv) == 2 and sys.argv[1] == "--pdf-size-probe":
        raise SystemExit(main(size_probe=True))
    elif len(sys.argv) == 1:
        raise SystemExit(main())
    else:
        raise SystemExit(2)
