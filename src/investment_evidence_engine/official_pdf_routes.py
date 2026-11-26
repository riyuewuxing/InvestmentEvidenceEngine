"""Narrow official document URL routing; no network, publication or admission claims."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_OFFICIAL_HOST = "static.cninfo.com.cn"
_DETAIL_HOST = "www.cninfo.com.cn"
_SZSE_HOST = "disc.static.szse.cn"
_SSE_HOST = "www.sse.com.cn"
_SZSE_PATH = re.compile(r"/disc/disk[0-9]{2}/finalpage/([0-9]{4}-[0-9]{2}-[0-9]{2})/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf", re.IGNORECASE)
_SSE_PATH = re.compile(r"/disclosure/fund/announcement/c/new/([0-9]{4}-[0-9]{2}-[0-9]{2})/[0-9]{6}_([0-9]{8})_[A-Za-z0-9]{1,32}\.pdf", re.IGNORECASE)
_PDF_PATH = re.compile(r"/finalpage/\d{4}-\d{2}-\d{2}/[0-9]+\.pdf", re.IGNORECASE)
_DETAIL_ALLOWED_KEYS = {"stockCode", "announcementId", "orgId", "announcementTime"}


def canonical_official_pdf_url(url: str) -> str:
    """Exact observed official static routes, not arbitrary URLs or issuer admission."""
    raw = str(url or "").strip()
    if any(ord(c) < 33 or ord(c) == 127 for c in raw) or "\\" in raw or "%" in raw:
        raise ValueError("Invalid official PDF URL")
    p = urlsplit(raw)
    if p.scheme not in {"http", "https"} or p.username is not None or p.password is not None or p.fragment:
        raise ValueError("Invalid official PDF URL")
    if p.hostname == _DETAIL_HOST and p.port in {None, 80, 443} and p.path == "/new/disclosure/detail":
        pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
        params: dict[str, str] = {}
        for k, v in pairs:
            if k not in _DETAIL_ALLOWED_KEYS or k in params:
                raise ValueError("Unsupported query parameter in official CNINFO detail URL")
            params[k] = v
        ann_id = params.get("announcementId", "")
        ann_date = params.get("announcementTime", "")
        stock_code = params.get("stockCode", "")
        org_id = params.get("orgId", "")
        if not re.fullmatch(r"[0-9]{1,24}", ann_id) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ann_date):
            raise ValueError("Missing or invalid CNINFO announcement identity")
        if stock_code and not re.fullmatch(r"[0-9]{6}", stock_code):
            raise ValueError("Invalid CNINFO stockCode")
        if org_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", org_id):
            raise ValueError("Invalid CNINFO orgId")
        date.fromisoformat(ann_date)
        return urlunsplit(("https", _OFFICIAL_HOST, f"/finalpage/{ann_date}/{ann_id}.PDF", "", ""))
    if p.hostname in {_SZSE_HOST, _SSE_HOST}:
        if p.scheme != "https" or p.port not in {None, 443} or p.query:
            raise ValueError("Invalid official exchange PDF URL")
        if p.hostname == _SZSE_HOST:
            match = _SZSE_PATH.fullmatch(p.path)
        else:
            match = _SSE_PATH.fullmatch(p.path)
        if not match:
            raise ValueError("Unsupported official exchange PDF path")
        published_day = date.fromisoformat(match.group(1))
        if p.hostname == _SSE_HOST and match.group(2) != published_day.strftime("%Y%m%d"):
            raise ValueError("Official exchange PDF dates disagree")
        return urlunsplit(("https", p.hostname, p.path, "", ""))
    if (p.hostname != _OFFICIAL_HOST
            or p.port not in {None, 443} or p.query
            or not _PDF_PATH.fullmatch(p.path)):
        raise ValueError("Only recognized official static disclosure PDF paths are allowed")
    # Reject malformed calendar dates even if the path shape matches.
    date.fromisoformat(p.path.split("/")[2])
    return urlunsplit(("https", _OFFICIAL_HOST, p.path, "", ""))


@dataclass(frozen=True)
class OfficialPdfRoute:
    url: str
    source_id: str
    root_host: str
    domain: str
    market_scope: str


def official_pdf_route(url: str) -> OfficialPdfRoute:
    canonical = canonical_official_pdf_url(url)
    host = urlsplit(canonical).hostname
    if host == _SSE_HOST:
        return OfficialPdfRoute(canonical, "cn_exchange_fund_official", "sse.com.cn",
                                "FUND_DISCLOSURE", "CN_ETF")
    if host == _SZSE_HOST:
        return OfficialPdfRoute(canonical, "official_exchange_public", "szse.cn",
                                "DISCLOSURE", "CN_A_STOCK")
    return OfficialPdfRoute(canonical, "official_exchange_public", "cninfo.com.cn",
                            "DISCLOSURE", "CN_A_STOCK")
