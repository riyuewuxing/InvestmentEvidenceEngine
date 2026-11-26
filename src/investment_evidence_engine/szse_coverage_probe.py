"""Bounded SZSE official aggregate observation and alternate HTTPS route probe.

A company count from a previous month is not the current A-share code universe.
Never use HTTP, paginate an unverified endpoint, or infer coverage by count.
"""
from __future__ import annotations

import base64
import hashlib
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .bounded_worker import run_json_worker, write_worker_result
from .issuer_disclosure_index import NoRedirect

MONTHLY = "https://docs.static.szse.cn/www/market/periodical/month/W020261103554316222775.html"
PAGE = ("https://www.szse.cn/api/report/ShowReport/data?"
        "SHOWTYPE=JSON&CATALOGID=1110&TABKEY=tab1&PAGENO=1")
URLS = {"monthly": MONTHLY, "page": PAGE}
MAX_BYTES = 512 * 1024


class TableText(HTMLParser):
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


def monthly_fields(raw: bytes, charset: str) -> dict:
    if charset.lower() not in {"utf-8", "gb18030", "gbk", "gb2312"}:
        raise ValueError("SZSE_MONTHLY_CHARSET")
    parser = TableText()
    parser.feed(raw.decode(charset, errors="strict"))
    text = " ".join(" ".join(parser.parts).split())
    if not re.search(r"MARKET\s+OVERVIEW\s*[-–—]?\s*\(2026[.]10\)", text):
        raise ValueError("SZSE_MONTHLY_IDENTITY")
    match = re.findall(
        r"上市公司数目\s*No[.]\s*of\s+Listed\s+Companies\s+([0-9,]+)\s*"
        r"创业板\s*ChiNext\s+([0-9,]+)\s*上市证券数目", text, re.I)
    if len(match) != 1:
        raise ValueError("SZSE_MONTHLY_COMPANY_ROW")
    total, gem = (int(x.replace(",", "")) for x in match[0])
    if not 0 < gem < total < 10000:
        raise ValueError("SZSE_MONTHLY_COUNT_RANGE")
    return {"period": "2026-10", "listed_company_count": total,
            "chinext_company_count": gem, "non_chinext_company_count_derived": total-gem,
            "unit": "COMPANIES_NOT_A_SHARE_IDENTIFIERS",
            "current_code_universe_verified": False, "pit_safe": False}


def page_fields(raw: bytes) -> dict:
    # Top-level array is documented by a third-party implementation. Reject
    # any other shape rather than guess at undocumented exchange fields.
    from .snapshot_integrity import strict_json_loads

    body = strict_json_loads(raw)
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
        raise ValueError("SZSE_PAGE_SCHEMA")
    page = body[0]
    records, metadata = page.get("data"), page.get("metadata")
    if not isinstance(records, list) or not 0 < len(records) <= 100 or not isinstance(metadata, dict):
        raise ValueError("SZSE_PAGE_COVERAGE")
    if not all(isinstance(row, dict) and isinstance(row.get("agdm"), str)
               and re.fullmatch(r"[0-9]{6}", row["agdm"]) for row in records):
        raise ValueError("SZSE_PAGE_CODE_SCHEMA")
    if len({row["agdm"] for row in records}) != len(records):
        raise ValueError("SZSE_PAGE_DUPLICATE")
    return {"observed_first_page_rows": len(records),
            "metadata_keys": sorted(str(k)[:80] for k in metadata)[:40],
            "current_code_universe_verified": False, "pit_safe": False}


def _child(kind: str, path: Path) -> None:
    url = URLS[kind]
    started = datetime.now(UTC)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity",
                                "Referer": "https://www.szse.cn/market/product/stock/list/"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("SZSE_RESPONSE_SCOPE")
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("SZSE_ENCODING")
            if response.headers.get("Content-Range") is not None:
                raise ValueError("SZSE_PARTIAL_RESPONSE")
            raw = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            declared = response.headers.get("Content-Length")
            if not 0 < len(raw) <= MAX_BYTES or (declared is not None and int(declared) != len(raw)):
                raise ValueError("SZSE_BODY_SIZE")
    except Exception as exc:  # noqa: BLE001
        write_worker_result(path, {"kind": kind, "error": type(exc).__name__,
                                   "http_status": exc.code if isinstance(exc, HTTPError) else None})
        return
    write_worker_result(path, {"kind": kind, "url": url, "charset": charset,
                               "started_at": started.isoformat(),
                               "retrieved_at": datetime.now(UTC).isoformat(),
                               "sha256": hashlib.sha256(raw).hexdigest(),
                               "body": base64.b64encode(raw).decode("ascii")})


def observe(kind: str) -> dict:
    task = run_json_worker((sys.executable, "-m", "investment_evidence_engine.szse_coverage_probe",
                            "--child", kind), timeout_seconds=25, max_bytes=1024*1024)
    out = {"kind": kind, "url": URLS[kind], "status": "BLOCK",
           "worker_status": task.status, "elapsed_seconds": task.elapsed_seconds,
           "decision_authority": False}
    if task.status != "OK" or task.payload is None:
        return out
    try:
        p = task.payload
        if p.get("kind") != kind:
            raise ValueError("SZSE_RECEIPT_KIND")
        if p.get("error"):
            return out | {"error": p["error"], "http_status": p.get("http_status")}
        begin, end = datetime.fromisoformat(p["started_at"]), datetime.fromisoformat(p["retrieved_at"])
        if (p["url"] != URLS[kind] or begin.utcoffset() is None or end.utcoffset() is None
                or not begin <= end <= datetime.now(UTC)):
            raise ValueError("SZSE_RECEIPT_SCOPE")
        raw = base64.b64decode(p["body"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if not 0 < len(raw) <= MAX_BYTES or digest != p["sha256"]:
            raise ValueError("SZSE_RECEIPT_HASH")
        out |= {"sha256": digest, "bytes": len(raw), "retrieved_at": end.isoformat(),
                "parent_rehash": "MATCH", "raw_body_retained": False}
        fields = monthly_fields(raw, p["charset"]) if kind == "monthly" else page_fields(raw)
        return out | {"status": "OBSERVED", "fields": fields}
    except Exception as exc:  # noqa: BLE001
        code = str(exc)
        return out | {"error": code if re.fullmatch(r"SZSE_[A-Z_]+", code) else type(exc).__name__}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--child" or sys.argv[2] not in URLS:
        raise SystemExit(2)
    _child(sys.argv[2], Path(sys.argv[3]))
