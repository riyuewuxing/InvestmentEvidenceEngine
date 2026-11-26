import pytest

from investment_evidence_engine.official_pdf_routes import (
    canonical_official_pdf_url,
    official_pdf_route,
)

SZSE = "https://disc.static.szse.cn/disc/disk03/finalpage/2026-11-24/01234567-89ab-cdef-0123-456789abcdef.PDF"
SSE = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-11-24/510050_20261124_TEST.pdf"


def test_exact_source_policy_mapping():
    r = official_pdf_route(SZSE)
    assert (r.url, r.source_id, r.root_host, r.domain, r.market_scope) == (
        SZSE, "official_exchange_public", "szse.cn", "DISCLOSURE", "CN_A_STOCK")
    r = official_pdf_route(SSE)
    assert (r.url, r.source_id, r.root_host, r.domain, r.market_scope) == (
        SSE, "cn_exchange_fund_official", "sse.com.cn", "FUND_DISCLOSURE", "CN_ETF")
    r = official_pdf_route("http://static.cninfo.com.cn/finalpage/2026-11-24/123.PDF")
    assert r.url.startswith("https://") and r.root_host == "cninfo.com.cn"
    assert canonical_official_pdf_url(
        "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600000&announcementId=123&announcementTime=2026-11-24"
    ) == "https://static.cninfo.com.cn/finalpage/2026-11-24/123.PDF"


@pytest.mark.parametrize("url", [
    SZSE.replace("https:", "http:"),
    SZSE.replace("disc.static.szse.cn", "disc.static.szse.cn.evil.example"),
    SZSE.replace("disc.static.szse.cn", "disc.static.szse.cn:8080"),
    SZSE.replace("2026-11-24", "2026-02-30"),
    SZSE.replace("01234567", "not-a-uuid"),
    SZSE+"?x=1",
    SZSE+"#fragment",
    SSE.replace("20261124", "20261125"),
    SSE.replace("www.sse.com.cn", "www.sse.com.cn@evil.example"),
    SSE.replace("TEST.pdf", "%54EST.pdf"),
    SSE.replace("2026-11-24", "../2026-11-24"),
    "https://fund.chinaamc.com/upload/resources/file/2026/11/24/0123456789abcdef0123456789abcdef.pdf",
    "https://127.0.0.1/file.pdf",
    "https://static.cninfo.com.cn/finalpage/2026-02-30/123.PDF",
])
def test_reject_unapproved_route_or_ambiguous_path(url):
    with pytest.raises(ValueError):
        official_pdf_route(url)
